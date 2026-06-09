"""0008 signature_pad_tokens (always-on signature pad URL token)

Revision ID: c8d3e4f50008
Revises: b7c2d3e40007
Create Date: 2026-06-09 00:00:00.000000

상시 서명패드(/sign/pad) URL 토큰 상태 — 테넌트당 active 1행. 재발급 시 같은 행의
token_id(UUID4)/issued_at/expires_at 을 갱신해 기존 URL 을 즉시 무효화한다. 토큰
문자열은 저장하지 않고 payload jti 를 token_id 와 대조해 검증한다. 신규 테이블 생성만
하며 기존 테이블은 변경하지 않는다. 앱은 PostgreSQL 구성 시에만 이 테이블을 사용한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8d3e4f50008'
down_revision: Union[str, Sequence[str], None] = 'b7c2d3e40007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'signature_pad_tokens',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=False),
        sa.Column('token_id', sa.Text(), nullable=False),
        sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('issued_by_login_id', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', name='uq_pad_token_per_tenant'),
    )


def downgrade() -> None:
    op.drop_table('signature_pad_tokens')
