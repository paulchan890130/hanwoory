"""Local-only DATABASE_URL guard.

Scripts that mutate a database (alembic migrations run via CLI, account
imports, anything generating DDL) call ``assert_local_database_url`` to
make sure they're talking to a developer's loopback PG and not to a
production instance.

The set of hosts considered "local" is intentionally tiny:
``localhost`` / ``127.0.0.1`` / ``::1``. Render-style hostnames (``*.render.com``,
``dpg-...``) never match, so even a misconfigured ``DATABASE_URL`` cannot
slip through. Failure mode is ``SystemExit`` — loud and immediate; the
caller's process dies before any DB connection is opened.

This guard does NOT run when the FastAPI app boots — the app's own
``/health/db`` is already a no-op when ``DATABASE_URL`` is missing, and the
production app must of course be able to point at a non-local URL.
"""
from __future__ import annotations

import sys
from typing import Optional
from urllib.parse import urlparse

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def assert_local_database_url(url: Optional[str]) -> None:
    """Exit immediately if ``url`` is unset or its host is not loopback."""
    if not url:
        print(
            "[local-guard] DATABASE_URL is not set. This script is local-only.\n"
            "             Start a local Docker PostgreSQL and export DATABASE_URL,\n"
            "             then re-run. See LOCAL_POSTGRES_BETA_PLAN.md §3.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host not in LOCAL_HOSTS:
        print(
            f"[local-guard] DATABASE_URL host {host!r} is NOT in {sorted(LOCAL_HOSTS)}.\n"
            f"             Refusing to run a local-only script against a non-local DB.\n"
            f"             If this is a mistake, unset DATABASE_URL or point it at a\n"
            f"             local Docker PG (see LOCAL_POSTGRES_BETA_PLAN.md §3).",
            file=sys.stderr,
        )
        raise SystemExit(3)
