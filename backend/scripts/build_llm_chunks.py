"""
자격별 LLM 작업 청크 빌더

각 자격코드(또는 자격코드 그룹)에 대해:
  - DB의 해당 row들
  - 매뉴얼(체류민원·사증민원) 관련 페이지 텍스트
  - 편람 관련 페이지 텍스트
를 묶어 backend/data/manuals/llm_chunks.json 으로 저장.

LLM 처리 단계 (다음 스크립트):
  - 각 청크를 Anthropic API에 전달
  - 정답 매뉴얼 페이지 + 편람 기반 실무 팁 + DB 수정사항 받음
  - 결과를 DB에 패치
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
OUT_PATH   = ROOT / "backend" / "data" / "manuals" / "llm_chunks.json"

# 자격코드 패턴
_CODE_RE = re.compile(r"[\(〔]([A-Z]-\d+(?:-(?:\d+|[A-Z][\w]*))?)[\)〕]")


def find_pages_with_code(doc: fitz.Document, code: str, max_pages: int = 50) -> list[int]:
    """자격코드가 등장하는 페이지 번호 (1-기반)."""
    pages = []
    code_re = re.compile(rf"[\(〔]{re.escape(code)}[\)〕]")
    for p in doc:
        if code_re.search(p.get_text()):
            pages.append(p.number + 1)
            if len(pages) >= max_pages:
                break
    return pages


def cluster_pages(pages: list[int], gap: int = 5) -> list[tuple[int, int]]:
    """연속 페이지 그룹화."""
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


def extract_text_pages(doc: fitz.Document, pf: int, pt: int, max_chars: int = 8000) -> str:
    """페이지 범위 텍스트 추출 (max_chars 한계)."""
    parts = []
    total = 0
    for p_no in range(pf, pt + 1):
        if p_no - 1 >= len(doc): break
        text = doc[p_no - 1].get_text()
        header = f"\n----- p.{p_no} -----\n"
        chunk = header + text
        if total + len(chunk) > max_chars:
            chunk = chunk[: max_chars - total]
            parts.append(chunk); break
        parts.append(chunk)
        total += len(chunk)
    return "".join(parts)


def build_chunks() -> dict:
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    rows = db["master_rows"]

    # 자격별 row 그룹화 (detailed_code 기반, no_code는 별도)
    rows_by_code: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        code = r.get("detailed_code", "").strip()
        if not code:
            rows_by_code["_NO_CODE"].append(r)
            continue
        # 메인 코드만 추출 (F-4-19 → F-4)
        main = re.match(r"^([A-Z]-\d+)", code)
        key = main.group(1) if main else code
        rows_by_code[key].append(r)

    # PDFs
    print("PDFs 열기...")
    pyeon = fitz.open(PYEONRAM)
    man_r = fitz.open(MANUAL_R)
    man_v = fitz.open(MANUAL_V)

    chunks = {}
    for main_code, code_rows in sorted(rows_by_code.items()):
        if main_code == "_NO_CODE":
            continue
        print(f"  {main_code}: {len(code_rows)} rows")

        # 매뉴얼 페이지 (이 자격코드)
        m_r_pages = find_pages_with_code(man_r, main_code)
        m_v_pages = find_pages_with_code(man_v, main_code)
        py_pages  = find_pages_with_code(pyeon, main_code)

        m_r_clusters = cluster_pages(m_r_pages)
        m_v_clusters = cluster_pages(m_v_pages)
        py_clusters  = cluster_pages(py_pages)

        # 가장 큰 클러스터만 텍스트 추출
        def biggest(clusters):
            if not clusters: return None
            return max(clusters, key=lambda c: c[1] - c[0])

        chunk = {
            "main_code": main_code,
            "rows": [
                {
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
                }
                for r in code_rows
            ],
            "manual_체류민원": {},
            "manual_사증민원": {},
            "pyeonram":        {},
        }
        if m_r_clusters:
            pf, pt = biggest(m_r_clusters)
            chunk["manual_체류민원"] = {
                "pages":    f"{pf}-{pt}",
                "page_count": pt - pf + 1,
                "text":     extract_text_pages(man_r, pf, pt, max_chars=15000),
            }
        if m_v_clusters:
            pf, pt = biggest(m_v_clusters)
            chunk["manual_사증민원"] = {
                "pages":    f"{pf}-{pt}",
                "page_count": pt - pf + 1,
                "text":     extract_text_pages(man_v, pf, pt, max_chars=12000),
            }
        if py_clusters:
            pf, pt = biggest(py_clusters)
            chunk["pyeonram"] = {
                "pages":    f"{pf}-{pt}",
                "page_count": pt - pf + 1,
                "text":     extract_text_pages(pyeon, pf, pt, max_chars=15000),
            }

        chunks[main_code] = chunk

    pyeon.close(); man_r.close(); man_v.close()

    # 저장
    OUT_PATH.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] {len(chunks)} 자격코드 청크 → {OUT_PATH}")
    print(f"  파일 크기: {OUT_PATH.stat().st_size:,} bytes")
    return chunks


if __name__ == "__main__":
    build_chunks()
