"""PostgreSQL foundation package (Phase 1).

This package exists to provide a SQLAlchemy engine, declarative base, and a
FastAPI dependency for obtaining a session. **No business tables are defined
here yet** — Phase 1 intentionally limits itself to the connection layer so
that the rest of the application (Google Sheets / Drive) is unaffected.

Importing this package must not connect to the database. The engine is only
constructed when something actively asks for it (lazy initialization in
``session.py``). This keeps app startup safe even when ``DATABASE_URL`` is
unset, which is the current default.
"""

from backend.db.session import (
    get_engine,
    get_sessionmaker,
    get_db,
    is_configured,
    DATABASE_URL_ENV,
)
from backend.db.base import Base

# Import the models package so every model registers itself on
# ``Base.metadata``. Alembic's autogenerate and ``upgrade head`` rely on
# this being complete before they read ``target_metadata`` in env.py.
from backend.db import models  # noqa: F401, E402

__all__ = [
    "Base",
    "get_engine",
    "get_sessionmaker",
    "get_db",
    "is_configured",
    "DATABASE_URL_ENV",
]
