"""
매뉴얼 PDF 페이지 인덱서 v3 — 본문 전체 스캔 + 그룹화

v2 한계: 페이지 헤더만 스캔 → 본문에만 코드 표기된 매뉴얼(체류민원) 누락
v3 개선:
  1. 본문 전체에서 자격코드 등장 페이지 모두 인덱싱
  2. 같은 코드의 연속/근접 페이지를 섹션으로 묶기 (5페이지 이내 갭 허용)
  3. 갭이 큰 경우 별도 섹션으로 분리 (예: F-4 본 섹션 vs F-4-R 별도 섹션)
  4. 각 섹션 내에서 action 키워드 첫 등장 페이지 검색

매뉴얼별 최적화:
  - 사증민원: TOC 78개로 명확 → TOC 우선 + 보조로 본문 스캔
  - 체류민원: TOC 없음 → 본문 스캔만

산출물: backend/data/manuals/manual_index_v3.json
"""
from __future__ import annotations
import json, re, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from collections import defaultdict
import fitz

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

ROOT     = Path(__file__).parent.parent.parent
MANUALS  = ROOT / "backend" / "data" / "manuals"
INDEX_V3 = MANUALS / "manual_index_v3.json"

# 자격 코드: A-1, F-4, F-4-R, F-4-19, F-5-S1, H-2, H-2-5 등
_CODE_RE = re.compile(r"\(([A-Z]-\d+(?:-(?:\d+|[A-Z][\w]*))?)\)")
_CODE_RE_LOOSE = re.compile(r"\b([A-Z]-\d+(?:-(?:\d+|[A-Z][\w]*))?)\b")  # 괄호 없이도

ACTION_KEYWORDS = {
    "CHANGE":                    ["체류자격 변경", "변경허가", "체류자격변경", "자격변경"],
    "EXTEND":                    ["체류기간 연장", "연장허가", "체류기간연장", "기간연장"],
    "REGISTRATION":              ["외국인등록", "외국인 등록", "등록 신청"],
    "REENTRY":                   ["재입국허가", "재입국 허가", "재입국 신청"],
    "EXTRA_WORK":                ["체류자격외 활동", "체류자격 외 활동", "자격외활동", "시간제취업"],
    "WORKPLACE":                 ["근무처 변경", "근무처 추가"],
    "GRANT":                     ["체류자격 부여", "자격부여", "체류자격부여"],
    "VISA_CONFIRM":              ["사증발급인정서", "사증발급"],
    "ACTIVITY_EXTRA":            ["활동범위 확대", "단순노무 특례", "동일사업장 계속근무"],
    "DOMESTIC_RESIDENCE_REPORT": ["거소신고", "국내거소신고"],
    "APPLICATION_CLAIM":         ["사실증명", "직접신청"],
}

# 코드별 등장 페이지 그룹화: 갭 임계치 (페이지 수)
_SECTION_GAP_THRESHOLD = 8


def find_code_pages(doc: fitz.Document) -> dict[str, list[int]]:
    """모든 페이지에서 자격코드 등장 페이지 인덱싱.
    Returns: {"F-4": [528, 530, 537, ...], "F-4-R": [619, 621, 625, ...], ...}
    """
    code_pages: dict[str, set[int]] = defaultdict(set)
    for p in doc:
        text = p.get_text()
        for m in _CODE_RE.finditer(text):
            code_pages[m.group(1)].add(p.number + 1)
    return {c: sorted(ps) for c, ps in code_pages.items()}


def group_into_sections(pages: list[int], gap_threshold: int = _SECTION_GAP_THRESHOLD) -> list[tuple[int, int]]:
    """연속/근접 페이지들을 섹션으로 그룹화.
    Returns: [(page_from, page_to), ...]

    예: [528, 530, 537, 568, 577, 619, 621, 625]
        gap_threshold=8 → [(528, 577), (619, 625)]
    """
    if not pages:
        return []
    sorted_p = sorted(pages)
    sections = []
    start = sorted_p[0]
    prev = sorted_p[0]
    for p in sorted_p[1:]:
        if p - prev > gap_threshold:
            sections.append((start, prev))
            start = p
        prev = p
    sections.append((start, prev))
    return sections


def find_action_in_range(
    doc: fitz.Document,
    page_from: int,
    page_to: int,
    keywords: list[str],
) -> Optional[tuple[int, int, str]]:
    """페이지 범위 내에서 키워드 첫·마지막 등장 페이지 찾기.
    Returns: (first_page, last_page, matched_keyword) or None
    """
    first, last, kw_used = None, None, None
    for p_no in range(page_from, page_to + 1):
        if p_no - 1 >= len(doc):
            break
        text = doc[p_no - 1].get_text()
        for kw in keywords:
            if kw in text:
                if first is None:
                    first, kw_used = p_no, kw
                last = p_no
                break
    if first is None:
        return None
    return (first, last, kw_used)


def build_index_for_pdf(pdf_path: Path, manual_label: str) -> dict:
    """단일 PDF 인덱싱."""
    doc = fitz.open(pdf_path)
    code_pages = find_code_pages(doc)
    print(f"  [{manual_label}] 본문 스캔: {len(code_pages)} 코드, "
          f"평균 {sum(len(p) for p in code_pages.values())/max(1,len(code_pages)):.1f} 페이지/코드")

    sections_per_code: dict[str, list[dict]] = {}
    for code, pages in code_pages.items():
        groups = group_into_sections(pages)
        sections_per_code[code] = [
            {"page_from": pf, "page_to": pt, "occurrences": [p for p in pages if pf <= p <= pt]}
            for pf, pt in groups
        ]

    # action 인덱스: (code, action) → [{manual, page_from, page_to, match_text, section_pf, section_pt}]
    action_index: dict[str, list[dict]] = defaultdict(list)
    for code, sections in sections_per_code.items():
        for sec in sections:
            for action_type, kws in ACTION_KEYWORDS.items():
                hit = find_action_in_range(doc, sec["page_from"], sec["page_to"], kws)
                if hit is None:
                    continue
                first, last, kw = hit
                action_index[f"{code}|{action_type}"].append({
                    "manual":      manual_label,
                    "page_from":   first,
                    "page_to":     last,
                    "match_text":  kw,
                    "section_pf":  sec["page_from"],
                    "section_pt":  sec["page_to"],
                })

    # 코드 단위 인덱스 (action 매칭 못해도 섹션 자체는 알 수 있게)
    code_index: dict[str, list[dict]] = {}
    for code, sections in sections_per_code.items():
        code_index[code] = [
            {"manual": manual_label, "page_from": s["page_from"], "page_to": s["page_to"]}
            for s in sections
        ]

    total = len(doc)
    doc.close()
    return {
        "label":        manual_label,
        "total_pages":  total,
        "code_pages":   code_pages,
        "sections":     sections_per_code,
        "code_index":   code_index,
        "action_index": dict(action_index),
    }


def build_all() -> dict:
    """모든 매뉴얼 인덱스 빌드 + 통합."""
    targets = {
        "체류민원": MANUALS / "unlocked_체류민원.pdf",
        "사증민원": MANUALS / "unlocked_사증민원.pdf",
    }

    manuals_info = {}
    code_index_all = defaultdict(list)
    action_index_all = defaultdict(list)

    for label, path in targets.items():
        if not path.exists():
            print(f"[skip] {label}: {path} 없음"); continue
        info = build_index_for_pdf(path, label)
        manuals_info[label] = {
            "file":        str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
            "total_pages": info["total_pages"],
            "section_count_per_code": {c: len(s) for c, s in info["sections"].items()},
        }
        for c, entries in info["code_index"].items():
            code_index_all[c].extend(entries)
        for k, entries in info["action_index"].items():
            action_index_all[k].extend(entries)

    # 사증민원 자격 섹션 = VISA_CONFIRM 자동 등록
    if "사증민원" in manuals_info:
        path = targets["사증민원"]
        doc = fitz.open(path)
        cps = find_code_pages(doc)
        for code, pages in cps.items():
            for pf, pt in group_into_sections(pages):
                action_index_all[f"{code}|VISA_CONFIRM"].append({
                    "manual":     "사증민원",
                    "page_from":  pf,
                    "page_to":    pt,
                    "match_text": "사증발급(섹션)",
                    "section_pf": pf,
                    "section_pt": pt,
                })
        doc.close()

    # action_index 중복 제거 (같은 manual + page_from)
    for k, entries in action_index_all.items():
        seen = set()
        unique = []
        for e in entries:
            key = (e["manual"], e["page_from"])
            if key in seen: continue
            seen.add(key)
            unique.append(e)
        action_index_all[k] = unique

    result = {
        "manuals":      manuals_info,
        "code_index":   dict(code_index_all),
        "action_index": dict(action_index_all),
        "built_at":     datetime.now(timezone.utc).isoformat(),
    }
    INDEX_V3.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def lookup(detailed_code: str, action_type: str) -> list[dict]:
    """v3 lookup. (code, action) 정확 → prefix → 코드 단위 fallback."""
    if not INDEX_V3.exists():
        raise FileNotFoundError(f"인덱스 없음: {INDEX_V3}")
    data = json.loads(INDEX_V3.read_text(encoding="utf-8"))

    # 1. 정확
    key = f"{detailed_code}|{action_type}"
    if key in data["action_index"]:
        return [{**e, "match_type": "action_exact"} for e in data["action_index"][key]]

    # 2. prefix
    main = re.match(r"^([A-Z]-\d+)", detailed_code)
    if main:
        pkey = f"{main.group(1)}|{action_type}"
        if pkey in data["action_index"]:
            return [{**e, "match_type": "action_prefix"} for e in data["action_index"][pkey]]

    # 3. 코드 섹션
    if detailed_code in data["code_index"]:
        return [{**e, "match_type": "section_only", "match_text": "자격 섹션 전체"}
                for e in data["code_index"][detailed_code]]
    if main and main.group(1) in data["code_index"]:
        return [{**e, "match_type": "section_only", "match_text": "자격 섹션 전체"}
                for e in data["code_index"][main.group(1)]]
    return []


# ── CLI ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    p_lk = sub.add_parser("lookup")
    p_lk.add_argument("code"); p_lk.add_argument("action")
    sub.add_parser("stats")

    args = p.parse_args()
    if args.cmd == "build":
        result = build_all()
        print(f"\n[OK] {len(result['manuals'])} manuals")
        print(f"  code_index:   {len(result['code_index'])} codes")
        print(f"  action_index: {len(result['action_index'])} (code|action) pairs")
    elif args.cmd == "lookup":
        print(json.dumps(lookup(args.code, args.action), indent=2, ensure_ascii=False))
    elif args.cmd == "stats":
        if not INDEX_V3.exists():
            print("인덱스 없음"); sys.exit(1)
        data = json.loads(INDEX_V3.read_text(encoding="utf-8"))
        print(f"manuals: {len(data['manuals'])}")
        print(f"codes:   {len(data['code_index'])}")
        print(f"action:  {len(data['action_index'])}")
        action_count = defaultdict(int)
        for k in data["action_index"]:
            _, a = k.split("|"); action_count[a] += 1
        print("\n액션별:")
        for a in sorted(action_count, key=lambda x: -action_count[x]):
            print(f"  {a:30}: {action_count[a]:>3}")
