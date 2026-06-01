"""Alembic environment (Phase 1).

Reads the database URL from the ``DATABASE_URL`` environment variable
(falling back to ``alembic.ini``'s ``sqlalchemy.url`` if explicitly set,
which we deliberately leave blank). Phase 1 does NOT register any
business models — ``target_metadata`` is the empty ``Base.metadata`` so
``alembic revision --autogenerate`` will emit no changes until Phase 2.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Make the project root importable so ``backend.*`` and ``config`` resolve
# when alembic is invoked from the repo root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.db.base import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject DATABASE_URL at runtime; alembic.ini's sqlalchemy.url stays empty.
# Mirror the driver-selection logic in backend/db/session.py:_normalize_url
# so alembic and the FastAPI app agree on which psycopg driver to use.
_env_url = os.environ.get("DATABASE_URL", "").strip()
if _env_url:
    if _env_url.startswith("postgres://"):
        _env_url = "postgresql://" + _env_url[len("postgres://"):]
    if _env_url.startswith("postgresql://"):
        _env_url = "postgresql+psycopg://" + _env_url[len("postgresql://"):]
    config.set_main_option("sqlalchemy.url", _env_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is not set and alembic.ini has no sqlalchemy.url. "
            "Set DATABASE_URL before running alembic."
        )
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {}) or {}
    if not section.get("sqlalchemy.url"):
        raise RuntimeError(
            "DATABASE_URL is not set and alembic.ini has no sqlalchemy.url. "
            "Set DATABASE_URL before running alembic."
        )
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
