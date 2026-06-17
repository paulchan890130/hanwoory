"""account_security 헬퍼/임계값/graceful 단위테스트(DB 불필요).

감지/차단 전체 흐름은 PG 통합이 필요해 별도(통합)로 분리. 여기서는 순수 로직만.
실행: pytest backend/tests/test_account_security.py
"""
import os

from backend.services import account_security_pg_service as s


def test_mask_ip():
    assert s.mask_ip("123.45.67.89") == "123.45.***.***"
    assert s.mask_ip("2001:db8:abcd::1").endswith(":***")
    assert s.mask_ip("") is None
    assert s.mask_ip(None) is None


def test_summarize_ua():
    assert s.summarize_ua("Mozilla/5.0 (Windows NT 10.0; Win64) Chrome/120 Safari/537") == "Windows Chrome"
    assert s.summarize_ua("Mozilla/5.0 (Macintosh; Intel Mac OS X) Safari/16") == "macOS Safari"
    assert s.summarize_ua("Mozilla/5.0 (iPhone) Safari") == "iOS Safari"
    assert s.summarize_ua("") is None


def test_hash_stable_and_present():
    h1 = s._hash("1.2.3.4")
    h2 = s._hash("1.2.3.4")
    assert h1 and h1 == h2
    assert s._hash("") is None


def test_thresholds_env_override(monkeypatch=None):
    # 기본값
    assert s.SUSPICION_BLOCK_THRESHOLD() == 2
    assert s.SUSPICION_BLOCK_WINDOW_DAYS() == 7
    # env override
    os.environ["SEC_BLOCK_THRESHOLD"] = "5"
    try:
        assert s.SUSPICION_BLOCK_THRESHOLD() == 5
    finally:
        os.environ.pop("SEC_BLOCK_THRESHOLD", None)


def test_graceful_without_db():
    # DATABASE_URL 미설정 → 전부 no-op/빈값(로그인 흐름 미차단)
    assert s.is_security_blocked("x") is False
    assert s.recent_login_events("x") == []
    assert s.notifications_for("x") == []
    assert s.security_status("x") == {"security_blocked": False, "suspicion_count": 0, "blocked_at": None}
    assert s.evaluate_suspicion(login_id="x", tenant_id="t") == {"suspicious": False, "blocked": False}
    # 기록/해제도 예외 없이 no-op
    s.record_event(login_id="x", tenant_id="t", event_type=s.EV_LOGIN_SUCCESS)
    assert s.unblock_account("x") is False
