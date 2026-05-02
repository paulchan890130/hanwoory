"""
HWP 5.x 배포용 문서 잠금 해제 서비스 (v4 — subprocess wrapper)

배포용 문서의 실제 보호 메커니즘:
  - FileHeader bit 2 = 1
  - BodyText/Section* = 빈 stub
  - ViewText/Section* = LEA-128 암호화 본문 + HWPTAG_DISTRIBUTE_DOC_DATA(0x1C) 키 record
  - ViewText 첫 4+256바이트가 키 record, 이후가 암호화된 섹션 데이터

따라서 정식 잠금해제는 LEA 복호화가 필요하므로,
이미 검증된 .NET 도구 OpenHwpExe.exe 의 Main.ConvertFile() 을 호출.

호출 방식: 매번 별도 Python 서브프로세스로 분리 (CLR Form 인스턴스 재사용 시
async Task.Wait 데드락 위험 회피).
"""
from __future__ import annotations
import sys, shutil, subprocess, json, os
from pathlib import Path
from typing import Optional, TypedDict
import olefile

ROOT          = Path(__file__).parent.parent.parent
_TOOL_DIR     = ROOT / "analysis" / "클로드" / "배포용 한글문서 변환기"
_OPEN_HWP_EXE = _TOOL_DIR / "OpenHwpExe.exe"

_HWP_SIGNATURE    = b"HWP Document File"
_BIT_PASSWORD     = 1 << 1
_BIT_DISTRIBUTION = 1 << 2
_BIT_DRM          = 1 << 4


def _decode_flags(flags: int) -> dict:
    return {
        "compressed":   bool(flags & 1),
        "password":     bool(flags & _BIT_PASSWORD),
        "distribution": bool(flags & _BIT_DISTRIBUTION),
        "script":       bool(flags & (1 << 3)),
        "drm":          bool(flags & _BIT_DRM),
        "raw":          f"0x{flags:08X}",
    }


def inspect_hwp(src: str | Path) -> dict:
    """HWP 파일 진단 — 파일 수정 없음."""
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(f"HWP 파일 없음: {src}")
    if not olefile.isOleFile(str(src)):
        raise ValueError(f"OLE 파일 아님: {src}")

    ole = olefile.OleFileIO(str(src))
    try:
        if not ole.exists("FileHeader"):
            raise ValueError("FileHeader 스트림 없음")
        fh = ole.openstream("FileHeader").read()

        body, view = [], []
        for entry in ole.listdir(streams=True):
            full = "/".join(entry)
            sz = ole.get_size(entry)
            if full.startswith("BodyText/Section"):
                body.append((full, sz))
            elif full.startswith("ViewText/Section"):
                view.append((full, sz))
    finally:
        ole.close()

    if not fh.startswith(_HWP_SIGNATURE):
        raise ValueError("HWP 시그니처 불일치")

    flags = int.from_bytes(fh[36:40], "little")
    return {
        "path": str(src),
        "size": src.stat().st_size,
        "version": ".".join(str(b) for b in [fh[35], fh[34], fh[33], fh[32]]),
        "flags": _decode_flags(flags),
        "body_text_sections": [{"name": n, "size": s} for n, s in body],
        "view_text_sections": [{"name": n, "size": s} for n, s in view],
        "body_total": sum(s for _, s in body),
        "view_total": sum(s for _, s in view),
    }


class UnlockResult(TypedDict):
    unlocked: bool
    reason: str
    src: str
    dst: Optional[str]
    old_flags: Optional[int]
    new_flags: Optional[int]


# ── _convert_worker: 별도 프로세스에서 실행되는 .NET 호출 부분 ──────────────
_WORKER_CODE = r'''
import sys, os, time, clr, System
clr.AddReference("System.Windows.Forms")
from System.Windows.Forms import Application
clr.AddReference(os.path.join(os.environ["HWP_TOOL_DIR"], "OpenMcdf.dll"))
clr.AddReference(os.path.join(os.environ["HWP_TOOL_DIR"], "HwpSharp.dll"))
asm = System.Reflection.Assembly.LoadFrom(
    os.path.join(os.environ["HWP_TOOL_DIR"], "OpenHwpExe.exe")
)
from System.Reflection import BindingFlags
bf = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance
main_t = asm.GetType("OpenHwpExe.Main")

# WinForms 컨텍스트 활성화 (SynchronizationContext 등록)
Application.EnableVisualStyles()
form = System.Activator.CreateInstance(main_t)
main_t.GetField("radSavePathPrefix", bf).GetValue(form).Checked = True
main_t.GetField("txtSavePathPrefix", bf).GetValue(form).Text = sys.argv[2]

src = sys.argv[1]
safe_name = os.path.basename(src)
method = main_t.GetMethod("ConvertFile", bf)
task = method.Invoke(form, [src, safe_name])

# DoEvents 폴링으로 async 메시지 펌프 (Application.Run 없이도 await 동작)
deadline = time.time() + int(sys.argv[3])
while not task.IsCompleted and time.time() < deadline:
    Application.DoEvents()
    time.sleep(0.02)

if not task.IsCompleted:
    print("TIMEOUT", file=sys.stderr); sys.exit(2)
if task.IsFaulted:
    print(f"FAULTED: {task.Exception}", file=sys.stderr); sys.exit(3)

log = main_t.GetField("txtLog", bf).GetValue(form).Text
print("LOG:", log)
print("OK")
'''


def unlock_hwp(
    src: str | Path,
    dst: Optional[str | Path] = None,
    *,
    overwrite: bool = False,
    timeout_sec: int = 180,
) -> UnlockResult:
    """
    배포용 HWP 잠금 해제 (subprocess wrapper).

    OpenHwpExe.exe 의 ConvertFile 을 별도 Python 프로세스에서 호출.
    """
    src = Path(src).resolve()
    if not src.exists():
        raise FileNotFoundError(f"HWP 파일 없음: {src}")
    if not olefile.isOleFile(str(src)):
        raise ValueError(f"OLE 파일 아님: {src}")
    if not _OPEN_HWP_EXE.exists():
        raise RuntimeError(f"OpenHwpExe.exe 없음: {_OPEN_HWP_EXE}")

    info = inspect_hwp(src)
    flags = int(info["flags"]["raw"], 16)
    bits = info["flags"]

    if bits["password"]:
        return UnlockResult(unlocked=False, reason="암호 보호 — 해제 불가",
                            src=str(src), dst=None,
                            old_flags=flags, new_flags=None)
    if bits["drm"]:
        return UnlockResult(unlocked=False, reason="DRM 보호 — 해제 불가",
                            src=str(src), dst=None,
                            old_flags=flags, new_flags=None)
    if not bits["distribution"]:
        if dst is None:
            dst = src.with_name("unlocked_" + src.name)
        else:
            dst = Path(dst)
        if dst.exists() and not overwrite:
            raise FileExistsError(f"출력 파일 이미 존재: {dst}")
        shutil.copy2(src, dst)
        return UnlockResult(unlocked=False, reason="이미 일반 문서",
                            src=str(src), dst=str(dst),
                            old_flags=flags, new_flags=flags)

    # ── subprocess로 ConvertFile 호출 ────────────────────────────────────
    prefix = "unlocked_"
    auto_dst = src.with_name(prefix + src.name)
    if auto_dst.exists():
        if not overwrite:
            raise FileExistsError(f"중간 출력 파일 존재: {auto_dst}")
        auto_dst.unlink()

    env = os.environ.copy()
    env["HWP_TOOL_DIR"] = str(_TOOL_DIR)

    proc = subprocess.run(
        [sys.executable, "-c", _WORKER_CODE, str(src), prefix, str(timeout_sec)],
        env=env, capture_output=True, timeout=timeout_sec + 30,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ConvertFile 실패 (rc={proc.returncode})\n"
            f"stdout: {proc.stdout.decode('utf-8','replace')}\n"
            f"stderr: {proc.stderr.decode('utf-8','replace')}"
        )

    if not auto_dst.exists():
        raise RuntimeError(
            f"변환 결과 파일 없음: {auto_dst}\n"
            f"stdout: {proc.stdout.decode('utf-8','replace')}\n"
            f"stderr: {proc.stderr.decode('utf-8','replace')}"
        )

    # dst 지정된 경우 이동
    if dst is not None:
        dst = Path(dst).resolve()
        if dst != auto_dst:
            if dst.exists():
                if not overwrite:
                    auto_dst.unlink()
                    raise FileExistsError(f"출력 파일 이미 존재: {dst}")
                dst.unlink()
            shutil.move(str(auto_dst), str(dst))
            final_dst = dst
        else:
            final_dst = auto_dst
    else:
        final_dst = auto_dst

    info_after = inspect_hwp(final_dst)
    new_flags = int(info_after["flags"]["raw"], 16)
    if info_after["flags"]["distribution"]:
        raise RuntimeError(
            f"잠금해제 실패 — 결과 파일에 distribution 비트 ON ({info_after['flags']['raw']})"
        )

    return UnlockResult(
        unlocked=True,
        reason=f"배포용 잠금 해제 완료 ({info_after['body_total']:,} bytes 본문 복원)",
        src=str(src), dst=str(final_dst),
        old_flags=flags, new_flags=new_flags,
    )


# ── CLI ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="HWP 5.x 배포용 잠금 해제")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_inspect = sub.add_parser("inspect")
    p_inspect.add_argument("path")

    p_unlock = sub.add_parser("unlock")
    p_unlock.add_argument("src")
    p_unlock.add_argument("-o", "--output", default=None)
    p_unlock.add_argument("--overwrite", action="store_true")
    p_unlock.add_argument("--timeout", type=int, default=180)

    args = p.parse_args()
    try:
        if args.cmd == "inspect":
            print(json.dumps(inspect_hwp(args.path), indent=2, ensure_ascii=False))
        else:
            result = unlock_hwp(args.src, args.output,
                                overwrite=args.overwrite,
                                timeout_sec=args.timeout)
            print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
