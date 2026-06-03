"""Calendar event row — one row per (tenant_id, date_str, line).

The Sheets path stores events as a flat list of (date_str, event_text)
rows; the frontend then groups by date_str. We keep the same shape in PG
to make the repository translation trivial — no schema mismatch to bridge.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    date_str: Mapped[str] = mapped_column(Text, nullable=False)
    event_text: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("idx_events_tenant_date", "tenant_id", "date_str"),)
