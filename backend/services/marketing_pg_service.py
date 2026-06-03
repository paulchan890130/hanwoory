"""PG repository for marketing posts (홈페이지게시물)."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import delete, select


FIELDS = (
    "id", "title", "slug", "category", "summary", "content",
    "thumbnail_url", "is_published", "is_featured",
    "created_by", "created_at", "updated_at",
    "image_file_id", "image_url", "image_alt",
    "meta_description", "tags",
)


def _row_to_dict(row) -> dict:
    return {f: ("" if getattr(row, f, None) is None else str(getattr(row, f))) for f in FIELDS}


def list_public() -> list[dict]:
    """Posts where is_published == TRUE, newest first."""
    from backend.db.models.marketing import MarketingPost
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(MarketingPost)
            .where(MarketingPost.is_published == "TRUE")
            .order_by(MarketingPost.created_at.desc())
        ).all()
    return [_row_to_dict(r) for r in rows]


def list_admin() -> list[dict]:
    """All posts regardless of publish state."""
    from backend.db.models.marketing import MarketingPost
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(MarketingPost).order_by(MarketingPost.created_at.desc())
        ).all()
    return [_row_to_dict(r) for r in rows]


def get_post(post_id: str) -> Optional[dict]:
    from backend.db.models.marketing import MarketingPost
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(select(MarketingPost).where(MarketingPost.id == post_id))
    return _row_to_dict(row) if row else None


def upsert_post(rec: dict) -> dict:
    from backend.db.models.marketing import MarketingPost
    from backend.db.session import get_sessionmaker

    pid = str(rec.get("id", "")).strip() or str(uuid.uuid4())
    payload = {f: str(rec.get(f, "") or "") for f in FIELDS if f != "id"}

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(select(MarketingPost).where(MarketingPost.id == pid))
        if row is None:
            row = MarketingPost(id=pid, **payload)
            session.add(row)
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        session.commit()
        session.refresh(row)
        return _row_to_dict(row)


def delete_post(post_id: str) -> bool:
    from backend.db.models.marketing import MarketingPost
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(delete(MarketingPost).where(MarketingPost.id == post_id))
        session.commit()
        return (result.rowcount or 0) > 0
