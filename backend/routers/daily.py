"""일일결산 라우터 (테넌트 인식)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException

from backend.auth import get_current_user
from backend.models import DailyEntry, BalanceData
# PG-only(Phase E): tenant_service Sheets I/O(read_sheet/upsert_sheet/get_worksheet 등) import 제거.

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


import re as _re_mod

_KID_RE = _re_mod.compile(r"\[KID\](.*?)\[/KID\]")


def _entry_card_expense(rec: dict) -> int:
    """일일결산 1건의 '카드' 지출 금액(원).

    결제수단/슬롯별 금액은 memo 의 ``[KID]inc=..;e1=..;e1a=..;e2=..;e2a=..[/KID]`` 블록에
    보존된다(프론트 packMemo). 신규 형식(e1a/e2a 존재)만 카드 금액을 정확히 분리할 수 있고,
    레거시(블록 없음)는 카드/이체/인지가 exp_etc 로 합산돼 분리 불가 → 0 으로 처리하여
    카드지출 과대계상을 막는다. 읽기 전용 계산이며 데이터를 변경하지 않는다."""
    memo = str(rec.get("memo", "") or "")
    m = _KID_RE.search(memo)
    if not m:
        return 0
    try:
        parts = dict(p.split("=", 1) for p in m.group(1).split(";") if "=" in p)
    except Exception:
        return 0
    total = 0
    for t_key, a_key in (("e1", "e1a"), ("e2", "e2a")):
        if parts.get(t_key, "") == "카드":
            total += _safe_int(parts.get(a_key, "0"))
    return total


def _fetch_daily_records(tenant_id: str) -> list:
    """일일결산 레코드 조회 — PG-only(Phase E). Google Sheets 미사용."""
    from backend.services.daily_pg_service import list_entries
    return list_entries(tenant_id) or []


def _entry_sales(rec: dict) -> int:
    return _safe_int(rec.get("income_cash")) + _safe_int(rec.get("income_etc"))


def _entry_expense(rec: dict) -> int:
    return _safe_int(rec.get("exp_cash")) + _safe_int(rec.get("exp_etc"))


def _entry_kid_parts(rec: dict) -> dict:
    """memo 의 [KID] 메타(inc/e1/e1a/e2/e2a/tax) 를 dict 로 파싱. 없으면 {}."""
    memo = str(rec.get("memo", "") or "")
    m = _KID_RE.search(memo)
    if not m:
        return {}
    try:
        return dict(p.split("=", 1) for p in m.group(1).split(";") if "=" in p)
    except Exception:
        return {}


def _entry_reported_sales(rec: dict) -> int:
    """세무 자동 신고매출 대상 금액(원). 수입 결제수단이 카드(inc=카드)이거나
    세금계산서 발행 체크(tax=1)면 그 행의 수입(income_cash+income_etc)을 **1회** 반환.
    카드+세금계산서 동시 true여도 중복 없이 1회. 일반 매출에는 그대로 포함되며,
    여기 합계는 순이익에 다시 더하지 않는 '세무 표시용' 별도 집계다."""
    parts = _entry_kid_parts(rec)
    is_card = parts.get("inc", "") == "카드"
    is_tax = str(parts.get("tax", "")).strip() in ("1", "true", "True")
    return _entry_sales(rec) if (is_card or is_tax) else 0


def _ym_to_int(s) -> Optional[int]:
    """'YYYY-MM' → 정렬/비교용 정수(year*12+month). 형식 불량이면 None."""
    s = str(s or "").strip()
    if len(s) < 7:
        return None
    try:
        return int(s[:4]) * 12 + int(s[5:7])
    except Exception:
        return None


def _fixed_amount_for_month(fixed_records: list, y: int, m: int) -> int:
    """선택월(y,m)에 유효한 고정지출 합계.
    - 반복(is_recurring): start_month ≤ 선택월 ≤ end_month(없으면 무기한).
    - 비반복(레거시): year_month == 선택월.
    매월 row 복사 없이 규칙 1건으로 모든 유효월에 자동 반영된다."""
    target = y * 12 + m
    total = 0
    for fx in fixed_records or []:
        amt = _safe_int(fx.get("amount", 0))
        if fx.get("is_recurring"):
            start = _ym_to_int(fx.get("start_month")) or _ym_to_int(fx.get("year_month"))
            end = _ym_to_int(fx.get("end_month"))
            if start is None:
                continue
            if start <= target and (end is None or target <= end):
                total += amt
        else:
            if _ym_to_int(fx.get("year_month")) == target:
                total += amt
    return total


_FIXED_RATIO_WARN = 35.0   # 고정지출 / 매출 경고 임계(%)
_REPORTED_DIFF_WARN = 20.0  # |신고매출 - 일일매출| / 일일매출 경고 임계(%)


def _diagnose(same_month, same_quarter, ytd, category_compare, year, month, quarter,
              tax_cur=None, tax_prev=None) -> dict:
    """전년 동월/동분기/YTD + 업무군 증감 + 고정지출/신고·부가세 기반 자동 진단(만원 표기)."""
    good, bad = [], []

    def find(rows, y):
        return next((r for r in rows if r["year"] == y), None)

    def pct(cur, prev):
        return None if prev == 0 else round((cur - prev) / prev * 100, 1)

    def won(n):
        return f"{round(n / 10000, 1)}만원"

    cm, pm = find(same_month, year), find(same_month, year - 1)
    if cm and pm:
        p = pct(cm["sales"], pm["sales"])
        if p is not None:
            (good if p >= 0 else bad).append(f"전년 동월 대비 매출 {'+' if p >= 0 else ''}{p}%")
        pn = pct(cm["net"], pm["net"])
        if pn is not None:
            (good if pn >= 0 else bad).append(f"전년 동월 대비 순이익 {'+' if pn >= 0 else ''}{pn}%")
        if cm["avg"] and pm["avg"]:
            da = cm["avg"] - pm["avg"]
            (good if da >= 0 else bad).append(f"평균 객단가 {'+' if da >= 0 else ''}{won(da)}")
        if cm["sales"] and pm["sales"]:
            d = round(cm["expense"] / cm["sales"] * 100 - pm["expense"] / pm["sales"] * 100, 1)
            (good if d <= 0 else bad).append(f"지출률 {'+' if d > 0 else ''}{d}%p")

    cq, pq = find(same_quarter, year), find(same_quarter, year - 1)
    if cq and pq:
        p = pct(cq["sales"], pq["sales"])
        if p is not None:
            (good if p >= 0 else bad).append(f"전년 동분기(Q{quarter}) 대비 매출 {'+' if p >= 0 else ''}{p}%")
        pn = pct(cq["net"], pq["net"])
        if pn is not None:
            (good if pn >= 0 else bad).append(f"전년 동분기(Q{quarter}) 대비 순이익 {'+' if pn >= 0 else ''}{pn}%")

    cy, py = find(ytd, year), find(ytd, year - 1)
    if cy and py:
        p = pct(cy["sales"], py["sales"])
        if p is not None:
            (good if p >= 0 else bad).append(f"YTD 누적 매출 {'+' if p >= 0 else ''}{p}%")
        pn = pct(cy["net"], py["net"])
        if pn is not None:
            (good if pn >= 0 else bad).append(f"YTD 누적 순이익 {'+' if pn >= 0 else ''}{pn}%")

    ups = [c for c in category_compare if c["delta"] > 0][:3]
    downs = sorted([c for c in category_compare if c["delta"] < 0], key=lambda x: x["delta"])[:3]
    for c in ups:
        good.append(f"{c['name']} 매출 +{won(c['delta'])}")
    for c in downs:
        bad.append(f"{c['name']} 매출 {won(c['delta'])}")

    # ── 고정지출 / 고정차감후 순이익 (same_month 행에 fixed/net_after_fixed 존재 시) ──
    if cm and pm and ("fixed" in cm):
        # 고정지출률 증감 (전년 동월 대비)
        if cm["sales"] and pm["sales"]:
            cur_rate = cm["fixed"] / cm["sales"] * 100
            prev_rate = pm["fixed"] / pm["sales"] * 100
            d = round(cur_rate - prev_rate, 1)
            (good if d <= 0 else bad).append(f"고정지출률 {'+' if d > 0 else ''}{d}%p")
            # 고정지출이 매출의 일정 비율 초과 경고
            if cur_rate > _FIXED_RATIO_WARN:
                bad.append(f"고정지출이 월 매출의 {round(cur_rate, 1)}% (>{_FIXED_RATIO_WARN:.0f}%)")
        # 고정차감 후 순이익 증감
        pf = pct(cm.get("net_after_fixed", 0), pm.get("net_after_fixed", 0))
        if pf is not None:
            (good if pf >= 0 else bad).append(f"고정차감 후 순이익 {'+' if pf >= 0 else ''}{pf}%")
        # 매출은 늘었지만 고정지출 때문에 실제 순이익이 감소
        sales_up = (cm["sales"] - pm["sales"]) > 0
        naf_down = cm.get("net_after_fixed", 0) - pm.get("net_after_fixed", 0) < 0
        if sales_up and naf_down:
            bad.append("매출은 증가했지만 고정지출 증가로 실제 순이익은 감소했습니다")

    # ── 신고 기준 / 부가세 ──
    if tax_cur:
        # 신고 매출과 일일결산 매출 차이
        if cm and cm["sales"]:
            diff = abs(tax_cur.get("reported_revenue", 0) - cm["sales"]) / cm["sales"] * 100
            if diff > _REPORTED_DIFF_WARN:
                bad.append(f"신고 매출과 일일결산 매출 차이가 큽니다 ({round(diff, 1)}%)")
        if tax_prev:
            pr = pct(tax_cur.get("reported_revenue", 0), tax_prev.get("reported_revenue", 0))
            if pr is not None:
                (good if pr >= 0 else bad).append(f"신고 매출 전년 동월 대비 {'+' if pr >= 0 else ''}{pr}%")
            pv = pct(tax_cur.get("expected_vat_payable", 0), tax_prev.get("expected_vat_payable", 0))
            if pv is not None:
                # 부가세 부담은 감소가 good
                (good if pv <= 0 else bad).append(f"예상 부가세 부담 {'+' if pv > 0 else ''}{pv}%")

    return {"good": good, "bad": bad}


def _build_yearly_overview(records: list, year: int, month: int,
                           fixed_records: Optional[list] = None,
                           pg_daily: bool = False,
                           tax_cur: Optional[dict] = None,
                           tax_prev: Optional[dict] = None) -> dict:
    """연도별 월간추이 overlay + 동월/동분기/YTD 비교 + 카테고리 증감 + 자동진단 (읽기 전용).

    현금출금 카테고리는 매출/건수 집계에서 제외(진행업무 매핑 기준과 동일).
    fixed_records(고정지출, PG 전용)가 주어지면 월별 고정지출/고정차감후 순이익을 반영한다.
    """
    from collections import defaultdict

    by_ym = defaultdict(lambda: {"sales": 0, "expense": 0, "net": 0, "card": 0, "count": 0})
    cat_by_ym: dict = defaultdict(lambda: defaultdict(int))
    years: set = set()

    for r in records:
        date_str = str(r.get("date", "") or "")
        if len(date_str) < 7:
            continue
        try:
            y = int(date_str[:4]); m = int(date_str[5:7])
        except Exception:
            continue
        cat = str(r.get("category", "") or "").strip() or "기타"
        if cat == "현금출금":
            continue
        years.add(y)
        sales = _entry_sales(r)
        expense = _entry_expense(r)
        cell = by_ym[(y, m)]
        cell["sales"] += sales
        cell["expense"] += expense
        cell["net"] += sales - expense
        cell["card"] += _entry_card_expense(r)
        cell["count"] += 1
        cat_by_ym[(y, m)][cat] += sales

    # 고정지출: 반복 규칙(start~end) 기준 — 매월 row 복사 없이 유효월에 자동 반영.
    # 규칙의 start/end 연도도 overlay 표시 대상에 포함시킨다.
    fixed_list = fixed_records or []
    for fx in fixed_list:
        for key in ("start_month", "year_month", "end_month"):
            v = _ym_to_int(fx.get(key))
            if v is not None:
                years.add(v // 12)

    years_sorted = sorted(years)

    def month_cell(y, m):
        c = by_ym.get((y, m))
        base = dict(c) if c else {"sales": 0, "expense": 0, "net": 0, "card": 0, "count": 0}
        base["fixed"] = _fixed_amount_for_month(fixed_list, y, m)
        base["net_after_fixed"] = base["net"] - base["fixed"]
        return base

    def agg_range(y, m_from, m_to):
        s = {"sales": 0, "expense": 0, "net": 0, "card": 0, "fixed": 0, "count": 0}
        for m in range(m_from, m_to + 1):
            c = month_cell(y, m)
            for k in s:
                s[k] += c[k]
        s["net_after_fixed"] = s["net"] - s["fixed"]
        s["avg"] = round(s["sales"] / s["count"]) if s["count"] else 0
        return s

    monthly_by_year = {
        str(y): [{"month": m, **month_cell(y, m)} for m in range(1, 13)]
        for y in years_sorted
    }

    q = (month - 1) // 3 + 1
    q_from, q_to = (q - 1) * 3 + 1, (q - 1) * 3 + 3
    same_month   = [{"year": y, **agg_range(y, month, month)} for y in years_sorted]
    same_quarter = [{"year": y, "quarter": q, **agg_range(y, q_from, q_to)} for y in years_sorted]
    ytd          = [{"year": y, **agg_range(y, 1, month)} for y in years_sorted]

    cur = cat_by_ym.get((year, month), {})
    prev = cat_by_ym.get((year - 1, month), {})
    cat_names = sorted(set(cur) | set(prev))
    category_compare = sorted(
        [{"name": c, "cur": cur.get(c, 0), "prev": prev.get(c, 0),
          "delta": cur.get(c, 0) - prev.get(c, 0)} for c in cat_names],
        key=lambda x: -x["cur"],
    )

    # 세무 자동 신고매출(선택월): 카드수입 + 세금계산서 발행 체크 수입 (행당 1회)
    sel_prefix = f"{year}-{month:02d}"
    auto_reported_sales = sum(
        _entry_reported_sales(r) for r in records
        if str(r.get("date", "")).startswith(sel_prefix)
    )

    return {
        "years": years_sorted,
        "selected": {"year": year, "month": month, "quarter": q},
        "pg_daily": pg_daily,
        "monthly_by_year": monthly_by_year,
        "same_month": same_month,
        "same_quarter": same_quarter,
        "ytd": ytd,
        "category_compare": category_compare,
        "tax": {
            "current": tax_cur or None,
            "prev": tax_prev or None,
            "auto_reported_sales": auto_reported_sales,
        },
        "diagnosis": _diagnose(same_month, same_quarter, ytd, category_compare, year, month, q,
                               tax_cur=tax_cur, tax_prev=tax_prev),
    }


@router.get("/entries")
def get_entries(
    date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    user: dict = Depends(get_current_user),
):
    # PG-only(Phase E): 일일결산 조회는 항상 PostgreSQL.
    from backend.services.daily_pg_service import list_entries
    return list_entries(user["tenant_id"], date=date)


_ACTIVE_HEADER = [
    "id", "category", "date", "name", "work", "details",
    "transfer", "cash", "card", "stamp", "receivable",
    "planned_expense", "processed", "processed_timestamp",
    "reception", "processing", "storage", "customer_id",
    "source_daily_id",
]


# [Phase E] dead Sheets bridge 함수(_append_delegation_to_customer) 제거됨 — PG mirror(_append_delegation_to_customer_pg) 사용.


# [Phase E] dead Sheets dedup helper(_DedupeResult/_dedupe_active_rows_by_source) 제거됨.


# [Phase E] dead Sheets bridge 함수(_apply_daily_to_active) 제거됨 — PG mirror(_apply_daily_to_active_pg) 사용.


# ── PG mirror of daily→active / daily→customer-delegation (PG-only) ─────────────
#
# The Sheets versions above operate on ``read_sheet`` / ``upsert_sheet`` which
# hit Google. In local PG beta these would fail (or, worse, hit a stale Sheets
# response). The PG versions implement the same business rules but talk only
# to PostgreSQL via the existing tenant-aware repository services.


def _apply_daily_to_active_pg(rec: dict, tenant_id: str) -> None:
    """PG mirror of :func:`_apply_daily_to_active`.

    Reads existing ``active_tasks`` rows from PG, decides whether to update an
    existing one (by ``source_daily_id`` or content match) or insert a new row,
    then writes via :func:`tasks_pg_service.upsert_active`. Money deltas are
    accumulated using the same memo-encoded slot rules used in the Sheets
    branch.
    """
    import re as _re
    from backend.services import tasks_pg_service as _tasks
    from backend.services.cache_service import cache_invalidate

    category = str(rec.get("category", "")).strip()
    if category == "현금출금":
        return

    name = str(rec.get("name", "")).strip()
    work = str(rec.get("task", "")).strip()  # daily.task == active.work
    date = str(rec.get("date", "")).strip()
    customer_id = str(rec.get("customer_id", "")).strip()
    source_daily_id = str(rec.get("id", "")).strip()
    active_task_id = ("daily-" + source_daily_id) if source_daily_id else str(uuid.uuid4())

    memo = str(rec.get("memo", "")) or ""
    m = _re.search(r"\[KID\](.*?)\[/KID\]", memo)
    inc_type = e1_type = e2_type = ""
    e1_indiv = e2_indiv = 0
    if m:
        parts = dict(p.split("=", 1) for p in m.group(1).split(";") if "=" in p)
        inc_type = parts.get("inc", "")
        e1_type = parts.get("e1", "")
        e2_type = parts.get("e2", "")
        try:
            e1_indiv = int(parts.get("e1a", "0") or "0")
        except Exception:
            e1_indiv = 0
        try:
            e2_indiv = int(parts.get("e2a", "0") or "0")
        except Exception:
            e2_indiv = 0

    exp_cash = _safe_int(rec.get("exp_cash", 0))
    exp_etc = _safe_int(rec.get("exp_etc", 0))

    delta: dict = {"transfer": 0, "cash": 0, "card": 0, "stamp": 0, "receivable": 0}
    if e1_indiv or e2_indiv:
        for etype, eamt in ((e1_type, e1_indiv), (e2_type, e2_indiv)):
            if not etype or not eamt:
                continue
            if etype == "이체":    delta["transfer"] += eamt
            elif etype == "현금":  delta["cash"]     += eamt
            elif etype == "카드":  delta["card"]     += eamt
            elif etype == "인지":  delta["stamp"]    += eamt
    else:
        non_cash_types = {t for t in (e1_type, e2_type) if t and t != "현금"}
        if len(non_cash_types) == 1:
            t = next(iter(non_cash_types))
            if t == "이체":    delta["transfer"] += exp_etc
            elif t == "카드":  delta["card"]     += exp_etc
            elif t == "인지":  delta["stamp"]    += exp_etc
        if "현금" in (e1_type, e2_type) and exp_cash:
            delta["cash"] += exp_cash

    # Lookup existing active task: source_daily_id first, then content match.
    active_tasks = _tasks.list_active(tenant_id)
    matched = None
    if source_daily_id:
        matched = next(
            (t for t in active_tasks
             if str(t.get("source_daily_id", "")).strip() == source_daily_id),
            None,
        )
    if not matched:
        matched = next(
            (t for t in active_tasks
             if not str(t.get("source_daily_id", "")).strip()
             and t.get("category") == category
             and t.get("date") == date
             and t.get("name") == name
             and t.get("work") == work),
            None,
        )

    if matched:
        # Accumulate money deltas into the matched row, preserve other fields.
        payload = dict(matched)
        for field, dv in delta.items():
            if dv:
                payload[field] = str(_safe_int(payload.get(field, 0)) + dv)
        if customer_id and not str(payload.get("customer_id", "")).strip():
            payload["customer_id"] = customer_id
        if source_daily_id and not str(payload.get("source_daily_id", "")).strip():
            payload["source_daily_id"] = source_daily_id
        _tasks.upsert_active(tenant_id, payload)
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
            "processed":           False,
            "processed_timestamp": "",
            "reception":           datetime.utcnow().isoformat() + "Z",
            "processing":          "",
            "storage":             "",
            "customer_id":         customer_id,
        }
        _tasks.upsert_active(tenant_id, new_task)

    # Clear the active-tasks list cache so the dashboard / tasks page
    # see the new row on their next refetch.
    cache_invalidate(tenant_id, "tasks:active")


def _append_delegation_to_customer_pg(rec: dict, tenant_id: str) -> None:
    """PG mirror of :func:`_append_delegation_to_customer`.

    Uses ``customer_pg_service.append_delegation`` which already implements
    the "append a newline-separated line to the existing 위임내역" behavior.
    Falls back to a Korean-name search when ``customer_id`` is empty (mirrors
    the Sheets-path name fallback).
    """
    from backend.services import customer_pg_service as _cust

    category = str(rec.get("category", "")).strip()
    name = str(rec.get("name", "")).strip()
    customer_id = str(rec.get("customer_id", "")).strip()
    if category == "현금출금" or not name:
        return

    date = str(rec.get("date", "")).strip()
    task = str(rec.get("task", "")).strip()
    memo = str(rec.get("memo", "")) or ""
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

    entry_line = " ".join(parts)
    if amt_parts:
        entry_line += f" ({', '.join(amt_parts)})"
    if user_note:
        entry_line += f" [{user_note}]"
    if not entry_line.strip():
        return

    # Locate the target customer. Prefer explicit customer_id; fall back to
    # the first row matching Korean name in this tenant.
    target_id = customer_id
    if not target_id:
        all_customers = _cust.list_customers(tenant_id)
        matches = [c for c in all_customers if (c.get("한글") or "").strip() == name]
        if len(matches) == 1:
            target_id = matches[0].get("고객ID", "")
    if not target_id:
        return

    _cust.append_delegation(tenant_id, target_id, entry_line)


@router.post("/entries", response_model=dict)
def add_entry(entry: DailyEntry, user: dict = Depends(get_current_user)):
    # PG-only(Phase E): 일일결산 저장 + 파생 진행업무(PG)·고객 위임내역(PG) 반영.
    if not entry.id:
        entry.id = str(uuid.uuid4())
    rec = {k: ("" if v is None else str(v)) for k, v in entry.model_dump().items()}
    from backend.services.daily_pg_service import upsert_entry
    result = upsert_entry(user["tenant_id"], rec)
    try:
        _apply_daily_to_active_pg(rec, user["tenant_id"])
    except Exception as _e:
        print(f"[daily.pg] apply_daily_to_active_pg 실패: {_e}")
    try:
        _append_delegation_to_customer_pg(rec, user["tenant_id"])
    except Exception as _e:
        print(f"[daily.pg] append_delegation_to_customer_pg 실패: {_e}")
    return result


@router.put("/entries/{entry_id}", response_model=dict)
def update_entry(entry_id: str, entry: DailyEntry, user: dict = Depends(get_current_user)):
    # PG-only(Phase E): 수정 + 파생 진행업무(PG) 금액 갱신.
    entry.id = entry_id
    rec = {k: ("" if v is None else str(v)) for k, v in entry.model_dump().items()}
    from backend.services.daily_pg_service import upsert_entry
    result = upsert_entry(user["tenant_id"], rec)
    try:
        _apply_daily_to_active_pg(rec, user["tenant_id"])
    except Exception as _e:
        print(f"[daily.pg] apply_daily_to_active_pg (edit) 실패: {_e}")
    return result


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, user: dict = Depends(get_current_user)):
    # PG-only(Phase E): 삭제 + 파생 진행업무(PG) cascade 삭제.
    from backend.services.daily_pg_service import delete_entry as _pg_del
    from backend.services import tasks_pg_service as _tasks
    from backend.services.cache_service import cache_invalidate
    _pg_del(user["tenant_id"], entry_id)
    try:
        _tasks.delete_active(user["tenant_id"], ["daily-" + entry_id])
        cache_invalidate(user["tenant_id"], "tasks:active")
    except Exception as _e:
        print(f"[daily.pg] cascade delete active failed: {_e}")
    return {"deleted": entry_id}


@router.get("/balance", response_model=BalanceData)
def get_balance(user: dict = Depends(get_current_user)):
    # PG-only(Phase E).
    from backend.services.daily_pg_service import get_balance as _pg_get_bal
    return _pg_get_bal(user["tenant_id"])


@router.post("/balance", response_model=BalanceData)
def save_balance(data: BalanceData, user: dict = Depends(get_current_user)):
    # PG-only(Phase E).
    from backend.services.daily_pg_service import save_balance as _pg_save_bal
    _pg_save_bal(user["tenant_id"], int(data.cash), int(data.profit))
    return data


@router.get("/summary")
def get_monthly_summary(
    year: int = Query(...),
    month: int = Query(...),
    user: dict = Depends(get_current_user),
):
    """월별 수입/지출 합계 — PG-only(Phase E)."""
    from backend.services.daily_pg_service import list_entries
    records = list_entries(user["tenant_id"]) or []

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
    # PG-only(Phase E).
    from backend.services.daily_pg_service import list_entries
    records = list_entries(user["tenant_id"]) or []

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


@router.get("/card-expense-summary")
def get_card_expense_summary(user: dict = Depends(get_current_user)):
    """진행업무 화면용 카드지출 누계 — 오늘 / 이번 달.

    일일결산의 '카드' 결제수단 지출 합계(읽기 전용). 진행업무 active_task.card 와 동일한
    원천(일일결산 카드지출)을 날짜 기준으로 집계한다. 단일 API → 프론트 중복계산 방지.
    """
    import datetime
    records = _fetch_daily_records(user["tenant_id"])
    today = datetime.date.today()
    today_str = today.isoformat()
    month_prefix = today.strftime("%Y-%m")
    today_total = sum(_entry_card_expense(r) for r in records
                      if str(r.get("date", "")).strip() == today_str)
    month_total = sum(_entry_card_expense(r) for r in records
                      if str(r.get("date", "")).startswith(month_prefix))
    return {
        "today": today_total,
        "month": month_total,
        "today_date": today_str,
        "month_prefix": month_prefix,
    }


@router.get("/income-summary")
def get_income_summary(user: dict = Depends(get_current_user)):
    """진행업무/업무관리 화면용 '수입 합계' — 오늘 / 이번 달.

    daily_entries 의 수입(income_cash + income_etc) 합계. 카드수입도 income_etc 로
    자연 포함된다. active_task 와 무관한 일일결산 기준 집계(읽기 전용). 단일 API.
    """
    import datetime
    records = _fetch_daily_records(user["tenant_id"])
    today = datetime.date.today()
    today_str = today.isoformat()
    month_prefix = today.strftime("%Y-%m")
    today_total = sum(_entry_sales(r) for r in records
                      if str(r.get("date", "")).strip() == today_str)
    month_total = sum(_entry_sales(r) for r in records
                      if str(r.get("date", "")).startswith(month_prefix))
    return {
        "today": today_total,
        "month": month_total,
        "today_date": today_str,
        "month_prefix": month_prefix,
    }


@router.get("/yearly-overview")
def get_yearly_overview(
    year: int = Query(...),
    month: int = Query(...),
    user: dict = Depends(get_current_user),
):
    """월간결산 고도화 — 연도별 월간추이 overlay + 동월/동분기/YTD 비교 + 카테고리 증감 + 자동진단.

    PG-only(Phase E): 고정지출(fixed_expenses)·신고/부가세(monthly_tax_summaries)도 PG에서
    읽어 고정차감후 순이익·세무 진단까지 반영한다.
    """
    tenant_id = user["tenant_id"]
    records = _fetch_daily_records(tenant_id)

    pg = True  # PG-only
    from backend.services.fixed_expense_pg_service import list_fixed_expenses
    from backend.services.monthly_tax_pg_service import get_tax_summary
    fixed_records = list_fixed_expenses(tenant_id) or []
    tax_cur = get_tax_summary(tenant_id, f"{year}-{month:02d}")
    tax_prev = get_tax_summary(tenant_id, f"{year - 1}-{month:02d}")

    return _build_yearly_overview(records, year, month, fixed_records=fixed_records,
                                  pg_daily=pg, tax_cur=tax_cur, tax_prev=tax_prev)


# ── 고정지출 / 신고·부가세 (PostgreSQL 전용 — FEATURE_PG_DAILY) ────────────────

def _require_pg_daily():
    # PG-only(Phase E): PostgreSQL 구성 필수. 미구성 시 503(조용한 Sheets fallback 없음).
    from backend.db.session import is_configured
    if not is_configured():
        raise HTTPException(
            status_code=503,
            detail="고정지출/신고 기능은 PostgreSQL 설정이 필요합니다. 관리자에게 문의하세요.",
        )


@router.get("/fixed-expenses")
def list_fixed_expenses_ep(
    effective_month: Optional[str] = Query(None, description="YYYY-MM (해당 월 유효 규칙)"),
    year_month: Optional[str] = Query(None, description="YYYY-MM"),
    year: Optional[str] = Query(None, description="YYYY"),
    user: dict = Depends(get_current_user),
):
    _require_pg_daily()
    from backend.services.fixed_expense_pg_service import list_fixed_expenses
    return list_fixed_expenses(user["tenant_id"], year_month=year_month, year=year,
                               effective_month=effective_month)


@router.post("/fixed-expenses")
def create_fixed_expense_ep(data: dict, user: dict = Depends(get_current_user)):
    """고정지출 신규 — 기본은 매월 자동 반영(반복) 규칙. start_month=선택월부터 무기한(end 없음)."""
    _require_pg_daily()
    ym = str(data.get("year_month", "")).strip()
    if not ym:
        raise HTTPException(status_code=400, detail="year_month는 필수입니다.")
    if not str(data.get("start_month", "")).strip():
        data["start_month"] = ym
    if "is_recurring" not in data:
        data["is_recurring"] = True
    from backend.services.fixed_expense_pg_service import upsert_fixed_expense
    return upsert_fixed_expense(user["tenant_id"], data)


@router.put("/fixed-expenses/{expense_id}")
def update_fixed_expense_ep(expense_id: str, data: dict, user: dict = Depends(get_current_user)):
    """선택월(data.year_month) 기준 수정. 금액 변경 시 term-out(과거 월 금액 보존)."""
    _require_pg_daily()
    eff = str(data.get("year_month", "")).strip()
    if not eff:
        raise HTTPException(status_code=400, detail="year_month(선택월)는 필수입니다.")
    from backend.services.fixed_expense_pg_service import update_fixed_expense
    try:
        return update_fixed_expense(user["tenant_id"], expense_id, data, eff)
    except ValueError:
        raise HTTPException(status_code=404, detail="해당 고정지출을 찾을 수 없습니다.")


@router.delete("/fixed-expenses/{expense_id}")
def delete_fixed_expense_ep(
    expense_id: str,
    effective_month: Optional[str] = Query(None, description="YYYY-MM (이 달부터 중단)"),
    user: dict = Depends(get_current_user),
):
    """effective_month 지정 시 그 달부터 중단(과거 보존), 없으면 행 완전 삭제."""
    _require_pg_daily()
    if effective_month:
        from backend.services.fixed_expense_pg_service import end_fixed_expense
        return end_fixed_expense(user["tenant_id"], expense_id, effective_month)
    from backend.services.fixed_expense_pg_service import delete_fixed_expense
    ok = delete_fixed_expense(user["tenant_id"], expense_id)
    return {"deleted": expense_id, "ok": ok}


@router.post("/fixed-expenses/copy")
def copy_fixed_expenses_ep(
    from_ym: str = Query(..., description="복사 원본 YYYY-MM"),
    to_ym: str = Query(..., description="복사 대상 YYYY-MM"),
    user: dict = Depends(get_current_user),
):
    _require_pg_daily()
    from backend.services.fixed_expense_pg_service import copy_fixed_expenses
    n = copy_fixed_expenses(user["tenant_id"], from_ym, to_ym)
    return {"copied": n, "from": from_ym, "to": to_ym}


@router.get("/tax-summary")
def get_tax_summary_ep(
    year_month: str = Query(..., description="YYYY-MM"),
    user: dict = Depends(get_current_user),
):
    _require_pg_daily()
    from backend.services.monthly_tax_pg_service import get_tax_summary
    return get_tax_summary(user["tenant_id"], year_month) or {}


@router.put("/tax-summary")
def upsert_tax_summary_ep(data: dict, user: dict = Depends(get_current_user)):
    _require_pg_daily()
    if not str(data.get("year_month", "")).strip():
        raise HTTPException(status_code=400, detail="year_month는 필수입니다.")
    from backend.services.monthly_tax_pg_service import upsert_tax_summary
    return upsert_tax_summary(user["tenant_id"], data)
