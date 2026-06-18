"""마이페이지 보안 알림/로그인 이력 서버 페이지네이션 + 본인 필터 테스트.

SQLite 임시 DB + FastAPI TestClient(get_current_user override)로 검증(운영 DB 불필요).

검증:
- 보안 알림 기본 5건/페이지, 로그인 이력 10건/페이지, 상한 10(page_size=999 → 422).
- '다음' 페이지 동작(중복 없이 나머지 반환).
- 마이페이지는 current_user.login_id + recipient_role="user" 로 강제 → 타계정/관리자역할 알림 제외.
- 관리자 > 로그인보안 전체 조회(/admin/security/recent)는 전 계정 유지.

실행: pytest backend/tests/test_my_security_pagination.py
"""
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from backend.services import account_security_pg_service as s


@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(element, compiler, **kw):  # noqa: ANN001
    return "INTEGER"


@pytest.fixture
def env(monkeypatch, tmp_path):
    from backend.db.base import Base
    from backend.db.models.account_security import (  # noqa: F401
        LoginEvent, AccountSecurity, SecurityNotification,
    )
    from backend.db.models.user import AccountUser  # noqa: F401
    from backend.db.models.user_session import UserSession  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path / 'sec.db'}", future=True)
    Base.metadata.create_all(engine, tables=[
        LoginEvent.__table__, AccountSecurity.__table__, SecurityNotification.__table__,
        UserSession.__table__, AccountUser.__table__,
    ])
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)

    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    monkeypatch.setattr(dbs, "get_sessionmaker", lambda: SessionLocal)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.auth import get_current_user
    from backend.routers import account_security as r

    app = FastAPI()
    app.include_router(r.router, prefix="/api")
    holder = {"user": {"login_id": "u1", "tenant_id": "t1", "is_admin": False}}
    app.dependency_overrides[get_current_user] = lambda: holder["user"]
    client = TestClient(app)
    return client, SessionLocal, holder


# ── 시드 헬퍼 ─────────────────────────────────────────────────────────────────
def _seed_notif(SessionLocal, login_id, role, title, *, when, tenant_id="t1"):
    from backend.db.models.account_security import SecurityNotification
    with SessionLocal() as ses:
        ses.add(SecurityNotification(
            recipient_login_id=login_id, recipient_role=role, tenant_id=tenant_id,
            type="suspicious", title=title, body="b", related_login_id=login_id,
            created_at=when,
        ))
        ses.commit()


def _seed_event(SessionLocal, login_id, title, *, when, tenant_id="t1"):
    from backend.db.models.account_security import LoginEvent
    with SessionLocal() as ses:
        ses.add(LoginEvent(
            login_id=login_id, tenant_id=tenant_id, event_type=s.EV_LOGIN_SUCCESS,
            ip_prefix_masked="1.2.***.***", user_agent_summary="Windows Chrome",
            success=True, reason=title, created_at=when,
        ))
        ses.commit()


_T0 = datetime(2026, 6, 18, 12, 0, 0, tzinfo=timezone.utc)


# ── 보안 알림: 5건/페이지 + 다음 ──────────────────────────────────────────────
def test_notifications_page_size_5_and_next(env):
    client, SessionLocal, _ = env
    for i in range(7):  # 본인 user-role 7건
        _seed_notif(SessionLocal, "u1", "user", f"n{i}", when=_T0 - timedelta(seconds=i))

    r1 = client.get("/api/my/security-notifications").json()
    assert r1["page_size"] == 5 and r1["page"] == 1
    assert len(r1["notifications"]) == 5
    assert r1["has_next"] is True

    r2 = client.get("/api/my/security-notifications", params={"page": 2}).json()
    assert len(r2["notifications"]) == 2
    assert r2["has_next"] is False
    # 페이지 간 중복 없음 + 합집합 == 전체.
    titles = {n["title"] for n in r1["notifications"]} | {n["title"] for n in r2["notifications"]}
    assert titles == {f"n{i}" for i in range(7)}


# ── 로그인 이력: 10건/페이지 + 다음 ───────────────────────────────────────────
def test_login_events_page_size_10_and_next(env):
    client, SessionLocal, _ = env
    for i in range(12):
        _seed_event(SessionLocal, "u1", f"e{i}", when=_T0 - timedelta(seconds=i))

    r1 = client.get("/api/my/login-events").json()
    assert r1["page_size"] == 10 and len(r1["events"]) == 10 and r1["has_next"] is True
    r2 = client.get("/api/my/login-events", params={"page": 2}).json()
    assert len(r2["events"]) == 2 and r2["has_next"] is False


# ── page_size 초과(999) → 422 ─────────────────────────────────────────────────
def test_page_size_over_max_rejected(env):
    client, _, _ = env
    assert client.get("/api/my/security-notifications", params={"page_size": 999}).status_code == 422
    assert client.get("/api/my/login-events", params={"page_size": 999}).status_code == 422
    # 상한 10 은 허용.
    assert client.get("/api/my/login-events", params={"page_size": 10}).status_code == 200


# ── 일반 사용자: 본인 + user-role 알림만(타계정/관리자역할 제외) ───────────────
def test_my_notifications_only_own_user_role(env):
    client, SessionLocal, _ = env
    _seed_notif(SessionLocal, "u1", "user", "mine", when=_T0)
    _seed_notif(SessionLocal, "u1", "admin", "admin_about_aa", when=_T0 - timedelta(seconds=1))  # 관리자역할
    _seed_notif(SessionLocal, "u2", "user", "other_user", when=_T0 - timedelta(seconds=2))       # 타계정
    out = client.get("/api/my/security-notifications").json()["notifications"]
    titles = [n["title"] for n in out]
    assert titles == ["mine"]


# ── 관리자 마이페이지: 본인 user-role 만(타계정 admin 알림 제외) ───────────────
def test_admin_mypage_only_own_user_role(env):
    client, SessionLocal, holder = env
    holder["user"] = {"login_id": "adm", "tenant_id": "t1", "is_admin": True}
    _seed_notif(SessionLocal, "adm", "user", "adm_personal", when=_T0)
    _seed_notif(SessionLocal, "adm", "admin", "alert_about_aa", when=_T0 - timedelta(seconds=1))
    _seed_notif(SessionLocal, "adm", "admin", "alert_about_bb", when=_T0 - timedelta(seconds=2))
    out = client.get("/api/my/security-notifications").json()["notifications"]
    titles = [n["title"] for n in out]
    assert titles == ["adm_personal"]  # 마이페이지엔 본인 user-role 만


# ── 관리자 로그인보안 전체 조회(/admin/security/recent) 유지 ──────────────────
def test_admin_recent_returns_all_accounts(env):
    client, SessionLocal, holder = env
    holder["user"] = {"login_id": "adm", "tenant_id": "t1", "is_admin": True}
    _seed_event(SessionLocal, "u1", "e_u1", when=_T0)
    _seed_event(SessionLocal, "u2", "e_u2", when=_T0 - timedelta(seconds=1))
    out = client.get("/api/admin/security/recent").json()["events"]
    logins = {e["login_id"] for e in out}
    assert {"u1", "u2"} <= logins  # 전 계정 노출 유지
