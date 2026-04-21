"""홈페이지 마케팅 게시물 라우터
공개 엔드포인트: GET /api/marketing/posts   (인증 불필요, 게시된 글만 반환)
관리자 전용:     /api/marketing/admin/posts  (인증 + is_admin 필요)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from backend.auth import get_current_user

router = APIRouter()

MARKETING_HEADER = [
    "id", "title", "slug", "category", "summary", "content",
    "thumbnail_url", "is_published", "is_featured",
    "created_by", "created_at", "updated_at",
]


def _sheet_name():
    from config import MARKETING_POSTS_SHEET_NAME
    return MARKETING_POSTS_SHEET_NAME


def _read_posts():
    from core.google_sheets import read_data_from_sheet
    return read_data_from_sheet(_sheet_name(), default_if_empty=[]) or []


def _upsert(rows):
    from core.google_sheets import upsert_rows_by_id
    upsert_rows_by_id(_sheet_name(), MARKETING_HEADER, rows, id_field="id")


def _delete(ids):
    from core.google_sheets import delete_rows_by_ids
    delete_rows_by_ids(_sheet_name(), ids, id_field="id")


class PostCreate(BaseModel):
    title: str
    slug: str = ""
    category: str = ""
    summary: str = ""
    content: str = ""
    thumbnail_url: str = ""
    is_featured: bool = False


class PostUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    category: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[str] = None
    thumbnail_url: Optional[str] = None
    is_featured: Optional[bool] = None
    is_published: Optional[bool] = None


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

@router.get("/admin/posts")
def admin_list_posts(user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다.")
    posts = _read_posts()
    posts.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return posts


@router.post("/admin/posts")
def create_post(body: PostCreate, user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다.")
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
    }
    _upsert([post])
    return post


@router.put("/admin/posts/{post_id}")
def update_post(post_id: str, body: PostUpdate, user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다.")
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
def delete_post(post_id: str, user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다.")
    _delete([post_id])
    return {"ok": True}


@router.patch("/admin/posts/{post_id}/publish")
def toggle_publish(post_id: str, user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다.")
    posts = _read_posts()
    existing = next((p for p in posts if p.get("id") == post_id), None)
    if not existing:
        raise HTTPException(status_code=404, detail="게시물을 찾을 수 없습니다.")
    currently_published = str(existing.get("is_published", "")).upper() in ("TRUE", "Y", "1")
    existing["is_published"] = "FALSE" if currently_published else "TRUE"
    existing["updated_at"] = datetime.datetime.now().isoformat()
    _upsert([existing])
    return existing
