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
    # 사용자 없는(정리 대상) tenant — pending_activation(발급 가능 상태).
    from backend.db.models.tenant import Tenant
    with db() as s:
        t = Tenant(tenant_id="of-empty", office_name="빈사무소", is_active=False)
        t.service_status = "pending_activation"; t.seat_limit = 2
        s.add(t); s.commit()
    r = ta.issue_admin_account("of-empty", "새관리자", "newadmin@x.kr", actor="sys",
                               confirm_tenant_id="of-empty")
    assert r["role"] == "office_admin" and r["account_status"] == "invited" and r["activation_token"]
    with db() as s:
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == "newadmin@x.kr"))
        assert u.is_admin is True and u.is_active is False and u.tenant_id == "of-empty"


# ── relink ───────────────────────────────────────────────────────────────────
_PHRASE_RELINK = "계정 사업장 연결 변경"


def _seed_relink_pair(db, *, src="src", tgt="tgt", acct="movable@x.kr",
                      account_status="invited", acct_active=False, is_admin=False,
                      src_status="suspended", src_active=False, tgt_seat=5):
    """relink 시나리오 seed: 유효한 원본(정지+비활성 기본)에 계정 1명, 여유 있는 대상 tenant."""
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    with db() as s:
        t1 = Tenant(tenant_id=src, office_name=src, is_active=src_active)
        t1.service_status = src_status; t1.seat_limit = 2
        t2 = Tenant(tenant_id=tgt, office_name=tgt, is_active=True)
        t2.service_status = "active"; t2.seat_limit = tgt_seat
        s.add(t1); s.add(t2); s.flush()
        s.add(AccountUser(login_id=acct, tenant_id=src, password_hash="x",
                          is_admin=is_admin, is_active=acct_active, account_status=account_status))
        s.commit()
    return acct, src, tgt


def test_relink_moves_account_keeps_data(db):
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.user import AccountUser
    # source: 정지+비활성, 계정 invited+비활성, 데이터 없음. target: 활성·여유 있음.
    acct, src, tgt = _seed_relink_pair(db)
    pv = ta.relink_preview(acct, tgt, actor_login="sys")
    assert pv["can_relink"] is True
    assert pv["role_after"] == "office_staff"
    assert pv["account"]["current_role"] == "office_staff" and pv["account"]["account_status"] == "invited"
    assert pv["source_tenant"]["tenant_id"] == src and pv["target_tenant"]["tenant_id"] == tgt
    assert "seat_limit" in pv["target_tenant"] and "user_count" in pv["source_tenant"]
    r = ta.relink_account(acct, tgt, "sys", acct, tgt,
                          confirmation_phrase=_PHRASE_RELINK, source_tenant_id=src)
    assert r["to_tenant_id"] == tgt and r["activation_token"] and r["role_after"] == "office_staff"
    with db() as s:
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == acct))
        assert u.tenant_id == tgt and u.account_status == "invited" and u.is_active is False
        assert u.is_admin is False


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
        ta.relink_account(staff_login, "tgt", "sys", staff_login, "tgt",
                          confirmation_phrase=_PHRASE_RELINK, source_tenant_id="of-a")
    assert ei.value.code == "BLOCKED"


# ── §1 suspended tenant 새 관리자 발급 정책 ───────────────────────────────────
def test_issue_admin_suspended_tenant_blocked_then_restore(db):
    from backend.services import tenant_admin_pg_service as ta
    from backend.services import account_lifecycle_pg_service as lc
    from backend.services import activation_pg_service as act
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.models.customer import Customer
    with db() as s:
        t = Tenant(tenant_id="of-susp", office_name="정지사무소", is_active=False)
        t.service_status = "suspended"; t.seat_limit = 2
        s.add(t); s.flush()
        s.add(Customer(tenant_id="of-susp", customer_id="0001"))  # 기존 업무 데이터
        s.commit()
    # 정지 사무소 → 발급 거부(unusable token 미발급).
    with pytest.raises(ta.TenantAdminError) as ei:
        ta.issue_admin_account("of-susp", "새관리자", "susadmin@x.kr", actor="sys", confirm_tenant_id="of-susp")
    assert ei.value.code == "TENANT_SUSPENDED"
    assert _count(db, "users", "login_id", "susadmin@x.kr") == 0        # user 생성 없음
    assert _count(db, "activation_tokens", "tenant_id", "of-susp") == 0  # token 생성 없음
    # 사업장 복구 후 발급 성공.
    lc.restore_tenant("of-susp", "sys")
    r = ta.issue_admin_account("of-susp", "새관리자", "susadmin@x.kr", actor="sys", confirm_tenant_id="of-susp")
    assert r["activation_token"] and r["role"] == "office_admin"
    # 발급 토큰으로 활성화 성공.
    res = act.complete_activation(r["activation_token"], "pw12345")
    assert res["login_id"] == "susadmin@x.kr"
    with db() as s:
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == "susadmin@x.kr"))
        assert u.is_active is True and u.is_admin is True and u.tenant_id == "of-susp"
        # 활성화 후 기존 tenant 고객 데이터 접근 가능(무접촉).
        assert int(s.execute(text("SELECT count(*) FROM customers WHERE tenant_id=:v"),
                             {"v": "of-susp"}).scalar()) == 1


# ── §2 relink 계정 상태 allowlist ─────────────────────────────────────────────
@pytest.mark.parametrize("status,active,ok", [
    ("invited", False, True),
    ("suspended", False, False),
    ("replaced", False, False),
    ("active", True, False),
    ("disabled", False, False),  # 레거시 비활성(비-SaaS 상태) → fail-closed
])
def test_relink_account_status_allowlist(db, status, active, ok):
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.user import AccountUser
    acct, src, tgt = _seed_relink_pair(db, account_status=status, acct_active=active)
    pv = ta.relink_preview(acct, tgt, actor_login="sys")
    assert pv["can_relink"] is ok
    if not ok:
        with pytest.raises(ta.TenantAdminError) as ei:
            ta.relink_account(acct, tgt, "sys", acct, tgt,
                              confirmation_phrase=_PHRASE_RELINK, source_tenant_id=src)
        assert ei.value.code == "BLOCKED"
        # 실패 시 tenant_id·status·token·session 무변경.
        with db() as s:
            u = s.scalar(select(AccountUser).where(AccountUser.login_id == acct))
            assert u.tenant_id == src
        assert _count(db, "activation_tokens", "tenant_id", tgt) == 0


# ── §3 시스템 관리자(master + SYSTEM_ADMIN_LOGIN_IDS) relink 차단 ─────────────
def test_relink_system_admin_blocked(db, monkeypatch):
    from backend.services import tenant_admin_pg_service as ta
    monkeypatch.setenv("SYSTEM_ADMIN_LOGIN_IDS", "sysop@x.kr")
    # master
    ta_acct, src, tgt = _seed_relink_pair(db, acct="wkdwhfl", src="s1", tgt="t1")
    assert ta.relink_preview("wkdwhfl", "t1", actor_login="sys")["can_relink"] is False
    # SYSTEM_ADMIN_LOGIN_IDS 계정
    _seed_relink_pair(db, acct="sysop@x.kr", src="s2", tgt="t2")
    assert ta.relink_preview("sysop@x.kr", "t2", actor_login="sys")["can_relink"] is False
    # 현재 actor 본인
    _seed_relink_pair(db, acct="me@x.kr", src="s3", tgt="t3")
    assert ta.relink_preview("me@x.kr", "t3", actor_login="me@x.kr")["can_relink"] is False
    # 일반 office_staff invited → 다른 조건 충족 시 허용
    _seed_relink_pair(db, acct="staff@x.kr", src="s4", tgt="t4")
    assert ta.relink_preview("staff@x.kr", "t4", actor_login="sys")["can_relink"] is True


# ── §4 원본 사업장 상태 제한 ──────────────────────────────────────────────────
@pytest.mark.parametrize("src_status,src_active,ok", [
    ("active", True, False),
    ("terminated", False, False),
    ("suspended", False, True),
    ("pending_activation", False, True),
])
def test_relink_source_tenant_state(db, src_status, src_active, ok):
    from backend.services import tenant_admin_pg_service as ta
    acct, src, tgt = _seed_relink_pair(db, src_status=src_status, src_active=src_active)
    assert ta.relink_preview(acct, tgt, actor_login="sys")["can_relink"] is ok


# ── §5 원본 데이터 전수 검사(대표 몇 개 아님) ─────────────────────────────────
def _add_source_row(db, tid, model_factory):
    with db() as s:
        s.add(model_factory()); s.commit()


@pytest.mark.parametrize("factory_name", ["fixed_expense", "document_metadata", "signature", "cert_price"])
def test_relink_blocked_by_any_residual_data(db, factory_name):
    from backend.services import tenant_admin_pg_service as ta
    acct, src, tgt = _seed_relink_pair(db)
    from backend.db.models.finance import FixedExpense
    from backend.db.models.document import DocumentMetadata
    from backend.db.models.signature import CustomerSignature
    from backend.db.models.certification import CertPrice
    factories = {
        "fixed_expense": lambda: FixedExpense(tenant_id=src, expense_id="e1", year_month="2026-01"),
        "document_metadata": lambda: DocumentMetadata(tenant_id=src, drive_file_id="drv1"),
        "signature": lambda: CustomerSignature(tenant_id=src, customer_id="0001", signature_data="x"),
        "cert_price": lambda: CertPrice(id="cp-1", tenant_id=src),
    }
    _add_source_row(db, src, factories[factory_name])
    pv = ta.relink_preview(acct, tgt, actor_login="sys")
    assert pv["can_relink"] is False
    assert pv["source_tenant"]["residual_data_counts"]  # 잔여 데이터 노출
    with pytest.raises(ta.TenantAdminError) as ei:
        ta.relink_account(acct, tgt, "sys", acct, tgt,
                          confirmation_phrase=_PHRASE_RELINK, source_tenant_id=src)
    assert ei.value.code == "BLOCKED"


def test_relink_ok_when_source_empty(db):
    from backend.services import tenant_admin_pg_service as ta
    acct, src, tgt = _seed_relink_pair(db)
    assert ta.relink_preview(acct, tgt, actor_login="sys")["can_relink"] is True


# ── §8 relink 강한 확인(문구 + 원본 tenant 불변) ─────────────────────────────
def test_relink_strong_confirmation(db):
    from backend.services import tenant_admin_pg_service as ta
    acct, src, tgt = _seed_relink_pair(db)
    # 잘못된 확인 문구.
    with pytest.raises(ta.TenantAdminError) as ei:
        ta.relink_account(acct, tgt, "sys", acct, tgt,
                          confirmation_phrase="틀린문구", source_tenant_id=src)
    assert ei.value.code == "CONFIRM_MISMATCH"
    # source_tenant_id 가 실제 원본과 다름(preview 이후 변경) → 거부.
    with pytest.raises(ta.TenantAdminError) as ei:
        ta.relink_account(acct, tgt, "sys", acct, tgt,
                          confirmation_phrase=_PHRASE_RELINK, source_tenant_id="다른원본")
    assert ei.value.code == "CONFIRM_MISMATCH"
    # 전부 정확 → 성공.
    r = ta.relink_account(acct, tgt, "sys", acct, tgt,
                          confirmation_phrase=_PHRASE_RELINK, source_tenant_id=src)
    assert r["to_tenant_id"] == tgt


# ── §9 기존 audit_logs 삭제 + PII 없는 요약만 보존 ────────────────────────────
def test_purge_deletes_audit_logs_pii_free(db):
    from backend.services import tenant_purge_pg_service as p
    from backend.db.models.audit import AuditLog
    # 요약 audit 은 이제 폐기 트랜잭션 내부에서 직접 기록되므로 FEATURE_PG_AUDIT 와 무관하게 남는다(§6).
    _seed_tenant(db, "of-a")
    _seed_tenant(db, "of-b")
    with db() as s:
        s.add(AuditLog(tenant_id="of-a", action="login", actor_login_id="admin@of-a.kr"))
        s.add(AuditLog(tenant_id="of-a", action="task_edit"))
        s.add(AuditLog(tenant_id="of-b", action="login"))
        s.commit()
    res = p.purge_tenant("of-a", "sys", "of-a", "사무소-of-a", "사업장 전체 폐기")
    assert res["ok"] is True
    # A audit 삭제, B 유지.
    assert _count(db, "audit_logs", "tenant_id", "of-a") == 0
    assert _count(db, "audit_logs", "tenant_id", "of-b") == 1
    # 새 요약 audit 1건: PII 없음(raw tenant ID 미포함), hash + 건수만.
    with db() as s:
        summ = s.scalars(select(AuditLog).where(AuditLog.action == "tenant_purged")).all()
        assert len(summ) == 1
        row = summ[0]
        assert row.tenant_id is None
        assert row.target_id == p._hash_tid("of-a")
        assert "of-a" not in (row.payload or {}).get("tenant_id_hash", "")
        assert "tenant_id_hash" in (row.payload or {}) and "deleted_counts" in (row.payload or {})
        # payload/target 어디에도 원문 tenant_id 없음.
        import json
        assert "of-a" not in json.dumps(row.payload or {})


# ── §10 local-* 모의 저장소는 폐기 차단하지 않음 ──────────────────────────────
def test_local_sentinel_storage_not_blocking(db):
    from backend.services import tenant_purge_pg_service as p
    _seed_tenant(db, "of-a", folder_id="local-folder-abc")
    from backend.db.models.tenant import Tenant
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == "of-a"))
        t.customer_sheet_key = "local-sheet-xyz"; s.commit()
    pv = p.purge_preview("of-a", actor_login="sys")
    assert pv["external_storage"] == [] and pv["can_purge"] is True
    assert pv["local_storage_refs"].get("folder_id") == "local-folder-abc"
    # 실제 폐기까지 성공(로컬 sentinel 은 fail-closed 대상 아님).
    res = p.purge_tenant("of-a", "sys", "of-a", "사무소-of-a", "사업장 전체 폐기")
    assert res["ok"] is True


def test_real_external_storage_blocks_and_mixed(db):
    from backend.services import tenant_purge_pg_service as p
    from backend.db.models.tenant import Tenant
    # 실제 ID → 차단.
    _seed_tenant(db, "of-real", folder_id="1AbCrealDriveId")
    pv = p.purge_preview("of-real", actor_login="sys")
    assert pv["can_purge"] is False and pv["external_storage_refs"].get("folder_id") == "1AbCrealDriveId"
    # local + real 혼합 → 실제 ID 때문에 차단.
    _seed_tenant(db, "of-mix", folder_id="local-mock")
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == "of-mix"))
        t.work_sheet_key = "realSheetKey123"; s.commit()
    pv2 = p.purge_preview("of-mix", actor_login="sys")
    assert pv2["can_purge"] is False
    assert pv2["local_storage_refs"].get("folder_id") == "local-mock"
    assert pv2["external_storage_refs"].get("work_sheet_key") == "realSheetKey123"


# ── §11 중복 관리자 초대 차단 ─────────────────────────────────────────────────
def test_issue_admin_duplicate_blocked(db):
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser

    def _mk(tid, admin_status, admin_active):
        with db() as s:
            t = Tenant(tenant_id=tid, office_name=tid, is_active=True)
            t.service_status = "active"; t.seat_limit = 3
            s.add(t); s.flush()
            s.add(AccountUser(login_id=f"boss@{tid}.kr", tenant_id=tid, password_hash="x",
                              is_admin=True, is_active=admin_active, account_status=admin_status))
            s.commit()
    # 활성 관리자 존재 → 차단.
    _mk("of-act", "active", True)
    with pytest.raises(ta.TenantAdminError) as ei:
        ta.issue_admin_account("of-act", "또관리자", "n1@x.kr", actor="sys", confirm_tenant_id="of-act")
    assert ei.value.code == "DUPLICATE_ADMIN"
    # 초대 관리자 존재 → 차단.
    _mk("of-inv", "invited", False)
    with pytest.raises(ta.TenantAdminError) as ei:
        ta.issue_admin_account("of-inv", "또관리자", "n2@x.kr", actor="sys", confirm_tenant_id="of-inv")
    assert ei.value.code == "DUPLICATE_ADMIN"
    # 정지 관리자만 존재 → 발급 허용(활성/초대 아님).
    _mk("of-sus", "suspended", False)
    r = ta.issue_admin_account("of-sus", "복구관리자", "n3@x.kr", actor="sys", confirm_tenant_id="of-sus")
    assert r["activation_token"]


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


# ══════════════════════════════════════════════════════════════════════════════
# 라운드2 하드닝 — target 상태/강한확인/JWT binding/좌석예약/세션·감사 원자성
# ══════════════════════════════════════════════════════════════════════════════

# ── §1 relink 대상 tenant 상태 검증 ───────────────────────────────────────────
@pytest.mark.parametrize("tgt_status,tgt_active,ok", [
    ("pending_activation", False, True),
    ("active", True, True),
    ("suspended", False, False),
    ("terminated", False, False),
    ("active", False, False),            # service_status↔is_active 불일치 → fail-closed
    ("pending_activation", True, False),  # 불일치 → fail-closed
])
def test_relink_target_tenant_state(db, tgt_status, tgt_active, ok):
    from backend.services import tenant_admin_pg_service as ta
    from backend.services import activation_pg_service as act
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    with db() as s:
        src = Tenant(tenant_id="src", office_name="src", is_active=False)
        src.service_status = "suspended"; src.seat_limit = 2
        tgt = Tenant(tenant_id="tgt", office_name="tgt", is_active=tgt_active)
        tgt.service_status = tgt_status; tgt.seat_limit = 5
        s.add(src); s.add(tgt); s.flush()
        s.add(AccountUser(login_id="m@x.kr", tenant_id="src", password_hash="x",
                          is_admin=False, is_active=False, account_status="invited"))
        s.commit()
    pv = ta.relink_preview("m@x.kr", "tgt", actor_login="sys")
    assert pv["can_relink"] is ok
    if ok:
        r = ta.relink_account("m@x.kr", "tgt", "sys", "m@x.kr", "tgt",
                              confirmation_phrase=_PHRASE_RELINK, source_tenant_id="src")
        # 발급된 token 이 실제 활성화 가능(처음부터 사용 불가 토큰이 아님, §5-7).
        res = act.complete_activation(r["activation_token"], "pw12345")
        assert res["login_id"] == "m@x.kr"
    else:
        with pytest.raises(ta.TenantAdminError) as ei:
            ta.relink_account("m@x.kr", "tgt", "sys", "m@x.kr", "tgt",
                              confirmation_phrase=_PHRASE_RELINK, source_tenant_id="src")
        assert ei.value.code == "BLOCKED"
        # 차단 시 user/token/session 무변경.
        with db() as s:
            u = s.scalar(select(AccountUser).where(AccountUser.login_id == "m@x.kr"))
            assert u.tenant_id == "src" and u.account_status == "invited" and u.is_active is False
        assert _count(db, "activation_tokens", "tenant_id", "tgt") == 0


# ── §2 source_tenant_id 강한 확인 우회 차단 ───────────────────────────────────
def test_relink_source_tenant_id_required(db):
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.user import AccountUser
    acct, src, tgt = _seed_relink_pair(db)
    # 빈 문자열 / 공백만 → CONFIRM_MISMATCH(우회 불가).
    for bad in ("", "   "):
        with pytest.raises(ta.TenantAdminError) as ei:
            ta.relink_account(acct, tgt, "sys", acct, tgt,
                              confirmation_phrase=_PHRASE_RELINK, source_tenant_id=bad)
        assert ei.value.code == "CONFIRM_MISMATCH"
    # 잘못된 값 → CONFIRM_MISMATCH.
    with pytest.raises(ta.TenantAdminError) as ei:
        ta.relink_account(acct, tgt, "sys", acct, tgt,
                          confirmation_phrase=_PHRASE_RELINK, source_tenant_id="wrong")
    assert ei.value.code == "CONFIRM_MISMATCH"
    # 우회 실패 시 무변경.
    with db() as s:
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == acct))
        assert u.tenant_id == src
    # 정확한 값 → 성공.
    r = ta.relink_account(acct, tgt, "sys", acct, tgt,
                          confirmation_phrase=_PHRASE_RELINK, source_tenant_id=src)
    assert r["to_tenant_id"] == tgt


def test_relink_request_model_requires_source_tenant_id():
    # 프론트 검증과 무관하게 직접 API 호출에서도 source_tenant_id 누락은 422(pydantic 필수).
    import pydantic
    from backend.routers.office_applications import RelinkRequest
    with pytest.raises(pydantic.ValidationError):
        RelinkRequest(login_id="a", target_tenant_id="t",
                      confirm_login_id="a", confirm_target_tenant_id="t",
                      confirmation_phrase="계정 사업장 연결 변경")  # source_tenant_id 누락


# ── §3 JWT tenant binding ─────────────────────────────────────────────────────
def _seed_active_user(db, login, tid):
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    with db() as s:
        if not s.scalar(select(Tenant).where(Tenant.tenant_id == tid)):
            t = Tenant(tenant_id=tid, office_name=tid, is_active=True)
            t.service_status = "active"; t.seat_limit = 5
            s.add(t); s.flush()
        s.add(AccountUser(login_id=login, tenant_id=tid, password_hash="x",
                          is_admin=False, is_active=True, account_status="active"))
        s.commit()


def test_jwt_tenant_binding_blocks_stale_tenant(db, monkeypatch):
    from fastapi import HTTPException
    from backend.auth import get_current_user, create_access_token
    monkeypatch.setenv("FEATURE_SINGLE_SESSION", "0")
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "0")
    # 계정은 현재 target 소속(활성) — relink 후 target 에서 활성화된 상태를 모사.
    _seed_active_user(db, "user@x.kr", "tgt")
    # 이전(source) tenant 를 가리키는 기존 JWT → 불일치 → 401 TENANT_MEMBERSHIP_CHANGED.
    stale = create_access_token({"sub": "user@x.kr", "tenant_id": "src", "is_admin": False, "role": "user"})
    with pytest.raises(HTTPException) as ei:
        get_current_user(stale)
    assert ei.value.status_code == 401
    assert (ei.value.detail or {}).get("code") == "TENANT_MEMBERSHIP_CHANGED"
    # FEATURE_SINGLE_SESSION=1 에서도 동일(무관하게 적용).
    monkeypatch.setenv("FEATURE_SINGLE_SESSION", "1")
    with pytest.raises(HTTPException) as ei2:
        get_current_user(stale)
    assert (ei2.value.detail or {}).get("code") == "TENANT_MEMBERSHIP_CHANGED"
    monkeypatch.setenv("FEATURE_SINGLE_SESSION", "0")
    # 새 JWT(target) → 정상 접근, tenant_id=target.
    fresh = create_access_token({"sub": "user@x.kr", "tenant_id": "tgt", "is_admin": True, "role": "admin"})
    cu = get_current_user(fresh)
    assert cu["tenant_id"] == "tgt"
    assert cu["is_admin"] is False  # 권한은 DB 가 source of truth(강등 반영), tenant 는 일치 → 통과


def test_jwt_same_tenant_role_change_ok(db, monkeypatch):
    from backend.auth import get_current_user, create_access_token
    monkeypatch.setenv("FEATURE_SINGLE_SESSION", "0")
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "0")
    _seed_active_user(db, "same@x.kr", "tgt")
    # tenant 동일 + JWT 권한만 stale(admin) → 401 아님, DB 권한으로 정규화.
    tok = create_access_token({"sub": "same@x.kr", "tenant_id": "tgt", "is_admin": True, "role": "admin"})
    cu = get_current_user(tok)
    assert cu["tenant_id"] == "tgt" and cu["is_admin"] is False


# ── §5 초대 좌석 예약(active + invited) ───────────────────────────────────────
def test_invitation_capacity_counts_invited(db):
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    # target: seat_limit=2, 활성 1명 → reserved=1.
    with db() as s:
        t = Tenant(tenant_id="tgt", office_name="tgt", is_active=True); t.service_status = "active"; t.seat_limit = 2
        s.add(t); s.flush()
        s.add(AccountUser(login_id="act@tgt.kr", tenant_id="tgt", password_hash="x",
                          is_admin=True, is_active=True, account_status="active"))
        # 두 개의 source(각각 invited 계정 1명, 정지+비활성 사업장).
        for i in (1, 2):
            src = Tenant(tenant_id=f"s{i}", office_name=f"s{i}", is_active=False)
            src.service_status = "suspended"; src.seat_limit = 2
            s.add(src); s.flush()
            s.add(AccountUser(login_id=f"inv{i}@x.kr", tenant_id=f"s{i}", password_hash="x",
                              is_admin=False, is_active=False, account_status="invited"))
        s.commit()
    # 첫 relink → reserved 1+1=2 <= 2 → 성공. 이후 target reserved=2(활성1+초대1).
    r = ta.relink_account("inv1@x.kr", "tgt", "sys", "inv1@x.kr", "tgt",
                          confirmation_phrase=_PHRASE_RELINK, source_tenant_id="s1")
    assert r["to_tenant_id"] == "tgt"
    # 둘째 relink → reserved 2+1=3 > 2 → 좌석 없음(초대 계정도 예약으로 계산).
    pv = ta.relink_preview("inv2@x.kr", "tgt", actor_login="sys")
    assert pv["can_relink"] is False
    with pytest.raises(ta.TenantAdminError) as ei:
        ta.relink_account("inv2@x.kr", "tgt", "sys", "inv2@x.kr", "tgt",
                          confirmation_phrase=_PHRASE_RELINK, source_tenant_id="s2")
    assert ei.value.code in ("BLOCKED", "SEAT_LIMIT")


def test_issue_admin_blocked_when_invited_reserves_seat(db):
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    # active 1 + invited 1, seat_limit=2 → 추가 관리자 발급 차단(활성만 세면 통과됐을 상황).
    with db() as s:
        t = Tenant(tenant_id="of-x", office_name="of-x", is_active=True); t.service_status = "active"; t.seat_limit = 2
        s.add(t); s.flush()
        s.add(AccountUser(login_id="staff@of-x.kr", tenant_id="of-x", password_hash="x",
                          is_admin=False, is_active=True, account_status="active"))
        s.add(AccountUser(login_id="inv@of-x.kr", tenant_id="of-x", password_hash="x",
                          is_admin=False, is_active=False, account_status="invited"))
        s.commit()
    with pytest.raises(ta.TenantAdminError) as ei:
        ta.issue_admin_account("of-x", "새관리자", "boss@of-x.kr", actor="sys", confirm_tenant_id="of-x")
    assert ei.value.code == "SEAT_LIMIT"
    assert _count(db, "users", "login_id", "boss@of-x.kr") == 0


def test_invitation_capacity_excludes_suspended_replaced(db):
    from backend.services.account_lifecycle_pg_service import reserved_seat_count
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    with db() as s:
        t = Tenant(tenant_id="of-r", office_name="of-r", is_active=True); t.service_status = "active"; t.seat_limit = 5
        s.add(t); s.flush()
        s.add(AccountUser(login_id="a@of-r.kr", tenant_id="of-r", password_hash="x", is_admin=True, is_active=True, account_status="active"))
        s.add(AccountUser(login_id="i@of-r.kr", tenant_id="of-r", password_hash="x", is_admin=False, is_active=False, account_status="invited"))
        s.add(AccountUser(login_id="s@of-r.kr", tenant_id="of-r", password_hash="x", is_admin=False, is_active=False, account_status="suspended"))
        s.add(AccountUser(login_id="r@of-r.kr", tenant_id="of-r", password_hash="x", is_admin=False, is_active=False, account_status="replaced"))
        s.commit()
    with db() as s:
        assert reserved_seat_count(s, "of-r") == 2  # active + invited 만(suspended/replaced 제외)


def test_invitation_capacity_concurrent_relink_one_wins(db):
    import threading
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    # target seat_limit=2, 활성 1명 → 남은 예약 1자리. 두 계정이 동시에 relink 시도.
    with db() as s:
        t = Tenant(tenant_id="tgt", office_name="tgt", is_active=True); t.service_status = "active"; t.seat_limit = 2
        s.add(t); s.flush()
        s.add(AccountUser(login_id="act@tgt.kr", tenant_id="tgt", password_hash="x", is_admin=True, is_active=True, account_status="active"))
        for i in (1, 2):
            src = Tenant(tenant_id=f"s{i}", office_name=f"s{i}", is_active=False)
            src.service_status = "suspended"; src.seat_limit = 2
            s.add(src); s.flush()
            s.add(AccountUser(login_id=f"c{i}@x.kr", tenant_id=f"s{i}", password_hash="x",
                              is_admin=False, is_active=False, account_status="invited"))
        s.commit()
    results: list = []
    def _try(login, src):
        try:
            ta.relink_account(login, "tgt", "sys", login, "tgt",
                              confirmation_phrase=_PHRASE_RELINK, source_tenant_id=src)
            results.append(("ok", login))
        except Exception as e:  # noqa: BLE001
            results.append(("err", getattr(e, "code", type(e).__name__)))
    threads = [threading.Thread(target=_try, args=(f"c{i}@x.kr", f"s{i}")) for i in (1, 2)]
    for t in threads: t.start()
    for t in threads: t.join()
    oks = [r for r in results if r[0] == "ok"]
    errs = [r for r in results if r[0] == "err"]
    assert len(oks) == 1 and len(errs) == 1, results  # 정확히 한 건만 성공(FOR UPDATE 직렬화)


# ── §4 relink 세션 revoke 원자성(같은 트랜잭션·실패 시 롤백) ──────────────────
def test_relink_session_revoke_failure_rolls_back(db, monkeypatch):
    from backend.services import tenant_admin_pg_service as ta
    from backend.services import session_pg_service as sps
    from backend.db.models.user import AccountUser
    acct, src, tgt = _seed_relink_pair(db)
    def _boom(*a, **k):
        raise RuntimeError("revoke failed")
    monkeypatch.setattr(sps, "revoke_active_sessions_in_session", _boom)
    with pytest.raises(Exception):
        ta.relink_account(acct, tgt, "sys", acct, tgt,
                          confirmation_phrase=_PHRASE_RELINK, source_tenant_id=src)
    # 전체 롤백 — tenant_id·상태 무변경, 새 토큰 없음.
    with db() as s:
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == acct))
        assert u.tenant_id == src and u.account_status == "invited" and u.is_active is False
    assert _count(db, "activation_tokens", "tenant_id", tgt) == 0


# ── §6 purge 감사 요약 원자성(같은 트랜잭션·실패 시 폐기 롤백) ────────────────
def test_purge_summary_failure_rolls_back(db, monkeypatch):
    from backend.services import tenant_purge_pg_service as p
    from backend.db.models.audit import AuditLog
    _seed_tenant(db, "of-a")
    with db() as s:
        s.add(AuditLog(tenant_id="of-a", action="login")); s.commit()
    def _boom(*a, **k):
        raise RuntimeError("summary insert failed")
    monkeypatch.setattr(p, "_write_purge_summary", _boom)
    with pytest.raises(Exception):
        p.purge_tenant("of-a", "sys", "of-a", "사무소-of-a", "사업장 전체 폐기")
    # 폐기 전체 롤백 — tenant·고객·사용자·기존 audit 모두 유지, 요약 미기록.
    assert _count(db, "customers", "tenant_id", "of-a") == 1
    assert _count(db, "users", "tenant_id", "of-a") == 2
    assert _count(db, "audit_logs", "tenant_id", "of-a") == 1
    with db() as s:
        assert s.scalars(select(AuditLog).where(AuditLog.action == "tenant_purged")).all() == []
        from backend.db.models.tenant import Tenant
        assert s.scalar(select(Tenant).where(Tenant.tenant_id == "of-a")) is not None


def test_purge_summary_actor_preserved_no_pii(db):
    from backend.services import tenant_purge_pg_service as p
    from backend.db.models.audit import AuditLog
    import json
    _seed_tenant(db, "of-a")
    p.purge_tenant("of-a", "sysop@admin.kr", "of-a", "사무소-of-a", "사업장 전체 폐기")
    with db() as s:
        row = s.scalars(select(AuditLog).where(AuditLog.action == "tenant_purged")).one()
        assert row.actor_login_id == "sysop@admin.kr"     # 운영자 식별자는 보존
        assert row.tenant_id is None and row.target_id == p._hash_tid("of-a")
        # 대상 tenant/고객 PII 없음.
        assert "of-a" not in json.dumps(row.payload or {})
        assert "admin@of-a.kr" not in json.dumps(row.payload or {})


# ══════════════════════════════════════════════════════════════════════════════
# 라운드3 — tenant service_status 엄격 판정(미상/빈 값 fail-closed)
# ══════════════════════════════════════════════════════════════════════════════

def _set_tenant_status(db, tid, status, is_active):
    from backend.db.models.tenant import Tenant
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == tid))
        t.service_status = status
        t.is_active = is_active
        s.commit()


# ── relink 대상: 미상/빈/공백/불일치 상태 fail-closed ─────────────────────────
@pytest.mark.parametrize("status,active", [
    ("maintenance", True),          # 미상 + 활성 → (레거시 폴백이면 active 로 통과했을 값)
    ("maintenance", False),         # 미상 + 비활성 → (폴백이면 pending 로 통과했을 값)
    ("", False),                    # 빈 값
    ("   ", True),                  # 공백만
    ("unknown", False),             # 신규 미정의 값
    ("active", False),              # 상태↔is_active 불일치
    ("pending_activation", True),   # 불일치
])
def test_relink_target_invalid_status_fail_closed(db, status, active):
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.user import AccountUser
    acct, src, tgt = _seed_relink_pair(db)
    _set_tenant_status(db, tgt, status, active)
    pv = ta.relink_preview(acct, tgt, actor_login="sys")
    assert pv["can_relink"] is False
    with pytest.raises(ta.TenantAdminError) as ei:
        ta.relink_account(acct, tgt, "sys", acct, tgt,
                          confirmation_phrase=_PHRASE_RELINK, source_tenant_id=src)
    assert ei.value.code == "BLOCKED"
    with db() as s:  # 차단 시 user/token/session 무변경
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == acct))
        assert u.tenant_id == src and u.account_status == "invited" and u.is_active is False
    assert _count(db, "activation_tokens", "tenant_id", tgt) == 0


def test_relink_target_valid_status_ok(db):
    from backend.services import tenant_admin_pg_service as ta
    from backend.services import activation_pg_service as act
    # active+활성 허용.
    acct, src, tgt = _seed_relink_pair(db)
    _set_tenant_status(db, tgt, "active", True)
    r = ta.relink_account(acct, tgt, "sys", acct, tgt,
                          confirmation_phrase=_PHRASE_RELINK, source_tenant_id=src)
    assert act.complete_activation(r["activation_token"], "pw12345")["login_id"] == acct
    # pending_activation+비활성 허용.
    acct2, src2, tgt2 = _seed_relink_pair(db, src="s9", tgt="t9", acct="m9@x.kr")
    _set_tenant_status(db, tgt2, "pending_activation", False)
    r2 = ta.relink_account(acct2, tgt2, "sys", acct2, tgt2,
                           confirmation_phrase=_PHRASE_RELINK, source_tenant_id=src2)
    assert act.complete_activation(r2["activation_token"], "pw12345")["login_id"] == acct2


# ── issue_admin: 미상/빈 상태 발급 차단 ───────────────────────────────────────
@pytest.mark.parametrize("status", ["maintenance", "", "   ", "unknown"])
def test_issue_admin_invalid_status_blocked(db, status):
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.tenant import Tenant
    with db() as s:
        t = Tenant(tenant_id="of-u", office_name="of-u", is_active=True)
        t.service_status = status; t.seat_limit = 2
        s.add(t); s.commit()
    with pytest.raises(ta.TenantAdminError) as ei:
        ta.issue_admin_account("of-u", "관리자", "u@x.kr", actor="sys", confirm_tenant_id="of-u")
    assert ei.value.code == "BAD_TENANT_STATE"
    assert _count(db, "users", "login_id", "u@x.kr") == 0        # user 무변경
    assert _count(db, "activation_tokens", "tenant_id", "of-u") == 0  # token 미발급


# ── activation verify/complete: 초대 후 상태 오염 시 fail-closed ──────────────
def test_activation_invalid_tenant_status_fail_closed(db):
    from backend.services import tenant_admin_pg_service as ta
    from backend.services import activation_pg_service as act
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    with db() as s:
        t = Tenant(tenant_id="of-p", office_name="of-p", is_active=False)
        t.service_status = "pending_activation"; t.seat_limit = 2
        s.add(t); s.commit()
    token = ta.issue_admin_account("of-p", "관리자", "p@x.kr", actor="sys",
                                   confirm_tenant_id="of-p")["activation_token"]
    _set_tenant_status(db, "of-p", "maintenance", True)  # 초대 후 미상 값으로 오염
    assert act.verify_activation_token(token) is None    # verify 무효
    with pytest.raises(act.ActivationError) as ei:
        act.complete_activation(token, "pw12345")
    assert ei.value.code == "BAD_TENANT_STATE"
    with db() as s:  # user invited·inactive 유지 + 토큰 미소비
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == "p@x.kr"))
        assert u.is_active is False and u.account_status == "invited"
        tok = s.execute(text("SELECT used_at FROM activation_tokens WHERE login_id='p@x.kr'")).first()
        assert tok is not None and tok[0] is None


# ── reissue: 미상 상태에서 재발급 차단 + 기존 토큰 무변경 ─────────────────────
def test_reissue_invalid_tenant_status_blocked(db):
    from backend.services import tenant_admin_pg_service as ta
    from backend.services import activation_pg_service as act
    from backend.db.models.tenant import Tenant
    with db() as s:
        t = Tenant(tenant_id="of-p2", office_name="of-p2", is_active=False)
        t.service_status = "pending_activation"; t.seat_limit = 2
        s.add(t); s.commit()
    ta.issue_admin_account("of-p2", "관리자", "p2@x.kr", actor="sys", confirm_tenant_id="of-p2")
    _set_tenant_status(db, "of-p2", "unknown", False)
    with pytest.raises(act.ActivationError) as ei:
        act.reissue_activation_token("p2@x.kr", actor="sys")
    assert ei.value.code == "BAD_TENANT_STATE"
    with db() as s:  # 기존 미사용 토큰 1개·미소비 유지
        rows = s.execute(text("SELECT used_at FROM activation_tokens WHERE login_id='p2@x.kr'")).fetchall()
        assert len(rows) == 1 and rows[0][0] is None


# ── 엄격 helper 단위 검증 ─────────────────────────────────────────────────────
def test_strict_tenant_status_helper():
    from backend.services import account_state as st

    class _T:
        def __init__(self, s, a): self.service_status = s; self.is_active = a
    # 정의된 상태만 그대로, 미상/빈/공백/None → None.
    assert st.strict_tenant_status_of(_T("active", True)) == "active"
    assert st.strict_tenant_status_of(_T("pending_activation", False)) == "pending_activation"
    assert st.strict_tenant_status_of(_T("maintenance", True)) is None
    assert st.strict_tenant_status_of(_T("", False)) is None
    assert st.strict_tenant_status_of(_T("   ", False)) is None
    assert st.strict_tenant_status_of(_T(None, True)) is None
    assert st.strict_tenant_status_of(None) is None
    # activation 가능 = pending+비활성 / active+활성만.
    assert st.activation_capable_tenant_block_reason(_T("pending_activation", False)) is None
    assert st.activation_capable_tenant_block_reason(_T("active", True)) is None
    assert st.activation_capable_tenant_block_reason(_T("active", False))[0] == "BAD_TENANT_STATE"
    assert st.activation_capable_tenant_block_reason(_T("maintenance", True))[0] == "BAD_TENANT_STATE"
    assert st.activation_capable_tenant_block_reason(_T("suspended", False))[0] == "TENANT_SUSPENDED"
    assert st.activation_capable_tenant_block_reason(_T("terminated", False))[0] == "TENANT_TERMINATED"
    assert st.activation_capable_tenant_block_reason(None)[0] == "NOT_FOUND"


# ══════════════════════════════════════════════════════════════════════════════
# 라운드4 — 계정 교체(replace) + relink 원본 tenant 엄격 상태
# ══════════════════════════════════════════════════════════════════════════════

def _seed_replace_target(db, tid, status, active, *, old="old",
                         is_admin=False, old_active=True, old_status="active"):
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    login = f"{old}@{tid}.kr"
    with db() as s:
        t = Tenant(tenant_id=tid, office_name=tid, is_active=active)
        t.service_status = status; t.seat_limit = 3
        s.add(t); s.flush()
        s.add(AccountUser(login_id=login, tenant_id=tid, password_hash="x",
                          is_admin=is_admin, is_active=old_active, account_status=old_status))
        s.commit()
    return login


# ── §2 replace_user(시스템 관리자): tenant 엄격 상태 ──────────────────────────
@pytest.mark.parametrize("status,active,code", [
    ("maintenance", True, "BAD_TENANT_STATE"),
    ("maintenance", False, "BAD_TENANT_STATE"),
    ("", True, "BAD_TENANT_STATE"),
    ("   ", False, "BAD_TENANT_STATE"),
    ("unknown", False, "BAD_TENANT_STATE"),
    ("active", False, "BAD_TENANT_STATE"),
    ("pending_activation", True, "BAD_TENANT_STATE"),
    ("suspended", False, "TENANT_SUSPENDED"),
    ("terminated", False, "TENANT_TERMINATED"),
])
def test_replace_user_invalid_tenant_state_blocked(db, status, active, code):
    from backend.services import account_lifecycle_pg_service as life
    from backend.db.models.user import AccountUser
    old = _seed_replace_target(db, "of-rep", status, active)
    with pytest.raises(life.LifecycleError) as ei:
        life.replace_user(old, "새이름", "new@of-rep.kr", actor="sys", new_role="office_staff")
    assert ei.value.code == code
    with db() as s:  # 기존 계정 무변경 + 신규 계정/토큰 없음
        u = s.scalar(select(AccountUser).where(AccountUser.login_id == old))
        assert u.account_status == "active" and u.is_active is True and u.replaced_by_user_id is None
        assert s.scalar(select(AccountUser).where(AccountUser.login_id == "new@of-rep.kr")) is None
    assert _count(db, "activation_tokens", "tenant_id", "of-rep") == 0


def test_replace_user_active_tenant_ok(db):
    from backend.services import account_lifecycle_pg_service as life
    from backend.services import activation_pg_service as act
    from backend.db.models.user import AccountUser
    old = _seed_replace_target(db, "of-ok", "active", True)
    rep = life.replace_user(old, "새직원", "new@of-ok.kr", actor="sys", new_role="office_staff")
    assert rep["new_login_id"] == "new@of-ok.kr"
    with db() as s:
        o = s.scalar(select(AccountUser).where(AccountUser.login_id == old))
        n = s.scalar(select(AccountUser).where(AccountUser.login_id == "new@of-ok.kr"))
        assert o.account_status == "replaced" and o.is_active is False
        assert n.account_status == "invited" and n.is_active is False
        assert o.replaced_by_user_id == n.id
    assert act.complete_activation(rep["activation_token"], "pw12345")["login_id"] == "new@of-ok.kr"


def test_replace_user_pending_tenant_ok(db):
    from backend.services import account_lifecycle_pg_service as life
    from backend.services import activation_pg_service as act
    from backend.db.models.tenant import Tenant
    # pending+비활성 사무소의 invited 계정 교체 → activation 후 tenant active+is_active=True.
    old = _seed_replace_target(db, "of-pd", "pending_activation", False,
                               old_active=False, old_status="invited")
    rep = life.replace_user(old, "새직원", "new@of-pd.kr", actor="sys", new_role="office_staff")
    assert act.complete_activation(rep["activation_token"], "pw12345")["login_id"] == "new@of-pd.kr"
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == "of-pd"))
        assert t.service_status == "active" and t.is_active is True


# ── §3 office_replace_sub(사무소 관리자): tenant 엄격 상태 + 권한 유지 ────────
def _seed_office(db, tid, status, active):
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    with db() as s:
        t = Tenant(tenant_id=tid, office_name=tid, is_active=active)
        t.service_status = status; t.seat_limit = 3
        s.add(t); s.flush()
        s.add(AccountUser(login_id=f"boss@{tid}.kr", tenant_id=tid, password_hash="x",
                          is_admin=True, is_active=True, account_status="active"))
        s.add(AccountUser(login_id=f"staff@{tid}.kr", tenant_id=tid, password_hash="x",
                          is_admin=False, is_active=True, account_status="active"))
        s.commit()


@pytest.mark.parametrize("status,active,code", [
    ("maintenance", True, "BAD_TENANT_STATE"),
    ("unknown", False, "BAD_TENANT_STATE"),
    ("", True, "BAD_TENANT_STATE"),
    ("active", False, "BAD_TENANT_STATE"),
    ("pending_activation", True, "BAD_TENANT_STATE"),
    ("suspended", False, "TENANT_SUSPENDED"),
    ("terminated", False, "TENANT_TERMINATED"),
])
def test_office_replace_sub_invalid_tenant_state_blocked(db, status, active, code):
    from backend.services import account_lifecycle_pg_service as life
    from backend.db.models.user import AccountUser
    _seed_office(db, "of-of", "active", True)
    _set_tenant_status(db, "of-of", status, active)
    with pytest.raises(life.LifecycleError) as ei:
        life.office_replace_sub("of-of", "boss@of-of.kr", "staff@of-of.kr", "새직원", "new@of-of.kr")
    assert ei.value.code == code
    with db() as s:  # 기존 서브계정 무변경 + 신규/토큰 없음
        st = s.scalar(select(AccountUser).where(AccountUser.login_id == "staff@of-of.kr"))
        assert st.account_status == "active" and st.replaced_by_user_id is None
        assert s.scalar(select(AccountUser).where(AccountUser.login_id == "new@of-of.kr")) is None
    assert _count(db, "activation_tokens", "tenant_id", "of-of") == 0


def test_office_replace_sub_active_ok_and_scope_preserved(db):
    from backend.services import account_lifecycle_pg_service as life
    from backend.services import activation_pg_service as act
    from backend.db.models.user import AccountUser
    _seed_office(db, "of-o2", "active", True)
    r = life.office_replace_sub("of-o2", "boss@of-o2.kr", "staff@of-o2.kr", "새직원", "new@of-o2.kr")
    assert r["role"] == "office_staff"
    with db() as s:
        n = s.scalar(select(AccountUser).where(AccountUser.login_id == "new@of-o2.kr"))
        assert n.is_admin is False and n.account_status == "invited"
    assert act.complete_activation(r["activation_token"], "pw12345")["login_id"] == "new@of-o2.kr"
    # 기존 권한 검증 유지: 다른 tenant/자기자신/office_admin/마스터 교체 금지.
    _seed_office(db, "of-o3", "active", True)
    with pytest.raises(life.LifecycleError) as ei:  # 크로스 테넌트
        life.office_replace_sub("of-o2", "boss@of-o2.kr", "staff@of-o3.kr", "x", "z@of-o2.kr")
    assert ei.value.code == "CROSS_TENANT"
    with pytest.raises(life.LifecycleError) as ei:  # 자기 자신
        life.office_replace_sub("of-o2", "boss@of-o2.kr", "boss@of-o2.kr", "x", "z2@of-o2.kr")
    assert ei.value.code == "SELF_FORBIDDEN"
    with pytest.raises(life.LifecycleError) as ei:  # office_admin(주계정) 대상 — actor 는 staff 가 아니지만
        life.office_replace_sub("of-o3", "staff@of-o3.kr", "boss@of-o3.kr", "x", "z3@of-o3.kr")
    assert ei.value.code == "NOT_SUB_ACCOUNT"


# ── §6 relink 원본 tenant 엄격 상태(미상/빈/공백/불일치 fail-closed) ──────────
@pytest.mark.parametrize("status,active,ok", [
    ("suspended", False, True),
    ("pending_activation", False, True),
    ("maintenance", False, False),
    ("maintenance", True, False),
    ("unknown", False, False),
    ("", False, False),
    ("   ", False, False),
    ("active", True, False),
    ("active", False, False),
    ("pending_activation", True, False),
    ("suspended", True, False),
    ("terminated", False, False),
])
def test_relink_source_invalid_status_fail_closed(db, status, active, ok):
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.user import AccountUser
    acct, src, tgt = _seed_relink_pair(db)  # src 기본 suspended+False, tgt active+True
    _set_tenant_status(db, src, status, active)
    pv = ta.relink_preview(acct, tgt, actor_login="sys")
    assert pv["can_relink"] is ok
    if not ok:
        with pytest.raises(ta.TenantAdminError) as ei:
            ta.relink_account(acct, tgt, "sys", acct, tgt,
                              confirmation_phrase=_PHRASE_RELINK, source_tenant_id=src)
        assert ei.value.code == "BLOCKED"
        with db() as s:  # 계정·token·session 무변경
            u = s.scalar(select(AccountUser).where(AccountUser.login_id == acct))
            assert u.tenant_id == src and u.account_status == "invited" and u.is_active is False
        assert _count(db, "activation_tokens", "tenant_id", tgt) == 0
    else:
        r = ta.relink_account(acct, tgt, "sys", acct, tgt,
                              confirmation_phrase=_PHRASE_RELINK, source_tenant_id=src)
        assert r["to_tenant_id"] == tgt
