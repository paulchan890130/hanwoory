"""PG repository for tasks (active / planned / completed).

Each row converts to a dict whose keys match the existing router
output exactly — no schema bridging needed in the router.
"""
from __future__ import annotations

import datetime as _dt
import uuid

from sqlalchemy import delete, select


ACTIVE_FIELDS = (
    "id", "category", "date", "name", "work", "details",
    "transfer", "cash", "card", "stamp", "receivable",
    "planned_expense", "processed", "processed_timestamp",
    "reception", "processing", "storage", "customer_id",
    "source_daily_id",
)


def _active_to_dict(row) -> dict:
    return {
        "id": row.task_id or "",
        "category": row.category or "",
        "date": row.date or "",
        "name": row.name or "",
        "work": row.work or "",
        "details": row.details or "",
        "transfer": row.transfer or "0",
        "cash": row.cash or "0",
        "card": row.card or "0",
        "stamp": row.stamp or "0",
        "receivable": row.receivable or "0",
        "planned_expense": row.planned_expense or "0",
        "processed": bool(row.processed),
        "processed_timestamp": row.processed_timestamp or "",
        "reception": row.reception or "",
        "processing": row.processing or "",
        "storage": row.storage or "",
        "customer_id": row.customer_id or "",
        "source_daily_id": row.source_daily_id or "",
    }


def _planned_to_dict(row) -> dict:
    return {
        "id": row.task_id or "",
        "date": row.date or "",
        "period": row.period or "",
        "content": row.content or "",
        "note": row.note or "",
    }


def _completed_to_dict(row) -> dict:
    return {
        "id": row.task_id or "",
        "category": row.category or "",
        "date": row.date or "",
        "name": row.name or "",
        "work": row.work or "",
        "details": row.details or "",
        "complete_date": row.complete_date or "",
        "reception": row.reception or "",
        "processing": row.processing or "",
        "storage": row.storage or "",
        "customer_id": row.customer_id or "",
    }


# ── active ────────────────────────────────────────────────────────────────

def list_active(tenant_id: str) -> list[dict]:
    from backend.db.models.task import ActiveTask
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(ActiveTask)
            .where(ActiveTask.tenant_id == tenant_id)
            .order_by(ActiveTask.date.desc(), ActiveTask.id.desc())
        ).all()
    return [_active_to_dict(r) for r in rows]


def upsert_active(tenant_id: str, rec: dict) -> dict:
    from backend.db.models.task import ActiveTask
    from backend.db.session import get_sessionmaker

    task_id = str(rec.get("id", "")).strip() or str(uuid.uuid4())
    payload = {
        "category": str(rec.get("category", "") or ""),
        "date": str(rec.get("date", "") or ""),
        "name": str(rec.get("name", "") or ""),
        "work": str(rec.get("work", "") or ""),
        "details": str(rec.get("details", "") or ""),
        "transfer": str(rec.get("transfer", "0") or "0"),
        "cash": str(rec.get("cash", "0") or "0"),
        "card": str(rec.get("card", "0") or "0"),
        "stamp": str(rec.get("stamp", "0") or "0"),
        "receivable": str(rec.get("receivable", "0") or "0"),
        "planned_expense": str(rec.get("planned_expense", "0") or "0"),
        "processed": bool(rec.get("processed", False)),
        "processed_timestamp": str(rec.get("processed_timestamp", "") or ""),
        "reception": str(rec.get("reception", "") or ""),
        "processing": str(rec.get("processing", "") or ""),
        "storage": str(rec.get("storage", "") or ""),
        "customer_id": str(rec.get("customer_id", "") or ""),
        "source_daily_id": str(rec.get("source_daily_id", "") or ""),
    }

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(ActiveTask).where(
                ActiveTask.tenant_id == tenant_id, ActiveTask.task_id == task_id
            )
        )
        if row is None:
            row = ActiveTask(tenant_id=tenant_id, task_id=task_id, **payload)
            session.add(row)
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        session.commit()
        session.refresh(row)
        return _active_to_dict(row)


def patch_active(tenant_id: str, task_id: str, changes: dict) -> dict | None:
    """Partial update — only the keys in ``changes`` are written."""
    from backend.db.models.task import ActiveTask
    from backend.db.session import get_sessionmaker

    field_map = {
        "category": "category", "date": "date", "name": "name", "work": "work",
        "details": "details", "transfer": "transfer", "cash": "cash", "card": "card",
        "stamp": "stamp", "receivable": "receivable", "planned_expense": "planned_expense",
        "processed": "processed", "processed_timestamp": "processed_timestamp",
        "reception": "reception", "processing": "processing", "storage": "storage",
        "customer_id": "customer_id", "source_daily_id": "source_daily_id",
    }

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(ActiveTask).where(
                ActiveTask.tenant_id == tenant_id, ActiveTask.task_id == task_id
            )
        )
        if row is None:
            return None
        for k, v in changes.items():
            if k in field_map:
                if k == "processed":
                    setattr(row, "processed", bool(v))
                else:
                    setattr(row, field_map[k], "" if v is None else str(v))
        session.commit()
        session.refresh(row)
        return _active_to_dict(row)


def delete_active(tenant_id: str, task_ids: list[str]) -> int:
    from backend.db.models.task import ActiveTask
    from backend.db.session import get_sessionmaker

    if not task_ids:
        return 0
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(
            delete(ActiveTask).where(
                ActiveTask.tenant_id == tenant_id, ActiveTask.task_id.in_(task_ids)
            )
        )
        session.commit()
        return result.rowcount or 0


# ── planned ────────────────────────────────────────────────────────────────

def list_planned(tenant_id: str) -> list[dict]:
    from backend.db.models.task import PlannedTask
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(PlannedTask)
            .where(PlannedTask.tenant_id == tenant_id)
            .order_by(PlannedTask.date.desc(), PlannedTask.id.desc())
        ).all()
    return [_planned_to_dict(r) for r in rows]


def upsert_planned(tenant_id: str, rec: dict) -> dict:
    from backend.db.models.task import PlannedTask
    from backend.db.session import get_sessionmaker

    task_id = str(rec.get("id", "")).strip() or str(uuid.uuid4())
    payload = {
        "date": str(rec.get("date", "") or ""),
        "period": str(rec.get("period", "") or ""),
        "content": str(rec.get("content", "") or ""),
        "note": str(rec.get("note", "") or ""),
    }
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(PlannedTask).where(
                PlannedTask.tenant_id == tenant_id, PlannedTask.task_id == task_id
            )
        )
        if row is None:
            row = PlannedTask(tenant_id=tenant_id, task_id=task_id, **payload)
            session.add(row)
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        session.commit()
        session.refresh(row)
        return _planned_to_dict(row)


def delete_planned(tenant_id: str, task_ids: list[str]) -> int:
    from backend.db.models.task import PlannedTask
    from backend.db.session import get_sessionmaker

    if not task_ids:
        return 0
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(
            delete(PlannedTask).where(
                PlannedTask.tenant_id == tenant_id, PlannedTask.task_id.in_(task_ids)
            )
        )
        session.commit()
        return result.rowcount or 0


# ── completed ──────────────────────────────────────────────────────────────

def list_completed(tenant_id: str) -> list[dict]:
    from backend.db.models.task import CompletedTask
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(CompletedTask)
            .where(CompletedTask.tenant_id == tenant_id)
            .order_by(CompletedTask.complete_date.desc(), CompletedTask.id.desc())
        ).all()
    return [_completed_to_dict(r) for r in rows]


def list_completed_paged(
    tenant_id: str,
    *,
    page: int = 1,
    page_size: int = 20,
    name: str = "",
    category: str = "",
    work: str = "",
    date_from: str = "",
    date_to: str = "",
    sort: str = "newest",
) -> dict:
    """완료업무 서버 페이지네이션 + 필터/정렬 (화면 목록 전용).

    ``list_completed`` (전량 조회) 는 work-summary/search 가 계속 사용하므로 그대로
    두고, 완료업무 화면 목록만 LIMIT/OFFSET + 필터를 DB에서 적용한다 → 서버 조회량이
    한 페이지(기본 20건)로 줄어든다.

    반환: ``{items, total, page, page_size, has_next, categories}``.
    정렬/날짜필터 기준 = complete_date 가 있으면 그것, 없으면 date (기존 프론트 로직과 동일).
    """
    from sqlalchemy import func as _f
    from backend.db.models.task import CompletedTask
    from backend.db.session import get_sessionmaker

    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 20)))
    offset = (page - 1) * page_size

    # 유효 날짜 = NULLIF(complete_date,'') 우선, 없으면 date
    eff_date = _f.coalesce(_f.nullif(CompletedTask.complete_date, ""), CompletedTask.date, "")

    conds = [CompletedTask.tenant_id == tenant_id]
    if name:
        conds.append(CompletedTask.name.ilike(f"%{name}%"))
    if category:
        conds.append(CompletedTask.category == category)
    if work:
        conds.append(CompletedTask.work.ilike(f"%{work}%"))
    if date_from:
        conds.append(eff_date >= date_from)
    if date_to:
        conds.append(eff_date <= date_to)

    if sort == "oldest":
        order_by = (eff_date.asc(), CompletedTask.id.asc())
    else:
        order_by = (eff_date.desc(), CompletedTask.id.desc())

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        total = session.scalar(
            select(_f.count()).select_from(CompletedTask).where(*conds)
        ) or 0
        rows = session.scalars(
            select(CompletedTask).where(*conds).order_by(*order_by).limit(page_size).offset(offset)
        ).all()
        # 분류 드롭다운 옵션 — 전체 완료업무의 distinct category (필터 미적용, 텍스트 1컬럼만)
        cats = session.scalars(
            select(CompletedTask.category)
            .where(
                CompletedTask.tenant_id == tenant_id,
                CompletedTask.category.isnot(None),
                CompletedTask.category != "",
            )
            .distinct()
            .order_by(CompletedTask.category.asc())
        ).all()

    items = [_completed_to_dict(r) for r in rows]
    return {
        "items": items,
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "has_next": offset + len(items) < int(total),
        "categories": [c for c in cats if c],
    }


def upsert_completed(tenant_id: str, rec: dict) -> dict:
    from backend.db.models.task import CompletedTask
    from backend.db.session import get_sessionmaker

    task_id = str(rec.get("id", "")).strip() or str(uuid.uuid4())
    payload = {
        "category": str(rec.get("category", "") or ""),
        "date": str(rec.get("date", "") or ""),
        "name": str(rec.get("name", "") or ""),
        "work": str(rec.get("work", "") or ""),
        "details": str(rec.get("details", "") or ""),
        "complete_date": str(rec.get("complete_date", "") or ""),
        "reception": str(rec.get("reception", "") or ""),
        "processing": str(rec.get("processing", "") or ""),
        "storage": str(rec.get("storage", "") or ""),
        "customer_id": str(rec.get("customer_id", "") or ""),
    }
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(CompletedTask).where(
                CompletedTask.tenant_id == tenant_id, CompletedTask.task_id == task_id
            )
        )
        if row is None:
            row = CompletedTask(tenant_id=tenant_id, task_id=task_id, **payload)
            session.add(row)
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        session.commit()
        session.refresh(row)
        return _completed_to_dict(row)


def delete_completed(tenant_id: str, task_ids: list[str]) -> int:
    from backend.db.models.task import CompletedTask
    from backend.db.session import get_sessionmaker

    if not task_ids:
        return 0
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(
            delete(CompletedTask).where(
                CompletedTask.tenant_id == tenant_id, CompletedTask.task_id.in_(task_ids)
            )
        )
        session.commit()
        return result.rowcount or 0


def complete_active(tenant_id: str, task_ids: list[str]) -> int:
    """Move rows from active_tasks → completed_tasks. Returns the moved count."""
    from backend.db.models.task import ActiveTask, CompletedTask
    from backend.db.session import get_sessionmaker

    today = _dt.date.today().isoformat()
    moved = 0
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(ActiveTask).where(
                ActiveTask.tenant_id == tenant_id, ActiveTask.task_id.in_(task_ids)
            )
        ).all()
        for r in rows:
            session.add(CompletedTask(
                tenant_id=tenant_id,
                task_id=r.task_id,
                category=r.category,
                date=r.date,
                name=r.name,
                work=r.work,
                details=r.details,
                complete_date=today,
                reception=r.reception,
                processing=r.processing,
                storage=r.storage,
                customer_id=r.customer_id,
            ))
            session.delete(r)
            moved += 1
        session.commit()
    return moved
