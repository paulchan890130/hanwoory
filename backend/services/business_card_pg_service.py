"""전자명함(business card) PG 서비스 — tenants 의 card_* 컬럼(migration 0015) 기반.

- 로그인 사용자: 자기 tenant 명함 조회/수정.
- 공개: card_is_public=true 인 명함만, **공개 필드만** 반환(내부 tenant_id/login_id/role/
  sheet key/secret 등은 절대 반환하지 않는다).
- fallback(테넌트 자체 정보만): phone←contact_tel, address←office_adr.
  ※ SaaS — 로고/업무분야에 한우리 등 특정 사무소 기본값을 넣지 않는다.
    로고는 입력한 URL 이 있을 때만, 업무분야는 입력한 값만 노출(없으면 빈 값).
"""
from __future__ import annotations

import re
from typing import Optional

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$")


class SlugTakenError(Exception):
    """다른 계정이 이미 사용 중인 공개 slug."""


class SlugFormatError(Exception):
    """slug 형식 오류(소문자/숫자/하이픈, 3~50자)."""


def _clean_work_fields(raw) -> list[str]:
    if not isinstance(raw, list):
        return []
    out = [str(x).strip() for x in raw if str(x or "").strip()]
    return out[:12]  # 과도한 개수 방지


def _effective(tenant, *, contact_tel: str = "", contact_name: str = "") -> dict:
    """저장값 + (테넌트 자체) fallback 을 적용한 표시용 dict.
    로고/업무분야는 입력값만 사용(특정 사무소 기본값 없음)."""
    has_logo = bool(tenant.card_logo_bytes) and bool(tenant.card_logo_mime)
    updated = getattr(tenant, "card_logo_updated_at", None)
    return {
        "office_name": tenant.office_name or "",
        "contact_name": (contact_name or "").strip(),
        "phone": (tenant.card_phone or "").strip() or (contact_tel or "").strip(),
        "address": (tenant.card_address or "").strip() or (tenant.office_adr or "").strip(),
        "bio": (tenant.card_bio or "").strip(),
        "work_fields": _clean_work_fields(tenant.card_work_fields),   # 입력값만, 없으면 []
        "logo_url": (tenant.card_logo_url or "").strip(),             # 입력 URL 있을 때만(하위호환)
        "has_logo": has_logo,                                          # 업로드 로고 존재(우선)
        "logo_updated_at": updated.isoformat() if updated else "",     # 캐시버스트 ?v= 용
        "public_slug": (tenant.card_public_slug or "").strip(),
        "is_public": bool(tenant.card_is_public),
    }


def get_my_card(tenant_id: str, contact_tel: str = "", contact_name: str = "") -> Optional[dict]:
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        if t is None:
            return None
        eff = _effective(t, contact_tel=contact_tel, contact_name=contact_name)
        # 편집 화면이 원본 저장값과 fallback 을 구분할 수 있도록 raw 도 함께 제공.
        eff["raw"] = {
            "card_phone": t.card_phone or "",
            "card_address": t.card_address or "",
            "card_logo_url": t.card_logo_url or "",
            "card_work_fields": _clean_work_fields(t.card_work_fields),
        }
        return eff


def update_my_card(tenant_id: str, *, phone=None, address=None, bio=None,
                   work_fields=None, logo_url=None, public_slug=None,
                   is_public=None) -> dict:
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker

    slug = None
    if public_slug is not None:
        slug = (public_slug or "").strip().lower()
        if slug and not _SLUG_RE.match(slug):
            raise SlugFormatError()

    with get_sessionmaker()() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        if t is None:
            raise ValueError("tenant not found")
        if slug:
            dup = session.scalar(
                select(Tenant).where(Tenant.card_public_slug == slug,
                                     Tenant.tenant_id != tenant_id))
            if dup is not None:
                raise SlugTakenError()
        if phone is not None:
            t.card_phone = phone.strip() or None
        if address is not None:
            t.card_address = address.strip() or None
        if bio is not None:
            t.card_bio = bio.strip() or None
        if work_fields is not None:
            cleaned = _clean_work_fields(work_fields)
            t.card_work_fields = cleaned or None
        if logo_url is not None:
            t.card_logo_url = logo_url.strip() or None
        if public_slug is not None:
            t.card_public_slug = slug or None
        if is_public is not None:
            t.card_is_public = bool(is_public)
        # 공개로 켜는데 slug 가 없으면 공개 불가(공개 URL 이 성립하지 않음).
        if t.card_is_public and not (t.card_public_slug or ""):
            raise SlugFormatError()
        session.commit()
        # get_my_card 와 동일한 형태로 반환 — 프론트 편집칸이 raw 로 채워지므로
        # raw 가 빠지면 저장 직후 work_fields/phone/address/logo_url 입력이 사라진다.
        eff = _effective(t, contact_tel="")
        eff["raw"] = {
            "card_phone": t.card_phone or "",
            "card_address": t.card_address or "",
            "card_logo_url": t.card_logo_url or "",
            "card_work_fields": _clean_work_fields(t.card_work_fields),
        }
        return eff


def get_public_card(slug: str) -> Optional[dict]:
    """공개(card_is_public=true) 명함만 공개 필드로 반환. 아니면 None.
    내부 식별자/권한/시트키/secret 은 절대 포함하지 않는다."""
    s = (slug or "").strip().lower()
    if not s:
        return None
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        t = session.scalar(select(Tenant).where(Tenant.card_public_slug == s))
        if t is None or not bool(t.card_is_public):
            return None
        # 행정사 이름/전화 fallback 은 해당 테넌트의 사용자(contact_*)에서 — 관리자 우선, 없으면 첫 사용자.
        u = session.scalar(
            select(AccountUser).where(AccountUser.tenant_id == t.tenant_id)
            .order_by(AccountUser.is_admin.desc(), AccountUser.login_id)
        )
        eff = _effective(
            t,
            contact_tel=(u.contact_tel if u else "") or "",
            contact_name=(u.contact_name if u else "") or "",
        )
        # 공개 필드만 반환 — 내부 식별자/권한/시트키/secret 절대 미포함.
        return {
            "office_name": eff["office_name"],
            "contact_name": eff["contact_name"],
            "phone": eff["phone"],
            "address": eff["address"],
            "bio": eff["bio"],
            "work_fields": eff["work_fields"],
            "logo_url": eff["logo_url"],
            "has_logo": eff["has_logo"],
            "logo_updated_at": eff["logo_updated_at"],
            "public_slug": eff["public_slug"],
        }


def save_logo(tenant_id: str, *, filename: str, mime: str, data: bytes) -> dict:
    """업로드 로고를 tenants 에 저장. 검증(형식/용량/실제 이미지)은 라우터에서 끝낸 뒤 호출.
    반환: 저장 결과 메타(has_logo/mime/size/updated_at)."""
    from sqlalchemy import func, select
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        if t is None:
            raise ValueError("tenant not found")
        t.card_logo_filename = (filename or "").strip()[:200] or None
        t.card_logo_mime = mime
        t.card_logo_size = len(data)
        t.card_logo_bytes = data
        t.card_logo_updated_at = func.now()
        session.commit()
        session.refresh(t)
        updated = t.card_logo_updated_at
        return {
            "has_logo": True,
            "mime": t.card_logo_mime or "",
            "size": int(t.card_logo_size or 0),
            "logo_updated_at": updated.isoformat() if updated else "",
        }


def delete_logo(tenant_id: str) -> dict:
    """업로드 로고만 제거(외부 card_logo_url / 명함 텍스트는 그대로)."""
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        if t is None:
            raise ValueError("tenant not found")
        t.card_logo_filename = None
        t.card_logo_mime = None
        t.card_logo_size = None
        t.card_logo_bytes = None
        t.card_logo_updated_at = None
        session.commit()
        return {"has_logo": False}


def get_my_logo(tenant_id: str) -> Optional[tuple[bytes, str]]:
    """소유자 본인 명함의 업로드 로고 (bytes, mime). 없으면 None.
    공개 여부와 무관(마이페이지 미리보기용, 인증 라우터에서만 호출)."""
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        if t is None or not t.card_logo_bytes or not t.card_logo_mime:
            return None
        return bytes(t.card_logo_bytes), str(t.card_logo_mime)


def get_public_logo(slug: str) -> Optional[tuple[bytes, str]]:
    """공개(card_is_public=true) 명함의 업로드 로고만 (bytes, mime) 로 반환.
    비공개/로고없음/slug 없음 → None."""
    s = (slug or "").strip().lower()
    if not s:
        return None
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        t = session.scalar(select(Tenant).where(Tenant.card_public_slug == s))
        if t is None or not bool(t.card_is_public):
            return None
        if not t.card_logo_bytes or not t.card_logo_mime:
            return None
        return bytes(t.card_logo_bytes), str(t.card_logo_mime)


def list_public_slugs() -> list[str]:
    """sitemap 용 — 공개된 명함 slug 목록."""
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        rows = session.scalars(
            select(Tenant.card_public_slug).where(
                Tenant.card_is_public.is_(True),
                Tenant.card_public_slug.isnot(None))
        ).all()
    return [r for r in rows if r]
