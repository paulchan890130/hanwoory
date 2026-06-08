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
    """일일결산 레코드 조회 — FEATURE_PG_DAILY 분기(저장과 동일 저장소). 읽기 전용."""
    from backend.db.feature_flags import pg_daily_enabled
    if pg_daily_enabled():
        from backend.services.daily_pg_service import list_entries
        return list_entries(tenant_id) or []
    from config import DAILY_SUMMARY_SHEET_NAME
    return read_sheet(DAILY_SUMMARY_SHEET_NAME, tenant_id, default_if_empty=[]) or []


def _entry_sales(rec: dict) -> int:
    return _safe_int(rec.get("income_cash")) + _safe_int(rec.get("income_etc"))


def _entry_expense(rec: dict) -> int:
    return _safe_int(rec.get("exp_cash")) + _safe_int(rec.get("exp_etc"))


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

    # 고정지출 월별 합계 (year_month "YYYY-MM" → 합계)
    fixed_by_ym: dict = defaultdict(int)
    for fx in (fixed_records or []):
        ym = str(fx.get("year_month", "") or "")
        if len(ym) < 7:
            continue
        try:
            fy = int(ym[:4]); fm = int(ym[5:7])
        except Exception:
            continue
        years.add(fy)
        fixed_by_ym[(fy, fm)] += _safe_int(fx.get("amount", 0))

    years_sorted = sorted(years)

    def month_cell(y, m):
        c = by_ym.get((y, m))
        base = dict(c) if c else {"sales": 0, "expense": 0, "net": 0, "card": 0, "count": 0}
        base["fixed"] = fixed_by_ym.get((y, m), 0)
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

    return {
        "years": years_sorted,
        "selected": {"year": year, "month": month, "quarter": q},
        "pg_daily": pg_daily,
        "monthly_by_year": monthly_by_year,
        "same_month": same_month,
        "same_quarter": same_quarter,
        "ytd": ytd,
        "category_compare": category_compare,
        "tax": {"current": tax_cur or None, "prev": tax_prev or None},
        "diagnosis": _diagnose(same_month, same_quarter, ytd, category_compare, year, month, q,
                               tax_cur=tax_cur, tax_prev=tax_prev),
    }


@router.get("/entries")
def get_entries(
    date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    user: dict = Depends(get_current_user),
):
    from backend.db.feature_flags import pg_daily_enabled
    if pg_daily_enabled():
        from backend.services.daily_pg_service import list_entries
        return list_entries(user["tenant_id"], date=date)

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


# ── PG-mode equivalents of _apply_daily_to_active / _append_delegation_to_customer ─
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
    from backend.db.feature_flags import pg_daily_enabled
    from config import DAILY_SUMMARY_SHEET_NAME
    if not entry.id:
        entry.id = str(uuid.uuid4())
    rec = {k: ("" if v is None else str(v)) for k, v in entry.model_dump().items()}

    if pg_daily_enabled():
        from backend.services.daily_pg_service import upsert_entry
        result = upsert_entry(user["tenant_id"], rec)
        # PG path: also propagate to active tasks + customer delegation,
        # mirroring the Sheets path. Each side-effect is best-effort so
        # the primary daily-entry save is reported as success.
        try:
            _apply_daily_to_active_pg(rec, user["tenant_id"])
        except Exception as _e:
            print(f"[daily.pg] apply_daily_to_active_pg 실패: {_e}")
        try:
            _append_delegation_to_customer_pg(rec, user["tenant_id"])
        except Exception as _e:
            print(f"[daily.pg] append_delegation_to_customer_pg 실패: {_e}")
        return result

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
    from backend.db.feature_flags import pg_daily_enabled
    from config import DAILY_SUMMARY_SHEET_NAME
    entry.id = entry_id
    rec = {k: ("" if v is None else str(v)) for k, v in entry.model_dump().items()}

    if pg_daily_enabled():
        from backend.services.daily_pg_service import upsert_entry
        result = upsert_entry(user["tenant_id"], rec)
        # Edits also need to refresh the derived active-task row so the
        # dashboard / task page reflect the latest amounts.
        try:
            _apply_daily_to_active_pg(rec, user["tenant_id"])
        except Exception as _e:
            print(f"[daily.pg] apply_daily_to_active_pg (edit) 실패: {_e}")
        return result

    upsert_sheet(DAILY_SUMMARY_SHEET_NAME, user["tenant_id"], DAILY_HEADER, [rec], id_field="id")
    return rec


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, user: dict = Depends(get_current_user)):
    from backend.db.feature_flags import pg_daily_enabled
    from config import DAILY_SUMMARY_SHEET_NAME

    if pg_daily_enabled():
        from backend.services.daily_pg_service import delete_entry as _pg_del
        from backend.services import tasks_pg_service as _tasks
        from backend.services.cache_service import cache_invalidate
        _pg_del(user["tenant_id"], entry_id)
        # Cascade: drop the derived active-task row keyed by source_daily_id,
        # so the dashboard / task page no longer show a stale entry. This
        # mirrors the Sheets path's behavior of deleting the matching row.
        try:
            derived_id = "daily-" + entry_id
            _tasks.delete_active(user["tenant_id"], [derived_id])
            cache_invalidate(user["tenant_id"], "tasks:active")
        except Exception as _e:
            print(f"[daily.pg] cascade delete active failed: {_e}")
        return {"deleted": entry_id}

    delete_from_sheet(DAILY_SUMMARY_SHEET_NAME, user["tenant_id"], [entry_id], id_field="id")
    return {"deleted": entry_id}


@router.get("/balance", response_model=BalanceData)
def get_balance(user: dict = Depends(get_current_user)):
    from backend.db.feature_flags import pg_daily_enabled
    from config import DAILY_BALANCE_SHEET_NAME

    if pg_daily_enabled():
        from backend.services.daily_pg_service import get_balance as _pg_get_bal
        return _pg_get_bal(user["tenant_id"])

    records = read_sheet(DAILY_BALANCE_SHEET_NAME, user["tenant_id"], default_if_empty=[])
    balance = {"cash": 0, "profit": 0}
    for r in records:
        k = r.get("key")
        if k in balance:
            balance[k] = _safe_int(r.get("value", 0))
    return balance


@router.post("/balance", response_model=BalanceData)
def save_balance(data: BalanceData, user: dict = Depends(get_current_user)):
    from backend.db.feature_flags import pg_daily_enabled
    from config import DAILY_BALANCE_SHEET_NAME
    tenant_id = user["tenant_id"]

    if pg_daily_enabled():
        from backend.services.daily_pg_service import save_balance as _pg_save_bal
        _pg_save_bal(tenant_id, int(data.cash), int(data.profit))
        return data

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
    from backend.db.feature_flags import pg_daily_enabled
    from config import DAILY_SUMMARY_SHEET_NAME

    if pg_daily_enabled():
        from backend.services.daily_pg_service import list_entries
        records = list_entries(user["tenant_id"]) or []
    else:
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
    from backend.db.feature_flags import pg_daily_enabled
    from config import DAILY_SUMMARY_SHEET_NAME

    if pg_daily_enabled():
        from backend.services.daily_pg_service import list_entries
        records = list_entries(user["tenant_id"]) or []
    else:
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


@router.get("/yearly-overview")
def get_yearly_overview(
    year: int = Query(...),
    month: int = Query(...),
    user: dict = Depends(get_current_user),
):
    """월간결산 고도화 — 연도별 월간추이 overlay + 동월/동분기/YTD 비교 + 카테고리 증감 + 자동진단.

    FEATURE_PG_DAILY on이면 고정지출(fixed_expenses)·신고/부가세(monthly_tax_summaries)도
    PG에서 읽어 고정차감후 순이익·세무 진단까지 반영한다. off면 일일 기준만(PG 전용 섹션 비표시).
    """
    from backend.db.feature_flags import pg_daily_enabled
    tenant_id = user["tenant_id"]
    records = _fetch_daily_records(tenant_id)

    pg = pg_daily_enabled()
    fixed_records = None
    tax_cur = tax_prev = None
    if pg:
        from backend.services.fixed_expense_pg_service import list_fixed_expenses
        from backend.services.monthly_tax_pg_service import get_tax_summary
        fixed_records = list_fixed_expenses(tenant_id) or []
        tax_cur = get_tax_summary(tenant_id, f"{year}-{month:02d}")
        tax_prev = get_tax_summary(tenant_id, f"{year - 1}-{month:02d}")

    return _build_yearly_overview(records, year, month, fixed_records=fixed_records,
                                  pg_daily=pg, tax_cur=tax_cur, tax_prev=tax_prev)


# ── 고정지출 / 신고·부가세 (PostgreSQL 전용 — FEATURE_PG_DAILY) ────────────────

def _require_pg_daily():
    from backend.db.feature_flags import pg_daily_enabled
    if not pg_daily_enabled():
        raise HTTPException(
            status_code=409,
            detail="고정지출/신고 기능은 PG 모드(FEATURE_PG_DAILY=true)에서만 사용할 수 있습니다.",
        )


@router.get("/fixed-expenses")
def list_fixed_expenses_ep(
    year_month: Optional[str] = Query(None, description="YYYY-MM"),
    year: Optional[str] = Query(None, description="YYYY"),
    user: dict = Depends(get_current_user),
):
    _require_pg_daily()
    from backend.services.fixed_expense_pg_service import list_fixed_expenses
    return list_fixed_expenses(user["tenant_id"], year_month=year_month, year=year)


@router.post("/fixed-expenses")
def create_fixed_expense_ep(data: dict, user: dict = Depends(get_current_user)):
    _require_pg_daily()
    if not str(data.get("year_month", "")).strip():
        raise HTTPException(status_code=400, detail="year_month는 필수입니다.")
    from backend.services.fixed_expense_pg_service import upsert_fixed_expense
    return upsert_fixed_expense(user["tenant_id"], data)


@router.put("/fixed-expenses/{expense_id}")
def update_fixed_expense_ep(expense_id: str, data: dict, user: dict = Depends(get_current_user)):
    _require_pg_daily()
    data["id"] = expense_id
    from backend.services.fixed_expense_pg_service import upsert_fixed_expense
    return upsert_fixed_expense(user["tenant_id"], data)


@router.delete("/fixed-expenses/{expense_id}")
def delete_fixed_expense_ep(expense_id: str, user: dict = Depends(get_current_user)):
    _require_pg_daily()
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
