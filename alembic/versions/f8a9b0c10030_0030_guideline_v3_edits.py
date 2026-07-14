"""0030 실무지침 v3 편집 오버레이 — guideline_v3_edits

Revision ID: f8a9b0c10030
Revises: d5e6f7080029
Create Date: 2026-07-14 00:00:00.000000

v3 자격중심 실무지침의 관리자 CRUD 영속 계층. 정본 JSON(backend/data/guidelines_v3,
이미지 베이크)은 수정하지 않고, 엔터티 단위 오버레이(upsert/delete 톰스톤)를 PG에
보관해 읽기 시점에 병합한다 — guideline_categories(0006) 오버레이 원칙과 동일.

- 엔터티당 최신 상태 1행(UNIQUE(entity_type, entity_id)). 변경 이력은 audit_logs.
- payload = 엔터티 전체 dict(JSON 직렬화 텍스트). delete 톰스톤은 payload NULL.
- FEATURE_GUIDELINES_V3_EDIT off(기본) → 테이블 미사용, 기존 동작 불변.

additive — 신규 테이블 1개, 기존 데이터/테이블 무변경.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f8a9b0c10030'
down_revision: Union[str, Sequence[str], None] = 'd5e6f7080029'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'guideline_v3_edits',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('entity_type', sa.Text(), nullable=False),
        sa.Column('entity_id', sa.Text(), nullable=False),
        sa.Column('op', sa.Text(), nullable=False, server_default='upsert'),
        sa.Column('payload', sa.Text(), nullable=True),
        sa.Column('updated_by', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('entity_type', 'entity_id', name='uq_guideline_v3_edit_entity'),
    )
    op.create_index('idx_guideline_v3_edits_type', 'guideline_v3_edits', ['entity_type'])


def downgrade() -> None:
    op.drop_index('idx_guideline_v3_edits_type', table_name='guideline_v3_edits')
    op.drop_table('guideline_v3_edits')
