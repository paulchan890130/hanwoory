"""Read-only diff: latest exported xlsx snapshot vs PostgreSQL.

Computes rows that are present in the latest xlsx workbooks but **missing
from PostgreSQL**. This is a *reporting* tool only.

Safety contract
---------------
* **STRICTLY READ-ONLY.** Issues ``SELECT`` queries exclusively. It never
  calls ``session.add`` / ``commit`` / ``execute(DELETE/UPDATE/INSERT)``.
* No ``--execute`` flag exists and there is no apply path. To actually
  import the missing rows you would run the existing importer separately
  (not done here).
* Reuses the importer's parsers/mappers (``import_excel_snapshot_to_pg_local``)
  so the keys compared here match exactly what an import would use.
* Reads ``--input-dir`` (default: the latest snapshot folder). It never
  writes to any input folder.

Target database
---------------
Diff runs against whatever ``DATABASE_URL`` points to. The script prints the
masked host so you can confirm local-vs-remote before trusting the output.
If ``DATABASE_URL`` is unset it refuses to run (no DB to compare against).

CLI
---
    # set DATABASE_URL first (local PG, or a read-only Render URL)
    python backend/scripts/diff_latest_xlsx_vs_pg.py
    python backend/scripts/diff_latest_xlsx_vs_pg.py --only hanwoory
    python backend/scripts/diff_latest_xlsx_vs_pg.py --only jpup --sample 30
    python backend/scripts/diff_latest_xlsx_vs_pg.py --out analysis/xlsx_vs_pg_diff_20260604.md
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

# Reuse the importer's parsing so keys match exactly. Importing the module is
# side-effect free w.r.t. the DB (its main() runs only under __main__).
from backend.scripts.import_excel_snapshot_to_pg_local import (  # noqa: E402
    _open_xlsx, _read_tab, _rows_to_dicts,
)

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


def _mask_db_url(url: str) -> str:
    """Hide credentials; keep host/db so target is identifiable."""
    out = url
    if "://" in out and "@" in out:
        scheme, rest = out.split("://", 1)
        out = scheme + "://***@" + rest.split("@", 1)[1]
    return out


# Latest-folder workbook layout (jpup files live at the folder root here,
# not under tenants/). 기준 * are templates → not tenant data, excluded.
LATEST_LAYOUT = [
    ("hanwoory_customers", "신 고객 데이터.xlsx", "hanwoory"),
    ("hanwoory_work",      "신 업무정리.xlsx",   "hanwoory"),
    ("jpup_customers",     "고객 데이터 - jpup.xlsx", "jpup"),
    ("jpup_work",          "업무정리 - jpup.xlsx",   "jpup"),
]

_CERT_TABS = [
    ("각종공인증_업체",     "CertVendor"),
    ("각종공인증_대분류",   "CertDirection"),
    ("각종공인증_중분류",   "CertGroup"),
    ("각종공인증_소분류지역", "CertRegion"),
    ("각종공인증_가격조건", "CertPrice"),
]


def _norm(v: Any) -> str:
    return str(v or "").strip()


# ── Generic keyed-domain diff ───────────────────────────────────────────────


class DiffResult:
    def __init__(self, domain: str):
        self.domain = domain
        self.sheet_total = 0       # rows in sheet (after dedup of empty keys)
        self.no_key = 0            # sheet rows lacking a natural key (not diffable by key)
        self.pg_total = 0          # rows in PG for this scope
        self.missing: list[dict] = []   # sheet rows whose key is absent in PG
        self.note: str = ""


def diff_keyed(
    domain: str,
    sheet_dicts: list[dict],
    key_fn: Callable[[dict], str],
    pg_keys: set[str],
    sample_fields: list[str],
    pg_total: int,
) -> DiffResult:
    r = DiffResult(domain)
    r.pg_total = pg_total
    seen: set[str] = set()
    for d in sheet_dicts:
        k = _norm(key_fn(d))
        if not k:
            r.no_key += 1
            continue
        if k in seen:
            continue
        seen.add(k)
        r.sheet_total += 1
        if k not in pg_keys:
            r.missing.append({"_key": k, **{f: _norm(d.get(f)) for f in sample_fields}})
    return r


# ── PG read-only key fetchers (SELECT only) ─────────────────────────────────


def pg_customer_keys(session, tenant: str) -> tuple[set[str], set[str], int]:
    from backend.db.models.customer import Customer
    from sqlalchemy import select
    live = set(session.scalars(select(Customer.customer_id).where(
        Customer.tenant_id == tenant, Customer.deleted_at.is_(None))).all())
    deleted = set(session.scalars(select(Customer.customer_id).where(
        Customer.tenant_id == tenant, Customer.deleted_at.is_not(None))).all())
    return {_norm(x) for x in live}, {_norm(x) for x in deleted}, len(live)


def pg_simple_keys(session, model_col, where) -> tuple[set[str], int]:
    from sqlalchemy import select
    vals = session.scalars(select(model_col).where(where)).all()
    s = {_norm(v) for v in vals}
    return s, len(vals)


# ── Per-file diff drivers ───────────────────────────────────────────────────


def diff_customers_workbook(session, wb, tenant: str, sample: int) -> list[DiffResult]:
    from backend.db.models.customer import Customer
    from backend.db.models.task import PlannedTask, ActiveTask, CompletedTask
    from backend.db.models.daily import DailyEntry
    from backend.db.models.event import Event
    from backend.db.models.relationship import AccommodationProvider, GuarantorConnection
    from sqlalchemy import select

    results: list[DiffResult] = []

    # customers (key 고객ID)
    h, rows = _read_tab(wb, "고객 데이터")
    live, deleted, pg_n = pg_customer_keys(session, tenant)
    r = diff_keyed(f"customers[{tenant}]", _rows_to_dicts(h, rows),
                   lambda d: d.get("고객ID"), live,
                   ["고객ID", "한글", "성", "명", "여권", "등록증"], pg_n)
    soft = sum(1 for m in r.missing if m["_key"] in deleted)
    if soft:
        r.note = f"이 중 {soft}건은 PG에 soft-deleted 로 존재(고객ID 재사용 주의)."
    results.append(r)

    # tasks (key = explicit id only; det-id rows counted as no_key/non-diffable)
    for tab, model, key in [
        ("예정업무", PlannedTask, PlannedTask.task_id),
        ("진행업무", ActiveTask, ActiveTask.task_id),
        ("완료업무", CompletedTask, CompletedTask.task_id),
    ]:
        h, rows = _read_tab(wb, tab)
        pk, pn = pg_simple_keys(session, key, model.tenant_id == tenant)
        r = diff_keyed(f"{tab}[{tenant}]", _rows_to_dicts(h, rows),
                       lambda d: d.get("id"), pk,
                       ["id", "date", "name", "work", "category"], pn)
        r.note = ("id 없는 행은 importer가 내용기반 det-id를 부여 → 키 비교 불가(아래 'id없음'은 별도 import 필요)."
                  if r.no_key else r.note)
        results.append(r)

    # daily (key = explicit id)
    h, rows = _read_tab(wb, "일일결산")
    pk, pn = pg_simple_keys(session, DailyEntry.entry_id, DailyEntry.tenant_id == tenant)
    r = diff_keyed(f"일일결산[{tenant}]", _rows_to_dicts(h, rows),
                   lambda d: d.get("id"), pk,
                   ["id", "date", "name", "task"], pn)
    results.append(r)

    # events (no natural key → compare (date_str, event_text))
    h, rows = _read_tab(wb, "일정")
    ev = session.execute(select(Event.date_str, Event.event_text).where(
        Event.tenant_id == tenant)).all()
    pg_ev = {f"{_norm(a)}|{_norm(b)}" for a, b in ev}
    r = diff_keyed(f"일정[{tenant}]", _rows_to_dicts(h, rows),
                   lambda d: f"{_norm(d.get('date_str'))}|{_norm(d.get('event_text'))}",
                   pg_ev, ["date_str", "event_text"], len(ev))
    r.note = "일정은 자연키가 없어 (날짜+내용)으로 비교."
    results.append(r)

    # relationships (key = target_customer_id)
    for tab, model in [("숙소제공자연결", AccommodationProvider),
                       ("신원보증인연결", GuarantorConnection)]:
        h, rows = _read_tab(wb, tab)
        pk, pn = pg_simple_keys(session, model.target_customer_id, model.tenant_id == tenant)
        r = diff_keyed(f"{tab}[{tenant}]", _rows_to_dicts(h, rows),
                       lambda d: d.get("target_customer_id"), pk,
                       ["target_customer_id"], pn)
        results.append(r)

    return results


def diff_work_workbook(session, wb, tenant: str, sample: int) -> list[DiffResult]:
    from backend.db.models import certification as cert
    from backend.db.models.work_data import WorkReferenceSheet, WorkReferenceRow
    from sqlalchemy import select, func
    from sqlalchemy import and_  # noqa: F401  (kept for clarity of intent)

    results: list[DiffResult] = []
    cert_tab_set = {t for t, _ in _CERT_TABS}

    # certification (key = explicit id per tab; det-id rows non-diffable)
    for tab, model_name in _CERT_TABS:
        model = getattr(cert, model_name)
        h, rows = _read_tab(wb, tab)
        pk, pn = pg_simple_keys(session, model.id, model.tenant_id == tenant)
        r = diff_keyed(f"{tab}[{tenant}]", _rows_to_dicts(h, rows),
                       lambda d: d.get("id"), pk,
                       ["id", "name", "group_name", "direction", "region", "condition"], pn)
        results.append(r)

    # work_reference (wipe-replace per sheet → coarse: sheet presence + row count delta)
    r = DiffResult(f"업무참고시트[{tenant}]")
    pg_sheet_names = session.scalars(select(WorkReferenceSheet.sheet_name).where(
        WorkReferenceSheet.tenant_id == tenant)).all()
    pg_sheet_counts: dict[str, int] = {}
    for n in pg_sheet_names:
        c = session.scalar(select(func.count()).select_from(WorkReferenceRow).where(
            WorkReferenceRow.tenant_id == tenant, WorkReferenceRow.sheet_name == n)) or 0
        pg_sheet_counts[_norm(n)] = int(c)
    r.pg_total = len(pg_sheet_counts)
    for sheet_name in wb.sheetnames:
        if sheet_name in cert_tab_set:
            continue
        h, rows = _read_tab(wb, sheet_name)
        if not h:
            continue
        r.sheet_total += 1
        pg_c = pg_sheet_counts.get(_norm(sheet_name))
        if pg_c is None:
            r.missing.append({"_key": sheet_name, "sheet": sheet_name,
                              "sheet_rows": str(len(rows)), "pg_rows": "(시트 없음)"})
        elif pg_c != len(rows):
            r.missing.append({"_key": sheet_name, "sheet": sheet_name,
                              "sheet_rows": str(len(rows)), "pg_rows": str(pg_c)})
    r.note = "업무참고/기타업무참고는 시트 단위 wipe-replace → 시트 부재 또는 행수 불일치만 표시(행단위 키 비교 아님)."
    results.append(r)

    return results


# ── Report rendering ────────────────────────────────────────────────────────


def render(results: list[DiffResult], sample: int) -> None:
    _say("\n[DIFF SUMMARY] (sheet rows missing from PG)")
    _say(f"  {'domain':32s} {'sheet':>7s} {'pg':>7s} {'missing':>8s} {'id없음':>7s}")
    _say(f"  {'-'*32} {'-'*7} {'-'*7} {'-'*8} {'-'*7}")
    grand_missing = 0
    for r in results:
        grand_missing += len(r.missing)
        _say(f"  {r.domain:32s} {r.sheet_total:7d} {r.pg_total:7d} "
             f"{len(r.missing):8d} {r.no_key:7d}")
    _say(f"  {'-'*32}")
    _say(f"  TOTAL missing rows (keyed domains): {grand_missing}")

    _say("\n[MISSING ROW SAMPLES]")
    for r in results:
        if not r.missing:
            continue
        _say(f"\n  ● {r.domain} — missing {len(r.missing)}건"
             + (f"  · {r.note}" if r.note else ""))
        for m in r.missing[:sample]:
            kv = "  ".join(f"{k}={v}" for k, v in m.items() if k != "_key" and v)
            _say(f"      - {m['_key']}: {kv}")
        if len(r.missing) > sample:
            _say(f"      … (+{len(r.missing) - sample}건 더, --sample 로 확대)")

    notes = [r.note for r in results if r.note and not r.missing]
    if notes:
        _say("\n[NOTES]")
        for n in dict.fromkeys(notes):
            _say(f"  - {n}")


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser(description="Read-only diff: latest xlsx snapshot vs PostgreSQL")
    ap.add_argument("--input-dir", default=str(ROOT / "migration_input_latest_20260604"))
    ap.add_argument("--only", choices=["hanwoory", "jpup", "all"], default="all")
    ap.add_argument("--sample", type=int, default=20, help="missing-row samples per domain")
    ap.add_argument("--out", default="", help="optional path to also write the report")
    args = ap.parse_args()

    input_dir = Path(args.input_dir).resolve()
    _say(f"[INPUT]   {input_dir}  exists={input_dir.exists()}")
    if not input_dir.exists():
        _say("[FATAL]   input dir not found")
        return 4

    from backend.db.session import is_configured
    if not is_configured():
        _say("[FATAL]   DATABASE_URL is not set — no PostgreSQL to diff against.")
        _say("          Set DATABASE_URL (local PG, or a READ-ONLY Render URL) and re-run.")
        return 3
    _say(f"[DB]      target = {_mask_db_url(os.environ.get('DATABASE_URL', ''))}")
    _say("[MODE]    READ-ONLY (SELECT only — no writes, no apply)")

    layout = [x for x in LATEST_LAYOUT
              if args.only == "all" or x[2] == args.only]
    present = [(role, input_dir / rel, tenant) for role, rel, tenant in layout
               if (input_dir / rel).exists()]
    missing_files = [rel for role, rel, tenant in layout if not (input_dir / rel).exists()]
    _say("[FILES]")
    for role, p, tenant in present:
        _say(f"  {role:20s} tenant={tenant:10s} {p.name}")
    for rel in missing_files:
        _say(f"  (missing) {rel}")

    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    all_results: list[DiffResult] = []
    # NOTE: read-only session — we never add/commit. Rolled back at close.
    with SessionLocal() as session:
        for role, p, tenant in present:
            wb = _open_xlsx(p)
            try:
                if role.endswith("_customers"):
                    all_results += diff_customers_workbook(session, wb, tenant, args.sample)
                elif role.endswith("_work"):
                    all_results += diff_work_workbook(session, wb, tenant, args.sample)
            finally:
                wb.close()
        session.rollback()  # ensure nothing is ever persisted

    render(all_results, args.sample)

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
