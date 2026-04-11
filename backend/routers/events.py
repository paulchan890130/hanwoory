"""캘린더 일정 라우터 (테넌트 인식)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, Depends
from backend.auth import get_current_user
from backend.models import EventsSaveRequest
from backend.services.tenant_service import read_sheet, upsert_sheet, get_worksheet
from backend.services.cache_service import cache_get, cache_set, cache_invalidate

router = APIRouter()

EVENTS_HEADER = ["date_str", "event_text"]
_CACHE_EVENTS = "events"
_TTL_EVENTS = 3.0  # 3 seconds — calendar needs near-immediate post-edit freshness


@router.get("")
def get_events(user: dict = Depends(get_current_user)):
    from config import EVENTS_SHEET_NAME
    tenant_id = user["tenant_id"]
    cached = cache_get(tenant_id, _CACHE_EVENTS)
    if cached is not None:
        return cached
    records = read_sheet(EVENTS_SHEET_NAME, tenant_id, default_if_empty=[])
    result: dict = {}
    for r in records:
        d = r.get("date_str", "")
        t = r.get("event_text", "")
        if d:
            result.setdefault(d, []).append(t)
    cache_set(tenant_id, _CACHE_EVENTS, result, _TTL_EVENTS)
    return result


@router.post("")
def save_events(req: EventsSaveRequest, user: dict = Depends(get_current_user)):
    from config import EVENTS_SHEET_NAME
    tenant_id = user["tenant_id"]
    rows = [{"date_str": e.date_str, "event_text": e.event_text} for e in req.events]

    # 전체 덮어쓰기: 워크시트를 직접 열어서 clear + 재작성
    try:
        ws = get_worksheet(EVENTS_SHEET_NAME, tenant_id)
        ws.clear()
        if rows:
            data = [EVENTS_HEADER] + [[r["date_str"], r["event_text"]] for r in rows]
            ws.update("A1", data, value_input_option="USER_ENTERED")
        cache_invalidate(tenant_id, _CACHE_EVENTS)
        return {"ok": True}
    except Exception as e:
        print(f"[events] save_events 실패: {e}")
        return {"ok": False}


@router.delete("/{date_str}")
def delete_event(date_str: str, user: dict = Depends(get_current_user)):
    """특정 날짜의 모든 이벤트 삭제"""
    from config import EVENTS_SHEET_NAME
    tenant_id = user["tenant_id"]
    records = read_sheet(EVENTS_SHEET_NAME, tenant_id, default_if_empty=[])
    filtered = [r for r in records if r.get("date_str", "") != date_str]

    try:
        ws = get_worksheet(EVENTS_SHEET_NAME, tenant_id)
        ws.clear()
        if filtered:
            data = [EVENTS_HEADER] + [[r["date_str"], r["event_text"]] for r in filtered]
            ws.update("A1", data, value_input_option="USER_ENTERED")
        cache_invalidate(tenant_id, _CACHE_EVENTS)
        return {"ok": True}
    except Exception as e:
        print(f"[events] delete_event 실패: {e}")
        return {"ok": False}
