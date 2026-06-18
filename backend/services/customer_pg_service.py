"""PG repository for customers — returns dicts with stable Korean-keyed columns.

The existing customers router and frontend expect Korean-keyed dicts
(``고객ID``, ``한글``, ``여권``, ...). The PG table uses English column
names for SQL ergonomics, so this module is the translation layer.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select

# Sheet-key ↔ PG-column mapping. Order matches _DEFAULT_CUSTOMER_HEADERS so
# the response shape is stable across callers.
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

# ── 외국인등록번호 뒷자리(reg_back) 암호화 정책 ────────────────────────────────
# 1차(전환기): 기존 평문 reg_back 컬럼을 fallback/rollback 용으로 **유지**하고, 읽기
# 경로에서 항상 마스킹/복호화로 분기한다. 2차에서 reg_back 을 마스크('1******')로
# 덮어쓰면 _row_to_dict(reveal=False)는 mask_reg_back 멱등성으로 동일 동작한다.
# 이 플래그를 False 로 바꾸면 신규 쓰기 시 reg_back 에 평문 대신 마스크를 저장한다.
_KEEP_PLAINTEXT_FALLBACK = True


def _encode_reg_back_into_payload(payload: dict, tenant_id: str) -> None:
    """payload 의 'reg_back'(평문 입력) → 암호화 보조 컬럼으로 변환(in-place).

    - 'reg_back' 키가 없으면(부분 업데이트) 아무것도 하지 않는다(기존 값 유지).
    - 입력이 마스킹값('*' 포함)이면 **덮어쓰지 않는다**(상세→저장 왕복 시 암호문 보존).
    - 빈 값이면 명시적 초기화(암호문/해시/last4 제거).
    - 키 미설정(PiiKeyMissing) 시 평문 reg_back 보관(현행 동작 유지) — 로그에 평문 금지.
    """
    if "reg_back" not in payload:
        return
    raw = payload.pop("reg_back")
    if raw is None:
        return
    from backend.services import pii_crypto as _pii

    s = str(raw)
    if "*" in s:
        # 마스킹된 표시값이 되돌아온 경우 — 저장된 암호문을 보존(미변경).
        return
    norm = _pii.normalize_reg_back(s)
    if not norm:
        payload["reg_back"] = ""
        payload["reg_back_encrypted"] = ""
        payload["reg_back_hash"] = ""
        payload["reg_back_last4"] = ""
        payload["reg_back_enc_ver"] = None
        return
    try:
        from datetime import datetime, timezone
        payload["reg_back_encrypted"] = _pii.encrypt_pii(norm)
        payload["reg_back_hash"] = _pii.hash_pii(tenant_id, norm)
        payload["reg_back_last4"] = _pii.last4_reg_back(norm)
        payload["reg_back_enc_ver"] = _pii.REG_BACK_ENC_VERSION
        payload["reg_back_migrated_at"] = datetime.now(timezone.utc)
        payload["reg_back"] = norm if _KEEP_PLAINTEXT_FALLBACK else _pii.mask_reg_back(norm)
    except _pii.PiiKeyMissing:
        # 운영(server): 키 미설정이면 평문 저장을 거부(fail-closed). 라우터가 503 으로 변환.
        if _pii.is_server_env():
            raise
        # 로컬/테스트: 평문 보관으로 graceful fallback. 평문 로그 금지.
        import logging
        logging.getLogger("customers.pii").warning(
            "CUSTOMER_PII_ENCRYPTION_KEY missing — reg_back stored as plaintext (local fallback)"
        )
        payload["reg_back"] = norm


def _row_to_dict(row, *, reveal: bool = False) -> dict:
    """Customer ORM row → 표준(한글 키) dict.

    reg_back(번호) 특수 처리:
    - reveal=False(목록/기본): 복호화하지 않고 ``1******`` 마스킹(첫 자리 보존 →
      만기 세기판별 호환). ``번호_last4`` 보조키 추가.
    - reveal=True(상세/문서): 암호문 복호화(없으면 평문 fallback). 실패 시 blank.
    """
    out: dict = {}
    for pg_col, sheet_key in PG_TO_SHEET.items():
        val = getattr(row, pg_col, "")
        out[sheet_key] = "" if val is None else str(val)

    from backend.services import pii_crypto as _pii

    enc = getattr(row, "reg_back_encrypted", "") or ""
    plain_fallback = str(getattr(row, "reg_back", "") or "")
    last4 = str(getattr(row, "reg_back_last4", "") or "")
    if reveal:
        if enc:
            try:
                out["번호"] = _pii.decrypt_pii(enc)
            except _pii.PiiCryptoError:
                # 키 미설정/불일치 — 평문 fallback(마스킹 아님)만 사용, 없으면 blank.
                out["번호"] = "" if "*" in plain_fallback else plain_fallback
        else:
            out["번호"] = plain_fallback  # old/unmigrated row
    else:
        # 마스킹(평문이면 마스킹, 이미 마스킹돼 있으면 멱등). 첫 자리 보존.
        out["번호"] = _pii.mask_reg_back(plain_fallback) if plain_fallback else ("*" if enc else "")
        if not last4 and plain_fallback and "*" not in plain_fallback:
            last4 = _pii.last4_reg_back(plain_fallback)
        out["번호_last4"] = last4
    return out


def list_customers(tenant_id: str) -> list[dict]:
    """Return all non-deleted customers for this tenant as 표준(한글 키) dicts.

    Sorted by ``customer_id`` descending (matching the existing router behavior).
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


def find_customer(tenant_id: str, customer_id: str, *, reveal: bool = False) -> Optional[dict]:
    """단일 고객 조회. reveal=True 면 reg_back(번호)을 복호화한 평문으로 반환(상세/문서용).

    기본(reveal=False)은 마스킹(``1******``)으로 반환 — 목록과 동일 정책.
    """
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
    return _row_to_dict(row, reveal=reveal) if row else None


def ids_by_reg_back_hash(tenant_id: str, target_hash: str) -> set:
    """주어진 HMAC 해시와 일치하는 (비삭제) 고객ID 집합. 검색용. 빈 해시 → 빈 집합."""
    if not target_hash:
        return set()
    from backend.db.models.customer import Customer
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        ids = session.scalars(
            select(Customer.customer_id).where(
                Customer.tenant_id == tenant_id,
                Customer.reg_back_hash == target_hash,
                Customer.deleted_at.is_(None),
            )
        ).all()
    return {str(x) for x in ids}


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


class TenantNotProvisioned(Exception):
    """The customer insert hit ``customers_tenant_id_fkey`` — the tenant has
    no row in ``tenants`` yet (PG workspace not provisioned). Retrying the
    customer-id is pointless; surface a clear, actionable error instead."""


def _constraint_name(exc: Exception) -> str:
    """Best-effort constraint name from an IntegrityError.

    Prefers psycopg's ``orig.diag.constraint_name``; falls back to scraping
    the DBAPI message (driver-agnostic) so we can still classify the error
    when diagnostics are unavailable."""
    diag = getattr(getattr(exc, "orig", None), "diag", None)
    name = getattr(diag, "constraint_name", None)
    if name:
        return name
    msg = str(getattr(exc, "orig", exc))
    for known in ("uq_customer_per_tenant", "customers_tenant_id_fkey"):
        if known in msg:
            return known
    return "unknown"


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
    _encode_reg_back_into_payload(base_payload, tenant_id)
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
            cname = _constraint_name(e)
            # 고객ID 중복(uq_customer_per_tenant)일 때만 다음 번호로 재시도한다.
            if cname == "uq_customer_per_tenant":
                last_err = e
                print(
                    f"[customer_pg_service.create_customer] IntegrityError "
                    f"tenant={tenant_id!r} customer_id={cid!r} constraint={cname} - retrying"
                )
                continue
            # tenant FK 위반: tenants 행이 없음 → 재시도해도 동일하게 실패하므로 즉시 중단.
            # (with-블록 종료 시 미커밋 트랜잭션은 자동 rollback)
            if cname == "customers_tenant_id_fkey":
                print(
                    f"[customer_pg_service.create_customer] IntegrityError "
                    f"tenant={tenant_id!r} customer_id={cid!r} constraint={cname} - tenant not provisioned"
                )
                raise TenantNotProvisioned(
                    "테넌트 초기화가 완료되지 않았습니다. 관리자에게 문의하세요."
                ) from e
            # 알 수 없는 무결성 오류: 무리하게 재시도하지 않고 그대로 전파.
            print(
                f"[customer_pg_service.create_customer] IntegrityError "
                f"tenant={tenant_id!r} customer_id={cid!r} constraint={cname} - not retryable"
            )
            raise
    raise CustomerIdConflict(
        "고객ID 생성 중 중복이 발생했습니다. 다시 시도해 주세요."
    ) from last_err


def upsert_customer(tenant_id: str, data: dict) -> dict:
    """Insert or update one customer. Returns the resulting 표준(한글 키) dict.

    ``data`` is expected to have Korean keys (``고객ID``, ``한글``, ...).
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
    _encode_reg_back_into_payload(payload, tenant_id)

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
