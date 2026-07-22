"""JWT 인증 유틸리티"""
import os
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "change-me-in-production-use-long-random-string")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8시간

# 마스터 계정 — 절대 비활성화/삭제/강등 불가(서버 강제). 항상 full admin 으로 취급한다.
MASTER_ADMIN_LOGIN_ID = "wkdwhfl"


def is_master_login(login_id: str) -> bool:
    return str(login_id or "").strip() == MASTER_ADMIN_LOGIN_ID


def _system_admin_login_ids() -> set[str]:
    """시스템 운영 관리자 login_id 허용목록(env ``SYSTEM_ADMIN_LOGIN_IDS``, 콤마구분).

    승인형 SaaS 의 **시스템 관리 API**(가입승인/반려·테넌트 정지·계정 교체 등)는 사무소
    관리자(office_admin, tenant 내 is_admin=true)와 반드시 구분해야 한다. is_admin 만으로는
    office_admin 도 통과하므로(권한상승), 시스템 운영자는 마스터 또는 이 허용목록으로만 식별한다.
    기본값은 비어 있음 → **마스터만** 시스템 관리자(deny-by-default, fail-closed).
    매 호출 env 를 새로 읽는다(재시작만으로 반영, 캐시 없음).
    """
    raw = os.environ.get("SYSTEM_ADMIN_LOGIN_IDS", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


def is_system_admin(login_id: str) -> bool:
    """시스템 운영 관리자 여부 = 마스터 OR env 허용목록. office_admin(is_admin) 은 포함되지 않는다."""
    lid = str(login_id or "").strip()
    if not lid:
        return False
    return is_master_login(lid) or (lid in _system_admin_login_ids())

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode["exp"] = expire
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않거나 만료된 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """현재 로그인된 사용자 정보를 JWT에서 추출합니다."""
    payload = decode_token(token)
    login_id: str = payload.get("sub")
    tenant_id: str = payload.get("tenant_id", "")
    is_admin: bool = payload.get("is_admin", False)
    if not login_id:
        raise HTTPException(status_code=401, detail="인증 정보가 없습니다.")

    # ── 계정 비활성/삭제 즉시 차단 + 권한(role) 재확인 ──────────────────────
    # JWT 디코드만으로 통과시키지 않는다. 매 요청 PG 의 is_active/role 을 재확인해,
    # 관리자가 비활성화/삭제/강등한 계정의 기존 토큰(최대 8h)이 계속 쓰이는 것을 막는다.
    # PG 미구성 환경(레거시)에서는 JWT 값을 그대로 사용한다(가용성 우선).
    role: str = str(payload.get("role", "") or ("admin" if is_admin else "user"))
    try:
        from backend.db.session import is_configured
        if is_configured():
            from backend.services.auth_pg_service import account_auth_status
            info = account_auth_status(login_id)
            if info["status"] in ("disabled", "missing"):
                raise HTTPException(
                    status_code=401,
                    detail={"code": "ACCOUNT_DISABLED",
                            "message": "계정이 비활성화되었습니다. 관리자에게 문의하십시오."},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # ── JWT tenant binding(1차 방어선) ────────────────────────────────
            # 세션 revoke 만으로는 부족하다(SINGLE_SESSION off / revoke 실패 시 기존 토큰이
            # 이전 tenant_id 를 계속 가리킬 수 있음). DB 조회가 **성공**했고(여기 도달) 현재 소속
            # tenant 가 JWT 의 tenant 와 다르면 fail-closed 로 재로그인시킨다. flag(SINGLE_SESSION/
            # APPROVED_SAAS)와 무관. JWT tenant 를 조용히 덮어쓰지 않는다. 마스터는 예외(escape hatch).
            db_tid = info.get("tenant_id")
            if (not is_master_login(login_id)) and tenant_id and db_tid and str(db_tid) != str(tenant_id):
                raise HTTPException(
                    status_code=401,
                    detail={"code": "TENANT_MEMBERSHIP_CHANGED",
                            "message": "계정의 소속 사업장이 변경되었습니다. 다시 로그인해 주세요."},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # PG 가 권한의 source of truth — 강등/승격이 즉시 반영되도록 PG 값으로 덮어쓴다.
            is_admin = bool(info["is_admin"])
            role = str(info["role"] or role)
    except HTTPException:
        raise
    except Exception:
        # PG 조회 실패 시 인증을 막지 않는다(가용성 우선) — 기존 세션검사 정책과 동일.
        pass

    # ── 테넌트 상태 검사 (승인형 SaaS) — flag ON 시 fail-closed ────────────────
    # FEATURE_APPROVED_SAAS on 이면 tenant.service_status 가 'active'/'pending_activation'
    # 인 요청만 허용하고, suspended/terminated/missing/null/no_column/error 는 모두 **차단**한다
    # (보안경계에서 예외 삼킴 없이 fail-closed). 마스터는 예외(운영 복구용 escape hatch).
    # flag OFF 면 이 검사는 전혀 동작하지 않아 기존 동작 100% 유지.
    # (activation 완료 전 계정은 is_active=false 로 이미 차단되므로 pending_activation 허용은 무해.)
    enforce_tenant = False
    if not is_master_login(login_id):
        try:
            from backend.db.feature_flags import approved_saas_enabled
            from backend.db.session import is_configured as _cfg
            enforce_tenant = bool(approved_saas_enabled() and _cfg() and tenant_id)
        except Exception:
            enforce_tenant = False
    if enforce_tenant:
        from backend.services.auth_pg_service import tenant_service_status
        tst = tenant_service_status(tenant_id)  # 예외 없이 상태 문자열 반환(오류도 문자열)
        if tst not in ("active", "pending_activation"):
            _code = "TENANT_SUSPENDED" if tst in ("suspended", "terminated") else "TENANT_UNAVAILABLE"
            raise HTTPException(
                status_code=401,
                detail={"code": _code,
                        "message": "사무소 서비스를 사용할 수 없습니다. 관리자에게 문의하십시오."},
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 마스터 계정은 항상 full admin 으로 취급(서버 강제).
    if is_master_login(login_id):
        is_admin = True
        role = "admin"

    # ── 단일 세션(새 로그인 우선) 강제 — FEATURE_SINGLE_SESSION on 일 때만 ──
    # off면 sid 검사 자체를 건너뛰어 기존 토큰/로그인 동작과 100% 동일.
    try:
        from backend.db.feature_flags import single_session_enabled
        enforce = single_session_enabled()
    except Exception:
        enforce = False
    if enforce:
        sid = payload.get("sid")
        if not sid:
            # 단일세션 도입 전 발급된(sid 없는) 토큰 → 재로그인 필요. (무한루프 방지: 한 번 401 후 프론트가 토큰 제거)
            raise HTTPException(status_code=401,
                                detail={"code": "SESSION_EXPIRED", "message": "세션이 만료되었습니다. 다시 로그인해 주세요."},
                                headers={"WWW-Authenticate": "Bearer"})
        try:
            from backend.services.session_pg_service import session_status
            st = session_status(sid)
        except Exception:
            # 세션 저장소 조회 실패 시 인증을 막지 않는다(가용성 우선) — 기존 동작 유지.
            st = "active"
        if st == "revoked":
            raise HTTPException(status_code=401,
                                detail={"code": "SESSION_REVOKED", "message": "다른 기기에서 로그인되어 로그아웃되었습니다."},
                                headers={"WWW-Authenticate": "Bearer"})
        if st != "active":
            raise HTTPException(status_code=401,
                                detail={"code": "SESSION_EXPIRED", "message": "세션이 만료되었습니다. 다시 로그인해 주세요."},
                                headers={"WWW-Authenticate": "Bearer"})

    office_name  = str(payload.get("office_name", "")).strip()
    contact_name = str(payload.get("contact_name", "")).strip()
    is_master = is_master_login(login_id)
    # 준 관리자: full admin 이 아니면서 role=='sub_admin'.
    is_sub_admin = (not is_admin) and (role == "sub_admin")
    return {
        "login_id":     login_id,
        "tenant_id":    tenant_id,
        "is_admin":     is_admin,
        "role":         role,
        "is_master":    is_master,
        "is_sub_admin": is_sub_admin,
        # 시스템 운영 관리자 여부(마스터 + SYSTEM_ADMIN_LOGIN_IDS). office_admin(is_admin)과 구분.
        "is_system_admin": is_system_admin(login_id),
        "office_name":  office_name,
        "contact_name": contact_name,
        "session_id":   payload.get("sid", ""),
    }


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """full admin(또는 마스터) 전용. 준 관리자(sub_admin)는 통과하지 못한다."""
    if not (current_user.get("is_admin") or current_user.get("is_master")):
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return current_user


def require_admin_or_sub_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """full admin / 마스터 / 준 관리자 허용 — 실무지침 수정·게시판 관리 공통 권한."""
    if not (current_user.get("is_admin") or current_user.get("is_master")
            or current_user.get("is_sub_admin")):
        raise HTTPException(status_code=403, detail="관리자 또는 준 관리자 권한이 필요합니다.")
    return current_user


# 준 관리자에게 허용되는 두 영역의 권한 dependency(의미를 명확히 하기 위한 별칭).
# 둘 다 admin/master/sub_admin 을 허용한다(계정관리·보안설정 등은 require_admin 유지).
require_guideline_editor = require_admin_or_sub_admin
require_board_manager = require_admin_or_sub_admin


def require_system_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """**시스템 운영 관리자 전용** — 승인형 SaaS 의 크로스테넌트/시스템 API 게이트.

    마스터 또는 env(SYSTEM_ADMIN_LOGIN_IDS) 허용목록만 통과한다. 사무소 관리자(office_admin,
    tenant 내 is_admin=true)는 is_admin 이 true 여도 **차단**된다 → 권한상승 방지. 프론트 숨김이
    아니라 서버에서 강제한다.
    """
    if not is_system_admin(current_user.get("login_id", "")):
        raise HTTPException(status_code=403, detail="시스템 관리자 권한이 필요합니다.")
    return current_user


def require_office_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """사무소 관리자(자기 tenant 내부 관리) — 시스템 관리자 또는 tenant 내 full admin.

    tenant 스코프 기능용. 시스템 관리 API 에는 쓰지 않는다(그건 require_system_admin).
    """
    if not (current_user.get("is_admin") or current_user.get("is_master")):
        raise HTTPException(status_code=403, detail="사무소 관리자 권한이 필요합니다.")
    return current_user


def require_admin_or_system(current_user: dict = Depends(get_current_user)) -> dict:
    """레거시 시스템 전체(A급) 관리 API 게이트 — flag 상태에 따라 권한을 전환한다.

    - FEATURE_APPROVED_SAAS ON: **시스템 운영 관리자(require_system_admin)만** 허용.
      office_admin(tenant 내 is_admin)은 403 → 전체 계정목록/계정생성/tenant_id변경/승격/워크스페이스 등
      크로스테넌트 시스템 기능을 우회할 수 없다.
    - FEATURE_APPROVED_SAAS OFF(현행 운영): 기존 require_admin(full admin/master) 동작 그대로 유지 → 회귀 없음.
    프론트 숨김이 아니라 서버에서 강제한다.
    """
    try:
        from backend.db.feature_flags import approved_saas_enabled
        saas_on = approved_saas_enabled()
    except Exception:
        saas_on = False
    if saas_on:
        if not is_system_admin(current_user.get("login_id", "")):
            raise HTTPException(status_code=403, detail="시스템 관리자 권한이 필요합니다.")
        return current_user
    # 레거시: 기존 full admin/master
    if not (current_user.get("is_admin") or current_user.get("is_master")):
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return current_user
