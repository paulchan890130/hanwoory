"""
LLM 매핑 롤백: manual_ref만 backup의 v6 매핑으로 복원.
LLM이 추가한 practical_notes(464개)와 corrections(56개)는 유지.

LLM 처리 후 매핑이 일부 부정확해서, v6 인덱서 매핑으로 되돌리되
편람 기반 실무 팁과 DB 수정사항은 그대로 둠.
"""
import json, sys, shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
DB_PATH = ROOT / "backend" / "data" / "immigration_guidelines_db_v2.json"
# 가장 최근 백업
BACKUP_PATH = sorted((ROOT / "backend" / "data").glob("immigration_guidelines_db_v2.json.backup-*"))[-1]

print(f"백업 파일: {BACKUP_PATH.name}")
backup = json.loads(BACKUP_PATH.read_text(encoding="utf-8"))
current = json.loads(DB_PATH.read_text(encoding="utf-8"))

backup_by_id = {r["row_id"]: r for r in backup["master_rows"]}

# 현재 DB의 manual_ref만 백업 값으로 복원
restored = 0
for r in current["master_rows"]:
    bk = backup_by_id.get(r["row_id"])
    if bk and bk.get("manual_ref"):
        if r.get("manual_ref") != bk["manual_ref"]:
            r["manual_ref"] = bk["manual_ref"]
            restored += 1

# 새 백업 (현재 LLM 결과)
ts = datetime.now().strftime("%Y%m%d-%H%M%S")
new_backup = DB_PATH.with_suffix(f".json.backup-llm-{ts}")
shutil.copy2(DB_PATH, new_backup)
print(f"LLM 결과 백업: {new_backup.name}")

# 저장
DB_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n[OK] manual_ref 복원: {restored}건 (v6 매핑으로)")
print(f"  LLM 추가 팁/수정은 유지")
