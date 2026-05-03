"""업무참고 라우터 - 테넌트별 work_sheet_key 기반 시트 탭 조회 + 인라인 편집"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from backend.auth import get_current_user
from backend.services.tenant_service import get_work_sheet_key, _get_spreadsheet
from backend.services.cache_service import cache_get, cache_set

router = APIRouter()

# ── 편집 요청 모델 ────────────────────────────────────────────────────────────

class CellUpdateBody(BaseModel):
    sheet_name: str
    row_index: int
    col_key: str
    value: str

class RowInsertBody(BaseModel):
    sheet_name: str
    insert_after: Optional[int] = None
    values: dict = {}

class RowDeleteBody(BaseModel):
    sheet_name: str
    row_index: int

class RowReorderBody(BaseModel):
    sheet_name: str
    from_index: int
    to_index: int

class RowHeightBody(BaseModel):
    sheet_name: str
    row_index: int
    pixel_height: int

class ColInsertBody(BaseModel):
    sheet_name: str
    col_name: str
    insert_after: Optional[str] = None

class ColDeleteBody(BaseModel):
    sheet_name: str
    col_key: str

class ColRenameBody(BaseModel):
    sheet_name: str
    old_name: str
    new_name: str

class ColWidthBody(BaseModel):
    sheet_name: str
    col_key: str
    pixel_width: int

class SheetCreateBody(BaseModel):
    sheet_name: str

class SheetDeleteBody(BaseModel):
    sheet_name: str

class SheetRenameBody(BaseModel):
    old_name: str
    new_name: str

_CACHE_REF_SHEETS = "reference:sheets"
_TTL_REF = 30.0  # seconds


def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


@router.get("/sheets")
def list_sheets(user: dict = Depends(get_current_user)):
    """테넌트의 업무정리 스프레드시트에 있는 시트 이름 목록 반환"""
    tenant_id = user["tenant_id"]
    cached = cache_get(tenant_id, _CACHE_REF_SHEETS)
    if cached is not None:
        return cached
    sheet_key = get_work_sheet_key(tenant_id)
    try:
        sh = _get_spreadsheet(sheet_key)
        titles = [ws.title for ws in sh.worksheets()]
        result = {"sheet_key": sheet_key, "sheets": titles}
        cache_set(tenant_id, _CACHE_REF_SHEETS, result, _TTL_REF)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"시트 목록 조회 실패: {e}")


@router.get("/data")
def get_sheet_data(
    sheet: str = Query(..., description="시트명"),
    user: dict = Depends(get_current_user),
):
    """특정 시트의 데이터 반환 (헤더 + 행 목록)"""
    tenant_id = user["tenant_id"]
    sheet_key = get_work_sheet_key(tenant_id)
    try:
        sh = _get_spreadsheet(sheet_key)
        ws = sh.worksheet(sheet)
        values = ws.get_all_values()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"시트 데이터 조회 실패: {e}")

    if not values:
        return {"sheet": sheet, "headers": [], "rows": []}

    raw_header = values[0]
    data_rows = values[1:]

    # 중복 헤더 처리
    header: list[str] = []
    used: dict[str, int] = {}
    for idx, h in enumerate(raw_header):
        name = (h or "").strip() or f"col_{idx + 1}"
        if name in used:
            used[name] += 1
            name = f"{name}_{used[name]}"
        else:
            used[name] = 1
        header.append(name)

    # 빈 행 제거
    rows = [dict(zip(header, row)) for row in data_rows if any(c.strip() for c in row)]

    return {"sheet": sheet, "headers": header, "rows": rows}


# ── 편집 엔드포인트 ───────────────────────────────────────────────────────────
# 기존 GET 엔드포인트 수정 없이 아래에 추가.

def _edit_svc():
    """편집 서비스 지연 import (순환 참조 방지)."""
    from backend.services import reference_edit_service as svc
    return svc


def _tenant(user: dict) -> str:
    return user.get("tenant_id", "")


# ── 셀 수정 ──────────────────────────────────────────────────────────────────

@router.patch("/cell")
def patch_cell(body: CellUpdateBody, user: dict = Depends(get_current_user)):
    """셀 1개 수정 — 해당 셀만 Sheets API로 업데이트."""
    try:
        svc = _edit_svc()
        val = svc.update_single_cell(
            _tenant(user), body.sheet_name,
            body.row_index, body.col_key, body.value,
        )
        return {"success": True, "value": val}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"셀 저장 실패: {e}")


# ── 행 추가 ──────────────────────────────────────────────────────────────────

@router.post("/row")
def post_row(body: RowInsertBody, user: dict = Depends(get_current_user)):
    """행 삽입 — insert_after 다음 위치 (None이면 맨 끝)."""
    try:
        svc = _edit_svc()
        new_idx = svc.insert_row_after(
            _tenant(user), body.sheet_name,
            body.insert_after, body.values,
        )
        return {"success": True, "row_index": new_idx}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"행 추가 실패: {e}")


# ── 행 삭제 ──────────────────────────────────────────────────────────────────

@router.delete("/row")
def delete_row(body: RowDeleteBody, user: dict = Depends(get_current_user)):
    """행 삭제 — row_index 행만 삭제."""
    try:
        svc = _edit_svc()
        svc.delete_single_row(_tenant(user), body.sheet_name, body.row_index)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"행 삭제 실패: {e}")


# ── 행 순서 변경 ─────────────────────────────────────────────────────────────

@router.patch("/row/reorder")
def patch_row_reorder(body: RowReorderBody, user: dict = Depends(get_current_user)):
    """행 순서 변경 — from_index → to_index 이동."""
    try:
        svc = _edit_svc()
        svc.reorder_row(_tenant(user), body.sheet_name, body.from_index, body.to_index)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"행 순서 변경 실패: {e}")


# ── 행 높이 변경 ─────────────────────────────────────────────────────────────

@router.patch("/row/height")
def patch_row_height(body: RowHeightBody, user: dict = Depends(get_current_user)):
    """행 높이 변경 — updateDimensionProperties 사용."""
    pixel_height = max(21, min(400, body.pixel_height))
    try:
        svc = _edit_svc()
        svc.update_row_height(_tenant(user), body.sheet_name, body.row_index, pixel_height)
        return {"success": True, "pixel_height": pixel_height}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"행 높이 변경 실패: {e}")


# ── 열 추가 ──────────────────────────────────────────────────────────────────

@router.post("/column")
def post_column(body: ColInsertBody, user: dict = Depends(get_current_user)):
    """열 삽입 — insert_after_col 다음 (None이면 맨 끝)."""
    try:
        svc = _edit_svc()
        svc.insert_column(_tenant(user), body.sheet_name, body.col_name, body.insert_after)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"열 추가 실패: {e}")


# ── 열 삭제 ──────────────────────────────────────────────────────────────────

@router.delete("/column")
def delete_column(body: ColDeleteBody, user: dict = Depends(get_current_user)):
    """열 삭제 — deleteDimension 사용."""
    try:
        svc = _edit_svc()
        svc.delete_column(_tenant(user), body.sheet_name, body.col_key)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"열 삭제 실패: {e}")


# ── 열 이름 변경 ─────────────────────────────────────────────────────────────

@router.patch("/column/rename")
def patch_column_rename(body: ColRenameBody, user: dict = Depends(get_current_user)):
    """열 이름 변경 — 헤더 셀 1개만 업데이트."""
    try:
        svc = _edit_svc()
        svc.rename_column_header(_tenant(user), body.sheet_name, body.old_name, body.new_name)
        return {"success": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"열 이름 변경 실패: {e}")


# ── 열 너비 변경 ─────────────────────────────────────────────────────────────

@router.patch("/column/width")
def patch_column_width(body: ColWidthBody, user: dict = Depends(get_current_user)):
    """열 너비 변경 — updateDimensionProperties 사용."""
    pixel_width = max(50, min(500, body.pixel_width))
    try:
        svc = _edit_svc()
        svc.update_column_width(_tenant(user), body.sheet_name, body.col_key, pixel_width)
        return {"success": True, "pixel_width": pixel_width}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"열 너비 변경 실패: {e}")


# ── 시트 탭 추가 ─────────────────────────────────────────────────────────────

@router.post("/sheet")
def post_sheet(body: SheetCreateBody, user: dict = Depends(get_current_user)):
    """시트 탭 추가."""
    try:
        svc = _edit_svc()
        svc.add_sheet_tab(_tenant(user), body.sheet_name)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"시트 탭 추가 실패: {e}")


# ── 시트 탭 삭제 ─────────────────────────────────────────────────────────────

@router.delete("/sheet")
def delete_sheet(body: SheetDeleteBody, user: dict = Depends(get_current_user)):
    """시트 탭 삭제."""
    try:
        svc = _edit_svc()
        svc.delete_sheet_tab(_tenant(user), body.sheet_name)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"시트 탭 삭제 실패: {e}")


# ── 시트 탭 이름 변경 ────────────────────────────────────────────────────────

@router.patch("/sheet/rename")
def patch_sheet_rename(body: SheetRenameBody, user: dict = Depends(get_current_user)):
    """시트 탭 이름 변경 — updateSheetProperties 사용."""
    try:
        svc = _edit_svc()
        svc.rename_sheet_tab(_tenant(user), body.old_name, body.new_name)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"시트 탭 이름 변경 실패: {e}")
