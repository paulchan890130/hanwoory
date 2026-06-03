"""Daily report entries + balance.

``daily_entries`` mirrors the Sheets ``일일결산`` rows. Money fields are
stored as INTEGER (cents-free won amounts are always integral in the
current app); the Sheets path also coerces them via ``_safe_int``.

``daily_balances`` collapses the two-row Sheets "잔액" tab into a single
row per tenant (cash, profit) — much simpler to keep consistent.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class DailyEntry(Base):
    __tablename__ = "daily_entries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    entry_id: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[str | None] = mapped_column(Text)
    time: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    task: Mapped[str | None] = mapped_column(Text)
    income_cash: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    income_etc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    exp_cash: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    exp_etc: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    cash_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    memo: Mapped[str | None] = mapped_column(Text)
    customer_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "entry_id", name="uq_daily_entry_per_tenant"),
        Index("idx_daily_tenant_date", "tenant_id", "date"),
    )


class DailyBalance(Base):
    __tablename__ = "daily_balances"

    tenant_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("tenants.tenant_id", onupdate="CASCADE"),
        primary_key=True,
    )
    cash: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    profit: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
