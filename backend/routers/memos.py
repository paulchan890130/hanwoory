"""메모 라우터 (테넌트 인식)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, Depends, HTTPException, Path
from backend.auth import get_current_user
from backend.models import MemoSaveRequest
from backend.services.tenant_service import read_memo, save_memo
from backend.services.cache_service import cache_get, cache_set, cache_invalidate

router = APIRouter()

_MEMO_SHEETS = {
    "short": "MEMO_SHORT_SHEET_NAME",
    "mid":   "MEMO_MID_SHEET_NAME",
    "long":  "MEMO_LONG_SHEET_NAME",
}
_TTL_MEMO = 30.0  # seconds — short memo is the one shown on dashboard


def _cache_key(memo_type: str) -> str:
    return f"memo:{memo_type}"


def _get_sheet_name(memo_type: str) -> str:
    import config
    attr = _MEMO_SHEETS.get(memo_type)
    if not attr:
        raise HTTPException(status_code=400, detail=f"메모 타입 오류: {memo_type}")
    return getattr(config, attr)


@router.get("/{memo_type}")
def get_memo(
    memo_type: str = Path(..., pattern="^(short|mid|long)$"),
    user: dict = Depends(get_current_user),
):
    tenant_id = user["tenant_id"]
    ck = _cache_key(memo_type)
    cached = cache_get(tenant_id, ck)
    if cached is not None:
        return cached
    sheet_name = _get_sheet_name(memo_type)
    content = read_memo(sheet_name, tenant_id)
    result = {"memo_type": memo_type, "content": content or ""}
    cache_set(tenant_id, ck, result, _TTL_MEMO)
    return result


@router.post("/{memo_type}")
def save_memo_route(
    req: MemoSaveRequest,
    memo_type: str = Path(..., pattern="^(short|mid|long)$"),
    user: dict = Depends(get_current_user),
):
    tenant_id = user["tenant_id"]
    sheet_name = _get_sheet_name(memo_type)
    ok = save_memo(sheet_name, tenant_id, req.content)
    if not ok:
        raise HTTPException(status_code=500, detail="메모 저장 실패")
    cache_invalidate(tenant_id, _cache_key(memo_type))
    return {"ok": True}
