"""일일결산 라우터 (테넌트 인식)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, Query

from backend.auth import get_current_user
from backend.models import DailyEntry, BalanceData
from backend.services.tenant_service import read_sheet, upsert_sheet, delete_from_sheet, get_worksheet

router = APIRouter()

DAILY_HEADER = [
    "id", "date", "time", "category", "name", "task",
    "income_cash", "income_etc", "exp_cash", "cash_out", "exp_etc", "memo",
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
    "reception", "processing", "storage",
]


def _append_delegation_to_customer(rec: dict, tenant_id: str) -> None:
    """일일결산 저장 후 고객 '위임내역' 컬럼에 한 줄 추가 (append only).
    현금출금 카테고리 및 이름이 비어있는 경우는 건너뜀.
    고객 조회는 한글이름(name 필드) 정확 매칭."""
    from config import CUSTOMER_SHEET_NAME

    category = str(rec.get("category", "")).strip()
    name     = str(rec.get("name",     "")).strip()
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

    # 고객 시트에서 한글이름으로 조회
    records = read_sheet(CUSTOMER_SHEET_NAME, tenant_id, default_if_empty=[]) or []
    if not records:
        return

    header_list = list(records[0].keys())
    target = next((r for r in records if str(r.get("한글", "")).strip() == name), None)
    if not target:
        return  # 매칭 없으면 조용히 건너뜀

    existing = str(target.get("위임내역", "")).strip()
    target["위임내역"] = (existing + "\n" + entry).strip() if existing else entry
    upsert_sheet(CUSTOMER_SHEET_NAME, tenant_id, header_list, [target], id_field="고객ID")


def _apply_daily_to_active(rec: dict, tenant_id: str) -> None:
    """page_daily.py apply_daily_to_active_tasks 와 동일한 로직.
    현금출금 제외한 모든 일일결산 저장 시 호출."""
    import re as _re
    from config import ACTIVE_TASKS_SHEET_NAME

    category = str(rec.get("category", "")).strip()
    if category == "현금출금":
        return

    name = str(rec.get("name", "")).strip()
    work = str(rec.get("task", "")).strip()   # daily.task == active.work
    date = str(rec.get("date", "")).strip()

    # 메모에서 income/expense 유형 파싱: [KID]inc=X;e1=Y;e2=Z[/KID]
    memo = str(rec.get("memo", "")) or ""
    m = _re.search(r'\[KID\](.*?)\[/KID\]', memo)
    inc_type = e1_type = e2_type = ""
    if m:
        parts = dict(p.split("=", 1) for p in m.group(1).split(";") if "=" in p)
        inc_type = parts.get("inc", "")
        e1_type  = parts.get("e1", "")
        e2_type  = parts.get("e2", "")

    income_cash = _safe_int(rec.get("income_cash", 0))
    income_etc  = _safe_int(rec.get("income_etc", 0))
    exp_cash    = _safe_int(rec.get("exp_cash", 0))
    exp_etc     = _safe_int(rec.get("exp_etc", 0))

    # 진행업무 필드별 누적 델타
    delta: dict = {"transfer": 0, "cash": 0, "card": 0, "stamp": 0, "receivable": 0}

    # 수입 유형 매핑
    if inc_type == "현금":
        delta["cash"] += income_cash
    elif inc_type == "이체":
        delta["transfer"] += income_etc
    elif inc_type == "카드":
        delta["card"] += income_etc
    elif inc_type == "미수":
        delta["receivable"] += income_etc

    # 지출 유형 매핑 (인지만 진행업무에 누적)
    for etype in (e1_type, e2_type):
        if etype == "인지":
            delta["stamp"] += exp_etc

    # 매칭 진행업무 조회 (category + date + name + work)
    active_tasks = read_sheet(ACTIVE_TASKS_SHEET_NAME, tenant_id, default_if_empty=[]) or []
    matched = next(
        (t for t in active_tasks
         if t.get("category") == category
         and t.get("date") == date
         and t.get("name") == name
         and t.get("work") == work),
        None
    )

    if matched:
        for field, dv in delta.items():
            if dv:
                matched[field] = str(_safe_int(matched.get(field, 0)) + dv)
        upsert_sheet(ACTIVE_TASKS_SHEET_NAME, tenant_id, _ACTIVE_HEADER, [matched], id_field="id")
    else:
        # 매칭 업무 없으면 신규 진행업무 생성
        new_task = {
            "id":                  str(uuid.uuid4()),
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
            "reception":           "",
            "processing":          "",
            "storage":             "",
        }
        upsert_sheet(ACTIVE_TASKS_SHEET_NAME, tenant_id, _ACTIVE_HEADER, [new_task], id_field="id")


@router.post("/entries", response_model=dict)
def add_entry(entry: DailyEntry, user: dict = Depends(get_current_user)):
    from config import DAILY_SUMMARY_SHEET_NAME
    if not entry.id:
        entry.id = str(uuid.uuid4())
    rec = {k: ("" if v is None else str(v)) for k, v in entry.model_dump().items()}
    upsert_sheet(DAILY_SUMMARY_SHEET_NAME, user["tenant_id"], DAILY_HEADER, [rec], id_field="id")
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
