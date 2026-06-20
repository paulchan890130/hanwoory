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


def _clamp_nonneg(v) -> int:
    """음수 입력 불허 — 0 미만은 0으로 클램프."""
    return max(_safe_int(v), 0)


def _vat_of(amount: int) -> int:
    """공급대가(부가세 포함) 금액의 부가세분 = 금액 − round(금액/1.1).
    현 시스템 방식(원 단위 반올림)에 통일. 음수/0이면 0."""
    amount = _safe_int(amount)
    if amount <= 0:
        return 0
    return amount - round(amount / 1.1)


def compute_tax(rec: dict, auto_card_sales: int = 0) -> dict:
    """입력 dict(+자동 카드매출) → 신고/부가세 계산 보강 dict. 저장·표시 공용.

    모든 입력은 공급대가(부가세 포함), 원 단위 정수, 음수 불허(0 클램프).
    - 신고 매출 합계 = 자동 카드매출 + 수동 세금계산서 매출액 + 기타 수동 조정 매출액
    - 매출세액 = 합계 × 10/110 (원 단위 반올림)
    - 공제대상 매입액 = max(사업용 카드 사용액 − 불공제/개인사용 제외액, 0)
    - 매입세액 = 공제대상 매입액 × 10/110
    - 예상 납부 부가세 = 매출세액 − 매입세액 (음수면 환급/이월 검토)
    """
    auto_card = _clamp_nonneg(auto_card_sales)
    invoice = _clamp_nonneg(rec.get("manual_tax_invoice_revenue"))
    other = _clamp_nonneg(rec.get("manual_other_revenue"))
    card_expense = _clamp_nonneg(rec.get("business_card_expense"))
    non_deduct = _clamp_nonneg(rec.get("non_deductible_expense"))

    total_sales = auto_card + invoice + other
    deductible = max(card_expense - non_deduct, 0)
    out_vat = _vat_of(total_sales)
    in_vat = _vat_of(deductible)
    expected = out_vat - in_vat

    return {
        "year_month": str(rec.get("year_month", "")).strip(),
        # 입력 구성값
        "auto_card_sales": auto_card,
        "manual_tax_invoice_revenue": invoice,
        "manual_other_revenue": other,
        "business_card_expense": card_expense,
        "non_deductible_expense": non_deduct,
        # 파생(표시용)
        "total_reported_sales": total_sales,
        "deductible_expense": deductible,
        # 스냅샷(YoY 비교/호환용 기존 컬럼)
        "reported_revenue": total_sales,
        "reported_expense": deductible,
        "reported_output_vat": out_vat,
        "reported_input_vat": in_vat,
        "expected_vat_payable": expected,
        "vat_basis": "tax_included",
        "memo": str(rec.get("memo", "")),
    }


def _to_dict(row) -> dict:
    """저장된 행 → dict(입력 구성값 포함). 자동 카드매출은 일일결산 파생이므로
    여기 포함되지 않는다 — 조회 시 auto_card_sales 를 받아 compute_tax 로 보강한다."""
    return {
        "year_month": row.year_month or "",
        "manual_tax_invoice_revenue": int(row.manual_tax_invoice_revenue or 0),
        "manual_other_revenue": int(row.manual_other_revenue or 0),
        "business_card_expense": int(row.business_card_expense or 0),
        "non_deductible_expense": int(row.non_deductible_expense or 0),
        "reported_revenue": int(row.reported_revenue or 0),
        "reported_expense": int(row.reported_expense or 0),
        "reported_output_vat": int(row.reported_output_vat or 0),
        "reported_input_vat": int(row.reported_input_vat or 0),
        "expected_vat_payable": int(row.expected_vat_payable or 0),
        "vat_basis": row.vat_basis or "tax_included",
        "memo": row.memo or "",
    }


def get_tax_summary(tenant_id: str, year_month: str,
                    auto_card_sales: Optional[int] = None) -> Optional[dict]:
    """저장된 신고/부가세 행 조회. ``auto_card_sales`` 가 주어지면(일일결산 카드수입
    합계) 그 값으로 신고매출 합계·세액·예상납부를 **최신 재계산**해 반환한다.
    None 이면 저장 스냅샷 그대로 반환(overview YoY 비교 등 기존 호출 호환)."""
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
        if not row:
            return None
        base = _to_dict(row)
        if auto_card_sales is None:
            return base
        return compute_tax(base, auto_card_sales=auto_card_sales)


def upsert_tax_summary(tenant_id: str, rec: dict, auto_card_sales: int = 0) -> dict:
    """year_month 기준 upsert. 자동 카드매출(일일결산 카드수입 합계)을 받아 신고/부가세를
    계산해 입력 구성값 + 스냅샷을 함께 저장한다."""
    from backend.db.models.finance import MonthlyTaxSummary
    from backend.db.session import get_sessionmaker

    computed = compute_tax(rec, auto_card_sales=auto_card_sales)
    year_month = computed["year_month"]
    if not year_month:
        raise ValueError("year_month is required")

    # 표시 전용 파생값은 컬럼이 없으므로 저장 payload 에서 제외(스냅샷은 기존 컬럼에 보존).
    _DERIVED_ONLY = {"year_month", "auto_card_sales", "total_reported_sales", "deductible_expense"}

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(MonthlyTaxSummary).where(
                MonthlyTaxSummary.tenant_id == tenant_id,
                MonthlyTaxSummary.year_month == year_month,
            )
        )
        payload = {k: v for k, v in computed.items() if k not in _DERIVED_ONLY}
        if row is None:
            row = MonthlyTaxSummary(tenant_id=tenant_id, year_month=year_month, **payload)
            session.add(row)
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        session.commit()
        session.refresh(row)
        return compute_tax(_to_dict(row), auto_card_sales=auto_card_sales)
