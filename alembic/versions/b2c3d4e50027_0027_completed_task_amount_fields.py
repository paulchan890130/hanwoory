"""0027 완료업무 금액 스냅샷 컬럼 — completed_tasks

Revision ID: b2c3d4e50027
Revises: a1b2c3d40026
Create Date: 2026-07-07 00:00:00.000000

완료처리(active_tasks → completed_tasks) 시점의 금액을 completed_tasks 에도
스냅샷으로 남겨, 완료업무 화면에서 금액을 확인할 수 있게 한다.

- active_tasks 의 금액 컬럼과 **동일한 이름·동일 타입(TEXT)** 으로 맞춘다
  (transfer/cash/card/stamp/receivable/planned_expense).
- 전부 **nullable** 로 추가한다. 기존 완료업무는 금액을 확실히 알 수 없으므로
  NULL(= 미확인) 로 둔다. NULL 과 "0"(0원) 은 의미가 다르므로 backfill 하지 않는다.
- 신규 컬럼 추가만 하는 additive migration — 기존 데이터/컬럼은 건드리지 않는다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e50027'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d40026'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_MONEY_COLS = ("transfer", "cash", "card", "stamp", "receivable", "planned_expense")


def upgrade() -> None:
    for col in _MONEY_COLS:
        op.add_column('completed_tasks', sa.Column(col, sa.Text(), nullable=True))


def downgrade() -> None:
    for col in reversed(_MONEY_COLS):
        op.drop_column('completed_tasks', col)
