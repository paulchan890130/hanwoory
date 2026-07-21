"""승인형 SaaS — 레거시 admin 우회 차단 + 좌석 한도 원자 검증 테스트.

검증 범위:
- require_admin_or_system: FEATURE OFF(레거시 require_admin 동작) vs ON(system admin 전용, office_admin 403)
- 좌석 한도 원자 검증: activation 완료 / 사용자 복구 / office_admin 복구 / 승인(seat<2)
- 레거시 /workspace: FEATURE ON 에서 409(활성화 우회 차단)

SQLite + get_sessionmaker monkeypatch (기존 패턴 재사용).
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
    from backend.db.models.office_application import OfficeApplication
    engine = create_engine(f"sqlite:///{tmp_path / 'bypass.db'}", future=True)
    Base.metadata.create_all(engine, tables=[
        Tenant.__table__, AccountUser.__table__, UserSession.__table__,
        ActivationToken.__table__, OfficeApplication.__table__,
    ])
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "get_sessionmaker", lambda: SessionLocal)
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    return SessionLocal


def _seed(db, tid="of-1", seat_limit=2, active_admins=1, active_staff=0):
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    label = tid.replace("-", "")
    with db() as s:
        t = Tenant(tenant_id=tid, office_name="T", is_active=True)
        t.service_status = "active"; t.seat_limit = seat_limit; t.service_tier = "managed_basic"
        s.add(t)
        for i in range(active_admins):
            a = AccountUser(login_id=f"admin{i}@{label}.kr", tenant_id=tid, password_hash="x",
                            is_admin=True, is_active=True)
            a.account_status = "active"; s.add(a)
        for i in range(active_staff):
            st = AccountUser(login_id=f"staff{i}@{label}.kr", tenant_id=tid, password_hash="x",
                             is_admin=False, is_active=True)
            st.account_status = "active"; s.add(st)
        s.commit()


# ── require_admin_or_system (flag 전환) ───────────────────────────────────────
def test_admin_or_system_off_allows_office_admin(monkeypatch):
    from backend.auth import require_admin_or_system
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "0")
    # OFF: 기존 require_admin 동작 — full admin 통과
    assert require_admin_or_system({"login_id": "a", "is_admin": True})["is_admin"] is True
    # 비관리자 403
    with pytest.raises(HTTPException) as ei:
        require_admin_or_system({"login_id": "s", "is_admin": False, "is_master": False})
    assert ei.value.status_code == 403


def test_admin_or_system_on_blocks_office_admin(monkeypatch):
    from backend.auth import require_admin_or_system
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "1")
    monkeypatch.delenv("SYSTEM_ADMIN_LOGIN_IDS", raising=False)
    # ON: office_admin(is_admin=true 이지만 system admin 아님) → 403
    with pytest.raises(HTTPException) as ei:
        require_admin_or_system({"login_id": "office@x.kr", "is_admin": True, "is_master": False})
    assert ei.value.status_code == 403
    # office_staff → 403
    with pytest.raises(HTTPException):
        require_admin_or_system({"login_id": "staff@x.kr", "is_admin": False, "is_master": False})
    # 마스터(system admin) → 통과
    from backend.auth import MASTER_ADMIN_LOGIN_ID
    ok = require_admin_or_system({"login_id": MASTER_ADMIN_LOGIN_ID, "is_admin": True, "is_master": True})
    assert ok["login_id"] == MASTER_ADMIN_LOGIN_ID


def test_admin_or_system_on_allows_env_system_admin(monkeypatch):
    from backend.auth import require_admin_or_system
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "1")
    monkeypatch.setenv("SYSTEM_ADMIN_LOGIN_IDS", "sysop@x.kr")
    ok = require_admin_or_system({"login_id": "sysop@x.kr", "is_admin": False, "is_master": False})
    assert ok["login_id"] == "sysop@x.kr"


# ── 좌석 한도 원자 검증 ───────────────────────────────────────────────────────
def test_restore_user_seat_limit(db):
    from backend.services import account_lifecycle_pg_service as svc
    from backend.db.models.user import AccountUser
    # seat_limit=1, 활성 관리자 1 → 정지된 staff 1 명 존재
    _seed(db, seat_limit=1, active_admins=1)
    with db() as s:
        st = AccountUser(login_id="staff@of1.kr", tenant_id="of-1", password_hash="x",
                         is_admin=False, is_active=False)
        st.account_status = "suspended"; s.add(st); s.commit()
    # 복구하면 active 2 > seat_limit 1 → SEAT_LIMIT
    with pytest.raises(svc.LifecycleError) as ei:
        svc.restore_user("staff@of1.kr", actor="admin0@of1.kr")
    assert ei.value.code == "SEAT_LIMIT"


def test_office_restore_sub_seat_limit(db):
    from backend.services import account_lifecycle_pg_service as svc
    from backend.db.models.user import AccountUser
    _seed(db, seat_limit=1, active_admins=1)
    with db() as s:
        st = AccountUser(login_id="staff@of1.kr", tenant_id="of-1", password_hash="x",
                         is_admin=False, is_active=False)
        st.account_status = "suspended"; s.add(st); s.commit()
    with pytest.raises(svc.LifecycleError) as ei:
        svc.office_restore_sub("of-1", "admin0@of1.kr", "staff@of1.kr")
    assert ei.value.code == "SEAT_LIMIT"


def test_restore_within_limit_ok(db):
    from backend.services import account_lifecycle_pg_service as svc
    from backend.db.models.user import AccountUser
    _seed(db, seat_limit=2, active_admins=1)
    with db() as s:
        st = AccountUser(login_id="staff@of1.kr", tenant_id="of-1", password_hash="x",
                         is_admin=False, is_active=False)
        st.account_status = "suspended"; s.add(st); s.commit()
    r = svc.restore_user("staff@of1.kr", actor="admin0@of1.kr")
    assert r["account_status"] == "active"


def test_complete_activation_seat_limit(db):
    from backend.services import activation_pg_service as act
    from backend.db.models.user import AccountUser
    # seat_limit=1, 활성 관리자 1 + 초대(invited) 1 + 그에 대한 activation 토큰
    _seed(db, seat_limit=1, active_admins=1)
    with db() as s:
        inv = AccountUser(login_id="new@of1.kr", tenant_id="of-1", password_hash="x",
                          is_admin=False, is_active=False)
        inv.account_status = "invited"; s.add(inv); s.flush()
        raw = act.issue_activation_token(s, "new@of1.kr", "of-1")
        s.commit()
    with pytest.raises(act.ActivationError) as ei:
        act.complete_activation(raw, "password123")
    assert ei.value.code == "SEAT_LIMIT"
    # 토큰이 소비되지 않았는지 확인(재검증 가능해야 함).
    assert act.verify_activation_token(raw) is not None


def test_complete_activation_within_limit_ok(db):
    from backend.services import activation_pg_service as act
    from backend.db.models.user import AccountUser
    _seed(db, seat_limit=2, active_admins=1)
    with db() as s:
        inv = AccountUser(login_id="new@of1.kr", tenant_id="of-1", password_hash="x",
                          is_admin=False, is_active=False)
        inv.account_status = "invited"; s.add(inv); s.flush()
        raw = act.issue_activation_token(s, "new@of1.kr", "of-1")
        s.commit()
    r = act.complete_activation(raw, "password123")
    assert r["login_id"] == "new@of1.kr"
    # 이제 토큰은 소비됨.
    assert act.verify_activation_token(raw) is None


# ── 레거시 /workspace: FEATURE ON → 409 ───────────────────────────────────────
def test_workspace_blocked_when_saas_on(monkeypatch):
    from backend.routers.admin import create_workspace, WorkspaceCreateRequest
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "1")
    with pytest.raises(HTTPException) as ei:
        create_workspace(WorkspaceCreateRequest(login_id="x", office_name="o"),
                         user={"login_id": "wkdwhfl", "is_admin": True, "is_master": True})
    assert ei.value.status_code == 409


# ── 승인: seat_limit < 2 거부 ─────────────────────────────────────────────────
def test_approve_rejects_seat_below_two(db):
    from backend.services import office_application_pg_service as svc
    from backend.db.models.office_application import OfficeApplication
    from backend.db.session import get_sessionmaker
    # 신청 1건 seed.
    SessionLocal = get_sessionmaker()
    with SessionLocal() as s:
        a = OfficeApplication(
            application_id="app-1", office_name="O",
            representative_name="R", business_registration_number="1",
            applicant_name="A", applicant_email="a@x.kr",
            requested_user_1_name="U1", requested_user_1_email="u1@x.kr",
            requested_user_2_name="U2", requested_user_2_email="u2@x.kr",
            status="submitted",
        )
        s.add(a); s.commit()
    with pytest.raises(svc.ApplicationError) as ei:
        svc.approve("app-1", "wkdwhfl", seat_limit=1)
    assert ei.value.code == "SEAT_LIMIT"


# ── 상태 전이 강제 (SQLite 수준 로직) ─────────────────────────────────────────
def _seed_invited_token(db, login_id, tid="of-1"):
    from backend.db.models.user import AccountUser
    from backend.services import activation_pg_service as act
    with db() as s:
        u = AccountUser(login_id=login_id, tenant_id=tid, password_hash="x",
                        is_admin=False, is_active=False)
        u.account_status = "invited"
        s.add(u); s.flush()
        raw = act.issue_activation_token(s, login_id, tid)
        s.commit()
    return raw


def test_verify_reflects_user_and_tenant_state(db):
    from backend.services import activation_pg_service as act
    from backend.db.models.user import AccountUser
    _seed(db, seat_limit=3, active_admins=1)
    raw = _seed_invited_token(db, "inv@of1.kr")
    assert act.verify_activation_token(raw) is not None      # invited + active tenant → 유효
    # 계정이 replaced 로 전이하면(교체) 잔존 링크는 상태상 무효로 표시돼야 한다.
    with db() as s:
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == "inv@of1.kr"))
        u.account_status = "replaced"; u.is_active = False; s.commit()
    assert act.verify_activation_token(raw) is None


def test_verify_none_when_tenant_suspended(db):
    from backend.services import activation_pg_service as act
    from backend.services import account_lifecycle_pg_service as life
    _seed(db, seat_limit=3, active_admins=1)
    raw = _seed_invited_token(db, "inv@of1.kr")
    life.suspend_tenant("of-1", actor="sys")
    assert act.verify_activation_token(raw) is None


def test_activation_blocked_when_not_invited(db):
    from backend.services import activation_pg_service as act
    from backend.db.models.user import AccountUser
    _seed(db, seat_limit=3, active_admins=1)
    # active 계정에 잔존 토큰이 있어도 활성화 불가.
    raw = _seed_invited_token(db, "u@of1.kr")
    with db() as s:
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == "u@of1.kr"))
        u.is_active = True; u.account_status = "active"; s.commit()
    with pytest.raises(act.ActivationError) as ei:
        act.complete_activation(raw, "password123")
    assert ei.value.code == "BAD_ACCOUNT_STATE"


def test_activation_blocked_when_tenant_suspended(db):
    from backend.services import activation_pg_service as act
    from backend.db.models.tenant import Tenant
    _seed(db, seat_limit=3, active_admins=1)
    raw = _seed_invited_token(db, "inv@of1.kr")
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == "of-1"))
        t.service_status = "suspended"; t.is_active = False; s.commit()
    with pytest.raises(act.ActivationError) as ei:
        act.complete_activation(raw, "password123")
    assert ei.value.code == "TENANT_SUSPENDED"


def test_restore_state_guards(db):
    from backend.services import account_lifecycle_pg_service as life
    from backend.db.models.user import AccountUser
    _seed(db, seat_limit=5, active_admins=1)
    with db() as s:
        for lid, st, act_ in [("inv@of1.kr", "invited", False), ("rep@of1.kr", "replaced", False),
                              ("act@of1.kr", "active", True)]:
            u = AccountUser(login_id=lid, tenant_id="of-1", password_hash="x", is_admin=False, is_active=act_)
            u.account_status = st; s.add(u)
        s.commit()
    for lid, code in [("inv@of1.kr", "INVITED"), ("rep@of1.kr", "REPLACED"), ("act@of1.kr", "ALREADY_ACTIVE")]:
        with pytest.raises(life.LifecycleError) as ei:
            life.restore_user(lid, actor="sys")
        assert ei.value.code == code, lid


def test_reissue_state_guards(db):
    from backend.services import activation_pg_service as act
    from backend.db.models.user import AccountUser
    _seed(db, seat_limit=5, active_admins=1)
    with db() as s:
        for lid, st, a in [("s@of1.kr", "suspended", False), ("r@of1.kr", "replaced", False),
                           ("a@of1.kr", "active", True)]:
            u = AccountUser(login_id=lid, tenant_id="of-1", password_hash="x", is_admin=False, is_active=a)
            u.account_status = st; s.add(u)
        s.commit()
    for lid, code in [("s@of1.kr", "SUSPENDED"), ("r@of1.kr", "REPLACED"), ("a@of1.kr", "ALREADY_ACTIVE")]:
        with pytest.raises(act.ActivationError) as ei:
            act.reissue_activation_token(lid, actor="sys")
        assert ei.value.code == code, lid


def test_suspend_revokes_unused_tokens(db):
    from backend.services import account_lifecycle_pg_service as life
    from backend.services import activation_pg_service as act
    from backend.db.models.activation_token import ActivationToken
    from backend.db.models.user import AccountUser
    from backend.services.activation_pg_service import _hash
    _seed(db, seat_limit=3, active_admins=1)
    # 정지는 active 계정 전용 → active 계정에 잔존 미사용 토큰이 있으면 정지 시 폐기돼야 한다.
    with db() as s:
        u = AccountUser(login_id="act@of1.kr", tenant_id="of-1", password_hash="x",
                        is_admin=False, is_active=True)
        u.account_status = "active"; s.add(u); s.flush()
        raw = act.issue_activation_token(s, "act@of1.kr", "of-1")
        s.commit()
    life.suspend_user("act@of1.kr", actor="sys")
    with db() as s:
        row = s.scalar(select(ActivationToken).where(ActivationToken.token_hash == _hash(raw)))
        assert row.used_at is not None


def test_replace_revokes_old_token(db):
    from backend.services import account_lifecycle_pg_service as life
    from backend.db.models.activation_token import ActivationToken
    from backend.services.activation_pg_service import _hash
    _seed(db, seat_limit=3, active_admins=1)
    raw = _seed_invited_token(db, "old@of1.kr")
    life.replace_user("old@of1.kr", "새이름", "new@of1.kr", actor="sys", new_role="office_staff")
    with db() as s:
        row = s.scalar(select(ActivationToken).where(ActivationToken.token_hash == _hash(raw)))
        assert row.used_at is not None


# ── 레거시 admin 상태변경 우회 차단 (FEATURE ON) ─────────────────────────────
def test_legacy_create_blocked_when_saas_on(db, monkeypatch):
    from backend.routers.admin import create_account
    from backend.models import AccountCreate
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "1")
    with pytest.raises(HTTPException) as ei:
        create_account(AccountCreate(login_id="x@of1.kr", password="pw123456", office_name="O"),
                       user={"login_id": "wkdwhfl", "is_admin": True, "is_master": True})
    assert ei.value.status_code == 409


def test_legacy_update_privileged_blocked_when_saas_on(db, monkeypatch):
    from backend.routers.admin import update_account
    from backend.models import AccountUpdate
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "1")
    _seed(db, seat_limit=3, active_admins=1)
    for payload in [{"is_active": True}, {"tenant_id": "other"}, {"is_admin": True}]:
        with pytest.raises(HTTPException) as ei:
            update_account("admin0@of1.kr", AccountUpdate(**payload),
                           user={"login_id": "wkdwhfl", "is_admin": True, "is_master": True})
        assert ei.value.status_code == 409, payload


def test_legacy_update_contact_allowed_when_saas_on(db, monkeypatch):
    from backend.routers.admin import update_account
    from backend.models import AccountUpdate
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "1")
    _seed(db, seat_limit=3, active_admins=1)
    # 연락처만 수정 → 허용(예외 없음).
    res = update_account("admin0@of1.kr", AccountUpdate(contact_name="새이름"),
                         user={"login_id": "wkdwhfl", "is_admin": True, "is_master": True})
    assert res.get("ok") is True


def test_legacy_restore_delegates_when_saas_on(db, monkeypatch):
    from backend.routers.admin import restore_account
    from backend.db.models.user import AccountUser
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "1")
    _seed(db, seat_limit=3, active_admins=1)
    with db() as s:
        u = AccountUser(login_id="s@of1.kr", tenant_id="of-1", password_hash="x", is_admin=False, is_active=False)
        u.account_status = "suspended"; s.add(u)
        inv = AccountUser(login_id="inv@of1.kr", tenant_id="of-1", password_hash="x", is_admin=False, is_active=False)
        inv.account_status = "invited"; s.add(inv)
        s.commit()
    # suspended → 복구 성공
    res = restore_account("s@of1.kr", user={"login_id": "wkdwhfl", "is_admin": True, "is_master": True})
    assert res.get("ok") is True and res.get("account_status") == "active"
    # invited → lifecycle 가 차단(409)
    with pytest.raises(HTTPException) as ei:
        restore_account("inv@of1.kr", user={"login_id": "wkdwhfl", "is_admin": True, "is_master": True})
    assert ei.value.status_code == 409
