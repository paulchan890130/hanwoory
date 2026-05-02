"""
369 row → 매뉴얼 정밀 매핑 (v2)

v1: detailed_code 단위 매핑만 (F-4 → F-4 섹션 전체)
v2: (detailed_code, action_type) 단위 매핑

각 row의 manual_ref:
  [
    {"manual": "체류민원", "page_from": 552, "page_to": 555,
     "match_text": "체류자격 변경허가", "match_type": "action_exact"},
    ...
  ]

match_type 종류:
  - action_exact     : (자격, action) 정확 매칭
  - action_prefix    : prefix 매칭 (F-4-19,CHANGE → F-4,CHANGE)
  - section_only     : 자격 섹션 전체 (action별 분리 안 됨)
  - none             : 매칭 실패
"""
import json, sys, re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from backend.services.manual_indexer_v2 import lookup_v2, INDEX_V2

DB_PATH = ROOT / "backend" / "data" / "immigration_guidelines_db_v2.json"


def find_match(detailed_code: str, action_type: str) -> tuple[list[dict], str]:
    """반환: (매칭리스트, 매칭타입)"""
    if not detailed_code:
        return [], "no_code"

    if not INDEX_V2.exists():
        return [], "no_index"

    data = json.loads(INDEX_V2.read_text(encoding="utf-8"))
    action_idx = data["action_index"]
    code_idx   = data["code_index"]

    # 1. 정확 (자격, action)
    key = f"{detailed_code}|{action_type}"
    if key in action_idx:
        return [{**e, "match_type": "action_exact"} for e in action_idx[key]], "action_exact"

    # 2. prefix (자격, action)
    main = re.match(r"^([A-Z]-\d+)", detailed_code)
    if main:
        prefix_key = f"{main.group(1)}|{action_type}"
        if prefix_key in action_idx:
            return [{**e, "match_type": "action_prefix"} for e in action_idx[prefix_key]], "action_prefix"

    # 3. 자격 섹션 전체 (action 분리 실패)
    candidates = []
    if detailed_code in code_idx:
        candidates.extend(code_idx[detailed_code])
    if main and main.group(1) in code_idx and main.group(1) != detailed_code:
        candidates.extend(code_idx[main.group(1)])
    if candidates:
        return [{**e, "match_type": "section_only", "match_text": "자격 섹션 전체"}
                for e in candidates], "section_only"

    return [], "none"


def main():
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    rows = db["master_rows"]

    stats = defaultdict(int)
    by_match = defaultdict(list)

    for r in rows:
        code = r.get("detailed_code", "")
        action = r.get("action_type", "")
        matches, match_type = find_match(code, action)
        r["manual_ref"] = matches
        stats[match_type] += 1
        by_match[match_type].append(r)

    db["master_rows"] = rows
    DB_PATH.write_text(
        json.dumps(db, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total = len(rows)
    print(f"=== 매핑 결과 (총 {total} rows) ===")
    print(f"  action_exact (정밀):     {stats['action_exact']:>4} ({stats['action_exact']/total*100:.1f}%)")
    print(f"  action_prefix (prefix):  {stats['action_prefix']:>4} ({stats['action_prefix']/total*100:.1f}%)")
    print(f"  section_only (자격만):    {stats['section_only']:>4} ({stats['section_only']/total*100:.1f}%)")
    print(f"  none (매칭 실패):         {stats['none']:>4} ({stats['none']/total*100:.1f}%)")
    print(f"  no_code (코드 없음):      {stats['no_code']:>4}")

    # section_only인 row를 action_type별로 분포
    if by_match["section_only"]:
        print(f"\n=== section_only ({len(by_match['section_only'])}건) — action_type별 분포 ===")
        action_dist = defaultdict(int)
        for r in by_match["section_only"]:
            action_dist[r.get("action_type","")] += 1
        for a in sorted(action_dist, key=lambda x: -action_dist[x]):
            print(f"  {a:30}: {action_dist[a]:>3}")

    if by_match["none"]:
        print(f"\n=== 매칭 실패 row {len(by_match['none'])}개 (수동 검토 필요) ===")
        for r in by_match["none"][:20]:
            print(f"  {r['row_id']} | {r.get('action_type','?'):20} | {r.get('detailed_code','-'):10} | {r.get('business_name','')[:50]}")
        if len(by_match["none"]) > 20:
            print(f"  ... +{len(by_match['none'])-20} more")

    print(f"\n[OK] DB 업데이트: {DB_PATH}")


if __name__ == "__main__":
    main()
