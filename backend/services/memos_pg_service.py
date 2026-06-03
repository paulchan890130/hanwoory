"""PG repository for memos (short / mid / long)."""
from __future__ import annotations

from sqlalchemy import select


def get_memo(tenant_id: str, kind: str) -> str:
    """Return memo content for this tenant + kind, or empty string."""
    from backend.db.models.memo import Memo
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(Memo).where(Memo.tenant_id == tenant_id, Memo.kind == kind)
        )
        return row.content if row else ""


def save_memo(tenant_id: str, kind: str, content: str) -> None:
    """Upsert memo content. Empty string is a valid 'clear' value."""
    from backend.db.models.memo import Memo
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(Memo).where(Memo.tenant_id == tenant_id, Memo.kind == kind)
        )
        if row is None:
            session.add(Memo(tenant_id=tenant_id, kind=kind, content=content or ""))
        else:
            row.content = content or ""
        session.commit()
