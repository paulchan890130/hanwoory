"""Audit-log service (local beta — guarded by FEATURE_PG_AUDIT).

``log_event`` is intentionally best-effort: it never raises, never blocks the
caller, and is a no-op whenever:

1. ``FEATURE_PG_AUDIT`` is not set to a truthy value, or
2. ``DATABASE_URL`` is unset, or
3. The DB write itself fails for any reason.

Audit failures must not break the surrounding request. If you need a hard
guarantee that an event is recorded (e.g. compliance), use a separate code
path — this service is observability, not durability.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from backend.db.feature_flags import pg_audit_enabled
from backend.db.session import is_configured

_log = logging.getLogger("audit")


def log_event(
    *,
    action: str,
    actor_login_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    if not pg_audit_enabled():
        return
    if not is_configured():
        _log.warning("audit: FEATURE_PG_AUDIT on but DATABASE_URL missing — skipping")
        return

    try:
        # Local imports keep this module importable even when SQLAlchemy isn't.
        from backend.db.models.audit import AuditLog
        from backend.db.session import get_sessionmaker

        SessionLocal = get_sessionmaker()
        with SessionLocal() as session:
            entry = AuditLog(
                action=action,
                actor_login_id=actor_login_id,
                tenant_id=tenant_id,
                target_type=target_type,
                target_id=target_id,
                payload=payload,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            session.add(entry)
            session.commit()
    except Exception as e:  # noqa: BLE001 — by-design swallow
        _log.warning("audit write failed (swallowed): %s: %s", type(e).__name__, e)
