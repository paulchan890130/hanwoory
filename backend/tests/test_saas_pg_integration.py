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
from sqlalchemy import create_engine, text, select, func
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


# ── 3: invited suspend 자체가 거부(정책) — 토큰 유효 유지, 활성화 링크는 정상 ──
def test_invited_suspend_rejected_token_still_valid(db):
    """invited 계정은 정지 자체가 INVITED 로 거부된다(suspend→restore 우회 원천 차단).

    기존 정책(invited 를 suspend 로 만든 뒤 토큰 폐기)에서 변경: invited 정지 불가 →
    토큰 무변경 → 활성화 링크를 통한 정상 활성화는 그대로 가능해야 한다.
    """
    from backend.services import activation_pg_service as act
    from backend.services import account_lifecycle_pg_service as life
    _mk_tenant(db, seat_limit=2, service_status="pending_activation")
    raw = _mk_invited_with_token(db, "inv@of1.kr")
    with pytest.raises(life.LifecycleError) as ei:
        life.suspend_user("inv@of1.kr", actor="sys")
    assert ei.value.code == "INVITED"
    assert _token_used(db, raw) is False          # 정지 실패 → 토큰 미폐기
    r = act.complete_activation(raw, "password123")  # 링크 활성화는 정상
    assert r["login_id"] == "inv@of1.kr"


# ── 3b: suspend 상태 전이 강제 (active 만 정지 가능) ──────────────────────────
def test_suspend_state_transitions(db):
    from backend.services import account_lifecycle_pg_service as life
    _mk_tenant(db, seat_limit=5)
    _mk_user(db, "active@of1.kr", is_active=True, account_status="active")
    _mk_user(db, "rep@of1.kr", is_active=False, account_status="replaced")
    _mk_user(db, "dis@of1.kr", is_active=False, account_status="disabled")
    _mk_invited_with_token(db, "inv@of1.kr")

    # replaced → 거부(REPLACED)
    with pytest.raises(life.LifecycleError) as e1:
        life.suspend_user("rep@of1.kr", actor="sys")
    assert e1.value.code == "REPLACED"
    # invited → 거부(INVITED)
    with pytest.raises(life.LifecycleError) as e2:
        life.suspend_user("inv@of1.kr", actor="sys")
    assert e2.value.code == "INVITED"
    # disabled(레거시) → 거부(LEGACY_DISABLED)
    with pytest.raises(life.LifecycleError) as e3:
        life.suspend_user("dis@of1.kr", actor="sys")
    assert e3.value.code == "LEGACY_DISABLED"
    # active → 성공
    r = life.suspend_user("active@of1.kr", actor="sys")
    assert r["account_status"] == "suspended"
    # 재정지 → ALREADY_SUSPENDED(멱등 거부)
    with pytest.raises(life.LifecycleError) as e4:
        life.suspend_user("active@of1.kr", actor="sys")
    assert e4.value.code == "ALREADY_SUSPENDED"


# ── 3c: replaced suspend→restore 우회 불가 (두 다리 모두 차단) ────────────────
def test_replaced_suspend_restore_bypass_blocked(db):
    from backend.services import account_lifecycle_pg_service as life
    _mk_tenant(db, seat_limit=5)
    _mk_user(db, "rep@of1.kr", is_active=False, account_status="replaced")
    # 1) suspend 다리 차단.
    with pytest.raises(life.LifecycleError) as e1:
        life.suspend_user("rep@of1.kr", actor="sys")
    assert e1.value.code == "REPLACED"
    # 2) restore 다리도 차단(설령 상태가 어떻게든 suspended 로 갔다 해도 replaced 는 복구불가).
    with pytest.raises(life.LifecycleError) as e2:
        life.restore_user("rep@of1.kr", actor="sys")
    assert e2.value.code == "REPLACED"


# ── 3d: office_admin 경로 — replaced/invited 서브계정 직접 정지 차단 ──────────
def test_office_suspend_sub_state_transitions(db):
    from backend.services import account_lifecycle_pg_service as life
    _mk_tenant(db, seat_limit=5)
    _mk_user(db, "admin@of1.kr", is_admin=True, is_active=True, account_status="active")
    _mk_user(db, "rep@of1.kr", is_admin=False, is_active=False, account_status="replaced")
    _mk_user(db, "inv@of1.kr", is_admin=False, is_active=False, account_status="invited")
    _mk_user(db, "act@of1.kr", is_admin=False, is_active=True, account_status="active")

    with pytest.raises(life.LifecycleError) as e1:
        life.office_suspend_sub("of-1", "admin@of1.kr", "rep@of1.kr")
    assert e1.value.code == "REPLACED"
    with pytest.raises(life.LifecycleError) as e2:
        life.office_suspend_sub("of-1", "admin@of1.kr", "inv@of1.kr")
    assert e2.value.code == "INVITED"
    # active 서브계정은 정상 정지.
    r = life.office_suspend_sub("of-1", "admin@of1.kr", "act@of1.kr")
    assert r["account_status"] == "suspended"


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


# ── 17: tenant lifecycle 상태 제한 ────────────────────────────────────────────
def test_restore_tenant_state_restrictions(db):
    from backend.services import account_lifecycle_pg_service as life
    from backend.db.models.tenant import Tenant
    # active → ALREADY_ACTIVE
    _mk_tenant(db, tid="of-act", service_status="active")
    with pytest.raises(life.LifecycleError) as e1:
        life.restore_tenant("of-act", actor="sys")
    assert e1.value.code == "ALREADY_ACTIVE"
    # terminated → 복구 거부(종착)
    _mk_tenant(db, tid="of-term", service_status="terminated")
    with pytest.raises(life.LifecycleError) as e2:
        life.restore_tenant("of-term", actor="sys")
    assert e2.value.code == "TENANT_TERMINATED"
    # pending → BAD_TENANT_STATE
    _mk_tenant(db, tid="of-pend", service_status="pending_activation")
    with pytest.raises(life.LifecycleError) as e3:
        life.restore_tenant("of-pend", actor="sys")
    assert e3.value.code == "BAD_TENANT_STATE"
    # suspended → 복구 성공
    _mk_tenant(db, tid="of-susp", service_status="suspended")
    r = life.restore_tenant("of-susp", actor="sys")
    assert r["service_status"] == "active"
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == "of-susp"))
        assert t.service_status == "active" and t.is_active is True


def test_suspend_terminated_tenant_blocked(db):
    from backend.services import account_lifecycle_pg_service as life
    from backend.db.models.tenant import Tenant
    _mk_tenant(db, tid="of-term", service_status="terminated")
    with pytest.raises(life.LifecycleError) as e:
        life.suspend_tenant("of-term", actor="sys")
    assert e.value.code == "TENANT_TERMINATED"
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == "of-term"))
        assert t.service_status == "terminated"  # 종착 상태 무변경


# ── 18: tenant suspend ↔ reissue 동시 실행(실제 FOR UPDATE) ──────────────────
def _count_unused_tokens(db, tenant_id="of-1"):
    from backend.db.models.activation_token import ActivationToken
    with db() as s:
        return s.scalar(select(func.count()).select_from(ActivationToken).where(
            ActivationToken.tenant_id == tenant_id,
            ActivationToken.used_at.is_(None))) or 0


def test_concurrent_tenant_suspend_and_reissue(db):
    """tenant suspend 와 activation 재발급이 동시에 일어나도 최종 미사용 토큰은 0개.

    A(reissue 선행): 새 토큰 발급→commit 후 suspend 가 폐기 → 0.
    B(suspend 선행): tenant suspended → reissue 는 잠금대기 후 TENANT_SUSPENDED → 미발급 → 0.
    어느 순서든 정지 사무소에 유효한 활성화 토큰이 남으면 안 된다.
    """
    from backend.services import account_lifecycle_pg_service as life
    from backend.services import activation_pg_service as act
    _mk_tenant(db, seat_limit=5, service_status="active")
    _mk_user(db, "inv@of1.kr", is_active=False, account_status="invited")

    def _suspend():
        try:
            life.suspend_tenant("of-1", actor="sys")
            return ("suspend", "ok")
        except life.LifecycleError as e:
            return ("suspend", e.code)

    def _reissue():
        try:
            act.reissue_activation_token("inv@of1.kr", actor="sys")
            return ("reissue", "ok")
        except act.ActivationError as e:
            return ("reissue", e.code)

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(_reissue), ex.submit(_suspend)]
        _ = [f.result() for f in futs]

    assert _count_unused_tokens(db, "of-1") == 0   # 정지 사무소에 유효 토큰 0개

    from backend.db.models.tenant import Tenant
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == "of-1"))
        assert t.service_status == "suspended"


# ── 19: tenant suspend ↔ user restore 동시 실행(실제 FOR UPDATE) ─────────────
def test_concurrent_tenant_suspend_and_user_restore(db):
    """suspended user restore 와 동일 tenant suspend 동시 실행.

    허용되는 최종 상태는 둘 중 하나:
      1) restore 선행: user active + 이후 tenant suspended(로그인은 tenant 로 차단)
      2) suspend 선행: restore 는 TENANT_SUSPENDED 로 거부 + user suspended 유지
    'tenant suspended 인데 user 가 active 로 복구 성공'이 되면 안 된다(불일치 금지).
    """
    from backend.services import account_lifecycle_pg_service as life
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    _mk_tenant(db, seat_limit=5, service_status="active")
    _mk_user(db, "s@of1.kr", is_active=False, account_status="suspended")

    def _restore():
        try:
            life.restore_user("s@of1.kr", actor="sys")
            return ("restore", "ok")
        except life.LifecycleError as e:
            return ("restore", e.code)

    def _suspend():
        life.suspend_tenant("of-1", actor="sys")
        return ("suspend", "ok")

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(_restore), ex.submit(_suspend)]
        results = dict(f.result() for f in futs)

    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == "of-1"))
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == "s@of1.kr"))
        assert t.service_status == "suspended"  # suspend 는 항상 반영됨
        if results.get("restore") == "ok":
            # restore 가 tenant 잠금을 먼저 잡음 → user active 지만 tenant 는 이후 정지.
            assert u.account_status == "active"
        else:
            # suspend 선행 → restore 는 TENANT_SUSPENDED 거부, user suspended 유지.
            assert results["restore"] == "TENANT_SUSPENDED"
            assert u.account_status == "suspended"


# ── 20~22: 전역 잠금 순서 통일 — activation/replace ↔ tenant suspend 데드락 없음 ──
# 표준 순서 user→tenant→token. suspend_tenant 는 tenant→token. 어느 순서든 데드락/500 없이
# 완료되고(future.result timeout), 허용된 최종 상태만 나오며 정지 tenant 미사용 token 은 0.
def test_concurrent_activation_and_tenant_suspend(db):
    from backend.services import activation_pg_service as act
    from backend.services import account_lifecycle_pg_service as life
    from backend.db.models.tenant import Tenant
    _mk_tenant(db, seat_limit=3, service_status="active")
    raw = _mk_invited_with_token(db, "inv@of1.kr")

    def _activate():
        try:
            act.complete_activation(raw, "password123")
            return ("act", "ok")
        except act.ActivationError as e:
            return ("act", e.code)

    def _suspend():
        life.suspend_tenant("of-1", actor="sys")
        return ("suspend", "ok")

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(_activate), ex.submit(_suspend)]
        results = dict(f.result(timeout=20) for f in futs)  # 데드락이면 여기서 타임아웃/에러

    assert results["suspend"] == "ok"
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == "of-1"))
        assert t.service_status == "suspended"           # suspend 성공 → 최종 suspended
    if results["act"] == "ok":
        assert _token_used(db, raw) is True              # A. activation 선행 → token 소비
    else:
        assert results["act"] in ("TENANT_SUSPENDED", "BAD_TOKEN"), results  # B. suspend 선행
    assert _count_unused_tokens(db, "of-1") == 0         # 정지 tenant 미사용 token 0


def test_concurrent_system_replace_and_tenant_suspend(db):
    from backend.services import account_lifecycle_pg_service as life
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    _mk_tenant(db, seat_limit=5, service_status="active")
    _mk_user(db, "admin@of1.kr", is_admin=True, is_active=True, account_status="active")
    _mk_user(db, "staff@of1.kr", is_admin=False, is_active=True, account_status="active")

    def _replace():
        try:
            life.replace_user("staff@of1.kr", "새이름", "new@of1.kr",
                              actor="admin@of1.kr", new_role="office_staff")
            return ("replace", "ok")
        except life.LifecycleError as e:
            return ("replace", e.code)

    def _suspend():
        life.suspend_tenant("of-1", actor="sys")
        return ("suspend", "ok")

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(_replace), ex.submit(_suspend)]
        results = dict(f.result(timeout=20) for f in futs)

    assert results["suspend"] == "ok"
    assert _count_unused_tokens(db, "of-1") == 0         # 교체가 새 token 을 냈어도 suspend 가 폐기
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == "of-1"))
        assert t.service_status == "suspended"
        old = s.scalar(select(AccountUser).where(AccountUser.login_id == "staff@of1.kr"))
        new = s.scalar(select(AccountUser).where(AccountUser.login_id == "new@of1.kr"))
        if results["replace"] == "ok":
            assert old.account_status == "replaced" and new is not None and new.account_status == "invited"
        else:
            assert results["replace"] == "TENANT_SUSPENDED", results
            assert new is None and old.account_status == "active"   # 교체 미실행


def test_concurrent_office_replace_and_tenant_suspend(db):
    from backend.services import account_lifecycle_pg_service as life
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    _mk_tenant(db, seat_limit=5, service_status="active")
    _mk_user(db, "admin@of1.kr", is_admin=True, is_active=True, account_status="active")
    _mk_user(db, "staff@of1.kr", is_admin=False, is_active=True, account_status="active")

    def _replace():
        try:
            life.office_replace_sub("of-1", "admin@of1.kr", "staff@of1.kr", "새이름", "new@of1.kr")
            return ("replace", "ok")
        except life.LifecycleError as e:
            return ("replace", e.code)

    def _suspend():
        life.suspend_tenant("of-1", actor="sys")
        return ("suspend", "ok")

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(_replace), ex.submit(_suspend)]
        results = dict(f.result(timeout=20) for f in futs)

    assert results["suspend"] == "ok"
    assert _count_unused_tokens(db, "of-1") == 0
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == "of-1"))
        assert t.service_status == "suspended"
        new = s.scalar(select(AccountUser).where(AccountUser.login_id == "new@of1.kr"))
        if results["replace"] != "ok":
            assert results["replace"] == "TENANT_SUSPENDED", results
            assert new is None


# ── 23: 동일 activation token 동시 complete 2건 → 정확히 1건만 성공 ────────────
def test_concurrent_same_token_activation(db):
    from backend.services import activation_pg_service as act
    _mk_tenant(db, seat_limit=3, service_status="pending_activation")
    raw = _mk_invited_with_token(db, "inv@of1.kr")

    def _try(_i):
        try:
            act.complete_activation(raw, "password123")
            return ("ok", None)
        except act.ActivationError as e:
            return ("err", e.code)

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(_try, i) for i in (0, 1)]
        results = [f.result(timeout=20) for f in futs]

    oks = [r for r in results if r[0] == "ok"]
    errs = [r for r in results if r[0] == "err"]
    assert len(oks) == 1, results        # 정확히 1건 성공
    assert len(errs) == 1, results        # 정확히 1건 실패
    assert errs[0][1] == "BAD_TOKEN", results
    assert _token_used(db, raw) is True   # 성공분이 소비
