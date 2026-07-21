"""사무소 이용 신청(office_applications) — 수동 승인형 SaaS 온보딩.

공개 신청자가 제출하는 신청서. **승인 전까지 tenants/users 를 만들지 않는다**(신청서만 저장).
승인 시 트랜잭션으로 tenant 1개 + user 2개를 생성하고 이 행에 approved_tenant_id 를 연결한다.

상태: pending → reviewing → approved | rejected | cancelled.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class OfficeApplication(Base):
    __tablename__ = "office_applications"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))

    office_name: Mapped[str] = mapped_column(Text, nullable=False)
    representative_name: Mapped[str | None] = mapped_column(Text)
    business_registration_number: Mapped[str | None] = mapped_column(Text)
    office_address: Mapped[str | None] = mapped_column(Text)
    office_phone: Mapped[str | None] = mapped_column(Text)

    applicant_name: Mapped[str | None] = mapped_column(Text)
    applicant_email: Mapped[str | None] = mapped_column(Text)
    applicant_phone: Mapped[str | None] = mapped_column(Text)
    intended_use: Mapped[str | None] = mapped_column(Text)

    requested_user_1_name: Mapped[str | None] = mapped_column(Text)
    requested_user_1_email: Mapped[str | None] = mapped_column(Text)
    requested_user_2_name: Mapped[str | None] = mapped_column(Text)
    requested_user_2_email: Mapped[str | None] = mapped_column(Text)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(Text)

    rejection_reason_public: Mapped[str | None] = mapped_column(Text)
    review_note_internal: Mapped[str | None] = mapped_column(Text)
    approved_tenant_id: Mapped[str | None] = mapped_column(Text)
    duplicate_flags: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    submit_ip_hash: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_office_app_status_time", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<OfficeApplication {self.application_id!r} status={self.status!r}>"
