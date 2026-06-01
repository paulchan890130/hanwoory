"""SQLAlchemy declarative base (Phase 1).

This module defines a single ``Base`` class derived from
``DeclarativeBase``. All future ORM models will inherit from it so that
Alembic ``--autogenerate`` can discover them via ``Base.metadata``.

Phase 1 does NOT define any business tables. Adding models here without an
accompanying Alembic migration would be a no-op at runtime, but it would
silently expand ``Base.metadata`` and confuse later autogenerate runs.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
