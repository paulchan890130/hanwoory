"""0018 고객 외국인등록번호 뒷자리(reg_back) 암호화 컬럼 (customers)

고객 reg_back(외국인등록번호 뒷자리, 고유식별정보)을 복호화 가능한 암호문으로 저장하기 위해
``customers`` 에 보조 컬럼을 추가한다.

- reg_back_encrypted   TEXT       : Fernet 암호문(상세/문서출력 복호화 소스)
- reg_back_hash        TEXT       : HMAC-SHA256(tenant_id:정규화7자리) 정확검색용
- reg_back_last4       VARCHAR(4) : 뒤 4자리 검색/표시 보조
- reg_back_migrated_at TIMESTAMPTZ: 변환 시각(NULL=미변환)
- reg_back_enc_ver     VARCHAR(8) : 암호화/알고리즘 버전 태그('v1')

**기존 평문 컬럼 ``reg_back`` 은 삭제하지 않는다(1차 fallback·rollback 안전).**
신규 컬럼 추가만(additive). 데이터 변환은 별도 스크립트(운영 적용은 승인 후).

Revision ID: a1b2c3d40018
Revises: f3a4b5c60017
Create Date: 2026-06-17 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d40018'
down_revision: Union[str, Sequence[str], None] = 'f3a4b5c60017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('customers', sa.Column('reg_back_encrypted', sa.Text(), nullable=True))
    op.add_column('customers', sa.Column('reg_back_hash', sa.Text(), nullable=True))
    op.add_column('customers', sa.Column('reg_back_last4', sa.String(length=4), nullable=True))
    op.add_column('customers', sa.Column('reg_back_migrated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('customers', sa.Column('reg_back_enc_ver', sa.String(length=8), nullable=True))
    # 정확검색(HMAC) 인덱스 — tenant 별 reg_back_hash 조회 가속.
    op.create_index('idx_customers_reg_back_hash', 'customers', ['tenant_id', 'reg_back_hash'])
    op.create_index('idx_customers_reg_back_last4', 'customers', ['tenant_id', 'reg_back_last4'])


def downgrade() -> None:
    op.drop_index('idx_customers_reg_back_last4', table_name='customers')
    op.drop_index('idx_customers_reg_back_hash', table_name='customers')
    op.drop_column('customers', 'reg_back_enc_ver')
    op.drop_column('customers', 'reg_back_migrated_at')
    op.drop_column('customers', 'reg_back_last4')
    op.drop_column('customers', 'reg_back_hash')
    op.drop_column('customers', 'reg_back_encrypted')
