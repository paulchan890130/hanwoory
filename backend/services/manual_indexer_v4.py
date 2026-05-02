"""
매뉴얼 PDF 페이지 인덱서 v4 — 헤더 가중치 + 점수화 + 상위 클러스터만 채택

v3 한계: 본문 단순 인용까지 매칭하여 F-5-2가 18 페이지로 잡힘 등 노이즈 과다
v4 개선:
  1. 페이지 점수 = 헤더(상단 15%) 등장 × 5 + 본문 등장 × 1
  2. 점수 임계치 미만 페이지는 인용으로 간주, 메인 섹션 후보에서 제외
  3. 메인 페이지 클러스터링 → 클러스터 점수(페이지 수 × 평균 점수)
  4. 자격당 매뉴얼당 상위 N개 클러스터만 채택 (기본 1)
  5. 매뉴얼에 메인 섹션 없는 자격은 prefix 폴백
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
INDEX_V4 = MANUALS / "manual_index_v4.json"

_CODE_RE = re.compile(r"\(([A-Z]-\d+(?:-(?:\d+|[A-Z][\w]*))?)\)")

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

# 점수 가중치
_HEADER_WEIGHT = 5
_BODY_WEIGHT = 1
_HEADER_HEIGHT_RATIO = 0.15
_PAGE_SCORE_THRESHOLD = 5   # 페이지가 메인 섹션 후보가 되려면 점수 ≥ 이 값
_SECTION_GAP_THRESHOLD = 8  # 클러스터 분리 임계 (페이지)
_TOP_CLUSTERS_PER_MANUAL = 1  # 자격당 매뉴얼당 채택할 클러스터 수


def page_score_for_code(page: fitz.Page, code: str) -> int:
    """페이지에서 자격코드 등장 점수: 헤더 ×5 + 본문 ×1."""
    pattern = re.compile(re.escape(code))
    rect = page.rect
    top = fitz.Rect(0, 0, rect.width, rect.height * _HEADER_HEIGHT_RATIO)
    head_text = page.get_text(clip=top)
    body_text = page.get_text()

    head_count = len(pattern.findall(head_text))
    body_count = len(pattern.findall(body_text)) - head_count  # 본문 = 전체 - 헤더
    return head_count * _HEADER_WEIGHT + max(0, body_count) * _BODY_WEIGHT


def collect_main_pages(doc: fitz.Document) -> dict[str, dict[int, int]]:
    """모든 자격코드의 메인 섹션 후보 페이지 + 점수.

    1. 헤더 가중치 점수 ≥ 임계값 페이지 = high-confidence
    2. 헤더 미충족이지만 본문에 코드가 등장하는 페이지를 추적
    3. 본문 등장 페이지가 N+ 연속 클러스터를 이루면 그 클러스터도 메인 섹션 후보
       (F-4-R처럼 헤더에 코드 명시 없는 자격 보호)
    """
    # 모든 페이지의 자격코드 + 점수
    all_pages: dict[str, dict[int, dict]] = defaultdict(dict)
    for p in doc:
        text = p.get_text()
        codes = set(_CODE_RE.findall(text))
        for code in codes:
            score = page_score_for_code(p, code)
            body_count = len(re.findall(re.escape(code), text))
            all_pages[code][p.number + 1] = {"score": score, "body_count": body_count}

    code_pages: dict[str, dict[int, int]] = defaultdict(dict)

    for code, page_data in all_pages.items():
        # 1. 점수 임계값 통과한 페이지 (high-confidence)
        for p, d in page_data.items():
            if d["score"] >= _PAGE_SCORE_THRESHOLD:
                code_pages[code][p] = d["score"]

        # 2. 본문 등장 페이지 그룹화 → 연속 3+ 클러스터는 메인 섹션 후보
        body_pages = sorted(p for p, d in page_data.items() if d["body_count"] >= 1)
        if not body_pages:
            continue
        # 연속 그룹 추출
        groups = []
        cur = [body_pages[0]]
        for p in body_pages[1:]:
            if p - cur[-1] <= 3:  # 3페이지 이내 = 연속
                cur.append(p)
            else:
                groups.append(cur); cur = [p]
        groups.append(cur)
        # 3+ 페이지 클러스터를 메인 섹션 후보로 (약한 점수 부여)
        for g in groups:
            if len(g) >= 3:
                for p in g:
                    if p not in code_pages[code]:
                        code_pages[code][p] = page_data[p]["score"] + 3  # 보너스 점수

    return dict(code_pages)


def cluster_pages_with_scores(
    page_scores: dict[int, int], gap: int = _SECTION_GAP_THRESHOLD,
) -> list[dict]:
    """페이지+점수를 클러스터로 묶고 클러스터별 점수 합산."""
    if not page_scores:
        return []
    pages = sorted(page_scores)
    clusters = []
    cur = [pages[0]]
    for p in pages[1:]:
        if p - cur[-1] > gap:
            clusters.append(cur)
            cur = [p]
        else:
            cur.append(p)
    clusters.append(cur)

    scored = []
    for c in clusters:
        total_score = sum(page_scores[p] for p in c)
        scored.append({
            "page_from": c[0],
            "page_to":   c[-1],
            "pages":     c,
            "score":     total_score,
            "page_count": len(c),
        })
    scored.sort(key=lambda x: -x["score"])  # 높은 점수 우선
    return scored


def find_action_in_range(
    doc: fitz.Document, pf: int, pt: int, keywords: list[str],
) -> Optional[tuple[int, int, str]]:
    first, last, kw_used = None, None, None
    for p_no in range(pf, pt + 1):
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
    doc = fitz.open(pdf_path)
    code_pages = collect_main_pages(doc)
    print(f"  [{manual_label}] 메인 섹션 후보: {len(code_pages)} 코드")

    code_index: dict[str, list[dict]] = {}
    action_index: dict[str, list[dict]] = defaultdict(list)

    for code, page_scores in code_pages.items():
        clusters = cluster_pages_with_scores(page_scores)
        # 상위 N개 클러스터만 채택
        top = clusters[:_TOP_CLUSTERS_PER_MANUAL]

        code_index[code] = [
            {"manual": manual_label, "page_from": c["page_from"], "page_to": c["page_to"],
             "score": c["score"], "page_count": c["page_count"]}
            for c in top
        ]

        for c in top:
            for action_type, kws in ACTION_KEYWORDS.items():
                hit = find_action_in_range(doc, c["page_from"], c["page_to"], kws)
                if hit is None:
                    continue
                first, last, kw = hit
                action_index[f"{code}|{action_type}"].append({
                    "manual":      manual_label,
                    "page_from":   first,
                    "page_to":     last,
                    "match_text":  kw,
                    "section_pf":  c["page_from"],
                    "section_pt":  c["page_to"],
                    "score":       c["score"],
                })

    total = len(doc)
    doc.close()
    return {
        "label":        manual_label,
        "total_pages":  total,
        "code_index":   code_index,
        "action_index": dict(action_index),
    }


def build_all() -> dict:
    targets = {
        "체류민원": MANUALS / "unlocked_체류민원.pdf",
        "사증민원": MANUALS / "unlocked_사증민원.pdf",
    }
    manuals_info = {}
    code_index_all = defaultdict(list)
    action_index_all = defaultdict(list)

    for label, path in targets.items():
        if not path.exists():
            print(f"[skip] {label}"); continue
        info = build_index_for_pdf(path, label)
        manuals_info[label] = {
            "file":        str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
            "total_pages": info["total_pages"],
            "code_count":  len(info["code_index"]),
        }
        for c, entries in info["code_index"].items():
            code_index_all[c].extend(entries)
        for k, entries in info["action_index"].items():
            action_index_all[k].extend(entries)

    # 사증민원 자격 섹션 → VISA_CONFIRM 자동 등록
    if "사증민원" in code_index_all.__class__.__name__ or True:
        for code, entries in list(code_index_all.items()):
            for e in entries:
                if e["manual"] != "사증민원":
                    continue
                key = f"{code}|VISA_CONFIRM"
                # 이미 다른 키워드로 매핑된 entry가 있는지
                action_index_all[key].append({
                    "manual":     "사증민원",
                    "page_from":  e["page_from"],
                    "page_to":    e["page_to"],
                    "match_text": "사증발급(섹션)",
                    "section_pf": e["page_from"],
                    "section_pt": e["page_to"],
                    "score":      e.get("score", 0),
                })

    # 중복 제거
    for k, entries in action_index_all.items():
        seen = set()
        unique = []
        for e in entries:
            key = (e["manual"], e["page_from"])
            if key in seen: continue
            seen.add(key); unique.append(e)
        action_index_all[k] = unique

    result = {
        "manuals":      manuals_info,
        "code_index":   dict(code_index_all),
        "action_index": dict(action_index_all),
        "built_at":     datetime.now(timezone.utc).isoformat(),
        "config": {
            "header_weight":  _HEADER_WEIGHT,
            "body_weight":    _BODY_WEIGHT,
            "page_threshold": _PAGE_SCORE_THRESHOLD,
            "gap":            _SECTION_GAP_THRESHOLD,
            "top_clusters":   _TOP_CLUSTERS_PER_MANUAL,
        },
    }
    INDEX_V4.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def lookup(detailed_code: str, action_type: str) -> list[dict]:
    if not INDEX_V4.exists():
        raise FileNotFoundError(f"인덱스 없음: {INDEX_V4}")
    data = json.loads(INDEX_V4.read_text(encoding="utf-8"))

    # 1. (code, action) 정확
    key = f"{detailed_code}|{action_type}"
    if key in data["action_index"]:
        return [{**e, "match_type": "action_exact"} for e in data["action_index"][key]]

    # 2. prefix
    main = re.match(r"^([A-Z]-\d+)", detailed_code)
    if main:
        pkey = f"{main.group(1)}|{action_type}"
        if pkey in data["action_index"]:
            return [{**e, "match_type": "action_prefix"} for e in data["action_index"][pkey]]

    # 3. 코드 섹션 fallback
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
    p_lk = sub.add_parser("lookup"); p_lk.add_argument("code"); p_lk.add_argument("action")
    sub.add_parser("stats")

    args = p.parse_args()
    if args.cmd == "build":
        result = build_all()
        print(f"\n[OK] {len(result['manuals'])} manuals")
        print(f"  code_index:   {len(result['code_index'])}")
        print(f"  action_index: {len(result['action_index'])}")
    elif args.cmd == "lookup":
        print(json.dumps(lookup(args.code, args.action), indent=2, ensure_ascii=False))
    elif args.cmd == "stats":
        if not INDEX_V4.exists(): print("인덱스 없음"); sys.exit(1)
        data = json.loads(INDEX_V4.read_text(encoding="utf-8"))
        print(f"manuals: {len(data['manuals'])}")
        print(f"codes:   {len(data['code_index'])}")
        print(f"action:  {len(data['action_index'])}")
        ac = defaultdict(int)
        for k in data["action_index"]:
            _, a = k.split("|"); ac[a] += 1
        for a in sorted(ac, key=lambda x: -ac[x]):
            print(f"  {a:30}: {ac[a]:>3}")
