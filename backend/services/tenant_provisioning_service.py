"""Idempotent PG tenant provisioning helper.

When a tenant's data is stored in PostgreSQL (FEATURE_PG_CUSTOMERS et al.),
every ``customers``/``tasks``/… row carries a FK to ``tenants.tenant_id``.
Accounts created before PG provisioning (e.g. admin ``create_account``) never
got a PG ``tenants`` row, so the first PG write fails with
``customers_tenant_id_fkey``. This helper closes that gap without changing
the login/account flow.

Design
------
* **Idempotent**: existing tenant rows are never touched (check-then-insert).
* **No-op without PG**: when ``DATABASE_URL`` is unset,
  this returns ``False`` and never connects — existing behavior unchanged.
* **Additive**: only inserts a missing tenant row; never updates or deletes.
"""
from __future__ import annotations

from typing import Optional


def ensure_tenant_provisioned(tenant_id: str, office_name: Optional[str] = None) -> bool:
    """Ensure a PG ``tenants`` row exists for ``tenant_id``.

    Returns ``True`` iff a new row was created, ``False`` if it already
    existed or PG is not configured. Idempotent and safe to call repeatedly.
    """
    from backend.db.session import is_configured, get_sessionmaker

    if not is_configured():
        return False
    tid = (tenant_id or "").strip()
    if not tid:
        return False

    from sqlalchemy import select
    from backend.db.models.tenant import Tenant

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        if session.scalar(select(Tenant).where(Tenant.tenant_id == tid)):
            return False
        session.add(Tenant(
            tenant_id=tid,
            office_name=(office_name or "").strip() or tid,  # office_name NOT NULL
            is_active=True,
        ))
        session.commit()
        return True
