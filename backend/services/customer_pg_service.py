"""PG repository for customers — returns dicts shaped like the Sheets path.

The existing customers router and frontend expect Korean-keyed dicts
(``고객ID``, ``한글``, ``여권``, ...). The PG table uses English column
names for SQL ergonomics, so this module is the translation layer.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

# Sheet-key ↔ PG-column mapping. Order matches _DEFAULT_CUSTOMER_HEADERS so
# the response shape is identical to the Sheets path.
SHEET_TO_PG = {
    "고객ID": "customer_id",
    "한글": "korean_name",
    "성": "surname_en",
    "명": "given_en",
    "여권": "passport_no",
    "국적": "nationality",
    "성별": "gender",
    "등록증": "reg_front",
    "번호": "reg_back",
    "발급일": "card_issue_date",
    "만기일": "card_expiry_date",
    "발급": "passport_issue_date",
    "만기": "passport_expiry_date",
    "주소": "address",
    "연": "phone1",
    "락": "phone2",
    "처": "phone3",
    "V": "v_status",
    "체류자격": "visa_status",
    "비자종류": "visa_type",
    "메모": "memo",
    "폴더": "folder_id",
    "위임내역": "delegation_history",
}
PG_TO_SHEET = {v: k for k, v in SHEET_TO_PG.items()}


def _row_to_dict(row) -> dict:
    """Convert a Customer ORM row to a Sheets-shaped dict."""
    out: dict = {}
    for pg_col, sheet_key in PG_TO_SHEET.items():
        val = getattr(row, pg_col, "")
        out[sheet_key] = "" if val is None else str(val)
    return out


def list_customers(tenant_id: str) -> list[dict]:
    """Return all non-deleted customers for this tenant as Sheets-shaped dicts.

    Sorted by ``customer_id`` descending (matching the Sheets router behavior).
    """
    from backend.db.models.customer import Customer
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(Customer)
            .where(Customer.tenant_id == tenant_id, Customer.deleted_at.is_(None))
            .order_by(Customer.customer_id.desc())
        ).all()
    return [_row_to_dict(r) for r in rows]


def find_customer(tenant_id: str, customer_id: str) -> Optional[dict]:
    from backend.db.models.customer import Customer
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                Customer.customer_id == customer_id,
                Customer.deleted_at.is_(None),
            )
        )
    return _row_to_dict(row) if row else None


def next_customer_id(tenant_id: str) -> str:
    """Return the next ``고객ID`` value for an auto-numbered insert.

    Matches the Sheets router's logic: take the max of integer-looking IDs
    and add 1, zero-padded to 4 digits.
    """
    existing = list_customers(tenant_id)
    nums = [int(r["고객ID"]) for r in existing if str(r.get("고객ID", "")).isdigit()]
    return str((max(nums, default=0) + 1)).zfill(4)


def upsert_customer(tenant_id: str, data: dict) -> dict:
    """Insert or update one customer. Returns the resulting Sheets-shaped dict.

    ``data`` is expected to have Sheets keys (``고객ID``, ``한글``, ...).
    Unknown keys are silently ignored. Missing fields are left untouched
    on update, or stored as ``None`` (rendered as empty string) on insert.
    """
    from backend.db.models.customer import Customer
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()

    payload = {SHEET_TO_PG[k]: v for k, v in data.items() if k in SHEET_TO_PG}
    customer_id = str(payload.get("customer_id", "")).strip()
    if not customer_id:
        raise ValueError("고객ID is required")

    with SessionLocal() as session:
        row = session.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                Customer.customer_id == customer_id,
            )
        )
        if row is None:
            payload["tenant_id"] = tenant_id
            row = Customer(**payload)
            session.add(row)
        else:
            # Restore from soft-delete if it was tombstoned, then patch fields.
            row.deleted_at = None
            for col, val in payload.items():
                setattr(row, col, val)
        session.commit()
        session.refresh(row)
        return _row_to_dict(row)


def append_delegation(tenant_id: str, customer_id: str, entry: str) -> Optional[dict]:
    """Append a line to the customer's ``위임내역`` history.

    Returns the updated row dict, or ``None`` if no matching customer.
    Append-only: existing history is preserved with a newline separator.
    """
    from backend.db.models.customer import Customer
    from backend.db.session import get_sessionmaker

    entry = entry.strip()
    if not entry:
        return None

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                Customer.customer_id == customer_id,
            )
        )
        if row is None:
            return None
        existing = (row.delegation_history or "").strip()
        row.delegation_history = (existing + "\n" + entry).strip() if existing else entry
        session.commit()
        session.refresh(row)
        return _row_to_dict(row)


def delete_customer(tenant_id: str, customer_id: str) -> bool:
    """Soft-delete one customer. Returns True iff a row was matched."""
    from datetime import datetime, timezone

    from backend.db.models.customer import Customer
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                Customer.customer_id == customer_id,
                Customer.deleted_at.is_(None),
            )
        )
        if row is None:
            return False
        row.deleted_at = datetime.now(timezone.utc)
        session.commit()
        return True
