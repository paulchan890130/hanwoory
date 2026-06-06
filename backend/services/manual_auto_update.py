"""manual_auto_update — rhwp 기반 매뉴얼 자동 staging (레거시 Hancom watcher 와 완전 분리).

목적
----
매일 15:00 KST 에 하이코리아 매뉴얼 첨부 변경을 감지하고, 변경이 있으면 원본 HWP/HWPX 를
``MANUALS_DATA_DIR/incoming/{version}/`` 에 받아 rhwp 파이프라인(extract+diff+candidates+
manifest)으로 **검토용 staging** 만 생성한다.

엄격한 비목표 (자동으로 하지 않는 것)
------------------------------------
* immigration_guidelines_db_v2.json 수정 금지 / 운영 manual_ref 자동 반영 금지.
* /apply 자동 실행·후보 자동 승인 금지.
* unlock_hwp / hwp_to_pdf / OpenHwpExe / Hancom COM 호출 금지 (import 조차 안 함).
* chromium / 검토 PDF 자동 생성 금지 (manual_update_local 을 --no-changed-pages-pdf 로 실행).
* 운영 unlocked_*.pdf 덮어쓰기 금지 (이 모듈은 incoming/staging 에만 쓴다).

활성화
------
``FEATURE_MANUAL_AUTO_UPDATE=true`` 일 때만 스케줄러에 등록된다(main.py). 기본값 OFF.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# repo root 을 sys.path 에 (python -m / 직접 실행 지원)
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

KST = timezone(timedelta(hours=9))  # 한국 표준시 (DST 없음 — 고정 오프셋)
_RUN_HISTORY_MAX = 10
_LOCK_STALE_SEC = 2 * 60 * 60  # 2h — 죽은 락 자동 회수
_STAGE_TIMEOUT_SEC = 30 * 60   # rhwp staging subprocess 타임아웃

# 추적 대상 — manual_watcher 의 라벨 키워드를 재사용(감지/다운로드 순수 함수만 사용)
_TRACKED = ("체류민원", "사증민원", "수정이력")


# ── 경로 ────────────────────────────────────────────────────────────────────
def _manuals_dir() -> Path:
    try:
        from config import MANUALS_DATA_DIR
        return Path(MANUALS_DATA_DIR)
    except Exception:
        env = os.environ.get("MANUALS_DATA_DIR")
        return Path(env) if env else (ROOT / "backend" / "data" / "manuals")


def _state_path() -> Path:
    return _manuals_dir() / "manual_auto_update_state.json"


def _lock_path() -> Path:
    return _manuals_dir() / ".manual_auto_update.lock"


def _incoming_dir(version: str) -> Path:
    return _manuals_dir() / "incoming" / version


def _staging_dir(version: str) -> Path:
    return _manuals_dir() / "staging" / version


# ── 시간 ────────────────────────────────────────────────────────────────────
def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _kst_today() -> str:
    return datetime.now(timezone.utc).astimezone(KST).strftime("%Y-%m-%d")


# ── 상태 파일 ─────────────────────────────────────────────────────────────────
def _default_state() -> dict:
    return {
        "status": "never_run",     # never_run|running|no_change|staged|error
        "last_run_at": None,
        "last_success_at": None,
        "last_run_date_kst": None,
        "last_checked_version": None,
        "last_detected_version": None,
        "last_staging_version": None,
        "needs_review": False,
        "error": None,
        "seen_timestamps": {},     # {label: hikorea timestamp} — 변경 감지 기준
        "run_history": [],
    }


def load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return _default_state()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        base = _default_state()
        base.update(data if isinstance(data, dict) else {})
        return base
    except Exception:
        return _default_state()


def save_state(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _push_history(state: dict, entry: dict) -> None:
    hist = state.get("run_history") or []
    hist.append(entry)
    state["run_history"] = hist[-_RUN_HISTORY_MAX:]


# ── 파일 락 (중복 실행 방지) ──────────────────────────────────────────────────
def _acquire_lock() -> bool:
    lock = _lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, f"{os.getpid()} {_utc_now_iso()}".encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except FileExistsError:
        # 죽은 락 회수: mtime 이 너무 오래됐으면 제거 후 재시도
        try:
            age = time.time() - lock.stat().st_mtime
            if age > _LOCK_STALE_SEC:
                lock.unlink()
                return _acquire_lock()
        except Exception:
            pass
        return False


def _release_lock() -> None:
    try:
        _lock_path().unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


# ── 감지 (읽기 전용 — 다운로드/스테이징 없음) ─────────────────────────────────
def _seed_seen_from_legacy(state: dict) -> None:
    """첫 실행 시 레거시 .watcher_state.json 의 timestamp 로 seen 을 시드한다.
    이미 레거시가 추적하던 버전을 '변경'으로 오인해 불필요하게 받지 않도록."""
    if state.get("seen_timestamps"):
        return
    legacy = _manuals_dir() / ".watcher_state.json"
    if not legacy.exists():
        return
    try:
        data = json.loads(legacy.read_text(encoding="utf-8"))
        seen = {}
        for label, meta in (data.get("manuals") or {}).items():
            ts = (meta or {}).get("timestamp")
            if ts:
                seen[label] = ts
        if seen:
            state["seen_timestamps"] = seen
    except Exception:
        pass


def detect_changes(state: dict | None = None) -> list[dict]:
    """하이코리아 첨부 목록을 받아 seen_timestamps 대비 변경된 항목만 반환.

    네트워크 읽기만 수행. 다운로드/스테이징/상태저장 없음 (dry-run 안전).
    반환: [{label, old_ts, new_ts, att}] (att 는 다운로드용 메타)."""
    import requests
    # 레거시 watcher 의 '순수' 함수만 재사용 — unlock/COM 은 import 하지 않는다.
    from backend.services.manual_watcher import (
        fetch_attachment_list, classify_attachment, HEADERS,
    )
    if state is None:
        state = load_state()
        _seed_seen_from_legacy(state)
    seen = state.get("seen_timestamps") or {}

    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = False
    attachments = fetch_attachment_list(s)

    changed: list[dict] = []
    for att in attachments:
        label = classify_attachment(att.get("ori", ""))
        if label is None or label not in _TRACKED:
            continue
        new_ts = att.get("timestamp")
        if not new_ts:
            continue
        old_ts = seen.get(label)
        if old_ts == new_ts:
            continue
        changed.append({"label": label, "old_ts": old_ts, "new_ts": new_ts, "att": att})
    return changed


def _version_from_changes(changed: list[dict]) -> str:
    """변경 항목들의 최신 timestamp(17자리 YYYYMMDDHHMMSSmmm)에서 YYMMDD 버전 산출.
    baseline 컨벤션(예: 260414)과 동일한 형식."""
    newest = max((c["new_ts"] for c in changed if c.get("new_ts")), default=None)
    if newest and len(newest) >= 8:
        return newest[2:8]
    # fallback — KST 오늘 날짜
    return datetime.now(timezone.utc).astimezone(KST).strftime("%y%m%d")


# ── 다운로드 ─────────────────────────────────────────────────────────────────
def _download_changed(changed: list[dict], version: str) -> list[Path]:
    """변경된 원본 HWP/HWPX 를 incoming/{version}/ 에 원본 파일명으로 저장.
    unlock/PDF 변환은 하지 않는다. 운영 unlocked_*.pdf 는 절대 건드리지 않는다."""
    import requests
    from backend.services.manual_watcher import download_attachment, HEADERS
    inc = _incoming_dir(version)
    inc.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = False
    saved: list[Path] = []
    for c in changed:
        att = c["att"]
        ori = att.get("ori") or f"{c['label']}.hwp"
        dst = inc / ori
        download_attachment(s, att, dst)
        saved.append(dst)
    return saved


# ── rhwp staging (chromium 없이 extract+diff+candidates+manifest) ─────────────
def _run_staging(version: str) -> dict:
    """manual_update_local.py 를 subprocess 로 호출해 staging 생성.
    --no-changed-pages-pdf → 검토 PDF/chromium 미사용. 운영 JSON 미수정.
    decision 병합(Phase 0)은 manual_update_local 내부 로직이 자동 적용한다."""
    script = ROOT / "backend" / "scripts" / "manual_update_local.py"
    inc = _incoming_dir(version)
    cmd = [
        sys.executable, str(script),
        "--version", version,
        "--input-dir", str(inc),
        "--no-changed-pages-pdf",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        timeout=_STAGE_TIMEOUT_SEC, env=os.environ.copy(),
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-800:]
        raise RuntimeError(f"manual_update_local rc={proc.returncode}: {tail}")
    # manifest 읽어 요약
    manifest_p = _staging_dir(version) / "manifest.json"
    summary = {"changed_page_count": 0, "manual_ref_candidate_count": 0}
    if manifest_p.exists():
        try:
            mf = json.loads(manifest_p.read_text(encoding="utf-8"))
            summary["changed_page_count"] = mf.get("changed_page_count", 0)
            summary["manual_ref_candidate_count"] = mf.get("manual_ref_candidate_count", 0)
            summary["pdf_mode"] = mf.get("pdf_mode")
        except Exception:
            pass
    return summary


# ── 관리자 알림 (best-effort, 비치명) ────────────────────────────────────────
def _post_review_notice(changed: list[dict], version: str, summary: dict) -> None:
    """게시판에 '검토 필요' 공지만 생성. '자동 반영 완료'처럼 보이는 문구는 쓰지 않는다.
    Sheets 실패해도 비치명(상위에서 무시)."""
    from core.google_sheets import upsert_rows_by_id
    import uuid
    labels = ", ".join(sorted({c["label"] for c in changed}))
    now = _utc_now_iso()
    content = (
        "새 매뉴얼 변경이 감지되어 검토용 staging이 생성되었습니다. "
        "운영 반영은 관리자 검토 후 별도 적용해야 합니다.\n\n"
        f"- 대상: {labels}\n"
        f"- staging version: {version}\n"
        f"- 변경 페이지: {summary.get('changed_page_count', 0)}건\n"
        f"- 영향 manual_ref 후보: {summary.get('manual_ref_candidate_count', 0)}건\n\n"
        "관리자 페이지 > 매뉴얼 업데이트 v1 (staging) 에서 검토하세요. "
        "(이 공지는 자동 생성이며, 운영 manual_ref 는 자동 반영되지 않았습니다.)"
    )
    row = {
        "id": str(uuid.uuid4()),
        "tenant_id": "_system",
        "author_login": "_rhwp_auto",
        "office_name": "매뉴얼 자동 staging",
        "is_notice": "Y",
        "category": "__manual_notice__",
        "title": f"[검토 필요] 새 매뉴얼 staging 생성 ({version})",
        "content": content,
        "created_at": now,
        "updated_at": now,
        "popup_yn": "N",
        "link_url": "",
    }
    header = ["id", "tenant_id", "author_login", "office_name", "is_notice",
              "category", "title", "content", "created_at", "updated_at",
              "popup_yn", "link_url"]
    upsert_rows_by_id("게시판", header, [row], "id")


# ── 메인 진입점 ───────────────────────────────────────────────────────────────
def run_auto_update(*, force: bool = False, detect_only: bool = False,
                    notify: bool = True) -> dict:
    """한 사이클: guard → 감지 → (변경 시) 다운로드 → staging → 상태 기록.

    detect_only=True 면 감지 결과만 반환(다운로드/스테이징/상태 변경 없음).
    어떤 예외도 밖으로 던지지 않는다 — 상태 파일에 기록하고 dict 반환."""
    if detect_only:
        try:
            changed = detect_changes()
            return {"status": "detect_only", "changed": [
                {"label": c["label"], "old_ts": c["old_ts"], "new_ts": c["new_ts"]}
                for c in changed]}
        except Exception as e:
            return {"status": "error", "error": f"{type(e).__name__}: {e}"}

    state = load_state()
    today = _kst_today()

    # already-ran guard (오늘 이미 시도했으면 skip)
    if not force and state.get("last_run_date_kst") == today:
        return {"status": "skipped", "reason": "already ran today", "date": today}

    # 파일 락 (중복 실행 방지)
    if not _acquire_lock():
        return {"status": "skipped", "reason": "locked (another run in progress)"}

    state["status"] = "running"
    state["last_run_at"] = _utc_now_iso()
    state["last_run_date_kst"] = today
    state["error"] = None
    save_state(state)

    result: dict
    try:
        _seed_seen_from_legacy(state)
        changed = detect_changes(state)
        state["last_checked_version"] = _version_from_changes(changed) if changed else None

        if not changed:
            state["status"] = "no_change"
            state["last_success_at"] = _utc_now_iso()
            _push_history(state, {"at": _utc_now_iso(), "status": "no_change"})
            save_state(state)
            result = {"status": "no_change"}
        else:
            version = _version_from_changes(changed)
            state["last_detected_version"] = version
            save_state(state)

            _download_changed(changed, version)
            summary = _run_staging(version)

            # 성공 — seen_timestamps 갱신(다음 감지 기준), 상태 기록
            for c in changed:
                state.setdefault("seen_timestamps", {})[c["label"]] = c["new_ts"]
            state["status"] = "staged"
            state["last_staging_version"] = version
            state["last_success_at"] = _utc_now_iso()
            state["needs_review"] = (summary.get("manual_ref_candidate_count", 0) > 0
                                     or summary.get("changed_page_count", 0) > 0)
            _push_history(state, {
                "at": _utc_now_iso(), "status": "staged", "version": version,
                "labels": sorted({c["label"] for c in changed}),
                "changed_pages": summary.get("changed_page_count", 0),
                "candidates": summary.get("manual_ref_candidate_count", 0),
            })
            save_state(state)
            result = {"status": "staged", "version": version, **summary}

            # 관리자 공지 (best-effort, 비치명)
            if notify:
                try:
                    _post_review_notice(changed, version, summary)
                except Exception as e:
                    print(f"[manual-auto] board notice skipped (non-fatal): {e}")

    except Exception as e:
        state["status"] = "error"
        state["error"] = f"{type(e).__name__}: {e}"
        _push_history(state, {"at": _utc_now_iso(), "status": "error",
                              "error": state["error"]})
        save_state(state)
        result = {"status": "error", "error": state["error"]}
    finally:
        _release_lock()

    return result


def scheduled_job() -> None:
    """APScheduler 가 호출하는 래퍼. 절대 예외를 밖으로 던지지 않는다(서버 보호)."""
    try:
        res = run_auto_update(force=False, detect_only=False, notify=True)
        print(f"[manual-auto] scheduled run: {res}")
    except Exception as e:  # run_auto_update 가 이미 잡지만 이중 방어
        print(f"[manual-auto] scheduled run crashed (suppressed): {e}")


# ── CLI (수동 dry-run 검증용) ─────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="rhwp 매뉴얼 자동 staging")
    ap.add_argument("--detect-only", action="store_true",
                    help="감지만 수행(다운로드/스테이징/상태변경 없음)")
    ap.add_argument("--force", action="store_true", help="오늘 already-ran guard 무시")
    ap.add_argument("--no-notify", action="store_true", help="게시판 공지 생략")
    args = ap.parse_args()
    out = run_auto_update(force=args.force, detect_only=args.detect_only,
                          notify=not args.no_notify)
    print(json.dumps(out, ensure_ascii=False, indent=2))
