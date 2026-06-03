"""Accommodation provider + guarantor connection (one row per target customer).

Both mirror the corresponding tabs in the customer workbook
(``숙소제공자연결`` / ``신원보증인연결``). The frontend expects exactly the
field names defined in ``frontend/lib/api.ts`` for ``AccommodationProvider``
and ``GuarantorConnection``; the PG column names match those keys 1:1 so the
service layer can hand the rows straight to the existing router.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class AccommodationProvider(Base):
    __tablename__ = "accommodation_providers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    target_customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_type: Mapped[str | None] = mapped_column(Text)            # customer_db | manual
    provider_customer_id: Mapped[str | None] = mapped_column(Text)
    provider_name: Mapped[str | None] = mapped_column(Text)
    provider_last_name: Mapped[str | None] = mapped_column(Text)
    provider_first_name: Mapped[str | None] = mapped_column(Text)
    provider_nation: Mapped[str | None] = mapped_column(Text)
    provider_reg_front: Mapped[str | None] = mapped_column(Text)
    provider_reg_back: Mapped[str | None] = mapped_column(Text)
    provider_birth: Mapped[str | None] = mapped_column(Text)
    provider_phone: Mapped[str | None] = mapped_column(Text)
    provider_address: Mapped[str | None] = mapped_column(Text)
    provider_relation: Mapped[str | None] = mapped_column(Text)
    provide_start_date: Mapped[str | None] = mapped_column(Text)
    provide_end_date: Mapped[str | None] = mapped_column(Text)
    housing_type: Mapped[str | None] = mapped_column(Text)
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
        UniqueConstraint(
            "tenant_id", "target_customer_id", name="uq_accommodation_per_target"
        ),
    )


class GuarantorConnection(Base):
    __tablename__ = "guarantor_connections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    target_customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    guarantor_type: Mapped[str | None] = mapped_column(Text)
    guarantor_customer_id: Mapped[str | None] = mapped_column(Text)
    guarantor_name: Mapped[str | None] = mapped_column(Text)
    guarantor_last_name: Mapped[str | None] = mapped_column(Text)
    guarantor_first_name: Mapped[str | None] = mapped_column(Text)
    guarantor_nation: Mapped[str | None] = mapped_column(Text)
    guarantor_reg_front: Mapped[str | None] = mapped_column(Text)
    guarantor_reg_back: Mapped[str | None] = mapped_column(Text)
    guarantor_birth: Mapped[str | None] = mapped_column(Text)
    guarantor_phone: Mapped[str | None] = mapped_column(Text)
    guarantor_address: Mapped[str | None] = mapped_column(Text)
    guarantor_relation: Mapped[str | None] = mapped_column(Text)
    guarantor_workplace: Mapped[str | None] = mapped_column(Text)
    guarantor_extra: Mapped[str | None] = mapped_column(Text)
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
        UniqueConstraint(
            "tenant_id", "target_customer_id", name="uq_guarantor_per_target"
        ),
    )
