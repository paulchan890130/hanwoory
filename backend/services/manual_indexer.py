"""
매뉴얼 PDF 페이지 인덱서

각 매뉴얼 PDF를 분석하여 체류자격 코드 → 페이지 범위 인덱스를 생성.
LLM 호출 없이 PDF 메타데이터(TOC) + 페이지 텍스트 패턴 매칭만 사용.

전략:
  - 사증민원: PDF TOC가 충분 → TOC를 직접 파싱
  - 체류민원: TOC 없음 → 페이지별 텍스트 스캔하여 "X. 명칭(Y-Z)" 패턴 추출

산출물: backend/data/manuals/manual_index.json
  {
    "manuals": {
      "사증민원": {"file": "...", "total_pages": 482, "entries": [...]},
      "체류민원": {"file": "...", "total_pages": 764, "entries": [...]}
    },
    "code_index": {
      "A-1": [{"manual": "사증민원", "page_from": 10, "page_to": 12, "title": "외 교(A-1)"}, ...],
      "F-4": [...],
      ...
    },
    "built_at": "2026-04-30T..."
  }

활용:
  - row의 `detailed_code`를 키로 code_index lookup
  - 결과로 row의 `manual_ref` 필드 채움
"""
from __future__ import annotations
import json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import fitz  # PyMuPDF

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

ROOT    = Path(__file__).parent.parent.parent
MANUALS = ROOT / "backend" / "data" / "manuals"
INDEX   = MANUALS / "manual_index.json"

# 자격 코드 패턴: A-1, A-2, B-1, B-2, C-1, C-3, C-3-1, ..., F-4-19, F-5-S1, F-4-R, H-2, H-2-5
_CODE_RE = re.compile(r"\(([A-Z]-\d+(?:-(?:\d+|[A-Z][\w]*))?)\)")
# 한글 명칭 + 코드 패턴: "외 교(A-1)" / "회화지도(E-2)" / "1. 외교(A-1)"
_TITLE_CODE_RE = re.compile(r"(?:\d+\.\s*)?([가-힣\s]+?)\s*\(([A-Z]-\d+(?:-(?:\d+|[A-Z][\w]*))?)\)")


def parse_toc_entries(doc: fitz.Document) -> list[dict]:
    """PDF TOC를 코드와 페이지 매핑 리스트로 변환."""
    toc = doc.get_toc()
    entries = []
    for level, title, page in toc:
        title = title.strip()
        for m in _CODE_RE.finditer(title):
            entries.append({
                "code":  m.group(1),
                "title": title,
                "page":  page,
                "level": level,
                "source": "toc",
            })
    return entries


def scan_pages_for_codes(
    doc: fitz.Document,
    *,
    header_only: bool = True,
    header_height_ratio: float = 0.18,
) -> list[dict]:
    """
    각 페이지를 스캔하여 자격 코드가 등장하는 페이지를 모두 기록.

    header_only=True: 페이지 상단(header_height_ratio 만큼)에 코드가 있을 때만 기록
                     — 본문 인용은 제외하여 "해당 자격 시작 페이지" 만 잡음.
    """
    found = []
    for page in doc:
        text = page.get_text()
        if header_only:
            # 페이지 상단 영역만 필터 (page rect 기준)
            rect = page.rect
            header_rect = fitz.Rect(0, 0, rect.width, rect.height * header_height_ratio)
            text = page.get_text(clip=header_rect)

        # 헤더에 코드가 있으면 기록
        for m in _TITLE_CODE_RE.finditer(text):
            title = m.group(1).strip()
            code = m.group(2)
            # 너무 일반적인 false positive 제외
            if len(title) < 1 or len(title) > 30:
                continue
            found.append({
                "code":   code,
                "title":  f"{title}({code})",
                "page":   page.number + 1,
                "source": "header_scan",
            })
            break  # 페이지당 첫 매치만 (시작 페이지 기준)
    return found


def consolidate_entries(entries: list[dict]) -> list[dict]:
    """
    같은 코드의 연속/중복 페이지를 정리:
      - 같은 코드는 첫 등장 페이지를 page_from, 다음 코드 시작 직전을 page_to
      - 단, 같은 코드 여러 번 등장 시 모두 별도 엔트리 (예: F-4 여러 위치)
    """
    if not entries:
        return []
    sorted_e = sorted(entries, key=lambda e: e["page"])
    consolidated = []
    for i, e in enumerate(sorted_e):
        page_from = e["page"]
        # 다음 다른 코드 시작 페이지 찾기 (또는 EOF)
        page_to = None
        for j in range(i+1, len(sorted_e)):
            if sorted_e[j]["page"] > page_from:
                page_to = sorted_e[j]["page"] - 1
                break
        consolidated.append({
            "code":      e["code"],
            "title":     e["title"],
            "page_from": page_from,
            "page_to":   page_to,
            "source":    e["source"],
        })
    return consolidated


def build_index(
    pdf_path: str | Path,
    *,
    use_toc: bool = True,
    header_scan: bool = True,
) -> dict:
    """단일 PDF를 인덱싱. TOC + 헤더 스캔 결합."""
    pdf_path = Path(pdf_path).resolve()
    doc = fitz.open(pdf_path)
    entries = []
    if use_toc:
        entries.extend(parse_toc_entries(doc))
    if header_scan:
        entries.extend(scan_pages_for_codes(doc))

    # 중복 제거 (같은 code+page는 1개만)
    seen = set()
    unique = []
    for e in entries:
        key = (e["code"], e["page"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)

    consolidated = consolidate_entries(unique)
    total = len(doc)
    doc.close()

    return {
        "file": str(pdf_path.relative_to(ROOT) if pdf_path.is_relative_to(ROOT) else pdf_path),
        "total_pages": total,
        "entries": consolidated,
    }


def build_all() -> dict:
    """매뉴얼 폴더의 모든 unlocked_*.pdf 인덱싱 + 통합 code_index 생성."""
    manuals = {}
    code_index: dict[str, list[dict]] = {}

    targets = {
        "체류민원": MANUALS / "unlocked_체류민원.pdf",
        "사증민원": MANUALS / "unlocked_사증민원.pdf",
    }
    for label, path in targets.items():
        if not path.exists():
            print(f"[skip] {label}: {path} 없음")
            continue
        info = build_index(path)
        manuals[label] = info
        for e in info["entries"]:
            code_index.setdefault(e["code"], []).append({
                "manual":    label,
                "page_from": e["page_from"],
                "page_to":   e["page_to"],
                "title":     e["title"],
                "source":    e["source"],
            })

    result = {
        "manuals":    manuals,
        "code_index": code_index,
        "built_at":   datetime.now(timezone.utc).isoformat(),
    }

    INDEX.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return result


def lookup(detailed_code: str) -> list[dict]:
    """detailed_code (예: 'F-4-19') 로 매뉴얼 페이지 찾기.

    매칭 우선순위:
      1. 정확 매칭 (F-4-19 → F-4-19)
      2. prefix 매칭 (F-4-19 → F-4)
      3. 메인 코드 매칭 (F-4-R → F-4)
    """
    if not INDEX.exists():
        raise FileNotFoundError(f"인덱스 파일 없음: {INDEX} (먼저 build_all() 실행)")
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    code_index = data["code_index"]

    # 1. 정확 매칭
    if detailed_code in code_index:
        return code_index[detailed_code]

    # 2. prefix 매칭 — F-4-19, F-4-R, F-4-S1 등 → F-4 의 페이지에서 찾음
    main_code = re.match(r"^([A-Z]-\d+)", detailed_code)
    if main_code:
        m = main_code.group(1)
        if m in code_index:
            return code_index[m]

    return []


# ── CLI ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="매뉴얼 PDF 인덱서")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("build", help="모든 매뉴얼 인덱스 빌드")

    p_lookup = sub.add_parser("lookup", help="코드로 페이지 찾기")
    p_lookup.add_argument("code")

    p_stats = sub.add_parser("stats", help="인덱스 통계")

    args = p.parse_args()
    if args.cmd == "build":
        result = build_all()
        print(f"[OK] {len(result['manuals'])} manuals, {len(result['code_index'])} unique codes")
        for label, info in result["manuals"].items():
            print(f"  {label}: {info['total_pages']} pages, {len(info['entries'])} entries")
    elif args.cmd == "lookup":
        result = lookup(args.code)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.cmd == "stats":
        if not INDEX.exists():
            print("인덱스 파일 없음. 먼저 build."); sys.exit(1)
        data = json.loads(INDEX.read_text(encoding="utf-8"))
        print(f"manuals: {len(data['manuals'])}, codes: {len(data['code_index'])}")
        codes = sorted(data['code_index'].keys())
        # 카테고리별 그룹
        from collections import defaultdict
        groups = defaultdict(list)
        for c in codes:
            groups[c[:1]].append(c)
        for letter in sorted(groups):
            print(f"  {letter}: {len(groups[letter])} codes — {', '.join(groups[letter][:8])}{'...' if len(groups[letter])>8 else ''}")
