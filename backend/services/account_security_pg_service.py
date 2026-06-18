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


def _bool_env(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return default
    return v.strip().lower() in ("1", "true", "yes", "y", "on")


# ── 감지 임계값(상수 + env override) ──────────────────────────────────────────
def DISTINCT_IPUA_24H_THRESHOLD() -> int:
    """24h 내 서로 다른 기기(ip_prefix + ua_summary 조합) 과다 임계.

    오탐 방지를 위해 **전체 IP가 아닌 마스킹 prefix**로 기기를 식별한다(아래 주석 참조).
    동적 IP가 바뀌어도 같은 PC면 prefix/UA 가 유지 → 1개 기기로 본다.
    """
    return _int_env("SEC_DISTINCT_IPUA_24H", 3)


def SUSPICION_BLOCK_WINDOW_DAYS() -> int:
    return _int_env("SEC_BLOCK_WINDOW_DAYS", 7)


def SUSPICION_BLOCK_THRESHOLD() -> int:
    return _int_env("SEC_BLOCK_THRESHOLD", 2)


def AUTO_BLOCK_ENABLED() -> bool:
    """자동 차단 활성 여부. **베타 기본 비활성(False)**.

    비활성이면 의심 신호는 기록·알림만 하고 ``security_blocked`` 는 절대 설정하지 않는다.
    상용화 시점에만 env ``ACCOUNT_SECURITY_AUTO_BLOCK=true`` 로 명시 활성화한다.
    """
    return _bool_env("ACCOUNT_SECURITY_AUTO_BLOCK", False)


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
def _count_distinct_devices_24h(session, login_id: str) -> int:
    """24h 내 서로 다른 기기 수 — **마스킹 prefix(ip_prefix_masked) + UA 요약(user_agent_summary)** 조합으로 식별.

    의도: 같은 PC/같은 사무실이면 동적 IP가 바뀌어도(통신사 재할당/모바일/IPv6) prefix·UA 가
    유지되므로 1개 기기로 본다. 과거엔 **전체 IP 해시**로 셌기 때문에 같은 PC라도 IP가 바뀌면
    distinct 가 늘어나 정상 1인 사용을 계정공유로 오탐했다(이번 사고 원인). 서로 다른 지역/PC 일
    때만 prefix·UA 조합이 늘어난다.
    """
    from sqlalchemy import select
    from backend.db.models.account_security import LoginEvent
    since = _now() - timedelta(hours=24)
    rows = session.execute(
        select(LoginEvent.ip_prefix_masked, LoginEvent.user_agent_summary).where(
            LoginEvent.login_id == login_id,
            LoginEvent.event_type == EV_LOGIN_SUCCESS,
            LoginEvent.created_at >= since,
        )
    ).all()
    combos = {(r[0], r[1]) for r in rows if r[0] or r[1]}
    return len(combos)


def _suspicion_events_in_window(session, login_id: str) -> int:
    """차단 판정용 의심 누적 수.

    7일 창 안의 SUSPICIOUS 이벤트를 세되, **마지막 보안해제(UNBLOCKED) 이후**만 센다.
    (해제 직후 과거 의심으로 즉시 재차단되는 것을 방지 — 관리자가 풀면 카운터가 실효 초기화.)
    """
    from sqlalchemy import select, func as f
    from backend.db.models.account_security import LoginEvent
    since = _now() - timedelta(days=SUSPICION_BLOCK_WINDOW_DAYS())
    last_unblock = session.scalar(
        select(f.max(LoginEvent.created_at)).where(
            LoginEvent.login_id == login_id,
            LoginEvent.event_type == EV_UNBLOCKED,
        )
    )
    effective_since = max(since, last_unblock) if last_unblock else since
    return int(session.scalar(
        select(f.count()).select_from(LoginEvent).where(
            LoginEvent.login_id == login_id,
            LoginEvent.event_type == EV_SUSPICIOUS,
            LoginEvent.created_at > effective_since,
        )
    ) or 0)


def _is_admin(session, login_id: str) -> bool:
    """해당 계정이 관리자인지. 조회 실패 시 보수적으로 False(=일반 사용자 취급)."""
    try:
        from sqlalchemy import select
        from backend.db.models.user import AccountUser
        return bool(session.scalar(
            select(AccountUser.is_admin).where(AccountUser.login_id == login_id)
        ))
    except Exception:
        return False


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
    """로그인 직후 호출. **강한 증거**만 의심으로 본다(기록·알림 중심).

    정책(2026-06-18 재점검 — 정상 1인 사용 오탐/과민 차단 사고 후):
    - 의심 기준은 **단 하나**: 24h 내 서로 다른 기기(ip prefix + UA 요약 조합)가 임계(기본 3) 이상.
      → 같은 PC/같은 사무실/같은 브라우저 재로그인·세션 밀림·동적 IP 변경은 1개 기기로 보아 **제외**.
    - 폐기된 과거 기준(오탐 원인, 더 이상 의심으로 세지 않음):
        · SESSION_REVOKED_BY_NEW_LOGIN(단일세션 밀림) — 이력으로만 기록.
        · 30분 내 반복 로그인/로그아웃 — 정상 재로그인/토큰만료 재로그인 포함이라 제외.
        · 전체 IP 해시 기반 distinct(동적 IP가 바뀌면 같은 PC도 다중 기기로 오탐) — prefix 기반으로 교체.
    - 차단은 **AUTO_BLOCK_ENABLED()** 가 true 일 때만(베타 기본 false → 기록·알림만).
    - **관리자 계정은 자동 차단 제외**(_block 내부에서 break-glass 처리).

    반환: {"suspicious": bool, "blocked": bool}. graceful(오류 → no-op).
    """
    lid = (login_id or "").strip()
    out = {"suspicious": False, "blocked": False}
    if not lid or not _configured():
        return out
    try:
        from backend.db.models.account_security import LoginEvent
        with _sl() as s:
            distinct_devices = _count_distinct_devices_24h(s, lid)
            # 유일 기준: 24시간 내 서로 다른 기기(prefix+UA) 과다 = 강한 증거.
            if distinct_devices < DISTINCT_IPUA_24H_THRESHOLD():
                return out
            reason_str = f"distinct_devices_24h={distinct_devices}"

            # 1회 의심 — 이벤트 + 카운트 + 알림(본인+관리자). 차단은 아래에서 별도 판단.
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

            # 자동 차단은 베타 기본 비활성. 활성 시에도 7일 내 누적 임계 이상 + 관리자 예외(_block).
            if AUTO_BLOCK_ENABLED():
                with _sl() as s2:
                    if _suspicion_events_in_window(s2, lid) >= SUSPICION_BLOCK_THRESHOLD():
                        out["blocked"] = _block(s2, lid, tenant_id, reason_str)
        return out
    except Exception:
        return out


def _block(session, login_id: str, tenant_id: Optional[str], reason: str) -> bool:
    from backend.db.models.account_security import LoginEvent
    # 관리자 break-glass: 관리자 계정은 자동 차단하지 않는다(차단되면 전체 시스템 관리 불가).
    # 대신 강한 경고를 관리자 전원에게 알린다. security_blocked 는 설정하지 않음.
    if _is_admin(session, login_id):
        session.add(LoginEvent(login_id=login_id, tenant_id=tenant_id, event_type=EV_SUSPICIOUS,
                               success=False, reason=f"admin_block_skipped:{reason}", risk_level="suspicious"))
        for admin_lid in _admin_login_ids(session):
            _notify(session, recipient_login_id=admin_lid, recipient_role="admin", tenant_id=tenant_id,
                    ntype="suspicious", title=f"[보안] 관리자 계정 의심 누적(자동차단 제외): {login_id}",
                    body=(f"{login_id}(관리자) 계정에서 계정공유 의심이 누적되었습니다. "
                          f"관리자 계정은 자동 차단되지 않으니 직접 확인하세요."),
                    related_login_id=login_id)
        session.commit()
        return False
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
def recent_login_events(login_id: str, limit: int = 50, offset: int = 0) -> List[dict]:
    lid = (login_id or "").strip()
    if not lid or not _configured():
        return []
    try:
        from sqlalchemy import select
        from backend.db.models.account_security import LoginEvent
        with _sl() as s:
            rows = s.scalars(
                select(LoginEvent).where(LoginEvent.login_id == lid)
                .order_by(LoginEvent.created_at.desc())
                .offset(max(0, int(offset))).limit(min(int(limit), 200))
            ).all()
            return [{
                "event_type": r.event_type, "ip_prefix_masked": r.ip_prefix_masked or "",
                "user_agent_summary": r.user_agent_summary or "", "success": r.success,
                "reason": r.reason or "", "risk_level": r.risk_level or "none",
                "created_at": r.created_at.isoformat() if r.created_at else "",
            } for r in rows]
    except Exception:
        return []


def recent_login_events_all(limit: int = 50, only_suspicious: bool = False, offset: int = 0) -> List[dict]:
    """전 계정 최근 로그인/보안 이벤트(관리자용, 검색 없이 기본 노출). 원문 PII 미반환.

    require_admin 라우터에서만 호출(슈퍼관리자는 교차 테넌트 계정관리와 동일 범위). 오류 시 빈 목록.
    """
    if not _configured():
        return []
    try:
        from sqlalchemy import select
        from backend.db.models.account_security import LoginEvent
        with _sl() as s:
            stmt = select(LoginEvent)
            if only_suspicious:
                stmt = stmt.where(LoginEvent.risk_level.in_(["suspicious", "blocked"]))
            stmt = (stmt.order_by(LoginEvent.created_at.desc())
                    .offset(max(0, int(offset))).limit(min(int(limit), 300)))
            rows = s.scalars(stmt).all()
            return [{
                "login_id": r.login_id, "tenant_id": r.tenant_id or "",
                "event_type": r.event_type, "ip_prefix_masked": r.ip_prefix_masked or "",
                "user_agent_summary": r.user_agent_summary or "", "success": r.success,
                "reason": r.reason or "", "risk_level": r.risk_level or "none",
                "created_at": r.created_at.isoformat() if r.created_at else "",
            } for r in rows]
    except Exception:
        return []


def list_blocked_accounts(limit: int = 200, offset: int = 0) -> List[dict]:
    """보안차단(security_blocked=true) 계정 목록(관리자용). 원문 PII 미반환. 오류 시 빈 목록."""
    if not _configured():
        return []
    try:
        from sqlalchemy import select
        from backend.db.models.account_security import AccountSecurity
        with _sl() as s:
            rows = s.scalars(
                select(AccountSecurity).where(AccountSecurity.security_blocked.is_(True))
                .order_by(AccountSecurity.blocked_at.desc().nullslast())
                .offset(max(0, int(offset))).limit(min(int(limit), 500))
            ).all()
            return [{
                "login_id": r.login_id, "tenant_id": r.tenant_id or "",
                "suspicion_count": int(r.suspicion_count or 0),
                "blocked_at": r.blocked_at.isoformat() if r.blocked_at else None,
                "blocked_reason": r.blocked_reason or "",
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


def notifications_for(recipient_login_id: str, only_unread: bool = False, limit: int = 50, offset: int = 0) -> List[dict]:
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
            stmt = (stmt.order_by(SecurityNotification.created_at.desc())
                    .offset(max(0, int(offset))).limit(min(int(limit), 200)))
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
