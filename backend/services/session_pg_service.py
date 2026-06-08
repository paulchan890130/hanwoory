"""로그인 세션 PG 서비스 — 단일 세션(새 로그인 우선) 정책. PostgreSQL-only.

일반 세션(is_kiosk=false)만 단일 세션 제한 대상. raw IP/User-Agent 는 저장하지 않고
짧은 해시만 보관.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update


def new_session_id() -> str:
    return uuid.uuid4().hex


def short_hash(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip()
    if not v:
        return None
    return hashlib.sha256(v.encode("utf-8", "ignore")).hexdigest()[:16]


def revoke_active_sessions(login_id: str, reason: str, only_non_kiosk: bool = True,
                           exclude_session_id: Optional[str] = None) -> int:
    """해당 login_id 의 활성(미revoke) 세션을 revoke. 새 로그인 시 호출. 반환: revoke 건수."""
    from backend.db.models.user_session import UserSession
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        stmt = (
            update(UserSession)
            .where(UserSession.login_id == login_id, UserSession.revoked_at.is_(None))
        )
        if only_non_kiosk:
            stmt = stmt.where(UserSession.is_kiosk.is_(False))
        if exclude_session_id:
            stmt = stmt.where(UserSession.session_id != exclude_session_id)
        stmt = stmt.values(revoked_at=datetime.now(timezone.utc), revoked_reason=reason)
        result = session.execute(stmt)
        session.commit()
        return result.rowcount or 0


def create_session(login_id: str, tenant_id: str, session_id: str,
                   device_label: Optional[str] = None, user_agent: Optional[str] = None,
                   ip: Optional[str] = None, is_kiosk: bool = False) -> dict:
    from backend.db.models.user_session import UserSession
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = UserSession(
            login_id=login_id, tenant_id=tenant_id or None, session_id=session_id,
            device_label=device_label or None,
            user_agent_hash=short_hash(user_agent), ip_hash=short_hash(ip),
            is_kiosk=is_kiosk,
        )
        session.add(row)
        session.commit()
        return {"session_id": session_id, "login_id": login_id}


def session_status(session_id: str) -> str:
    """일반 세션 상태: 'active' | 'revoked' | 'missing'.
    is_kiosk=true 세션은 일반 인증에선 'missing' 으로 취급(분리)."""
    from backend.db.models.user_session import UserSession
    from backend.db.session import get_sessionmaker

    sid = str(session_id or "").strip()
    if not sid:
        return "missing"
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(select(UserSession).where(UserSession.session_id == sid))
        if row is None or row.is_kiosk:
            return "missing"
        return "revoked" if row.revoked_at is not None else "active"


def revoke_session(session_id: str, reason: str = "logout") -> bool:
    """단일 세션 revoke (로그아웃용)."""
    from backend.db.models.user_session import UserSession
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(
            update(UserSession)
            .where(UserSession.session_id == str(session_id).strip(), UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc), revoked_reason=reason)
        )
        session.commit()
        return (result.rowcount or 0) > 0
