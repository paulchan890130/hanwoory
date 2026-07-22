"""사업장(tenant) 관리 — 시스템 관리자 전용: 연결현황 / 사용자 없는 사업장 /
기존 tenant 에 새 관리자 발급 / 계정 연결 변경(relink).

원칙:
- 고객·업무·분류·업무참고 데이터는 **AccountUser.tenant_id → tenant** 를 통해 접근한다.
  이 서비스는 그 데이터의 ``tenant_id`` 를 **절대 변경하지 않는다**(사업장 간 데이터 이전/병합 아님).
- 계정 연결 변경(relink)은 **계정이 접근하는 사업장만** 바꾼다. 데이터는 이동하지 않는다.
- 모든 변경은 시스템 관리자 전용 + preview/confirm + 단일 트랜잭션.
- 잠금 순서 표준: user → tenant(들, tenant_id 정렬) → token.
"""
from __future__ import annotations

import re
import secrets
from typing import Optional

from sqlalchemy import func, select


class TenantAdminError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _tenant_status(t) -> str:
    st = (getattr(t, "service_status", None) or "").strip().lower()
    if st in ("pending_activation", "active", "suspended", "terminated"):
        return st
    return "active" if bool(getattr(t, "is_active", False)) else "pending_activation"


# ── 연결 현황 요약 ───────────────────────────────────────────────────────────
def tenant_connection_summary(tenant_id: str) -> Optional[dict]:
    """tenant + 계정 요약 + 업무 데이터 건수 + 로그인 사용자 없음/정리 필요 플래그."""
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services import account_state as _st
    from backend.services import tenant_purge_pg_service as _purge

    tid = (tenant_id or "").strip()
    if not tid:
        return None
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tid))
        if t is None:
            return None
        rows = session.scalars(
            select(AccountUser).where(AccountUser.tenant_id == tid)
            .order_by(AccountUser.is_admin.desc(), AccountUser.id.asc())).all()
        accounts = [{
            "login_id": u.login_id,
            "name": u.contact_name or "",
            "is_admin": bool(u.is_admin),
            "account_status": _st.account_status_of(u),
            "is_active": bool(u.is_active),
        } for u in rows]
        # 로그인 가능(활성화 완료·정지 아님) 계정 수 — invited/replaced/disabled/suspended 제외.
        loginable = sum(1 for a in accounts if a["account_status"] == _st.ACCOUNT_ACTIVE and a["is_active"])
        # 관리자(office_admin) 현황(§11) — 새 관리자 발급 화면에서 중복 여부를 명확히 보이기 위함.
        active_admins = sum(1 for a in accounts if a["is_admin"] and a["account_status"] == _st.ACCOUNT_ACTIVE)
        invited_admins = sum(1 for a in accounts if a["is_admin"] and a["account_status"] == _st.ACCOUNT_INVITED)
        suspended_admins = sum(1 for a in accounts if a["is_admin"] and a["account_status"] == _st.ACCOUNT_SUSPENDED)
        # 새 관리자 발급 가능 여부(정지/종료 사무소 차단 + 중복 관리자 차단, issue_admin_account 와 동일 규칙).
        tstatus = _tenant_status(t)
        can_issue_admin = tstatus in _st.TENANT_ACTIVATABLE and active_admins == 0 and invited_admins == 0
        counts = _purge.tenant_data_counts(session, tid)
        return {
            "tenant_id": t.tenant_id,
            "office_name": t.office_name or "",
            "service_status": tstatus,
            "is_active": bool(getattr(t, "is_active", False)),
            "seat_limit": int(getattr(t, "seat_limit", 2) or 2),
            "total_users": len(accounts),
            "active_users": sum(1 for a in accounts if a["is_active"]),
            "loginable_users": loginable,
            "active_admins": active_admins,
            "invited_admins": invited_admins,
            "suspended_admins": suspended_admins,
            "can_issue_admin": can_issue_admin,
            "no_login_users": loginable == 0,
            "needs_cleanup": len(accounts) == 0 or loginable == 0,
            "accounts": accounts,
            "data_counts": counts,
        }


def list_no_user_tenants() -> list[dict]:
    """연결 계정이 0명이거나 로그인 가능한 계정이 0명인 사업장 목록(정리 대상)."""
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    out: list[dict] = []
    with SessionLocal() as session:
        tenant_ids = list(session.scalars(select(Tenant.tenant_id)).all())
    for tid in tenant_ids:
        s = tenant_connection_summary(tid)
        if s and s["needs_cleanup"]:
            out.append(s)
    return out


# ── 기존 tenant 에 새 관리자 발급 ─────────────────────────────────────────────
def issue_admin_account(tenant_id: str, name: str, email: str, actor: str,
                        confirm_tenant_id: Optional[str] = None) -> dict:
    """기존 사업장에 **새 office_admin 초대 계정**을 발급하고 activation 토큰을 반환한다.

    서버 고정: tenant_id=URL tenant, is_admin=true, role=admin, account_status=invited,
    is_active=false. 마지막 계정 오삭제/무관리자 사업장 복구용.
    """
    from backend.auth import is_master_login
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services.accounts_service import hash_password
    from backend.services import account_state as _st
    from backend.services import activation_pg_service as _act
    from backend.services.account_lifecycle_pg_service import (
        assert_seat_within_limit, assert_invitation_capacity, LifecycleError)

    tid = (tenant_id or "").strip()
    name = (name or "").strip()
    email = (email or "").strip().lower()
    if not tid:
        raise TenantAdminError("BAD_REQUEST", "tenant_id 가 필요합니다.")
    if confirm_tenant_id is not None and (confirm_tenant_id or "").strip() != tid:
        raise TenantAdminError("CONFIRM_MISMATCH", "확인용 사업장 ID가 일치하지 않습니다.")
    if not name or not email:
        raise TenantAdminError("MISSING_USER", "새 관리자 이름과 이메일이 필요합니다.")
    if not _EMAIL_RE.match(email):
        raise TenantAdminError("BAD_EMAIL", "이메일 형식이 올바르지 않습니다.")
    if is_master_login(email):
        raise TenantAdminError("PROTECTED", "예약된 계정 식별자입니다.")

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # user 잠금 대상은 없음(신규) — 표준 순서상 tenant → token.
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tid).with_for_update())
        if t is None:
            raise TenantAdminError("NOT_FOUND", "사업장을 찾을 수 없습니다.")
        # unusable activation token 발급 금지 — activation 이 실제 가능한 사무소만 허용한다.
        # **엄격 raw 판정**(activation_capable_tenant_block_reason): pending+비활성 / active+활성만
        # 통과, 미상/빈/불일치 service_status 는 is_active 로 추론하지 않고 fail-closed(§strict).
        tblock = _st.activation_capable_tenant_block_reason(t)
        if tblock is not None:
            code = tblock[0]
            if code == "TENANT_TERMINATED":
                raise TenantAdminError("TENANT_TERMINATED", "종료된 사업장에는 계정을 발급할 수 없습니다.")
            if code == "TENANT_SUSPENDED":
                raise TenantAdminError(
                    "TENANT_SUSPENDED",
                    "정지된 사업장입니다. 사업장을 먼저 복구한 뒤 새 관리자 계정을 발급하세요.")
            raise TenantAdminError("BAD_TENANT_STATE", "새 관리자를 발급할 수 없는 사업장 상태입니다.")
        # 중복 관리자 초대 방지(§11) — 이미 활성/초대 상태의 office_admin 이 있으면 차단.
        # (사용자 없는 사업장 복구가 목적이므로 무제한 invited admin 생성을 막는다.)
        existing_admins = session.scalars(
            select(AccountUser).where(AccountUser.tenant_id == tid, AccountUser.is_admin.is_(True))).all()
        for a in existing_admins:
            ast = _st.account_status_of(a)
            if ast in (_st.ACCOUNT_ACTIVE, _st.ACCOUNT_INVITED):
                kind = "활성" if ast == _st.ACCOUNT_ACTIVE else "초대"
                raise TenantAdminError(
                    "DUPLICATE_ADMIN",
                    f"이미 {kind} 상태의 관리자 계정이 있어 새 관리자를 발급할 수 없습니다"
                    f"({a.login_id}). 기존 관리자를 정지·교체하거나 활성화 링크를 재발급하세요.")
        if session.scalar(select(AccountUser.id).where(AccountUser.login_id == email)) is not None:
            raise TenantAdminError("EMAIL_IN_USE", "이미 사용 중인 이메일입니다.")

        row = AccountUser(
            login_id=email,
            tenant_id=tid,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            contact_name=name,
            is_admin=True,
            is_active=False,
        )
        row.role = "admin"
        row.account_status = "invited"
        from datetime import datetime, timezone
        row.invited_at = datetime.now(timezone.utc)
        session.add(row)
        session.flush()
        # 좌석 원자 검증(invited 는 활성 좌석 미소비지만 tenant 잠금·한도 확인).
        # + 초대 좌석 예약 검증(§5) — 방금 flush 한 invited 행이 reserved 에 포함되므로 +0.
        try:
            assert_seat_within_limit(session, tid, activating_login_id=None)
            assert_invitation_capacity(session, tid, additional_invites=0)
        except LifecycleError as e:
            if getattr(e, "code", "") == "SEAT_LIMIT":
                raise TenantAdminError("SEAT_LIMIT", e.message)
            raise
        raw = _act.issue_activation_token(session, email, tid)
        session.commit()

    _audit("tenant_admin_issued", actor, email, tid, {"role": "office_admin"})
    return {"login_id": email, "tenant_id": tid, "role": "office_admin",
            "account_status": "invited", "activation_token": raw}


# ── 계정 연결 변경(relink) ────────────────────────────────────────────────────
# 강한 확인 문구(§8) — 정확히 일치해야 실행. 프론트/백엔드 동일.
RELINK_CONFIRMATION_PHRASE = "계정 사업장 연결 변경"

# relink 후 역할(§7) — 재연결은 항상 office_staff 로 서버가 강제한다. 데이터는 이동하지 않고
# 새 사업장에서는 초대(invited) 멤버십으로 시작하므로 최소 권한이 안전하다. office_admin 연결이
# 필요하면 "새 관리자 발급"(issue_admin_account, 중복 방지·정지 사무소 차단 포함)을 쓴다.
RELINK_ROLE_AFTER = "office_staff"


def _current_role(u) -> str:
    return "office_admin" if bool(getattr(u, "is_admin", False)) else "office_staff"


def _relink_blocking(session, u, source_t, target_t, actor_login: str) -> list[str]:
    from backend.auth import is_master_login, is_system_admin
    from backend.db.models.user import AccountUser
    from backend.services import account_state as _st
    from backend.services import tenant_purge_pg_service as _purge

    reasons: list[str] = []
    if u is None:
        return ["대상 계정을 찾을 수 없습니다."]
    # 시스템 관리자 보호(§3) — master / SYSTEM_ADMIN_LOGIN_IDS / 현재 actor. office_admin(is_admin)
    # 과 혼동하지 않는다(is_system_admin 은 마스터 + env 허용목록만). 확인 실패 시 fail-closed.
    if is_master_login(u.login_id):
        reasons.append("마스터 계정은 연결을 변경할 수 없습니다.")
    else:
        try:
            sysadmin = is_system_admin(u.login_id)
        except Exception:
            sysadmin = True  # 시스템 관리자 여부 확인 실패 → fail-closed(차단).
        if sysadmin:
            reasons.append("시스템 관리자 계정은 연결을 변경할 수 없습니다.")
    if actor_login and u.login_id == actor_login:
        reasons.append("본인 계정은 연결을 변경할 수 없습니다.")
    # 계정 상태 allowlist(§2) — invited + 비활성만. suspended→invited→active 우회 차단.
    acct_block = _st.relink_account_block_reason(u)
    if acct_block is not None:
        reasons.append(acct_block[1])
    # 대상 사업장 상태(§1) — activation 가능 상태만(pending+inactive / active+active).
    # suspended 대상으로 relink 하면 사용 불가 activation token 만 발급되므로 차단한다.
    tgt_block = _st.relink_target_tenant_block_reason(target_t)
    if tgt_block is not None:
        reasons.append(tgt_block[1])
    if target_t is not None:
        # 초대 좌석 예약 검사(§5) — 활성 계정만 세던 방식은 초대 계정 과다 발급을 허용한다.
        # relink 후 대상에 초대 1개가 추가되므로 reserved(활성+초대) + 1 <= seat_limit 이어야 한다.
        from backend.services.account_lifecycle_pg_service import reserved_seat_count
        seat_limit = int(getattr(target_t, "seat_limit", 2) or 2)
        reserved = reserved_seat_count(session, target_t.tenant_id)
        if reserved + 1 > seat_limit:
            reasons.append(f"대상 사업장의 좌석 여유가 없습니다(예약 {reserved}/{seat_limit}).")
    # 원본 사업장 상태 제한(§4) — active 원본에서 마지막 계정 이탈 금지. suspended/pending + 비활성만.
    src_block = _st.relink_source_tenant_block_reason(source_t)
    if src_block is not None:
        reasons.append(src_block[1])
    if source_t is not None:
        other_users = session.scalar(select(func.count()).select_from(AccountUser).where(
            AccountUser.tenant_id == source_t.tenant_id,
            AccountUser.login_id != u.login_id)) or 0
        if int(other_users) > 0:
            reasons.append("원본 사업장에 다른 사용자가 있어 연결을 변경할 수 없습니다.")
        # 원본 데이터 전수 검사(§5) — TENANT_PURGE_PLAN 재사용. 이동 대상 user 인프라 외 잔존/미분류 차단.
        _counts, src_reasons = _purge.relink_source_blocking(session, source_t.tenant_id)
        reasons.extend(src_reasons)
    return reasons


def _tenant_block_dict(session, t, *, is_target: bool) -> Optional[dict]:
    """preview 용 tenant 요약(사용자 수·데이터 건수·좌석 현황 포함, §6)."""
    from backend.db.models.user import AccountUser
    from backend.services import account_state as _st
    from backend.services import tenant_purge_pg_service as _purge

    if t is None:
        return None
    tid = t.tenant_id
    user_count = int(session.scalar(select(func.count()).select_from(AccountUser).where(
        AccountUser.tenant_id == tid)) or 0)
    out = {
        "tenant_id": tid,
        "office_name": t.office_name or "",
        "service_status": _tenant_status(t),
        "is_active": bool(getattr(t, "is_active", False)),
        "user_count": user_count,
        "data_counts": _purge.tenant_data_counts(session, tid),
    }
    if is_target:
        seat_limit = int(getattr(t, "seat_limit", 2) or 2)
        active_cnt = int(session.scalar(select(func.count()).select_from(AccountUser).where(
            AccountUser.tenant_id == tid, AccountUser.is_active.is_(True))) or 0)
        invited_cnt = int(session.scalar(select(func.count()).select_from(AccountUser).where(
            AccountUser.tenant_id == tid, AccountUser.account_status == _st.ACCOUNT_INVITED)) or 0)
        out.update({"seat_limit": seat_limit, "active_count": active_cnt, "invited_count": invited_cnt})
    else:
        # 원본은 relink 차단 판정과 동일 기준의 잔여 데이터 상세를 함께 보여준다.
        out["residual_data_counts"] = _purge.relink_source_data_counts(session, tid)
    return out


def relink_preview(login_id: str, target_tenant_id: str, actor_login: str = "") -> dict:
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services import account_state as _st

    lid = (login_id or "").strip()
    ttid = (target_tenant_id or "").strip()
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == lid))
        source_t = session.scalar(select(Tenant).where(Tenant.tenant_id == u.tenant_id)) if u else None
        target_t = session.scalar(select(Tenant).where(Tenant.tenant_id == ttid)) if ttid else None
        reasons = _relink_blocking(session, u, source_t, target_t, actor_login)
        account_block = {
            "login_id": lid,
            "account_status": (_st.account_status_of(u) if u else None),
            "is_active": (bool(u.is_active) if u else None),
            "current_role": (_current_role(u) if u else None),
        }
        warnings = ["고객·업무·분류 등 데이터 자체는 이동하지 않습니다(계정이 접근하는 사업장만 변경).",
                    "연결 후 대상 계정은 초대(invited) 상태가 되어 활성화 링크가 필요합니다.",
                    f"연결 후 역할은 항상 '{RELINK_ROLE_AFTER}' 입니다(관리자 연결은 '새 관리자 발급' 사용)."]
        return {
            "account": account_block,
            "source_tenant": _tenant_block_dict(session, source_t, is_target=False),
            "target_tenant": _tenant_block_dict(session, target_t, is_target=True),
            "role_after": RELINK_ROLE_AFTER,
            "confirmation_phrase": RELINK_CONFIRMATION_PHRASE,
            "warnings": warnings,
            "blocking_reasons": reasons,
            "can_relink": len(reasons) == 0,
            # 하위호환(기존 프론트가 읽던 평탄 필드).
            "login_id": lid,
            "source_tenant_id": (u.tenant_id if u else None),
            "source_office_name": (source_t.office_name if source_t else None),
            "target_tenant_id": ttid or None,
            "target_office_name": (target_t.office_name if target_t else None),
        }


def relink_account(login_id: str, target_tenant_id: str, actor_login: str,
                   confirm_login_id: str, confirm_target_tenant_id: str,
                   confirmation_phrase: str = "", source_tenant_id: str = "") -> dict:
    """계정의 소속 tenant 를 변경한다(데이터 이동 아님). 단일 트랜잭션·명시적 잠금.

    강한 확인(§8): login ID · 대상 tenant ID · 확인 문구 4값이 정확히 일치해야 하고, preview
    시점의 원본 tenant(``source_tenant_id``)가 실행 시점과 같아야 한다(그 사이 원본이 바뀌면 거부).
    역할(§7)은 서버가 항상 office_staff 로 강제한다(프론트가 보낸 is_admin/role 불신).
    """
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services import activation_pg_service as _act
    from backend.services.account_lifecycle_pg_service import (
        _revoke_unused_tokens, assert_invitation_capacity, LifecycleError)
    from backend.services.session_pg_service import revoke_active_sessions_in_session

    lid = (login_id or "").strip()
    ttid = (target_tenant_id or "").strip()
    if (confirm_login_id or "").strip() != lid:
        raise TenantAdminError("CONFIRM_MISMATCH", "확인용 로그인 ID가 일치하지 않습니다.")
    if (confirm_target_tenant_id or "").strip() != ttid:
        raise TenantAdminError("CONFIRM_MISMATCH", "확인용 대상 사업장 ID가 일치하지 않습니다.")
    if (confirmation_phrase or "").strip() != RELINK_CONFIRMATION_PHRASE:
        raise TenantAdminError(
            "CONFIRM_MISMATCH",
            f"확인 문구가 일치하지 않습니다. '{RELINK_CONFIRMATION_PHRASE}' 를 정확히 입력하세요.")
    # source_tenant_id 는 필수 강한 확인값(§8) — 빈 값이면 우회 불가로 거부(조건부 검사 제거).
    if not (source_tenant_id or "").strip():
        raise TenantAdminError("CONFIRM_MISMATCH", "확인용 원본 사업장 ID가 필요합니다.")

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # 1) user 잠금.
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == lid).with_for_update())
        if u is None:
            raise TenantAdminError("NOT_FOUND", "대상 계정을 찾을 수 없습니다.")
        source_tid = u.tenant_id
        # preview 이후 원본이 바뀌었으면 실행 거부(§8) — 빈 값은 위에서 이미 거부, 값이 실제와 다르면 거부.
        if (source_tenant_id or "").strip() != (source_tid or ""):
            raise TenantAdminError("CONFIRM_MISMATCH",
                                   "원본 사업장이 preview 시점과 달라 실행을 거부했습니다. 다시 확인하세요.")
        if source_tid == ttid:
            raise TenantAdminError("SAME_TENANT", "이미 해당 사업장에 소속되어 있습니다.")
        role_before = _current_role(u)
        # 2~3) 두 tenant 를 tenant_id 정렬 순서로 FOR UPDATE(데드락 방지).
        for tid_lock in sorted([x for x in {source_tid, ttid} if x]):
            session.scalar(select(Tenant).where(Tenant.tenant_id == tid_lock).with_for_update())
        source_t = session.scalar(select(Tenant).where(Tenant.tenant_id == source_tid)) if source_tid else None
        target_t = session.scalar(select(Tenant).where(Tenant.tenant_id == ttid)) if ttid else None
        # 4) preview 조건 재검증(잠금 이후).
        reasons = _relink_blocking(session, u, source_t, target_t, actor_login)
        if reasons:
            raise TenantAdminError("BLOCKED", " / ".join(reasons))
        # 5) 초대 좌석 예약 원자 검증(§5) — 대상 tenant FOR UPDATE 후 reserved+1<=limit(동시성 직렬화).
        try:
            assert_invitation_capacity(session, ttid, additional_invites=1)
        except LifecycleError as e:
            if getattr(e, "code", "") == "SEAT_LIMIT":
                raise TenantAdminError("SEAT_LIMIT", e.message)
            raise
        # 6) 미사용 초대 토큰 폐기 + 세션 revoke 를 **같은 트랜잭션**에서 수행(§4) — revoke 실패 시 전체 롤백.
        _revoke_unused_tokens(session, lid)
        revoke_active_sessions_in_session(session, lid, reason="account_relinked", only_non_kiosk=False)
        # 7~9) 소속 변경 + invited/비활성 + 역할 서버 강제(office_staff).
        u.tenant_id = ttid
        u.is_active = False
        u.account_status = "invited"
        u.is_admin = False
        u.role = "user"
        # 10) 새 activation 토큰.
        raw = _act.issue_activation_token(session, lid, ttid)
        session.commit()
    # 세션 revoke 는 위 트랜잭션에 포함(commit 시 확정). JWT tenant binding(auth.get_current_user)이 1차 방어선.
    _audit("account_relinked", actor_login, lid, ttid,
           {"from_tenant": source_tid, "to_tenant": ttid,
            "role_before": role_before, "role_after": RELINK_ROLE_AFTER})
    return {"login_id": lid, "from_tenant_id": source_tid, "to_tenant_id": ttid,
            "account_status": "invited", "role_after": RELINK_ROLE_AFTER,
            "role_before": role_before, "activation_token": raw}


def _audit(action: str, actor: Optional[str], target_login: Optional[str],
           tenant_id: Optional[str], payload: Optional[dict] = None) -> None:
    try:
        from backend.services import audit_service
        audit_service.log_event(action=action, actor_login_id=actor, tenant_id=tenant_id,
                                target_type="user", target_id=target_login, payload=payload)
    except Exception:
        pass
