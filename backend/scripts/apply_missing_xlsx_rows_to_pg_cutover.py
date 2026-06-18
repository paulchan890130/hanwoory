"""Apply ONLY the missing latest-snapshot rows into PostgreSQL (hanwoory cutover).

Companion to ``diff_latest_xlsx_vs_pg.py``. It re-computes the diff live and
**inserts only the rows whose natural key is absent from PG**. It is the narrow,
auditable "catch-up" path for the 43 rows the latest exported snapshot has
that Render PG does not yet have.

Hard safety contract
--------------------
* **Insert-only of missing keys.** A row is written *only* when its key does not
  already exist in PG. Existing rows are **never updated** → existing non-empty
  PG values can never be overwritten with blank sheet values.
* **No** delete / truncate / table-clear / reset / broad replace anywhere.
* **Dry-run by default.** Writing requires ALL of:
    --apply  --allow-remote-render-pg  --confirm "<exact string>"
  (the loopback case still requires --apply + --confirm; --allow-remote only
  matters for a non-local host such as Render).
* Scope is **hanwoory only** and only these domains:
  customers / 진행업무(active) / 완료업무(completed) / 일일결산(daily) /
  일정(events) / 숙소제공자연결(lodging) / 신원보증인연결(guarantor).
  It never opens the work workbook, so certification / 기타업무참고 / work_ref
  are untouched; jpup, accounts, tenants, board, marketing, manual_ref, and
  No external API is read or written.
* Logs only counts + safe IDs (고객ID / task_id / entry_id / target_customer_id /
  date). Never prints DATABASE_URL, secrets, or full row contents.

CLI
---
    # dry-run (default; still reads PG to recompute the missing set)
    .venv\\Scripts\\python.exe -X utf8 backend\\scripts\\apply_missing_xlsx_rows_to_pg_cutover.py --tenant hanwoory --dry-run

    # apply (triple-gated)
    .venv\\Scripts\\python.exe -X utf8 backend\\scripts\\apply_missing_xlsx_rows_to_pg_cutover.py --tenant hanwoory --apply --allow-remote-render-pg --confirm "I-UNDERSTAND-APPLY-MISSING-XLSX-ROWS-TO-RENDER-PG"
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# Reuse the importer's parsing + customer mapping so keys/fields match exactly.
from backend.scripts.import_excel_snapshot_to_pg_local import (  # noqa: E402
    _open_xlsx, _read_tab, _rows_to_dicts, _customer_row_to_pg,
)
from backend.db.local_guard import (  # noqa: E402
    LOCAL_HOSTS, database_host, mask_host, looks_render_host,
)

APPLY_CONFIRM_STRING = "I-UNDERSTAND-APPLY-MISSING-XLSX-ROWS-TO-RENDER-PG"
SCOPE_TENANT = "hanwoory"
CUSTOMERS_FILE = "신 고객 데이터.xlsx"   # holds customers/tasks/daily/events/relationships tabs

_REPORT: list[str] = []


def _utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass


def _say(msg: str = "") -> None:
    print(msg, flush=True)
    _REPORT.append(msg)


def _norm(v: Any) -> str:
    return str(v or "").strip()


def _to_int(v: Any) -> int:
    s = str(v or "").strip().replace(",", "")
    if not s or s in ("-", "."):
        return 0
    try:
        return int(float(s))
    except Exception:
        return 0


# ── field builders (mirror import_excel_snapshot_to_pg_local exactly) ───────


def _active_fields(d: dict) -> dict:
    proc_raw = _norm(d.get("processed")).upper()
    return {
        "category": d.get("category") or None,
        "date": d.get("date") or None,
        "name": d.get("name") or None,
        "work": d.get("work") or None,
        "details": d.get("details") or None,
        "transfer": d.get("transfer") or None,
        "cash": d.get("cash") or None,
        "card": d.get("card") or None,
        "stamp": d.get("stamp") or None,
        "receivable": d.get("receivable") or None,
        "planned_expense": d.get("planned_expense") or None,
        "processed": proc_raw in ("TRUE", "1", "Y", "YES"),
        "processed_timestamp": d.get("processed_timestamp") or None,
        "reception": d.get("reception") or None,
        "processing": d.get("processing") or None,
        "storage": d.get("storage") or None,
        "customer_id": d.get("customer_id") or None,
        "source_daily_id": d.get("source_daily_id") or None,
    }


def _completed_fields(d: dict) -> dict:
    return {
        "category": d.get("category") or None,
        "date": d.get("date") or None,
        "name": d.get("name") or None,
        "work": d.get("work") or None,
        "details": d.get("details") or None,
        "complete_date": d.get("complete_date") or None,
        "reception": d.get("reception") or None,
        "processing": d.get("processing") or None,
        "storage": d.get("storage") or None,
        "customer_id": d.get("customer_id") or None,
    }


def _daily_fields(d: dict) -> dict:
    return {
        "date": d.get("date") or None,
        "time": d.get("time") or None,
        "category": d.get("category") or None,
        "name": d.get("name") or None,
        "task": d.get("task") or None,
        "income_cash": _to_int(d.get("income_cash")),
        "income_etc": _to_int(d.get("income_etc")),
        "exp_cash": _to_int(d.get("exp_cash")),
        "exp_etc": _to_int(d.get("exp_etc")),
        "cash_out": _to_int(d.get("cash_out")),
        "memo": d.get("memo") or None,
        "customer_id": d.get("customer_id") or None,
    }


_LODGING_FIELDS = [
    "provider_type", "provider_customer_id", "provider_name",
    "provider_last_name", "provider_first_name", "provider_nation",
    "provider_reg_front", "provider_reg_back", "provider_birth",
    "provider_phone", "provider_address", "provider_relation",
    "provide_start_date", "provide_end_date", "housing_type",
]
_GUARANTOR_FIELDS = [
    "guarantor_type", "guarantor_customer_id", "guarantor_name",
    "guarantor_last_name", "guarantor_first_name", "guarantor_nation",
    "guarantor_reg_front", "guarantor_reg_back", "guarantor_birth",
    "guarantor_phone", "guarantor_address", "guarantor_relation",
    "guarantor_workplace", "guarantor_extra",
]


# ── domain result ───────────────────────────────────────────────────────────


class Stat:
    def __init__(self, domain: str):
        self.domain = domain
        self.sheet = 0
        self.no_key = 0
        self.pg = 0
        self.missing_ids: list[str] = []
        self.inserted = 0
        self.exceptions: list[str] = []   # explicitly explained skips


def _generic(
    stat: Stat,
    sheet_dicts: list[dict],
    key_fn: Callable[[dict], str],
    pg_keys: set[str],
    build_fn: Callable[[str, dict], Any],
    id_fn: Callable[[str, dict], str],
    *,
    write: bool,
    session,
) -> None:
    stat.pg = len(pg_keys)
    seen: set[str] = set()
    for d in sheet_dicts:
        k = _norm(key_fn(d))
        if not k:
            stat.no_key += 1
            continue
        if k in seen:
            continue
        seen.add(k)
        stat.sheet += 1
        if k in pg_keys:
            continue  # already present → not missing → never touched
        stat.missing_ids.append(id_fn(k, d))
        if write:
            session.add(build_fn(k, d))
            stat.inserted += 1


# ── apply driver ────────────────────────────────────────────────────────────


def run(session, wb, *, write: bool) -> list[Stat]:
    from sqlalchemy import select, func
    from backend.db.models.customer import Customer
    from backend.db.models.task import ActiveTask, CompletedTask
    from backend.db.models.daily import DailyEntry
    from backend.db.models.event import Event
    from backend.db.models.relationship import AccommodationProvider, GuarantorConnection

    t = SCOPE_TENANT
    stats: list[Stat] = []

    # ── customers (고객ID) — existence vs ALL rows incl. soft-deleted ──
    s = Stat("customers[hanwoory]")
    all_ids = {_norm(x) for x in session.scalars(
        select(Customer.customer_id).where(Customer.tenant_id == t)).all()}
    deleted_ids = {_norm(x) for x in session.scalars(
        select(Customer.customer_id).where(
            Customer.tenant_id == t, Customer.deleted_at.is_not(None))).all()}

    def _build_customer(k: str, d: dict):
        pg = _customer_row_to_pg(d)
        pg.pop("customer_id", None)
        return Customer(tenant_id=t, customer_id=k, **pg)

    h, rows = _read_tab(wb, "고객 데이터")
    # annotate soft-deleted collisions as explicit exceptions (never resurrect)
    seen: set[str] = set()
    for d in _rows_to_dicts(h, rows):
        cid = _norm(d.get("고객ID"))
        if cid and cid in deleted_ids and cid not in seen:
            s.exceptions.append(f"{cid} (PG soft-deleted → 미적용, 부활 안 함)")
        seen.add(cid)
    _generic(s, _rows_to_dicts(h, rows), lambda d: d.get("고객ID"),
             all_ids, _build_customer, lambda k, d: k, write=write, session=session)
    if write:
        session.commit()
    stats.append(s)

    # ── 진행업무 / active (task_id = explicit id) ──
    s = Stat("진행업무[hanwoory]")
    pg = {_norm(x) for x in session.scalars(
        select(ActiveTask.task_id).where(ActiveTask.tenant_id == t)).all()}
    h, rows = _read_tab(wb, "진행업무")
    _generic(s, _rows_to_dicts(h, rows), lambda d: d.get("id"), pg,
             lambda k, d: ActiveTask(tenant_id=t, task_id=k, **_active_fields(d)),
             lambda k, d: k, write=write, session=session)
    if write:
        session.commit()
    stats.append(s)

    # ── 완료업무 / completed (task_id = explicit id) ──
    s = Stat("완료업무[hanwoory]")
    pg = {_norm(x) for x in session.scalars(
        select(CompletedTask.task_id).where(CompletedTask.tenant_id == t)).all()}
    h, rows = _read_tab(wb, "완료업무")
    _generic(s, _rows_to_dicts(h, rows), lambda d: d.get("id"), pg,
             lambda k, d: CompletedTask(tenant_id=t, task_id=k, **_completed_fields(d)),
             lambda k, d: k, write=write, session=session)
    if write:
        session.commit()
    stats.append(s)

    # ── 일일결산 / daily (entry_id = explicit id) ──
    s = Stat("일일결산[hanwoory]")
    pg = {_norm(x) for x in session.scalars(
        select(DailyEntry.entry_id).where(DailyEntry.tenant_id == t)).all()}
    h, rows = _read_tab(wb, "일일결산")
    _generic(s, _rows_to_dicts(h, rows), lambda d: d.get("id"), pg,
             lambda k, d: DailyEntry(tenant_id=t, entry_id=k, **_daily_fields(d)),
             lambda k, d: k, write=write, session=session)
    if write:
        session.commit()
    stats.append(s)

    # ── 일정 / events (no natural key → (date_str|event_text); append-only) ──
    s = Stat("일정[hanwoory]")
    existing = session.execute(select(Event.date_str, Event.event_text).where(
        Event.tenant_id == t)).all()
    pg = {f"{_norm(a)}|{_norm(b)}" for a, b in existing}
    next_order = (session.scalar(select(func.max(Event.sort_order)).where(
        Event.tenant_id == t)) or 0) + 1
    counter = {"n": next_order}

    def _build_event(k: str, d: dict):
        ev = Event(tenant_id=t, date_str=_norm(d.get("date_str")),
                   event_text=_norm(d.get("event_text")), sort_order=counter["n"])
        counter["n"] += 1
        return ev

    h, rows = _read_tab(wb, "일정")
    _generic(s, _rows_to_dicts(h, rows),
             lambda d: f"{_norm(d.get('date_str'))}|{_norm(d.get('event_text'))}",
             pg, _build_event, lambda k, d: _norm(d.get("date_str")) or "(no-date)",
             write=write, session=session)
    if write:
        session.commit()
    stats.append(s)

    # ── 숙소제공자연결 / lodging (target_customer_id) ──
    s = Stat("숙소제공자연결[hanwoory]")
    pg = {_norm(x) for x in session.scalars(
        select(AccommodationProvider.target_customer_id).where(
            AccommodationProvider.tenant_id == t)).all()}
    h, rows = _read_tab(wb, "숙소제공자연결")
    _generic(s, _rows_to_dicts(h, rows), lambda d: d.get("target_customer_id"), pg,
             lambda k, d: AccommodationProvider(
                 tenant_id=t, target_customer_id=k,
                 **{f: (d.get(f) or None) for f in _LODGING_FIELDS}),
             lambda k, d: k, write=write, session=session)
    if write:
        session.commit()
    stats.append(s)

    # ── 신원보증인연결 / guarantor (target_customer_id) ──
    s = Stat("신원보증인연결[hanwoory]")
    pg = {_norm(x) for x in session.scalars(
        select(GuarantorConnection.target_customer_id).where(
            GuarantorConnection.tenant_id == t)).all()}
    h, rows = _read_tab(wb, "신원보증인연결")
    _generic(s, _rows_to_dicts(h, rows), lambda d: d.get("target_customer_id"), pg,
             lambda k, d: GuarantorConnection(
                 tenant_id=t, target_customer_id=k,
                 **{f: (d.get(f) or None) for f in _GUARANTOR_FIELDS}),
             lambda k, d: k, write=write, session=session)
    if write:
        session.commit()
    stats.append(s)

    return stats


def render(stats: list[Stat], write: bool, sample: int) -> None:
    _say("\n[PLAN] rows missing from PG (insert-only; existing rows never touched)")
    _say(f"  {'domain':28s} {'sheet':>6s} {'pg':>6s} {'missing':>8s} {'inserted':>9s} {'id없음':>7s}")
    _say(f"  {'-'*28} {'-'*6} {'-'*6} {'-'*8} {'-'*9} {'-'*7}")
    tot_missing = tot_ins = 0
    for s in stats:
        tot_missing += len(s.missing_ids)
        tot_ins += s.inserted
        _say(f"  {s.domain:28s} {s.sheet:6d} {s.pg:6d} "
             f"{len(s.missing_ids):8d} {s.inserted:9d} {s.no_key:7d}")
    _say(f"  {'-'*28}")
    verb = "INSERTED" if write else "WOULD INSERT"
    _say(f"  TOTAL missing={tot_missing}  {verb}={tot_ins if write else tot_missing}")

    _say("\n[MISSING KEYS]")
    for s in stats:
        if not s.missing_ids and not s.exceptions:
            continue
        _say(f"  ● {s.domain}: missing {len(s.missing_ids)}")
        for k in s.missing_ids[:sample]:
            _say(f"      - {k}")
        if len(s.missing_ids) > sample:
            _say(f"      … (+{len(s.missing_ids) - sample} more)")
        for ex in s.exceptions:
            _say(f"      ⚠ exception: {ex}")


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser(description="Insert-only apply of missing latest-sheet rows → PG (hanwoory)")
    ap.add_argument("--tenant", default=SCOPE_TENANT)
    ap.add_argument("--input-dir", default=str(ROOT / "migration_input_latest_20260604"))
    ap.add_argument("--dry-run", action="store_true", help="explicit dry-run (default behavior)")
    ap.add_argument("--apply", action="store_true", help="perform inserts (requires gate flags)")
    ap.add_argument("--allow-remote-render-pg", action="store_true")
    ap.add_argument("--confirm", default="")
    ap.add_argument("--sample", type=int, default=50)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.tenant != SCOPE_TENANT:
        _say(f"[ABORT] scope is '{SCOPE_TENANT}' only — got --tenant={args.tenant!r}. "
             f"jpup and other tenants are intentionally out of scope.")
        return 6

    write = bool(args.apply) and not args.dry_run

    input_dir = Path(args.input_dir).resolve()
    wb_path = input_dir / CUSTOMERS_FILE
    _say(f"[INPUT]   {wb_path}  exists={wb_path.exists()}")
    if not wb_path.exists():
        _say("[FATAL]   hanwoory customer workbook not found")
        return 4

    from backend.db.session import is_configured
    if not is_configured():
        _say("[FATAL]   DATABASE_URL is not set — nothing to compare/apply.")
        return 3

    url = os.environ.get("DATABASE_URL", "")
    host = database_host(url)
    remote = host not in LOCAL_HOSTS
    kind = "Render-style" if looks_render_host(host) else ("non-local" if remote else "LOCAL loopback")
    _say(f"[DB]      host={mask_host(host)}  ({kind})")

    # ── write gate ──
    if write:
        if args.confirm != APPLY_CONFIRM_STRING:
            _say('[ABORT]   --apply requires --confirm "%s" (exact).' % APPLY_CONFIRM_STRING)
            return 5
        if remote and not args.allow_remote_render_pg:
            _say(f"[ABORT]   host {mask_host(host)} is non-local — --apply also requires "
                 f"--allow-remote-render-pg.")
            return 5
        _say("[MODE]    APPLY — insert-only of missing rows (no update/delete/reset).")
    else:
        _say("[MODE]    DRY-RUN — reads PG to recompute missing set; writes nothing.")

    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    wb = _open_xlsx(wb_path)
    try:
        with SessionLocal() as session:
            stats = run(session, wb, write=write)
            if not write:
                session.rollback()  # belt-and-suspenders: never persist in dry-run
    finally:
        wb.close()

    render(stats, write, args.sample)
    if not write:
        _say("\n[NEXT]    To apply, re-run with: --apply --allow-remote-render-pg "
             f'--confirm "{APPLY_CONFIRM_STRING}"')
        _say("          FEATURE_PG_* flags are NOT changed by this script.")

    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(_REPORT), encoding="utf-8")
        _say(f"\n[OUT]     report written → {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
