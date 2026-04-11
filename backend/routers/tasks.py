"""업무 라우터 - 예정/진행/완료 업무 CRUD (테넌트 인식)"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uuid
import datetime
from typing import List
from fastapi import APIRouter, Depends

from backend.auth import get_current_user
from backend.models import (
    ActiveTask, PlannedTask, CompletedTask,
    CompleteTasksRequest, DeleteTasksRequest,
    BatchProgressRequest,
)
from backend.services.tenant_service import read_sheet, upsert_sheet, delete_from_sheet
from backend.services.cache_service import cache_get, cache_set, cache_invalidate

_CACHE_ACTIVE  = "tasks:active"
_CACHE_PLANNED = "tasks:planned"
_TTL = 30.0  # seconds

router = APIRouter()


def _sheet_names():
    from config import ACTIVE_TASKS_SHEET_NAME, PLANNED_TASKS_SHEET_NAME, COMPLETED_TASKS_SHEET_NAME
    return ACTIVE_TASKS_SHEET_NAME, PLANNED_TASKS_SHEET_NAME, COMPLETED_TASKS_SHEET_NAME


# ────────────────────────────── 진행업무 ──────────────────────────────────────

ACTIVE_HEADER = [
    "id", "category", "date", "name", "work", "details",
    "transfer", "cash", "card", "stamp", "receivable",
    "planned_expense", "processed", "processed_timestamp",
    "reception", "processing", "storage",
]


_CAT_RANK = {c: i for i, c in enumerate(["출입국","전자민원","공증","여권","초청","영주권","기타"])}
_MAX_NS = 9999999999999999999


def _sort_key_active(t: dict):
    """정렬: 체크 조합 순서 (없음 → 접수 → 접수+처리 → 접수+처리+보관중), 각 그룹 내 날짜 오름차순.
    독립 체크 가능하므로 체크된 단계의 수와 순서로 rank를 계산.
    """
    import datetime as _dt

    cat_rank = _CAT_RANK.get(t.get("category", "기타"), 99)

    reception  = bool((t.get("reception",  "") or "").strip())
    processing = bool((t.get("processing", "") or "").strip())
    storage    = bool((t.get("storage",    "") or "").strip())

    # rank: 높을수록 뒤에 정렬 (진행이 많이 된 것이 아래)
    # 조합 순서: 없음=0, 접수만=1, 접수+처리=2, 접수+처리+보관중=3
    # 독립 체크로 순서가 맞지 않더라도 최고 단계로 처리
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
    tenant_id = user["tenant_id"]
    cached = cache_get(tenant_id, _CACHE_ACTIVE)
    if cached is not None:
        return cached
    ACTIVE, *_ = _sheet_names()
    tasks = read_sheet(ACTIVE, tenant_id, default_if_empty=[]) or []
    tasks.sort(key=_sort_key_active)
    cache_set(tenant_id, _CACHE_ACTIVE, tasks, _TTL)
    return tasks


@router.post("/active", response_model=dict)
def add_active_task(task: ActiveTask, user: dict = Depends(get_current_user)):
    ACTIVE, *_ = _sheet_names()
    tenant_id = user["tenant_id"]
    if not task.id:
        task.id = str(uuid.uuid4())
    rec = {k: ("" if v is None else str(v)) for k, v in task.model_dump().items()}
    upsert_sheet(ACTIVE, tenant_id, ACTIVE_HEADER, [rec], id_field="id")
    cache_invalidate(tenant_id, _CACHE_ACTIVE)
    return rec


@router.put("/active/{task_id}", response_model=dict)
def update_active_task(task_id: str, task: ActiveTask, user: dict = Depends(get_current_user)):
    ACTIVE, *_ = _sheet_names()
    tenant_id = user["tenant_id"]
    # Partial update: only fields explicitly sent by the client are written.
    # model_dump(exclude_unset=True) excludes Pydantic defaults for unset fields,
    # preventing a single-field edit from zeroing all other columns.
    changes = {k: ("" if v is None else str(v))
               for k, v in task.model_dump(exclude_unset=True).items()}
    changes["id"] = task_id
    all_tasks = read_sheet(ACTIVE, tenant_id, default_if_empty=[]) or []
    existing = next((r for r in all_tasks if r.get("id") == task_id), {})
    merged = {**existing, **changes}
    upsert_sheet(ACTIVE, tenant_id, ACTIVE_HEADER, [merged], id_field="id")
    cache_invalidate(tenant_id, _CACHE_ACTIVE)
    return merged


@router.patch("/active/batch-progress")
def batch_update_active_progress(req: BatchProgressRequest, user: dict = Depends(get_current_user)):
    """진행업무 접수/처리/보관중 일괄 업데이트.
    1회 read + 1회 write로 Google Sheets 429 quota 방어."""
    ACTIVE, *_ = _sheet_names()
    tenant_id = user["tenant_id"]
    all_tasks = read_sheet(ACTIVE, tenant_id, default_if_empty=[]) or []
    by_id = {r.get("id"): r for r in all_tasks if r.get("id")}

    changed = []
    for upd in req.updates:
        row = by_id.get(upd.id)
        if row is None:
            continue
        row["reception"]  = upd.reception
        row["processing"] = upd.processing
        row["storage"]    = upd.storage
        changed.append(row)

    if changed:
        upsert_sheet(ACTIVE, tenant_id, ACTIVE_HEADER, changed, id_field="id")
        cache_invalidate(tenant_id, _CACHE_ACTIVE)

    return {"updated": len(changed)}


@router.delete("/active")
def delete_active_tasks(req: DeleteTasksRequest, user: dict = Depends(get_current_user)):
    ACTIVE, *_ = _sheet_names()
    tenant_id = user["tenant_id"]
    delete_from_sheet(ACTIVE, tenant_id, req.task_ids, id_field="id")
    cache_invalidate(tenant_id, _CACHE_ACTIVE)
    return {"deleted": len(req.task_ids)}


@router.post("/active/complete")
def complete_tasks(req: CompleteTasksRequest, user: dict = Depends(get_current_user)):
    """진행업무 → 완료업무 이동"""
    ACTIVE, _, COMPLETED = _sheet_names()
    tenant_id = user["tenant_id"]

    all_active = read_sheet(ACTIVE, tenant_id, default_if_empty=[])
    by_id = {r.get("id"): r for r in all_active if r.get("id")}

    today = datetime.date.today().isoformat()
    completed_header = ["id", "category", "date", "name", "work", "details", "complete_date",
                        "reception", "processing", "storage"]
    completed_records = []

    for tid in req.task_ids:
        t = by_id.get(tid)
        if t:
            base_keys = ["id", "category", "date", "name", "work", "details"]
            cr = {k: str(t.get(k, "")) for k in base_keys}
            cr["complete_date"] = today
            # carry over status timestamps
            for ts_field in ("reception", "processing", "storage"):
                cr[ts_field] = str(t.get(ts_field, ""))
            completed_records.append(cr)

    if completed_records:
        upsert_sheet(COMPLETED, tenant_id, completed_header, completed_records, id_field="id")

    delete_from_sheet(ACTIVE, tenant_id, req.task_ids, id_field="id")
    cache_invalidate(tenant_id, _CACHE_ACTIVE)
    return {"completed": len(completed_records)}


# ────────────────────────────── 예정업무 ──────────────────────────────────────

PLANNED_HEADER = ["id", "date", "period", "content", "note"]


@router.get("/planned", response_model=List[dict])
def get_planned_tasks(user: dict = Depends(get_current_user)):
    tenant_id = user["tenant_id"]
    cached = cache_get(tenant_id, _CACHE_PLANNED)
    if cached is not None:
        return cached
    _, PLANNED, _ = _sheet_names()
    result = read_sheet(PLANNED, tenant_id, default_if_empty=[]) or []
    cache_set(tenant_id, _CACHE_PLANNED, result, _TTL)
    return result


@router.post("/planned", response_model=dict)
def add_planned_task(task: PlannedTask, user: dict = Depends(get_current_user)):
    _, PLANNED, _ = _sheet_names()
    tenant_id = user["tenant_id"]
    if not task.id:
        task.id = str(uuid.uuid4())
    rec = {k: ("" if v is None else str(v)) for k, v in task.model_dump().items()}
    upsert_sheet(PLANNED, tenant_id, PLANNED_HEADER, [rec], id_field="id")
    cache_invalidate(tenant_id, _CACHE_PLANNED)
    return rec


@router.put("/planned/{task_id}", response_model=dict)
def update_planned_task(task_id: str, task: PlannedTask, user: dict = Depends(get_current_user)):
    _, PLANNED, _ = _sheet_names()
    tenant_id = user["tenant_id"]
    changes = {k: ("" if v is None else str(v))
               for k, v in task.model_dump(exclude_unset=True).items()}
    changes["id"] = task_id
    all_tasks = read_sheet(PLANNED, tenant_id, default_if_empty=[]) or []
    existing = next((r for r in all_tasks if r.get("id") == task_id), {})
    merged = {**existing, **changes}
    upsert_sheet(PLANNED, tenant_id, PLANNED_HEADER, [merged], id_field="id")
    cache_invalidate(tenant_id, _CACHE_PLANNED)
    return merged


@router.delete("/planned")
def delete_planned_tasks(req: DeleteTasksRequest, user: dict = Depends(get_current_user)):
    _, PLANNED, _ = _sheet_names()
    tenant_id = user["tenant_id"]
    delete_from_sheet(PLANNED, tenant_id, req.task_ids, id_field="id")
    cache_invalidate(tenant_id, _CACHE_PLANNED)
    return {"deleted": len(req.task_ids)}


# ────────────────────────────── 완료업무 ──────────────────────────────────────

COMPLETED_HEADER = ["id", "category", "date", "name", "work", "details", "complete_date",
                    "reception", "processing", "storage"]


@router.get("/completed", response_model=List[dict])
def get_completed_tasks(user: dict = Depends(get_current_user)):
    _, _, COMPLETED = _sheet_names()
    return read_sheet(COMPLETED, user["tenant_id"], default_if_empty=[])


@router.put("/completed/{task_id}", response_model=dict)
def update_completed_task(task_id: str, task: CompletedTask, user: dict = Depends(get_current_user)):
    _, _, COMPLETED = _sheet_names()
    task.id = task_id
    rec = {k: ("" if v is None else str(v)) for k, v in task.model_dump().items()}
    upsert_sheet(COMPLETED, user["tenant_id"], COMPLETED_HEADER, [rec], id_field="id")
    return rec


@router.delete("/completed")
def delete_completed_tasks(req: DeleteTasksRequest, user: dict = Depends(get_current_user)):
    _, _, COMPLETED = _sheet_names()
    delete_from_sheet(COMPLETED, user["tenant_id"], req.task_ids, id_field="id")
    return {"deleted": len(req.task_ids)}
