"""0006 guideline category overlay (실무지침 분류 편집)

Revision ID: a6b1c2d30006
Revises: e5f1a2b30005
Create Date: 2026-06-08 00:00:00.000000

PG overlay for the 실무지침 classification tree. The source data
(immigration_guidelines_db_v2.json) is NEVER modified — these tables only
provide editable display names / order / activation, plus per-row category
overrides keyed by row_id. Additive; does not touch existing tables.

Categories are GLOBAL (shared, like the guidelines JSON) — no tenant_id.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a6b1c2d30006'
down_revision: Union[str, Sequence[str], None] = 'e5f1a2b30005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'guideline_categories',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('parent_id', sa.BigInteger(), nullable=True),
        sa.Column('level', sa.Text(), nullable=False),         # major | middle | minor
        sa.Column('source_key', sa.Text(), nullable=True),     # JSON 파생 분류 연결키(없으면 커스텀)
        sa.Column('display_name', sa.Text(), nullable=False),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('TRUE'), nullable=False),
        sa.Column('is_custom', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_key', name='uq_guideline_category_source_key'),
    )
    op.create_index('idx_guideline_category_parent', 'guideline_categories', ['parent_id'], unique=False)
    op.create_index('idx_guideline_category_level', 'guideline_categories', ['level'], unique=False)

    op.create_table(
        'guideline_category_overrides',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('row_id', sa.Text(), nullable=False),
        sa.Column('category_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('row_id', name='uq_guideline_override_row'),
    )
    op.create_index('idx_guideline_override_category', 'guideline_category_overrides', ['category_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_guideline_override_category', table_name='guideline_category_overrides')
    op.drop_table('guideline_category_overrides')
    op.drop_index('idx_guideline_category_level', table_name='guideline_categories')
    op.drop_index('idx_guideline_category_parent', table_name='guideline_categories')
    op.drop_table('guideline_categories')
