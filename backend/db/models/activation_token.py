"""activation_tokens — 최초 비밀번호 설정용 1회성 토큰.

원문 토큰은 **저장하지 않는다** — sha256 hash 만 보관한다. 만료(expires_at)와 1회성
(used_at)으로 보호한다. 승인 응답에서 raw 토큰을 1회 반환해 관리자가 대상자에게 전달한다
(자동 이메일 발송 없음).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class ActivationToken(Base):
    __tablename__ = "activation_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    login_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'activation'"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ActivationToken login_id={self.login_id!r} used={self.used_at is not None}>"
