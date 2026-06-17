"""로그인 실패 제한/계정잠금 — PG(login_attempts, migration 0019).

정책: 동일 login_id 연속 5회 실패 → 10분 잠금. 성공 시 카운터 초기화.
**fail-open**: PG 미구성/테이블 없음/오류 시 잠금 로직을 건너뛰고 정상 로그인 흐름을
막지 않는다(가용성 우선). 잠금은 단일세션·is_active 차단과 독립(인증 이전 단계).
원문 비밀번호는 절대 다루지 않으며 로그에 남기지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

THRESHOLD = 5
LOCK_MINUTES = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sl():
    from backend.db.session import get_sessionmaker
    return get_sessionmaker()()


def _configured() -> bool:
    try:
        from backend.db.session import is_configured
        return is_configured()
    except Exception:
        return False


def check_locked(login_id: str) -> Optional[datetime]:
    """현재 잠금 중이면 locked_until 반환, 아니면 None. 오류 시 None(fail-open)."""
    lid = (login_id or "").strip()
    if not lid or not _configured():
        return None
    try:
        from backend.db.models.login_attempt import LoginAttempt
        with _sl() as s:
            row = s.get(LoginAttempt, lid)
            if row and row.locked_until and row.locked_until > _now():
                return row.locked_until
            return None
    except Exception:
        return None


def record_failure(login_id: str, ip: Optional[str] = None, user_agent: Optional[str] = None) -> bool:
    """실패 1회 기록. 임계 도달 시 잠금하고 True 반환. 오류 시 False(fail-open)."""
    lid = (login_id or "").strip()
    if not lid or not _configured():
        return False
    try:
        from backend.db.models.login_attempt import LoginAttempt
        now = _now()
        with _sl() as s:
            row = s.get(LoginAttempt, lid)
            if row is None:
                row = LoginAttempt(login_id=lid, failed_count=0, first_failed_at=now)
                s.add(row)
            row.failed_count = int(row.failed_count or 0) + 1
            row.last_failed_at = now
            row.last_ip = ip
            row.last_user_agent = (user_agent or "")[:300]
            if row.first_failed_at is None:
                row.first_failed_at = now
            locked = False
            if row.failed_count >= THRESHOLD:
                row.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                row.failed_count = 0  # 잠금 후 카운터 리셋(만료 후 신규 시도 허용)
                locked = True
            s.commit()
            return locked
    except Exception:
        return False


def record_success(login_id: str) -> None:
    """성공 로그인 — 실패 카운터/잠금 해제. 오류 무시(fail-open)."""
    lid = (login_id or "").strip()
    if not lid or not _configured():
        return
    try:
        from backend.db.models.login_attempt import LoginAttempt
        with _sl() as s:
            row = s.get(LoginAttempt, lid)
            if row:
                row.failed_count = 0
                row.locked_until = None
                s.commit()
    except Exception:
        return
