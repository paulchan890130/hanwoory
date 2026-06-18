"""PG repository for signatures — agent / customer / temp slots.

The HMAC token logic in ``backend/routers/signature.py`` is stateless and
stays as-is. The storage layer is PostgreSQL when
``FEATURE_PG_SIGNATURES`` is on.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, select


# ── agent (per tenant) ────────────────────────────────────────────────────

def get_agent_signature(tenant_id: str) -> Optional[str]:
    """Return the base64 signature for this tenant's agent, or None."""
    from backend.db.models.signature import AgentSignature
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(AgentSignature).where(AgentSignature.tenant_id == tenant_id)
        )
        return row.signature_data if row else None


def save_agent_signature(tenant_id: str, signature_data: str) -> None:
    from backend.db.models.signature import AgentSignature
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(AgentSignature).where(AgentSignature.tenant_id == tenant_id)
        )
        if row is None:
            session.add(AgentSignature(tenant_id=tenant_id, signature_data=signature_data))
        else:
            row.signature_data = signature_data
        session.commit()


# ── customer (per customer) ───────────────────────────────────────────────

def get_customer_signature(tenant_id: str, customer_id: str) -> Optional[str]:
    from backend.db.models.signature import CustomerSignature
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(CustomerSignature).where(
                CustomerSignature.tenant_id == tenant_id,
                CustomerSignature.customer_id == customer_id,
            )
        )
        return row.signature_data if row else None


def save_customer_signature(tenant_id: str, customer_id: str, signature_data: str) -> None:
    from backend.db.models.signature import CustomerSignature
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(CustomerSignature).where(
                CustomerSignature.tenant_id == tenant_id,
                CustomerSignature.customer_id == customer_id,
            )
        )
        if row is None:
            session.add(CustomerSignature(
                tenant_id=tenant_id, customer_id=customer_id,
                signature_data=signature_data,
            ))
        else:
            row.signature_data = signature_data
        session.commit()


def has_customer_signature(tenant_id: str, customer_id: str) -> bool:
    return get_customer_signature(tenant_id, customer_id) is not None


def delete_customer_signature(tenant_id: str, customer_id: str) -> bool:
    """Delete the applied customer signature row. Returns True iff a row was
    removed. Temp slots / customer profile are untouched."""
    from backend.db.models.signature import CustomerSignature
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(
            delete(CustomerSignature).where(
                CustomerSignature.tenant_id == tenant_id,
                CustomerSignature.customer_id == customer_id,
            )
        )
        session.commit()
        return (result.rowcount or 0) > 0


# ── 상시 서명패드 토큰 (테넌트당 active 1행, token_id=UUID4, 1년) ─────────────
# PG 전용. tenant 당 한 행만 두고 재발급 시 같은 행을 갱신한다(새 행 X). 토큰 문자열은
# 저장하지 않고 payload jti 를 token_id 와 대조해 검증한다. 캐시 없음(재발급 즉시 반영).

_PAD_TOKEN_TTL_DAYS = 365


def _pad_to_dict(row) -> dict:
    return {
        "token_id":   row.token_id,
        "issued_at":  row.issued_at,
        "expires_at": row.expires_at,
        "issued_by":  row.issued_by_login_id or "",
    }


def _aware(dt):
    """naive datetime 은 UTC 로 간주(테스트 SQLite 호환). 비교 안전화."""
    from datetime import timezone
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def get_active_pad_token(tenant_id: str) -> Optional[dict]:
    """현재 테넌트의 서명패드 토큰 상태. 없으면 None.
    {token_id, issued_at, expires_at, issued_by}"""
    from backend.db.models.signature import SignaturePadToken
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(SignaturePadToken).where(SignaturePadToken.tenant_id == tenant_id)
        )
        return _pad_to_dict(row) if row else None


def ensure_pad_token(tenant_id: str, issued_by: str = "") -> dict:
    """유효한 토큰이 있으면 '그대로' 반환(같은 URL 재현). 없거나 만료면 새 token_id(UUID4)로
    생성/갱신(1년). 재발급(regenerate)과 달리 유효한 동안에는 갱신하지 않는다."""
    import uuid
    from datetime import datetime, timedelta, timezone

    from backend.db.models.signature import SignaturePadToken
    from backend.db.session import get_sessionmaker

    now = datetime.now(timezone.utc)
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(SignaturePadToken).where(SignaturePadToken.tenant_id == tenant_id)
        )
        if row is not None and _aware(row.expires_at) > now:
            return _pad_to_dict(row)
        new_id = str(uuid.uuid4())
        expires = now + timedelta(days=_PAD_TOKEN_TTL_DAYS)
        if row is None:
            row = SignaturePadToken(
                tenant_id=tenant_id, token_id=new_id,
                issued_at=now, expires_at=expires,
                issued_by_login_id=(issued_by or None),
            )
            session.add(row)
        else:
            row.token_id = new_id
            row.issued_at = now
            row.expires_at = expires
            row.issued_by_login_id = (issued_by or None)
        session.commit()
        session.refresh(row)
        return _pad_to_dict(row)


def regenerate_pad_token(tenant_id: str, issued_by: str = "") -> dict:
    """기존 행의 token_id 를 새 UUID4 로 교체하고 issued_at/expires_at 갱신. 행이 없으면 생성.
    이전 URL 은 token_id 불일치로 즉시 무효화된다."""
    import uuid
    from datetime import datetime, timedelta, timezone

    from backend.db.models.signature import SignaturePadToken
    from backend.db.session import get_sessionmaker

    now = datetime.now(timezone.utc)
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(SignaturePadToken).where(SignaturePadToken.tenant_id == tenant_id)
        )
        new_id = str(uuid.uuid4())
        expires = now + timedelta(days=_PAD_TOKEN_TTL_DAYS)
        if row is None:
            row = SignaturePadToken(
                tenant_id=tenant_id, token_id=new_id,
                issued_at=now, expires_at=expires,
                issued_by_login_id=(issued_by or None),
            )
            session.add(row)
        else:
            row.token_id = new_id
            row.issued_at = now
            row.expires_at = expires
            row.issued_by_login_id = (issued_by or None)
        session.commit()
        session.refresh(row)
        return _pad_to_dict(row)


def pad_token_is_active(tenant_id: str, token_id: str) -> bool:
    """payload 의 (tenant_id, token_id) 가 DB active 토큰과 일치하고 만료 전인지."""
    from datetime import datetime, timezone

    state = get_active_pad_token(tenant_id)
    if state is None:
        return False
    if str(token_id) != str(state["token_id"]):
        return False
    if _aware(state["expires_at"]) <= datetime.now(timezone.utc):
        return False
    return True


# ── temp slots (1 / 2 / 3 per tenant) ─────────────────────────────────────

def get_temp_slots(tenant_id: str) -> list[dict]:
    """Return all temp slots for this tenant as a list of dicts."""
    from backend.db.models.signature import TempSignatureSlot
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(TempSignatureSlot)
            .where(TempSignatureSlot.tenant_id == tenant_id)
            .order_by(TempSignatureSlot.slot)
        ).all()
    return [
        {
            "slot": r.slot,
            "signature_data": r.signature_data,
            "note": r.note or "",
            "saved_at": r.saved_at.isoformat() if r.saved_at else "",
        }
        for r in rows
    ]


def save_temp_slot(tenant_id: str, slot: int, signature_data: str, note: str = "") -> None:
    from backend.db.models.signature import TempSignatureSlot
    from backend.db.session import get_sessionmaker

    if slot not in (1, 2, 3):
        raise ValueError("slot must be 1, 2, or 3")
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(TempSignatureSlot).where(
                TempSignatureSlot.tenant_id == tenant_id,
                TempSignatureSlot.slot == slot,
            )
        )
        if row is None:
            session.add(TempSignatureSlot(
                tenant_id=tenant_id, slot=slot,
                signature_data=signature_data, note=note,
            ))
        else:
            row.signature_data = signature_data
            row.note = note
        session.commit()


def delete_temp_slot(tenant_id: str, slot: int) -> bool:
    from backend.db.models.signature import TempSignatureSlot
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(
            delete(TempSignatureSlot).where(
                TempSignatureSlot.tenant_id == tenant_id,
                TempSignatureSlot.slot == slot,
            )
        )
        session.commit()
        return (result.rowcount or 0) > 0
