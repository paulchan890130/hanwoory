"""승인형 SaaS — 신청/승인/계정 lifecycle 테스트.

SQLite 임시 DB + get_sessionmaker monkeypatch(운영 DB 불필요). 기존 test_guideline_categories 패턴.
실행: pytest backend/tests/test_approved_saas.py
"""
import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker


# ── SQLite 호환 shim (postgresql 전용 타입) ──────────────────────────────────
@compiles(BigInteger, "sqlite")
def _bigint_as_integer(element, compiler, **kw):  # noqa: ANN001
    return "INTEGER"


@compiles(JSONB, "sqlite")
def _jsonb_as_json(element, compiler, **kw):  # noqa: ANN001
    return "JSON"


@compiles(INET, "sqlite")
def _inet_as_text(element, compiler, **kw):  # noqa: ANN001
    return "TEXT"


@pytest.fixture
def db(monkeypatch, tmp_path):
    from backend.db.base import Base
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.models.office_application import OfficeApplication
    from backend.db.models.activation_token import ActivationToken
    from backend.db.models.user_session import UserSession

    engine = create_engine(f"sqlite:///{tmp_path / 'saas.db'}", future=True)
    Base.metadata.create_all(engine, tables=[
        Tenant.__table__, AccountUser.__table__, OfficeApplication.__table__,
        ActivationToken.__table__, UserSession.__table__,
    ])
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "get_sessionmaker", lambda: SessionLocal)
    # 감사/보안은 별도 세션이므로 no-op 유지(FEATURE_PG_AUDIT off 기본). 세션 revoke 는 같은 SessionLocal.
    return SessionLocal


def _base_app_data(**over):
    # canonical 신청 구조: 대표자(승인 시 office_admin) + 실무자(office_staff).
    d = {
        "office_name": "한빛행정사",
        "representative_name": "관리자A", "representative_email": "admin@hanbit.kr",
        "business_registration_number": "1112233444", "office_address": "서울 강남",
        "office_phone": "02-111-2222",
        "staff_name": "직원B", "staff_email": "staff@hanbit.kr",
    }
    d.update(over)
    return d


# ── 신청 생성 / 검증 / 중복경고 ───────────────────────────────────────────────
def test_create_application(db):
    from backend.services import office_application_pg_service as svc
    r = svc.create_application(_base_app_data())
    assert r["status"] == "pending"
    assert r["application_id"].startswith("APP-")
    apps = svc.list_applications()
    assert len(apps) == 1 and apps[0]["office_name"] == "한빛행정사"


def test_create_application_requires_office_name(db):
    from backend.services import office_application_pg_service as svc
    with pytest.raises(svc.ApplicationError) as ei:
        svc.create_application(_base_app_data(office_name=""))
    assert ei.value.code == "MISSING_OFFICE_NAME"


def test_duplicate_pending_blocked(db):
    from backend.services import office_application_pg_service as svc
    svc.create_application(_base_app_data())
    with pytest.raises(svc.ApplicationError) as ei:
        svc.create_application(_base_app_data())  # 같은 사무소+이메일 미결 신청
    assert ei.value.code == "DUPLICATE_PENDING"


def test_duplicate_flags_existing_tenant_biz(db):
    from backend.services import office_application_pg_service as svc
    from backend.db.models.tenant import Tenant
    SessionLocal = db
    with SessionLocal() as s:
        s.add(Tenant(tenant_id="t-old", office_name="기존", biz_reg_no="1112233444", is_active=True))
        s.commit()
    r = svc.create_application(_base_app_data())
    app = svc.get_application(r["application_id"])
    assert app["duplicate_flags"].get("existing_tenant_biz_reg_no") is True


# ── 권한 가드 (승인은 full admin 전용) ────────────────────────────────────────
def test_require_admin_blocks_non_admin():
    from fastapi import HTTPException
    from backend.auth import require_admin
    with pytest.raises(HTTPException) as ei:
        require_admin({"login_id": "u", "is_admin": False, "is_master": False, "is_sub_admin": True})
    assert ei.value.status_code == 403
    # full admin 은 통과
    assert require_admin({"login_id": "a", "is_admin": True})["is_admin"] is True


# ── 승인: tenant 1 + user 2, 멱등, 격리 ───────────────────────────────────────
def test_approve_creates_one_tenant_two_users(db):
    from backend.services import office_application_pg_service as svc
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    r = svc.create_application(_base_app_data())
    res = svc.approve(r["application_id"], "wkdwhfl")
    assert res["already_approved"] is False
    assert len(res["users"]) == 2
    SessionLocal = db
    with SessionLocal() as s:
        tenants = s.scalars(select(Tenant)).all()
        users = s.scalars(select(AccountUser)).all()
        assert len(tenants) == 1
        assert len(users) == 2
        # 계정1 admin, 계정2 staff
        roles = sorted([u.is_admin for u in users])
        assert roles == [False, True]
        # 승인 직후 두 계정 모두 비활성(activation 전 로그인 불가)
        assert all(u.is_active is False for u in users)
        assert all(u.account_status == "invited" for u in users)
        t = tenants[0]
        assert t.service_tier == "managed_basic" and t.seat_limit == 2
        assert t.service_status == "pending_activation"
    # 신청 상태 approved + tenant 연결
    app = svc.get_application(r["application_id"])
    assert app["status"] == "approved" and app["approved_tenant_id"] == res["tenant_id"]


def test_approve_is_idempotent(db):
    from backend.services import office_application_pg_service as svc
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    r = svc.create_application(_base_app_data())
    res1 = svc.approve(r["application_id"], "wkdwhfl")
    res2 = svc.approve(r["application_id"], "wkdwhfl")  # 재승인(중복 클릭)
    assert res2["already_approved"] is True
    assert res2["tenant_id"] == res1["tenant_id"]
    SessionLocal = db
    with SessionLocal() as s:
        assert len(s.scalars(select(Tenant)).all()) == 1
        assert len(s.scalars(select(AccountUser)).all()) == 2  # 중복 생성 없음


def test_approve_rolls_back_on_error(db, monkeypatch):
    """승인 중 오류 → tenant/user 전부 롤백, 신청은 여전히 미승인."""
    from backend.services import office_application_pg_service as svc
    from backend.services import activation_pg_service as act
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    r = svc.create_application(_base_app_data())

    calls = {"n": 0}
    real_issue = act.issue_activation_token
    def boom(session, login_id, tenant_id, ttl_hours=72):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated failure mid-transaction")
        return real_issue(session, login_id, tenant_id, ttl_hours)
    monkeypatch.setattr(act, "issue_activation_token", boom)

    with pytest.raises(RuntimeError):
        svc.approve(r["application_id"], "wkdwhfl")
    SessionLocal = db
    with SessionLocal() as s:
        assert s.scalars(select(Tenant)).all() == []   # 롤백
        assert s.scalars(select(AccountUser)).all() == []
    assert svc.get_application(r["application_id"])["status"] == "pending"  # 승인 안 됨


def test_approve_blocks_duplicate_email(db):
    from backend.services import office_application_pg_service as svc
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    SessionLocal = db
    # 신청은 이메일이 아직 계정이 아닐 때 접수된다(접수 시점엔 통과).
    r = svc.create_application(_base_app_data())
    # 접수 후 같은 이메일이 다른 경로로 계정이 됨 → 승인 시점 충돌.
    with SessionLocal() as s:
        s.add(Tenant(tenant_id="t-x", office_name="X", is_active=True))
        s.add(AccountUser(login_id="admin@hanbit.kr", tenant_id="t-x",
                          password_hash="x", is_admin=False, is_active=True))
        s.commit()
    with pytest.raises(svc.ApplicationError) as ei:
        svc.approve(r["application_id"], "wkdwhfl")
    assert ei.value.code == "EMAIL_IN_USE"


def test_create_blocks_email_already_account(db):
    # §6-5: 이미 계정으로 발급된 이메일이면 신청 접수 단계에서 차단(승인 후 재신청 방지).
    from backend.services import office_application_pg_service as svc
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    with db() as s:
        s.add(Tenant(tenant_id="t-x", office_name="X", is_active=True))
        s.add(AccountUser(login_id="admin@hanbit.kr", tenant_id="t-x",
                          password_hash="x", is_admin=False, is_active=True))
        s.commit()
    with pytest.raises(svc.ApplicationError) as ei:
        svc.create_application(_base_app_data())
    assert ei.value.code == "EMAIL_IN_USE"


def test_tenant_isolation(db):
    from backend.services import office_application_pg_service as svc
    r1 = svc.create_application(_base_app_data())
    r2 = svc.create_application(_base_app_data(
        office_name="두번째행정사",
        representative_email="admin2@x.kr", staff_email="staff2@x.kr"))
    a = svc.approve(r1["application_id"], "wkdwhfl")
    b = svc.approve(r2["application_id"], "wkdwhfl")
    assert a["tenant_id"] != b["tenant_id"]  # 격리된 별도 tenant


# ── 반려 ─────────────────────────────────────────────────────────────────────
def test_reject_then_cannot_approve(db):
    from backend.services import office_application_pg_service as svc
    r = svc.create_application(_base_app_data())
    svc.reject(r["application_id"], "wkdwhfl", "요건 미충족")
    assert svc.get_application(r["application_id"])["status"] == "rejected"
    with pytest.raises(svc.ApplicationError) as ei:
        svc.approve(r["application_id"], "wkdwhfl")
    assert ei.value.code == "BAD_STATE"


def test_approved_cannot_reject(db):
    from backend.services import office_application_pg_service as svc
    r = svc.create_application(_base_app_data())
    svc.approve(r["application_id"], "wkdwhfl")
    with pytest.raises(svc.ApplicationError) as ei:
        svc.reject(r["application_id"], "wkdwhfl", "사유")
    assert ei.value.code == "ALREADY_APPROVED"


# ── 활성화 (최초 비밀번호) ────────────────────────────────────────────────────
def test_activation_flow(db):
    from backend.services import office_application_pg_service as svc
    from backend.services import activation_pg_service as act
    from backend.services.auth_pg_service import account_auth_status
    r = svc.create_application(_base_app_data())
    res = svc.approve(r["application_id"], "wkdwhfl")
    token = res["users"][0]["activation_token"]
    login_id = res["users"][0]["login_id"]
    # 활성화 전: 비활성
    assert account_auth_status(login_id)["status"] == "disabled"
    # 유효 토큰 확인
    assert act.verify_activation_token(token)["login_id"] == login_id
    # 완료 → 활성
    act.complete_activation(token, "newpass123")
    assert account_auth_status(login_id)["status"] == "active"
    # 1회성: 재사용 불가
    with pytest.raises(act.ActivationError) as ei:
        act.complete_activation(token, "another123")
    assert ei.value.code == "BAD_TOKEN"


def test_activation_weak_password_rejected(db):
    from backend.services import office_application_pg_service as svc
    from backend.services import activation_pg_service as act
    r = svc.create_application(_base_app_data())
    res = svc.approve(r["application_id"], "wkdwhfl")
    token = res["users"][0]["activation_token"]
    with pytest.raises(act.ActivationError) as ei:
        act.complete_activation(token, "123")
    assert ei.value.code == "WEAK_PASSWORD"


# ── 정지/복구 + 세션 무효화 ───────────────────────────────────────────────────
def test_suspend_user_blocks_login_and_revokes_sessions(db):
    from backend.services import office_application_pg_service as svc
    from backend.services import activation_pg_service as act
    from backend.services import account_lifecycle_pg_service as life
    from backend.services.auth_pg_service import account_auth_status
    from backend.services.session_pg_service import create_session, session_status
    r = svc.create_application(_base_app_data())
    res = svc.approve(r["application_id"], "wkdwhfl")
    login_id = res["users"][0]["login_id"]
    act.complete_activation(res["users"][0]["activation_token"], "newpass123")
    # 활성 세션 생성
    create_session(login_id, res["tenant_id"], "sid-1")
    assert session_status("sid-1") == "active"
    assert account_auth_status(login_id)["status"] == "active"
    # 정지
    life.suspend_user(login_id, "wkdwhfl")
    assert account_auth_status(login_id)["status"] == "disabled"   # 로그인/요청 차단
    assert session_status("sid-1") == "revoked"                    # 기존 세션 무효화
    # 복구
    life.restore_user(login_id, "wkdwhfl")
    assert account_auth_status(login_id)["status"] == "active"


def test_suspend_tenant_status_and_sessions(db):
    from backend.services import office_application_pg_service as svc
    from backend.services import account_lifecycle_pg_service as life
    from backend.services.auth_pg_service import tenant_service_status
    from backend.services.session_pg_service import create_session, session_status
    r = svc.create_application(_base_app_data())
    res = svc.approve(r["application_id"], "wkdwhfl")
    tid = res["tenant_id"]
    create_session(res["users"][0]["login_id"], tid, "sid-t")
    life.suspend_tenant(tid, "wkdwhfl")
    assert tenant_service_status(tid) == "suspended"   # 로그인/요청 차단 근거
    assert session_status("sid-t") == "revoked"
    life.restore_tenant(tid, "wkdwhfl")
    assert tenant_service_status(tid) == "active"


def test_master_cannot_be_suspended(db):
    from backend.services import account_lifecycle_pg_service as life
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    SessionLocal = db
    with SessionLocal() as s:
        s.add(Tenant(tenant_id="wkdwhfl", office_name="master", is_active=True))
        s.add(AccountUser(login_id="wkdwhfl", tenant_id="wkdwhfl", password_hash="x",
                          is_admin=True, is_active=True))
        s.commit()
    with pytest.raises(life.LifecycleError) as ei:
        life.suspend_user("wkdwhfl", "wkdwhfl")
    assert ei.value.code == "MASTER_PROTECTED"


# ── 계정 교체 (과거 이력 보존) ────────────────────────────────────────────────
def test_replace_user_preserves_old_and_links(db):
    from backend.services import office_application_pg_service as svc
    from backend.services import account_lifecycle_pg_service as life
    from backend.db.models.user import AccountUser
    r = svc.create_application(_base_app_data())
    res = svc.approve(r["application_id"], "wkdwhfl")
    old_login = res["users"][0]["login_id"]  # admin@hanbit.kr
    rep = life.replace_user(old_login, "새직원", "new@hanbit.kr", "wkdwhfl")
    assert rep["new_login_id"] == "new@hanbit.kr"
    SessionLocal = db
    with SessionLocal() as s:
        old = s.scalar(select(AccountUser).where(AccountUser.login_id == old_login))
        new = s.scalar(select(AccountUser).where(AccountUser.login_id == "new@hanbit.kr"))
        # 기존 사용자 보존(삭제/덮어쓰기 없음) — 이름/이메일 그대로
        assert old is not None and old.contact_name == "관리자A"
        assert old.account_status == "replaced" and old.is_active is False
        # 신규는 초대 상태(비활성)
        assert new is not None and new.is_active is False and new.account_status == "invited"
        # 링크 연결
        assert old.replaced_by_user_id == new.id and new.replaces_user_id == old.id
        # 같은 tenant, active seat 초과 없음
        assert new.tenant_id == old.tenant_id
        active = s.scalars(select(AccountUser).where(
            AccountUser.tenant_id == old.tenant_id, AccountUser.is_active.is_(True))).all()
        assert len(active) <= 2


def test_replace_blocks_email_in_use(db):
    from backend.services import office_application_pg_service as svc
    from backend.services import account_lifecycle_pg_service as life
    r = svc.create_application(_base_app_data())
    res = svc.approve(r["application_id"], "wkdwhfl")
    old_login = res["users"][0]["login_id"]
    other = res["users"][1]["login_id"]  # 이미 사용 중
    with pytest.raises(life.LifecycleError) as ei:
        life.replace_user(old_login, "x", other, "wkdwhfl")
    assert ei.value.code == "EMAIL_IN_USE"


# ── 기존 tenant/user 회귀 (backfill 무해) ─────────────────────────────────────
def test_existing_active_user_unaffected(db):
    """0031 컬럼 추가/backfill 이 기존 active 계정의 인증에 영향 없음(회귀 프록시)."""
    from backend.services.auth_pg_service import account_auth_status
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    SessionLocal = db
    with SessionLocal() as s:
        s.add(Tenant(tenant_id="legacy", office_name="레거시", is_active=True))
        s.add(AccountUser(login_id="legacy-admin", tenant_id="legacy", password_hash="x",
                          is_admin=True, is_active=True))
        s.commit()
    info = account_auth_status("legacy-admin")
    # 0031 컬럼 추가/backfill 이후에도 기존 active admin 인증이 정상(회귀 없음).
    # (role='admin' 백필은 migration 0024 소관 — create_all 기반 테스트에선 기본값 'user').
    assert info["status"] == "active" and info["is_admin"] is True
