"""0023 월간결산 신고/부가세 입력 분해 컬럼

월간결산 신고/부가세 영역을 행정사 실무에 맞게 단순화하기 위해
monthly_tax_summaries 에 수동 입력 구성 컬럼 4개를 추가한다(전부 additive).

- manual_tax_invoice_revenue : 수동 세금계산서 매출액 (공급대가)
- manual_other_revenue       : 기타 수동 조정 매출액 (공급대가)
- business_card_expense      : 사업용 카드 사용액 (공급대가)
- non_deductible_expense     : 불공제/개인사용 제외액 (공급대가)

자동 카드매출(일일결산 카드수입 합계)은 저장하지 않고 매 조회 시 일일결산에서
재계산한다. 신고 매출 합계/매출세액/공제대상 매입/매입세액/예상납부는 기존
스냅샷 컬럼(reported_revenue/reported_expense/reported_output_vat/
reported_input_vat/expected_vat_payable)에 저장 시 갱신한다.

기존 reported_revenue('수동 추가/조정 신고매출')는 manual_other_revenue 로 복사해
기존 입력을 보존한다. 데이터 손실 없음.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8c9d0e10023'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d00022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'monthly_tax_summaries',
        sa.Column('manual_tax_invoice_revenue', sa.Integer(), server_default='0', nullable=False),
    )
    op.add_column(
        'monthly_tax_summaries',
        sa.Column('manual_other_revenue', sa.Integer(), server_default='0', nullable=False),
    )
    op.add_column(
        'monthly_tax_summaries',
        sa.Column('business_card_expense', sa.Integer(), server_default='0', nullable=False),
    )
    op.add_column(
        'monthly_tax_summaries',
        sa.Column('non_deductible_expense', sa.Integer(), server_default='0', nullable=False),
    )
    # 기존 '수동 추가/조정 신고매출'(reported_revenue) → 기타 수동 조정 매출액으로 보존 복사.
    op.execute(
        "UPDATE monthly_tax_summaries "
        "SET manual_other_revenue = COALESCE(reported_revenue, 0)"
    )


def downgrade() -> None:
    op.drop_column('monthly_tax_summaries', 'non_deductible_expense')
    op.drop_column('monthly_tax_summaries', 'business_card_expense')
    op.drop_column('monthly_tax_summaries', 'manual_other_revenue')
    op.drop_column('monthly_tax_summaries', 'manual_tax_invoice_revenue')
