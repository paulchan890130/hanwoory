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


# ── 삭제 제약 (Phase G-1) — Sheets certification_service 와 동일 의미를 PG 로 구현 ──
# price 가 참조하는 vendor/direction/group/region 은 삭제 차단(409) 또는 soft-delete.
#   vendor : price.vendor_id == vendor.id     → soft-delete(active=false)
#   group  : price.group_id  == group.id      → 409
#   dir    : price.direction == direction.name → 409 (price 는 이름으로 참조)
#   region : price.region    == region.name    → 409 (price 는 이름으로 참조)
# 충돌 예외는 router 가 catch 하는 certification_service.ReferenceConflictError 를 그대로 사용
# (예외 클래스 import 만 — Sheets 런타임 호출 없음).

def _all_prices(tenant_id: str) -> list[dict]:
    from backend.db.models.certification import CertPrice
    return _list(tenant_id, CertPrice, PRICE_FIELDS)


def _conflict(msg: str):
    from backend.services.certification_service import ReferenceConflictError
    return ReferenceConflictError(msg)


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
    """가격조건이 연결된 업체 → soft-delete(active=false). 없으면 hard-delete. (Sheets 동일)"""
    from backend.db.models.certification import CertVendor
    from backend.db.session import get_sessionmaker
    ref = sum(1 for p in _all_prices(tenant_id) if p.get("vendor_id") == vid)
    if ref > 0:
        SessionLocal = get_sessionmaker()
        with SessionLocal() as session:
            row = session.scalar(select(CertVendor).where(
                CertVendor.id == vid, CertVendor.tenant_id == tenant_id))
            if row is None:
                return {"action": "not_found", "ref_count": 0}
            row.active = "false"
            session.commit()
        return {"action": "deactivated", "ref_count": ref}
    _delete(tenant_id, CertVendor, vid)
    return {"action": "deleted", "ref_count": 0}


def get_directions(tenant_id: str):
    from backend.db.models.certification import CertDirection
    return _list(tenant_id, CertDirection, DIRECTION_FIELDS)

def save_direction(tenant_id: str, body: dict):
    from backend.db.models.certification import CertDirection
    return _upsert(tenant_id, CertDirection, DIRECTION_FIELDS, body)

def delete_direction(tenant_id: str, did: str):
    from backend.db.models.certification import CertDirection
    d = next((x for x in _list(tenant_id, CertDirection, DIRECTION_FIELDS) if x.get("id") == did), None)
    if d:
        ref = sum(1 for p in _all_prices(tenant_id) if p.get("direction") == d.get("name", ""))
        if ref > 0:
            raise _conflict(
                f"이 대분류를 사용하는 가격조건이 {ref}건 있어 삭제할 수 없습니다. "
                "먼저 가격조건을 수정하거나 비활성 처리하세요."
            )
    return {"deleted": _delete(tenant_id, CertDirection, did)}


def get_groups(tenant_id: str):
    from backend.db.models.certification import CertGroup
    return _list(tenant_id, CertGroup, GROUP_FIELDS)

def save_group(tenant_id: str, body: dict):
    from backend.db.models.certification import CertGroup
    return _upsert(tenant_id, CertGroup, GROUP_FIELDS, body)

def delete_group(tenant_id: str, gid: str):
    from backend.db.models.certification import CertGroup
    ref = sum(1 for p in _all_prices(tenant_id) if p.get("group_id") == gid)
    if ref > 0:
        raise _conflict(
            f"이 중분류를 사용하는 가격조건이 {ref}건 있어 삭제할 수 없습니다. "
            "먼저 해당 가격조건을 수정하거나 삭제하세요."
        )
    return {"deleted": _delete(tenant_id, CertGroup, gid)}


def get_regions(tenant_id: str):
    from backend.db.models.certification import CertRegion
    return _list(tenant_id, CertRegion, REGION_FIELDS)

def save_region(tenant_id: str, body: dict):
    from backend.db.models.certification import CertRegion
    return _upsert(tenant_id, CertRegion, REGION_FIELDS, body)

def delete_region(tenant_id: str, rid: str):
    from backend.db.models.certification import CertRegion
    r = next((x for x in _list(tenant_id, CertRegion, REGION_FIELDS) if x.get("id") == rid), None)
    if r:
        ref = sum(1 for p in _all_prices(tenant_id) if p.get("region") == r.get("name", ""))
        if ref > 0:
            raise _conflict(
                f"이 소분류/지역을 사용하는 가격조건이 {ref}건 있어 삭제할 수 없습니다. "
                "먼저 해당 가격조건을 수정하거나 삭제하세요."
            )
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
