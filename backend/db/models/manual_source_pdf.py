"""원문 매뉴얼 PDF 저장소 (migration 0029).

실무지침 업데이트 검토함의 '원문 열기'용 — manual_type(visa/stay)별로
**최신 1개 + 직전 1개만** 보관한다(3번째로 오래된 것은 업로드 시 자동 삭제).
저장은 PostgreSQL BYTEA (운영 source of truth = PG, Render ephemeral FS 미의존).

OOM 규칙: 목록 조회는 pdf_data 를 defer 로 제외하고, blob 은 id 단건으로만 로드.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, LargeBinary, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class ManualSourcePdf(Base):
    __tablename__ = "manual_source_pdfs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    manual_type: Mapped[str] = mapped_column(Text, nullable=False)       # visa | stay
    version_label: Mapped[str | None] = mapped_column(Text)             # 예: 260617
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)      # application/pdf
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    pdf_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    uploaded_by: Mapped[str | None] = mapped_column(Text)               # login_id (PII 아님)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_manual_source_pdfs_type_current", "manual_type", "is_current"),
    )
