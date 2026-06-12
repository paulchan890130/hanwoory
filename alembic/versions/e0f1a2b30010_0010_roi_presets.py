"""0010 roi_presets (스캔 ROI 좌표 프리셋 — PG-only, Phase I)

Revision ID: e0f1a2b30010
Revises: d9e0f1a20009
Create Date: 2026-06-10 00:00:00.000000

ROI 프리셋(스캔 OCR 좌표)을 Google Sheets ``ROI_프리셋`` 탭에서 PostgreSQL 로 이관(Phase I).
테넌트당 슬롯 1/2/3(슬롯1=기본값). data 는 passport/arc 좌표 등 임의 구조라 JSONB.
신규 테이블 생성만 하며 기존 테이블은 변경하지 않는다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e0f1a2b30010'
down_revision: Union[str, Sequence[str], None] = 'd9e0f1a20009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'roi_presets',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=False),
        sa.Column('slot', sa.Integer(), nullable=False),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'slot', name='uq_roi_preset_per_tenant'),
    )


def downgrade() -> None:
    op.drop_table('roi_presets')
