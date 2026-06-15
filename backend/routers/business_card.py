"""전자명함(business card) 라우터.

- GET  /api/my/business-card            (로그인) 내 명함 조회(fallback 적용)
- PATCH /api/my/business-card           (로그인) 내 명함 저장
- GET  /api/public/business-card/{slug} (공개)  공개된 명함만 공개 필드 반환

권한: 항상 JWT 의 tenant_id 기준으로만 조회/수정 → 타 계정 명함 수정 불가.
공개 엔드포인트는 card_is_public=true 인 경우에만 200, 아니면 404.
PG 미구성 시 503.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.db.session import is_configured

router = APIRouter()


class BusinessCardUpdate(BaseModel):
    phone: Optional[str] = None
    address: Optional[str] = None
    bio: Optional[str] = None
    work_fields: Optional[list[str]] = None
    logo_url: Optional[str] = None
    public_slug: Optional[str] = None
    is_public: Optional[bool] = None


def _require_pg():
    if not is_configured():
        raise HTTPException(status_code=503, detail="저장소(PostgreSQL)가 구성되지 않았습니다.")


@router.get("/my/business-card")
def get_my_business_card(user: dict = Depends(get_current_user)):
    _require_pg()
    from backend.services import business_card_pg_service as svc
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    # 연락처/행정사 이름 fallback 은 users.contact_* — accounts_service 로 안전 조회.
    contact_tel = ""
    contact_name = ""
    try:
        from backend.services.accounts_service import find_account
        acc = find_account(user.get("login_id") or user.get("sub", "")) or {}
        contact_tel = str(acc.get("contact_tel", "") or "")
        contact_name = str(acc.get("contact_name", "") or "")
    except Exception:
        pass
    card = svc.get_my_card(tenant_id, contact_tel=contact_tel, contact_name=contact_name)
    if card is None:
        raise HTTPException(status_code=404, detail="테넌트를 찾을 수 없습니다.")
    return card


@router.patch("/my/business-card")
def update_my_business_card(body: BusinessCardUpdate, user: dict = Depends(get_current_user)):
    _require_pg()
    from backend.services import business_card_pg_service as svc
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    try:
        return svc.update_my_card(
            tenant_id,
            phone=body.phone, address=body.address, bio=body.bio,
            work_fields=body.work_fields, logo_url=body.logo_url,
            public_slug=body.public_slug, is_public=body.is_public,
        )
    except svc.SlugTakenError:
        raise HTTPException(status_code=409, detail="이미 사용 중인 공개 주소(slug)입니다. 다른 값을 입력하세요.")
    except svc.SlugFormatError:
        raise HTTPException(status_code=400, detail="공개 주소(slug)는 영문 소문자·숫자·하이픈 3~50자여야 하며, 공개하려면 slug 가 필요합니다.")
    except ValueError:
        raise HTTPException(status_code=404, detail="테넌트를 찾을 수 없습니다.")


@router.get("/public/business-card/{slug}")
def get_public_business_card(slug: str):
    _require_pg()
    from backend.services import business_card_pg_service as svc
    card = svc.get_public_card(slug)
    if card is None:
        raise HTTPException(status_code=404, detail="공개된 전자명함이 없습니다.")
    return card


@router.get("/public/business-cards")
def list_public_business_cards():
    """sitemap 용 — 공개된 전자명함 slug 목록(공개 정보 외 노출 없음). PG 미구성 시 빈 목록."""
    if not is_configured():
        return {"slugs": []}
    from backend.services import business_card_pg_service as svc
    try:
        return {"slugs": svc.list_public_slugs()}
    except Exception:
        return {"slugs": []}
