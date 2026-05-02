"""
Phase A PoC — 하이코리아에서 HWP 다운로드 → 잠금해제 → 검증

전체 파이프라인을 한 번에 검증:
  1. 하이코리아 페이지 접근
  2. 체류민원 자격별 안내 매뉴얼 HWP 다운로드
  3. inspect_hwp 로 배포용 비트 확인
  4. unlock_hwp 로 잠금해제
  5. 다시 inspect 로 비트 OFF 확인
"""
import sys, io, urllib3, json
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import requests
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from backend.services.hwp_unlock import inspect_hwp, unlock_hwp

ROOT     = Path(__file__).parent.parent.parent
MANUALS  = ROOT / "backend" / "data" / "manuals"
MANUALS.mkdir(parents=True, exist_ok=True)

HIKOREA_PAGE = "https://www.hikorea.go.kr/board/BoardNtcDetailR.pt?BBS_SEQ=1&BBS_GB_CD=BS10&NTCCTT_SEQ=1062&page=1"
DL_URL       = "https://www.hikorea.go.kr/fileNewExistsChkAjax.pt"
HEADERS      = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    HIKOREA_PAGE,
}

# 다운로드할 파일들 — APND_SEQ는 페이지에서 동적으로 갱신됨
TARGETS = [
    {
        "label":      "체류민원 매뉴얼",
        "apnd":       "260414 체류민원 자격별 안내 매뉴얼[20260414182305670].hwp",
        "ori":        "260414 체류민원 자격별 안내 매뉴얼.hwp",
        "apnd_seq":   "463",
    },
    {
        "label":      "사증민원 매뉴얼",
        "apnd":       "260414 사증민원 자격별 안내 매뉴얼[20260414182305646].hwp",
        "ori":        "260414 사증민원 자격별 안내 매뉴얼.hwp",
        "apnd_seq":   "462",
    },
]


def download_hwp(session, target: dict, save_to: Path) -> Path:
    data = {
        "spec":       "pt",
        "dir":        "ntc",
        "apndFileNm": target["apnd"],
        "oriFileNm":  target["ori"],
        "BBS_GB_CD":  "BS10",
        "BBS_SEQ":    "1",
        "NTCCTT_SEQ": "1062",
        "APND_SEQ":   target["apnd_seq"],
        "BBS_SKIN":   "NORMAL",
    }
    r = session.post(DL_URL, data=data, timeout=60, allow_redirects=True)
    r.raise_for_status()
    if not r.content.startswith(b"\xd0\xcf\x11\xe0"):
        raise RuntimeError(f"다운로드 응답이 OLE 파일 아님 (첫 바이트: {r.content[:8].hex()})")
    save_to.write_bytes(r.content)
    return save_to


def main():
    print("=" * 70)
    print("Phase A PoC — HWP 다운로드 + 잠금해제 + 검증")
    print("=" * 70)

    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = False

    # 페이지 한 번 방문 (세션 쿠키)
    print("\n[1] 하이코리아 페이지 방문 (세션 쿠키 획득)")
    r = s.get(HIKOREA_PAGE, timeout=20)
    print(f"    status={r.status_code}, len={len(r.text)}")

    for tgt in TARGETS:
        print("\n" + "=" * 70)
        print(f"  대상: {tgt['label']}")
        print("=" * 70)

        # 다운로드
        raw_path = MANUALS / f"raw_{tgt['ori']}"
        print(f"[2] 다운로드 → {raw_path.name}")
        try:
            download_hwp(s, tgt, raw_path)
            print(f"    OK ({raw_path.stat().st_size:,} bytes)")
        except Exception as e:
            print(f"    [FAIL] {e}")
            continue

        # Inspect 원본
        print(f"[3] inspect 원본")
        try:
            info = inspect_hwp(raw_path)
            print(f"    버전: {info['version']} ({info['version_dword']})")
            print(f"    flags: {json.dumps(info['flags'], ensure_ascii=False)}")
            is_dist_before = info["flags"]["distribution"]
        except Exception as e:
            print(f"    [FAIL] {e}")
            continue

        # Unlock
        unlocked_path = MANUALS / f"unlocked_{tgt['ori']}"
        print(f"[4] unlock → {unlocked_path.name}")
        try:
            result = unlock_hwp(raw_path, unlocked_path, overwrite=True)
            print(f"    unlocked={result['unlocked']}  reason={result['reason']}")
            if result.get("old_flags") is not None:
                print(f"    old_flags={result['old_flags']:#010x} → new_flags={result['new_flags']:#010x}")
        except Exception as e:
            print(f"    [FAIL] {e}")
            continue

        # Inspect 결과 검증
        print(f"[5] inspect 잠금해제본 — 검증")
        try:
            info2 = inspect_hwp(unlocked_path)
            print(f"    flags: {json.dumps(info2['flags'], ensure_ascii=False)}")
            is_dist_after = info2["flags"]["distribution"]
            if is_dist_before and not is_dist_after:
                print(f"    [PASS] 배포용 비트 ON → OFF")
            elif not is_dist_before:
                print(f"    [SKIP] 원본이 이미 일반 문서")
            else:
                print(f"    [FAIL] 비트가 여전히 ON")
        except Exception as e:
            print(f"    [FAIL] {e}")

    print("\n" + "=" * 70)
    print("저장 위치:", MANUALS)
    print("=" * 70)


if __name__ == "__main__":
    main()
