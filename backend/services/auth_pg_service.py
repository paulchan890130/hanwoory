"""PostgreSQL-side user lookup (local beta — feature-gated).

This module is consulted by the local-beta dev endpoints
(``backend/routers/dev_pg.py``) so the user can verify the PG login path
side-by-side with the existing Google Sheets login at ``/api/auth/login``.
**It is not wired into the production login route.** As long as that route
keeps using ``backend.services.accounts_service``, existing behavior is
unaffected.

Password verification reuses ``accounts_service.verify_password`` so the
hash format on disk stays identical to what the Sheets-backed flow already
uses — the same hash works in both places.
"""
from __future__ import annotations

from typing import Optional, TypedDict

from sqlalchemy import select


class PGUserInfo(TypedDict):
    login_id: str
    tenant_id: str
    password_hash: str
    is_admin: bool
    is_active: bool
    contact_name: str


def find_user_pg(login_id: str) -> Optional[PGUserInfo]:
    """Look up one user by ``login_id``. Returns ``None`` if not found.

    Raises whatever SQLAlchemy raises on connection failure — callers
    (the dev endpoints) catch and surface as HTTP 503.
    """
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if row is None:
            return None
        return PGUserInfo(
            login_id=row.login_id,
            tenant_id=row.tenant_id,
            password_hash=row.password_hash,
            is_admin=bool(row.is_admin),
            is_active=bool(row.is_active),
            contact_name=row.contact_name or "",
        )


def verify_login_pg(login_id: str, password: str) -> Optional[PGUserInfo]:
    """Return the user dict iff the credentials are valid AND the user is active."""
    from backend.services.accounts_service import verify_password

    info = find_user_pg(login_id)
    if info is None:
        return None
    if not info["is_active"]:
        return None
    if not verify_password(password, info["password_hash"]):
        return None
    return info
