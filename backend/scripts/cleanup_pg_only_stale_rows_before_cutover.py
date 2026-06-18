"""Surgical cleanup of PG-only stale rows before enabling FEATURE_PG_* (hanwoory).

Removes ONLY an explicit allow-list of rows confirmed stale in the PG-only
report. It cannot delete anything else — the SQL is scoped to
``tenant_id='hanwoory'`` AND an exact id / (date_str, event_text) allow-list.

Hard safety contract
--------------------
* **Allow-list only.** Active: exactly the 8 task_ids below. Events: exactly the
  2 (date_str, event_text) pairs below. No pattern/range/broad delete anywhere.
* **No** table clear / truncate / reset. Touches only ``active_tasks`` (and
  ``events`` when explicitly opted in). Never touches completed_tasks,
  customers, daily_*, work_ref, certification, accounts, or tenants.
* **Dry-run by default.** Deleting active rows requires ALL of:
    --apply  --allow-remote-render-pg  --confirm "I-UNDERSTAND-CLEANUP-PG-ONLY-STALE-ROWS"
* **Events are preview-only by default.** Per the cutover decision they must be
  dry-run-confirmed first, so deleting them requires an ADDITIONAL ``--apply-events``
  flag on top of the apply gate. A plain ``--apply`` never deletes events.
* Always prints the exact rows that would be / were removed, and writes a full
  archive (all columns) to ``analysis/`` BEFORE any delete (restore reference).
* Never prints DATABASE_URL or secrets (host is masked).

CLI
---
    # dry-run (default) — prints + archives candidates, deletes nothing
    .venv\\Scripts\\python.exe -X utf8 backend\\scripts\\cleanup_pg_only_stale_rows_before_cutover.py --dry-run

    # apply: delete the 8 active rows only (events stay preview-only)
    .venv\\Scripts\\python.exe -X utf8 backend\\scripts\\cleanup_pg_only_stale_rows_before_cutover.py \\
        --apply --allow-remote-render-pg --confirm "I-UNDERSTAND-CLEANUP-PG-ONLY-STALE-ROWS"

    # later, to also delete the 2 events (extra explicit opt-in):
    #   ... --apply --apply-events --allow-remote-render-pg --confirm "I-UNDERSTAND-CLEANUP-PG-ONLY-STALE-ROWS"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
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

from backend.db.local_guard import (  # noqa: E402
    LOCAL_HOSTS, database_host, mask_host, looks_render_host,
)

CONFIRM_STRING = "I-UNDERSTAND-CLEANUP-PG-ONLY-STALE-ROWS"
TENANT = "hanwoory"

# Exactly the 8 stale active task_ids confirmed in the PG-only report.
ACTIVE_STALE_IDS: list[str] = [
    "daily-004c80cc-220f-4343-a20e-fbfb1bd7d862",
    "daily-b735aff1-1028-45fd-9770-d964ed197f99",
    "daily-9324890b-bbfb-4f22-a668-bed407989fae",
    "1e14c773-b513-4285-af80-c5542e928f29",
    "bda85d89-516f-43fc-809a-e324200cf06c",
    "a807cec3-cdea-4f2f-8b7e-aec165c5516e",
    "471a192a-42c1-4fa3-b25e-fd9eaaf5cc90",
    "e8f39544-39f1-4fc0-93c6-ff6e47a03650",
]

# Exactly the 2 stale event rows — dry-run only unless --apply-events is given.
EVENT_STALE: list[tuple[str, str]] = [
    ("2026-06-05 00:00:00", "0936 윤찬 이향재 윤주아"),
    ("2026-06-05 00:00:00", "0948 윤혁"),
]

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


def _row_dict(obj) -> dict:
    """Serialize all columns of an ORM row (datetimes → str)."""
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name, None)
        out[col.name] = None if v is None else (v if isinstance(v, (int, float, str)) else str(v))
    return out


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser(description="Surgical cleanup of PG-only stale rows (hanwoory)")
    ap.add_argument("--dry-run", action="store_true", help="explicit dry-run (default behavior)")
    ap.add_argument("--apply", action="store_true", help="delete the 8 stale active rows (gated)")
    ap.add_argument("--apply-events", action="store_true",
                    help="ALSO delete the 2 stale events (requires --apply too)")
    ap.add_argument("--allow-remote-render-pg", action="store_true")
    ap.add_argument("--confirm", default="")
    ap.add_argument("--out", default="analysis/cleanup_pg_only_stale_rows_report.md")
    ap.add_argument("--backup", default="analysis/cleanup_pg_only_stale_backup.json")
    args = ap.parse_args()

    _w("# Cleanup PG-only stale rows before cutover (hanwoory)")
    _w(f"- generated: {datetime.now().isoformat(timespec='seconds')}")

    write_active = bool(args.apply) and not args.dry_run
    write_events = write_active and bool(args.apply_events)

    from backend.db.session import is_configured
    if not is_configured():
        _w("[FATAL] DATABASE_URL is not set — nothing to inspect/clean.")
        return 3

    host = database_host(os.environ.get("DATABASE_URL", ""))
    remote = host not in LOCAL_HOSTS
    kind = "Render-style" if looks_render_host(host) else ("non-local" if remote else "LOCAL loopback")
    _w(f"- DB host: `{mask_host(host)}` ({kind})")

    # ── write gate ──
    if write_active:
        if args.confirm != CONFIRM_STRING:
            _w(f'[ABORT] --apply requires --confirm "{CONFIRM_STRING}" (exact).')
            return 5
        if remote and not args.allow_remote_render_pg:
            _w(f"[ABORT] host {mask_host(host)} is non-local — --apply also requires "
               f"--allow-remote-render-pg.")
            return 5
        _w("- mode: **APPLY** — delete 8 active rows"
           + ("; **also delete 2 events** (--apply-events)" if write_events
              else "; events = PREVIEW-only (no --apply-events)"))
    else:
        _w("- mode: **DRY-RUN** — prints + archives candidates, deletes nothing")

    from backend.db.session import get_sessionmaker
    from backend.db.models.task import ActiveTask
    from backend.db.models.event import Event
    from sqlalchemy import select

    archive: dict[str, list[dict]] = {"active_tasks": [], "events": []}
    deleted_active = deleted_events = 0

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # ── ACTIVE: exact id allow-list, exact tenant ──
        rows = session.scalars(select(ActiveTask).where(
            ActiveTask.tenant_id == TENANT,
            ActiveTask.task_id.in_(ACTIVE_STALE_IDS),
        )).all()
        found_ids = {_norm(r.task_id) for r in rows}
        missing_ids = [i for i in ACTIVE_STALE_IDS if i not in found_ids]

        _w("\n## 진행업무[hanwoory] — 삭제 대상 (정확히 이 8개 ID만)")
        _w(f"- allow-list: {len(ACTIVE_STALE_IDS)}  ·  PG에서 발견: {len(rows)}  ·  미발견: {len(missing_ids)}")
        _w("")
        _w("| task_id | date | name | work | category | source_daily_id |")
        _w("| --- | --- | --- | --- | --- | --- |")
        for r in rows:
            archive["active_tasks"].append(_row_dict(r))
            _w(f"| {_norm(r.task_id)} | {_norm(r.date)} | {_norm(r.name)} | "
               f"{_norm(r.work)} | {_norm(r.category)} | {_norm(r.source_daily_id)} |")
        if missing_ids:
            _w("\n- ⚠ 이미 없거나 매칭 안 된 ID (정상일 수 있음 — 이전 실행/수동삭제):")
            for i in missing_ids:
                _w(f"  - {i}")

        # defensive: never delete anything outside the allow-list
        safe_rows = [r for r in rows
                     if _norm(r.task_id) in set(ACTIVE_STALE_IDS) and r.tenant_id == TENANT]
        assert len(safe_rows) == len(rows), "allow-list guard mismatch (aborting)"

        if write_active:
            for r in safe_rows:
                session.delete(r)
            session.commit()
            deleted_active = len(safe_rows)
            _w(f"\n- ✅ APPLIED: 진행업무 {deleted_active}건 삭제 완료.")
        else:
            _w(f"\n- DRY-RUN: 진행업무 {len(safe_rows)}건 삭제 예정 (실삭제 안 함).")

        # ── EVENTS: exact (date_str, event_text) allow-list ──
        ev_pairs = set(EVENT_STALE)
        ev_rows = session.scalars(select(Event).where(Event.tenant_id == TENANT)).all()
        ev_match = [e for e in ev_rows if (_norm(e.date_str), _norm(e.event_text)) in ev_pairs]
        matched_pairs = {(_norm(e.date_str), _norm(e.event_text)) for e in ev_match}
        missing_pairs = [p for p in EVENT_STALE if p not in matched_pairs]

        _w("\n## 일정[hanwoory] — 후보 (기본 PREVIEW only)")
        _w(f"- allow-list: {len(EVENT_STALE)}  ·  PG에서 발견: {len(ev_match)}  ·  미발견: {len(missing_pairs)}")
        _w("")
        _w("| date_str | event_text | sort_order |")
        _w("| --- | --- | --- |")
        for e in ev_match:
            archive["events"].append(_row_dict(e))
            _w(f"| {_norm(e.date_str)} | {_norm(e.event_text)} | {e.sort_order} |")
        if missing_pairs:
            _w("\n- ⚠ 매칭 안 된 후보 (내용/날짜 문자열 불일치 가능 — 삭제 안 됨):")
            for ds, et in missing_pairs:
                _w(f"  - {ds} | {et}")

        safe_ev = [e for e in ev_match
                   if (_norm(e.date_str), _norm(e.event_text)) in ev_pairs and e.tenant_id == TENANT]
        assert len(safe_ev) == len(ev_match), "event allow-list guard mismatch (aborting)"

        if write_events:
            for e in safe_ev:
                session.delete(e)
            session.commit()
            deleted_events = len(safe_ev)
            _w(f"\n- ✅ APPLIED: 일정 {deleted_events}건 삭제 완료 (--apply-events).")
        else:
            reason = "preview-only (--apply-events 미지정)" if write_active else "dry-run"
            _w(f"\n- {reason.upper()}: 일정 {len(safe_ev)}건은 삭제하지 않음. "
               f"실삭제하려면 --apply 와 함께 --apply-events 추가 필요.")

        if not (write_active or write_events):
            session.rollback()  # belt-and-suspenders

    # ── archive (always written — full row contents for restore reference) ──
    backup_path = Path(args.backup)
    if not backup_path.is_absolute():
        backup_path = ROOT / backup_path
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    backup_payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "tenant_id": TENANT,
        "applied_active": bool(write_active),
        "applied_events": bool(write_events),
        "active_tasks": archive["active_tasks"],
        "events": archive["events"],
    }
    backup_path.write_text(json.dumps(backup_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _w(f"\n## archive\n- full-row backup → `{backup_path}` "
       f"(active={len(archive['active_tasks'])}, events={len(archive['events'])})")

    _w("\n## summary")
    _w(f"- active deleted: {deleted_active}  ·  events deleted: {deleted_events}")
    if not (write_active or write_events):
        _w(f'- to apply active: --apply --allow-remote-render-pg --confirm "{CONFIRM_STRING}"')
        _w("- to also apply events: add --apply-events")
    _w("- FEATURE_PG_* 는 이 스크립트가 변경하지 않습니다.")

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(_REPORT), encoding="utf-8")
    print(f"\n[OUT] report → {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
