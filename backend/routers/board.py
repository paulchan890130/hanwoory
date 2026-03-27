"""게시판 라우터 - 기존 Streamlit page_board.py 구조 복원
헤더: id, tenant_id, author_login, office_name, is_notice, category, title, content, created_at, updated_at
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uuid
import datetime
from fastapi import APIRouter, Depends, HTTPException

from backend.auth import get_current_user
from backend.models import BoardPost, BoardComment

router = APIRouter()

# 기존 Streamlit page_board.py BOARD_HEADERS와 동일
POST_HEADER = [
    "id", "tenant_id", "author_login", "office_name",
    "is_notice", "category", "title", "content",
    "created_at", "updated_at",
]
COMMENT_HEADER = [
    "id", "post_id", "tenant_id", "author_login", "office_name",
    "content", "created_at", "updated_at",
]


def _read():
    from core.google_sheets import read_data_from_sheet
    return read_data_from_sheet

def _write():
    from core.google_sheets import upsert_rows_by_id, delete_rows_by_ids
    return upsert_rows_by_id, delete_rows_by_ids

def _sheet():
    from config import BOARD_SHEET_NAME, BOARD_COMMENT_SHEET_NAME
    return BOARD_SHEET_NAME, BOARD_COMMENT_SHEET_NAME


@router.get("")
def get_posts(user: dict = Depends(get_current_user)):
    """게시판 목록 - 공지 상단, 나머지 최신순 (댓글 수 포함)"""
    read = _read()
    BOARD, COMMENT = _sheet()
    posts = read(BOARD, default_if_empty=[]) or []
    comments = read(COMMENT, default_if_empty=[]) or []
    # 게시글별 댓글 수 집계
    from collections import Counter
    comment_counts = Counter(c.get("post_id") for c in comments if c.get("post_id"))
    for p in posts:
        p["comment_count"] = comment_counts.get(p.get("id", ""), 0)
    # 공지 먼저, 나머지는 최신순
    notices = [p for p in posts if str(p.get("is_notice", "")).strip().upper() == "Y"]
    normal  = [p for p in posts if str(p.get("is_notice", "")).strip().upper() != "Y"]
    notices.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    normal.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return notices + normal


@router.post("", response_model=dict)
def create_post(post: BoardPost, user: dict = Depends(get_current_user)):
    import traceback as _tb
    upsert, _ = _write()
    BOARD, _ = _sheet()
    now = datetime.datetime.now().isoformat()
    post.id          = str(uuid.uuid4())
    post.tenant_id   = user.get("tenant_id", "")
    post.author_login= user.get("login_id", "")
    post.author      = user.get("login_id", "")  # 하위호환
    post.office_name = user.get("office_name", "")
    post.created_at  = now
    post.updated_at  = now
    # 관리자가 아닌 경우 is_notice 강제 해제
    if not user.get("is_admin", False):
        post.is_notice = ""
    rec = {k: ("" if v is None else str(v)) for k, v in post.model_dump().items()}
    try:
        result = upsert(BOARD, header_list=POST_HEADER, records=[rec], id_field="id")
        if not result:
            raise HTTPException(status_code=500, detail="upsert returned False — check server log")
    except HTTPException:
        raise
    except Exception as _e:
        raise HTTPException(status_code=500, detail=f"upsert error: {_tb.format_exc()}")
    return rec


@router.put("/{post_id}", response_model=dict)
def update_post(post_id: str, post: BoardPost, user: dict = Depends(get_current_user)):
    upsert, _ = _write()
    BOARD, _ = _sheet()
    # 기존 글 조회해서 작성자 확인 + 서버 필드 보존
    read = _read()
    posts = read(BOARD, default_if_empty=[]) or []
    existing = next((p for p in posts if p.get("id") == post_id), None)
    if not existing:
        raise HTTPException(status_code=404, detail="게시글을 찾을 수 없습니다.")
    is_own = existing.get("author_login") == user.get("login_id")
    if not (is_own or user.get("is_admin", False)):
        raise HTTPException(status_code=403, detail="수정 권한 없음")
    # Partial update: start from existing row, only override user-editable fields
    rec = {k: str(existing.get(k, "")) for k in POST_HEADER}
    for f in ("title", "content", "category"):
        val = getattr(post, f, None)
        if val is not None:
            rec[f] = str(val)
    rec["id"]         = post_id
    rec["updated_at"] = datetime.datetime.now().isoformat()
    if not user.get("is_admin", False):
        rec["is_notice"] = ""
    elif post.is_notice is not None:
        rec["is_notice"] = str(post.is_notice)
    upsert(BOARD, header_list=POST_HEADER, records=[rec], id_field="id")
    return rec


@router.delete("/{post_id}")
def delete_post(post_id: str, user: dict = Depends(get_current_user)):
    _, delete = _write()
    BOARD, COMMENT = _sheet()
    # 작성자 또는 관리자만 삭제 가능
    read = _read()
    posts = read(BOARD, default_if_empty=[]) or []
    existing = next((p for p in posts if p.get("id") == post_id), None)
    if existing:
        is_own = existing.get("author_login") == user.get("login_id")
        is_admin = user.get("is_admin", False)
        if not (is_own or is_admin):
            raise HTTPException(status_code=403, detail="삭제 권한 없음")
    delete(BOARD, [post_id], id_field="id")
    # 댓글도 삭제
    comments = read(COMMENT, default_if_empty=[]) or []
    comment_ids = [c["id"] for c in comments if c.get("post_id") == post_id and c.get("id")]
    if comment_ids:
        delete(COMMENT, comment_ids, id_field="id")
    return {"ok": True}


@router.get("/{post_id}/comments")
def get_comments(post_id: str, user: dict = Depends(get_current_user)):
    read = _read()
    _, COMMENT = _sheet()
    comments = read(COMMENT, default_if_empty=[]) or []
    return [c for c in comments if c.get("post_id") == post_id]


@router.post("/{post_id}/comments", response_model=dict)
def add_comment(post_id: str, comment: BoardComment, user: dict = Depends(get_current_user)):
    upsert, _ = _write()
    _, COMMENT = _sheet()
    now = datetime.datetime.now().isoformat()
    comment.id          = str(uuid.uuid4())
    comment.post_id     = post_id
    comment.author_login= user.get("login_id", "")
    comment.author      = user.get("login_id", "")
    comment.office_name = user.get("office_name", "")
    comment.tenant_id   = user.get("tenant_id", "")
    comment.created_at  = now
    comment.updated_at  = now
    rec = {k: ("" if v is None else str(v)) for k, v in comment.model_dump().items()}
    upsert(COMMENT, header_list=COMMENT_HEADER, records=[rec], id_field="id")
    return rec


@router.delete("/{post_id}/comments/{comment_id}")
def delete_comment(post_id: str, comment_id: str, user: dict = Depends(get_current_user)):
    _, delete = _write()
    _, COMMENT = _sheet()
    # 작성자 또는 관리자만
    read = _read()
    comments = read(_sheet()[1], default_if_empty=[]) or []
    existing = next((c for c in comments if c.get("id") == comment_id), None)
    if existing:
        is_own = existing.get("author_login") == user.get("login_id")
        is_admin = user.get("is_admin", False)
        if not (is_own or is_admin):
            raise HTTPException(status_code=403, detail="삭제 권한 없음")
    delete(COMMENT, [comment_id], id_field="id")
    return {"ok": True}
