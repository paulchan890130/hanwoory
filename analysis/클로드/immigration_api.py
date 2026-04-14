"""
출입국 실무지침 데이터베이스 - FastAPI 서버
immigration_guidelines_db_v2.json 기반

실행:
    pip install fastapi uvicorn
    uvicorn immigration_api:app --reload --port 8000

Node.js에서 호출:
    fetch('http://localhost:8000/api/v2/guidelines/code/F-4')
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import json, re, os

# ── 데이터 로딩 ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "immigration_guidelines_db_v2.json")

with open(DB_PATH, encoding="utf-8") as f:
    DB = json.load(f)

MASTER_ROWS: List[dict] = DB["master_rows"]
RULES: List[dict] = DB["rules"]
EXCEPTIONS: List[dict] = DB["exceptions"]
DOC_DICT: List[dict] = DB["doc_dictionary"]

# 검색용 인덱스 구축
CODE_INDEX: dict[str, List[dict]] = {}
for row in MASTER_ROWS:
    code = row.get("detailed_code", "")
    if code:
        CODE_INDEX.setdefault(code, []).append(row)

SEARCH_INDEX: dict[str, List[str]] = {}  # keyword → [row_id, ...]
for row in MASTER_ROWS:
    for sk in row.get("search_keys", []):
        kv = str(sk.get("key_value", "")).lower()
        if kv:
            SEARCH_INDEX.setdefault(kv, []).append(row["row_id"])

ROW_INDEX: dict[str, dict] = {r["row_id"]: r for r in MASTER_ROWS}

# ── 앱 초기화 ─────────────────────────────────────────────────
app = FastAPI(
    title="출입국 실무지침 DB API",
    description="출입국 업무관리 시스템 실무지침 데이터베이스 v2.0",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 개발용 - 운영 시 Node.js 서버 URL로 제한
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── 유틸 ─────────────────────────────────────────────────────
def paginate(items, page, limit):
    start = (page - 1) * limit
    end = start + limit
    return {
        "total": len(items),
        "page": page,
        "limit": limit,
        "pages": (len(items) + limit - 1) // limit,
        "data": items[start:end],
    }

# ── 엔드포인트 ────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "service": "출입국 실무지침 DB API",
        "version": "2.0.0",
        "master_rows": len(MASTER_ROWS),
        "docs_url": "/docs",
    }

@app.get("/api/v2/stats")
def stats():
    """데이터베이스 통계"""
    return DB["statistics"]

# ── MASTER_ROWS ────────────────────────────────────────────────

@app.get("/api/v2/guidelines")
def list_guidelines(
    action_type: Optional[str] = Query(None, description="CHANGE|EXTEND|EXTRA_WORK|WORKPLACE|REGISTRATION|REENTRY|GRANT|VISA_CONFIRM|APPLICATION_CLAIM"),
    domain: Optional[str] = Query(None, description="체류민원|사증민원"),
    major_action: Optional[str] = Query(None, description="업무대분류 (부분일치)"),
    status: str = Query("active", description="active|inactive|all"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """전체 MASTER_ROWS 목록 (필터+페이징)"""
    items = MASTER_ROWS
    if status != "all":
        items = [r for r in items if r.get("status") == status]
    if action_type:
        items = [r for r in items if r.get("action_type") == action_type]
    if domain:
        items = [r for r in items if r.get("domain") == domain]
    if major_action:
        items = [r for r in items if major_action in str(r.get("major_action_std", ""))]
    return paginate(items, page, limit)


@app.get("/api/v2/guidelines/{row_id}")
def get_guideline(row_id: str):
    """row_id로 단건 조회 (예: M1-0001)"""
    row = ROW_INDEX.get(row_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"row_id '{row_id}' 를 찾을 수 없습니다.")
    
    # 연관 RULES, EXCEPTIONS 같이 반환
    code = row.get("detailed_code", "")
    major = row.get("major_action_std", "")
    action = row.get("action_type", "")

    def rule_matches(rule):
        cp = str(rule.get("applies_to_code_pattern", ""))
        mp = str(rule.get("applies_to_major", ""))
        code_ok = cp == "*" or code in [c.strip() for c in cp.split("|")]
        major_ok = mp == "*" or major in mp
        return code_ok and major_ok

    def exc_matches(exc):
        cp = str(exc.get("applies_to_code_pattern", ""))
        mp = str(exc.get("applies_to_major", ""))
        code_ok = cp == "*" or code in [c.strip() for c in cp.split("|")]
        major_ok = mp == "*" or major in mp or mp == "*"
        return code_ok and major_ok

    related_rules = [r for r in RULES if rule_matches(r)]
    related_exceptions = [e for e in EXCEPTIONS if exc_matches(e)]

    return {
        **row,
        "related_rules": related_rules,
        "related_exceptions": related_exceptions,
    }


@app.get("/api/v2/guidelines/code/{code}")
def get_by_code(code: str):
    """체류자격 코드로 관련 업무 전체 조회 (예: F-4, E-7)"""
    # 정확히 일치 + 세부코드 포함 (예: F-4 → F-4, F-4-1, F-4-2...)
    result = []
    for row in MASTER_ROWS:
        rc = str(row.get("detailed_code", ""))
        rc_parts = rc.split("-")
        q_parts = code.split("-")
        if rc_parts[:len(q_parts)] == q_parts:
            result.append(row)
    if not result:
        raise HTTPException(status_code=404, detail=f"코드 '{code}' 에 해당하는 업무가 없습니다.")
    return {
        "code": code,
        "count": len(result),
        "action_types": list(set(r["action_type"] for r in result)),
        "data": result,
    }


@app.get("/api/v2/guidelines/search/query")
def search_guidelines(
    q: str = Query(..., min_length=1, description="검색어 (코드/업무명/서류명 등)"),
    action_type: Optional[str] = Query(None),
    domain: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    """
    키워드 검색
    - 체류자격 코드 (F-4, E-7-1 등)
    - 업무명 (시간제취업, 거소신고 등)
    - 서류명 (사업자등록증, 통합신청서 등)
    """
    q_lower = q.lower().strip()
    matched_ids = set()

    # 1) SEARCH_KEYS 정확 일치
    for kv, ids in SEARCH_INDEX.items():
        if q_lower in kv:
            matched_ids.update(ids)

    # 2) MASTER_ROWS 직접 풀텍스트 (코드/업무명/overview)
    for row in MASTER_ROWS:
        if (q_lower in str(row.get("detailed_code","")).lower()
            or q_lower in str(row.get("business_name","")).lower()
            or q_lower in str(row.get("overview_short","")).lower()
            or q_lower in str(row.get("form_docs","")).lower()
            or q_lower in str(row.get("supporting_docs","")).lower()):
            matched_ids.add(row["row_id"])

    items = [ROW_INDEX[rid] for rid in matched_ids if rid in ROW_INDEX]

    # 필터
    if action_type:
        items = [r for r in items if r.get("action_type") == action_type]
    if domain:
        items = [r for r in items if r.get("domain") == domain]

    # 정렬 (코드 순)
    items.sort(key=lambda r: str(r.get("detailed_code","") or ""))
    return paginate(items, page, limit)


# ── RULES / EXCEPTIONS ────────────────────────────────────────

@app.get("/api/v2/rules")
def list_rules(
    rule_type: Optional[str] = Query(None, description="DocPolicy|ActionTemplate|FeeTemplate|FeeOverride|StatusTemplate|StatusActionOverride"),
    applies_to_major: Optional[str] = Query(None),
    status: str = Query("active"),
):
    """공통 RULES 목록"""
    items = RULES
    if status != "all":
        items = [r for r in items if r.get("status") == status]
    if rule_type:
        items = [r for r in items if r.get("rule_type") == rule_type]
    if applies_to_major:
        items = [r for r in items if applies_to_major in str(r.get("applies_to_major",""))]
    return {"total": len(items), "data": items}


@app.get("/api/v2/exceptions")
def list_exceptions(
    applies_to_major: Optional[str] = Query(None),
    applies_to_code: Optional[str] = Query(None),
    status: str = Query("active"),
):
    """EXCEPTIONS 목록"""
    items = EXCEPTIONS
    if status != "all":
        items = [e for e in items if e.get("status") == status]
    if applies_to_major:
        items = [e for e in items if applies_to_major in str(e.get("applies_to_major",""))]
    if applies_to_code:
        items = [e for e in items
                 if applies_to_code in str(e.get("applies_to_code_pattern",""))]
    return {"total": len(items), "data": items}


# ── DOC_DICTIONARY ────────────────────────────────────────────

@app.get("/api/v2/docs/lookup")
def lookup_doc(name: str = Query(..., description="서류명 (부분일치)")):
    """서류명 표준화 조회"""
    name_lower = name.lower()
    results = [
        d for d in DOC_DICT
        if name_lower in str(d.get("standard_name","")).lower()
        or name_lower in str(d.get("alias_1","")).lower()
        or name_lower in str(d.get("alias_2","")).lower()
        or name_lower in str(d.get("alias_3","")).lower()
    ]
    return {"query": name, "total": len(results), "data": results}


