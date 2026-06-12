"""0009 work_reference_sheets.meta (column widths / row heights for PG-only 업무참고 편집)

Revision ID: d9e0f1a20009
Revises: c8d3e4f50008
Create Date: 2026-06-10 00:00:00.000000

업무참고/업무정리 인라인 편집을 PG-only(Phase G)로 전환하면서, Google Sheets 의
dimension properties(열 너비/행 높이)에 대응하는 UI 메타데이터를 보관할 JSONB 컬럼을
``work_reference_sheets`` 에 추가한다. 형태: {"col_widths": {col_key: px}, "row_heights":
{row_index: px}}. 기존 행 데이터(work_reference_rows)는 변경하지 않는다. 기존 행은
NULL(메타 없음)로 남으며 서비스가 빈 dict 로 취급한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd9e0f1a20009'
down_revision: Union[str, Sequence[str], None] = 'c8d3e4f50008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'work_reference_sheets',
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('work_reference_sheets', 'meta')
