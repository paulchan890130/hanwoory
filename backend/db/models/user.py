"""Account user model — one row per login_id.

The class is named ``AccountUser`` (not ``User``) to avoid shadowing the
ubiquitous ``user`` dict that FastAPI dependencies pass around in this
codebase. The table is still ``users``.

The ``password_hash`` column stores the same pbkdf2_hmac(sha256)+base64 value
produced by ``backend.services.accounts_service.hash_password`` — it's
deliberately the same format so we can carry hashes forward without
re-asking users for passwords.

``tenant_id`` references ``tenants.tenant_id`` (the business key, not the
surrogate ``id``). The FK uses ``ON UPDATE CASCADE`` so renaming a tenant
ID propagates cleanly; deletion is restricted by default to avoid orphaning
users.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class AccountUser(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    login_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("tenants.tenant_id", onupdate="CASCADE"),
        nullable=False,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    contact_name: Mapped[str | None] = mapped_column(Text)
    contact_tel: Mapped[str | None] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("FALSE")
    )
    # 'user'(기본) | 'sub_admin'(준 관리자) | 'admin'. full admin 여부는 is_admin 이
    # source of truth 이고, role 은 sub_admin 구분용 추가 컬럼이다(migration 0024).
    # deferred=True: 기본 full-row SELECT 에 포함하지 않는다 → 0024 미적용 DB 에서도
    # 기존 select(AccountUser) 가 깨지지 않는다(role 은 명시 접근 시에만, 가드와 함께 읽음).
    role: Mapped[str] = mapped_column(
        Text, nullable=False, default="user", server_default=text("'user'"), deferred=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("TRUE")
    )
    # ── 승인형 SaaS lifecycle (migration 0031) — deferred: 0031 미적용 DB 에서도
    #    기존 full-row select(AccountUser) 가 깨지지 않도록 명시 접근 시에만 읽는다.
    #    is_active 가 여전히 로그인/차단의 source of truth 이고, account_status 는 병행 상태값. ──
    account_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="active",
        server_default=text("'active'"), deferred=True,
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), deferred=True)
    approved_by: Mapped[str | None] = mapped_column(Text, deferred=True)
    replaced_by_user_id: Mapped[int | None] = mapped_column(BigInteger, deferred=True)
    replaces_user_id: Mapped[int | None] = mapped_column(BigInteger, deferred=True)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), deferred=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), deferred=True)
    # ── 최초 로그인 온보딩(사용법 안내) 상태 (migration 0032) — deferred: 미적용 DB 에서도
    #    기존 full-row select(AccountUser) 가 깨지지 않도록 명시 접근 시에만 읽는다.
    #    NULL = 미완료(신규 초대 사용자). 기존 사용자는 migration 에서 현재 버전으로 backfill. ──
    onboarding_completed_version: Mapped[int | None] = mapped_column(Integer, deferred=True)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), deferred=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<AccountUser login_id={self.login_id!r} tenant_id={self.tenant_id!r}>"
