"""Read-only report: PG rows that are NOT in the latest exported xlsx.

Reverse of ``diff_latest_xlsx_vs_pg.py``. After the cutover apply, PG has a
few more rows than the snapshot in some domains. This tool lists those **PG-only**
rows so they can be classified as: prior-import fallback rows, app-generated
rows, duplicates, or genuine rows worth keeping.

STRICTLY READ-ONLY
------------------
* SELECT only. Never add / update / delete / commit. Session is rolled back.
* No ``--apply``; no write path exists. DB is never modified.
* Scope: hanwoory, domains 진행업무(active) / 완료업무(completed) / 일정(events).
* Logs ids/date/name/work/event_text only — no DATABASE_URL, no secrets.

Classification heuristics (per PG-only row)
-------------------------------------------
* ``det-…`` id   → prior-import fallback (sheet row had no explicit id at import).
* ``daily-…`` id → auto-created from 일일결산 dedup (app logic; sheet never had it).
* otherwise      → explicit id (app-created, or removed from the latest sheet).
* ``content_in_sheet`` (date|name|work|category, or date|text for events): if the
  same content still exists in the latest sheet, the PG-only row is most likely a
  re-keyed duplicate of a current sheet row; if not, it was either added in-app
  after the snapshot or deleted from the sheet — review before any cleanup.

CLI
---
    # DATABASE_URL must point at the PG to inspect (read-only Render URL is fine)
    .venv\\Scripts\\python.exe -X utf8 backend\\scripts\\pg_only_rows_after_cutover.py
    .venv\\Scripts\\python.exe -X utf8 backend\\scripts\\pg_only_rows_after_cutover.py --out analysis\\pg_only_rows_after_cutover.md
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from backend.scripts.import_excel_snapshot_to_pg_local import (  # noqa: E402
    _open_xlsx, _read_tab, _rows_to_dicts,
)
from backend.db.local_guard import (  # noqa: E402
    LOCAL_HOSTS, database_host, mask_host, looks_render_host,
)

SCOPE_TENANT = "hanwoory"
CUSTOMERS_FILE = "신 고객 데이터.xlsx"

_REPORT: list[str] = []


def _utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass


def _w(line: str = "") -> None:
    print(line, flush=True)
    _REPORT.append(line)


def _norm(v: Any) -> str:
    return str(v or "").strip()


def _sig(*parts: Any) -> str:
    return "|".join(_norm(p) for p in parts)


def _classify(task_id: str) -> str:
    if task_id.startswith("det-"):
        return "import-fallback(det)"
    if task_id.startswith("daily-"):
        return "daily-auto"
    return "explicit-id"


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    def esc(x: str) -> str:
        return _norm(x).replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(esc(c) for c in r) + " |")
    return out


def report_tasks(session, wb, *, tab: str, model, has_source_daily: bool, title: str) -> None:
    from sqlalchemy import select
    h, rows = _read_tab(wb, tab)
    sheet_dicts = _rows_to_dicts(h, rows)
    sheet_ids = {_norm(d.get("id")) for d in sheet_dicts if _norm(d.get("id"))}
    sheet_sigs = {_sig(d.get("date"), d.get("name"), d.get("work"), d.get("category"))
                  for d in sheet_dicts}

    pg_rows = session.scalars(select(model).where(model.tenant_id == SCOPE_TENANT)).all()
    pg_only = [r for r in pg_rows if _norm(r.task_id) not in sheet_ids]

    _w(f"\n## {title}")
    _w(f"- sheet rows (explicit id): {len(sheet_ids)}  ·  PG rows: {len(pg_rows)}  ·  "
       f"**PG-only: {len(pg_only)}**")
    if not pg_only:
        _w("- (PG-only 없음)")
        return

    cls_counts: dict[str, int] = {}
    in_sheet_yes = 0
    table_rows: list[list[str]] = []
    for r in sorted(pg_only, key=lambda x: (_classify(_norm(x.task_id)), _norm(x.date))):
        tid = _norm(r.task_id)
        cls = _classify(tid)
        cls_counts[cls] = cls_counts.get(cls, 0) + 1
        sig = _sig(r.date, r.name, r.work, r.category)
        content_in_sheet = "yes" if sig in sheet_sigs else "no"
        if content_in_sheet == "yes":
            in_sheet_yes += 1
        cols = [tid, _norm(r.date), _norm(r.name), _norm(r.work), _norm(r.category)]
        if has_source_daily:
            cols.append(_norm(getattr(r, "source_daily_id", "")))
        cols += [cls, content_in_sheet]
        table_rows.append(cols)

    summary = "  ·  ".join(f"{k}={v}" for k, v in sorted(cls_counts.items()))
    _w(f"- 분류: {summary}  ·  content_in_sheet=yes: {in_sheet_yes}/{len(pg_only)}")
    headers = ["id", "date", "name", "work", "category"]
    if has_source_daily:
        headers.append("source_daily_id")
    headers += ["분류", "content_in_sheet"]
    _w("")
    for line in _md_table(headers, table_rows):
        _w(line)


def report_events(session, wb) -> None:
    from backend.db.models.event import Event
    from sqlalchemy import select
    h, rows = _read_tab(wb, "일정")
    sheet_dicts = _rows_to_dicts(h, rows)
    sheet_set = {_sig(d.get("date_str"), d.get("event_text")) for d in sheet_dicts}
    sheet_dates = {_norm(d.get("date_str")) for d in sheet_dicts}

    pg_rows = session.execute(
        select(Event.date_str, Event.event_text, Event.sort_order)
        .where(Event.tenant_id == SCOPE_TENANT)).all()
    pg_only = [(ds, et, so) for ds, et, so in pg_rows
               if _sig(ds, et) not in sheet_set]

    _w("\n## 일정[hanwoory] (events)")
    _w(f"- sheet rows: {len(sheet_dicts)}  ·  PG rows: {len(pg_rows)}  ·  "
       f"**PG-only: {len(pg_only)}**")
    if not pg_only:
        _w("- (PG-only 없음)")
        return

    table_rows: list[list[str]] = []
    for ds, et, so in sorted(pg_only, key=lambda x: _norm(x[0])):
        same_date = "yes" if _norm(ds) in sheet_dates else "no"
        table_rows.append([_norm(ds), _norm(et), str(so), same_date])
    _w("- (events는 자연키가 없어 (날짜+내용)으로 비교. same_date_in_sheet=같은 날짜의 다른 일정이 시트에 있는지)")
    _w("")
    for line in _md_table(["date_str", "event_text", "sort_order", "same_date_in_sheet"], table_rows):
        _w(line)


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser(description="Read-only report of PG-only rows (active/completed/events)")
    ap.add_argument("--input-dir", default=str(ROOT / "migration_input_latest_20260604"))
    ap.add_argument("--out", default="analysis/pg_only_rows_after_cutover.md")
    args = ap.parse_args()

    wb_path = Path(args.input_dir).resolve() / CUSTOMERS_FILE
    _w("# PG-only rows after cutover (read-only)")
    _w(f"- input: `{wb_path.name}`  exists={wb_path.exists()}")
    if not wb_path.exists():
        _w("[FATAL] hanwoory customer workbook not found")
        return 4

    from backend.db.session import is_configured
    if not is_configured():
        _w("[FATAL] DATABASE_URL is not set — nothing to inspect.")
        return 3

    host = database_host(os.environ.get("DATABASE_URL", ""))
    remote = host not in LOCAL_HOSTS
    kind = "Render-style" if looks_render_host(host) else ("non-local" if remote else "LOCAL loopback")
    _w(f"- DB host: `{mask_host(host)}` ({kind})")
    _w("- mode: **READ-ONLY** (SELECT only — no writes)")

    from backend.db.session import get_sessionmaker
    from backend.db.models.task import ActiveTask, CompletedTask
    SessionLocal = get_sessionmaker()
    wb = _open_xlsx(wb_path)
    try:
        with SessionLocal() as session:
            report_tasks(session, wb, tab="진행업무", model=ActiveTask,
                         has_source_daily=True, title="진행업무[hanwoory] (active)")
            report_tasks(session, wb, tab="완료업무", model=CompletedTask,
                         has_source_daily=False, title="완료업무[hanwoory] (completed)")
            report_events(session, wb)
            session.rollback()  # belt-and-suspenders: never persist
    finally:
        wb.close()

    _w("\n## 판단 가이드")
    _w("- **import-fallback(det) + content_in_sheet=yes** → 최초 import 때 id 없던 시트행의 보정행. "
       "현재 시트에도 동일 내용 존재 → 보존 OK(중복 아님, 단지 키가 det-).")
    _w("- **import-fallback(det) + content_in_sheet=no** → 과거 시트엔 있었으나 최신 시트에서 빠진 내용 → "
       "삭제된 것인지 검토 필요.")
    _w("- **daily-auto** → 일일결산→진행업무 자동생성행(앱 로직). 시트엔 원래 없음 → 보존 권장.")
    _w("- **explicit-id + content_in_sheet=no** → 앱에서 직접 추가됐거나 시트에서 삭제된 실데이터 → 보존 가능성 높음.")
    _w("- **explicit-id + content_in_sheet=yes** → 동일 내용이 시트에 다른 id로도 존재 가능 → 중복 후보(검토).")
    _w("- events PG-only → 앱에서 추가됐거나 시트에서 삭제된 일정. same_date_in_sheet 로 중복/추가 여부 가늠.")
    _w("\n*이 보고서는 read-only 입니다. 어떤 행도 삭제/수정하지 않았습니다.*")

    if args.out:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(_REPORT), encoding="utf-8")
        print(f"\n[OUT] report written → {out_path}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
