"""0011 agent_rrn 암호화 컬럼 (tenants) — Phase I-1J-6E

Revision ID: f1a2b3c40011
Revises: e0f1a2b30010
Create Date: 2026-06-11 00:00:00.000000

행정사 주민등록번호(agent_rrn)를 복호화 가능한 암호문으로 1회 저장해 PDF 자동출력에 쓰기 위해
``tenants`` 에 컬럼을 추가한다. **평문 컬럼은 만들지 않는다.** 기존 ``agent_rrn_hash`` 는
그대로 두되 출력 소스로 쓰지 않는다(검증/기록용).

- agent_rrn_encrypted   TEXT      : Fernet 암호문(PDF 출력 소스)
- agent_rrn_last4       VARCHAR(4): 표시 보조용 마지막 4자리(원문 아님)
- agent_rrn_updated_at  TIMESTAMPTZ: 마지막 변경 시각

신규 컬럼 추가만 하며 기존 데이터/컬럼은 변경하지 않는다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c40011'
down_revision: Union[str, Sequence[str], None] = 'e0f1a2b30010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenants', sa.Column('agent_rrn_encrypted', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('agent_rrn_last4', sa.String(length=4), nullable=True))
    op.add_column('tenants', sa.Column('agent_rrn_updated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('tenants', 'agent_rrn_updated_at')
    op.drop_column('tenants', 'agent_rrn_last4')
    op.drop_column('tenants', 'agent_rrn_encrypted')
