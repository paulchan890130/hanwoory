"""0016 전자명함 로고 파일 컬럼 (tenants)

마이페이지에서 로고를 **파일 업로드**로 받아 PostgreSQL 에 저장하기 위한 컬럼.
기존 ``card_logo_url`` (0015, 외부 URL) 은 하위 호환용으로 그대로 둔다 —
공개 표시 우선순위는 업로드 로고 > card_logo_url > 없음.

- card_logo_filename   TEXT       : 원본 파일명(표시/다운로드용, 신뢰 입력 아님)
- card_logo_mime       TEXT       : 저장 MIME(image/jpeg|png|webp — 서버 검증값)
- card_logo_size       INTEGER    : 바이트 크기(검증/표시용)
- card_logo_bytes      BYTEA      : 이미지 원본 바이트
- card_logo_updated_at TIMESTAMPTZ: 마지막 업로드 시각(캐시 무효화 ?v= 용)

모두 nullable — 신규 컬럼 추가만, 기존 데이터/컬럼 변경 없음(additive).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e2f3a4b50016'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a40015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenants', sa.Column('card_logo_filename', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('card_logo_mime', sa.Text(), nullable=True))
    op.add_column('tenants', sa.Column('card_logo_size', sa.Integer(), nullable=True))
    op.add_column('tenants', sa.Column('card_logo_bytes', sa.LargeBinary(), nullable=True))
    op.add_column('tenants', sa.Column(
        'card_logo_updated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('tenants', 'card_logo_updated_at')
    op.drop_column('tenants', 'card_logo_bytes')
    op.drop_column('tenants', 'card_logo_size')
    op.drop_column('tenants', 'card_logo_mime')
    op.drop_column('tenants', 'card_logo_filename')
