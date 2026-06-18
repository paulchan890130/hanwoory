"""메모 라우터 (테넌트 인식) — PG-only(Phase F).

장기/중기/단기메모(long/mid/short)는 PostgreSQL(memos_pg_service)만 사용한다.
PG 미구성 시 조용한 fallback 없이 RuntimeError를 낸다. 응답 구조는 기존과 동일
({"memo_type": ..., "content": ...}).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, Depends, Path
from backend.auth import get_current_user
from backend.models import MemoSaveRequest

router = APIRouter()


@router.get("/{memo_type}")
def get_memo(
    memo_type: str = Path(..., pattern="^(short|mid|long)$"),
    user: dict = Depends(get_current_user),
):
    from backend.services.memos_pg_service import get_memo as _pg_get
    content = _pg_get(user["tenant_id"], memo_type)
    return {"memo_type": memo_type, "content": content or ""}


@router.post("/{memo_type}")
def save_memo_route(
    req: MemoSaveRequest,
    memo_type: str = Path(..., pattern="^(short|mid|long)$"),
    user: dict = Depends(get_current_user),
):
    from backend.services.memos_pg_service import save_memo as _pg_save
    _pg_save(user["tenant_id"], memo_type, req.content or "")
    return {"ok": True}
