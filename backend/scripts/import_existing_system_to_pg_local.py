"""Full local-beta importer — reads existing system Sheets (READ-ONLY) → local PG.

Safety contract
---------------
* Refuses to run unless ``DATABASE_URL`` host is loopback (localhost/127.0.0.1/::1).
* Default mode is **dry-run** — prints what would be imported and exits.
* ``--execute`` is required for actual PG writes.
* **Never writes to Google Sheets.** Only ``get_all_records()`` / ``get_all_values()``
  read calls are issued.
* **Never writes to Google Drive.**
* Every domain is wrapped in a try/except so one failure (e.g. missing tab,
  permission denied) doesn't kill the rest of the import.

CLI
---
    # Dry-run (no DB writes, no Sheets writes)
    python backend/scripts/import_existing_system_to_pg_local.py

    # Actual write
    python backend/scripts/import_existing_system_to_pg_local.py --execute

    # Only certain domains
    python backend/scripts/import_existing_system_to_pg_local.py --execute \
      --only accounts,hanwoory_customers

Domains
-------
* ``accounts``           — admin Accounts sheet → tenants + users
* ``board``              — admin 게시판 + 게시판댓글 → board_posts + board_comments
* ``marketing``          — admin 홈페이지게시물 → marketing_posts
* ``agent_signatures``   — admin 행정사서명 → agent_signatures (one per tenant)
* ``temp_signatures``    — admin 서명임시저장 → temp_signature_slots
* ``hanwoory_customers`` — hanwoory's customer workbook → customers + events + memos
                           + daily + tasks + signatures + relationships
* ``hanwoory_work``      — hanwoory's work workbook → work_reference + certification
* ``tenant_workbooks``   — every other tenant's workbooks (same content)
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except ImportError:
    pass


_REPORT: list[str] = []


def _utf8() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass


def _say(msg: str) -> None:
    print(msg, flush=True)
    _REPORT.append(msg)


# ── Sheet readers (READ-ONLY) ─────────────────────────────────────────────

def _gspread_client():
    """Return a gspread Client. Reads ``config.KEY_PATH`` service account JSON."""
    import gspread
    from google.oauth2.service_account import Credentials
    import config

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_file(config.KEY_PATH, scopes=scopes)
    return gspread.authorize(creds)


def _open_workbook(client, sheet_key: str):
    return client.open_by_key(sheet_key)


def _read_tab(workbook, tab_name: str) -> tuple[list[str], list[list[str]]]:
    """Return (headers, rows). Empty if the tab is missing or empty."""
    try:
        ws = workbook.worksheet(tab_name)
    except Exception as e:
        _say(f"        [skip] tab '{tab_name}' not found: {type(e).__name__}")
        return [], []
    values = ws.get_all_values()
    if not values:
        return [], []
    return values[0], values[1:]


def _read_records(workbook, tab_name: str) -> list[dict]:
    headers, rows = _read_tab(workbook, tab_name)
    if not headers:
        return []
    return [dict(zip(headers, row)) for row in rows]


# ── Domain importers ─────────────────────────────────────────────────────

def import_accounts(client) -> dict:
    """Admin Accounts → tenants + users."""
    import config
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from sqlalchemy import select

    wb = _open_workbook(client, config.SHEET_KEY)
    records = _read_records(wb, config.ACCOUNTS_SHEET_NAME)
    _say(f"      [accounts] read {len(records)} rows from admin Accounts")

    SessionLocal = get_sessionmaker()
    n_t = n_u = n_skip = 0
    skipped = []
    with SessionLocal() as session:
        seen_tenants = set()
        for r in records:
            login_id = str(r.get("login_id", "")).strip()
            if not login_id:
                skipped.append("(no login_id)")
                n_skip += 1
                continue
            password_hash = str(r.get("password_hash", "")).strip()
            if not password_hash:
                skipped.append(f"{login_id}: no password_hash")
                n_skip += 1
                continue
            tenant_id = str(r.get("tenant_id", "") or login_id).strip()
            office_name = str(r.get("office_name", "")).strip() or login_id
            is_active = str(r.get("is_active", "")).strip().lower() in (
                "true", "1", "y", "yes", "활성", "active",
            ) or not str(r.get("is_active", "")).strip()
            is_admin = str(r.get("is_admin", "")).strip().lower() in ("true", "1", "y", "yes")

            if tenant_id not in seen_tenants:
                seen_tenants.add(tenant_id)
                t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
                if t is None:
                    session.add(Tenant(
                        tenant_id=tenant_id, office_name=office_name,
                        office_adr=str(r.get("office_adr", "") or None),
                        biz_reg_no=str(r.get("biz_reg_no", "") or None),
                        folder_id=str(r.get("folder_id", "") or None),
                        customer_sheet_key=str(r.get("customer_sheet_key", "") or None),
                        work_sheet_key=str(r.get("work_sheet_key", "") or None),
                        is_active=is_active,
                    ))
                    n_t += 1
                else:
                    t.office_name = office_name
                    t.office_adr = str(r.get("office_adr", "") or None)
                    t.biz_reg_no = str(r.get("biz_reg_no", "") or None)
                    t.folder_id = str(r.get("folder_id", "") or None)
                    t.customer_sheet_key = str(r.get("customer_sheet_key", "") or None)
                    t.work_sheet_key = str(r.get("work_sheet_key", "") or None)
                    t.is_active = is_active
            session.flush()

            u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
            if u is None:
                session.add(AccountUser(
                    login_id=login_id, tenant_id=tenant_id,
                    password_hash=password_hash,
                    contact_name=str(r.get("contact_name", "") or None),
                    contact_tel=str(r.get("contact_tel", "") or None),
                    is_admin=is_admin, is_active=is_active,
                ))
            else:
                u.tenant_id = tenant_id
                u.password_hash = password_hash
                u.contact_name = str(r.get("contact_name", "") or None)
                u.contact_tel = str(r.get("contact_tel", "") or None)
                u.is_admin = is_admin
                u.is_active = is_active
            n_u += 1
        session.commit()

    return {
        "tenants_upserted": n_t, "users_upserted": n_u,
        "skipped": n_skip, "skip_reasons": skipped[:10],
    }


def import_board(client) -> dict:
    import config
    from backend.db.models.board import BoardComment, BoardPost
    from backend.db.session import get_sessionmaker
    from sqlalchemy import select

    wb = _open_workbook(client, config.SHEET_KEY)
    posts = _read_records(wb, "게시판")
    comments = _read_records(wb, "게시판댓글")
    _say(f"      [board] read {len(posts)} posts, {len(comments)} comments")

    SessionLocal = get_sessionmaker()
    n_p = n_c = 0
    with SessionLocal() as session:
        for r in posts:
            pid = str(r.get("id", "")).strip()
            if not pid:
                continue
            row = session.scalar(select(BoardPost).where(BoardPost.id == pid))
            payload = dict(
                tenant_id=str(r.get("tenant_id", "")) or None,
                author_login=str(r.get("author_login", "")) or None,
                office_name=str(r.get("office_name", "")) or None,
                is_notice=str(r.get("is_notice", "")) or None,
                category=str(r.get("category", "")) or None,
                title=str(r.get("title", "")) or None,
                content=str(r.get("content", "")) or None,
                created_at=str(r.get("created_at", "")) or None,
                updated_at=str(r.get("updated_at", "")) or None,
                popup_yn=str(r.get("popup_yn", "")) or None,
                link_url=str(r.get("link_url", "")) or None,
                comment_count=int(r.get("comment_count") or 0),
            )
            if row is None:
                session.add(BoardPost(id=pid, **payload))
            else:
                for k, v in payload.items():
                    setattr(row, k, v)
            n_p += 1
        for r in comments:
            cid = str(r.get("id", "")).strip()
            post_id = str(r.get("post_id", "")).strip()
            if not cid or not post_id:
                continue
            row = session.scalar(select(BoardComment).where(BoardComment.id == cid))
            payload = dict(
                post_id=post_id,
                tenant_id=str(r.get("tenant_id", "")) or None,
                author_login=str(r.get("author_login", "")) or None,
                office_name=str(r.get("office_name", "")) or None,
                content=str(r.get("content", "")) or None,
                created_at=str(r.get("created_at", "")) or None,
                updated_at=str(r.get("updated_at", "")) or None,
            )
            if row is None:
                session.add(BoardComment(id=cid, **payload))
            else:
                for k, v in payload.items():
                    setattr(row, k, v)
            n_c += 1
        session.commit()
    return {"posts": n_p, "comments": n_c}


def import_marketing(client) -> dict:
    import config
    from backend.db.models.marketing import MarketingPost
    from backend.db.session import get_sessionmaker
    from sqlalchemy import select

    wb = _open_workbook(client, config.SHEET_KEY)
    records = _read_records(wb, config.MARKETING_POSTS_SHEET_NAME)
    _say(f"      [marketing] read {len(records)} rows")

    SessionLocal = get_sessionmaker()
    n = 0
    with SessionLocal() as session:
        for r in records:
            pid = str(r.get("id", "")).strip()
            if not pid:
                continue
            row = session.scalar(select(MarketingPost).where(MarketingPost.id == pid))
            payload = {k: (str(r.get(k, "")) or None) for k in (
                "title", "slug", "category", "summary", "content",
                "thumbnail_url", "is_published", "is_featured",
                "created_by", "created_at", "updated_at",
                "image_file_id", "image_url", "image_alt",
                "meta_description", "tags",
            )}
            if row is None:
                session.add(MarketingPost(id=pid, **payload))
            else:
                for k, v in payload.items():
                    setattr(row, k, v)
            n += 1
        session.commit()
    return {"marketing_posts": n}


def import_signatures_admin(client) -> dict:
    import config
    from backend.db.models.signature import AgentSignature, TempSignatureSlot
    from backend.db.session import get_sessionmaker
    from sqlalchemy import select

    wb = _open_workbook(client, config.SHEET_KEY)
    agent = _read_records(wb, "행정사서명")
    temp = _read_records(wb, "서명임시저장")
    _say(f"      [signatures] read {len(agent)} agent sigs, {len(temp)} temp slots")

    SessionLocal = get_sessionmaker()
    n_a = n_t = 0
    with SessionLocal() as session:
        for r in agent:
            tid = str(r.get("tenant_id", "")).strip()
            data = str(r.get("서명데이터", "")).strip()
            if not tid or not data:
                continue
            row = session.scalar(select(AgentSignature).where(AgentSignature.tenant_id == tid))
            if row is None:
                session.add(AgentSignature(tenant_id=tid, signature_data=data))
            else:
                row.signature_data = data
            n_a += 1
        for r in temp:
            try:
                slot = int(str(r.get("slot", "")).strip())
            except ValueError:
                continue
            tid = str(r.get("tenant_id", "")).strip()
            data = str(r.get("서명데이터", "")).strip()
            if slot not in (1, 2, 3) or not tid or not data:
                continue
            row = session.scalar(select(TempSignatureSlot).where(
                TempSignatureSlot.tenant_id == tid, TempSignatureSlot.slot == slot,
            ))
            note = str(r.get("비고", "") or "")
            if row is None:
                session.add(TempSignatureSlot(
                    tenant_id=tid, slot=slot, signature_data=data, note=note,
                ))
            else:
                row.signature_data = data
                row.note = note
            n_t += 1
        session.commit()
    return {"agent_signatures": n_a, "temp_slots": n_t}


def _import_customer_workbook(client, tenant_id: str, sheet_key: str) -> dict:
    """Import every supported tab from one customer workbook."""
    import config
    from sqlalchemy import select

    from backend.db.models.customer import Customer
    from backend.db.models.daily import DailyBalance, DailyEntry
    from backend.db.models.event import Event
    from backend.db.models.memo import Memo
    from backend.db.models.relationship import (
        AccommodationProvider, GuarantorConnection,
    )
    from backend.db.models.signature import CustomerSignature
    from backend.db.models.task import ActiveTask, CompletedTask, PlannedTask
    from backend.db.session import get_sessionmaker
    from backend.services.customer_pg_service import SHEET_TO_PG

    try:
        wb = _open_workbook(client, sheet_key)
    except Exception as e:
        _say(f"      [customer-workbook:{tenant_id}] cannot open ({sheet_key}): {e}")
        return {"error": str(e)}

    SessionLocal = get_sessionmaker()
    counts: dict[str, int] = {}

    with SessionLocal() as session:
        # customers
        rows = _read_records(wb, config.CUSTOMER_SHEET_NAME)
        n = 0
        for r in rows:
            cid = str(r.get("고객ID", "")).strip()
            if not cid:
                continue
            payload = {SHEET_TO_PG[k]: str(r.get(k, "") or "") for k in SHEET_TO_PG if k in r}
            payload["customer_id"] = cid
            row = session.scalar(select(Customer).where(
                Customer.tenant_id == tenant_id, Customer.customer_id == cid,
            ))
            if row is None:
                session.add(Customer(tenant_id=tenant_id, **payload))
            else:
                for k, v in payload.items():
                    setattr(row, k, v)
                row.deleted_at = None
            n += 1
        counts["customers"] = n

        # events
        ev_rows = _read_records(wb, config.EVENTS_SHEET_NAME)
        session.execute(__import__("sqlalchemy").delete(Event).where(Event.tenant_id == tenant_id))
        n = 0
        per_date: dict[str, int] = {}
        for r in ev_rows:
            d = str(r.get("date_str", "")).strip()
            t = str(r.get("event_text", "")).strip()
            if not d or not t:
                continue
            idx = per_date.get(d, 0)
            session.add(Event(tenant_id=tenant_id, date_str=d, event_text=t, sort_order=idx))
            per_date[d] = idx + 1
            n += 1
        counts["events"] = n

        # memos
        memo_map = {
            "short": config.MEMO_SHORT_SHEET_NAME,
            "mid":   config.MEMO_MID_SHEET_NAME,
            "long":  config.MEMO_LONG_SHEET_NAME,
        }
        n_memo = 0
        for kind, tab in memo_map.items():
            try:
                ws = wb.worksheet(tab)
                content = (ws.acell("A1").value or "").strip()
            except Exception:
                content = ""
            if content:
                row = session.scalar(select(Memo).where(
                    Memo.tenant_id == tenant_id, Memo.kind == kind,
                ))
                if row is None:
                    session.add(Memo(tenant_id=tenant_id, kind=kind, content=content))
                else:
                    row.content = content
                n_memo += 1
        counts["memos"] = n_memo

        # daily entries + balance
        de = _read_records(wb, config.DAILY_SUMMARY_SHEET_NAME)
        n = 0
        for r in de:
            eid = str(r.get("id", "")).strip()
            if not eid:
                continue
            row = session.scalar(select(DailyEntry).where(
                DailyEntry.tenant_id == tenant_id, DailyEntry.entry_id == eid,
            ))
            def _i(v):
                try: return int(float(str(v).replace(",", "").strip() or "0"))
                except Exception: return 0
            payload = dict(
                date=str(r.get("date", "")),
                time=str(r.get("time", "")),
                category=str(r.get("category", "")),
                name=str(r.get("name", "")),
                task=str(r.get("task", "")),
                income_cash=_i(r.get("income_cash")),
                income_etc=_i(r.get("income_etc")),
                exp_cash=_i(r.get("exp_cash")),
                exp_etc=_i(r.get("exp_etc")),
                cash_out=_i(r.get("cash_out")),
                memo=str(r.get("memo", "")),
                customer_id=str(r.get("customer_id", "")),
            )
            if row is None:
                session.add(DailyEntry(tenant_id=tenant_id, entry_id=eid, **payload))
            else:
                for k, v in payload.items():
                    setattr(row, k, v)
            n += 1
        counts["daily_entries"] = n

        bal = _read_records(wb, config.DAILY_BALANCE_SHEET_NAME)
        cash = profit = 0
        for r in bal:
            k = r.get("key")
            v = r.get("value", "0")
            try:
                iv = int(float(str(v).replace(",", "").strip() or "0"))
            except Exception:
                iv = 0
            if k == "cash":
                cash = iv
            elif k == "profit":
                profit = iv
        if bal:
            row = session.scalar(select(DailyBalance).where(DailyBalance.tenant_id == tenant_id))
            if row is None:
                session.add(DailyBalance(tenant_id=tenant_id, cash=cash, profit=profit))
            else:
                row.cash = cash
                row.profit = profit
            counts["daily_balance"] = 1

        # tasks
        def _import_task(tab: str, model, payload_keys: dict):
            from sqlalchemy import select as _sel
            rows = _read_records(wb, tab)
            cnt = 0
            for r in rows:
                tid = str(r.get("id", "")).strip()
                if not tid:
                    continue
                row = session.scalar(_sel(model).where(
                    model.tenant_id == tenant_id, model.task_id == tid,
                ))
                pl = {pg: str(r.get(sh, "")) for sh, pg in payload_keys.items() if sh in r}
                if "processed" in pl:
                    pl["processed"] = str(pl["processed"]).strip().lower() in ("true", "1", "y")
                if row is None:
                    session.add(model(tenant_id=tenant_id, task_id=tid, **pl))
                else:
                    for k, v in pl.items():
                        setattr(row, k, v)
                cnt += 1
            return cnt

        ACTIVE_MAP = {f: f for f in (
            "category", "date", "name", "work", "details",
            "transfer", "cash", "card", "stamp", "receivable",
            "planned_expense", "processed", "processed_timestamp",
            "reception", "processing", "storage", "customer_id", "source_daily_id",
        )}
        PLANNED_MAP = {f: f for f in ("date", "period", "content", "note")}
        COMPLETED_MAP = {f: f for f in (
            "category", "date", "name", "work", "details", "complete_date",
            "reception", "processing", "storage", "customer_id",
        )}
        counts["active_tasks"] = _import_task(config.ACTIVE_TASKS_SHEET_NAME, ActiveTask, ACTIVE_MAP)
        counts["planned_tasks"] = _import_task(config.PLANNED_TASKS_SHEET_NAME, PlannedTask, PLANNED_MAP)
        counts["completed_tasks"] = _import_task(config.COMPLETED_TASKS_SHEET_NAME, CompletedTask, COMPLETED_MAP)

        # customer signatures
        cs = _read_records(wb, "고객서명")
        n = 0
        for r in cs:
            cid = str(r.get("고객ID", "")).strip()
            data = str(r.get("서명데이터", "")).strip()
            if not cid or not data:
                continue
            row = session.scalar(select(CustomerSignature).where(
                CustomerSignature.tenant_id == tenant_id,
                CustomerSignature.customer_id == cid,
            ))
            if row is None:
                session.add(CustomerSignature(
                    tenant_id=tenant_id, customer_id=cid, signature_data=data,
                ))
            else:
                row.signature_data = data
            n += 1
        counts["customer_signatures"] = n

        # accommodation
        ap = _read_records(wb, "숙소제공자연결")
        n = 0
        ACCOM_FIELDS = (
            "target_customer_id", "provider_type", "provider_customer_id",
            "provider_name", "provider_last_name", "provider_first_name",
            "provider_nation", "provider_reg_front", "provider_reg_back",
            "provider_birth", "provider_phone", "provider_address",
            "provider_relation", "provide_start_date", "provide_end_date", "housing_type",
        )
        for r in ap:
            tgt = str(r.get("target_customer_id", "")).strip()
            if not tgt:
                continue
            row = session.scalar(select(AccommodationProvider).where(
                AccommodationProvider.tenant_id == tenant_id,
                AccommodationProvider.target_customer_id == tgt,
            ))
            pl = {f: str(r.get(f, "") or "") for f in ACCOM_FIELDS}
            if row is None:
                session.add(AccommodationProvider(tenant_id=tenant_id, **pl))
            else:
                for k, v in pl.items():
                    setattr(row, k, v)
            n += 1
        counts["accommodation_providers"] = n

        # guarantor
        gp = _read_records(wb, "신원보증인연결")
        n = 0
        GUARANTOR_FIELDS = (
            "target_customer_id", "guarantor_type", "guarantor_customer_id",
            "guarantor_name", "guarantor_last_name", "guarantor_first_name",
            "guarantor_nation", "guarantor_reg_front", "guarantor_reg_back",
            "guarantor_birth", "guarantor_phone", "guarantor_address",
            "guarantor_relation", "guarantor_workplace", "guarantor_extra",
        )
        for r in gp:
            tgt = str(r.get("target_customer_id", "")).strip()
            if not tgt:
                continue
            row = session.scalar(select(GuarantorConnection).where(
                GuarantorConnection.tenant_id == tenant_id,
                GuarantorConnection.target_customer_id == tgt,
            ))
            pl = {f: str(r.get(f, "") or "") for f in GUARANTOR_FIELDS}
            if row is None:
                session.add(GuarantorConnection(tenant_id=tenant_id, **pl))
            else:
                for k, v in pl.items():
                    setattr(row, k, v)
            n += 1
        counts["guarantor_connections"] = n

        session.commit()

    return counts


def _import_work_workbook(client, tenant_id: str, sheet_key: str) -> dict:
    """Import every tab from one work_sheet_key workbook."""
    from backend.services.reference_pg_service import replace_sheet
    counts: dict[str, int] = {}
    try:
        wb = _open_workbook(client, sheet_key)
    except Exception as e:
        _say(f"      [work-workbook:{tenant_id}] cannot open: {e}")
        return {"error": str(e)}

    for ws in wb.worksheets():
        tab = ws.title
        try:
            values = ws.get_all_values()
        except Exception as e:
            _say(f"        [skip] {tab}: {e}")
            continue
        if not values:
            continue
        headers = [(h or "").strip() or f"col_{i + 1}" for i, h in enumerate(values[0])]
        # dedupe header names
        seen: dict[str, int] = {}
        clean: list[str] = []
        for h in headers:
            if h in seen:
                seen[h] += 1
                clean.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                clean.append(h)
        data = [
            {clean[i]: (row[i] if i < len(row) else "") for i in range(len(clean))}
            for row in values[1:]
            if any(c.strip() for c in row)
        ]
        try:
            replace_sheet(tenant_id, tab, clean, data)
            counts[tab] = len(data)
        except Exception as e:
            _say(f"        [skip] replace_sheet({tab}) failed: {e}")
    return counts


def import_hanwoory(client) -> dict:
    """신 고객 데이터 + 신 업무정리 (hanwoory's live workbooks)."""
    import config
    from sqlalchemy import select

    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == config.DEFAULT_TENANT_ID))
        customer_key = t.customer_sheet_key if t and t.customer_sheet_key else None
        work_key = t.work_sheet_key if t and t.work_sheet_key else None

    # If hanwoory has explicit keys, use them. Otherwise fall back to the admin
    # master SHEET_KEY (matches the DEFAULT_TENANT_ID fallback in tenant_service).
    customer_key = customer_key or config.SHEET_KEY
    work_key = work_key or config.WORK_REFERENCE_TEMPLATE_ID
    _say(f"    [hanwoory] customer_workbook={customer_key[-8:]}...  work_workbook={work_key[-8:]}...")

    out = {
        "customer_workbook": _import_customer_workbook(client, config.DEFAULT_TENANT_ID, customer_key),
        "work_workbook": _import_work_workbook(client, config.DEFAULT_TENANT_ID, work_key),
    }
    return out


def import_tenant_workbooks(client) -> dict:
    """Every non-hanwoory tenant's customer + work workbooks."""
    import config
    from sqlalchemy import select

    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(select(Tenant)).all()
        targets = [
            (t.tenant_id, t.customer_sheet_key, t.work_sheet_key)
            for t in rows
            if t.tenant_id != config.DEFAULT_TENANT_ID
        ]

    out: dict[str, dict] = {}
    for tid, ck, wk in targets:
        sub = {}
        if ck:
            sub["customer_workbook"] = _import_customer_workbook(client, tid, ck)
        else:
            sub["customer_workbook"] = {"skip": "no customer_sheet_key"}
        if wk:
            sub["work_workbook"] = _import_work_workbook(client, tid, wk)
        else:
            sub["work_workbook"] = {"skip": "no work_sheet_key"}
        out[tid] = sub
    return out


# ── main ──────────────────────────────────────────────────────────────────

DOMAINS = {
    "accounts", "board", "marketing", "signatures",
    "hanwoory", "tenant_workbooks",
}


def main() -> int:
    _utf8()
    ap = argparse.ArgumentParser(description="Full local-beta importer.")
    ap.add_argument("--execute", action="store_true", help="Write to local PG.")
    ap.add_argument(
        "--only", default="all",
        help=f"Comma-separated subset of: {','.join(sorted(DOMAINS))}",
    )
    args = ap.parse_args()

    from backend.db.local_guard import assert_local_database_url
    assert_local_database_url(os.environ.get("DATABASE_URL"))
    _say("[guard] DATABASE_URL host: PASS (loopback)")
    _say(f"[mode]  {'EXECUTE — writes to local PG' if args.execute else 'DRY-RUN — no writes'}")

    wanted = DOMAINS if args.only == "all" else {x.strip() for x in args.only.split(",") if x.strip()}
    unknown = wanted - DOMAINS
    if unknown:
        print(f"[abort] unknown domains: {unknown}", file=sys.stderr)
        return 2
    _say(f"[plan]  domains: {sorted(wanted)}")

    if not args.execute:
        _say("[dry-run] No DB writes, no Sheets writes. Re-run with --execute to actually import.")
        return 0

    try:
        client = _gspread_client()
    except Exception as e:
        _say(f"[abort] gspread client init failed: {type(e).__name__}: {e}")
        _say("        Possible cause: KEY_PATH service account JSON missing or invalid.")
        return 3

    import_batch_id = uuid.uuid4().hex[:12]
    _say(f"[batch] import_batch_id={import_batch_id}")

    results: dict[str, Any] = {"import_batch_id": import_batch_id}

    def _safe_run(name: str, fn):
        if name not in wanted:
            return
        _say(f"\n[run] {name}")
        try:
            results[name] = fn(client)
            _say(f"    [ok] {name}: {results[name]}")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            _say(f"    [fail] {name}: {err}")
            _say(traceback.format_exc())
            results[name] = {"error": err}

    _safe_run("accounts", import_accounts)
    _safe_run("board", import_board)
    _safe_run("marketing", import_marketing)
    _safe_run("signatures", import_signatures_admin)
    _safe_run("hanwoory", import_hanwoory)
    _safe_run("tenant_workbooks", import_tenant_workbooks)

    _say("\n[done]")
    for k, v in results.items():
        if k != "import_batch_id":
            _say(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
