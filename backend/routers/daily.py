"""일일결산 라우터 (테넌트 인식)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException

from backend.auth import get_current_user
from backend.models import DailyEntry, BalanceData
from backend.services.tenant_service import read_sheet, upsert_sheet, delete_from_sheet, get_worksheet, invalidate_read_cache

router = APIRouter()

DAILY_HEADER = [
    "id", "date", "time", "category", "name", "task",
    "income_cash", "income_etc", "exp_cash", "cash_out", "exp_etc", "memo",
    "customer_id",
]
BALANCE_HEADER = ["key", "value"]


def _safe_int(v):
    try:
        return int(float(str(v).replace(",", "").strip() or "0"))
    except Exception:
        return 0


@router.get("/entries")
def get_entries(
    date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    user: dict = Depends(get_current_user),
):
    from config import DAILY_SUMMARY_SHEET_NAME
    records = read_sheet(DAILY_SUMMARY_SHEET_NAME, user["tenant_id"], default_if_empty=[])
    if date:
        records = [r for r in records if r.get("date", "") == date]
    return records


_ACTIVE_HEADER = [
    "id", "category", "date", "name", "work", "details",
    "transfer", "cash", "card", "stamp", "receivable",
    "planned_expense", "processed", "processed_timestamp",
    "reception", "processing", "storage", "customer_id",
    "source_daily_id",
]


def _append_delegation_to_customer(rec: dict, tenant_id: str) -> None:
    """일일결산 저장 후 고객 '위임내역' 컬럼에 한 줄 추가 (append only).
    현금출금 카테고리 및 이름이 비어있는 경우는 건너뜀.
    customer_id가 있으면 고객ID로 정확 매칭, 없으면 한글이름 매칭으로 폴백."""
    from config import CUSTOMER_SHEET_NAME

    category    = str(rec.get("category",    "")).strip()
    name        = str(rec.get("name",        "")).strip()
    customer_id = str(rec.get("customer_id", "")).strip()
    if category == "현금출금" or not name:
        return

    date = str(rec.get("date", "")).strip()
    task = str(rec.get("task", "")).strip()

    # packed memo → 사용자 노트 추출: [KID]...[/KID] 뒤 텍스트
    memo      = str(rec.get("memo", "")) or ""
    user_note = ""
    if "[/KID]" in memo:
        user_note = memo[memo.index("[/KID]") + 6:].strip()
    elif "[KID]" not in memo:
        user_note = memo.strip()

    deposit    = _safe_int(rec.get("income_cash", 0)) + _safe_int(rec.get("income_etc", 0))
    withdrawal = (_safe_int(rec.get("exp_cash", 0)) + _safe_int(rec.get("exp_etc", 0))
                  + _safe_int(rec.get("cash_out", 0)))
    net_profit = deposit - withdrawal

    parts = [p for p in [date, category, task] if p]
    amt_parts: list = []
    if deposit:               amt_parts.append(f"입금 {deposit:,}")
    if withdrawal:            amt_parts.append(f"출금 {withdrawal:,}")
    if deposit or withdrawal: amt_parts.append(f"순수익 {net_profit:,}")

    entry = " ".join(parts)
    if amt_parts:
        entry += f" ({', '.join(amt_parts)})"
    if user_note:
        entry += f" [{user_note}]"
    if not entry.strip():
        return

    # 고객 시트 조회
    records = read_sheet(CUSTOMER_SHEET_NAME, tenant_id, default_if_empty=[]) or []
    if not records:
        return

    header_list = list(records[0].keys())

    # customer_id 우선 매칭, 없으면 한글이름 폴백
    if customer_id:
        target = next((r for r in records if str(r.get("고객ID", "")).strip() == customer_id), None)
    else:
        target = next((r for r in records if str(r.get("한글", "")).strip() == name), None)
    if not target:
        return  # 매칭 없으면 조용히 건너뜀

    existing = str(target.get("위임내역", "")).strip()
    target["위임내역"] = (existing + "\n" + entry).strip() if existing else entry
    upsert_sheet(CUSTOMER_SHEET_NAME, tenant_id, header_list, [target], id_field="고객ID")


class _DedupeResult:
    """Return value of _dedupe_active_rows_by_source."""
    __slots__ = ("matched_count", "kept_row", "deleted_rows")
    def __init__(self, matched_count: int = 0, kept_row: "int | None" = None, deleted_rows: "list[int] | None" = None):
        self.matched_count = matched_count
        self.kept_row      = kept_row
        self.deleted_rows  = deleted_rows or []


def _dedupe_active_rows_by_source(source_daily_id: str, task_id: str, tenant_id: str) -> _DedupeResult:
    """진행업무 시트에서 source_daily_id 또는 task_id 가 일치하는 중복 행을 row index 기준으로 제거.
    id 값이 공유되는 경우에도 안전하게 동작. reception 등 더 완전한 행을 우선 보존.
    반환값: matched_count (0이면 해당 행이 시트에 없음 = upsert가 실제로 기록 안 됨)."""
    from config import ACTIVE_TASKS_SHEET_NAME
    if not source_daily_id and not task_id:
        return _DedupeResult()
    try:
        ws = get_worksheet(ACTIVE_TASKS_SHEET_NAME, tenant_id)
        values = ws.get_all_values()
        if len(values) < 2:
            return _DedupeResult()
        header = values[0]
        id_idx        = header.index("id")              if "id"              in header else None
        sdid_idx      = header.index("source_daily_id") if "source_daily_id" in header else None
        reception_idx = header.index("reception")       if "reception"       in header else None

        dup_rows: list = []  # (sheet_row_index, reception_value)
        for r_i, row in enumerate(values[1:], start=2):
            row_id   = str(row[id_idx]).strip()   if id_idx   is not None and id_idx   < len(row) else ""
            row_sdid = str(row[sdid_idx]).strip() if sdid_idx is not None and sdid_idx < len(row) else ""
            if (source_daily_id and row_sdid == source_daily_id) or (task_id and row_id == task_id):
                reception = str(row[reception_idx]).strip() if reception_idx is not None and reception_idx < len(row) else ""
                dup_rows.append((r_i, reception))

        matched_count = len(dup_rows)
        if matched_count <= 1:
            kept = dup_rows[0][0] if dup_rows else None
            return _DedupeResult(matched_count=matched_count, kept_row=kept)

        # Keep the most complete row: prefer a row that has a reception timestamp.
        # Among ties, keep the last occurrence (most recently appended).
        keep_pos = max(range(len(dup_rows)), key=lambda i: (bool(dup_rows[i][1]), i))
        rows_to_delete = sorted(
            [r_i for j, (r_i, _) in enumerate(dup_rows) if j != keep_pos],
            reverse=True,  # highest index first so row numbers don't shift
        )
        for row_no in rows_to_delete:
            ws.delete_rows(row_no)
            print(f"[daily] dedupe: removed duplicate active-task row {row_no}")
        invalidate_read_cache(tenant_id, ACTIVE_TASKS_SHEET_NAME)
        kept_row = dup_rows[keep_pos][0]
        print(f"[daily] dedupe: kept row {kept_row}, removed {len(rows_to_delete)} duplicate(s)")
        return _DedupeResult(matched_count=matched_count, kept_row=kept_row, deleted_rows=rows_to_delete)
    except Exception as e:
        print(f"[daily] dedupe failed (non-fatal): {e}")
        return _DedupeResult()  # unknown state — caller must decide


def _apply_daily_to_active(rec: dict, tenant_id: str) -> None:
    """page_daily.py apply_daily_to_active_tasks 와 동일한 로직.
    현금출금 제외한 모든 일일결산 저장 시 호출.
    source_daily_id + 결정론적 id 로 gspread retry/propagation race 에 의한 중복 append 방지."""
    import re as _re
    from config import ACTIVE_TASKS_SHEET_NAME

    category    = str(rec.get("category",    "")).strip()
    if category == "현금출금":
        return

    name        = str(rec.get("name",        "")).strip()
    work        = str(rec.get("task",        "")).strip()   # daily.task == active.work
    date        = str(rec.get("date",        "")).strip()
    customer_id = str(rec.get("customer_id", "")).strip()
    source_daily_id = str(rec.get("id", "")).strip()

    # 결정론적 active task id — 동일 일일결산 row 에서 항상 동일한 id.
    # gspread retry 시 upsert_sheet 가 append 대신 update 를 수행하도록 보장.
    active_task_id = ("daily-" + source_daily_id) if source_daily_id else str(uuid.uuid4())

    # 메모에서 income/expense 유형 파싱: [KID]inc=X;e1=Y;e2=Z[/KID]
    memo = str(rec.get("memo", "")) or ""
    m = _re.search(r'\[KID\](.*?)\[/KID\]', memo)
    inc_type = e1_type = e2_type = ""
    e1_indiv = e2_indiv = 0  # per-slot amounts from new memo format (e1a= / e2a=)
    if m:
        parts = dict(p.split("=", 1) for p in m.group(1).split(";") if "=" in p)
        inc_type = parts.get("inc", "")
        e1_type  = parts.get("e1", "")
        e2_type  = parts.get("e2", "")
        try: e1_indiv = int(parts.get("e1a", "0") or "0")
        except Exception: e1_indiv = 0
        try: e2_indiv = int(parts.get("e2a", "0") or "0")
        except Exception: e2_indiv = 0

    income_cash = _safe_int(rec.get("income_cash", 0))
    income_etc  = _safe_int(rec.get("income_etc", 0))
    exp_cash    = _safe_int(rec.get("exp_cash", 0))
    exp_etc     = _safe_int(rec.get("exp_etc", 0))

    # 진행업무 필드별 누적 델타
    delta: dict = {"transfer": 0, "cash": 0, "card": 0, "stamp": 0, "receivable": 0}

    # 수입 유형 매핑 — income-side values must NOT flow into active-task columns.
    # Active-task columns are populated from expense slots only.

    # 지출 유형 매핑: expense slots → active-task payment columns
    # New format (e1a/e2a present): precise per-slot mapping
    if e1_indiv or e2_indiv:
        for etype, eamt in ((e1_type, e1_indiv), (e2_type, e2_indiv)):
            if not etype or not eamt:
                continue
            if etype == "이체":   delta["transfer"] += eamt
            elif etype == "현금": delta["cash"]     += eamt
            elif etype == "카드": delta["card"]     += eamt
            elif etype == "인지": delta["stamp"]    += eamt
    else:
        # Legacy format: no individual amounts — best-effort mapping
        # If only one distinct non-cash expense type exists, map exp_etc to it
        non_cash_types = {t for t in (e1_type, e2_type) if t and t != "현금"}
        if len(non_cash_types) == 1:
            t = next(iter(non_cash_types))
            if t == "이체":   delta["transfer"] += exp_etc
            elif t == "카드": delta["card"]     += exp_etc
            elif t == "인지": delta["stamp"]    += exp_etc
        # Cash expenses from exp_cash
        if "현금" in (e1_type, e2_type) and exp_cash:
            delta["cash"] += exp_cash

    # 매칭 진행업무 조회
    active_tasks = read_sheet(ACTIVE_TASKS_SHEET_NAME, tenant_id, default_if_empty=[]) or []

    # 1차: source_daily_id 기반 매칭 — 가장 안전한 idempotency key
    matched = None
    if source_daily_id:
        matched = next(
            (t for t in active_tasks
             if str(t.get("source_daily_id", "")).strip() == source_daily_id),
            None
        )

    # 2차 fallback: source_daily_id 없는 레거시 행에 한해 content 매칭
    if not matched:
        matched = next(
            (t for t in active_tasks
             if not str(t.get("source_daily_id", "")).strip()
             and t.get("category") == category
             and t.get("date") == date
             and t.get("name") == name
             and t.get("work") == work),
            None
        )

    if matched:
        for field, dv in delta.items():
            if dv:
                matched[field] = str(_safe_int(matched.get(field, 0)) + dv)
        # customer_id가 새로 들어오면 기존 행에도 반영 (빈값인 경우만 덮어쓰기)
        if customer_id and not str(matched.get("customer_id", "")).strip():
            matched["customer_id"] = customer_id
        # 레거시 행에 source_daily_id 마이그레이션
        if source_daily_id and not str(matched.get("source_daily_id", "")).strip():
            matched["source_daily_id"] = source_daily_id
        upsert_sheet(ACTIVE_TASKS_SHEET_NAME, tenant_id, _ACTIVE_HEADER, [matched], id_field="id")
    else:
        new_task = {
            "id":                  active_task_id,
            "source_daily_id":     source_daily_id,
            "category":            category,
            "date":                date,
            "name":                name,
            "work":                work,
            "details":             "",
            "transfer":            str(delta["transfer"]),
            "cash":                str(delta["cash"]),
            "card":                str(delta["card"]),
            "stamp":               str(delta["stamp"]),
            "receivable":          str(delta["receivable"]),
            "planned_expense":     "",
            "processed":           "",
            "processed_timestamp": "",
            "reception":           datetime.utcnow().isoformat() + "Z",
            "processing":          "",
            "storage":             "",
            "customer_id":         customer_id,
        }
        upsert_error: "Exception | None" = None
        try:
            upsert_sheet(ACTIVE_TASKS_SHEET_NAME, tenant_id, _ACTIVE_HEADER, [new_task], id_field="id")
        except Exception as upsert_err:
            _raise_if_quota(upsert_err)
            upsert_error = upsert_err
            print(f"[daily] active task upsert exception — verifying via re-read: {upsert_err}")

        # Read-back: verify the row exists and clean up any duplicates from retry/race.
        dedupe_result = _dedupe_active_rows_by_source(source_daily_id, active_task_id, tenant_id)

        if upsert_error is not None and dedupe_result.matched_count == 0:
            # Exception raised AND row is confirmed absent: the write failed.
            # Re-raise so the caller (add_entry) returns an error to the frontend.
            raise upsert_error

        if upsert_error is None and dedupe_result.matched_count == 0:
            # Upsert appeared to succeed but the row is not in the sheet.
            # This is a serious data inconsistency.
            raise RuntimeError(
                f"[daily] active task write inconsistency: upsert reported success "
                f"but source_daily_id={source_daily_id!r} / id={active_task_id!r} "
                f"not found on re-read. Daily entry was saved but 진행업무 was not."
            )

    # 백엔드 캐시 무효화 — tasks.py get_active_tasks 가 TTL 캐시를 사용하므로
    # 여기서 직접 sheet 에 쓴 뒤 캐시를 비워야 프론트 refetch 시 최신 데이터가 반환됨
    from backend.services.cache_service import cache_invalidate
    cache_invalidate(tenant_id, "tasks:active")


@router.post("/entries", response_model=dict)
def add_entry(entry: DailyEntry, user: dict = Depends(get_current_user)):
    from config import DAILY_SUMMARY_SHEET_NAME
    if not entry.id:
        entry.id = str(uuid.uuid4())
    rec = {k: ("" if v is None else str(v)) for k, v in entry.model_dump().items()}
    ok = upsert_sheet(DAILY_SUMMARY_SHEET_NAME, user["tenant_id"], DAILY_HEADER, [rec], id_field="id")
    if not ok:
        raise HTTPException(status_code=500, detail="일일결산 저장 실패 — 구글 시트에 기록되지 않았습니다.")
    # 일일결산 저장 후 진행업무에 반영 (현금출금 제외)
    try:
        _apply_daily_to_active(rec, user["tenant_id"])
    except Exception as _e:
        print(f"[daily] apply_daily_to_active 실패: {_e}")
    # 일일결산 저장 후 고객 위임내역에 이력 추가
    try:
        _append_delegation_to_customer(rec, user["tenant_id"])
    except Exception as _e:
        print(f"[daily] append_delegation_to_customer 실패: {_e}")
    return rec


@router.put("/entries/{entry_id}", response_model=dict)
def update_entry(entry_id: str, entry: DailyEntry, user: dict = Depends(get_current_user)):
    from config import DAILY_SUMMARY_SHEET_NAME
    entry.id = entry_id
    rec = {k: ("" if v is None else str(v)) for k, v in entry.model_dump().items()}
    upsert_sheet(DAILY_SUMMARY_SHEET_NAME, user["tenant_id"], DAILY_HEADER, [rec], id_field="id")
    return rec


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, user: dict = Depends(get_current_user)):
    from config import DAILY_SUMMARY_SHEET_NAME
    delete_from_sheet(DAILY_SUMMARY_SHEET_NAME, user["tenant_id"], [entry_id], id_field="id")
    return {"deleted": entry_id}


@router.get("/balance", response_model=BalanceData)
def get_balance(user: dict = Depends(get_current_user)):
    from config import DAILY_BALANCE_SHEET_NAME
    records = read_sheet(DAILY_BALANCE_SHEET_NAME, user["tenant_id"], default_if_empty=[])
    balance = {"cash": 0, "profit": 0}
    for r in records:
        k = r.get("key")
        if k in balance:
            balance[k] = _safe_int(r.get("value", 0))
    return balance


@router.post("/balance", response_model=BalanceData)
def save_balance(data: BalanceData, user: dict = Depends(get_current_user)):
    from config import DAILY_BALANCE_SHEET_NAME
    tenant_id = user["tenant_id"]
    rows = [
        {"key": "cash",   "value": str(data.cash)},
        {"key": "profit", "value": str(data.profit)},
    ]
    try:
        ws = get_worksheet(DAILY_BALANCE_SHEET_NAME, tenant_id)
        ws.clear()
        ws.update("A1", [BALANCE_HEADER] + [[r["key"], r["value"]] for r in rows],
                  value_input_option="RAW")
    except Exception as e:
        print(f"[daily] save_balance 실패: {e}")
    return data


@router.get("/summary")
def get_monthly_summary(
    year: int = Query(...),
    month: int = Query(...),
    user: dict = Depends(get_current_user),
):
    """월별 수입/지출 합계"""
    from config import DAILY_SUMMARY_SHEET_NAME
    records = read_sheet(DAILY_SUMMARY_SHEET_NAME, user["tenant_id"], default_if_empty=[])

    prefix = f"{year}-{month:02d}"
    monthly = [r for r in records if str(r.get("date", "")).startswith(prefix)]

    total_income_cash = sum(_safe_int(r.get("income_cash")) for r in monthly)
    total_income_etc  = sum(_safe_int(r.get("income_etc")) for r in monthly)
    total_exp_cash    = sum(_safe_int(r.get("exp_cash")) for r in monthly)
    total_exp_etc     = sum(_safe_int(r.get("exp_etc")) for r in monthly)
    total_cash_out    = sum(_safe_int(r.get("cash_out")) for r in monthly)

    return {
        "year": year,
        "month": month,
        "income_cash": total_income_cash,
        "income_etc": total_income_etc,
        "exp_cash": total_exp_cash,
        "exp_etc": total_exp_etc,
        "cash_out": total_cash_out,
        "net_income": (total_income_cash + total_income_etc) - (total_exp_cash + total_exp_etc),
        "entries": monthly,
    }


@router.get("/monthly-analysis")
def get_monthly_analysis(
    year: int = Query(...),
    month: int = Query(...),
    user: dict = Depends(get_current_user),
):
    """월간 결산 분석 (요약테이블 + 추세 + 요일별 + 카테고리별 + 시간대별)"""
    import datetime
    from collections import defaultdict
    from config import DAILY_SUMMARY_SHEET_NAME

    records = read_sheet(DAILY_SUMMARY_SHEET_NAME, user["tenant_id"], default_if_empty=[])

    # ── 전체 월별 요약 테이블 + 추세 ─────────────────────────────────────────
    monthly_full: dict = defaultdict(lambda: {
        "income_cash": 0, "income_etc": 0,
        "exp_cash": 0, "exp_etc": 0, "net": 0,
    })
    for r in records:
        date_str = str(r.get("date", ""))
        if len(date_str) >= 7:
            ym = date_str[:7]
            ic = _safe_int(r.get("income_cash"))
            ie = _safe_int(r.get("income_etc"))
            ec = _safe_int(r.get("exp_cash"))
            ee = _safe_int(r.get("exp_etc"))
            monthly_full[ym]["income_cash"] += ic
            monthly_full[ym]["income_etc"]  += ie
            monthly_full[ym]["exp_cash"]    += ec
            monthly_full[ym]["exp_etc"]     += ee
            monthly_full[ym]["net"]         += (ic + ie) - (ec + ee)

    summary_table = [{"month": k, **v} for k, v in sorted(monthly_full.items())]

    # ── 선택 월 상세 분석 ────────────────────────────────────────────────────
    prefix = f"{year}-{month:02d}"
    monthly_entries = [r for r in records if str(r.get("date", "")).startswith(prefix)]

    WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]
    dow_data:      dict = defaultdict(int)
    category_data: dict = defaultdict(int)
    hour_data:     dict = defaultdict(int)

    for r in monthly_entries:
        date_str = str(r.get("date", ""))
        time_str = str(r.get("time", "00:00"))
        cat      = str(r.get("category", "기타")).strip() or "기타"
        net      = (_safe_int(r.get("income_cash")) + _safe_int(r.get("income_etc"))) - \
                   (_safe_int(r.get("exp_cash"))    + _safe_int(r.get("exp_etc")))

        try:
            d = datetime.date.fromisoformat(date_str)
            dow_data[WEEKDAY_KR[d.weekday()]] += net
        except Exception:
            pass

        category_data[cat] += net

        try:
            hour = int(time_str.split(":")[0])
            hour_data[hour] += net
        except Exception:
            pass

    return {
        "summary_table": summary_table,
        "trend": [{"month": row["month"], "net": row["net"]} for row in summary_table],
        "selected_month": prefix,
        "dow": [{"name": n, "net": dow_data[n]} for n in WEEKDAY_KR],
        "category": sorted(
            [{"name": k, "net": v} for k, v in category_data.items()],
            key=lambda x: -x["net"],
        ),
        "hour": [
            {"hour": f"{h:02d}시", "net": hour_data[h]}
            for h in sorted(hour_data.keys())
        ],
    }
