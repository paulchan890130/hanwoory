"""
backend/services/reference_edit_service.py

업무참고 시트 인라인 편집 서비스 함수.

핵심 원칙:
  - 변경된 단위만 저장 (전체 시트 읽기/쓰기 절대 금지)
  - 모든 함수는 work_sheet_key 기반 (get_work_sheet_key 사용)
  - 행 높이 / 열 너비 변경은 spreadsheet.batch_update() (Sheets API v4 batchUpdate)
"""
import logging
from typing import Optional

import gspread

from backend.services.tenant_service import get_work_sheet_key, _get_spreadsheet

_log = logging.getLogger("reference_edit_service")


# ── 공통 헬퍼 ─────────────────────────────────────────────────────────────────

def _get_work_ws(tenant_id: str, sheet_name: str):
    """
    work_sheet_key → spreadsheet → worksheet 반환.
    worksheet 없으면 gspread.exceptions.WorksheetNotFound 예외.
    """
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    return sh, sh.worksheet(sheet_name)


def _get_header_col_index(ws: gspread.Worksheet, col_key: str) -> int:
    """
    헤더 행(1행)만 읽어서 col_key의 1-based 열 번호 반환.
    없으면 ValueError.
    전체 시트 읽기 금지 — ws.row_values(1) 만 사용.
    """
    headers = ws.row_values(1)
    try:
        return headers.index(col_key) + 1  # 1-based
    except ValueError:
        raise ValueError(f"열을 찾을 수 없습니다: {col_key!r}")


# ── 셀 수정 ───────────────────────────────────────────────────────────────────

def update_single_cell(
    tenant_id: str, sheet_name: str,
    row_index: int, col_key: str, value: str,
) -> str:
    """
    row_index(0-based, 헤더 제외) 행, col_key 열의 셀 1개만 업데이트.
    헤더 행은 row 1, 데이터 첫 행은 row 2 → sheet_row = row_index + 2.
    반환: 저장된 값.
    """
    sh, ws = _get_work_ws(tenant_id, sheet_name)
    col_num = _get_header_col_index(ws, col_key)
    ws.update_cell(row_index + 2, col_num, value)
    return value


# ── 행 추가 ───────────────────────────────────────────────────────────────────

def insert_row_after(
    tenant_id: str, sheet_name: str,
    insert_after: Optional[int],
    values_dict: dict,
) -> int:
    """
    insert_after(0-based, 헤더 제외): None이면 맨 끝 append.
    values_dict: {col_key: value} — 없는 키는 빈 문자열.
    반환: 새 행의 row_index(0-based).
    헤더만 읽어서 열 순서 파악 (전체 시트 읽기 금지).
    """
    sh, ws = _get_work_ws(tenant_id, sheet_name)
    headers = ws.row_values(1)
    row_data = [str(values_dict.get(h, "")) for h in headers]

    if insert_after is None:
        ws.append_row(row_data, value_input_option="USER_ENTERED")
        # row_count는 그리드 크기이므로 정확한 데이터 행 수 대신 0 반환
        # 프론트엔드의 낙관적 업데이트가 실제 위치를 관리함
        return 0
    else:
        # 헤더(row 1) + insert_after 행(0-based) + 1 (다음 위치)
        insert_row_num = insert_after + 3
        ws.insert_rows([row_data], row=insert_row_num,
                       value_input_option="USER_ENTERED")
        return insert_after + 1


# ── 행 삭제 ───────────────────────────────────────────────────────────────────

def delete_single_row(tenant_id: str, sheet_name: str, row_index: int) -> bool:
    """row_index(0-based, 헤더 제외) 행 삭제."""
    sh, ws = _get_work_ws(tenant_id, sheet_name)
    ws.delete_rows(row_index + 2)
    return True


# ── 행 순서 변경 ──────────────────────────────────────────────────────────────

def reorder_row(
    tenant_id: str, sheet_name: str,
    from_index: int, to_index: int,
) -> bool:
    """
    from_index 행을 to_index 위치로 이동 (둘 다 0-based, 헤더 제외).
    1. 해당 행 데이터만 읽기 (ws.row_values)
    2. 원래 위치 삭제
    3. to_index + 2 위치에 삽입

    삭제 후 to_index + 2가 항상 올바른 이유:
      - to_index < from_index: 삭제로 인한 인덱스 변화 없음
      - to_index > from_index: 삭제 후 원본 to_index 항목이 to_index-1로 이동하지만
        insert_rows의 row 파라미터는 삽입 "이후" 위치이므로 보정 불필요
    """
    if from_index == to_index:
        return True
    sh, ws = _get_work_ws(tenant_id, sheet_name)
    row_data = ws.row_values(from_index + 2)
    ws.delete_rows(from_index + 2)
    ws.insert_rows([row_data], row=to_index + 2,
                   value_input_option="USER_ENTERED")
    return True


# ── 행 높이 변경 ──────────────────────────────────────────────────────────────

def update_row_height(
    tenant_id: str, sheet_name: str,
    row_index: int, pixel_height: int,
) -> bool:
    """
    row_index(0-based, 헤더 제외) 행의 높이를 pixel_height로 변경.
    최소/최대 클램프는 라우터에서 처리.
    spreadsheet.batch_update() 사용 (ws.batch_update 아님).
    startIndex는 시트 전체 기준 0-based: 헤더=0, 데이터 첫 행=1.
    """
    sh, ws = _get_work_ws(tenant_id, sheet_name)
    body = {
        "requests": [{
            "updateDimensionProperties": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "ROWS",
                    "startIndex": row_index + 1,   # 헤더(0) 제외, 데이터 시작 = 1
                    "endIndex":   row_index + 2,
                },
                "properties": {"pixelSize": pixel_height},
                "fields": "pixelSize",
            }
        }]
    }
    sh.batch_update(body)
    return True


# ── 열 추가 ───────────────────────────────────────────────────────────────────

def insert_column(
    tenant_id: str, sheet_name: str,
    col_name: str,
    insert_after_col: Optional[str],
) -> bool:
    """
    insert_after_col: None이면 맨 끝. 열 이름이면 그 다음에 삽입.
    1. 헤더만 읽어서 삽입 위치 결정
    2. insertDimension (Sheets API v4) 으로 열 삽입
    3. 헤더 셀에 col_name 입력
    """
    sh, ws = _get_work_ws(tenant_id, sheet_name)
    headers = ws.row_values(1)

    if insert_after_col is None:
        col_insert_index = len(headers)           # 0-based, 맨 끝
    else:
        try:
            col_insert_index = headers.index(insert_after_col) + 1
        except ValueError:
            col_insert_index = len(headers)

    body = {
        "requests": [{
            "insertDimension": {
                "range": {
                    "sheetId":   ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": col_insert_index,
                    "endIndex":   col_insert_index + 1,
                },
                "inheritFromBefore": col_insert_index > 0,
            }
        }]
    }
    sh.batch_update(body)
    ws.update_cell(1, col_insert_index + 1, col_name)
    return True


# ── 열 삭제 ───────────────────────────────────────────────────────────────────

def delete_column(tenant_id: str, sheet_name: str, col_key: str) -> bool:
    """
    헤더만 읽어서 열 번호 파악 → deleteDimension (Sheets API v4) 호출.
    """
    sh, ws = _get_work_ws(tenant_id, sheet_name)
    col_num   = _get_header_col_index(ws, col_key)   # 1-based
    col_index = col_num - 1                           # 0-based

    body = {
        "requests": [{
            "deleteDimension": {
                "range": {
                    "sheetId":   ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": col_index,
                    "endIndex":   col_index + 1,
                }
            }
        }]
    }
    sh.batch_update(body)
    return True


# ── 열 이름 변경 ──────────────────────────────────────────────────────────────

def rename_column_header(
    tenant_id: str, sheet_name: str,
    old_name: str, new_name: str,
) -> bool:
    """헤더 행(row 1)의 해당 셀 1개만 변경."""
    sh, ws = _get_work_ws(tenant_id, sheet_name)
    col_num = _get_header_col_index(ws, old_name)
    ws.update_cell(1, col_num, new_name)
    return True


# ── 열 너비 변경 ──────────────────────────────────────────────────────────────

def update_column_width(
    tenant_id: str, sheet_name: str,
    col_key: str, pixel_width: int,
) -> bool:
    """
    spreadsheet.batch_update() → updateDimensionProperties COLUMNS.
    최소/최대 클램프는 라우터에서 처리.
    """
    sh, ws = _get_work_ws(tenant_id, sheet_name)
    col_num   = _get_header_col_index(ws, col_key)
    col_index = col_num - 1   # 0-based

    body = {
        "requests": [{
            "updateDimensionProperties": {
                "range": {
                    "sheetId":   ws.id,
                    "dimension": "COLUMNS",
                    "startIndex": col_index,
                    "endIndex":   col_index + 1,
                },
                "properties": {"pixelSize": pixel_width},
                "fields": "pixelSize",
            }
        }]
    }
    sh.batch_update(body)
    return True


# ── 시트 탭 추가 ──────────────────────────────────────────────────────────────

def add_sheet_tab(tenant_id: str, sheet_name: str) -> bool:
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    sh.add_worksheet(title=sheet_name, rows=20, cols=10)
    return True


# ── 시트 탭 삭제 ──────────────────────────────────────────────────────────────

def delete_sheet_tab(tenant_id: str, sheet_name: str) -> bool:
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    ws = sh.worksheet(sheet_name)
    sh.del_worksheet(ws)
    return True


# ── 시트 탭 이름 변경 ─────────────────────────────────────────────────────────

def rename_sheet_tab(tenant_id: str, old_name: str, new_name: str) -> bool:
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    ws = sh.worksheet(old_name)
    body = {
        "requests": [{
            "updateSheetProperties": {
                "properties": {
                    "sheetId": ws.id,
                    "title":   new_name,
                },
                "fields": "title",
            }
        }]
    }
    sh.batch_update(body)
    return True
