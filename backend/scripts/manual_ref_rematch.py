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
import re
import sys
from pathlib import Path
from typing import Optional

ROOT     = Path(__file__).parent.parent.parent
DB_PATH  = ROOT / "backend" / "data" / "immigration_guidelines_db_v2.json"
MANUALS  = ROOT / "backend" / "data" / "manuals"
BACKUP   = ROOT / "backend" / "data" / "backups"
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


# ── 분석 ─────────────────────────────────────────────────────────────────────
def analyse_row(
    row_id: str,
    detailed_code: str,
    action_type: str,
    title: str,
    ref: dict,
) -> dict:
    """단일 manual_ref 엔트리를 분석해 결과 dict 반환."""
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
        "heading_snippet":  "",
        "auto_apply":       False,
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

    if not found_pages:
        base["status"] = "NOT_FOUND"
        return base

    # 가장 가까운 페이지 선택
    closest = min(found_pages, key=lambda p: abs(p - current_pf))
    base["found_page"] = closest

    # heading snippet
    pages = _get_pdf_pages(manual)
    if pages and 1 <= closest <= len(pages):
        snippet = pages[closest - 1][:200].replace("\n", " ").strip()
        base["heading_snippet"] = snippet

    if closest == current_pf:
        base["status"] = "PASS"
        return base

    # 페이지 다름
    base["status"] = "PAGE_CHANGED"
    page_diff = abs(closest - current_pf)
    # auto_apply: 찾은 페이지 1개이고 차이 50 이내
    if len(found_pages) == 1 and page_diff <= 50:
        base["auto_apply"] = True

    return base


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
