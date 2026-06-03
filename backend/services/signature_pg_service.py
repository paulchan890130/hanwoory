"""PG repository for signatures — agent / customer / temp slots.

The HMAC token logic in ``backend/routers/signature.py`` is stateless and
stays as-is. Only the storage layer swaps from Sheets to PG when
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
