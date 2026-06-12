"""0012 doc_tree_nodes + doc_required_documents (문서자동작성 편집형 트리 — PG 설정, Phase I-1J-6O)

Revision ID: a2b3c4d50012
Revises: f1a2b3c40011
Create Date: 2026-06-12 00:00:00.000000

문서자동작성 선택 구조(구분/민원/종류/세부)와 필요서류를 관리자 편집형 DB 설정으로
이관(Phase I-1J-6O). 기존 quick_doc.py 하드코딩 상수는 fallback/seed 용도로만 남기고,
DB 에 설정이 있고 ``FEATURE_PG_QUICK_DOC_CONFIG`` 가 켜졌을 때 DB 값을 우선 사용한다.

- ``doc_tree_nodes``: self-referential 트리(category→petition→type→subtype). tenant_id NULL=전역.
- ``doc_required_documents``: 노드별 필요서류(main/agent) + templates/ PDF 자동매핑 상태.

신규 테이블 생성만 하며 기존 테이블은 변경하지 않는다. 운영 DB 에 자동 적용 금지(수동 upgrade).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2b3c4d50012'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c40011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'doc_tree_nodes',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        sa.Column('parent_id', sa.BigInteger(), nullable=True),
        sa.Column('level', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], onupdate='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['doc_tree_nodes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_doc_tree_nodes_parent', 'doc_tree_nodes', ['parent_id'])
    op.create_index('ix_doc_tree_nodes_level', 'doc_tree_nodes', ['level'])

    op.create_table(
        'doc_required_documents',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('node_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('doc_group', sa.Text(), nullable=False, server_default=sa.text("'main'")),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('template_filename', sa.Text(), nullable=True),
        sa.Column('template_status', sa.Text(), nullable=False, server_default=sa.text("'missing'")),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['node_id'], ['doc_tree_nodes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_doc_required_documents_node', 'doc_required_documents', ['node_id'])


def downgrade() -> None:
    op.drop_index('ix_doc_required_documents_node', table_name='doc_required_documents')
    op.drop_table('doc_required_documents')
    op.drop_index('ix_doc_tree_nodes_level', table_name='doc_tree_nodes')
    op.drop_index('ix_doc_tree_nodes_parent', table_name='doc_tree_nodes')
    op.drop_table('doc_tree_nodes')
