"""0019 로그인 실패 제한/계정잠금 테이블 (login_attempts)

동일 login_id 의 연속 로그인 실패를 카운트하고 일정 횟수 초과 시 잠금한다.
단일세션/is_active 차단과 독립(인증 이전 단계). 신규 테이블 추가만(additive).

- login_attempts.login_id (PK)  : 계정 식별자(소문자 정규화 권장)
- failed_count                  : 연속 실패 횟수
- first_failed_at/last_failed_at: 실패 시각
- locked_until                  : 잠금 해제 시각(NULL=비잠금)
- last_ip/last_user_agent       : 해시 또는 원문(IP는 짧게) — 진단용

Revision ID: b2c3d4e50019
Revises: a1b2c3d40018
Create Date: 2026-06-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e50019'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d40018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'login_attempts',
        sa.Column('login_id', sa.Text(), nullable=False),
        sa.Column('failed_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('first_failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_ip', sa.Text(), nullable=True),
        sa.Column('last_user_agent', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('login_id', name='pk_login_attempts'),
    )


def downgrade() -> None:
    op.drop_table('login_attempts')
