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
    office_name  = str(payload.get("office_name", "")).strip()
    contact_name = str(payload.get("contact_name", "")).strip()
    return {
        "login_id":     login_id,
        "tenant_id":    tenant_id,
        "is_admin":     is_admin,
        "office_name":  office_name,
        "contact_name": contact_name,
    }


def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
    return current_user
