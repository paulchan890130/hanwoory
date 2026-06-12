"""0013 manual_review_decisions reviewer override columns (PG manual-update 수동 페이지 지정)

Revision ID: b3c4d5e60013
Revises: a2b3c4d50012
Create Date: 2026-06-12 00:00:00.000000

자동 매칭이 틀렸을 때 관리자가 직접 기존/후보 페이지를 지정(override)할 수 있도록
``manual_review_decisions`` 에 reviewer_* 컬럼을 추가. 자동 추천값(candidate 테이블)은
그대로 보존하며, override 가 있으면 화면/diff/운영반영의 '현재 검토 기준'으로 사용된다.
컬럼 추가만 하며 기존 데이터는 변경하지 않는다(운영 DB 자동 적용 금지).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e60013'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d50012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('manual_review_decisions', sa.Column('reviewer_baseline_from', sa.Integer(), nullable=True))
    op.add_column('manual_review_decisions', sa.Column('reviewer_baseline_to', sa.Integer(), nullable=True))
    op.add_column('manual_review_decisions', sa.Column('reviewer_candidate_from', sa.Integer(), nullable=True))
    op.add_column('manual_review_decisions', sa.Column('reviewer_candidate_to', sa.Integer(), nullable=True))
    op.add_column('manual_review_decisions', sa.Column('reviewer_override_reason', sa.Text(), nullable=True))
    op.add_column('manual_review_decisions', sa.Column('reviewer_override_by', sa.Text(), nullable=True))
    op.add_column('manual_review_decisions', sa.Column('reviewer_override_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in ('reviewer_override_at', 'reviewer_override_by', 'reviewer_override_reason',
                'reviewer_candidate_to', 'reviewer_candidate_from',
                'reviewer_baseline_to', 'reviewer_baseline_from'):
        op.drop_column('manual_review_decisions', col)
