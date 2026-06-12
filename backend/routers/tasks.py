"""업무 라우터 - 예정/진행/완료 업무 CRUD (테넌트 인식) — PG-only(Phase D).

업무 3종(진행/예정/완료)은 PostgreSQL(tasks_pg_service)만 사용한다. Google Sheets
(진행업무/예정업무/완료업무 탭) 런타임 read/write 및 work_sheet_key 기반 라우팅은 제거됐다.
PG 미구성 시 조용한 Sheets fallback 없이 get_sessionmaker()가 RuntimeError를 낸다.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_current_user
from backend.models import (
    ActiveTask, PlannedTask, CompletedTask,
    CompleteTasksRequest, DeleteTasksRequest,
    BatchProgressRequest, BatchMoneyRequest,
)

router = APIRouter()


# ────────────────────────────── 진행업무 ──────────────────────────────────────

_CAT_RANK = {c: i for i, c in enumerate(["출입국", "전자민원", "공증", "여권", "초청", "영주권", "기타"])}
_MAX_NS = 9999999999999999999


def _sort_key_active(t: dict):
    """정렬: 체크 조합 순서(없음 → 접수 → 접수+처리 → 접수+처리+보관중), 각 그룹 내 날짜 오름차순."""
    import datetime as _dt

    cat_rank = _CAT_RANK.get(t.get("category", "기타"), 99)

    reception  = bool((t.get("reception",  "") or "").strip())
    processing = bool((t.get("processing", "") or "").strip())
    storage    = bool((t.get("storage",    "") or "").strip())

    if storage:
        status_rank = 3
    elif processing:
        status_rank = 2
    elif reception:
        status_rank = 1
    else:
        status_rank = 0

    raw_date = t.get("date", "") or ""
    try:
        dt_date = _dt.date.fromisoformat(raw_date[:10])
        date_ns = int(_dt.datetime.combine(dt_date, _dt.time.min).timestamp() * 1e9)
    except Exception:
        date_ns = _MAX_NS

    return (status_rank, cat_rank, date_ns)


@router.get("/active", response_model=List[dict])
def get_active_tasks(user: dict = Depends(get_current_user)):
    from backend.services.tasks_pg_service import list_active
    tasks = list_active(user["tenant_id"])
    tasks.sort(key=_sort_key_active)
    return tasks


@router.post("/active", response_model=dict)
def add_active_task(task: ActiveTask, user: dict = Depends(get_current_user)):
    if not task.id:
        task.id = str(uuid.uuid4())
    rec = {k: ("" if v is None else str(v)) for k, v in task.model_dump().items()}
    from backend.services.tasks_pg_service import upsert_active
    return upsert_active(user["tenant_id"], rec)


@router.put("/active/{task_id}", response_model=dict)
def update_active_task(task_id: str, task: ActiveTask, user: dict = Depends(get_current_user)):
    # Partial update: only fields explicitly sent by the client are written.
    changes = {k: ("" if v is None else str(v))
               for k, v in task.model_dump(exclude_unset=True).items()}
    changes["id"] = task_id
    from backend.services.tasks_pg_service import patch_active, upsert_active
    result = patch_active(user["tenant_id"], task_id, changes)
    if result is None:
        result = upsert_active(user["tenant_id"], changes)  # create if not exists
    return result


@router.patch("/active/batch-progress")
def batch_update_active_progress(req: BatchProgressRequest, user: dict = Depends(get_current_user)):
    """진행업무 접수/처리/보관중 일괄 업데이트 — PG-only."""
    from backend.services.tasks_pg_service import patch_active
    tenant_id = user["tenant_id"]
    n = 0
    for upd in req.updates:
        ok = patch_active(tenant_id, upd.id, {
            "reception": upd.reception,
            "processing": upd.processing,
            "storage": upd.storage,
        })
        if ok is not None:
            n += 1
    return {"updated": n}


@router.patch("/active/batch-money")
def batch_update_active_money(req: BatchMoneyRequest, user: dict = Depends(get_current_user)):
    """진행업무 금액 필드 일괄 부분 업데이트 — PG-only. 지정 row의 지정 필드만 변경.
    중복/미존재 id 는 409로 fail-fast (어떤 row도 건드리지 않음)."""
    from backend.services.tasks_pg_service import patch_active, list_active
    tenant_id = user["tenant_id"]
    ALLOWED = {"transfer", "cash", "card", "stamp", "receivable", "planned_expense"}

    # 중복/미존재 id 사전 검증 (PG 기준)
    id_to_count: dict = {}
    for row in list_active(tenant_id):
        rid = str(row.get("id", "")).strip()
        if rid:
            id_to_count[rid] = id_to_count.get(rid, 0) + 1
    results: dict = {"updated": [], "not_found": [], "duplicate_id": []}
    for upd in req.updates:
        rid = upd.id.strip()
        c = id_to_count.get(rid, 0)
        if c == 0:
            results["not_found"].append(rid)
        elif c > 1:
            results["duplicate_id"].append(rid)
    if results["duplicate_id"] or results["not_found"]:
        raise HTTPException(status_code=409, detail=results)

    n = 0
    for upd in req.updates:
        field_changes = upd.changes.model_dump(exclude_none=True)
        safe_changes = {k: str(v) for k, v in field_changes.items() if k in ALLOWED}
        if patch_active(tenant_id, upd.id.strip(), safe_changes) is not None:
            n += 1
    return {"updated": n}


@router.delete("/active")
def delete_active_tasks(req: DeleteTasksRequest, user: dict = Depends(get_current_user)):
    from backend.services.tasks_pg_service import delete_active as _pg_del
    return {"deleted": _pg_del(user["tenant_id"], req.task_ids)}


@router.post("/active/complete")
def complete_tasks(req: CompleteTasksRequest, user: dict = Depends(get_current_user)):
    """진행업무 → 완료업무 이동 — PG-only."""
    from backend.services.tasks_pg_service import complete_active
    return {"completed": complete_active(user["tenant_id"], req.task_ids)}


# ────────────────────────────── 예정업무 ──────────────────────────────────────

@router.get("/planned", response_model=List[dict])
def get_planned_tasks(user: dict = Depends(get_current_user)):
    from backend.services.tasks_pg_service import list_planned
    return list_planned(user["tenant_id"])


@router.post("/planned", response_model=dict)
def add_planned_task(task: PlannedTask, user: dict = Depends(get_current_user)):
    if not task.id:
        task.id = str(uuid.uuid4())
    rec = {k: ("" if v is None else str(v)) for k, v in task.model_dump().items()}
    from backend.services.tasks_pg_service import upsert_planned
    return upsert_planned(user["tenant_id"], rec)


@router.put("/planned/{task_id}", response_model=dict)
def update_planned_task(task_id: str, task: PlannedTask, user: dict = Depends(get_current_user)):
    changes = {k: ("" if v is None else str(v))
               for k, v in task.model_dump(exclude_unset=True).items()}
    changes["id"] = task_id
    from backend.services.tasks_pg_service import upsert_planned
    return upsert_planned(user["tenant_id"], changes)


@router.delete("/planned")
def delete_planned_tasks(req: DeleteTasksRequest, user: dict = Depends(get_current_user)):
    from backend.services.tasks_pg_service import delete_planned as _pg_del
    return {"deleted": _pg_del(user["tenant_id"], req.task_ids)}


# ────────────────────────────── 완료업무 ──────────────────────────────────────

@router.get("/completed", response_model=List[dict])
def get_completed_tasks(user: dict = Depends(get_current_user)):
    from backend.services.tasks_pg_service import list_completed
    return list_completed(user["tenant_id"])


@router.put("/completed/{task_id}", response_model=dict)
def update_completed_task(task_id: str, task: CompletedTask, user: dict = Depends(get_current_user)):
    task.id = task_id
    rec = {k: ("" if v is None else str(v)) for k, v in task.model_dump().items()}
    from backend.services.tasks_pg_service import upsert_completed
    return upsert_completed(user["tenant_id"], rec)


@router.delete("/completed")
def delete_completed_tasks(req: DeleteTasksRequest, user: dict = Depends(get_current_user)):
    from backend.services.tasks_pg_service import delete_completed as _pg_del
    return {"deleted": _pg_del(user["tenant_id"], req.task_ids)}
