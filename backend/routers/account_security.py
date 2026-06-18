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

# ── 서버 페이지네이션 공통 ────────────────────────────────────────────────────
# 전체 로딩 금지: 화면 진입 시 최신순 N건만 내려주고, 다음 페이지는 별도 요청한다.
# has_next 는 page_size+1 건을 조회해 초과분 존재 여부로 판정(추가 count 쿼리 불필요).
PAGE_SIZE_DEFAULT = 20        # 관리자 화면 기본
PAGE_SIZE_MAX = 50            # 관리자 화면 상한
# 마이페이지(본인 전용) — 화면/서버 부담 축소: 알림 5건, 로그인 이력 10건, 상한 10.
MY_NOTIF_PAGE_SIZE = 5
MY_EVENTS_PAGE_SIZE = 10
MY_PAGE_SIZE_MAX = 10


def _paginate(fetch, page: int, page_size: int):
    """fetch(limit, offset) -> rows(list). page_size+1 조회 후 has_next 판정·trim."""
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), PAGE_SIZE_MAX))
    offset = (page - 1) * page_size
    rows = fetch(page_size + 1, offset) or []
    has_next = len(rows) > page_size
    return rows[:page_size], page, page_size, has_next


class UnblockBody(BaseModel):
    login_id: str


# ── 관리자 ────────────────────────────────────────────────────────────────────
@router.get("/admin/security/login-events")
def admin_login_events(login_id: str = Query(...),
                       page: int = Query(1, ge=1),
                       page_size: int = Query(PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
                       user: dict = Depends(require_admin)):
    rows, p, ps, has_next = _paginate(
        lambda lim, off: _sec.recent_login_events(login_id, limit=lim, offset=off), page, page_size)
    return {"events": rows, "status": _sec.security_status(login_id),
            "page": p, "page_size": ps, "has_next": has_next}


@router.get("/admin/security/recent")
def admin_recent_events(page: int = Query(1, ge=1),
                        page_size: int = Query(PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
                        only_suspicious: bool = Query(False),
                        user: dict = Depends(require_admin)):
    """검색 없이 기본 노출용 — 전 계정 최근 로그인/보안 이벤트(최신순, 페이지 단위, 원문 PII 미반환)."""
    rows, p, ps, has_next = _paginate(
        lambda lim, off: _sec.recent_login_events_all(limit=lim, only_suspicious=only_suspicious, offset=off),
        page, page_size)
    return {"events": rows, "page": p, "page_size": ps, "has_next": has_next}


@router.get("/admin/security/blocked")
def admin_blocked_accounts(page: int = Query(1, ge=1),
                           page_size: int = Query(PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
                           user: dict = Depends(require_admin)):
    """보안차단 계정 목록(최신순, 페이지 단위) — 목록에서 바로 해제 가능하도록."""
    rows, p, ps, has_next = _paginate(
        lambda lim, off: _sec.list_blocked_accounts(limit=lim, offset=off), page, page_size)
    return {"blocked": rows, "page": p, "page_size": ps, "has_next": has_next}


@router.get("/admin/security/status")
def admin_security_status(login_id: str = Query(...), user: dict = Depends(require_admin)):
    return _sec.security_status(login_id)


@router.post("/admin/security/unblock")
def admin_security_unblock(body: UnblockBody, user: dict = Depends(require_admin)):
    ok = _sec.unblock_account(body.login_id, actor_login_id=user.get("login_id"))
    if not ok:
        raise HTTPException(status_code=503, detail="보안 해제를 처리할 수 없습니다(보안 기능 미구성).")
    return {"ok": True, "status": _sec.security_status(body.login_id)}


@router.get("/admin/security/notifications")
def admin_security_notifications(page: int = Query(1, ge=1),
                                 page_size: int = Query(PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
                                 only_unread: bool = Query(False),
                                 user: dict = Depends(require_admin)):
    rows, p, ps, has_next = _paginate(
        lambda lim, off: _sec.notifications_for(user.get("login_id", ""), only_unread=only_unread, limit=lim, offset=off),
        page, page_size)
    return {"notifications": rows, "page": p, "page_size": ps, "has_next": has_next}


# ── 사용자 본인 ───────────────────────────────────────────────────────────────
@router.get("/my/login-events")
def my_login_events(page: int = Query(1, ge=1),
                    page_size: int = Query(MY_EVENTS_PAGE_SIZE, ge=1, le=MY_PAGE_SIZE_MAX),
                    user: dict = Depends(get_current_user)):
    # 본인 계정만: login_id 는 항상 토큰(current_user)에서 강제 — 클라이언트 입력 불신.
    lid = user.get("login_id", "")
    rows, p, ps, has_next = _paginate(
        lambda lim, off: _sec.recent_login_events(lid, limit=lim, offset=off), page, page_size)
    return {"events": rows, "status": _sec.security_status(lid),
            "page": p, "page_size": ps, "has_next": has_next}


@router.get("/my/security-notifications")
def my_security_notifications(page: int = Query(1, ge=1),
                              page_size: int = Query(MY_NOTIF_PAGE_SIZE, ge=1, le=MY_PAGE_SIZE_MAX),
                              only_unread: bool = Query(False),
                              user: dict = Depends(get_current_user)):
    # 마이페이지는 **본인 계정 기준**: recipient_role="user" 만 노출한다.
    # 관리자에게 발송된 타계정 보안 알림(recipient_role="admin")은 여기서 제외되고
    # 관리자 > 로그인보안 화면(/admin/security/notifications)에서만 보인다.
    lid = user.get("login_id", "")
    rows, p, ps, has_next = _paginate(
        lambda lim, off: _sec.notifications_for(lid, only_unread=only_unread,
                                                recipient_role="user", limit=lim, offset=off),
        page, page_size)
    return {"notifications": rows, "page": p, "page_size": ps, "has_next": has_next}


@router.post("/my/security-notifications/{notif_id}/read")
def my_mark_read(notif_id: int, user: dict = Depends(get_current_user)):
    ok = _sec.mark_notification_read(notif_id, user.get("login_id", ""))
    return {"ok": ok}
