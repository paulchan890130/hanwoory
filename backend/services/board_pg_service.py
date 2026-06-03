"""PG repository for board posts + comments (admin-shared)."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import delete, select


POST_FIELDS = (
    "id", "tenant_id", "author_login", "office_name",
    "is_notice", "category", "title", "content",
    "created_at", "updated_at", "popup_yn", "link_url", "comment_count",
)
COMMENT_FIELDS = (
    "id", "post_id", "tenant_id", "author_login", "office_name",
    "content", "created_at", "updated_at",
)


def _post_to_dict(row) -> dict:
    return {
        "id": row.id, "tenant_id": row.tenant_id or "",
        "author_login": row.author_login or "", "office_name": row.office_name or "",
        "is_notice": row.is_notice or "", "category": row.category or "",
        "title": row.title or "", "content": row.content or "",
        "created_at": row.created_at or "", "updated_at": row.updated_at or "",
        "popup_yn": row.popup_yn or "", "link_url": row.link_url or "",
        "comment_count": int(row.comment_count or 0),
    }


def _comment_to_dict(row) -> dict:
    return {
        "id": row.id, "post_id": row.post_id,
        "tenant_id": row.tenant_id or "",
        "author_login": row.author_login or "", "office_name": row.office_name or "",
        "content": row.content or "",
        "created_at": row.created_at or "", "updated_at": row.updated_at or "",
    }


# ── posts ────────────────────────────────────────────────────────────────

def list_posts(exclude_categories: tuple[str, ...] = ()) -> list[dict]:
    from backend.db.models.board import BoardPost
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(select(BoardPost).order_by(BoardPost.created_at.desc())).all()
    posts = [_post_to_dict(r) for r in rows]
    if exclude_categories:
        posts = [p for p in posts if p.get("category", "") not in exclude_categories]
    return posts


def get_popup_posts() -> list[dict]:
    posts = list_posts()
    return [p for p in posts if str(p.get("popup_yn", "")).strip().upper() == "Y"]


def upsert_post(rec: dict) -> dict:
    from backend.db.models.board import BoardPost
    from backend.db.session import get_sessionmaker

    pid = str(rec.get("id", "")).strip() or str(uuid.uuid4())
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(select(BoardPost).where(BoardPost.id == pid))
        payload = {f: rec.get(f, "") for f in POST_FIELDS if f != "id"}
        payload["comment_count"] = int(rec.get("comment_count", 0) or 0)
        if row is None:
            row = BoardPost(id=pid, **payload)
            session.add(row)
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        session.commit()
        session.refresh(row)
        return _post_to_dict(row)


def delete_post(post_id: str) -> bool:
    from backend.db.models.board import BoardComment, BoardPost
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        session.execute(delete(BoardComment).where(BoardComment.post_id == post_id))
        result = session.execute(delete(BoardPost).where(BoardPost.id == post_id))
        session.commit()
        return (result.rowcount or 0) > 0


# ── comments ──────────────────────────────────────────────────────────────

def list_comments(post_id: str) -> list[dict]:
    from backend.db.models.board import BoardComment
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(BoardComment).where(BoardComment.post_id == post_id)
            .order_by(BoardComment.created_at)
        ).all()
    return [_comment_to_dict(r) for r in rows]


def add_comment(rec: dict) -> dict:
    from backend.db.models.board import BoardComment, BoardPost
    from backend.db.session import get_sessionmaker

    cid = str(rec.get("id", "")).strip() or str(uuid.uuid4())
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = BoardComment(
            id=cid,
            post_id=str(rec.get("post_id", "")),
            tenant_id=str(rec.get("tenant_id", "")),
            author_login=str(rec.get("author_login", "")),
            office_name=str(rec.get("office_name", "")),
            content=str(rec.get("content", "")),
            created_at=str(rec.get("created_at", "")),
            updated_at=str(rec.get("updated_at", "")),
        )
        session.add(row)
        # bump post.comment_count
        post = session.scalar(select(BoardPost).where(BoardPost.id == row.post_id))
        if post is not None:
            post.comment_count = (post.comment_count or 0) + 1
        session.commit()
        session.refresh(row)
        return _comment_to_dict(row)


def delete_comment(post_id: str, comment_id: str) -> bool:
    from backend.db.models.board import BoardComment, BoardPost
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(
            delete(BoardComment).where(BoardComment.id == comment_id)
        )
        if (result.rowcount or 0) > 0:
            post = session.scalar(select(BoardPost).where(BoardPost.id == post_id))
            if post is not None and (post.comment_count or 0) > 0:
                post.comment_count -= 1
        session.commit()
        return (result.rowcount or 0) > 0
