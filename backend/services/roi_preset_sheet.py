"""
backend/services/roi_preset_sheet.py

ROI 프리셋을 사무소별 고객 데이터 스프레드시트의 "ROI_프리셋" 시트에 저장/조회.

- 저장 위치: tenant_id → customer_sheet_key → "ROI_프리셋" 탭
- 슬롯: 1 / 2 / 3 고정 (슬롯 1 = 시스템 기본값, 삭제 불가)
- 스레드 안전: 모듈-레벨 Lock으로 write 직렬화
"""
import json
import threading
import datetime
import logging
from typing import Optional

import gspread

from backend.services.tenant_service import get_customer_sheet_key, _get_spreadsheet

_log = logging.getLogger("roi_preset_sheet")
_PRESET_LOCK = threading.Lock()

# ── 상수 ──────────────────────────────────────────────────────────────────────

SHEET_NAME = "ROI_프리셋"
HEADERS = ["slot", "name", "data_json", "is_default", "updated_at"]

# STEP 0에서 파악한 기존 하드코딩 좌표를 그대로 반영
DEFAULT_PRESET_DATA: dict = {
    "passport": {
        "mrz": {"x": 0.129, "y": 0.635, "w": 0.693, "h": 0.085},
        "rotation": 0,
        "zoom": 1.0,
        "pan": {"x": 0, "y": 0},
    },
    "arc": {
        "한글":   {"x": 0.368, "y": 0.232, "w": 0.058, "h": 0.018},
        "등록증": {"x": 0.368, "y": 0.174, "w": 0.090, "h": 0.024},
        "번호":   {"x": 0.478, "y": 0.174, "w": 0.117, "h": 0.024},
        "발급일": {"x": 0.675, "y": 0.336, "w": 0.088, "h": 0.028},
        "만기일": {"x": 0.290, "y": 0.665, "w": 0.108, "h": 0.030},
        "주소":   {"x": 0.265, "y": 0.828, "w": 0.200, "h": 0.043},
        "rotation": 0,
        "zoom": 1.0,
        "pan": {"x": 0, "y": 0},
    },
}

# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _col_letter(n: int) -> str:
    """1-based 컬럼 인덱스 → Excel 컬럼 문자 (A, B, …, Z, AA, …)."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _row_to_preset(row: dict) -> Optional[dict]:
    """get_all_records() 행 하나를 프리셋 dict로 변환. 오류 시 None."""
    try:
        slot = int(row.get("slot", 0))
        if slot not in (1, 2, 3):
            return None
        data_raw = row.get("data_json") or "{}"
        try:
            data = json.loads(data_raw)
        except json.JSONDecodeError:
            data = {}
        is_default_raw = str(row.get("is_default", "")).strip().lower()
        return {
            "slot": slot,
            "name": str(row.get("name", "")),
            "data": data,
            "is_default": is_default_raw in ("true", "1"),
        }
    except Exception as e:
        _log.warning("프리셋 행 변환 실패: %s | row=%s", e, row)
        return None


def _find_slot_row_num(all_values: list, slot: int) -> Optional[int]:
    """
    get_all_values() 결과에서 해당 슬롯 행의 1-based 행 번호 반환.
    없으면 None.
    """
    if not all_values or len(all_values) < 2:
        return None
    headers = all_values[0]
    slot_idx = headers.index("slot") if "slot" in headers else 0
    for i, row in enumerate(all_values[1:], start=2):
        if len(row) > slot_idx and str(row[slot_idx]).strip() == str(slot):
            return i
    return None


# ── 공개 API ──────────────────────────────────────────────────────────────────

def ensure_roi_preset_sheet(tenant_id: str) -> gspread.Worksheet:
    """
    ROI_프리셋 시트가 없으면 생성 + 헤더 입력.
    있으면 그대로 반환.
    헤더 불일치 시 경고 로그만, 덮어쓰기 금지.
    """
    sheet_key = get_customer_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)

    try:
        ws = sh.worksheet(SHEET_NAME)
        existing = ws.row_values(1)
        if existing and existing != HEADERS:
            _log.warning(
                "ROI_프리셋 헤더 불일치 (tenant=%s): existing=%s expected=%s",
                tenant_id, existing, HEADERS,
            )
        return ws
    except gspread.exceptions.WorksheetNotFound:
        pass
    except Exception as e:
        # gspread 버전에 따라 예외 경로가 다를 수 있음
        if "not found" not in str(e).lower():
            raise

    _log.info("ROI_프리셋 시트 없음 → 신규 생성 (tenant=%s)", tenant_id)
    ws = sh.add_worksheet(title=SHEET_NAME, rows=10, cols=len(HEADERS))
    ws.append_row(HEADERS, value_input_option="USER_ENTERED")
    return ws


def get_all_presets(tenant_id: str) -> list:
    """
    슬롯 1, 2, 3 순서로 반환. 빈 슬롯은 None.
    슬롯 1이 시트에 없으면 DEFAULT_PRESET_DATA로 자동 시드 후 반환.

    반환 예:
      [
        {"slot":1, "name":"기본값", "data":{...}, "is_default":True},
        None,
        {"slot":3, "name":"여권형", "data":{...}, "is_default":False},
      ]
    """
    ws = ensure_roi_preset_sheet(tenant_id)
    records = ws.get_all_records()

    slot_map: dict = {}
    for row in records:
        p = _row_to_preset(row)
        if p:
            slot_map[p["slot"]] = p

    # 슬롯 1 없으면 자동 시드
    if 1 not in slot_map:
        _log.info("슬롯 1 자동 시드 (tenant=%s)", tenant_id)
        preset = upsert_preset(
            tenant_id, slot=1, name="기본값",
            data=DEFAULT_PRESET_DATA, is_default=True,
        )
        slot_map[1] = preset

    return [slot_map.get(i) for i in (1, 2, 3)]


def upsert_preset(
    tenant_id: str,
    slot: int,
    name: str,
    data: dict,
    is_default: bool,
) -> dict:
    """
    slot 행이 있으면 업데이트, 없으면 append.
    is_default=True 이면 다른 슬롯들의 is_default를 False로 일괄 변경.

    시트 전체 읽기 → 메모리에서 변경 → 변경된 행 범위만 batch_update.
    전체 시트 덮어쓰기 금지.
    """
    with _PRESET_LOCK:
        ws = ensure_roi_preset_sheet(tenant_id)
        now = datetime.datetime.now().isoformat()
        data_json = json.dumps(data, ensure_ascii=False)

        all_values = ws.get_all_values()

        # 헤더가 없는 빈 시트 처리
        if not all_values or not all_values[0]:
            ws.append_row(HEADERS, value_input_option="USER_ENTERED")
            all_values = ws.get_all_values()

        headers = all_values[0] if all_values else HEADERS

        # 인덱스 조회 (헤더가 다를 경우 HEADERS 기본값 사용)
        def _idx(col: str) -> int:
            try:
                return headers.index(col)
            except ValueError:
                return HEADERS.index(col)

        slot_idx        = _idx("slot")
        name_idx        = _idx("name")
        data_json_idx   = _idx("data_json")
        is_default_idx  = _idx("is_default")
        updated_at_idx  = _idx("updated_at")

        # 대상 행 찾기
        target_row_num = _find_slot_row_num(all_values, slot)

        batch: list = []

        # is_default=True → 다른 슬롯들 False로 변경
        if is_default:
            for i, row in enumerate(all_values[1:], start=2):
                if len(row) > slot_idx and str(row[slot_idx]).strip() != str(slot):
                    col = _col_letter(is_default_idx + 1)
                    batch.append({"range": f"{col}{i}", "values": [["False"]]})

        # 새 행 값 조립
        new_row: list = [""] * max(len(HEADERS), len(headers))
        new_row[slot_idx]       = str(slot)
        new_row[name_idx]       = name
        new_row[data_json_idx]  = data_json
        new_row[is_default_idx] = str(is_default)
        new_row[updated_at_idx] = now
        new_row = new_row[:len(HEADERS)]  # 컬럼 수 맞춤

        if target_row_num is not None:
            # 기존 행 전체 교체
            end_col = _col_letter(len(HEADERS))
            batch.append({
                "range": f"A{target_row_num}:{end_col}{target_row_num}",
                "values": [new_row],
            })

        if batch:
            ws.batch_update(batch, value_input_option="USER_ENTERED")

        if target_row_num is None:
            ws.append_row(new_row, value_input_option="USER_ENTERED")

    return {
        "slot":       slot,
        "name":       name,
        "data":       data,
        "is_default": is_default,
    }


def delete_preset(tenant_id: str, slot: int):
    """
    슬롯 행 삭제.
    - slot=1: 삭제 불가 → DEFAULT_PRESET_DATA로 리셋,
               {"deleted": False, "reset_to_default": True, "preset": {...}} 반환.
    - 슬롯 없음: False 반환.
    - 성공: True 반환.
    """
    if slot == 1:
        preset = upsert_preset(
            tenant_id, slot=1, name="기본값",
            data=DEFAULT_PRESET_DATA, is_default=True,
        )
        return {"deleted": False, "reset_to_default": True, "preset": preset}

    with _PRESET_LOCK:
        ws = ensure_roi_preset_sheet(tenant_id)
        all_values = ws.get_all_values()
        row_num = _find_slot_row_num(all_values, slot)
        if row_num is None:
            return False
        ws.delete_rows(row_num)

    return True


def rename_preset(tenant_id: str, slot: int, new_name: str) -> dict:
    """
    name 컬럼만 변경, updated_at 갱신.
    슬롯이 없으면 ValueError 발생.
    """
    with _PRESET_LOCK:
        ws = ensure_roi_preset_sheet(tenant_id)
        now = datetime.datetime.now().isoformat()

        all_values = ws.get_all_values()
        if not all_values or len(all_values) < 2:
            raise ValueError(f"슬롯 {slot}을 찾을 수 없습니다.")

        headers = all_values[0]

        def _idx(col: str) -> int:
            try:
                return headers.index(col)
            except ValueError:
                return HEADERS.index(col)

        name_idx       = _idx("name")
        updated_at_idx = _idx("updated_at")
        data_json_idx  = _idx("data_json")
        is_default_idx = _idx("is_default")

        row_num = _find_slot_row_num(all_values, slot)
        if row_num is None:
            raise ValueError(f"슬롯 {slot}을 찾을 수 없습니다.")

        ws.batch_update([
            {"range": f"{_col_letter(name_idx + 1)}{row_num}",       "values": [[new_name]]},
            {"range": f"{_col_letter(updated_at_idx + 1)}{row_num}", "values": [[now]]},
        ], value_input_option="USER_ENTERED")

        # 현재 행에서 나머지 필드 읽기 (row_num은 1-based)
        row = all_values[row_num - 1]  # 0-based index

        def _cell(idx: int) -> str:
            return row[idx] if len(row) > idx else ""

        data_raw = _cell(data_json_idx)
        try:
            data = json.loads(data_raw) if data_raw else {}
        except json.JSONDecodeError:
            data = {}
        is_def = _cell(is_default_idx).strip().lower() in ("true", "1")

    return {
        "slot":       slot,
        "name":       new_name,
        "data":       data,
        "is_default": is_def,
    }
