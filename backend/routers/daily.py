"""일일결산 라우터 (테넌트 인식)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uuid
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException

from backend.auth import get_current_user
from backend.models import DailyEntry, BalanceData
# PG-only(Phase E): tenant_service I/O import 제거.

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
    """일일결산 레코드 조회 — PG-only(Phase E)."""
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


def _is_card_income_method(v) -> bool:
    """수입 결제수단이 '카드' 류인지 판정. 입력 UI(INCOME_METHODS)는 '카드'만
    저장하지만, 표기 변형(신용카드/체크카드/영문 card)도 방어적으로 인식한다.
    공백/대소문자 무시. 지출(e1/e2)이 아니라 수입 결제수단(inc)에만 적용한다."""
    s = str(v or "").strip().lower()
    if not s:
        return False
    return ("카드" in s) or (s in ("card", "creditcard", "credit card", "debitcard"))


def _entry_card_income(rec: dict) -> int:
    """일일결산 1건의 '카드' 수입 금액(원). 수입 결제수단이 카드인 행의
    수입(income_cash+income_etc)을 반환, 아니면 0. 월간결산 '자동 카드매출' 합산용.
    읽기 전용 — 일일결산 데이터 구조를 변경하지 않는다."""
    return _entry_sales(rec) if _is_card_income_method(_entry_kid_parts(rec).get("inc", "")) else 0


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

    # 세무 자동 신고매출(선택월): 카드수입 + 세금계산서 발행 체크 수입 (행당 1회, 레거시 호환)
    sel_prefix = f"{year}-{month:02d}"
    auto_reported_sales = sum(
        _entry_reported_sales(r) for r in records
        if str(r.get("date", "")).startswith(sel_prefix)
    )
    # 자동 카드매출(선택월): 결제수단이 카드인 수입 합계 + 건수 (신고/부가세 단순화 기준)
    auto_card_sales = sum(
        _entry_card_income(r) for r in records
        if str(r.get("date", "")).startswith(sel_prefix)
    )
    auto_card_count = sum(
        1 for r in records
        if str(r.get("date", "")).startswith(sel_prefix) and _entry_card_income(r) > 0
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
            "auto_card_sales": auto_card_sales,
            "auto_card_count": auto_card_count,
        },
        "diagnosis": _diagnose(same_month, same_quarter, ytd, category_compare, year, month, q,
                               tax_cur=tax_cur, tax_prev=tax_prev),
    }


# ── 기준일까지 누계 비교 / 일별·시간대 분석 (요구사항 1·3·5·6) ──────────────────
import calendar as _calendar

# 시간대 버킷 (1~2시간 단위, 권장 기본값). lo ≤ hh < hi.
_HOUR_BUCKETS = [
    ("09~11", 9, 11), ("11~13", 11, 13), ("13~15", 13, 15),
    ("15~17", 15, 17), ("17~19", 17, 19),
]
_HOUR_ETC = "기타/시간미상"


def _days_in_month(y: int, m: int) -> int:
    """해당 연·월의 마지막 일(윤년/2월/30·31일 안전)."""
    return _calendar.monthrange(y, m)[1]


def _won(n: int) -> str:
    """만원 단위 표기(자동 분석 문구용). 음수는 부호 유지."""
    return f"{round(n / 10000):,}만원"


def _analyze_period(period: dict, hour_compare: list, category_compare: list,
                    tax_cur: Optional[dict] = None) -> dict:
    """기준일까지 누계(period) + 시간대 + 업무군 기반 자동 분석(장점/부족/대응).

    - 전년 동월 동일기간 데이터가 없으면 전년 비교를 생략하고 현재월 내부 지표만 안내.
    - 과장 금지, 데이터 부족 시 명시.
    """
    good: list = []
    bad: list = []
    actions: list = []
    cur, prev = period["cur"], period["prev"]

    def pct(c, p):
        return None if not p else round((c - p) / abs(p) * 100, 1)

    if period["is_future"]:
        actions.append("아직 시작되지 않은 월입니다. 분석할 데이터가 없습니다.")
        return {"good": good, "bad": bad, "actions": actions}

    if cur["count"] == 0:
        bad.append("데이터 부족: 이번 기간 결산 데이터가 없습니다.")

    has_prev = bool(prev["sales"] or prev["count"])
    if has_prev and cur["count"]:
        ps = pct(cur["sales"], prev["sales"])
        if ps is not None:
            (good if ps >= 0 else bad).append(
                f"이번 기간 누계 매출은 전년 동월 동일기간 대비 {'+' if ps >= 0 else ''}{ps}% "
                f"({_won(abs(cur['sales'] - prev['sales']))}) {'증가' if ps >= 0 else '감소'}했습니다."
            )
        pn = pct(cur["net"], prev["net"])
        if pn is not None:
            (good if pn >= 0 else bad).append(
                f"이번 기간 누계 순수익은 전년 동월 동일기간 대비 "
                f"{'+' if pn >= 0 else ''}{pn}% {'증가' if pn >= 0 else '감소'}했습니다."
            )
        cur_rate = cur["net"] / cur["sales"] * 100 if cur["sales"] else 0
        prev_rate = prev["net"] / prev["sales"] * 100 if prev["sales"] else 0
        if ps is not None and ps > 0 and round(cur_rate - prev_rate, 1) < 0:
            bad.append("매출은 증가했으나 지출 증가율이 더 높아 순수익률이 하락했습니다.")
        # 시간대 약점(전년 대비 20% 이상 감소)
        for h in hour_compare:
            if h["prev_sales"] > 0:
                hp = pct(h["cur_sales"], h["prev_sales"])
                if hp is not None and hp <= -20:
                    bad.append(f"{h['bucket']} 시간대 매출이 전년 대비 {hp}% 감소했습니다.")
        # 업무군 하락(상위 2개)
        downs = sorted([c for c in category_compare if c["delta"] < 0],
                       key=lambda x: x["delta"])[:2]
        for c in downs:
            bad.append(
                f"{c['name']} 매출이 전년 동월 대비 {_won(abs(c['delta']))} 감소했습니다. "
                f"해당 업무 유입을 점검하십시오."
            )
        ups = sorted([c for c in category_compare if c["delta"] > 0],
                     key=lambda x: -x["delta"])[:2]
        for c in ups:
            good.append(f"{c['name']} 매출이 전년 동월 대비 {_won(c['delta'])} 증가했습니다.")
    elif cur["count"]:
        actions.append("전년 동월 데이터가 없어 전년 비교 대신 현재월 내부 지표만 표시합니다.")

    # 월말 예상(진행 중인 월에서만 의미)
    if period["is_current_month"] and cur["count"]:
        actions.append(
            f"현재 일평균 기준 월말 예상 순수익은 약 {_won(period['projected_net'])}입니다."
        )
        actions.append(f"월말 예상 매출은 약 {_won(period['projected_sales'])}입니다.")

    # 현재기간 강한 시간대 요약
    valid = [h for h in hour_compare if h["bucket"] != _HOUR_ETC and h["cur_sales"] > 0]
    if valid:
        top = max(valid, key=lambda h: h["cur_sales"])
        good.append(f"이번 기간 매출이 가장 높은 시간대는 {top['bucket']}입니다.")

    return {"good": good, "bad": bad, "actions": actions}


def _build_period_analysis(records: list, year: int, month: int, today,
                           category_compare: list,
                           tax_cur: Optional[dict] = None) -> dict:
    """선택월 기준일까지의 누계 비교 + 일별 추이(작년 동월 겹쳐보기) + 시간대별 비교 + 자동 분석.

    기준일 규칙:
    - 진행 중인 월(=오늘이 속한 월): 기준일 = 오늘 day.
    - 과거 완료 월: 기준일 = 해당월 말일.
    - 미래 월: 데이터 없음(말일 기준, 분석 생략).
    전년 동월 비교 구간은 같은 day까지로 자르되, 전년 해당월에 그 day가 없으면 말일로 보정.
    현금출금 카테고리는 매출/순수익/건수에서 제외(cash_out 미반영). 읽기 전용.
    """
    from collections import defaultdict

    dim = _days_in_month(year, month)
    is_current = (year == today.year and month == today.month)
    is_future = (year > today.year) or (year == today.year and month > today.month)
    ref_day = min(today.day, dim) if is_current else dim
    prev_dim = _days_in_month(year - 1, month)
    prev_ref_day = min(ref_day, prev_dim)  # 윤년/말일 보정

    def daily_map(y: int, m: int) -> dict:
        dmap: dict = defaultdict(lambda: {"sales": 0, "net": 0, "count": 0})
        for r in records:
            ds = str(r.get("date", "") or "")
            if len(ds) < 10:
                continue
            try:
                ry, rm, rd = int(ds[:4]), int(ds[5:7]), int(ds[8:10])
            except Exception:
                continue
            if ry != y or rm != m:
                continue
            cat = str(r.get("category", "") or "").strip() or "기타"
            if cat == "현금출금":
                continue
            sales = _entry_sales(r)
            cell = dmap[rd]
            cell["sales"] += sales
            cell["net"] += sales - _entry_expense(r)
            cell["count"] += 1
        return dmap

    cur_dm = daily_map(year, month)
    prev_dm = daily_map(year - 1, month)

    def agg(dmap: dict, day_limit: int) -> dict:
        s = {"sales": 0, "net": 0, "count": 0}
        for d, v in dmap.items():
            if d <= day_limit:
                s["sales"] += v["sales"]
                s["net"] += v["net"]
                s["count"] += v["count"]
        return s

    cur_p = agg(cur_dm, ref_day)
    prev_p = agg(prev_dm, prev_ref_day)

    # 일별 추이(1~말일) — 올해 vs 전년 동월, 일별 + 누계. 진행 중 월은 오늘 이후를 미래로 표시.
    daily_series = []
    cum_cs = cum_cn = cum_ps = cum_pn = 0
    for d in range(1, dim + 1):
        c = cur_dm.get(d)
        p = prev_dm.get(d) if d <= prev_dim else None
        future = d > ref_day
        cs = (c["sales"] if c else 0) if not future else 0
        cn = (c["net"] if c else 0) if not future else 0
        ps = p["sales"] if p else 0
        pn = p["net"] if p else 0
        cum_cs += cs
        cum_cn += cn
        cum_ps += ps
        cum_pn += pn
        daily_series.append({
            "day": d,
            "cur_sales": cs, "cur_net": cn,
            "prev_sales": ps, "prev_net": pn,
            "cur_cum_sales": None if future else cum_cs,
            "cur_cum_net": None if future else cum_cn,
            "prev_cum_sales": cum_ps, "prev_cum_net": cum_pn,
            "is_future": future,
        })

    # 시간대별 비교(현재기간 vs 전년 동월 동일기간)
    def hour_agg(y: int, m: int, day_limit: int) -> dict:
        buckets = {name: {"sales": 0, "net": 0, "count": 0} for name, _, _ in _HOUR_BUCKETS}
        buckets[_HOUR_ETC] = {"sales": 0, "net": 0, "count": 0}
        for r in records:
            ds = str(r.get("date", "") or "")
            if len(ds) < 10:
                continue
            try:
                ry, rm, rd = int(ds[:4]), int(ds[5:7]), int(ds[8:10])
            except Exception:
                continue
            if ry != y or rm != m or rd > day_limit:
                continue
            cat = str(r.get("category", "") or "").strip() or "기타"
            if cat == "현금출금":
                continue
            sales = _entry_sales(r)
            net = sales - _entry_expense(r)
            ts = str(r.get("time", "") or "").strip()
            label = _HOUR_ETC
            if ts:
                try:
                    hh = int(ts.split(":")[0])
                    for name, lo, hi in _HOUR_BUCKETS:
                        if lo <= hh < hi:
                            label = name
                            break
                except Exception:
                    label = _HOUR_ETC
            b = buckets[label]
            b["sales"] += sales
            b["net"] += net
            b["count"] += 1
        return buckets

    ch = hour_agg(year, month, ref_day)
    ph = hour_agg(year - 1, month, prev_ref_day)
    order = [n for n, _, _ in _HOUR_BUCKETS] + [_HOUR_ETC]
    hour_compare = [{
        "bucket": n,
        "cur_sales": ch[n]["sales"], "cur_net": ch[n]["net"], "cur_count": ch[n]["count"],
        "prev_sales": ph[n]["sales"], "prev_net": ph[n]["net"], "prev_count": ph[n]["count"],
    } for n in order]

    period = {
        "ref_day": ref_day,
        "prev_ref_day": prev_ref_day,
        "days_in_month": dim,
        "is_current_month": is_current,
        "is_future": is_future,
        "cur": {"sales": cur_p["sales"], "net": cur_p["net"], "count": cur_p["count"],
                "expense": cur_p["sales"] - cur_p["net"]},
        "prev": {"sales": prev_p["sales"], "net": prev_p["net"], "count": prev_p["count"],
                 "expense": prev_p["sales"] - prev_p["net"]},
        "avg_daily_sales": round(cur_p["sales"] / ref_day) if ref_day else 0,
        "avg_daily_net": round(cur_p["net"] / ref_day) if ref_day else 0,
        "projected_sales": round(cur_p["sales"] / ref_day * dim) if ref_day else 0,
        "projected_net": round(cur_p["net"] / ref_day * dim) if ref_day else 0,
    }

    return {
        "period": period,
        "daily_series": daily_series,
        "hour_compare": hour_compare,
        "analysis": _analyze_period(period, hour_compare, category_compare, tax_cur),
    }


# ── 업무군별 경영 진단 보고서 (business_insights) ──────────────────────────────
# 신규 입력은 프론트 구분_옵션과 동일한 표준 버킷이지만, 과거/레거시 데이터에는
# "영주"(권 없음)·"체류"·"연장"·"공인증"·"전자" 등 자유 입력값이 섞일 수 있어
# normalize_business_category()로 표준 7종에 정규화한다(현금출금은 호출 전 제외).
_BIZ_CATEGORIES = ["출입국", "전자민원", "공증", "여권", "초청", "영주권", "기타"]
_LOW_VOLUME_CATS = {"여권", "초청", "영주권", "기타"}  # 건수 적으면 추세 판단 제한 문구
_LOW_VOLUME_N = 3

# 키워드 정규화 매핑(부분 일치). 우선순위 순서가 중요하다:
# 영주권(F-5 최우선) → 전자민원 → 공증 → 여권 → 초청 → 출입국 → 기타.
# F-5는 영주권, 그 외 체류자격 코드(F-1~F-4/F-6/H-2/E-7/D-2/D-4/D-8/D-10)는 출입국.
_PERMANENT_CODES = ("F-5",)
_IMMIG_CODES = ("F-1", "F-2", "F-3", "F-4", "F-6", "H-2", "E-7", "D-2", "D-4", "D-8", "D-10")
_KW_PERMANENT = ("영주권", "영주신청", "영주자격", "영주")   # "영주"가 "영주권"·"영주자격"도 포함
_KW_PERMANENT_EN = ("permanent residence",)
_KW_EMINWON   = ("전자민원", "온라인민원", "민원24", "정부24", "전자", "온라인")
_KW_GONGJEUNG = ("중국공증", "번역공증", "미재혼공증", "미혼공증", "공증", "공인증", "아포스티유", "인증")
_KW_PASSPORT  = ("여권연장", "여권신청", "여권")
_KW_INVITE    = ("사증초청", "초청장", "초청")
_KW_IMMIG     = ("출입국", "체류", "사증", "등록사항", "등록", "연장", "변경", "부여", "신고", "주소")

_CLEAR_BUCKETS = ("전자민원", "공증", "여권", "초청", "영주권")  # 명확 → aux로 덮어쓰지 않음


def _classify_category_text(text) -> str:
    """문자열 하나를 표준 업무군으로 분류(부분 일치, 우선순위).
    영주권(F-5 최우선) → 전자민원 → 공증 → 여권 → 초청 → 출입국 → 기타.
    매칭 실패/빈 값 → '기타'.
    """
    c = str(text or "").strip()
    if not c:
        return "기타"
    s = c.upper().replace(" ", "")     # 코드 비교: 공백 제거 + 대문자 + 하이픈 유무 허용
    cl = c.lower()                      # 영문 키워드 비교

    def has_code(codes) -> bool:
        for code in codes:
            if code in s or code.replace("-", "") in s:
                return True
        return False

    if (has_code(_PERMANENT_CODES) or any(k in c for k in _KW_PERMANENT)
            or any(k in cl for k in _KW_PERMANENT_EN)):
        return "영주권"
    if any(k in c for k in _KW_EMINWON):
        return "전자민원"
    if any(k in c for k in _KW_GONGJEUNG):
        return "공증"
    if any(k in c for k in _KW_PASSPORT):
        return "여권"
    if any(k in c for k in _KW_INVITE):
        return "초청"
    if has_code(_IMMIG_CODES) or any(k in c for k in _KW_IMMIG):
        return "출입국"
    return "기타"


def normalize_business_category(category, aux="") -> str:
    """원본 category(+보조 task/work/details)를 표준 업무군 7종으로 정규화.

    정책(확정):
    - category가 전자민원/공증/여권/초청/영주권으로 명확하면 그대로(aux로 덮어쓰지 않음).
    - category가 '출입국'이면, aux에 강한 영주권 신호(영주/영주권/F-5/F5/영주자격/
      permanent residence)가 있을 때만 '영주권', 아니면 '출입국' 유지.
    - category가 기타/빈값/미매핑이면 aux로 전체 fallback 분류(매칭 없으면 '기타').
    원본 저장값은 변경하지 않으며 business_insights 분석 분류에만 사용한다.
    현금출금은 호출부에서 별도 제외.
    """
    base = _classify_category_text(category)
    if base in _CLEAR_BUCKETS:
        return base
    aux_cat = _classify_category_text(aux)
    if base == "출입국":
        return "영주권" if aux_cat == "영주권" else "출입국"
    # base == "기타" (category 기타/빈값/미매핑) → aux 전체 fallback
    return aux_cat

# 업무군 성격(통제가능성/외부 위험요인) — 데이터 주장이 아닌 도메인 정의.
_CAT_PROFILE = {
    "출입국":   {"controllability": "낮음 (제도·매뉴얼 영향 큼)",
                "risk_factors": ["하이코리아 매뉴얼 변경", "체류자격별 심사 강화/완화", "계절성 신청 수요", "특정 체류자격 이슈"]},
    "전자민원": {"controllability": "높음 (내부 처리·응대 통제 가능)",
                "risk_factors": ["처리 속도", "안내문/가격표", "반복업무 자동화", "SNS 유입", "응대 스크립트"]},
    "공증":     {"controllability": "중간 (외부 요인 영향 큼)",
                "risk_factors": ["중국 현지 정책", "계절성", "서류 준비 난이도", "상담 후 이탈률", "가격 민감도"]},
    "여권":     {"controllability": "중간", "risk_factors": ["발급 수요 계절성", "낮은 단가"]},
    "초청":     {"controllability": "중간", "risk_factors": ["초청 요건 변경", "서류 준비 난이도"]},
    "영주권":   {"controllability": "중간", "risk_factors": ["요건 충족 난이도", "심사 기간"]},
    "기타":     {"controllability": "-", "risk_factors": []},
}


# 외부요인/매뉴얼 이슈 — 상태별 문구(현재 가능한 수준과 한계를 명확히 기술).
_MANUAL_MSG_NONE = (
    "선택월에 감지된 매뉴얼 변경 데이터가 없습니다. 이번 달 출입국 실적 변화는 "
    "매뉴얼 변경보다는 상담 유입, 계절성, 체류자격별 수요, 내부 응대 전환율을 중심으로 "
    "확인해야 합니다."
)
_MANUAL_MSG_ERROR = (
    "매뉴얼 변경 데이터를 조회하지 못했습니다. 월간결산의 출입국 분석에는 매뉴얼 변경 요인이 "
    "반영되지 않았으므로, 관리자 → 매뉴얼 업데이트 PG 화면에서 변경 이력을 별도로 확인하십시오."
)


def _manual_issue_for_month(year: int, month: int, ref_day: int) -> dict:
    """선택월에 감지된 매뉴얼 업데이트(manual_update_versions)를 best-effort로 연결.

    상태:
    - linked    : 선택월 변경 기록 존재(건수/페이지수 제시). 단, 체류자격별 정밀 매칭은 아님.
    - not_linked: PG 정상 조회됐으나 선택월 변경 없음.
    - error     : PG 미구성 또는 조회 예외(반영 불가).
    절대 예외로 크래시하지 않는다.
    """
    try:
        from backend.db.session import is_configured, get_sessionmaker
        if not is_configured():
            return {"status": "error", "comment": _MANUAL_MSG_ERROR, "related_changes": []}
        from backend.db.models.manual_update import ManualUpdateVersion
        SM = get_sessionmaker()
        with SM() as s:
            rows = (s.query(ManualUpdateVersion)
                    .order_by(ManualUpdateVersion.detected_at.desc())
                    .limit(100).all())
        sel = []
        for v in rows:
            dt = v.detected_at
            if dt and dt.year == year and dt.month == month and dt.day <= ref_day:
                sel.append(v)
        if not sel:
            return {"status": "not_linked", "comment": _MANUAL_MSG_NONE, "related_changes": []}
        changes = [{
            "version": v.version,
            "detected_at": v.detected_at.strftime("%Y-%m-%d"),
            "changed_page_count": int(v.changed_page_count or 0),
            "candidate_count": int(v.candidate_count or 0),
        } for v in sel]
        total_changed = sum(c["changed_page_count"] for c in changes)
        comment = (
            f"선택월에 매뉴얼 변경 {len(sel)}건 / 관련 페이지 {total_changed}개가 감지되었습니다. "
            f"다만 현재 월간결산은 변경 내용과 체류자격별 매출·건수를 정밀 매칭하지는 않습니다. "
            f"변경된 체류자격과 실제 출입국 업무 증감을 함께 검토하십시오."
        )
        return {"status": "linked", "comment": comment, "related_changes": changes}
    except Exception:
        return {"status": "error", "comment": _MANUAL_MSG_ERROR, "related_changes": []}


def _build_business_insights(records: list, year: int, month: int, today) -> dict:
    """업무군별 손익 + 전년 동월 동일기간 비교 + 진단/개선 제안 보고서 (읽기 전용).

    기준일/전년 보정/현금출금 제외/미수(수입 0) 제외는 기존 누계 비교 로직과 동일.
    근거 없는 문장은 만들지 않으며, 전년 데이터 없음·건수 부족은 그대로 표시한다.
    """
    from collections import defaultdict

    dim = _days_in_month(year, month)
    is_current = (year == today.year and month == today.month)
    is_future = (year > today.year) or (year == today.year and month > today.month)
    ref_day = min(today.day, dim) if is_current else dim
    prev_dim = _days_in_month(year - 1, month)
    prev_ref_day = min(ref_day, prev_dim)

    cur = defaultdict(lambda: {"count": 0, "sales": 0, "expense": 0, "net": 0})
    prev = defaultdict(lambda: {"count": 0, "sales": 0, "expense": 0, "net": 0})
    for r in records:
        ds = str(r.get("date", "") or "")
        if len(ds) < 10:
            continue
        try:
            ry, rm, rd = int(ds[:4]), int(ds[5:7]), int(ds[8:10])
        except Exception:
            continue
        cat0 = str(r.get("category", "") or "").strip()
        if cat0 == "현금출금":   # cash_out 전용 카테고리 → 제외
            continue
        sales = _entry_sales(r)        # 미수는 income 0 → 매출 0 자연 제외
        exp = _entry_expense(r)
        # 일일결산의 보조 텍스트는 task(업무 설명). work/details는 진행업무 전용 필드라 daily엔 없음.
        aux = str(r.get("task", "") or "")
        bucket = normalize_business_category(cat0, aux)
        if ry == year and rm == month and rd <= ref_day:
            b = cur[bucket]
        elif ry == year - 1 and rm == month and rd <= prev_ref_day:
            b = prev[bucket]
        else:
            continue
        b["count"] += 1
        b["sales"] += sales
        b["expense"] += exp
        b["net"] += sales - exp

    def margin(net, sales):
        return None if not sales else round(net / sales * 100, 1)

    def pct(c, p):
        return None if not p else round((c - p) / abs(p) * 100, 1)

    def won(n):
        return f"{round(n / 10000):,}만원"

    # 활동이 있는 버킷만(현재 또는 전년) — 표준 순서 유지
    active = [c for c in _BIZ_CATEGORIES if cur[c]["count"] or prev[c]["count"]]

    cats = []
    for c in active:
        cu, pv = cur[c], prev[c]
        has_prev = bool(pv["count"] or pv["sales"])
        cu_margin = margin(cu["net"], cu["sales"])
        pv_margin = margin(pv["net"], pv["sales"])
        prof = _CAT_PROFILE.get(c, _CAT_PROFILE["기타"])
        cats.append({
            "category": c,
            "cur_count": cu["count"], "cur_sales": cu["sales"], "cur_expense": cu["expense"],
            "cur_net": cu["net"], "cur_margin": cu_margin,
            "cur_avg_ticket": round(cu["sales"] / cu["count"]) if cu["count"] else 0,
            "cur_net_per_case": round(cu["net"] / cu["count"]) if cu["count"] else 0,
            "prev_count": pv["count"], "prev_sales": pv["sales"], "prev_net": pv["net"],
            "prev_margin": pv_margin, "has_prev": has_prev,
            "count_delta": cu["count"] - pv["count"],
            "count_delta_pct": pct(cu["count"], pv["count"]),
            "sales_delta": cu["sales"] - pv["sales"],
            "sales_delta_pct": pct(cu["sales"], pv["sales"]),
            "net_delta": cu["net"] - pv["net"],
            "net_delta_pct": pct(cu["net"], pv["net"]),
            "margin_delta": (None if (cu_margin is None or pv_margin is None)
                             else round(cu_margin - pv_margin, 1)),
            "controllability": prof["controllability"],
            "risk_factors": prof["risk_factors"],
        })

    by_cat = {c["category"]: c for c in cats}
    gong = by_cat.get("공증")

    # 진단/개선 문장 (모두 계산값에 근거)
    for c in cats:
        name = c["category"]
        m_txt = f"{c['cur_margin']}%" if c["cur_margin"] is not None else "-"
        diag = (f"{name}은(는) {c['cur_count']}건, 매출 {won(c['cur_sales'])}, "
                f"순이익 {won(c['cur_net'])}으로 순이익률 {m_txt}입니다.")
        # 전년 비교
        if not c["has_prev"]:
            diag += " 전년 동기 데이터가 없습니다."
        else:
            cd = "증가" if c["count_delta"] >= 0 else "감소"
            nd = "증가" if c["net_delta"] >= 0 else "감소"
            diag += (f" 전년 동기 대비 건수가 {cd}({c['count_delta']:+}건), "
                     f"순이익은 {nd}({won(c['net_delta'])})했습니다.")
        # 저건수 경고
        if name in _LOW_VOLUME_CATS and c["cur_count"] < _LOW_VOLUME_N:
            diag += " 건수가 적어 추세 판단이 제한됩니다."
        # 전자민원 ↔ 공증 순이익률 비교
        if (name == "전자민원" and c["cur_margin"] is not None
                and gong and gong["cur_margin"] is not None):
            rel = "높은" if c["cur_margin"] >= gong["cur_margin"] else "낮은"
            diag += f" 공증 순이익률 {gong['cur_margin']}%와 비교하면 {rel} 수준입니다."

        # 개선 제안 (업무군 성격 + 실제 수치 조건)
        recs = []
        if name == "전자민원":
            if c["cur_margin"] is not None and c["cur_margin"] >= 50 and c["cur_count"] <= 5:
                recs.append("순이익률이 높고 건수가 낮아 적극 확대(반복업무 자동화·템플릿화·마케팅 강화)가 필요합니다.")
            elif c["cur_margin"] is not None and c["cur_margin"] < 30:
                recs.append("순이익률이 낮아 수수료 조정 또는 처리시간 단축이 필요합니다.")
            else:
                recs.append("처리 속도·안내문·가격표·응대 스크립트 개선으로 통제 가능한 업무군입니다.")
        elif name == "공증":
            if c["has_prev"] and c["count_delta"] < 0:
                recs.append("전년 대비 건수가 감소했습니다. 문의 유입 경로·상담 후 이탈률·준비서류 안내문·마케팅 노출을 점검하십시오.")
            if c["cur_margin"] is not None and c["cur_margin"] < 30:
                recs.append("순이익률이 낮아 대행 범위와 가격 재검토가 필요합니다.")
            if not recs:
                recs.append("계절성·현지 정책 영향을 받는 업무군이므로 유입 경로와 상담 품질을 점검하십시오.")
        elif name == "출입국":
            if c["has_prev"] and c["count_delta"] < 0:
                recs.append("전년 대비 건수가 감소했습니다. 제도 이슈·상담 전환율·고객 유입 경로를 점검하십시오.")
            recs.append("하이코리아 매뉴얼 변경·체류자격별 심사 변화의 영향을 받으므로 최근 매뉴얼 변동 반영 여부를 확인하십시오.")
        else:  # 여권/초청/영주권/기타
            if c["cur_count"] < _LOW_VOLUME_N:
                recs.append("건수가 적어 추세 판단이 제한됩니다. 데이터 누적 후 재평가가 필요합니다.")
            elif c["cur_margin"] is not None and c["cur_margin"] < 30:
                recs.append("순이익률이 낮아 가격·처리시간 점검이 필요합니다.")
            else:
                recs.append("현재 추세를 유지하며 유입 경로를 점검하십시오.")
        c["diagnosis"] = diag
        c["recommendation"] = " ".join(recs)

    # ── 요약 카드 ──
    margin_cats = [c for c in cats if c["cur_margin"] is not None and c["cur_count"] > 0]
    best = max(margin_cats, key=lambda c: c["cur_margin"]) if margin_cats else None
    decl = [c for c in cats if c["has_prev"] and c["net_delta"] < 0]
    worst = min(decl, key=lambda c: c["net_delta"]) if decl else None

    total_sales = sum(c["cur_sales"] for c in cats)
    # 집중 개선 대상: 매출 비중 15%↑ 중 순이익률 최저(없으면 최대 감소 업무군)
    focus = None
    sizable = [c for c in cats if c["cur_margin"] is not None and total_sales
               and c["cur_sales"] / total_sales >= 0.15]
    if sizable:
        focus = min(sizable, key=lambda c: c["cur_margin"])
    elif worst:
        focus = worst

    summary = {
        "best_margin_category": best["category"] if best else None,
        "best_margin_value": best["cur_margin"] if best else None,
        "worst_decline_category": worst["category"] if worst else None,
        "worst_decline_net": worst["net_delta"] if worst else None,
        "focus_category": focus["category"] if focus else None,
        "focus_margin": focus["cur_margin"] if focus else None,
    }

    # 총평
    total_net = sum(c["cur_net"] for c in cats)
    total_margin = margin(total_net, total_sales)
    if is_future:
        total_comment = "아직 시작되지 않은 월입니다. 분석할 데이터가 없습니다."
    elif not cats:
        total_comment = "데이터 부족: 이번 기간 결산 데이터가 없습니다."
    else:
        tm = f"{total_margin}%" if total_margin is not None else "-"
        total_comment = (f"이번 기간(1~{ref_day}일) 총 매출 {won(total_sales)}, "
                         f"순이익 {won(total_net)}(순이익률 {tm})입니다.")
        if best:
            total_comment += f" 수익성이 가장 높은 업무군은 {best['category']}({best['cur_margin']}%)입니다."
        if worst:
            total_comment += f" 전년 대비 순이익이 가장 많이 감소한 업무군은 {worst['category']}({won(worst['net_delta'])})입니다."
        elif not any(c["has_prev"] for c in cats):
            total_comment += " 전년 동기 데이터가 없어 전년 비교는 생략합니다."

    # 다음 달 액션 (교차 분석 규칙 — 모두 계산값 근거)
    actions = []
    ej, gj = by_cat.get("전자민원"), by_cat.get("공증")
    if (ej and gj and ej["cur_margin"] is not None and gj["cur_margin"] is not None
            and ej["cur_margin"] > gj["cur_margin"] and ej["cur_count"] < gj["cur_count"]):
        actions.append("전자민원이 공증보다 순이익률이 높고 건수는 적습니다 → 전자민원 확대 전략을 검토하십시오.")
    if gj and gj["cur_margin"] is not None and gj["cur_margin"] < 30 and total_sales and gj["cur_sales"] / total_sales >= 0.15:
        actions.append("공증은 매출 비중은 크지만 순이익률이 낮습니다 → 대행 범위·가격·준비서류 안내를 개선하십시오.")
    ig = by_cat.get("출입국")
    if ig and ig["has_prev"] and ig["count_delta"] < 0 and (ig["cur_margin"] or 0) >= 30:
        actions.append("출입국은 순이익률은 양호하나 전년 대비 건수가 감소했습니다 → 제도 이슈·상담 전환율·유입 경로를 점검하십시오.")
    # 전체: 건수↑·순이익률↓
    cur_total_margin = total_margin
    prev_total_sales = sum(c["prev_sales"] for c in cats)
    prev_total_net = sum(c["prev_net"] for c in cats)
    prev_total_margin = margin(prev_total_net, prev_total_sales)
    cur_total_count = sum(c["cur_count"] for c in cats)
    prev_total_count = sum(c["prev_count"] for c in cats)
    if (prev_total_margin is not None and cur_total_margin is not None
            and cur_total_count > prev_total_count and cur_total_margin < prev_total_margin):
        actions.append("건수는 늘었으나 순이익률이 하락했습니다 → 저가 업무 증가 또는 지출 증가 원인을 점검하십시오.")
    if (prev_total_sales and total_sales > prev_total_sales and total_net < prev_total_net):
        actions.append("매출은 늘었으나 순이익이 줄었습니다 → 비용 누수 또는 가격 정책을 점검하십시오.")
    if focus and not actions:
        actions.append(f"집중 개선 대상은 {focus['category']}입니다. 순이익률 개선을 우선 검토하십시오.")

    manual_issue = _manual_issue_for_month(year, month, ref_day)

    return {
        "summary": summary,
        "total_comment": total_comment,
        "categories": cats,
        "manual_issue": manual_issue,
        "actions": actions,
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


# [Phase E] PG mirror(_append_delegation_to_customer_pg) 사용.


# [Phase E] dedup helper(_DedupeResult/_dedupe_active_rows_by_source) 제거됨.


# [Phase E] PG mirror(_apply_daily_to_active_pg) 사용.


# ── PG mirror of daily→active / daily→customer-delegation (PG-only) ─────────────
#
# These PG mirrors implement the daily→active / daily→customer-delegation
# business rules talking only to PostgreSQL via the tenant-aware repository
# services.


def _apply_daily_to_active_pg(rec: dict, tenant_id: str) -> None:
    """PG mirror of :func:`_apply_daily_to_active`.

    Reads existing ``active_tasks`` rows from PG, decides whether to update an
    existing one (by ``source_daily_id`` or content match) or insert a new row,
    then writes via :func:`tasks_pg_service.upsert_active`. Money deltas are
    accumulated using the same memo-encoded slot rules as the original
    implementation.
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
    the name fallback).
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

    overview = _build_yearly_overview(records, year, month, fixed_records=fixed_records,
                                      pg_daily=pg, tax_cur=tax_cur, tax_prev=tax_prev)
    # 기준일까지 누계 비교 + 일별 추이 + 시간대 비교 + 자동 분석(요구사항 1·3·5·6)
    import datetime as _dt
    _today = _dt.date.today()
    overview.update(_build_period_analysis(
        records, year, month, _today,
        overview["category_compare"], tax_cur=tax_cur,
    ))
    # 업무군별 경영 진단 보고서
    overview["business_insights"] = _build_business_insights(records, year, month, _today)
    return overview


# ── 고정지출 / 신고·부가세 (PostgreSQL 전용 — FEATURE_PG_DAILY) ────────────────

def _require_pg_daily():
    # PG-only(Phase E): PostgreSQL 구성 필수. 미구성 시 503(조용한 fallback 없음).
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


def _auto_card_stats_for_month(tenant_id: str, year_month: str) -> tuple[int, int]:
    """선택월(YYYY-MM)의 자동 카드매출 (합계원, 건수). 일일결산 중 수입 결제수단이
    카드이고 수입>0 인 행만 집계(읽기 전용). 일일결산은 하드삭제라 별도 무효상태
    컬럼이 없으므로 조회 결과(live rows)만 합산한다 — migration/컬럼변경 없음."""
    prefix = str(year_month or "").strip()[:7]
    if len(prefix) < 7:
        return 0, 0
    records = _fetch_daily_records(tenant_id)
    sales = 0
    count = 0
    for r in records:
        if not str(r.get("date", "")).startswith(prefix):
            continue
        amt = _entry_card_income(r)
        if amt > 0:
            sales += amt
            count += 1
    return sales, count


def _auto_card_sales_for_month(tenant_id: str, year_month: str) -> int:
    """선택월 자동 카드매출 합계(원). 건수까지 필요하면 _auto_card_stats_for_month 사용."""
    return _auto_card_stats_for_month(tenant_id, year_month)[0]


def _enrich_tax_response(base: dict, auto_card_revenue: int, auto_card_count: int) -> dict:
    """tax-summary 응답에 자동 카드 건수 + 명시적 이름의 파생 키를 보강한다.
    기존 키(auto_card_sales/total_reported_sales/reported_output_vat/...)는 호환 위해 유지.
    DB 컬럼 변경/마이그레이션 없음 — 일일결산 조회 결과에서 계산해 응답만 보강한다."""
    out = dict(base or {})
    out["auto_card_revenue"] = auto_card_revenue
    out["auto_card_sales"] = auto_card_revenue            # 기존 키 호환
    out["auto_card_count"] = auto_card_count
    out["reported_revenue_total"] = out.get("total_reported_sales", out.get("reported_revenue", 0))
    out["deductible_purchase"] = out.get("deductible_expense", out.get("reported_expense", 0))
    out["output_vat"] = out.get("reported_output_vat", 0)
    out["input_vat"] = out.get("reported_input_vat", 0)
    out["estimated_vat_payable"] = out.get("expected_vat_payable", 0)
    return out


@router.get("/tax-summary")
def get_tax_summary_ep(
    year_month: str = Query(..., description="YYYY-MM"),
    user: dict = Depends(get_current_user),
):
    _require_pg_daily()
    from backend.services.monthly_tax_pg_service import get_tax_summary, compute_tax
    auto_card, auto_count = _auto_card_stats_for_month(user["tenant_id"], year_month)
    base = get_tax_summary(user["tenant_id"], year_month, auto_card_sales=auto_card)
    if base is None:
        # 저장된 행이 없어도 자동 카드매출 기준 파생값을 계산해 반환(빈 월도 계산판 표시).
        base = compute_tax({"year_month": year_month}, auto_card_sales=auto_card)
    return _enrich_tax_response(base, auto_card, auto_count)


@router.put("/tax-summary")
def upsert_tax_summary_ep(data: dict, user: dict = Depends(get_current_user)):
    _require_pg_daily()
    year_month = str(data.get("year_month", "")).strip()
    if not year_month:
        raise HTTPException(status_code=400, detail="year_month는 필수입니다.")
    from backend.services.monthly_tax_pg_service import upsert_tax_summary
    auto_card, auto_count = _auto_card_stats_for_month(user["tenant_id"], year_month)
    saved = upsert_tax_summary(user["tenant_id"], data, auto_card_sales=auto_card)
    return _enrich_tax_response(saved, auto_card, auto_count)
