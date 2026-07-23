"""인증 라우터 - 로그인 / 회원가입 / 마이페이지"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from typing import Optional
from backend.models import LoginRequest, SignupRequest, TokenResponse
from backend.auth import (
    create_access_token, get_current_user, is_master_login,
    is_system_admin as _is_system_admin,
)

# ── 공용 helper (모든 Accounts 읽기·쓰기는 accounts_service 경유) ─────────────
from backend.services.accounts_service import (
    hash_password   as _hash_password,
    verify_password as _verify_password,
    find_account    as _find_account,
    build_account_dict,
    append_account,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# /login
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, request: Request = None):
    # PG-only(Phase B): 계정은 PostgreSQL(users + tenants)에서만 조회한다.
    from backend.services import login_guard_pg_service as _guard
    from backend.services import audit_service as _audit
    from backend.services import account_security_pg_service as _sec

    _ua = request.headers.get("user-agent") if request else None
    _xff = request.headers.get("x-forwarded-for") if request else None
    _ip = (_xff.split(",")[0].strip() if _xff else (request.client.host if request and request.client else None))
    _GENERIC = "ID 또는 비밀번호가 올바르지 않습니다."  # 계정 존재 여부 비노출(통일 메시지)
    _LOCKED_MSG = "로그인 시도가 너무 많습니다. 약 10분 후 다시 시도해 주세요."

    # 1) 잠금 확인(인증 이전). fail-open: PG 오류 시 None.
    if _guard.check_locked(req.login_id):
        _audit.log_event(action="LOGIN_LOCKED", actor_login_id=req.login_id,
                         ip_address=_ip, user_agent=_ua, payload={"success": False})
        _sec.record_event(login_id=req.login_id, tenant_id=None, event_type=_sec.EV_LOGIN_LOCKED,
                          ip=_ip, user_agent=_ua, success=False, reason="lockout", risk_level="low")
        raise HTTPException(status_code=429, detail=_LOCKED_MSG)

    acc = _find_account(req.login_id) or {}

    def _fail():
        locked = _guard.record_failure(req.login_id, ip=_ip, user_agent=_ua)
        _audit.log_event(action="LOGIN_FAILED", actor_login_id=req.login_id,
                         ip_address=_ip, user_agent=_ua,
                         payload={"success": False, "locked": locked})
        _sec.record_event(login_id=req.login_id, tenant_id=(str(acc.get("tenant_id", "")).strip() or None),
                          event_type=(_sec.EV_LOGIN_LOCKED if locked else _sec.EV_LOGIN_FAILED),
                          ip=_ip, user_agent=_ua, success=False,
                          reason=("lockout" if locked else "bad_credentials"),
                          risk_level=("low" if locked else "none"))
        if locked:
            raise HTTPException(status_code=429, detail=_LOCKED_MSG)
        raise HTTPException(status_code=401, detail=_GENERIC)

    # 계정 미존재 — 존재 여부를 드러내지 않도록 잘못된 자격증명과 동일 처리(+실패 카운트).
    if not acc:
        _fail()

    is_active = str(acc.get("is_active", "")).strip().lower() in ("true", "1", "y")
    if not is_active:
        # 승인 대기/비활성은 별도 안내(UX). 잠금 카운트에는 포함하지 않음.
        # 승인 후 '초대(invited)' 상태(최초 비밀번호 미설정)면 구조화 오류로 구분해 사용자가
        # 활성화 링크를 요청하도록 안내한다(invited 계정은 사용 가능한 비밀번호가 없어 비밀번호
        # 검증 이전 단계에서만 구분 가능 — 기존에도 비활성 존재는 노출되므로 노출 범위 동일).
        _not_activated = False
        try:
            from backend.db.session import is_configured as _cfg2
            if _cfg2():
                from sqlalchemy import select as _sel
                from backend.db.models.user import AccountUser as _AU
                from backend.db.session import get_sessionmaker as _gsm
                from backend.services import account_state as _st2
                with _gsm()() as _s:
                    _u = _s.scalar(_sel(_AU).where(_AU.login_id == req.login_id))
                    _not_activated = _u is not None and _st2.account_status_of(_u) == _st2.ACCOUNT_INVITED
        except Exception:
            _not_activated = False
        if _not_activated:
            raise HTTPException(
                status_code=403,
                detail={"code": "ACCOUNT_NOT_ACTIVATED",
                        "message": "아직 최초 비밀번호가 설정되지 않은 계정입니다. "
                                   "관리자가 전달한 활성화 링크에서 비밀번호를 먼저 설정하거나, 관리자에게 재발급을 요청하세요."})
        raise HTTPException(status_code=403, detail="관리자 승인 전이거나 비활성화된 계정입니다.")

    hashed = str(acc.get("password_hash", "")).strip()
    if not hashed or not _verify_password(req.password, hashed):
        _fail()

    # 비밀번호 정상 — 계정공유 의심 보안차단 확인(비밀번호 맞아도 차단 시 로그인 불가).
    # is_active(관리자 비활성)와 구분되는 별도 보안차단.
    if _sec.is_security_blocked(req.login_id):
        raise HTTPException(status_code=403, detail=_sec.BLOCK_MESSAGE)

    # 성공 — 실패 카운터/잠금 해제.
    _guard.record_success(req.login_id)

    is_admin  = str(acc.get("is_admin", "")).strip().lower() in ("true", "1", "y")
    tenant_id = str(acc.get("tenant_id", "")).strip() or req.login_id
    office_name = str(acc.get("office_name", "")).strip()
    contact_name = str(acc.get("contact_name", "")).strip()

    # 승인형 SaaS: flag ON 시 tenant 가 active/pending_activation 이 아니면 신규 토큰 발급 차단
    # (fail-closed — suspended/terminated/missing/no_column/error 모두 차단). 마스터 예외.
    # flag OFF 면 무동작(기존 로그인 동작 유지).
    _enforce_tenant = False
    if not is_master_login(req.login_id):
        try:
            from backend.db.feature_flags import approved_saas_enabled
            from backend.db.session import is_configured as _cfg
            _enforce_tenant = bool(approved_saas_enabled() and _cfg())
        except Exception:
            _enforce_tenant = False
    if _enforce_tenant:
        from backend.services.auth_pg_service import tenant_service_status
        if tenant_service_status(tenant_id) not in ("active", "pending_activation"):
            raise HTTPException(status_code=403, detail="사무소 서비스를 사용할 수 없습니다. 관리자에게 문의하십시오.")

    # 권한(role) 산정 — 마스터는 항상 admin, 그 외는 PG role 조회(없으면 is_admin 기반).
    is_master = is_master_login(req.login_id)
    if is_master:
        is_admin = True
    role = "admin" if is_admin else "user"
    try:
        from backend.db.session import is_configured
        if is_configured():
            from backend.services.auth_pg_service import account_auth_status
            _info = account_auth_status(req.login_id)
            if _info["status"] != "missing":
                is_admin = bool(_info["is_admin"]) or is_master
                role = "admin" if is_admin else str(_info["role"] or "user")
    except Exception:
        pass

    claims = {
        "sub":         req.login_id,
        "tenant_id":   tenant_id,
        "is_admin":    is_admin,
        "role":        role,
        "office_name": office_name,
        "contact_name": contact_name,
    }
    # 단일 세션(새 로그인 우선): 기존 활성 일반 세션 revoke + 새 sid 발급/저장.
    # FEATURE_SINGLE_SESSION off면 전혀 동작하지 않음(claims에 sid 없음 → 기존과 동일).
    try:
        from backend.db.feature_flags import single_session_enabled
        if single_session_enabled():
            from backend.services.session_pg_service import (
                new_session_id, revoke_active_sessions, create_session,
            )
            sid = new_session_id()
            _revoked = revoke_active_sessions(req.login_id, reason="new_login", only_non_kiosk=True)
            if _revoked:
                # 단일세션으로 기존 세션이 밀려남 → 공유 의심 신호 이벤트.
                _sec.record_event(login_id=req.login_id, tenant_id=tenant_id,
                                  event_type=_sec.EV_SESSION_REVOKED_BY_NEW_LOGIN,
                                  ip=_ip, user_agent=_ua, success=True, reason="new_login", risk_level="low")
            create_session(req.login_id, tenant_id, sid, user_agent=_ua, ip=_ip, is_kiosk=False)
            claims["sid"] = sid
    except Exception as e:
        # 비치명적: 세션 저장 실패해도 로그인 자체는 진행(가용성). 단 flag on 환경은 0007 적용 필수.
        print(f"[auth.login] single-session setup failed (non-fatal): {e}")

    token = create_access_token(claims)
    _audit.log_event(action="LOGIN_SUCCESS", actor_login_id=req.login_id, tenant_id=tenant_id,
                     ip_address=_ip, user_agent=_ua, payload={"success": True})
    # 로그인 성공 이벤트 기록 + 계정공유 의심 평가(1회 알림 / 누적 2회 차단).
    _sec.record_event(login_id=req.login_id, tenant_id=tenant_id, event_type=_sec.EV_LOGIN_SUCCESS,
                      ip=_ip, user_agent=_ua, success=True, reason="login", risk_level="none")
    _sec.evaluate_suspicion(login_id=req.login_id, tenant_id=tenant_id, ip=_ip, user_agent=_ua)
    return TokenResponse(
        access_token=token,
        login_id=req.login_id,
        tenant_id=tenant_id,
        is_admin=is_admin,
        role=role,
        is_master=is_master,
        is_system_admin=_is_system_admin(req.login_id),
        office_name=office_name,
        contact_name=contact_name,
    )


# ─────────────────────────────────────────────────────────────────────────────
# /logout — 현재 세션 revoke (단일 세션 모드). off면 토큰 무상태라 no-op 성공.
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/logout")
def logout(current_user: dict = Depends(get_current_user)):
    try:
        from backend.db.feature_flags import single_session_enabled
        if single_session_enabled():
            sid = current_user.get("session_id")
            if sid:
                from backend.services.session_pg_service import revoke_session
                revoke_session(sid, reason="logout")
    except Exception as e:
        print(f"[auth.logout] {e}")
    # 로그아웃 이벤트 기록(감지는 LOGOUT 단독 기준 금지 — 보조 신호). best-effort.
    try:
        from backend.services import account_security_pg_service as _sec
        _sec.record_event(login_id=current_user.get("sub", ""),
                          tenant_id=current_user.get("tenant_id"),
                          event_type=_sec.EV_LOGOUT, success=True, reason="logout", risk_level="none")
    except Exception:
        pass
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# /signup
# ─────────────────────────────────────────────────────────────────────────────
def _prepare_agent_rrn_fields(raw_value):
    """입력된 행정사 주민번호를 **검증·암호화**해 tenants 컬럼 dict 로 반환(fail-closed).

    정책(확정):
    - 빈 값 → None(선택 입력 → 가입 계속, agent_rrn 미저장).
    - 입력됨 + 형식 오류 → HTTPException 400("행정사 주민등록번호 형식이 올바르지 않습니다.").
      허용 형식: ``900101-1234567`` / ``9001011234567`` (숫자 13자리 기준).
    - 입력됨 + 암호화 키 미설정/암호화 실패 → HTTPException 503(키 이름 비노출).
    검증·암호화는 **DB write 이전**에 수행하므로, 실패 시 계정이 생성되지 않는다.
    평문/해시는 저장하지 않으며 예외 메시지·로그에 PII(raw RRN)를 남기지 않는다.
    """
    raw = (raw_value or "").strip()
    if not raw:
        return None
    from datetime import datetime, timezone
    from backend.services.pii_crypto import (
        encrypt_agent_rrn, rrn_last4, validate_rrn_format, RrnFormatError,
    )
    if not validate_rrn_format(raw):
        raise HTTPException(status_code=400, detail="행정사 주민등록번호 형식이 올바르지 않습니다.")
    try:
        cipher = encrypt_agent_rrn(raw)
        last4 = rrn_last4(raw)
    except RrnFormatError:
        raise HTTPException(status_code=400, detail="행정사 주민등록번호 형식이 올바르지 않습니다.")
    except Exception:
        # PiiKeyMissing 등 모든 암호화 실패 → 키 이름/평문 비노출, 가입 자체를 차단.
        raise HTTPException(
            status_code=503,
            detail="주민등록번호 보안 저장 설정이 완료되지 않아 가입신청을 처리할 수 없습니다. 관리자에게 문의하십시오.",
        )
    return {
        "agent_rrn_encrypted": cipher,
        "agent_rrn_last4": last4,
        "agent_rrn_updated_at": datetime.now(timezone.utc),
    }


@router.post("/signup")
def signup(req: SignupRequest):
    # 승인형 SaaS 활성 시 직접 가입(즉시 tenant/user 생성) 차단 — '사무소 이용신청' 흐름만 허용.
    # 프론트 우회/직접 API 호출로도 tenant/user 가 만들어지지 않도록 서버에서 강제.
    # FEATURE_APPROVED_SAAS OFF(현행 운영)면 기존 동작 그대로 유지.
    try:
        from backend.db.feature_flags import approved_saas_enabled
        _saas_on = approved_saas_enabled()
    except Exception:
        _saas_on = False
    if _saas_on:
        raise HTTPException(
            status_code=409,
            detail="사무소 이용신청 화면(/apply)을 이용해 주세요. 관리자 심사 후 계정이 발급됩니다.",
        )
    if req.password != req.confirm_password:
        raise HTTPException(status_code=400, detail="비밀번호 확인이 일치하지 않습니다.")
    if not req.login_id.strip():
        raise HTTPException(status_code=400, detail="로그인 ID를 입력해주세요.")
    if not req.office_name.strip():
        raise HTTPException(status_code=400, detail="사무실 이름을 입력해주세요.")

    login_id = req.login_id.strip()

    # 행정사 주민번호 검증·암호화를 **계정 생성 이전**에 먼저 수행(fail-closed).
    # 형식 오류 → 400, 키 미설정/암호화 실패 → 503 으로 즉시 차단되어 계정이 생성되지 않는다.
    rrn_fields = _prepare_agent_rrn_fields(req.agent_rrn)

    # ── PG-only(Phase B) ─────────────────────────────────────────────────
    # 가입신청은 PostgreSQL(tenants + users)에만 기록한다.
    # is_active=False → 관리자 승인 후 활성화.
    # 행정사 주민번호(agent_rrn)는 입력되면 **암호화**해 tenants.agent_rrn_encrypted 에 저장한다
    # (평문/해시는 저장하지 않음). tenant+user 는 단일 commit 으로 원자적으로 생성된다.
    # 승인 플로우는 is_active/시트키만 갱신하므로 이 값은 보존된다.
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        if session.scalar(select(AccountUser).where(AccountUser.login_id == login_id)):
            raise HTTPException(status_code=409, detail="동일한 ID가 존재합니다. 다른 ID로 가입신청해 주십시오.")
        tenant_id = login_id  # default rule: tenant_id == login_id
        existing_tenant = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        if not existing_tenant:
            t = Tenant(
                tenant_id=tenant_id,
                office_name=req.office_name.strip(),
                office_adr=(req.office_adr or "").strip() or None,
                biz_reg_no=(req.biz_reg_no or "").strip() or None,
                is_active=False,
            )
            if rrn_fields:
                for col, val in rrn_fields.items():
                    setattr(t, col, val)
            session.add(t)
            session.flush()
        elif rrn_fields:
            # tenant 가 이미 있고 rrn 이 입력된 경우에도 저장(검증은 위에서 통과한 상태).
            for col, val in rrn_fields.items():
                setattr(existing_tenant, col, val)
        session.add(AccountUser(
            login_id=login_id,
            tenant_id=tenant_id,
            password_hash=_hash_password(req.password),
            contact_name=(req.contact_name or "").strip() or None,
            contact_tel=(req.contact_tel or "").strip() or None,
            is_admin=False,
            is_active=False,  # admin approval required
        ))
        session.commit()
    return {
        "message": "가입신청이 완료되었습니다. 관리자 승인 후 로그인 가능합니다.",
        "login_id": login_id,
        "tenant_id": tenant_id,
        "status": "pending",
    }


# ─────────────────────────────────────────────────────────────────────────────
# /me
# ─────────────────────────────────────────────────────────────────────────────
# 현재 온보딩(사용법 안내) 버전. 신규 초대 사용자만 미완료로 시작(migration backfill).
ONBOARDING_VERSION = 1

# 문서 자동작성 필수정보 — 역할별 required 필드. staff 는 tenant 공통정보를 요구하지 않는다.
_PROFILE_REQUIRED = {
    "office_admin": ["office_name", "office_adr", "contact_name", "contact_tel", "biz_reg_no", "agent_rrn"],
    "office_staff": ["contact_name", "contact_tel"],
}


def _is_system_admin(current_user: dict) -> bool:
    return bool(current_user.get("is_system_admin") or current_user.get("is_master"))


def _office_role_for(is_admin: bool, source_application_id, current_user: dict) -> Optional[str]:
    """canonical 사무소 역할 — DB role(admin/user/sub_admin) 저장 체계와 **분리**해 계산한다.

    - system admin/master → None
    - 승인형 사무소 계정(tenant.source_application_id 존재) + is_admin → "office_admin"
    - 승인형 사무소 계정 + not is_admin → "office_staff"
    - 그 외(레거시 비-SaaS) → None (문서 필수정보/온보딩 강제 안 함)"""
    if _is_system_admin(current_user):
        return None
    if not (str(source_application_id or "").strip()):
        return None
    return "office_admin" if is_admin else "office_staff"


def _compute_profile(role: str, *, office_name, office_adr, contact_name,
                     contact_tel_effective, biz_reg_no, agent_rrn_registered) -> tuple[bool, list[str]]:
    """역할별 문서 자동작성 필수정보 완성도. (complete, missing_keys). 비-office 역할은 완성 처리(경고 억제)."""
    from backend.services.korean_identifier_format import validate_biz_reg_no, validate_phone
    required = _PROFILE_REQUIRED.get(role)
    if not required:
        return True, []
    present = {
        "office_name": bool((office_name or "").strip()),
        "office_adr": bool((office_adr or "").strip()),
        "contact_name": bool((contact_name or "").strip()),
        "contact_tel": validate_phone(contact_tel_effective),
        "biz_reg_no": validate_biz_reg_no(biz_reg_no),
        "agent_rrn": bool(agent_rrn_registered),
    }
    missing = [k for k in required if not present.get(k, False)]
    return (len(missing) == 0), missing


def _read_onboarding_version(login_id: str) -> Optional[int]:
    """users.onboarding_completed_version 안전 조회 — 컬럼 미적용(migration 전)이면 None(경고 억제)."""
    try:
        from sqlalchemy import select
        from backend.db.models.user import AccountUser
        from backend.db.session import get_sessionmaker, is_configured
        if not is_configured():
            return ONBOARDING_VERSION  # DB 미구성 → 강제 팝업 없음
        SessionLocal = get_sessionmaker()
        with SessionLocal() as session:
            u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
            if u is None:
                return ONBOARDING_VERSION
            return getattr(u, "onboarding_completed_version", None)
    except Exception:
        return ONBOARDING_VERSION  # 조회 실패 → fail-safe(강제 팝업 없음)


@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    """현재 사용자 정보 — JWT 기본 + 사무소/문서 자동작성 필수정보 상태.

    주민등록번호 평문/복호값은 반환하지 않는다(등록 여부 + 끝 4자리만). GET 은 DB 를 수정하지 않는다."""
    from backend.services.accounts_service import find_account
    from backend.services.korean_identifier_format import format_phone, format_biz_reg_no, normalize_phone

    login_id = current_user.get("login_id", "")
    acc = find_account(login_id) or {}
    role = acc.get("role", "") or ""
    acc_is_admin = str(acc.get("is_admin", "")).upper() in ("TRUE", "Y", "1")
    # canonical 사무소 역할(DB role 과 분리) — profile/onboarding 판정은 이 값을 쓴다.
    office_role = _office_role_for(acc_is_admin, acc.get("source_application_id", ""), current_user)

    contact_tel = acc.get("contact_tel", "") or ""
    contact_tel_source = "stored"
    # 대표자(office_admin) 연락처 미기입 + 승인 신청서에 유효한 office_phone → 표시용 fallback(GET 은 DB 미수정).
    if office_role == "office_admin" and not normalize_phone(contact_tel):
        app_id = acc.get("source_application_id", "") or ""
        if app_id:
            try:
                from backend.services.office_application_pg_service import get_application_office_phone
                app_phone = get_application_office_phone(app_id)
            except Exception:
                app_phone = ""
            from backend.services.korean_identifier_format import validate_phone
            if validate_phone(app_phone):
                contact_tel = app_phone
                contact_tel_source = "application_fallback"

    biz_reg_no = acc.get("biz_reg_no", "") or ""
    agent_rrn_registered = bool(acc.get("agent_rrn_registered"))
    agent_rrn_last4 = acc.get("agent_rrn_last4", "") or ""

    complete, missing = _compute_profile(
        office_role or "",
        office_name=acc.get("office_name", ""), office_adr=acc.get("office_adr", ""),
        contact_name=acc.get("contact_name", ""), contact_tel_effective=contact_tel,
        biz_reg_no=biz_reg_no, agent_rrn_registered=agent_rrn_registered,
    )

    done_ver = _read_onboarding_version(login_id)
    # 시스템 관리자는 신규 tenant 용 tour 를 강제하지 않는다. office_role 기준으로만 강제.
    onboarding_required = (office_role in _PROFILE_REQUIRED) and (
        done_ver is None or int(done_ver) < ONBOARDING_VERSION)

    return {
        **current_user,
        "role":                 role or current_user.get("role", ""),
        "office_role":          office_role,
        "office_name":          acc.get("office_name", "") or current_user.get("office_name", ""),
        "office_adr":           acc.get("office_adr", ""),
        "contact_name":         acc.get("contact_name", "") or current_user.get("contact_name", ""),
        "contact_tel":          contact_tel,
        "contact_tel_formatted": format_phone(contact_tel),
        "contact_tel_source":   contact_tel_source,
        "biz_reg_no":           biz_reg_no,
        "biz_reg_no_formatted": format_biz_reg_no(biz_reg_no),
        "agent_rrn_registered": agent_rrn_registered,
        "agent_rrn_last4":      agent_rrn_last4,
        "profile_complete":     complete,
        "missing_profile_fields": missing,
        "onboarding_required":  bool(onboarding_required),
        "onboarding_version":   ONBOARDING_VERSION,
    }


class MeUpdateRequest(BaseModel):
    office_name:  Optional[str] = None
    office_adr:   Optional[str] = None
    contact_name: Optional[str] = None
    contact_tel:  Optional[str] = None
    biz_reg_no:   Optional[str] = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password:     str


class AgentRrnMeRequest(BaseModel):
    agent_rrn: str = ""


class OnboardingCompleteRequest(BaseModel):
    version: int = ONBOARDING_VERSION
    action:  str = "completed"   # "completed" | "skipped"


@router.patch("/me")
def update_me(body: MeUpdateRequest, current_user: dict = Depends(get_current_user)):
    """사무소/문서 필수정보 수정. 본인 연락처는 누구나, tenant 공통정보(사무소명·주소·사업자번호)는
    office_admin(또는 전체 관리자)만. 서버에서 숫자 정규화·유효성 검증 후 저장."""
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services.korean_identifier_format import (
        normalize_phone, validate_phone, normalize_biz_reg_no, validate_biz_reg_no,
    )

    login_id = current_user.get("login_id", "")
    fields = body.model_dump(exclude_none=True)
    role = ""
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        role = (getattr(u, "role", "") or "")
        can_edit_tenant = (role == "office_admin") or bool(current_user.get("is_admin")) or bool(current_user.get("is_master"))

        # 본인 연락처
        if "contact_name" in fields:
            u.contact_name = (fields["contact_name"] or "").strip()
        if "contact_tel" in fields:
            tel = normalize_phone(fields["contact_tel"])
            if tel and not validate_phone(tel):
                raise HTTPException(status_code=400, detail="전화번호 형식이 올바르지 않습니다.")
            u.contact_tel = tel

        # tenant 공통정보 — 권한 필요
        tenant_fields = [k for k in ("office_name", "office_adr", "biz_reg_no") if k in fields]
        if tenant_fields and not can_edit_tenant:
            raise HTTPException(status_code=403, detail="사무소 공통정보는 대표자(사무소 관리자)만 수정할 수 있습니다.")
        if tenant_fields:
            t = session.scalar(select(Tenant).where(Tenant.tenant_id == u.tenant_id))
            if t is not None:
                if "office_name" in fields:
                    t.office_name = (fields["office_name"] or "").strip()
                if "office_adr" in fields:
                    t.office_adr = (fields["office_adr"] or "").strip()
                if "biz_reg_no" in fields:
                    biz = normalize_biz_reg_no(fields["biz_reg_no"])
                    if biz and not validate_biz_reg_no(biz):
                        raise HTTPException(status_code=400, detail="사업자등록번호는 숫자 10자리여야 합니다.")
                    t.biz_reg_no = biz
        session.commit()

    try:
        import backend.services.tenant_service as _ts
        _ts._TENANT_MAP_CACHE = {}
        _ts._TENANT_MAP_TIME = 0
    except Exception:
        pass

    return {"ok": True}


@router.patch("/me/agent-rrn")
def update_my_agent_rrn(body: AgentRrnMeRequest, current_user: dict = Depends(get_current_user)):
    """행정사 주민등록번호 등록/변경 — office_admin(또는 전체 관리자)만. 암호화 저장, 원문 미반환.
    키 미설정 시 503(fail-closed). 평문은 로그/응답/예외에 남기지 않는다."""
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    login_id = current_user.get("login_id", "")
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        role = (getattr(u, "role", "") or "")
        allowed = (role == "office_admin") or bool(current_user.get("is_admin")) or bool(current_user.get("is_master"))
        if not allowed:
            raise HTTPException(status_code=403, detail="행정사 주민등록번호는 대표자(사무소 관리자)만 변경할 수 있습니다.")
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == u.tenant_id))
        if t is None:
            raise HTTPException(status_code=404, detail="사무소 정보를 찾을 수 없습니다.")
        raw = (body.agent_rrn or "").strip()
        if not raw:
            raise HTTPException(status_code=400, detail="행정사 주민등록번호를 입력하세요.")
        prepared = _prepare_agent_rrn_fields(raw)  # 형식오류 400 / 키없음 503 (평문 미노출)
        t.agent_rrn_encrypted = prepared["agent_rrn_encrypted"]
        t.agent_rrn_last4 = prepared["agent_rrn_last4"]
        t.agent_rrn_updated_at = prepared["agent_rrn_updated_at"]
        last4 = prepared["agent_rrn_last4"]
        session.commit()
    return {"ok": True, "registered": True, "agent_rrn_last4": last4}


@router.post("/me/onboarding/complete")
def complete_my_onboarding(body: OnboardingCompleteRequest, current_user: dict = Depends(get_current_user)):
    """최초 로그인 온보딩 완료/건너뛰기 기록 — 현재 사용자에게만. 다른 tenant/user 미수정.
    action 은 completed|skipped, version 은 현재 ONBOARDING_VERSION 과 정확히 일치해야 한다(그 외 400)."""
    from datetime import datetime, timezone
    from sqlalchemy import select
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    if body.action not in ("completed", "skipped"):
        raise HTTPException(status_code=400, detail={
            "code": "INVALID_ONBOARDING_ACTION", "message": "action 은 completed 또는 skipped 여야 합니다."})
    if int(body.version) != ONBOARDING_VERSION:
        raise HTTPException(status_code=400, detail={
            "code": "INVALID_ONBOARDING_VERSION",
            "message": "온보딩 버전이 현재 버전과 일치하지 않습니다.",
            "expected_version": ONBOARDING_VERSION})

    login_id = current_user.get("login_id", "")
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        u.onboarding_completed_version = ONBOARDING_VERSION
        u.onboarding_completed_at = datetime.now(timezone.utc)
        session.commit()
    return {"ok": True, "onboarding_version": ONBOARDING_VERSION, "action": body.action}


@router.patch("/me/password")
def change_password(body: PasswordChangeRequest, current_user: dict = Depends(get_current_user)):
    """비밀번호 변경 — PG-only(users.password_hash)."""
    from sqlalchemy import select
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services.accounts_service import verify_password, hash_password

    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="새 비밀번호는 6자 이상이어야 합니다.")

    login_id = current_user.get("login_id", "")
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        if not verify_password(body.current_password, u.password_hash or ""):
            raise HTTPException(status_code=400, detail="현재 비밀번호가 올바르지 않습니다.")
        u.password_hash = hash_password(body.new_password)
        session.commit()

    return {"ok": True}
