"""Three task tables: active / planned / completed.

These mirror the corresponding Sheets tabs exactly (same column names) so
the repository can hand dicts straight to the existing router/frontend
without any key renaming.

Money columns (``transfer``, ``cash``, ``card``, ``stamp``, ``receivable``,
``planned_expense``) are TEXT, not INTEGER, because the Sheets path passes
them through as strings and the frontend's money-draft pattern relies on
that — empty string, "0", "1,000" all need to round-trip.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class ActiveTask(Base):
    __tablename__ = "active_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(Text, nullable=False)

    category: Mapped[str | None] = mapped_column(Text)
    date: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    work: Mapped[str | None] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text)

    transfer: Mapped[str | None] = mapped_column(Text)
    cash: Mapped[str | None] = mapped_column(Text)
    card: Mapped[str | None] = mapped_column(Text)
    stamp: Mapped[str | None] = mapped_column(Text)
    receivable: Mapped[str | None] = mapped_column(Text)
    planned_expense: Mapped[str | None] = mapped_column(Text)

    processed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    processed_timestamp: Mapped[str | None] = mapped_column(Text)

    reception: Mapped[str | None] = mapped_column(Text)
    processing: Mapped[str | None] = mapped_column(Text)
    storage: Mapped[str | None] = mapped_column(Text)

    customer_id: Mapped[str | None] = mapped_column(Text)
    source_daily_id: Mapped[str | None] = mapped_column(Text)

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
        UniqueConstraint("tenant_id", "task_id", name="uq_active_task_per_tenant"),
        Index("idx_active_tenant_date", "tenant_id", "date"),
    )


class PlannedTask(Base):
    __tablename__ = "planned_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[str | None] = mapped_column(Text)
    period: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
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
        UniqueConstraint("tenant_id", "task_id", name="uq_planned_task_per_tenant"),
    )


class CompletedTask(Base):
    __tablename__ = "completed_tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    date: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    work: Mapped[str | None] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text)
    complete_date: Mapped[str | None] = mapped_column(Text)
    reception: Mapped[str | None] = mapped_column(Text)
    processing: Mapped[str | None] = mapped_column(Text)
    storage: Mapped[str | None] = mapped_column(Text)
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
        UniqueConstraint("tenant_id", "task_id", name="uq_completed_task_per_tenant"),
        Index("idx_completed_tenant_customer", "tenant_id", "customer_id"),
    )
