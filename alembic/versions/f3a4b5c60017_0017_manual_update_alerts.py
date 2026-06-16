"""0017 매뉴얼 업데이트 알림 테이블

첨부파일 제목 변동을 1일 1회 감지해 alert event 를 만들고, 전 사용자가 최초 로그인 시
알림을 보며 "이번 업데이트 다시 알리지 않음"으로 본인만 숨길 수 있게 한다.

- manual_update_alert_events     : 제목 변동 1건당 1행(manual+new_title_hash 멱등)
- manual_update_alert_dismissals : 사용자(login_id)별 event dismiss 기록

모두 신규 테이블 추가만(additive). Google Drive/Sheets 미사용, PG 저장.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a4b5c60017'
down_revision: Union[str, Sequence[str], None] = 'e2f3a4b50016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'manual_update_alert_events',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('manual', sa.Text(), nullable=False),
        sa.Column('old_title', sa.Text(), nullable=True),
        sa.Column('new_title', sa.Text(), nullable=True),
        sa.Column('old_title_hash', sa.Text(), nullable=True),
        sa.Column('new_title_hash', sa.Text(), nullable=True),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('version_label', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('manual', 'new_title_hash', name='uq_manual_alert_manual_titlehash'),
    )
    op.create_index('idx_manual_alert_active', 'manual_update_alert_events', ['is_active', 'detected_at'])

    op.create_table(
        'manual_update_alert_dismissals',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('alert_event_id', sa.BigInteger(), nullable=False),
        sa.Column('login_id', sa.Text(), nullable=False),
        sa.Column('dismissed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('dismiss_type', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['alert_event_id'], ['manual_update_alert_events.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('alert_event_id', 'login_id', name='uq_manual_alert_dismissal'),
    )
    op.create_index('idx_manual_alert_dismissal_user', 'manual_update_alert_dismissals', ['login_id'])


def downgrade() -> None:
    op.drop_index('idx_manual_alert_dismissal_user', table_name='manual_update_alert_dismissals')
    op.drop_table('manual_update_alert_dismissals')
    op.drop_index('idx_manual_alert_active', table_name='manual_update_alert_events')
    op.drop_table('manual_update_alert_events')
