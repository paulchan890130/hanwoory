"""로그인 실패 제한/계정잠금 — login_attempts (migration 0019).

동일 login_id 의 연속 실패를 카운트하고 임계 초과 시 locked_until 로 잠근다.
단일세션/is_active 차단과 독립(인증 이전 단계).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    login_id: Mapped[str] = mapped_column(Text, primary_key=True)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ip: Mapped[str | None] = mapped_column(Text)
    last_user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
