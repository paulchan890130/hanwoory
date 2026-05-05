"""
하이코리아 매뉴얼 워치독 — 자동 다운로드 + 잠금해제 + PDF 변환

파이프라인:
  1. 하이코리아 NTCCTT_SEQ=1062 페이지 폴링
  2. 첨부파일 목록 파싱 (apnd_filename에 timestamp 포함)
  3. 캐시된 메타데이터(매뉴얼 ID → 마지막 본 timestamp)와 비교
  4. 변경 감지 시:
     a. 새 HWP 다운로드      → manuals/raw_<oriFileNm>
     b. 배포용 잠금 해제      → manuals/unlocked_<oriFileNm>
     c. PDF 변환             → manuals/unlocked_<oriFileNm>.pdf
     d. 메타데이터 캐시 갱신
     e. (선택) 게시판에 자동 공지 ("__manual_notice__" 카테고리)

캐시 파일:
  backend/data/manuals/.watcher_state.json
  {
    "manuals": {
      "체류민원": {
        "ori_filename": "...",
        "apnd_filename": "...[20260414182305670].hwp",
        "apnd_seq": "463",
        "timestamp": "20260414182305670",
        "downloaded_at": "2026-04-30T16:00:00",
        "raw_size": 3167744,
        "unlocked_path": "...",
        "pdf_path": "...",
        "pdf_size": 11645052
      },
      "사증민원": { ... }
    },
    "last_check": "2026-04-30T16:30:00"
  }
"""
from __future__ import annotations
import json, re, sys, urllib3, shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import requests

# repo root을 sys.path에 추가 (직접 실행 지원)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ROOT     = Path(__file__).parent.parent.parent
MANUALS  = ROOT / "backend" / "data" / "manuals"
STATE    = MANUALS / ".watcher_state.json"

HIKOREA_PAGE = "https://www.hikorea.go.kr/board/BoardNtcDetailR.pt?BBS_SEQ=1&BBS_GB_CD=BS10&NTCCTT_SEQ=1062&page=1"
DL_URL       = "https://www.hikorea.go.kr/fileNewExistsChkAjax.pt"
HEADERS      = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":    HIKOREA_PAGE,
}

# 우리가 추적할 매뉴얼 — 이름 키워드로 매핑
TRACKED_MANUALS = {
    "체류민원": ["체류민원 자격별 안내 매뉴얼"],
    "사증민원": ["사증민원 자격별 안내 매뉴얼"],
    "수정이력": ["사증.체류 민원 자격별 안내 매뉴얼 수정 이력"],
}


# ── 페이지 파싱 ─────────────────────────────────────────────────────────────
_FN_PATTERN = re.compile(
    r"fnNewFileDownLoad\(\s*"
    r"'(?P<spec>[^']*)'\s*,\s*'(?P<dir>[^']*)'\s*,\s*"
    r"'(?P<apnd>[^']*)'\s*,\s*'(?P<ori>[^']*)'\s*,\s*"
    r"'(?P<comcttSeq>[^']*)'\s*,\s*'(?P<bbsSeq>[^']*)'\s*,\s*'(?P<bbsGbCd>[^']*)'\s*,\s*"
    r"'(?P<apndSeq>[^']*)'\s*,\s*'(?P<bbsSkin>[^']*)'\s*\)"
)
_TS_RE = re.compile(r"\[(\d{17})\]\.hwp$")  # apnd 파일명에 포함된 17자리 timestamp


def fetch_attachment_list(session: requests.Session) -> list[dict]:
    """페이지를 가져와 첨부파일 메타데이터 목록 반환."""
    r = session.get(HIKOREA_PAGE, timeout=20)
    r.raise_for_status()
    items = []
    for m in _FN_PATTERN.finditer(r.text):
        d = m.groupdict()
        ts_match = _TS_RE.search(d["apnd"])
        d["timestamp"] = ts_match.group(1) if ts_match else None
        items.append(d)
    return items


def classify_attachment(ori_name: str) -> Optional[str]:
    """파일명을 보고 어떤 매뉴얼인지 분류. 추적 대상 아니면 None."""
    for label, keywords in TRACKED_MANUALS.items():
        if any(kw in ori_name for kw in keywords):
            return label
    return None


# ── 다운로드 ────────────────────────────────────────────────────────────────
def download_attachment(
    session: requests.Session, attachment: dict, save_to: Path
) -> Path:
    data = {
        "spec":       attachment["spec"],
        "dir":        attachment["dir"],
        "apndFileNm": attachment["apnd"],
        "oriFileNm":  attachment["ori"],
        "BBS_GB_CD":  attachment["bbsGbCd"],
        "BBS_SEQ":    attachment["bbsSeq"],
        "NTCCTT_SEQ": attachment["comcttSeq"],
        "APND_SEQ":   attachment["apndSeq"],
        "BBS_SKIN":   attachment["bbsSkin"],
    }
    r = session.post(DL_URL, data=data, timeout=120, allow_redirects=True)
    r.raise_for_status()
    if not r.content.startswith(b"\xd0\xcf\x11\xe0"):
        raise RuntimeError(f"OLE 파일 아님: 첫 8바이트 {r.content[:8].hex()}")
    save_to.parent.mkdir(parents=True, exist_ok=True)
    save_to.write_bytes(r.content)
    return save_to


# ── 상태 관리 ───────────────────────────────────────────────────────────────
def load_state() -> dict:
    if not STATE.exists():
        return {"manuals": {}, "last_check": None}
    return json.loads(STATE.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# ── 메인 처리 ───────────────────────────────────────────────────────────────
def check_and_update(
    *,
    convert_pdf: bool = True,
    notify_board: bool = True,   # 기본값 True — 새 버전 감지 시 1회만 자동 발송
    force_refresh: bool = False,
) -> dict:
    """
    한 번의 체크 사이클 실행.

    Args:
        convert_pdf: HWP→PDF 변환까지 수행할지 (한컴오피스 필요, 시간 소요)
        notify_board: 변경 감지 시 게시판 자동 공지 — last_notified_timestamp 비교로 1회만
        force_refresh: 캐시 무시하고 무조건 재다운로드

    Returns:
        {checked_at, changed: [...], errors: [...]}
    """
    from backend.services.hwp_unlock import unlock_hwp

    state = load_state()
    now_iso = datetime.now(timezone.utc).isoformat()

    s = requests.Session()
    s.headers.update(HEADERS); s.verify = False
    attachments = fetch_attachment_list(s)
    print(f"[watcher] attachments found: {len(attachments)}")

    changed: list[dict] = []
    errors: list[dict] = []

    for att in attachments:
        label = classify_attachment(att["ori"])
        if label is None:
            continue

        cached = state["manuals"].get(label, {})
        cached_ts = cached.get("timestamp")
        new_ts = att.get("timestamp")

        if not force_refresh and cached_ts == new_ts and cached_ts is not None:
            print(f"[watcher] {label}: unchanged (ts={cached_ts})")
            continue

        print(f"[watcher] {label}: {cached_ts} → {new_ts} (변경 감지)")
        try:
            # 1. 다운로드
            raw_path = MANUALS / f"raw_{att['ori']}"
            download_attachment(s, att, raw_path)
            print(f"  [DOWN] raw: {raw_path.stat().st_size:,} bytes")

            # 2. 잠금해제
            unlocked_path = MANUALS / f"unlocked_{label}.hwp"
            ur = unlock_hwp(raw_path, unlocked_path, overwrite=True, timeout_sec=180)
            print(f"  [UNLOCK] {ur['reason']}")

            # 3. PDF 변환 (옵션)
            pdf_path = None
            if convert_pdf:
                from backend.services.hwp_to_pdf import hwp_to_pdf
                pdf_path = MANUALS / f"unlocked_{label}.pdf"
                pr = hwp_to_pdf(unlocked_path, pdf_path, overwrite=True, timeout_sec=300)
                print(f"  [PDF] {pr['size_bytes']:,} bytes ({pr['elapsed_sec']}s)")

            # 4. 상태 갱신 — 기존 값(last_notified_timestamp 등) 보존
            existing = state["manuals"].get(label, {})
            state["manuals"][label] = {
                **existing,
                "ori_filename":   att["ori"],
                "apnd_filename":  att["apnd"],
                "apnd_seq":       att["apndSeq"],
                "timestamp":      new_ts,
                "downloaded_at":  now_iso,
                "raw_path":       str(raw_path),
                "raw_size":       raw_path.stat().st_size,
                "unlocked_path":  str(unlocked_path),
                "unlocked_size":  unlocked_path.stat().st_size,
                "pdf_path":       str(pdf_path) if pdf_path else None,
                "pdf_size":       pdf_path.stat().st_size if pdf_path else None,
            }
            changed.append({
                "label":   label,
                "old_ts":  cached_ts,
                "new_ts":  new_ts,
                "ori":     att["ori"],
            })

        except Exception as e:
            err = {"label": label, "error": f"{type(e).__name__}: {e}"}
            errors.append(err)
            print(f"  [X]{err['error']}")

    state["last_check"] = now_iso
    save_state(state)

    # 5. PDF 변환 후 rematch 자동 실행 (PDF 변환이 있었고 변경된 경우)
    rematch_summary: dict = {}
    if convert_pdf and changed:
        try:
            import subprocess, sys as _sys
            rematch_py = ROOT / "backend" / "scripts" / "manual_ref_rematch.py"
            if rematch_py.exists():
                print("[watcher] rematch 자동 실행...")
                r = subprocess.run(
                    [_sys.executable, str(rematch_py), "--report-only"],
                    capture_output=True, text=True, encoding="utf-8", timeout=300,
                )
                if r.returncode == 0:
                    review_path = MANUALS / "manual_update_review.json"
                    if review_path.exists():
                        rd = json.loads(review_path.read_text(encoding="utf-8"))
                        rc = rd.get("counts", {})
                        rematch_summary = {
                            "page_changed": rc.get("PAGE_CHANGED_AUTO", 0) + rc.get("PAGE_CHANGED_REVIEW", 0),
                            "not_found":    rc.get("NOT_FOUND", 0),
                        }
                        print(
                            f"  [REMATCH] PAGE_CHANGED={rematch_summary['page_changed']}"
                            f" NOT_FOUND={rematch_summary['not_found']}"
                        )
                else:
                    print(f"  [REMATCH] 실패: {r.stderr[:200]}")
        except Exception as e:
            print(f"  [REMATCH] 예외: {e}")

    # 6. 게시판 공지 — last_notified_timestamp 기준 1회만 발송
    if notify_board and changed:
        to_notify = []
        for c in changed:
            label = c["label"]
            new_ts = c["new_ts"]
            last_notified = state["manuals"].get(label, {}).get("last_notified_timestamp")
            if last_notified != new_ts:
                to_notify.append(c)
            else:
                print(f"[watcher] {label}: 알림 이미 발송됨 (ts={new_ts}), 건너뜀")
        if to_notify:
            try:
                _post_board_notice(to_notify, rematch_summary=rematch_summary)
                # 발송 완료 기록 — 즉시 파일에 저장
                for c in to_notify:
                    state["manuals"].setdefault(c["label"], {})["last_notified_timestamp"] = c["new_ts"]
                save_state(state)
                print(f"[watcher] 게시판 공지 발송 + last_notified_timestamp 저장: {[c['label'] for c in to_notify]}")
            except Exception as e:
                errors.append({"step": "board_notice", "error": str(e)})

    return {"checked_at": now_iso, "changed": changed, "errors": errors, "rematch": rematch_summary}


def _post_board_notice(changed: list[dict], rematch_summary: dict | None = None) -> None:
    """변경된 매뉴얼을 게시판에 자동 공지."""
    from core.google_sheets import upsert_rows_by_id
    from config import SHEET_KEY
    import uuid
    rows = []
    for c in changed:
        rows.append({
            "id":           str(uuid.uuid4()),
            "tenant_id":    "_system",
            "author_login": "_watcher",
            "office_name":  "출입국 매뉴얼 워치독",
            "is_notice":    "Y",
            "category":     "__manual_notice__",
            "title":        f"[자동] {c['label']} 매뉴얼 갱신 ({c['new_ts'][:8]})",
            "content":      (
                f"하이코리아에서 새 버전이 감지되어 자동 처리되었습니다.\n\n"
                f"- 파일명: {c['ori']}\n"
                f"- 이전 timestamp: {c['old_ts']}\n"
                f"- 신규 timestamp: {c['new_ts']}\n\n"
                f"잠금 해제된 PDF는 시스템에 자동 반영되었습니다."
                + (
                    f"\n\n📋 페이지 변경 감지 결과\n"
                    f"- 페이지 변경: {rematch_summary.get('page_changed', 0)}건\n"
                    f"- 재확인 필요: {rematch_summary.get('not_found', 0)}건\n\n"
                    f"관리자 페이지 > 매뉴얼 업데이트 검토에서 확인하세요."
                    if rematch_summary else ""
                )
            ),
            "created_at":   datetime.now(timezone.utc).isoformat(),
            "updated_at":   datetime.now(timezone.utc).isoformat(),
            "popup_yn":     "Y",
            "link_url":     HIKOREA_PAGE,
        })
    POST_HEADER = ["id","tenant_id","author_login","office_name","is_notice",
                   "category","title","content","created_at","updated_at",
                   "popup_yn","link_url"]
    upsert_rows_by_id("게시판", POST_HEADER, rows, "id")


# ── CLI ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="하이코리아 매뉴얼 워치독")
    p.add_argument("--no-pdf", action="store_true", help="PDF 변환 건너뛰기")
    p.add_argument("--notify", action="store_true", help="변경 시 게시판 자동 공지")
    p.add_argument("--force",  action="store_true", help="캐시 무시 재다운로드")
    args = p.parse_args()
    try:
        result = check_and_update(
            convert_pdf=not args.no_pdf,
            notify_board=args.notify,
            force_refresh=args.force,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
