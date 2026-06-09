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
    # frontend(고객카드)와 레거시 시트는 비고 컬럼을 "비고" 키로 사용한다.
    # 입력 alias로 "메모"도 받아주되(과거/외부 payload 호환), PG 컬럼은 memo 하나만 쓴다.
    "메모": "memo",
    "비고": "memo",
    "폴더": "folder_id",
    "위임내역": "delegation_history",
}
# 역매핑: 단순 comprehension 이면 memo 의 출력 키가 "메모"/"비고" 중 입력 순서에 좌우되므로,
# API/프론트로 나가는 키를 "비고"로 명시 고정한다(form["비고"]와 정합).
PG_TO_SHEET = {v: k for k, v in SHEET_TO_PG.items()}
PG_TO_SHEET["memo"] = "비고"


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


def _max_customer_number(tenant_id: str) -> int:
    """Highest integer-looking ``고객ID`` for this tenant, **including
    soft-deleted rows**.

    The unique index ``uq_customer_per_tenant (tenant_id, customer_id)`` still
    holds tombstoned rows, so an auto-numbered id must clear them too —
    otherwise id re-use can collide with a deleted customer's slot and
    raise an IntegrityError on insert.
    """
    from backend.db.models.customer import Customer
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        ids = session.scalars(
            select(Customer.customer_id).where(Customer.tenant_id == tenant_id)
        ).all()
    nums = [int(x) for x in ids if str(x).strip().isdigit()]
    return max(nums, default=0)


def next_customer_id(tenant_id: str) -> str:
    """Return the next ``고객ID`` value for an auto-numbered insert.

    Max of integer-looking IDs (across all rows incl. soft-deleted) + 1,
    zero-padded to 4 digits.
    """
    return str(_max_customer_number(tenant_id) + 1).zfill(4)


class CustomerIdConflict(Exception):
    """Auto-numbered ``고객ID`` kept colliding with the unique index after
    retries (concurrent inserts / stale id)."""


def create_customer(tenant_id: str, data: dict, *, max_retries: int = 5) -> dict:
    """Insert a new customer, auto-numbering ``고객ID`` when absent.

    Defends against the check-then-insert race (two concurrent adds compute
    the same next id) and stale-id reuse by retrying with a freshly computed
    id when the ``(tenant_id, customer_id)`` unique constraint is violated.
    When the caller supplies an explicit ``고객ID`` we defer to
    :func:`upsert_customer` (update-or-restore semantics, unchanged).
    """
    explicit_id = str(data.get("고객ID", "")).strip()
    if explicit_id:
        return upsert_customer(tenant_id, data)

    from sqlalchemy.exc import IntegrityError

    from backend.db.models.customer import Customer
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    base_payload = {SHEET_TO_PG[k]: v for k, v in data.items() if k in SHEET_TO_PG}
    last_err: Optional[Exception] = None
    for _ in range(max(1, max_retries)):
        cid = next_customer_id(tenant_id)
        payload = dict(base_payload, tenant_id=tenant_id, customer_id=cid)
        try:
            with SessionLocal() as session:
                row = Customer(**payload)
                session.add(row)
                session.commit()
                session.refresh(row)
                return _row_to_dict(row)
        except IntegrityError as e:
            last_err = e
            diag = getattr(getattr(e, "orig", None), "diag", None)
            cname = getattr(diag, "constraint_name", None) or "unknown"
            print(
                f"[customer_pg_service.create_customer] IntegrityError "
                f"tenant={tenant_id!r} customer_id={cid!r} constraint={cname} - retrying"
            )
            continue
    raise CustomerIdConflict(
        "고객ID 생성 중 중복이 발생했습니다. 다시 시도해 주세요."
    ) from last_err


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
