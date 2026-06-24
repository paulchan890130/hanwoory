"""업무별 준비서류 중분류 (document_groups).

공개 홈페이지 /documents 의 중분류(F-1, F-4, F-5/영주권, 국적·귀화 …)를
관리자가 CRUD 할 수 있도록 영구 저장하는 테이블.

글↔중분류 연결은 기존 ``marketing_posts.tags`` 의 ``doc_group:<group_key>``
태그를 그대로 사용한다(A안). 이 테이블은 중분류 *메타데이터*(이름/설명/순서/
공개여부)만 담당하며 글 테이블/slug/URL 은 일절 건드리지 않는다.

v1 정책: 물리 삭제 없음 — 공개/비공개(is_published) 전환만 제공.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class DocumentGroup(Base):
    __tablename__ = "document_groups"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # uuid string
    # doc_group:<group_key> 태그 값과 1:1 — 변경 금지(글 연결이 깨짐).
    group_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    is_published: Mapped[str | None] = mapped_column(Text)  # "TRUE" | "FALSE"
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)
    db_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("idx_document_groups_sort", "sort_order"),)
