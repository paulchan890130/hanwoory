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


# ── HTTP (간헐 ConnectionReset 대응 retry/backoff) ───────────────────────────
# 우리는 NTCCTT_SEQ=1062 고정 상세 게시물만 추적한다. 메인/목록 페이지는 호출하지 않는다.
_HIKOREA_DETAIL_URL = (
    "https://www.hikorea.go.kr/board/BoardNtcDetailR.pt"
    "?BBS_SEQ=1&BBS_GB_CD=BS10&NTCCTT_SEQ=1062&page=1"
)
_HIKOREA_DL_URL = "https://www.hikorea.go.kr/fileNewExistsChkAjax.pt"
_HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Referer": _HIKOREA_DETAIL_URL,
    "Connection": "close",
}
_HTTP_TIMEOUT = 30          # 초 (요청당)
_DL_TIMEOUT = 180           # 첨부 다운로드는 더 길게
_RETRY_BACKOFFS = [20, 30, 60, 90, 120]  # 최대 5회 재시도 (초)


def _log(event: str, **fields) -> None:
    """단계별 진행 로그(JSON 1줄) — Render 로그에서 stage 추적용."""
    try:
        print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)
    except Exception:
        print(f"[manual-auto] {event} {fields}", flush=True)


def _retryable_excs() -> tuple:
    from requests import exceptions as rexc
    excs = [rexc.ConnectionError, rexc.Timeout, rexc.SSLError, rexc.ChunkedEncodingError]
    try:
        from urllib3.exceptions import ProtocolError as _U3Protocol
        excs.append(_U3Protocol)
    except Exception:
        pass
    return tuple(excs)


def _http_session():
    import requests
    s = requests.Session()
    s.headers.update(_HTTP_HEADERS)
    s.verify = False  # 하이코리아 인증서 체인 이슈 회피(기존 watcher 와 동일)
    return s


def _request_with_retry(session, method: str, url: str, *, stage: str,
                        timeout: int = _HTTP_TIMEOUT, **kwargs):
    """ConnectionReset/Timeout/SSL/ProtocolError 에 한해 backoff 재시도.
    HTTP 4xx/5xx(raise_for_status) 등 비연결 오류는 즉시 전파(재시도 안 함)."""
    retryable = _retryable_excs()
    attempts = 1 + len(_RETRY_BACKOFFS)
    last_exc = None
    for i in range(attempts):
        try:
            _log(f"{stage}_attempt", attempt=i + 1, url=url)
            resp = session.request(method, url, timeout=timeout, **kwargs)
            resp.raise_for_status()
            return resp
        except retryable as e:  # 연결성 오류만 재시도
            last_exc = e
            _log(f"{stage}_retry", attempt=i + 1, error=f"{type(e).__name__}: {e}")
            if i < len(_RETRY_BACKOFFS):
                time.sleep(_RETRY_BACKOFFS[i])
            continue
    _log(f"{stage}_failed", error=f"{type(last_exc).__name__}: {last_exc}")
    raise last_exc if last_exc else RuntimeError(f"{stage}: unknown request failure")


def _fetch_detail_html(session) -> str:
    """고정 상세 URL(NTCCTT_SEQ=1062) GET — retry/backoff 적용."""
    r = _request_with_retry(session, "GET", _HIKOREA_DETAIL_URL, stage="detail_fetch")
    _log("detail_fetch_success", bytes=len(r.text or ""))
    return r.text


def _parse_attachments(html: str) -> list[dict]:
    """상세 HTML 에서 첨부 메타(파일명/timestamp) 파싱. watcher 의 정규식만 재사용."""
    from backend.services.manual_watcher import _FN_PATTERN, _TS_RE
    items: list[dict] = []
    for m in _FN_PATTERN.finditer(html or ""):
        d = m.groupdict()
        ts = _TS_RE.search(d.get("apnd", ""))
        d["timestamp"] = ts.group(1) if ts else None
        items.append(d)
    _log("attachment_parse", found=len(items))
    return items


def _compare_attachments(attachments: list[dict], seen: dict) -> list[dict]:
    """추적 라벨만 골라 seen_timestamps 대비 변경분 반환."""
    from backend.services.manual_watcher import classify_attachment
    changed: list[dict] = []
    for att in attachments:
        label = classify_attachment(att.get("ori", ""))
        if label is None or label not in _TRACKED:
            continue
        new_ts = att.get("timestamp")
        if not new_ts:
            continue
        if seen.get(label) == new_ts:
            continue
        changed.append({"label": label, "old_ts": seen.get(label), "new_ts": new_ts, "att": att})
    _log("timestamp_compare", changed=len(changed))
    return changed


def _download_with_retry(session, att: dict, dst: Path) -> Path:
    """첨부 1개 다운로드 — retry/backoff, Referer=상세URL, OLE 시그니처 검증."""
    data = {
        "spec": att.get("spec"), "dir": att.get("dir"),
        "apndFileNm": att.get("apnd"), "oriFileNm": att.get("ori"),
        "BBS_GB_CD": att.get("bbsGbCd"), "BBS_SEQ": att.get("bbsSeq"),
        "NTCCTT_SEQ": att.get("comcttSeq"), "APND_SEQ": att.get("apndSeq"),
        "BBS_SKIN": att.get("bbsSkin"),
    }
    _log("download_attempt", file=att.get("ori"))
    r = _request_with_retry(
        session, "POST", _HIKOREA_DL_URL, stage="attachment_download",
        timeout=_DL_TIMEOUT, data=data,
        headers={"Referer": _HIKOREA_DETAIL_URL}, allow_redirects=True,
    )
    if not r.content.startswith(b"\xd0\xcf\x11\xe0"):
        raise RuntimeError(f"downloaded content is not OLE/HWP: first8={r.content[:8].hex()}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(r.content)
    _log("download_success", file=att.get("ori"), bytes=len(r.content))
    return dst


def detect_changes(state: dict | None = None) -> list[dict]:
    """하이코리아 고정 상세 게시물에서 변경 첨부만 반환 (retry/backoff 적용).

    네트워크 읽기만 수행. 다운로드/스테이징/상태저장 없음 (dry-run 안전).
    반환: [{label, old_ts, new_ts, att}] (att 는 다운로드용 메타)."""
    if state is None:
        state = load_state()
        _seed_seen_from_legacy(state)
    seen = state.get("seen_timestamps") or {}
    session = _http_session()
    html = _fetch_detail_html(session)
    attachments = _parse_attachments(html)
    return _compare_attachments(attachments, seen)


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
    """변경된 원본 HWP/HWPX 를 incoming/{version}/ 에 원본 파일명으로 저장(retry 적용).
    unlock/PDF 변환은 하지 않는다. 운영 unlocked_*.pdf 는 절대 건드리지 않는다."""
    inc = _incoming_dir(version)
    inc.mkdir(parents=True, exist_ok=True)
    session = _http_session()
    saved: list[Path] = []
    for c in changed:
        att = c["att"]
        ori = att.get("ori") or f"{c['label']}.hwp"
        saved.append(_download_with_retry(session, att, inc / ori))
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


# ── PG 기반 entry (단일 출처 = PostgreSQL) ────────────────────────────────────
def _download_changed_to(changed: list[dict], dest_dir: Path, session=None) -> list[Path]:
    """변경 원본을 임의 디렉토리(/tmp 등)에 원본 파일명으로 저장(retry 적용). unlock/PDF 변환 없음."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    s = session or _http_session()
    saved: list[Path] = []
    for c in changed:
        att = c["att"]
        ori = att.get("ori") or f"{c['label']}.hwp"
        saved.append(_download_with_retry(s, att, dest_dir / ori))
    return saved


def _seen_from_pg(svc) -> dict:
    """PG 의 최신 version label_timestamps 를 seen 기준으로 사용. 없으면 레거시 시드."""
    versions = svc.list_versions()
    if versions:
        lt = versions[0].get("label_timestamps") or {}
        if lt:
            return lt
    state: dict = {}
    _seed_seen_from_legacy(state)
    return state.get("seen_timestamps", {})


def run_auto_update_pg(*, force: bool = False, trigger: str = "manual",
                       notify: bool = True) -> dict:
    """PG 단일 출처 파이프라인: 감지 → /tmp 다운로드 → rhwp extract(/tmp) →
    PG baseline diff → PG 저장(version/changed/candidates) → decision 병합 →
    /tmp 삭제. chromium/검토PDF 미사용. 운영 manual_ref/PDF 무수정. 예외 비전파."""
    import shutil
    import tempfile

    from backend.services import manual_update_pg_service as svc
    if not svc.pg_enabled():
        return {"status": "skipped", "reason": "pg_disabled "
                "(need DATABASE_URL + FEATURE_PG_MANUAL_UPDATE=true)"}

    run_id = svc.start_run(trigger, force=force,
                           instance=os.environ.get("RENDER_INSTANCE_ID"))
    if run_id is None:
        return {"status": "skipped", "reason": "already ran today or locked"}

    tmpdir: Path | None = None
    version: str | None = None
    stage = "init"
    try:
        # 1) 감지 (고정 상세 URL fetch + parse + compare) — 단계별 stage 추적
        seen = _seen_from_pg(svc)
        session = _http_session()
        stage = "detail_fetch"
        html = _fetch_detail_html(session)
        stage = "attachment_parse"
        attachments = _parse_attachments(html)
        stage = "timestamp_compare"
        changed = _compare_attachments(attachments, seen)
        if not changed:
            svc.finish_no_change(run_id)
            return {"status": "no_change"}

        version = _version_from_changes(changed)
        tmpdir = Path(tempfile.gettempdir()) / "manual_update" / version

        # 2) 다운로드 (/tmp, retry) — 같은 session 재사용(Referer=상세URL)
        stage = "attachment_download"
        _download_changed_to(changed, tmpdir, session=session)

        # 3) rhwp extract → /tmp, diff vs PG baseline (chromium 불필요)
        from backend.scripts.manual_update_local import (
            NODE_TOOLS, run_node, load_jsonl, classify_label, diff_pages,
        )
        new_pages_by_label: dict[str, list[dict]] = {}
        all_changed: list[dict] = []
        label_ts: dict[str, str] = {c["label"]: c["new_ts"] for c in changed}

        stage = "extract"
        _log("extract_start", version=version)
        for p in sorted(tmpdir.iterdir()):
            if not p.is_file() or p.suffix.lower() not in (".hwp", ".hwpx"):
                continue
            label = classify_label(p.name)
            if not label:
                continue
            run_node([
                str(NODE_TOOLS / "extract.mjs"),
                "--src", str(p), "--label", label,
                "--out-dir", str(tmpdir),
            ], tmpdir / f"extract_{label}.log")
            pages = load_jsonl(tmpdir / f"{label}_pages.jsonl")
            new_pages_by_label[label] = pages
            baseline = svc.load_baseline_pages(label)
            if baseline:
                stage = "diff"
                _log("diff_start", label=label, baseline_pages=len(baseline), new_pages=len(pages))
                all_changed.extend(diff_pages(baseline, pages))
            else:
                _log("diff_skip_no_baseline", label=label)

        non_same = [c for c in all_changed if c.get("change_type") != "same"]
        refs = svc.load_base_refs()
        stage = "candidates"
        _log("candidates_start", changed=len(non_same), refs=len(refs))
        candidates = svc.compute_candidates(all_changed, new_pages_by_label, refs)

        stage = "save"
        svc.save_version(version, label_ts, non_same, candidates, run_id)
        stage = "merge"
        merge = svc.merge_decisions_for_version(version, candidates)
        svc.finish_staged(run_id, version, len(non_same), len(candidates))
        _log("run_staged", version=version, changed=len(non_same), candidates=len(candidates))

        if notify:
            try:
                _post_review_notice(
                    changed, version,
                    {"changed_page_count": len(non_same),
                     "manual_ref_candidate_count": len(candidates)},
                )
            except Exception as e:
                print(f"[manual-auto] board notice skipped (non-fatal): {e}")

        return {"status": "staged", "version": version,
                "changed": len(non_same), "candidates": len(candidates),
                "decisions": merge}
    except Exception as e:
        err = f"[{stage}] {type(e).__name__}: {e}"
        _log("run_failed", stage=stage, error=err)
        svc.finish_error(run_id, err)  # error 문자열에 error_stage 포함
        return {"status": "error", "error_stage": stage, "error": err}
    finally:
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)


def run_auto_update_pg_dryrun(force: bool = False, allow_node: bool = True) -> dict:
    """로컬 전용 test-run — 감지→/tmp 다운로드→rhwp extract→PG baseline diff→candidates
    까지만 수행하고 **카운트만** 반환한다. PG staging(version/changed/candidates/decision)
    이나 운영 manual_ref/PDF 에 **아무것도 쓰지 않는다**(start_run/save_version 미호출).
    /tmp 는 항상 삭제. node(rhwp)가 필요하므로 호스트(또는 node 포함 워커)에서 실행해야 한다.
    force=True 면 seen 을 무시해 현재 첨부 전체를 변경분으로 간주(다운로드/추출/후보 단계 검증용).
    allow_node=False(=node 미설치 런타임) 면 감지까지만 하고 다운로드/추출/후보는 건너뛴다."""
    import shutil
    import tempfile
    from backend.services import manual_update_pg_service as svc
    if not svc.pg_enabled():
        return {"status": "skipped", "reason": "pg_disabled (need DATABASE_URL + FEATURE_PG_MANUAL_UPDATE=true)"}
    tmpdir: Path | None = None
    stage = "init"
    out: dict = {"status": "ok", "stages": {}, "wrote_to_pg": False, "force": force}
    try:
        seen = {} if force else _seen_from_pg(svc)
        out["stages"]["seen_timestamps"] = seen
        session = _http_session()
        stage = "detail_fetch"
        html = _fetch_detail_html(session)
        out["stages"]["detail_fetch_bytes"] = len(html or "")
        stage = "attachment_parse"
        atts = _parse_attachments(html)
        out["stages"]["attachments_found"] = len(atts)
        stage = "timestamp_compare"
        changed = _compare_attachments(atts, seen)
        out["stages"]["changed"] = [{"label": c["label"], "old_ts": c["old_ts"], "new_ts": c["new_ts"]} for c in changed]
        if not changed:
            out["status"] = "no_change"
            return out
        version = _version_from_changes(changed)
        out["version"] = version
        if not allow_node:
            # node(rhwp) 없는 런타임(backend container/Render): 감지까지만, 다운로드/추출 생략.
            out["status"] = "detection_only"
            out["stages"]["note"] = "변경 감지됨 — 이 런타임에 node/rhwp 미설치로 다운로드/추출/후보 생략. 실제 처리는 Render Cron/Worker(Dockerfile.worker)가 담당."
            return out
        tmpdir = Path(tempfile.gettempdir()) / "manual_update_dryrun" / version
        out["stages"]["tmp_dir"] = str(tmpdir)
        stage = "download"
        saved = _download_changed_to(changed, tmpdir, session=session)
        out["stages"]["downloaded"] = [{"name": p.name, "bytes": p.stat().st_size} for p in saved]
        from backend.scripts.manual_update_local import (
            NODE_TOOLS, run_node, load_jsonl, classify_label, diff_pages,
        )
        new_pages_by_label: dict[str, list[dict]] = {}
        all_changed: list[dict] = []
        stage = "extract"
        for p in sorted(tmpdir.iterdir()):
            if not p.is_file() or p.suffix.lower() not in (".hwp", ".hwpx"):
                continue
            label = classify_label(p.name)
            if not label:
                continue
            run_node([str(NODE_TOOLS / "extract.mjs"), "--src", str(p),
                      "--label", label, "--out-dir", str(tmpdir)],
                     tmpdir / f"extract_{label}.log")
            pages = load_jsonl(tmpdir / f"{label}_pages.jsonl")
            new_pages_by_label[label] = pages
            baseline = svc.load_baseline_pages(label)
            if baseline:
                all_changed.extend(diff_pages(baseline, pages))
        out["stages"]["extracted_pages"] = {k: len(v) for k, v in new_pages_by_label.items()}
        non_same = [c for c in all_changed if c.get("change_type") != "same"]
        refs = svc.load_base_refs()
        stage = "candidates"
        candidates = svc.compute_candidates(all_changed, new_pages_by_label, refs)
        out["stages"]["changed_pages"] = len(non_same)
        out["stages"]["candidates"] = len(candidates)
        out["status"] = "dryrun_complete"
        return out
    except Exception as e:
        out["status"] = "error"
        out["error_stage"] = stage
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    finally:
        if tmpdir is not None:
            shutil.rmtree(tmpdir, ignore_errors=True)
            out["source_deleted"] = not tmpdir.exists()


_MANUAL_NORM = {"visa": "visa", "사증민원": "visa",
                "residence": "stay", "stay": "stay", "체류민원": "stay"}


def _existing_artifact_rowids(svc, version: str) -> set:
    """해당 version 에 이미 생성된 candidate PDF artifact 의 row_id 집합.
    candidate bundle 의 note 규칙은 'candidate <row_id>' (save_pdf_artifact 호출부와 일치)."""
    rowids: set = set()
    try:
        for a in svc.get_pdf_artifacts(version=version):
            note = (a.get("note") or "")
            if note.startswith("candidate "):
                rid = note[len("candidate "):].strip()
                if rid:
                    rowids.add(rid)
    except Exception:
        pass
    return rowids


def generate_pdf_artifacts_for_version(version: str | None = None, *, neighbor: int = 1,
                                       limit: int | None = None,
                                       row_ids: list[str] | None = None,
                                       skip_existing: bool = True) -> dict:
    """변경 페이지 PDF artifact 생성(node/chromium 필요 — host/worker 전용).

    흐름: 후보 조회 → (skip_existing) 이미 artifact 있는 후보 제외 → 남은 후보가 있으면
    현재 첨부 /tmp 다운로드 → 후보별 (페이지±이웃) 목록 산출 → generate_pdf.mjs --pages
    1회 실행(문서 1회 로드) → 후보별 per-page PDF 를 PyMuPDF 로 묶어
    manual_pdf_artifacts.pdf_blob 저장 → /tmp 삭제.

    중복 방지: 같은 version 의 candidate(row_id)에 이미 artifact 가 있으면 재생성하지 않는다
    (skip_existing=True). 남은 후보가 없으면 다운로드조차 하지 않고 skip 한다.
    PDF 생성 실패는 텍스트/후보 데이터에 영향 없다(이 함수는 artifact 만 다룬다).
    반환: {version, generated, failed, skipped_existing, artifact_ids, errors, status}."""
    import shutil
    import tempfile
    from backend.services import manual_update_pg_service as svc
    if not svc.pg_enabled():
        return {"status": "skipped", "reason": "pg_disabled"}
    version = version or svc.get_state_dict().get("last_staging_version")
    if not version:
        return {"status": "skipped", "reason": "no staging version"}

    out = {"version": version, "generated": 0, "failed": 0, "skipped_existing": 0,
           "artifact_ids": [], "errors": []}

    # 생성 대상(target) 을 다운로드 전에 확정해 불필요한 하이코리아 접속/추출을 피한다.
    cands_all = svc.get_candidates_enriched(version)
    if row_ids:
        cands_all = [c for c in cands_all if c.get("row_id") in row_ids]
    existing_rowids = _existing_artifact_rowids(svc, version)
    if skip_existing:
        target = [c for c in cands_all if c.get("row_id") not in existing_rowids]
        out["skipped_existing"] = len(cands_all) - len(target)
    else:
        target = list(cands_all)
    if limit:
        target = target[:limit]
    if not cands_all:
        return {**out, "status": "skipped", "reason": "no_candidates"}
    if not target:
        return {**out, "status": "skipped", "reason": "artifacts_already_exist",
                "existing_artifacts": len(existing_rowids), "candidates": len(cands_all)}

    tmpdir = Path(tempfile.gettempdir()) / "manual_pdf_artifacts" / version
    try:
        # 현재 첨부 다운로드(force = seen 무시)
        session = _http_session()
        atts = _parse_attachments(_fetch_detail_html(session))
        changed = _compare_attachments(atts, {})
        if not changed:
            return {**out, "status": "no_attachments"}
        _download_changed_to(changed, tmpdir, session=session)

        from backend.scripts.manual_update_local import NODE_TOOLS, run_node, classify_label
        import fitz

        for hwp in sorted(tmpdir.iterdir()):
            if not hwp.is_file() or hwp.suffix.lower() not in (".hwp", ".hwpx"):
                continue
            label = classify_label(hwp.name)
            manual = _MANUAL_NORM.get(label or "")
            if not manual:
                continue
            # target 은 이미 row_ids/skip_existing/limit 적용된 생성 대상 후보다.
            cands = [c for c in target if c.get("manual_label") == label]
            if not cands:
                continue
            # 후보별 페이지(±이웃) 합집합 → 1회 렌더
            def _crange(c):
                a = int(c.get("candidate_page_from") or 0); b = int(c.get("candidate_page_to") or a)
                lo = max(1, min(a, b) - neighbor); hi = max(a, b) + neighbor
                return list(range(lo, hi + 1))
            needed = sorted({p for c in cands for p in _crange(c)})
            pages_dir = tmpdir / f"pages_{label}"
            try:
                run_node([str(NODE_TOOLS / "generate_pdf.mjs"), "--src", str(hwp),
                          "--label", label, "--pages", ",".join(map(str, needed)),
                          "--flat", "--out-dir", str(pages_dir)],
                         tmpdir / f"genpdf_{label}.log")
            except Exception as e:
                out["failed"] += len(cands)
                out["errors"].append(f"{label} generate_pdf failed: {type(e).__name__}: {e}")
                continue
            # 후보별 번들 저장
            for c in cands:
                pages = _crange(c)
                try:
                    bundle = fitz.open()
                    used = []
                    for p in pages:
                        pf = pages_dir / label / f"p{p:04d}.pdf"
                        if not pf.is_file():
                            pf = pages_dir / f"p{p:04d}.pdf"
                        if pf.is_file():
                            with fitz.open(pf) as src:
                                bundle.insert_pdf(src)
                            used.append(p)
                    if not used:
                        out["failed"] += 1
                        out["errors"].append(f"{c['row_id']}: no page PDFs")
                        bundle.close()
                        continue
                    blob = bundle.tobytes()
                    bundle.close()
                    rec = svc.save_pdf_artifact(
                        manual=manual, artifact_type="changed_page_bundle", version=version,
                        source="staging", page_from=min(used), page_to=max(used),
                        page_numbers=used, pdf_blob=blob, page_count=len(used),
                        status="generated", note=f"candidate {c['row_id']}",
                    )
                    out["generated"] += 1
                    out["artifact_ids"].append(rec.get("id"))
                except Exception as e:
                    out["failed"] += 1
                    out["errors"].append(f"{c['row_id']}: bundle failed: {type(e).__name__}: {e}")
        out["status"] = "ok"
        return out
    except Exception as e:
        return {**out, "status": "error", "error": f"{type(e).__name__}: {e}"}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
        out["source_deleted"] = not tmpdir.exists()


def _backfill_pdf_artifacts(*, limit: int | None = None, neighbor: int = 1) -> dict:
    """no_change 사이클 보강: 신규 매뉴얼 변경이 없어도, 최신 staging version 의 candidate
    중 PDF artifact 가 아직 없는 것만 생성(backfill)한다. 이미 충분하면 생성하지 않고 skip.

    '다음 실제 변경 때까지 PDF 0' 문제를 해소하기 위한 경로. 후보별 중복 방지는
    generate_pdf_artifacts_for_version 내부 dedup(skip_existing=True)에 위임한다.
    운영 manual_ref/apply/배포 PDF 는 절대 건드리지 않는다(staging artifact 만 생성)."""
    from backend.services import manual_update_pg_service as svc
    if not svc.pg_enabled():
        _log("pdf_backfill_check", pg=False)
        return {"status": "skipped", "reason": "pg_disabled", "mode": "backfill"}
    version = svc.get_state_dict().get("last_staging_version")
    if not version:
        versions = svc.list_versions()
        version = versions[0].get("version") if versions else None
    _log("pdf_backfill_check", version=version)
    if not version:
        _log("pdf_backfill_no_staging_version")
        return {"status": "skipped", "reason": "no_staging_version", "mode": "backfill"}
    cands = svc.get_candidates_enriched(version)
    existing = _existing_artifact_rowids(svc, version)
    missing = [c for c in cands if c.get("row_id") not in existing]
    if not cands:
        _log("pdf_backfill_no_candidates", version=version)
        return {"status": "skipped", "reason": "no_candidates",
                "version": version, "mode": "backfill"}
    if not missing:
        _log("pdf_backfill_artifacts_already_exist", version=version,
             candidates=len(cands), artifacts=len(existing))
        return {"status": "skipped", "reason": "artifacts_already_exist", "version": version,
                "candidates": len(cands), "existing_artifacts": len(existing), "mode": "backfill"}
    _log("pdf_backfill_generate_start", version=version, missing=len(missing))
    try:
        res = generate_pdf_artifacts_for_version(
            version, limit=limit, neighbor=neighbor,
            row_ids=[c["row_id"] for c in missing], skip_existing=True)
    except Exception as e:  # 이중 방어 — staging 에 전이 금지
        _log("pdf_backfill_failed", version=version, error=f"{type(e).__name__}: {e}")
        return {"status": "error", "version": version, "mode": "backfill",
                "error": f"{type(e).__name__}: {e}"}
    _log("pdf_backfill_generate_done", version=version,
         generated=res.get("generated"), failed=res.get("failed"),
         skipped_existing=res.get("skipped_existing"))
    res["mode"] = "backfill"
    return res


def run_worker_cycle(*, force: bool = False, with_pdf: bool = True,
                     notify: bool = True, limit: int | None = None,
                     trigger: str = "cron") -> dict:
    """Render Cron Job / Worker 1사이클 — 서버 자동화 진입점.

    흐름:
      1) run_auto_update_pg(): 감지 → /tmp 다운로드 → rhwp extract → diff →
         candidates → PG version/changed/candidates 저장 → decision 병합 → /tmp 삭제.
      2) with_pdf 면 PDF artifact 단계:
         - staging == 'staged' (신규 변경): 그 version 의 후보로 PDF 생성.
         - staging == 'no_change' (신규 변경 없음): 최신 staging version 의 후보 중
           artifact 가 없는 것만 backfill 생성(_backfill_pdf_artifacts).
         두 경로 모두 후보별 중복 방지(skip_existing)가 적용된다.

    PDF 단계 실패는 텍스트/후보 저장(staging) 결과에 **전이되지 않는다** — PDF 오류는
    out['pdf'] 에 담아 반환할 뿐, staging 성공은 그대로 유지한다. 어떤 예외도 밖으로
    던지지 않는다(서버 자동화 보호). 실행 결과 기록은 run_auto_update_pg 내부의
    manual_update_runs(svc.finish_staged/finish_error) + save_pdf_artifact 가 담당한다."""
    staging = run_auto_update_pg(force=force, trigger=trigger, notify=notify)
    out = {"staging": staging, "pdf": None}
    if not with_pdf:
        out["pdf"] = {"status": "skipped", "reason": "with_pdf=False"}
        return out
    status = staging.get("status") if isinstance(staging, dict) else None
    if status == "staged":
        version = staging.get("version")
        try:
            out["pdf"] = generate_pdf_artifacts_for_version(version, limit=limit)
        except Exception as e:  # 이중 방어 — staging 에 전이 금지
            out["pdf"] = {"status": "error", "version": version,
                          "error": f"{type(e).__name__}: {e}"}
    elif status == "no_change":
        # 신규 변경이 없어도 최신 staging version 의 누락 PDF 를 backfill.
        out["pdf"] = _backfill_pdf_artifacts(limit=limit)
    else:
        out["pdf"] = {"status": "skipped", "reason": f"staging status={status}"}
    return out


def scheduled_job() -> None:
    """APScheduler 가 호출하는 래퍼. 절대 예외를 밖으로 던지지 않는다(서버 보호).
    FEATURE_PG_MANUAL_UPDATE=true 면 PG 경로, 아니면 파일 기반 경로(fallback)."""
    use_pg = False
    try:
        from backend.db.feature_flags import pg_manual_update_enabled
        use_pg = pg_manual_update_enabled()
    except Exception:
        use_pg = False
    try:
        if use_pg:
            res = run_auto_update_pg(force=False, trigger="web", notify=True)
        else:
            res = run_auto_update(force=False, detect_only=False, notify=True)
        print(f"[manual-auto] scheduled run ({'pg' if use_pg else 'file'}): {res}")
    except Exception as e:  # entry 들이 이미 잡지만 이중 방어
        print(f"[manual-auto] scheduled run crashed (suppressed): {e}")


# ── CLI (수동 dry-run 검증용) ─────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="rhwp 매뉴얼 자동 staging")
    ap.add_argument("--pg", action="store_true",
                    help="PG 단일 출처 경로 실행(Render Cron Job 권장). 미지정 시 파일 기반")
    ap.add_argument("--with-pdf", action="store_true",
                    help="PG staging 후 변경 페이지 PDF artifact 까지 생성(node+chromium 필요). --pg 와 함께 사용")
    ap.add_argument("--limit", type=int, default=None,
                    help="--with-pdf 시 PDF 생성 후보 수 제한(테스트용)")
    ap.add_argument("--detect-only", action="store_true",
                    help="감지만 수행(다운로드/스테이징/상태변경 없음)")
    ap.add_argument("--force", action="store_true", help="오늘 already-ran guard 무시")
    ap.add_argument("--no-notify", action="store_true", help="게시판 공지 생략")
    args = ap.parse_args()
    if args.with_pdf:
        # staging → (chromium) PDF artifact 까지. PG 경로 전용(파일 기반은 미지원).
        out = run_worker_cycle(force=args.force, with_pdf=True,
                               notify=not args.no_notify, limit=args.limit,
                               trigger="manual")
    elif args.pg:
        out = run_auto_update_pg(force=args.force, trigger="manual",
                                 notify=not args.no_notify)
    else:
        out = run_auto_update(force=args.force, detect_only=args.detect_only,
                              notify=not args.no_notify)
    print(json.dumps(out, ensure_ascii=False, indent=2))
