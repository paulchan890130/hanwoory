"""Marketing 이미지 (PG BYTEA 저장 — Google Drive 대체, migration 0022).

마케팅 게시글 본문/커버 이미지를 Google Drive 대신 PostgreSQL 에 원본 바이트로 저장한다.
공개 서빙은 ``GET /api/marketing/images/{id}`` (무인증). 목록 조회 시 ``data`` BYTEA 는
절대 함께 로드하지 않는다(단건 PK 조회에서만 로드).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, LargeBinary, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class MarketingImage(Base):
    __tablename__ = "marketing_images"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(Text)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("idx_marketing_images_tenant", "tenant_id"),
        Index("idx_marketing_images_created", "created_at"),
    )
