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
# 운영 DB 는 이미지 baked 경로 유지(절대 Persistent Disk 로 옮기지 않는다).
_DB_PATH = os.path.join(_BASE_DIR, "data", "immigration_guidelines_db_v2.json")
# 매뉴얼/스테이징 디렉토리만 MANUALS_DATA_DIR(기본=backend/data/manuals)로 분리.
# 운영 PDF 뷰어·staging 검토·매뉴얼 PDF 가 모두 이 경로를 읽는다.
try:
    from config import MANUALS_DATA_DIR as _MANUALS_DIR
except Exception:
    _MANUALS_DIR = os.path.join(_BASE_DIR, "data", "manuals")

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
        "data": [_clean_row_display(r) if isinstance(r, dict) else r for r in items[start:end]],
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
        "data": [_clean_row_display(r) for r in result],
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

# ── 사용자 노출 텍스트에서 '편람' 제거 ────────────────────────────────────────
def _strip_pyolam(text: str) -> str:
    """API 응답 전, 사용자에게 보이는 필드에서 '편람' 단어를 제거한다.
    JSON 원본은 건드리지 않음 — 응답 dict 복사본에만 적용."""
    if not text or "편람" not in text:
        return text
    t = text
    t = _re.sub(r"\d{6}\s+체류관리편람\s+", "", t)         # "221230 체류관리편람 섹션명"
    t = _re.sub(r"\d{4}\s+편람\s+기준\s*", "", t)           # "2022 편람 기준"
    t = _re.sub(r"\d{4}\s+편람상\s*", "", t)                # "2022 편람상"
    t = _re.sub(r"\(편람\s+기준\)", "", t)                   # "(편람 기준)"
    # "편람 p.숫자[조사] 명시" — 조사 최대 4글자, 명시가 바로 다음에 올 때만
    t = _re.sub(r"편람\s+p\.\d+[가-힣]{0,4}\s+명시\s*", "", t)
    # "편람 p.숫자[짧은조사]" — 조사 최대 3글자 (에, 에서, 에는 등)
    t = _re.sub(r"편람\s+p\.\d+[가-힣]{0,3}\s*", "", t)
    t = _re.sub(r"편람에\s+따르면\s*", "", t)                # "편람에 따르면"
    t = _re.sub(r"편람에\s+명시된?\s*", "", t)               # "편람에 명시된 / 명시"
    t = _re.sub(r"편람상\s*", "", t)                         # "편람상"
    t = _re.sub(r"편람의?\s*", "", t)                        # "편람의 / 편람" (catch-all)
    t = _re.sub(r"\(\s*\)", "", t)                           # 빈 괄호 정리
    t = _re.sub(r"\s+\.", ".", t)                            # " ." → "."
    t = _re.sub(r"  +", " ", t)                             # 다중 공백 정리
    return t.strip()


_DISPLAY_CLEAN_FIELDS = ("basis_section", "practical_notes", "exceptions_summary")


def _clean_row_display(row: dict) -> dict:
    """편람 포함 필드가 있는 row만 shallow-copy 후 정제해 반환."""
    if not any("편람" in str(row.get(f, "")) for f in _DISPLAY_CLEAN_FIELDS):
        return row
    out = dict(row)
    for f in _DISPLAY_CLEAN_FIELDS:
        if out.get(f):
            out[f] = _strip_pyolam(str(out[f]))
    return out

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

    path = os.path.join(_MANUALS_DIR, _MANUAL_FILES[manual])
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


_STAGING_LABEL_MAP = {
    "residence": "체류민원",
    "visa": "사증민원",
    "revision_history": "수정이력",
}


@router.get("/manual-pdf-staging/{version}/{label}/download")
def serve_manual_pdf_staging(
    version: str,
    label: str,
    user: dict = Depends(require_admin),
):
    """Staged rhwp PDF 다운로드 (admin only).

    경로: ``backend/data/manuals/staging/{version}/rhwp_pdf/rhwp_{version}_{label}.pdf``
    label: residence / visa / revision_history

    운영 PDF 뷰어 (``/manual-pdf/{manual}``) 와 분리된 경로. 본 엔드포인트는 신규
    rhwp 파이프라인이 만든 staging PDF 의 admin 다운로드 전용. 운영 뷰어 / 운영
    PDF 파일은 무수정.
    """
    if label not in _STAGING_LABEL_MAP:
        raise HTTPException(status_code=400, detail=f"unknown label '{label}'. Use one of {list(_STAGING_LABEL_MAP)}")
    # version sanity — prevent path traversal
    if not version.replace('_', '').replace('-', '').isalnum():
        raise HTTPException(status_code=400, detail=f"invalid version: {version!r}")
    base = os.path.join(_MANUALS_DIR, "staging", version, "rhwp_pdf")
    path = os.path.join(base, f"rhwp_{version}_{label}.pdf")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"staging PDF not found: {path}")
    from urllib.parse import quote
    ascii_name = f"rhwp_{version}_{label}.pdf"
    kr = _STAGING_LABEL_MAP[label]
    utf8_name = quote(f"rhwp_{version}_{kr}.pdf", safe="")
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            # staging — no long cache, no public sharing
            "Cache-Control": "no-store",
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}",
            "X-Staging-Version": version,
        },
    )


@router.get("/manual-pdf-staging/{version}/manifest")
def get_manual_pdf_staging_manifest(
    version: str,
    user: dict = Depends(require_admin),
):
    """staging 버전의 manifest.json 반환. 운영 영향 없음."""
    if not version.replace('_', '').replace('-', '').isalnum():
        raise HTTPException(status_code=400, detail=f"invalid version: {version!r}")
    path = os.path.join(_MANUALS_DIR, "staging", version, "manifest.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"manifest not found: {path}")
    with open(path, encoding="utf-8") as f:
        import json as _json
        return _json.load(f)


# ── Manual Update v1 — staging review endpoints (admin only) ─────────────────
# 운영 PDF 뷰어(/manual-pdf/{manual})·운영 PDF 파일과 완전히 분리.
# 본 엔드포인트들은 rhwp 파이프라인이 backend/data/manuals/staging/{version}/ 에
# 만든 검토용 staging 산출물만 노출한다. 운영 데이터는 절대 건드리지 않는다.

def _safe_version(version: str) -> str:
    """버전 경로 검증 — path traversal 차단. alnum + _ + - 만 허용."""
    if not version or not version.replace('_', '').replace('-', '').isalnum():
        raise HTTPException(status_code=400, detail=f"invalid version: {version!r}")
    return version


def _staging_dir(version: str):
    return os.path.join(_MANUALS_DIR, "staging", _safe_version(version))


def _read_staging_json(version: str, *rel_parts: str):
    """staging/{version}/<rel_parts> JSON 읽기. 없으면 404, 손상 시 500."""
    base = _staging_dir(version)
    path = os.path.normpath(os.path.join(base, *rel_parts))
    # normpath 후에도 staging dir 밖이면 거부 (이중 방어)
    if os.path.commonpath([os.path.abspath(path), os.path.abspath(base)]) != os.path.abspath(base):
        raise HTTPException(status_code=400, detail="invalid path")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"not found: {os.path.basename(path)}")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"read failed: {e}")


_NOSTORE = {"Cache-Control": "no-store"}


@router.get("/manual-staging/versions")
def list_manual_staging_versions(user: dict = Depends(require_admin)):
    """staging/ 아래 사용 가능한 버전 목록 (manifest.json 보유 버전만)."""
    root = os.path.join(_MANUALS_DIR, "staging")
    out = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if os.path.isdir(d) and os.path.isfile(os.path.join(d, "manifest.json")):
                out.append(name)
    from fastapi.responses import JSONResponse
    return JSONResponse({"versions": out}, headers=_NOSTORE)


@router.get("/manual-staging/{version}/manifest")
def get_manual_staging_manifest(version: str, user: dict = Depends(require_admin)):
    """staging 버전 manifest.json (pdf_mode/changed_page_count/candidate_count 포함)."""
    from fastapi.responses import JSONResponse
    return JSONResponse(_read_staging_json(version, "manifest.json"), headers=_NOSTORE)


@router.get("/manual-staging/{version}/changed-pages")
def get_manual_staging_changed_pages(version: str, user: dict = Depends(require_admin)):
    """변경 페이지 목록 (non-same: modified/moved/added/deleted)."""
    from fastapi.responses import JSONResponse
    data = _read_staging_json(version, "diff", "changed_pages.json")
    return JSONResponse({"version": version, "count": len(data), "rows": data}, headers=_NOSTORE)


@router.get("/manual-staging/{version}/candidates")
def get_manual_staging_candidates(version: str, user: dict = Depends(require_admin)):
    """영향 받은 manual_ref 후보 목록 (변경 페이지에 연결된 항목만)."""
    from fastapi.responses import JSONResponse
    data = _read_staging_json(version, "candidates", "manual_ref_update_candidates.json")
    return JSONResponse({"version": version, "count": len(data), "rows": data}, headers=_NOSTORE)


@router.get("/manual-staging/{version}/{label}/review-page/{page_no}/pdf")
def get_manual_staging_review_page_pdf(
    version: str,
    label: str,
    page_no: int,
    token: Optional[str] = Query(None, description="JWT (iframe 인증용 query token)"),
    authorization: Optional[str] = Header(None),
):
    """변경 페이지 검토용 PDF 1장 서빙.

    경로: staging/{version}/review_pdf_pages/{label}/p####.pdf
    iframe 임베드 지원을 위해 query token 또는 Authorization 헤더 허용 — 단,
    반드시 admin 토큰이어야 한다. 운영 PDF 뷰어와 분리된 검토 전용 경로.
    """
    payload = _verify_token_flexible(token, authorization)
    if not payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    if label not in _STAGING_LABEL_MAP:
        raise HTTPException(status_code=400, detail=f"unknown label '{label}'. Use one of {list(_STAGING_LABEL_MAP)}")
    if page_no < 1 or page_no > 99999:
        raise HTTPException(status_code=400, detail=f"invalid page_no: {page_no}")
    base = _staging_dir(version)
    path = os.path.normpath(os.path.join(base, "review_pdf_pages", label, f"p{page_no:04d}.pdf"))
    if os.path.commonpath([os.path.abspath(path), os.path.abspath(base)]) != os.path.abspath(base):
        raise HTTPException(status_code=400, detail="invalid path")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"review page PDF not found: {label} p.{page_no}")
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'inline; filename="review_{label}_p{page_no:04d}.pdf"',
            "X-Staging-Version": version,
        },
    )


@router.get("/manual-auto-update/state")
def get_manual_auto_update_state(user: dict = Depends(require_admin)):
    """rhwp 자동 staging 상태 조회 (admin).

    manual_auto_update_state.json 을 그대로 노출한다 + 사용 가능한 staging 버전 목록.
    needs_review=True 면 admin UI 가 '새 매뉴얼 검토 필요' 배너를 띄울 수 있다.
    이 엔드포인트는 어떤 자동 반영도 트리거하지 않는다 — 읽기 전용 상태 보고일 뿐."""
    from fastapi.responses import JSONResponse
    path = os.path.join(_MANUALS_DIR, "manual_auto_update_state.json")
    state = {"status": "never_run", "needs_review": False}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            state = {"status": "error", "error": f"state read failed: {e}"}
    # 검토 대상 staging 버전 목록(없으면 빈 리스트)
    versions = []
    root = os.path.join(_MANUALS_DIR, "staging")
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            if os.path.isfile(os.path.join(root, name, "manifest.json")):
                versions.append(name)
    return JSONResponse({"state": state, "staging_versions": versions}, headers=_NOSTORE)


# ── Manual Update v1 — PG single-source endpoints (admin) ────────────────────
# FEATURE_PG_MANUAL_UPDATE=true → PostgreSQL 조회. false → 기존 파일 기반 fallback.
# admin 기본 화면은 active current + 이번 orphaned 1회만(archive·구세대 제외).

def _pg_manual_enabled() -> bool:
    try:
        from backend.db.feature_flags import pg_manual_update_enabled
        from backend.db.session import is_configured
        return is_configured() and pg_manual_update_enabled()
    except Exception:
        return False


@router.get("/manual-update/state")
def get_manual_update_state_v2(user: dict = Depends(require_admin)):
    """자동화 상태. PG on → manual_update_state, off → manual_auto_update_state.json."""
    from fastapi.responses import JSONResponse
    if _pg_manual_enabled():
        from backend.services import manual_update_pg_service as svc
        return JSONResponse(
            {"source": "pg", "state": svc.get_state_dict(),
             "baseline": svc.get_baseline_summary()},
            headers=_NOSTORE,
        )
    # 파일 fallback
    path = os.path.join(_MANUALS_DIR, "manual_auto_update_state.json")
    state = {"status": "never_run", "needs_review": False}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
        except Exception as e:
            state = {"status": "error", "error": f"state read failed: {e}"}
    return JSONResponse({"source": "file", "state": state}, headers=_NOSTORE)


@router.get("/manual-update/versions")
def list_manual_update_versions_v2(user: dict = Depends(require_admin)):
    """감지된 업데이트 버전 목록."""
    from fastapi.responses import JSONResponse
    if _pg_manual_enabled():
        from backend.services import manual_update_pg_service as svc
        return JSONResponse({"source": "pg", "versions": svc.list_versions()}, headers=_NOSTORE)
    # 파일 fallback: staging/ 하위 manifest 보유 버전
    out = []
    root = os.path.join(_MANUALS_DIR, "staging")
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            if os.path.isfile(os.path.join(root, name, "manifest.json")):
                out.append({"version": name})
    return JSONResponse({"source": "file", "versions": out}, headers=_NOSTORE)


@router.get("/manual-update/versions/{version}/changed-pages")
def get_manual_update_changed_pages_v2(version: str, user: dict = Depends(require_admin)):
    """버전별 변경 페이지."""
    from fastapi.responses import JSONResponse
    if _pg_manual_enabled():
        from backend.services import manual_update_pg_service as svc
        rows = svc.get_changed_pages(version)
        return JSONResponse({"source": "pg", "version": version, "count": len(rows),
                             "rows": rows}, headers=_NOSTORE)
    data = _read_staging_json(version, "diff", "changed_pages.json")
    return JSONResponse({"source": "file", "version": version, "count": len(data),
                         "rows": data}, headers=_NOSTORE)


@router.get("/manual-update/versions/{version}/candidates")
def get_manual_update_candidates_v2(version: str, user: dict = Depends(require_admin)):
    """버전별 영향 manual_ref 후보."""
    from fastapi.responses import JSONResponse
    if _pg_manual_enabled():
        from backend.services import manual_update_pg_service as svc
        rows = svc.get_candidates(version)
        return JSONResponse({"source": "pg", "version": version, "count": len(rows),
                             "rows": rows}, headers=_NOSTORE)
    data = _read_staging_json(version, "candidates", "manual_ref_update_candidates.json")
    return JSONResponse({"source": "file", "version": version, "count": len(data),
                         "rows": data}, headers=_NOSTORE)


@router.get("/manual-update/decisions/active")
def get_manual_update_active_decisions_v2(user: dict = Depends(require_admin)):
    """admin 기본 검토 화면용 active decision(현재 + 이번 orphaned 1회). archive 제외."""
    from fastapi.responses import JSONResponse
    if _pg_manual_enabled():
        from backend.services import manual_update_pg_service as svc
        rows = svc.get_active_decisions()
        return JSONResponse({"source": "pg", "count": len(rows), "rows": rows},
                            headers=_NOSTORE)
    # 파일 fallback: manual_review_decisions.json (Phase 0 구조)
    path = os.path.join(_MANUALS_DIR, "manual_review_decisions.json")
    rows = []
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            decisions = (data.get("decisions") or {}) if isinstance(data, dict) else {}
            # 파일 fallback 은 version 정보가 약해 비-2세대 orphaned 까지 단순 노출
            for rid, d in decisions.items():
                if isinstance(d, dict):
                    rows.append({"row_id": rid, **d})
        except Exception as e:
            return JSONResponse({"source": "file", "error": f"read failed: {e}",
                                 "rows": []}, headers=_NOSTORE)
    return JSONResponse({"source": "file", "count": len(rows), "rows": rows},
                        headers=_NOSTORE)


@router.get("/manual-pdf-info")
def get_manual_pdf_info(user: dict = Depends(get_current_user)):
    """프론트가 사용 가능한 매뉴얼 목록 + 메타 정보 조회."""
    info = {}
    for label, fname in _MANUAL_FILES.items():
        path = os.path.join(_MANUALS_DIR, fname)
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
        **_clean_row_display(dict(row)),
        "related_rules": [r for r in _RULES if _rule_matches(r)],
        "related_exceptions": [e for e in _EXCEPTIONS if _exc_matches(e)],
    }
