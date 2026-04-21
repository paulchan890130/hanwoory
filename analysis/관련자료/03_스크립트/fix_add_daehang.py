"""
대행업무수행확인서 일괄 추가 (2026-04-19)
- 위임장 있는 form_docs에 대행업무수행확인서 누락된 348건 추가
- 위임장 바로 뒤에 삽입: 통합신청서 | 위임장 | 대행업무수행확인서 | [나머지]
- 구분자를 ' | '로 정규화
"""
import json, sys, re
sys.stdout.reconfigure(encoding="utf-8")

db_path = r"C:\Users\윤찬\K.ID soft\backend\data\immigration_guidelines_db_v2.json"
with open(db_path, encoding="utf-8") as f:
    db = json.load(f)
rows = db["master_rows"]

TARGET = "대행업무수행확인서"
ANCHOR = "위임장"

fixed = 0
for r in rows:
    fd = r.get("form_docs", "")
    if ANCHOR not in fd:
        continue
    if TARGET in fd:
        continue

    # 구분자 정규화: 앞뒤 공백 포함 '|' → ' | '
    parts = [p.strip() for p in re.split(r"\s*\|\s*", fd)]
    idx = next((i for i, p in enumerate(parts) if p == ANCHOR or p.startswith(ANCHOR)), None)
    if idx is None:
        print(f"  [SKIP] {r.get('row_id')} 위임장 위치 찾기 실패: {fd}")
        continue

    parts.insert(idx + 1, TARGET)
    r["form_docs"] = " | ".join(parts)
    print(f"  [추가] {r.get('row_id')} {r.get('detailed_code')}")
    fixed += 1

print(f"\n[완료] {fixed}건 수정")

db["갱신일"] = "2026-04-19 (add 대행업무수행확인서)"
db["master_rows"] = rows
with open(db_path, "w", encoding="utf-8") as f:
    json.dump(db, f, ensure_ascii=False, separators=(",", ":"))
print(f"저장 완료: {db_path}")
