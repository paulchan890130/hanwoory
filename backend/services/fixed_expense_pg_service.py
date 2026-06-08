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


def _ym_to_int(s) -> Optional[int]:
    s = str(s or "").strip()
    if len(s) < 7:
        return None
    try:
        return int(s[:4]) * 12 + int(s[5:7])
    except Exception:
        return None


def _prev_month(ym: str) -> str:
    """'YYYY-MM' → 직전월 'YYYY-MM'. 형식 불량이면 빈 문자열.

    _ym_to_int 인코딩은 year*12+month(month 1~12)이므로 디코드는 (n-1) 보정이 필요하다.
    """
    n = _ym_to_int(ym)
    if n is None:
        return ""
    n -= 1
    return f"{(n - 1) // 12:04d}-{((n - 1) % 12) + 1:02d}"


def _is_effective(row, target_int: int) -> bool:
    """row(ORM)가 target 월에 유효한지. 반복은 start~end 범위, 비반복은 year_month 일치."""
    if row.is_recurring:
        start = _ym_to_int(row.start_month) or _ym_to_int(row.year_month)
        end = _ym_to_int(row.end_month)
        return start is not None and start <= target_int and (end is None or target_int <= end)
    return _ym_to_int(row.year_month) == target_int


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
                        year: Optional[str] = None,
                        effective_month: Optional[str] = None) -> list[dict]:
    """고정지출 목록.

    - effective_month("YYYY-MM"): 해당 월에 **유효한 규칙**(반복 start~end 범위 또는
      비반복 year_month 일치)만 반환 → 월간결산/관리 UI용. (매월 복사 없이 자동 반영)
    - year_month / year: 정확월/연도 필터(레거시).
    - 모두 없으면 전체(overview 집계에서 규칙 단위로 사용).
    """
    from backend.db.models.finance import FixedExpense
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        q = select(FixedExpense).where(FixedExpense.tenant_id == tenant_id)
        if effective_month:
            rows = session.scalars(q.order_by(FixedExpense.id.asc())).all()
            target = _ym_to_int(effective_month)
            rows = [r for r in rows if target is not None and _is_effective(r, target)]
            return [_to_dict(r) for r in rows]
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


def update_fixed_expense(tenant_id: str, expense_id: str, data: dict, effective_from: str) -> dict:
    """선택월(effective_from) 기준 수정.

    - 금액이 그대로면 메타(name/category/payment/memo 등) **제자리 수정**.
    - 금액이 바뀌고 반복 규칙이며 규칙 시작월이 선택월보다 과거면 → **term-out**:
      기존 규칙을 (선택월-1)로 종료하고, 선택월부터 새 금액 규칙을 신규 생성한다.
      → 과거 월 금액은 변하지 않는다.
    - 규칙 시작월 == 선택월이면(이번 달부터 시작한 규칙) 제자리 수정(과거 영향 없음).
    """
    from backend.db.models.finance import FixedExpense
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(FixedExpense).where(
                FixedExpense.tenant_id == tenant_id, FixedExpense.expense_id == expense_id
            )
        )
        if row is None:
            raise ValueError("fixed expense not found")

        new_amount = _safe_int(data.get("amount", row.amount))
        amount_changed = new_amount != int(row.amount or 0)
        start_int = _ym_to_int(row.start_month) or _ym_to_int(row.year_month)
        eff_int = _ym_to_int(effective_from)

        def _apply_meta(target):
            for k in ("name", "category", "payment_method", "memo"):
                if k in data:
                    setattr(target, k, str(data.get(k, "") or ""))
            if "vat_included" in data:
                target.vat_included = bool(data.get("vat_included"))

        # term-out 조건: 금액 변경 + 반복 + 규칙이 선택월보다 과거에 시작
        if (amount_changed and bool(row.is_recurring)
                and start_int is not None and eff_int is not None and start_int < eff_int):
            old_end = row.end_month  # 원래 종료(무기한이면 빈값)
            row.end_month = _prev_month(effective_from)  # 기존 규칙은 전월까지
            new_row = FixedExpense(
                tenant_id=tenant_id, expense_id=uuid.uuid4().hex,
                year_month=effective_from, start_month=effective_from, end_month=old_end or "",
                name=str(data.get("name", row.name) or ""),
                amount=new_amount,
                category=str(data.get("category", row.category) or ""),
                payment_method=str(data.get("payment_method", row.payment_method) or ""),
                vat_included=bool(data.get("vat_included", row.vat_included)),
                vat_amount=_safe_int(data.get("vat_amount", row.vat_amount)),
                memo=str(data.get("memo", row.memo) or ""),
                is_recurring=True,
            )
            session.add(new_row)
            session.commit()
            session.refresh(new_row)
            return _to_dict(new_row)

        # 제자리 수정
        row.amount = new_amount
        if "vat_amount" in data:
            row.vat_amount = _safe_int(data.get("vat_amount"))
        _apply_meta(row)
        session.commit()
        session.refresh(row)
        return _to_dict(row)


def end_fixed_expense(tenant_id: str, expense_id: str, effective_from: str) -> dict:
    """선택월부터 고정지출 중단.

    - 반복 규칙이고 시작월이 선택월보다 과거면 → end_month=(선택월-1)로 **종료**(과거 보존).
    - 그 외(이번 달 시작 규칙/비반복)면 → 행 **삭제**.
    """
    from backend.db.models.finance import FixedExpense
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(FixedExpense).where(
                FixedExpense.tenant_id == tenant_id, FixedExpense.expense_id == expense_id
            )
        )
        if row is None:
            return {"deleted": expense_id, "ok": False}
        start_int = _ym_to_int(row.start_month) or _ym_to_int(row.year_month)
        eff_int = _ym_to_int(effective_from)
        if bool(row.is_recurring) and start_int is not None and eff_int is not None and start_int < eff_int:
            row.end_month = _prev_month(effective_from)
            session.commit()
            return {"ended": expense_id, "end_month": row.end_month, "ok": True}
        session.execute(
            delete(FixedExpense).where(
                FixedExpense.tenant_id == tenant_id, FixedExpense.expense_id == expense_id
            )
        )
        session.commit()
        return {"deleted": expense_id, "ok": True}


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
