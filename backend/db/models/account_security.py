"""계정공유 의심 감지 / 로그인 이력 / 보안 알림 모델 (migration 0021, 베타).

등록기기 개념 없음. IP/UA 는 해시 + 마스킹/요약만 저장(원문 전체 미저장).
``account_security.security_blocked`` 는 관리자 비활성(``users.is_active``)과 구분된다.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class LoginEvent(Base):
    __tablename__ = "login_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str | None] = mapped_column(Text)
    login_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(Text)
    ip_prefix_masked: Mapped[str | None] = mapped_column(Text)
    user_agent_hash: Mapped[str | None] = mapped_column(Text)
    user_agent_summary: Mapped[str | None] = mapped_column(Text)
    success: Mapped[bool | None] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text)
    risk_level: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AccountSecurity(Base):
    __tablename__ = "account_security"

    login_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(Text)
    suspicion_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_suspicion_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    security_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SecurityNotification(Base):
    __tablename__ = "security_notifications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    recipient_login_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    recipient_role: Mapped[str] = mapped_column(Text, nullable=False)  # admin|user
    tenant_id: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text, nullable=False)            # suspicious|blocked|unblocked
    title: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    related_login_id: Mapped[str | None] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
