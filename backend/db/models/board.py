"""Board posts + comments (shared across all tenants in the production system).

These rows live in PostgreSQL (board tables).
In PG they live in standalone tables, keyed by ``tenant_id`` but readable
across tenants (matching the existing public-board semantics).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class BoardPost(Base):
    __tablename__ = "board_posts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # UUID string
    tenant_id: Mapped[str | None] = mapped_column(Text)
    author_login: Mapped[str | None] = mapped_column(Text)
    office_name: Mapped[str | None] = mapped_column(Text)
    is_notice: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)  # ISO string from sheet
    updated_at: Mapped[str | None] = mapped_column(Text)
    popup_yn: Mapped[str | None] = mapped_column(Text)
    link_url: Mapped[str | None] = mapped_column(Text)
    comment_count: Mapped[int] = mapped_column(default=0, server_default="0")
    db_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_board_posts_category", "category"),
    )


class BoardComment(Base):
    __tablename__ = "board_comments"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    post_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    tenant_id: Mapped[str | None] = mapped_column(Text)
    author_login: Mapped[str | None] = mapped_column(Text)
    office_name: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(Text)
    db_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
