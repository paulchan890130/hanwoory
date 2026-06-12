"""메뉴얼 관련 라우터

엔드포인트:
  GET  /api/manual/search                    - GPT 기반 출입국 법령 Q&A
  GET  /api/manual/watcher-state             - 매뉴얼 최신 버전 메타
  GET  /api/manual/update-review             - 페이지 변경 검토 목록 (admin)
  POST /api/manual/update-review/{id}/apply  - 페이지 변경 적용 (admin)
  POST /api/manual/update-review/{id}/skip   - 검토 건너뜀 (admin)
  POST /api/manual/run-rematch               - rematch 스크립트 즉시 실행 (admin)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
import datetime as dt
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from urllib.parse import quote as _url_quote
from backend.auth import get_current_user, require_admin, decode_token

router = APIRouter()

ROOT        = Path(__file__).parent.parent.parent
# 매뉴얼/검토 산출물 디렉토리 — MANUALS_DATA_DIR(기본=backend/data/manuals)로 분리.
# Render 운영에서 Persistent Disk(/data/manuals)를 쓰면 watcher_state/review JSON 이 영속화된다.
try:
    from config import MANUALS_DATA_DIR as _MANUALS_DATA_DIR
    MANUALS = Path(_MANUALS_DATA_DIR)
except Exception:
    MANUALS = ROOT / "backend" / "data" / "manuals"
BACKUP_DIR  = ROOT / "backend" / "data" / "backups"
STATE_PATH  = MANUALS / ".watcher_state.json"
REVIEW_PATH = MANUALS / "manual_update_review.json"
DB_PATH     = ROOT / "backend" / "data" / "immigration_guidelines_db_v2.json"
REMATCH_PY  = ROOT / "backend" / "scripts" / "manual_ref_rematch.py"


# ── 매뉴얼 PDF 직접 다운로드 ─────────────────────────────────────────────────
ALLOWED_MANUAL_TYPES = {"체류민원", "사증민원"}


@router.get("/download/{manual_type}")
def download_manual_pdf(
    manual_type: str,
    token: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    """서버에 저장된 잠금해제 PDF 직접 다운로드 — query token 또는 Authorization 헤더 허용."""
    actual = token
    if not actual and authorization and authorization.startswith("Bearer "):
        actual = authorization[7:]
    if not actual:
        raise HTTPException(status_code=401, detail="인증 토큰 필요")
    try:
        payload = decode_token(actual)
        if not payload.get("sub"):
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰")

    if manual_type not in ALLOWED_MANUAL_TYPES:
        raise HTTPException(status_code=400, detail=f"manual_type은 {ALLOWED_MANUAL_TYPES} 중 하나여야 합니다.")

    pdf_path = MANUALS / f"unlocked_{manual_type}.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"{manual_type} PDF 파일이 없습니다.")

    # watcher_state.json에서 timestamp 읽어 파일명에 포함
    timestamp_part = ""
    if STATE_PATH.exists():
        try:
            st = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            ts = st.get("manuals", {}).get(manual_type, {}).get("timestamp", "")
            if ts:
                timestamp_part = f"_{ts[:8]}"   # YYYYMMDD만 사용
        except Exception:
            pass

    filename = f"{manual_type}{timestamp_part}.pdf"
    encoded = _url_quote(filename, safe="")
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


# ── GPT 검색 (기존) ──────────────────────────────────────────────────────────
@router.get("/search")
def manual_search(
    q: str,
    user: dict = Depends(get_current_user),
):
    """GPT 기반 출입국 법령 검색."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="검색어를 입력하세요.")
    try:
        from core.manual_search import search_via_server
        answer = search_via_server(q.strip())
        return {"question": q.strip(), "answer": answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"검색 오류: {str(e)}")


# ── 매뉴얼 버전 상태 ─────────────────────────────────────────────────────────
@router.get("/watcher-state")
def get_watcher_state(user: dict = Depends(get_current_user)):
    """매뉴얼 파일 최신 버전 메타 반환."""
    if not STATE_PATH.exists():
        return {}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        manuals = state.get("manuals", {})
        result = {}
        for label, meta in manuals.items():
            result[label] = {
                "timestamp":     meta.get("timestamp", ""),
                "downloaded_at": meta.get("downloaded_at", ""),
                "pdf_path":      meta.get("pdf_path"),
                "ori_filename":  meta.get("ori_filename", ""),
            }
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"상태 파일 읽기 실패: {e}")


# ── 사용자 알림용: 최신 매뉴얼 업데이트 식별자 ─────────────────────────────────
@router.get("/latest")
def latest_manual_update(user: dict = Depends(get_current_user)):
    """로그인 사용자 알림용(비관리자 허용, 읽기 전용).

    PG ``manual_update_versions`` 최신 1건의 (version, detected_at) 반환.
    PG 미구성 / 데이터 없음 / 오류 시 ``version=None`` 으로 graceful.
    프론트는 이 식별자로 '매뉴얼 업데이트' 토스트를 로그인 최초 1회만 띄운다
    (localStorage marker; DB read-marker 는 정식 개선안으로 유보)."""
    try:
        from backend.db.session import get_sessionmaker, is_configured
        if not is_configured():
            return {"version": None, "detected_at": None}
        from backend.db.models.manual_update import ManualUpdateVersion
        from sqlalchemy import select
        with get_sessionmaker()() as s:
            row = s.scalars(
                select(ManualUpdateVersion)
                .order_by(ManualUpdateVersion.detected_at.desc())
                .limit(1)
            ).first()
            if row is None:
                return {"version": None, "detected_at": None}
            return {
                "version": row.version,
                "detected_at": row.detected_at.isoformat() if row.detected_at else None,
            }
    except Exception:
        return {"version": None, "detected_at": None}


# ── 페이지 변경 검토 목록 ──────────────────────────────────────────────────────
@router.get("/update-review")
def get_update_review(admin: dict = Depends(require_admin)):
    """manual_update_review.json 반환."""
    if not REVIEW_PATH.exists():
        return {"rows": [], "last_run": None, "total_override": 0, "counts": {}}
    try:
        return json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"리뷰 파일 읽기 실패: {e}")


# ── 페이지 변경 적용 ───────────────────────────────────────────────────────────
class ApplyPageBody(BaseModel):
    page_from: int
    page_to: int


@router.post("/update-review/{row_id}/apply")
def apply_page_change(
    row_id: str,
    body: ApplyPageBody,
    admin: dict = Depends(require_admin),
):
    """승인된 후보/직접입력 페이지만 운영 manual_ref 에 반영(2단계 분리).

    가드: 해당 row 의 decision 이 REVIEWED_APPROVE_CANDIDATE 또는 NEEDS_MANUAL_PAGE
    일 때만 반영한다. KEEP_EXISTING / REJECTED / UNRESOLVED / 미검토(NEW_CANDIDATE)는
    운영 반영을 거부 → 기존 매핑을 자동/실수로 강등하지 않는다."""
    if body.page_from < 1:
        raise HTTPException(status_code=400, detail="page_from은 1 이상이어야 합니다.")

    # 운영 반영 전 staging 결정 확인 (승인/직접입력만 허용)
    APPLYABLE = {"REVIEWED_APPROVE_CANDIDATE", "NEEDS_MANUAL_PAGE"}
    review_row = _get_review_row(row_id)
    decision = (review_row or {}).get("decision", "")
    if decision not in APPLYABLE:
        raise HTTPException(
            status_code=400,
            detail=(f"운영 반영 불가: decision='{decision or '미검토'}'. "
                    f"'후보 승인' 또는 '직접 페이지 입력' 상태에서만 반영할 수 있습니다."),
        )

    # DB 읽기
    if not DB_PATH.exists():
        raise HTTPException(status_code=500, detail="DB 파일 없음")
    raw = DB_PATH.read_bytes()
    db  = json.loads(raw.decode("utf-8"))
    rows = db.get("master_rows", [])
    row = next((r for r in rows if r.get("row_id") == row_id), None)
    if not row:
        raise HTTPException(status_code=404, detail=f"row_id '{row_id}' 없음")

    # manual_ref 수정
    found = False
    for ref in (row.get("manual_ref") or []):
        if ref.get("match_type") == "manual_override":
            old_pf = ref.get("page_from", 0)
            ref["page_from"] = body.page_from
            ref["page_to"]   = body.page_to
            found = True
            break

    if not found:
        raise HTTPException(status_code=400, detail="manual_override ref 없음")

    # 백업
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    bk = BACKUP_DIR / f"immigration_guidelines_db_v2.manual_rematch_backup_{ts}.json"
    bk.write_bytes(raw)

    # DB 저장
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")

    # review JSON 갱신 (decision=APPLIED)
    _update_review_row(row_id, applied=True, reviewed=True, decision="APPLIED",
                       page_from=body.page_from, page_to=body.page_to)

    return {"ok": True, "row_id": row_id, "page_from": body.page_from, "page_to": body.page_to, "backup": bk.name}


# ── 검토 건너뜀 (하위호환) ─────────────────────────────────────────────────────
@router.post("/update-review/{row_id}/skip")
def skip_review(row_id: str, admin: dict = Depends(require_admin)):
    """검토 건너뜀 표시 (하위호환 — 운영 반영 없음, review JSON 만 갱신)."""
    _update_review_row(row_id, reviewed=True)
    return {"ok": True, "row_id": row_id}


# ── 검토 결정 저장 (staging 전용 — 운영 manual_ref 미반영) ──────────────────────
_VALID_DECISIONS = {
    "NEW_CANDIDATE", "REVIEWED_KEEP_EXISTING", "REVIEWED_APPROVE_CANDIDATE",
    "REJECTED_BAD_CANDIDATE", "NEEDS_MANUAL_PAGE", "UNRESOLVED",
}


class DecisionBody(BaseModel):
    decision: str
    page_from: Optional[int] = None
    page_to: Optional[int] = None
    note: Optional[str] = None


@router.post("/update-review/{row_id}/decision")
def set_review_decision(row_id: str, body: DecisionBody, admin: dict = Depends(require_admin)):
    """검토 결정을 review JSON 에만 저장한다. 운영 manual_ref(DB)는 절대 건드리지 않음.

    실제 운영 반영은 별도의 /apply (운영 반영) 액션으로만 수행된다."""
    if body.decision not in _VALID_DECISIONS:
        raise HTTPException(status_code=400, detail=f"허용되지 않은 decision: {body.decision}")
    ok = _set_review_decision(
        row_id, body.decision,
        manual_page_from=body.page_from, manual_page_to=body.page_to, note=body.note,
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"row_id '{row_id}' 없음")
    return {"ok": True, "row_id": row_id, "decision": body.decision}


# ── rematch 즉시 실행 ─────────────────────────────────────────────────────────
@router.post("/run-rematch")
def run_rematch(admin: dict = Depends(require_admin)):
    """manual_ref_rematch.py --report-only 실행 후 summary 반환."""
    if not REMATCH_PY.exists():
        raise HTTPException(status_code=500, detail="rematch 스크립트 없음")
    try:
        result = subprocess.run(
            [sys.executable, str(REMATCH_PY), "--report-only"],
            capture_output=True, text=True, encoding="utf-8", timeout=300,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"rematch 실패: {result.stderr[:500]}")

        # 최신 review 파일 읽기
        if REVIEW_PATH.exists():
            data = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
            return {
                "ok": True,
                "stdout": result.stdout[-1000:],
                "last_run": data.get("last_run"),
                "counts": data.get("counts", {}),
                "total_override": data.get("total_override", 0),
            }
        return {"ok": True, "stdout": result.stdout[-1000:]}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="rematch 타임아웃 (5분)")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────────
def _get_review_row(row_id: str) -> Optional[dict]:
    """manual_update_review.json 에서 단일 row 반환 (읽기 전용)."""
    if not REVIEW_PATH.exists():
        return None
    try:
        data = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
        for r in data.get("rows", []):
            if r.get("row_id") == row_id:
                return r
    except Exception:
        return None
    return None


def _update_review_row(
    row_id: str,
    *,
    reviewed: bool = False,
    applied: bool = False,
    decision: Optional[str] = None,
    page_from: Optional[int] = None,
    page_to: Optional[int] = None,
) -> None:
    """manual_update_review.json의 특정 row 필드 업데이트."""
    if not REVIEW_PATH.exists():
        return
    try:
        data = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
        for r in data.get("rows", []):
            if r.get("row_id") == row_id:
                if reviewed:
                    r["reviewed"] = True
                if applied:
                    r["applied"] = True
                if decision is not None:
                    r["decision"] = decision
                if page_from is not None:
                    r["found_page"] = page_from
                break
        REVIEW_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _set_review_decision(
    row_id: str,
    decision: str,
    *,
    manual_page_from: Optional[int] = None,
    manual_page_to: Optional[int] = None,
    note: Optional[str] = None,
) -> bool:
    """검토 결정을 review JSON 에 저장 (staging 전용). 운영 DB 미반영.

    결정 시점의 후보 페이지를 reviewed_candidate_page 로 스냅샷 → 재실행 시
    후보가 바뀌면 candidate_changed 로 재검토를 유도한다."""
    if not REVIEW_PATH.exists():
        return False
    try:
        data = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False
    hit = False
    for r in data.get("rows", []):
        if r.get("row_id") == row_id:
            hit = True
            r["decision"] = decision
            # NEW_CANDIDATE 로 되돌리는 경우만 미검토로, 그 외 결정은 검토완료로 표시
            r["reviewed"] = decision != "NEW_CANDIDATE"
            r["reviewed_candidate_page"] = r.get("found_page")
            r["candidate_changed"] = False
            if decision == "NEEDS_MANUAL_PAGE" and manual_page_from is not None:
                r["manual_page_from"] = manual_page_from
                r["manual_page_to"] = manual_page_to if manual_page_to is not None else manual_page_from
            if note is not None:
                r["decision_note"] = note
            break
    if not hit:
        return False
    try:
        REVIEW_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return False
    return True
