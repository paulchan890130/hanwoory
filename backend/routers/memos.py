"""메모 라우터 (테넌트 인식)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, Depends, HTTPException, Path
from backend.auth import get_current_user
from backend.models import MemoSaveRequest
from backend.services.tenant_service import read_memo, save_memo

router = APIRouter()

_MEMO_SHEETS = {
    "short": "MEMO_SHORT_SHEET_NAME",
    "mid":   "MEMO_MID_SHEET_NAME",
    "long":  "MEMO_LONG_SHEET_NAME",
}


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
    sheet_name = _get_sheet_name(memo_type)
    content = read_memo(sheet_name, user["tenant_id"])
    return {"memo_type": memo_type, "content": content or ""}


@router.post("/{memo_type}")
def save_memo_route(
    req: MemoSaveRequest,
    memo_type: str = Path(..., pattern="^(short|mid|long)$"),
    user: dict = Depends(get_current_user),
):
    sheet_name = _get_sheet_name(memo_type)
    ok = save_memo(sheet_name, user["tenant_id"], req.content)
    if not ok:
        raise HTTPException(status_code=500, detail="메모 저장 실패")
    return {"ok": True}
