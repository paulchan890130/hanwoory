"""고객관리 라우터 — tenant_service 전용 (streamlit 의존 없음)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth import get_current_user
from backend.services.cache_service import cache_get, cache_set, cache_invalidate

router = APIRouter()

_CACHE_EXPIRY = "customers:expiry-alerts"
_TTL_EXPIRY = 30.0  # seconds

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
    """tenant_service.read_sheet 경유로 고객 레코드 목록 반환 (JSON-safe)"""
    from backend.services.tenant_service import read_sheet
    from config import CUSTOMER_SHEET_NAME
    raw = read_sheet(CUSTOMER_SHEET_NAME, tenant_id, default_if_empty=[]) or []
    return [_sanitize_record(r) for r in raw]


@router.get("/expiry-alerts")
def get_expiry_alerts(user: dict = Depends(get_current_user)):
    """등록증/여권 만기 알림 — 등록증 4개월 이내, 여권 6개월 이내"""
    import datetime
    try:
        import pandas as pd
    except ImportError:
        return {"card_alerts": [], "passport_alerts": []}

    tenant_id = user["tenant_id"]
    cached = cache_get(tenant_id, _CACHE_EXPIRY)
    if cached is not None:
        return cached
    records = _get_records(tenant_id)
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
    cache_set(tenant_id, _CACHE_EXPIRY, result, _TTL_EXPIRY)
    return result


@router.get("")
def get_customers(
    search: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    tenant_id = user["tenant_id"]
    records = _get_records(tenant_id)
    if not records:
        return []

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
    return records


@router.post("")
def add_customer(data: dict, user: dict = Depends(get_current_user)):
    """신규 고객 등록"""
    from backend.services.tenant_service import upsert_sheet
    from config import CUSTOMER_SHEET_NAME

    tenant_id = user["tenant_id"]
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
    from backend.services.tenant_service import upsert_sheet
    from config import CUSTOMER_SHEET_NAME

    tenant_id = user["tenant_id"]
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
    from backend.services.tenant_service import upsert_sheet
    from config import CUSTOMER_SHEET_NAME

    entry: str = str(data.get("entry", "")).strip()
    if not entry:
        raise HTTPException(status_code=422, detail="entry 필드가 비어있습니다.")

    tenant_id = user["tenant_id"]
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
    return {"ok": True, "위임내역": target["위임내역"]}


@router.delete("/{customer_id}")
def delete_customer(customer_id: str, user: dict = Depends(get_current_user)):
    from backend.services.tenant_service import delete_from_sheet
    from config import CUSTOMER_SHEET_NAME

    tenant_id = user["tenant_id"]
    ok = delete_from_sheet(CUSTOMER_SHEET_NAME, tenant_id, [customer_id], id_field="고객ID")
    if not ok:
        raise HTTPException(status_code=500, detail="고객 삭제 실패")
    cache_invalidate(tenant_id, _CACHE_EXPIRY)
    return {"ok": True}
