"""서명 라우터 — QR 기반 모바일 서명 수집"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import base64
import hashlib
import hmac as _hmac
import json
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.auth import get_current_user

_log = logging.getLogger("signature")

router = APIRouter()

# ── 고객 직접서명용 HMAC 토큰 (서버 메모리 불필요) ────────────────────────────
# 환경변수로 반드시 오버라이드 할 것 (Render Secret에 설정)
_SIGN_SECRET = os.getenv("SIGNATURE_TOKEN_SECRET", "hw-sign-dev-key-change-in-prod")
_CUSTOMER_TOKEN_TTL = 300  # 5분


def _encode_customer_token(customer_id: str, customer_sheet_key: str,
                           office_name: str, ttl: int = _CUSTOMER_TOKEN_TTL) -> str:
    """고객 직접서명용 HMAC 서명 토큰 발급.
    payload는 base64url(json) + "." + hex_sig[:16] 형태."""
    payload = {
        "t": "c",                           # type = customer
        "cid": customer_id,
        "csk": customer_sheet_key,
        "on": office_name,
        "exp": int(time.time()) + ttl,
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    data_b64 = base64.urlsafe_b64encode(data.encode()).rstrip(b"=").decode()
    sig = _hmac.new(_SIGN_SECRET.encode(), data_b64.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{data_b64}.{sig}"


def _decode_customer_token(token: str) -> "dict | None":
    """HMAC 검증 + 만료 확인. 유효하면 payload dict, 아니면 None."""
    try:
        data_b64, sig = token.rsplit(".", 1)
        expected = _hmac.new(_SIGN_SECRET.encode(), data_b64.encode(), hashlib.sha256).hexdigest()[:16]
        if not _hmac.compare_digest(sig, expected):
            return None
        # re-add base64 padding
        pad = (4 - len(data_b64) % 4) % 4
        payload = json.loads(base64.urlsafe_b64decode(data_b64 + "=" * pad).decode())
        if payload.get("t") != "c":
            return None
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None


# ── 인메모리 토큰 저장소 (agent/temp 전용 — 고객 직접서명에는 사용 안 함) ──────
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
    """QR 서명 요청 생성 — 토큰 + URL 반환.
    customer 타입: HMAC 서명 stateless 토큰 (서버 메모리 불필요).
    agent 타입: 기존 _pending 방식 유지."""
    if body.type not in ("agent", "customer"):
        raise HTTPException(status_code=400, detail="type은 'agent' 또는 'customer'여야 합니다.")
    if body.type == "customer" and not body.customer_id:
        raise HTTPException(status_code=400, detail="customer 타입은 customer_id 필수.")

    tenant_id = user.get("tenant_id") or user.get("sub", "")

    try:
        from backend.services.accounts_service import get_office_name
        office_name = get_office_name(tenant_id) or user.get("office_name", "") or "행정사사무소"
    except Exception:
        office_name = user.get("office_name", "") or "행정사사무소"

    if body.type == "customer":
        # Stateless HMAC token — no server memory needed
        try:
            customer_sheet_key = _resolve_customer_sheet_key(tenant_id, body.customer_sheet_key)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"customer_sheet_key 조회 실패: {e}")
        token = _encode_customer_token(body.customer_id, customer_sheet_key, office_name)
    else:
        # agent: keep _pending-based token
        _cleanup()
        token = secrets.token_urlsafe(6)
        _pending[token] = {
            "type":       body.type,
            "tenant_id":  tenant_id,
            "office_name": office_name,
            "created_at": _now(),
            "data":       None,
        }

    url = f"https://www.hanwory.com/sign/{token}"
    return {"token": token, "url": url}


@router.get("/info/{token}")
def get_signature_info(token: str):
    """모바일 서명 페이지용 토큰 정보 — 인증 불필요."""
    # stateless customer token
    payload = _decode_customer_token(token)
    if payload is not None:
        return {"status": "valid", "office_name": payload.get("on", "")}
    # agent/temp: _pending fallback
    entry = _pending.get(token)
    if entry is None or _is_expired(entry):
        return {"status": "expired", "office_name": ""}
    return {"status": "valid", "office_name": entry.get("office_name", "")}


@router.get("/poll/{token}")
def poll_signature(token: str, user: dict = Depends(get_current_user)):
    """서명 완료 여부 폴링."""
    # stateless customer token: poll via Sheets A-column exists check
    payload = _decode_customer_token(token)
    if payload is not None:
        from backend.services.signature_service import has_customer_signature
        csk = payload.get("csk", "")
        cid = payload.get("cid", "")
        if csk and cid and has_customer_signature(csk, cid):
            return {"status": "saved"}
        return {"status": "pending"}
    # agent/temp: _pending fallback
    entry = _pending.get(token)
    if entry is None or _is_expired(entry):
        return {"status": "expired"}
    if entry["data"] is None:
        return {"status": "waiting"}
    return {"status": "done", "data": entry["data"]}


@router.post("/submit/{token}")
def submit_signature(token: str, body: SignatureSubmitBody):
    """모바일에서 서명 제출 — customer 타입은 즉시 고객서명 시트에 저장. _pending 없음."""
    from backend.services.signature_service import compress_signature
    try:
        compressed = compress_signature(body.data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"서명 처리 실패: {e}")

    # ── stateless customer token ──────────────────────────────────────────────
    payload = _decode_customer_token(token)
    if payload is not None:
        customer_id = payload.get("cid", "")
        customer_sheet_key = payload.get("csk", "")
        if not customer_id or not customer_sheet_key:
            raise HTTPException(status_code=400, detail="고객 정보가 없습니다.")
        token_hint = token[:8] + "…"
        _log.info("[submit] token=%s customer_id=%s step=saving_to_sheets", token_hint, customer_id)
        try:
            from backend.services.signature_service import save_customer_signature
            save_customer_signature(customer_sheet_key, customer_id, compressed)
        except Exception as e:
            _log.error("[submit] token=%s customer_id=%s step=save_failed exc=%s msg=%s",
                       token_hint, customer_id, type(e).__name__, e)
            raise HTTPException(status_code=500, detail=f"서명 저장 실패: {e}")
        _log.info("[submit] token=%s customer_id=%s step=saved", token_hint, customer_id)
        return {"status": "ok"}  # no _pending update

    # ── agent/temp: _pending fallback ─────────────────────────────────────────
    entry = _pending.get(token)
    if entry is None or _is_expired(entry):
        raise HTTPException(status_code=404, detail="링크가 만료되었거나 유효하지 않습니다.")
    _pending[token]["data"] = compressed
    return {"status": "ok"}


@router.post("/save/{token}")
def save_signature(token: str, user: dict = Depends(get_current_user)):
    """서명 저장 확인 엔드포인트.
    - customer 타입 (stateless token): 이미 저장됐는지 확인 → idempotent confirm
    - agent 타입 (_pending): 여기서 실제 저장"""
    token_hint = token[:8] + "…" if len(token) >= 8 else token

    # ── stateless customer token ──────────────────────────────────────────────
    payload = _decode_customer_token(token)
    if payload is not None:
        csk = payload.get("csk", "")
        cid = payload.get("cid", "")
        from backend.services.signature_service import has_customer_signature, get_customer_signature
        if csk and cid and has_customer_signature(csk, cid):
            _log.info("[save] token=%s customer_id=%s status=confirmed_from_sheets", token_hint, cid)
            try:
                sig_data = get_customer_signature(csk, cid)
            except Exception:
                sig_data = None
            return {"status": "ok", "data": sig_data}
        _log.warning("[save] token=%s customer_id=%s status=not_saved_yet", token_hint, cid)
        raise HTTPException(
            status_code=404,
            detail="아직 저장된 서명이 없습니다. 고객에게 서명 제출을 요청하세요.",
        )

    # ── agent: _pending fallback ──────────────────────────────────────────────
    entry = _pending.get(token)
    if entry is None or _is_expired(entry):
        _log.info("[save] token=%s status=token_not_found", token_hint)
        raise HTTPException(status_code=404, detail="토큰이 만료되었거나 이미 저장되었습니다.")
    if entry["data"] is None:
        raise HTTPException(status_code=400, detail="아직 서명이 제출되지 않았습니다.")

    sig_type = entry.get("type", "")
    _log.info("[save] token=%s type=%s step=writing_to_sheets", token_hint, sig_type)
    from backend.services.signature_service import save_agent_signature
    try:
        save_agent_signature(entry["tenant_id"], entry["data"])
        _log.info("[save] token=%s step=sheets_write_ok", token_hint)
    except Exception as e:
        _log.error("[save] token=%s step=sheets_write_failed exc=%s msg=%s",
                   token_hint, type(e).__name__, e)
        raise HTTPException(status_code=500, detail=f"저장 실패: {e}")

    saved_data = entry["data"]
    try:
        del _pending[token]
    except KeyError:
        pass
    _log.info("[save] token=%s step=done", token_hint)
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
