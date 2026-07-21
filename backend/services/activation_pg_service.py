"""activation 토큰 서비스 — 최초 비밀번호 설정(승인된 계정 활성화).

- 원문 토큰은 저장하지 않는다(sha256 hash 만). 만료 + 1회성으로 보호.
- issue_activation_token 은 승인 트랜잭션 **내부**에서 같은 session 을 받아 원자적으로 기록한다.
- complete_activation 은 토큰을 검증·소비하고 계정을 활성화(비밀번호 설정 + is_active=True)한다.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select

DEFAULT_TTL_HOURS = 72
MIN_PASSWORD_LEN = 6  # 기존 change_password 정책과 동일


class ActivationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def issue_activation_token(session, login_id: str, tenant_id: Optional[str],
                           ttl_hours: int = DEFAULT_TTL_HOURS) -> str:
    """승인/교체 트랜잭션 내부에서 호출 — 같은 session 에 토큰 hash 를 기록하고 **원문**을 반환.

    원문은 호출측(승인 응답)에서 1회 관리자에게 전달하고 저장하지 않는다.
    """
    from backend.db.models.activation_token import ActivationToken

    raw = secrets.token_urlsafe(32)
    session.add(ActivationToken(
        token_hash=_hash(raw),
        login_id=login_id,
        tenant_id=tenant_id,
        purpose="activation",
        expires_at=_now() + timedelta(hours=ttl_hours),
    ))
    return raw


def reissue_activation_token(login_id: str, actor: Optional[str] = None,
                             ttl_hours: int = DEFAULT_TTL_HOURS) -> dict:
    """활성화 토큰 **재발급** — 기존 미사용 토큰을 모두 폐기하고 새 토큰 1개를 발급한다.

    시스템 관리자만 호출(라우터에서 require_system_admin). 대상 계정이 아직 미활성이어야 한다.
    반환 raw 토큰은 1회만 노출(관리자가 대상자에게 전달). 원문/평문은 저장·로그하지 않는다.
    """
    from backend.db.models.activation_token import ActivationToken
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from sqlalchemy import update

    lid = (login_id or "").strip()
    if not lid:
        raise ActivationError("NO_USER", "대상 계정이 없습니다.")
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == lid))
        if u is None:
            raise ActivationError("NO_USER", "계정을 찾을 수 없습니다.")
        if bool(u.is_active):
            raise ActivationError("ALREADY_ACTIVE", "이미 활성화된 계정입니다.")
        # 기존 미사용 토큰 폐기(used_at 설정 → verify/complete 에서 거부됨).
        session.execute(
            update(ActivationToken)
            .where(ActivationToken.login_id == lid, ActivationToken.used_at.is_(None))
            .values(used_at=_now())
        )
        raw = issue_activation_token(session, lid, u.tenant_id, ttl_hours)
        tenant_id = u.tenant_id
        session.commit()
    try:
        from backend.services import audit_service
        audit_service.log_event(action="activation_reissued", actor_login_id=actor,
                                tenant_id=tenant_id, target_type="user", target_id=lid)
    except Exception:
        pass
    return {"login_id": lid, "activation_token": raw}


def verify_activation_token(raw: str) -> Optional[dict]:
    """읽기 전용 검증 — 유효하면 {'login_id','tenant_id'} 아니면 None."""
    from backend.db.models.activation_token import ActivationToken
    from backend.db.session import get_sessionmaker

    if not raw:
        return None
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(select(ActivationToken).where(
            ActivationToken.token_hash == _hash(raw)))
        if row is None or row.used_at is not None:
            return None
        exp = row.expires_at
        if exp is not None and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp is not None and exp < _now():
            return None
        return {"login_id": row.login_id, "tenant_id": row.tenant_id}


def complete_activation(raw: str, new_password: str) -> dict:
    """토큰을 검증·소비하고 계정을 활성화(비밀번호 설정 + is_active=True). 원자적."""
    from backend.db.models.activation_token import ActivationToken
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services.accounts_service import hash_password

    if not raw:
        raise ActivationError("BAD_TOKEN", "유효하지 않은 활성화 링크입니다.")
    if len((new_password or "")) < MIN_PASSWORD_LEN:
        raise ActivationError("WEAK_PASSWORD", f"비밀번호는 {MIN_PASSWORD_LEN}자 이상이어야 합니다.")

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(ActivationToken)
            .where(ActivationToken.token_hash == _hash(raw))
            .with_for_update()
        )
        if row is None or row.used_at is not None:
            raise ActivationError("BAD_TOKEN", "이미 사용되었거나 유효하지 않은 활성화 링크입니다.")
        exp = row.expires_at
        if exp is not None and exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp is not None and exp < _now():
            raise ActivationError("EXPIRED", "활성화 링크가 만료되었습니다. 관리자에게 재발급을 요청하세요.")

        u = session.scalar(select(AccountUser).where(AccountUser.login_id == row.login_id))
        if u is None:
            raise ActivationError("NO_USER", "계정을 찾을 수 없습니다.")

        now = _now()
        u.password_hash = hash_password(new_password)
        u.is_active = True
        u.account_status = "active"
        u.activated_at = now
        row.used_at = now

        # 첫 활성화 시 tenant 를 active 로 승격.
        if row.tenant_id:
            t = session.scalar(select(Tenant).where(Tenant.tenant_id == row.tenant_id))
            if t is not None:
                t.service_status = "active"
        login_id = u.login_id
        tenant_id = u.tenant_id
        session.commit()

    try:
        from backend.services import audit_service
        audit_service.log_event(action="activation_completed", actor_login_id=login_id,
                                tenant_id=tenant_id, target_type="user", target_id=login_id)
    except Exception:
        pass
    return {"login_id": login_id, "tenant_id": tenant_id}
