"""PG repository for work-reference tabs (업무참고 / 업무정리 / …).

Only READ paths are exposed — the existing edit endpoints in
``reference_edit_service`` go through gspread directly and remain Sheets-only
for this round (those edits do cell-precise updates that don't translate
cleanly to a row-based PG schema in one pass).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select


def list_sheets(tenant_id: str) -> dict:
    """Return {"sheet_key": <synthetic>, "sheets": [sheet_name, ...]}.

    Local PG mode doesn't have a real spreadsheet ID, so we return a sentinel
    so the existing frontend doesn't have to special-case it.
    """
    from backend.db.models.work_data import WorkReferenceSheet
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(WorkReferenceSheet)
            .where(WorkReferenceSheet.tenant_id == tenant_id)
            .order_by(WorkReferenceSheet.sheet_name)
        ).all()
    return {
        "sheet_key": f"local-work-{tenant_id}",
        "sheets": [r.sheet_name for r in rows],
    }


def get_sheet_data(tenant_id: str, sheet_name: str) -> dict:
    """Return {"sheet": ..., "headers": [...], "rows": [{header: value}, ...]}."""
    from backend.db.models.work_data import WorkReferenceRow, WorkReferenceSheet
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        sheet = session.scalar(
            select(WorkReferenceSheet).where(
                WorkReferenceSheet.tenant_id == tenant_id,
                WorkReferenceSheet.sheet_name == sheet_name,
            )
        )
        if sheet is None:
            return {"sheet": sheet_name, "headers": [], "rows": [],
                    "column_widths": {}, "row_heights": {}}
        rows_orm = session.scalars(
            select(WorkReferenceRow)
            .where(
                WorkReferenceRow.tenant_id == tenant_id,
                WorkReferenceRow.sheet_name == sheet_name,
            )
            .order_by(WorkReferenceRow.row_index)
        ).all()
        meta = sheet.meta or {}

    headers = sheet.headers or []
    rows = [r.data or {} for r in rows_orm]
    # PG-only(Phase G): Sheets dimension 대응 UI 메타(열 너비/행 높이). 추가 필드(하위호환).
    return {
        "sheet": sheet_name, "headers": headers, "rows": rows,
        "column_widths": (meta.get("col_widths") or {}),
        "row_heights": (meta.get("row_heights") or {}),
    }


def replace_sheet(tenant_id: str, sheet_name: str, headers: list[str], rows: list[dict]) -> int:
    """Replace the entire (tenant, sheet) content. Used by the importer."""
    from sqlalchemy import delete

    from backend.db.models.work_data import WorkReferenceRow, WorkReferenceSheet
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # Upsert sheet metadata
        sheet = session.scalar(
            select(WorkReferenceSheet).where(
                WorkReferenceSheet.tenant_id == tenant_id,
                WorkReferenceSheet.sheet_name == sheet_name,
            )
        )
        if sheet is None:
            sheet = WorkReferenceSheet(
                tenant_id=tenant_id, sheet_name=sheet_name, headers=headers
            )
            session.add(sheet)
        else:
            sheet.headers = headers

        # Replace row data
        session.execute(
            delete(WorkReferenceRow).where(
                WorkReferenceRow.tenant_id == tenant_id,
                WorkReferenceRow.sheet_name == sheet_name,
            )
        )
        for i, row in enumerate(rows):
            session.add(WorkReferenceRow(
                tenant_id=tenant_id,
                sheet_name=sheet_name,
                row_index=i,
                data=row,
            ))
        session.commit()
        return len(rows)
