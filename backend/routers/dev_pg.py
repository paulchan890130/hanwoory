"""Local-beta dev endpoints for the PostgreSQL migration path.

These endpoints exist so a developer can poke at the PG code path during
the local beta without touching the real ``/api/auth/login`` route. Each
endpoint guards itself by feature flag — when its flag is off it returns
HTTP 503 and explains why.

For defense-in-depth, this router is **only registered when
``HANWOORY_ENV=local``** (see ``backend/main.py``). It never reaches a
production deployment.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.db.feature_flags import (
    pg_audit_enabled,
    pg_customers_enabled,
    pg_users_enabled,
    snapshot,
)

router = APIRouter()


def _flag_off(name: str) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": f"{name} is off",
            "detail": "Set the env var to 1/true/yes and restart uvicorn to enable this endpoint.",
            "flags": snapshot(),
        },
    )


def _db_error(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": "PG access failed",
            "type": type(exc).__name__,
            "detail": str(exc)[:300],
        },
    )


# ── Status ──────────────────────────────────────────────────────────────────

@router.get("/flags")
def get_flags() -> dict:
    """Return the live state of every PG feature flag."""
    return snapshot()


# ── Users (FEATURE_PG_USERS) ────────────────────────────────────────────────

class LoginRequest(BaseModel):
    login_id: str
    password: str


@router.get("/users/count")
def users_count():
    if not pg_users_enabled():
        return _flag_off("FEATURE_PG_USERS")
    try:
        from sqlalchemy import func, select

        from backend.db.models.user import AccountUser
        from backend.db.session import get_sessionmaker

        SessionLocal = get_sessionmaker()
        with SessionLocal() as session:
            count = session.scalar(select(func.count()).select_from(AccountUser))
        return {"count": int(count or 0)}
    except Exception as e:  # noqa: BLE001 — surfaced as JSON 503
        return _db_error(e)


@router.post("/login-test")
def login_test(req: LoginRequest):
    """Verify credentials against the PG ``users`` table.

    This does NOT issue a JWT or set a session cookie. It only confirms
    that the PG row exists, is active, and the password matches.
    """
    if not pg_users_enabled():
        return _flag_off("FEATURE_PG_USERS")
    try:
        from backend.services.auth_pg_service import verify_login_pg

        info = verify_login_pg(req.login_id, req.password)
    except Exception as e:  # noqa: BLE001
        return _db_error(e)

    if info is None:
        return {"ok": False, "reason": "invalid_credentials_or_inactive"}
    return {
        "ok": True,
        "login_id": info["login_id"],
        "tenant_id": info["tenant_id"],
        "is_admin": info["is_admin"],
    }


# ── Audit (FEATURE_PG_AUDIT) ────────────────────────────────────────────────

class AuditTestRequest(BaseModel):
    action: str = "dev.test"
    tenant_id: Optional[str] = None
    actor_login_id: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[str] = None


@router.post("/audit-test")
def audit_test(req: AuditTestRequest):
    """Write one test row through audit_service. Returns the row count delta."""
    if not pg_audit_enabled():
        return _flag_off("FEATURE_PG_AUDIT")
    try:
        from sqlalchemy import func, select

        from backend.db.models.audit import AuditLog
        from backend.db.session import get_sessionmaker
        from backend.services.audit_service import log_event

        SessionLocal = get_sessionmaker()
        with SessionLocal() as session:
            before = int(session.scalar(select(func.count()).select_from(AuditLog)) or 0)

        log_event(
            action=req.action,
            tenant_id=req.tenant_id,
            actor_login_id=req.actor_login_id,
            target_type=req.target_type,
            target_id=req.target_id,
            payload={"source": "dev_pg.audit_test"},
        )

        with SessionLocal() as session:
            after = int(session.scalar(select(func.count()).select_from(AuditLog)) or 0)
        return {"ok": True, "rows_before": before, "rows_after": after, "delta": after - before}
    except Exception as e:  # noqa: BLE001
        return _db_error(e)


# ── Customers (FEATURE_PG_CUSTOMERS — placeholder) ──────────────────────────

@router.get("/customers/ping")
def customers_ping():
    """Reserved for Phase 4. Always 503 today (flag exists but no table yet)."""
    if not pg_customers_enabled():
        return _flag_off("FEATURE_PG_CUSTOMERS")
    return JSONResponse(
        status_code=501,
        content={
            "error": "Not implemented",
            "detail": "customers table is intentionally out of scope for the local beta.",
        },
    )
