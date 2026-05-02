"""
매뉴얼 PDF 페이지 인덱서 v6 — sub-category 정식 섹션 인식 + 자동 영역 결정

v5 문제: 〔F-5-4〕 섹션이 단일 페이지로 잡히고 그 안에 action 키워드 없으면
         prefix F-5 폴백되어 사용자가 정답 페이지를 못 봄.

v6 핵심:
  1. 〔F-X-Y〕 형식 = sub-category 정식 시작 (매뉴얼 표기 약속)
  2. sub-category 영역 = 자기 시작 ~ 다음 〔??〕 시작 직전
  3. sub-category는 자동으로 모든 action_type에 매핑 (부모 자격이 어떤 action 섹션인지 추론)
  4. 일반 자격(F-4, H-2 등)은 기존 점수 시스템 + 본문 연속 등장 보호 유지
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
INDEX_V6 = MANUALS / "manual_index_v6.json"

_CODE_BODY = r"[A-Z]-\d+(?:-(?:\d+|[A-Z][\w]*))?"
_BRACKET_FORMAL = re.compile(rf"〔({_CODE_BODY})〕")
_BRACKET_PAREN  = re.compile(rf"\(({_CODE_BODY})\)")

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

_HEADER_HEIGHT_RATIO  = 0.30
_W_HEAD_PAREN  = 5
_W_BODY_PAREN  = 1
_PAGE_THRESHOLD = 10
_GAP = 8


def find_subcategory_starts(doc: fitz.Document) -> list[tuple[int, str]]:
    """매뉴얼에서 〔F-X-Y〕 형식 sub-category 시작 페이지 추출.

    페이지 전체에서 〔...〕 형식 검색.
    같은 코드의 여러 페이지 등장 시 첫 페이지만 시작점으로.
    Returns: [(page_no, code), ...] 페이지 오름차순
    """
    code_first_page: dict[str, int] = {}
    for p in doc:
        text = p.get_text()  # 페이지 전체
        for m in _BRACKET_FORMAL.finditer(text):
            code = m.group(1)
            if code not in code_first_page:
                code_first_page[code] = p.number + 1
    starts = sorted([(p, c) for c, p in code_first_page.items()])
    return starts


def build_subcategory_sections(starts: list[tuple[int, str]], total_pages: int,
                                 max_section_size: int = 30) -> dict[str, list[tuple[int, int]]]:
    """sub-category 시작 페이지 목록 → 각 코드의 (page_from, page_to) 영역.

    영역 끝 = 다음 sub-category 시작 직전, 또는 max_section_size 페이지 제한.
    """
    sections: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for i, (start, code) in enumerate(starts):
        if i + 1 < len(starts):
            next_start = starts[i + 1][0]
            end = next_start - 1
        else:
            end = min(start + max_section_size, total_pages)
        # 영역 너무 크면 자르기 (다음 sub-category 시작점이 아주 멀 경우)
        if end - start > max_section_size:
            end = start + max_section_size
        sections[code].append((start, end))
    return dict(sections)


def page_score_general(page: fitz.Page, code: str) -> int:
    """일반 자격(sub-category 아닌 경우)용 페이지 점수."""
    rect = page.rect
    top = fitz.Rect(0, 0, rect.width, rect.height * _HEADER_HEIGHT_RATIO)
    head = page.get_text(clip=top)
    full = page.get_text()
    head_p = len(re.findall(rf"\({re.escape(code)}\)", head))
    body_p = len(re.findall(rf"\({re.escape(code)}\)", full)) - head_p
    return head_p * _W_HEAD_PAREN + max(0, body_p) * _W_BODY_PAREN


def collect_general_main_pages(doc: fitz.Document, exclude_codes: set[str]) -> dict[str, dict[int, int]]:
    """sub-category 외의 일반 자격 코드용 메인 페이지 수집."""
    all_codes_per_page: dict[int, set[str]] = {}
    for p in doc:
        text = p.get_text()
        codes = set(_BRACKET_PAREN.findall(text)) - exclude_codes
        if codes:
            all_codes_per_page[p.number + 1] = codes

    code_pages: dict[str, dict[int, int]] = defaultdict(dict)
    for p_no, codes in all_codes_per_page.items():
        page = doc[p_no - 1]
        for code in codes:
            sc = page_score_general(page, code)
            if sc >= _PAGE_THRESHOLD:
                code_pages[code][p_no] = sc

    # 본문 연속 3+ 페이지 보너스
    for code in {c for codes in all_codes_per_page.values() for c in codes}:
        body_pages = sorted(p for p, codes in all_codes_per_page.items() if code in codes)
        if not body_pages: continue
        groups, cur = [], [body_pages[0]]
        for p in body_pages[1:]:
            if p - cur[-1] <= 3:
                cur.append(p)
            else:
                groups.append(cur); cur = [p]
        groups.append(cur)
        for g in groups:
            if len(g) >= 3:
                for p in g:
                    if p not in code_pages[code]:
                        code_pages[code][p] = 3
    return dict(code_pages)


def cluster_pages(page_scores: dict[int, int], gap: int = _GAP) -> list[dict]:
    if not page_scores: return []
    pages = sorted(page_scores)
    clusters, cur = [], [pages[0]]
    for p in pages[1:]:
        if p - cur[-1] > gap:
            clusters.append(cur); cur = [p]
        else:
            cur.append(p)
    clusters.append(cur)
    scored = [{
        "page_from": c[0], "page_to": c[-1], "pages": c,
        "score": sum(page_scores[p] for p in c), "page_count": len(c),
    } for c in clusters]
    scored.sort(key=lambda x: -x["score"])
    return scored


def find_action_in_range(doc, pf, pt, kws):
    first = last = kw = None
    for p_no in range(pf, pt + 1):
        if p_no - 1 >= len(doc): break
        text = doc[p_no - 1].get_text()
        for k in kws:
            if k in text:
                if first is None:
                    first, kw = p_no, k
                last = p_no
                break
    return (first, last, kw) if first else None


def build_index_for_pdf(pdf_path: Path, manual_label: str) -> dict:
    doc = fitz.open(pdf_path)
    total = len(doc)

    # === 1. sub-category 정식 섹션 ===
    starts = find_subcategory_starts(doc)
    sub_sections = build_subcategory_sections(starts, total)
    print(f"  [{manual_label}] sub-category 정식 섹션: {len(sub_sections)} 코드 (총 {sum(len(v) for v in sub_sections.values())} 인스턴스)")

    code_index = {}
    action_index = defaultdict(list)

    # sub-category: 자기 영역에서 action 키워드 매칭 + CHANGE 강제 등록
    # (F-5 sub-category는 대부분 영주 변경 케이스이므로 CHANGE 우선)
    for code, ranges in sub_sections.items():
        ranges_sorted = sorted(ranges, key=lambda r: -(r[1] - r[0]))
        pf, pt = ranges_sorted[0]
        code_index[code] = [{
            "manual": manual_label, "page_from": pf, "page_to": pt,
            "score": 100, "page_count": pt - pf + 1, "kind": "subcategory_formal",
        }]
        # 모든 sub-category에 CHANGE 강제 등록 (sub-category 자체가 변경 케이스 표기)
        action_index[f"{code}|CHANGE"].append({
            "manual": manual_label, "page_from": pf, "page_to": pt,
            "match_text": "sub-category 정식 섹션",
            "section_pf": pf, "section_pt": pt,
            "score": 100, "match_kind": "subcategory_change_default",
        })
        # 추가 action 키워드도 보조로 등록 (CHANGE 제외 — 이미 위에서 등록)
        for action_type, kws in ACTION_KEYWORDS.items():
            if action_type == "CHANGE": continue
            hit = find_action_in_range(doc, pf, pt, kws)
            if hit is None: continue
            first, last, kw = hit
            action_index[f"{code}|{action_type}"].append({
                "manual": manual_label, "page_from": first, "page_to": last,
                "match_text": kw, "section_pf": pf, "section_pt": pt,
                "score": 100, "match_kind": "subcategory_with_action",
            })

    # === 2. 일반 자격 (sub-category 아닌 코드) ===
    general_codes = collect_general_main_pages(doc, exclude_codes=set(sub_sections))
    print(f"  [{manual_label}] 일반 자격 코드: {len(general_codes)} 코드")
    for code, page_scores in general_codes.items():
        clusters = cluster_pages(page_scores)
        if not clusters: continue
        top = clusters[0]
        # 이미 code_index에 있으면 추가
        if code not in code_index:
            code_index[code] = []
        code_index[code].append({
            "manual": manual_label, "page_from": top["page_from"], "page_to": top["page_to"],
            "score": top["score"], "page_count": top["page_count"], "kind": "general",
        })
        for action_type, kws in ACTION_KEYWORDS.items():
            hit = find_action_in_range(doc, top["page_from"], top["page_to"], kws)
            if hit is None: continue
            first, last, kw = hit
            action_index[f"{code}|{action_type}"].append({
                "manual": manual_label, "page_from": first, "page_to": last,
                "match_text": kw, "section_pf": top["page_from"], "section_pt": top["page_to"],
                "score": top["score"], "match_kind": "general_with_action",
            })

    doc.close()
    return {"label": manual_label, "total_pages": total,
            "code_index": code_index, "action_index": dict(action_index)}


def build_all() -> dict:
    targets = {
        "체류민원": MANUALS / "unlocked_체류민원.pdf",
        "사증민원": MANUALS / "unlocked_사증민원.pdf",
    }
    manuals_info, code_index_all, action_index_all = {}, defaultdict(list), defaultdict(list)
    for label, path in targets.items():
        if not path.exists(): print(f"[skip] {label}"); continue
        info = build_index_for_pdf(path, label)
        manuals_info[label] = {
            "file": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
            "total_pages": info["total_pages"],
            "code_count": len(info["code_index"]),
        }
        for c, e in info["code_index"].items(): code_index_all[c].extend(e)
        for k, e in info["action_index"].items(): action_index_all[k].extend(e)

    # 사증민원 자격 섹션 → VISA_CONFIRM
    for code, entries in list(code_index_all.items()):
        for e in entries:
            if e["manual"] != "사증민원": continue
            action_index_all[f"{code}|VISA_CONFIRM"].append({
                "manual": "사증민원", "page_from": e["page_from"], "page_to": e["page_to"],
                "match_text": "사증발급(섹션)", "section_pf": e["page_from"], "section_pt": e["page_to"],
                "score": e.get("score", 0), "match_kind": "visa_section",
            })

    # 중복 제거
    for k, entries in action_index_all.items():
        seen, uniq = set(), []
        for e in entries:
            key = (e["manual"], e["page_from"])
            if key in seen: continue
            seen.add(key); uniq.append(e)
        action_index_all[k] = uniq

    result = {
        "manuals": manuals_info,
        "code_index": dict(code_index_all),
        "action_index": dict(action_index_all),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    INDEX_V6.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


# ── DB 코드 → 매뉴얼 코드 alias 테이블 ─────────────────────────────────
DB_TO_MANUAL_ALIAS = {
    "F-5-2": "F-5-4",   # DB "영주권자 미성년 자녀" → 매뉴얼 "일반 영주자의 배우자 또는 미성년 자녀"
}

# ── 수동 페이지 override 테이블 ──────────────────────────────────────
# 사용자가 직접 알려준 정답 페이지를 절대 우선으로 매핑.
# 자동 매핑이 잡지 못하는 케이스(매뉴얼 본문 표기 불일치 등) 보정.
# 매뉴얼 표시 페이지 번호 기준 (사용자가 PDF에서 보는 번호).
# PDF 0-기반 인덱스 = 매뉴얼 표시 - 1 (대부분 케이스).
MANUAL_PAGE_OVERRIDE = {
    # "DB_code|action_type": [{"manual": ..., "page_from": ..., "page_to": ...}]
    "F-5-6|CHANGE": [
        {"manual": "체류민원", "page_from": 446, "page_to": 446,
         "match_text": "결혼이민자 (사용자 지정)"},
    ],
    "F-5-2|CHANGE": [
        {"manual": "체류민원", "page_from": 453, "page_to": 453,
         "match_text": "일반 영주자의 배우자/미성년 자녀 〔F-5-4〕 (사용자 지정)"},
    ],
    "F-5-1|CHANGE": [
        {"manual": "체류민원", "page_from": 445, "page_to": 452,
         "match_text": "국민의 배우자·자녀 〔F-5-1〕 (매뉴얼 정식 sub-category)"},
    ],
    "F-5-11|CHANGE": [
        {"manual": "체류민원", "page_from": 458, "page_to": 461,
         "match_text": "특정분야 능력소유자 〔F-5-11〕 (매뉴얼 정식 sub-category)"},
    ],
    "F-5-14|CHANGE": [
        {"manual": "체류민원", "page_from": 579, "page_to": 583,
         "match_text": "방문취업 4년 영주 〔F-5-14〕"},
    ],
    "F-4|EXTRA_WORK": [
        {"manual": "체류민원", "page_from": 357, "page_to": 360,
         "match_text": "인구감소지역 거주 재외동포 활동허가"},
    ],
    "F-4-R|EXTEND": [
        {"manual": "체류민원", "page_from": 625, "page_to": 626,
         "match_text": "지역동포가족 체류자격 변경 및 연장"},
    ],
    # 사용자가 추가로 알려주는 row는 여기에 누적
}


def lookup(detailed_code: str, action_type: str) -> list[dict]:
    if not INDEX_V6.exists():
        raise FileNotFoundError(f"인덱스 없음: {INDEX_V6}")

    # 1. 수동 페이지 override 우선 (사용자 지정)
    override_key = f"{detailed_code}|{action_type}"
    if override_key in MANUAL_PAGE_OVERRIDE:
        return [{**e, "match_type": "manual_override"} for e in MANUAL_PAGE_OVERRIDE[override_key]]

    data = json.loads(INDEX_V6.read_text(encoding="utf-8"))

    # 2. alias 적용
    actual_code = DB_TO_MANUAL_ALIAS.get(detailed_code, detailed_code)
    key = f"{actual_code}|{action_type}"
    if key in data["action_index"]:
        return [{**e, "match_type": "action_exact"} for e in data["action_index"][key]]
    # alias 적용 후 prefix 매칭
    main = re.match(r"^([A-Z]-\d+)", actual_code)
    if main:
        pkey = f"{main.group(1)}|{action_type}"
        if pkey in data["action_index"]:
            return [{**e, "match_type": "action_prefix"} for e in data["action_index"][pkey]]
    if actual_code in data["code_index"]:
        return [{**e, "match_type": "section_only", "match_text": "자격 섹션 전체"}
                for e in data["code_index"][actual_code]]
    if main and main.group(1) in data["code_index"]:
        return [{**e, "match_type": "section_only", "match_text": "자격 섹션 전체"}
                for e in data["code_index"][main.group(1)]]
    return []


# ── CLI ──
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    p_lk = sub.add_parser("lookup"); p_lk.add_argument("code"); p_lk.add_argument("action")
    sub.add_parser("stats")
    args = p.parse_args()
    if args.cmd == "build":
        result = build_all()
        print(f"\n[OK] code_index:{len(result['code_index'])}, action_index:{len(result['action_index'])}")
    elif args.cmd == "lookup":
        print(json.dumps(lookup(args.code, args.action), indent=2, ensure_ascii=False))
    elif args.cmd == "stats":
        if not INDEX_V6.exists(): print("없음"); sys.exit(1)
        data = json.loads(INDEX_V6.read_text(encoding="utf-8"))
        print(f"codes:{len(data['code_index'])}, action:{len(data['action_index'])}")
