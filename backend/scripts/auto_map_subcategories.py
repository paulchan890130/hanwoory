"""
매뉴얼 sub-category 헤더 자동 추출 + DB row 매칭

매뉴얼 패턴: "N. 한글명칭〔F-X-Y〕" 또는 "한글명칭(F-X-Y)" sub-category 헤더
DB row의 business_name과 토큰 매칭하여 정답 페이지 결정.

LLM 없이도 높은 정확도. 매칭 안 되는 row는 별도 보고.
"""
from __future__ import annotations
import json, re, sys, fitz
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH    = ROOT / "backend" / "data" / "immigration_guidelines_db_v2.json"
MANUAL_R   = ROOT / "backend" / "data" / "manuals" / "unlocked_체류민원.pdf"
MANUAL_V   = ROOT / "backend" / "data" / "manuals" / "unlocked_사증민원.pdf"

# 매뉴얼 sub-category 헤더 패턴
# "1. 국민의 배우자·자녀〔F-5-1〕" or "1. 국민의 배우자·자녀 (F-5-1)"
# 또는 본문 시작에 "결혼이민자(F-5-2)" 같은 명칭+코드
_HEADER_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:\d+\.\s*)?([가-힣\s·\(\)\,\·]+?)\s*[〔\(]([A-Z]-\d+(?:-(?:\d+|[A-Z][\w]*))?)[〕\)]",
    re.MULTILINE
)


def extract_headers(doc: fitz.Document, manual_label: str) -> list[dict]:
    """매뉴얼에서 sub-category 헤더 페이지 추출.
    Returns: [{page, code, name}, ...]
    """
    seen = set()
    results = []
    for p in doc:
        text = p.get_text()
        for m in _HEADER_PATTERN.finditer(text):
            name = m.group(1).strip()
            code = m.group(2)
            # 너무 일반적/짧은 이름 제외
            if len(name) < 2 or len(name) > 40:
                continue
            # 중복 제거 (같은 코드의 첫 등장만)
            if code in seen:
                continue
            seen.add(code)
            results.append({
                "manual": manual_label,
                "page": p.number + 1,
                "code": code,
                "name": name,
            })
    return results


def tokenize_korean(text: str) -> set[str]:
    """간단 한글 토큰화 (2글자 이상)."""
    tokens = re.findall(r"[가-힣]{2,}", text)
    # 일반적 단어 제외
    stop = {"체류", "자격", "변경", "연장", "허가", "미성년", "신청", "업무"}
    return {t for t in tokens if t not in stop}


def match_score(row_name: str, header_name: str) -> float:
    """row business_name과 매뉴얼 헤더 명칭의 매칭 점수."""
    row_tokens = tokenize_korean(row_name)
    hdr_tokens = tokenize_korean(header_name)
    if not row_tokens or not hdr_tokens:
        return 0.0
    common = row_tokens & hdr_tokens
    return len(common) / min(len(row_tokens), len(hdr_tokens))


def main():
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    rows = db["master_rows"]

    print("매뉴얼 sub-category 헤더 추출...")
    man_r = fitz.open(MANUAL_R); man_v = fitz.open(MANUAL_V)
    headers_r = extract_headers(man_r, "체류민원")
    headers_v = extract_headers(man_v, "사증민원")
    man_r.close(); man_v.close()
    print(f"  체류민원: {len(headers_r)} 헤더, 사증민원: {len(headers_v)} 헤더")

    all_headers = headers_r + headers_v

    # 각 row를 매뉴얼 헤더에 매칭
    stats = defaultdict(int)
    overrides = {}  # {(row_id, action): [refs]}

    for r in rows:
        row_id = r["row_id"]
        code = r.get("detailed_code", "").strip()
        name = r.get("business_name", "").strip()
        action = r.get("action_type", "").strip()
        if not code or not name:
            stats["skip"] += 1; continue

        # 1. 정확한 코드 매칭 우선
        exact = [h for h in all_headers if h["code"] == code]
        if exact:
            stats["exact_code"] += 1
            overrides[f"{row_id}"] = {
                "row_id": row_id, "method": "exact_code",
                "manual_ref": [{
                    "manual":     h["manual"],
                    "page_from":  h["page"],
                    "page_to":    h["page"],
                    "match_text": f"{h['name']}〔{h['code']}〕",
                    "match_type": "auto_header_exact",
                } for h in exact],
            }
            continue

        # 2. 한글 명칭 매칭
        scored = [(match_score(name, h["name"]), h) for h in all_headers]
        scored = [(s, h) for s, h in scored if s >= 0.5]  # 최소 50% 토큰 일치
        scored.sort(key=lambda x: -x[0])
        if scored:
            best = scored[:3]  # 상위 3개
            stats["name_match"] += 1
            overrides[f"{row_id}"] = {
                "row_id": row_id, "method": "name_match",
                "score":  best[0][0],
                "manual_ref": [{
                    "manual":     h["manual"],
                    "page_from":  h["page"],
                    "page_to":    h["page"],
                    "match_text": f"{h['name']}〔{h['code']}〕 (score={s:.2f})",
                    "match_type": "auto_header_namematch",
                } for s, h in best],
            }
        else:
            stats["no_match"] += 1

    print(f"\n결과: exact_code={stats['exact_code']}, name_match={stats['name_match']}, no_match={stats['no_match']}, skip={stats['skip']}")

    # 결과 저장 (옵션 1: 자동 적용)
    out_path = ROOT / "backend" / "data" / "manuals" / "auto_subcategory_overrides.json"
    out_path.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {out_path}")

    # 검증용: F-5 결과만 출력
    print("\n=== F-5 검증 ===")
    for row in rows:
        if row.get("detailed_code","").startswith("F-5") and row["row_id"] in overrides:
            ov = overrides[row["row_id"]]
            print(f"  {row['row_id']} | {row['detailed_code']:8} | {row['business_name'][:30]}")
            print(f"     method={ov['method']}, ref:")
            for ref in ov["manual_ref"][:2]:
                print(f"       {ref['manual']} p.{ref['page_from']} — {ref['match_text']}")


if __name__ == "__main__":
    main()
