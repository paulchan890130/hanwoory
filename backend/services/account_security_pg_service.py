"""계정공유 의심 감지 / 로그인 이력 / 보안 알림 — PG(migration 0021, 베타).

설계 원칙
- **graceful**: PG 미구성/0021 미적용/오류 시 전부 no-op·빈 목록 → 로그인/기존 기능 미차단.
- 등록기기 개념 없음. IP/UA 는 해시(비교용) + 마스킹/요약(표시용)만 저장, 원문 전체 미저장.
- ``security_blocked``(보안차단)는 ``users.is_active``(관리자 비활성)와 **구분**.
- 감지 임계값은 상수 + env override.
- LOGOUT 만으로 감지하지 않는다(브라우저 종료 시 누락) → 복수 신호 사용.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

# ── 이벤트 타입 ────────────────────────────────────────────────────────────────
EV_LOGIN_SUCCESS = "LOGIN_SUCCESS"
EV_LOGIN_FAILED = "LOGIN_FAILED"
EV_LOGIN_LOCKED = "LOGIN_LOCKED"
EV_LOGOUT = "LOGOUT"
EV_SESSION_REVOKED_BY_NEW_LOGIN = "SESSION_REVOKED_BY_NEW_LOGIN"
EV_SUSPICIOUS = "SUSPICIOUS_LOGIN_DETECTED"
EV_BLOCKED = "ACCOUNT_SECURITY_BLOCKED"
EV_UNBLOCKED = "ACCOUNT_SECURITY_UNBLOCKED"

BLOCK_MESSAGE = "계정공유 의심 행위가 반복되어 계정이 일시 차단되었습니다. 관리자 확인 후 이용할 수 있습니다."


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


# ── 감지 임계값(상수 + env override) ──────────────────────────────────────────
def NEWLOGIN_REVOKE_24H_THRESHOLD() -> int:
    return _int_env("SEC_NEWLOGIN_REVOKE_24H", 2)


def REPEAT_LOGIN_30M_THRESHOLD() -> int:
    return _int_env("SEC_REPEAT_LOGIN_30M", 3)


def DISTINCT_IPUA_24H_THRESHOLD() -> int:
    return _int_env("SEC_DISTINCT_IPUA_24H", 3)


def SUSPICION_BLOCK_WINDOW_DAYS() -> int:
    return _int_env("SEC_BLOCK_WINDOW_DAYS", 7)


def SUSPICION_BLOCK_THRESHOLD() -> int:
    return _int_env("SEC_BLOCK_THRESHOLD", 2)


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


# ── IP/UA 해시·마스킹·요약 ────────────────────────────────────────────────────
def _hash(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()
    if not v:
        return None
    return hashlib.sha256(v.encode("utf-8")).hexdigest()[:32]


def mask_ip(ip: Optional[str]) -> Optional[str]:
    v = (ip or "").strip()
    if not v:
        return None
    if ":" in v:  # IPv6 — 앞 2그룹만
        parts = v.split(":")
        return ":".join(parts[:2]) + ":***"
    parts = v.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.***.***"
    return "***"


def summarize_ua(ua: Optional[str]) -> Optional[str]:
    s = (ua or "")
    if not s.strip():
        return None
    os_name = ("Windows" if "Windows" in s else "macOS" if ("Mac OS" in s or "Macintosh" in s)
               else "iOS" if ("iPhone" in s or "iPad" in s) else "Android" if "Android" in s
               else "Linux" if "Linux" in s else "기타")
    if "Edg" in s:
        br = "Edge"
    elif "OPR" in s or "Opera" in s:
        br = "Opera"
    elif "Chrome" in s:
        br = "Chrome"
    elif "Firefox" in s:
        br = "Firefox"
    elif "Safari" in s:
        br = "Safari"
    else:
        br = "기타"
    return f"{os_name} {br}"


# ── 이벤트 기록 ────────────────────────────────────────────────────────────────
def record_event(*, login_id: str, tenant_id: Optional[str], event_type: str,
                 ip: Optional[str] = None, user_agent: Optional[str] = None,
                 success: Optional[bool] = None, reason: Optional[str] = None,
                 risk_level: str = "none") -> None:
    """로그인/보안 이벤트 1건 기록. graceful(오류 무시)."""
    lid = (login_id or "").strip()
    if not lid or not _configured():
        return
    try:
        from backend.db.models.account_security import LoginEvent
        with _sl() as s:
            s.add(LoginEvent(
                login_id=lid, tenant_id=tenant_id, event_type=event_type,
                ip_hash=_hash(ip), ip_prefix_masked=mask_ip(ip),
                user_agent_hash=_hash(user_agent), user_agent_summary=summarize_ua(user_agent),
                success=success, reason=reason, risk_level=risk_level,
            ))
            s.commit()
    except Exception:
        return


# ── 감지 ──────────────────────────────────────────────────────────────────────
def _count_new_login_revokes_24h(session, login_id: str) -> int:
    """단일세션 신호: 최근 24h 내 new_login 으로 밀려난 세션 수(user_sessions)."""
    from sqlalchemy import select, func as f
    from backend.db.models.user_session import UserSession
    since = _now() - timedelta(hours=24)
    return int(session.scalar(
        select(f.count()).select_from(UserSession).where(
            UserSession.login_id == login_id,
            UserSession.revoked_reason == "new_login",
            UserSession.revoked_at >= since,
        )
    ) or 0)


def _count_repeat_logins_30m(session, login_id: str) -> int:
    from sqlalchemy import select, func as f
    from backend.db.models.account_security import LoginEvent
    since = _now() - timedelta(minutes=30)
    return int(session.scalar(
        select(f.count()).select_from(LoginEvent).where(
            LoginEvent.login_id == login_id,
            LoginEvent.event_type.in_([EV_LOGIN_SUCCESS, EV_LOGOUT]),
            LoginEvent.created_at >= since,
        )
    ) or 0)


def _count_distinct_ipua_24h(session, login_id: str) -> int:
    from sqlalchemy import select, func as f
    from backend.db.models.account_security import LoginEvent
    since = _now() - timedelta(hours=24)
    rows = session.execute(
        select(LoginEvent.ip_hash, LoginEvent.user_agent_hash).where(
            LoginEvent.login_id == login_id,
            LoginEvent.event_type == EV_LOGIN_SUCCESS,
            LoginEvent.created_at >= since,
        )
    ).all()
    combos = {(r[0], r[1]) for r in rows if r[0] or r[1]}
    return len(combos)


def _suspicion_events_in_window(session, login_id: str) -> int:
    from sqlalchemy import select, func as f
    from backend.db.models.account_security import LoginEvent
    since = _now() - timedelta(days=SUSPICION_BLOCK_WINDOW_DAYS())
    return int(session.scalar(
        select(f.count()).select_from(LoginEvent).where(
            LoginEvent.login_id == login_id,
            LoginEvent.event_type == EV_SUSPICIOUS,
            LoginEvent.created_at >= since,
        )
    ) or 0)


def _admin_login_ids(session) -> List[str]:
    try:
        from sqlalchemy import select
        from backend.db.models.user import AccountUser
        return [str(x) for x in session.scalars(
            select(AccountUser.login_id).where(
                AccountUser.is_admin.is_(True), AccountUser.is_active.is_(True)
            )
        ).all()]
    except Exception:
        return []


def _notify(session, *, recipient_login_id: str, recipient_role: str, tenant_id: Optional[str],
            ntype: str, title: str, body: str, related_login_id: Optional[str]) -> None:
    from backend.db.models.account_security import SecurityNotification
    session.add(SecurityNotification(
        recipient_login_id=recipient_login_id, recipient_role=recipient_role, tenant_id=tenant_id,
        type=ntype, title=title, body=body, related_login_id=related_login_id,
    ))


def _get_or_create_security(session, login_id: str, tenant_id: Optional[str]):
    from backend.db.models.account_security import AccountSecurity
    row = session.get(AccountSecurity, login_id)
    if row is None:
        row = AccountSecurity(login_id=login_id, tenant_id=tenant_id, suspicion_count=0)
        session.add(row)
    return row


def is_security_blocked(login_id: str) -> bool:
    """보안차단 여부. graceful(오류/미구성 → False, 로그인 미차단)."""
    lid = (login_id or "").strip()
    if not lid or not _configured():
        return False
    try:
        from backend.db.models.account_security import AccountSecurity
        with _sl() as s:
            row = s.get(AccountSecurity, lid)
            return bool(row and row.security_blocked)
    except Exception:
        return False


def evaluate_suspicion(*, login_id: str, tenant_id: Optional[str],
                       ip: Optional[str] = None, user_agent: Optional[str] = None) -> dict:
    """로그인 직후 호출. 의심 신호 평가 → 1회 알림 / 누적 2회 차단.

    반환: {"suspicious": bool, "blocked": bool}. graceful(오류 → no-op).
    """
    lid = (login_id or "").strip()
    out = {"suspicious": False, "blocked": False}
    if not lid or not _configured():
        return out
    try:
        from backend.db.models.account_security import LoginEvent
        with _sl() as s:
            reasons = []
            if _count_new_login_revokes_24h(s, lid) >= NEWLOGIN_REVOKE_24H_THRESHOLD():
                reasons.append("new_login_revoke_24h")
            if _count_repeat_logins_30m(s, lid) >= REPEAT_LOGIN_30M_THRESHOLD():
                reasons.append("repeat_login_30m")
            if _count_distinct_ipua_24h(s, lid) >= DISTINCT_IPUA_24H_THRESHOLD():
                reasons.append("distinct_ipua_24h")
            if not reasons:
                return out

            # 1회 의심 — 이벤트 + 카운트 + 알림(본인+관리자). 차단은 아래에서 판단.
            reason_str = ",".join(reasons)
            s.add(LoginEvent(login_id=lid, tenant_id=tenant_id, event_type=EV_SUSPICIOUS,
                             ip_hash=_hash(ip), ip_prefix_masked=mask_ip(ip),
                             user_agent_hash=_hash(user_agent), user_agent_summary=summarize_ua(user_agent),
                             success=True, reason=reason_str, risk_level="suspicious"))
            sec = _get_or_create_security(s, lid, tenant_id)
            sec.suspicion_count = int(sec.suspicion_count or 0) + 1
            sec.last_suspicion_at = _now()
            out["suspicious"] = True

            _notify(s, recipient_login_id=lid, recipient_role="user", tenant_id=tenant_id,
                    ntype="suspicious", title="계정공유 의심 로그인 감지",
                    body="평소와 다른 접속 패턴이 감지되었습니다. 본인이 아니라면 비밀번호를 변경하세요.",
                    related_login_id=lid)
            for admin_lid in _admin_login_ids(s):
                _notify(s, recipient_login_id=admin_lid, recipient_role="admin", tenant_id=tenant_id,
                        ntype="suspicious", title=f"[보안] 계정공유 의심: {lid}",
                        body=f"{lid} 계정에서 의심 로그인 신호({reason_str})가 감지되었습니다.",
                        related_login_id=lid)
            s.commit()

            # 7일 내 의심 누적 2회 → 차단
            with _sl() as s2:
                if _suspicion_events_in_window(s2, lid) >= SUSPICION_BLOCK_THRESHOLD():
                    out["blocked"] = _block(s2, lid, tenant_id, reason_str)
        return out
    except Exception:
        return out


def _block(session, login_id: str, tenant_id: Optional[str], reason: str) -> bool:
    from backend.db.models.account_security import LoginEvent
    sec = _get_or_create_security(session, login_id, tenant_id)
    if sec.security_blocked:
        return True
    sec.security_blocked = True
    sec.blocked_at = _now()
    sec.blocked_reason = reason
    session.add(LoginEvent(login_id=login_id, tenant_id=tenant_id, event_type=EV_BLOCKED,
                           success=False, reason=reason, risk_level="blocked"))
    _notify(session, recipient_login_id=login_id, recipient_role="user", tenant_id=tenant_id,
            ntype="blocked", title="계정이 보안 차단되었습니다",
            body=BLOCK_MESSAGE, related_login_id=login_id)
    for admin_lid in _admin_login_ids(session):
        _notify(session, recipient_login_id=admin_lid, recipient_role="admin", tenant_id=tenant_id,
                ntype="blocked", title=f"[보안] 계정 자동차단: {login_id}",
                body=f"{login_id} 계정이 계정공유 의심 누적으로 차단되었습니다. 확인 후 해제하세요.",
                related_login_id=login_id)
    session.commit()
    # 현재 활성 세션 revoke(보안차단). 단일세션 모듈 재사용.
    try:
        from backend.services.session_pg_service import revoke_active_sessions
        revoke_active_sessions(login_id, reason="security_blocked", only_non_kiosk=False)
    except Exception:
        pass
    return True


def unblock_account(login_id: str, actor_login_id: Optional[str] = None) -> bool:
    """관리자 해제: security_blocked=false + suspicion_count=0 + 이벤트 + 사용자 알림."""
    lid = (login_id or "").strip()
    if not lid or not _configured():
        return False
    try:
        from backend.db.models.account_security import AccountSecurity, LoginEvent
        with _sl() as s:
            row = s.get(AccountSecurity, lid)
            tenant_id = row.tenant_id if row else None
            if row is None:
                row = AccountSecurity(login_id=lid, tenant_id=tenant_id)
                s.add(row)
            row.security_blocked = False
            row.blocked_at = None
            row.blocked_reason = None
            row.suspicion_count = 0
            s.add(LoginEvent(login_id=lid, tenant_id=tenant_id, event_type=EV_UNBLOCKED,
                             success=True, reason=f"unblocked_by:{actor_login_id or 'admin'}",
                             risk_level="none"))
            _notify(s, recipient_login_id=lid, recipient_role="user", tenant_id=tenant_id,
                    ntype="unblocked", title="계정 보안 차단이 해제되었습니다",
                    body="관리자 확인 후 차단이 해제되었습니다. 다시 로그인할 수 있습니다.",
                    related_login_id=lid)
            s.commit()
        return True
    except Exception:
        return False


# ── 조회(UI) ──────────────────────────────────────────────────────────────────
def recent_login_events(login_id: str, limit: int = 50) -> List[dict]:
    lid = (login_id or "").strip()
    if not lid or not _configured():
        return []
    try:
        from sqlalchemy import select
        from backend.db.models.account_security import LoginEvent
        with _sl() as s:
            rows = s.scalars(
                select(LoginEvent).where(LoginEvent.login_id == lid)
                .order_by(LoginEvent.created_at.desc()).limit(min(int(limit), 200))
            ).all()
            return [{
                "event_type": r.event_type, "ip_prefix_masked": r.ip_prefix_masked or "",
                "user_agent_summary": r.user_agent_summary or "", "success": r.success,
                "reason": r.reason or "", "risk_level": r.risk_level or "none",
                "created_at": r.created_at.isoformat() if r.created_at else "",
            } for r in rows]
    except Exception:
        return []


def security_status(login_id: str) -> dict:
    lid = (login_id or "").strip()
    if not lid or not _configured():
        return {"security_blocked": False, "suspicion_count": 0, "blocked_at": None}
    try:
        from backend.db.models.account_security import AccountSecurity
        with _sl() as s:
            row = s.get(AccountSecurity, lid)
            if not row:
                return {"security_blocked": False, "suspicion_count": 0, "blocked_at": None}
            return {"security_blocked": bool(row.security_blocked),
                    "suspicion_count": int(row.suspicion_count or 0),
                    "blocked_at": row.blocked_at.isoformat() if row.blocked_at else None}
    except Exception:
        return {"security_blocked": False, "suspicion_count": 0, "blocked_at": None}


def notifications_for(recipient_login_id: str, only_unread: bool = False, limit: int = 50) -> List[dict]:
    lid = (recipient_login_id or "").strip()
    if not lid or not _configured():
        return []
    try:
        from sqlalchemy import select
        from backend.db.models.account_security import SecurityNotification
        with _sl() as s:
            stmt = select(SecurityNotification).where(SecurityNotification.recipient_login_id == lid)
            if only_unread:
                stmt = stmt.where(SecurityNotification.is_read.is_(False))
            stmt = stmt.order_by(SecurityNotification.created_at.desc()).limit(min(int(limit), 200))
            rows = s.scalars(stmt).all()
            return [{
                "id": r.id, "type": r.type, "title": r.title or "", "body": r.body or "",
                "related_login_id": r.related_login_id or "", "is_read": bool(r.is_read),
                "recipient_role": r.recipient_role,
                "created_at": r.created_at.isoformat() if r.created_at else "",
            } for r in rows]
    except Exception:
        return []


def mark_notification_read(notification_id: int, recipient_login_id: str) -> bool:
    lid = (recipient_login_id or "").strip()
    if not lid or not _configured():
        return False
    try:
        from backend.db.models.account_security import SecurityNotification
        with _sl() as s:
            row = s.get(SecurityNotification, int(notification_id))
            if row is None or row.recipient_login_id != lid:
                return False  # 본인 알림만
            row.is_read = True
            s.commit()
            return True
    except Exception:
        return False
