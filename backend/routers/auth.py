"""인증 라우터 - 로그인 / 회원가입 / 마이페이지"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
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
    """현재 사용자 정보 — JWT 기본 + Accounts 시트 상세 정보."""
    from backend.services.accounts_service import find_account
    login_id = current_user.get("login_id", "")
    acc = find_account(login_id) or {}
    return {
        **current_user,
        "office_adr":   acc.get("office_adr",   ""),
        "contact_tel":  acc.get("contact_tel",  ""),
        "biz_reg_no":   acc.get("biz_reg_no",   ""),
        # 주민등록번호는 뒷 8자리 마스킹
        "agent_rrn":    _mask_rrn(acc.get("agent_rrn", "")),
    }


def _mask_rrn(rrn: str) -> str:
    """주민등록번호 뒷 8자리 마스킹: 880101-1****** → 880101-1******"""
    clean = rrn.replace("-", "")
    if len(clean) < 7:
        return rrn
    return clean[:7] + "*" * (len(clean) - 7)


class MeUpdateRequest(BaseModel):
    office_name:  Optional[str] = None
    office_adr:   Optional[str] = None
    contact_name: Optional[str] = None
    contact_tel:  Optional[str] = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password:     str


@router.patch("/me")
def update_me(body: MeUpdateRequest, current_user: dict = Depends(get_current_user)):
    """사무소 정보 수정."""
    from core.google_sheets import read_data_from_sheet, upsert_rows_by_id
    from backend.services.accounts_service import ACCOUNTS_SCHEMA
    from config import ACCOUNTS_SHEET_NAME

    login_id = current_user.get("login_id", "")
    records = read_data_from_sheet(ACCOUNTS_SHEET_NAME, default_if_empty=[]) or []
    target = next((r for r in records if str(r.get("login_id", "")).strip() == login_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")

    for field, value in body.model_dump(exclude_none=True).items():
        target[field] = value

    header_list = ACCOUNTS_SCHEMA[:]
    for k in target:
        if k not in header_list:
            header_list.append(k)

    ok = upsert_rows_by_id(ACCOUNTS_SHEET_NAME, header_list=header_list, records=[target], id_field="login_id")
    if not ok:
        raise HTTPException(status_code=500, detail="저장 실패")

    # 테넌트 캐시 초기화
    try:
        import backend.services.tenant_service as _ts
        _ts._TENANT_MAP_CACHE = {}
        _ts._TENANT_MAP_TIME = 0
    except Exception:
        pass

    return {"ok": True}


@router.patch("/me/password")
def change_password(body: PasswordChangeRequest, current_user: dict = Depends(get_current_user)):
    """비밀번호 변경."""
    from core.google_sheets import read_data_from_sheet, upsert_rows_by_id
    from backend.services.accounts_service import (
        ACCOUNTS_SCHEMA, verify_password, hash_password,
    )
    from config import ACCOUNTS_SHEET_NAME

    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="새 비밀번호는 6자 이상이어야 합니다.")

    login_id = current_user.get("login_id", "")
    records = read_data_from_sheet(ACCOUNTS_SHEET_NAME, default_if_empty=[]) or []
    target = next((r for r in records if str(r.get("login_id", "")).strip() == login_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")

    if not verify_password(body.current_password, str(target.get("password_hash", ""))):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 올바르지 않습니다.")

    target["password_hash"] = hash_password(body.new_password)

    header_list = ACCOUNTS_SCHEMA[:]
    for k in target:
        if k not in header_list:
            header_list.append(k)

    ok = upsert_rows_by_id(ACCOUNTS_SHEET_NAME, header_list=header_list, records=[target], id_field="login_id")
    if not ok:
        raise HTTPException(status_code=500, detail="비밀번호 변경 실패")

    return {"ok": True}
