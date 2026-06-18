"""Audit log model — append-only event trail.

Intentionally not foreign-keyed to ``tenants`` or ``users`` — audit rows must
survive even when the actor's account is deleted, and rows can be written
for tenants that don't yet exist in PG (during the transition window when
the source of truth is PostgreSQL).

``payload`` uses ``JSONB`` so we can index into specific keys later if a
query pattern emerges. ``ip_address`` uses ``INET`` (PG-native) for the
same reason — cheaper indexing than raw text.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str | None] = mapped_column(Text)
    actor_login_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_audit_tenant_time", "tenant_id", "created_at"),
        Index("idx_audit_target", "target_type", "target_id"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog action={self.action!r} actor={self.actor_login_id!r}>"
