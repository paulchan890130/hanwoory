"""인증 라우터 - 로그인 / 회원가입"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, HTTPException, Depends
from backend.models import LoginRequest, SignupRequest, TokenResponse
from backend.auth import create_access_token, get_current_user

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
def login(req: LoginRequest):
    acc = _find_account(req.login_id)
    if not acc:
        raise HTTPException(status_code=401, detail="계정이 존재하지 않습니다.")

    is_active = str(acc.get("is_active", "")).strip().lower() in ("true", "1", "y")
    if not is_active:
        raise HTTPException(status_code=403, detail="관리자 승인 전이거나 비활성화된 계정입니다.")

    hashed = str(acc.get("password_hash", "")).strip()
    if not hashed or not _verify_password(req.password, hashed):
        raise HTTPException(status_code=401, detail="ID 또는 비밀번호가 올바르지 않습니다.")

    is_admin  = str(acc.get("is_admin", "")).strip().lower() in ("true", "1", "y")
    tenant_id = str(acc.get("tenant_id", "")).strip() or req.login_id
    office_name = str(acc.get("office_name", "")).strip()
    contact_name = str(acc.get("contact_name", "")).strip()

    token = create_access_token({
        "sub":         req.login_id,
        "tenant_id":   tenant_id,
        "is_admin":    is_admin,
        "office_name": office_name,
        "contact_name": contact_name,
    })
    return TokenResponse(
        access_token=token,
        login_id=req.login_id,
        tenant_id=tenant_id,
        is_admin=is_admin,
        office_name=office_name,
        contact_name=contact_name,
    )


# ─────────────────────────────────────────────────────────────────────────────
# /signup
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/signup")
def signup(req: SignupRequest):
    if req.password != req.confirm_password:
        raise HTTPException(status_code=400, detail="비밀번호 확인이 일치하지 않습니다.")
    if not req.login_id.strip():
        raise HTTPException(status_code=400, detail="로그인 ID를 입력해주세요.")
    if not req.office_name.strip():
        raise HTTPException(status_code=400, detail="사무실 이름을 입력해주세요.")

    # 중복 체크 (accounts_service 경유 → 서비스 계정 사용)
    existing = _find_account(req.login_id.strip())
    if existing:
        raise HTTPException(status_code=409, detail="동일한 ID가 존재합니다. 다른 ID로 가입신청해 주십시오.")

    # 16컬럼 dict 생성 후 append
    account = build_account_dict(
        login_id=req.login_id,
        password_hash=_hash_password(req.password),
        office_name=req.office_name,
        office_adr=req.office_adr or "",
        contact_name=req.contact_name or "",
        contact_tel=req.contact_tel or "",
        biz_reg_no=req.biz_reg_no or "",
        agent_rrn=req.agent_rrn or "",
        is_admin=False,
        is_active=False,   # 가입신청 → 관리자 승인 필요
    )

    try:
        append_account(account)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"계정 생성에 실패했습니다: {e}")

    return {"message": "가입신청이 완료되었습니다. 관리자 승인 후 로그인 가능합니다."}


# ─────────────────────────────────────────────────────────────────────────────
# /me
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/me")
def get_me(current_user: dict = Depends(get_current_user)):
    """현재 사용자 정보 (프론트에서 토큰 검증용)"""
    return current_user
