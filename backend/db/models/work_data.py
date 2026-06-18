"""Work-reference data — freeform tabs in the ``work_sheet_key`` workbook.

The reference router exposes arbitrary tabs (``업무참고``, ``업무정리``, and
whatever the user added). Schema is therefore JSONB so we can store
heterogeneous rows without losing fidelity.

* ``work_reference_sheets`` — one row per (tenant, sheet_name), holds the
  header order and a sheet-level update timestamp.
* ``work_reference_rows`` — one row per (tenant, sheet_name, row_index),
  data column is JSONB keyed by header → cell text.

Read-side router (``GET /api/reference/sheets`` and ``/data``) goes through
PG when ``FEATURE_PG_REFERENCE`` is on. Edit endpoints stay on the legacy store
because the existing ``reference_edit_service`` performs cell-precise
updates that are too elaborate to fully replicate this round —
those edits remain on the legacy store.
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class WorkReferenceSheet(Base):
    __tablename__ = "work_reference_sheets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    sheet_name: Mapped[str] = mapped_column(Text, nullable=False)
    headers: Mapped[list[str] | None] = mapped_column(JSONB)
    # PG-only(Phase G) UI 메타: {"col_widths": {col_key: px}, "row_heights": {row_index: px}}
    meta: Mapped[dict | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "sheet_name", name="uq_work_ref_sheet_per_tenant"),
    )


class WorkReferenceRow(Base):
    __tablename__ = "work_reference_rows"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    sheet_name: Mapped[str] = mapped_column(Text, nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "sheet_name", "row_index", name="uq_work_ref_row"
        ),
        Index("idx_work_ref_rows_lookup", "tenant_id", "sheet_name", "row_index"),
    )
