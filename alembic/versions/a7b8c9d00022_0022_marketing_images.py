"""0022 marketing_images — 마케팅 이미지 PG(BYTEA) 저장 (Google Drive 대체)

업로드 이미지를 Google Drive 대신 PostgreSQL BYTEA 로 저장한다. 게시글은 내부 URL
(``/api/marketing/images/{id}``) 만 참조한다. 기존 Drive URL 게시글은 자동 이관하지
않고 그대로 둔다(외부 URL 로 계속 표시). 순수 additive(신규 테이블만) — rollback = drop.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a7b8c9d00022"
down_revision = "d4e5f6070021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketing_images",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_marketing_images_tenant", "marketing_images", ["tenant_id"])
    op.create_index("idx_marketing_images_created", "marketing_images", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_marketing_images_created", table_name="marketing_images")
    op.drop_index("idx_marketing_images_tenant", table_name="marketing_images")
    op.drop_table("marketing_images")
