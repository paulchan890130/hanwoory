"""로그인 세션 원장 — 단일 세션(새 로그인 우선) 정책.

일반 로그인 세션만 대상. is_kiosk=true 세션(추후 서명 키오스크/QR 토큰)은 분리.
login_id/tenant_id 는 Sheets·PG 어느 경로든 동작하도록 FK 없이 Text 로 보관.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Text, UniqueConstraint, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    login_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(Text)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    device_label: Mapped[str | None] = mapped_column(Text)
    user_agent_hash: Mapped[str | None] = mapped_column(Text)
    ip_hash: Mapped[str | None] = mapped_column(Text)
    is_kiosk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("FALSE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("session_id", name="uq_user_session_sid"),
        Index("idx_user_session_login", "login_id"),
    )
