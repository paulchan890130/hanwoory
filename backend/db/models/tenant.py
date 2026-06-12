"""Tenant model — one row per office/workspace.

The natural key is ``tenant_id`` (TEXT), which matches the value already used
in JWTs and across ``backend.services.tenant_service``. The numeric ``id`` is
a surrogate primary key for FKs that prefer integers; ``tenant_id`` is the
business key and is UNIQUE.

Sheet keys (``customer_sheet_key`` / ``work_sheet_key``) and Drive folder ID
are mirrored here during the transition window so the PG row carries enough
context to talk to the existing Google layer when needed. Once Sheets is
retired, those columns can be dropped.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    office_name: Mapped[str] = mapped_column(Text, nullable=False)
    office_adr: Mapped[str | None] = mapped_column(Text)
    biz_reg_no: Mapped[str | None] = mapped_column(Text)
    agent_rrn_hash: Mapped[str | None] = mapped_column(Text)
    # 행정사 주민등록번호 — 복호화 가능한 암호문(PDF 출력 소스). 평문 컬럼은 두지 않는다.
    agent_rrn_encrypted: Mapped[str | None] = mapped_column(Text)
    agent_rrn_last4: Mapped[str | None] = mapped_column(String(4))
    agent_rrn_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    folder_id: Mapped[str | None] = mapped_column(Text)
    customer_sheet_key: Mapped[str | None] = mapped_column(Text)
    work_sheet_key: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("TRUE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<Tenant tenant_id={self.tenant_id!r} office={self.office_name!r}>"
