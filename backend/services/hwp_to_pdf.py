"""
HWP → PDF 변환 서비스 (+ 모아찍기 자동 분할)

한컴오피스 COM 자동화(HWPFrame.HwpObject) 사용.
배포용 잠금이 풀린 HWP 파일을 PDF로 변환.

한컴 COM API 핵심:
  - Open(path, format, arg)        — 파일 열기
  - SaveAs(path, format, arg)      — 다른 형식 저장 (format="PDF")
  - RegisterModule("FilePathCheckDLL", "AutomationModule")
                                    — 보안 모듈 등록 (대화상자 우회)
  - Quit()                         — 정리

자동화 보안 정책:
  한컴은 자동화 호출 시 "이 문서를 자동으로 처리하시겠습니까?" 대화상자를 띄움.
  이를 우회하려면 보안 레지스트리 등록 필요.
  최초 1회만 사용자가 한컴에서 도구>환경설정>보안>"낮음" 설정 또는
  AutomationModule을 등록.

호출 방식:
  - subprocess 분리 실행 (한컴 COM 안정성 확보)
  - 같은 worker 패턴으로 hwp_unlock.py와 일관성 유지
"""
from __future__ import annotations
import sys, os, subprocess, json
from pathlib import Path
from typing import Optional


_WORKER_CODE = r'''
import sys, os
import win32com.client

src = sys.argv[1]
dst = sys.argv[2]

hwp = win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")
try:
    # 보안 대화상자 우회
    hwp.RegisterModule("FilePathCheckDLL", "AutomationModule")

    # 파일 열기 (배포용 해제된 파일이어야 함)
    if not hwp.Open(src, "HWP", "forceopen:true;suspendpassword:true"):
        print(f"OPEN_FAILED: {src}", file=sys.stderr); sys.exit(2)

    # 인쇄 설정 강제 1페이지/장 (HWP 내부 PrintSetup이 2-up일 수 있음)
    try:
        pset_print = hwp.HParameterSet.HPrintSetup
        hwp.HAction.GetDefault("FilePrintSetup", pset_print.HSet)
        # PagesPerSheet: 0=1page, 1=2pages, 2=4pages, ...
        pset_print.PagesPerSheet = 0
        # PrintMethod: 0=normal, 1=poster ... — 1페이지/장이 보장되도록 normal
        pset_print.PrintMethod = 0
        hwp.HAction.Execute("FilePrintSetup", pset_print.HSet)
    except Exception as e:
        print(f"WARN: PrintSetup adjust failed: {e}", file=sys.stderr)

    # FileSaveAsPdf 액션으로 PDF 저장 (SaveAs 보다 옵션 제어 정확)
    saved = False
    try:
        pset = hwp.HParameterSet.HFileOpenSave
        hwp.HAction.GetDefault("FileSaveAsPdf", pset.HSet)
        pset.filename = dst
        pset.Format = "PDF"
        pset.Attributes = 0
        saved = bool(hwp.HAction.Execute("FileSaveAsPdf", pset.HSet))
    except Exception as e:
        print(f"WARN: FileSaveAsPdf failed: {e} — fallback to SaveAs", file=sys.stderr)

    # fallback: 구식 SaveAs
    if not saved:
        if not hwp.SaveAs(dst, "PDF", ""):
            print(f"SAVE_FAILED: {dst}", file=sys.stderr); sys.exit(3)

    if not os.path.exists(dst):
        print(f"NO_OUTPUT: {dst}", file=sys.stderr); sys.exit(4)

    print(f"OK size={os.path.getsize(dst)}")
finally:
    try:
        hwp.Clear(option=1)
    except: pass
    try:
        hwp.Quit()
    except: pass
'''


def split_2up_landscape(pdf_path: str | Path, *, in_place: bool = True) -> dict:
    """
    가로 A4(841×595)에 두 페이지가 좌/우로 모아찍기된 PDF를 1-up 세로로 분할.

    각 landscape 페이지를 width/2 기준으로 좌·우 두 페이지로 쪼개서
    원본 페이지 수의 2배가 되는 새 PDF를 생성. portrait 페이지는 그대로 유지.

    Returns:
        {ok, src, dst, original_pages, output_pages, split_pages}
    """
    import fitz
    pdf_path = Path(pdf_path).resolve()
    src = fitz.open(pdf_path)
    new = fitz.open()
    split_count = 0

    for page in src:
        rect = page.rect
        # landscape이고 비율이 ~ √2 인 경우만 2-up으로 간주 (단순 가로 페이지 보호)
        is_landscape_2up = (
            rect.width > rect.height
            and 1.3 < rect.width / rect.height < 1.5  # A4 가로/세로 ≈ 1.414
        )
        if is_landscape_2up:
            half_w = rect.width / 2
            # 왼쪽
            left = new.new_page(width=half_w, height=rect.height)
            left.show_pdf_page(left.rect, src, page.number,
                               clip=fitz.Rect(0, 0, half_w, rect.height))
            # 오른쪽
            right = new.new_page(width=half_w, height=rect.height)
            right.show_pdf_page(right.rect, src, page.number,
                                clip=fitz.Rect(half_w, 0, rect.width, rect.height))
            split_count += 1
        else:
            new.new_page(width=rect.width, height=rect.height).show_pdf_page(
                fitz.Rect(0, 0, rect.width, rect.height), src, page.number)

    output_pages = len(new)
    original_pages = len(src)
    src.close()

    if in_place:
        tmp = pdf_path.with_suffix(".tmp.pdf")
        new.save(tmp)
        new.close()
        pdf_path.unlink()
        tmp.rename(pdf_path)
        dst = pdf_path
    else:
        dst = pdf_path.with_name(pdf_path.stem + "_split.pdf")
        new.save(dst)
        new.close()

    return {
        "ok": True,
        "src": str(pdf_path),
        "dst": str(dst),
        "original_pages": original_pages,
        "output_pages": output_pages,
        "split_pages": split_count,
    }


def hwp_to_pdf(
    src: str | Path,
    dst: Optional[str | Path] = None,
    *,
    overwrite: bool = False,
    timeout_sec: int = 300,
    auto_split_2up: bool = True,
) -> dict:
    """
    HWP 파일을 PDF로 변환.

    Args:
        src: 입력 .hwp 경로 (배포용 잠금 해제된 상태여야 함)
        dst: 출력 .pdf 경로 (None이면 .hwp → .pdf)
        overwrite: dst 존재 시 덮어쓰기
        timeout_sec: 변환 최대 대기 시간

    Returns:
        {ok, src, dst, size_bytes, elapsed_sec}
    """
    src = Path(src).resolve()
    if not src.exists():
        raise FileNotFoundError(f"HWP 파일 없음: {src}")
    if src.suffix.lower() != ".hwp":
        raise ValueError(f"확장자가 .hwp 아님: {src}")

    if dst is None:
        dst = src.with_suffix(".pdf")
    else:
        dst = Path(dst).resolve()
    if dst.exists():
        if not overwrite:
            raise FileExistsError(f"출력 파일 이미 존재: {dst}")
        dst.unlink()

    import time
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, "-c", _WORKER_CODE, str(src), str(dst)],
        capture_output=True, timeout=timeout_sec,
    )
    elapsed = time.time() - t0

    if proc.returncode != 0:
        raise RuntimeError(
            f"HWP→PDF 변환 실패 (rc={proc.returncode})\n"
            f"stdout: {proc.stdout.decode('utf-8','replace')}\n"
            f"stderr: {proc.stderr.decode('utf-8','replace')}"
        )
    if not dst.exists():
        raise RuntimeError(f"변환 후 PDF 파일 없음: {dst}")

    split_info = None
    if auto_split_2up:
        split_info = split_2up_landscape(dst, in_place=True)

    return {
        "ok": True,
        "src": str(src),
        "dst": str(dst),
        "size_bytes": dst.stat().st_size,
        "elapsed_sec": round(elapsed, 2),
        "split": split_info,
    }


# ── CLI ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="HWP → PDF 변환 (한컴 COM)")
    p.add_argument("src")
    p.add_argument("-o", "--output", default=None)
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--timeout", type=int, default=300)
    args = p.parse_args()
    try:
        r = hwp_to_pdf(args.src, args.output, overwrite=args.overwrite, timeout_sec=args.timeout)
        print(json.dumps(r, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
