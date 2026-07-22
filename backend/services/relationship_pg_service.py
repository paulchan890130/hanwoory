"""PG repository for 숙소제공자연결 + 신원보증인연결."""
from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, select


_ACCOM_FIELDS = (
    "target_customer_id", "provider_type", "provider_customer_id",
    "provider_name", "provider_last_name", "provider_first_name",
    "provider_nation", "provider_reg_front", "provider_reg_back",
    "provider_birth", "provider_phone", "provider_address",
    "provider_relation", "provide_start_date", "provide_end_date", "housing_type",
)

_GUARANTOR_FIELDS = (
    "target_customer_id", "guarantor_type", "guarantor_customer_id",
    "guarantor_name", "guarantor_last_name", "guarantor_first_name",
    "guarantor_nation", "guarantor_reg_front", "guarantor_reg_back",
    "guarantor_birth", "guarantor_phone", "guarantor_address",
    "guarantor_relation", "guarantor_workplace", "guarantor_extra",
)


def _canonicalize_reg_front_fields(d: dict) -> None:
    """provider_reg_front / guarantor_reg_front 의 선행 0 손실을 비파괴적으로 복구(in-place)."""
    from backend.services.customer_identifier_normalize import (
        canonical_reg_front_for_legacy_read,
    )
    for f in ("provider_reg_front", "guarantor_reg_front"):
        if f in d and str(d.get(f, "")).strip():
            d[f] = canonical_reg_front_for_legacy_read(d.get(f, ""))


def _row_to_dict(row, fields) -> dict:
    if row is None:
        return {}
    out = {f: ("" if getattr(row, f, None) is None else str(getattr(row, f))) for f in fields}
    out["created_at"] = row.created_at.isoformat() if row.created_at else ""
    out["updated_at"] = row.updated_at.isoformat() if row.updated_at else ""
    _canonicalize_reg_front_fields(out)
    return out


# ── accommodation ─────────────────────────────────────────────────────────

def get_accommodation(tenant_id: str, customer_id: str) -> Optional[dict]:
    from backend.db.models.relationship import AccommodationProvider
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(AccommodationProvider).where(
                AccommodationProvider.tenant_id == tenant_id,
                AccommodationProvider.target_customer_id == customer_id,
            )
        )
    return _row_to_dict(row, _ACCOM_FIELDS) if row else None


def save_accommodation(tenant_id: str, data: dict) -> dict:
    from backend.db.models.relationship import AccommodationProvider
    from backend.db.session import get_sessionmaker

    target = str(data.get("target_customer_id", "")).strip()
    if not target:
        raise ValueError("target_customer_id required")

    payload = {f: str(data.get(f, "") or "") for f in _ACCOM_FIELDS}
    _canonicalize_reg_front_fields(payload)
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(AccommodationProvider).where(
                AccommodationProvider.tenant_id == tenant_id,
                AccommodationProvider.target_customer_id == target,
            )
        )
        if row is None:
            row = AccommodationProvider(tenant_id=tenant_id, **payload)
            session.add(row)
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        session.commit()
        session.refresh(row)
        return _row_to_dict(row, _ACCOM_FIELDS)


def delete_accommodation(tenant_id: str, customer_id: str) -> bool:
    from backend.db.models.relationship import AccommodationProvider
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(
            delete(AccommodationProvider).where(
                AccommodationProvider.tenant_id == tenant_id,
                AccommodationProvider.target_customer_id == customer_id,
            )
        )
        session.commit()
        return (result.rowcount or 0) > 0


# ── guarantor ─────────────────────────────────────────────────────────────

def get_guarantor(tenant_id: str, customer_id: str) -> Optional[dict]:
    from backend.db.models.relationship import GuarantorConnection
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(GuarantorConnection).where(
                GuarantorConnection.tenant_id == tenant_id,
                GuarantorConnection.target_customer_id == customer_id,
            )
        )
    return _row_to_dict(row, _GUARANTOR_FIELDS) if row else None


def save_guarantor(tenant_id: str, data: dict) -> dict:
    from backend.db.models.relationship import GuarantorConnection
    from backend.db.session import get_sessionmaker

    target = str(data.get("target_customer_id", "")).strip()
    if not target:
        raise ValueError("target_customer_id required")

    payload = {f: str(data.get(f, "") or "") for f in _GUARANTOR_FIELDS}
    _canonicalize_reg_front_fields(payload)
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(GuarantorConnection).where(
                GuarantorConnection.tenant_id == tenant_id,
                GuarantorConnection.target_customer_id == target,
            )
        )
        if row is None:
            row = GuarantorConnection(tenant_id=tenant_id, **payload)
            session.add(row)
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        session.commit()
        session.refresh(row)
        return _row_to_dict(row, _GUARANTOR_FIELDS)


def delete_guarantor(tenant_id: str, customer_id: str) -> bool:
    from backend.db.models.relationship import GuarantorConnection
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(
            delete(GuarantorConnection).where(
                GuarantorConnection.tenant_id == tenant_id,
                GuarantorConnection.target_customer_id == customer_id,
            )
        )
        session.commit()
        return (result.rowcount or 0) > 0
