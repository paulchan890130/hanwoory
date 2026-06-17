"""0021 계정공유 의심 감지 + 로그인 이력 + 보안 알림 (베타)

등록기기 기능은 베타 범위에서 제외. 로그인/보안 이벤트 이력, 계정 보안상태,
내부 알림 3종 테이블을 추가한다. 모두 신규 테이블(additive).

- login_events           : 로그인/보안 이벤트 이력(감지 소스·UI). IP/UA 는 해시+마스킹/요약만 저장(원문 전체 미저장)
- account_security       : 계정별 의심 누적·보안차단 상태(login_id PK). is_active(관리자 비활성)와 구분
- security_notifications : 내부 알림(관리자/본인). 외부 문자/메일/카카오 미사용

Revision ID: d4e5f6070021
Revises: c3d4e5f60020
Create Date: 2026-06-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6070021'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f60020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'login_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        sa.Column('login_id', sa.Text(), nullable=False),
        sa.Column('event_type', sa.Text(), nullable=False),
        sa.Column('ip_hash', sa.Text(), nullable=True),
        sa.Column('ip_prefix_masked', sa.Text(), nullable=True),     # 123.123.***.***
        sa.Column('user_agent_hash', sa.Text(), nullable=True),
        sa.Column('user_agent_summary', sa.Text(), nullable=True),   # Windows Chrome
        sa.Column('success', sa.Boolean(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('risk_level', sa.Text(), nullable=True),           # none|low|suspicious|blocked
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_login_events'),
    )
    op.create_index('idx_login_events_login_created', 'login_events', ['login_id', 'created_at'])
    op.create_index('idx_login_events_type', 'login_events', ['login_id', 'event_type'])

    op.create_table(
        'account_security',
        sa.Column('login_id', sa.Text(), nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        sa.Column('suspicion_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_suspicion_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('security_blocked', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('blocked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('blocked_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('login_id', name='pk_account_security'),
    )

    op.create_table(
        'security_notifications',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('recipient_login_id', sa.Text(), nullable=False),
        sa.Column('recipient_role', sa.Text(), nullable=False),      # admin|user
        sa.Column('tenant_id', sa.Text(), nullable=True),
        sa.Column('type', sa.Text(), nullable=False),                # suspicious|blocked|unblocked
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('related_login_id', sa.Text(), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_security_notifications'),
    )
    op.create_index('idx_sec_notif_recipient', 'security_notifications', ['recipient_login_id', 'is_read'])


def downgrade() -> None:
    op.drop_index('idx_sec_notif_recipient', table_name='security_notifications')
    op.drop_table('security_notifications')
    op.drop_table('account_security')
    op.drop_index('idx_login_events_type', table_name='login_events')
    op.drop_index('idx_login_events_login_created', table_name='login_events')
    op.drop_table('login_events')
