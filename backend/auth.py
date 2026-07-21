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
            # PG 가 권한의 source of truth — 강등/승격이 즉시 반영되도록 PG 값으로 덮어쓴다.
            is_admin = bool(info["is_admin"])
            role = str(info["role"] or role)
    except HTTPException:
        raise
    except Exception:
        # PG 조회 실패 시 인증을 막지 않는다(가용성 우선) — 기존 세션검사 정책과 동일.
        pass

    # ── 테넌트 정지/종료 즉시 차단 (승인형 SaaS) ──────────────────────────────
    # FEATURE_APPROVED_SAAS on 이고 tenant.service_status 가 suspended/terminated 면
    # 해당 tenant 전체 사용자를 차단한다. 마스터는 예외(운영 복구용). 컬럼 미적용/조회
    # 실패는 fail-open(기존 동작 유지). 이 검사는 flag off 면 전혀 동작하지 않는다.
    if not is_master_login(login_id):
        try:
            from backend.db.feature_flags import approved_saas_enabled
            from backend.db.session import is_configured as _cfg
            if approved_saas_enabled() and _cfg() and tenant_id:
                from backend.services.auth_pg_service import tenant_service_status
                tst = tenant_service_status(tenant_id)
                if tst in ("suspended", "terminated"):
                    raise HTTPException(
                        status_code=401,
                        detail={"code": "TENANT_SUSPENDED",
                                "message": "사무소 서비스가 정지되었습니다. 관리자에게 문의하십시오."},
                        headers={"WWW-Authenticate": "Bearer"},
                    )
        except HTTPException:
            raise
        except Exception:
            pass

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
