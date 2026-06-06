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
    """If true, customers router reads/writes go to PG instead of Sheets."""
    return _bool("FEATURE_PG_CUSTOMERS")


def pg_events_enabled() -> bool:
    """If true, events router reads/writes go to PG."""
    return _bool("FEATURE_PG_EVENTS")


def pg_tasks_enabled() -> bool:
    """If true, active/planned/completed task routes go to PG."""
    return _bool("FEATURE_PG_TASKS")


def pg_daily_enabled() -> bool:
    """If true, daily entries + balance go to PG."""
    return _bool("FEATURE_PG_DAILY")


def pg_memos_enabled() -> bool:
    """If true, memos (short/mid/long) go to PG."""
    return _bool("FEATURE_PG_MEMOS")


def pg_signatures_enabled() -> bool:
    """Reserved — signature flow not yet wired (deferred for safety)."""
    return _bool("FEATURE_PG_SIGNATURES")


def pg_reference_enabled() -> bool:
    """If true, work_reference + certification routes go to PG (read side)."""
    return _bool("FEATURE_PG_REFERENCE")


def pg_board_enabled() -> bool:
    """If true, board posts/comments go to PG."""
    return _bool("FEATURE_PG_BOARD")


def pg_marketing_enabled() -> bool:
    """If true, marketing posts go to PG."""
    return _bool("FEATURE_PG_MARKETING")


def pg_admin_enabled() -> bool:
    """If true, admin account listing / approval flows go to PG."""
    return _bool("FEATURE_PG_ADMIN")


def pg_tenant_provisioning_enabled() -> bool:
    """If true, tenant workspace creation routes through the local mock."""
    return _bool("FEATURE_PG_TENANT_PROVISIONING")


def local_drive_mock_enabled() -> bool:
    """If true, Drive folder/file create/copy calls are mocked locally."""
    return _bool("FEATURE_LOCAL_DRIVE_MOCK")


def pg_manual_update_enabled() -> bool:
    """If true, manual-update (baseline/staging/decisions/state) uses PostgreSQL
    as the single source of truth. Off → file-based fallback (legacy JSON/staging).
    별개 플래그 FEATURE_MANUAL_AUTO_UPDATE 는 '자동 실행' 스위치이며, 본 플래그는
    '저장/조회를 PG 로 할지'를 제어한다."""
    return _bool("FEATURE_PG_MANUAL_UPDATE")


def snapshot() -> dict[str, bool]:
    """Return the current flag state. Useful for debug endpoints."""
    return {
        "FEATURE_PG_USERS": pg_users_enabled(),
        "FEATURE_PG_AUDIT": pg_audit_enabled(),
        "FEATURE_PG_CUSTOMERS": pg_customers_enabled(),
        "FEATURE_PG_EVENTS": pg_events_enabled(),
        "FEATURE_PG_TASKS": pg_tasks_enabled(),
        "FEATURE_PG_DAILY": pg_daily_enabled(),
        "FEATURE_PG_MEMOS": pg_memos_enabled(),
        "FEATURE_PG_SIGNATURES": pg_signatures_enabled(),
        "FEATURE_PG_REFERENCE": pg_reference_enabled(),
        "FEATURE_PG_BOARD": pg_board_enabled(),
        "FEATURE_PG_MARKETING": pg_marketing_enabled(),
        "FEATURE_PG_ADMIN": pg_admin_enabled(),
        "FEATURE_PG_TENANT_PROVISIONING": pg_tenant_provisioning_enabled(),
        "FEATURE_LOCAL_DRIVE_MOCK": local_drive_mock_enabled(),
        "FEATURE_PG_MANUAL_UPDATE": pg_manual_update_enabled(),
    }
