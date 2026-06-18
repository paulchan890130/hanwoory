"""Finance models — fixed expenses ledger + monthly tax/VAT summary.

PostgreSQL-only. Exposed only when ``FEATURE_PG_DAILY`` is on.

* ``fixed_expenses`` — one row per (tenant, month, expense). Recurring items are
  materialized as explicit monthly rows ("전월 복사" helper), keeping the ledger
  auditable. ``expense_id`` is the business key for id-based upsert/delete.
* ``monthly_tax_summaries`` — one upsert row per (tenant, year_month) holding the
  management-estimate reported revenue/expense + VAT figures.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class FixedExpense(Base):
    __tablename__ = "fixed_expenses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False, index=True
    )
    expense_id: Mapped[str] = mapped_column(Text, nullable=False)
    year_month: Mapped[str] = mapped_column(Text, nullable=False)  # "YYYY-MM"
    name: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    category: Mapped[str | None] = mapped_column(Text)
    payment_method: Mapped[str | None] = mapped_column(Text)  # 카드/계좌/현금
    vat_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("FALSE"))
    vat_amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    memo: Mapped[str | None] = mapped_column(Text)
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("FALSE"))
    start_month: Mapped[str | None] = mapped_column(Text)
    end_month: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "expense_id", name="uq_fixed_expense_per_tenant"),
        Index("idx_fixed_expense_tenant_ym", "tenant_id", "year_month"),
    )


class MonthlyTaxSummary(Base):
    __tablename__ = "monthly_tax_summaries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False, index=True
    )
    year_month: Mapped[str] = mapped_column(Text, nullable=False)  # "YYYY-MM"
    reported_revenue: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reported_expense: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reported_output_vat: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reported_input_vat: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    expected_vat_payable: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    vat_basis: Mapped[str] = mapped_column(Text, nullable=False, default="tax_included", server_default="tax_included")
    memo: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "year_month", name="uq_monthly_tax_per_tenant"),
    )
