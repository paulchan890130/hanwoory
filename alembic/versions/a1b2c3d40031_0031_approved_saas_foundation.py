"""0031 approved-SaaS foundation — office_applications, activation_tokens, tenant/user lifecycle cols

수동 승인형 B2B SaaS 기반. **전부 additive**(신규 테이블 2개 + 기존 tenants/users 컬럼 추가 + 안전 backfill).
기존 테이블/컬럼 삭제·의미변경 없음. 기존 active 사용자 일괄 비활성화 없음.

backfill 정책:
- tenants: service_tier='managed_basic', service_status = is_active ? 'active' : 'pending_activation',
  seat_limit = greatest(2, 해당 tenant 의 현재 active user 수)  → 기존 3명 이상이어도 정지/삭제 안 함.
- users: account_status = is_active ? 'active' : 'disabled'.

신규 승인 tenant 만 애플리케이션 레벨에서 seat_limit=2 를 강제한다(여기 backfill 은 기존 보존용).

운영 적용은 별도 승인 전 금지(로컬 head 만 갱신). 단일 head 유지.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a1b2c3d40031"
down_revision: Union[str, Sequence[str], None] = "f8a9b0c10030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── office_applications (신규) ──────────────────────────────────────────
    op.create_table(
        "office_applications",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("application_id", sa.Text(), nullable=False, unique=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("office_name", sa.Text(), nullable=False),
        sa.Column("representative_name", sa.Text(), nullable=True),
        sa.Column("business_registration_number", sa.Text(), nullable=True),
        sa.Column("office_address", sa.Text(), nullable=True),
        sa.Column("office_phone", sa.Text(), nullable=True),
        sa.Column("applicant_name", sa.Text(), nullable=True),
        sa.Column("applicant_email", sa.Text(), nullable=True),
        sa.Column("applicant_phone", sa.Text(), nullable=True),
        sa.Column("intended_use", sa.Text(), nullable=True),
        sa.Column("requested_user_1_name", sa.Text(), nullable=True),
        sa.Column("requested_user_1_email", sa.Text(), nullable=True),
        sa.Column("requested_user_2_name", sa.Text(), nullable=True),
        sa.Column("requested_user_2_email", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.Text(), nullable=True),
        sa.Column("rejection_reason_public", sa.Text(), nullable=True),
        sa.Column("review_note_internal", sa.Text(), nullable=True),
        sa.Column("approved_tenant_id", sa.Text(), nullable=True),
        sa.Column("duplicate_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("submit_ip_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_office_app_status_time", "office_applications", ["status", "created_at"])
    # 신청 1건당 tenant 1개(멱등 승인) — approved_tenant_id 는 승인된 건에만 채워지므로 부분 unique.
    op.create_index(
        "uq_office_app_approved_tenant",
        "office_applications",
        ["approved_tenant_id"],
        unique=True,
        postgresql_where=sa.text("approved_tenant_id IS NOT NULL"),
    )

    # ── activation_tokens (신규) — 원문 미저장, hash 만 ──────────────────────
    op.create_table(
        "activation_tokens",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("login_id", sa.Text(), nullable=False, index=True),
        sa.Column("tenant_id", sa.Text(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False, server_default=sa.text("'activation'")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # ── tenants 컬럼 추가 (additive) ────────────────────────────────────────
    op.add_column("tenants", sa.Column("service_tier", sa.Text(), nullable=False, server_default=sa.text("'managed_basic'")))
    op.add_column("tenants", sa.Column("seat_limit", sa.Integer(), nullable=False, server_default=sa.text("2")))
    op.add_column("tenants", sa.Column("service_status", sa.Text(), nullable=False, server_default=sa.text("'pending_activation'")))
    op.add_column("tenants", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenants", sa.Column("approved_by", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("source_application_id", sa.Text(), nullable=True))

    # ── users 컬럼 추가 (additive) ──────────────────────────────────────────
    op.add_column("users", sa.Column("account_status", sa.Text(), nullable=False, server_default=sa.text("'active'")))
    op.add_column("users", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("approved_by", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("replaced_by_user_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("replaces_user_id", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True))

    # ── backfill (기존 데이터 보존) ─────────────────────────────────────────
    # 기존 tenant: 활성이면 active, 아니면 pending_activation.
    op.execute("UPDATE tenants SET service_status = 'active' WHERE is_active = true")
    # seat_limit = greatest(2, tenant 별 active user 수). 기존 3명 이상이어도 축소 안 함.
    op.execute(
        """
        UPDATE tenants t
        SET seat_limit = GREATEST(2, sub.cnt)
        FROM (
            SELECT tenant_id, COUNT(*) AS cnt
            FROM users
            WHERE is_active = true
            GROUP BY tenant_id
        ) sub
        WHERE t.tenant_id = sub.tenant_id
        """
    )
    # 기존 user: account_status 를 is_active 로 backfill(비활성 → disabled).
    op.execute("UPDATE users SET account_status = 'disabled' WHERE is_active = false")


def downgrade() -> None:
    op.drop_column("users", "activated_at")
    op.drop_column("users", "invited_at")
    op.drop_column("users", "replaces_user_id")
    op.drop_column("users", "replaced_by_user_id")
    op.drop_column("users", "approved_by")
    op.drop_column("users", "approved_at")
    op.drop_column("users", "account_status")

    op.drop_column("tenants", "source_application_id")
    op.drop_column("tenants", "approved_by")
    op.drop_column("tenants", "approved_at")
    op.drop_column("tenants", "service_status")
    op.drop_column("tenants", "seat_limit")
    op.drop_column("tenants", "service_tier")

    op.drop_table("activation_tokens")
    op.drop_index("uq_office_app_approved_tenant", table_name="office_applications")
    op.drop_index("idx_office_app_status_time", table_name="office_applications")
    op.drop_table("office_applications")
