"""전자명함(business card) 라우터.

- GET  /api/my/business-card            (로그인) 내 명함 조회(fallback 적용)
- PATCH /api/my/business-card           (로그인) 내 명함 저장
- GET  /api/public/business-card/{slug} (공개)  공개된 명함만 공개 필드 반환

권한: 항상 JWT 의 tenant_id 기준으로만 조회/수정 → 타 계정 명함 수정 불가.
공개 엔드포인트는 card_is_public=true 인 경우에만 200, 아니면 404.
PG 미구성 시 503.
"""
import io
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.db.session import is_configured

router = APIRouter()

# 로고 업로드 정책 — 서버에서도 반드시 검증(프론트 1차 검증을 신뢰하지 않는다).
_MAX_LOGO_BYTES = 200 * 1024          # 200KB
# Pillow 가 판별한 포맷(authoritative) → 저장 MIME. SVG 등은 애초에 매칭되지 않아 거부.
_ALLOWED_LOGO_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


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


@router.post("/my/business-card/logo")
async def upload_business_card_logo(
    file: UploadFile = File(...), user: dict = Depends(get_current_user)
):
    """로고 파일 업로드(JPG/PNG/WEBP, ≤200KB). PG 에 BYTEA 로 저장."""
    _require_pg()
    from backend.services import business_card_pg_service as svc
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(data) > _MAX_LOGO_BYTES:
        raise HTTPException(status_code=400, detail="로고 파일은 200KB 이하만 업로드할 수 있습니다.")
    # 확장자/Content-Type 만 믿지 않고 실제 이미지 디코딩으로 형식을 판별한다.
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = (im.format or "").upper()
            im.verify()
    except Exception:
        raise HTTPException(status_code=400, detail="이미지 파일을 인식할 수 없습니다. JPG/PNG/WEBP 만 업로드하세요.")
    mime = _ALLOWED_LOGO_FORMATS.get(fmt)
    if not mime:
        raise HTTPException(status_code=400, detail="허용되지 않는 이미지 형식입니다. JPG/PNG/WEBP 만 업로드하세요.")
    try:
        return svc.save_logo(tenant_id, filename=file.filename or "logo", mime=mime, data=data)
    except ValueError:
        raise HTTPException(status_code=404, detail="테넌트를 찾을 수 없습니다.")


@router.get("/my/business-card/logo")
def get_my_business_card_logo(user: dict = Depends(get_current_user)):
    """소유자 본인 로고 이미지(마이페이지 미리보기용). 없으면 404."""
    _require_pg()
    from backend.services import business_card_pg_service as svc
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    res = svc.get_my_logo(tenant_id)
    if res is None:
        raise HTTPException(status_code=404, detail="로고가 없습니다.")
    data, mime = res
    return Response(content=data, media_type=mime, headers={"Cache-Control": "no-store"})


@router.delete("/my/business-card/logo")
def delete_business_card_logo(user: dict = Depends(get_current_user)):
    """업로드 로고만 삭제(명함 텍스트/외부 URL 은 유지)."""
    _require_pg()
    from backend.services import business_card_pg_service as svc
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    try:
        return svc.delete_logo(tenant_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="테넌트를 찾을 수 없습니다.")


@router.get("/public/business-card/{slug}/logo")
def get_public_business_card_logo(slug: str):
    """공개된 명함의 업로드 로고 이미지. 비공개/로고없음 → 404.
    외부 메신저(og:image)·브라우저가 로그인 없이 접근 가능해야 하므로 무인증."""
    _require_pg()
    from backend.services import business_card_pg_service as svc
    res = svc.get_public_logo(slug)
    if res is None:
        raise HTTPException(status_code=404, detail="로고가 없습니다.")
    data, mime = res
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=600"},
    )


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
