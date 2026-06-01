"""Local-beta: import Accounts → local PostgreSQL.

Safety contract
---------------
* Refuses to run unless ``DATABASE_URL`` points at a loopback host
  (``localhost`` / ``127.0.0.1`` / ``::1``). See ``backend.db.local_guard``.
* Defaults to **dry-run** — prints what would be imported and exits.
  ``--execute`` is required for any actual ``INSERT``/``UPDATE``.
* Never writes to Google Sheets. The only Sheets access path used is
  ``backend.services.accounts_service._get_ws_readonly()``, which reads but
  cannot mutate.
* ``--seed-synthetic`` bypasses Google entirely and uses a tiny hardcoded
  dataset — the safest way to verify the import code path without involving
  any production data at all.

CLI
---
    # Dry-run from prod Accounts sheet (read-only)
    python backend/scripts/migrate_accounts_to_pg.py

    # Actually insert from prod sheet into local PG
    python backend/scripts/migrate_accounts_to_pg.py --execute

    # Code-path smoke test with 3 synthetic rows (no Sheets read at all)
    python backend/scripts/migrate_accounts_to_pg.py --seed-synthetic --execute

The synthetic dataset's password is ``beta_test_password_123`` — used to
verify ``/api/dev/pg/login-test`` round-trips correctly.
"""
from __future__ import annotations

import argparse
import os
import sys
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


def _truthy(s: object) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "y", "on", "활성", "active"}


def _falsy(s: object) -> bool:
    return str(s).strip().lower() in {"0", "false", "no", "n", "off", "비활성"}


def _build_synthetic_rows() -> list[dict]:
    """Three rows that exercise: admin, regular user, inactive user.

    The hash is generated fresh with the project's own hash function so
    ``verify_password`` round-trips correctly.
    """
    from backend.services.accounts_service import hash_password

    h = hash_password(SYNTHETIC_PASSWORD)
    return [
        {
            "login_id": "test_admin",
            "tenant_id": "test_admin",
            "password_hash": h,
            "office_name": "Beta Admin Office",
            "office_adr": "",
            "biz_reg_no": "",
            "folder_id": "",
            "customer_sheet_key": "",
            "work_sheet_key": "",
            "contact_name": "Beta Admin",
            "contact_tel": "",
            "is_admin": "TRUE",
            "is_active": "TRUE",
        },
        {
            "login_id": "test_user",
            "tenant_id": "test_user",
            "password_hash": h,
            "office_name": "Beta User Office",
            "office_adr": "",
            "biz_reg_no": "",
            "folder_id": "",
            "customer_sheet_key": "",
            "work_sheet_key": "",
            "contact_name": "Beta User",
            "contact_tel": "",
            "is_admin": "FALSE",
            "is_active": "TRUE",
        },
        {
            "login_id": "inactive_user",
            "tenant_id": "inactive_user",
            "password_hash": h,
            "office_name": "Inactive Office",
            "office_adr": "",
            "biz_reg_no": "",
            "folder_id": "",
            "customer_sheet_key": "",
            "work_sheet_key": "",
            "contact_name": "Inactive",
            "contact_tel": "",
            "is_admin": "FALSE",
            "is_active": "FALSE",
        },
    ]


def _read_accounts_from_sheet() -> list[dict]:
    print("[read] reading Accounts sheet (READ-ONLY — no writes)...")
    from backend.services.accounts_service import _get_ws_readonly

    ws = _get_ws_readonly()
    rows = ws.get_all_records()
    print(f"[read] {len(rows)} rows fetched")
    return rows


def main() -> int:
    # Windows console defaults to cp949 — force UTF-8 so em-dash etc. don't crash.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="Local-only Accounts → PG import (beta).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="See LOCAL_POSTGRES_BETA_PLAN.md §4 for the full command sequence.",
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help="Actually INSERT/UPDATE. Without this, run is dry-run (print only).",
    )
    ap.add_argument(
        "--seed-synthetic",
        action="store_true",
        help="Use 3 hardcoded synthetic rows; skip Google Sheets entirely.",
    )
    args = ap.parse_args()

    # 1) Hard local-only guard — must come before anything that could connect.
    from backend.db.local_guard import assert_local_database_url

    db_url = os.environ.get("DATABASE_URL")
    assert_local_database_url(db_url)
    print(f"[guard] DATABASE_URL host check: PASS (local loopback only)")

    # 2) Load source rows
    if args.seed_synthetic:
        print("[source] synthetic — Google Sheets NOT accessed.")
        rows = _build_synthetic_rows()
        print(f"[source] {len(rows)} synthetic rows prepared")
    else:
        rows = _read_accounts_from_sheet()

    if not rows:
        print("[abort] no rows to process")
        return 1

    # 3) Build plan
    tenants_plan: list[dict] = []
    users_plan: list[dict] = []
    skipped: list[tuple[str | None, str]] = []
    seen_tenants: set[str] = set()

    for r in rows:
        login_id = str(r.get("login_id", "")).strip()
        if not login_id:
            skipped.append((None, "missing login_id"))
            continue
        password_hash = str(r.get("password_hash", "")).strip()
        if not password_hash:
            skipped.append((login_id, "missing password_hash"))
            continue

        tenant_id = str(r.get("tenant_id", "") or login_id).strip()
        office_name = str(r.get("office_name", "")).strip() or "(no name)"
        is_active_raw = str(r.get("is_active", "")).strip()
        is_active = (
            False if _falsy(is_active_raw) else True  # default True when blank
        )
        is_admin = _truthy(r.get("is_admin", ""))

        if tenant_id not in seen_tenants:
            seen_tenants.add(tenant_id)
            tenants_plan.append({
                "tenant_id": tenant_id,
                "office_name": office_name,
                "office_adr": (str(r.get("office_adr", "")).strip() or None),
                "biz_reg_no": (str(r.get("biz_reg_no", "")).strip() or None),
                "folder_id": (str(r.get("folder_id", "")).strip() or None),
                "customer_sheet_key": (str(r.get("customer_sheet_key", "")).strip() or None),
                "work_sheet_key": (str(r.get("work_sheet_key", "")).strip() or None),
                "is_active": is_active,
            })

        users_plan.append({
            "login_id": login_id,
            "tenant_id": tenant_id,
            "password_hash": password_hash,
            "contact_name": (str(r.get("contact_name", "")).strip() or None),
            "contact_tel": (str(r.get("contact_tel", "")).strip() or None),
            "is_admin": is_admin,
            "is_active": is_active,
        })

    print()
    print(f"[plan] tenants : {len(tenants_plan)}")
    print(f"[plan] users   : {len(users_plan)}")
    print(f"[plan] skipped : {len(skipped)}")
    if skipped:
        for lid, reason in skipped[:5]:
            print(f"        - {lid}: {reason}")
        if len(skipped) > 5:
            print(f"        ... and {len(skipped) - 5} more")

    if not args.execute:
        print()
        print("[dry-run] no DB changes made. Re-run with --execute to insert.")
        if not args.seed_synthetic:
            print("[dry-run] (Google Sheets was read READ-ONLY; nothing modified there.)")
        return 0

    # 4) Apply
    print()
    print("[execute] upserting into local PG...")
    from sqlalchemy import select

    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    inserted_t = updated_t = inserted_u = updated_u = 0
    with SessionLocal() as session:
        for t in tenants_plan:
            existing = session.scalar(
                select(Tenant).where(Tenant.tenant_id == t["tenant_id"])
            )
            if existing is None:
                session.add(Tenant(**t))
                inserted_t += 1
            else:
                for k, v in t.items():
                    setattr(existing, k, v)
                updated_t += 1
        session.flush()  # make tenant rows visible for the FK from users

        for u in users_plan:
            existing = session.scalar(
                select(AccountUser).where(AccountUser.login_id == u["login_id"])
            )
            if existing is None:
                session.add(AccountUser(**u))
                inserted_u += 1
            else:
                for k, v in u.items():
                    setattr(existing, k, v)
                updated_u += 1
        session.commit()

    print(f"[execute] tenants: inserted={inserted_t} updated={updated_t}")
    print(f"[execute] users  : inserted={inserted_u} updated={updated_u}")
    if args.seed_synthetic:
        print()
        print(f"[hint] synthetic password = {SYNTHETIC_PASSWORD}")
        print(f"[hint] try: POST /api/dev/pg/login-test  body={{login_id:'test_admin', password:'{SYNTHETIC_PASSWORD}'}}")
    print("[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
