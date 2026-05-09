"""
backend/services/tenant_service.py

Streamlit 의존 없는 테넌트별 Google Sheets 접근 레이어.

핵심 문제:
  core/google_sheets.py 의 get_worksheet() 이 내부적으로
  get_current_tenant_id() -> st.session_state 를 사용하므로
  FastAPI 컨텍스트에서 호출하면 RuntimeError 발생.

해결:
  tenant_id 를 JWT(get_current_user)에서 직접 받아서
  sheet_key 를 명시적으로 해결한 뒤, gspread 를 직접 열어준다.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import threading
import time
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

# ── 설정 상수 ──────────────────────────────────────────────────────────────────
from config import (
    KEY_PATH,
    SHEET_KEY,
    DEFAULT_TENANT_ID,
    ACCOUNTS_SHEET_NAME,
    TENANT_MODE,
    CUSTOMER_SHEET_NAME,
    DAILY_SUMMARY_SHEET_NAME,
    DAILY_BALANCE_SHEET_NAME,
    PLANNED_TASKS_SHEET_NAME,
    ACTIVE_TASKS_SHEET_NAME,
    COMPLETED_TASKS_SHEET_NAME,
    EVENTS_SHEET_NAME,
    MEMO_LONG_SHEET_NAME,
    MEMO_MID_SHEET_NAME,
    MEMO_SHORT_SHEET_NAME,
)

from config import CUSTOMER_DATA_TEMPLATE_ID, WORK_REFERENCE_TEMPLATE_ID

# 고객 데이터 워크북에 속하는 시트 이름 집합
_CUSTOMER_WORKBOOK_SHEETS = {
    CUSTOMER_SHEET_NAME,
    DAILY_SUMMARY_SHEET_NAME,
    DAILY_BALANCE_SHEET_NAME,
    PLANNED_TASKS_SHEET_NAME,
    ACTIVE_TASKS_SHEET_NAME,
    COMPLETED_TASKS_SHEET_NAME,
    EVENTS_SHEET_NAME,
    MEMO_LONG_SHEET_NAME,
    MEMO_MID_SHEET_NAME,
    MEMO_SHORT_SHEET_NAME,
    "숙소제공자연결",  # 고객별 숙소제공자 연결 정보
}

# 업무정리 워크북에 속하는 시트 이름 집합
_WORK_WORKBOOK_SHEETS = {"업무참고", "업무정리"}

# ── 인증 / gspread 클라이언트 ────────────────────────────────────────────────
_GSPREAD_CLIENT: Optional[gspread.Client] = None
_GSPREAD_LOCK = threading.Lock()
_GSPREAD_INIT_TIME: float = 0
_GSPREAD_TTL = 600  # 10분


def _get_gspread_client() -> gspread.Client:
    """
    스레드-세이프 싱글턴 gspread Client.
    Streamlit 캐시(@st.cache_resource) 대신 모듈 수준 싱글턴 + TTL 사용.
    """
    global _GSPREAD_CLIENT, _GSPREAD_INIT_TIME
    now = time.time()
    if _GSPREAD_CLIENT is None or (now - _GSPREAD_INIT_TIME) > _GSPREAD_TTL:
        with _GSPREAD_LOCK:
            if _GSPREAD_CLIENT is None or (now - _GSPREAD_INIT_TIME) > _GSPREAD_TTL:
                scopes = [
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive.file",
                    "https://www.googleapis.com/auth/drive",
                ]
                creds = Credentials.from_service_account_file(KEY_PATH, scopes=scopes)
                _GSPREAD_CLIENT = gspread.authorize(creds)
                _GSPREAD_INIT_TIME = time.time()
    return _GSPREAD_CLIENT


# ── 테넌트 시트 키 매핑 캐시 ───────────────────────────────────────────────────
_TENANT_MAP_CACHE: dict = {}
_TENANT_MAP_TIME: float = 0
_TENANT_MAP_TTL = 600  # 10분


def _load_tenant_map() -> dict:
    """
    Accounts 시트에서 tenant_id → {customer, work} 매핑 로드.
    TTL 캐싱 적용 (Streamlit @st.cache_data 대체).
    """
    global _TENANT_MAP_CACHE, _TENANT_MAP_TIME
    now = time.time()
    if _TENANT_MAP_CACHE and (now - _TENANT_MAP_TIME) < _TENANT_MAP_TTL:
        return _TENANT_MAP_CACHE

    try:
        client = _get_gspread_client()
        sh = client.open_by_key(SHEET_KEY)
        ws = sh.worksheet(ACCOUNTS_SHEET_NAME)
        records = ws.get_all_records()
    except Exception as e:
        print(f"[tenant_service] Accounts 시트 로드 실패: {e}")
        return _TENANT_MAP_CACHE  # 이전 캐시라도 반환

    mapping: dict = {}
    for r in records:
        tid = str(r.get("tenant_id") or r.get("login_id") or "").strip()
        if not tid:
            continue
        # is_active 체크 완화: 빈 값도 허용 (admin이 아직 설정 안 한 경우 포함)
        is_active = str(r.get("is_active", "")).strip().lower()
        if is_active and is_active not in ("true", "1", "y", "활성", "active"):
            continue
        mapping[tid] = {
            "customer": str(r.get("customer_sheet_key", "")).strip(),
            "work": str(r.get("work_sheet_key", "")).strip(),
        }

    _TENANT_MAP_CACHE = mapping
    _TENANT_MAP_TIME = time.time()
    return mapping


def get_customer_sheet_key(tenant_id: str) -> str:
    """
    tenant_id에 해당하는 고객 데이터 스프레드시트 ID 반환.

    - DEFAULT_TENANT_ID(한우리): 자기 키 없으면 SHEET_KEY로 폴백 (호환성 유지)
    - 다른 테넌트: 자기 키 없으면 ValueError 발생 (admin 데이터로 폴백 금지)
    """
    import logging
    mapping = _load_tenant_map()
    rec = mapping.get(tenant_id)
    if rec and rec.get("customer"):
        return rec["customer"]

    if tenant_id == DEFAULT_TENANT_ID:
        # 기본 테넌트는 마스터 시트로 폴백 허용
        return SHEET_KEY

    # 다른 테넌트는 워크스페이스가 아직 미생성 → 명시적 에러
    logging.getLogger("tenant_service").error(
        "[tenant_service] %s의 customer_sheet_key 없음 — 워크스페이스 미생성 또는 is_active=FALSE", tenant_id,
    )
    raise ValueError(
        f"tenant_id='{tenant_id}' 의 customer_sheet_key가 설정되지 않았습니다. "
        "관리자 페이지에서 워크스페이스를 먼저 생성하세요."
    )


def get_work_sheet_key(tenant_id: str) -> str:
    """
    tenant_id에 해당하는 업무정리 스프레드시트 ID 반환.

    - DEFAULT_TENANT_ID(한우리): 자기 키 없으면 WORK_REFERENCE_TEMPLATE_ID로 폴백
    - 다른 테넌트: 자기 키 없으면 ValueError 발생 (admin 데이터로 폴백 금지)
    """
    import logging
    mapping = _load_tenant_map()
    rec = mapping.get(tenant_id)
    if rec and rec.get("work"):
        return rec["work"]

    if tenant_id == DEFAULT_TENANT_ID:
        return WORK_REFERENCE_TEMPLATE_ID

    logging.getLogger("tenant_service").error(
        "[tenant_service] %s의 work_sheet_key 없음 — 워크스페이스 미생성 또는 is_active=FALSE", tenant_id,
    )
    raise ValueError(
        f"tenant_id='{tenant_id}' 의 work_sheet_key가 설정되지 않았습니다. "
        "관리자 페이지에서 워크스페이스를 먼저 생성하세요."
    )


def _resolve_sheet_key(sheet_name: str, tenant_id: str) -> str:
    """시트 이름으로 적절한 스프레드시트 key를 결정한다."""
    if sheet_name in _CUSTOMER_WORKBOOK_SHEETS:
        return get_customer_sheet_key(tenant_id)
    if sheet_name in _WORK_WORKBOOK_SHEETS:
        return get_work_sheet_key(tenant_id)
    # fallback: admin 마스터 시트 (Accounts 등)
    return SHEET_KEY


# ── Spreadsheet 캐시 ──────────────────────────────────────────────────────────
_SH_CACHE: dict[str, tuple[float, object]] = {}  # sheet_key -> (timestamp, spreadsheet)
_SH_TTL = 600


def _get_spreadsheet(sheet_key: str):
    now = time.time()
    if sheet_key in _SH_CACHE:
        ts, sh = _SH_CACHE[sheet_key]
        if now - ts < _SH_TTL:
            return sh
    client = _get_gspread_client()
    sh = client.open_by_key(sheet_key)
    _SH_CACHE[sheet_key] = (time.time(), sh)
    return sh


def get_worksheet(sheet_name: str, tenant_id: str) -> gspread.Worksheet:
    """
    tenant_id 기반으로 올바른 스프레드시트를 열어 worksheet를 반환한다.
    Streamlit 의존 없음.
    """
    sheet_key = _resolve_sheet_key(sheet_name, tenant_id)
    sh = _get_spreadsheet(sheet_key)
    return sh.worksheet(sheet_name)


# ── 고수준 Read/Write 래퍼 ────────────────────────────────────────────────────

def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


# ── 읽기 캐시 + 동시 요청 직렬화 ────────────────────────────────────────────
# 대시보드 로드 시 5~6개 Sheets 읽기가 동시에 cold-cache 를 뚫고
# Google Sheets API를 동시 호출 → 429 / hang 을 방지하기 위해:
#   1) TTL 을 120 초로 연장해 cold-cache 빈도를 줄임
#   2) 시트별 per-key lock 으로 동일 (tenant, sheet) 의 동시 API 호출을 직렬화
#      (double-checked locking — lock 획득 후 재확인하면 두 번째 이후 요청은 캐시 히트)
# 쓰기(upsert/delete) 시 해당 키를 무효화하므로 데이터 일관성은 유지됨.
_READ_CACHE: dict = {}            # (tenant_id, sheet_name) → (timestamp, records)
_READ_CACHE_LOCK = threading.Lock()
_READ_CACHE_TTL = 120             # seconds — was 30; extended to cut cold-call frequency

# Per-(tenant,sheet) 직렬화 락 — thundering herd 방지
_READ_KEY_LOCKS: dict = {}
_READ_KEY_LOCKS_LOCK = threading.Lock()

# 무효화 토큰 — read 도중 upsert가 캐시를 지웠을 때 stale 결과를 재캐싱하지 않도록
_INVALIDATION_TOKENS: dict = {}  # (tenant_id, sheet_name) → float


def _get_read_lock(key: tuple) -> threading.Lock:
    with _READ_KEY_LOCKS_LOCK:
        if key not in _READ_KEY_LOCKS:
            _READ_KEY_LOCKS[key] = threading.Lock()
        return _READ_KEY_LOCKS[key]


def _invalidate_read_cache(sheet_name: str, tenant_id: str) -> None:
    key = (tenant_id, sheet_name)
    with _READ_CACHE_LOCK:
        _READ_CACHE.pop(key, None)
        _INVALIDATION_TOKENS[key] = time.time()


def invalidate_read_cache(tenant_id: str, sheet_name: str) -> None:
    """Public helper: evict one (tenant, sheet) entry from the read cache.
    Safe to call even if the key is absent. Logs only names, never data.
    """
    _invalidate_read_cache(sheet_name, tenant_id)
    print(f"[sheets] cache invalidated: sheet={sheet_name!r} tenant={tenant_id!r}")


def get_invalidation_token(tenant_id: str, sheet_name: str) -> float:
    """Return current invalidation token for (tenant, sheet).
    Callers can snapshot this before a slow read_sheet call and compare after
    to detect whether a concurrent write invalidated the cache mid-read.
    """
    key = (tenant_id, sheet_name)
    with _READ_CACHE_LOCK:
        return _INVALIDATION_TOKENS.get(key, 0)


def read_sheet(sheet_name: str, tenant_id: str, default_if_empty=None):
    """
    tenant_id 기반으로 sheet_name 워크시트에서 모든 레코드를 읽어 반환.
    get_all_values() 사용 → 모든 값이 문자열로 반환되어 선행0(010 등) 보존됨.
    120초 TTL 캐시 + per-key 직렬화락으로 동시 cold-cache burst 차단.
    """
    key = (tenant_id, sheet_name)

    # 1) 빠른 경로: 캐시 히트 (per-key 락 불필요)
    with _READ_CACHE_LOCK:
        entry = _READ_CACHE.get(key)
        if entry and (time.time() - entry[0]) < _READ_CACHE_TTL:
            return entry[1]

    # 2) 느린 경로: per-key 락 획득 → 동일 시트에 대한 동시 API 호출 직렬화
    klock = _get_read_lock(key)
    with klock:
        # double-check: 락 대기 중 다른 스레드가 이미 채웠을 수 있음
        with _READ_CACHE_LOCK:
            entry = _READ_CACHE.get(key)
            if entry and (time.time() - entry[0]) < _READ_CACHE_TTL:
                return entry[1]
            # API 호출 시작 전 무효화 토큰을 기록 — 읽기 도중 upsert가 캐시를 지웠는지 감지
            read_token = _INVALIDATION_TOKENS.get(key, 0)

        # 이 시점에서 이 (tenant, sheet) 에 대한 API 호출은 정확히 1개
        t0 = time.time()
        try:
            ws = get_worksheet(sheet_name, tenant_id)
            t1 = time.time()
            values = ws.get_all_values()
            t2 = time.time()
            print(
                f"[sheets] read_sheet({sheet_name!r}, {tenant_id!r}) "
                f"ws_open={t1-t0:.2f}s data_fetch={t2-t1:.2f}s "
                f"rows={len(values)} total={t2-t0:.2f}s"
            )
        except Exception as e:
            print(f"[sheets] read_sheet 실패 ({sheet_name}, {tenant_id}): {e}")
            return default_if_empty

        if not values:
            return default_if_empty

        header = values[0]
        seen: dict = {}
        clean_header: list = []
        for col in header:
            if col in seen:
                seen[col] += 1
                clean_header.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 0
                clean_header.append(col)
        records = [
            {clean_header[i]: (row[i] if i < len(row) else "") for i in range(len(clean_header))}
            for row in values[1:]
        ]
        result = records if records else default_if_empty
        with _READ_CACHE_LOCK:
            # 읽는 도중 upsert가 캐시를 무효화했으면 stale 결과를 저장하지 않는다.
            # 다음 read_sheet 호출이 새로 API를 호출해 최신 데이터를 가져온다.
            if _INVALIDATION_TOKENS.get(key, 0) == read_token:
                _READ_CACHE[key] = (time.time(), result)
        return result


def upsert_sheet(
    sheet_name: str,
    tenant_id: str,
    header_list: list,
    records: list,
    id_field: str = "id",
) -> bool:
    """
    tenant_id 기반으로 sheet_name 에 records를 upsert.
    core/google_sheets.py upsert_rows_by_id() 의 FastAPI 대응 버전.
    """
    try:
        ws = get_worksheet(sheet_name, tenant_id)
        values = ws.get_all_values()
        last_col = _col_letter(len(header_list))

        if not values:
            rows = [header_list] + [
                [str(r.get(c, "")) for c in header_list] for r in records
            ]
            ws.update(f"A1:{last_col}{len(rows)}", rows, value_input_option="RAW")
            return True

        header = values[0]
        if header != header_list:
            ws.update(f"A1:{last_col}1", [header_list], value_input_option="RAW")
            header = header_list

        if id_field not in header:
            raise ValueError(f"시트 헤더에 '{id_field}' 컬럼이 없습니다.")

        id_idx = header.index(id_field)
        existing = {}
        for r_i, row in enumerate(values[1:], start=2):
            if id_idx < len(row):
                rid = str(row[id_idx]).strip()
                if rid:
                    existing[rid] = r_i

        updates = []
        appends = []
        for rec in records:
            rid = str(rec.get(id_field, "")).strip()
            row_vals = [str(rec.get(c, "")) for c in header_list]
            if rid and rid in existing:
                row_no = existing[rid]
                updates.append({
                    "range": f"A{row_no}:{last_col}{row_no}",
                    "values": [row_vals],
                })
            else:
                appends.append(row_vals)

        if updates:
            ws.batch_update(updates, value_input_option="RAW")
        if appends:
            ws.append_rows(appends, value_input_option="RAW")

        _invalidate_read_cache(sheet_name, tenant_id)
        return True
    except Exception as e:
        print(f"[tenant_service] upsert_sheet 실패 ({sheet_name}): {e}")
        return False


def delete_from_sheet(
    sheet_name: str,
    tenant_id: str,
    rids: list,
    id_field: str = "id",
) -> bool:
    """
    tenant_id 기반으로 sheet_name 에서 rids 에 해당하는 행들 삭제.
    core/google_sheets.py delete_rows_by_ids() 의 FastAPI 대응 버전.
    """
    rids = [str(r).strip() for r in rids if r]
    if not rids:
        return True
    try:
        ws = get_worksheet(sheet_name, tenant_id)
        values = ws.get_all_values()
        if not values:
            return True

        header = values[0]
        if id_field not in header:
            raise ValueError(f"시트 헤더에 '{id_field}' 컬럼이 없습니다.")
        id_idx = header.index(id_field)

        target_set = set(rids)
        rows_to_delete = []
        for r_i, row in enumerate(values[1:], start=2):
            if id_idx < len(row) and str(row[id_idx]).strip() in target_set:
                rows_to_delete.append(r_i)

        # 역순으로 삭제 (행 번호 밀림 방지)
        for row_no in sorted(rows_to_delete, reverse=True):
            ws.delete_rows(row_no)

        _invalidate_read_cache(sheet_name, tenant_id)
        return True
    except Exception as e:
        print(f"[tenant_service] delete_from_sheet 실패 ({sheet_name}): {e}")
        return False


def read_memo(sheet_name: str, tenant_id: str) -> str:
    """단일 셀(A1) 메모 읽기."""
    try:
        ws = get_worksheet(sheet_name, tenant_id)
        val = ws.acell("A1").value
        return val if val is not None else ""
    except Exception as e:
        print(f"[tenant_service] read_memo 실패 ({sheet_name}): {e}")
        return ""


def save_memo(sheet_name: str, tenant_id: str, content: str) -> bool:
    """단일 셀(A1) 메모 저장."""
    try:
        ws = get_worksheet(sheet_name, tenant_id)
        ws.update("A1", [[content]], value_input_option="RAW")
        return True
    except Exception as e:
        print(f"[tenant_service] save_memo 실패 ({sheet_name}): {e}")
        return False
