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
  GET /tree/entry-points      - 상담 진입점 목록
  GET /tree/results           - quickdoc 파라미터로 해당 업무 rows 조회
  POST /tb/evaluate           - 결핵 검사 필요 여부 평가
  GET /{row_id}               - 단건 상세 조회
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import json
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from backend.auth import get_current_user, require_admin

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


# ══════════════════════════════════════════════════════════════════
# 트리·TB 데이터 (/{row_id} 보다 먼저 정의 — 경로 충돌 방지)
# ══════════════════════════════════════════════════════════════════

_ENTRY_POINTS_DATA = [
    {"id": "F5",   "label": "영주 (F-5)",        "subtitle": "영주자격 변경",       "codes": "F-5",       "color": "#48BB78", "search_query": "F-5",        "action_types": ["CHANGE"]},
    {"id": "F4",   "label": "재외동포 (F-4)",    "subtitle": "체류자격 변경·연장",  "codes": "F-4",       "color": "#4299E1", "search_query": "F-4",        "action_types": ["CHANGE","EXTEND","REGISTRATION"]},
    {"id": "E7",   "label": "특정활동 (E-7)",    "subtitle": "변경·연장·부여",      "codes": "E-7",       "color": "#9F7AEA", "search_query": "E-7",        "action_types": ["CHANGE","EXTEND","GRANT"]},
    {"id": "D2",   "label": "유학 (D-2)",        "subtitle": "등록·변경·연장",      "codes": "D-2",       "color": "#667EEA", "search_query": "D-2",        "action_types": ["CHANGE","EXTEND","REGISTRATION","EXTRA_WORK"]},
    {"id": "H2",   "label": "방문취업 (H-2)",    "subtitle": "등록·연장·변경",      "codes": "H-2",       "color": "#ED8936", "search_query": "H-2",        "action_types": ["CHANGE","EXTEND","REGISTRATION"]},
    {"id": "F6",   "label": "결혼이민 (F-6)",    "subtitle": "변경·연장·부여",      "codes": "F-6",       "color": "#FC8181", "search_query": "F-6",        "action_types": ["CHANGE","EXTEND","GRANT"]},
    {"id": "REG",  "label": "외국인 등록",        "subtitle": "최초 등록 절차",      "codes": "등록",       "color": "#38B2AC", "search_query": "외국인등록",  "action_types": ["REGISTRATION"]},
    {"id": "REEN", "label": "재입국 허가",        "subtitle": "단수·복수 재입국",    "codes": "재입국",     "color": "#F6AD55", "search_query": "재입국허가",  "action_types": ["REENTRY"]},
    {"id": "EX",   "label": "체류자격 외 활동",  "subtitle": "시간제취업·기타",     "codes": "자격외활동", "color": "#ED8936", "search_query": "시간제취업",  "action_types": ["EXTRA_WORK"]},
    {"id": "WP",   "label": "근무처 변경·추가",  "subtitle": "취업자격 근무처",     "codes": "근무처",     "color": "#9F7AEA", "search_query": "근무처변경",  "action_types": ["WORKPLACE"]},
    {"id": "GR",   "label": "체류자격 부여",     "subtitle": "출생·귀화 후 부여",   "codes": "부여",       "color": "#FC8181", "search_query": "체류자격부여","action_types": ["GRANT"]},
    {"id": "VC",   "label": "사증발급인정서",    "subtitle": "국내 초청 사증",       "codes": "사증",       "color": "#667EEA", "search_query": "사증발급인정","action_types": ["VISA_CONFIRM"]},
    {"id": "DR",   "label": "거소신고",          "subtitle": "재외동포 거소",        "codes": "거소",       "color": "#68D391", "search_query": "거소신고",    "action_types": ["DOMESTIC_RESIDENCE_REPORT"]},
    {"id": "AC",   "label": "직접신청",          "subtitle": "체류지·신고 등",       "codes": "신고",       "color": "#A0AEC0", "search_query": "직접신청",    "action_types": ["APPLICATION_CLAIM"]},
]

_TB_HIGH_RISK_ISO3 = {
    "KHM","CHN","IND","IDN","LAO","MNG","MMR","NPL","PAK","PHL","PNG","PRK","VNM","BGD","BTN","TLS",
    "AGO","CAF","COD","COG","ETH","GAB","GNB","LSO","LBR","MDG","MWI","MLI","MOZ","NAM","NER","NGA",
    "SOM","ZAF","SSD","SDN","SWZ","TZA","UGA","ZMB","ZWE","CMR","TCD","GIN","CIV","BFA","SLE","TGO",
    "AZE","BLR","GEO","KAZ","KGZ","MDA","RUS","TJK","TKM","UKR","UZB","ARM",
    "BOL","ECU","GTM","GUY","HTI","HND","PER",
}

_TB_EXEMPT_PREFIXES = ["A-", "B-", "C-"]
_TB_STAGE_MAP = {
    "REGISTRATION": "registration",
    "CHANGE":       "stay_permission",
    "EXTEND":       "stay_permission",
    "GRANT":        "stay_permission",
}


class TbEvaluateRequest(BaseModel):
    nationality_iso3: str
    action_type: str
    detailed_code: str = ""
    age: Optional[int] = None


import re as _re
_CODE_PATTERN = _re.compile(r'^[A-Z]-[0-9A-Z]', _re.I)

@router.get("/tree/entry-points")
def get_entry_points(user: dict = Depends(get_current_user)):
    """상담 진입점 목록 + 각 진입점별 업무 건수"""
    result = []
    for ep in _ENTRY_POINTS_DATA:
        q = ep["search_query"].lower()
        at_filter = ep.get("action_types", [])
        if _CODE_PATTERN.match(ep["search_query"]):
            # 코드 기반: detailed_code 접두사 매칭
            count = sum(
                1 for row in _MASTER_ROWS
                if str(row.get("detailed_code", "")).lower().startswith(q)
            )
        else:
            # 업무 기반: action_type만으로 집계
            count = sum(
                1 for row in _MASTER_ROWS
                if not at_filter or row.get("action_type", "") in at_filter
            )
        result.append({**ep, "count": count})
    return {"total": len(result), "data": result}


@router.get("/tree/results")
def get_tree_results(
    category: Optional[str]    = Query(None),
    minwon: Optional[str]      = Query(None),
    kind: Optional[str]        = Query(None),
    detail: Optional[str]      = Query(None),
    action_type: Optional[str] = Query(None),
    search_query: Optional[str]= Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """quickdoc 파라미터 기준으로 실무지침 rows 반환 (딥링크 연결용)"""
    items = list(_MASTER_ROWS)
    if category:
        items = [r for r in items if r.get("quickdoc_category") == category]
    if minwon:
        items = [r for r in items if r.get("quickdoc_minwon") == minwon]
    if kind:
        items = [r for r in items if r.get("quickdoc_kind") == kind]
    if detail:
        items = [r for r in items if r.get("quickdoc_detail") == detail]
    if action_type:
        items = [r for r in items if r.get("action_type") == action_type]
    if search_query:
        q = search_query.lower()
        items = [r for r in items
                 if q in str(r.get("detailed_code","")).lower()
                 or q in str(r.get("business_name","")).lower()]
    items.sort(key=lambda r: str(r.get("detailed_code","") or ""))
    return _paginate(items, page, limit)


@router.post("/tb/evaluate")
def evaluate_tb(req: TbEvaluateRequest, user: dict = Depends(get_current_user)):
    """
    결핵 검사 필요 여부 평가.
    TB-001: 외국인등록 단계 / TB-002: 체류허가(변경·연장·부여) 단계
    """
    iso3  = req.nationality_iso3.upper().strip()
    at    = req.action_type.upper().strip()
    code  = req.detailed_code.strip()

    is_high_risk  = iso3 in _TB_HIGH_RISK_ISO3
    is_exempt     = any(code.startswith(p) for p in _TB_EXEMPT_PREFIXES)
    stage         = _TB_STAGE_MAP.get(at)

    if not is_high_risk:
        return {"required": False, "stage": None,
                "reason": f"{iso3}은(는) 결핵 고위험국이 아닙니다.",
                "is_high_risk_country": False, "rule_id": None}

    if is_exempt:
        return {"required": False, "stage": None,
                "reason": f"{code} 체류자격은 결핵 검사 면제 대상입니다.",
                "is_high_risk_country": True, "rule_id": None}

    if stage == "registration":
        return {"required": True, "stage": "registration",
                "reason": f"{iso3} 국적자는 외국인등록 신청 시 결핵 검사 증명서를 제출해야 합니다.",
                "is_high_risk_country": True, "rule_id": "TB-001",
                "instruction": "외국인등록 신청 전 보건소 또는 지정 의료기관에서 결핵 검사를 받고 검진 결과서를 제출하세요."}

    if stage == "stay_permission":
        return {"required": True, "stage": "stay_permission",
                "reason": f"{iso3} 국적자는 체류허가 신청 시 결핵 검사 증명서를 제출해야 합니다.",
                "is_high_risk_country": True, "rule_id": "TB-002",
                "instruction": "체류허가 신청 전 보건소 또는 지정 의료기관에서 결핵 검사를 받고 검진 결과서를 제출하세요."}

    return {"required": False, "stage": None,
            "reason": f"{at} 업무는 결핵 검사 의무 단계가 아닙니다 (고위험국 참고).",
            "is_high_risk_country": True, "rule_id": None}


@router.get("/tb/high-risk-countries")
def get_tb_countries(user: dict = Depends(get_current_user)):
    """결핵 고위험국 ISO3 목록"""
    return {"total": len(_TB_HIGH_RISK_ISO3), "countries": sorted(_TB_HIGH_RISK_ISO3)}


# ── 매뉴얼 PDF 서빙 ──────────────────────────────────────────────────────
from fastapi.responses import FileResponse
from fastapi import Header
from backend.auth import decode_token

_MANUAL_FILES = {
    "체류민원": "unlocked_체류민원.pdf",
    "사증민원": "unlocked_사증민원.pdf",
}


def _verify_token_flexible(token: Optional[str], authorization: Optional[str]) -> dict:
    """query token 또는 Authorization header 둘 다 허용 (iframe에서 인증 가능)."""
    actual = token
    if not actual and authorization:
        if authorization.startswith("Bearer "):
            actual = authorization[7:]
    if not actual:
        raise HTTPException(status_code=401, detail="인증 토큰 필요")
    payload = decode_token(actual)
    if not payload.get("sub"):
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰")
    return payload


@router.get("/manual-pdf/{manual}")
def serve_manual_pdf(
    manual: str,
    token: Optional[str] = Query(None, description="JWT (iframe 인증용 query token)"),
    authorization: Optional[str] = Header(None),
):
    """매뉴얼 PDF 직접 서빙 — iframe 임베드용.

    - 매뉴얼 이름: 체류민원 / 사증민원
    - 페이지 지정은 클라이언트 fragment(#page=N)로 — PDF.js/브라우저 내장 뷰어가 처리
    - 인증: Authorization 헤더 또는 ?token= 쿼리 (iframe은 헤더 못 보내므로 query 지원)
    """
    _verify_token_flexible(token, authorization)

    if manual not in _MANUAL_FILES:
        raise HTTPException(status_code=404, detail=f"매뉴얼 '{manual}' 없음. 사용 가능: {list(_MANUAL_FILES)}")

    path = os.path.join(_BASE_DIR, "data", "manuals", _MANUAL_FILES[manual])
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"PDF 파일 없음: {_MANUAL_FILES[manual]}")

    # 한글 파일명은 latin-1 헤더에 직접 못 넣음 → RFC 5987 형식 + ASCII fallback
    from urllib.parse import quote
    ascii_name = {"체류민원": "stay_manual.pdf", "사증민원": "visa_manual.pdf"}.get(manual, "manual.pdf")
    utf8_name  = quote(f"{manual}.pdf", safe="")
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Disposition": f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}",
        },
    )


@router.get("/manual-pdf-info")
def get_manual_pdf_info(user: dict = Depends(get_current_user)):
    """프론트가 사용 가능한 매뉴얼 목록 + 메타 정보 조회."""
    info = {}
    for label, fname in _MANUAL_FILES.items():
        path = os.path.join(_BASE_DIR, "data", "manuals", fname)
        info[label] = {
            "available": os.path.isfile(path),
            "filename":  fname,
            "size":      os.path.getsize(path) if os.path.isfile(path) else 0,
        }
    return info


@router.get("")
@router.get("/")
def list_guidelines(
    action_type: Optional[str] = Query(None, description="CHANGE|EXTEND|EXTRA_WORK|WORKPLACE|REGISTRATION|REENTRY|GRANT|VISA_CONFIRM|APPLICATION_CLAIM"),
    domain: Optional[str] = Query(None, description="체류민원|사증민원"),
    major_action: Optional[str] = Query(None, description="업무대분류 (부분일치)"),
    status: str = Query("active", description="active|inactive|all"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=500),
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


_EDITABLE_FIELDS = {"form_docs", "supporting_docs", "fee_rule", "practical_notes"}


class GuidelineFieldPatch(BaseModel):
    field: str
    value: str


@router.patch("/{row_id}")
def patch_guideline_field(
    row_id: str,
    body: GuidelineFieldPatch,
    admin: dict = Depends(require_admin),
):
    """관리자 전용: 실무지침 단일 필드 수정 (form_docs/supporting_docs/fee_rule/practical_notes만 허용)."""
    if body.field not in _EDITABLE_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"수정 불가 필드: '{body.field}'. 허용 필드: {sorted(_EDITABLE_FIELDS)}",
        )
    row = _ROW_INDEX.get(row_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"row_id '{row_id}' 를 찾을 수 없습니다.")

    # 메모리 인덱스 업데이트
    row[body.field] = body.value

    # JSON 파일 영구 저장
    try:
        with open(_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(_DB, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"파일 저장 실패: {e}")

    return {"row_id": row_id, "field": body.field, "value": body.value, "ok": True}


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
