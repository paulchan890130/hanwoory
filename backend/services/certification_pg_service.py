"""PG repository for 각종공인증 (5 entities)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, select


_NOW = lambda: datetime.now().isoformat(timespec="seconds")


def _row(row, fields) -> dict:
    return {f: ("" if getattr(row, f, None) is None else str(getattr(row, f))) for f in fields}


def _list(tenant_id: str, model, fields) -> list[dict]:
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(select(model).where(model.tenant_id == tenant_id)).all()
    return [_row(r, fields) for r in rows]


def _upsert(tenant_id: str, model, fields, payload: dict) -> dict:
    from backend.db.session import get_sessionmaker
    pid = str(payload.get("id", "")).strip() or str(uuid.uuid4())
    now = _NOW()
    data = {f: str(payload.get(f, "") or "") for f in fields if f not in ("id", "tenant_id", "created_at", "updated_at")}
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(select(model).where(model.id == pid, model.tenant_id == tenant_id))
        if row is None:
            row = model(id=pid, tenant_id=tenant_id, created_at=now, updated_at=now, **data)
            session.add(row)
        else:
            for k, v in data.items():
                setattr(row, k, v)
            row.updated_at = now
        session.commit()
        session.refresh(row)
        return _row(row, fields)


def _delete(tenant_id: str, model, eid: str) -> bool:
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(delete(model).where(model.tenant_id == tenant_id, model.id == eid))
        session.commit()
        return (result.rowcount or 0) > 0


VENDOR_FIELDS = ("id", "name", "contact", "memo", "active", "created_at", "updated_at")
DIRECTION_FIELDS = ("id", "name", "sort_order", "active", "created_at", "updated_at")
GROUP_FIELDS = ("id", "group_name", "aliases", "default_direction", "applicable_directions",
                "sort_order", "active", "created_at", "updated_at")
REGION_FIELDS = ("id", "name", "applicable_directions", "applicable_group_ids",
                 "sort_order", "active", "created_at", "updated_at")
PRICE_FIELDS = (
    "id", "vendor_id", "group_id", "direction", "region", "condition",
    "price", "possible", "documents", "lead_time", "strength", "risk",
    "source", "last_checked", "created_at", "updated_at",
)


def bootstrap(tenant_id: str) -> dict:
    """Return the full bootstrap shape expected by /api/certification-services/bootstrap."""
    from backend.db.models.certification import (
        CertVendor, CertDirection, CertGroup, CertRegion, CertPrice,
    )
    return {
        "vendors":    _list(tenant_id, CertVendor, VENDOR_FIELDS),
        "directions": _list(tenant_id, CertDirection, DIRECTION_FIELDS),
        "groups":     _list(tenant_id, CertGroup, GROUP_FIELDS),
        "regions":    _list(tenant_id, CertRegion, REGION_FIELDS),
        "prices":     _list(tenant_id, CertPrice, PRICE_FIELDS),
    }


def get_vendors(tenant_id: str):
    from backend.db.models.certification import CertVendor
    return _list(tenant_id, CertVendor, VENDOR_FIELDS)

def save_vendor(tenant_id: str, body: dict):
    from backend.db.models.certification import CertVendor
    return _upsert(tenant_id, CertVendor, VENDOR_FIELDS, body)

def delete_vendor(tenant_id: str, vid: str):
    from backend.db.models.certification import CertVendor
    return {"deleted": _delete(tenant_id, CertVendor, vid)}


def get_directions(tenant_id: str):
    from backend.db.models.certification import CertDirection
    return _list(tenant_id, CertDirection, DIRECTION_FIELDS)

def save_direction(tenant_id: str, body: dict):
    from backend.db.models.certification import CertDirection
    return _upsert(tenant_id, CertDirection, DIRECTION_FIELDS, body)

def delete_direction(tenant_id: str, did: str):
    from backend.db.models.certification import CertDirection
    return {"deleted": _delete(tenant_id, CertDirection, did)}


def get_groups(tenant_id: str):
    from backend.db.models.certification import CertGroup
    return _list(tenant_id, CertGroup, GROUP_FIELDS)

def save_group(tenant_id: str, body: dict):
    from backend.db.models.certification import CertGroup
    return _upsert(tenant_id, CertGroup, GROUP_FIELDS, body)

def delete_group(tenant_id: str, gid: str):
    from backend.db.models.certification import CertGroup
    return {"deleted": _delete(tenant_id, CertGroup, gid)}


def get_regions(tenant_id: str):
    from backend.db.models.certification import CertRegion
    return _list(tenant_id, CertRegion, REGION_FIELDS)

def save_region(tenant_id: str, body: dict):
    from backend.db.models.certification import CertRegion
    return _upsert(tenant_id, CertRegion, REGION_FIELDS, body)

def delete_region(tenant_id: str, rid: str):
    from backend.db.models.certification import CertRegion
    return {"deleted": _delete(tenant_id, CertRegion, rid)}


def get_prices(tenant_id: str):
    from backend.db.models.certification import CertPrice
    return _list(tenant_id, CertPrice, PRICE_FIELDS)

def save_price(tenant_id: str, body: dict):
    from backend.db.models.certification import CertPrice
    return _upsert(tenant_id, CertPrice, PRICE_FIELDS, body)

def delete_price(tenant_id: str, pid: str):
    from backend.db.models.certification import CertPrice
    return {"deleted": _delete(tenant_id, CertPrice, pid)}
