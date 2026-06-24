"""홈페이지 마케팅 게시물 라우터
공개 엔드포인트: GET /api/marketing/posts   (인증 불필요, 게시된 글만 반환)
관리자 전용:     /api/marketing/admin/posts  (인증 + is_admin 필요)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uuid
import io
import re
import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from pydantic import BaseModel
from typing import Optional

from backend.auth import get_current_user, require_board_manager

# 마케팅 이미지는 PostgreSQL(marketing_images, BYTEA)에 저장한다(Google Drive 미사용, migration 0022).
# 업로드 응답 url = 내부 URL(/api/marketing/images/{id}), 공개 서빙은 GET /images/{id}(무인증).

router = APIRouter()

MARKETING_HEADER = [
    "id", "title", "slug", "category", "summary", "content",
    "thumbnail_url", "is_published", "is_featured",
    "created_by", "created_at", "updated_at",
    "image_file_id", "image_url", "image_alt",
    "meta_description", "tags",
]


def _sheet_name():
    from config import MARKETING_POSTS_SHEET_NAME
    return MARKETING_POSTS_SHEET_NAME


# PG-only(Phase H): 마케팅 글 metadata 는 marketing_pg_service.
# (이미지 파일은 Google Drive 외부 리소스 — upload_image 별도, DB 데이터와 분리.)
def _read_posts():
    from backend.services.marketing_pg_service import list_admin
    return list_admin()


def _upsert(rows):
    from backend.services.marketing_pg_service import upsert_post
    for r in rows:
        upsert_post(r)


def _delete(ids):
    from backend.services.marketing_pg_service import delete_post
    for i in ids:
        delete_post(i)


class PostCreate(BaseModel):
    title: str
    slug: str = ""
    category: str = ""
    summary: str = ""
    content: str = ""
    thumbnail_url: str = ""
    is_featured: bool = False
    image_file_id: str = ""
    image_url: str = ""
    image_alt: str = ""
    meta_description: str = ""
    tags: str = ""


class PostUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    category: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    thumbnail_url: Optional[str] = None
    is_featured: Optional[bool] = None
    is_published: Optional[bool] = None
    image_file_id: Optional[str] = None
    image_url: Optional[str] = None
    image_alt: Optional[str] = None
    meta_description: Optional[str] = None
    tags: Optional[str] = None


# ── 공개 엔드포인트 (인증 불필요) ─────────────────────────────────────────────

@router.get("/posts")
def public_list_posts():
    """게시된 홈페이지 게시물 반환 (공개)"""
    posts = _read_posts()
    published = [
        p for p in posts
        if str(p.get("is_published", "")).upper() in ("TRUE", "Y", "1")
    ]
    published.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return published


@router.get("/posts/{post_id}")
def public_get_post(post_id: str):
    """ID 또는 slug로 단건 공개 게시물 반환 (공개, is_published=TRUE만)"""
    posts = _read_posts()
    is_pub = lambda p: str(p.get("is_published", "")).upper() in ("TRUE", "Y", "1")
    post = next((p for p in posts if p.get("slug") == post_id and is_pub(p)), None)
    if not post:
        post = next((p for p in posts if p.get("id") == post_id and is_pub(p)), None)
    if not post:
        raise HTTPException(status_code=404, detail="게시물을 찾을 수 없습니다.")
    return post


# ── 관리자 전용 엔드포인트 ─────────────────────────────────────────────────────

# 업로드 허용 형식(서버가 Pillow 로 디코딩해 실제 판별 — 확장자/Content-Type 불신).
_IMG_FMT_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_IMG_MAX_BYTES = 3 * 1024 * 1024  # 3MB


@router.post("/admin/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    user: dict = Depends(require_board_manager),
):
    """이미지를 PostgreSQL(marketing_images, BYTEA)에 저장하고 내부 URL 반환. (Google Drive 미사용)

    신규 이미지는 image_url(내부 URL)만 사용한다 — image_file_id(레거시 Drive id)에는 넣지 않는다.
    """

    contents = await file.read()
    if len(contents) > _IMG_MAX_BYTES:
        raise HTTPException(status_code=400, detail="이미지 파일은 3MB 이하만 업로드할 수 있습니다.")

    # 실제 이미지인지 Pillow 로 디코딩 검증 + 형식 판별(JPG/PNG/WEBP 만 — GIF/SVG/기타 거절).
    try:
        from PIL import Image
        probe = Image.open(io.BytesIO(contents))
        fmt = (probe.format or "").upper()
        probe.verify()
    except Exception:
        raise HTTPException(status_code=415, detail="유효한 이미지 파일이 아닙니다 (JPG/PNG/WEBP).")
    if fmt not in _IMG_FMT_MIME:
        raise HTTPException(status_code=415, detail="JPG / PNG / WEBP 형식만 업로드할 수 있습니다. (GIF/SVG 등 미지원)")

    content_type = _IMG_FMT_MIME[fmt]
    from backend.services import marketing_image_pg_service as _img
    try:
        meta = _img.save_image(
            tenant_id=user.get("tenant_id", ""),
            created_by=user.get("login_id", ""),
            filename=file.filename or "image",
            content_type=content_type,
            data=contents,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"이미지 저장 실패: {e}")
    return {
        "url": f"/api/marketing/images/{meta['id']}",
        "id": meta["id"],
        "content_type": meta["content_type"],
        "size_bytes": meta["size_bytes"],
    }


@router.get("/images/{image_id}")
def get_marketing_image(image_id: str):
    """공개 마케팅 이미지 서빙(무인증) — 공개 게시판 표시용. 없음/삭제 → 404."""
    from backend.services import marketing_image_pg_service as _img
    res = _img.get_image(image_id)
    if res is None:
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
    data, mime = res
    return Response(content=data, media_type=mime, headers={"Cache-Control": "public, max-age=600"})


@router.get("/admin/posts")
def admin_list_posts(user: dict = Depends(require_board_manager)):
    posts = _read_posts()
    posts.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return posts


@router.post("/admin/posts")
def create_post(body: PostCreate, user: dict = Depends(require_board_manager)):
    now = datetime.datetime.now().isoformat()
    post = {
        "id": str(uuid.uuid4()),
        "title": body.title,
        "slug": body.slug or body.title,
        "category": body.category,
        "summary": body.summary,
        "content": body.content,
        "thumbnail_url": body.thumbnail_url,
        "is_published": "FALSE",
        "is_featured": "TRUE" if body.is_featured else "FALSE",
        "created_by": user.get("login_id", ""),
        "created_at": now,
        "updated_at": now,
        "image_file_id": body.image_file_id,
        "image_url": body.image_url,
        "image_alt": body.image_alt,
        "meta_description": body.meta_description,
        "tags": body.tags,
    }
    _upsert([post])
    return post


@router.put("/admin/posts/{post_id}")
def update_post(post_id: str, body: PostUpdate, user: dict = Depends(require_board_manager)):
    posts = _read_posts()
    existing = next((p for p in posts if p.get("id") == post_id), None)
    if not existing:
        raise HTTPException(status_code=404, detail="게시물을 찾을 수 없습니다.")
    updates = body.model_dump(exclude_unset=True)
    if "is_published" in updates:
        updates["is_published"] = "TRUE" if updates["is_published"] else "FALSE"
    if "is_featured" in updates:
        updates["is_featured"] = "TRUE" if updates["is_featured"] else "FALSE"
    merged = {**existing}
    for k, v in updates.items():
        merged[k] = str(v) if v is not None else ""
    merged["updated_at"] = datetime.datetime.now().isoformat()
    _upsert([merged])
    return merged


@router.delete("/admin/posts/{post_id}")
def delete_post(post_id: str, user: dict = Depends(require_board_manager)):
    _delete([post_id])
    return {"ok": True}


@router.patch("/admin/posts/{post_id}/publish")
def toggle_publish(post_id: str, user: dict = Depends(require_board_manager)):
    posts = _read_posts()
    existing = next((p for p in posts if p.get("id") == post_id), None)
    if not existing:
        raise HTTPException(status_code=404, detail="게시물을 찾을 수 없습니다.")
    currently_published = str(existing.get("is_published", "")).upper() in ("TRUE", "Y", "1")
    existing["is_published"] = "FALSE" if currently_published else "TRUE"
    existing["updated_at"] = datetime.datetime.now().isoformat()
    _upsert([existing])
    return existing


# ── 업무별 준비서류 중분류 (document_groups) ──────────────────────────────────
# 글↔중분류 연결은 marketing_posts.tags 의 doc_group:<group_key> 태그를 사용한다(A안).
# v1 정책: 물리 삭제 없음 — 공개/비공개 전환만 제공(DELETE 엔드포인트 없음).

# group_key 는 [a-z0-9-] 만 — 콤마 구분 태그에서 안전하게 캡처(\S+ 의 콤마-탐욕 방지).
_DOC_GROUP_TAG_RE = re.compile(r"doc_group:([a-z0-9][a-z0-9-]*)")


def _post_group_key(post: dict) -> str:
    """게시물 tags 에서 doc_group:<key> 추출(소문자 정규화). 없으면 ''."""
    m = _DOC_GROUP_TAG_RE.search(str(post.get("tags") or ""))
    return m.group(1).strip().lower() if m else ""


def _group_post_counts() -> dict:
    """group_key → {'total': n, 'published': n} (관리자 화면 하위 글 개수)."""
    counts: dict = {}
    for p in _read_posts():
        key = _post_group_key(p)
        if not key:
            continue
        c = counts.setdefault(key, {"total": 0, "published": 0})
        c["total"] += 1
        if str(p.get("is_published", "")).upper() in ("TRUE", "Y", "1"):
            c["published"] += 1
    return counts


class DocGroupCreate(BaseModel):
    group_key: str
    title: str = ""
    description: str = ""
    sort_order: Optional[int] = None
    is_published: bool = True


class DocGroupUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


# 공개: 게시된 중분류만, sort_order 순.
@router.get("/doc-groups")
def public_list_doc_groups():
    from backend.services import document_group_pg_service as svc
    return svc.list_groups(published_only=True)


@router.get("/admin/doc-groups")
def admin_list_doc_groups(user: dict = Depends(require_board_manager)):
    """전체 중분류(비공개 포함) + 하위 글 개수."""
    from backend.services import document_group_pg_service as svc
    groups = svc.list_groups(published_only=False)
    counts = _group_post_counts()
    for g in groups:
        c = counts.get(g.get("group_key", ""), {"total": 0, "published": 0})
        g["post_count"] = c["total"]
        g["published_post_count"] = c["published"]
    return groups


@router.post("/admin/doc-groups")
def create_doc_group(body: DocGroupCreate, user: dict = Depends(require_board_manager)):
    from backend.services import document_group_pg_service as svc
    try:
        return svc.create_group(
            group_key=body.group_key,
            title=body.title,
            description=body.description,
            sort_order=body.sort_order,
            is_published=body.is_published,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/admin/doc-groups/{group_id}")
def update_doc_group(
    group_id: str, body: DocGroupUpdate, user: dict = Depends(require_board_manager)
):
    from backend.services import document_group_pg_service as svc
    updated = svc.update_group(
        group_id,
        title=body.title,
        description=body.description,
        sort_order=body.sort_order,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="중분류를 찾을 수 없습니다.")
    return updated


@router.patch("/admin/doc-groups/{group_id}/publish")
def toggle_doc_group_publish(group_id: str, user: dict = Depends(require_board_manager)):
    from backend.services import document_group_pg_service as svc
    updated = svc.toggle_published(group_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="중분류를 찾을 수 없습니다.")
    return updated
