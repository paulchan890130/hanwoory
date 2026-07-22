"""수동 승인형 SaaS — 공개 신청 / 활성화 / 관리자 심사·승인·계정 lifecycle 라우터.

전체가 FEATURE_APPROVED_SAAS 로 게이트된다(off → 404). 관리자(시스템 운영) 엔드포인트는 require_system_admin
(서버측 권한검사) 로 보호한다. 공개 엔드포인트는 무인증이며 rate-limit + 입력검증을 적용한다.

증빙 업로드는 FEATURE_OFFICE_APPLICATION_UPLOADS 로 별도 게이트(기본 off) — 지속 스토리지 확정 전까지 비활성.
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.auth import require_system_admin, require_office_admin
from backend.services.account_state import STATE_ERROR_HTTP as _STATE_HTTP

router = APIRouter()


# ── 공통 가드 ────────────────────────────────────────────────────────────────
def _require_saas() -> None:
    from backend.db.feature_flags import approved_saas_enabled
    from backend.db.session import is_configured
    if not approved_saas_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    if not is_configured():
        raise HTTPException(status_code=503, detail="데이터베이스가 구성되지 않았습니다.")


# ── 간단 IP rate limiter (per-process, in-memory) ────────────────────────────
_RL_LOCK = Lock()
_RL_HITS: dict[str, deque] = {}
_RL_WINDOW_SEC = 3600
_RL_MAX = 5  # 시간당 IP 당 최대 신청 수


def _rate_limit(ip: str) -> None:
    now = time.time()
    with _RL_LOCK:
        dq = _RL_HITS.setdefault(ip or "?", deque())
        while dq and now - dq[0] > _RL_WINDOW_SEC:
            dq.popleft()
        if len(dq) >= _RL_MAX:
            raise HTTPException(status_code=429, detail="신청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.")
        dq.append(now)


def _trust_proxy() -> bool:
    """신뢰 프록시(예: Render 엣지) 뒤에 있을 때만 X-Forwarded-For 를 신뢰한다.
    env ``TRUST_PROXY_HEADERS`` truthy 일 때만 True. 기본 False → XFF 무시(스푸핑 방지).
    운영(Render)에서는 반드시 켜야 rate-limit 이 클라이언트별로 동작한다(꺼져 있으면 프록시 IP
    하나로 집계되어 과차단될 수 있음 — 안전측 실패)."""
    import os
    return os.environ.get("TRUST_PROXY_HEADERS", "").strip().lower() in ("1", "true", "yes", "y", "on")


def _client_ip(request: Optional[Request]) -> Optional[str]:
    """서버에서 신뢰 가능한 IP 만 추출한다. 클라이언트가 제출한 IP(body/query)는 절대 사용하지 않는다.

    - 기본: TCP 연결의 request.client.host 만 사용(스푸핑 불가).
    - TRUST_PROXY_HEADERS on(신뢰 엣지 프록시 뒤): X-Forwarded-For 의 최좌측(원 클라이언트) 사용.
      off 인데 XFF 가 와도 **무시**한다 → 임의 클라이언트가 XFF 로 rate-limit 우회 불가.
    """
    if request is None:
        return None
    direct = request.client.host if request.client else None
    if _trust_proxy():
        xff = request.headers.get("x-forwarded-for")
        if xff:
            first = xff.split(",")[0].strip()
            if first:
                return first
    return direct


# ── 스키마 ───────────────────────────────────────────────────────────────────
class OfficeApplicationCreate(BaseModel):
    office_name: str
    representative_name: Optional[str] = None
    representative_email: Optional[str] = None        # 승인 시 office_admin 계정으로 발급
    business_registration_number: Optional[str] = None
    office_address: Optional[str] = None
    office_phone: Optional[str] = None
    staff_name: Optional[str] = None                  # 승인 시 office_staff 서브계정으로 발급
    staff_email: Optional[str] = None
    # 구버전 클라이언트 호환용 fallback(신규 폼은 위 canonical 필드를 사용).
    applicant_name: Optional[str] = None
    applicant_email: Optional[str] = None
    applicant_phone: Optional[str] = None
    intended_use: Optional[str] = None
    requested_user_1_name: Optional[str] = None
    requested_user_1_email: Optional[str] = None
    requested_user_2_name: Optional[str] = None
    requested_user_2_email: Optional[str] = None
    agree_privacy: bool = False
    agree_terms: bool = False


class ReviewPatch(BaseModel):
    action: str  # "start_review" | "note"
    review_note_internal: Optional[str] = None


class ApproveUser(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None  # office_admin | office_staff


class ApproveRequest(BaseModel):
    user1: Optional[ApproveUser] = None
    user2: Optional[ApproveUser] = None
    seat_limit: int = 2


class RejectRequest(BaseModel):
    rejection_reason_public: str
    review_note_internal: Optional[str] = None


class ActivationComplete(BaseModel):
    token: str
    new_password: str


class ReplaceRequest(BaseModel):
    new_name: str
    new_email: str
    new_role: Optional[str] = None


class PurgeRequest(BaseModel):
    confirm_tenant_id: str
    confirm_office_name: str
    confirmation_phrase: str


class IssueAdminRequest(BaseModel):
    name: str
    email: str
    confirm_tenant_id: Optional[str] = None


class RelinkPreviewRequest(BaseModel):
    login_id: str
    target_tenant_id: str


class RelinkRequest(BaseModel):
    login_id: str
    target_tenant_id: str
    confirm_login_id: str
    confirm_target_tenant_id: str
    # 강한 확인(§8) — 확인 문구 + preview 시점 원본 tenant. 서버가 4값 + 원본 불변을 검증.
    confirmation_phrase: str
    source_tenant_id: str


# ── 공개: 신청 접수 ───────────────────────────────────────────────────────────
@router.post("/public/office-applications")
def submit_application(body: OfficeApplicationCreate, request: Request = None):
    _require_saas()
    if not body.agree_privacy or not body.agree_terms:
        raise HTTPException(status_code=400, detail="개인정보 및 이용약관에 동의해야 신청할 수 있습니다.")
    ip = _client_ip(request)
    _rate_limit(ip or "?")
    from backend.services import office_application_pg_service as svc
    from backend.services.session_pg_service import short_hash
    try:
        result = svc.create_application(body.model_dump(exclude={"agree_privacy", "agree_terms"}),
                                        ip_hash=short_hash(ip))
    except svc.ApplicationError as e:
        code_map = {"DUPLICATE_PENDING": 409, "DUPLICATE_USER_EMAIL": 409,
                    "MISSING_OFFICE_NAME": 400, "MISSING_FIELD": 400, "BAD_EMAIL": 400,
                    "BAD_BIZ_REG_NO": 400, "BAD_PHONE": 400}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail=e.message)
    try:
        from backend.services import audit_service
        audit_service.log_event(action="office_application_submitted",
                                target_type="office_application",
                                target_id=result["application_id"])
    except Exception:
        pass
    # 신청자에게는 접수번호만 노출(내부 메모/중복경고 비노출). 계정/로그인 링크 없음.
    return {
        "application_id": result["application_id"],
        "status": result["status"],
        "message": "신청이 접수되었습니다. 관리자 심사 후 별도로 안내드립니다.",
    }


# ── 공개: 활성화(최초 비밀번호 설정) ──────────────────────────────────────────
@router.get("/public/activation/{token}")
def check_activation(token: str):
    _require_saas()
    from backend.services import activation_pg_service as act
    info = act.verify_activation_token(token)
    if info is None:
        raise HTTPException(status_code=404, detail="유효하지 않거나 만료된 활성화 링크입니다.")
    # login_id 만 노출(안내용). 토큰 재노출 없음.
    return {"valid": True, "login_id": info["login_id"]}


@router.post("/public/activation/complete")
def complete_activation(body: ActivationComplete):
    _require_saas()
    from backend.services import activation_pg_service as act
    try:
        result = act.complete_activation(body.token, body.new_password)
    except act.ActivationError as e:
        code_map = {"EXPIRED": 410, "BAD_TOKEN": 400, "NO_USER": 404,
                    "WEAK_PASSWORD": 400, **_STATE_HTTP}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail=e.message)
    return {"ok": True, "login_id": result["login_id"]}


# ── 관리자: 신청 심사 ─────────────────────────────────────────────────────────
@router.get("/admin/office-applications")
def admin_list_applications(status: Optional[str] = None, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import office_application_pg_service as svc
    return {"applications": svc.list_applications(status)}


@router.get("/admin/office-applications/{application_id}")
def admin_get_application(application_id: str, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import office_application_pg_service as svc
    a = svc.get_application(application_id)
    if a is None:
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다.")
    return a


@router.patch("/admin/office-applications/{application_id}/review")
def admin_review(application_id: str, body: ReviewPatch, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import office_application_pg_service as svc
    try:
        if body.action == "start_review":
            return svc.start_review(application_id, user.get("login_id", ""))
        if body.action == "note":
            return svc.update_review_note(application_id, user.get("login_id", ""),
                                          body.review_note_internal)
        raise HTTPException(status_code=400, detail="알 수 없는 action 입니다.")
    except svc.ApplicationError as e:
        code_map = {"NOT_FOUND": 404, "BAD_STATE": 409}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail=e.message)


@router.post("/admin/office-applications/{application_id}/approve")
def admin_approve(application_id: str, body: ApproveRequest, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import office_application_pg_service as svc
    try:
        return svc.approve(
            application_id, user.get("login_id", ""),
            user1=body.user1.model_dump() if body.user1 else None,
            user2=body.user2.model_dump() if body.user2 else None,
            seat_limit=body.seat_limit,
        )
    except svc.ApplicationError as e:
        code_map = {"NOT_FOUND": 404, "BAD_STATE": 409, "EMAIL_IN_USE": 409,
                    "DUPLICATE_USER_EMAIL": 409, "MISSING_USER": 400, "BAD_EMAIL": 400,
                    "SEAT_LIMIT": 409}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail=e.message)


@router.post("/admin/office-applications/{application_id}/reject")
def admin_reject(application_id: str, body: RejectRequest, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import office_application_pg_service as svc
    if not (body.rejection_reason_public or "").strip():
        raise HTTPException(status_code=400, detail="반려 사유(공개)를 입력해 주세요.")
    try:
        return svc.reject(application_id, user.get("login_id", ""),
                          body.rejection_reason_public, body.review_note_internal)
    except svc.ApplicationError as e:
        code_map = {"NOT_FOUND": 404, "BAD_STATE": 409, "ALREADY_APPROVED": 409}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail=e.message)


# ── 관리자: 테넌트/사용자 lifecycle ───────────────────────────────────────────
@router.post("/admin/tenants/{tenant_id}/suspend")
def admin_suspend_tenant(tenant_id: str, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import account_lifecycle_pg_service as svc
    try:
        return svc.suspend_tenant(tenant_id, user.get("login_id", ""))
    except svc.LifecycleError as e:
        code_map = {"NOT_FOUND": 404, **_STATE_HTTP}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail=e.message)


@router.post("/admin/tenants/{tenant_id}/restore")
def admin_restore_tenant(tenant_id: str, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import account_lifecycle_pg_service as svc
    try:
        return svc.restore_tenant(tenant_id, user.get("login_id", ""))
    except svc.LifecycleError as e:
        code_map = {"NOT_FOUND": 404, **_STATE_HTTP}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail=e.message)


@router.post("/admin/users/{login_id}/suspend")
def admin_suspend_user(login_id: str, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import account_lifecycle_pg_service as svc
    try:
        return svc.suspend_user(login_id, user.get("login_id", ""))
    except svc.LifecycleError as e:
        code_map = {"NOT_FOUND": 404, "MASTER_PROTECTED": 400, **_STATE_HTTP}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail=e.message)


@router.post("/admin/users/{login_id}/restore")
def admin_restore_user(login_id: str, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import account_lifecycle_pg_service as svc
    try:
        return svc.restore_user(login_id, user.get("login_id", ""))
    except svc.LifecycleError as e:
        code_map = {"NOT_FOUND": 404, **_STATE_HTTP}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail=e.message)


@router.post("/admin/users/{login_id}/reissue-activation")
def admin_reissue_activation(login_id: str, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import activation_pg_service as act
    try:
        return act.reissue_activation_token(login_id, actor=user.get("login_id", ""))
    except act.ActivationError as e:
        code_map = {"NO_USER": 404, **_STATE_HTTP}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail=e.message)


@router.post("/admin/users/{login_id}/replace")
def admin_replace_user(login_id: str, body: ReplaceRequest, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import account_lifecycle_pg_service as svc
    try:
        return svc.replace_user(login_id, body.new_name, body.new_email,
                                user.get("login_id", ""), new_role=body.new_role)
    except svc.LifecycleError as e:
        code_map = {"NOT_FOUND": 404, "EMAIL_IN_USE": 409, "ALREADY_REPLACED": 409,
                    "SEAT_LIMIT": 409, "MASTER_PROTECTED": 400, "BAD_EMAIL": 400, "MISSING_USER": 400,
                    **_STATE_HTTP}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail=e.message)


# ── 공개: 승인형 SaaS 신청 가용 여부(민감정보 미반환, flag 상태만) ─────────────
@router.get("/public/availability")
def public_availability():
    from backend.db.feature_flags import approved_saas_enabled
    from backend.db.session import is_configured
    return {"enabled": bool(approved_saas_enabled() and is_configured())}


# ── 시스템 관리자: tenant 계정 요약(승인 결과 상시 확인용, read-only) ──────────
@router.get("/admin/tenants/{tenant_id}/summary")
def admin_tenant_summary(tenant_id: str, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import account_lifecycle_pg_service as svc
    s = svc.tenant_account_summary(tenant_id)
    if s is None:
        raise HTTPException(status_code=404, detail="테넌트를 찾을 수 없습니다.")
    return s


# ── 사무소 주계정(office_admin): 자기 tenant 계정 관리 ────────────────────────
# tenant_id 는 JWT 에서만 취득(body/query 불신). 서브계정(office_staff)만 관리 가능.
@router.get("/my/office/accounts")
def my_office_accounts(user: dict = Depends(require_office_admin)):
    _require_saas()
    from backend.services import account_lifecycle_pg_service as svc
    s = svc.tenant_account_summary(user.get("tenant_id", ""))
    if s is None:
        raise HTTPException(status_code=404, detail="사무소 정보를 찾을 수 없습니다.")
    return s


_OFFICE_CODE_MAP = {"NOT_FOUND": 404, "CROSS_TENANT": 403, "NOT_SUB_ACCOUNT": 403,
                    "SELF_FORBIDDEN": 403, "MASTER_PROTECTED": 403,
                    "EMAIL_IN_USE": 409, "ALREADY_REPLACED": 409,
                    "BAD_EMAIL": 400, "MISSING_USER": 400,
                    # 상태 전이 코드(BAD_ACCOUNT_STATE/TENANT_*/SEAT_LIMIT/INVITED/… 409)는 공통 소스 사용.
                    **_STATE_HTTP}


@router.post("/my/office/users/{login_id}/suspend")
def my_office_suspend(login_id: str, user: dict = Depends(require_office_admin)):
    _require_saas()
    from backend.services import account_lifecycle_pg_service as svc
    try:
        return svc.office_suspend_sub(user.get("tenant_id", ""), user.get("login_id", ""), login_id)
    except svc.LifecycleError as e:
        raise HTTPException(status_code=_OFFICE_CODE_MAP.get(e.code, 400), detail=e.message)


@router.post("/my/office/users/{login_id}/restore")
def my_office_restore(login_id: str, user: dict = Depends(require_office_admin)):
    _require_saas()
    from backend.services import account_lifecycle_pg_service as svc
    try:
        return svc.office_restore_sub(user.get("tenant_id", ""), user.get("login_id", ""), login_id)
    except svc.LifecycleError as e:
        raise HTTPException(status_code=_OFFICE_CODE_MAP.get(e.code, 400), detail=e.message)


@router.post("/my/office/users/{login_id}/reissue-activation")
def my_office_reissue(login_id: str, user: dict = Depends(require_office_admin)):
    _require_saas()
    from backend.services import account_lifecycle_pg_service as svc
    try:
        return svc.office_reissue_sub(user.get("tenant_id", ""), user.get("login_id", ""), login_id)
    except svc.LifecycleError as e:
        raise HTTPException(status_code=_OFFICE_CODE_MAP.get(e.code, 400), detail=e.message)


@router.post("/my/office/users/{login_id}/replace")
def my_office_replace(login_id: str, body: ReplaceRequest, user: dict = Depends(require_office_admin)):
    _require_saas()
    from backend.services import account_lifecycle_pg_service as svc
    try:
        return svc.office_replace_sub(user.get("tenant_id", ""), user.get("login_id", ""),
                                      login_id, body.new_name, body.new_email)
    except svc.LifecycleError as e:
        raise HTTPException(status_code=_OFFICE_CODE_MAP.get(e.code, 400), detail=e.message)


# ── 시스템 관리자: 신규 신청 건수(배지·알림용) ────────────────────────────────
@router.get("/admin/office-application-stats")
def admin_application_stats(user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import office_application_pg_service as svc
    return svc.stats()


# ── 시스템 관리자: 사업장 연결 현황 / 사용자 없는 사업장 ──────────────────────
@router.get("/admin/tenants/{tenant_id}/connection-summary")
def admin_tenant_connection_summary(tenant_id: str, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import tenant_admin_pg_service as svc
    s = svc.tenant_connection_summary(tenant_id)
    if s is None:
        raise HTTPException(status_code=404, detail="사업장을 찾을 수 없습니다.")
    return s


@router.get("/admin/no-user-tenants")
def admin_no_user_tenants(user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import tenant_admin_pg_service as svc
    return {"tenants": svc.list_no_user_tenants()}


_TENANT_ADMIN_CODE_MAP = {
    "BAD_REQUEST": 400, "NOT_FOUND": 404, "MISSING_USER": 400, "BAD_EMAIL": 400,
    "EMAIL_IN_USE": 409, "TENANT_TERMINATED": 409, "TENANT_SUSPENDED": 409,
    "BAD_TENANT_STATE": 409, "DUPLICATE_ADMIN": 409, "SEAT_LIMIT": 409, "PROTECTED": 403,
    "CONFIRM_MISMATCH": 400, "SAME_TENANT": 409, "BLOCKED": 409,
}


@router.post("/admin/tenants/{tenant_id}/issue-admin-account")
def admin_issue_admin_account(tenant_id: str, body: IssueAdminRequest,
                              user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import tenant_admin_pg_service as svc
    try:
        return svc.issue_admin_account(tenant_id, body.name, body.email,
                                       user.get("login_id", ""), confirm_tenant_id=body.confirm_tenant_id)
    except svc.TenantAdminError as e:
        raise HTTPException(status_code=_TENANT_ADMIN_CODE_MAP.get(e.code, 400), detail=e.message)


# ── 시스템 관리자: 계정 연결 변경(relink) — 데이터는 이동하지 않음 ────────────
@router.post("/admin/account-links/preview")
def admin_account_link_preview(body: RelinkPreviewRequest, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import tenant_admin_pg_service as svc
    return svc.relink_preview(body.login_id, body.target_tenant_id, user.get("login_id", ""))


@router.post("/admin/account-links/relink")
def admin_account_link_relink(body: RelinkRequest, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import tenant_admin_pg_service as svc
    try:
        return svc.relink_account(body.login_id, body.target_tenant_id, user.get("login_id", ""),
                                  body.confirm_login_id, body.confirm_target_tenant_id,
                                  confirmation_phrase=body.confirmation_phrase,
                                  source_tenant_id=body.source_tenant_id)
    except svc.TenantAdminError as e:
        raise HTTPException(status_code=_TENANT_ADMIN_CODE_MAP.get(e.code, 400), detail=e.message)


# ── 시스템 관리자: 사업장 전체 폐기(고위험) ──────────────────────────────────
@router.get("/admin/tenants/{tenant_id}/purge-preview")
def admin_purge_preview(tenant_id: str, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import tenant_purge_pg_service as svc
    try:
        return svc.purge_preview(tenant_id, actor_login=user.get("login_id", ""))
    except svc.PurgeError as e:
        code_map = {"NOT_FOUND": 404, "BAD_REQUEST": 400}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail=e.message)


@router.post("/admin/tenants/{tenant_id}/purge")
def admin_purge_tenant(tenant_id: str, body: PurgeRequest, user: dict = Depends(require_system_admin)):
    _require_saas()
    from backend.services import tenant_purge_pg_service as svc
    try:
        return svc.purge_tenant(
            tenant_id, user.get("login_id", ""),
            confirm_tenant_id=body.confirm_tenant_id,
            confirm_office_name=body.confirm_office_name,
            confirmation_phrase=body.confirmation_phrase,
        )
    except svc.PurgeError as e:
        code_map = {"NOT_FOUND": 404, "BAD_REQUEST": 400, "CONFIRM_MISMATCH": 400,
                    "BAD_STATE": 409, "PROTECTED": 403, "EXTERNAL_STORAGE": 409,
                    "UNCLASSIFIED_TABLES": 409}
        raise HTTPException(status_code=code_map.get(e.code, 400), detail=e.message)
