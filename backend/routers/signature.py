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
        "rid": secrets.token_urlsafe(16),   # unique request nonce — isolates each request
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


# ── 상시 서명패드 토큰 (사무실 기기 전용 URL, HMAC, 일반 로그인/세션과 분리) ───
# 상태는 PG signature_pad_tokens(테넌트당 active 1행, token_id=UUID4)에 저장한다.
# payload 의 jti(=token_id) 를 DB active token_id 와 대조해 검증 → 재발급 시 즉시 무효화.
# exp 는 DB expires_at(1년) 의 epoch 을 그대로 사용 → 유효한 동안 같은 토큰 문자열 재현.

def _encode_pad_token(tenant_id: str, office_name: str, token_id: str, exp: int) -> str:
    payload = {"t": "p", "tid": tenant_id, "on": office_name,
               "jti": str(token_id), "exp": int(exp)}
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    data_b64 = base64.urlsafe_b64encode(data.encode()).rstrip(b"=").decode()
    sig = _hmac.new(_SIGN_SECRET.encode(), data_b64.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{data_b64}.{sig}"


def _epoch(dt) -> int:
    """tz-aware/naive datetime → epoch 초(naive 는 UTC 로 간주)."""
    from datetime import timezone
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _decode_pad_token(token: str) -> "dict | None":
    try:
        data_b64, sig = token.rsplit(".", 1)
        expected = _hmac.new(_SIGN_SECRET.encode(), data_b64.encode(), hashlib.sha256).hexdigest()[:16]
        if not _hmac.compare_digest(sig, expected):
            return None
        pad = (4 - len(data_b64) % 4) % 4
        payload = json.loads(base64.urlsafe_b64decode(data_b64 + "=" * pad).decode())
        if payload.get("t") != "p":
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


class PadSaveBody(BaseModel):
    data: str                              # base64 PNG (투명 배경)


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
        try:
            customer_sheet_key = _resolve_customer_sheet_key(tenant_id, body.customer_sheet_key)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"customer_sheet_key 조회 실패: {e}")
        _cleanup()
        token = _encode_customer_token(body.customer_id, customer_sheet_key, office_name)
        # Extract rid from token and register in _pending to track submission for this request.
        # poll will only return "saved" when _pending[rid]["submitted"] is True.
        _decoded = _decode_customer_token(token)
        rid = _decoded.get("rid", "") if _decoded else ""
        if rid:
            _pending[rid] = {
                "type": "customer_pending",
                "customer_id": body.customer_id,
                "customer_sheet_key": customer_sheet_key,
                "submitted": False,
                "created_at": _now(),
            }
            _log.info("[request] type=customer rid=%s customer_id=%s token=%s",
                      rid, body.customer_id, token[:8] + "…")
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
    result: dict = {"token": token, "url": url}
    if body.type == "customer" and rid:
        result["request_id"] = rid
    return result


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
    # stateless customer token: poll via _pending[rid] to isolate each request.
    # Never check Sheets directly — a pre-existing signature must NOT trigger "saved".
    payload = _decode_customer_token(token)
    if payload is not None:
        rid = payload.get("rid", "")
        cid = payload.get("cid", "")
        token_hint = token[:8] + "…"
        if rid:
            entry = _pending.get(rid)
            if entry is not None:
                if entry.get("submitted"):
                    _log.info("[poll] token=%s rid=%s customer_id=%s status=saved (submitted)",
                              token_hint, rid, cid)
                    return {"status": "saved", "request_id": rid}
                _log.info("[poll] token=%s rid=%s customer_id=%s status=pending (not yet submitted)",
                          token_hint, rid, cid)
                return {"status": "pending", "request_id": rid}
            # Pending entry gone (server restart or already cleaned up after save).
            # Do NOT fall back to Sheets — that would re-trigger the old signature bug.
            _log.warning("[poll] token=%s rid=%s customer_id=%s pending_entry_missing — returning pending",
                         token_hint, rid, cid)
            return {"status": "pending"}
        # Old token format without rid (pre-fix tokens, expires in <5 min) — keep old behavior
        csk = payload.get("csk", "")
        if not csk or not cid:
            return {"status": "pending"}
        from backend.services.signature_service import has_customer_signature, SignatureLookupError
        try:
            saved = has_customer_signature(csk, cid)
        except SignatureLookupError:
            return {"status": "pending"}
        return {"status": "saved"} if saved else {"status": "pending"}
    # agent/temp: _pending fallback
    entry = _pending.get(token)
    if entry is None or _is_expired(entry):
        return {"status": "expired"}
    if entry.get("data") is None:
        # agent 즉시 저장 완료 → "done" 반환 (data는 save/{token}에서 Sheets에서 읽음)
        if entry.get("type") == "agent" and entry.get("status") == "saved":
            return {"status": "done"}
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
        rid = payload.get("rid", "")
        if not customer_id or not customer_sheet_key:
            raise HTTPException(status_code=400, detail="고객 정보가 없습니다.")
        token_hint = token[:8] + "…"
        _log.info("[submit] token=%s rid=%s customer_id=%s step=saving_to_sheets",
                  token_hint, rid, customer_id)
        try:
            from backend.services.signature_service import save_customer_signature
            save_customer_signature(customer_sheet_key, customer_id, compressed)
        except Exception as e:
            _log.error("[submit] token=%s rid=%s customer_id=%s step=save_failed exc=%s msg=%s",
                       token_hint, rid, customer_id, type(e).__name__, e)
            raise HTTPException(status_code=500, detail=f"서명 저장 실패: {e}")
        # Mark _pending[rid] as submitted so poll returns "saved" for this specific request.
        if rid:
            if rid in _pending:
                _pending[rid]["submitted"] = True
                _log.info("[submit] token=%s rid=%s customer_id=%s pending_marked_submitted",
                          token_hint, rid, customer_id)
            else:
                _log.warning("[submit] token=%s rid=%s customer_id=%s pending_entry_missing "
                             "(server restart?) — signature saved to Sheets but poll cannot notify",
                             token_hint, rid, customer_id)
        else:
            _log.warning("[submit] token=%s customer_id=%s no_rid_in_token (pre-fix token)",
                         token_hint, customer_id)
        _log.info("[submit] token=%s rid=%s customer_id=%s step=done", token_hint, rid, customer_id)
        return {"status": "ok"}

    # ── agent/temp: _pending fallback ─────────────────────────────────────────
    entry = _pending.get(token)
    if entry is None or _is_expired(entry):
        raise HTTPException(status_code=404, detail="링크가 만료되었거나 유효하지 않습니다.")

    t_hint = token[:8] + "…"

    if entry.get("type") == "agent":
        # agent 서명: _pending 의존 없이 즉시 Sheets 영구 저장 (서버 재시작 내성)
        tid = entry.get("tenant_id", "")
        _log.info("[submit] token=%s type=agent tenant=%s step=saving_immediately", t_hint, tid)
        from backend.services.signature_service import save_agent_signature
        try:
            save_agent_signature(tid, compressed)
            _log.info("[submit] token=%s type=agent step=saved_to_sheets", t_hint)
        except Exception as e:
            _log.error("[submit] token=%s type=agent step=save_failed exc=%s msg=%s",
                       t_hint, type(e).__name__, e)
            raise HTTPException(status_code=500, detail=f"행정사 서명 저장 실패: {e}")
        # _pending에는 Sheets 저장 완료 메타데이터만 유지 (poll / save 응답용)
        _pending[token] = {
            "type":       "agent",
            "tenant_id":  tid,
            "office_name": entry.get("office_name", ""),
            "status":     "saved",        # data는 Sheets에 있으므로 여기 보관 불필요
            "created_at": entry["created_at"],
        }
        return {"status": "ok"}
    else:
        # temp: 기존 동작 유지 — /temp-slots/{slot}/save/{token}에서 Sheets 저장
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
        rid = payload.get("rid", "")

        if rid:
            # New token format: gate on _pending[rid]["submitted"].
            # A pre-existing signature in Sheets must never be auto-saved here.
            entry = _pending.get(rid)
            has_pending = entry is not None and bool(entry.get("submitted"))
            _log.info("[save] token=%s rid=%s customer_id=%s has_pending_submission=%s",
                      token_hint, rid, cid, has_pending)
            if not has_pending:
                _log.warning("[save] token=%s rid=%s customer_id=%s "
                             "rejected — no pending submission (source=rejected_no_pending)",
                             token_hint, rid, cid)
                raise HTTPException(
                    status_code=409,
                    detail="이 서명 요청에 제출된 서명이 없습니다. 고객이 아직 서명하지 않았거나 세션이 만료되었습니다.",
                )
            # Confirmed: this specific request was submitted. Fetch from Sheets.
            from backend.services.signature_service import (
                has_customer_signature, get_customer_signature, SignatureLookupError,
            )
            try:
                saved = bool(csk and cid and has_customer_signature(csk, cid))
            except SignatureLookupError as e:
                _log.error("[save] token=%s rid=%s cid=%s sheets_lookup_failed: %s",
                           token_hint, rid, cid, e)
                raise HTTPException(status_code=503, detail="고객서명 조회 실패. 잠시 후 다시 시도해 주세요.") from e
            if saved:
                _log.info("[save] token=%s rid=%s customer_id=%s status=ok "
                          "source=pending_current_request", token_hint, rid, cid)
                try:
                    sig_data = get_customer_signature(csk, cid)
                except Exception:
                    sig_data = None
                try:
                    del _pending[rid]
                except KeyError:
                    pass
                return {"status": "ok", "data": sig_data}
            _log.warning("[save] token=%s rid=%s customer_id=%s status=not_in_sheets_yet",
                         token_hint, rid, cid)
            raise HTTPException(status_code=404, detail="아직 저장된 서명이 없습니다. 잠시 후 다시 시도해 주세요.")

        # Old token format without rid (pre-fix, expires in <5 min) — keep old behavior.
        from backend.services.signature_service import (
            has_customer_signature, get_customer_signature, SignatureLookupError,
        )
        try:
            saved = bool(csk and cid and has_customer_signature(csk, cid))
        except SignatureLookupError as e:
            _log.error("[save] token=%s cid=%s sheets_lookup_failed: %s", token_hint, cid, e)
            raise HTTPException(status_code=503, detail="고객서명 조회 실패. 잠시 후 다시 시도해 주세요.") from e
        if saved:
            _log.info("[save] token=%s customer_id=%s status=confirmed_from_sheets (old_token_no_rid)",
                      token_hint, cid)
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

    # ── agent: submit에서 이미 Sheets 즉시 저장됨 — 조회/확인만 (idempotent) ───
    # _pending이 살아있으면 tenant_id 확인 후 정리. 서버 재시작으로 없어도 user로 조회.
    tenant_id_for_lookup = user.get("tenant_id") or user.get("sub", "")
    entry = _pending.get(token)
    if entry is not None and not _is_expired(entry):
        tenant_id_for_lookup = entry.get("tenant_id", tenant_id_for_lookup)
        _log.info("[save] token=%s type=agent tenant=%s step=confirming_from_sheets",
                  token_hint, tenant_id_for_lookup)
        try:
            del _pending[token]
        except KeyError:
            pass
    else:
        _log.info("[save] token=%s status=pending_gone tenant=%s step=checking_sheets",
                  token_hint, tenant_id_for_lookup)

    from backend.services.signature_service import get_agent_signature
    sig_data = get_agent_signature(tenant_id_for_lookup)
    if sig_data:
        _log.info("[save] token=%s tenant=%s step=confirmed_from_sheets", token_hint, tenant_id_for_lookup)
        return {"status": "ok", "data": sig_data}
    _log.warning("[save] token=%s tenant=%s step=not_found_in_sheets", token_hint, tenant_id_for_lookup)
    raise HTTPException(
        status_code=404,
        detail="행정사 서명 데이터가 만료되었습니다. 다시 등록해 주세요.",
    )


@router.get("/agent/exists")
def check_agent_signature_exists(user: dict = Depends(get_current_user)):
    """행정사 서명 존재 여부 확인."""
    from backend.services.signature_service import get_agent_signature as _get
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    data = _get(tenant_id)
    return {"exists": bool(data)}


@router.get("/agent")
def get_agent_signature(user: dict = Depends(get_current_user)):
    """현재 로그인 테넌트의 행정사 서명 조회.
    서명 없음: HTTP 200 {"data": null}
    서명 존재: HTTP 200 {"data": "base64..."}
    Sheets/API 오류: HTTP 503 (프론트엔드가 error 상태로 표시)"""
    from backend.services.signature_service import get_agent_signature as _get
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    try:
        data = _get(tenant_id)
        return {"data": data}
    except Exception as e:
        print(f"[signature] /agent 조회 오류: {e}")
        raise HTTPException(
            status_code=503,
            detail="행정사 서명 조회에 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
        )


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


# ── 상시 서명패드 (/sign/pad) — 임시서명 빈 슬롯 자동 저장 ─────────────────────

def _pad_office_name(user: dict, tenant_id: str) -> str:
    try:
        from backend.services.accounts_service import get_office_name
        return get_office_name(tenant_id) or user.get("office_name", "") or "행정사사무소"
    except Exception:
        return user.get("office_name", "") or "행정사사무소"


_PAD_PG_REQUIRED = "서명패드 기능은 PostgreSQL 설정이 필요합니다. 관리자에게 문의하세요."


@router.get("/pad/token")
def get_pad_token(user: dict = Depends(get_current_user)):
    """사무실 기기용 상시 서명패드 URL/토큰 (로그인 필요). 계정(테넌트)당 1개.
    유효한 토큰이 있으면 같은 URL 을 재현해 반환, 없거나 만료면 새 token_id 로 발급(1년)."""
    from backend.db.session import is_configured
    if not is_configured():
        raise HTTPException(status_code=503, detail=_PAD_PG_REQUIRED)
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    issued_by = user.get("sub", "") or user.get("login_id", "")
    office_name = _pad_office_name(user, tenant_id)
    from backend.services.signature_pg_service import ensure_pad_token
    state = ensure_pad_token(tenant_id, issued_by)
    token = _encode_pad_token(tenant_id, office_name, state["token_id"], _epoch(state["expires_at"]))
    return {"token": token, "url": f"https://www.hanwory.com/sign/pad?token={token}"}


@router.post("/pad/token/regenerate")
def regenerate_pad_token_endpoint(user: dict = Depends(get_current_user)):
    """서명패드 URL 재발급 — token_id 를 새 UUID4 로 교체해 기존 URL/QR 을 즉시 무효화."""
    from backend.db.session import is_configured
    if not is_configured():
        raise HTTPException(status_code=503, detail=_PAD_PG_REQUIRED)
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    issued_by = user.get("sub", "") or user.get("login_id", "")
    office_name = _pad_office_name(user, tenant_id)
    from backend.services.signature_pg_service import regenerate_pad_token
    state = regenerate_pad_token(tenant_id, issued_by)
    token = _encode_pad_token(tenant_id, office_name, state["token_id"], _epoch(state["expires_at"]))
    return {"token": token, "url": f"https://www.hanwory.com/sign/pad?token={token}"}


@router.get("/pad/info")
def pad_info(token: str = Query(...)):
    """서명패드 페이지용 토큰 확인 — 인증 불필요. 고객정보는 반환하지 않음.
    재발급/만료된(token_id 불일치) 토큰은 valid:false."""
    payload = _decode_pad_token(token)
    if payload is None:
        return {"valid": False, "office_name": ""}
    from backend.db.session import is_configured
    if not is_configured():
        return {"valid": False, "office_name": ""}
    tid = payload.get("tid", "")
    jti = payload.get("jti", "")
    try:
        from backend.services.signature_pg_service import pad_token_is_active
        active = pad_token_is_active(tid, jti)
    except Exception as e:
        # 저장소 일시 오류는 보수적으로 통과 처리(저장 시 재검증됨)
        print(f"[signature.pad] info token check failed (treat as active): {e}")
        active = True
    if not active:
        return {"valid": False, "office_name": ""}
    return {"valid": True, "office_name": payload.get("on", "")}


@router.post("/pad/save")
def pad_save(body: PadSaveBody, token: str = Query(...)):
    """서명패드 저장 — 비어 있는 가장 앞 임시서명 슬롯(1→2→3)에 저장. 모두 차면 차단.
    pad 토큰(HMAC)만으로 동작하며 일반 로그인 세션/FEATURE_SINGLE_SESSION 과 무관."""
    payload = _decode_pad_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="유효하지 않거나 만료된 서명패드 토큰입니다.")
    # tenant_id 는 토큰 내부 값만 사용(프론트 입력 불신).
    tenant_id = payload.get("tid", "")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="토큰에 사무실 정보가 없습니다.")
    from backend.db.session import is_configured
    if not is_configured():
        raise HTTPException(status_code=503, detail=_PAD_PG_REQUIRED)
    # 재발급/만료 가드: DB active token_id 와 payload jti 대조.
    from backend.services.signature_pg_service import pad_token_is_active
    if not pad_token_is_active(tenant_id, payload.get("jti", "")):
        raise HTTPException(
            status_code=401,
            detail="만료되었거나 재발급된 서명패드 주소입니다. 새 URL을 사용해 주세요.",
        )
    from backend.services.signature_service import compress_signature, save_temp_slot_first_empty
    try:
        compressed = compress_signature(body.data)   # 투명 배경 유지 + 압축
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"서명 처리 실패: {e}")
    try:
        slot = save_temp_slot_first_empty(tenant_id, compressed, memo="서명패드")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"저장 실패: {e}")
    if slot is None:
        return {"status": "full"}
    return {"status": "ok", "slot": slot}


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
    """고객 서명 존재 여부 확인.
    - exists:true/false → 조회 성공 (있음/없음)
    - HTTP 503 → Sheets 조회 실패 (frontend가 error로 처리해야 함, false 해석 금지)
    """
    from backend.services.signature_service import has_customer_signature, SignatureLookupError
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    try:
        csk = _resolve_customer_sheet_key(tenant_id, customer_sheet_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        exists = has_customer_signature(csk, customer_id)
    except SignatureLookupError as e:
        raise HTTPException(
            status_code=503,
            detail="고객서명 조회에 실패했습니다. 잠시 후 다시 시도해 주세요.",
        ) from e
    return {"exists": exists}


@router.delete("/customer/{customer_id}")
def delete_customer_signature_endpoint(
    customer_id: str,
    customer_sheet_key: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """고객에게 적용된 고객서명만 삭제. 임시서명 1·2·3 및 고객 기본정보는 비접촉.

    customer_sheet_key 는 항상 로그인 사용자(tenant_id) 기준으로 resolve 하므로
    다른 tenant 의 고객서명은 삭제할 수 없다."""
    from backend.services.signature_service import delete_customer_signature as _del
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    try:
        csk = _resolve_customer_sheet_key(tenant_id, customer_sheet_key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        deleted = _del(csk, customer_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"서명 삭제 실패: {e}")
    return {"ok": True, "deleted": deleted}
