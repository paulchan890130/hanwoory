"""고객관리 라우터 — tenant_service 전용 (streamlit 의존 없음)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging
import threading
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth import get_current_user
from backend.services.cache_service import cache_get, cache_set, cache_invalidate

router = APIRouter()
_log = logging.getLogger("customers.accommodation")

# ── process-level worksheet header validation cache ───────────────────────────
# key: (sheet_key, worksheet_name) — 서버 재시작 시 초기화 허용
_VALIDATED_CUSTOMER_WORKSHEETS: set = set()

# ── relationship sheet read cache (accommodation / guarantor) ─────────────────
# Prevents thundering-herd 429 when CustomerDrawer + QuickDocPanel fire
# concurrent get_all_values() calls for the same worksheet.
# Pattern mirrors tenant_service.read_sheet(): TTL cache + per-key lock.
_RELATIONSHIP_READ_TTL = 60.0  # seconds
_RELATIONSHIP_READ_LOCKS: dict = {}
_RELATIONSHIP_READ_LOCKS_MUTEX = threading.Lock()


def _get_relationship_lock(lock_key: str) -> threading.Lock:
    """Return (creating if necessary) a per-key lock for relationship reads."""
    with _RELATIONSHIP_READ_LOCKS_MUTEX:
        if lock_key not in _RELATIONSHIP_READ_LOCKS:
            _RELATIONSHIP_READ_LOCKS[lock_key] = threading.Lock()
        return _RELATIONSHIP_READ_LOCKS[lock_key]


def _raise_if_quota(e: Exception) -> None:
    """gspread APIError에서 429/Quota를 감지하면 HTTP 503으로 변환."""
    s = str(e)
    if "429" in s or "Quota exceeded" in s or "quota" in s.lower():
        raise HTTPException(
            status_code=503,
            detail="Google Sheets 읽기 한도 초과입니다. 잠시 후 다시 시도해 주세요.",
        ) from e

_CACHE_EXPIRY = "customers:expiry-alerts"
_TTL_EXPIRY = 120.0  # seconds — extended from 30; 고객 데이터 1,451 rows is the heaviest read

# 기본 고객 컬럼 스키마 (신규 테넌트 또는 빈 시트일 때 사용)
_DEFAULT_CUSTOMER_HEADERS = [
    "고객ID",
    "한글",        # 한글이름
    "성",          # 영문 성
    "명",          # 영문 이름
    "여권",        # 여권번호
    "국적",
    "성별",
    "등록증",      # 등록번호 앞자리
    "번호",        # 등록번호 뒷자리
    "발급일",      # 등록증 발급일
    "만기일",      # 등록증 만기일
    "발급",        # 여권 발급일
    "만기",        # 여권 만기일
    "주소",
    "연",          # 전화번호 앞자리
    "락",          # 전화번호 중간자리
    "처",          # 전화번호 뒷자리
    "V",           # 비고/체류자격 등
    "체류자격",
    "비자종류",
    "메모",
    "폴더",
]


def _sanitize_record(r: dict) -> dict:
    """gspread 레코드를 JSON-safe 문자열 dict로 변환.
    주의: get_all_values() 사용 시 모두 str로 오므로 float 변환은 안전망용."""
    import math
    out = {}
    for k, v in r.items():
        if v is None:
            out[str(k)] = ""
        elif isinstance(v, float):
            # NaN/Inf → 빈 문자열, 그 외 float → 정수면 정수 str (선행0 복구 불가)
            out[str(k)] = "" if (math.isnan(v) or math.isinf(v)) else str(int(v)) if v == int(v) else str(v)
        elif isinstance(v, bool):
            out[str(k)] = "TRUE" if v else "FALSE"
        else:
            # str로 온 값은 변환 없이 그대로 유지 → "010" 등 선행0 보존
            out[str(k)] = str(v)
    return out


def _get_records(tenant_id: str) -> list:
    """tenant_service.read_sheet 경유로 고객 레코드 목록 반환 (JSON-safe).

    FEATURE_PG_CUSTOMERS=true일 때는 로컬 PostgreSQL에서 읽어 같은 형태의
    dict 리스트를 반환한다. 플래그 off면 기존 Sheets 경로 그대로.
    """
    from backend.db.feature_flags import pg_customers_enabled
    if pg_customers_enabled():
        from backend.services.customer_pg_service import list_customers
        return list_customers(tenant_id)
    from backend.services.tenant_service import read_sheet
    from config import CUSTOMER_SHEET_NAME
    raw = read_sheet(CUSTOMER_SHEET_NAME, tenant_id, default_if_empty=[]) or []
    return [_sanitize_record(r) for r in raw]


@router.get("/expiry-alerts")
def get_expiry_alerts(user: dict = Depends(get_current_user)):
    """등록증/여권 만기 알림 — 등록증 4개월 이내, 여권 6개월 이내"""
    import datetime
    import time as _time
    try:
        import pandas as pd
    except ImportError:
        return {"card_alerts": [], "passport_alerts": []}

    tenant_id = user["tenant_id"]
    cached = cache_get(tenant_id, _CACHE_EXPIRY)
    if cached is not None:
        return cached
    t0 = _time.time()
    records = _get_records(tenant_id)
    print(f"[expiry-alerts] tenant={tenant_id} rows={len(records)} read={_time.time()-t0:.2f}s")
    if not records:
        return {"card_alerts": [], "passport_alerts": []}

    df = pd.DataFrame(records)
    today = pd.Timestamp.today().normalize()
    card_limit = today + pd.DateOffset(months=4)
    pass_limit = today + pd.DateOffset(months=6)

    def _parse_date(col):
        if col not in df.columns:
            return pd.Series([pd.NaT] * len(df))
        return pd.to_datetime(
            df[col].astype(str).str.replace(".", "-").str[:10],
            format="%Y-%m-%d", errors="coerce",
        )

    def _fmt_phone(row):
        parts = [str(row.get(c, "")).strip().split(".")[0] for c in ["연", "락", "처"]]
        if all(p in ("", "nan") for p in parts):
            return ""
        return " ".join(p for p in parts if p and p != "nan")

    def _fmt_birth(row):
        s = str(row.get("등록증", "")).strip().split(".")[0]
        if len(s) < 6 or not s[:6].isdigit():
            return ""
        yy, mm, dd = int(s[:2]), int(s[2:4]), int(s[4:6])
        rb = str(row.get("번호", "")).strip().split(".")[0]
        century = (
            1900 if (rb and rb[0] in "1256") else
            2000 if (rb and rb[0] in "3478") else
            (1900 if yy > today.year % 100 else 2000)
        )
        try:
            return datetime.date(century + yy, mm, dd).isoformat()
        except Exception:
            return ""

    card_dt = _parse_date("만기일")
    pass_dt = _parse_date("만기")

    card_mask = card_dt.notna() & (card_dt >= today) & (card_dt <= card_limit)
    pass_mask = pass_dt.notna() & (pass_dt >= today) & (pass_dt <= pass_limit)

    def _build_rows(mask, dt_series, date_label):
        rows = []
        for i in df.index[mask]:
            r = df.loc[i].to_dict()
            eng = f"{str(r.get('성', '')).strip()} {str(r.get('명', '')).strip()}".strip()
            rows.append({
                "한글이름": str(r.get("한글", "")),
                "영문이름": eng,
                "여권번호": str(r.get("여권", "")),
                "생년월일": _fmt_birth(r),
                "전화번호": _fmt_phone(r),
                date_label: dt_series[i].strftime("%Y-%m-%d") if pd.notna(dt_series[i]) else "",
            })
        rows.sort(key=lambda x: x[date_label])
        return rows

    result = {
        "card_alerts": _build_rows(card_mask, card_dt, "등록증만기일"),
        "passport_alerts": _build_rows(pass_mask, pass_dt, "여권만기일"),
    }
    print(f"[expiry-alerts] tenant={tenant_id} total={_time.time()-t0:.2f}s")
    cache_set(tenant_id, _CACHE_EXPIRY, result, _TTL_EXPIRY)
    return result


@router.get("")
def get_customers(
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user: dict = Depends(get_current_user),
):
    tenant_id = user["tenant_id"]
    records = _get_records(tenant_id)
    if not records:
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}

    if search:
        s = search.lower()
        records = [
            r for r in records
            if any(s in str(v).lower() for v in r.values())
        ]

    # 고객ID 내림차순 정렬 (숫자형 안전 처리)
    def _sort_key(r):
        v = str(r.get("고객ID", ""))
        return -int(v) if v.isdigit() else 0

    records.sort(key=_sort_key)

    total = len(records)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    items = records[start:start + page_size]

    return {"items": items, "total": total, "page": page, "page_size": page_size, "total_pages": total_pages}


@router.post("")
def add_customer(data: dict, user: dict = Depends(get_current_user)):
    """신규 고객 등록"""
    from backend.db.feature_flags import pg_customers_enabled
    tenant_id = user["tenant_id"]

    if pg_customers_enabled():
        from backend.services.customer_pg_service import next_customer_id, upsert_customer
        if not data.get("고객ID"):
            data["고객ID"] = next_customer_id(tenant_id)
        upsert_customer(tenant_id, data)
        cache_invalidate(tenant_id, _CACHE_EXPIRY)
        return {"ok": True, "고객ID": data["고객ID"]}

    from backend.services.tenant_service import upsert_sheet
    from config import CUSTOMER_SHEET_NAME

    records = _get_records(tenant_id)

    # 헤더 결정: 기존 레코드 키 or 기본 스키마
    if records:
        header_list = list(records[0].keys())
    else:
        header_list = _DEFAULT_CUSTOMER_HEADERS[:]

    # 고객ID 자동 채번
    if not data.get("고객ID"):
        existing_ids = [str(r.get("고객ID", "")) for r in records]
        next_num = max(
            [int(x) for x in existing_ids if x.isdigit()],
            default=0,
        ) + 1
        data["고객ID"] = str(next_num).zfill(4)

    rec = {col: str(data.get(col, "")) for col in header_list}
    ok = upsert_sheet(CUSTOMER_SHEET_NAME, tenant_id, header_list, [rec], id_field="고객ID")
    if not ok:
        raise HTTPException(status_code=500, detail="고객 추가 실패")
    cache_invalidate(tenant_id, _CACHE_EXPIRY)
    return {"ok": True, "고객ID": rec["고객ID"]}


@router.put("/{customer_id}")
def update_customer(customer_id: str, data: dict, user: dict = Depends(get_current_user)):
    from backend.db.feature_flags import pg_customers_enabled
    tenant_id = user["tenant_id"]

    if pg_customers_enabled():
        from backend.services.customer_pg_service import find_customer, upsert_customer
        existing = find_customer(tenant_id, str(customer_id).strip())
        if existing is None:
            raise HTTPException(status_code=404, detail="해당 고객을 찾을 수 없습니다.")
        merged = {**existing, **{k: str(v) for k, v in data.items()}}
        merged["고객ID"] = customer_id
        upsert_customer(tenant_id, merged)
        cache_invalidate(tenant_id, _CACHE_EXPIRY)
        return {"ok": True}

    from backend.services.tenant_service import upsert_sheet
    from config import CUSTOMER_SHEET_NAME

    records = _get_records(tenant_id)
    if not records:
        raise HTTPException(status_code=404, detail="고객을 찾을 수 없습니다.")

    header_list = list(records[0].keys())
    target = None
    for r in records:
        if str(r.get("고객ID", "")).strip() == str(customer_id).strip():
            target = r
            break

    if not target:
        raise HTTPException(status_code=404, detail="해당 고객을 찾을 수 없습니다.")

    for k, v in data.items():
        if k in header_list:
            target[k] = str(v)

    ok = upsert_sheet(CUSTOMER_SHEET_NAME, tenant_id, header_list, [target], id_field="고객ID")
    if not ok:
        raise HTTPException(status_code=500, detail="고객 수정 실패")
    cache_invalidate(tenant_id, _CACHE_EXPIRY)
    return {"ok": True}


@router.post("/{customer_id}/delegation-append")
def append_delegation(customer_id: str, data: dict, user: dict = Depends(get_current_user)):
    """위임내역 필드에 새 항목을 줄 바꿈으로 추가 (덮어쓰기 아님)"""
    from backend.db.feature_flags import pg_customers_enabled
    entry: str = str(data.get("entry", "")).strip()
    if not entry:
        raise HTTPException(status_code=422, detail="entry 필드가 비어있습니다.")

    tenant_id = user["tenant_id"]

    if pg_customers_enabled():
        from backend.services.customer_pg_service import append_delegation as _pg_append
        updated = _pg_append(tenant_id, str(customer_id).strip(), entry)
        if updated is None:
            raise HTTPException(status_code=404, detail="해당 고객을 찾을 수 없습니다.")
        cache_invalidate(tenant_id, _CACHE_EXPIRY)
        return {"ok": True, "위임내역": updated.get("위임내역", "")}

    from backend.services.tenant_service import upsert_sheet
    from config import CUSTOMER_SHEET_NAME
    records = _get_records(tenant_id)
    if not records:
        raise HTTPException(status_code=404, detail="고객을 찾을 수 없습니다.")

    header_list = list(records[0].keys())
    target = None
    for r in records:
        if str(r.get("고객ID", "")).strip() == str(customer_id).strip():
            target = r
            break

    if not target:
        raise HTTPException(status_code=404, detail="해당 고객을 찾을 수 없습니다.")

    # 위임내역 컬럼이 시트에 없으면 header_list에 추가 (신규 테넌트 대응)
    if "위임내역" not in header_list:
        header_list.append("위임내역")

    existing = str(target.get("위임내역", "")).strip()
    target["위임내역"] = (existing + "\n" + entry).strip() if existing else entry

    ok = upsert_sheet(CUSTOMER_SHEET_NAME, tenant_id, header_list, [target], id_field="고객ID")
    if not ok:
        raise HTTPException(status_code=500, detail="위임내역 업데이트 실패")
    cache_invalidate(tenant_id, _CACHE_EXPIRY)
    return {"ok": True, "위임내역": target["위임내역"]}


@router.delete("/{customer_id}")
def delete_customer(customer_id: str, user: dict = Depends(get_current_user)):
    from backend.db.feature_flags import pg_customers_enabled
    tenant_id = user["tenant_id"]

    if pg_customers_enabled():
        from backend.services.customer_pg_service import delete_customer as _pg_delete
        ok = _pg_delete(tenant_id, str(customer_id).strip())
        if not ok:
            raise HTTPException(status_code=404, detail="해당 고객을 찾을 수 없습니다.")
        cache_invalidate(tenant_id, _CACHE_EXPIRY)
        return {"ok": True}

    from backend.services.tenant_service import delete_from_sheet
    from config import CUSTOMER_SHEET_NAME

    ok = delete_from_sheet(CUSTOMER_SHEET_NAME, tenant_id, [customer_id], id_field="고객ID")
    if not ok:
        raise HTTPException(status_code=500, detail="고객 삭제 실패")
    cache_invalidate(tenant_id, _CACHE_EXPIRY)
    return {"ok": True}


# ── 고객별 업무 현황 ──────────────────────────────────────────────────────────

_CAT_GROUP_MAP: dict = {
    "출입국":  "출입국",
    "영주권":  "출입국",
    "전자민원": "전자민원",
    "공증":    "공증",
    "여권":    "여권·초청",
    "초청":    "여권·초청",
    "기타":    "기타",
}

def _cat_group(cat: str) -> str:
    return _CAT_GROUP_MAP.get(cat.strip(), "기타")

_EMPTY_GROUPS = {"출입국": 0, "전자민원": 0, "공증": 0, "여권·초청": 0, "기타": 0}


def _load_completed_active_for_tenant(tenant_id: str) -> tuple[list[dict], list[dict]]:
    """Return (completed, active) lists for the tenant.

    PG mode (``FEATURE_PG_TASKS=true``) reads from PostgreSQL via
    ``tasks_pg_service``; otherwise falls back to the Sheets path.

    Both ``/work-summary`` and ``/completed-tasks`` MUST use this single
    helper so the summary counts and the detail-modal list never diverge.
    """
    from backend.db.feature_flags import pg_tasks_enabled
    if pg_tasks_enabled():
        from backend.services.tasks_pg_service import list_completed, list_active
        return (list_completed(tenant_id) or [], list_active(tenant_id) or [])
    from backend.services.tenant_service import read_sheet
    from config import COMPLETED_TASKS_SHEET_NAME, ACTIVE_TASKS_SHEET_NAME
    return (
        read_sheet(COMPLETED_TASKS_SHEET_NAME, tenant_id, default_if_empty=[]) or [],
        read_sheet(ACTIVE_TASKS_SHEET_NAME, tenant_id, default_if_empty=[]) or [],
    )


def _resolve_customer_tasks(
    tenant_id: str,
    customer_id: str,
    customer_name: Optional[str],
) -> dict:
    """Single source of truth for customer-card task matching.

    Returns a dict with:
      - ``by_id``: completed rows whose ``customer_id`` matches.
      - ``by_name_only``: completed rows with **empty** ``customer_id`` whose
        ``name`` matches ``customer_name`` (legacy fallback only).
      - ``active_by_id``: active rows by customer_id.
      - ``has_name_duplicate``: True iff 2+ customers in this tenant share
        the same Korean name (used to warn the user that legacy matches may
        be ambiguous).

    Matching rules:
      A. ``customer_id`` exact match if the task has one.
      B. If the task has no customer_id AND ``customer_name`` is given, fall
         back to exact Korean-name match.
      C. Tasks with a non-matching customer_id are never returned — the
         resolver does not silently re-bind them.

    Both ``/work-summary`` and ``/completed-tasks`` use the same returned
    structure so their counts agree.
    """
    completed, active = _load_completed_active_for_tenant(tenant_id)
    by_id = [r for r in completed if str(r.get("customer_id", "")).strip() == customer_id]
    by_name_only: list[dict] = []
    has_name_duplicate = False

    if customer_name:
        nm = customer_name.strip()
        if nm:
            by_name_only = [
                r for r in completed
                if not str(r.get("customer_id", "")).strip()
                and str(r.get("name", "")).strip() == nm
            ]
            # name duplicate check via the same source the customers list reads.
            from backend.db.feature_flags import pg_customers_enabled
            if pg_customers_enabled():
                from backend.services.customer_pg_service import list_customers
                all_customers = list_customers(tenant_id) or []
            else:
                from backend.services.tenant_service import read_sheet
                from config import CUSTOMER_SHEET_NAME
                all_customers = read_sheet(CUSTOMER_SHEET_NAME, tenant_id, default_if_empty=[]) or []
            has_name_duplicate = (
                sum(1 for c in all_customers if str(c.get("한글", "")).strip() == nm) >= 2
            )

    active_by_id = [r for r in active if str(r.get("customer_id", "")).strip() == customer_id]
    return {
        "by_id": by_id,
        "by_name_only": by_name_only,
        "active_by_id": active_by_id,
        "has_name_duplicate": has_name_duplicate,
    }


@router.get("/{customer_id}/work-summary")
def get_work_summary(
    customer_id: str,
    name: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """고객별 업무 요약.

    구성:
      - ``groups`` / ``total`` — 이 고객 (customer_id 일치) 의 완료업무 카테고리
      - ``active_total`` — 이 고객의 진행업무 개수 (드로어가 열려 있는 동안 일일
        결산 추가/삭제로 즉시 반영되어야 함)
      - ``legacy_groups`` / ``legacy_total`` — customer_id 가 비어 있고 한글
        이름만 일치하는 과거 업무 (참고)
      - ``has_name_duplicate`` — 동명이인 경고용

    Local PG mode (``FEATURE_PG_TASKS=true``) 는 PG 의 active_tasks /
    completed_tasks / customers 를 직접 조회. 운영 Sheets 경로는 그대로 폴백.
    """
    resolved = _resolve_customer_tasks(user["tenant_id"], customer_id, name)
    groups: dict = {k: 0 for k in _EMPTY_GROUPS}
    legacy_groups: dict = {k: 0 for k in _EMPTY_GROUPS}
    for r in resolved["by_id"]:
        g = _cat_group(str(r.get("category", "")))
        groups[g] = groups.get(g, 0) + 1
    for r in resolved["by_name_only"]:
        g = _cat_group(str(r.get("category", "")))
        legacy_groups[g] = legacy_groups.get(g, 0) + 1
    return {
        "groups":            groups,
        "total":             sum(groups.values()),
        "active_total":      len(resolved["active_by_id"]),
        "legacy_groups":     legacy_groups,
        "legacy_total":      sum(legacy_groups.values()),
        "has_name_duplicate": resolved["has_name_duplicate"],
    }


@router.get("/{customer_id}/completed-tasks")
def get_customer_completed_tasks(
    customer_id: str,
    name: Optional[str] = Query(None),
    include_legacy: bool = Query(False),
    user: dict = Depends(get_current_user),
):
    """고객별 완료업무 목록.

    ``/work-summary`` 와 **같은** ``_resolve_customer_tasks`` 를 사용한다.
    따라서 summary 가 ``출입국 1`` 을 반환하면 detail modal 도 그 1 건을
    정확히 보여준다 (`tasks` 리스트). 두 응답이 서로 다른 데이터 소스를
    바라보던 이전의 inconsistency 는 제거됨.

    ``include_legacy=true`` 일 때만 name-기반 legacy 결과가 ``legacy_tasks``
    에 동봉된다. legacy 결과는 customer_id 가 비어 있고 한글 이름이 정확히
    일치하는 행 — summary 의 ``legacy_total`` 과 일치한다.
    """
    resolved = _resolve_customer_tasks(user["tenant_id"], customer_id, name)
    by_id = sorted(
        resolved["by_id"],
        key=lambda x: (x.get("complete_date") or x.get("date") or ""),
        reverse=True,
    )
    legacy: list = []
    if include_legacy:
        legacy = sorted(
            resolved["by_name_only"],
            key=lambda x: (x.get("complete_date") or x.get("date") or ""),
            reverse=True,
        )
    return {
        "tasks":              by_id,
        "legacy_tasks":       legacy,
        "has_name_duplicate": resolved["has_name_duplicate"],
    }


# ── 숙소제공자 연결 ────────────────────────────────────────────────────────────

_ACCOMMODATION_SHEET = "숙소제공자연결"
_ACCOMMODATION_HEADERS = [
    "target_customer_id",
    "provider_type",
    "provider_customer_id",
    "provider_name",        # 한글 성명
    "provider_last_name",   # 영문 성
    "provider_first_name",  # 영문 이름
    "provider_nation",      # 국적
    "provider_reg_front",   # 등록번호 앞자리
    "provider_reg_back",    # 등록번호 뒷자리
    "provider_birth",       # 생년월일 (보조)
    "provider_phone",       # 연락처 (단일 문자열)
    "provider_address",     # 숙소 소재지 / 제공자 주소 (PDF adress 필드 없으므로 참고용)
    "provider_relation",    # 피제공자와의 관계 → PDF "관계" 필드
    "provide_start_date",   # 제공 시작일 YYYY-MM-DD → PDF 제공년/월/일
    "provide_end_date",     # 제공 종료일 (선택)
    "housing_type",         # 자가/임대/개인주택/친척/기타 → PDF 체크박스
    "created_at",
    "updated_at",
]


def _get_accommodation_ws(tenant_id: str):
    """고객 워크북에서 숙소제공자연결 탭을 가져오거나 없으면 생성한다 (lazy migration).
    컬럼이 추가된 경우 헤더를 자동 확장한다 (기존 데이터 보존).

    Guard:
    - CUSTOMER_DATA_TEMPLATE_ID로 resolved되면 항상 차단 (기준 데이터에 저장 금지)
    - DEFAULT_TENANT_ID 외 테넌트가 SHEET_KEY로 resolved되면 차단
    """
    from config import (
        SHEET_KEY as _ADMIN_KEY,
        CUSTOMER_DATA_TEMPLATE_ID as _TMPL_ID,
        DEFAULT_TENANT_ID as _DEFAULT_TID,
    )
    from backend.services.tenant_service import get_customer_sheet_key, _get_gspread_client, _col_letter

    sheet_key = get_customer_sheet_key(tenant_id)  # ValueError if no CSK for non-default tenant

    # ── 잘못된 저장 방지 guard ────────────────────────────────────────────────
    if sheet_key == _TMPL_ID:
        _log.error(
            "[accommodation] tenant=%s → sheet_key가 CUSTOMER_DATA_TEMPLATE_ID — 저장 차단",
            tenant_id,
        )
        raise ValueError(
            f"tenant '{tenant_id}': customer_sheet_key가 기준 데이터 템플릿입니다. "
            "워크스페이스를 다시 설정하세요."
        )
    if sheet_key == _ADMIN_KEY and tenant_id != _DEFAULT_TID:
        _log.error(
            "[accommodation] tenant=%s → sheet_key가 어드민 마스터 SHEET_KEY — "
            "비한우리 테넌트 저장 차단",
            tenant_id,
        )
        raise ValueError(
            f"tenant '{tenant_id}': customer_sheet_key가 어드민 마스터 시트입니다. "
            "워크스페이스를 설정하세요."
        )

    gc = _get_gspread_client()
    sh = gc.open_by_key(sheet_key)
    _log.debug("[accommodation] tenant=%s sheet_id=...%s title=%r", tenant_id, sheet_key[-6:], sh.title)

    import gspread
    cache_key = (sheet_key, _ACCOMMODATION_SHEET)
    try:
        ws = sh.worksheet(_ACCOMMODATION_SHEET)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=_ACCOMMODATION_SHEET, rows=500, cols=len(_ACCOMMODATION_HEADERS))
        ws.update("A1", [_ACCOMMODATION_HEADERS], value_input_option="RAW")
        _VALIDATED_CUSTOMER_WORKSHEETS.add(cache_key)
        _log.info("[accommodation] tenant=%s 새 탭 생성 완료 (sheet_id=...%s)",
                  tenant_id, sheet_key[-6:])
        return ws
    except Exception as e:
        _raise_if_quota(e)
        raise

    # 헤더 검증 — process-level cache로 반복 row_values 생략
    if cache_key not in _VALIDATED_CUSTOMER_WORKSHEETS:
        try:
            existing_header = ws.row_values(1) if ws.row_count > 0 else []
        except Exception as e:
            _raise_if_quota(e)
            raise
        if not existing_header:
            ws.update("A1", [_ACCOMMODATION_HEADERS], value_input_option="RAW")
            _log.info("[accommodation] tenant=%s 헤더 초기화 완료", tenant_id)
        elif existing_header != _ACCOMMODATION_HEADERS:
            ws.update(f"A1:{_col_letter(len(_ACCOMMODATION_HEADERS))}1",
                      [_ACCOMMODATION_HEADERS], value_input_option="RAW")
            _log.info("[accommodation] tenant=%s 헤더 확장 완료 (%d→%d컬럼)",
                      tenant_id, len(existing_header), len(_ACCOMMODATION_HEADERS))
        _VALIDATED_CUSTOMER_WORKSHEETS.add(cache_key)
    return ws


_ACCOMM_CACHE_NAME = "rel:accommodation"


def _read_accommodation_record(ws, customer_id: str, tenant_id: str) -> dict | None:
    """Read accommodation record, using per-tenant TTL cache + in-flight lock."""
    # Fast path: cache hit
    values = cache_get(tenant_id, _ACCOMM_CACHE_NAME)
    if values is None:
        # Slow path: serialize concurrent cold-cache reads to one API call
        lock = _get_relationship_lock(f"{tenant_id}::{_ACCOMM_CACHE_NAME}")
        with lock:
            values = cache_get(tenant_id, _ACCOMM_CACHE_NAME)  # double-check
            if values is None:
                values = ws.get_all_values()
                cache_set(tenant_id, _ACCOMM_CACHE_NAME, values, _RELATIONSHIP_READ_TTL)
                _log.debug("[accommodation.cache] tenant=%s refreshed (%d rows)", tenant_id, len(values))
    if len(values) < 2:
        return None
    header = values[0]
    for row in values[1:]:
        if row and row[0].strip() == customer_id.strip():
            return dict(zip(header, row))
    return None


def _upsert_accommodation_record(ws, record: dict) -> None:
    from backend.services.tenant_service import _col_letter
    values = ws.get_all_values()
    if not values:
        ws.update("A1", [_ACCOMMODATION_HEADERS], value_input_option="RAW")
        ws.append_row([str(record.get(h, "")) for h in _ACCOMMODATION_HEADERS], value_input_option="RAW")
        return

    header = values[0]
    if header != _ACCOMMODATION_HEADERS:
        ws.update(f"A1:{_col_letter(len(_ACCOMMODATION_HEADERS))}1",
                  [_ACCOMMODATION_HEADERS], value_input_option="RAW")
        header = _ACCOMMODATION_HEADERS

    customer_id = str(record.get("target_customer_id", "")).strip()
    for i, row in enumerate(values[1:], start=2):
        if row and row[0].strip() == customer_id:
            # 기존 created_at 보존
            existing = dict(zip(values[0], row))
            if not record.get("created_at") and existing.get("created_at"):
                record["created_at"] = existing["created_at"]
            row_data = [str(record.get(h, "")) for h in header]
            ws.update(f"A{i}:{_col_letter(len(header))}{i}",
                      [row_data], value_input_option="RAW")
            return
    ws.append_row([str(record.get(h, "")) for h in header], value_input_option="RAW")


@router.get("/{customer_id}/accommodation-provider")
def get_accommodation_provider(customer_id: str, user: dict = Depends(get_current_user)):
    """고객의 숙소제공자 연결 정보 조회."""
    from backend.db.feature_flags import pg_customers_enabled
    if pg_customers_enabled():
        from backend.services.relationship_pg_service import get_accommodation
        record = get_accommodation(user["tenant_id"], customer_id)
        return {"data": record}
    tenant_id = user["tenant_id"]
    try:
        ws = _get_accommodation_ws(tenant_id)
        record = _read_accommodation_record(ws, customer_id, tenant_id)
        return record
    except HTTPException:
        raise
    except Exception as e:
        _raise_if_quota(e)
        raise HTTPException(status_code=500, detail=f"숙소제공자 조회 실패: {e}")


@router.post("/{customer_id}/accommodation-provider")
def save_accommodation_provider(customer_id: str, data: dict, user: dict = Depends(get_current_user)):
    """고객의 숙소제공자 연결 저장 (upsert)."""
    from backend.db.feature_flags import pg_customers_enabled
    if pg_customers_enabled():
        from backend.services.relationship_pg_service import save_accommodation
        data["target_customer_id"] = customer_id
        record = save_accommodation(user["tenant_id"], data)
        return {"ok": True, "data": record}
    """레거시 Sheets 경로 (플래그 OFF)
    provider_type=customer_db이면 고객 DB에서 빈 필드를 자동 보완한다."""
    import datetime
    tenant_id = user["tenant_id"]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    record = {
        "target_customer_id": customer_id,
        "provider_type":       str(data.get("provider_type", "manual")),
        "provider_customer_id": str(data.get("provider_customer_id", "")),
        "provider_name":       str(data.get("provider_name", "")),
        "provider_last_name":  str(data.get("provider_last_name", "")),
        "provider_first_name": str(data.get("provider_first_name", "")),
        "provider_nation":     str(data.get("provider_nation", "")),
        "provider_reg_front":  str(data.get("provider_reg_front", "")),
        "provider_reg_back":   str(data.get("provider_reg_back", "")),
        "provider_birth":      str(data.get("provider_birth", "")),
        "provider_phone":      str(data.get("provider_phone", "")),
        "provider_address":    str(data.get("provider_address", "")),
        "provider_relation":   str(data.get("provider_relation", "")),
        "provide_start_date":  str(data.get("provide_start_date", "")),
        "provide_end_date":    str(data.get("provide_end_date", "")),
        "housing_type":        str(data.get("housing_type", "")),
        "created_at":          now,
        "updated_at":          now,
    }

    # DB 고객 선택 시 빈 필드 자동 보완
    if record["provider_type"] == "customer_db" and record["provider_customer_id"]:
        try:
            from backend.services.tenant_service import read_sheet
            customers = read_sheet("고객 데이터", tenant_id) or []
            pid = record["provider_customer_id"]
            for c in customers:
                if str(c.get("고객ID", "")).strip() == pid:
                    def _fill(field: str, src: str) -> None:
                        if not record[field]:
                            record[field] = str(c.get(src, ""))
                    _fill("provider_name",       "한글")
                    _fill("provider_last_name",  "성")
                    _fill("provider_first_name", "명")
                    _fill("provider_nation",     "국적")
                    _fill("provider_reg_front",  "등록증")
                    _fill("provider_reg_back",   "번호")
                    _fill("provider_address",    "주소")
                    if not record["provider_phone"]:
                        p = "-".join(x for x in [
                            str(c.get("연","")).strip(),
                            str(c.get("락","")).strip(),
                            str(c.get("처","")).strip(),
                        ] if x)
                        record["provider_phone"] = p
                    break
        except Exception as e:
            print(f"[accommodation] 고객 자동채움 실패: {e}")

    try:
        _log.info(
            "[accommodation.save] tenant=%s target_customer_id=%s provider_type=%s provider_name=%s",
            tenant_id, customer_id,
            record.get("provider_type", ""),
            record.get("provider_name", ""),
        )
        ws = _get_accommodation_ws(tenant_id)
        _upsert_accommodation_record(ws, record)
        cache_invalidate(tenant_id, _ACCOMM_CACHE_NAME)
        _log.info("[accommodation.save] tenant=%s 저장 완료", tenant_id)
        return {"ok": True, "data": record}
    except ValueError as e:
        _log.error("[accommodation.save] tenant=%s guard 차단: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        _log.error("[accommodation.save] tenant=%s 저장 실패: %s", tenant_id, e)
        _raise_if_quota(e)
        raise HTTPException(status_code=500, detail=f"숙소제공자 저장 실패: {e}")


@router.delete("/{customer_id}/accommodation-provider")
def delete_accommodation_provider(customer_id: str, user: dict = Depends(get_current_user)):
    """고객의 숙소제공자 연결 해제 (해당 행 삭제)."""
    from backend.db.feature_flags import pg_customers_enabled
    tenant_id = user["tenant_id"]
    if pg_customers_enabled():
        from backend.services.relationship_pg_service import delete_accommodation
        delete_accommodation(tenant_id, customer_id)
        return {"ok": True}
    try:
        ws = _get_accommodation_ws(tenant_id)
        values = ws.get_all_values()
        if len(values) < 2:
            return {"ok": True}
        for i, row in enumerate(values[1:], start=2):
            if row and row[0].strip() == customer_id.strip():
                ws.delete_rows(i)
                cache_invalidate(tenant_id, _ACCOMM_CACHE_NAME)
                return {"ok": True}
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        _raise_if_quota(e)
        raise HTTPException(status_code=500, detail=f"숙소제공자 연결 해제 실패: {e}")


# ── 신원보증인 연결 ────────────────────────────────────────────────────────────

_GUARANTOR_SHEET = "신원보증인연결"
_GUARANTOR_HEADERS = [
    "target_customer_id",
    "guarantor_type",          # customer_db / manual
    "guarantor_customer_id",   # DB 고객 선택 시 고객ID
    "guarantor_name",          # 한글 성명 → bkoreanname
    "guarantor_last_name",     # 영문 성 → bsurname
    "guarantor_first_name",    # 영문 이름 → bgiven names
    "guarantor_nation",        # 국적 → bnation
    "guarantor_reg_front",     # 등록번호 앞자리 → bfnumber / byyyy계산
    "guarantor_reg_back",      # 등록번호 뒷자리 → brnumber
    "guarantor_birth",         # 생년월일 보조
    "guarantor_phone",         # 연락처 → bphone1/2/3
    "guarantor_address",       # 주소 → badress
    "guarantor_relation",      # 관계
    "guarantor_workplace",     # 직장/근무처
    "guarantor_extra",         # 비고
    "created_at",
    "updated_at",
]


def _get_guarantor_ws(tenant_id: str):
    """고객 워크북에서 신원보증인연결 탭을 가져오거나 없으면 생성한다 (lazy migration).
    숙소제공자연결과 동일한 guard 적용."""
    from config import (
        SHEET_KEY as _ADMIN_KEY,
        CUSTOMER_DATA_TEMPLATE_ID as _TMPL_ID,
        DEFAULT_TENANT_ID as _DEFAULT_TID,
    )
    from backend.services.tenant_service import get_customer_sheet_key, _get_gspread_client, _col_letter

    sheet_key = get_customer_sheet_key(tenant_id)

    if sheet_key == _TMPL_ID:
        _log.error("[guarantor] tenant=%s → sheet_key가 CUSTOMER_DATA_TEMPLATE_ID — 저장 차단", tenant_id)
        raise ValueError(f"tenant '{tenant_id}': customer_sheet_key가 기준 데이터 템플릿입니다.")
    if sheet_key == _ADMIN_KEY and tenant_id != _DEFAULT_TID:
        _log.error("[guarantor] tenant=%s → sheet_key가 어드민 마스터 SHEET_KEY — 비한우리 테넌트 저장 차단", tenant_id)
        raise ValueError(f"tenant '{tenant_id}': customer_sheet_key가 어드민 마스터 시트입니다.")

    gc = _get_gspread_client()
    sh = gc.open_by_key(sheet_key)
    _log.debug("[guarantor] tenant=%s sheet_id=...%s title=%r", tenant_id, sheet_key[-6:], sh.title)

    import gspread
    cache_key = (sheet_key, _GUARANTOR_SHEET)
    try:
        ws = sh.worksheet(_GUARANTOR_SHEET)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=_GUARANTOR_SHEET, rows=500, cols=len(_GUARANTOR_HEADERS))
        ws.update("A1", [_GUARANTOR_HEADERS], value_input_option="RAW")
        _VALIDATED_CUSTOMER_WORKSHEETS.add(cache_key)
        _log.info("[guarantor] tenant=%s 새 탭 생성 완료", tenant_id)
        return ws
    except Exception as e:
        _raise_if_quota(e)
        raise

    # 헤더 검증 — process-level cache로 반복 row_values 생략
    if cache_key not in _VALIDATED_CUSTOMER_WORKSHEETS:
        try:
            existing_header = ws.row_values(1) if ws.row_count > 0 else []
        except Exception as e:
            _raise_if_quota(e)
            raise
        if not existing_header:
            ws.update("A1", [_GUARANTOR_HEADERS], value_input_option="RAW")
        elif existing_header != _GUARANTOR_HEADERS:
            ws.update(f"A1:{_col_letter(len(_GUARANTOR_HEADERS))}1",
                      [_GUARANTOR_HEADERS], value_input_option="RAW")
            _log.info("[guarantor] tenant=%s 헤더 확장 완료", tenant_id)
        _VALIDATED_CUSTOMER_WORKSHEETS.add(cache_key)
    return ws


_GUARANTOR_CACHE_NAME = "rel:guarantor"


def _read_guarantor_record(ws, customer_id: str, tenant_id: str) -> "dict | None":
    """Read guarantor record, using per-tenant TTL cache + in-flight lock."""
    values = cache_get(tenant_id, _GUARANTOR_CACHE_NAME)
    if values is None:
        lock = _get_relationship_lock(f"{tenant_id}::{_GUARANTOR_CACHE_NAME}")
        with lock:
            values = cache_get(tenant_id, _GUARANTOR_CACHE_NAME)
            if values is None:
                values = ws.get_all_values()
                cache_set(tenant_id, _GUARANTOR_CACHE_NAME, values, _RELATIONSHIP_READ_TTL)
                _log.debug("[guarantor.cache] tenant=%s refreshed (%d rows)", tenant_id, len(values))
    if len(values) < 2:
        return None
    header = values[0]
    for row in values[1:]:
        if row and row[0].strip() == customer_id.strip():
            return dict(zip(header, row))
    return None


def _upsert_guarantor_record(ws, record: dict) -> None:
    from backend.services.tenant_service import _col_letter
    values = ws.get_all_values()
    if not values:
        ws.update("A1", [_GUARANTOR_HEADERS], value_input_option="RAW")
        ws.append_row([str(record.get(h, "")) for h in _GUARANTOR_HEADERS], value_input_option="RAW")
        return
    header = values[0]
    if header != _GUARANTOR_HEADERS:
        ws.update(f"A1:{_col_letter(len(_GUARANTOR_HEADERS))}1",
                  [_GUARANTOR_HEADERS], value_input_option="RAW")
        header = _GUARANTOR_HEADERS
    customer_id = str(record.get("target_customer_id", "")).strip()
    for i, row in enumerate(values[1:], start=2):
        if row and row[0].strip() == customer_id:
            existing = dict(zip(values[0], row))
            if not record.get("created_at") and existing.get("created_at"):
                record["created_at"] = existing["created_at"]
            ws.update(f"A{i}:{_col_letter(len(header))}{i}",
                      [[str(record.get(h, "")) for h in header]], value_input_option="RAW")
            return
    ws.append_row([str(record.get(h, "")) for h in header], value_input_option="RAW")


@router.get("/{customer_id}/guarantor")
def get_guarantor(customer_id: str, user: dict = Depends(get_current_user)):
    """고객의 신원보증인 연결 정보 조회."""
    from backend.db.feature_flags import pg_customers_enabled
    tenant_id = user["tenant_id"]
    if pg_customers_enabled():
        from backend.services.relationship_pg_service import get_guarantor as _pg
        return _pg(tenant_id, customer_id)
    try:
        ws = _get_guarantor_ws(tenant_id)
        record = _read_guarantor_record(ws, customer_id, tenant_id)
        return record
    except HTTPException:
        raise
    except Exception as e:
        _raise_if_quota(e)
        raise HTTPException(status_code=500, detail=f"신원보증인 조회 실패: {e}")


@router.post("/{customer_id}/guarantor")
def save_guarantor(customer_id: str, data: dict, user: dict = Depends(get_current_user)):
    """고객의 신원보증인 연결 저장 (upsert).
    guarantor_type=customer_db이면 고객 DB에서 빈 필드를 자동 보완한다."""
    from backend.db.feature_flags import pg_customers_enabled
    import datetime
    tenant_id = user["tenant_id"]
    if pg_customers_enabled():
        from backend.services.relationship_pg_service import save_guarantor as _pg
        data["target_customer_id"] = customer_id
        record = _pg(tenant_id, data)
        return {"ok": True, "data": record}
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    record = {
        "target_customer_id":   customer_id,
        "guarantor_type":       str(data.get("guarantor_type", "manual")),
        "guarantor_customer_id": str(data.get("guarantor_customer_id", "")),
        "guarantor_name":       str(data.get("guarantor_name", "")),
        "guarantor_last_name":  str(data.get("guarantor_last_name", "")),
        "guarantor_first_name": str(data.get("guarantor_first_name", "")),
        "guarantor_nation":     str(data.get("guarantor_nation", "")),
        "guarantor_reg_front":  str(data.get("guarantor_reg_front", "")),
        "guarantor_reg_back":   str(data.get("guarantor_reg_back", "")),
        "guarantor_birth":      str(data.get("guarantor_birth", "")),
        "guarantor_phone":      str(data.get("guarantor_phone", "")),
        "guarantor_address":    str(data.get("guarantor_address", "")),
        "guarantor_relation":   str(data.get("guarantor_relation", "")),
        "guarantor_workplace":  str(data.get("guarantor_workplace", "")),
        "guarantor_extra":      str(data.get("guarantor_extra", "")),
        "created_at":           now,
        "updated_at":           now,
    }

    # DB 고객 선택 시 빈 필드 자동 보완
    if record["guarantor_type"] == "customer_db" and record["guarantor_customer_id"]:
        try:
            from backend.services.tenant_service import read_sheet
            customers = read_sheet("고객 데이터", tenant_id) or []
            pid = record["guarantor_customer_id"]
            for c in customers:
                if str(c.get("고객ID", "")).strip() == pid:
                    def _fill(field: str, src: str) -> None:
                        if not record[field]:
                            record[field] = str(c.get(src, ""))
                    _fill("guarantor_name",       "한글")
                    _fill("guarantor_last_name",  "성")
                    _fill("guarantor_first_name", "명")
                    _fill("guarantor_nation",     "국적")
                    _fill("guarantor_reg_front",  "등록증")
                    _fill("guarantor_reg_back",   "번호")
                    _fill("guarantor_address",    "주소")
                    if not record["guarantor_phone"]:
                        p = "-".join(x for x in [
                            str(c.get("연", "")).strip(),
                            str(c.get("락", "")).strip(),
                            str(c.get("처", "")).strip(),
                        ] if x)
                        record["guarantor_phone"] = p
                    break
        except Exception as e:
            print(f"[guarantor] 고객 자동채움 실패: {e}")

    try:
        _log.info("[guarantor.save] tenant=%s target=%s type=%s name=%s",
                  tenant_id, customer_id, record.get("guarantor_type", ""), record.get("guarantor_name", ""))
        ws = _get_guarantor_ws(tenant_id)
        _upsert_guarantor_record(ws, record)
        cache_invalidate(tenant_id, _GUARANTOR_CACHE_NAME)
        return {"ok": True, "data": record}
    except ValueError as e:
        _log.error("[guarantor.save] tenant=%s guard 차단: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        _log.error("[guarantor.save] tenant=%s 저장 실패: %s", tenant_id, e)
        _raise_if_quota(e)
        raise HTTPException(status_code=500, detail=f"신원보증인 저장 실패: {e}")


@router.delete("/{customer_id}/guarantor")
def delete_guarantor(customer_id: str, user: dict = Depends(get_current_user)):
    """고객의 신원보증인 연결 해제."""
    from backend.db.feature_flags import pg_customers_enabled
    if pg_customers_enabled():
        from backend.services.relationship_pg_service import delete_guarantor as _pg
        _pg(user["tenant_id"], customer_id)
        return {"ok": True}
    tenant_id = user["tenant_id"]
    try:
        ws = _get_guarantor_ws(tenant_id)
        values = ws.get_all_values()
        if len(values) < 2:
            return {"ok": True}
        for i, row in enumerate(values[1:], start=2):
            if row and row[0].strip() == customer_id.strip():
                ws.delete_rows(i)
                cache_invalidate(tenant_id, _GUARANTOR_CACHE_NAME)
                return {"ok": True}
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        _raise_if_quota(e)
        raise HTTPException(status_code=500, detail=f"신원보증인 연결 해제 실패: {e}")
