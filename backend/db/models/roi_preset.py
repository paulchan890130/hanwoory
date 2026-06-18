"""ROI 프리셋 — 스캔(OCR) 좌표 프리셋. 테넌트당 슬롯 1/2/3 (슬롯1=기본값).

ROI 프리셋 PG 테이블(Phase I).
data 는 passport/arc 좌표 등 임의 구조라 JSONB. (tenant_id, slot) 유니크.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class RoiPreset(Base):
    __tablename__ = "roi_presets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    slot: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 | 2 | 3
    name: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict | None] = mapped_column(JSONB)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "slot", name="uq_roi_preset_per_tenant"),
    )
