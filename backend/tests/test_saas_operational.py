"""승인형 SaaS 운영 UX — availability / signup 차단 / tenant 요약 / office_admin 스코프 테스트.

SQLite + get_sessionmaker monkeypatch. 기존 패턴 재사용.
"""
import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from fastapi import HTTPException


@compiles(BigInteger, "sqlite")
def _bi(e, c, **k):  # noqa: ANN001
    return "INTEGER"


@compiles(JSONB, "sqlite")
def _jb(e, c, **k):  # noqa: ANN001
    return "JSON"


@compiles(INET, "sqlite")
def _in(e, c, **k):  # noqa: ANN001
    return "TEXT"


@pytest.fixture
def db(monkeypatch, tmp_path):
    from backend.db.base import Base
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.models.user_session import UserSession
    from backend.db.models.activation_token import ActivationToken
    engine = create_engine(f"sqlite:///{tmp_path / 'ux.db'}", future=True)
    Base.metadata.create_all(engine, tables=[
        Tenant.__table__, AccountUser.__table__, UserSession.__table__, ActivationToken.__table__,
    ])
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "get_sessionmaker", lambda: SessionLocal)
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    return SessionLocal


def _seed_tenant(db, tid="of-1"):
    # login_id 를 tid 로 파생해 다중 tenant seed 시 충돌 방지 (of-1 → admin@of1.kr).
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    label = tid.replace("-", "")
    with db() as s:
        t = Tenant(tenant_id=tid, office_name="테스트사무소", is_active=True)
        t.service_status = "active"; t.seat_limit = 2; t.service_tier = "managed_basic"
        s.add(t)
        admin = AccountUser(login_id=f"admin@{label}.kr", tenant_id=tid, password_hash="x", is_admin=True, is_active=True)
        admin.account_status = "active"
        staff = AccountUser(login_id=f"staff@{label}.kr", tenant_id=tid, password_hash="x", is_admin=False, is_active=True)
        staff.account_status = "active"
        s.add(admin); s.add(staff); s.commit()


# ── availability (flag 반영) ──────────────────────────────────────────────────
def test_availability_reflects_flag(monkeypatch):
    from backend.routers.office_applications import public_availability
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "1")
    assert public_availability() == {"enabled": True}
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "0")
    assert public_availability() == {"enabled": False}


# ── signup 차단 (flag on) ─────────────────────────────────────────────────────
def test_signup_blocked_when_saas_on(monkeypatch):
    from backend.routers.auth import signup
    from backend.models import SignupRequest
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "1")
    req = SignupRequest(login_id="x", password="pw", confirm_password="pw", office_name="o")
    with pytest.raises(HTTPException) as ei:
        signup(req)
    assert ei.value.status_code == 409


# ── tenant 요약 (안전필드만) ──────────────────────────────────────────────────
def test_tenant_summary_shape(db):
    from backend.services import account_lifecycle_pg_service as svc
    _seed_tenant(db)
    s = svc.tenant_account_summary("of-1")
    assert s["tenant_id"] == "of-1" and s["seat_limit"] == 2 and s["active_count"] == 2
    assert {a["role"] for a in s["accounts"]} == {"office_admin", "office_staff"}
    # 안전필드만 — hash/token 노출 없음
    flat = str(s)
    assert "password_hash" not in flat and "token" not in flat.lower()


def test_tenant_summary_missing():
    from backend.services import account_lifecycle_pg_service as svc
    import backend.db.session as dbs
    # get_sessionmaker 없이도 tid 빈값 → None
    assert svc.tenant_account_summary("") is None


# ── office_admin 스코프 가드 ──────────────────────────────────────────────────
def test_office_scope_blocks_cross_tenant(db):
    from backend.services import account_lifecycle_pg_service as svc
    _seed_tenant(db, "of-1")
    _seed_tenant(db, "of-2")
    # of-1 admin 이 of-2 staff 관리 시도 → CROSS_TENANT
    with pytest.raises(svc.LifecycleError) as ei:
        svc._assert_manageable_sub("of-1", "admin@of1.kr", "staff@of2.kr")
    assert ei.value.code == "CROSS_TENANT"


def test_office_scope_blocks_admin_target(db):
    from backend.services import account_lifecycle_pg_service as svc
    _seed_tenant(db)
    # 주계정(office_admin)은 서브계정 관리 대상 아님
    with pytest.raises(svc.LifecycleError) as ei:
        svc._assert_manageable_sub("of-1", "admin@of1.kr", "admin@of1.kr")
    assert ei.value.code in ("SELF_FORBIDDEN", "NOT_SUB_ACCOUNT")


def test_office_scope_allows_own_staff(db):
    from backend.services import account_lifecycle_pg_service as svc
    _seed_tenant(db)
    svc._assert_manageable_sub("of-1", "admin@of1.kr", "staff@of1.kr")  # no raise


def test_office_suspend_restore_sub(db):
    from backend.services import account_lifecycle_pg_service as svc
    from backend.services.auth_pg_service import account_active_status
    _seed_tenant(db)
    svc.office_suspend_sub("of-1", "admin@of1.kr", "staff@of1.kr")
    assert account_active_status("staff@of1.kr") == "disabled"
    svc.office_restore_sub("of-1", "admin@of1.kr", "staff@of1.kr")
    assert account_active_status("staff@of1.kr") == "active"


def test_office_cannot_suspend_own_admin(db):
    from backend.services import account_lifecycle_pg_service as svc
    _seed_tenant(db)
    with pytest.raises(svc.LifecycleError) as ei:
        svc.office_suspend_sub("of-1", "admin@of1.kr", "admin@of1.kr")
    assert ei.value.code in ("SELF_FORBIDDEN", "NOT_SUB_ACCOUNT")


# ── require_office_admin / 라우터 배선 ───────────────────────────────────────
def test_require_office_admin_blocks_staff():
    from backend.auth import require_office_admin
    with pytest.raises(HTTPException) as ei:
        require_office_admin({"login_id": "s", "is_admin": False, "is_master": False})
    assert ei.value.status_code == 403
    assert require_office_admin({"login_id": "a", "is_admin": True})["is_admin"] is True


def test_router_dependency_wiring():
    from backend.routers import office_applications as r
    from backend.auth import require_office_admin, require_system_admin
    from fastapi.routing import APIRoute
    routes = {rt.path: rt for rt in r.router.routes if isinstance(rt, APIRoute)}
    # office_admin 스코프 경로
    for p in ["/my/office/accounts", "/my/office/users/{login_id}/suspend",
              "/my/office/users/{login_id}/restore", "/my/office/users/{login_id}/reissue-activation",
              "/my/office/users/{login_id}/replace"]:
        deps = [d.call for d in routes[p].dependant.dependencies]
        assert require_office_admin in deps, f"{p} not office-admin gated"
        assert require_system_admin not in deps
    # 시스템 관리자 요약
    deps = [d.call for d in routes["/admin/tenants/{tenant_id}/summary"].dependant.dependencies]
    assert require_system_admin in deps
    # 공개 availability 는 무인증
    deps = [d.call for d in routes["/public/availability"].dependant.dependencies]
    assert require_office_admin not in deps and require_system_admin not in deps
