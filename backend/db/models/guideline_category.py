"""실무지침 분류 오버레이 모델 (A+ 방식).

원본 immigration_guidelines_db_v2.json 은 절대 수정하지 않는다. 이 테이블들은
편집 가능한 표시명/순서/활성 상태와, row_id→category 재배치(override)만 제공한다.
실무지침은 공유 참조데이터이므로 분류는 **글로벌**(tenant_id 없음).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Text, UniqueConstraint, Index, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class GuidelineCategory(Base):
    __tablename__ = "guideline_categories"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    level: Mapped[str] = mapped_column(Text, nullable=False)            # major | middle | minor
    source_key: Mapped[str | None] = mapped_column(Text)               # JSON 파생 연결키 (없으면 커스텀)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("TRUE"))
    is_custom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("FALSE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("source_key", name="uq_guideline_category_source_key"),
        Index("idx_guideline_category_level", "level"),
    )


class GuidelineCategoryOverride(Base):
    __tablename__ = "guideline_category_overrides"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    row_id: Mapped[str] = mapped_column(Text, nullable=False)
    category_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("row_id", name="uq_guideline_override_row"),
    )
