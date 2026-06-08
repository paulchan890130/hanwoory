"""PG repository for monthly_tax_summaries (월별 신고/부가세 관리값). PostgreSQL-only.

부가세는 일반과세 10% 관리용 예상 계산. 사용자가 매출세액/매입세액/예상납부액을
직접 입력하면 그 값을 우선하고, 비어 있으면(0) 신고 매출/매입에서 자동 계산한다.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select


def _safe_int(v) -> int:
    try:
        return int(float(str(v).replace(",", "").strip() or "0"))
    except Exception:
        return 0


def _vat_split(amount: int, basis: str) -> tuple[int, int]:
    """(공급가액, 부가세). basis: 'supply_price'(입력=공급가액) | 'tax_included'(입력=공급대가)."""
    amount = _safe_int(amount)
    if amount <= 0:
        return 0, 0
    if basis == "supply_price":
        return amount, round(amount * 0.1)
    supply = round(amount / 1.1)
    return supply, amount - supply


def compute_tax(rec: dict) -> dict:
    """입력 dict → 계산 보강 dict(자동/수동 우선 규칙 적용). 저장·표시 공용."""
    basis = (rec.get("vat_basis") or "tax_included").strip() or "tax_included"
    rev = _safe_int(rec.get("reported_revenue"))
    exp = _safe_int(rec.get("reported_expense"))
    _, auto_out = _vat_split(rev, basis)
    _, auto_in = _vat_split(exp, basis)
    out_vat = _safe_int(rec.get("reported_output_vat")) or auto_out
    in_vat = _safe_int(rec.get("reported_input_vat")) or auto_in
    expected = rec.get("expected_vat_payable")
    expected = _safe_int(expected) if str(expected or "").strip() not in ("", "0") else (out_vat - in_vat)
    return {
        "year_month": str(rec.get("year_month", "")).strip(),
        "reported_revenue": rev,
        "reported_expense": exp,
        "reported_output_vat": out_vat,
        "reported_input_vat": in_vat,
        "expected_vat_payable": expected,
        "vat_basis": basis,
        "memo": str(rec.get("memo", "")),
    }


def _to_dict(row) -> dict:
    return {
        "year_month": row.year_month or "",
        "reported_revenue": int(row.reported_revenue or 0),
        "reported_expense": int(row.reported_expense or 0),
        "reported_output_vat": int(row.reported_output_vat or 0),
        "reported_input_vat": int(row.reported_input_vat or 0),
        "expected_vat_payable": int(row.expected_vat_payable or 0),
        "vat_basis": row.vat_basis or "tax_included",
        "memo": row.memo or "",
    }


def get_tax_summary(tenant_id: str, year_month: str) -> Optional[dict]:
    from backend.db.models.finance import MonthlyTaxSummary
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(MonthlyTaxSummary).where(
                MonthlyTaxSummary.tenant_id == tenant_id,
                MonthlyTaxSummary.year_month == year_month,
            )
        )
        return _to_dict(row) if row else None


def upsert_tax_summary(tenant_id: str, rec: dict) -> dict:
    """year_month 기준 upsert. 부가세 자동/수동 계산을 적용해 저장."""
    from backend.db.models.finance import MonthlyTaxSummary
    from backend.db.session import get_sessionmaker

    computed = compute_tax(rec)
    year_month = computed["year_month"]
    if not year_month:
        raise ValueError("year_month is required")

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(MonthlyTaxSummary).where(
                MonthlyTaxSummary.tenant_id == tenant_id,
                MonthlyTaxSummary.year_month == year_month,
            )
        )
        payload = {k: v for k, v in computed.items() if k != "year_month"}
        if row is None:
            row = MonthlyTaxSummary(tenant_id=tenant_id, year_month=year_month, **payload)
            session.add(row)
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        session.commit()
        session.refresh(row)
        return _to_dict(row)
