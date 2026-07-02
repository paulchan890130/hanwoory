"""0026 고객 외부 사이트 계정(하이코리아/소시넷) 컬럼 — customers

Revision ID: a1b2c3d40026
Revises: c9d0e1f20025
Create Date: 2026-07-02 00:00:00.000000

고객별 외부 사이트(하이코리아/소시넷) 로그인 계정을 저장한다.
- 아이디/비밀번호 **모두 평문 TEXT**로 저장한다(사용자 지시). 암호화/복호화 없음
  (encrypt_pii/decrypt_pii·CUSTOMER_PII_ENCRYPTION_KEY 의존성 없음).
- 목록/검색 API·로그에는 노출하지 않고, 고객 상세 카드에서만 확인/편집한다.

신규 컬럼 추가만 하며 기존 데이터/컬럼은 변경하지 않는다(additive, nullable).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d40026'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f20025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('customers', sa.Column('hikorea_id', sa.Text(), nullable=True))
    op.add_column('customers', sa.Column('hikorea_pw', sa.Text(), nullable=True))
    op.add_column('customers', sa.Column('socinet_id', sa.Text(), nullable=True))
    op.add_column('customers', sa.Column('socinet_pw', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('customers', 'socinet_pw')
    op.drop_column('customers', 'socinet_id')
    op.drop_column('customers', 'hikorea_pw')
    op.drop_column('customers', 'hikorea_id')
