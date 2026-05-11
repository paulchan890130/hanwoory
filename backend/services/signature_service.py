"""서명 데이터 저장/조회 서비스 — Google Sheets 기반"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import base64
import datetime
import time as _time

AGENT_SIGN_SHEET    = "행정사서명"
CUSTOMER_SIGN_SHEET = "고객서명"
TEMP_SIGN_SHEET     = "서명임시저장"

_AGENT_HEADERS    = ["tenant_id", "서명데이터", "등록일시"]
_CUSTOMER_HEADERS = ["고객ID",    "서명데이터", "등록일시"]
_TEMP_HEADERS     = ["slot", "tenant_id", "서명데이터", "비고", "저장일시"]

# process-level set: skip redundant header-check reads after first validation
_validated_worksheets: set = set()

# TTL caches: (result, monotonic_timestamp)
_temp_slots_cache: dict = {}      # key: tenant_id
_TEMP_SLOTS_CACHE_TTL = 60.0     # seconds

_sig_exists_cache: dict = {}      # key: (customer_sheet_key, customer_id)
_SIG_EXISTS_CACHE_TTL = 30.0     # seconds

# A-column-only cache for 고객서명: avoids reading base64 B column
# key: customer_sheet_key  value: (col_a_list, monotonic_timestamp)
_cust_col_a_cache: dict = {}
_CUST_COL_A_CACHE_TTL = 60.0


def _get_gspread_client():
    from backend.services.tenant_service import _get_gspread_client as _gc
    return _gc()


def _master_sh():
    from config import SHEET_KEY
    gc = _get_gspread_client()
    return gc.open_by_key(SHEET_KEY)


def _get_or_create_ws(sh, title: str, headers: list):
    # use (spreadsheet_id, title) as cache key to avoid repeated header-read API calls
    key = (sh.id, title)
    try:
        ws = sh.worksheet(title)
    except Exception:
        ws = sh.add_worksheet(title=title, rows=500, cols=len(headers) + 1)
        ws.update("A1", [headers], value_input_option="RAW")
        _validated_worksheets.add(key)
        return ws
    if key not in _validated_worksheets:
        first = ws.row_values(1) if ws.row_count > 0 else []
        if first != headers:
            ws.update("A1", [headers], value_input_option="RAW")
        _validated_worksheets.add(key)
    return ws


def _tenant_customer_sh(customer_sheet_key: str):
    gc = _get_gspread_client()
    return gc.open_by_key(customer_sheet_key)


def _find_row(ws, id_col_idx: int, id_value: str):
    """행 전체 값을 반환. 없으면 None. (행정사서명 등 소형 시트용)"""
    values = ws.get_all_values()
    if len(values) < 2:
        return None, None
    header = values[0]
    for i, row in enumerate(values[1:], start=2):
        if len(row) > id_col_idx and row[id_col_idx].strip() == id_value.strip():
            return i, dict(zip(header, row))
    return None, None


# ── 고객서명 A-column 전용 헬퍼 — base64 B열 읽기 금지 ───────────────────────

def _get_cust_col_a(ws, customer_sheet_key: str) -> list:
    """고객서명 시트의 A열만 읽어 반환. B열(base64) 비접촉."""
    cached = _cust_col_a_cache.get(customer_sheet_key)
    if cached:
        values, ts = cached
        if _time.monotonic() - ts < _CUST_COL_A_CACHE_TTL:
            return values
    values = ws.col_values(1)  # A열만 — 단일 API 호출
    _cust_col_a_cache[customer_sheet_key] = (values, _time.monotonic())
    return values


def _find_cust_row(ws, customer_sheet_key: str, customer_id: str) -> "int | None":
    """첫 번째 matching row 번호. 없으면 None."""
    rows = _find_cust_rows(ws, customer_sheet_key, customer_id)
    return rows[0] if rows else None


def _find_cust_rows(ws, customer_sheet_key: str, customer_id: str) -> "list[int]":
    """A열만으로 customer_id와 일치하는 모든 row 번호(1-based) 반환."""
    col_a = _get_cust_col_a(ws, customer_sheet_key)
    cid = customer_id.strip()
    return [i for i, val in enumerate(col_a[1:], start=2) if val.strip() == cid]


# ── 행정사 서명 ───────────────────────────────────────────────────────────────

def get_agent_signature(tenant_id: str) -> str | None:
    try:
        sh = _master_sh()
        ws = _get_or_create_ws(sh, AGENT_SIGN_SHEET, _AGENT_HEADERS)
        _, record = _find_row(ws, 0, tenant_id)
        if record is None:
            return None
        data = record.get("서명데이터", "").strip()
        return data if data else None
    except Exception as e:
        print(f"[signature_service.get_agent_signature] 오류: {e}")
        return None


def save_agent_signature(tenant_id: str, b64: str) -> None:
    sh = _master_sh()
    ws = _get_or_create_ws(sh, AGENT_SIGN_SHEET, _AGENT_HEADERS)
    row_idx, _ = _find_row(ws, 0, tenant_id)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_row = [tenant_id, b64, now]
    if row_idx:
        ws.update(f"A{row_idx}", [new_row], value_input_option="RAW")
    else:
        ws.append_row(new_row, value_input_option="RAW")


# ── 고객 서명 ─────────────────────────────────────────────────────────────────

def get_customer_signature(customer_sheet_key: str, customer_id: str) -> str | None:
    """A열로 행 찾기 → B셀 하나만 읽기. get_all_values() 호출 없음."""
    try:
        sh = _tenant_customer_sh(customer_sheet_key)
        ws = _get_or_create_ws(sh, CUSTOMER_SIGN_SHEET, _CUSTOMER_HEADERS)
        row = _find_cust_row(ws, customer_sheet_key, customer_id)
        if row is None:
            return None
        data = (ws.acell(f"B{row}").value or "").strip()
        return data if data else None
    except Exception as e:
        print(f"[signature_service.get_customer_signature] 오류: {e}")
        return None


def save_customer_signature(customer_sheet_key: str, customer_id: str, b64: str) -> None:
    """A열로 모든 matching 행 찾기 → B:C 전체 업데이트 또는 신규 행 추가.
    중복 행이 있으면 모두 최신 서명으로 덮어쓴다. get_all_values() 없음."""
    sh = _tenant_customer_sh(customer_sheet_key)
    ws = _get_or_create_ws(sh, CUSTOMER_SIGN_SHEET, _CUSTOMER_HEADERS)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = _find_cust_rows(ws, customer_sheet_key, customer_id)

    if rows:
        if len(rows) > 1:
            print(f"[signature] duplicate customer_id rows found: "
                  f"customer_id={customer_id}, rows={rows}, overwritten_all=True")
        for row in rows:
            ws.update(f"B{row}:C{row}", [[b64, now]], value_input_option="RAW")
        # verify first row
        saved_b = (ws.acell(f"B{rows[0]}").value or "").strip()
        if not saved_b:
            raise RuntimeError(f"서명 저장 확인 실패: B{rows[0]} 셀이 비어있습니다")
    else:
        ws.append_row([customer_id, b64, now], value_input_option="RAW")
        _cust_col_a_cache.pop(customer_sheet_key, None)  # new row — invalidate A-col cache
    _sig_exists_cache.pop((customer_sheet_key, customer_id), None)


class SignatureLookupError(Exception):
    """Google Sheets 조회 실패 — 서명 없음과 구별되는 오류."""


def has_customer_signature(customer_sheet_key: str, customer_id: str) -> bool:
    """A열만 읽어 존재 여부 확인. B열(base64) 비접촉.

    Returns:
        True  — 서명 row가 실제로 존재
        False — 서명 row가 실제로 없음
    Raises:
        SignatureLookupError — Sheets 조회 자체가 실패한 경우 (캐시 저장 안 함)
    """
    cache_key = (customer_sheet_key, customer_id)
    cached = _sig_exists_cache.get(cache_key)
    if cached:
        result, ts = cached
        if _time.monotonic() - ts < _SIG_EXISTS_CACHE_TTL:
            return result
    # 조회 성공 시에만 캐시 저장 — 예외는 캐시하지 않음
    try:
        sh = _tenant_customer_sh(customer_sheet_key)
        ws = _get_or_create_ws(sh, CUSTOMER_SIGN_SHEET, _CUSTOMER_HEADERS)
        row = _find_cust_row(ws, customer_sheet_key, customer_id)
        result = row is not None
    except Exception as e:
        raise SignatureLookupError(f"고객서명 조회 실패: {e}") from e
    _sig_exists_cache[cache_key] = (result, _time.monotonic())
    return result


# ── 임시저장 슬롯 ─────────────────────────────────────────────────────────────

def _find_temp_row(ws, tenant_id: str, slot: int):
    """(slot, tenant_id) 복합키로 행 탐색."""
    values = ws.get_all_values()
    if len(values) < 2:
        return None, None
    header = values[0]
    for i, row in enumerate(values[1:], start=2):
        if len(row) >= 2 and row[0].strip() == str(slot) and row[1].strip() == tenant_id.strip():
            return i, dict(zip(header, row))
    return None, None


def get_temp_slots(tenant_id: str) -> list:
    """테넌트의 임시저장 슬롯 1~3 상태 반환. 서명데이터는 제외."""
    cached = _temp_slots_cache.get(tenant_id)
    if cached:
        result, ts = cached
        if _time.monotonic() - ts < _TEMP_SLOTS_CACHE_TTL:
            return result

    try:
        sh = _master_sh()
        ws = _get_or_create_ws(sh, TEMP_SIGN_SHEET, _TEMP_HEADERS)
        all_values = ws.get_all_values()  # single read — was previously 3× get_all_values
        if len(all_values) < 2:
            result = [{"slot": s, "has_data": False, "비고": ""} for s in (1, 2, 3)]
            _temp_slots_cache[tenant_id] = (result, _time.monotonic())
            return result
        header = all_values[0]
        row_map: dict[int, dict] = {}
        for row in all_values[1:]:
            if len(row) >= 2:
                try:
                    slot_val = int(row[0].strip())
                    if row[1].strip() == tenant_id.strip() and slot_val in (1, 2, 3):
                        row_map.setdefault(slot_val, dict(zip(header, row)))
                except ValueError:
                    pass
        result = []
        for slot in (1, 2, 3):
            record = row_map.get(slot)
            if record:
                has_data = bool(record.get("서명데이터", "").strip())
                memo = record.get("비고", "").strip()
            else:
                has_data, memo = False, ""
            result.append({"slot": slot, "has_data": has_data, "비고": memo})
        _temp_slots_cache[tenant_id] = (result, _time.monotonic())
        return result
    except Exception as e:
        print(f"[signature_service.get_temp_slots] APIError: {e}")
        return [{"slot": s, "has_data": False, "비고": ""} for s in (1, 2, 3)]


def save_temp_slot(tenant_id: str, slot: int, b64: str, memo: str) -> None:
    sh = _master_sh()
    ws = _get_or_create_ws(sh, TEMP_SIGN_SHEET, _TEMP_HEADERS)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_row = [str(slot), tenant_id, b64, memo, now]
    row_idx, _ = _find_temp_row(ws, tenant_id, slot)
    if row_idx:
        ws.update(f"A{row_idx}", [new_row], value_input_option="RAW")
    else:
        ws.append_row(new_row, value_input_option="RAW")
    _temp_slots_cache.pop(tenant_id, None)


def get_temp_slot_data(tenant_id: str, slot: int) -> str | None:
    try:
        sh = _master_sh()
        ws = _get_or_create_ws(sh, TEMP_SIGN_SHEET, _TEMP_HEADERS)
        _, record = _find_temp_row(ws, tenant_id, slot)
        if record is None:
            return None
        data = record.get("서명데이터", "").strip()
        return data if data else None
    except Exception as e:
        print(f"[signature_service.get_temp_slot_data] 오류: {e}")
        return None


def clear_temp_slot(tenant_id: str, slot: int) -> None:
    sh = _master_sh()
    ws = _get_or_create_ws(sh, TEMP_SIGN_SHEET, _TEMP_HEADERS)
    row_idx, record = _find_temp_row(ws, tenant_id, slot)
    if row_idx and record:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ws.update(f"A{row_idx}", [[str(slot), tenant_id, "", "", now]], value_input_option="RAW")
    _temp_slots_cache.pop(tenant_id, None)


# ── 압축 ─────────────────────────────────────────────────────────────────────

def compress_signature(b64: str) -> str:
    """
    base64 서명 이미지 → 흰색/밝은 픽셀 투명 처리 + 400×150 이내 리사이즈 → 압축 base64 반환.
    50,000자 초과 시 ValueError.
    """
    from PIL import Image
    import io

    raw = b64
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[1]

    img_bytes = base64.b64decode(raw)
    img = Image.open(io.BytesIO(img_bytes))
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    # 흰색/밝은 픽셀 → 투명 처리
    data = img.getdata()
    new_data = []
    for pixel in data:
        r, g, b, a = pixel
        if r > 200 and g > 200 and b > 200:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(pixel)
    img.putdata(new_data)

    # 400×150 이내 비율 유지 리사이즈
    img.thumbnail((400, 150), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    compressed = base64.b64encode(buf.getvalue()).decode("ascii")
    result = f"data:image/png;base64,{compressed}"

    if len(result) > 50_000:
        raise ValueError(f"압축 후에도 서명 데이터가 너무 큽니다: {len(result)}자")

    return result
