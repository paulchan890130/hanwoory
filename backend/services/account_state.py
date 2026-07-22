"""승인형 SaaS 계정/테넌트 상태 — **단일 해석 소스**.

서비스마다 account_status/service_status 를 다르게 해석하면 상태 전이 우회가 생긴다.
그 해석과 허용 전이 규칙을 이 모듈 한 곳에 모아 모든 서비스(activation/lifecycle/admin)가
같은 기준을 쓰게 한다. 이 모듈은 순수 함수만 두고 다른 서비스에 의존하지 않는다(순환 import 방지).

허용 전이(서버 강제):
  invited  → active     : 활성화 링크 완료로만
  active   → suspended  : suspend lifecycle 로만
  suspended→ active     : restore lifecycle 로만
  * → replaced          : replace lifecycle 로만
  replaced              : 복구/활성화/재발급 불가(종착)
  disabled(레거시)       : 레거시 정책 별도 — invited 와 혼동 금지
"""
from __future__ import annotations

from typing import Optional, Tuple

# ── 계정 상태(account_status) ─────────────────────────────────────────────────
ACCOUNT_INVITED = "invited"
ACCOUNT_ACTIVE = "active"
ACCOUNT_SUSPENDED = "suspended"
ACCOUNT_REPLACED = "replaced"
ACCOUNT_DISABLED = "disabled"   # 레거시: SaaS lifecycle 상태 없이 is_active=False 인 계정
_SAAS_ACCOUNT_STATES = (ACCOUNT_INVITED, ACCOUNT_ACTIVE, ACCOUNT_SUSPENDED, ACCOUNT_REPLACED)

# ── 테넌트 상태(service_status) ───────────────────────────────────────────────
TENANT_PENDING = "pending_activation"
TENANT_ACTIVE = "active"
TENANT_SUSPENDED = "suspended"
TENANT_TERMINATED = "terminated"
_TENANT_STATES = (TENANT_PENDING, TENANT_ACTIVE, TENANT_SUSPENDED, TENANT_TERMINATED)

# activation/restore/reissue 를 진행할 수 있는 테넌트 상태.
TENANT_ACTIVATABLE = (TENANT_PENDING, TENANT_ACTIVE)

# (code, http_status) 매핑 — 라우터가 그대로 쓸 수 있게 노출한다.
STATE_ERROR_HTTP = {
    "BAD_ACCOUNT_STATE": 409,
    "BAD_TENANT_STATE": 409,
    "TENANT_SUSPENDED": 409,
    "TENANT_TERMINATED": 409,
    "SEAT_LIMIT": 409,
    "ALREADY_ACTIVE": 409,
    "ALREADY_SUSPENDED": 409,
    "INVITED": 409,
    "REPLACED": 409,
    "SUSPENDED": 409,
    "LEGACY_DISABLED": 409,
}

BlockReason = Optional[Tuple[str, str]]  # (code, message) 또는 None(허용)


def account_status_of(user) -> str:
    """AccountUser 행의 lifecycle 상태를 **하나의 규칙**으로 해석한다.

    저장된 account_status 가 SaaS 상태값이면 그대로, 아니면(NULL/미상) 레거시로 본다:
    is_active True → active, False → disabled. **레거시 disabled 를 invited 로 승격하지 않는다.**
    """
    st = (getattr(user, "account_status", None) or "").strip().lower()
    if st in _SAAS_ACCOUNT_STATES:
        return st
    return ACCOUNT_ACTIVE if bool(getattr(user, "is_active", False)) else ACCOUNT_DISABLED


def tenant_status_of(tenant) -> str:
    """Tenant 행의 service_status 를 하나의 규칙으로 해석한다(NULL → is_active 기반 폴백)."""
    st = (getattr(tenant, "service_status", None) or "").strip().lower()
    if st in _TENANT_STATES:
        return st
    return TENANT_ACTIVE if bool(getattr(tenant, "is_active", False)) else TENANT_PENDING


def _tenant_block(tenant) -> BlockReason:
    """activation/restore/reissue 공통 — 테넌트가 진행 불가 상태면 차단 사유 반환."""
    tstatus = tenant_status_of(tenant)
    if tstatus == TENANT_SUSPENDED:
        return ("TENANT_SUSPENDED", "정지된 사무소의 계정은 처리할 수 없습니다. 사무소를 먼저 복구하세요.")
    if tstatus == TENANT_TERMINATED:
        return ("TENANT_TERMINATED", "종료된 사무소의 계정은 처리할 수 없습니다.")
    if tstatus not in TENANT_ACTIVATABLE:
        return ("BAD_ACCOUNT_STATE", "처리할 수 없는 사무소 상태입니다.")
    return None


def activation_block_reason(user, tenant) -> BlockReason:
    """활성화(invited→active) 허용 여부. 허용이면 None, 아니면 (code, message).

    - 계정은 반드시 invited + is_active=False.
    - 테넌트는 pending_activation/active (suspended/terminated 거부).
    """
    if account_status_of(user) != ACCOUNT_INVITED or bool(getattr(user, "is_active", False)):
        return ("BAD_ACCOUNT_STATE", "이미 처리되었거나 활성화할 수 없는 계정입니다.")
    return _tenant_block(tenant)


def reissue_block_reason(user, tenant) -> BlockReason:
    """활성화 토큰 재발급 허용 여부(invited 전용). 허용이면 None."""
    st = account_status_of(user)
    if st != ACCOUNT_INVITED or bool(getattr(user, "is_active", False)):
        if st == ACCOUNT_ACTIVE:
            return ("ALREADY_ACTIVE", "이미 활성화된 계정입니다.")
        if st == ACCOUNT_SUSPENDED:
            return ("SUSPENDED", "정지된 계정은 재발급할 수 없습니다. 먼저 복구하세요.")
        if st == ACCOUNT_REPLACED:
            return ("REPLACED", "교체된 계정은 재발급할 수 없습니다.")
        if st == ACCOUNT_DISABLED:
            return ("LEGACY_DISABLED", "레거시 비활성 계정입니다. 레거시 정책으로 처리하세요.")
        return ("BAD_ACCOUNT_STATE", "재발급할 수 없는 계정 상태입니다.")
    return _tenant_block(tenant)


def restore_block_reason(user, tenant) -> BlockReason:
    """복구(suspended→active) 허용 여부(suspended 전용). 허용이면 None."""
    st = account_status_of(user)
    if st == ACCOUNT_ACTIVE:
        return ("ALREADY_ACTIVE", "이미 활성 상태인 계정입니다.")
    if st == ACCOUNT_INVITED:
        return ("INVITED", "초대 상태 계정입니다. 활성화 링크를 사용하거나 재발급하세요.")
    if st == ACCOUNT_REPLACED:
        return ("REPLACED", "교체된 계정은 복구할 수 없습니다.")
    if st == ACCOUNT_DISABLED:
        return ("LEGACY_DISABLED", "레거시 비활성 계정입니다. 레거시 정책으로 처리하세요.")
    # st == suspended → 계정은 허용. 테넌트 상태만 추가로 확인.
    return _tenant_block(tenant)


def _suspend_tenant_block(tenant) -> BlockReason:
    """정지 공통 — 정지/종료 사무소의 개별 계정은 사무소 단위로만 처리(개별 정지 거부)."""
    tstatus = tenant_status_of(tenant)
    if tstatus == TENANT_SUSPENDED:
        return ("TENANT_SUSPENDED", "정지된 사무소의 계정은 개별 정지할 수 없습니다. 사무소 단위로 처리하세요.")
    if tstatus == TENANT_TERMINATED:
        return ("TENANT_TERMINATED", "종료된 사무소의 계정입니다.")
    return None


def suspend_block_reason(user, tenant) -> BlockReason:
    """정지(active→suspended) 허용 여부. 허용이면 None, 아니면 (code, message).

    현재 상태를 확인하지 않고 account_status="suspended" 로 덮어쓰면 replaced/invited 계정을
    suspended 로 만든 뒤 restore 로 되살리는 우회가 생긴다. 그래서 **active + is_active=True**
    계정만 정지할 수 있게 강제한다:
    - invited   → INVITED (활성화 취소/교체로만)
    - suspended → ALREADY_SUSPENDED (멱등 거부)
    - replaced  → REPLACED (종착 상태 — 되살릴 수 없음)
    - disabled  → LEGACY_DISABLED (레거시 정책 별도)
    - active 인데 is_active=False 등 불일치 → BAD_ACCOUNT_STATE
    - 사무소가 정지/종료 → 사무소 단위로만 처리(TENANT_*)
    """
    st = account_status_of(user)
    if st == ACCOUNT_INVITED:
        return ("INVITED", "초대 상태 계정은 정지할 수 없습니다. 활성화 취소 또는 계정 교체를 사용하세요.")
    if st == ACCOUNT_SUSPENDED:
        return ("ALREADY_SUSPENDED", "이미 정지된 계정입니다.")
    if st == ACCOUNT_REPLACED:
        return ("REPLACED", "교체된 계정은 정지할 수 없습니다(종착 상태).")
    if st == ACCOUNT_DISABLED:
        return ("LEGACY_DISABLED", "레거시 비활성 계정입니다. 레거시 정책으로 처리하세요.")
    if st != ACCOUNT_ACTIVE:
        return ("BAD_ACCOUNT_STATE", "정지할 수 없는 계정 상태입니다.")
    if not bool(getattr(user, "is_active", False)):
        return ("BAD_ACCOUNT_STATE", "계정 상태가 일치하지 않습니다(active/비활성 불일치).")
    return _suspend_tenant_block(tenant)


def suspend_tenant_block_reason(tenant) -> BlockReason:
    """사무소 정지 허용 여부. terminated 는 종착이라 거부(그 외 상태는 정지 허용/멱등)."""
    if tenant_status_of(tenant) == TENANT_TERMINATED:
        return ("TENANT_TERMINATED", "종료된 사무소는 정지할 수 없습니다(종착 상태).")
    return None


def restore_tenant_block_reason(tenant) -> BlockReason:
    """사무소 복구 허용 여부 — **suspended 전용**. 허용이면 None."""
    tstatus = tenant_status_of(tenant)
    if tstatus == TENANT_ACTIVE:
        return ("ALREADY_ACTIVE", "이미 활성 상태인 사무소입니다.")
    if tstatus == TENANT_TERMINATED:
        return ("TENANT_TERMINATED", "종료된 사무소는 복구할 수 없습니다(종착 상태).")
    if tstatus != TENANT_SUSPENDED:
        return ("BAD_TENANT_STATE", "복구할 수 없는 사무소 상태입니다.")
    return None


def relink_account_block_reason(user) -> BlockReason:
    """계정 연결 변경(relink) 대상 계정 허용 여부 — **명시적 allowlist**. 허용이면 None.

    is_active=false 라는 이유만으로 허용하던 방식은 정지/교체/레거시 계정까지 통과시켜
    ``suspended → relink → invited → active`` 우회를 열어준다. 그래서 **invited + 비활성**
    한 가지만 허용하고 나머지는 상태별로 거부한다(정책 미확정 상태는 fail-closed).
    """
    if bool(getattr(user, "is_active", False)):
        return ("BAD_ACCOUNT_STATE", "활성(로그인 가능) 계정은 연결을 변경할 수 없습니다. 먼저 정지·교체하세요.")
    st = account_status_of(user)
    if st == ACCOUNT_INVITED:
        return None
    if st == ACCOUNT_ACTIVE:
        return ("BAD_ACCOUNT_STATE", "활성 계정은 연결을 변경할 수 없습니다.")
    if st == ACCOUNT_SUSPENDED:
        return ("SUSPENDED", "정지된 계정은 연결을 변경할 수 없습니다(정지→초대→활성 우회 차단). "
                             "계정 교체 또는 새 관리자 발급을 사용하세요.")
    if st == ACCOUNT_REPLACED:
        return ("REPLACED", "교체된 계정은 연결을 변경할 수 없습니다.")
    if st == ACCOUNT_DISABLED:
        return ("LEGACY_DISABLED", "레거시 비활성 계정은 연결을 변경할 수 없습니다(정책 미확정 — fail-closed).")
    return ("BAD_ACCOUNT_STATE", "연결을 변경할 수 없는 계정 상태입니다.")


def relink_source_tenant_block_reason(tenant) -> BlockReason:
    """relink 원본 사업장 상태 허용 여부 — 허용이면 None.

    active 사업장에서 마지막 계정을 빼내면 무관리자 활성 사업장이 생긴다. 그래서 원본은
    **정지(suspended)+비활성** 또는 **미활성화(pending_activation)+비활성** 만 허용한다.
    active/terminated, is_active=true, 상태 불일치는 fail-closed 로 거부한다.
    """
    if tenant is None:
        return ("NOT_FOUND", "원본 사업장을 찾을 수 없습니다.")
    if bool(getattr(tenant, "is_active", False)):
        return ("BAD_TENANT_STATE", "활성 상태의 원본 사업장에서는 계정 연결을 변경할 수 없습니다"
                                    "(마지막 계정 이탈 방지). 먼저 사업장을 정지하세요.")
    st = tenant_status_of(tenant)
    if st in (TENANT_SUSPENDED, TENANT_PENDING):
        return None
    if st == TENANT_TERMINATED:
        return ("TENANT_TERMINATED", "종료된 원본 사업장에서는 연결을 변경할 수 없습니다.")
    if st == TENANT_ACTIVE:
        return ("BAD_TENANT_STATE", "활성 상태의 원본 사업장에서는 계정 연결을 변경할 수 없습니다.")
    return ("BAD_TENANT_STATE", "연결을 변경할 수 없는 원본 사업장 상태입니다.")


def replace_tenant_block_reason(tenant) -> BlockReason:
    """계정 교체 허용 여부(테넌트 관점). 정지/종료 사무소는 **fail-closed** 로 거부한다.

    active/pending 만 허용(교체 대상은 invited 또는 active 계정일 수 있으므로 pending 도 허용).
    정지 사무소에서의 교체 정책이 모호하므로 명시적으로 TENANT_SUSPENDED(409) 로 막는다 —
    복구 후 교체하도록 유도한다.
    """
    tstatus = tenant_status_of(tenant)
    if tstatus == TENANT_SUSPENDED:
        return ("TENANT_SUSPENDED", "정지된 사무소에서는 계정을 교체할 수 없습니다. 사무소를 먼저 복구하세요.")
    if tstatus == TENANT_TERMINATED:
        return ("TENANT_TERMINATED", "종료된 사무소에서는 계정을 교체할 수 없습니다.")
    return None
