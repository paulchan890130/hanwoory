"""SQLAlchemy ORM models (local beta).

Importing this package registers every model on ``Base.metadata`` so Alembic's
``--autogenerate`` and ``upgrade head`` see them. The package is imported from
``backend.db.__init__`` for that exact purpose.

Phase boundary: only the three foundation tables are included here
(``tenants``, ``users``, ``audit_logs``). Customers and other business tables
are intentionally out of scope for the local beta.
"""

from backend.db.models.tenant import Tenant  # noqa: F401
from backend.db.models.user import AccountUser  # noqa: F401
from backend.db.models.audit import AuditLog  # noqa: F401

__all__ = ["Tenant", "AccountUser", "AuditLog"]
