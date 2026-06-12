"""backend/routers/certification.py — 각종공인증 API"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, Depends, HTTPException
from backend.auth import get_current_user
# 각종공인증은 PG-only(Phase G). certification_service(Sheets)는 미사용(dead, sheets_guard 차단).
# ReferenceConflictError 예외 클래스만 import(런타임 Sheets 호출 없음).
from backend.services.certification_service import ReferenceConflictError

router = APIRouter()


def _tenant(user=Depends(get_current_user)) -> str:
    return user["tenant_id"]


def _svc():
    """PG-only(Phase G): 각종공인증은 항상 PostgreSQL(certification_pg_service). Sheets fallback 제거."""
    import backend.services.certification_pg_service as _pg
    return _pg


# ── Bootstrap ─────────────────────────────────────────────────────────────────

@router.get("/bootstrap")
def bootstrap(user=Depends(get_current_user)):
    try:
        return _svc().bootstrap(user["tenant_id"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Debug storage ──────────────────────────────────────────────────────────────

@router.get("/debug-storage")
def debug_storage(user=Depends(get_current_user)):
    """
    진단용 엔드포인트.
    실제로 어느 스프레드시트에 각종공인증 탭을 만들고 있는지 확인.
    배포 후 /api/certification-services/debug-storage 로 호출.
    """
    try:
        return svc.debug_storage_info(
            tenant_id=user["tenant_id"],
            login_id=user.get("login_id", ""),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Vendors ───────────────────────────────────────────────────────────────────

@router.get("/vendors")
def list_vendors(tenant_id: str = Depends(_tenant)):
    try:
        return _svc().get_vendors(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vendors")
def create_vendor(body: dict, tenant_id: str = Depends(_tenant)):
    try:
        return _svc().save_vendor(tenant_id, dict(body))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/vendors/{vid}")
def update_vendor(vid: str, body: dict, tenant_id: str = Depends(_tenant)):
    body["id"] = vid
    try:
        return _svc().save_vendor(tenant_id, dict(body))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/vendors/{vid}")
def del_vendor(vid: str, tenant_id: str = Depends(_tenant)):
    try:
        return _svc().delete_vendor(tenant_id, vid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Directions ────────────────────────────────────────────────────────────────

@router.get("/directions")
def list_directions(tenant_id: str = Depends(_tenant)):
    try:
        return _svc().get_directions(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/directions")
def create_direction(body: dict, tenant_id: str = Depends(_tenant)):
    try:
        return _svc().save_direction(tenant_id, dict(body))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/directions/{did}")
def update_direction(did: str, body: dict, tenant_id: str = Depends(_tenant)):
    body["id"] = did
    try:
        return _svc().save_direction(tenant_id, dict(body))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/directions/{did}")
def del_direction(did: str, tenant_id: str = Depends(_tenant)):
    try:
        _svc().delete_direction(tenant_id, did)
        return {"ok": True}
    except ReferenceConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Groups ────────────────────────────────────────────────────────────────────

@router.get("/groups")
def list_groups(tenant_id: str = Depends(_tenant)):
    try:
        return _svc().get_groups(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/groups")
def create_group(body: dict, tenant_id: str = Depends(_tenant)):
    try:
        return _svc().save_group(tenant_id, dict(body))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/groups/{gid}")
def update_group(gid: str, body: dict, tenant_id: str = Depends(_tenant)):
    body["id"] = gid
    try:
        return _svc().save_group(tenant_id, dict(body))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/groups/{gid}")
def del_group(gid: str, tenant_id: str = Depends(_tenant)):
    try:
        _svc().delete_group(tenant_id, gid)
        return {"ok": True}
    except ReferenceConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Regions ───────────────────────────────────────────────────────────────────

@router.get("/regions")
def list_regions(tenant_id: str = Depends(_tenant)):
    try:
        return _svc().get_regions(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/regions")
def create_region(body: dict, tenant_id: str = Depends(_tenant)):
    try:
        return _svc().save_region(tenant_id, dict(body))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/regions/{rid}")
def update_region(rid: str, body: dict, tenant_id: str = Depends(_tenant)):
    body["id"] = rid
    try:
        return _svc().save_region(tenant_id, dict(body))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/regions/{rid}")
def del_region(rid: str, tenant_id: str = Depends(_tenant)):
    try:
        _svc().delete_region(tenant_id, rid)
        return {"ok": True}
    except ReferenceConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Prices ────────────────────────────────────────────────────────────────────

@router.get("/prices")
def list_prices(tenant_id: str = Depends(_tenant)):
    try:
        return _svc().get_prices(tenant_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prices")
def create_price(body: dict, tenant_id: str = Depends(_tenant)):
    try:
        return _svc().save_price(tenant_id, dict(body))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/prices/{pid}")
def update_price(pid: str, body: dict, tenant_id: str = Depends(_tenant)):
    body["id"] = pid
    try:
        return _svc().save_price(tenant_id, dict(body))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/prices/{pid}")
def del_price(pid: str, tenant_id: str = Depends(_tenant)):
    try:
        _svc().delete_price(tenant_id, pid)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
