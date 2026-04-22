"""홈페이지 마케팅 게시물 라우터
공개 엔드포인트: GET /api/marketing/posts   (인증 불필요, 게시된 글만 반환)
관리자 전용:     /api/marketing/admin/posts  (인증 + is_admin 필요)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uuid
import io
import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional

from backend.auth import get_current_user

# 마케팅 이미지 Google Drive 폴더 ID (모듈 초기화 시 캐시)
_MARKETING_IMG_FOLDER: Optional[str] = None


def _get_drive():
    """Google Drive API 서비스 객체 반환"""
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    import config
    creds = Credentials.from_service_account_file(
        config.KEY_PATH,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _get_or_create_img_folder() -> str:
    """PARENT_DRIVE_FOLDER_ID 하위 'marketing-images' 폴더 ID 반환 (없으면 생성)"""
    global _MARKETING_IMG_FOLDER
    if _MARKETING_IMG_FOLDER:
        return _MARKETING_IMG_FOLDER
    import config
    drive = _get_drive()
    q = (
        f"name='marketing-images' and "
        f"'{config.PARENT_DRIVE_FOLDER_ID}' in parents and "
        f"mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    res = drive.files().list(q=q, fields="files(id)").execute()
    files = res.get("files", [])
    if files:
        _MARKETING_IMG_FOLDER = files[0]["id"]
    else:
        folder = drive.files().create(
            body={
                "name": "marketing-images",
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [config.PARENT_DRIVE_FOLDER_ID],
            },
            fields="id",
        ).execute()
        _MARKETING_IMG_FOLDER = folder["id"]
    return _MARKETING_IMG_FOLDER

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

@router.post("/admin/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """이미지 파일을 Google Drive marketing-images 폴더에 업로드하고 공개 URL 반환"""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="관리자만 접근 가능합니다.")

    allowed_types = {"image/jpeg", "image/png", "image/gif", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다 (jpg/png/gif/webp).")

    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="파일 크기는 5MB 이하여야 합니다.")

    try:
        from googleapiclient.http import MediaIoBaseUpload
        drive = _get_drive()
        folder_id = _get_or_create_img_folder()

        safe_name = file.filename or "image"
        ext = safe_name.rsplit(".", 1)[-1].lower() if "." in safe_name else "jpg"
        fname = f"mkt_{str(uuid.uuid4())[:8]}.{ext}"

        media = MediaIoBaseUpload(io.BytesIO(contents), mimetype=file.content_type)
        uploaded = drive.files().create(
            body={"name": fname, "parents": [folder_id]},
            media_body=media,
            fields="id",
        ).execute()

        file_id = uploaded["id"]
        drive.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        url = f"https://drive.google.com/uc?export=view&id={file_id}"
        return {"url": url, "file_id": file_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"이미지 업로드 실패: {e}")


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
