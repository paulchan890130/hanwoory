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


def assert_seat_within_limit(session, tenant_id: Optional[str],
                             activating_login_id: Optional[str] = None) -> None:
    """좌석 한도 원자 검증 — **열려 있는 트랜잭션 내부에서만** 호출한다.

    tenant 행을 ``FOR UPDATE`` 로 잠가 같은 tenant 의 동시 좌석 조작(activation/restore/
    replace/legacy create)을 직렬화한 뒤, ``activating_login_id`` 를 활성으로 전환했을 때의
    active 사용자 수가 ``seat_limit`` 을 넘으면 ``SEAT_LIMIT`` 로 거부(호출측 롤백)한다.

    - ``activating_login_id`` 가 이미 active 면 추가 좌석을 세지 않는다(멱등 — 재실행 안전).
    - ``activating_login_id`` 가 None 이면 현재 active 수만 한도와 비교(교체 후 검증 등).
    - tenant 행이 없으면(레거시/미프로비저닝) 검증을 건너뛴다.
    """
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser

    if not tenant_id:
        return
    t = session.scalar(
        select(Tenant).where(Tenant.tenant_id == tenant_id).with_for_update())
    if t is None:
        return
    seat_limit = int(getattr(t, "seat_limit", 2) or 2)
    active_cnt = session.scalar(select(func.count()).select_from(AccountUser).where(
        AccountUser.tenant_id == tenant_id, AccountUser.is_active.is_(True))) or 0
    projected = int(active_cnt)
    if activating_login_id:
        already = session.scalar(select(AccountUser.is_active).where(
            AccountUser.login_id == activating_login_id))
        if not already:
            projected += 1
    if projected > seat_limit:
        raise LifecycleError(
            "SEAT_LIMIT",
            f"좌석 한도({seat_limit})를 초과합니다. 좌석을 늘리거나 기존 계정을 정지/교체하세요.")


def reserved_seat_count(session, tenant_id: str) -> int:
    """좌석을 **예약**하는 계정 수 = 활성(is_active) OR account_status in (active, invited).

    - 활성 계정: 좌석 소비.
    - invited 계정: 활성화되면 좌석을 소비 → 예약으로 계산(과다 초대 방지).
    - replaced/suspended/legacy-disabled: 제외.
    - is_active↔account_status 불일치(예: status=active·비활성)는 위 OR 조건상 예약으로 계산 → fail-closed.
    """
    from backend.db.models.user import AccountUser
    from sqlalchemy import or_

    if not tenant_id:
        return 0
    return int(session.scalar(
        select(func.count()).select_from(AccountUser).where(
            AccountUser.tenant_id == tenant_id,
            or_(AccountUser.is_active.is_(True),
                AccountUser.account_status.in_(("active", "invited"))),
        )) or 0)


def assert_invitation_capacity(session, tenant_id: Optional[str],
                               additional_invites: int = 1) -> None:
    """초대 좌석 예약 원자 검증 — **열린 트랜잭션 내부에서만** 호출한다.

    tenant 행을 ``FOR UPDATE`` 로 잠가 동시 초대/활성화를 직렬화한 뒤, 예약 좌석 수
    (reserved_seat_count)에 ``additional_invites`` 를 더한 값이 ``seat_limit`` 을 넘으면
    ``SEAT_LIMIT`` 로 거부한다(호출측 롤백). 이미 존재하는(플러시된) 초대 계정은 reserved 에
    이미 포함되므로 그 경우 ``additional_invites=0`` 으로 호출한다. tenant 행이 없으면 skip.
    """
    from backend.db.models.tenant import Tenant

    if not tenant_id:
        return
    t = session.scalar(
        select(Tenant).where(Tenant.tenant_id == tenant_id).with_for_update())
    if t is None:
        return
    seat_limit = int(getattr(t, "seat_limit", 2) or 2)
    reserved = reserved_seat_count(session, tenant_id)
    if reserved + int(additional_invites or 0) > seat_limit:
        raise LifecycleError(
            "SEAT_LIMIT",
            f"좌석 한도({seat_limit})를 초과합니다(예약 {reserved} + 신규 {additional_invites}). "
            f"좌석을 늘리거나 기존 계정을 정지/교체하세요.")


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
def _revoke_unused_tokens(session, login_id: str) -> None:
    """열린 트랜잭션 내부에서 해당 계정의 **미사용 activation token 전부** used_at 처리.

    정지/교체 시 잔존 초대 링크로 계정이 다시 활성화되는 우회를 막는다.
    """
    from backend.db.models.activation_token import ActivationToken
    from sqlalchemy import update
    session.execute(
        update(ActivationToken)
        .where(ActivationToken.login_id == login_id, ActivationToken.used_at.is_(None))
        .values(used_at=_now())
    )


def suspend_user(login_id: str, actor: str) -> dict:
    from backend.auth import is_master_login
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services import account_state as _st

    if is_master_login(login_id):
        raise LifecycleError("MASTER_PROTECTED", "마스터 계정은 정지할 수 없습니다.")
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(
            select(AccountUser).where(AccountUser.login_id == login_id).with_for_update())
        if u is None:
            raise LifecycleError("NOT_FOUND", "계정을 찾을 수 없습니다.")
        tenant_id = u.tenant_id
        # 표준 잠금 순서 user → tenant → token: tenant 도 FOR UPDATE 로 잠근 뒤 token 을 폐기한다.
        t = session.scalar(
            select(Tenant).where(Tenant.tenant_id == tenant_id).with_for_update()) if tenant_id else None
        # 정지는 active 계정 전용(공통 해석 소스). invited/replaced/suspended/disabled 및
        # 상태 불일치는 거부 → 여기서 실패하면 account_status/is_active/토큰/세션 무변경.
        block = _st.suspend_block_reason(u, t)
        if block is not None:
            raise LifecycleError(block[0], block[1])
        u.is_active = False
        u.account_status = "suspended"
        # 미사용 초대 토큰 폐기 — 같은 트랜잭션(정지 우회 방지), tenant 잠금 이후에만.
        _revoke_unused_tokens(session, login_id)
        session.commit()
    _revoke_sessions(login_id, reason="account_suspended")
    _audit("user_suspended", actor, login_id, tenant_id)
    return {"login_id": login_id, "account_status": "suspended"}


def restore_user(login_id: str, actor: str) -> dict:
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services import account_state as _st

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(
            select(AccountUser).where(AccountUser.login_id == login_id).with_for_update())
        if u is None:
            raise LifecycleError("NOT_FOUND", "계정을 찾을 수 없습니다.")
        tenant_id = u.tenant_id
        # tenant 를 FOR UPDATE 로 먼저 잠근 뒤 상태를 검사한다 — 동시 suspend_tenant 와의
        # 경쟁을 직렬화(잠금 획득 후 재검사)해 "정지된 사무소에서 뒤늦게 복구 성공"을 차단.
        t = session.scalar(
            select(Tenant).where(Tenant.tenant_id == tenant_id).with_for_update()) if tenant_id else None
        # 복구는 suspended 계정 전용(공통 해석 소스). invited/replaced/active/disabled 및
        # 정지·종료 tenant 는 거부 → 사용자만 임의로 활성화되지 않는다.
        block = _st.restore_block_reason(u, t)
        if block is not None:
            raise LifecycleError(block[0], block[1])
        # 복구는 좌석을 1개 소비 → 트랜잭션 내 원자 검증(초과 시 롤백).
        assert_seat_within_limit(session, tenant_id, activating_login_id=login_id)
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
    from backend.services import account_state as _st

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # tenant 를 FOR UPDATE 로 잠근 뒤 상태검사·정지·토큰폐기를 같은 트랜잭션에서 수행한다.
        t = session.scalar(
            select(Tenant).where(Tenant.tenant_id == tenant_id).with_for_update())
        if t is None:
            raise LifecycleError("NOT_FOUND", "테넌트를 찾을 수 없습니다.")
        block = _st.suspend_tenant_block_reason(t)  # terminated → 거부(종착 상태)
        if block is not None:
            raise LifecycleError(block[0], block[1])
        logins = list(session.scalars(
            select(AccountUser.login_id).where(AccountUser.tenant_id == tenant_id)).all())
        # P0 보호: 마스터/시스템 관리자 계정이 연결된 사업장은 정지 불가. 변이 이전에 차단하므로
        # tenant/users/tokens/sessions 모두 무변경(트랜잭션 미commit 롤백). audit 는 아래에서 별도 기록.
        from backend.auth import is_system_admin as _is_sysadmin
        if any(_is_sysadmin(str(l or "")) for l in logins):
            _audit("tenant_suspend_blocked", actor, None, tenant_id,
                   {"reason": "master_tenant_protected", "user_count": len(logins)})
            raise LifecycleError(
                "MASTER_TENANT_PROTECTED",
                "시스템 관리자 계정이 연결된 보호 사업장입니다. 시스템 관리자 연결을 안전하게 "
                "분리하기 전에는 정지할 수 없습니다.")
        t.service_status = "suspended"
        t.is_active = False
        # 소속 사용자 전원의 미사용 초대 토큰 폐기 — 같은 트랜잭션(정지 우회 방지).
        from backend.db.models.activation_token import ActivationToken
        from sqlalchemy import update
        session.execute(
            update(ActivationToken)
            .where(ActivationToken.tenant_id == tenant_id, ActivationToken.used_at.is_(None))
            .values(used_at=_now())
        )
        session.commit()
    # 방어선: tenant-wide 세션 revoke 에서도 시스템 관리자는 제외(정상 경로엔 애초에 없음).
    from backend.auth import is_system_admin as _is_sysadmin2
    for lid in logins:
        if _is_sysadmin2(str(lid or "")):
            continue
        _revoke_sessions(lid, reason="tenant_suspended")
    _audit("tenant_suspended", actor, None, tenant_id, {"user_count": len(logins)})
    return {"tenant_id": tenant_id, "service_status": "suspended"}


def restore_tenant(tenant_id: str, actor: str) -> dict:
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker
    from backend.services import account_state as _st

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        t = session.scalar(
            select(Tenant).where(Tenant.tenant_id == tenant_id).with_for_update())
        if t is None:
            raise LifecycleError("NOT_FOUND", "테넌트를 찾을 수 없습니다.")
        # 복구는 suspended 사무소 전용 — active(멱등 아님·거부)/terminated(종착)/기타 상태 거부.
        block = _st.restore_tenant_block_reason(t)
        if block is not None:
            raise LifecycleError(block[0], block[1])
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
    from backend.services import account_state as _st

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
        # 표준 잠금 순서 user → tenant → token: 기존 계정 잠금 → tenant 잠금·상태검사 → (그 뒤) token 폐기.
        old = session.scalar(
            select(AccountUser).where(AccountUser.login_id == old_login_id).with_for_update())
        if old is None:
            raise LifecycleError("NOT_FOUND", "교체 대상 계정을 찾을 수 없습니다.")
        if old.account_status == "replaced":
            raise LifecycleError("ALREADY_REPLACED", "이미 교체된 계정입니다.")
        tenant_id = old.tenant_id
        # tenant FOR UPDATE(token 폐기 이전) — 정지/종료 사무소는 fail-closed 로 교체 거부.
        t = session.scalar(
            select(Tenant).where(Tenant.tenant_id == tenant_id).with_for_update()) if tenant_id else None
        block = _st.replace_tenant_block_reason(t)
        if block is not None:
            raise LifecycleError(block[0], block[1])
        if session.scalar(select(AccountUser.id).where(AccountUser.login_id == new_email)) is not None:
            raise LifecycleError("EMAIL_IN_USE", "이미 사용 중인 이메일입니다.")

        # 기존 역할을 기본 제안값으로 사용(관리자 override 가능).
        default_role = new_role or ("office_admin" if old.is_admin else "office_staff")
        is_admin = (default_role == "office_admin")

        now = _now()
        # 기존 사용자 replaced 처리(삭제 아님, 이름/이메일 보존).
        old.is_active = False
        old.account_status = "replaced"
        # 기존 계정의 미사용 초대 토큰 폐기 — 신규 계정 토큰만 유효(교체 우회 방지). tenant 잠금 이후.
        _revoke_unused_tokens(session, old_login_id)

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

        # active seat 원자 검증 — 신규 계정은 invited(비활성)이라 좌석을 소비하지 않지만,
        # tenant 를 잠가 동시 좌석 조작을 직렬화하고 현재 active 수가 한도 내인지 확인한다.
        assert_seat_within_limit(session, tenant_id, activating_login_id=None)

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


# ── 요약 조회 (읽기전용, 안전필드만 — hash/token/평문 미포함) ──────────────────
def tenant_account_summary(tenant_id: str) -> Optional[dict]:
    """tenant + 소속 계정 요약. 비밀번호 hash/activation token/PII 원문은 포함하지 않는다."""
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

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
            .order_by(AccountUser.is_admin.desc(), AccountUser.id.asc())
        ).all()
        accounts = [{
            "login_id": u.login_id,
            "name": u.contact_name or "",
            "role": "office_admin" if u.is_admin else "office_staff",
            "is_admin": bool(u.is_admin),
            "account_status": getattr(u, "account_status", None) or ("active" if u.is_active else "disabled"),
            "is_active": bool(u.is_active),
            "invited_at": u.invited_at.isoformat() if getattr(u, "invited_at", None) else None,
            "activated_at": u.activated_at.isoformat() if getattr(u, "activated_at", None) else None,
        } for u in rows]
        active_cnt = sum(1 for a in accounts if a["is_active"])
        return {
            "tenant_id": t.tenant_id,
            "office_name": t.office_name or "",
            "service_status": getattr(t, "service_status", None) or ("active" if t.is_active else "pending_activation"),
            "service_tier": getattr(t, "service_tier", None) or "managed_basic",
            "seat_limit": int(getattr(t, "seat_limit", 2) or 2),
            "active_count": active_cnt,
            "accounts": accounts,
        }


# ── office_admin 스코프 검증 — 대상이 같은 tenant 의 서브계정(office_staff)인지 확인 ──
def _assert_manageable_sub_locked(session, tenant_id: str, actor_login: str,
                                  target_login: str):
    """**열린 session 내부**에서 대상 서브계정을 ``FOR UPDATE`` 로 잠그고 스코프를 검증한 뒤
    그 행을 반환한다. 검증과 후속 조작을 **하나의 트랜잭션**으로 묶어 TOCTOU 를 제거한다.

    - 대상이 같은 tenant 소속이어야 함(크로스테넌트 차단)
    - 대상이 자기 자신이면 불가(주계정 자기 정지/교체 금지)
    - 대상이 office_staff(is_admin=false) 여야 함(다른 관리자/주계정 관리 불가)
    - 마스터 대상 불가
    """
    from backend.auth import is_master_login
    from backend.db.models.user import AccountUser

    if target_login == actor_login:
        raise LifecycleError("SELF_FORBIDDEN", "본인 계정은 이 화면에서 관리할 수 없습니다.")
    if is_master_login(target_login):
        raise LifecycleError("MASTER_PROTECTED", "관리할 수 없는 계정입니다.")
    u = session.scalar(
        select(AccountUser).where(AccountUser.login_id == target_login).with_for_update())
    if u is None:
        raise LifecycleError("NOT_FOUND", "계정을 찾을 수 없습니다.")
    if (u.tenant_id or "") != (tenant_id or ""):
        raise LifecycleError("CROSS_TENANT", "다른 사무소의 계정은 관리할 수 없습니다.")
    if bool(u.is_admin):
        raise LifecycleError("NOT_SUB_ACCOUNT", "서브계정(직원)만 관리할 수 있습니다.")
    return u


def office_suspend_sub(tenant_id: str, actor_login: str, target_login: str) -> dict:
    """스코프 검증 + 상태 전이 검증 + 정지를 **단일 트랜잭션**으로 수행."""
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker
    from backend.services import account_state as _st

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = _assert_manageable_sub_locked(session, tenant_id, actor_login, target_login)
        # 표준 잠금 순서 user → tenant → token(user 는 위에서 이미 FOR UPDATE).
        t = session.scalar(
            select(Tenant).where(Tenant.tenant_id == tenant_id).with_for_update()) if tenant_id else None
        # 정지는 active 전용(시스템 관리자 경로와 동일 규칙) — replaced/invited/suspended 우회 차단.
        block = _st.suspend_block_reason(u, t)
        if block is not None:
            raise LifecycleError(block[0], block[1])
        u.is_active = False
        u.account_status = "suspended"
        # 미사용 초대 토큰 폐기 — 같은 트랜잭션(정지 우회 방지), tenant 잠금 이후에만.
        _revoke_unused_tokens(session, target_login)
        session.commit()
    _revoke_sessions(target_login, reason="account_suspended")
    _audit("user_suspended", actor_login, target_login, tenant_id)
    return {"login_id": target_login, "account_status": "suspended"}


def office_restore_sub(tenant_id: str, actor_login: str, target_login: str) -> dict:
    """스코프 검증 + 상태 전이 검증 + 좌석 원자 검증 + 복구를 **단일 트랜잭션**으로 수행."""
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker
    from backend.services import account_state as _st

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = _assert_manageable_sub_locked(session, tenant_id, actor_login, target_login)
        # tenant FOR UPDATE 로 잠근 뒤 상태검사 — 동시 suspend_tenant 경쟁 직렬화.
        t = session.scalar(
            select(Tenant).where(Tenant.tenant_id == tenant_id).with_for_update()) if tenant_id else None
        # 복구는 suspended 전용(시스템 관리자 경로와 동일 규칙).
        block = _st.restore_block_reason(u, t)
        if block is not None:
            raise LifecycleError(block[0], block[1])
        assert_seat_within_limit(session, tenant_id, activating_login_id=target_login)
        u.is_active = True
        u.account_status = "active"
        session.commit()
    _audit("user_restored", actor_login, target_login, tenant_id)
    return {"login_id": target_login, "account_status": "active"}


def office_reissue_sub(tenant_id: str, actor_login: str, target_login: str) -> dict:
    """스코프 검증 + 상태 전이 검증 + 활성화 토큰 재발급을 **단일 트랜잭션**으로 수행.

    라우터가 private ``_assert_manageable_sub`` 를 직접 호출하던 우회를 제거하고,
    재발급 허용 상태(invited + tenant pending/active)는 시스템 관리자 경로와 같은 소스를 쓴다.
    """
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker
    from backend.services import activation_pg_service as _act
    from backend.services import account_state as _st

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = _assert_manageable_sub_locked(session, tenant_id, actor_login, target_login)
        # tenant FOR UPDATE 로 잠근 뒤 상태검사 — 동시 suspend_tenant 경쟁 직렬화.
        t = session.scalar(
            select(Tenant).where(Tenant.tenant_id == tenant_id).with_for_update()) if tenant_id else None
        block = _st.reissue_block_reason(u, t)
        if block is not None:
            raise LifecycleError(block[0], block[1])
        # 기존 미사용 토큰 폐기 후 새 토큰 발급 — 같은 트랜잭션.
        _revoke_unused_tokens(session, target_login)
        raw = _act.issue_activation_token(session, target_login, u.tenant_id)
        session.commit()
    _audit("activation_reissued", actor_login, target_login, tenant_id)
    return {"login_id": target_login, "activation_token": raw}


def office_replace_sub(tenant_id: str, actor_login: str, old_login: str,
                       new_name: str, new_email: str) -> dict:
    """스코프 검증 + 교체를 **단일 트랜잭션**으로 수행(서브계정 역할 유지 — 주계정 승격 금지)."""
    import re
    import secrets
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services.accounts_service import hash_password
    from backend.services import activation_pg_service as _act
    from backend.services import account_state as _st

    new_email = (new_email or "").strip().lower()
    new_name = (new_name or "").strip()
    if not new_name or not new_email:
        raise LifecycleError("MISSING_USER", "신규 사용자 이름과 이메일이 필요합니다.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", new_email):
        raise LifecycleError("BAD_EMAIL", "이메일 형식이 올바르지 않습니다.")

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # 표준 잠금 순서 user → tenant → token(user 는 _assert_manageable_sub_locked 에서 FOR UPDATE).
        old = _assert_manageable_sub_locked(session, tenant_id, actor_login, old_login)
        if old.account_status == "replaced":
            raise LifecycleError("ALREADY_REPLACED", "이미 교체된 계정입니다.")
        # tenant FOR UPDATE(token 폐기 이전) — 정지/종료 사무소는 fail-closed 로 교체 거부.
        t = session.scalar(
            select(Tenant).where(Tenant.tenant_id == tenant_id).with_for_update()) if tenant_id else None
        block = _st.replace_tenant_block_reason(t)
        if block is not None:
            raise LifecycleError(block[0], block[1])
        if session.scalar(select(AccountUser.id).where(AccountUser.login_id == new_email)) is not None:
            raise LifecycleError("EMAIL_IN_USE", "이미 사용 중인 이메일입니다.")

        now = _now()
        old.is_active = False
        old.account_status = "replaced"
        # 기존 계정의 미사용 초대 토큰 폐기 — 신규 계정 토큰만 유효(교체 우회 방지). tenant 잠금 이후.
        _revoke_unused_tokens(session, old_login)

        new_row = AccountUser(
            login_id=new_email,
            tenant_id=tenant_id,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            contact_name=new_name,
            is_admin=False,           # 서브계정 교체는 항상 office_staff 유지
            is_active=False,
        )
        new_row.role = "user"
        new_row.account_status = "invited"
        new_row.invited_at = now
        new_row.replaces_user_id = old.id
        session.add(new_row)
        session.flush()
        old.replaced_by_user_id = new_row.id

        assert_seat_within_limit(session, tenant_id, activating_login_id=None)
        raw = _act.issue_activation_token(session, new_email, tenant_id)
        session.commit()

    _revoke_sessions(old_login, reason="account_replaced")
    _audit("user_replaced", actor_login, old_login, tenant_id,
           {"new_login_id": new_email, "role": "office_staff"})
    _audit("user_invited", actor_login, new_email, tenant_id,
           {"role": "office_staff", "replaces": old_login})
    return {
        "old_login_id": old_login,
        "new_login_id": new_email,
        "role": "office_staff",
        "activation_token": raw,
    }
