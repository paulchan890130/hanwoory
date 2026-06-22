"""0024 users.role — 준 관리자(sub_admin) 권한 컬럼

관리자 페이지에서 특정 계정에 "준 관리자" 권한을 부여/회수하기 위한 role 컬럼.
값: 'user'(기본) | 'sub_admin' | 'admin'. full admin 여부는 기존 is_admin boolean 이
source of truth 이고, role 은 그와 별개로 sub_admin 을 구분하기 위한 추가 컬럼이다
(is_admin 동작은 변경하지 않는다 — additive).

- 신규 컬럼만 추가(additive, 데이터 손실 없음).
- 기본값 'user'. 기존 is_admin=true 계정은 'admin' 으로 backfill.

운영 적용은 별도 승인 전 금지(로컬 head 만 갱신). 단일 head 유지.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a5c6d7e80024'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e10023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('role', sa.Text(), server_default=sa.text("'user'"), nullable=False),
    )
    # 기존 관리자 계정은 role='admin' 으로 backfill (is_admin 이 여전히 source of truth).
    op.execute("UPDATE users SET role = 'admin' WHERE is_admin = true")


def downgrade() -> None:
    op.drop_column('users', 'role')
