"""고객 날짜 4개 컬럼 정리 (로컬 전용).

마이그레이션 데이터 중 yyyy-mm-dd hh:mm:ss / ISO timestamp 형태로 저장된
날짜를 날짜부만(yyyy-mm-dd) 남기도록 정리한다.

대상 컬럼(전부 TEXT):
  card_issue_date      등록증 발급일
  card_expiry_date     체류 만료일
  passport_issue_date  여권 발급일
  passport_expiry_date 여권 만기일

규칙:
  2026-06-24 00:00:00  → 2026-06-24   (converted)
  2026-06-24 15:30:00  → 2026-06-24   (converted)
  2026-06-24T15:30:00Z → 2026-06-24   (converted)
  2026.06.24 ...       → 2026-06-24   (converted)
  20260624             → 2026-06-24   (converted)
  2026-06-24           → 변경 없음     (already)
  빈값                 → skip
  판독 불가/이상 포맷   → 변환하지 않고 보고만 (unparseable)

원칙: 멱등 · dry-run 기본 · --apply 시에만 UPDATE · 운영 DB 실행 금지 ·
민감정보(reg_back/passport_no/주소) 미출력(고객ID·필드·날짜문자열만).

사용:
  python -m backend.scripts.cleanup_customer_dates           # dry-run
  python -m backend.scripts.cleanup_customer_dates --apply   # 로컬 DB 반영
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

DATE_COLUMNS = [
    ("card_issue_date", "등록증 발급일"),
    ("card_expiry_date", "체류 만료일"),
    ("passport_issue_date", "여권 발급일"),
    ("passport_expiry_date", "여권 만기일"),
]

_YMD = re.compile(r"^(\d{4})-(\d{2})-(\d{2})([ T].*)?$")
_DOTTED = re.compile(r"^(\d{4})[./](\d{2})[./](\d{2})([ T].*)?$")
_YYYYMMDD = re.compile(r"^\d{8}$")


def to_date_only(v):
    """(new_value, status). status ∈ empty/already/converted/unparseable."""
    if v is None:
        return None, "empty"
    s = str(v).strip()
    if not s:
        return s, "empty"
    m = _YMD.match(s)
    if m:
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        return date, ("already" if not m.group(4) else "converted")
    m = _DOTTED.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "converted"
    if _YYYYMMDD.match(s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}", "converted"
    return s, "unparseable"


def run(apply: bool):
    from backend.db.models.customer import Customer
    from backend.db.session import get_sessionmaker
    from sqlalchemy import select

    SessionLocal = get_sessionmaker()
    per_field = {col: 0 for col, _ in DATE_COLUMNS}
    examples = []          # (cust, field, before, after)
    unparseable = []       # (cust, field, raw)
    total_rows = 0
    changed_rows = 0

    with SessionLocal() as session:
        rows = session.scalars(select(Customer)).all()
        total_rows = len(rows)
        for row in rows:
            row_changed = False
            for col, _label in DATE_COLUMNS:
                cur = getattr(row, col, None)
                new, status = to_date_only(cur)
                if status == "converted" and new != (cur or ""):
                    per_field[col] += 1
                    if len(examples) < 10:
                        examples.append((row.customer_id, col, str(cur), new))
                    if apply:
                        setattr(row, col, new)
                    row_changed = True
                elif status == "unparseable":
                    unparseable.append((row.customer_id, col, str(cur)))
            if row_changed:
                changed_rows += 1
        if apply:
            session.commit()

    total_changes = sum(per_field.values())
    print(f"전체 고객 행: {total_rows}")
    print(f"변환 대상 행: {changed_rows}")
    print(f"변환 대상 값(필드 합계): {total_changes}")
    print("\n[필드별 변환 대상 건수]")
    for col, label in DATE_COLUMNS:
        print(f"  {label:<12} ({col:<20}): {per_field[col]}")

    print("\n[변환 예시 (최대 10건)]")
    if not examples:
        print("  (없음)")
    for cust, col, before, after in examples:
        print(f"  고객ID={cust} {col}: '{before}' -> '{after}'")

    print(f"\n[판독 불가 / 이상 포맷 — 변환하지 않음: {len(unparseable)}건]")
    if not unparseable:
        print("  (없음)")
    for cust, col, raw in unparseable[:50]:
        print(f"  고객ID={cust} {col}: '{raw}'")
    if len(unparseable) > 50:
        print(f"  ... 외 {len(unparseable) - 50}건")

    if apply:
        print(f"\n[APPLIED] {total_changes}건 날짜 정리 완료.")
    else:
        print("\n[DRY-RUN] 쓰기 없음. 실제 반영하려면 --apply 옵션을 사용하세요.")


def main():
    parser = argparse.ArgumentParser(description="고객 날짜 4개 컬럼 정리 (로컬 전용)")
    parser.add_argument("--apply", action="store_true", help="실제 DB 반영 (기본: dry-run)")
    args = parser.parse_args()

    from backend.db import session as db_session
    if not db_session.is_configured():
        print("[ERROR] PostgreSQL 미구성 (DATABASE_URL 없음). 로컬 DB 설정 후 실행하세요.")
        sys.exit(1)

    print(f"=== 고객 날짜 정리 ({'APPLY' if args.apply else 'DRY-RUN'}) ===")
    run(args.apply)


if __name__ == "__main__":
    main()
