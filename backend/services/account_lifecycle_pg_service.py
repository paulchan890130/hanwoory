"""계정/테넌트 lifecycle — 정지·복구·교체 (승인형 SaaS).

세션 즉시 무효화는 기존 session_pg_service.revoke_active_sessions 를 재사용한다.
정지의 1차 방어선은 users.is_active=False(get_current_user 가 매 요청 차단), 2차는 세션 revoke.
tenant 정지는 tenants.service_status='suspended' + 전체 사용자 세션 revoke 이며, 로그인 차단은
auth 경로의 tenant service_status 검사(approved_saas on 일 때)로 이뤄진다.

**업무 데이터는 절대 삭제하지 않는다.** 교체는 기존 사용자 행을 보존하고 새 행을 추가하며,
과거 created_by/updated_by 는 기존 사용자 id 를 유지한다.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func


class LifecycleError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _revoke_sessions(login_id: str, reason: str) -> None:
    try:
        from backend.services.session_pg_service import revoke_active_sessions
        revoke_active_sessions(login_id, reason=reason, only_non_kiosk=False)
    except Exception:
        pass  # 세션 저장소 미구성/오류는 정지 자체를 막지 않음(is_active 가 1차 차단)


def _audit(action: str, actor: Optional[str], target_login: Optional[str],
           tenant_id: Optional[str], payload: Optional[dict] = None) -> None:
    try:
        from backend.services import audit_service
        audit_service.log_event(action=action, actor_login_id=actor, tenant_id=tenant_id,
                                target_type="user", target_id=target_login, payload=payload)
    except Exception:
        pass


# ── 사용자 정지/복구 ─────────────────────────────────────────────────────────
def suspend_user(login_id: str, actor: str) -> dict:
    from backend.auth import is_master_login
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    if is_master_login(login_id):
        raise LifecycleError("MASTER_PROTECTED", "마스터 계정은 정지할 수 없습니다.")
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            raise LifecycleError("NOT_FOUND", "계정을 찾을 수 없습니다.")
        tenant_id = u.tenant_id
        u.is_active = False
        u.account_status = "suspended"
        session.commit()
    _revoke_sessions(login_id, reason="account_suspended")
    _audit("user_suspended", actor, login_id, tenant_id)
    return {"login_id": login_id, "account_status": "suspended"}


def restore_user(login_id: str, actor: str) -> dict:
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            raise LifecycleError("NOT_FOUND", "계정을 찾을 수 없습니다.")
        if u.account_status == "replaced":
            raise LifecycleError("REPLACED", "교체된 계정은 복구할 수 없습니다.")
        tenant_id = u.tenant_id
        u.is_active = True
        u.account_status = "active"
        session.commit()
    _audit("user_restored", actor, login_id, tenant_id)
    return {"login_id": login_id, "account_status": "active"}


# ── 테넌트 정지/복구 ─────────────────────────────────────────────────────────
def suspend_tenant(tenant_id: str, actor: str) -> dict:
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        if t is None:
            raise LifecycleError("NOT_FOUND", "테넌트를 찾을 수 없습니다.")
        t.service_status = "suspended"
        t.is_active = False
        logins = list(session.scalars(
            select(AccountUser.login_id).where(AccountUser.tenant_id == tenant_id)).all())
        session.commit()
    for lid in logins:
        _revoke_sessions(lid, reason="tenant_suspended")
    _audit("tenant_suspended", actor, None, tenant_id, {"user_count": len(logins)})
    return {"tenant_id": tenant_id, "service_status": "suspended"}


def restore_tenant(tenant_id: str, actor: str) -> dict:
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        if t is None:
            raise LifecycleError("NOT_FOUND", "테넌트를 찾을 수 없습니다.")
        t.service_status = "active"
        t.is_active = True
        session.commit()
    _audit("tenant_restored", actor, None, tenant_id)
    return {"tenant_id": tenant_id, "service_status": "active"}


# ── 계정 교체 ────────────────────────────────────────────────────────────────
def replace_user(old_login_id: str, new_name: str, new_email: str, actor: str,
                 new_role: Optional[str] = None) -> dict:
    """퇴사자 계정을 replaced 처리하고 신규 실명 계정을 생성(초대). 원자적.

    - 기존 사용자 행/이름/이메일은 **덮어쓰지 않는다** → 과거 created_by/updated_by 보존.
    - active seat 수가 seat_limit 을 넘지 않도록 트랜잭션 내에서 검증한다.
    - 신규 계정은 is_active=False(invited) → activation 완료 시 활성화. 원문 토큰 반환.
    """
    import re
    from backend.auth import is_master_login
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services.accounts_service import hash_password
    from backend.services import activation_pg_service as _act

    new_email = (new_email or "").strip().lower()
    new_name = (new_name or "").strip()
    if not new_name or not new_email:
        raise LifecycleError("MISSING_USER", "신규 사용자 이름과 이메일이 필요합니다.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", new_email):
        raise LifecycleError("BAD_EMAIL", "이메일 형식이 올바르지 않습니다.")
    if is_master_login(old_login_id):
        raise LifecycleError("MASTER_PROTECTED", "마스터 계정은 교체할 수 없습니다.")

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        old = session.scalar(
            select(AccountUser).where(AccountUser.login_id == old_login_id).with_for_update())
        if old is None:
            raise LifecycleError("NOT_FOUND", "교체 대상 계정을 찾을 수 없습니다.")
        if old.account_status == "replaced":
            raise LifecycleError("ALREADY_REPLACED", "이미 교체된 계정입니다.")
        tenant_id = old.tenant_id
        if session.scalar(select(AccountUser.id).where(AccountUser.login_id == new_email)) is not None:
            raise LifecycleError("EMAIL_IN_USE", "이미 사용 중인 이메일입니다.")

        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        seat_limit = int(getattr(t, "seat_limit", 2) or 2) if t is not None else 2

        # 기존 역할을 기본 제안값으로 사용(관리자 override 가능).
        default_role = new_role or ("office_admin" if old.is_admin else "office_staff")
        is_admin = (default_role == "office_admin")

        now = _now()
        # 기존 사용자 replaced 처리(삭제 아님, 이름/이메일 보존).
        old.is_active = False
        old.account_status = "replaced"

        new_row = AccountUser(
            login_id=new_email,
            tenant_id=tenant_id,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            contact_name=new_name,
            is_admin=is_admin,
            is_active=False,
        )
        new_row.role = "admin" if is_admin else "user"
        new_row.account_status = "invited"
        new_row.invited_at = now
        new_row.replaces_user_id = old.id
        session.add(new_row)
        session.flush()
        old.replaced_by_user_id = new_row.id

        # active seat 검증 — 교체 후 tenant 의 active 사용자 수가 seat_limit 을 넘지 않아야 한다.
        active_cnt = session.scalar(select(func.count()).select_from(AccountUser).where(
            AccountUser.tenant_id == tenant_id, AccountUser.is_active.is_(True)))
        if active_cnt is not None and active_cnt > seat_limit:
            raise LifecycleError("SEAT_LIMIT", "좌석 수를 초과합니다.")  # 롤백

        raw = _act.issue_activation_token(session, new_email, tenant_id)
        session.commit()

    _revoke_sessions(old_login_id, reason="account_replaced")
    _audit("user_replaced", actor, old_login_id, tenant_id,
           {"new_login_id": new_email, "role": default_role})
    _audit("user_invited", actor, new_email, tenant_id, {"role": default_role, "replaces": old_login_id})
    return {
        "old_login_id": old_login_id,
        "new_login_id": new_email,
        "role": default_role,
        "activation_token": raw,
    }
