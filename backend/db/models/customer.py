"""Customer model — one row per (tenant_id, customer_id).

The data flow keeps Korean header names in dicts that are passed
straight to the React frontend (e.g. ``한글``, ``여권``, ``등록증``). For PG
ergonomics this model uses English column names; the repository layer
(``backend/services/customer_pg_service.py``) translates between the two
shapes so the existing router and frontend keep working unchanged.

Date columns are stored as TEXT (not DATE) because the app returns
date strings as-is — and frontends already tolerate ``YYYY-MM-DD``,
``YYYY.MM.DD``, blanks, etc. Storing as TEXT preserves round-trip fidelity
and avoids surprise reformatting.

Sensitive fields (``passport_no``, ``reg_back``) are stored as plaintext
**for the local beta only** — a deliberate trade-off so PDF generation and
the existing UI keep working without an encryption layer. Production
encryption is required before any non-local deployment; see
LOCAL_USABLE_POSTGRES_FINAL_REPORT.md §"Sensitive-data handling".
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)  # 고객ID

    korean_name: Mapped[str | None] = mapped_column(Text)  # 한글
    surname_en: Mapped[str | None] = mapped_column(Text)   # 성
    given_en: Mapped[str | None] = mapped_column(Text)     # 명
    passport_no: Mapped[str | None] = mapped_column(Text)  # 여권 (sensitive)
    nationality: Mapped[str | None] = mapped_column(Text)  # 국적
    gender: Mapped[str | None] = mapped_column(Text)       # 성별

    reg_front: Mapped[str | None] = mapped_column(Text)              # 등록증
    reg_back: Mapped[str | None] = mapped_column(Text)               # 번호 (sensitive; 1차 fallback/마스킹 소스)
    # 외국인등록번호 뒷자리 암호화 보조 컬럼 (migration 0018). 평문 reg_back 은 유지(fallback).
    reg_back_encrypted: Mapped[str | None] = mapped_column(Text)        # Fernet 암호문(복호화 소스)
    reg_back_hash: Mapped[str | None] = mapped_column(Text)            # HMAC 정확검색용
    reg_back_last4: Mapped[str | None] = mapped_column(Text)           # 뒤 4자리(검색/표시 보조)
    reg_back_migrated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reg_back_enc_ver: Mapped[str | None] = mapped_column(Text)         # 암호화 버전 태그('v1')
    card_issue_date: Mapped[str | None] = mapped_column(Text)        # 발급일
    card_expiry_date: Mapped[str | None] = mapped_column(Text)       # 만기일
    passport_issue_date: Mapped[str | None] = mapped_column(Text)    # 발급
    passport_expiry_date: Mapped[str | None] = mapped_column(Text)   # 만기

    address: Mapped[str | None] = mapped_column(Text)      # 주소
    phone1: Mapped[str | None] = mapped_column(Text)       # 연
    phone2: Mapped[str | None] = mapped_column(Text)       # 락
    phone3: Mapped[str | None] = mapped_column(Text)       # 처

    v_status: Mapped[str | None] = mapped_column(Text)         # V
    visa_status: Mapped[str | None] = mapped_column(Text)      # 체류자격
    visa_type: Mapped[str | None] = mapped_column(Text)        # 비자종류
    memo: Mapped[str | None] = mapped_column(Text)             # 메모
    folder_id: Mapped[str | None] = mapped_column(Text)        # 폴더
    delegation_history: Mapped[str | None] = mapped_column(Text)  # 위임내역

    # 외부 사이트 계정(하이코리아/소시넷, migration 0026). 아이디/비밀번호 모두 **평문 TEXT**
    # (사용자 지시, 암호화 없음). 목록/검색 API·로그에는 미노출 — 상세(reveal=True)에서만 반환.
    hikorea_id: Mapped[str | None] = mapped_column(Text)
    hikorea_pw: Mapped[str | None] = mapped_column(Text)
    socinet_id: Mapped[str | None] = mapped_column(Text)
    socinet_pw: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_id", name="uq_customer_per_tenant"),
        Index("idx_customers_tenant_alive", "tenant_id", postgresql_where=(deleted_at.is_(None))),
        Index("idx_customers_card_expiry", "card_expiry_date"),
        Index("idx_customers_passport_expiry", "passport_expiry_date"),
    )
