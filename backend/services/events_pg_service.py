"""PG repository for calendar events (per-date)."""
from __future__ import annotations

from sqlalchemy import delete, select


def get_events_map(tenant_id: str) -> dict[str, list[str]]:
    """Return {date_str: [event_text, ...]} for this tenant.

    Matches the existing router's ``get_events`` response shape exactly.
    """
    from backend.db.models.event import Event
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(Event)
            .where(Event.tenant_id == tenant_id)
            .order_by(Event.date_str, Event.sort_order, Event.id)
        ).all()
    result: dict[str, list[str]] = {}
    for r in rows:
        result.setdefault(r.date_str, []).append(r.event_text)
    return result


def save_events_for_date(tenant_id: str, date_str: str, lines: list[str]) -> int:
    """Reconcile rows for ``date_str`` against the new ``lines`` using
    row-level INSERT / UPDATE / DELETE — never a wipe-and-reinsert.

    Each existing Event row has a stable BIGINT ``id``. We sort existing rows
    by ``(sort_order, id)`` to define the canonical sequence, then walk both
    lists in parallel:

      - index < min(len_existing, len_new): UPDATE existing row's
        ``event_text`` / ``sort_order`` in place (preserves the primary key).
      - index >= len_existing: INSERT a new row.
      - index >= len_new: DELETE the trailing row by its primary key.

    This means a user's "save day's events" call mutates only the specific
    rows that actually changed, satisfying the local-PG row-level write rule
    (no full-domain delete-and-reinsert). Returns the number of rows present
    after the reconciliation.
    """
    from backend.db.models.event import Event
    from backend.db.session import get_sessionmaker

    cleaned = [l.strip() for l in lines if l.strip()]

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        existing = session.scalars(
            select(Event)
            .where(Event.tenant_id == tenant_id, Event.date_str == date_str)
            .order_by(Event.sort_order, Event.id)
        ).all()

        n_keep = min(len(existing), len(cleaned))
        # Update overlap in place.
        for i in range(n_keep):
            row = existing[i]
            if row.event_text != cleaned[i] or row.sort_order != i:
                row.event_text = cleaned[i]
                row.sort_order = i
        # Insert any new tail rows.
        for i in range(n_keep, len(cleaned)):
            session.add(Event(
                tenant_id=tenant_id, date_str=date_str,
                event_text=cleaned[i], sort_order=i,
            ))
        # Delete any leftover tail rows by primary key.
        for i in range(n_keep, len(existing)):
            session.delete(existing[i])

        session.commit()
    return len(cleaned)


def delete_events_for_date(tenant_id: str, date_str: str) -> int:
    """Remove every row for ``date_str``. Returns the deleted-row count."""
    from backend.db.models.event import Event
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(
            delete(Event).where(Event.tenant_id == tenant_id, Event.date_str == date_str)
        )
        session.commit()
        return result.rowcount or 0
