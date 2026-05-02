"""
LLM 처리 결과(llm_results.json)를 DB에 적용:
  1. manual_ref 갱신 (LLM이 결정한 정답 페이지)
  2. practical_notes에 새 실무 팁 추가
  3. corrections 적용 (DB 필드 수정)

backup: DB를 immigration_guidelines_db_v2.json.backup-{timestamp} 로 백업.
"""
from __future__ import annotations
import json, sys, shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

DB_PATH = ROOT / "backend" / "data" / "immigration_guidelines_db_v2.json"
RESULTS = ROOT / "backend" / "data" / "manuals" / "llm_results.json"


def main():
    if not RESULTS.exists():
        print(f"결과 파일 없음: {RESULTS}"); sys.exit(1)

    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    rows = db["master_rows"]
    row_by_id = {r["row_id"]: r for r in rows}

    results = json.loads(RESULTS.read_text(encoding="utf-8"))

    # 백업
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = DB_PATH.with_suffix(f".json.backup-{ts}")
    shutil.copy2(DB_PATH, backup)
    print(f"DB 백업: {backup.name}")

    stats = {"manual_ref": 0, "tips_added": 0, "corrections": 0, "errors": 0}

    for main_code, result in results.items():
        if "_error" in result:
            stats["errors"] += 1
            print(f"  [{main_code}] 오류: {result['_error']}")
            continue
        for upd in result.get("row_updates", []):
            row_id = upd.get("row_id")
            row = row_by_id.get(row_id)
            if not row:
                print(f"  [{main_code}] {row_id} 없음 건너뜀"); continue

            # 1. manual_ref 갱신
            if upd.get("manual_ref"):
                row["manual_ref"] = upd["manual_ref"]
                stats["manual_ref"] += 1

            # 2. practical_notes 추가
            tips = upd.get("practical_tips_to_add", [])
            if tips:
                existing = row.get("practical_notes", "").split("|") if row.get("practical_notes") else []
                existing = [t.strip() for t in existing if t.strip()]
                for t in tips:
                    t = t.strip()
                    if t and t not in existing:
                        existing.append(t)
                row["practical_notes"] = " | ".join(existing)
                stats["tips_added"] += len(tips)

            # 3. corrections
            corr = upd.get("corrections") or {}
            for field, value in corr.items():
                if field in {"supporting_docs", "form_docs", "fee_rule",
                             "exceptions_summary", "overview_short"}:
                    if value and value != row.get(field):
                        row[f"_prev_{field}"] = row.get(field, "")  # 이전 값 보존
                        row[field] = value
                        stats["corrections"] += 1

    db["master_rows"] = rows
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[OK] 적용 완료")
    print(f"  manual_ref 갱신: {stats['manual_ref']}")
    print(f"  실무 팁 추가:    {stats['tips_added']}")
    print(f"  수정사항 적용:    {stats['corrections']}")
    print(f"  오류 자격:        {stats['errors']}")


if __name__ == "__main__":
    main()
