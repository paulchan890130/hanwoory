"""0020 약관/개인정보 동의 테이블 (terms_versions, user_terms_acceptances)

이용약관·개인정보처리방침·고유식별정보 처리 동의·계정공유 금지 확인을 버전 단위로
관리하고, 사용자별 동의 기록을 남긴다. 신규 테이블 추가만(additive).

- terms_versions          : (type, version) 단위 약관 본문, is_active 로 현행 버전 지정
- user_terms_acceptances  : 사용자(login_id)별 동의 기록(버전 id, ip, ua, 시각)

Revision ID: c3d4e5f60020
Revises: b2c3d4e50019
Create Date: 2026-06-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f60020'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e50019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'terms_versions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('type', sa.Text(), nullable=False),       # tos|privacy|unique_id|no_share
        sa.Column('version', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('effective_date', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_terms_versions'),
        sa.UniqueConstraint('type', 'version', name='uq_terms_type_version'),
    )
    op.create_index('idx_terms_active', 'terms_versions', ['type', 'is_active'])

    op.create_table(
        'user_terms_acceptances',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('login_id', sa.Text(), nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=True),
        sa.Column('terms_version_id', sa.BigInteger(), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('ip', sa.Text(), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_user_terms_acceptances'),
        sa.UniqueConstraint('login_id', 'terms_version_id', name='uq_user_terms_once'),
    )
    op.create_index('idx_user_terms_login', 'user_terms_acceptances', ['login_id'])


def downgrade() -> None:
    op.drop_index('idx_user_terms_login', table_name='user_terms_acceptances')
    op.drop_table('user_terms_acceptances')
    op.drop_index('idx_terms_active', table_name='terms_versions')
    op.drop_table('terms_versions')
