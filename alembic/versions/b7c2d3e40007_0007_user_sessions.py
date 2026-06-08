"""0007 user_sessions (single-session enforcement)

Revision ID: b7c2d3e40007
Revises: a6b1c2d30006
Create Date: 2026-06-08 00:00:00.000000

단일 세션(새 로그인 우선) 정책용 세션 원장. 일반 로그인 세션만 대상이며
is_kiosk=true 세션(추후 서명 키오스크/QR)은 분리 가능하도록 설계. 기존 테이블 무변경.
앱은 FEATURE_SINGLE_SESSION=true 일 때만 이 테이블을 사용한다(기본 off → 기존 로그인 그대로).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c2d3e40007'
down_revision: Union[str, Sequence[str], None] = 'a6b1c2d30006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_sessions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('login_id', sa.Text(), nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        sa.Column('session_id', sa.Text(), nullable=False),
        sa.Column('device_label', sa.Text(), nullable=True),
        sa.Column('user_agent_hash', sa.Text(), nullable=True),
        sa.Column('ip_hash', sa.Text(), nullable=True),
        sa.Column('is_kiosk', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_reason', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', name='uq_user_session_sid'),
    )
    op.create_index('idx_user_session_login', 'user_sessions', ['login_id'], unique=False)
    op.create_index('idx_user_session_login_active', 'user_sessions', ['login_id'],
                    unique=False, postgresql_where=sa.text('revoked_at IS NULL'))


def downgrade() -> None:
    op.drop_index('idx_user_session_login_active', table_name='user_sessions', postgresql_where=sa.text('revoked_at IS NULL'))
    op.drop_index('idx_user_session_login', table_name='user_sessions')
    op.drop_table('user_sessions')
