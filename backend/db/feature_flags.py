"""Feature flags for PostgreSQL-backed code paths (local beta).

All flags default to **off** so existing behavior is preserved
unless the caller explicitly opts in via env var. Truthy values are
``1``/``true``/``yes``/``y``/``on`` (case-insensitive); anything else, plus
absence and empty string, is false.

Flags are read fresh on every call rather than at import time so toggling
the env var and restarting the process is enough — no module reload needed.
"""
from __future__ import annotations

import os

_TRUTHY = frozenset({"1", "true", "yes", "y", "on"})


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in _TRUTHY


def pg_users_enabled() -> bool:
    """If true, dev endpoints will query PG users; existing login is unaffected."""
    return _bool("FEATURE_PG_USERS")


def pg_audit_enabled() -> bool:
    """If true, audit_service.log_event writes to audit_logs; off → no-op."""
    return _bool("FEATURE_PG_AUDIT")


def pg_customers_enabled() -> bool:
    """If true, customers router reads/writes go to PostgreSQL."""
    return _bool("FEATURE_PG_CUSTOMERS")


def pg_events_enabled() -> bool:
    """If true, events router reads/writes go to PG."""
    return _bool("FEATURE_PG_EVENTS")


def pg_tasks_enabled() -> bool:
    """If true, active/planned/completed task routes go to PG."""
    return _bool("FEATURE_PG_TASKS")


def pg_daily_enabled() -> bool:
    """If true, daily entries + balance go to PG."""
    return _bool("FEATURE_PG_DAILY")


def pg_memos_enabled() -> bool:
    """If true, memos (short/mid/long) go to PG."""
    return _bool("FEATURE_PG_MEMOS")


def pg_signatures_enabled() -> bool:
    """Reserved — signature flow not yet wired (deferred for safety)."""
    return _bool("FEATURE_PG_SIGNATURES")


def pg_reference_enabled() -> bool:
    """If true, work_reference + certification routes go to PG (read side)."""
    return _bool("FEATURE_PG_REFERENCE")


def pg_board_enabled() -> bool:
    """If true, board posts/comments go to PG."""
    return _bool("FEATURE_PG_BOARD")


def pg_marketing_enabled() -> bool:
    """If true, marketing posts go to PG."""
    return _bool("FEATURE_PG_MARKETING")


def pg_admin_enabled() -> bool:
    """If true, admin account listing / approval flows go to PG."""
    return _bool("FEATURE_PG_ADMIN")


def pg_tenant_provisioning_enabled() -> bool:
    """If true, tenant workspace creation routes through the local mock."""
    return _bool("FEATURE_PG_TENANT_PROVISIONING")


def local_drive_mock_enabled() -> bool:
    """If true, Drive folder/file create/copy calls are mocked locally."""
    return _bool("FEATURE_LOCAL_DRIVE_MOCK")


def single_session_enabled() -> bool:
    """If true, 일반 로그인은 단일 세션(새 로그인 우선)으로 제한된다.
    Off → 기존 로그인/토큰 동작 그대로(세션 테이블 미사용). user_sessions 테이블
    (Alembic 0007) 적용 후에만 켜야 한다."""
    return _bool("FEATURE_SINGLE_SESSION")


def pg_guidelines_enabled() -> bool:
    """If true, 실무지침 분류 오버레이(편집형 카테고리/override)를 PG로 제공.
    Off → 분류 편집 API 비활성(409), 조회 트리는 기존 JSON 파생 그대로."""
    return _bool("FEATURE_PG_GUIDELINES")


def pg_quick_doc_config_enabled() -> bool:
    """If true, 문서자동작성 선택 트리(구분/민원/종류/세부)와 필요서류를 PG 설정
    테이블(``doc_tree_nodes`` / ``doc_required_documents``, Alembic 0012)에서 읽어
    렌더링한다. Off 또는 PG 미구성 또는 테이블이 비었을 때 → 기존 하드코딩 상수
    (CATEGORY_OPTIONS/MINWON_OPTIONS/TYPE_OPTIONS/SUBTYPE_OPTIONS/REQUIRED_DOCS)로
    fallback(현행 동작 유지). 관리자 편집 API 는 PG 구성 시 플래그와 무관하게 동작
    (503/require_admin)하되, 공개 /tree·/required-docs 반영은 본 플래그 ON 일 때만."""
    return _bool("FEATURE_PG_QUICK_DOC_CONFIG")


def pg_manual_update_enabled() -> bool:
    """If true, manual-update (baseline/staging/decisions/state) uses PostgreSQL
    as the single source of truth. Off → file-based fallback (legacy JSON/staging).
    별개 플래그 FEATURE_MANUAL_AUTO_UPDATE 는 '자동 실행' 스위치이며, 본 플래그는
    '저장/조회를 PG 로 할지'를 제어한다."""
    return _bool("FEATURE_PG_MANUAL_UPDATE")


def snapshot() -> dict[str, bool]:
    """Return the current flag state. Useful for debug endpoints."""
    return {
        "FEATURE_PG_USERS": pg_users_enabled(),
        "FEATURE_PG_AUDIT": pg_audit_enabled(),
        "FEATURE_PG_CUSTOMERS": pg_customers_enabled(),
        "FEATURE_PG_EVENTS": pg_events_enabled(),
        "FEATURE_PG_TASKS": pg_tasks_enabled(),
        "FEATURE_PG_DAILY": pg_daily_enabled(),
        "FEATURE_PG_MEMOS": pg_memos_enabled(),
        "FEATURE_PG_SIGNATURES": pg_signatures_enabled(),
        "FEATURE_PG_REFERENCE": pg_reference_enabled(),
        "FEATURE_PG_BOARD": pg_board_enabled(),
        "FEATURE_PG_MARKETING": pg_marketing_enabled(),
        "FEATURE_PG_ADMIN": pg_admin_enabled(),
        "FEATURE_PG_TENANT_PROVISIONING": pg_tenant_provisioning_enabled(),
        "FEATURE_LOCAL_DRIVE_MOCK": local_drive_mock_enabled(),
        "FEATURE_PG_MANUAL_UPDATE": pg_manual_update_enabled(),
        "FEATURE_PG_GUIDELINES": pg_guidelines_enabled(),
        "FEATURE_PG_QUICK_DOC_CONFIG": pg_quick_doc_config_enabled(),
        "FEATURE_SINGLE_SESSION": single_session_enabled(),
    }
