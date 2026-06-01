"""Feature flags for PostgreSQL-backed code paths (local beta).

All flags default to **off** so existing Google Sheets behavior is preserved
unless the caller explicitly opts in via env var. Truthy values are
``1``/``true``/``yes``/``y``/``on`` (case-insensitive); anything else, plus
absence and empty string, is false.

Flags are read fresh on every call rather than at import time so toggling
the env var and restarting the process is enough — no module reload needed.
"""
from __future__ import annotations

import os

_TRUTHY = frozenset({"1", "true", "yes", "y", "on"})


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in _TRUTHY


def pg_users_enabled() -> bool:
    """If true, dev endpoints will query PG users; existing login is unaffected."""
    return _bool("FEATURE_PG_USERS")


def pg_audit_enabled() -> bool:
    """If true, audit_service.log_event writes to audit_logs; off → no-op."""
    return _bool("FEATURE_PG_AUDIT")


def pg_customers_enabled() -> bool:
    """Reserved for Phase 4. Not yet wired to any code path."""
    return _bool("FEATURE_PG_CUSTOMERS")


def snapshot() -> dict[str, bool]:
    """Return the current flag state. Useful for debug endpoints."""
    return {
        "FEATURE_PG_USERS": pg_users_enabled(),
        "FEATURE_PG_AUDIT": pg_audit_enabled(),
        "FEATURE_PG_CUSTOMERS": pg_customers_enabled(),
    }
