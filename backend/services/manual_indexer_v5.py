"""
매뉴얼 PDF 페이지 인덱서 v5 — sub-category 정식 표기 인식

v4 한계: 매뉴얼 본문 인용까지 모두 잡아 노이즈. sub-category 별도 섹션 못 찾음.
v5 핵심:
  - 매뉴얼이 sub-category 정식 시작을 〔F-5-4〕 꺾쇠 괄호로 표기
  - 일반 (F-5-4) 괄호는 본문 인용용 (노이즈 多)
  - 두 형식을 구분하여 sub-category별 정확한 페이지 인덱싱
  - F-4-R 같은 코드는 〔F-4-R〕 꺾쇠 + 한글 명칭 매칭 + 본문 다수 등장 조합

신뢰도 가중치 (페이지 점수):
  - 헤더(상단 20%)에 〔F-X-Y〕 = +20점 (강력)
  - 헤더(상단 20%)에 (F-X-Y) = +5점
  - 본문에 〔F-X-Y〕 = +5점
  - 본문에 (F-X-Y) = +1점
  - 페이지 점수 ≥ 임계값(10) = 메인 섹션 후보
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
INDEX_V5 = MANUALS / "manual_index_v5.json"

# 자격코드: A-1, F-4, F-4-R, F-4-19, F-5-S1 등
_CODE_BODY = r"[A-Z]-\d+(?:-(?:\d+|[A-Z][\w]*))?"
_BRACKET_FORMAL = re.compile(rf"〔({_CODE_BODY})〕")  # 정식 sub-category 표기
_BRACKET_PAREN  = re.compile(rf"\(({_CODE_BODY})\)")  # 일반 괄호 (인용 가능성)

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

_HEADER_HEIGHT_RATIO  = 0.30  # 헤더 영역 확장 (제목이 30%까지 내려올 수 있음)
# 〔...〕 정식 표기는 압도적 가중치. 단 1번 등장으로도 임계값 통과
_W_HEAD_FORMAL = 50
_W_BODY_FORMAL = 30   # 본문이라도 〔...〕은 sub-category 시작 시그널
# (...) 일반 괄호는 약한 가중치. 다수 등장(25+ 페이지에 분산)해야 의미 있음
_W_HEAD_PAREN  = 3
_W_BODY_PAREN  = 1
_PAGE_THRESHOLD = 25  # 〔...〕 1번이면 통과, (...)만으로는 어려움
_GAP = 8
_TOP_CLUSTERS_PER_MANUAL = 1


def page_score(page: fitz.Page, code: str) -> tuple[int, dict]:
    """페이지 코드 점수 + 디버그 정보."""
    rect = page.rect
    top = fitz.Rect(0, 0, rect.width, rect.height * _HEADER_HEIGHT_RATIO)
    head = page.get_text(clip=top)
    full = page.get_text()
    body = full  # 본문 전체 (헤더 포함하지만 가중치 차이로 처리)

    # 코드 등장 횟수 (괄호 형식별)
    head_formal = len(re.findall(rf"〔{re.escape(code)}〕", head))
    head_paren  = len(re.findall(rf"\({re.escape(code)}\)", head))
    body_formal = len(re.findall(rf"〔{re.escape(code)}〕", body)) - head_formal
    body_paren  = len(re.findall(rf"\({re.escape(code)}\)", body)) - head_paren

    score = (head_formal * _W_HEAD_FORMAL + head_paren * _W_HEAD_PAREN +
             body_formal * _W_BODY_FORMAL + body_paren  * _W_BODY_PAREN)
    return score, {"hf": head_formal, "hp": head_paren, "bf": body_formal, "bp": body_paren}


def collect_main_pages(doc: fitz.Document) -> dict[str, dict[int, int]]:
    """모든 자격코드의 메인 섹션 후보 페이지."""
    # 페이지에 등장하는 모든 자격코드 (괄호 두 형식 합)
    all_codes_per_page: dict[int, set[str]] = {}
    for p in doc:
        text = p.get_text()
        codes = set(_BRACKET_FORMAL.findall(text)) | set(_BRACKET_PAREN.findall(text))
        if codes:
            all_codes_per_page[p.number + 1] = codes

    code_pages: dict[str, dict[int, int]] = defaultdict(dict)
    code_metas: dict[str, dict[int, dict]] = defaultdict(dict)
    for p_no, codes in all_codes_per_page.items():
        page = doc[p_no - 1]
        for code in codes:
            sc, meta = page_score(page, code)
            if sc >= _PAGE_THRESHOLD:
                code_pages[code][p_no] = sc
                code_metas[code][p_no] = meta

    # 본문 등장만 있는 자격코드도 연속 3+페이지 클러스터는 메인 섹션 후보로 추가
    for code in list(all_codes_per_page.values()):
        pass  # placeholder

    # 본문 연속 등장 보호 (F-4-R 같이 헤더에 코드 없는 케이스)
    for code in {c for codes in all_codes_per_page.values() for c in codes}:
        body_pages = []
        for p_no, codes in all_codes_per_page.items():
            if code in codes and p_no not in code_pages[code]:
                body_pages.append(p_no)
        body_pages.sort()
        # 3페이지 이내 연속 그룹
        if not body_pages:
            continue
        groups = []
        cur = [body_pages[0]]
        for p in body_pages[1:]:
            if p - cur[-1] <= 3:
                cur.append(p)
            else:
                groups.append(cur); cur = [p]
        groups.append(cur)
        for g in groups:
            if len(g) >= 3:
                for p in g:
                    code_pages[code][p] = code_pages[code].get(p, 0) + 3

    return dict(code_pages)


def cluster_pages(page_scores: dict[int, int], gap: int = _GAP) -> list[dict]:
    if not page_scores:
        return []
    pages = sorted(page_scores)
    clusters = []
    cur = [pages[0]]
    for p in pages[1:]:
        if p - cur[-1] > gap:
            clusters.append(cur); cur = [p]
        else:
            cur.append(p)
    clusters.append(cur)
    scored = []
    for c in clusters:
        total = sum(page_scores[p] for p in c)
        scored.append({"page_from": c[0], "page_to": c[-1], "pages": c,
                       "score": total, "page_count": len(c)})
    scored.sort(key=lambda x: -x["score"])
    return scored


def find_action_in_range(doc, pf, pt, kws):
    first = last = kw_used = None
    for p_no in range(pf, pt + 1):
        if p_no - 1 >= len(doc): break
        text = doc[p_no - 1].get_text()
        for kw in kws:
            if kw in text:
                if first is None:
                    first, kw_used = p_no, kw
                last = p_no
                break
    if first is None:
        return None
    return (first, last, kw_used)


def build_index_for_pdf(pdf_path: Path, manual_label: str) -> dict:
    doc = fitz.open(pdf_path)
    code_pages = collect_main_pages(doc)
    print(f"  [{manual_label}] sub-category 후보: {len(code_pages)} 코드")

    code_index = {}
    action_index = defaultdict(list)
    for code, page_scores in code_pages.items():
        clusters = cluster_pages(page_scores)
        top = clusters[:_TOP_CLUSTERS_PER_MANUAL]
        code_index[code] = [
            {"manual": manual_label, "page_from": c["page_from"], "page_to": c["page_to"],
             "score": c["score"], "page_count": c["page_count"]}
            for c in top
        ]
        for c in top:
            for action_type, kws in ACTION_KEYWORDS.items():
                hit = find_action_in_range(doc, c["page_from"], c["page_to"], kws)
                if hit is None: continue
                first, last, kw = hit
                action_index[f"{code}|{action_type}"].append({
                    "manual": manual_label, "page_from": first, "page_to": last,
                    "match_text": kw,
                    "section_pf": c["page_from"], "section_pt": c["page_to"],
                    "score": c["score"],
                })
    total = len(doc)
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
        if not path.exists():
            print(f"[skip] {label}"); continue
        info = build_index_for_pdf(path, label)
        manuals_info[label] = {
            "file": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
            "total_pages": info["total_pages"], "code_count": len(info["code_index"]),
        }
        for c, e in info["code_index"].items(): code_index_all[c].extend(e)
        for k, e in info["action_index"].items(): action_index_all[k].extend(e)

    # 사증민원의 자격 섹션 → VISA_CONFIRM 자동 등록
    for code, entries in list(code_index_all.items()):
        for e in entries:
            if e["manual"] != "사증민원": continue
            action_index_all[f"{code}|VISA_CONFIRM"].append({
                "manual": "사증민원", "page_from": e["page_from"], "page_to": e["page_to"],
                "match_text": "사증발급(섹션)", "section_pf": e["page_from"], "section_pt": e["page_to"],
                "score": e.get("score", 0),
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
    INDEX_V5.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def lookup(detailed_code: str, action_type: str) -> list[dict]:
    if not INDEX_V5.exists():
        raise FileNotFoundError(f"인덱스 없음: {INDEX_V5}")
    data = json.loads(INDEX_V5.read_text(encoding="utf-8"))
    key = f"{detailed_code}|{action_type}"
    if key in data["action_index"]:
        return [{**e, "match_type": "action_exact"} for e in data["action_index"][key]]
    main = re.match(r"^([A-Z]-\d+)", detailed_code)
    if main:
        pkey = f"{main.group(1)}|{action_type}"
        if pkey in data["action_index"]:
            return [{**e, "match_type": "action_prefix"} for e in data["action_index"][pkey]]
    if detailed_code in data["code_index"]:
        return [{**e, "match_type": "section_only", "match_text": "자격 섹션 전체"}
                for e in data["code_index"][detailed_code]]
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
        if not INDEX_V5.exists(): print("없음"); sys.exit(1)
        data = json.loads(INDEX_V5.read_text(encoding="utf-8"))
        print(f"codes:{len(data['code_index'])}, action:{len(data['action_index'])}")
