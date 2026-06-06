"""
manual_ref_rematch.py — 매뉴얼 PDF 업데이트 후 manual_override 건 페이지 검증

LLM 없음. 비용 없음. 텍스트 검색 기반.

동작:
  1. DB에서 match_type == "manual_override" 행만 선택
  2. match_text에서 핵심 키워드 추출
  3. 해당 PDF 전체 검색 → 페이지 변경 여부 판단
  4. JSON 리포트 저장

CLI:
  python backend/scripts/manual_ref_rematch.py            # dry-run (기본)
  python backend/scripts/manual_ref_rematch.py --auto-apply   # 명확한 변경 자동 적용
  python backend/scripts/manual_ref_rematch.py --report-only  # 리포트만
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

ROOT     = Path(__file__).parent.parent.parent
DB_PATH  = ROOT / "backend" / "data" / "immigration_guidelines_db_v2.json"  # 운영 DB — 이동 금지
# 매뉴얼/검토 산출물 디렉토리 — MANUALS_DATA_DIR(기본=backend/data/manuals)로 분리.
# unlocked_*.pdf(검증용) 와 manual_update_review.json 이 이 경로를 따른다.
MANUALS  = Path(os.environ.get("MANUALS_DATA_DIR", str(ROOT / "backend" / "data" / "manuals")))
BACKUP   = ROOT / "backend" / "data" / "backups"  # DB 백업 — 운영 DB 와 함께 baked 경로 유지
OUT_JSON = MANUALS / "manual_update_review.json"

PDF_MAP = {
    "체류민원": MANUALS / "unlocked_체류민원.pdf",
    "사증민원": MANUALS / "unlocked_사증민원.pdf",
}

# ── 텍스트 정규화 (quality_gate_v4.py 동일 로직) ─────────────────────────────
_NORMALIZE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"체류자격\s*부\s*여"),               "체류자격부여"),
    (re.compile(r"근무처의?\s*변경[·\s]*추가"),        "근무처변경추가"),
    (re.compile(r"체류자격\s*외\s*활동"),              "체류자격외활동"),
    (re.compile(r"사증\s*발급\s*인정서"),              "사증발급인정서"),
    (re.compile(r"사증\s*발급\s*확인서"),              "사증발급확인서"),
    (re.compile(r"외국인\s*등록"),                     "외국인등록"),
    (re.compile(r"재입국\s*허가"),                     "재입국허가"),
    (re.compile(r"체류기간\s*연장"),                   "체류기간연장"),
    (re.compile(r"체류자격\s*변경"),                   "체류자격변경"),
]


def normalize_pdf_text(text: str) -> str:
    if not text:
        return ""
    out = text
    for pat, repl in _NORMALIZE_PATTERNS:
        out = pat.sub(repl, out)
    out = re.sub(r"[ \t　]+", " ", out)
    return out


# ── 키워드 추출 ──────────────────────────────────────────────────────────────
# PDF에서 찾을 수 없는 영어 action type 단어 목록
_EN_ACTION_WORDS = re.compile(
    r"\b(?:CHANGE|EXTEND|REGISTRATION|EXTRA_WORK|WORKPLACE|GRANT|VISA_CONFIRM|"
    r"DOMESTIC_RESIDENCE_REPORT|ACTIVITY_EXTRA|REENTRY|APPLICATION_CLAIM|"
    r"LLM|judge|verifier|ACCEPTED)\b"
)


def extract_keyword(match_text: str) -> str:
    """match_text에서 핵심 검색 토큰 목록 반환을 위한 정제 문자열."""
    if not match_text:
        return ""
    kw = match_text
    # 페이지 괄호 제거: (체류민원 p.349) 등
    kw = re.sub(r"[（(（\(](?:체류민원|사증민원)\s*p[\.\d\-~+]+[^）)）\)]*[）)）\)]", "", kw)
    # 후미 제거 (—이후 검증 문구)
    kw = re.sub(r"\s*—\s*(?:수동 검증|LLM judge|verifier 검증|LLM verifier|ACCEPTED).*", "", kw)
    # 영어 action type 단어 제거 (PDF에 없는 단어)
    kw = _EN_ACTION_WORDS.sub("", kw)
    # 괄호/특수문자 제거
    kw = re.sub(r"[+【】\(\)（）〔〕\[\]]", " ", kw)
    # 다중 공백 정리
    kw = re.sub(r"\s+", " ", kw).strip()
    if len(kw) < 2:
        return match_text.strip()
    return kw


def keyword_to_tokens(keyword: str) -> list[str]:
    """키워드를 개별 검색 토큰으로 분리 (공백 기준, 2자 이상만)."""
    return [t for t in keyword.split() if len(t) >= 2]


# ── PDF 검색 ─────────────────────────────────────────────────────────────────
_pdf_cache: dict[str, list[str]] = {}  # manual → [page_text, ...]


def _get_pdf_pages(manual: str) -> Optional[list[str]]:
    """PDF 페이지 텍스트 목록. 캐시 있으면 재사용."""
    if manual in _pdf_cache:
        return _pdf_cache[manual]
    pdf_path = PDF_MAP.get(manual)
    if not pdf_path or not pdf_path.exists():
        return None
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        pages = [normalize_pdf_text(doc.load_page(i).get_text()) for i in range(doc.page_count)]
        doc.close()
        _pdf_cache[manual] = pages
        return pages
    except Exception as e:
        print(f"[warn] PDF 로드 실패 ({manual}): {e}", file=sys.stderr)
        return None


def search_keyword_in_pdf(manual: str, keyword: str) -> list[int]:
    """keyword 토큰이 모두 포함된 페이지 번호(1-indexed) 목록 반환.

    전략:
    1. 토큰 ALL-match: 모든 토큰이 페이지에 존재하면 히트
    2. 토큰이 1개이면 substring 검색
    """
    pages = _get_pdf_pages(manual)
    if pages is None:
        return []

    tokens = keyword_to_tokens(normalize_pdf_text(keyword))
    if not tokens:
        return []

    # 토큰이 1개이면 단순 substring
    if len(tokens) == 1:
        tok = tokens[0].lower()
        return [i + 1 for i, pt in enumerate(pages) if tok in pt.lower()]

    # 2개 이상: 모든 토큰 포함 페이지만 (AND)
    hits = []
    for i, pt in enumerate(pages):
        pt_lower = pt.lower()
        if all(t.lower() in pt_lower for t in tokens):
            hits.append(i + 1)

    # AND로 못 찾으면 핵심 2토큰(한글 포함 우선)으로 완화
    if not hits:
        kor_tokens = [t for t in tokens if re.search(r"[가-힣]", t)]
        search_tokens = kor_tokens[:2] if len(kor_tokens) >= 2 else tokens[:2]
        for i, pt in enumerate(pages):
            pt_lower = pt.lower()
            if all(t.lower() in pt_lower for t in search_tokens):
                hits.append(i + 1)

    return hits


# ── 보수적 추천 품질 가드 ─────────────────────────────────────────────────────
# 핵심 원칙: 기존 manual_ref 를 자동으로 강등(degrade)하지 않는다. 후보가 "명백히
# 더 낫다"고 판단될 때만 APPROVE_CANDIDATE 를 권장하고, 그 외에는 KEEP_EXISTING.
_COMMON_PAGE_HITS = 8   # 키워드가 이만큼 많은 페이지에 등장하면 후보 선택 신뢰도↓ (공통 페이지)
_LARGE_MOVE_PAGES = 30  # 이 이상 페이지가 이동하면 고위험


def _title_tokens(title: str) -> list[str]:
    """제목에서 한글 토큰(2자 이상)만 추출 — 후보 페이지 제목 일치 검사용."""
    toks = keyword_to_tokens(normalize_pdf_text(title or ""))
    return [t for t in toks if re.search(r"[가-힣]", t)]


def _visa_code_prefix(detailed_code: str) -> str:
    """'F-4-19' → 'F-4', 'E-7' → 'E-7'. 자격코드 강일치 검사용."""
    m = re.match(r"([A-Za-z]-?\d+)", (detailed_code or "").strip())
    return m.group(1) if m else ""


# title 강일치 판정에서 '단독'으로는 인정하지 않는 일반 업무어(정규화 후 단일 토큰 기준).
# 이 단어 하나만 페이지에 있다고 기존 페이지를 유효로 보면, 실제로 틀린 manual_ref 도
# KEEP_EXISTING 으로 숨어버리므로 제외한다.
_TITLE_STOPWORDS = {
    "신청", "요건", "대상", "서류", "변경", "연장", "등록", "체류",
    "사증", "외국인", "허가", "발급", "인정", "활동", "자격",
}

# 여러 페이지에 반복되는 일반 동작구/업무유형 정규화 문구. title 토큰이 이 중 하나여도
# '고유성'으로 인정하지 않는다(단독 KEEP 위험 차단). normalize_pdf_text 가 만들어내는
# 복합어 형태까지 포함한다(예: 근무처변경추가, 사증발급확인서).
_TITLE_GENERIC_PHRASES = {
    "체류기간연장", "외국인등록", "사증발급인정서", "사증발급확인서",
    "체류자격변경", "체류자격부여", "근무처변경", "근무처추가", "근무처변경추가",
    "체류자격외활동", "재입국허가", "외국인등록사항변경",
    "거소신고", "거소이전신고", "비자연장", "비자변경",
}


def _strong_title_match(title: str, page_text_lower: str) -> bool:
    """현재 페이지에 title 이 '강하게' 일치하는지 판정 (약한 토큰 1개로는 불인정).

    phrase(전체 문구) match 는 제거했다 — 일반 업무유형 문구가 여러 페이지에 반복돼
    틀린 manual_ref 를 KEEP 으로 숨길 위험이 있기 때문. 오직 '고유성 있는 토큰' 기준만 본다:
      (a) 공통어/일반업무구 제외 '의미 토큰' 2개 이상이 현재 페이지에 존재
      (b) 4글자 이상 고유 토큰(공통어/일반업무구 아님)이 현재 페이지에 존재
    """
    toks = _title_tokens(title)
    meaningful = [
        t for t in toks
        if t not in _TITLE_STOPWORDS and t not in _TITLE_GENERIC_PHRASES
    ]
    present = [t for t in meaningful if t.lower() in page_text_lower]
    if len(present) >= 2:                                                     # (a)
        return True
    if any(len(t) >= 4 and t.lower() in page_text_lower for t in meaningful):  # (b)
        return True
    return False


# 코드 비교용 정규화 — 공백/각종 하이픈·대시·중점·점 제거(소문자). PDF가 'F­1­15'(소프트
# 하이픈) 처럼 다른 글자로 코드를 렌더해도 'f115' 로 일치시키기 위함.
_CODE_STRIP = re.compile(r"[\s\-­‐‑‒–—―·.]")


def _code_norm(s: str) -> str:
    return _CODE_STRIP.sub("", (s or "").lower())


def _current_page_signals(
    pages: Optional[list[str]],
    current_pf: int,
    detailed_code: str,
    title: str,
) -> dict:
    """현재(사람이 정한) 페이지의 코드/제목 신호를 **분리** 판정.

    취약한 키워드 AND-검색과 독립적으로 현재 페이지 텍스트만 본다.
      - full_code_on_current   : full detailed_code(예 F-1-15/E-7-2/D-8-2)가 그대로 존재
      - family_code_on_current : 자격코드 패밀리(예 F-1/E-7)만 존재 (약한 신호)
      - title_strong_on_current: 고유성 있는 강한 title 일치(_strong_title_match)

    Returns: dict(위 3개 bool). KEEP 판단은 호출부에서 정책에 따라 결정한다.
    """
    out = {
        "full_code_on_current": False,
        "family_code_on_current": False,
        "title_strong_on_current": False,
    }
    if not pages or not (1 <= current_pf <= len(pages)):
        return out
    cur = pages[current_pf - 1]
    curl = cur.lower()
    cur_code = _code_norm(cur)

    dc_ns = _code_norm(detailed_code)
    if len(dc_ns) >= 2 and dc_ns in cur_code:
        out["full_code_on_current"] = True

    fam_ns = _code_norm(_visa_code_prefix(detailed_code))
    if fam_ns and fam_ns in cur_code:
        out["family_code_on_current"] = True

    if _strong_title_match(title, curl):
        out["title_strong_on_current"] = True

    return out


# decision: 운영 워크플로 상태. status 는 원시 분석 결과(PASS/PAGE_CHANGED/NOT_FOUND/SKIP).
# recommendation/confidence/risk 는 보수적 권고(자동 반영 아님).
def analyse_row(
    row_id: str,
    detailed_code: str,
    action_type: str,
    title: str,
    ref: dict,
) -> dict:
    """단일 manual_ref 엔트리를 분석해 결과 dict 반환 (보수적 품질 가드 포함)."""
    manual = ref.get("manual", "")
    current_pf = ref.get("page_from", 0)
    current_pt = ref.get("page_to", 0)
    match_text  = ref.get("match_text", "") or ""

    base = {
        "row_id":           row_id,
        "detailed_code":    detailed_code,
        "action_type":      action_type,
        "title":            title,
        "manual":           manual,
        "current_page_from": current_pf,
        "current_page_to":  current_pt,
        "found_page":       0,
        "found_pages":      [],
        "status":           "SKIP",
        "match_text":       match_text,
        "search_keyword":   "",
        "heading_snippet":  "",        # 후보 페이지 스니펫(하위호환)
        "current_snippet":  "",        # 기존 페이지 스니펫
        "candidate_snippet": "",       # 후보 페이지 스니펫
        "recommendation":   "",        # KEEP_EXISTING|APPROVE_CANDIDATE|NEEDS_MANUAL_PAGE|UNRESOLVED
        "confidence":       "",        # HIGH|MEDIUM|LOW
        "risk_flags":       [],        # large_move|weak_code_match|common_page|no_title_match|no_pdf_match
        "reason":           "",
        "decision":         "",        # 워크플로 상태(아래 7종). 미검토 후보=NEW_CANDIDATE
        "reviewed_candidate_page": None,  # 결정 시점의 후보 페이지(재실행 시 변경 감지)
        "candidate_changed": False,    # 재실행 후 후보가 바뀌면 True → 재검토 필요
        "manual_page_from": None,      # NEEDS_MANUAL_PAGE 직접 입력값
        "manual_page_to":   None,
        "auto_apply":       False,     # 폐기됨(자동 반영 금지) — 항상 False
        "reviewed":         False,
        "applied":          False,
    }

    if not match_text:
        base["status"] = "SKIP"
        return base

    keyword = extract_keyword(match_text)
    base["search_keyword"] = keyword
    if not keyword or len(keyword) < 2:
        base["status"] = "SKIP"
        return base

    found_pages = search_keyword_in_pdf(manual, keyword)
    base["found_pages"] = found_pages
    pages = _get_pdf_pages(manual)
    if pages and 1 <= current_pf <= len(pages):
        base["current_snippet"] = pages[current_pf - 1][:220].replace("\n", " ").strip()

    # ── 기존 페이지 유효성 가드 (취약 키워드 검색과 독립) ───────────────────────────
    # KEEP_EXISTING 으로 숨기는 조건은 '강한 신호'만 허용한다:
    #   (1) full detailed_code(예 F-1-15/E-7-2/D-8-2)가 현재 페이지에 존재
    #   (2) strong title match
    #   (3) candidate_page == current_page (아래 분기에서 처리)
    # family prefix(F-1/E-7 등)만 존재하는 경우는 KEEP 으로 숨기지 않고 검토로 보낸다
    # (family_code_only / weak_family_code_match risk 부여). 운영 반영은 explicit apply 로만.
    sig = _current_page_signals(pages, current_pf, detailed_code, title)
    if sig["full_code_on_current"] or sig["title_strong_on_current"]:
        evidence = [k for k in ("full_code_on_current", "title_strong_on_current") if sig[k]]
        base["status"] = "PASS"          # decision 공란 → 기본 미검토 목록에서 숨김
        base["decision"] = ""
        base["recommendation"] = "KEEP_EXISTING"
        base["confidence"] = "HIGH"
        base["risk_flags"] = ["current_still_valid"]
        if found_pages:                  # 참고용 후보만 표시 (대체 아님)
            closest = min(found_pages, key=lambda p: abs(p - current_pf))
            base["found_page"] = closest
            if pages and 1 <= closest <= len(pages):
                snip = pages[closest - 1][:220].replace("\n", " ").strip()
                base["heading_snippet"] = snip
                base["candidate_snippet"] = snip
        base["reason"] = (
            f"현재 p.{current_pf} 에 {'·'.join(evidence)} 존재 → 기존 manual_ref 유지 "
            f"(후보 페이지는 참고용, 자동 변경 안 함)."
        )
        return base

    # full code·strong title 없음 → KEEP 으로 숨기지 않는다. family prefix 만 있으면 weak
    # 신호로만 기록하고 검토 로직으로 넘긴다.
    extra_risk: list[str] = []
    if sig["family_code_on_current"]:
        extra_risk = ["family_code_only", "weak_family_code_match"]

    if not found_pages:
        base["status"] = "NOT_FOUND"
        base["decision"] = "UNRESOLVED"
        base["recommendation"] = "NEEDS_MANUAL_PAGE"
        base["confidence"] = "LOW"
        base["risk_flags"] = ["no_pdf_match"] + extra_risk
        base["reason"] = (
            "현재 페이지에 full code/strong title 없음"
            + (" (family code-prefix만 존재)" if extra_risk else "")
            + " + PDF 키워드 미발견 → 직접 페이지 확인 필요."
        )
        return base

    closest = min(found_pages, key=lambda p: abs(p - current_pf))
    base["found_page"] = closest
    if pages and 1 <= closest <= len(pages):
        snip = pages[closest - 1][:220].replace("\n", " ").strip()
        base["heading_snippet"] = snip
        base["candidate_snippet"] = snip

    if closest == current_pf:
        base["status"] = "PASS"            # 후보=현재 → 유지 (decision 공란 → 기본 숨김)
        base["recommendation"] = "KEEP_EXISTING"
        base["confidence"] = "HIGH"
        base["risk_flags"] = ["candidate_equals_current"]
        base["reason"] = "후보 페이지 = 현재 페이지 → 기존 유지 (변경 없음)."
        return base

    # ── 페이지 다름 → 보수적 품질 평가 ──
    base["status"] = "PAGE_CHANGED"
    base["decision"] = "NEW_CANDIDATE"
    page_diff = abs(closest - current_pf)
    cand_text = pages[closest - 1].lower() if (pages and 1 <= closest <= len(pages)) else ""
    old_still_matches = current_pf in found_pages   # 기존 페이지에 키워드가 여전히 존재

    risk: list[str] = []
    if len(found_pages) >= _COMMON_PAGE_HITS:
        risk.append("common_page")
    if page_diff >= _LARGE_MOVE_PAGES:
        risk.append("large_move")
    code_prefix = _visa_code_prefix(detailed_code)
    if code_prefix and code_prefix.lower().replace("-", "") not in cand_text.replace("-", ""):
        risk.append("weak_code_match")
    ttoks = _title_tokens(title)
    if ttoks and not any(t.lower() in cand_text for t in ttoks):
        risk.append("no_title_match")

    # family prefix 만 맞던 약한 신호(weak_family_code_match/family_code_only) 합류
    for f in extra_risk:
        if f not in risk:
            risk.append(f)

    if "common_page" in risk or "no_title_match" in risk:
        conf = "LOW"
    elif "large_move" in risk or "weak_code_match" in risk:
        conf = "MEDIUM"
    else:
        conf = "HIGH"
    base["risk_flags"] = risk
    base["confidence"] = conf

    if old_still_matches:
        # 기존 페이지가 여전히 유효 → 절대 자동 강등하지 않음
        base["recommendation"] = "KEEP_EXISTING"
        base["reason"] = (f"기존 p.{current_pf} 에 키워드가 여전히 존재 → 기존 유지 권장 "
                          f"(후보 p.{closest}, 강등 방지).")
    elif conf == "HIGH":
        base["recommendation"] = "APPROVE_CANDIDATE"
        base["reason"] = (f"후보 p.{closest} 코드/제목 강일치·이동폭/위험 낮음 → 후보 승인 검토. "
                          f"(이동 {page_diff}p)")
    else:
        # MEDIUM/LOW 후보로는 기존을 강등하지 않는다(보수적 기본값)
        base["recommendation"] = "KEEP_EXISTING"
        base["reason"] = (f"후보 신뢰도 {conf}, 위험 {risk or '없음'} → 기존 유지 권장 "
                          f"(자동 강등 방지, 이동 {page_diff}p).")
    return base


# ── 이전 결정 병합 ─────────────────────────────────────────────────────────────
_PERSISTED_DECISIONS = {
    "REVIEWED_KEEP_EXISTING", "REVIEWED_APPROVE_CANDIDATE",
    "REJECTED_BAD_CANDIDATE", "NEEDS_MANUAL_PAGE", "UNRESOLVED",
}


def _flag_recheck(r: dict, p: dict) -> None:
    """검토 당시 후보(reviewed_candidate_page)와 새 후보(found_page)가 다르면 결정은
    유지한 채 candidate_changed/needs_recheck/recheck_reason 만 표시(재검토 유도)."""
    prev = p.get("reviewed_candidate_page")
    new = r.get("found_page")
    reasons: list[str] = []
    if prev is not None and new and int(new) != int(prev):
        r["candidate_changed"] = True
        reasons.append(f"candidate page {prev}→{new}")
        if p.get("applied"):
            reasons.append("applied page may be stale")
    if reasons:
        r["needs_recheck"] = True
        r["recheck_reason"] = "; ".join(reasons)


def _merge_prior_decisions(results: list[dict]) -> None:
    """기존 manual_update_review.json 의 검토 결정을 새 분석 결과에 병합한다.

    - applied=True 행은 운영 반영 완료 → decision=APPLIED 로 보존.
    - 검토 결정(_PERSISTED_DECISIONS)은 그대로 보존 → 재검토 목록에 다시 안 뜸.
    - 후보 페이지가 직전 검토 시점과 달라졌으면 candidate_changed/needs_recheck 로 표시해
      재검토를 유도(결정은 유지하되 UI가 actionable 로 노출).
    - 이번 분석 결과에 더 이상 없는 row_id 의 검토/반영 결정은 버리지 않고 orphaned=True 로
      보존해 results 에 다시 추가한다(매뉴얼 개정으로 항목이 사라졌다 돌아오는 경우 대비).
    이 함수는 어떤 운영 DB(manual_ref)도 수정하지 않는다 — review JSON 병합만 수행."""
    if not OUT_JSON.exists():
        return
    try:
        prior = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    except Exception:
        return
    prior_map = {r.get("row_id"): r for r in prior.get("rows", []) if r.get("row_id")}

    for r in results:
        r.setdefault("candidate_changed", False)
        r.setdefault("needs_recheck", False)
        r.setdefault("recheck_reason", "")
        r.setdefault("orphaned", False)
        p = prior_map.get(r["row_id"])
        if not p:
            continue
        if p.get("applied"):
            r["applied"] = True
            r["reviewed"] = True
            r["decision"] = "APPLIED"
            r["reviewed_candidate_page"] = p.get("reviewed_candidate_page")
            _flag_recheck(r, p)
            continue
        prior_decision = p.get("decision", "")
        if prior_decision in _PERSISTED_DECISIONS:
            r["decision"] = prior_decision
            r["reviewed"] = True
            r["reviewed_candidate_page"] = p.get("reviewed_candidate_page")
            if p.get("manual_page_from") is not None:
                r["manual_page_from"] = p.get("manual_page_from")
                r["manual_page_to"] = p.get("manual_page_to")
            if p.get("decision_note"):
                r["decision_note"] = p["decision_note"]
            # 후보 변경 감지: 검토 당시 후보와 새 후보가 다르면 재검토 필요
            _flag_recheck(r, p)

    # orphaned 보존: 이번 결과에 없는 row_id 의 사람 결정/반영은 삭제하지 않고 보존
    existing_ids = {r["row_id"] for r in results}
    for rid, p in prior_map.items():
        if rid in existing_ids:
            continue
        if p.get("applied") or p.get("decision", "") in _PERSISTED_DECISIONS:
            orphan = dict(p)
            orphan["orphaned"] = True
            orphan["needs_recheck"] = True
            orphan["recheck_reason"] = "row no longer present in DB/analysis — decision preserved"
            results.append(orphan)


# ── 메인 ──────────────────────────────────────────────────────────────────────
def run(dry_run: bool = True, auto_apply: bool = False, report_only: bool = False) -> dict:
    raw = DB_PATH.read_bytes()
    db  = json.loads(raw.decode("utf-8"))
    rows = db.get("master_rows", [])

    results: list[dict] = []
    total_override = 0

    for row in rows:
        rid   = row.get("row_id", "")
        code  = row.get("detailed_code", "")
        action = row.get("action_type", "")
        title  = row.get("business_name", "")
        refs   = row.get("manual_ref") or []

        for ref in refs:
            if ref.get("match_type") != "manual_override":
                continue
            total_override += 1
            result = analyse_row(rid, code, action, title, ref)
            results.append(result)
            break  # row당 첫 번째 manual_override만

    # ── shared generic page: family_code_only(= full code/strong title 없이 family prefix만)
    #    행이 같은 (manual, current_page) 를 2개 이상 공유하면 generic 공유 페이지로 보고
    #    shared_generic_page risk 를 추가한다. (예: F-1 계열이 모두 p.355 복수재입국허가 공유) ──
    from collections import Counter as _Counter
    _fam_pages = _Counter(
        (r.get("manual"), r.get("current_page_from"))
        for r in results
        if "family_code_only" in (r.get("risk_flags") or [])
    )
    for r in results:
        if (
            "family_code_only" in (r.get("risk_flags") or [])
            and _fam_pages[(r.get("manual"), r.get("current_page_from"))] >= 2
            and "shared_generic_page" not in r["risk_flags"]
        ):
            r["risk_flags"].append("shared_generic_page")

    # 통계
    counts = {
        "PASS": 0, "PAGE_CHANGED_AUTO": 0, "PAGE_CHANGED_REVIEW": 0,
        "NOT_FOUND": 0, "SKIP": 0,
    }
    for r in results:
        s = r["status"]
        if s == "PASS":
            counts["PASS"] += 1
        elif s == "PAGE_CHANGED":
            if r["auto_apply"]:
                counts["PAGE_CHANGED_AUTO"] += 1
            else:
                counts["PAGE_CHANGED_REVIEW"] += 1
        elif s == "NOT_FOUND":
            counts["NOT_FOUND"] += 1
        elif s == "SKIP":
            counts["SKIP"] += 1

    now_iso = dt.datetime.now().isoformat()

    # auto_apply
    applied_ids: list[str] = []
    if auto_apply and not dry_run and not report_only:
        # 백업
        BACKUP.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        bk = BACKUP / f"immigration_guidelines_db_v2.manual_rematch_backup_{ts}.json"
        bk.write_bytes(raw)
        print(f"[backup] {bk.relative_to(ROOT)}")

        row_index = {r["row_id"]: r for r in rows}
        changed = False
        for res in results:
            if res["status"] == "PAGE_CHANGED" and res["auto_apply"] and not res["applied"]:
                db_row = row_index.get(res["row_id"])
                if db_row:
                    for ref in (db_row.get("manual_ref") or []):
                        if ref.get("match_type") == "manual_override":
                            old_pf = ref.get("page_from", 0)
                            ref["page_from"] = res["found_page"]
                            ref["page_to"]   = res["found_page"]
                            print(f"  [apply] {res['row_id']} {res['manual']} p.{old_pf} → p.{res['found_page']}")
                            break
                    changed = True
                    res["applied"]  = True
                    res["reviewed"] = True
                    applied_ids.append(res["row_id"])

        if changed:
            DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[save] DB updated: {len(applied_ids)} rows")

    # ── 이전 검토 결정 병합 (재실행 시 검토완료 항목이 다시 미검토로 돌아오지 않게) ──
    _merge_prior_decisions(results)

    # 리포트 저장
    out = {
        "last_run": now_iso,
        "total_override": total_override,
        "counts": counts,
        "rows": results,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[out] {OUT_JSON.relative_to(ROOT)} ({OUT_JSON.stat().st_size:,} bytes)")

    return {"counts": counts, "total_override": total_override, "applied": applied_ids, "last_run": now_iso}


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="manual_ref 페이지 변경 감지 스크립트")
    ap.add_argument("--auto-apply",  action="store_true", help="auto_apply 건 자동 DB 수정")
    ap.add_argument("--report-only", action="store_true", help="JSON 저장만, DB 수정 없음")
    ap.add_argument("--dry-run",     action="store_true", help="DB 수정 없음 (기본값)")
    args = ap.parse_args()

    is_dry  = not args.auto_apply
    result  = run(
        dry_run=is_dry,
        auto_apply=args.auto_apply,
        report_only=args.report_only,
    )
    c = result["counts"]

    print()
    print("=" * 60)
    print("MANUAL_REF REMATCH — SUMMARY")
    print("=" * 60)
    print(f"  Total manual_override rows : {result['total_override']}")
    print(f"  PASS                       : {c['PASS']}")
    print(f"  PAGE_CHANGED (auto)        : {c['PAGE_CHANGED_AUTO']}")
    print(f"  PAGE_CHANGED (review)      : {c['PAGE_CHANGED_REVIEW']}")
    print(f"  NOT_FOUND                  : {c['NOT_FOUND']}")
    print(f"  SKIP                       : {c['SKIP']}")
    if result["applied"]:
        print(f"  Applied                    : {len(result['applied'])} rows")
    mode = "APPLY" if args.auto_apply else "DRY-RUN"
    print(f"  Mode                       : {mode}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
