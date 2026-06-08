"""0005 fixed_expenses + monthly_tax_summaries

Revision ID: e5f1a2b30005
Revises: c0ffee004ab1
Create Date: 2026-06-08 00:00:00.000000

PG-only finance tables (no Sheets origin). Additive — does not touch existing
tables. Exposed by the app only when FEATURE_PG_DAILY is on.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f1a2b30005'
down_revision: Union[str, Sequence[str], None] = 'c0ffee004ab1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'fixed_expenses',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=False),
        sa.Column('expense_id', sa.Text(), nullable=False),
        sa.Column('year_month', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=True),
        sa.Column('amount', sa.Integer(), server_default='0', nullable=False),
        sa.Column('category', sa.Text(), nullable=True),
        sa.Column('payment_method', sa.Text(), nullable=True),
        sa.Column('vat_included', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
        sa.Column('vat_amount', sa.Integer(), server_default='0', nullable=False),
        sa.Column('memo', sa.Text(), nullable=True),
        sa.Column('is_recurring', sa.Boolean(), server_default=sa.text('FALSE'), nullable=False),
        sa.Column('start_month', sa.Text(), nullable=True),
        sa.Column('end_month', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'expense_id', name='uq_fixed_expense_per_tenant'),
    )
    op.create_index('idx_fixed_expense_tenant_ym', 'fixed_expenses', ['tenant_id', 'year_month'], unique=False)

    op.create_table(
        'monthly_tax_summaries',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('tenant_id', sa.Text(), nullable=False),
        sa.Column('year_month', sa.Text(), nullable=False),
        sa.Column('reported_revenue', sa.Integer(), server_default='0', nullable=False),
        sa.Column('reported_expense', sa.Integer(), server_default='0', nullable=False),
        sa.Column('reported_output_vat', sa.Integer(), server_default='0', nullable=False),
        sa.Column('reported_input_vat', sa.Integer(), server_default='0', nullable=False),
        sa.Column('expected_vat_payable', sa.Integer(), server_default='0', nullable=False),
        sa.Column('vat_basis', sa.Text(), server_default='tax_included', nullable=False),
        sa.Column('memo', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.tenant_id'], onupdate='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'year_month', name='uq_monthly_tax_per_tenant'),
    )
    op.create_index('idx_monthly_tax_tenant_ym', 'monthly_tax_summaries', ['tenant_id', 'year_month'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_monthly_tax_tenant_ym', table_name='monthly_tax_summaries')
    op.drop_table('monthly_tax_summaries')
    op.drop_index('idx_fixed_expense_tenant_ym', table_name='fixed_expenses')
    op.drop_table('fixed_expenses')
