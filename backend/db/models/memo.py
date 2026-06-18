"""Memo model — one row per (tenant_id, kind).

Rows store memos as the literal A1 cell of a per-kind tab.
Here we collapse the three kinds (short / mid / long) into a single
relational table, one row per kind per tenant.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


MEMO_KINDS = ("short", "mid", "long")


class Memo(Base):
    __tablename__ = "memos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "kind", name="uq_memo_per_tenant_kind"),
        CheckConstraint("kind IN ('short', 'mid', 'long')", name="ck_memo_kind"),
    )
