"""업무참고/업무정리 인라인 편집 — PostgreSQL 전용(Phase G).

``reference_edit_service``(Google Sheets gspread)의 PG 대체. 동일한 함수 시그니처를
제공하여 ``reference.py`` 의 편집 엔드포인트가 드롭인으로 PG 를 사용한다.

저장 구조 (work_data 모델, JSONB row 기반 — 신규 테이블 없이 기존 구조 사용):
  - ``work_reference_sheets``: (tenant_id, sheet_name) 당 1행. ``headers``(JSONB list,
    열 순서) + ``meta``(JSONB, 열 너비/행 높이 = Sheets dimension 대응, migration 0009).
  - ``work_reference_rows``: (tenant_id, sheet_name, row_index 0-based) 당 1행. ``data``
    (JSONB, header→cell 값).

행 인덱스(row_index)는 0-based(헤더 제외)로 reference_edit_service 와 동일 의미.
열은 header 이름(col_key)으로 식별. 행 삽입/삭제/이동·열 삽입/삭제 시 row_index/headers 를
0..n 연속으로 재작성(rewrite)하여 unique 제약 충돌을 피한다.

PG 미구성 시 get_sessionmaker() 가 RuntimeError → 조용한 Sheets fallback 없음.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import delete as _delete, select


def _SL():
    """새 Session 인스턴스 반환(context-manager). get_sessionmaker()는 factory 이므로 () 호출."""
    from backend.db.session import get_sessionmaker
    return get_sessionmaker()()


def _get_sheet(session, tenant_id: str, sheet_name: str):
    from backend.db.models.work_data import WorkReferenceSheet
    return session.scalar(
        select(WorkReferenceSheet).where(
            WorkReferenceSheet.tenant_id == tenant_id,
            WorkReferenceSheet.sheet_name == sheet_name,
        )
    )


def _require_sheet(session, tenant_id: str, sheet_name: str):
    sheet = _get_sheet(session, tenant_id, sheet_name)
    if sheet is None:
        raise ValueError(f"시트를 찾을 수 없습니다: {sheet_name!r}")
    return sheet


def _ordered_rows(session, tenant_id: str, sheet_name: str):
    from backend.db.models.work_data import WorkReferenceRow
    return session.scalars(
        select(WorkReferenceRow)
        .where(WorkReferenceRow.tenant_id == tenant_id,
               WorkReferenceRow.sheet_name == sheet_name)
        .order_by(WorkReferenceRow.row_index)
    ).all()


def _ordered_data(session, tenant_id: str, sheet_name: str) -> list[dict]:
    return [dict(r.data or {}) for r in _ordered_rows(session, tenant_id, sheet_name)]


def _rewrite_rows(session, tenant_id: str, sheet_name: str, data_list: list[dict]) -> None:
    """(tenant, sheet) 의 모든 행을 data_list 순서로 0..n-1 재작성(unique 충돌 회피)."""
    from backend.db.models.work_data import WorkReferenceRow
    session.execute(
        _delete(WorkReferenceRow).where(
            WorkReferenceRow.tenant_id == tenant_id,
            WorkReferenceRow.sheet_name == sheet_name,
        )
    )
    session.flush()
    for i, d in enumerate(data_list):
        session.add(WorkReferenceRow(
            tenant_id=tenant_id, sheet_name=sheet_name, row_index=i, data=d,
        ))


# ── 셀 수정 ───────────────────────────────────────────────────────────────────

def update_single_cell(tenant_id: str, sheet_name: str,
                       row_index: int, col_key: str, value: str) -> str:
    from backend.db.models.work_data import WorkReferenceRow
    with _SL() as session:
        sheet = _require_sheet(session, tenant_id, sheet_name)
        headers = list(sheet.headers or [])
        if col_key not in headers:
            raise ValueError(f"열을 찾을 수 없습니다: {col_key!r}")
        row = session.scalar(
            select(WorkReferenceRow).where(
                WorkReferenceRow.tenant_id == tenant_id,
                WorkReferenceRow.sheet_name == sheet_name,
                WorkReferenceRow.row_index == row_index,
            )
        )
        if row is None:
            raise ValueError(f"행을 찾을 수 없습니다: row_index={row_index}")
        d = dict(row.data or {})
        d[col_key] = str(value)
        row.data = d
        session.commit()
    return str(value)


# ── 행 추가/삭제/이동 ─────────────────────────────────────────────────────────

def insert_row_after(tenant_id: str, sheet_name: str,
                     insert_after: Optional[int], values_dict: dict) -> int:
    with _SL() as session:
        sheet = _require_sheet(session, tenant_id, sheet_name)
        headers = list(sheet.headers or [])
        data = _ordered_data(session, tenant_id, sheet_name)
        new_row = {h: str((values_dict or {}).get(h, "")) for h in headers}
        pos = len(data) if insert_after is None else min(insert_after + 1, len(data))
        data.insert(pos, new_row)
        _rewrite_rows(session, tenant_id, sheet_name, data)
        session.commit()
    return pos


def delete_single_row(tenant_id: str, sheet_name: str, row_index: int) -> bool:
    with _SL() as session:
        _require_sheet(session, tenant_id, sheet_name)
        data = _ordered_data(session, tenant_id, sheet_name)
        if 0 <= row_index < len(data):
            data.pop(row_index)
            _rewrite_rows(session, tenant_id, sheet_name, data)
            session.commit()
    return True


def reorder_row(tenant_id: str, sheet_name: str, from_index: int, to_index: int) -> bool:
    if from_index == to_index:
        return True
    with _SL() as session:
        _require_sheet(session, tenant_id, sheet_name)
        data = _ordered_data(session, tenant_id, sheet_name)
        if not (0 <= from_index < len(data)):
            return True
        row = data.pop(from_index)
        to = max(0, min(to_index, len(data)))
        data.insert(to, row)
        _rewrite_rows(session, tenant_id, sheet_name, data)
        session.commit()
    return True


# ── 행 높이 (meta) ────────────────────────────────────────────────────────────

def update_row_height(tenant_id: str, sheet_name: str, row_index: int, pixel_height: int) -> bool:
    with _SL() as session:
        sheet = _require_sheet(session, tenant_id, sheet_name)
        meta = dict(sheet.meta or {})
        heights = dict(meta.get("row_heights", {}))
        heights[str(row_index)] = int(pixel_height)
        meta["row_heights"] = heights
        sheet.meta = meta
        session.commit()
    return True


# ── 열 추가/삭제/이름변경/너비 ─────────────────────────────────────────────────

def insert_column(tenant_id: str, sheet_name: str,
                  col_name: str, insert_after_col: Optional[str]) -> bool:
    with _SL() as session:
        sheet = _require_sheet(session, tenant_id, sheet_name)
        headers = list(sheet.headers or [])
        if col_name in headers:
            raise ValueError(f"이미 존재하는 열입니다: {col_name!r}")
        if insert_after_col is None or insert_after_col not in headers:
            pos = len(headers)
        else:
            pos = headers.index(insert_after_col) + 1
        headers.insert(pos, col_name)
        sheet.headers = headers
        # 모든 행에 빈 값 키 추가
        data = _ordered_data(session, tenant_id, sheet_name)
        for d in data:
            d[col_name] = ""
        _rewrite_rows(session, tenant_id, sheet_name, data)
        session.commit()
    return True


def delete_column(tenant_id: str, sheet_name: str, col_key: str) -> bool:
    with _SL() as session:
        sheet = _require_sheet(session, tenant_id, sheet_name)
        headers = list(sheet.headers or [])
        if col_key not in headers:
            raise ValueError(f"열을 찾을 수 없습니다: {col_key!r}")
        headers.remove(col_key)
        sheet.headers = headers
        # meta 열 너비 정리
        meta = dict(sheet.meta or {})
        if "col_widths" in meta and col_key in meta["col_widths"]:
            cw = dict(meta["col_widths"]); cw.pop(col_key, None); meta["col_widths"] = cw
            sheet.meta = meta
        data = _ordered_data(session, tenant_id, sheet_name)
        for d in data:
            d.pop(col_key, None)
        _rewrite_rows(session, tenant_id, sheet_name, data)
        session.commit()
    return True


def rename_column_header(tenant_id: str, sheet_name: str, old_name: str, new_name: str) -> bool:
    with _SL() as session:
        sheet = _require_sheet(session, tenant_id, sheet_name)
        headers = list(sheet.headers or [])
        if old_name not in headers:
            raise ValueError(f"열을 찾을 수 없습니다: {old_name!r}")
        if new_name != old_name and new_name in headers:
            raise ValueError(f"이미 존재하는 열입니다: {new_name!r}")
        headers[headers.index(old_name)] = new_name
        sheet.headers = headers
        meta = dict(sheet.meta or {})
        if "col_widths" in meta and old_name in meta["col_widths"]:
            cw = dict(meta["col_widths"]); cw[new_name] = cw.pop(old_name); meta["col_widths"] = cw
            sheet.meta = meta
        data = _ordered_data(session, tenant_id, sheet_name)
        for d in data:
            if old_name in d:
                d[new_name] = d.pop(old_name)
        _rewrite_rows(session, tenant_id, sheet_name, data)
        session.commit()
    return True


def update_column_width(tenant_id: str, sheet_name: str, col_key: str, pixel_width: int) -> bool:
    with _SL() as session:
        sheet = _require_sheet(session, tenant_id, sheet_name)
        if col_key not in (sheet.headers or []):
            raise ValueError(f"열을 찾을 수 없습니다: {col_key!r}")
        meta = dict(sheet.meta or {})
        widths = dict(meta.get("col_widths", {}))
        widths[col_key] = int(pixel_width)
        meta["col_widths"] = widths
        sheet.meta = meta
        session.commit()
    return True


# ── 시트 탭 추가/삭제/이름변경 ─────────────────────────────────────────────────

def add_sheet_tab(tenant_id: str, sheet_name: str) -> bool:
    from backend.db.models.work_data import WorkReferenceSheet
    with _SL() as session:
        if _get_sheet(session, tenant_id, sheet_name) is not None:
            raise ValueError(f"이미 존재하는 시트입니다: {sheet_name!r}")
        session.add(WorkReferenceSheet(tenant_id=tenant_id, sheet_name=sheet_name, headers=[]))
        session.commit()
    return True


def delete_sheet_tab(tenant_id: str, sheet_name: str) -> bool:
    from backend.db.models.work_data import WorkReferenceRow, WorkReferenceSheet
    with _SL() as session:
        session.execute(
            _delete(WorkReferenceRow).where(
                WorkReferenceRow.tenant_id == tenant_id,
                WorkReferenceRow.sheet_name == sheet_name,
            )
        )
        session.execute(
            _delete(WorkReferenceSheet).where(
                WorkReferenceSheet.tenant_id == tenant_id,
                WorkReferenceSheet.sheet_name == sheet_name,
            )
        )
        session.commit()
    return True


def rename_sheet_tab(tenant_id: str, old_name: str, new_name: str) -> bool:
    from backend.db.models.work_data import WorkReferenceRow
    with _SL() as session:
        sheet = _require_sheet(session, tenant_id, old_name)
        if old_name != new_name and _get_sheet(session, tenant_id, new_name) is not None:
            raise ValueError(f"이미 존재하는 시트입니다: {new_name!r}")
        sheet.sheet_name = new_name
        for r in _ordered_rows(session, tenant_id, old_name):
            r.sheet_name = new_name
        session.commit()
    return True
