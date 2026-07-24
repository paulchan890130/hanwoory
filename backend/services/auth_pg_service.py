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

    반환: ``{"status": "active"|"disabled"|"missing", "is_admin": bool, "role": str,
    "tenant_id": str|None}``. ``tenant_id`` 는 **현재 DB 상의 소속 tenant** — 호출측(auth)이
    JWT 발급 시점의 tenant_id 와 비교해 relink 등으로 소속이 바뀐 기존 토큰을 차단한다.
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
            select(AccountUser.is_active, AccountUser.is_admin, AccountUser.tenant_id)
            .where(AccountUser.login_id == login_id)
        ).first()
        if row is None:
            return {"status": "missing", "is_admin": False, "role": "user", "tenant_id": None}
        is_active, is_admin, tenant_id = bool(row[0]), bool(row[1]), row[2]
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
            "tenant_id": tenant_id,
        }


def tenant_service_status(tenant_id: str) -> str:
    """tenant 의 service_status 정밀 상태.

    반환:
      - 'active' / 'suspended' / 'terminated' / 'pending_activation' : service_status 실제값
      - 'missing'      : tenant 행 없음
      - 'null_status'  : 행은 있으나 service_status 가 NULL(비정상 — NOT NULL default 라 정상엔 없음)
      - 'no_column'    : service_status 컬럼 없음(migration 0031 미적용)
      - 'error'        : 조회/DB 오류

    **예외를 삼키지 않는다** — 오류는 문자열 상태('error'/'no_column')로 반환해, 호출측(auth)이
    fail-closed 로 차단할 수 있게 한다. 이 함수 자체는 flag 를 보지 않으며 상태만 알려준다.
    """
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker

    tid = (tenant_id or "").strip()
    if not tid:
        return "missing"
    try:
        SessionLocal = get_sessionmaker()
        with SessionLocal() as session:
            try:
                row = session.execute(
                    select(Tenant.id, Tenant.service_status).where(Tenant.tenant_id == tid)
                ).first()
            except Exception as e:  # noqa: BLE001
                msg = str(e).lower()
                if "service_status" in msg or "undefined column" in msg or "no such column" in msg:
                    return "no_column"  # 0031 미적용
                return "error"
            if row is None:
                return "missing"
            st = row[1]
            return str(st) if st is not None else "null_status"
    except Exception:  # 세션 획득 실패 등
        return "error"


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


def find_document_office_profile_by_tenant_pg(tenant_id: str) -> Optional[dict]:
    """문서 자동작성 **전용** 사무소 프로필 계약.

    사무소 공통정보(office_name/office_adr/biz_reg_no/agent_rrn_encrypted)는 ``tenants`` 행에서,
    담당자(성명/연락처)는 **대표자 계정에서만** 가져온다. 문서에는 대표 행정사의 정보만 들어가야
    하므로 다음을 **금지**한다: 실무자(office_staff)로 fallback, 현재 로그인한 사용자의 연락처
    사용, login_id/user-id 순서로 임의 대체. 조회는 ``tenant_id`` 로만 대표자를 결정한다.

    대표자 후보(모두 만족): 같은 tenant · ``is_admin=true`` · ``is_active=true`` · **시스템
    관리자(마스터/SYSTEM_ADMIN_LOGIN_IDS) 아님**. (is_active 가 활성 SoT — suspended/invited/
    replaced 는 모두 is_active=False 라 account_status=active 가 함의됨. account_status 는
    deferred 라 운영 스키마 gap 에서 500 위험이 있어 base 컬럼만 조회한다.)
    - 후보 1명 → 대표자로 사용(``representative_configured=True``).
    - 후보 0명 → ``representative_configured=False`` (호출측 409 OFFICE_REPRESENTATIVE_NOT_CONFIGURED).
    - 후보 2명 이상 → ``representative_ambiguous=True`` (호출측 409 OFFICE_REPRESENTATIVE_AMBIGUOUS).
    **id 최소 임의 선택·실무자 fallback·마스터 fallback 금지.**

    반환: tenant 행 없음 → ``None``. 그 외 dict."""
    from backend.auth import is_system_admin
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        if t is None:
            return None
        # 활성 관리자 후보(base 컬럼만) → 시스템 관리자는 Python 에서 제외.
        rows = session.execute(
            select(AccountUser.login_id, AccountUser.contact_name, AccountUser.contact_tel)
            .where(
                AccountUser.tenant_id == tenant_id,
                AccountUser.is_admin.is_(True),
                AccountUser.is_active.is_(True),
            )
            .order_by(AccountUser.id.asc())
        ).all()
        candidates = [r for r in rows if not is_system_admin(str(r[0] or ""))]
        n = len(candidates)
        rep = candidates[0] if n == 1 else None    # 정확히 1명일 때만 대표자
        return {
            "tenant_id":    t.tenant_id,
            "office_name":  t.office_name or "",
            "office_adr":   t.office_adr or "",
            "biz_reg_no":   t.biz_reg_no or "",
            # 원본 주민번호는 평문 미보관 — 암호문만 전달(호출측이 복호화).
            "agent_rrn_encrypted": t.agent_rrn_encrypted or "",
            # 담당자(성명/연락처)는 대표자 계정에서만 — 실무자/시스템관리자 fallback 없음.
            "contact_name": (rep[1] if rep else "") or "",
            "contact_tel":  (rep[2] if rep else "") or "",
            "representative_configured": n == 1,
            "representative_ambiguous": n >= 2,
            "representative_candidate_count": n,
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
