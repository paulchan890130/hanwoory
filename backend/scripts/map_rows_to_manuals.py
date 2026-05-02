"""
369개 guideline rows를 매뉴얼 PDF 페이지에 매핑.

1차: detailed_code 직접 매칭 (manual_indexer.lookup 사용)
2차: prefix 매칭 (F-4-19 → F-4)
3차: 매칭 실패 row 별도 보고 → 추후 LLM 폴백 또는 수동 검토

결과: 각 row에 `manual_ref` 필드 추가
  manual_ref: [
    {"manual": "체류민원", "page_from": 245, "page_to": 252, "title": "재외동포(F-4)"},
    {"manual": "사증민원", "page_from": 145, "page_to": 150, "title": "재외동포(F-4)"}
  ]

매뉴얼 매칭 우선순위:
  - action_type == "VISA_CONFIRM" → 사증민원 우선
  - 그 외 → 체류민원 우선
"""
import json, sys, re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from backend.services.manual_indexer import lookup as idx_lookup, INDEX

DB_PATH = ROOT / "backend" / "data" / "immigration_guidelines_db_v2.json"

# action_type → 우선 매뉴얼
PRIMARY_MANUAL = {
    "VISA_CONFIRM":              "사증민원",
    "APPLICATION_CLAIM":         "사증민원",
    # 그 외 모두 체류민원
}


def find_best_match(detailed_code: str, action_type: str) -> tuple[list[dict], str]:
    """매뉴얼 페이지 매칭 반환 + 매칭 방식.

    Returns:
        (matches, method) — matches는 manual_ref 형식 리스트, method는 'exact'/'prefix'/'none'
    """
    # 1. 정확 매칭
    exact = idx_lookup(detailed_code)
    if exact:
        return _prioritize(exact, action_type), "exact"

    # 2. prefix (메인 코드 추출)
    main = re.match(r"^([A-Z]-\d+)", detailed_code)
    if main:
        prefix_match = idx_lookup(main.group(1))
        if prefix_match:
            return _prioritize(prefix_match, action_type), "prefix"

    return [], "none"


def _prioritize(matches: list[dict], action_type: str) -> list[dict]:
    """우선 매뉴얼이 앞에 오도록 정렬."""
    primary = PRIMARY_MANUAL.get(action_type, "체류민원")
    return sorted(matches, key=lambda m: (m["manual"] != primary, m["page_from"]))


def main():
    if not INDEX.exists():
        print(f"인덱스 파일 없음: {INDEX}\n  → python backend/services/manual_indexer.py build")
        sys.exit(1)

    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    rows = db.get("master_rows", [])

    stats = defaultdict(int)
    unmatched = []

    for r in rows:
        code = r.get("detailed_code", "")
        action = r.get("action_type", "")
        if not code:
            stats["no_code"] += 1
            continue

        matches, method = find_best_match(code, action)
        if matches:
            r["manual_ref"] = matches
            stats[method] += 1
        else:
            r["manual_ref"] = []
            stats["none"] += 1
            unmatched.append({
                "row_id": r["row_id"],
                "code":   code,
                "action": action,
                "name":   r.get("business_name", "")[:50],
            })

    # 저장
    db["master_rows"] = rows
    DB_PATH.write_text(
        json.dumps(db, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 보고
    total = len(rows)
    print(f"=== 매핑 결과 (총 {total} rows) ===")
    print(f"  정확 매칭 (exact):   {stats['exact']:>4} ({stats['exact']/total*100:.1f}%)")
    print(f"  prefix 매칭:         {stats['prefix']:>4} ({stats['prefix']/total*100:.1f}%)")
    print(f"  매칭 실패 (none):    {stats['none']:>4} ({stats['none']/total*100:.1f}%)")
    if stats["no_code"]:
        print(f"  코드 없음:           {stats['no_code']:>4}")

    if unmatched:
        print(f"\n=== 매칭 실패 row {len(unmatched)}개 (LLM 폴백 또는 수동 매핑 필요) ===")
        # 코드별 그룹
        by_code = defaultdict(list)
        for u in unmatched:
            by_code[u["code"]].append(u)
        for code in sorted(by_code):
            items = by_code[code]
            print(f"  {code}: {len(items)}건")
            for u in items[:3]:
                print(f"    - {u['row_id']} {u['action']:15} {u['name']}")
            if len(items) > 3:
                print(f"    ... +{len(items)-3} more")

    print(f"\n[OK] DB 업데이트: {DB_PATH}")


if __name__ == "__main__":
    main()
