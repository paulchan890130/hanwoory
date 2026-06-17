"""계정공유 의심/로그인 이력/보안 알림 API (베타).

- 관리자: /api/admin/security/* (require_admin) — 계정별 이력·상태·차단해제·관리자 알림
- 사용자 본인: /api/my/* (login 사용자) — 내 이력·알림·읽음처리

graceful: 0021 미적용/PG 오류 시 빈 목록·no-op.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.auth import get_current_user, require_admin
from backend.services import account_security_pg_service as _sec

router = APIRouter()


class UnblockBody(BaseModel):
    login_id: str


# ── 관리자 ────────────────────────────────────────────────────────────────────
@router.get("/admin/security/login-events")
def admin_login_events(login_id: str = Query(...), limit: int = Query(50),
                       user: dict = Depends(require_admin)):
    return {"events": _sec.recent_login_events(login_id, limit=limit),
            "status": _sec.security_status(login_id)}


@router.get("/admin/security/status")
def admin_security_status(login_id: str = Query(...), user: dict = Depends(require_admin)):
    return _sec.security_status(login_id)


@router.post("/admin/security/unblock")
def admin_security_unblock(body: UnblockBody, user: dict = Depends(require_admin)):
    ok = _sec.unblock_account(body.login_id, actor_login_id=user.get("sub"))
    if not ok:
        raise HTTPException(status_code=503, detail="보안 해제를 처리할 수 없습니다(보안 기능 미구성).")
    return {"ok": True, "status": _sec.security_status(body.login_id)}


@router.get("/admin/security/notifications")
def admin_security_notifications(only_unread: bool = Query(False), user: dict = Depends(require_admin)):
    return {"notifications": _sec.notifications_for(user.get("sub", ""), only_unread=only_unread)}


# ── 사용자 본인 ───────────────────────────────────────────────────────────────
@router.get("/my/login-events")
def my_login_events(limit: int = Query(30), user: dict = Depends(get_current_user)):
    return {"events": _sec.recent_login_events(user.get("sub", ""), limit=limit),
            "status": _sec.security_status(user.get("sub", ""))}


@router.get("/my/security-notifications")
def my_security_notifications(only_unread: bool = Query(False), user: dict = Depends(get_current_user)):
    return {"notifications": _sec.notifications_for(user.get("sub", ""), only_unread=only_unread)}


@router.post("/my/security-notifications/{notif_id}/read")
def my_mark_read(notif_id: int, user: dict = Depends(get_current_user)):
    ok = _sec.mark_notification_read(notif_id, user.get("sub", ""))
    return {"ok": ok}
