"""Backfill ``completed_tasks.customer_id`` from name → unique-customer match.

Local PG only. Row-level UPDATE only (no full table overwrite).

Rule
----
For each row in ``completed_tasks`` whose ``customer_id`` is NULL or empty:

  1. Take the row's ``name`` (Korean name as stored on the legacy completed
     row).
  2. Within the same tenant, look up active customers whose ``korean_name``
     matches **exactly** (after strip).
  3. If exactly **one** customer matches → UPDATE that single row's
     ``customer_id`` field.
  4. If **zero** matches → skip (orphan legacy row, leave alone).
  5. If **two or more** matches → skip (ambiguous, leave alone) and count
     toward ``ambiguous`` so the caller can audit.

Safety
------
* ``backend.db.local_guard.assert_local_database_url`` refuses non-loopback
  hosts.
* Default mode is **dry-run** — no DB writes. Pass ``--execute`` to apply.
* Never deletes any row. Never touches rows whose ``customer_id`` is already
  populated. Pure additive UPDATE.

CLI
---

    python backend/scripts/backfill_completed_customer_id.py
    python backend/scripts/backfill_completed_customer_id.py --execute
    python backend/scripts/backfill_completed_customer_id.py --execute --tenant hanwoory
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def _utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass


def main() -> int:
    _utf8()
    parser = argparse.ArgumentParser(description="Backfill completed_tasks.customer_id from name match (local PG only).")
    parser.add_argument("--execute", action="store_true", help="Actually write to PG. Default dry-run.")
    parser.add_argument("--tenant", default=None, help="Only process this tenant (default: all).")
    args = parser.parse_args()

    from backend.db.local_guard import assert_local_database_url
    assert_local_database_url(os.environ.get("DATABASE_URL"))

    from sqlalchemy import select
    from backend.db.models.customer import Customer
    from backend.db.models.task import CompletedTask
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    stats = {"scanned": 0, "matched_unique": 0, "ambiguous": 0, "no_match": 0, "updated": 0}
    ambiguous_names: dict[str, set[str]] = defaultdict(set)

    with SessionLocal() as session:
        # Build the tenant → {korean_name → [customer_id, ...]} index once.
        cust_q = select(Customer).where(Customer.deleted_at.is_(None))
        if args.tenant:
            cust_q = cust_q.where(Customer.tenant_id == args.tenant)
        index: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for c in session.scalars(cust_q).all():
            tid = c.tenant_id
            nm = (c.korean_name or "").strip()
            if not nm:
                continue
            index[tid][nm].append(c.customer_id)
        print(f"[index] built — tenants={len(index)}, names={sum(len(v) for v in index.values())}")

        # Scan completed_tasks with empty/null customer_id.
        comp_q = select(CompletedTask).where(
            (CompletedTask.customer_id.is_(None)) | (CompletedTask.customer_id == "")
        )
        if args.tenant:
            comp_q = comp_q.where(CompletedTask.tenant_id == args.tenant)
        rows = session.scalars(comp_q).all()
        print(f"[scan] {len(rows)} completed_tasks rows with empty customer_id")

        for row in rows:
            stats["scanned"] += 1
            nm = (row.name or "").strip()
            if not nm:
                stats["no_match"] += 1
                continue
            candidates = index.get(row.tenant_id, {}).get(nm, [])
            if len(candidates) == 1:
                stats["matched_unique"] += 1
                if args.execute:
                    # Row-level UPDATE — only this row's customer_id.
                    row.customer_id = candidates[0]
                    stats["updated"] += 1
            elif len(candidates) >= 2:
                stats["ambiguous"] += 1
                ambiguous_names[row.tenant_id].add(nm)
            else:
                stats["no_match"] += 1

        if args.execute:
            session.commit()

    print()
    print(f"[result] {'EXECUTED' if args.execute else 'DRY-RUN'}")
    for k, v in stats.items():
        print(f"  {k:18s} {v}")
    if ambiguous_names:
        print()
        print(f"[ambiguous] names skipped (multiple customers share same Korean name):")
        for tid, names in ambiguous_names.items():
            print(f"  tenant={tid} count={len(names)}")
            for nm in sorted(names)[:10]:
                print(f"    - {nm}")
            if len(names) > 10:
                print(f"    ... and {len(names)-10} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
