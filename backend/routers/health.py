"""DB health endpoint (Phase 1).

``GET /health/db`` is intentionally lightweight: it never raises, never
crashes the app, and tells callers exactly which of three states the
database is in:

* ``unconfigured`` — ``DATABASE_URL`` env var is missing. HTTP 200 so
  uptime checks treat this as expected during the transition window.
* ``unavailable`` — the URL is set but a connection attempt failed.
  HTTP 503 so monitoring systems flag it.
* ``ok``         — a ``SELECT 1`` round-trip succeeded. HTTP 200.

This endpoint does not touch any business data and is safe to call
publicly during development.
"""
from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from backend.db.session import DATABASE_URL_ENV, get_engine, is_configured

router = APIRouter()


@router.get("/db")
def health_db() -> JSONResponse:
    if not is_configured():
        return JSONResponse(
            status_code=200,
            content={
                "db": "unconfigured",
                "detail": f"{DATABASE_URL_ENV} is not set. PostgreSQL is "
                          "not yet wired up; the app is running on Google "
                          "PostgreSQL as before.",
            },
        )

    t0 = time.monotonic()
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency_ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(
            status_code=200,
            content={"db": "ok", "latency_ms": latency_ms},
        )
    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return JSONResponse(
            status_code=503,
            content={
                "db": "unavailable",
                "latency_ms": latency_ms,
                "error": type(exc).__name__,
                "detail": str(exc)[:500],
            },
        )
