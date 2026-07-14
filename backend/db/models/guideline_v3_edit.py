"""실무지침 v3 편집 오버레이 모델 (migration 0030).

정본 JSON(backend/data/guidelines_v3)은 수정하지 않는다. 이 테이블은 엔터티 단위
오버레이(upsert 전체 payload / delete 톰스톤)만 보관하고, 읽기 시점에 병합된다.
엔터티당 최신 상태 1행 — 변경 이력은 audit_logs(FEATURE_PG_AUDIT)가 담당.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, UniqueConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class GuidelineV3Edit(Base):
    __tablename__ = "guideline_v3_edits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)   # group | qualification | stay_block | visa_route | doc_requirement
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)     # 예: "F", "Q:F-2-7S", "SB:...", "VR:...", "DR:..."
    op: Mapped[str] = mapped_column(Text, nullable=False, server_default="upsert")  # upsert | delete
    payload: Mapped[str | None] = mapped_column(Text)                # 엔터티 전체 dict(JSON 문자열), delete는 NULL
    updated_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", name="uq_guideline_v3_edit_entity"),
        Index("idx_guideline_v3_edits_type", "entity_type"),
    )
