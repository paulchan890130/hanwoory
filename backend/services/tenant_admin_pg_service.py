"""사업장(tenant) 관리 — 시스템 관리자 전용: 연결현황 / 사용자 없는 사업장 /
기존 tenant 에 새 관리자 발급 / 계정 연결 변경(relink).

원칙:
- 고객·업무·분류·업무참고 데이터는 **AccountUser.tenant_id → tenant** 를 통해 접근한다.
  이 서비스는 그 데이터의 ``tenant_id`` 를 **절대 변경하지 않는다**(사업장 간 데이터 이전/병합 아님).
- 계정 연결 변경(relink)은 **계정이 접근하는 사업장만** 바꾼다. 데이터는 이동하지 않는다.
- 모든 변경은 시스템 관리자 전용 + preview/confirm + 단일 트랜잭션.
- 잠금 순서 표준: user → tenant(들, tenant_id 정렬) → token.
"""
from __future__ import annotations

import re
import secrets
from typing import Optional

from sqlalchemy import func, select


class TenantAdminError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _tenant_status(t) -> str:
    st = (getattr(t, "service_status", None) or "").strip().lower()
    if st in ("pending_activation", "active", "suspended", "terminated"):
        return st
    return "active" if bool(getattr(t, "is_active", False)) else "pending_activation"


# ── 연결 현황 요약 ───────────────────────────────────────────────────────────
def tenant_connection_summary(tenant_id: str) -> Optional[dict]:
    """tenant + 계정 요약 + 업무 데이터 건수 + 로그인 사용자 없음/정리 필요 플래그."""
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services import account_state as _st
    from backend.services import tenant_purge_pg_service as _purge

    tid = (tenant_id or "").strip()
    if not tid:
        return None
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tid))
        if t is None:
            return None
        rows = session.scalars(
            select(AccountUser).where(AccountUser.tenant_id == tid)
            .order_by(AccountUser.is_admin.desc(), AccountUser.id.asc())).all()
        accounts = [{
            "login_id": u.login_id,
            "name": u.contact_name or "",
            "is_admin": bool(u.is_admin),
            "account_status": _st.account_status_of(u),
            "is_active": bool(u.is_active),
        } for u in rows]
        # 로그인 가능(활성화 완료·정지 아님) 계정 수 — invited/replaced/disabled/suspended 제외.
        loginable = sum(1 for a in accounts if a["account_status"] == _st.ACCOUNT_ACTIVE and a["is_active"])
        counts = _purge.tenant_data_counts(session, tid)
        return {
            "tenant_id": t.tenant_id,
            "office_name": t.office_name or "",
            "service_status": _tenant_status(t),
            "is_active": bool(getattr(t, "is_active", False)),
            "seat_limit": int(getattr(t, "seat_limit", 2) or 2),
            "total_users": len(accounts),
            "active_users": sum(1 for a in accounts if a["is_active"]),
            "loginable_users": loginable,
            "no_login_users": loginable == 0,
            "needs_cleanup": len(accounts) == 0 or loginable == 0,
            "accounts": accounts,
            "data_counts": counts,
        }


def list_no_user_tenants() -> list[dict]:
    """연결 계정이 0명이거나 로그인 가능한 계정이 0명인 사업장 목록(정리 대상)."""
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    out: list[dict] = []
    with SessionLocal() as session:
        tenant_ids = list(session.scalars(select(Tenant.tenant_id)).all())
    for tid in tenant_ids:
        s = tenant_connection_summary(tid)
        if s and s["needs_cleanup"]:
            out.append(s)
    return out


# ── 기존 tenant 에 새 관리자 발급 ─────────────────────────────────────────────
def issue_admin_account(tenant_id: str, name: str, email: str, actor: str,
                        confirm_tenant_id: Optional[str] = None) -> dict:
    """기존 사업장에 **새 office_admin 초대 계정**을 발급하고 activation 토큰을 반환한다.

    서버 고정: tenant_id=URL tenant, is_admin=true, role=admin, account_status=invited,
    is_active=false. 마지막 계정 오삭제/무관리자 사업장 복구용.
    """
    from backend.auth import is_master_login
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services.accounts_service import hash_password
    from backend.services import activation_pg_service as _act
    from backend.services.account_lifecycle_pg_service import assert_seat_within_limit, LifecycleError

    tid = (tenant_id or "").strip()
    name = (name or "").strip()
    email = (email or "").strip().lower()
    if not tid:
        raise TenantAdminError("BAD_REQUEST", "tenant_id 가 필요합니다.")
    if confirm_tenant_id is not None and (confirm_tenant_id or "").strip() != tid:
        raise TenantAdminError("CONFIRM_MISMATCH", "확인용 사업장 ID가 일치하지 않습니다.")
    if not name or not email:
        raise TenantAdminError("MISSING_USER", "새 관리자 이름과 이메일이 필요합니다.")
    if not _EMAIL_RE.match(email):
        raise TenantAdminError("BAD_EMAIL", "이메일 형식이 올바르지 않습니다.")
    if is_master_login(email):
        raise TenantAdminError("PROTECTED", "예약된 계정 식별자입니다.")

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # user 잠금 대상은 없음(신규) — 표준 순서상 tenant → token.
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tid).with_for_update())
        if t is None:
            raise TenantAdminError("NOT_FOUND", "사업장을 찾을 수 없습니다.")
        if _tenant_status(t) == "terminated":
            raise TenantAdminError("TENANT_TERMINATED", "종료된 사업장에는 계정을 발급할 수 없습니다.")
        if session.scalar(select(AccountUser.id).where(AccountUser.login_id == email)) is not None:
            raise TenantAdminError("EMAIL_IN_USE", "이미 사용 중인 이메일입니다.")

        row = AccountUser(
            login_id=email,
            tenant_id=tid,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            contact_name=name,
            is_admin=True,
            is_active=False,
        )
        row.role = "admin"
        row.account_status = "invited"
        from datetime import datetime, timezone
        row.invited_at = datetime.now(timezone.utc)
        session.add(row)
        session.flush()
        # 좌석 원자 검증(invited 는 좌석 미소비지만 tenant 잠금·한도 확인).
        try:
            assert_seat_within_limit(session, tid, activating_login_id=None)
        except LifecycleError as e:
            if getattr(e, "code", "") == "SEAT_LIMIT":
                raise TenantAdminError("SEAT_LIMIT", e.message)
            raise
        raw = _act.issue_activation_token(session, email, tid)
        session.commit()

    _audit("tenant_admin_issued", actor, email, tid, {"role": "office_admin"})
    return {"login_id": email, "tenant_id": tid, "role": "office_admin",
            "account_status": "invited", "activation_token": raw}


# ── 계정 연결 변경(relink) ────────────────────────────────────────────────────
def _relink_blocking(session, u, source_t, target_t, actor_login: str) -> list[str]:
    from backend.auth import is_master_login
    from backend.db.models.user import AccountUser
    from backend.services import account_state as _st
    from backend.services import tenant_purge_pg_service as _purge

    reasons: list[str] = []
    if u is None:
        return ["대상 계정을 찾을 수 없습니다."]
    if is_master_login(u.login_id):
        reasons.append("마스터 계정은 연결을 변경할 수 없습니다.")
    if actor_login and u.login_id == actor_login:
        reasons.append("본인 계정은 연결을 변경할 수 없습니다.")
    if bool(u.is_active):
        reasons.append("활성(로그인 가능) 계정은 연결을 변경할 수 없습니다. 먼저 정지하세요.")
    if _st.account_status_of(u) == _st.ACCOUNT_REPLACED:
        reasons.append("교체된 계정은 연결을 변경할 수 없습니다.")
    if target_t is None:
        reasons.append("대상 사업장을 찾을 수 없습니다.")
    else:
        if _tenant_status(target_t) == "terminated":
            reasons.append("종료된 사업장으로는 연결할 수 없습니다.")
        seat_limit = int(getattr(target_t, "seat_limit", 2) or 2)
        active_cnt = session.scalar(select(func.count()).select_from(AccountUser).where(
            AccountUser.tenant_id == target_t.tenant_id, AccountUser.is_active.is_(True))) or 0
        # relink 후 invited(비활성)로 들어가므로 즉시 좌석을 소비하진 않지만, 활성 계정 수가
        # 이미 한도 이상이면 활성화 단계에서 막히므로 미리 차단(여유 필요).
        if int(active_cnt) >= seat_limit:
            reasons.append(f"대상 사업장의 좌석 여유가 없습니다(활성 {active_cnt}/{seat_limit}).")
    if source_t is not None:
        other_users = session.scalar(select(func.count()).select_from(AccountUser).where(
            AccountUser.tenant_id == source_t.tenant_id,
            AccountUser.login_id != u.login_id)) or 0
        if int(other_users) > 0:
            reasons.append("원본 사업장에 다른 사용자가 있어 연결을 변경할 수 없습니다.")
        if _purge.tenant_has_business_data(session, source_t.tenant_id):
            reasons.append("원본 사업장에 고객·업무·분류 등 데이터가 남아 있어 연결을 변경할 수 없습니다. "
                           "데이터 처리 방침을 먼저 결정하세요.")
    return reasons


def relink_preview(login_id: str, target_tenant_id: str, actor_login: str = "") -> dict:
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    lid = (login_id or "").strip()
    ttid = (target_tenant_id or "").strip()
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == lid))
        source_t = session.scalar(select(Tenant).where(Tenant.tenant_id == u.tenant_id)) if u else None
        target_t = session.scalar(select(Tenant).where(Tenant.tenant_id == ttid)) if ttid else None
        reasons = _relink_blocking(session, u, source_t, target_t, actor_login)
        return {
            "login_id": lid,
            "source_tenant_id": (u.tenant_id if u else None),
            "source_office_name": (source_t.office_name if source_t else None),
            "target_tenant_id": ttid or None,
            "target_office_name": (target_t.office_name if target_t else None),
            "blocking_reasons": reasons,
            "can_relink": len(reasons) == 0,
        }


def relink_account(login_id: str, target_tenant_id: str, actor_login: str,
                   confirm_login_id: str, confirm_target_tenant_id: str) -> dict:
    """계정의 소속 tenant 를 변경한다(데이터 이동 아님). 단일 트랜잭션·명시적 잠금."""
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services import activation_pg_service as _act
    from backend.services.account_lifecycle_pg_service import _revoke_unused_tokens, _revoke_sessions

    lid = (login_id or "").strip()
    ttid = (target_tenant_id or "").strip()
    if (confirm_login_id or "").strip() != lid:
        raise TenantAdminError("CONFIRM_MISMATCH", "확인용 로그인 ID가 일치하지 않습니다.")
    if (confirm_target_tenant_id or "").strip() != ttid:
        raise TenantAdminError("CONFIRM_MISMATCH", "확인용 대상 사업장 ID가 일치하지 않습니다.")

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # 1) user 잠금.
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == lid).with_for_update())
        if u is None:
            raise TenantAdminError("NOT_FOUND", "대상 계정을 찾을 수 없습니다.")
        source_tid = u.tenant_id
        if source_tid == ttid:
            raise TenantAdminError("SAME_TENANT", "이미 해당 사업장에 소속되어 있습니다.")
        # 2~3) 두 tenant 를 tenant_id 정렬 순서로 FOR UPDATE(데드락 방지).
        for tid_lock in sorted([x for x in {source_tid, ttid} if x]):
            session.scalar(select(Tenant).where(Tenant.tenant_id == tid_lock).with_for_update())
        source_t = session.scalar(select(Tenant).where(Tenant.tenant_id == source_tid)) if source_tid else None
        target_t = session.scalar(select(Tenant).where(Tenant.tenant_id == ttid)) if ttid else None
        # 4) preview 조건 재검증(잠금 이후).
        reasons = _relink_blocking(session, u, source_t, target_t, actor_login)
        if reasons:
            raise TenantAdminError("BLOCKED", " / ".join(reasons))
        # 5~6) 기존 세션·미사용 토큰 폐기.
        _revoke_unused_tokens(session, lid)
        # 7~9) 소속 변경 + invited/비활성.
        u.tenant_id = ttid
        u.is_active = False
        u.account_status = "invited"
        # 10) 새 activation 토큰.
        raw = _act.issue_activation_token(session, lid, ttid)
        session.commit()
    _revoke_sessions(lid, reason="account_relinked")
    _audit("account_relinked", actor_login, lid, ttid,
           {"from_tenant": source_tid, "to_tenant": ttid})
    return {"login_id": lid, "from_tenant_id": source_tid, "to_tenant_id": ttid,
            "account_status": "invited", "activation_token": raw}


def _audit(action: str, actor: Optional[str], target_login: Optional[str],
           tenant_id: Optional[str], payload: Optional[dict] = None) -> None:
    try:
        from backend.services import audit_service
        audit_service.log_event(action=action, actor_login_id=actor, tenant_id=tenant_id,
                                target_type="user", target_id=target_login, payload=payload)
    except Exception:
        pass
