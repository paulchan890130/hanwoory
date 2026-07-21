"""승인형 SaaS 계정 상태 전이 — **실제 PostgreSQL** 통합·동시성 테스트.

SQLite 는 ``FOR UPDATE`` 가 no-op 이라 좌석 경쟁/직렬화를 검증하지 못한다. 이 파일은
``TEST_DATABASE_URL`` 이 설정된 경우에만 실행되며(미설정 → skip), 실제 PostgreSQL 에서
상태 전이·토큰 폐기·좌석 한도·동시 activation 경쟁을 확인한다.

CI 는 postgres:16 service 를 띄우고 ``TEST_DATABASE_URL`` 를 주입한다(ci.yml).
로컬 실행 예:
  TEST_DATABASE_URL=postgresql+psycopg://kid:kid@localhost:5432/kid_saas_it \
    .venv/Scripts/python -m pytest backend/tests/test_saas_pg_integration.py -q
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="TEST_DATABASE_URL 미설정 — 실제 PostgreSQL 통합 테스트 skip")


def _ensure_database(url_str: str) -> None:
    """대상 DB 가 없으면 서버 maintenance('postgres') DB 에 붙어 생성한다(멱등)."""
    url = make_url(url_str)
    target = url.database
    admin_url = url.set(database="postgres")
    eng = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with eng.connect() as c:
            exists = c.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target}
            ).first()
            if not exists:
                c.execute(text(f'CREATE DATABASE "{target}"'))
    finally:
        eng.dispose()


@pytest.fixture(scope="module")
def engine():
    _ensure_database(TEST_DB_URL)
    eng = create_engine(TEST_DB_URL, future=True, pool_size=5, max_overflow=5)
    from backend.db.base import Base
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.models.user_session import UserSession
    from backend.db.models.activation_token import ActivationToken
    tables = [Tenant.__table__, AccountUser.__table__, UserSession.__table__, ActivationToken.__table__]
    # 격리: 우리 테이블만 drop 후 재생성(빈 CI DB 기준 — 다른 테이블 FK 없음).
    Base.metadata.drop_all(eng, tables=list(reversed(tables)))
    Base.metadata.create_all(eng, tables=tables)
    yield eng
    Base.metadata.drop_all(eng, tables=list(reversed(tables)))
    eng.dispose()


@pytest.fixture
def db(engine, monkeypatch):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "get_sessionmaker", lambda: SessionLocal)
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    # 각 테스트 전 초기화.
    with engine.begin() as c:
        c.execute(text("TRUNCATE activation_tokens, user_sessions, users, tenants RESTART IDENTITY CASCADE"))
    return SessionLocal


# ── seed helpers ──────────────────────────────────────────────────────────────
def _mk_tenant(db, tid="of-1", seat_limit=2, service_status="active"):
    from backend.db.models.tenant import Tenant
    with db() as s:
        t = Tenant(tenant_id=tid, office_name="T", is_active=(service_status == "active"))
        t.service_status = service_status
        t.seat_limit = seat_limit
        t.service_tier = "managed_basic"
        s.add(t)
        s.commit()


def _mk_user(db, login_id, tid="of-1", is_admin=False, is_active=True, account_status="active"):
    from backend.db.models.user import AccountUser
    with db() as s:
        u = AccountUser(login_id=login_id, tenant_id=tid, password_hash="x",
                        is_admin=is_admin, is_active=is_active)
        u.account_status = account_status
        s.add(u); s.commit()


def _mk_invited_with_token(db, login_id, tid="of-1"):
    """invited 계정 + 그 계정의 유효 activation token(raw) 생성."""
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


def _token_used(db, raw):
    from backend.db.models.activation_token import ActivationToken
    from backend.services.activation_pg_service import _hash
    with db() as s:
        row = s.scalar(select(ActivationToken).where(ActivationToken.token_hash == _hash(raw)))
        return None if row is None else (row.used_at is not None)


# ── 1~2: replaced 계정/토큰 ────────────────────────────────────────────────────
def test_replaced_old_token_activation_fails(db):
    from backend.services import activation_pg_service as act
    from backend.services import account_lifecycle_pg_service as life
    _mk_tenant(db, seat_limit=2)
    _mk_user(db, "admin@of1.kr", is_admin=True)
    _mk_user(db, "staff@of1.kr", is_admin=False)  # 교체 대상(active staff)
    # 먼저 invited 로 만들고 토큰 발급하는 대신, 교체 전 staff 에 잔존 토큰을 만들어 둔다.
    old_raw = _mk_invited_with_token(db, "old@of1.kr")
    # old 를 교체 → old 는 replaced, 기존 토큰 폐기되어야 함.
    life.replace_user("old@of1.kr", "새이름", "new@of1.kr", actor="admin@of1.kr", new_role="office_staff")
    with pytest.raises(act.ActivationError) as ei:
        act.complete_activation(old_raw, "password123")
    assert ei.value.code in ("BAD_TOKEN", "BAD_ACCOUNT_STATE")


def test_replaced_token_verify_fails(db):
    from backend.services import activation_pg_service as act
    from backend.services import account_lifecycle_pg_service as life
    _mk_tenant(db, seat_limit=2)
    _mk_user(db, "admin@of1.kr", is_admin=True)
    old_raw = _mk_invited_with_token(db, "old@of1.kr")
    life.replace_user("old@of1.kr", "새이름", "new@of1.kr", actor="admin@of1.kr", new_role="office_staff")
    # 폐기(used_at) 되었거나 상태상 무효 → verify None.
    assert act.verify_activation_token(old_raw) is None


# ── 3: invited suspend 후 토큰 활성화 실패 ────────────────────────────────────
def test_invited_suspend_then_activation_fails(db):
    from backend.services import activation_pg_service as act
    from backend.services import account_lifecycle_pg_service as life
    _mk_tenant(db, seat_limit=2)
    raw = _mk_invited_with_token(db, "inv@of1.kr")
    life.suspend_user("inv@of1.kr", actor="sys")
    with pytest.raises(act.ActivationError):
        act.complete_activation(raw, "password123")
    assert _token_used(db, raw) is True  # suspend 시 폐기


# ── 4~5: tenant suspend 후 활성화 실패 + tenant 상태 유지 ─────────────────────
def test_tenant_suspend_blocks_activation_and_stays_suspended(db):
    from backend.services import activation_pg_service as act
    from backend.services import account_lifecycle_pg_service as life
    from backend.db.models.tenant import Tenant
    _mk_tenant(db, seat_limit=2, service_status="pending_activation")
    raw = _mk_invited_with_token(db, "inv@of1.kr")
    life.suspend_tenant("of-1", actor="sys")
    with pytest.raises(act.ActivationError) as ei:
        act.complete_activation(raw, "password123")
    assert ei.value.code in ("TENANT_SUSPENDED", "BAD_TOKEN")
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == "of-1"))
        assert t.service_status == "suspended"  # 활성화가 정지를 해제하지 않음


# ── 6: activation 실패 시 토큰 미소비 ─────────────────────────────────────────
def test_failed_activation_does_not_consume_token(db):
    from backend.services import activation_pg_service as act
    # seat_limit=1 + 활성 admin 1 → invited 활성화 시 SEAT_LIMIT
    _mk_tenant(db, seat_limit=1)
    _mk_user(db, "admin@of1.kr", is_admin=True)
    raw = _mk_invited_with_token(db, "inv@of1.kr")
    with pytest.raises(act.ActivationError) as ei:
        act.complete_activation(raw, "password123")
    assert ei.value.code == "SEAT_LIMIT"
    assert _token_used(db, raw) is False  # 미소비


# ── 7~9: restore 상태 제한 ────────────────────────────────────────────────────
def test_restore_invited_blocked(db):
    from backend.services import account_lifecycle_pg_service as life
    _mk_tenant(db)
    _mk_invited_with_token(db, "inv@of1.kr")
    with pytest.raises(life.LifecycleError) as ei:
        life.restore_user("inv@of1.kr", actor="sys")
    assert ei.value.code == "INVITED"


def test_restore_suspended_succeeds(db):
    from backend.services import account_lifecycle_pg_service as life
    _mk_tenant(db, seat_limit=2)
    _mk_user(db, "s@of1.kr", is_active=False, account_status="suspended")
    r = life.restore_user("s@of1.kr", actor="sys")
    assert r["account_status"] == "active"


def test_restore_replaced_blocked(db):
    from backend.services import account_lifecycle_pg_service as life
    _mk_tenant(db)
    _mk_user(db, "r@of1.kr", is_active=False, account_status="replaced")
    with pytest.raises(life.LifecycleError) as ei:
        life.restore_user("r@of1.kr", actor="sys")
    assert ei.value.code == "REPLACED"


# ── 10: suspended/replaced 재발급 409 ─────────────────────────────────────────
def test_reissue_blocked_for_suspended_and_replaced(db):
    from backend.services import activation_pg_service as act
    _mk_tenant(db)
    _mk_user(db, "s@of1.kr", is_active=False, account_status="suspended")
    _mk_user(db, "r@of1.kr", is_active=False, account_status="replaced")
    with pytest.raises(act.ActivationError) as e1:
        act.reissue_activation_token("s@of1.kr", actor="sys")
    assert e1.value.code == "SUSPENDED"
    with pytest.raises(act.ActivationError) as e2:
        act.reissue_activation_token("r@of1.kr", actor="sys")
    assert e2.value.code == "REPLACED"


# ── 11: replace 시 기존 토큰 폐기 ─────────────────────────────────────────────
def test_replace_revokes_old_tokens(db):
    from backend.services import account_lifecycle_pg_service as life
    _mk_tenant(db, seat_limit=2)
    _mk_user(db, "admin@of1.kr", is_admin=True)
    old_raw = _mk_invited_with_token(db, "old@of1.kr")
    life.replace_user("old@of1.kr", "새이름", "new@of1.kr", actor="admin@of1.kr", new_role="office_staff")
    assert _token_used(db, old_raw) is True


# ── 12: tenant suspend 시 소속 미사용 토큰 전부 폐기 ──────────────────────────
def test_tenant_suspend_revokes_all_unused_tokens(db):
    from backend.services import account_lifecycle_pg_service as life
    _mk_tenant(db, seat_limit=3)
    r1 = _mk_invited_with_token(db, "a@of1.kr")
    r2 = _mk_invited_with_token(db, "b@of1.kr")
    life.suspend_tenant("of-1", actor="sys")
    assert _token_used(db, r1) is True
    assert _token_used(db, r2) is True


# ── 13~15: 동시 activation 경쟁 (실제 FOR UPDATE) ─────────────────────────────
def test_concurrent_activation_seat_race(db):
    from backend.services import activation_pg_service as act
    # seat_limit=2, 활성 admin 1 → 남은 좌석 1. invited 2명이 동시에 활성화 시도.
    _mk_tenant(db, seat_limit=2)
    _mk_user(db, "admin@of1.kr", is_admin=True)
    raw1 = _mk_invited_with_token(db, "u1@of1.kr")
    raw2 = _mk_invited_with_token(db, "u2@of1.kr")

    def _try(raw):
        try:
            act.complete_activation(raw, "password123")
            return ("ok", None)
        except act.ActivationError as e:
            return ("err", e.code)

    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(_try, [raw1, raw2]))

    oks = [r for r in results if r[0] == "ok"]
    errs = [r for r in results if r[0] == "err"]
    assert len(oks) == 1, results          # 정확히 1건 성공
    assert len(errs) == 1, results         # 정확히 1건 실패
    assert errs[0][1] == "SEAT_LIMIT", results
    # 실패한 요청의 토큰은 미소비여야 한다.
    used1, used2 = _token_used(db, raw1), _token_used(db, raw2)
    assert [used1, used2].count(True) == 1   # 성공분만 소비
    assert [used1, used2].count(False) == 1  # 실패분 미소비


# ── 16: seat_limit=2 두 초대 계정 순차 활성화 성공 ────────────────────────────
def test_two_invited_activate_within_seat_limit(db):
    from backend.services import activation_pg_service as act
    _mk_tenant(db, seat_limit=2, service_status="pending_activation")
    raw1 = _mk_invited_with_token(db, "u1@of1.kr")
    raw2 = _mk_invited_with_token(db, "u2@of1.kr")
    r1 = act.complete_activation(raw1, "password123")
    r2 = act.complete_activation(raw2, "password123")
    assert r1["login_id"] == "u1@of1.kr" and r2["login_id"] == "u2@of1.kr"
    # 첫 활성화가 tenant 를 active 로 승격했는지 확인.
    from backend.db.models.tenant import Tenant
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == "of-1"))
        assert t.service_status == "active" and t.is_active is True
