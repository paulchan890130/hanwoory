"""온보딩 실사용 흐름 — 신청→승인→활성화→로그인 + 중복 방지 + 사업장 관리 (실제 PostgreSQL).

신청 1건 → tenant 1개 → 계정 2개(대표자 admin / 실무자 staff, 동일 tenant) → 각자 활성화·로그인,
중복 신청 방지(순차/동시/지문 변형)와 승인 시 정확 중복 자동취소, 사업장 목록/정지/복구/폐기
preview 를 실제 FK·advisory lock·트랜잭션에서 검증한다. TEST_DATABASE_URL 없으면 skip.
"""
from __future__ import annotations

import os
import threading

import pytest
from sqlalchemy import create_engine, text, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

_BASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
TEST_DB_URL = ""
if _BASE_URL:
    _u = make_url(_BASE_URL)
    TEST_DB_URL = _u.set(database=(_u.database or "kid") + "_onboard").render_as_string(hide_password=False)
pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="TEST_DATABASE_URL 미설정 — 실제 PostgreSQL 통합 테스트 skip")


def _ensure_database(url_str: str) -> None:
    url = make_url(url_str)
    eng = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT", future=True)
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
    eng = create_engine(TEST_DB_URL, future=True, pool_size=8, max_overflow=8)
    import backend.db.models  # noqa: F401
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


def _app(**over) -> dict:
    d = {
        "office_name": "한빛행정사",
        "representative_name": "대표",
        "representative_email": "rep@hanbit.kr",
        "business_registration_number": "2131237464",
        "office_address": "서울시 종로구",
        "office_phone": "01012345678",
        "staff_name": "직원",
        "staff_email": "staff@hanbit.kr",
    }
    d.update(over)
    return d


def _count(db, table, col, val):
    with db() as s:
        return int(s.execute(text(f"SELECT count(*) FROM {table} WHERE {col}=:v"), {"v": val}).scalar())


# ── 전체 실사용 흐름: 신청 1 → tenant 1 → 계정 2 → 활성화·로그인 ────────────────
def test_full_onboarding_flow(db):
    from backend.services import office_application_pg_service as svc
    from backend.services import activation_pg_service as act
    from backend.services import auth_pg_service as authpg
    from backend.db.models.user import AccountUser
    from backend.db.models.tenant import Tenant

    r = svc.create_application(_app())
    res = svc.approve(r["application_id"], "wkdwhfl", seat_limit=2)
    assert res["tenant_id"] and len(res["users"]) == 2
    tid = res["tenant_id"]
    toks = {u["login_id"]: u for u in res["users"]}

    with db() as s:
        rep = s.scalar(select(AccountUser).where(AccountUser.login_id == "rep@hanbit.kr"))
        staff = s.scalar(select(AccountUser).where(AccountUser.login_id == "staff@hanbit.kr"))
        assert rep.tenant_id == tid and staff.tenant_id == tid           # 동일 tenant
        assert rep.is_admin is True and staff.is_admin is False          # 역할
        assert rep.account_status == "invited" and staff.account_status == "invited"
        assert rep.is_active is False and staff.is_active is False
        assert int(s.execute(text("SELECT count(*) FROM tenants WHERE tenant_id=:v"), {"v": tid}).scalar()) == 1
        assert int(s.execute(text("SELECT count(*) FROM users WHERE tenant_id=:v"), {"v": tid}).scalar()) == 2

    # 가입신청 단계 비밀번호 없음 → 임시 랜덤 해시로는 로그인 불가.
    assert authpg.verify_login_pg("rep@hanbit.kr", "whatever") is None
    # 초대 상태 → account_not_activated 조건(로그인 서비스 레벨).
    from backend.services import account_state as st
    with db() as s:
        assert st.account_status_of(s.scalar(select(AccountUser).where(AccountUser.login_id == "rep@hanbit.kr"))) == "invited"

    # 대표자 활성화 → tenant active 승격.
    act.complete_activation(toks["rep@hanbit.kr"]["activation_token"], "reppw123")
    # 실무자 활성화(다른 비밀번호).
    act.complete_activation(toks["staff@hanbit.kr"]["activation_token"], "staffpw123")

    rep_login = authpg.verify_login_pg("rep@hanbit.kr", "reppw123")
    staff_login = authpg.verify_login_pg("staff@hanbit.kr", "staffpw123")
    assert rep_login is not None and staff_login is not None
    assert rep_login["tenant_id"] == staff_login["tenant_id"] == tid     # 같은 tenant 공유
    assert rep_login["is_admin"] is True and staff_login["is_admin"] is False
    # 잘못된 비밀번호는 실패(활성 계정도).
    assert authpg.verify_login_pg("rep@hanbit.kr", "wrong") is None
    with db() as s:
        t = s.scalar(select(Tenant).where(Tenant.tenant_id == tid))
        assert t.service_status == "active" and t.is_active is True


# ── 중복 방지: 순차 ────────────────────────────────────────────────────────────
def test_duplicate_sequential_one_row(db):
    from backend.services import office_application_pg_service as svc
    svc.create_application(_app())
    with pytest.raises(svc.ApplicationError) as ei:
        svc.create_application(_app())
    assert ei.value.code == "DUPLICATE_PENDING"
    assert _count(db, "office_applications", "status", "pending") == 1


# ── 중복 방지: 동시(advisory lock) — 정확히 1행 ─────────────────────────────────
@pytest.mark.parametrize("n", [2, 10])
def test_duplicate_concurrent_one_row(db, n):
    from backend.services import office_application_pg_service as svc
    results: list = []
    barrier = threading.Barrier(n)

    def _go():
        barrier.wait()
        try:
            svc.create_application(_app())
            results.append("ok")
        except svc.ApplicationError as e:
            results.append(e.code)
        except Exception as e:  # noqa: BLE001 — 500 유발 여부 확인
            results.append(f"ERR:{type(e).__name__}")

    threads = [threading.Thread(target=_go) for _ in range(n)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert results.count("ok") == 1, results
    assert all(r == "ok" or r == "DUPLICATE_PENDING" for r in results), results  # 500 없음
    assert _count(db, "office_applications", "office_name", "한빛행정사") == 1


# ── 지문 변형: 서로 다르면 별도 신청 허용 / 정규화 후 같으면 중복 ───────────────
def test_fingerprint_variants(db):
    from backend.services import office_application_pg_service as svc
    svc.create_application(_app())
    # 사업자번호 다름 → 허용.
    svc.create_application(_app(business_registration_number="9998887776"))
    # 대표자 이메일 다름 → 허용.
    svc.create_application(_app(representative_email="rep2@hanbit.kr"))
    # 실무자 이메일 다름 → 허용.
    svc.create_application(_app(staff_email="staff2@hanbit.kr"))
    assert _count(db, "office_applications", "status", "pending") == 4
    # 사무소명 대소문자·공백만 다름 + 나머지 동일 → 중복.
    with pytest.raises(svc.ApplicationError) as ei:
        svc.create_application(_app(office_name="  한빛행정사 "))
    assert ei.value.code == "DUPLICATE_PENDING"


def test_same_rep_staff_email_rejected(db):
    from backend.services import office_application_pg_service as svc
    with pytest.raises(svc.ApplicationError) as ei:
        svc.create_application(_app(staff_email="rep@hanbit.kr"))
    assert ei.value.code == "DUPLICATE_USER_EMAIL"


# ── 승인 시 정확 중복 자동 취소 ────────────────────────────────────────────────
def _insert_dup_directly(db, application_id):
    """create 의 dedup 을 우회해 정확 중복 pending 행을 직접 삽입(운영 잔존 중복 모사)."""
    from backend.db.models.office_application import OfficeApplication
    from datetime import datetime, timezone
    with db() as s:
        s.add(OfficeApplication(
            application_id=application_id, status="pending", office_name="한빛행정사",
            business_registration_number="2131237464",
            requested_user_1_name="대표", requested_user_1_email="rep@hanbit.kr",
            requested_user_2_name="직원", requested_user_2_email="staff@hanbit.kr",
            submitted_at=datetime.now(timezone.utc)))
        s.commit()


def test_approve_cancels_exact_duplicates(db):
    from backend.services import office_application_pg_service as svc
    r = svc.create_application(_app())
    _insert_dup_directly(db, "APP-DUP1")
    _insert_dup_directly(db, "APP-DUP2")
    # 유사하지만 다른 신청(대표자 이메일 다름) — 자동 취소 대상 아님.
    other = svc.create_application(_app(representative_email="other@hanbit.kr"))
    res = svc.approve(r["application_id"], "wkdwhfl", seat_limit=2)
    assert res["cancelled_duplicate_count"] == 2
    with db() as s:
        assert int(s.execute(text("SELECT count(*) FROM tenants")).scalar()) == 1
        assert int(s.execute(text("SELECT count(*) FROM users")).scalar()) == 2
        assert int(s.execute(text("SELECT count(*) FROM activation_tokens")).scalar()) == 2
        cancelled = list(s.execute(text(
            "SELECT application_id FROM office_applications WHERE status='cancelled'")).scalars())
        assert set(cancelled) == {"APP-DUP1", "APP-DUP2"}
        oth = s.execute(text("SELECT status FROM office_applications WHERE application_id=:a"),
                        {"a": other["application_id"]}).scalar()
        assert oth == "pending"  # 다른 신청은 무변경


def test_approve_atomic_rollback(db, monkeypatch):
    from backend.services import office_application_pg_service as svc
    from backend.services import activation_pg_service as _act
    r = svc.create_application(_app())
    _insert_dup_directly(db, "APP-DUP1")
    calls = {"n": 0}
    real = _act.issue_activation_token
    def _boom(session, login_id, tenant_id, ttl_hours=72):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("token issue failed")
        return real(session, login_id, tenant_id, ttl_hours)
    monkeypatch.setattr(_act, "issue_activation_token", _boom)
    with pytest.raises(Exception):
        svc.approve(r["application_id"], "wkdwhfl", seat_limit=2)
    with db() as s:  # 전체 롤백 — tenant/user/token 미생성, 신청·중복 상태 무변경
        assert int(s.execute(text("SELECT count(*) FROM tenants")).scalar()) == 0
        assert int(s.execute(text("SELECT count(*) FROM users")).scalar()) == 0
        assert int(s.execute(text("SELECT count(*) FROM activation_tokens")).scalar()) == 0
        st = s.execute(text("SELECT status FROM office_applications WHERE application_id=:a"),
                       {"a": r["application_id"]}).scalar()
        assert st in ("pending", "reviewing")
        assert s.execute(text("SELECT status FROM office_applications WHERE application_id='APP-DUP1'")).scalar() == "pending"


# ── 사업장 관리: 목록·필터·검색·정지·복구·폐기 preview ──────────────────────────
def test_tenant_list_filter_suspend_restore_purge(db):
    from backend.services import office_application_pg_service as svc
    from backend.services import tenant_admin_pg_service as ta
    from backend.services import account_lifecycle_pg_service as life
    from backend.services import tenant_purge_pg_service as purge
    r = svc.create_application(_app())
    res = svc.approve(r["application_id"], "wkdwhfl", seat_limit=2)
    tid = res["tenant_id"]

    # 전체 목록 + 검색.
    allrows = ta.list_tenants_for_actor("all", None, "sys")
    assert any(x["tenant_id"] == tid for x in allrows)
    assert ta.list_tenants_for_actor("all", "한빛", "sys")[0]["tenant_id"] == tid
    assert ta.list_tenants_for_actor("all", tid, "sys")[0]["tenant_id"] == tid
    # 상태 필터: 승인 직후 pending_activation.
    assert any(x["tenant_id"] == tid for x in ta.list_tenants_for_actor("pending_activation", None, "sys"))
    assert all(x["service_status"] == "suspended" for x in ta.list_tenants_for_actor("suspended", None, "sys"))

    # 활성 사업장(활성화 후) purge preview → can_purge False(정지 필요).
    from backend.services import activation_pg_service as act
    for u in res["users"]:
        act.complete_activation(u["activation_token"], "pw123456")
    pv = purge.purge_preview(tid, actor_login="sys")
    assert pv["can_purge"] is False

    # 사업장 정지 → 상태 suspended.
    life.suspend_tenant(tid, "sys")
    row = [x for x in ta.list_tenants_for_actor("all", None, "sys") if x["tenant_id"] == tid][0]
    assert row["service_status"] == "suspended"
    # 정지+비활성 + 외부저장소 없음 → purge preview can_purge True.
    pv2 = purge.purge_preview(tid, actor_login="sys")
    assert pv2["can_purge"] is True
    # 복구 → active.
    life.restore_tenant(tid, "sys")
    row2 = [x for x in ta.list_tenants_for_actor("all", None, "sys") if x["tenant_id"] == tid][0]
    assert row2["service_status"] == "active"


def test_tenant_list_external_and_local_storage(db):
    from backend.services import tenant_admin_pg_service as ta
    from backend.db.models.tenant import Tenant
    with db() as s:
        for tid, folder in (("of-real", "1AbcRealDriveId"), ("of-local", "local-mock")):
            t = Tenant(tenant_id=tid, office_name=tid, is_active=False, folder_id=folder)
            t.service_status = "suspended"; t.seat_limit = 2
            s.add(t)
        s.commit()
    rows = {x["tenant_id"]: x for x in ta.list_tenants_for_actor("all", None, "sys")}
    # 실제 외부 저장소 → 폐기 차단.
    assert rows["of-real"]["can_purge"] is False
    assert "folder_id" in rows["of-real"]["external_storage_refs"]
    # local-* → 폐기 차단 아님(정지+비활성이므로 can_purge True).
    assert rows["of-local"]["can_purge"] is True
    assert "folder_id" in rows["of-local"]["local_storage_refs"]
