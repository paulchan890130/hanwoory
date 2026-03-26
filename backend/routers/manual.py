"""메뉴얼 검색 라우터 - GPT 기반 출입국 법령 Q&A"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, Depends, HTTPException, Query
from backend.auth import get_current_user
from core.manual_search import search_via_server

router = APIRouter()


@router.get("/search")
def manual_search(
    q: str = Query(..., min_length=1, description="검색 질문"),
    user: dict = Depends(get_current_user),
):
    """
    GPT 기반 출입국 법령 검색.
    core.manual_search.search_via_server()를 래핑하여 REST API로 노출.
    """
    if not q.strip():
        raise HTTPException(status_code=400, detail="검색어를 입력하세요.")
    try:
        answer = search_via_server(q.strip())
        return {"question": q.strip(), "answer": answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"검색 오류: {str(e)}")
