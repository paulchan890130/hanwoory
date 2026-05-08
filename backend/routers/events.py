"""캘린더 일정 라우터 (테넌트 인식)

핵심 원칙:
- ws.clear() 절대 금지 — 전체 시트 삭제 위험
- 날짜 단위(per-date) row 조작만 허용
- 쓰기 실패 시 HTTP 500 (HTTP 200 + ok:false 금지)
- 쓰기 후 검증 필수
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, Depends, HTTPException
from backend.auth import get_current_user
from backend.models import EventDateSaveRequest
from backend.services.tenant_service import (
    read_sheet, get_worksheet,
    invalidate_read_cache, get_invalidation_token,
)
from backend.services.cache_service import cache_get, cache_set, cache_invalidate

router = APIRouter()

EVENTS_HEADER = ["date_str", "event_text"]
_CACHE_EVENTS = "events"
_TTL_EVENTS = 30.0  # seconds


# ── GET ───────────────────────────────────────────────────────────────────────

@router.get("")
def get_events(user: dict = Depends(get_current_user)):
    import time as _time
    from config import EVENTS_SHEET_NAME
    tenant_id = user["tenant_id"]

    cached = cache_get(tenant_id, _CACHE_EVENTS)
    if cached is not None:
        total = sum(len(v) for v in cached.values())
        print(f"[events GET] HIT tenant={tenant_id} event_count={total}")
        return cached

    # 읽기 전 무효화 토큰 스냅샷 — 읽는 도중 POST가 캐시를 무효화했으면 cache_set 건너뜀
    inv_token = get_invalidation_token(tenant_id, EVENTS_SHEET_NAME)

    t0 = _time.time()
    records = read_sheet(EVENTS_SHEET_NAME, tenant_id, default_if_empty=[])
    result: dict = {}
    for r in records:
        d = r.get("date_str", "")
        t = r.get("event_text", "")
        if d:
            result.setdefault(d, []).append(t)

    total = sum(len(v) for v in result.values())
    print(f"[events GET] MISS tenant={tenant_id} rows={len(records)} event_count={total} total={_time.time()-t0:.2f}s")

    if get_invalidation_token(tenant_id, EVENTS_SHEET_NAME) == inv_token:
        cache_set(tenant_id, _CACHE_EVENTS, result, _TTL_EVENTS)
    else:
        print(f"[events GET] skip cache_set — concurrent write detected during read")

    return result


# ── POST (per-date 저장, ws.clear 없음) ──────────────────────────────────────

@router.post("")
def save_events(req: EventDateSaveRequest, user: dict = Depends(get_current_user)):
    """
    단일 날짜의 일정을 저장한다.

    - ws.clear() 사용 안 함 — 다른 날짜 데이터 절대 건드리지 않음
    - 해당 날짜 기존 행을 row-level 삭제 후 새 행 추가
    - 안전 순서: append 먼저 → 기존 행 삭제 (실패 시 중복 생기지만 소실 없음)
    - 쓰기 실패 시 HTTP 500 반환 (200 + ok:false 금지)
    - 쓰기 후 검증 수행
    """
    from config import EVENTS_SHEET_NAME
    tenant_id = user["tenant_id"]
    date_str = req.date_str.strip()
    lines = [l.strip() for l in req.lines if l.strip()]

    if not date_str:
        raise HTTPException(status_code=400, detail="date_str은 필수입니다")

    # 1. 현재 시트 읽기
    try:
        ws = get_worksheet(EVENTS_SHEET_NAME, tenant_id)
        all_values = ws.get_all_values()
    except Exception as e:
        print(f"[events POST] sheet read 실패: {e}")
        raise HTTPException(status_code=500, detail=f"일정 시트 읽기 실패: {e}")

    # 헤더가 없으면 초기화
    if not all_values:
        try:
            ws.update("A1", [EVENTS_HEADER], value_input_option="USER_ENTERED")
            all_values = [EVENTS_HEADER]
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"일정 시트 헤더 초기화 실패: {e}")

    # 2. 삭제 대상 row 번호 수집 (1-based, row1=헤더, data는 row2~)
    old_row_nums = []
    for idx, row in enumerate(all_values[1:], start=2):
        if row and row[0].strip() == date_str:
            old_row_nums.append(idx)

    # 3. 새 행 먼저 추가 (실패 시 기존 데이터 그대로, 소실 없음)
    if lines:
        new_rows = [[date_str, line] for line in lines]
        try:
            ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        except Exception as e:
            print(f"[events POST] append 실패: {e}")
            raise HTTPException(status_code=500, detail=f"일정 행 추가 실패: {e}")

    # 4. 기존 행 삭제 (역순 — row 번호 밀림 방지)
    deleted = 0
    for row_num in sorted(old_row_nums, reverse=True):
        try:
            ws.delete_rows(row_num)
            deleted += 1
        except Exception as e:
            # 중복이 남을 수 있지만 데이터 소실보다 안전
            print(f"[events POST] delete_rows({row_num}) 실패 (중복 가능성): {e}")

    # 5. 쓰기 검증 — 저장된 행이 실제로 존재하는지 확인
    if lines:
        try:
            verify = ws.get_all_values()
            verify_data = verify[1:] if verify else []
            saved = [r for r in verify_data if r and r[0].strip() == date_str]
            if not saved:
                raise HTTPException(
                    status_code=500,
                    detail="일정 저장 검증 실패: 저장된 행을 시트에서 찾을 수 없습니다"
                )
            print(f"[events POST] 검증 OK: date={date_str} saved_rows={len(saved)}")
        except HTTPException:
            raise
        except Exception as e:
            print(f"[events POST] 검증 실패: {e}")
            raise HTTPException(status_code=500, detail=f"일정 저장 검증 실패: {e}")

    # 6. 캐시 무효화
    invalidate_read_cache(tenant_id, EVENTS_SHEET_NAME)
    cache_invalidate(tenant_id, _CACHE_EVENTS)
    print(
        f"[events POST] tenant={tenant_id} date={date_str} "
        f"lines={len(lines)} deleted_old={deleted} invalidated={_CACHE_EVENTS!r}"
    )

    return {"ok": True}


# ── DELETE (per-date, ws.clear 없음) ─────────────────────────────────────────

@router.delete("/{date_str}")
def delete_event(date_str: str, user: dict = Depends(get_current_user)):
    """특정 날짜의 모든 이벤트 삭제 — 다른 날짜 건드리지 않음."""
    from config import EVENTS_SHEET_NAME
    tenant_id = user["tenant_id"]

    # 1. 현재 시트 읽기
    try:
        ws = get_worksheet(EVENTS_SHEET_NAME, tenant_id)
        all_values = ws.get_all_values()
    except Exception as e:
        print(f"[events DELETE] sheet read 실패: {e}")
        raise HTTPException(status_code=500, detail=f"일정 시트 읽기 실패: {e}")

    old_row_nums = []
    for idx, row in enumerate(all_values[1:] if all_values else [], start=2):
        if row and row[0].strip() == date_str:
            old_row_nums.append(idx)

    if not old_row_nums:
        # 삭제할 행 없음 — 정상 (멱등)
        invalidate_read_cache(tenant_id, EVENTS_SHEET_NAME)
        cache_invalidate(tenant_id, _CACHE_EVENTS)
        print(f"[events DELETE] tenant={tenant_id} date_str={date_str} nothing to delete")
        return {"ok": True, "deleted": 0}

    # 2. 역순으로 행 삭제
    deleted = 0
    for row_num in sorted(old_row_nums, reverse=True):
        try:
            ws.delete_rows(row_num)
            deleted += 1
        except Exception as e:
            print(f"[events DELETE] delete_rows({row_num}) 실패: {e}")
            raise HTTPException(status_code=500, detail=f"일정 행 삭제 실패 (row {row_num}): {e}")

    # 3. 캐시 무효화
    invalidate_read_cache(tenant_id, EVENTS_SHEET_NAME)
    cache_invalidate(tenant_id, _CACHE_EVENTS)
    print(f"[events DELETE] tenant={tenant_id} date_str={date_str} deleted={deleted} invalidated={_CACHE_EVENTS!r}")

    return {"ok": True, "deleted": deleted}
