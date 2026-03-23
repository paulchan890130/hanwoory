"""통합검색 라우터 - tenant별 격리 실제 구현"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import traceback
from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.services.tenant_service import read_sheet, read_memo
from config import (
    CUSTOMER_SHEET_NAME,
    PLANNED_TASKS_SHEET_NAME,
    ACTIVE_TASKS_SHEET_NAME,
    COMPLETED_TASKS_SHEET_NAME,
    MEMO_LONG_SHEET_NAME,
    MEMO_MID_SHEET_NAME,
)

try:
    from config import BOARD_SHEET_NAME
except ImportError:
    BOARD_SHEET_NAME = "게시판"

router = APIRouter()


# ── 스키마 ────────────────────────────────────────────────────────────────────

class SearchResult(BaseModel):
    id: str
    type: str           # customer | task | board | reference | memo
    title: str
    summary: str
    highlight: Optional[str] = None
    url: str


class SearchResponse(BaseModel):
    query: str
    type: str
    total: int
    results: List[SearchResult]


VALID_TYPES = {"all", "customer", "task", "board", "reference", "memo"}


# ── 공통 매처 ─────────────────────────────────────────────────────────────────

def _match(row: dict, q: str) -> bool:
    ql = q.lower()
    return any(ql in str(v).lower() for v in row.values() if v)


# ── 검색 소스별 함수 ──────────────────────────────────────────────────────────

def _search_customers(q: str, tenant_id: str) -> List[SearchResult]:
    """
    고객 데이터 검색.
    - tenant_id 기반 시트 격리 (tenant_service.read_sheet 사용)
    - 다른 tenant의 데이터는 절대 검색되지 않음
    """
    rows = read_sheet(CUSTOMER_SHEET_NAME, tenant_id, default_if_empty=[]) or []
    results = []
    for r in rows:
        if not _match(r, q):
            continue
        # 한글이름: 실무 컬럼 "한글" 우선, fallback "한글이름"
        name = str(r.get("한글", "") or r.get("한글이름", "")).strip()
        # 영문이름: 실무 컬럼 "성"+"명", fallback "영문이름"
        eng_last  = str(r.get("성", "")).strip()
        eng_first = str(r.get("명", "")).strip()
        eng = f"{eng_last} {eng_first}".strip() or str(r.get("영문이름", "")).strip()
        cid = str(r.get("고객ID", "")).strip()
        nationality = str(r.get("국적", "")).strip()
        visa = str(r.get("체류자격", "") or r.get("비자종류", "")).strip()
        summary_parts = [p for p in [name, eng, nationality, visa] if p]
        results.append(SearchResult(
            id=cid or name,
            type="customer",
            title=name or eng or cid or "(이름 없음)",
            summary=" · ".join(summary_parts),
            url=f"/customers?search={cid}",
        ))
    return results


def _search_tasks(q: str, tenant_id: str) -> List[SearchResult]:
    """예정/진행/완료 업무 검색 — tenant 격리"""
    results = []
    for sheet_name, label in [
        (PLANNED_TASKS_SHEET_NAME,   "예정"),
        (ACTIVE_TASKS_SHEET_NAME,    "진행"),
        (COMPLETED_TASKS_SHEET_NAME, "완료"),
    ]:
        rows = read_sheet(sheet_name, tenant_id, default_if_empty=[]) or []
        for r in rows:
            if not _match(r, q):
                continue
            # 업무 시트의 이름 컬럼: "이름"/"한글"/"고객명" 순으로 fallback
            name = (
                str(r.get("이름",   "")).strip() or
                str(r.get("한글",   "")).strip() or
                str(r.get("고객명", "")).strip()
            )
            tid = str(r.get("id", "") or r.get("업무ID", "") or r.get("고객ID", "")).strip()
            minwon = str(r.get("민원", "") or r.get("업무내용", "")).strip()
            status = str(r.get("상태", "")).strip()
            summary_parts = [p for p in [label, minwon, status] if p]
            results.append(SearchResult(
                id=tid or name,
                type="task",
                title=f"[{label}] {name}" if name else f"[{label}] 업무",
                summary=" · ".join(summary_parts),
                url="/tasks",
            ))
    return results


def _search_board(q: str, tenant_id: str) -> List[SearchResult]:
    """게시판 검색 — tenant 격리"""
    rows = read_sheet(BOARD_SHEET_NAME, tenant_id, default_if_empty=[]) or []
    results = []
    for r in rows:
        if not _match(r, q):
            continue
        title   = str(r.get("제목", "") or r.get("title", "")).strip()
        bid     = str(r.get("id", "") or r.get("게시판ID", "")).strip()
        content = str(r.get("내용", "") or r.get("content", ""))
        snip    = content[:80].replace("\n", " ")
        results.append(SearchResult(
            id=bid or title,
            type="board",
            title=title or "게시글",
            summary=snip,
            url="/board",
        ))
    return results


def _search_reference(q: str, tenant_id: str) -> List[SearchResult]:
    """업무참고 시트 검색 — tenant 격리 (업무정리 워크북 기준)"""
    rows = read_sheet("업무참고", tenant_id, default_if_empty=[]) or []
    results = []
    for r in rows:
        if not _match(r, q):
            continue
        cols  = [k for k in r.keys() if k]
        title = str(r.get(cols[0], "")).strip() if cols else ""
        summary = " · ".join(
            str(r.get(c, "")).strip() for c in cols[1:3] if r.get(c)
        )
        results.append(SearchResult(
            id=title,
            type="reference",
            title=title or "업무참고",
            summary=summary,
            url="/reference",
        ))
    return results


def _search_memo(q: str, tenant_id: str) -> List[SearchResult]:
    """장기/중기 메모 검색 — tenant 격리"""
    results = []
    for sheet_name, label in [
        (MEMO_LONG_SHEET_NAME, "장기"),
        (MEMO_MID_SHEET_NAME,  "중기"),
    ]:
        try:
            content = read_memo(sheet_name, tenant_id) or ""
        except Exception:
            content = ""
        if not content or q.lower() not in content.lower():
            continue
        idx  = content.lower().find(q.lower())
        snip = content[max(0, idx - 20): idx + 60].replace("\n", " ")
        results.append(SearchResult(
            id=label,
            type="memo",
            title=f"{label} 메모",
            summary=snip,
            highlight=snip,
            url="/memos",
        ))
    return results


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1, description="검색 키워드"),
    type: str = Query("all", description="검색 범위: all|customer|task|board|reference|memo"),
    user: dict = Depends(get_current_user),
):
    """
    통합검색 — tenant_id 기반 완전 격리.
    타 tenant 데이터는 절대 검색되지 않음 (read_sheet가 tenant_id로 시트 키를 결정).
    """
    if type not in VALID_TYPES:
        type = "all"

    tenant_id = user.get("tenant_id") or user.get("sub", "")
    results: List[SearchResult] = []

    try:
        if type in ("all", "customer"):
            results += _search_customers(q, tenant_id)
        if type in ("all", "task"):
            results += _search_tasks(q, tenant_id)
        if type in ("all", "board"):
            results += _search_board(q, tenant_id)
        if type in ("all", "reference"):
            results += _search_reference(q, tenant_id)
        if type in ("all", "memo"):
            results += _search_memo(q, tenant_id)
    except Exception as e:
        print(f"[search] 검색 오류 (tenant={tenant_id}, q={q}): {e}\n{traceback.format_exc()}")

    return SearchResponse(query=q, type=type, total=len(results), results=results)
