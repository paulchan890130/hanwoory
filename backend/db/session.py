"""SQLAlchemy engine / session factory (Phase 1).

Design rules
------------
1. Importing this module must never connect to PostgreSQL. The engine is
   built lazily on first request so the FastAPI app can boot even when
   ``DATABASE_URL`` is missing (which is the case in every existing
   environment today).
2. ``get_db()`` is a FastAPI dependency that yields a ``Session`` and
   always closes it, regardless of how the request ended.
3. Render injects ``DATABASE_URL`` (or ``INTERNAL_DATABASE_URL``) as an
   environment variable. We do NOT read ``.env`` files here — the parent
   ``backend/main.py`` already calls ``load_dotenv`` early, so by the time
   this module runs, ``os.environ`` is authoritative.
4. ``sslmode=require`` is appended automatically when talking to a remote
   Render hostname and the user has not specified one. Local Postgres
   (e.g. ``postgresql://...@localhost/...``) is left untouched.
"""
from __future__ import annotations

import os
import threading
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL_ENV = "DATABASE_URL"

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker[Session]] = None
_lock = threading.Lock()


def _read_database_url() -> Optional[str]:
    """Return the configured database URL, or ``None`` when unset/empty."""
    raw = os.environ.get(DATABASE_URL_ENV, "").strip()
    return raw or None


def _normalize_url(url: str) -> str:
    """Apply small, conservative URL fixups.

    - SQLAlchemy expects ``postgresql://``; Render also exposes
      ``postgres://`` aliases that older SQLAlchemy versions rejected.
      2.x accepts both but the canonical form is preferred.
    - ``postgresql://`` defaults to the ``psycopg2`` driver, which we
      intentionally do NOT install. We installed ``psycopg`` (v3) instead,
      so rewrite the scheme to ``postgresql+psycopg://`` when no explicit
      driver was given.
    - When the host looks like a Render-managed instance and the user did
      not provide an ``sslmode``, default it to ``require`` so a missing
      SSL flag does not silently fail in production.
    """
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    if "sslmode=" not in url and (".render.com" in url or "oregon-postgres" in url):
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return url


def is_configured() -> bool:
    """True iff ``DATABASE_URL`` is present and non-empty."""
    return _read_database_url() is not None


def get_engine() -> Engine:
    """Return a process-wide SQLAlchemy engine. Lazily built.

    Raises ``RuntimeError`` when ``DATABASE_URL`` is not configured — the
    health endpoint catches this and degrades gracefully.
    """
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        url = _read_database_url()
        if not url:
            raise RuntimeError(
                f"{DATABASE_URL_ENV} is not set. PostgreSQL is not configured."
            )
        normalized = _normalize_url(url)
        pool_size = int(os.environ.get("DATABASE_POOL_SIZE", "5") or "5")
        max_overflow = int(os.environ.get("DATABASE_MAX_OVERFLOW", "10") or "10")
        connect_timeout = int(os.environ.get("DATABASE_CONNECT_TIMEOUT", "5") or "5")
        _engine = create_engine(
            normalized,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            future=True,
            connect_args={"connect_timeout": connect_timeout},
        )
        _SessionLocal = sessionmaker(
            bind=_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
            class_=Session,
        )
        return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    """Return the configured sessionmaker, building the engine if needed."""
    if _SessionLocal is None:
        get_engine()
    assert _SessionLocal is not None  # for type-checkers
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency. Yields a Session and guarantees close()."""
    SessionLocal = get_sessionmaker()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
