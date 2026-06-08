"""PG repository for fixed_expenses (월별 고정지출 원장). PostgreSQL-only."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import delete, select


def _safe_int(v) -> int:
    try:
        return int(float(str(v).replace(",", "").strip() or "0"))
    except Exception:
        return 0


def _to_dict(row) -> dict:
    return {
        "id": row.expense_id or "",
        "year_month": row.year_month or "",
        "name": row.name or "",
        "amount": int(row.amount or 0),
        "category": row.category or "",
        "payment_method": row.payment_method or "",
        "vat_included": bool(row.vat_included),
        "vat_amount": int(row.vat_amount or 0),
        "memo": row.memo or "",
        "is_recurring": bool(row.is_recurring),
        "start_month": row.start_month or "",
        "end_month": row.end_month or "",
    }


def list_fixed_expenses(tenant_id: str, year_month: Optional[str] = None,
                        year: Optional[str] = None) -> list[dict]:
    """고정지출 목록. year_month("YYYY-MM") 또는 year("YYYY") 필터, 둘 다 없으면 전체."""
    from backend.db.models.finance import FixedExpense
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        q = select(FixedExpense).where(FixedExpense.tenant_id == tenant_id)
        if year_month:
            q = q.where(FixedExpense.year_month == year_month)
        elif year:
            q = q.where(FixedExpense.year_month.like(f"{year}-%"))
        rows = session.scalars(q.order_by(FixedExpense.year_month.desc(), FixedExpense.id.asc())).all()
    return [_to_dict(r) for r in rows]


def upsert_fixed_expense(tenant_id: str, rec: dict) -> dict:
    """expense_id(=rec['id']) 기준 upsert. 없으면 uuid 발급."""
    from backend.db.models.finance import FixedExpense
    from backend.db.session import get_sessionmaker

    expense_id = str(rec.get("id", "")).strip() or uuid.uuid4().hex
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(FixedExpense).where(
                FixedExpense.tenant_id == tenant_id, FixedExpense.expense_id == expense_id
            )
        )
        payload = {
            "year_month": str(rec.get("year_month", "")).strip(),
            "name": str(rec.get("name", "")).strip(),
            "amount": _safe_int(rec.get("amount", 0)),
            "category": str(rec.get("category", "")).strip(),
            "payment_method": str(rec.get("payment_method", "")).strip(),
            "vat_included": bool(rec.get("vat_included", False)),
            "vat_amount": _safe_int(rec.get("vat_amount", 0)),
            "memo": str(rec.get("memo", "")),
            "is_recurring": bool(rec.get("is_recurring", False)),
            "start_month": str(rec.get("start_month", "")).strip(),
            "end_month": str(rec.get("end_month", "")).strip(),
        }
        if row is None:
            row = FixedExpense(tenant_id=tenant_id, expense_id=expense_id, **payload)
            session.add(row)
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        session.commit()
        session.refresh(row)
        return _to_dict(row)


def delete_fixed_expense(tenant_id: str, expense_id: str) -> bool:
    from backend.db.models.finance import FixedExpense
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(
            delete(FixedExpense).where(
                FixedExpense.tenant_id == tenant_id, FixedExpense.expense_id == expense_id
            )
        )
        session.commit()
        return (result.rowcount or 0) > 0


def copy_fixed_expenses(tenant_id: str, from_ym: str, to_ym: str) -> int:
    """from_ym 의 고정지출을 to_ym 으로 복사(새 expense_id 발급). 반환: 복사 건수.
    to_ym 에 이미 행이 있으면 중복 추가하지 않도록 (name, amount) 기준으로 건너뛴다."""
    from backend.db.models.finance import FixedExpense
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    copied = 0
    with SessionLocal() as session:
        src = session.scalars(
            select(FixedExpense).where(
                FixedExpense.tenant_id == tenant_id, FixedExpense.year_month == from_ym
            )
        ).all()
        existing = session.scalars(
            select(FixedExpense).where(
                FixedExpense.tenant_id == tenant_id, FixedExpense.year_month == to_ym
            )
        ).all()
        seen = {(e.name or "", int(e.amount or 0)) for e in existing}
        for s in src:
            key = (s.name or "", int(s.amount or 0))
            if key in seen:
                continue
            session.add(FixedExpense(
                tenant_id=tenant_id, expense_id=uuid.uuid4().hex, year_month=to_ym,
                name=s.name, amount=s.amount, category=s.category,
                payment_method=s.payment_method, vat_included=s.vat_included,
                vat_amount=s.vat_amount, memo=s.memo, is_recurring=s.is_recurring,
                start_month=s.start_month, end_month=s.end_month,
            ))
            seen.add(key)
            copied += 1
        session.commit()
    return copied
