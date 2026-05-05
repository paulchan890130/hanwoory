"""서명 라우터 — QR 기반 모바일 서명 수집"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.auth import get_current_user

router = APIRouter()

# ── 인메모리 토큰 저장소 ──────────────────────────────────────────────────────
# { token: { type, tenant_id, customer_id, customer_sheet_key, created_at, data } }
_pending: dict[str, dict] = {}

_TOKEN_TTL = 300  # 5분


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _cleanup():
    now = _now()
    expired = [
        t for t, v in _pending.items()
        if (now - v["created_at"]).total_seconds() > _TOKEN_TTL
    ]
    for t in expired:
        del _pending[t]


def _is_expired(entry: dict) -> bool:
    return (_now() - entry["created_at"]).total_seconds() > _TOKEN_TTL


# ── 요청 모델 ─────────────────────────────────────────────────────────────────

class SignatureRequestBody(BaseModel):
    type: str                              # "agent" | "customer"
    customer_id: Optional[str] = None
    customer_sheet_key: Optional[str] = None


class SignatureSubmitBody(BaseModel):
    data: str                              # base64 PNG


class TempSlotRequestBody(BaseModel):
    memo: str = ""


class TempMapCustomerBody(BaseModel):
    customer_id: str


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

def _resolve_customer_sheet_key(tenant_id: str, provided: Optional[str]) -> str:
    if provided and provided.strip():
        return provided.strip()
    from backend.services.tenant_service import get_customer_sheet_key
    return get_customer_sheet_key(tenant_id)


@router.post("/request")
def request_signature(
    body: SignatureRequestBody,
    user: dict = Depends(get_current_user),
):
    """QR 서명 요청 생성 — 토큰 + URL 반환."""
    if body.type not in ("agent", "customer"):
        raise HTTPException(status_code=400, detail="type은 'agent' 또는 'customer'여야 합니다.")
    if body.type == "customer" and not body.customer_id:
        raise HTTPException(status_code=400, detail="customer 타입은 customer_id 필수.")

    _cleanup()
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    customer_sheet_key = None
    if body.type == "customer":
        try:
            customer_sheet_key = _resolve_customer_sheet_key(tenant_id, body.customer_sheet_key)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"customer_sheet_key 조회 실패: {e}")

    # 사무소 이름 조회
    try:
        from backend.services.accounts_service import get_office_name
        office_name = get_office_name(tenant_id) or user.get("office_name", "") or "행정사사무소"
    except Exception:
        office_name = user.get("office_name", "") or "행정사사무소"

    token = secrets.token_urlsafe(6)
    _pending[token] = {
        "type":               body.type,
        "tenant_id":          tenant_id,
        "customer_id":        body.customer_id,
        "customer_sheet_key": customer_sheet_key,
        "office_name":        office_name,
        "created_at":         _now(),
        "data":               None,
    }
    url = f"https://www.hanwory.com/sign/{token}"
    return {"token": token, "url": url}


@router.get("/info/{token}")
def get_signature_info(token: str):
    """모바일 서명 페이지용 토큰 정보 — 인증 불필요."""
    entry = _pending.get(token)
    if entry is None or _is_expired(entry):
        return {"status": "expired", "office_name": ""}
    return {"status": "valid", "office_name": entry.get("office_name", "")}


@router.get("/poll/{token}")
def poll_signature(token: str, user: dict = Depends(get_current_user)):
    """서명 완료 여부 폴링."""
    entry = _pending.get(token)
    if entry is None or _is_expired(entry):
        return {"status": "expired"}
    if entry["data"] is None:
        return {"status": "waiting"}
    return {"status": "done", "data": entry["data"]}


@router.post("/submit/{token}")
def submit_signature(token: str, body: SignatureSubmitBody):
    """모바일에서 서명 제출 — 인증 불필요."""
    entry = _pending.get(token)
    if entry is None or _is_expired(entry):
        raise HTTPException(status_code=404, detail="링크가 만료되었거나 유효하지 않습니다.")

    from backend.services.signature_service import compress_signature
    try:
        compressed = compress_signature(body.data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"서명 처리 실패: {e}")

    _pending[token]["data"] = compressed
    return {"status": "ok"}


@router.post("/save/{token}")
def save_signature(token: str, user: dict = Depends(get_current_user)):
    """폴링 완료 후 Sheets에 저장."""
    entry = _pending.get(token)
    if entry is None or _is_expired(entry):
        raise HTTPException(status_code=404, detail="토큰이 만료되었습니다.")
    if entry["data"] is None:
        raise HTTPException(status_code=400, detail="아직 서명이 제출되지 않았습니다.")

    from backend.services.signature_service import save_agent_signature, save_customer_signature
    try:
        if entry["type"] == "agent":
            save_agent_signature(entry["tenant_id"], entry["data"])
        else:
            save_customer_signature(
                entry["customer_sheet_key"] or "",
                entry["customer_id"] or "",
                entry["data"],
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"저장 실패: {e}")

    saved_data = entry["data"]
    del _pending[token]
    return {"status": "ok", "data": saved_data}


@router.get("/agent")
def get_agent_signature(user: dict = Depends(get_current_user)):
    """현재 로그인 테넌트의 행정사 서명 조회."""
    from backend.services.signature_service import get_agent_signature as _get
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    data = _get(tenant_id)
    return {"data": data}


@router.get("/customer/{customer_id}")
def get_customer_signature(
    customer_id: str,
    customer_sheet_key: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """고객 서명 데이터 조회."""
    from backend.services.signature_service import get_customer_signature as _get
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    try:
        csk = _resolve_customer_sheet_key(tenant_id, customer_sheet_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    data = _get(csk, customer_id)
    return {"data": data}


# ── 임시저장 슬롯 엔드포인트 ──────────────────────────────────────────────────

@router.get("/temp-slots")
def get_temp_slots(user: dict = Depends(get_current_user)):
    """슬롯 1~3 상태 반환 (서명데이터 제외)."""
    from backend.services.signature_service import get_temp_slots as _get
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    return _get(tenant_id)


@router.post("/temp-slots/{slot}/request")
def request_temp_slot(slot: int, body: TempSlotRequestBody, user: dict = Depends(get_current_user)):
    """임시저장 슬롯용 QR 서명 요청 — 토큰 + URL 반환."""
    if slot not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="slot은 1, 2, 3 중 하나여야 합니다.")
    _cleanup()
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    try:
        from backend.services.accounts_service import get_office_name
        office_name = get_office_name(tenant_id) or user.get("office_name", "") or "행정사사무소"
    except Exception:
        office_name = user.get("office_name", "") or "행정사사무소"

    token = secrets.token_urlsafe(6)
    _pending[token] = {
        "type":       "temp",
        "tenant_id":  tenant_id,
        "slot":       slot,
        "memo":       body.memo,
        "office_name": office_name,
        "created_at": _now(),
        "data":       None,
    }
    url = f"https://www.hanwory.com/sign/{token}"
    return {"token": token, "url": url}


@router.post("/temp-slots/{slot}/save/{token}")
def save_temp_slot_endpoint(slot: int, token: str, user: dict = Depends(get_current_user)):
    """폴링 완료 후 임시저장 슬롯에 저장."""
    entry = _pending.get(token)
    if entry is None or _is_expired(entry):
        raise HTTPException(status_code=404, detail="토큰이 만료되었습니다.")
    if entry["data"] is None:
        raise HTTPException(status_code=400, detail="아직 서명이 제출되지 않았습니다.")
    from backend.services.signature_service import save_temp_slot
    try:
        save_temp_slot(entry["tenant_id"], slot, entry["data"], entry.get("memo", ""))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"저장 실패: {e}")
    del _pending[token]
    return {"status": "ok"}


@router.get("/temp-slots/{slot}/data")
def get_temp_slot_data_endpoint(slot: int, user: dict = Depends(get_current_user)):
    """슬롯 서명 데이터 조회."""
    from backend.services.signature_service import get_temp_slot_data
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    data = get_temp_slot_data(tenant_id, slot)
    return {"data": data}


@router.post("/temp-slots/{slot}/clear")
def clear_temp_slot_endpoint(slot: int, user: dict = Depends(get_current_user)):
    """슬롯 데이터 삭제."""
    from backend.services.signature_service import clear_temp_slot
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    clear_temp_slot(tenant_id, slot)
    return {"status": "ok"}


@router.post("/temp-slots/{slot}/map-customer")
def map_temp_slot_to_customer(
    slot: int,
    body: TempMapCustomerBody,
    user: dict = Depends(get_current_user),
):
    """슬롯 서명 → 고객 서명으로 복사 후 슬롯 삭제."""
    from backend.services.signature_service import (
        get_temp_slot_data, save_customer_signature, clear_temp_slot,
    )
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    data = get_temp_slot_data(tenant_id, slot)
    if not data:
        raise HTTPException(status_code=404, detail="슬롯에 서명 데이터가 없습니다.")
    try:
        csk = _resolve_customer_sheet_key(tenant_id, None)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"customer_sheet_key 조회 실패: {e}")
    try:
        save_customer_signature(csk, body.customer_id, data)
        clear_temp_slot(tenant_id, slot)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"매핑 실패: {e}")
    return {"status": "ok"}


@router.post("/temp-slots/{slot}/map/{customer_id}")
def map_temp_slot_url(
    slot: int,
    customer_id: str,
    user: dict = Depends(get_current_user),
):
    """슬롯 서명 → 고객 서명 복사 + 슬롯 삭제 (URL 방식)."""
    from backend.services.signature_service import (
        get_temp_slot_data, save_customer_signature, clear_temp_slot,
    )
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    data = get_temp_slot_data(tenant_id, slot)
    if not data:
        raise HTTPException(status_code=404, detail="슬롯에 서명 데이터가 없습니다.")
    try:
        csk = _resolve_customer_sheet_key(tenant_id, None)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"customer_sheet_key 조회 실패: {e}")
    try:
        save_customer_signature(csk, customer_id, data)
        clear_temp_slot(tenant_id, slot)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"매핑 실패: {e}")
    return {"status": "ok"}


@router.get("/customer/{customer_id}/exists")
def check_customer_signature_exists(
    customer_id: str,
    customer_sheet_key: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """고객 서명 존재 여부 확인."""
    from backend.services.signature_service import has_customer_signature
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    try:
        csk = _resolve_customer_sheet_key(tenant_id, customer_sheet_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    exists = has_customer_signature(csk, customer_id)
    return {"exists": exists}
