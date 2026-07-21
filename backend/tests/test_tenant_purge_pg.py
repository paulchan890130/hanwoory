"""사업장 전체 폐기 + 계정 연결(relink) + 스키마 커버리지 — **실제 PostgreSQL** 통합 테스트.

계정 삭제와 사업장 폐기의 데이터 수명 분리, cross-tenant 격리, 미분류 테이블/외부저장소/상태
가드, rollback, relink 가드를 실제 FK·트랜잭션에서 검증한다. TEST_DATABASE_URL 없으면 skip.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import create_engine, text, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

_BASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
# 전체 스키마를 만드는 테스트라 다른 PG 테스트(4개 테이블만 관리)와 섞이지 않도록 전용 DB 사용.
TEST_DB_URL = ""
if _BASE_URL:
    _u = make_url(_BASE_URL)
    # str(url) 은 비밀번호를 *** 로 가린다 → render_as_string(hide_password=False) 사용.
    TEST_DB_URL = _u.set(database=(_u.database or "kid") + "_purge").render_as_string(hide_password=False)
pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="TEST_DATABASE_URL 미설정 — 실제 PostgreSQL 통합 테스트 skip")


def _ensure_database(url_str: str) -> None:
    url = make_url(url_str)
    admin_url = url.set(database="postgres")
    eng = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with eng.connect() as c:
            if not c.execute(text("SELECT 1 FROM pg_database WHERE datname=:n"),
                             {"n": url.database}).first():
                c.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        eng.dispose()


@pytest.fixture(scope="module")
def engine():
    _ensure_database(TEST_DB_URL)
    eng = create_engine(TEST_DB_URL, future=True, pool_size=5, max_overflow=5)
    import backend.db.models  # noqa: F401  — 모든 모델을 Base.metadata 에 등록
    from backend.db.base import Base
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine, monkeypatch):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "get_sessionmaker", lambda: SessionLocal)
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    from backend.db.base import Base
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    return SessionLocal


# ── seed ──────────────────────────────────────────────────────────────────────
def _seed_tenant(db, tid, *, service_status="suspended", is_active=False,
                 admin_login=None, staff_login=None, with_data=True, folder_id=None):
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.models.customer import Customer
    from backend.db.models.task import ActiveTask, CompletedTask
    from backend.db.models.memo import Memo
    from backend.db.models.event import Event
    from backend.db.models.certification import CertGroup
    from backend.db.models.work_data import WorkReferenceRow
    from backend.db.models.board import BoardPost
    from backend.db.models.user_session import UserSession
    from backend.db.models.activation_token import ActivationToken
    from backend.db.models.login_attempt import LoginAttempt
    from backend.db.models.office_application import OfficeApplication
    admin_login = admin_login or f"admin@{tid}.kr"
    staff_login = staff_login or f"staff@{tid}.kr"
    with db() as s:
        t = Tenant(tenant_id=tid, office_name=f"사무소-{tid}", is_active=is_active, folder_id=folder_id)
        t.service_status = service_status
        t.seat_limit = 2
        s.add(t)
        s.flush()  # tenants 를 먼저 insert(자연키 FK — ORM 이 순서를 자동 추론하지 않음).
        s.add(AccountUser(login_id=admin_login, tenant_id=tid, password_hash="x",
                          is_admin=True, is_active=is_active, account_status="active" if is_active else "suspended"))
        s.add(AccountUser(login_id=staff_login, tenant_id=tid, password_hash="x",
                          is_admin=False, is_active=is_active, account_status="active" if is_active else "suspended"))
        if with_data:
            s.add(Customer(tenant_id=tid, customer_id="0001"))
            s.add(ActiveTask(tenant_id=tid, task_id="T1"))
            s.add(CompletedTask(tenant_id=tid, task_id="CT1"))
            s.add(Memo(tenant_id=tid, kind="short"))
            s.add(Event(tenant_id=tid, date_str="2026-01-01", event_text="x"))
            s.add(CertGroup(id=f"cg-{tid}", tenant_id=tid))
            s.add(WorkReferenceRow(tenant_id=tid, sheet_name="업무참고", row_index=0))
            s.add(BoardPost(id=f"bp-{tid}", tenant_id=tid))
        s.add(UserSession(login_id=admin_login, tenant_id=tid, session_id=f"sid-{tid}"))
        s.add(ActivationToken(token_hash=f"h-{tid}", login_id=staff_login, tenant_id=tid,
                              expires_at=datetime.now(timezone.utc) + timedelta(hours=72)))
        s.add(LoginAttempt(login_id=admin_login))
        s.add(OfficeApplication(application_id=f"APP-{tid}", office_name=f"사무소-{tid}",
                                status="approved", approved_tenant_id=tid))
        s.commit()
    return admin_login, staff_login


def _count(db, table, col, val):
    with db() as s:
        return int(s.execute(text(f"SELECT count(*) FROM {table} WHERE {col}=:v"), {"v": val}).scalar())


# ── 스키마 커버리지: 미분류 tenant_id 테이블이 없어야 한다 ────────────────────
def test_purge_plan_covers_all_tenant_tables(db):
    from backend.services import tenant_purge_pg_service as p
    with db() as s:
        missing = p.unclassified_tenant_tables(s)
    assert missing == [], f"purge plan 에 분류되지 않은 tenant_id 테이블: {missing}"


# ── preview count 정확성 + can_purge ─────────────────────────────────────────
def test_preview_counts_and_can_purge(db):
    from backend.services import tenant_purge_pg_service as p
    _seed_tenant(db, "of-a")
    pv = p.purge_preview("of-a", actor_login="sys")
    assert pv["users"] == 2
    assert pv["customers"] == 1
    assert pv["active_tasks"] == 1 and pv["completed_tasks"] == 1
    assert pv["counts"]["cert_groups"] == 1
    assert pv["counts"]["login_attempts"] == 1     # 간접(login_id) 집계
    assert pv["applications"] == 1                  # approved_tenant_id 집계
    assert pv["can_purge"] is True                  # suspended + inactive + 외부저장소 없음


def test_active_tenant_purge_blocked(db):
    from backend.services import tenant_purge_pg_service as p
    _seed_tenant(db, "of-a", service_status="active", is_active=True)
    pv = p.purge_preview("of-a", actor_login="sys")
    assert pv["can_purge"] is False
    with pytest.raises(p.PurgeError) as ei:
        p.purge_tenant("of-a", "sys", "of-a", "사무소-of-a", "사업장 전체 폐기")
    assert ei.value.code == "BAD_STATE"


def test_confirmation_mismatch_blocked(db):
    from backend.services import tenant_purge_pg_service as p
    _seed_tenant(db, "of-a")
    for ct, cn, ph in [("wrong", "사무소-of-a", "사업장 전체 폐기"),
                       ("of-a", "wrong", "사업장 전체 폐기"),
                       ("of-a", "사무소-of-a", "폐기")]:
        with pytest.raises(p.PurgeError) as ei:
            p.purge_tenant("of-a", "sys", ct, cn, ph)
        assert ei.value.code == "CONFIRM_MISMATCH"
    assert _count(db, "customers", "tenant_id", "of-a") == 1  # 무변경


def test_external_storage_blocks_purge(db):
    from backend.services import tenant_purge_pg_service as p
    _seed_tenant(db, "of-a", folder_id="drive-folder-xyz")
    pv = p.purge_preview("of-a", actor_login="sys")
    assert pv["can_purge"] is False and pv["external_storage"]
    with pytest.raises(p.PurgeError) as ei:
        p.purge_tenant("of-a", "sys", "of-a", "사무소-of-a", "사업장 전체 폐기")
    assert ei.value.code == "EXTERNAL_STORAGE"
    assert _count(db, "customers", "tenant_id", "of-a") == 1  # 무변경


def test_master_and_actor_tenant_protected(db):
    from backend.services import tenant_purge_pg_service as p
    # actor 가 이 tenant 소속 → 차단.
    admin_login, _ = _seed_tenant(db, "of-a")
    with pytest.raises(p.PurgeError) as ei:
        p.purge_tenant("of-a", admin_login, "of-a", "사무소-of-a", "사업장 전체 폐기")
    assert ei.value.code == "PROTECTED"
    # 마스터 계정이 소속된 tenant → 차단.
    _seed_tenant(db, "of-m", admin_login="wkdwhfl")
    pv = p.purge_preview("of-m", actor_login="sys")
    assert pv["can_purge"] is False


def test_unclassified_table_blocks_purge(db, engine):
    from backend.services import tenant_purge_pg_service as p
    _seed_tenant(db, "of-a")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS zz_rogue_tenant (id serial primary key, tenant_id text)"))
    try:
        with db() as s:
            assert "zz_rogue_tenant" in p.unclassified_tenant_tables(s)
        pv = p.purge_preview("of-a", actor_login="sys")
        assert pv["can_purge"] is False
        with pytest.raises(p.PurgeError) as ei:
            p.purge_tenant("of-a", "sys", "of-a", "사무소-of-a", "사업장 전체 폐기")
        assert ei.value.code == "UNCLASSIFIED_TABLES"
    finally:
        with engine.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS zz_rogue_tenant"))


def test_purge_deletes_a_keeps_b(db):
    from backend.services import tenant_purge_pg_service as p
    _seed_tenant(db, "of-a")
    _seed_tenant(db, "of-b")
    res = p.purge_tenant("of-a", "sys", "of-a", "사무소-of-a", "사업장 전체 폐기")
    assert res["ok"] is True and res["deleted_total"] > 0
    # A 전부 삭제.
    for tbl in ("customers", "active_tasks", "completed_tasks", "memos", "events",
                "cert_groups", "work_reference_rows", "board_posts", "user_sessions",
                "activation_tokens", "users"):
        assert _count(db, tbl, "tenant_id", "of-a") == 0, tbl
    assert _count(db, "office_applications", "approved_tenant_id", "of-a") == 0
    assert _count(db, "login_attempts", "login_id", "admin@of-a.kr") == 0
    with db() as s:
        from backend.db.models.tenant import Tenant
        assert s.scalar(select(Tenant).where(Tenant.tenant_id == "of-a")) is None
    # B 무변경.
    for tbl in ("customers", "active_tasks", "completed_tasks", "users"):
        assert _count(db, tbl, "tenant_id", "of-b") == 1 if tbl != "users" else True, tbl
    assert _count(db, "users", "tenant_id", "of-b") == 2
    assert _count(db, "customers", "tenant_id", "of-b") == 1
    with db() as s:
        from backend.db.models.tenant import Tenant
        assert s.scalar(select(Tenant).where(Tenant.tenant_id == "of-b")) is not None


def test_purge_rollback_on_midway_error(db, monkeypatch):
    from backend.services import tenant_purge_pg_service as p
    _seed_tenant(db, "of-a")
    # 존재하지 않는 테이블을 목록에 끼워 넣어 중간에 DELETE 실패 → 전체 rollback.
    orig = p._existing_tables
    monkeypatch.setattr(p, "_existing_tables", lambda s: orig(s) | {"zz_missing_table"})
    monkeypatch.setattr(p, "PURGE_BY_TENANT_ID", ["customers", "zz_missing_table", "users"])
    with pytest.raises(Exception):
        p.purge_tenant("of-a", "sys", "of-a", "사무소-of-a", "사업장 전체 폐기")
    # customers 는 목록상 zz 앞이지만 트랜잭션이 통째 롤백돼 그대로 남아야 한다.
    assert _count(db, "customers", "tenant_id", "of-a") == 1
    assert _count(db, "users", "tenant_id", "of-a") == 2


# ── 계정 삭제(로그인 계정만)와 데이터 수명 분리 ──────────────────────────────
def test_account_delete_keeps_tenant_data(db):
    from backend.services import tenant_purge_pg_service as p
    from backend.db.models.user import AccountUser
    _seed_tenant(db, "of-a")
    with db() as s:
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == "staff@of-a.kr"))
        s.delete(u); s.commit()   # 계정만 삭제(하드 삭제 흉내) — 데이터 무접촉
    with db() as s:
        assert p.tenant_data_counts(s, "of-a")["customers"] == 1
        assert p.tenant_data_counts(s, "of-a")["active_tasks"] == 1


# ── issue-admin-account ──────────────────────────────────────────────────────
def test_issue_admin_account(db):
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.user import AccountUser
    # 사용자 없는(정리 대상) tenant.
    from backend.db.models.tenant import Tenant
    with db() as s:
        t = Tenant(tenant_id="of-empty", office_name="빈사무소", is_active=False)
        t.service_status = "suspended"; t.seat_limit = 2
        s.add(t); s.commit()
    r = ta.issue_admin_account("of-empty", "새관리자", "newadmin@x.kr", actor="sys",
                               confirm_tenant_id="of-empty")
    assert r["role"] == "office_admin" and r["account_status"] == "invited" and r["activation_token"]
    with db() as s:
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == "newadmin@x.kr"))
        assert u.is_admin is True and u.is_active is False and u.tenant_id == "of-empty"


# ── relink ───────────────────────────────────────────────────────────────────
def test_relink_moves_account_keeps_data(db):
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.user import AccountUser
    from backend.db.models.tenant import Tenant
    # source: 사용자 1명, 데이터 없음. target: 여유 있는 tenant.
    with db() as s:
        for tid in ("src", "tgt"):
            t = Tenant(tenant_id=tid, office_name=tid, is_active=True); t.service_status = "active"; t.seat_limit = 2
            s.add(t)
        s.flush()
        s.add(AccountUser(login_id="movable@x.kr", tenant_id="src", password_hash="x",
                          is_admin=False, is_active=False, account_status="suspended"))
        s.commit()
    pv = ta.relink_preview("movable@x.kr", "tgt", actor_login="sys")
    assert pv["can_relink"] is True
    r = ta.relink_account("movable@x.kr", "tgt", "sys", "movable@x.kr", "tgt")
    assert r["to_tenant_id"] == "tgt" and r["activation_token"]
    with db() as s:
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == "movable@x.kr"))
        assert u.tenant_id == "tgt" and u.account_status == "invited" and u.is_active is False


def test_relink_blocked_when_source_has_data_or_active(db):
    from backend.services import tenant_admin_pg_service as ta
    admin_login, staff_login = _seed_tenant(db, "of-a", service_status="active", is_active=True)
    from backend.db.models.tenant import Tenant
    with db() as s:
        t = Tenant(tenant_id="tgt", office_name="tgt", is_active=True); t.service_status = "active"; t.seat_limit = 5
        s.add(t); s.commit()
    # active 계정 + 원본에 데이터·다른 사용자 존재 → 차단.
    pv = ta.relink_preview(staff_login, "tgt", actor_login="sys")
    assert pv["can_relink"] is False
    with pytest.raises(ta.TenantAdminError) as ei:
        ta.relink_account(staff_login, "tgt", "sys", staff_login, "tgt")
    assert ei.value.code == "BLOCKED"


def test_relink_master_and_actor_blocked(db):
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.user import AccountUser
    from backend.db.models.tenant import Tenant
    with db() as s:
        for tid in ("src", "tgt"):
            t = Tenant(tenant_id=tid, office_name=tid, is_active=True); t.service_status = "active"; t.seat_limit = 5
            s.add(t)
        s.flush()
        s.add(AccountUser(login_id="wkdwhfl", tenant_id="src", password_hash="x",
                          is_admin=True, is_active=False, account_status="suspended"))
        s.commit()
    pv = ta.relink_preview("wkdwhfl", "tgt", actor_login="sys")
    assert pv["can_relink"] is False   # 마스터 차단
