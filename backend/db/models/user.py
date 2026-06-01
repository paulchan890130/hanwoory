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

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Text, func, text
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
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("TRUE")
    )
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
