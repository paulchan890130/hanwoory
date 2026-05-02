"""369 row → 매뉴얼 정밀 매핑 (v3, 본문 전체 스캔 기반)."""
import json, sys, re
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from backend.services.manual_indexer_v6 import lookup as lookup_v3, INDEX_V6 as INDEX_V3

DB_PATH = ROOT / "backend" / "data" / "immigration_guidelines_db_v2.json"


def main():
    if not INDEX_V3.exists():
        print(f"인덱스 없음: {INDEX_V3}\n  → python backend/services/manual_indexer_v3.py build")
        sys.exit(1)

    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    rows = db["master_rows"]
    stats = defaultdict(int)
    by_match = defaultdict(list)

    for r in rows:
        code = r.get("detailed_code", "")
        action = r.get("action_type", "")
        if not code:
            r["manual_ref"] = []
            stats["no_code"] += 1
            continue
        matches = lookup_v3(code, action)
        r["manual_ref"] = matches
        if matches:
            mt = matches[0].get("match_type", "?")
            stats[mt] += 1
            by_match[mt].append(r)
        else:
            stats["none"] += 1
            by_match["none"].append(r)

    db["master_rows"] = rows
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")

    total = len(rows)
    print(f"=== v3 매핑 결과 (총 {total} rows) ===")
    print(f"  action_exact (정밀):     {stats['action_exact']:>4} ({stats['action_exact']/total*100:.1f}%)")
    print(f"  action_prefix (prefix):  {stats['action_prefix']:>4} ({stats['action_prefix']/total*100:.1f}%)")
    print(f"  section_only (자격만):    {stats['section_only']:>4} ({stats['section_only']/total*100:.1f}%)")
    print(f"  none (매칭 실패):         {stats['none']:>4} ({stats['none']/total*100:.1f}%)")
    print(f"  no_code:                  {stats['no_code']:>4}")

    if by_match["section_only"]:
        ad = defaultdict(int)
        for r in by_match["section_only"]:
            ad[r.get("action_type","")] += 1
        print(f"\n=== section_only ({len(by_match['section_only'])}건) action_type 분포 ===")
        for a in sorted(ad, key=lambda x: -ad[x]):
            print(f"  {a:30}: {ad[a]:>3}")

    if by_match["none"]:
        print(f"\n=== 매칭 실패 ({len(by_match['none'])}건) ===")
        for r in by_match["none"][:15]:
            print(f"  {r['row_id']} | {r.get('action_type','?'):20} | {r.get('detailed_code','-'):10} | {r.get('business_name','')[:40]}")

    print(f"\n[OK] DB 업데이트: {DB_PATH}")


if __name__ == "__main__":
    main()
