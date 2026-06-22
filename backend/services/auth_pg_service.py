"""PostgreSQL-side user lookup (local beta — feature-gated).

This module is consulted by the local-beta dev endpoints
(``backend/routers/dev_pg.py``) so the user can verify the PG login path
for the login flow at ``/api/auth/login``.
**It is not wired into the production login route.** As long as that route
keeps using ``backend.services.accounts_service``, existing behavior is
unaffected.

Password verification reuses ``accounts_service.verify_password`` so the
hash format on disk stays identical to what the previous flow already
uses — the same hash works in both places.
"""
from __future__ import annotations

from typing import Optional, TypedDict

from sqlalchemy import select


class PGUserInfo(TypedDict):
    login_id: str
    tenant_id: str
    password_hash: str
    is_admin: bool
    is_active: bool
    contact_name: str


def account_active_status(login_id: str) -> str:
    """login_id 의 현재 활성 상태 — 'active' | 'disabled' | 'missing'.

    매 요청 인증(get_current_user)에서 비활성/삭제된 계정을 **즉시 차단**하기 위한 조회.
    JWT 디코드만으로 통과시키지 않도록, 토큰이 유효해도 이 상태를 다시 확인한다.
    조회 실패(연결 오류 등)는 호출측에서 가용성 우선으로 처리한다(여기선 예외 전파).
    """
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if row is None:
            return "missing"
        return "active" if bool(row.is_active) else "disabled"


def account_auth_status(login_id: str) -> dict:
    """매 요청 인증용 — 상태 + 권한을 1회 조회.

    반환: ``{"status": "active"|"disabled"|"missing", "is_admin": bool, "role": str}``.
    role 컬럼(migration 0024)이 아직 없는 DB 에서도 깨지지 않도록 role 은 별도 가드 조회로
    읽고, 실패하면 is_admin 기반 기본값('admin'/'user')으로 폴백한다(가용성 우선).
    조회 실패(연결 오류 등)는 호출측에서 가용성 우선 처리하도록 예외를 전파한다.
    """
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # 0024 이전에도 존재가 보장된 컬럼만 먼저 조회(role 미포함 → full-row select 회피).
        row = session.execute(
            select(AccountUser.is_active, AccountUser.is_admin)
            .where(AccountUser.login_id == login_id)
        ).first()
        if row is None:
            return {"status": "missing", "is_admin": False, "role": "user"}
        is_active, is_admin = bool(row[0]), bool(row[1])
        role = "admin" if is_admin else "user"
        try:
            r = session.scalar(
                select(AccountUser.role).where(AccountUser.login_id == login_id)
            )
            if r:
                role = str(r)
        except Exception:
            # role 컬럼 미적용(0024 전) → is_admin 기반 기본값 유지. 세션은 곧 닫혀 안전.
            pass
        return {
            "status": "active" if is_active else "disabled",
            "is_admin": is_admin,
            "role": role,
        }


def find_user_pg(login_id: str) -> Optional[PGUserInfo]:
    """Look up one user by ``login_id``. Returns ``None`` if not found.

    Raises whatever SQLAlchemy raises on connection failure — callers
    (the dev endpoints) catch and surface as HTTP 503.
    """
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if row is None:
            return None
        return PGUserInfo(
            login_id=row.login_id,
            tenant_id=row.tenant_id,
            password_hash=row.password_hash,
            is_admin=bool(row.is_admin),
            is_active=bool(row.is_active),
            contact_name=row.contact_name or "",
        )


def find_account_by_tenant_pg(tenant_id: str) -> Optional[dict]:
    """tenant_id 로 행정사/사무소 계정 정보를 Accounts-시트와 동일한 키 형태로 반환.

    문서자동작성(_load_account)과 키 이름을 맞춘다:
    ``office_name`` / ``office_adr`` / ``biz_reg_no`` / ``contact_name`` / ``contact_tel``.
    원본 주민등록번호(``agent_rrn``)는 PG 가 해시(``agent_rrn_hash``)만 보관하므로 포함하지
    않는다 — 호출측이 보완한다. PG 에 tenant 가 없으면 ``None``.
    사무소 필드는 ``tenants`` 행, 담당자(연락처/이름)는 해당 tenant 의 대표(가능하면 admin)
    ``users`` 행에서 가져온다.
    """
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        if t is None:
            return None
        u = session.scalar(
            select(AccountUser)
            .where(AccountUser.tenant_id == tenant_id)
            .order_by(AccountUser.is_admin.desc(), AccountUser.id.asc())
        )
        return {
            "tenant_id":    t.tenant_id,
            "office_name":  t.office_name or "",
            "office_adr":   t.office_adr or "",
            "biz_reg_no":   t.biz_reg_no or "",
            "contact_name": (u.contact_name if u else "") or "",
            "contact_tel":  (u.contact_tel if u else "") or "",
            # 원본 주민번호는 평문 미보관 — 암호문만 전달(호출측이 복호화). 평문/해시는 출력 소스 아님.
            "agent_rrn_encrypted": t.agent_rrn_encrypted or "",
        }


def verify_login_pg(login_id: str, password: str) -> Optional[PGUserInfo]:
    """Return the user dict iff the credentials are valid AND the user is active."""
    from backend.services.accounts_service import verify_password

    info = find_user_pg(login_id)
    if info is None:
        return None
    if not info["is_active"]:
        return None
    if not verify_password(password, info["password_hash"]):
        return None
    return info
