"""0015 전자명함(business card) 컬럼 (tenants)

마이페이지 계정별 전자명함을 저장/공개 공유하기 위해 ``tenants`` 에 컬럼을 추가한다.
공개 페이지(/card/{slug})는 ``card_is_public=true`` 인 명함만 노출하며, 내부 정보
(login_id/role/sheet key/secret 등)는 절대 공개하지 않는다.

- card_bio          TEXT     : 약력
- card_work_fields  JSONB    : 업무분야 문자열 배열
- card_phone        TEXT     : 명함 전화번호(빈 값이면 users.contact_tel fallback)
- card_address      TEXT     : 명함 주소(빈 값이면 tenants.office_adr fallback)
- card_logo_url     TEXT     : 로고 URL(빈 값이면 /hanwoori-logo-new.png fallback)
- card_public_slug  TEXT UNIQUE : 공개 URL slug
- card_is_public    BOOLEAN  : 공개 여부(기본 false)

신규 컬럼 추가만 하며 기존 데이터/컬럼은 변경하지 않는다(모두 nullable / 기본값 false).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'd1e2f3a40015'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f70014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenants', sa.Column('card_bio', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('card_work_fields', JSONB(), nullable=True))
    op.add_column('tenants', sa.Column('card_phone', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('card_address', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('card_logo_url', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('card_public_slug', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column(
        'card_is_public', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    # 공개 slug 는 전역 유일(공개/비공개 무관, 빈 값은 NULL → 유니크 제약 영향 없음)
    op.create_unique_constraint('uq_tenants_card_public_slug', 'tenants', ['card_public_slug'])


def downgrade() -> None:
    op.drop_constraint('uq_tenants_card_public_slug', 'tenants', type_='unique')
    op.drop_column('tenants', 'card_is_public')
    op.drop_column('tenants', 'card_public_slug')
    op.drop_column('tenants', 'card_logo_url')
    op.drop_column('tenants', 'card_address')
    op.drop_column('tenants', 'card_phone')
    op.drop_column('tenants', 'card_work_fields')
    op.drop_column('tenants', 'card_bio')
