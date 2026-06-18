"""계정공유 감지 정책 통합테스트 (2026-06-18 오탐/과민차단 사고 재발방지).

SQLite 임시 DB 로 ``evaluate_suspicion`` 전 흐름을 검증한다(PG 불필요).
session 모듈의 ``is_configured`` / ``get_sessionmaker`` 를 임시 엔진으로 monkeypatch.

핵심 회귀 방지:
- 같은 IP/UA(같은 PC·사무실) 재로그인·다음날 재접속·세션 밀림은 절대 의심·차단되지 않는다.
- 강한 증거(서로 다른 기기 3+)만 의심으로 기록한다.
- 자동 차단은 기본 비활성(베타). env 활성 시에만, 그것도 관리자 제외하고 동작한다.

실행: pytest backend/tests/test_account_security_policy.py
"""
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from backend.services import account_security_pg_service as s


# SQLite 는 BIGINT PK 에 rowid 자동증가를 적용하지 않는다(INTEGER 만). 테스트 한정으로
# BigInteger 를 INTEGER 로 렌더해 autoincrement PK 가 동작하게 한다(모델 변경 없음).
@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(element, compiler, **kw):  # noqa: ANN001
    return "INTEGER"


@pytest.fixture
def db(monkeypatch, tmp_path):
    """임시 SQLite 엔진 + 전체 스키마 + 서비스 session 후크 monkeypatch."""
    from backend.db.base import Base
    # 테스트에 필요한 테이블만 생성한다. tenants 모델은 SQLite 미지원 JSONB 컬럼이 있어
    # 전체 create_all 이 실패하므로 제외. users.tenant_id FK 는 SQLite 기본 미강제라 무방.
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
    # 기본 비활성 보장(다른 테스트가 env 를 남겨도 격리).
    monkeypatch.delenv("ACCOUNT_SECURITY_AUTO_BLOCK", raising=False)
    return SessionLocal


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────
def _seed_login(SessionLocal, login_id, ip, ua, *, when=None, tenant_id="t1",
                event_type=None):
    from backend.db.models.account_security import LoginEvent
    with SessionLocal() as ses:
        ses.add(LoginEvent(
            login_id=login_id, tenant_id=tenant_id,
            event_type=event_type or s.EV_LOGIN_SUCCESS,
            ip_hash=s._hash(ip), ip_prefix_masked=s.mask_ip(ip),
            user_agent_hash=s._hash(ua), user_agent_summary=s.summarize_ua(ua),
            success=True, created_at=(when or datetime.now(timezone.utc)),
        ))
        ses.commit()


def _seed_new_login_revoke(SessionLocal, login_id, *, when=None, tenant_id="t1"):
    from backend.db.models.user_session import UserSession
    with SessionLocal() as ses:
        ses.add(UserSession(
            login_id=login_id, tenant_id=tenant_id, session_id=f"sid-{when or datetime.now(timezone.utc)}",
            revoked_reason="new_login", revoked_at=(when or datetime.now(timezone.utc)),
        ))
        ses.commit()


def _seed_user(SessionLocal, login_id, *, is_admin=False, tenant_id="t1"):
    # tenants 테이블은 생성하지 않으나 SQLite 가 FK 를 강제하지 않으므로 users 만 삽입한다.
    from backend.db.models.user import AccountUser
    with SessionLocal() as ses:
        ses.add(AccountUser(login_id=login_id, tenant_id=tenant_id,
                            password_hash="x", is_admin=is_admin, is_active=True))
        ses.commit()


_WIN_CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64) Chrome/120 Safari/537"


# ── 1: 같은 IP + 같은 UA 재로그인/다음날 재접속 → 차단 안 됨 ──────────────────
def test_same_device_relogin_next_day_not_suspicious(db):
    lid = "user_same"
    # 오늘 여러 번 + 어제(같은 PC, 동적 IP라 끝자리만 다름) 재접속.
    _seed_login(db, lid, "1.2.3.4", _WIN_CHROME)
    _seed_login(db, lid, "1.2.9.9", _WIN_CHROME)  # 동적 IP 변경, prefix 동일
    _seed_login(db, lid, "1.2.3.4", _WIN_CHROME,
                when=datetime.now(timezone.utc) - timedelta(hours=20))
    out = s.evaluate_suspicion(login_id=lid, tenant_id="t1", ip="1.2.3.4", user_agent=_WIN_CHROME)
    assert out == {"suspicious": False, "blocked": False}
    assert s.security_status(lid)["security_blocked"] is False


# ── 2: SESSION_REVOKED_BY_NEW_LOGIN 누적도 suspicion 증가 안 함 ────────────────
def test_session_revoked_by_new_login_does_not_count(db):
    lid = "user_revoke"
    # 단일세션으로 여러 번 밀려난 이력 + 같은 기기 로그인.
    for _ in range(5):
        _seed_new_login_revoke(db, lid)
    _seed_login(db, lid, "10.0.0.1", _WIN_CHROME)
    _seed_login(db, lid, "10.0.0.1", _WIN_CHROME)
    out = s.evaluate_suspicion(login_id=lid, tenant_id="t1", ip="10.0.0.1", user_agent=_WIN_CHROME)
    assert out["suspicious"] is False
    assert s.security_status(lid)["suspicion_count"] == 0


# ── 3: 같은 IP + 같은 UA 반복 로그인은 자동 차단 안 됨 ────────────────────────
def test_repeated_same_device_logins_never_blocked(db):
    lid = "user_repeat"
    for _ in range(10):
        _seed_login(db, lid, "192.168.0.50", _WIN_CHROME)
    for _ in range(3):
        out = s.evaluate_suspicion(login_id=lid, tenant_id="t1", ip="192.168.0.50", user_agent=_WIN_CHROME)
        assert out == {"suspicious": False, "blocked": False}
    assert s.security_status(lid)["security_blocked"] is False


# ── 4: 서로 다른 기기 3개일 때만 SUSPICIOUS 발생 ──────────────────────────────
def test_distinct_devices_triggers_suspicious(db):
    lid = "user_multi"
    _seed_login(db, lid, "1.1.0.1", _WIN_CHROME)
    _seed_login(db, lid, "2.2.0.1", "Mozilla/5.0 (Macintosh; Intel Mac OS X) Safari/16")
    _seed_login(db, lid, "3.3.0.1", "Mozilla/5.0 (Android) Chrome/120")
    out = s.evaluate_suspicion(login_id=lid, tenant_id="t1", ip="3.3.0.1", user_agent="Mozilla/5.0 (Android) Chrome/120")
    assert out["suspicious"] is True
    assert out["blocked"] is False  # 자동차단 기본 비활성
    # SUSPICIOUS 이벤트가 기록되었는지.
    from backend.db.models.account_security import LoginEvent
    with db() as ses:
        n = ses.scalar(select(__import__("sqlalchemy").func.count()).select_from(LoginEvent)
                       .where(LoginEvent.login_id == lid, LoginEvent.event_type == s.EV_SUSPICIOUS))
        assert int(n) >= 1


# ── 5: AUTO_BLOCK=false 면 어떤 경우에도 security_blocked=true 안 됨 ───────────
def test_auto_block_disabled_never_blocks(db, monkeypatch):
    monkeypatch.delenv("ACCOUNT_SECURITY_AUTO_BLOCK", raising=False)
    assert s.AUTO_BLOCK_ENABLED() is False
    lid = "user_noblock"
    _seed_login(db, lid, "1.1.0.1", _WIN_CHROME)
    _seed_login(db, lid, "2.2.0.1", "Mozilla/5.0 (Macintosh; Intel Mac OS X) Safari/16")
    _seed_login(db, lid, "3.3.0.1", "Mozilla/5.0 (Android) Chrome/120")
    for _ in range(5):
        out = s.evaluate_suspicion(login_id=lid, tenant_id="t1", ip="3.3.0.1",
                                   user_agent="Mozilla/5.0 (Android) Chrome/120")
        assert out["blocked"] is False
    assert s.security_status(lid)["security_blocked"] is False


# ── 6: AUTO_BLOCK=true + 강한 의심 누적 시에만 차단(비관리자) ──────────────────
def test_auto_block_enabled_blocks_strong_suspicion(db, monkeypatch):
    monkeypatch.setenv("ACCOUNT_SECURITY_AUTO_BLOCK", "true")
    assert s.AUTO_BLOCK_ENABLED() is True
    lid = "user_block"
    _seed_user(db, lid, is_admin=False)
    _seed_login(db, lid, "1.1.0.1", _WIN_CHROME)
    _seed_login(db, lid, "2.2.0.1", "Mozilla/5.0 (Macintosh; Intel Mac OS X) Safari/16")
    _seed_login(db, lid, "3.3.0.1", "Mozilla/5.0 (Android) Chrome/120")
    # 임계 2회: 두 번째 평가에서 누적 2 → 차단.
    s.evaluate_suspicion(login_id=lid, tenant_id="t1", ip="3.3.0.1", user_agent="Mozilla/5.0 (Android) Chrome/120")
    out2 = s.evaluate_suspicion(login_id=lid, tenant_id="t1", ip="3.3.0.1", user_agent="Mozilla/5.0 (Android) Chrome/120")
    assert out2["blocked"] is True
    assert s.security_status(lid)["security_blocked"] is True


# ── 7: 관리자 계정은 자동차단 제외(break-glass) ───────────────────────────────
def test_admin_never_auto_blocked(db, monkeypatch):
    monkeypatch.setenv("ACCOUNT_SECURITY_AUTO_BLOCK", "true")
    lid = "admin1"
    _seed_user(db, lid, is_admin=True)
    _seed_login(db, lid, "1.1.0.1", _WIN_CHROME)
    _seed_login(db, lid, "2.2.0.1", "Mozilla/5.0 (Macintosh; Intel Mac OS X) Safari/16")
    _seed_login(db, lid, "3.3.0.1", "Mozilla/5.0 (Android) Chrome/120")
    for _ in range(5):
        out = s.evaluate_suspicion(login_id=lid, tenant_id="t1", ip="3.3.0.1",
                                   user_agent="Mozilla/5.0 (Android) Chrome/120")
        assert out["blocked"] is False
    assert s.security_status(lid)["security_blocked"] is False
    # 관리자 대상 경고 알림(자동차단 제외)이 기록됐는지.
    notes = s.notifications_for(lid)
    assert any("자동차단 제외" in (n.get("title") or "") for n in notes)


# ── 8: unblock 정상 ───────────────────────────────────────────────────────────
def test_unblock(db, monkeypatch):
    monkeypatch.setenv("ACCOUNT_SECURITY_AUTO_BLOCK", "true")
    lid = "user_unblock"
    _seed_user(db, lid, is_admin=False)
    _seed_login(db, lid, "1.1.0.1", _WIN_CHROME)
    _seed_login(db, lid, "2.2.0.1", "Mozilla/5.0 (Macintosh; Intel Mac OS X) Safari/16")
    _seed_login(db, lid, "3.3.0.1", "Mozilla/5.0 (Android) Chrome/120")
    s.evaluate_suspicion(login_id=lid, tenant_id="t1", ip="3.3.0.1", user_agent="Mozilla/5.0 (Android) Chrome/120")
    s.evaluate_suspicion(login_id=lid, tenant_id="t1", ip="3.3.0.1", user_agent="Mozilla/5.0 (Android) Chrome/120")
    assert s.security_status(lid)["security_blocked"] is True
    assert s.unblock_account(lid, actor_login_id="admin1") is True
    st = s.security_status(lid)
    assert st["security_blocked"] is False
    assert st["suspicion_count"] == 0


# ── 9: login_events 기록 정상 ─────────────────────────────────────────────────
def test_record_event_and_listing(db):
    lid = "user_log"
    s.record_event(login_id=lid, tenant_id="t1", event_type=s.EV_LOGIN_SUCCESS,
                   ip="1.2.3.4", user_agent=_WIN_CHROME, success=True, reason="login")
    rows = s.recent_login_events(lid)
    assert len(rows) == 1
    assert rows[0]["event_type"] == s.EV_LOGIN_SUCCESS
    assert rows[0]["ip_prefix_masked"] == "1.2.***.***"
    assert rows[0]["user_agent_summary"] == "Windows Chrome"


# ── 10: LOGIN_FAILED/LOCKED 는 distinct 기기 집계에 포함되지 않음(회귀) ────────
def test_failed_locked_events_do_not_trigger_suspicion(db):
    lid = "user_failed"
    # 실패/잠금 이벤트는 서로 다른 IP 라도 의심 집계 대상이 아님(LOGIN_SUCCESS 만 집계).
    _seed_login(db, lid, "1.1.0.1", _WIN_CHROME, event_type=s.EV_LOGIN_FAILED)
    _seed_login(db, lid, "2.2.0.1", _WIN_CHROME, event_type=s.EV_LOGIN_FAILED)
    _seed_login(db, lid, "3.3.0.1", _WIN_CHROME, event_type=s.EV_LOGIN_LOCKED)
    out = s.evaluate_suspicion(login_id=lid, tenant_id="t1", ip="3.3.0.1", user_agent=_WIN_CHROME)
    assert out == {"suspicious": False, "blocked": False}
