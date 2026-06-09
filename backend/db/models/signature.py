"""Signatures — agent (per tenant), customer (per customer), and temp slots.

* ``agent_signatures`` — one per tenant. Replaces the ``행정사서명`` tab.
* ``customer_signatures`` — one per (tenant, customer). Replaces ``고객서명``.
* ``temp_signature_slots`` — three slots per tenant (1/2/3). Replaces ``서명임시저장``.

Signature payload is base64-encoded PNG. Stored as TEXT for local-beta
simplicity; production would prefer either:
* BYTEA + application-side encoding, or
* file-system reference (drive_file_id) with the bytes off the row.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class AgentSignature(Base):
    __tablename__ = "agent_signatures"

    tenant_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("tenants.tenant_id", onupdate="CASCADE"),
        primary_key=True,
    )
    signature_data: Mapped[str] = mapped_column(Text, nullable=False)  # base64 PNG
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CustomerSignature(Base):
    __tablename__ = "customer_signatures"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    customer_id: Mapped[str] = mapped_column(Text, nullable=False)
    signature_data: Mapped[str] = mapped_column(Text, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_id", name="uq_customer_signature"),
    )


class SignaturePadToken(Base):
    """상시 서명패드(/sign/pad) URL 토큰 상태 — 테넌트당 active 1행.

    완전 stateless HMAC 만으로는 '재발급 시 기존 URL 폐기'를 보장할 수 없어,
    테넌트별 active ``token_id``(UUID4) + 만료시각을 PG 에 저장한다. 토큰 문자열
    자체는 저장하지 않고, payload 의 ``jti`` 를 이 행의 ``token_id`` 와 대조해
    검증한다. 재발급은 같은 행의 token_id/issued_at/expires_at 을 갱신한다(새 행 X).
    """
    __tablename__ = "signature_pad_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    token_id: Mapped[str] = mapped_column(Text, nullable=False)  # UUID4 문자열
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    issued_by_login_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_pad_token_per_tenant"),
    )


class TempSignatureSlot(Base):
    __tablename__ = "temp_signature_slots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        Text, ForeignKey("tenants.tenant_id", onupdate="CASCADE"), nullable=False
    )
    slot: Mapped[int] = mapped_column(nullable=False)  # 1 | 2 | 3
    signature_data: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "slot", name="uq_temp_slot_per_tenant"),
        CheckConstraint("slot IN (1, 2, 3)", name="ck_temp_slot_range"),
    )
