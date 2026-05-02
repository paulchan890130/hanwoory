"""
매뉴얼 PDF 페이지 인덱서 v2 — (자격, action_type) 정밀 매핑

v1 한계: 자격 코드 단위 매핑만 가능 (F-4 → 페이지 528~)
v2 개선:
  1. 자격 섹션 경계 식별 (연속 페이지에 같은 자격코드 헤더 등장 → 섹션)
  2. 섹션 내 action 키워드 첫 등장 페이지 검색
  3. (detailed_code, action_type) → 정밀 페이지

매뉴얼 구조 차이:
  - 사증민원: TOC 78개로 자격별 잘 분류됨, 모두 사증발급 절차
  - 체류민원: 자격별 섹션 안에 변경/연장/등록 통합 서술 → 키워드 검색 필요

산출물: backend/data/manuals/manual_index_v2.json
  {
    "manuals": {...},
    "code_index": {"F-4": [...]},  # v1 호환
    "action_index": {
      "F-4|CHANGE":       [{"manual": "체류민원", "page_from": 245, "page_to": 250, "match_text": "체류자격 변경허가"}],
      "F-4|EXTEND":       [...],
      "F-4|REGISTRATION": [...],
      ...
    },
    "built_at": "..."
  }
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
INDEX_V2 = MANUALS / "manual_index_v2.json"

_CODE_RE = re.compile(r"\(([A-Z]-\d+(?:-(?:\d+|[A-Z][\w]*))?)\)")

# action_type → 매뉴얼 검색 키워드
ACTION_KEYWORDS = {
    "CHANGE":                    ["체류자격 변경", "변경허가", "체류자격변경"],
    "EXTEND":                    ["체류기간 연장", "연장허가", "체류기간연장"],
    "REGISTRATION":              ["외국인등록", "등록 신청", "외국인 등록"],
    "REENTRY":                   ["재입국허가", "재입국 허가"],
    "EXTRA_WORK":                ["체류자격외 활동", "체류자격 외 활동", "자격외활동", "시간제취업"],
    "WORKPLACE":                 ["근무처 변경", "근무처 추가"],
    "GRANT":                     ["체류자격 부여", "자격부여"],
    "VISA_CONFIRM":              ["사증발급인정서", "사증발급"],
    "ACTIVITY_EXTRA":            ["활동범위 확대", "단순노무 특례", "동일사업장 계속근무"],
    "DOMESTIC_RESIDENCE_REPORT": ["거소신고", "국내거소신고"],
    "APPLICATION_CLAIM":         ["사실증명", "직접신청"],
}


def detect_code_in_top(page, top_ratio: float = 0.15) -> Optional[str]:
    """페이지 상단 영역에서 자격코드를 추출."""
    rect = page.rect
    top = fitz.Rect(0, 0, rect.width, rect.height * top_ratio)
    text = page.get_text(clip=top)
    m = _CODE_RE.search(text)
    if m:
        return m.group(1)
    return None


def find_quality_sections(pdf_path: Path) -> list[dict]:
    """
    매뉴얼에서 자격별 섹션을 식별.

    각 페이지의 상단 헤더에서 자격코드를 추출하고, 같은 코드의 연속 페이지를
    하나의 섹션으로 묶음.
    """
    doc = fitz.open(pdf_path)
    page_codes = []
    for p in doc:
        code = detect_code_in_top(p)
        page_codes.append(code)

    # 연속 페이지 묶기
    sections = []
    i = 0
    while i < len(page_codes):
        code = page_codes[i]
        if not code:
            i += 1; continue
        start = i
        while i < len(page_codes) and (page_codes[i] == code or page_codes[i] is None):
            i += 1
        # 끝쪽 None은 잘라내기 — 마지막 같은 코드까지만
        end = start
        for j in range(i-1, start-1, -1):
            if page_codes[j] == code:
                end = j; break
        sections.append({
            "code":      code,
            "page_from": start + 1,
            "page_to":   end + 1,
        })

    doc.close()
    return sections


def find_action_pages_in_range(
    doc: fitz.Document,
    page_from: int,
    page_to: int,
    keywords: list[str],
) -> list[tuple[int, str]]:
    """
    페이지 범위 내에서 키워드 첫 등장을 찾음.
    Returns: [(page_no, matched_keyword), ...]
    """
    hits = []
    for p_no in range(page_from, page_to + 1):
        if p_no - 1 >= len(doc): break
        text = doc[p_no - 1].get_text()
        for kw in keywords:
            if kw in text:
                hits.append((p_no, kw))
                break  # 한 페이지당 하나
    return hits


def build_action_index(pdf_path: Path, manual_label: str) -> tuple[list[dict], dict]:
    """
    자격 섹션 + (자격, action) 정밀 매핑.

    Returns:
        (sections, action_index) — action_index 키는 'F-4|CHANGE' 형식
    """
    sections = find_quality_sections(pdf_path)
    print(f"  [{manual_label}] 자격 섹션 {len(sections)}개 식별")

    doc = fitz.open(pdf_path)
    action_index = defaultdict(list)

    for sec in sections:
        code = sec["code"]
        pf, pt = sec["page_from"], sec["page_to"]
        for action_type, kws in ACTION_KEYWORDS.items():
            hits = find_action_pages_in_range(doc, pf, pt, kws)
            if not hits:
                continue
            # 첫 매치를 (자격,action)의 페이지 시작으로
            first_page, first_kw = hits[0]
            # 다른 action의 매치가 더 이른 페이지면 그 직전까지를 종료로
            # 단순화: 이 섹션 안에서 같은 action 키워드가 연속된 마지막 페이지를 page_to
            last_page = first_page
            for p_no, _ in hits:
                if p_no - last_page <= 5:  # 5페이지 이내 연속이면 같은 영역
                    last_page = p_no
                else:
                    break
            action_index[f"{code}|{action_type}"].append({
                "manual":      manual_label,
                "page_from":   first_page,
                "page_to":     last_page,
                "match_text":  first_kw,
                "section_pf":  pf,
                "section_pt":  pt,
            })

    doc.close()
    return sections, dict(action_index)


def build_all_v2() -> dict:
    """모든 매뉴얼 v2 인덱스 빌드."""
    targets = {
        "체류민원": MANUALS / "unlocked_체류민원.pdf",
        "사증민원": MANUALS / "unlocked_사증민원.pdf",
    }

    manuals_info = {}
    code_index = defaultdict(list)
    action_index = defaultdict(list)

    for label, path in targets.items():
        if not path.exists():
            print(f"[skip] {label}: {path} 없음")
            continue
        sections, ai = build_action_index(path, label)
        doc = fitz.open(path)
        manuals_info[label] = {
            "file":        str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
            "total_pages": len(doc),
            "sections":    sections,
        }
        doc.close()

        # 자격 코드 단위 인덱스 (v1 호환)
        for sec in sections:
            code_index[sec["code"]].append({
                "manual":    label,
                "page_from": sec["page_from"],
                "page_to":   sec["page_to"],
            })

        # 액션 인덱스 통합
        for key, entries in ai.items():
            action_index[key].extend(entries)

    # 사증민원의 모든 자격 섹션은 action_type=VISA_CONFIRM 으로도 등록
    if "사증민원" in manuals_info:
        for sec in manuals_info["사증민원"]["sections"]:
            key = f"{sec['code']}|VISA_CONFIRM"
            action_index[key].append({
                "manual":      "사증민원",
                "page_from":   sec["page_from"],
                "page_to":     sec["page_to"],
                "match_text":  "사증발급(섹션 전체)",
                "section_pf":  sec["page_from"],
                "section_pt":  sec["page_to"],
            })

    result = {
        "manuals":      manuals_info,
        "code_index":   dict(code_index),
        "action_index": dict(action_index),
        "built_at":     datetime.now(timezone.utc).isoformat(),
    }
    INDEX_V2.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return result


def lookup_v2(detailed_code: str, action_type: str) -> list[dict]:
    """(코드, action) 정밀 lookup. 없으면 prefix → 코드 단위 fallback."""
    if not INDEX_V2.exists():
        raise FileNotFoundError(f"인덱스 없음: {INDEX_V2}")
    data = json.loads(INDEX_V2.read_text(encoding="utf-8"))

    # 1. 정확 매칭 (자격, action)
    key = f"{detailed_code}|{action_type}"
    if key in data["action_index"]:
        return data["action_index"][key]

    # 2. prefix 매칭 (F-4-19|CHANGE → F-4|CHANGE)
    main = re.match(r"^([A-Z]-\d+)", detailed_code)
    if main:
        prefix_key = f"{main.group(1)}|{action_type}"
        if prefix_key in data["action_index"]:
            return data["action_index"][prefix_key]

    # 3. 자격 코드 단위 (v1 호환) — action 정보 없이 섹션 전체
    if detailed_code in data["code_index"]:
        return [{
            **e, "match_text": "자격 섹션 전체 (action별 분리 안됨)"
        } for e in data["code_index"][detailed_code]]
    if main and main.group(1) in data["code_index"]:
        return [{
            **e, "match_text": "자격 섹션 전체 (action별 분리 안됨)"
        } for e in data["code_index"][main.group(1)]]

    return []


# ── CLI ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    p_lk = sub.add_parser("lookup")
    p_lk.add_argument("code")
    p_lk.add_argument("action")
    sub.add_parser("stats")

    args = p.parse_args()
    if args.cmd == "build":
        result = build_all_v2()
        print(f"\n[OK] {len(result['manuals'])} manuals")
        print(f"  code_index: {len(result['code_index'])} codes")
        print(f"  action_index: {len(result['action_index'])} (code|action) pairs")
    elif args.cmd == "lookup":
        print(json.dumps(lookup_v2(args.code, args.action), indent=2, ensure_ascii=False))
    elif args.cmd == "stats":
        if not INDEX_V2.exists():
            print("인덱스 없음"); sys.exit(1)
        data = json.loads(INDEX_V2.read_text(encoding="utf-8"))
        print(f"manuals: {len(data['manuals'])}")
        print(f"code_index: {len(data['code_index'])}")
        print(f"action_index: {len(data['action_index'])} pairs")
        # action별 분포
        action_counts = defaultdict(int)
        for key in data["action_index"]:
            _, action = key.split("|")
            action_counts[action] += 1
        print("\n액션별 매핑된 자격 수:")
        for a in sorted(action_counts, key=lambda x: -action_counts[x]):
            print(f"  {a:30}: {action_counts[a]:>3}")
