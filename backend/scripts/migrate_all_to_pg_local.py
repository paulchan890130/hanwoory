"""Local-beta orchestrator — seed every implemented domain in one shot.

Safety contract (same as ``migrate_accounts_to_pg.py``):
* Refuses unless ``DATABASE_URL`` host is loopback (``localhost``/``127.0.0.1``/``::1``).
* Dry-run by default; ``--execute`` is required for any DB write.
* **Never writes to Google Sheets or Drive.** The default ``--source synthetic``
  doesn't even read from Google. ``--source sheets`` (opt-in) reads from
  the production Sheets read-only.

Domains seeded:
* tenants + users (delegates to migrate_accounts_to_pg.py logic)
* customers
* events
* memos (short / mid / long)
* daily_entries + daily_balance
* active_tasks / planned_tasks / completed_tasks

CLI
---
    # Default — synthetic seed for every domain into local PG (dry-run)
    python backend/scripts/migrate_all_to_pg_local.py

    # Actually write
    python backend/scripts/migrate_all_to_pg_local.py --execute

    # Only certain domains
    python backend/scripts/migrate_all_to_pg_local.py --execute --only customers,events

    # Reset all implemented tables (DELETE rows) before seeding
    python backend/scripts/migrate_all_to_pg_local.py --execute --reset
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


SYNTHETIC_PASSWORD = "beta_test_password_123"
SYNTHETIC_TENANT_IDS = ("test_admin", "test_user")


def _utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass


def _seed_tenants_users() -> tuple[int, int]:
    """Insert the two synthetic tenants + 3 users (admin/user/inactive)."""
    from sqlalchemy import select

    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services.accounts_service import hash_password

    h = hash_password(SYNTHETIC_PASSWORD)
    tenants_seed = [
        {"tenant_id": "test_admin", "office_name": "Beta Admin Office", "is_active": True},
        {"tenant_id": "test_user", "office_name": "Beta User Office", "is_active": True},
        {"tenant_id": "inactive_user", "office_name": "Inactive Office", "is_active": False},
    ]
    users_seed = [
        {"login_id": "test_admin", "tenant_id": "test_admin", "password_hash": h,
         "is_admin": True, "is_active": True, "contact_name": "Beta Admin"},
        {"login_id": "test_user", "tenant_id": "test_user", "password_hash": h,
         "is_admin": False, "is_active": True, "contact_name": "Beta User"},
        {"login_id": "inactive_user", "tenant_id": "inactive_user", "password_hash": h,
         "is_admin": False, "is_active": False, "contact_name": "Inactive"},
    ]

    SessionLocal = get_sessionmaker()
    n_t = n_u = 0
    with SessionLocal() as session:
        for t in tenants_seed:
            row = session.scalar(select(Tenant).where(Tenant.tenant_id == t["tenant_id"]))
            if row is None:
                session.add(Tenant(**t))
                n_t += 1
            else:
                for k, v in t.items():
                    setattr(row, k, v)
        session.flush()
        for u in users_seed:
            row = session.scalar(select(AccountUser).where(AccountUser.login_id == u["login_id"]))
            if row is None:
                session.add(AccountUser(**u))
                n_u += 1
            else:
                for k, v in u.items():
                    setattr(row, k, v)
        session.commit()
    return n_t, n_u


def _seed_customers() -> int:
    """Create 3 customers under test_admin tenant."""
    from backend.services.customer_pg_service import upsert_customer

    fixtures = [
        {
            "고객ID": "0001", "한글": "김민수", "성": "KIM", "명": "MINSU",
            "여권": "M12345678", "국적": "대한민국", "성별": "남",
            "등록증": "900101", "번호": "1234567", "발급일": "2020-01-15",
            "만기일": "2030-01-14", "발급": "2020-03-01", "만기": "2030-02-28",
            "주소": "서울시 강남구 역삼동", "연": "010", "락": "1234", "처": "5678",
            "체류자격": "F-2", "비자종류": "거주", "메모": "베타 테스트 고객 1",
        },
        {
            "고객ID": "0002", "한글": "이수민", "성": "LEE", "명": "SUMIN",
            "여권": "P87654321", "국적": "대한민국", "성별": "여",
            "등록증": "920505", "번호": "2345678", "발급일": "2021-06-10",
            "만기일": "2026-09-30", "발급": "2021-07-01", "만기": "2026-12-31",
            "주소": "서울시 마포구 합정동", "연": "010", "락": "9876", "처": "5432",
            "체류자격": "D-10", "비자종류": "구직", "메모": "곧 만기 — 알림 테스트",
        },
        {
            "고객ID": "0003", "한글": "박지영", "성": "PARK", "명": "JIYOUNG",
            "여권": "K11223344", "국적": "대한민국", "성별": "여",
            "등록증": "880812", "번호": "3456789", "발급일": "2019-03-20",
            "만기일": "2029-03-19", "발급": "2019-04-01", "만기": "2029-04-30",
            "주소": "부산시 해운대구", "연": "010", "락": "5555", "처": "1111",
            "체류자격": "F-5", "비자종류": "영주", "메모": "베타 테스트 고객 3",
        },
    ]
    n = 0
    for f in fixtures:
        upsert_customer("test_admin", f)
        n += 1
    return n


def _seed_events() -> int:
    """Add events on three dates under test_admin."""
    from backend.services.events_pg_service import save_events_for_date

    today_iso = "2026-06-02"  # current date per session reminder
    seed = {
        today_iso: ["오전 — 베타 회의", "오후 — 고객 0001 면담"],
        "2026-06-10": ["진행업무 마감 검토"],
        "2026-06-25": ["월말 정산"],
    }
    n = 0
    for d, lines in seed.items():
        save_events_for_date("test_admin", d, lines)
        n += len(lines)
    return n


def _seed_memos() -> int:
    from backend.services.memos_pg_service import save_memo

    save_memo("test_admin", "short", "오늘 처리할 일: 위임장 PDF 1건 출력")
    save_memo("test_admin", "mid", "이번 주 — F-2 갱신 5건, 사회통합프로그램 신청 안내")
    save_memo("test_admin", "long", "베타 테스트 기간 동안 누적 메모 영역")
    return 3


def _seed_daily() -> tuple[int, int]:
    from backend.services.daily_pg_service import save_balance, upsert_entry

    entries = [
        {
            "id": str(uuid.uuid4()), "date": "2026-06-02", "time": "10:00",
            "category": "전자민원", "name": "김민수", "task": "F-2 체류기간 연장",
            "income_cash": 50000, "income_etc": 0,
            "exp_cash": 0, "exp_etc": 30000, "cash_out": 0,
            "memo": "베타 시드 #1", "customer_id": "0001",
        },
        {
            "id": str(uuid.uuid4()), "date": "2026-06-02", "time": "14:30",
            "category": "공증", "name": "이수민", "task": "위임장 공증",
            "income_cash": 0, "income_etc": 80000,
            "exp_cash": 25000, "exp_etc": 0, "cash_out": 0,
            "memo": "베타 시드 #2", "customer_id": "0002",
        },
        {
            "id": str(uuid.uuid4()), "date": "2026-06-01", "time": "09:00",
            "category": "출입국", "name": "박지영", "task": "영주증 발급 신청",
            "income_cash": 100000, "income_etc": 0,
            "exp_cash": 0, "exp_etc": 0, "cash_out": 0,
            "memo": "베타 시드 #3", "customer_id": "0003",
        },
    ]
    n = 0
    for e in entries:
        upsert_entry("test_admin", e)
        n += 1
    save_balance("test_admin", cash=350000, profit=175000)
    return n, 1


def _seed_tasks() -> tuple[int, int, int]:
    from backend.services.tasks_pg_service import (
        upsert_active, upsert_completed, upsert_planned,
    )

    active = [
        {
            "id": "active-001", "category": "전자민원", "date": "2026-06-02",
            "name": "김민수", "work": "F-2 체류기간 연장", "details": "",
            "transfer": "0", "cash": "50000", "card": "0", "stamp": "0",
            "receivable": "0", "planned_expense": "30000",
            "processed": False, "reception": "2026-06-02T10:05:00Z",
            "processing": "", "storage": "", "customer_id": "0001",
        },
        {
            "id": "active-002", "category": "공증", "date": "2026-06-02",
            "name": "이수민", "work": "위임장 공증", "details": "외국 대학 제출용",
            "transfer": "0", "cash": "0", "card": "80000", "stamp": "0",
            "receivable": "0", "planned_expense": "25000",
            "processed": False, "reception": "2026-06-02T14:35:00Z",
            "processing": "2026-06-02T15:10:00Z", "storage": "", "customer_id": "0002",
        },
    ]
    planned = [
        {
            "id": "planned-001", "date": "2026-06-15",
            "period": "오전", "content": "정기 만기 점검", "note": "월 1회 루틴",
        },
    ]
    completed = [
        {
            "id": "completed-001", "category": "출입국", "date": "2026-05-30",
            "name": "박지영", "work": "영주증 발급 신청", "details": "",
            "complete_date": "2026-06-01",
            "reception": "2026-05-30", "processing": "2026-05-31",
            "storage": "2026-06-01", "customer_id": "0003",
        },
    ]
    n_a = n_p = n_c = 0
    for t in active:
        upsert_active("test_admin", t)
        n_a += 1
    for t in planned:
        upsert_planned("test_admin", t)
        n_p += 1
    for t in completed:
        upsert_completed("test_admin", t)
        n_c += 1
    return n_a, n_p, n_c


def _reset_tables() -> None:
    """Delete all rows from implemented domain tables. Local-only safety net."""
    from sqlalchemy import delete

    from backend.db.models.audit import AuditLog
    from backend.db.models.customer import Customer
    from backend.db.models.daily import DailyBalance, DailyEntry
    from backend.db.models.event import Event
    from backend.db.models.memo import Memo
    from backend.db.models.task import ActiveTask, CompletedTask, PlannedTask
    from backend.db.models.user import AccountUser
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        for model in (
            ActiveTask, PlannedTask, CompletedTask,
            DailyEntry, DailyBalance,
            Event, Memo, Customer, AuditLog,
            AccountUser, Tenant,
        ):
            session.execute(delete(model))
        session.commit()


def main() -> int:
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="Seed every implemented PG domain (local beta).")
    ap.add_argument("--execute", action="store_true",
                    help="Actually write. Default = dry-run (print plan only).")
    ap.add_argument("--reset", action="store_true",
                    help="DELETE all rows from implemented tables first. Local-only safety.")
    ap.add_argument(
        "--only", default="all",
        help="Comma-separated subset of: tenants_users,customers,events,memos,daily,tasks (default: all)",
    )
    args = ap.parse_args()

    # 1) Hard local-only guard
    from backend.db.local_guard import assert_local_database_url
    assert_local_database_url(os.environ.get("DATABASE_URL"))
    print(f"[guard] DATABASE_URL host: PASS (loopback)")

    domains = {"tenants_users", "customers", "events", "memos", "daily", "tasks"}
    if args.only != "all":
        wanted = {x.strip() for x in args.only.split(",") if x.strip()}
        unknown = wanted - domains
        if unknown:
            print(f"[abort] unknown domains: {unknown}", file=sys.stderr)
            return 2
        domains = wanted

    print(f"[plan] domains: {sorted(domains)}")
    print(f"[plan] mode   : {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print(f"[plan] reset  : {bool(args.reset)}")

    if not args.execute:
        print()
        print("[dry-run] Would seed the listed domains with synthetic data into local PG.")
        print("[dry-run] No Google Sheets or Drive access. No DB writes.")
        print("[dry-run] Re-run with --execute to actually write.")
        return 0

    # 2) Optional reset
    if args.reset:
        print("[reset] DELETE FROM all implemented tables...")
        _reset_tables()

    # 3) Apply
    total = {"tenants": 0, "users": 0, "customers": 0, "events": 0, "memos": 0,
             "daily_entries": 0, "daily_balance": 0,
             "active_tasks": 0, "planned_tasks": 0, "completed_tasks": 0}

    if "tenants_users" in domains:
        nt, nu = _seed_tenants_users()
        total["tenants"], total["users"] = nt, nu
    if "customers" in domains:
        total["customers"] = _seed_customers()
    if "events" in domains:
        total["events"] = _seed_events()
    if "memos" in domains:
        total["memos"] = _seed_memos()
    if "daily" in domains:
        de, db = _seed_daily()
        total["daily_entries"], total["daily_balance"] = de, db
    if "tasks" in domains:
        na, np, nc = _seed_tasks()
        total["active_tasks"], total["planned_tasks"], total["completed_tasks"] = na, np, nc

    print()
    print("[done] inserted/updated:")
    for k, v in total.items():
        print(f"  {k:<20} {v}")
    print()
    print(f"[hint] synthetic password = {SYNTHETIC_PASSWORD}")
    print(f"[hint] admin login        = test_admin / {SYNTHETIC_PASSWORD}")
    print(f"[hint] user  login        = test_user  / {SYNTHETIC_PASSWORD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
