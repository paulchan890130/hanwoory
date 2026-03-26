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
)
from backend.services.tenant_service import read_sheet, upsert_sheet, delete_from_sheet

router = APIRouter()


def _sheet_names():
    from config import ACTIVE_TASKS_SHEET_NAME, PLANNED_TASKS_SHEET_NAME, COMPLETED_TASKS_SHEET_NAME
    return ACTIVE_TASKS_SHEET_NAME, PLANNED_TASKS_SHEET_NAME, COMPLETED_TASKS_SHEET_NAME


# ────────────────────────────── 진행업무 ──────────────────────────────────────

ACTIVE_HEADER = [
    "id", "category", "date", "name", "work", "details",
    "transfer", "cash", "card", "stamp", "receivable",
    "planned_expense", "processed", "processed_timestamp",
]


_CAT_RANK = {c: i for i, c in enumerate(["출입국","전자민원","공증","여권","초청","영주권","기타"])}
_MAX_NS = 9999999999999999999


def _sort_key_active(t: dict):
    """page_home.py _sort_key_active 와 동일한 정렬키"""
    import datetime as _dt
    proc = str(t.get("processed", "")).strip().lower() in ("true", "1", "y")
    cat_rank = _CAT_RANK.get(t.get("category", "기타"), 99)

    raw_date = t.get("date", "") or ""
    try:
        dt_date = _dt.date.fromisoformat(raw_date[:10])
        date_ns = int(_dt.datetime.combine(dt_date, _dt.time.min).timestamp() * 1e9)
    except Exception:
        date_ns = _MAX_NS

    if proc:
        raw_ts = t.get("processed_timestamp", "") or ""
        try:
            ts = _dt.datetime.fromisoformat(raw_ts)
            ts_ns = int(ts.timestamp() * 1e9)
        except Exception:
            ts_ns = -1
        return (0, cat_rank, -ts_ns, date_ns)
    return (1, cat_rank, date_ns)


@router.get("/active", response_model=List[dict])
def get_active_tasks(user: dict = Depends(get_current_user)):
    ACTIVE, *_ = _sheet_names()
    tasks = read_sheet(ACTIVE, user["tenant_id"], default_if_empty=[]) or []
    tasks.sort(key=_sort_key_active)
    return tasks


@router.post("/active", response_model=dict)
def add_active_task(task: ActiveTask, user: dict = Depends(get_current_user)):
    ACTIVE, *_ = _sheet_names()
    if not task.id:
        task.id = str(uuid.uuid4())
    rec = {k: ("" if v is None else str(v)) for k, v in task.model_dump().items()}
    upsert_sheet(ACTIVE, user["tenant_id"], ACTIVE_HEADER, [rec], id_field="id")
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
    return merged


@router.delete("/active")
def delete_active_tasks(req: DeleteTasksRequest, user: dict = Depends(get_current_user)):
    ACTIVE, *_ = _sheet_names()
    delete_from_sheet(ACTIVE, user["tenant_id"], req.task_ids, id_field="id")
    return {"deleted": len(req.task_ids)}


@router.post("/active/complete")
def complete_tasks(req: CompleteTasksRequest, user: dict = Depends(get_current_user)):
    """진행업무 → 완료업무 이동"""
    ACTIVE, _, COMPLETED = _sheet_names()
    tenant_id = user["tenant_id"]

    all_active = read_sheet(ACTIVE, tenant_id, default_if_empty=[])
    by_id = {r.get("id"): r for r in all_active if r.get("id")}

    today = datetime.date.today().isoformat()
    completed_header = ["id", "category", "date", "name", "work", "details", "complete_date"]
    completed_records = []

    for tid in req.task_ids:
        t = by_id.get(tid)
        if t:
            cr = {k: str(t.get(k, "")) for k in completed_header[:-1]}
            cr["complete_date"] = today
            completed_records.append(cr)

    if completed_records:
        upsert_sheet(COMPLETED, tenant_id, completed_header, completed_records, id_field="id")

    delete_from_sheet(ACTIVE, tenant_id, req.task_ids, id_field="id")
    return {"completed": len(completed_records)}


# ────────────────────────────── 예정업무 ──────────────────────────────────────

PLANNED_HEADER = ["id", "date", "period", "content", "note"]


@router.get("/planned", response_model=List[dict])
def get_planned_tasks(user: dict = Depends(get_current_user)):
    _, PLANNED, _ = _sheet_names()
    return read_sheet(PLANNED, user["tenant_id"], default_if_empty=[])


@router.post("/planned", response_model=dict)
def add_planned_task(task: PlannedTask, user: dict = Depends(get_current_user)):
    _, PLANNED, _ = _sheet_names()
    if not task.id:
        task.id = str(uuid.uuid4())
    rec = {k: ("" if v is None else str(v)) for k, v in task.model_dump().items()}
    upsert_sheet(PLANNED, user["tenant_id"], PLANNED_HEADER, [rec], id_field="id")
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
    return merged


@router.delete("/planned")
def delete_planned_tasks(req: DeleteTasksRequest, user: dict = Depends(get_current_user)):
    _, PLANNED, _ = _sheet_names()
    delete_from_sheet(PLANNED, user["tenant_id"], req.task_ids, id_field="id")
    return {"deleted": len(req.task_ids)}


# ────────────────────────────── 완료업무 ──────────────────────────────────────

COMPLETED_HEADER = ["id", "category", "date", "name", "work", "details", "complete_date"]


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
