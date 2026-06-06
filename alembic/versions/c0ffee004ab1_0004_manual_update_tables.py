"""0004 manual update tables (PG single source of truth)

Revision ID: c0ffee004ab1
Revises: a9e88d5f778a
Create Date: 2026-06-06 16:00:00.000000

Additive, create-only. 기존 테이블을 변경/삭제하지 않는다.
manual update v1 의 baseline / 변경결과 / 검토 decision / 상태 테이블 10개를 생성한다.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c0ffee004ab1'
down_revision: Union[str, Sequence[str], None] = 'a9e88d5f778a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — create manual update tables (additive only)."""
    # manual_base_versions
    op.create_table(
        'manual_base_versions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('manual_label', sa.Text(), nullable=False),
        sa.Column('version', sa.Text(), nullable=False),
        sa.Column('source_sha256', sa.Text(), nullable=True),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('manual_label', 'version', name='uq_manual_base_versions_label_version'),
    )
    op.create_index('idx_manual_base_versions_label_active', 'manual_base_versions',
                    ['manual_label', 'is_active'], unique=False)

    # manual_base_pages
    op.create_table(
        'manual_base_pages',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('base_version_id', sa.BigInteger(), nullable=False),
        sa.Column('manual_label', sa.Text(), nullable=False),
        sa.Column('page_index', sa.Integer(), nullable=False),
        sa.Column('printed_page_no', sa.Integer(), nullable=True),
        sa.Column('title_guess', sa.Text(), nullable=True),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('text_hash', sa.Text(), nullable=True),
        sa.Column('normalized_text_hash', sa.Text(), nullable=True),
        sa.Column('keywords', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['base_version_id'], ['manual_base_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_manual_base_pages_ver_page', 'manual_base_pages',
                    ['base_version_id', 'page_index'], unique=False)
    op.create_index('idx_manual_base_pages_nhash', 'manual_base_pages',
                    ['normalized_text_hash'], unique=False)

    # manual_base_refs
    op.create_table(
        'manual_base_refs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('row_id', sa.Text(), nullable=False),
        sa.Column('item_index', sa.Integer(), nullable=True),
        sa.Column('manual_label', sa.Text(), nullable=True),
        sa.Column('manual_kr', sa.Text(), nullable=True),
        sa.Column('page_from', sa.Integer(), nullable=True),
        sa.Column('page_to', sa.Integer(), nullable=True),
        sa.Column('match_text', sa.Text(), nullable=True),
        sa.Column('match_type', sa.Text(), nullable=True),
        sa.Column('detailed_code', sa.Text(), nullable=True),
        sa.Column('business_name', sa.Text(), nullable=True),
        sa.Column('major_action_std', sa.Text(), nullable=True),
        sa.Column('snapshot_tag', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_manual_base_refs_row', 'manual_base_refs', ['row_id'], unique=False)
    op.create_index('idx_manual_base_refs_label', 'manual_base_refs', ['manual_label'], unique=False)

    # manual_update_runs
    op.create_table(
        'manual_update_runs',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('run_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('trigger', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('detected', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('detected_version', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('instance', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_manual_update_runs_run_at', 'manual_update_runs', ['run_at'], unique=False)

    # manual_update_versions
    op.create_table(
        'manual_update_versions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('version', sa.Text(), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('label_timestamps', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('changed_page_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('candidate_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('run_id', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['manual_update_runs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version', name='uq_manual_update_versions_version'),
    )
    op.create_index('idx_manual_update_versions_detected', 'manual_update_versions',
                    ['detected_at'], unique=False)

    # manual_update_changed_pages
    op.create_table(
        'manual_update_changed_pages',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('update_version_id', sa.BigInteger(), nullable=False),
        sa.Column('manual_label', sa.Text(), nullable=True),
        sa.Column('change_type', sa.Text(), nullable=True),
        sa.Column('baseline_page', sa.Integer(), nullable=True),
        sa.Column('new_page', sa.Integer(), nullable=True),
        sa.Column('similarity', sa.Float(), nullable=True),
        sa.Column('new_snippet', sa.Text(), nullable=True),
        sa.Column('baseline_snippet', sa.Text(), nullable=True),
        sa.Column('keywords', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['update_version_id'], ['manual_update_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_manual_update_changed_ver', 'manual_update_changed_pages',
                    ['update_version_id'], unique=False)

    # manual_update_candidates
    op.create_table(
        'manual_update_candidates',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('update_version_id', sa.BigInteger(), nullable=False),
        sa.Column('row_id', sa.Text(), nullable=False),
        sa.Column('item_index', sa.Integer(), nullable=True),
        sa.Column('manual_label', sa.Text(), nullable=True),
        sa.Column('old_page_from', sa.Integer(), nullable=True),
        sa.Column('old_page_to', sa.Integer(), nullable=True),
        sa.Column('candidate_page_from', sa.Integer(), nullable=True),
        sa.Column('candidate_page_to', sa.Integer(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('change_type', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Text(), nullable=True),
        sa.Column('action', sa.Text(), nullable=True),
        sa.Column('match_text', sa.Text(), nullable=True),
        sa.Column('new_snippet', sa.Text(), nullable=True),
        sa.Column('detailed_code', sa.Text(), nullable=True),
        sa.Column('business_name', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['update_version_id'], ['manual_update_versions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_manual_update_candidates_ver', 'manual_update_candidates',
                    ['update_version_id'], unique=False)
    op.create_index('idx_manual_update_candidates_row', 'manual_update_candidates',
                    ['row_id'], unique=False)

    # manual_review_decisions (active)
    op.create_table(
        'manual_review_decisions',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('row_id', sa.Text(), nullable=False),
        sa.Column('decision', sa.Text(), nullable=True),
        sa.Column('decision_note', sa.Text(), nullable=True),
        sa.Column('reviewed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('reviewed_candidate_page', sa.Integer(), nullable=True),
        sa.Column('manual_page_from', sa.Integer(), nullable=True),
        sa.Column('manual_page_to', sa.Integer(), nullable=True),
        sa.Column('applied', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('source_version', sa.Text(), nullable=True),
        sa.Column('previous_version', sa.Text(), nullable=True),
        sa.Column('previous_decision_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('orphaned', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('orphaned_at', sa.Text(), nullable=True),
        sa.Column('needs_recheck', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('candidate_changed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('row_id', name='uq_manual_review_decisions_row_id'),
    )
    op.create_index('idx_manual_review_decisions_source', 'manual_review_decisions',
                    ['source_version'], unique=False)
    op.create_index('idx_manual_review_decisions_orphaned', 'manual_review_decisions',
                    ['orphaned'], unique=False)

    # manual_review_decisions_archive
    op.create_table(
        'manual_review_decisions_archive',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('row_id', sa.Text(), nullable=False),
        sa.Column('decision', sa.Text(), nullable=True),
        sa.Column('decision_note', sa.Text(), nullable=True),
        sa.Column('reviewed', sa.Boolean(), nullable=True),
        sa.Column('reviewed_candidate_page', sa.Integer(), nullable=True),
        sa.Column('manual_page_from', sa.Integer(), nullable=True),
        sa.Column('manual_page_to', sa.Integer(), nullable=True),
        sa.Column('applied', sa.Boolean(), nullable=True),
        sa.Column('source_version', sa.Text(), nullable=True),
        sa.Column('previous_version', sa.Text(), nullable=True),
        sa.Column('previous_decision_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('orphaned', sa.Boolean(), nullable=True),
        sa.Column('orphaned_at', sa.Text(), nullable=True),
        sa.Column('needs_recheck', sa.Boolean(), nullable=True),
        sa.Column('candidate_changed', sa.Boolean(), nullable=True),
        sa.Column('archived_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('archived_reason', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_manual_review_archive_row', 'manual_review_decisions_archive',
                    ['row_id'], unique=False)

    # manual_update_state (single row)
    op.create_table(
        'manual_update_state',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_date_kst', sa.Text(), nullable=True),
        sa.Column('last_checked_version', sa.Text(), nullable=True),
        sa.Column('last_detected_version', sa.Text(), nullable=True),
        sa.Column('last_staging_version', sa.Text(), nullable=True),
        sa.Column('needs_review', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema — drop manual update tables in reverse order."""
    op.drop_table('manual_update_state')
    op.drop_index('idx_manual_review_archive_row', table_name='manual_review_decisions_archive')
    op.drop_table('manual_review_decisions_archive')
    op.drop_index('idx_manual_review_decisions_orphaned', table_name='manual_review_decisions')
    op.drop_index('idx_manual_review_decisions_source', table_name='manual_review_decisions')
    op.drop_table('manual_review_decisions')
    op.drop_index('idx_manual_update_candidates_row', table_name='manual_update_candidates')
    op.drop_index('idx_manual_update_candidates_ver', table_name='manual_update_candidates')
    op.drop_table('manual_update_candidates')
    op.drop_index('idx_manual_update_changed_ver', table_name='manual_update_changed_pages')
    op.drop_table('manual_update_changed_pages')
    op.drop_index('idx_manual_update_versions_detected', table_name='manual_update_versions')
    op.drop_table('manual_update_versions')
    op.drop_index('idx_manual_update_runs_run_at', table_name='manual_update_runs')
    op.drop_table('manual_update_runs')
    op.drop_index('idx_manual_base_refs_label', table_name='manual_base_refs')
    op.drop_index('idx_manual_base_refs_row', table_name='manual_base_refs')
    op.drop_table('manual_base_refs')
    op.drop_index('idx_manual_base_pages_nhash', table_name='manual_base_pages')
    op.drop_index('idx_manual_base_pages_ver_page', table_name='manual_base_pages')
    op.drop_table('manual_base_pages')
    op.drop_index('idx_manual_base_versions_label_active', table_name='manual_base_versions')
    op.drop_table('manual_base_versions')
