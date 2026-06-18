"""PG repository for daily entries + balance."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, select

DAILY_FIELDS = (
    "id",
    "date",
    "time",
    "category",
    "name",
    "task",
    "income_cash",
    "income_etc",
    "exp_cash",
    "cash_out",
    "exp_etc",
    "memo",
    "customer_id",
)


def _safe_int(v) -> int:
    try:
        return int(float(str(v).replace(",", "").strip() or "0"))
    except Exception:
        return 0


def _entry_to_dict(row) -> dict:
    """Convert a DailyEntry ORM row to a 표준(한글 키) dict."""
    return {
        "id": row.entry_id or "",
        "date": row.date or "",
        "time": row.time or "",
        "category": row.category or "",
        "name": row.name or "",
        "task": row.task or "",
        "income_cash": int(row.income_cash or 0),
        "income_etc": int(row.income_etc or 0),
        "exp_cash": int(row.exp_cash or 0),
        "cash_out": int(row.cash_out or 0),
        "exp_etc": int(row.exp_etc or 0),
        "memo": row.memo or "",
        "customer_id": row.customer_id or "",
    }


def list_entries(tenant_id: str, date: Optional[str] = None) -> list[dict]:
    from backend.db.models.daily import DailyEntry
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        q = select(DailyEntry).where(DailyEntry.tenant_id == tenant_id)
        if date:
            q = q.where(DailyEntry.date == date)
        rows = session.scalars(q.order_by(DailyEntry.date.desc(), DailyEntry.time.desc())).all()
    return [_entry_to_dict(r) for r in rows]


def upsert_entry(tenant_id: str, rec: dict) -> dict:
    from backend.db.models.daily import DailyEntry
    from backend.db.session import get_sessionmaker

    entry_id = str(rec.get("id", "")).strip()
    if not entry_id:
        raise ValueError("id is required")

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(DailyEntry).where(
                DailyEntry.tenant_id == tenant_id, DailyEntry.entry_id == entry_id
            )
        )
        payload = {
            "date": str(rec.get("date", "")).strip(),
            "time": str(rec.get("time", "")).strip(),
            "category": str(rec.get("category", "")).strip(),
            "name": str(rec.get("name", "")).strip(),
            "task": str(rec.get("task", "")).strip(),
            "income_cash": _safe_int(rec.get("income_cash", 0)),
            "income_etc": _safe_int(rec.get("income_etc", 0)),
            "exp_cash": _safe_int(rec.get("exp_cash", 0)),
            "exp_etc": _safe_int(rec.get("exp_etc", 0)),
            "cash_out": _safe_int(rec.get("cash_out", 0)),
            "memo": str(rec.get("memo", "")),
            "customer_id": str(rec.get("customer_id", "")).strip(),
        }
        if row is None:
            row = DailyEntry(tenant_id=tenant_id, entry_id=entry_id, **payload)
            session.add(row)
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        session.commit()
        session.refresh(row)
        return _entry_to_dict(row)


def delete_entry(tenant_id: str, entry_id: str) -> bool:
    from backend.db.models.daily import DailyEntry
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(
            delete(DailyEntry).where(
                DailyEntry.tenant_id == tenant_id, DailyEntry.entry_id == entry_id
            )
        )
        session.commit()
        return (result.rowcount or 0) > 0


# ── balance ────────────────────────────────────────────────────────────────

def get_balance(tenant_id: str) -> dict:
    from backend.db.models.daily import DailyBalance
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(select(DailyBalance).where(DailyBalance.tenant_id == tenant_id))
        if row is None:
            return {"cash": 0, "profit": 0}
        return {"cash": int(row.cash or 0), "profit": int(row.profit or 0)}


def save_balance(tenant_id: str, cash: int, profit: int) -> dict:
    from backend.db.models.daily import DailyBalance
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(select(DailyBalance).where(DailyBalance.tenant_id == tenant_id))
        if row is None:
            row = DailyBalance(tenant_id=tenant_id, cash=cash, profit=profit)
            session.add(row)
        else:
            row.cash = cash
            row.profit = profit
        session.commit()
    return {"cash": cash, "profit": profit}
