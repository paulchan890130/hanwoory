"""출입국 실무지침 라우터
immigration_guidelines_db_v2.json 기반 정적 참조 데이터 API

주요 엔드포인트 (prefix: /api/guidelines):
  GET /stats                  - DB 통계
  GET /                       - MASTER_ROWS 목록 (필터+페이징)
  GET /search/query           - 키워드 검색
  GET /code/{code}            - 체류자격 코드별 전체 업무 조회
  GET /rules                  - 공통 규칙 목록
  GET /exceptions             - 예외 조건 목록
  GET /docs/lookup            - 서류명 표준화 조회
  GET /{row_id}               - 단건 상세 조회
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from backend.auth import get_current_user

router = APIRouter()

# ── 데이터 로딩 (모듈 임포트 시 1회) ──────────────────────────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DB_PATH = os.path.join(_BASE_DIR, "data", "immigration_guidelines_db_v2.json")

with open(_DB_PATH, encoding="utf-8") as _f:
    _DB = json.load(_f)

_MASTER_ROWS: List[dict] = _DB.get("master_rows", [])
_RULES: List[dict] = _DB.get("rules", [])
_EXCEPTIONS: List[dict] = _DB.get("exceptions", [])
_DOC_DICT: List[dict] = _DB.get("doc_dictionary", [])

# 검색용 인덱스 구축
_CODE_INDEX: dict = {}
for _row in _MASTER_ROWS:
    _code = _row.get("detailed_code", "")
    if _code:
        _CODE_INDEX.setdefault(_code, []).append(_row)

_SEARCH_INDEX: dict = {}  # keyword → [row_id, ...]
for _row in _MASTER_ROWS:
    for _sk in _row.get("search_keys", []):
        _kv = str(_sk.get("key_value", "")).lower()
        if _kv:
            _SEARCH_INDEX.setdefault(_kv, []).append(_row["row_id"])

_ROW_INDEX: dict = {r["row_id"]: r for r in _MASTER_ROWS}


# ── 유틸 ──────────────────────────────────────────────────────────
def _paginate(items: list, page: int, limit: int) -> dict:
    start = (page - 1) * limit
    end = start + limit
    return {
        "total": len(items),
        "page": page,
        "limit": limit,
        "pages": max(1, (len(items) + limit - 1) // limit),
        "data": items[start:end],
    }


# ══════════════════════════════════════════════════════════════════
# 엔드포인트
# ══════════════════════════════════════════════════════════════════

@router.get("/stats")
def get_stats(user: dict = Depends(get_current_user)):
    """데이터베이스 통계 조회"""
    return {
        "버전": _DB.get("버전", "2.0"),
        "갱신일": _DB.get("갱신일", ""),
        "통계": _DB.get("통계", {}),
    }


@router.get("/search/query")
def search_guidelines(
    q: str = Query(..., min_length=1, description="검색어 (코드/업무명/서류명 등)"),
    action_type: Optional[str] = Query(None, description="CHANGE|EXTEND|EXTRA_WORK|WORKPLACE|REGISTRATION|REENTRY|GRANT|VISA_CONFIRM|APPLICATION_CLAIM"),
    domain: Optional[str] = Query(None, description="체류민원|사증민원"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """
    키워드 검색 (체류자격 코드, 업무명, 서류명 등)
    예: ?q=F-4  /  ?q=시간제취업  /  ?q=사업자등록증
    """
    q_lower = q.lower().strip()
    matched_ids: set = set()

    # 1) SEARCH_KEYS 인덱스
    for kv, ids in _SEARCH_INDEX.items():
        if q_lower in kv:
            matched_ids.update(ids)

    # 2) MASTER_ROWS 풀텍스트 (코드/업무명/overview/서류)
    for row in _MASTER_ROWS:
        if (
            q_lower in str(row.get("detailed_code", "")).lower()
            or q_lower in str(row.get("business_name", "")).lower()
            or q_lower in str(row.get("overview_short", "")).lower()
            or q_lower in str(row.get("form_docs", "")).lower()
            or q_lower in str(row.get("supporting_docs", "")).lower()
        ):
            matched_ids.add(row["row_id"])

    items = [_ROW_INDEX[rid] for rid in matched_ids if rid in _ROW_INDEX]

    if action_type:
        items = [r for r in items if r.get("action_type") == action_type]
    if domain:
        items = [r for r in items if r.get("domain") == domain]

    items.sort(key=lambda r: str(r.get("detailed_code", "") or ""))
    return _paginate(items, page, limit)


@router.get("/code/{code}")
def get_by_code(code: str, user: dict = Depends(get_current_user)):
    """
    체류자격 코드로 관련 업무 전체 조회
    예: /code/F-4  →  F-4, F-4-1, F-4-2 ... 모두 반환
    """
    result = []
    q_parts = code.split("-")
    for row in _MASTER_ROWS:
        rc = str(row.get("detailed_code", ""))
        rc_parts = rc.split("-")
        if rc_parts[: len(q_parts)] == q_parts:
            result.append(row)
    if not result:
        raise HTTPException(status_code=404, detail=f"코드 '{code}' 에 해당하는 업무가 없습니다.")
    return {
        "code": code,
        "count": len(result),
        "action_types": list(set(r["action_type"] for r in result)),
        "data": result,
    }


@router.get("/rules")
def list_rules(
    rule_type: Optional[str] = Query(None, description="DocPolicy|ActionTemplate|FeeTemplate|FeeOverride|StatusTemplate|StatusActionOverride"),
    applies_to_major: Optional[str] = Query(None, description="업무대분류 (부분일치)"),
    status: str = Query("active", description="active|inactive|all"),
    user: dict = Depends(get_current_user),
):
    """공통 RULES 목록"""
    items = _RULES
    if status != "all":
        items = [r for r in items if r.get("status") == status]
    if rule_type:
        items = [r for r in items if r.get("rule_type") == rule_type]
    if applies_to_major:
        items = [r for r in items if applies_to_major in str(r.get("applies_to_major", ""))]
    return {"total": len(items), "data": items}


@router.get("/exceptions")
def list_exceptions(
    applies_to_major: Optional[str] = Query(None),
    applies_to_code: Optional[str] = Query(None),
    status: str = Query("active"),
    user: dict = Depends(get_current_user),
):
    """EXCEPTIONS 목록"""
    items = _EXCEPTIONS
    if status != "all":
        items = [e for e in items if e.get("status") == status]
    if applies_to_major:
        items = [e for e in items if applies_to_major in str(e.get("applies_to_major", ""))]
    if applies_to_code:
        items = [e for e in items if applies_to_code in str(e.get("applies_to_code_pattern", ""))]
    return {"total": len(items), "data": items}


@router.get("/docs/lookup")
def lookup_doc(
    name: str = Query(..., description="서류명 (부분일치)"),
    user: dict = Depends(get_current_user),
):
    """서류명 표준화 조회"""
    name_lower = name.lower()
    results = [
        d
        for d in _DOC_DICT
        if name_lower in str(d.get("standard_name", "")).lower()
        or name_lower in str(d.get("alias_1", "")).lower()
        or name_lower in str(d.get("alias_2", "")).lower()
        or name_lower in str(d.get("alias_3", "")).lower()
    ]
    return {"query": name, "total": len(results), "data": results}


@router.get("/")
def list_guidelines(
    action_type: Optional[str] = Query(None, description="CHANGE|EXTEND|EXTRA_WORK|WORKPLACE|REGISTRATION|REENTRY|GRANT|VISA_CONFIRM|APPLICATION_CLAIM"),
    domain: Optional[str] = Query(None, description="체류민원|사증민원"),
    major_action: Optional[str] = Query(None, description="업무대분류 (부분일치)"),
    status: str = Query("active", description="active|inactive|all"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """MASTER_ROWS 전체 목록 (필터 + 페이징)"""
    items = _MASTER_ROWS
    if status != "all":
        items = [r for r in items if r.get("status") == status]
    if action_type:
        items = [r for r in items if r.get("action_type") == action_type]
    if domain:
        items = [r for r in items if r.get("domain") == domain]
    if major_action:
        items = [r for r in items if major_action in str(r.get("major_action_std", ""))]
    return _paginate(items, page, limit)


@router.get("/{row_id}")
def get_guideline(row_id: str, user: dict = Depends(get_current_user)):
    """
    row_id 단건 조회 (예: M1-0001)
    연관 RULES, EXCEPTIONS 함께 반환
    """
    row = _ROW_INDEX.get(row_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"row_id '{row_id}' 를 찾을 수 없습니다.")

    code = row.get("detailed_code", "")
    major = row.get("major_action_std", "")

    def _rule_matches(rule: dict) -> bool:
        cp = str(rule.get("applies_to_code_pattern", ""))
        mp = str(rule.get("applies_to_major", ""))
        code_ok = cp == "*" or code in [c.strip() for c in cp.split("|")]
        major_ok = mp == "*" or major in mp
        return code_ok and major_ok

    def _exc_matches(exc: dict) -> bool:
        cp = str(exc.get("applies_to_code_pattern", ""))
        mp = str(exc.get("applies_to_major", ""))
        code_ok = cp == "*" or code in [c.strip() for c in cp.split("|")]
        major_ok = mp == "*" or major in mp
        return code_ok and major_ok

    return {
        **row,
        "related_rules": [r for r in _RULES if _rule_matches(r)],
        "related_exceptions": [e for e in _EXCEPTIONS if _exc_matches(e)],
    }
