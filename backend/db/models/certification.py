"""각종공인증 — 5 tables (vendors / directions / groups / regions / prices).

Schemas mirror those defined in ``backend/services/certification_service.py``
(``VENDORS_HEADER`` etc.) so the existing router responses don't change.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class _CertBase:
    """Common columns for every certification table."""
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # uuid string
    tenant_id: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    active: Mapped[str | None] = mapped_column(Text)         # "TRUE" / "FALSE"
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)


class CertVendor(_CertBase, Base):
    __tablename__ = "cert_vendors"
    name: Mapped[str | None] = mapped_column(Text)
    contact: Mapped[str | None] = mapped_column(Text)
    memo: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("idx_cert_vendors_tenant", "tenant_id"),)


class CertDirection(_CertBase, Base):
    __tablename__ = "cert_directions"
    name: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("idx_cert_directions_tenant", "tenant_id"),)


class CertGroup(_CertBase, Base):
    __tablename__ = "cert_groups"
    group_name: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[str | None] = mapped_column(Text)
    default_direction: Mapped[str | None] = mapped_column(Text)
    applicable_directions: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("idx_cert_groups_tenant", "tenant_id"),)


class CertRegion(_CertBase, Base):
    __tablename__ = "cert_regions"
    name: Mapped[str | None] = mapped_column(Text)
    applicable_directions: Mapped[str | None] = mapped_column(Text)
    applicable_group_ids: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("idx_cert_regions_tenant", "tenant_id"),)


class CertPrice(_CertBase, Base):
    __tablename__ = "cert_prices"
    vendor_id: Mapped[str | None] = mapped_column(Text)
    group_id: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    condition: Mapped[str | None] = mapped_column(Text)
    price: Mapped[str | None] = mapped_column(Text)
    possible: Mapped[str | None] = mapped_column(Text)
    documents: Mapped[str | None] = mapped_column(Text)
    lead_time: Mapped[str | None] = mapped_column(Text)
    strength: Mapped[str | None] = mapped_column(Text)
    risk: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    last_checked: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("idx_cert_prices_tenant", "tenant_id"),)
