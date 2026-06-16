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
        rows = svc.get_candidates_enriched(version)  # + change_kind/needs_review/similarity/changed_detail
        return JSONResponse({"source": "pg", "version": version, "count": len(rows),
                             "rows": rows}, headers=_NOSTORE)
    data = _read_staging_json(version, "candidates", "manual_ref_update_candidates.json")
    return JSONResponse({"source": "file", "version": version, "count": len(data),
                         "rows": data}, headers=_NOSTORE)


@router.get("/manual-update/versions/{version}/candidates/{row_id}/detail")
def get_manual_update_candidate_detail(version: str, row_id: str, user: dict = Depends(require_admin)):
    """후보 1건 상세 비교(기존 baseline 전체 텍스트 + 후보 스니펫 + 변경 페이지 + 본문 diff)."""
    from fastapi.responses import JSONResponse
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성(FEATURE_PG_MANUAL_UPDATE off)")
    from backend.services import manual_update_pg_service as svc
    d = svc.candidate_detail(version, row_id)
    if d is None:
        raise HTTPException(status_code=404, detail=f"후보 '{row_id}' 없음(version={version})")
    # 본문 diff: 변경 페이지별 baseline_snippet vs new_snippet 을 difflib 로 비교.
    import difflib
    for cp in d.get("changed_pages", []):
        a = (cp.get("baseline_snippet") or "")
        b = (cp.get("new_snippet") or "")
        sm = difflib.SequenceMatcher(None, a, b)
        segs = []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                segs.append({"op": "equal", "text": a[i1:i2]})
            elif op == "delete":
                segs.append({"op": "delete", "text": a[i1:i2]})
            elif op == "insert":
                segs.append({"op": "insert", "text": b[j1:j2]})
            else:  # replace
                segs.append({"op": "delete", "text": a[i1:i2]})
                segs.append({"op": "insert", "text": b[j1:j2]})
        cp["diff_segments"] = segs
        cp["has_text_change"] = any(s["op"] != "equal" and s["text"].strip() for s in segs)
    return JSONResponse(d, headers=_NOSTORE)


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


# ── PG manual-update 검토 결정 / 운영 반영 (admin 전용) ───────────────────────
# 결정 저장(POST decision/bulk)은 운영 manual_ref(JSON)를 절대 수정하지 않는다.
# 운영 반영은 오직 명시적 /apply 액션으로만 수행되며, 승인/직접입력 상태에서만 허용한다.
_PG_DECISION_UI_MAP = {
    "approve": "REVIEWED_APPROVE_CANDIDATE",     # 승인(후보 채택)
    "keep_existing": "REVIEWED_KEEP_EXISTING",   # 기존 유지
    "hold": "UNRESOLVED",                        # 보류(미결)
    "reject": "REJECTED_BAD_CANDIDATE",          # 제외(후보 기각)
    "manual_page": "NEEDS_MANUAL_PAGE",          # 직접 페이지 입력
}
_PG_VALID_DECISIONS = set(_PG_DECISION_UI_MAP.values()) | {"NEW_CANDIDATE"}
_PG_APPLYABLE = {"REVIEWED_APPROVE_CANDIDATE", "NEEDS_MANUAL_PAGE"}


def _pg_map_decision(d: str) -> str:
    return _PG_DECISION_UI_MAP.get(d, d)


def _pg_candidate_page(row_id: str) -> Optional[int]:
    """최신 staging 버전 후보에서 row_id 의 candidate_page_from 조회(승인 시 페이지 산출용)."""
    from backend.services import manual_update_pg_service as svc
    latest = svc.get_state_dict().get("last_staging_version")
    if not latest:
        return None
    for c in svc.get_candidates(latest):
        if c.get("row_id") == row_id:
            return c.get("candidate_page_from")
    return None


class PgDecisionBody(BaseModel):
    decision: str  # approve|keep_existing|hold|reject|manual_page (또는 raw vocabulary)
    candidate_page_from: Optional[int] = None
    candidate_page_to: Optional[int] = None
    note: Optional[str] = None


@router.post("/manual-update/decisions/{row_id}")
def pg_set_decision(row_id: str, body: PgDecisionBody, admin: dict = Depends(require_admin)):
    """검토 결정을 PG decision 행에 저장(운영 manual_ref 미반영)."""
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성(FEATURE_PG_MANUAL_UPDATE off)")
    mapped = _pg_map_decision(body.decision)
    if mapped not in _PG_VALID_DECISIONS:
        raise HTTPException(status_code=400, detail=f"허용되지 않은 decision: {body.decision}")
    from backend.services import manual_update_pg_service as svc
    page = body.candidate_page_from
    if mapped == "REVIEWED_APPROVE_CANDIDATE" and page is None:
        page = _pg_candidate_page(row_id)  # 승인인데 페이지 미지정 → 후보 페이지 자동 채움
    svc.upsert_decision(
        row_id, decision=mapped, reviewed=True, reviewed_candidate_page=page,
        manual_page_from=page, manual_page_to=body.candidate_page_to or page,
        decision_note=body.note or "",
    )
    return {"ok": True, "row_id": row_id, "decision": mapped}


class PgBulkDecisionBody(BaseModel):
    row_ids: List[str]
    decision: str


@router.post("/manual-update/decisions/bulk")
def pg_bulk_decision(body: PgBulkDecisionBody, admin: dict = Depends(require_admin)):
    """여러 row 에 같은 결정을 일괄 저장. 승인이면 각 후보 페이지를 자동 채운다."""
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성(FEATURE_PG_MANUAL_UPDATE off)")
    mapped = _pg_map_decision(body.decision)
    if mapped not in _PG_VALID_DECISIONS:
        raise HTTPException(status_code=400, detail=f"허용되지 않은 decision: {body.decision}")
    from backend.services import manual_update_pg_service as svc
    page_map: dict = {}
    if mapped == "REVIEWED_APPROVE_CANDIDATE":
        latest = svc.get_state_dict().get("last_staging_version")
        if latest:
            page_map = {c.get("row_id"): c.get("candidate_page_from")
                        for c in svc.get_candidates(latest)}
    done = 0
    for rid in body.row_ids:
        page = page_map.get(rid) if mapped == "REVIEWED_APPROVE_CANDIDATE" else None
        svc.upsert_decision(rid, decision=mapped, reviewed=True,
                            reviewed_candidate_page=page, manual_page_from=page,
                            manual_page_to=page)
        done += 1
    return {"ok": True, "decision": mapped, "count": done}


class PgApplyBody(BaseModel):
    page_from: int
    page_to: int


@router.post("/manual-update/decisions/{row_id}/apply")
def pg_apply_decision(row_id: str, body: PgApplyBody, admin: dict = Depends(require_admin)):
    """승인/직접입력 결정만 운영 manual_ref(JSON)에 반영. 반영 전 백업, 반영 후 applied 기록.

    가드: PG decision 이 REVIEWED_APPROVE_CANDIDATE / NEEDS_MANUAL_PAGE 일 때만.
    기존유지/제외/보류/미검토는 거부 → 기존 매핑을 실수로 강등하지 않는다."""
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성(FEATURE_PG_MANUAL_UPDATE off)")
    if body.page_from < 1:
        raise HTTPException(status_code=400, detail="page_from은 1 이상이어야 합니다.")
    from backend.services import manual_update_pg_service as svc
    dec = svc.get_decision(row_id)
    if not dec or dec.get("decision") not in _PG_APPLYABLE:
        raise HTTPException(
            status_code=400,
            detail=(f"운영 반영 불가: decision='{(dec or {}).get('decision') or '미검토'}'. "
                    f"'승인' 또는 '직접 페이지 입력' 상태에서만 반영할 수 있습니다."),
        )
    row = _ROW_INDEX.get(row_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"row_id '{row_id}' 없음(운영 DB)")
    found = False
    for ref in (row.get("manual_ref") or []):
        if ref.get("match_type") == "manual_override":
            ref["page_from"] = body.page_from
            ref["page_to"] = body.page_to
            found = True
            break
    if not found:
        raise HTTPException(status_code=400, detail="manual_override ref 없음")
    import datetime as _dt
    backup_dir = os.path.join(_BASE_DIR, "data", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    bk = os.path.join(backup_dir, f"immigration_guidelines_db_v2.pg_apply_backup_{ts}.json")
    try:
        with open(_DB_PATH, "rb") as _src:
            raw = _src.read()
        with open(bk, "wb") as _dst:
            _dst.write(raw)
        with open(_DB_PATH, "w", encoding="utf-8") as _out:
            json.dump(_DB, _out, ensure_ascii=False, indent=2)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"운영 DB 쓰기 실패: {e}")
    svc.mark_decision_applied(row_id, body.page_from, body.page_to)
    return {"ok": True, "row_id": row_id, "page_from": body.page_from,
            "page_to": body.page_to, "backup": os.path.basename(bk)}


# ── 수동 페이지 지정(override) / 재비교 / 최신·배포 PDF ───────────────────────
class PgOverrideBody(BaseModel):
    baseline_from: Optional[int] = None
    baseline_to: Optional[int] = None
    candidate_from: Optional[int] = None
    candidate_to: Optional[int] = None
    reason: Optional[str] = None
    manual: Optional[str] = None      # 페이지 상한 검증용(매뉴얼 라벨). 없으면 fallback 상한.
    version: Optional[str] = None     # staging 전체본이 있으면 그 page_count 로 검증


@router.post("/manual-update/decisions/{row_id}/override")
def pg_save_override(row_id: str, body: PgOverrideBody, admin: dict = Depends(require_admin)):
    """관리자 수동 페이지 지정 저장(자동 추천값 보존, 운영 manual_ref 미반영).

    기존/추천 페이지가 모두 틀릴 때 임의 페이지를 직접 입력하는 경로. 잘못된 페이지는
    400 으로 막는다:
      - 0/음수/정수 아님 → 400
      - from > to → 400
      - 매뉴얼 전체 page_count 를 알 수 있으면 1~page_count 초과 → 400
        (예: 764페이지 PDF 에서 3000 입력 차단)
      - page_count 를 알 수 없을 때만 fallback 상한(_MAX_PAGE) 사용(UI 는 pdf-source 의
        page_count=null 로 '전체 페이지 수 확인 불가' 를 구분 표시)."""
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성(FEATURE_PG_MANUAL_UPDATE off)")
    _MAX_PAGE = 5000  # page_count 미확인 시에만 쓰는 안전 상한
    page_count = None
    if body.manual:
        kr = _pdf_label_to_kr(body.manual)
        if kr:
            page_count, _ = _full_pdf_page_count(kr, body.version or "")
    upper = page_count if page_count else _MAX_PAGE
    bound_txt = (f"1~{page_count} (전체 {page_count}페이지)" if page_count
                 else f"1~{_MAX_PAGE} (전체 페이지 수 확인 불가)")

    def _vpair(frm, to, name):
        for v in (frm, to):
            if v is not None and (int(v) < 1 or int(v) > upper):
                raise HTTPException(status_code=400,
                    detail=f"{name} 페이지는 {bound_txt} 범위여야 합니다.")
        if frm is not None and to is not None and int(frm) > int(to):
            raise HTTPException(status_code=400, detail=f"{name} 시작 페이지가 끝 페이지보다 큽니다.")
    _vpair(body.baseline_from, body.baseline_to, "기준")
    _vpair(body.candidate_from, body.candidate_to, "후보")
    from backend.services import manual_update_pg_service as svc
    return svc.save_reviewer_override(
        row_id, baseline_from=body.baseline_from, baseline_to=body.baseline_to,
        candidate_from=body.candidate_from, candidate_to=body.candidate_to,
        reason=(body.reason or ""), by=str(admin.get("login_id") or ""))


@router.delete("/manual-update/decisions/{row_id}/override")
def pg_clear_override(row_id: str, admin: dict = Depends(require_admin)):
    """수동 지정 초기화(자동 추천값으로 복귀)."""
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성(FEATURE_PG_MANUAL_UPDATE off)")
    from backend.services import manual_update_pg_service as svc
    return svc.clear_reviewer_override(row_id)


@router.get("/manual-update/recompare")
def pg_recompare(version: str, label: str,
                 baseline_from: int = Query(...), baseline_to: int = Query(0),
                 candidate_from: int = Query(...), candidate_to: int = Query(0),
                 admin: dict = Depends(require_admin)):
    """수동 지정 페이지 기준으로 기존/후보 텍스트 재추출 + diff 재계산.
    후보(신규) 텍스트는 변경 페이지 스니펫 기반(전체 본문 미보유 → candidate_partial=true)."""
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성(FEATURE_PG_MANUAL_UPDATE off)")
    from backend.services import manual_update_pg_service as svc
    return svc.recompare(version, label, baseline_from, baseline_to or baseline_from,
                         candidate_from, candidate_to or candidate_from)


def _pdf_label_to_kr(label: str) -> Optional[str]:
    """candidate manual_label(visa/residence/stay…) → _MANUAL_FILES 키(사증민원/체류민원)."""
    m = {"visa": "사증민원", "사증민원": "사증민원",
         "residence": "체류민원", "stay": "체류민원", "체류민원": "체류민원"}
    return m.get((label or "").strip())


def _staging_full_pdf_path(version: str, kr_label: str) -> Optional[str]:
    """버전별 staging 전체 PDF 가 있으면 그 경로(없으면 None). 향후 업로드 대비 hook.
    convention: data/manuals/staging/{version}/{kr}_full.pdf 또는 review_pdf/{kr}.pdf."""
    cand = [
        os.path.join(_MANUALS_DIR, "staging", version, f"{kr_label}_full.pdf"),
        os.path.join(_MANUALS_DIR, "staging", version, "review_pdf", f"{kr_label}.pdf"),
    ]
    for p in cand:
        if os.path.isfile(p):
            return p
    return None


def _full_pdf_page_count(kr_label: str, version: str = "") -> tuple[Optional[int], Optional[str]]:
    """검증 기준이 되는 매뉴얼 전체 페이지 수 → (page_count, source).
    staging 전체 PDF 가 있으면 그것, 없으면 배포본 PDF 의 page_count. 둘 다 없으면 (None, None)."""
    candidates = []
    staging = _staging_full_pdf_path(version, kr_label) if version else None
    if staging:
        candidates.append((staging, "staging"))
    deployed = os.path.join(_MANUALS_DIR, _MANUAL_FILES.get(kr_label, ""))
    if os.path.isfile(deployed):
        candidates.append((deployed, "deployed"))
    for path, src in candidates:
        try:
            import fitz
            with fitz.open(path) as d:
                return d.page_count, src
        except Exception:
            continue
    return None, None


@router.get("/manual-update/pdf-source")
def pg_pdf_source(manual: str, version: str = "", admin: dict = Depends(require_admin)):
    """버튼 라벨/배너용 + 임의 페이지 검증 기준.

    resolver 우선순위(pg_pdf 와 동일): staging 파일 > worker full_pdf > review_splice 합성 > 배포본.
    ``review_only`` 가 True 면 PyMuPDF 검토용 합성본(운영 미반영)이다.
    ``page_count`` 는 임의 페이지 입력 검증 상한(없으면 null → '전체 페이지 수 확인 불가')."""
    kr = _pdf_label_to_kr(manual)
    if not kr:
        raise HTTPException(status_code=400, detail=f"알 수 없는 manual '{manual}'")
    staging = _staging_full_pdf_path(version, kr) if version else None
    deployed = os.path.join(_MANUALS_DIR, _MANUAL_FILES.get(kr, ""))
    manual_norm = _MANUAL_NORM.get((manual or "").strip())
    page_count, page_count_source = _full_pdf_page_count(kr, version)
    # 0순위: 관리자 업로드 PDF(있으면 page_count·source 를 그것으로 — 임의페이지 검증도 이 기준).
    uploaded = None
    try:
        from backend.services import manual_pdf_upload_service as _up
        uploaded = _up.resolve_review_pdf_meta(manual, version)
    except Exception:
        uploaded = None
    if uploaded:
        return {
            "manual": manual, "kr_label": kr, "version": version,
            "is_staging": uploaded["source"] == "upload_staging",
            "source": uploaded["source"],          # upload_staging | upload_deployed
            "review_only": bool(uploaded["review_only"]),
            "page_count": uploaded.get("page_count"),   # 업로드 PDF page_count 우선
            "page_count_source": uploaded["source"],
            "available": True,
        }
    # 소스 판정(스트리밍은 pg_pdf 가 동일 우선순위로 수행)
    source, review_only = "deployed", False
    if staging:
        source, review_only = "staging", False
    elif manual_norm and version:
        try:
            from backend.services import manual_update_pg_service as svc
            if svc.pg_enabled():
                # worker/node 가 미리 만든 full_pdf artifact 만 인정. (web 합성 review_splice 비활성)
                if svc.get_worker_full_pdf(manual_norm, version):
                    source, review_only = "worker_artifact", False
        except Exception:
            pass
    return {
        "manual": manual, "kr_label": kr, "version": version,
        "is_staging": bool(staging),
        "source": source,
        "review_only": review_only,        # True → 검토용(운영 미반영) 합성본
        "page_count": page_count,          # 임의 페이지 검증 상한(null=확인 불가)
        "page_count_source": page_count_source,
        "available": bool(staging) or os.path.isfile(deployed),
    }


@router.get("/manual-update/pdf-status")
def pg_pdf_status(manual: str, version: str = "", admin: dict = Depends(require_admin)):
    """PDF 최신화 진단 — 뷰어가 실제 여는 파일/소스, 배포본 메타, 최신화 파이프라인 연결 상태.

    화면이 왜 3월/배포본 PDF 로 fallback 하는지 관리자에게 그대로 노출한다(미구현 숨김 금지)."""
    kr = _pdf_label_to_kr(manual)
    if not kr:
        raise HTTPException(status_code=400, detail=f"알 수 없는 manual '{manual}'")
    staging = _staging_full_pdf_path(version, kr) if version else None
    deployed_fname = _MANUAL_FILES.get(kr, "")
    deployed_path = os.path.join(_MANUALS_DIR, deployed_fname)
    deployed = {"filename": deployed_fname, "exists": os.path.isfile(deployed_path),
                "mtime": None, "page_count": None}
    if deployed["exists"]:
        import datetime as _dt
        deployed["mtime"] = _dt.datetime.fromtimestamp(os.path.getmtime(deployed_path)).strftime("%Y-%m-%d %H:%M")
        try:
            import fitz
            with fitz.open(deployed_path) as _d:
                deployed["page_count"] = _d.page_count
        except Exception:
            pass
    # 최신화 파이프라인 연결 상태(현 시점 사실 그대로).
    gen_node = os.path.join(_BASE_DIR, "..", "tools", "rhwp_manual_pipeline", "node_modules")
    generator_present = os.path.isdir(gen_node)
    incoming_dir = os.path.join(_MANUALS_DIR, "incoming")
    source_hwp_present = False
    if version and os.path.isdir(incoming_dir):
        source_hwp_present = any(version in n for n in os.listdir(incoming_dir))
    # PDF artifact 레지스트리(Step 3) — worker full_pdf / review_splice 합성 구분.
    artifact_summary = {"total": 0, "by_manual": {}}
    full_artifact = None            # worker/node 가 만든 진짜 full_pdf (review_splice 아님)
    review_splice_available = False  # 변경 페이지 → 배포본 스플라이스 합성 가능 여부
    manual_norm = _MANUAL_NORM.get((manual or "").strip())
    try:
        from backend.services import manual_update_pg_service as svc
        if svc.pg_enabled():
            artifact_summary = svc.pdf_artifact_summary(manual=manual)
            if manual_norm:
                full_artifact = svc.get_worker_full_pdf(manual_norm, version or None)
                if version:
                    review_splice_available = bool(svc._changed_components(manual_norm, version))
    except Exception:
        pass
    # 0순위: 관리자 업로드 PDF(staging manual_upload → 승격 deployed).
    uploaded_meta = None
    try:
        from backend.services import manual_pdf_upload_service as _up
        uploaded_meta = _up.resolve_review_pdf_meta(manual, version)
    except Exception:
        uploaded_meta = None
    # viewer 우선순위: 업로드본 > staging 파일 > worker full_pdf > 배포본.
    # ※ OOM 방지: review_splice(web PyMuPDF 합성)는 viewer 경로에서 비활성 — 절대 자동 합성하지 않는다.
    if uploaded_meta:
        viewer_source = uploaded_meta["source"]   # upload_staging | upload_deployed
        viewer_file = f"upload_artifact#{uploaded_meta.get('artifact_id')}"
    elif staging:
        viewer_source, viewer_file = "staging", os.path.basename(staging)
    elif full_artifact:
        viewer_source, viewer_file = "worker_artifact", f"artifact#{full_artifact['id']}"
    else:
        viewer_source, viewer_file = "deployed", deployed_fname
    return {
        "manual": manual, "kr_label": kr, "version": version,
        "viewer_source": viewer_source,
        "viewer_file": viewer_file,
        "staging_pdf_exists": bool(staging),
        "deployed": deployed,
        "artifacts": artifact_summary.get("by_manual", {}).get(manual, {"total": 0}),
        "artifacts_total": artifact_summary.get("total", 0),
        "full_pdf_artifact": full_artifact,               # worker full_pdf artifact(있으면 viewer 우선)
        "review_splice_available": review_splice_available,  # 변경 페이지 존재 여부(worker 합성 후보; web 합성 안 함)
        "review_splice_web_disabled": True,                # web 요청 중 PyMuPDF full 합성 비활성(OOM 방지)
        "review_only": viewer_source == "upload_staging",  # 검토용(운영 미반영) 표시 중인지
        "generator_present": generator_present,           # rhwp+chromium CLI 설치 여부
        "source_hwp_present": source_hwp_present,          # 해당 version HWP 원본 보유 여부
        "replace_pipeline_wired": False,                  # web 자동 합성 비활성(운영 반영은 업로드→승격으로)
        "can_refresh_now": False,
        "reason": ("관리자 업로드 검토용 PDF 표시 중(운영 미반영)" if viewer_source == "upload_staging" else
                   "관리자 업로드 운영 PDF(승격본) 표시 중" if viewer_source == "upload_deployed" else
                   "최신 staging PDF 가 있어 그것을 표시 중" if staging else
                   "worker full_pdf artifact 표시 중" if full_artifact else
                   "업로드 PDF 없음 → 기존 배포본 fallback (web 합성 비활성)."),
    }


@router.get("/manual-update/pdf")
def pg_pdf(manual: str, version: str = "",
           token: Optional[str] = Query(None), authorization: Optional[str] = Header(None)):
    """viewer resolver — '변경 반영된 완전한 PDF'(전체 문서) 를 #page 점프와 함께 제공.

    우선순위:
      1) staging 전체 PDF 파일(worker 가 렌더한 완전한 새 매뉴얼)
      2) worker/node 가 만든 진짜 full_pdf artifact (review_splice 아님)
      3) 변경 페이지 artifact 를 배포본에 스플라이스한 review_splice 합성본(검토용·운영 미반영, PyMuPDF)
      4) 배포본 전체 PDF fallback
    어느 경우든 변경 페이지만 있는 bundle 이 아니라 '전체 문서'를 반환 → 앞뒤 스크롤 가능.
    인증: Authorization 헤더 또는 ?token= (iframe)."""
    _verify_token_flexible(token, authorization)
    from fastapi.responses import Response as _Resp
    from urllib.parse import quote
    kr = _pdf_label_to_kr(manual)
    if not kr:
        raise HTTPException(status_code=400, detail=f"알 수 없는 manual '{manual}'")
    _hdr = {
        "Cache-Control": "private, max-age=600",
        "Content-Disposition": f"inline; filename=\"manual.pdf\"; filename*=UTF-8''{quote(kr + '.pdf', safe='')}",
    }
    # 0순위: 관리자 업로드 PDF(staging manual_upload → 승격된 deployed). 후보 상세 viewer 가
    # 옛 배포본이 아니라 '최신 업로드본 전체'를 열도록 최우선. 실패는 graceful(아래 체인으로 폴백).
    try:
        from backend.services import manual_pdf_upload_service as _up
        _uploaded = _up.resolve_review_pdf(manual, version)
        if _uploaded and _uploaded.get("blob"):
            return _Resp(content=_uploaded["blob"], media_type="application/pdf", headers=_hdr)
    except Exception:
        pass
    # 1순위: staging 전체 PDF(이미 완전한 새 매뉴얼)
    staging = _staging_full_pdf_path(version, kr) if version else None
    if staging and os.path.isfile(staging):
        return FileResponse(staging, media_type="application/pdf", headers=_hdr)
    deployed_path = os.path.join(_MANUALS_DIR, _MANUAL_FILES.get(kr, ""))
    manual_norm = _MANUAL_NORM.get((manual or "").strip())
    if manual_norm:
        try:
            from backend.services import manual_update_pg_service as svc
            if svc.pg_enabled():
                # 2순위: worker/node 가 미리 만든 full_pdf artifact(저장된 blob 만 서빙).
                worker = svc.get_worker_full_pdf(manual_norm, version or None)
                if worker:
                    blob = svc.get_pdf_artifact_blob(worker["id"])
                    if blob:
                        return _Resp(content=blob, media_type="application/pdf", headers=_hdr)
                # ※ OOM 방지: web 요청 중 전체 PDF 합성/스플라이스(compose_full_pdf_blob) 금지.
                #   업로드본/worker artifact 가 없으면 합성하지 않고 배포본 fallback 으로 간다.
        except Exception:
            pass
    # 3순위: 배포본 전체 PDF fallback (합성 없음)
    if not os.path.isfile(deployed_path):
        raise HTTPException(status_code=404, detail=f"PDF 파일 없음: {kr}")
    return FileResponse(deployed_path, media_type="application/pdf", headers=_hdr)


# ── PDF artifact 레지스트리 API (Step 3) ─────────────────────────────────────
@router.get("/manual-update/pdf-artifacts")
def pg_list_pdf_artifacts(manual: str = "", version: str = "", admin: dict = Depends(require_admin)):
    """artifact 목록(blob 제외) + manual 별 요약."""
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성(FEATURE_PG_MANUAL_UPDATE off)")
    from backend.services import manual_update_pg_service as svc
    rows = svc.get_pdf_artifacts(manual or None, version or None)
    return {"count": len(rows), "summary": svc.pdf_artifact_summary(manual or None), "rows": rows}


@router.get("/manual-update/pdf-artifacts/{artifact_id}")
def pg_get_pdf_artifact(artifact_id: int, admin: dict = Depends(require_admin)):
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성(FEATURE_PG_MANUAL_UPDATE off)")
    from backend.services import manual_update_pg_service as svc
    a = svc.get_pdf_artifact(artifact_id)
    if not a:
        raise HTTPException(status_code=404, detail=f"artifact {artifact_id} 없음")
    return a


@router.get("/manual-update/pdf-artifacts/{artifact_id}/content")
def pg_get_pdf_artifact_content(artifact_id: int,
                                token: Optional[str] = Query(None),
                                authorization: Optional[str] = Header(None)):
    """artifact PDF 바이트(application/pdf). iframe 용 ?token= 도 허용."""
    _verify_token_flexible(token, authorization)
    from fastapi.responses import Response as _Resp
    from backend.services import manual_update_pg_service as svc
    if not svc.pg_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성")
    blob = svc.get_pdf_artifact_blob(artifact_id)
    if blob is None:
        raise HTTPException(status_code=404, detail=f"artifact {artifact_id} blob 없음")
    return _Resp(content=blob, media_type="application/pdf",
                 headers={"Cache-Control": "private, max-age=600",
                          "Content-Disposition": f"inline; filename=\"artifact_{artifact_id}.pdf\""})


_MANUAL_NORM = {"visa": "visa", "사증민원": "visa", "residence": "stay", "stay": "stay", "체류민원": "stay"}


# ── 관리자 최신 PDF 업로드 (web 컨테이너 합성/렌더 없이 저장+텍스트추출+비교) ──────────
import tempfile as _tempfile
from fastapi import File as _File, Form as _Form, UploadFile as _UploadFile


@router.post("/manual-update/upload-pdf")
async def pg_upload_pdf(
    manual: str = _Form(...),
    version: str = _Form(...),
    memo: str = _Form(""),
    file: _UploadFile = _File(...),
    admin: dict = Depends(require_admin),
):
    """관리자가 변환한 최신 PDF 업로드 → staging 저장 + 페이지 텍스트 추출 + 변경 감지.

    메모리 폭발 방지: UploadFile 을 통째로 읽지 않고 1MB chunk 로 임시파일에 저장하며 크기 제한,
    PyMuPDF 로 열림/page_count 검증, 검증 통과분만 blob 저장. 실패 시 임시파일 정리."""
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성(FEATURE_PG_MANUAL_UPDATE off)")
    from backend.services import manual_pdf_upload_service as up

    fd, tmp_path = _tempfile.mkstemp(suffix=".pdf")
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > up.MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413,
                                        detail=f"PDF 가 너무 큽니다(최대 {up.MAX_UPLOAD_BYTES // (1024*1024)}MB).")
                out.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="빈 파일입니다.")
        ct = (file.content_type or "").lower()
        if "pdf" not in ct and not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="PDF 파일만 업로드할 수 있습니다.")
        try:
            return up.process_upload(
                manual=manual, version=version, temp_path=tmp_path,
                orig_filename=file.filename or "",
                uploaded_by=admin.get("login_id") or admin.get("sub", ""),
                memo=memo,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


class PgPromotePdfBody(BaseModel):
    manual: str
    version: str


@router.post("/manual-update/promote-pdf")
def pg_promote_pdf(body: PgPromotePdfBody, admin: dict = Depends(require_admin)):
    """검토 완료된 staging 업로드 PDF 를 운영(deployed)으로 승격(기존본은 previous 보존)."""
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성")
    from backend.services import manual_pdf_upload_service as up
    try:
        return up.promote(body.manual, body.version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/manual-update/uploaded-pdf")
def pg_uploaded_pdf(manual: str, version: str = "",
                    token: Optional[str] = Query(None),
                    authorization: Optional[str] = Header(None)):
    """검토용 업로드 PDF(staging) 전체를 그대로 서빙(iframe ?token= 허용). 운영 미반영."""
    _verify_token_flexible(token, authorization)
    from fastapi.responses import Response as _Resp
    from backend.services import manual_pdf_upload_service as up
    res = up.get_staging_blob(manual, version)
    if res is None:
        raise HTTPException(status_code=404, detail="업로드된 검토용 PDF 가 없습니다.")
    blob, meta = res
    return _Resp(content=blob, media_type="application/pdf",
                 headers={"Cache-Control": "private, max-age=120",
                          "Content-Disposition": f"inline; filename=\"staging_{meta.get('manual')}_{meta.get('version')}.pdf\""})


@router.get("/manual-update/uploads")
def pg_list_uploads(manual: str = "", admin: dict = Depends(require_admin)):
    """업로드(staging/deployed) PDF 목록(메타) — 관리자 화면 표시용."""
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성")
    from backend.services import manual_pdf_upload_service as up
    return {"rows": up.list_uploads(manual)}


class PgDetectChangesBody(BaseModel):
    manual: str
    version: str


@router.post("/manual-update/detect-changes")
def pg_detect_changes(body: PgDetectChangesBody, admin: dict = Depends(require_admin)):
    """업로드 직후 분리된 '변경 감지 실행' — 업로드 PDF 텍스트 추출 + baseline 비교 + 후보 생성.

    업로드(저장)와 분리된 무거운 단계. 실패해도 업로드 PDF 는 유지된다(viewer 계속 사용 가능)."""
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성")
    from backend.services import manual_pdf_upload_service as up
    try:
        return up.run_change_detection(body.manual, body.version)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # 변경감지 실패 — 업로드 PDF 는 보존, 상태만 실패로 알린다(앱 안 깨짐).
        raise HTTPException(status_code=500, detail=f"변경 감지 실패: {type(e).__name__}: {e}")


@router.get("/manual-update/versions/{version}/candidates/{row_id}/pdf-artifact")
def pg_candidate_pdf_artifact(version: str, row_id: str, admin: dict = Depends(require_admin)):
    """후보 상세 PDF viewer resolver.

    검토용 PDF 는 '변경 페이지만 있는 bundle' 이 아니라 **변경 반영된 완전한 PDF**(전체 문서)
    이어야 한다 → ``mode="full"`` + 후보 페이지(``page``)를 돌려준다. 프론트는
    ``/manual-update/pdf?manual&version#page=N`` 으로 전체 문서를 열고 후보 페이지로 자동
    이동하며 앞뒤 스크롤이 가능하다. (참고용으로 해당 후보를 덮는 변경 페이지 artifact id 도
    함께 제공.)"""
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성(FEATURE_PG_MANUAL_UPDATE off)")
    from backend.services import manual_update_pg_service as svc
    c = next((x for x in svc.get_candidates_enriched(version) if x.get("row_id") == row_id), None)
    if not c:
        raise HTTPException(status_code=404, detail=f"후보 '{row_id}' 없음")
    manual = _MANUAL_NORM.get(c.get("manual_label") or "", c.get("manual_label"))
    pf = int(c.get("candidate_page_from") or 0)
    pt = int(c.get("candidate_page_to") or pf or 0)
    arts = svc.get_pdf_artifacts(manual, version)

    def _covers(a) -> bool:
        nums = a.get("page_numbers")
        if nums:
            return any(pf <= int(p) <= (pt or pf) for p in nums)
        if a.get("page_from") and a.get("page_to"):
            return not (a["page_to"] < pf or a["page_from"] > (pt or pf))
        return False
    bundle = [a for a in arts if a["artifact_type"] in ("changed_page_bundle", "changed_page") and _covers(a)]
    changed_id = bundle[0]["id"] if bundle else None
    return {
        "mode": "full",
        "manual": manual,
        "version": version,
        "page": pf or 1,
        "changed_artifact_id": changed_id,   # 참고용(변경 페이지만 따로 보고 싶을 때)
    }


# ── 관리자 수동 실행: 진단(dry-run) / 실제 업데이트(record) + capability check ──
import threading as _threading

_RUN_NOW_LOCK = _threading.Lock()
_RUN_NOW_STATE = {"running": False, "mode": None, "started_at": None}


def _chromium_runtime_status() -> tuple[bool, str]:
    """실제 chromium 실행 파일이 있는지(=PDF 생성 가능)를 _lib.mjs 의 CHROME_PATH 규칙대로 판정.

    npm 패키지(playwright-core) 디렉터리 존재 ≠ chromium 브라우저 존재. _lib.mjs 는:
      * CHROME_PATH=<경로>  → 그 실행 파일을 executablePath 로 사용 (파일이 존재해야 함)
      * CHROME_PATH=""       → playwright 번들 chromium(ms-playwright 캐시) 사용
      * CHROME_PATH 미설정    → 기본값(Windows 로컬 Chrome)
    반환: (실행가능여부, 점검한 경로/위치 설명)."""
    import glob
    cp = os.environ.get("CHROME_PATH")
    if cp:  # 비어있지 않은 명시 경로 → 그 파일이 실제로 있어야 한다(워커 이미지: /usr/bin/chromium)
        return (os.path.isfile(cp), cp)
    if cp == "":  # 명시적 빈 문자열 → playwright 번들 chromium 탐색
        base = (os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
                or os.path.expanduser("~/.cache/ms-playwright"))
        hits = (glob.glob(os.path.join(base, "chromium-*", "chrome-linux", "chrome"))
                + glob.glob(os.path.join(base, "chromium-*", "chrome-linux", "headless_shell")))
        return (bool(hits), f"playwright-bundled:{base}")
    # CHROME_PATH 미설정 → _lib.mjs 기본값(로컬 Windows Chrome)
    default = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    return (os.path.isfile(default), default)


def _run_capability() -> dict:
    """현재 프로세스 런타임에서 rhwp extract(실제 기록) / chromium(변경 페이지 PDF) 실행이
    가능한지 진단한다. 각 능력을 **독립적으로** 판단한다:
      * node / rhwp / extract.mjs  → can_record_update (PG staging 기록)
      * 위 + chromium 실제 실행파일 → can_generate_pdf (PDF artifact 생성)
    웹서비스(chromium 없음)는 can_generate_pdf=False; Render Cron/Worker(chromium 있음)는 True."""
    import shutil
    node_available = bool(shutil.which("node"))
    tools = os.path.join(_BASE_DIR, "..", "tools", "rhwp_manual_pipeline")
    extract_mjs_exists = os.path.isfile(os.path.join(tools, "extract.mjs"))
    rhwp_available = os.path.isdir(os.path.join(tools, "node_modules", "@rhwp", "core"))
    # playwright-core npm 패키지 존재(≠ 브라우저) — 진단 표시용으로만 분리해 노출
    chromium_pkg_present = os.path.isdir(os.path.join(tools, "node_modules", "playwright-core"))
    chromium_executable, chromium_path = _chromium_runtime_status()
    chromium_available = node_available and chromium_pkg_present and chromium_executable

    is_worker = str(os.environ.get("MANUAL_UPDATE_WORKER") or "").strip().lower() in (
        "1", "true", "yes", "y", "on")
    is_server = str(os.environ.get("HANWOORY_ENV") or os.environ.get("RUN_ENV") or "").lower() == "server"
    if is_worker:
        runtime = "render-worker"
    elif is_server:
        runtime = "render-web"
    elif os.path.exists("/.dockerenv"):
        runtime = "docker-backend"
    else:
        runtime = "host"

    can_record_update = node_available and extract_mjs_exists and rhwp_available
    can_generate_pdf = can_record_update and chromium_available

    record_reason = "" if can_record_update else (
        "node/rhwp runtime is not available in this environment "
        "(이 런타임에 node/rhwp 실행 환경이 없어 실제 업데이트(PG 기록)가 비활성화됨).")
    if can_generate_pdf:
        pdf_reason = ""
    elif not can_record_update:
        pdf_reason = record_reason
    elif not chromium_available:
        pdf_reason = (
            "chromium 실행 환경이 없습니다 (checked: " + chromium_path + "). "
            "변경 페이지 PDF 생성은 chromium 이 포함된 Render Cron/Worker(Dockerfile.worker)가 담당합니다.")
    else:
        pdf_reason = ""

    return {
        "can_diagnose": True,                         # 감지(detail/parse/compare)는 node 없이 가능
        "can_record_update": can_record_update,       # 실제 PG 기록 실행 가능 여부
        "can_generate_pdf": can_generate_pdf,         # 변경 페이지 PDF 생성 가능 여부(=record + chromium)
        "node_available": node_available,
        "extract_mjs_exists": extract_mjs_exists,
        "rhwp_available": rhwp_available,
        "chromium_pkg_present": chromium_pkg_present,  # playwright-core npm 패키지(≠ 브라우저)
        "chromium_available": chromium_available,      # 실제 chromium 실행파일까지 확인됨
        "chromium_path": chromium_path,                # 점검한 chromium 경로/위치
        "is_worker": is_worker,                        # PDF 담당 워커 런타임 여부
        "runtime": runtime,
        "running": _RUN_NOW_STATE["running"],
        "reason": record_reason,                       # (하위호환) record 비활성 사유
        "pdf_reason": pdf_reason,                      # PDF 생성 비활성 사유(분리)
    }


@router.get("/manual-update/capabilities")
def pg_capabilities(admin: dict = Depends(require_admin)):
    return _run_capability()


class RunNowBody(BaseModel):
    mode: str = "diagnose"          # diagnose | record | generate_pdf_artifacts
    limit: Optional[int] = None     # generate_pdf_artifacts 테스트용 후보 수 제한


@router.post("/manual-update/run-now")
def pg_run_now(body: RunNowBody, admin: dict = Depends(require_admin)):
    """관리자 수동 실행.
      mode=diagnose              : run_auto_update_pg_dryrun() — 감지→(node 가능 시)추출/후보. PG 미기록.
      mode=record                : 실제 run_auto_update_pg() — PG version/changed/candidate 기록.
                                   capability(can_record_update) 통과 시에만 허용.
      mode=generate_pdf_artifacts: 변경 페이지 PDF artifact 생성·저장(node+chromium 필요).
                                   capability(can_generate_pdf) 통과 시에만 허용.
    중복 실행은 in-process lock 으로 차단(409)."""
    if not _pg_manual_enabled():
        raise HTTPException(status_code=409, detail="PG manual-update 비활성(FEATURE_PG_MANUAL_UPDATE off)")
    mode = (body.mode or "diagnose").strip()
    if mode not in ("diagnose", "record", "generate_pdf_artifacts"):
        raise HTTPException(status_code=400, detail="mode 는 diagnose|record|generate_pdf_artifacts 만 허용")
    cap = _run_capability()
    if mode == "record" and not cap["can_record_update"]:
        raise HTTPException(status_code=409, detail="실제 업데이트 실행 불가: " + cap["reason"])
    if mode == "generate_pdf_artifacts" and not cap["can_generate_pdf"]:
        raise HTTPException(status_code=409, detail="PDF artifact 생성 불가: chromium 실행 환경이 없습니다. 변경 페이지 PDF 생성은 Render Cron/Worker(Dockerfile.worker)가 담당합니다.")
    if not _RUN_NOW_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail={"code": "RUNNING",
                            "message": "이미 매뉴얼 업데이트 실행 중입니다.", "state": dict(_RUN_NOW_STATE)})
    import datetime as _dt
    _RUN_NOW_STATE.update(running=True, mode=mode, started_at=_dt.datetime.now().isoformat())
    try:
        from backend.services import manual_auto_update as mau
        if mode == "diagnose":
            result = mau.run_auto_update_pg_dryrun(force=True, allow_node=cap["can_record_update"])
        elif mode == "generate_pdf_artifacts":
            result = mau.generate_pdf_artifacts_for_version(limit=body.limit)
        else:
            result = mau.run_auto_update_pg(force=True, trigger="admin-run-now", notify=False)
            if isinstance(result, dict):
                result.setdefault("wrote_to_pg", result.get("status") == "staged")
        return {"mode": mode, "capability": cap, "result": result}
    finally:
        _RUN_NOW_STATE.update(running=False, mode=None, started_at=None)
        _RUN_NOW_LOCK.release()


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
