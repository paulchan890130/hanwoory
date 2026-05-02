"""
자격별 LLM 작업 청크 빌더 v2 — v6 인덱스 활용

자격(예: F-5)에 대해:
  - v6 sub-category 정식 섹션 + 일반 섹션 모두 통합
  - 매뉴얼 텍스트 추출 (체류민원 + 사증민원)
  - 편람은 같은 자격코드 검색
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from collections import defaultdict
import fitz

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH    = ROOT / "backend" / "data" / "immigration_guidelines_db_v2.json"
PYEONRAM   = ROOT / "analysis" / "클로드" / "221230 체류관리편람.pdf"
MANUAL_R   = ROOT / "backend" / "data" / "manuals" / "unlocked_체류민원.pdf"
MANUAL_V   = ROOT / "backend" / "data" / "manuals" / "unlocked_사증민원.pdf"
INDEX_V6   = ROOT / "backend" / "data" / "manuals" / "manual_index_v6.json"
OUT_PATH   = ROOT / "backend" / "data" / "manuals" / "llm_chunks_v2.json"


def find_pages_with_code_pyeonram(doc: fitz.Document, code: str, max_pages: int = 100) -> list[int]:
    """편람에서 자격코드 등장 페이지."""
    pages = []
    code_re = re.compile(rf"[\(〔]?{re.escape(code)}[\)〕]?")
    for p in doc:
        text = p.get_text()
        # F-5 같은 짧은 코드는 false positive 많으니 컨텍스트 확인
        if re.search(rf"\b{re.escape(code)}\b", text):
            pages.append(p.number + 1)
            if len(pages) >= max_pages: break
    return pages


def cluster_pages(pages: list[int], gap: int = 8) -> list[tuple[int, int]]:
    if not pages: return []
    pages = sorted(pages)
    clusters = []; cur = [pages[0]]
    for p in pages[1:]:
        if p - cur[-1] > gap:
            clusters.append((cur[0], cur[-1])); cur = [p]
        else:
            cur.append(p)
    clusters.append((cur[0], cur[-1]))
    return clusters


def extract_text_pages(doc: fitz.Document, pf: int, pt: int, max_chars: int = 25000) -> str:
    parts = []; total = 0
    for p_no in range(pf, pt + 1):
        if p_no - 1 >= len(doc): break
        text = doc[p_no - 1].get_text()
        chunk = f"\n----- p.{p_no} -----\n{text}"
        if total + len(chunk) > max_chars:
            parts.append(chunk[:max_chars - total]); break
        parts.append(chunk); total += len(chunk)
    return "".join(parts)


def get_v6_section_range(idx_data: dict, main_code: str, manual_label: str) -> tuple[int, int] | None:
    """v6 인덱스에서 main_code + sub-category의 통합 페이지 범위."""
    ranges = []
    for code, entries in idx_data["code_index"].items():
        if code == main_code or code.startswith(main_code + "-"):
            for e in entries:
                if e["manual"] == manual_label:
                    ranges.append((e["page_from"], e["page_to"]))
    if not ranges: return None
    return (min(r[0] for r in ranges), max(r[1] for r in ranges))


def build():
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    rows = db["master_rows"]
    v6 = json.loads(INDEX_V6.read_text(encoding="utf-8"))

    rows_by_main: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        code = r.get("detailed_code", "").strip()
        if not code:
            rows_by_main["_NO_CODE"].append(r); continue
        m = re.match(r"^([A-Z]-\d+)", code)
        rows_by_main[m.group(1) if m else code].append(r)

    print("PDFs 열기...")
    pyeon = fitz.open(PYEONRAM)
    man_r = fitz.open(MANUAL_R)
    man_v = fitz.open(MANUAL_V)

    chunks = {}
    for main_code, code_rows in sorted(rows_by_main.items()):
        if main_code == "_NO_CODE": continue
        print(f"  {main_code}: {len(code_rows)} rows")

        chunk = {
            "main_code": main_code,
            "rows": [{
                "row_id":          r["row_id"],
                "detailed_code":   r.get("detailed_code", ""),
                "action_type":     r.get("action_type", ""),
                "business_name":   r.get("business_name", ""),
                "overview_short":  r.get("overview_short", ""),
                "form_docs":       r.get("form_docs", ""),
                "supporting_docs": r.get("supporting_docs", ""),
                "fee_rule":        r.get("fee_rule", ""),
                "exceptions_summary": r.get("exceptions_summary", ""),
                "practical_notes": r.get("practical_notes", ""),
                "manual_ref":      r.get("manual_ref", []),
            } for r in code_rows],
            "manual_체류민원": {},
            "manual_사증민원": {},
            "pyeonram":        {},
        }

        # 매뉴얼: v6 인덱스로 통합 섹션
        rng_r = get_v6_section_range(v6, main_code, "체류민원")
        if rng_r:
            pf, pt = rng_r
            chunk["manual_체류민원"] = {
                "pages": f"{pf}-{pt}", "page_count": pt - pf + 1,
                "text": extract_text_pages(man_r, pf, pt, max_chars=25000),
            }
        rng_v = get_v6_section_range(v6, main_code, "사증민원")
        if rng_v:
            pf, pt = rng_v
            chunk["manual_사증민원"] = {
                "pages": f"{pf}-{pt}", "page_count": pt - pf + 1,
                "text": extract_text_pages(man_v, pf, pt, max_chars=18000),
            }

        # 편람: 자격코드 등장 페이지 가장 큰 클러스터
        py_pages = find_pages_with_code_pyeonram(pyeon, main_code)
        py_clusters = cluster_pages(py_pages, gap=10)
        if py_clusters:
            biggest = max(py_clusters, key=lambda c: c[1] - c[0])
            pf, pt = biggest
            chunk["pyeonram"] = {
                "pages": f"{pf}-{pt}", "page_count": pt - pf + 1,
                "text": extract_text_pages(pyeon, pf, pt, max_chars=18000),
            }

        chunks[main_code] = chunk

    pyeon.close(); man_r.close(); man_v.close()
    OUT_PATH.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] {len(chunks)} 청크 → {OUT_PATH}")
    print(f"  파일 크기: {OUT_PATH.stat().st_size:,} bytes")
    return chunks


if __name__ == "__main__":
    build()
