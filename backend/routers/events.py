"""캘린더 일정 라우터 (테넌트 인식) — PG-only(Phase F).

일정(events)은 PostgreSQL(events_pg_service)만 사용한다. PG 미구성 시 조용한 fallback
없이 get_sessionmaker()가 RuntimeError를 낸다. 응답 구조는 기존과 동일
(GET: {date_str: [event_text, ...]} 맵).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, Depends, HTTPException
from backend.auth import get_current_user
from backend.models import EventDateSaveRequest

router = APIRouter()


@router.get("")
def get_events(user: dict = Depends(get_current_user)):
    from backend.services.events_pg_service import get_events_map
    return get_events_map(user["tenant_id"])


@router.post("")
def save_events(req: EventDateSaveRequest, user: dict = Depends(get_current_user)):
    """단일 날짜의 일정을 저장(per-date 교체). 쓰기 실패 시 HTTP 500."""
    date_str = req.date_str.strip()
    if not date_str:
        raise HTTPException(status_code=400, detail="date_str은 필수입니다")
    lines = [l.strip() for l in req.lines if l.strip()]
    from backend.services.events_pg_service import save_events_for_date
    try:
        written = save_events_for_date(user["tenant_id"], date_str, lines)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"일정 저장 실패: {e}")
    print(f"[events POST] PG tenant={user['tenant_id']} date={date_str} written={written}")
    return {"ok": True}


@router.delete("/{date_str}")
def delete_event(date_str: str, user: dict = Depends(get_current_user)):
    """특정 날짜의 모든 이벤트 삭제 — 다른 날짜 건드리지 않음 (멱등)."""
    from backend.services.events_pg_service import delete_events_for_date
    deleted = delete_events_for_date(user["tenant_id"], date_str)
    return {"ok": True, "deleted": deleted}
