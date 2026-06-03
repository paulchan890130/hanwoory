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


# ── Explicit, confirmed remote (e.g. Render) execution ───────────────────────
# The default contract above is unchanged: local loopback only. The helper
# below is the *single source of truth* for the one narrow escape hatch —
# writing to a non-local DB requires three explicit signals together. It is
# shared by the importer and the password-migration script so the policy and
# confirmation string can never drift between them.
REMOTE_CONFIRM_STRING = "I-UNDERSTAND-IMPORT-TO-RENDER-PG"


def database_host(url: Optional[str]) -> str:
    return (urlparse(url).hostname or "").lower() if url else ""


def mask_host(host: str) -> str:
    """Show enough of the host to recognize it, hiding the unique middle.

    ``urlparse().hostname`` excludes any ``user:pass`` — no credential leaks."""
    if not host:
        return "(none)"
    if len(host) <= 12:
        return host[:3] + "***"
    return f"{host[:8]}…{host[-12:]}"


def looks_render_host(host: str) -> bool:
    h = host or ""
    return ("render.com" in h) or h.startswith("dpg-")


def resolve_execution_mode(
    url: Optional[str],
    *,
    allow_remote: bool,
    confirm: str,
    reset_requested: bool = False,
    command_hint: str = "",
    say=print,
) -> Optional[str]:
    """Decide how a mutating script may proceed against ``url``.

    Returns ``"LOCAL"`` or ``"REMOTE_RENDER_CONFIRMED"`` when allowed, or
    ``None`` after printing a clear abort message (caller should exit non-zero).
    Unset / local URLs delegate to :func:`assert_local_database_url` (which
    exits on unset). No DB connection is opened here; no password is printed.
    """
    host = database_host(url)

    if not url:
        assert_local_database_url(url)   # exits(2) with the standard message
        return None                      # unreachable

    if host in LOCAL_HOSTS:
        assert_local_database_url(url)   # belt-and-suspenders; passes for loopback
        say(f"[guard]   target host: {mask_host(host)}  (LOCAL loopback)")
        say("[guard]   execution mode: LOCAL")
        return "LOCAL"

    # ── Non-local host ──
    # Hard block: destructive reset must NEVER touch a non-local DB, even with
    # the allow flag + confirmation present.
    if reset_requested:
        say(f"[guard][ABORT] destructive reset is FORBIDDEN against a non-local DB "
            f"(host {mask_host(host)}). Remove the reset flag to import into Render.")
        return None

    if not (allow_remote and confirm == REMOTE_CONFIRM_STRING):
        say(f"[guard][ABORT] DATABASE_URL points at a NON-LOCAL host "
            f"({mask_host(host)}) — refusing without explicit confirmation.")
        if allow_remote and confirm != REMOTE_CONFIRM_STRING:
            say("[guard]        --allow-remote-render-pg given but --confirm does not match.")
        if command_hint:
            say("[guard]        To proceed against the remote DB, run EXACTLY:")
            for line in command_hint.splitlines():
                say(f"[guard]          {line}")
        return None

    kind = "Render-style" if looks_render_host(host) else "non-local (explicitly confirmed)"
    say(f"[guard]   target host: {mask_host(host)}  ({kind})")
    say("[guard]   execution mode: REMOTE_RENDER_CONFIRMED")
    return "REMOTE_RENDER_CONFIRMED"
