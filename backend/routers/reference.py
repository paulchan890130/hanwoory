"""업무참고 라우터 - 테넌트별 work_sheet_key 기반 시트 탭 조회"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, Depends, HTTPException, Query
from backend.auth import get_current_user
from backend.services.tenant_service import get_work_sheet_key, _get_spreadsheet

router = APIRouter()


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
    sheet_key = get_work_sheet_key(tenant_id)
    try:
        sh = _get_spreadsheet(sheet_key)
        titles = [ws.title for ws in sh.worksheets()]
        return {"sheet_key": sheet_key, "sheets": titles}
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
