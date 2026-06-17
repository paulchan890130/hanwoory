"""약관/개인정보 동의 라우터 — /api/terms/*

- GET  /api/terms/active   : 현행 약관 목록(로그인)
- GET  /api/terms/pending  : 미동의 현행 약관 목록(로그인) — 최초 로그인/버전변경 강제동의용
- POST /api/terms/accept   : 동의 기록(로그인) + 감사로그 TERMS_ACCEPT

graceful: 0020 미적용/PG 오류 시 빈 목록·no-op(로그인 흐름 미차단).
"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.services import terms_pg_service as _terms
from backend.services import audit_service as _audit

router = APIRouter()


class AcceptBody(BaseModel):
    version_ids: list[int] = []


@router.get("/active")
def active_terms(user: dict = Depends(get_current_user)):
    return {"terms": _terms.get_active_terms()}


@router.get("/pending")
def pending_terms(user: dict = Depends(get_current_user)):
    return {"pending": _terms.pending_for(user.get("sub", ""))}


@router.post("/accept")
def accept_terms(body: AcceptBody, user: dict = Depends(get_current_user), request: Request = None):
    login_id = user.get("sub", "")
    tenant_id = user.get("tenant_id")
    ua = request.headers.get("user-agent") if request else None
    xff = request.headers.get("x-forwarded-for") if request else None
    ip = (xff.split(",")[0].strip() if xff else (request.client.host if request and request.client else None))
    n = _terms.record_acceptance(login_id, tenant_id, body.version_ids, ip=ip, user_agent=ua)
    _audit.log_event(action="TERMS_ACCEPT", actor_login_id=login_id, tenant_id=tenant_id,
                     target_type="terms", target_id=",".join(str(v) for v in body.version_ids)[:200],
                     ip_address=ip, user_agent=ua,
                     payload={"success": True, "accepted_count": n, "version_ids": body.version_ids})
    return {"ok": True, "accepted": n, "pending": _terms.pending_for(login_id)}
