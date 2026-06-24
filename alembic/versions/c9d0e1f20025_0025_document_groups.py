"""0025 업무별 준비서류 중분류 테이블 (document_groups)

공개 홈페이지 /documents 의 중분류(F-1 … 중국 공증·아포스티유)를 관리자가
CRUD 할 수 있도록 영구 저장하는 신규 테이블 1개를 추가한다(additive only).

글↔중분류 연결은 기존 marketing_posts.tags 의 doc_group:<group_key> 태그를
그대로 사용한다(A안) — 글 테이블/slug/URL 은 변경하지 않는다.

v1 정책: 물리 삭제 없음(공개/비공개 전환만) → DELETE API 없음.

down_revision = a5c6d7e80024 (0024 user_role) — 단일 head 유지.
(직전 작업의 0024 라벨은 user_role 이 선점하고 있어 0025 로 재배치했다.)
운영 DB 에는 적용하지 않는다(로컬 전용).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9d0e1f20025'
down_revision: Union[str, Sequence[str], None] = 'a5c6d7e80024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'document_groups',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('group_key', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=False),
        sa.Column('is_published', sa.Text(), nullable=True),
        sa.Column('created_at', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.Text(), nullable=True),
        sa.Column(
            'db_created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('group_key', name='uq_document_groups_group_key'),
    )
    op.create_index('idx_document_groups_sort', 'document_groups', ['sort_order'])


def downgrade() -> None:
    op.drop_index('idx_document_groups_sort', table_name='document_groups')
    op.drop_table('document_groups')
