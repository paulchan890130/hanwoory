"""0028 문서자동작성 HWPX 템플릿 매핑 — doc_required_documents

Revision ID: c3d4e5f60028
Revises: b2c3d4e50027
Create Date: 2026-07-07 00:00:00.000000

관리자 "문서 자동작성 설정"이 PDF(template_filename)만 매핑하던 것을 HWPX 도
명시 매핑할 수 있게 한다.

- ``hwpx_template_filename`` (Text, nullable): templates/hwpx/ 의 .hwpx 파일명
  (확장자 포함). NULL = 명시 매핑 없음 → 기존 파일명 정규화 자동매칭(레지스트리)
  fallback 유지.
- ``output_format`` (Text, nullable): pdf | hwpx | both | disabled.
  NULL = 자동(기존 동작 — 템플릿 존재 여부에 따름).

additive/nullable — 기존 PDF 매핑·데이터 무변경.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f60028'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e50027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('doc_required_documents',
                  sa.Column('hwpx_template_filename', sa.Text(), nullable=True))
    op.add_column('doc_required_documents',
                  sa.Column('output_format', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('doc_required_documents', 'output_format')
    op.drop_column('doc_required_documents', 'hwpx_template_filename')
