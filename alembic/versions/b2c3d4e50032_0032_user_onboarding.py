"""0032 user onboarding state

users.onboarding_completed_version / onboarding_completed_at 추가.
최초 로그인 사용법 안내(온보딩) 완료 상태를 사용자별로 기록한다.

- 추가만(additive) — 기존 컬럼 변경/삭제 없음. 단일 head 유지.
- 운영 적용은 별도 승인 전 금지(로컬 head 만 갱신).
- **backfill**: 기존 사용자는 현재 온보딩 버전(1)으로 완료 처리해 갑작스런 최초 로그인 팝업을 막는다.
  migration 이후 생성되는 신규 초대 사용자는 컬럼 기본값 없이 NULL(미완료)로 시작한다.

Revision ID: b2c3d4e50032
Revises: a1b2c3d40031
Create Date: 2026-07-23
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e50032"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d40031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CURRENT_ONBOARDING_VERSION = 1


def upgrade() -> None:
    op.add_column("users", sa.Column("onboarding_completed_version", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True))
    # 기존 사용자 backfill — 현재 버전 완료 처리하되, **account_status='invited'(아직 최초 로그인 전
    # 초대 상태)는 NULL 로 남겨** 활성화 후 최초 로그인에서 안내가 뜨게 한다. active/기타(정지·교체·
    # 비활성 등) 기존 사용자는 갑작스런 팝업 방지를 위해 완료 처리. version 과 시각이 모순되지 않게
    # onboarding_completed_at 도 migration 실행 시각으로 채운다. account_status 는 0031 에서 추가됨
    # (0032 down_revision) → 항상 존재. NULL 이면 active 로 간주.
    op.execute(
        "UPDATE users SET onboarding_completed_version = %d, onboarding_completed_at = now() "
        "WHERE onboarding_completed_version IS NULL "
        "AND COALESCE(account_status, 'active') <> 'invited'" % CURRENT_ONBOARDING_VERSION
    )


def downgrade() -> None:
    op.drop_column("users", "onboarding_completed_at")
    op.drop_column("users", "onboarding_completed_version")
