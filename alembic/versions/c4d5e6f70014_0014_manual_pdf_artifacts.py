"""0014 manual_pdf_artifacts (PDF artifact 레지스트리 — 변경 페이지 PDF viewer 우선사용 기반)

Revision ID: c4d5e6f70014
Revises: b3c4d5e60013
Create Date: 2026-06-12 00:00:00.000000

생성된 PDF artifact(변경 페이지 등)의 메타 + blob 을 PG 에 저장하는 레지스트리.
변경 페이지 PDF 는 용량이 작아 ``pdf_blob``(bytea) 우선, full PDF 등 대용량은 ``pdf_path``.
원본 HWP/HWPX 는 저장하지 않는다. 신규 테이블 생성만, 기존 테이블 무변경(운영 자동적용 금지).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c4d5e6f70014'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e60013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'manual_pdf_artifacts',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.BigInteger(), nullable=True),
        sa.Column('manual', sa.Text(), nullable=False),
        sa.Column('version', sa.Text(), nullable=True),
        sa.Column('artifact_type', sa.Text(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False, server_default=sa.text("'staging'")),
        sa.Column('page_from', sa.Integer(), nullable=True),
        sa.Column('page_to', sa.Integer(), nullable=True),
        sa.Column('page_numbers', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('pdf_blob', sa.LargeBinary(), nullable=True),
        sa.Column('pdf_path', sa.Text(), nullable=True),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('content_hash', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False, server_default=sa.text("'generated'")),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_manual_pdf_artifacts_lookup', 'manual_pdf_artifacts',
                    ['manual', 'version', 'status'])


def downgrade() -> None:
    op.drop_index('idx_manual_pdf_artifacts_lookup', table_name='manual_pdf_artifacts')
    op.drop_table('manual_pdf_artifacts')
