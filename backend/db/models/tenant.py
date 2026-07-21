"""Tenant model — one row per office/workspace.

The natural key is ``tenant_id`` (TEXT), which matches the value already used
in JWTs and across ``backend.services.tenant_service``. The numeric ``id`` is
a surrogate primary key for FKs that prefer integers; ``tenant_id`` is the
business key and is UNIQUE.

Sheet keys (``customer_sheet_key`` / ``work_sheet_key``) and Drive folder ID
are mirrored here during the transition window so the PG row carries enough
context for tenant routing when needed. Once the legacy layer is
retired, those columns can be dropped.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, LargeBinary, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
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
    # ── 전자명함(business card) — 마이페이지 입력 / 공개 /card/{slug} (migration 0015) ──
    card_bio: Mapped[str | None] = mapped_column(Text)
    card_work_fields: Mapped[list | None] = mapped_column(JSONB)
    card_phone: Mapped[str | None] = mapped_column(Text)
    card_address: Mapped[str | None] = mapped_column(Text)
    card_logo_url: Mapped[str | None] = mapped_column(Text)
    # 업로드 로고(파일) — migration 0016. card_logo_url(외부 URL)보다 우선 표시.
    card_logo_filename: Mapped[str | None] = mapped_column(Text)
    card_logo_mime: Mapped[str | None] = mapped_column(Text)
    card_logo_size: Mapped[int | None] = mapped_column(Integer)
    card_logo_bytes: Mapped[bytes | None] = mapped_column(LargeBinary)
    card_logo_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    card_public_slug: Mapped[str | None] = mapped_column(Text, unique=True)
    card_is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("TRUE")
    )
    # ── 승인형 SaaS lifecycle (migration 0031) — deferred: 0031 미적용 DB 에서도
    #    기존 full-row select(Tenant) 가 깨지지 않도록 명시 접근 시에만 읽는다. ──
    service_tier: Mapped[str] = mapped_column(
        Text, nullable=False, default="managed_basic",
        server_default=text("'managed_basic'"), deferred=True,
    )
    seat_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, server_default=text("2"), deferred=True,
    )
    service_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending_activation",
        server_default=text("'pending_activation'"), deferred=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), deferred=True)
    approved_by: Mapped[str | None] = mapped_column(Text, deferred=True)
    source_application_id: Mapped[str | None] = mapped_column(Text, deferred=True)
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
