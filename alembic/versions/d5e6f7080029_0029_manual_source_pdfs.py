"""0029 원문 매뉴얼 PDF 저장소 — manual_source_pdfs

Revision ID: d5e6f7080029
Revises: c3d4e5f60028
Create Date: 2026-07-07 00:00:00.000000

실무지침 업데이트 검토함의 '원문 열기'용 원본 매뉴얼 PDF 를 PostgreSQL BYTEA 로
보관한다. manual_type(visa/stay)별 **최신 1개 + 직전 1개만** 유지(retention 은
서비스 레이어가 업로드 시 강제 — 3번째로 오래된 행 삭제).

- Render ephemeral filesystem / Google Drive 미의존, PG = source of truth.
- 용량: 매뉴얼 PDF ≈ 12MB × 최대 4행 ≈ 50MB 수준.
- OOM 규칙: 목록은 pdf_data defer, blob 은 id 단건 조회만 (서비스에서 강제).

additive — 신규 테이블 1개, 기존 데이터/테이블 무변경.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7080029'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f60028'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'manual_source_pdfs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('manual_type', sa.Text(), nullable=False),
        sa.Column('version_label', sa.Text(), nullable=True),
        sa.Column('original_filename', sa.Text(), nullable=False),
        sa.Column('content_type', sa.Text(), nullable=False),
        sa.Column('file_size', sa.BigInteger(), nullable=False),
        sa.Column('sha256', sa.Text(), nullable=False),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('pdf_data', sa.LargeBinary(), nullable=False),
        sa.Column('is_current', sa.Boolean(), nullable=False),
        sa.Column('uploaded_by', sa.Text(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_manual_source_pdfs_type_current', 'manual_source_pdfs',
                    ['manual_type', 'is_current'])


def downgrade() -> None:
    op.drop_index('idx_manual_source_pdfs_type_current', table_name='manual_source_pdfs')
    op.drop_table('manual_source_pdfs')
