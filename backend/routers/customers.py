"""고객관리 라우터 — tenant_service 전용 (streamlit 의존 없음)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import logging
import threading
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from fastapi.responses import Response

from backend.auth import get_current_user
from backend.services.cache_service import cache_get, cache_set, cache_invalidate
from backend.services import audit_service as _audit


def _req_ip_ua(request: "Request | None"):
    if request is None:
        return None, None
    ua = request.headers.get("user-agent")
    xff = request.headers.get("x-forwarded-for")
    ip = (xff.split(",")[0].strip() if xff else (request.client.host if request.client else None))
    return ip, ua

router = APIRouter()
_log = logging.getLogger("customers.accommodation")

# ── process-level header validation cache ───────────────────────────
# key: (sheet_key, name) — 서버 재시작 시 초기화 허용
_VALIDATED_CUSTOMER_WORKSHEETS: set = set()

# ── relationship sheet read cache (accommodation / guarantor) ─────────────────
# Prevents thundering-herd 429 when CustomerDrawer + QuickDocPanel fire
# concurrent reads for the same table.
# TTL cache + per-key lock (thundering-herd 방지).
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
    """외부 API 429/Quota 오류를 HTTP 503으로 변환(방어적)."""
    s = str(e)
    if "429" in s or "Quota exceeded" in s or "quota" in s.lower():
        raise HTTPException(
            status_code=503,
            detail="데이터 조회 한도 초과입니다. 잠시 후 다시 시도해 주세요.",
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
    "비고",        # PG memo 컬럼과 매핑(customer_pg_service); frontend 고객카드 "비고" 키와 일치
    "폴더",
]


def _sanitize_record(r: dict) -> dict:
    """레코드를 JSON-safe 문자열 dict로 변환.
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
    """고객 레코드 목록 반환 (JSON-safe) — PostgreSQL 전용.

    PG-only(Phase C): 항상 PostgreSQL 에서 읽어 dict 리스트를 반환한다.
    """
    from backend.services.customer_pg_service import list_customers
    return list_customers(tenant_id)


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
                # 고객카드를 고유키로 열기 위함 — 이름 매칭 금지(동명이인 방지).
                "고객ID": str(r.get("고객ID", "")),
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
        q = search.strip()
        s = q.lower()
        digits = "".join(ch for ch in q if ch.isdigit())
        # 평문 필드 부분검색 — 마스킹된 번호/해시 보조키는 제외(별표 오매칭·해시노출 방지).
        _excluded = {"번호", "번호_last4"}
        text_hits = [
            r for r in records
            if any(s in str(v).lower() for k, v in r.items() if k not in _excluded)
        ]
        # 등록번호 뒷자리 검색: 순수숫자 7자리=HMAC 정확검색, 4자리=last4 (1~3자리 미지원).
        # 기존 평문필드 검색과 합집합(전화 뒤4자리 등 회귀 방지).
        reg_hits: list = []
        if q == digits and len(digits) == 7:
            from backend.services.customer_pg_service import ids_by_reg_back_hash
            from backend.services.pii_crypto import hash_pii, hash_secret_available, is_server_env
            # 운영 fail-closed: HMAC 비밀키 미설정이면 조용한 빈 결과 대신 명확한 503.
            if is_server_env() and not hash_secret_available():
                raise HTTPException(status_code=503, detail="등록번호 정확검색을 사용할 수 없습니다(보안 검색 설정 미완료). 관리자에게 문의하세요.")
            id_set = ids_by_reg_back_hash(tenant_id, hash_pii(tenant_id, digits))
            reg_hits = [r for r in records if r.get("고객ID", "") in id_set]
        elif q == digits and len(digits) == 4:
            reg_hits = [r for r in records if r.get("번호_last4", "") == digits]
        if reg_hits:
            seen = {id(r) for r in text_hits}
            text_hits = text_hits + [r for r in reg_hits if id(r) not in seen]
        records = text_hits

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


# ── 엑셀 일괄 고객등록 ─────────────────────────────────────────────────────────
# 주의: 아래 /bulk-* 는 /{customer_id} 보다 먼저 등록해야 한다(literal vs path-param 우선순위).
# 권한: get_current_user(tenant-scoped) — add_customer 와 동일. 등록은 create_customer 경유(암호화).
_BULK_MAX_BYTES = 5 * 1024 * 1024  # 5MB


@router.get("/bulk-template")
def bulk_template(user: dict = Depends(get_current_user)):
    """엑셀 일괄등록 기준 양식(xlsx) 다운로드."""
    from backend.services import customer_bulk_service as bulk
    data = bulk.build_template_bytes()
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="customer_bulk_template.xlsx"'},
    )


def _read_upload(file: UploadFile) -> bytes:
    if file is None:
        raise HTTPException(status_code=400, detail="파일이 없습니다.")
    name = (file.filename or "").lower()
    if not name.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="xlsx 파일만 업로드할 수 있습니다.")
    content = file.file.read()
    if len(content) > _BULK_MAX_BYTES:
        raise HTTPException(status_code=400, detail="엑셀 파일은 5MB 이하만 업로드할 수 있습니다.")
    if not content:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    return content


@router.post("/bulk-validate")
def bulk_validate(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """업로드 엑셀 파싱+검증(등록하지 않음). 신규/중복의심/오류 미리보기 반환."""
    tenant_id = user["tenant_id"]
    content = _read_upload(file)
    from backend.services import customer_bulk_service as bulk
    try:
        return bulk.validate(content, tenant_id)
    except HTTPException:
        raise
    except bulk.BulkTemplateMismatch:
        raise HTTPException(status_code=400, detail="고객 일괄등록 양식이 일치하지 않습니다. 최신 양식을 다시 다운로드하세요.")
    except Exception:
        # 파싱 실패 — 민감정보 노출 방지 위해 일반 메시지만.
        raise HTTPException(status_code=400, detail="엑셀을 읽는 중 오류가 발생했습니다. 양식을 확인해 주세요.")


@router.post("/bulk-commit")
def bulk_commit(
    file: UploadFile = File(...),
    include_duplicates: bool = Form(False),
    user: dict = Depends(get_current_user),
):
    """검증 통과 행 등록(부분 성공). 중복 의심은 include_duplicates 시에만 신규 등록."""
    tenant_id = user["tenant_id"]
    content = _read_upload(file)
    from backend.services import customer_bulk_service as bulk
    try:
        result = bulk.commit(content, tenant_id, include_duplicates)
    except HTTPException:
        raise
    except bulk.BulkTemplateMismatch:
        raise HTTPException(status_code=400, detail="고객 일괄등록 양식이 일치하지 않습니다. 최신 양식을 다시 다운로드하세요.")
    except Exception:
        raise HTTPException(status_code=400, detail="엑셀을 읽는 중 오류가 발생했습니다. 양식을 확인해 주세요.")
    cache_invalidate(tenant_id, _CACHE_EXPIRY)
    return result


@router.get("/bulk-export")
def bulk_export(user: dict = Depends(get_current_user), request: Request = None):
    """현재 tenant 고객 전체를 고객카드 기준 컬럼으로 Excel 추출(하이코리아/소시넷 계정 제외)."""
    tenant_id = user["tenant_id"]
    from backend.services import customer_excel_service as excel

    data, count = excel.build_tenant_export_bytes(tenant_id)
    _ip, _ua = _req_ip_ua(request)
    _audit.log_event(action="CUSTOMER_BULK_EXPORT", actor_login_id=user.get("sub"), tenant_id=tenant_id,
                     target_type="customer", target_id="bulk", ip_address=_ip, user_agent=_ua,
                     payload={"count": count, "success": True, "pii_accessed": True})
    return Response(
        content=data,
        media_type=excel.EXCEL_MIME,
        headers={"Content-Disposition": 'attachment; filename="customer_export.xlsx"'},
    )


@router.get("/{customer_id}")
def get_customer(customer_id: str, user: dict = Depends(get_current_user), request: Request = None):
    """단일 고객 전체 레코드 조회 — 고객카드(CustomerDrawer)를 고유키로 열기 위함.

    홈 대시보드 만기 목록/진행업무 카드에서 고객ID만으로 카드를 열 때 사용한다.
    이름 검색이 아닌 PG find_customer(고유키) 사용 → 동명이인 오매칭 없음.
    """
    tenant_id = user["tenant_id"]
    from backend.services.customer_pg_service import find_customer
    # 상세조회 — 단건만 reg_back 복호화(reveal=True). 고객카드/customer-copy-popup 호환.
    rec = find_customer(tenant_id, str(customer_id).strip(), reveal=True)
    if rec is None:
        raise HTTPException(status_code=404, detail="해당 고객을 찾을 수 없습니다.")
    _ip, _ua = _req_ip_ua(request)
    _audit.log_event(action="CUSTOMER_VIEW", actor_login_id=user.get("sub"), tenant_id=tenant_id,
                     target_type="customer", target_id=str(customer_id), ip_address=_ip, user_agent=_ua,
                     payload={"customer_id": str(customer_id), "success": True, "pii_accessed": True})
    return rec


@router.post("")
def add_customer(data: dict, user: dict = Depends(get_current_user)):
    """신규 고객 등록 — PG-only(Phase C)."""
    tenant_id = user["tenant_id"]
    print(f"[write-path] customers(add): PG tenant={tenant_id!r}")
    from backend.services.customer_pg_service import (
        create_customer, CustomerIdConflict, TenantNotProvisioned,
    )
    from backend.services.customer_identifier_normalize import RegFrontValidationError
    from backend.services.pii_crypto import PiiKeyMissing
    try:
        result = create_customer(tenant_id, data)
    except RegFrontValidationError as e:
        # 웹/API 신규 등록 = 엄격: 잘못된 앞자리는 조용히 복구하지 않고 구조화 오류(422).
        raise HTTPException(status_code=422, detail={"code": e.code, "message": str(e)})
    except TenantNotProvisioned as e:
        raise HTTPException(status_code=409, detail=str(e))
    except CustomerIdConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    except PiiKeyMissing:
        # 운영 fail-closed: 암호화 키 미설정 시 평문 저장 금지(키명 비노출).
        raise HTTPException(status_code=503, detail="개인정보 보안 저장 설정이 완료되지 않아 저장할 수 없습니다. 관리자에게 문의하세요.")
    cache_invalidate(tenant_id, _CACHE_EXPIRY)
    return {"ok": True, "고객ID": result["고객ID"]}


@router.put("/{customer_id}")
def update_customer(customer_id: str, data: dict, user: dict = Depends(get_current_user), request: Request = None):
    # PG-only(Phase C): 고객 수정은 항상 PostgreSQL.
    tenant_id = user["tenant_id"]
    print(f"[write-path] customers(update): PG tenant={tenant_id!r}")
    from backend.services.customer_pg_service import find_customer, upsert_customer
    # reveal=True 로 평문 번호를 가져와야 클라이언트가 번호를 안 보낸 경우에도
    # 마스킹값이 재암호화되어 손상되는 일이 없다(masked 입력은 서비스가 무시하지만 이중 안전).
    existing = find_customer(tenant_id, str(customer_id).strip(), reveal=True)
    if existing is None:
        raise HTTPException(status_code=404, detail="해당 고객을 찾을 수 없습니다.")
    # 마스킹 보조키는 저장 payload 에서 제외(원문 아님).
    existing.pop("번호_last4", None)
    merged = {**existing, **{k: str(v) for k, v in data.items()}}
    merged["고객ID"] = customer_id
    # 사용자가 등록증(앞자리)을 **직접 수정한 경우에만** 엄격 검증한다(웹 입력 = 엄격).
    # 미전송(다른 필드만 수정) 시엔 화면 canonical/레거시 값을 grandfather 로 통과시켜
    # 복구 불가한 레거시 앞자리 때문에 다른 필드 저장이 막히지 않게 한다.
    if "등록증" in data:
        from backend.services.customer_identifier_normalize import (
            RegFrontValidationError, validate_reg_front_for_write,
        )
        try:
            merged["등록증"] = validate_reg_front_for_write(merged.get("등록증"))
        except RegFrontValidationError as e:
            raise HTTPException(status_code=422, detail={"code": e.code, "message": str(e)})
    from backend.services.pii_crypto import PiiKeyMissing
    try:
        upsert_customer(tenant_id, merged)
    except PiiKeyMissing:
        raise HTTPException(status_code=503, detail="개인정보 보안 저장 설정이 완료되지 않아 저장할 수 없습니다. 관리자에게 문의하세요.")
    cache_invalidate(tenant_id, _CACHE_EXPIRY)
    _ip, _ua = _req_ip_ua(request)
    _pii_changed = "번호" in data  # 외국인등록번호 뒷자리 변경 여부
    _audit.log_event(action="CUSTOMER_UPDATE", actor_login_id=user.get("sub"), tenant_id=tenant_id,
                     target_type="customer", target_id=str(customer_id), ip_address=_ip, user_agent=_ua,
                     payload={"customer_id": str(customer_id), "success": True,
                              "pii_accessed": _pii_changed, "changed_keys": sorted(data.keys())})
    return {"ok": True}


@router.post("/{customer_id}/delegation-append")
def append_delegation(customer_id: str, data: dict, user: dict = Depends(get_current_user)):
    """위임내역 필드에 새 항목을 줄 바꿈으로 추가 (덮어쓰기 아님)"""
    entry: str = str(data.get("entry", "")).strip()
    if not entry:
        raise HTTPException(status_code=422, detail="entry 필드가 비어있습니다.")

    tenant_id = user["tenant_id"]
    # PG-only(Phase C): 위임내역 추가는 항상 PostgreSQL.
    from backend.services.customer_pg_service import append_delegation as _pg_append
    updated = _pg_append(tenant_id, str(customer_id).strip(), entry)
    if updated is None:
        raise HTTPException(status_code=404, detail="해당 고객을 찾을 수 없습니다.")
    cache_invalidate(tenant_id, _CACHE_EXPIRY)
    return {"ok": True, "위임내역": updated.get("위임내역", "")}


@router.delete("/{customer_id}")
def delete_customer(customer_id: str, user: dict = Depends(get_current_user), request: Request = None):
    tenant_id = user["tenant_id"]
    # PG-only(Phase C): 고객 삭제는 항상 PostgreSQL.
    print(f"[write-path] customers(delete): PG tenant={tenant_id!r}")
    from backend.services.customer_pg_service import delete_customer as _pg_delete
    ok = _pg_delete(tenant_id, str(customer_id).strip())
    if not ok:
        raise HTTPException(status_code=404, detail="해당 고객을 찾을 수 없습니다.")
    cache_invalidate(tenant_id, _CACHE_EXPIRY)
    _ip, _ua = _req_ip_ua(request)
    _audit.log_event(action="CUSTOMER_DELETE", actor_login_id=user.get("sub"), tenant_id=tenant_id,
                     target_type="customer", target_id=str(customer_id), ip_address=_ip, user_agent=_ua,
                     payload={"customer_id": str(customer_id), "success": True, "pii_accessed": False})
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
    ``tasks_pg_service``; otherwise uses the default path.

    Both ``/work-summary`` and ``/completed-tasks`` MUST use this single
    helper so the summary counts and the detail-modal list never diverge.
    """
    # PG-only(Phase D): 고객 카드의 완료/진행업무 참조도 항상 PostgreSQL.
    from backend.services.tasks_pg_service import list_completed, list_active
    return (list_completed(tenant_id) or [], list_active(tenant_id) or [])


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
            # name duplicate check via the same source the customers list reads (PG-only).
            from backend.services.customer_pg_service import list_customers
            all_customers = list_customers(tenant_id) or []
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
    completed_tasks / customers 를 직접 조회. 기본 경로로 폴백.
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

    # 업무별 지불금액(I-1J-6N): 완료업무 task_id 는 "daily-<entry_id>" 로, 해당 일일결산의
    # 수입(income_cash+income_etc = 고객이 지불한 금액)과 연결된다. 매칭 안 되면 paid_amount=""(→ UI '—').
    try:
        from backend.services.daily_pg_service import list_entries
        _paid_by_entry: dict = {}
        for e in (list_entries(user["tenant_id"]) or []):
            eid = str(e.get("id", "")).strip()
            if eid:
                _paid_by_entry[eid] = int(e.get("income_cash", 0) or 0) + int(e.get("income_etc", 0) or 0)
    except Exception:
        _paid_by_entry = {}

    def _attach_paid(rows: list) -> list:
        out = []
        for r in rows:
            rr = dict(r)
            tid = str(r.get("id", "")).strip()
            amt = _paid_by_entry.get(tid[6:]) if tid.startswith("daily-") else None
            rr["paid_amount"] = amt if (amt is not None and amt > 0) else ""
            out.append(rr)
        return out

    return {
        "tasks":              _attach_paid(by_id),
        "legacy_tasks":       _attach_paid(legacy),
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


def _fill_relation_from_customer(tenant_id: str, customer_db_id: str, record: dict,
                                 *, name_map: dict, phone_key: str) -> None:
    """provider_type/guarantor_type == 'customer_db' 일 때 PG 고객에서 record 의 빈 필드를 보완.
    PG-only(Phase C). name_map = {record_key: 고객컬럼}."""
    cid = str(customer_db_id or "").strip()
    if not cid:
        return
    try:
        from backend.services.customer_pg_service import find_customer
        c = find_customer(tenant_id, cid)
    except Exception:
        c = None
    if not c:
        return
    for rk, ck in name_map.items():
        if not str(record.get(rk, "")).strip():
            record[rk] = str(c.get(ck, "") or "")
    if not str(record.get(phone_key, "")).strip():
        p = "-".join(x for x in [
            str(c.get("연", "")).strip(), str(c.get("락", "")).strip(), str(c.get("처", "")).strip(),
        ] if x)
        if p:
            record[phone_key] = p


@router.get("/{customer_id}/accommodation-provider")
def get_accommodation_provider(customer_id: str, user: dict = Depends(get_current_user)):
    """고객의 숙소제공자 연결 정보 조회 — PG-only(Phase C).
    응답 body 자체가 레코드(프론트 기대 형태). 없으면 None."""
    from backend.services.relationship_pg_service import get_accommodation
    return get_accommodation(user["tenant_id"], customer_id)


@router.post("/{customer_id}/accommodation-provider")
def save_accommodation_provider(customer_id: str, data: dict, user: dict = Depends(get_current_user)):
    """고객의 숙소제공자 연결 저장 (upsert) — PG-only(Phase C).
    provider_type=customer_db이면 PG 고객에서 빈 필드를 자동 보완한다."""
    tenant_id = user["tenant_id"]
    print(f"[write-path] lodging-provider: PG tenant={tenant_id!r}")
    from backend.services.relationship_pg_service import save_accommodation
    data["target_customer_id"] = customer_id
    if str(data.get("provider_type", "")) == "customer_db":
        _fill_relation_from_customer(
            tenant_id, data.get("provider_customer_id"), data,
            name_map={
                "provider_name": "한글", "provider_last_name": "성", "provider_first_name": "명",
                "provider_nation": "국적", "provider_reg_front": "등록증",
                "provider_reg_back": "번호", "provider_address": "주소",
            },
            phone_key="provider_phone",
        )
    record = save_accommodation(tenant_id, data)
    return {"ok": True, "data": record}


@router.delete("/{customer_id}/accommodation-provider")
def delete_accommodation_provider(customer_id: str, user: dict = Depends(get_current_user)):
    """고객의 숙소제공자 연결 해제 — PG-only(Phase C)."""
    from backend.services.relationship_pg_service import delete_accommodation
    delete_accommodation(user["tenant_id"], customer_id)
    return {"ok": True}


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


_GUARANTOR_CACHE_NAME = "rel:guarantor"


@router.get("/{customer_id}/guarantor")
def get_guarantor(customer_id: str, user: dict = Depends(get_current_user)):
    """고객의 신원보증인 연결 정보 조회 — PG-only(Phase C)."""
    from backend.services.relationship_pg_service import get_guarantor as _pg
    return _pg(user["tenant_id"], customer_id)


@router.post("/{customer_id}/guarantor")
def save_guarantor(customer_id: str, data: dict, user: dict = Depends(get_current_user)):
    """고객의 신원보증인 연결 저장 (upsert) — PG-only(Phase C).
    guarantor_type=customer_db이면 PG 고객에서 빈 필드를 자동 보완한다."""
    tenant_id = user["tenant_id"]
    print(f"[write-path] guarantor: PG tenant={tenant_id!r}")
    from backend.services.relationship_pg_service import save_guarantor as _pg
    data["target_customer_id"] = customer_id
    if str(data.get("guarantor_type", "")) == "customer_db":
        _fill_relation_from_customer(
            tenant_id, data.get("guarantor_customer_id"), data,
            name_map={
                "guarantor_name": "한글", "guarantor_last_name": "성", "guarantor_first_name": "명",
                "guarantor_nation": "국적", "guarantor_reg_front": "등록증",
                "guarantor_reg_back": "번호", "guarantor_address": "주소",
            },
            phone_key="guarantor_phone",
        )
    record = _pg(tenant_id, data)
    return {"ok": True, "data": record}


@router.delete("/{customer_id}/guarantor")
def delete_guarantor(customer_id: str, user: dict = Depends(get_current_user)):
    """고객의 신원보증인 연결 해제 — PG-only(Phase C)."""
    from backend.services.relationship_pg_service import delete_guarantor as _pg
    _pg(user["tenant_id"], customer_id)
    return {"ok": True}
