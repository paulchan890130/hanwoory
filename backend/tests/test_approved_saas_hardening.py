"""승인형 SaaS 보안 하드닝 테스트 — 권한분리 / tenant fail-closed / IP추출 / 토큰 재발급.

SQLite + get_sessionmaker monkeypatch. 기존 test_approved_saas 와 동일 패턴.
"""
import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from fastapi import HTTPException


@compiles(BigInteger, "sqlite")
def _bigint(element, compiler, **kw):  # noqa: ANN001
    return "INTEGER"


@compiles(JSONB, "sqlite")
def _jsonb(element, compiler, **kw):  # noqa: ANN001
    return "JSON"


@compiles(INET, "sqlite")
def _inet(element, compiler, **kw):  # noqa: ANN001
    return "TEXT"


@pytest.fixture
def db(monkeypatch, tmp_path):
    from backend.db.base import Base
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.models.office_application import OfficeApplication
    from backend.db.models.activation_token import ActivationToken
    from backend.db.models.user_session import UserSession
    engine = create_engine(f"sqlite:///{tmp_path / 'h.db'}", future=True)
    Base.metadata.create_all(engine, tables=[
        Tenant.__table__, AccountUser.__table__, OfficeApplication.__table__,
        ActivationToken.__table__, UserSession.__table__,
    ])
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "get_sessionmaker", lambda: SessionLocal)
    return SessionLocal


# ══ 2. 시스템 관리자 vs 사무소 관리자 권한 분리 ═══════════════════════════════
def test_require_system_admin_blocks_office_admin(monkeypatch):
    """office_admin(is_admin=true, 마스터/allowlist 아님)은 시스템 API 차단(권한상승 방지)."""
    monkeypatch.delenv("SYSTEM_ADMIN_LOGIN_IDS", raising=False)
    from backend.auth import require_system_admin
    office_admin = {"login_id": "admin@office.kr", "is_admin": True, "is_master": False}
    with pytest.raises(HTTPException) as ei:
        require_system_admin(office_admin)
    assert ei.value.status_code == 403


def test_require_system_admin_allows_master(monkeypatch):
    monkeypatch.delenv("SYSTEM_ADMIN_LOGIN_IDS", raising=False)
    from backend.auth import require_system_admin
    assert require_system_admin({"login_id": "wkdwhfl", "is_admin": True})["login_id"] == "wkdwhfl"


def test_require_system_admin_env_allowlist(monkeypatch):
    monkeypatch.setenv("SYSTEM_ADMIN_LOGIN_IDS", "op1, op2")
    from backend.auth import require_system_admin
    assert require_system_admin({"login_id": "op1", "is_admin": False})["login_id"] == "op1"
    # 목록에 없는 office_admin 은 여전히 차단
    with pytest.raises(HTTPException):
        require_system_admin({"login_id": "op3", "is_admin": True})


def test_office_admin_still_passes_require_admin():
    """회귀: office_admin(is_admin=true)은 tenant 스코프용 require_admin/require_office_admin 통과."""
    from backend.auth import require_admin, require_office_admin
    oa = {"login_id": "admin@office.kr", "is_admin": True, "is_master": False}
    assert require_admin(oa)["is_admin"] is True
    assert require_office_admin(oa)["is_admin"] is True


def test_system_routes_use_system_admin_dependency():
    """라우터 배선 검증 — 모든 /admin/* 시스템 라우트가 require_system_admin 에 의존한다."""
    from backend.routers import office_applications as r
    from backend.auth import require_system_admin
    from fastapi.routing import APIRoute
    admin_routes = [rt for rt in r.router.routes
                    if isinstance(rt, APIRoute) and rt.path.startswith("/admin/")]
    assert admin_routes, "no admin routes found"
    for rt in admin_routes:
        deps = [d.call for d in rt.dependant.dependencies]
        assert require_system_admin in deps, f"{rt.path} not gated by require_system_admin"


def test_public_routes_have_no_admin_dependency():
    """공개 라우트(/public/*)는 관리자 의존성이 없어야 한다(무인증 접수/활성화)."""
    from backend.routers import office_applications as r
    from backend.auth import require_system_admin, require_admin
    from fastapi.routing import APIRoute
    for rt in r.router.routes:
        if isinstance(rt, APIRoute) and rt.path.startswith("/public/"):
            deps = [d.call for d in rt.dependant.dependencies]
            assert require_system_admin not in deps and require_admin not in deps


# ══ 3. tenant status fail-closed ═════════════════════════════════════════════
def test_tenant_status_precise_states(db):
    from backend.services import office_application_pg_service as svc
    from backend.services import account_lifecycle_pg_service as life
    from backend.services.auth_pg_service import tenant_service_status
    ALLOWED = ("active", "pending_activation")
    # 미존재 tenant → missing (차단 대상)
    assert tenant_service_status("nope") == "missing"
    assert "missing" not in ALLOWED
    # 승인 → pending_activation (허용)
    r = svc.create_application({"office_name": "t", "applicant_email": "a@a.kr",
                                "requested_user_1_name": "A", "requested_user_1_email": "a1@a.kr",
                                "requested_user_2_name": "B", "requested_user_2_email": "b1@a.kr"})
    res = svc.approve(r["application_id"], "wkdwhfl")
    tid = res["tenant_id"]
    assert tenant_service_status(tid) == "pending_activation"
    assert tenant_service_status(tid) in ALLOWED
    # 정지 → suspended (차단)
    life.suspend_tenant(tid, "wkdwhfl")
    assert tenant_service_status(tid) == "suspended"
    assert "suspended" not in ALLOWED
    # 복구 → active (허용)
    life.restore_tenant(tid, "wkdwhfl")
    assert tenant_service_status(tid) == "active"


def test_tenant_status_empty_id_is_missing(db):
    from backend.services.auth_pg_service import tenant_service_status
    assert tenant_service_status("") == "missing"
    assert tenant_service_status(None) == "missing"  # type: ignore[arg-type]


# ══ 4. IP 추출 (서버 신뢰) ════════════════════════════════════════════════════
class _StubReq:
    def __init__(self, host, xff=None):
        self.client = type("C", (), {"host": host})() if host else None
        self.headers = {"x-forwarded-for": xff} if xff else {}
        # dict.get 호환
        self.headers = _Headers(self.headers)


class _Headers(dict):
    def get(self, k, default=None):
        return super().get(k, default)


def test_client_ip_ignores_xff_by_default(monkeypatch):
    monkeypatch.delenv("TRUST_PROXY_HEADERS", raising=False)
    from backend.routers.office_applications import _client_ip
    req = _StubReq("10.0.0.5", xff="1.2.3.4")  # 공격자가 XFF 로 가짜 IP 주장
    assert _client_ip(req) == "10.0.0.5"  # XFF 무시, 실제 연결 IP 사용


def test_client_ip_trusts_xff_when_enabled(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "1")
    from backend.routers.office_applications import _client_ip
    req = _StubReq("10.0.0.5", xff="1.2.3.4, 10.0.0.1")
    assert _client_ip(req) == "1.2.3.4"  # 신뢰 프록시 뒤 → 최좌측 원 클라이언트


def test_application_schema_has_no_ip_field():
    from backend.routers.office_applications import OfficeApplicationCreate
    assert "ip" not in OfficeApplicationCreate.model_fields
    assert "submit_ip_hash" not in OfficeApplicationCreate.model_fields


def test_rate_limit_uses_server_ip(monkeypatch):
    from backend.routers import office_applications as r
    r._RL_HITS.clear()
    # 동일 서버 IP 로 _RL_MAX 회 → 다음 회차 차단
    for _ in range(r._RL_MAX):
        r._rate_limit("9.9.9.9")
    with pytest.raises(HTTPException) as ei:
        r._rate_limit("9.9.9.9")
    assert ei.value.status_code == 429
    # 다른 IP 는 독립 버킷(우회 아님 — 서버가 IP 를 정한다)
    r._rate_limit("8.8.8.8")


# ══ 5. activation token 재발급 ════════════════════════════════════════════════
def test_reissue_revokes_old_token(db):
    from backend.services import office_application_pg_service as svc
    from backend.services import activation_pg_service as act
    r = svc.create_application({"office_name": "t", "applicant_email": "a@a.kr",
                                "requested_user_1_name": "A", "requested_user_1_email": "a1@a.kr",
                                "requested_user_2_name": "B", "requested_user_2_email": "b1@a.kr"})
    res = svc.approve(r["application_id"], "wkdwhfl")
    old = res["users"][0]["activation_token"]
    login_id = res["users"][0]["login_id"]
    assert act.verify_activation_token(old) is not None  # 최초 유효
    out = act.reissue_activation_token(login_id, actor="wkdwhfl")
    new = out["activation_token"]
    assert new != old
    assert act.verify_activation_token(old) is None        # 기존 토큰 폐기
    assert act.verify_activation_token(new)["login_id"] == login_id  # 새 토큰 유효
    # 새 토큰으로 활성화 성공
    act.complete_activation(new, "newpass123")


def test_reissue_blocked_when_active(db):
    from backend.services import office_application_pg_service as svc
    from backend.services import activation_pg_service as act
    r = svc.create_application({"office_name": "t", "applicant_email": "a@a.kr",
                                "requested_user_1_name": "A", "requested_user_1_email": "a1@a.kr",
                                "requested_user_2_name": "B", "requested_user_2_email": "b1@a.kr"})
    res = svc.approve(r["application_id"], "wkdwhfl")
    login_id = res["users"][0]["login_id"]
    act.complete_activation(res["users"][0]["activation_token"], "newpass123")
    with pytest.raises(act.ActivationError) as ei:
        act.reissue_activation_token(login_id, actor="wkdwhfl")
    assert ei.value.code == "ALREADY_ACTIVE"


def test_reissue_missing_user(db):
    from backend.services import activation_pg_service as act
    with pytest.raises(act.ActivationError) as ei:
        act.reissue_activation_token("ghost@x.kr", actor="wkdwhfl")
    assert ei.value.code == "NO_USER"


def test_reissue_endpoint_is_system_admin_gated():
    from backend.routers import office_applications as r
    from backend.auth import require_system_admin
    from fastapi.routing import APIRoute
    rt = next(x for x in r.router.routes
              if isinstance(x, APIRoute) and x.path.endswith("/reissue-activation"))
    deps = [d.call for d in rt.dependant.dependencies]
    assert require_system_admin in deps
