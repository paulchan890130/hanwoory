"""Customer Excel templates and tenant-scoped bulk export."""

from __future__ import annotations

import io
from typing import Iterable

EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_EXPORT_COLUMNS: tuple[tuple[str, str, int], ...] = (
    ("고객ID", "고객ID", 12),
    ("성명", "한글", 14),
    ("영문 성", "성", 16),
    ("영문 이름", "명", 20),
    ("성별", "성별", 8),
    ("국적", "국적", 14),
    ("전화번호", "_phone", 16),
    ("외국인등록번호 앞자리", "등록증", 20),
    ("외국인등록번호 뒷자리", "번호", 20),
    ("등록증 발급일", "발급일", 14),
    ("체류 만료일", "만기일", 14),
    ("여권번호", "여권", 16),
    ("여권 발급일", "발급", 14),
    ("여권 만기일", "만기", 14),
    ("체류자격", "_visa", 12),
    ("주소", "주소", 36),
    ("메모", "비고", 30),
    ("위임내역", "위임내역", 32),
    ("폴더", "폴더", 28),
)
_TEXT_EXPORT_KEYS = {"고객ID", "_phone", "등록증", "번호", "여권"}


def build_bulk_template_bytes() -> bytes:
    """Return the bulk-add workbook with phone cells preformatted as text.

    Excel's General format drops the leading zero from 010... values. Formatting
    the entire phone input column as Text before the user types preserves it.
    """
    from openpyxl import load_workbook
    from backend.services import customer_bulk_service as bulk

    wb = load_workbook(io.BytesIO(bulk.build_template_bytes()))
    ws = wb[bulk.SHEET_NAME]
    phone_col = bulk.STD_KEYS.index("_phone") + 1

    # Example row + all currently unlocked input rows.
    for row in range(bulk.EXAMPLE_ROW, bulk.DATA_START_ROW + 1000):
        ws.cell(row=row, column=phone_col).number_format = "@"

    if "사용법" in wb.sheetnames:
        info = wb["사용법"]
        info.cell(
            row=info.max_row + 2,
            column=1,
            value="※ 전화번호 열은 텍스트 형식입니다. 010으로 시작하는 번호를 그대로 입력하세요.",
        )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _phone(record: dict) -> str:
    parts = [str(record.get(key, "") or "").strip() for key in ("연", "락", "처")]
    return "-".join(part for part in parts if part)


def _value(record: dict, key: str) -> str:
    if key == "_phone":
        return _phone(record)
    if key == "_visa":
        return str(record.get("체류자격") or record.get("V") or "").strip()
    return str(record.get(key, "") or "")


def build_export_bytes_from_records(records: Iterable[dict]) -> tuple[bytes, int]:
    """Build a customer export workbook from already tenant-scoped records."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    safe_records = list(records)
    wb = Workbook()
    ws = wb.active
    ws.title = "고객목록"

    headers = [column[0] for column in _EXPORT_COLUMNS]
    ws.append(headers)
    header_fill = PatternFill("solid", fgColor="F0E6C8")
    for col_idx, (_header, _key, width) in enumerate(_EXPORT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = Font(bold=True, size=10)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[cell.column_letter].width = width

    for row_idx, record in enumerate(safe_records, start=2):
        ws.append([_value(record, key) for _header, key, _width in _EXPORT_COLUMNS])
        for col_idx, (_header, key, _width) in enumerate(_EXPORT_COLUMNS, start=1):
            cell = ws.cell(row=row_idx, column=col_idx)
            if key in _TEXT_EXPORT_KEYS:
                cell.number_format = "@"
            cell.alignment = Alignment(vertical="top", wrap_text=key in {"주소", "비고", "위임내역"})

    ws.freeze_panes = "A2"
    last_col = ws.cell(row=1, column=len(_EXPORT_COLUMNS)).column_letter
    ws.auto_filter.ref = f"A1:{last_col}{max(1, len(safe_records) + 1)}"
    ws.row_dimensions[1].height = 32

    info = wb.create_sheet("안내")
    notes = (
        "[고객 일괄추출 안내]",
        "",
        f"추출 고객 수: {len(safe_records)}명",
        "이 파일에는 외국인등록번호·여권번호·주소 등 개인정보가 포함될 수 있습니다.",
        "하이코리아·소시넷 아이디와 비밀번호는 추출 대상에서 제외했습니다.",
        "업무 목적이 끝난 파일은 안전하게 폐기하세요.",
    )
    for idx, note in enumerate(notes, start=1):
        cell = info.cell(row=idx, column=1, value=note)
        if idx == 1:
            cell.font = Font(bold=True, size=12)
    info.column_dimensions["A"].width = 88

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), len(safe_records)


def build_tenant_export_bytes(tenant_id: str) -> tuple[bytes, int]:
    """Load non-deleted customers for one tenant and build the export workbook."""
    from sqlalchemy import select
    from backend.db.models.customer import Customer
    from backend.db.session import get_sessionmaker
    from backend.services.customer_pg_service import _row_to_dict

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(Customer)
            .where(Customer.tenant_id == tenant_id, Customer.deleted_at.is_(None))
            .order_by(Customer.customer_id.desc())
        ).all()
        records = [_row_to_dict(row, reveal=True) for row in rows]

    # External-site credentials are intentionally absent from _EXPORT_COLUMNS.
    return build_export_bytes_from_records(records)
