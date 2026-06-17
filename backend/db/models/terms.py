"""약관/개인정보 동의 — terms_versions, user_terms_acceptances (migration 0020)."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class TermsVersion(Base):
    __tablename__ = "terms_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)   # tos|privacy|unique_id|no_share
    version: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    effective_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("type", "version", name="uq_terms_type_version"),
    )


class UserTermsAcceptance(Base):
    __tablename__ = "user_terms_acceptances"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    login_id: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_id: Mapped[str | None] = mapped_column(Text)
    terms_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ip: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("login_id", "terms_version_id", name="uq_user_terms_once"),
    )
