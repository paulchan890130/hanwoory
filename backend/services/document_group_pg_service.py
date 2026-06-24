"""PG repository for 업무별 준비서류 중분류 (document_groups).

순수 함수 + get_sessionmaker. 반환은 호출부가 그대로 쓰는 정규화 dict.
글↔중분류 연결은 marketing_posts.tags 의 doc_group:<group_key> 태그로 하며
이 서비스는 중분류 메타데이터만 다룬다(A안).

v1: 물리 삭제 없음 — set_published 로 공개/비공개만 전환.
"""
from __future__ import annotations

import datetime
import re
import uuid
from typing import Optional

from sqlalchemy import select


FIELDS = (
    "id", "group_key", "title", "description",
    "sort_order", "is_published", "created_at", "updated_at",
)

# group_key 규칙: 소문자/숫자/하이픈, 태그(doc_group:<key>)에 안전한 형태.
_GROUP_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def _is_true(v) -> bool:
    return str(v).strip().upper() in ("TRUE", "Y", "1")


def _row_to_dict(row) -> dict:
    out = {}
    for f in FIELDS:
        v = getattr(row, f, None)
        if f == "sort_order":
            out[f] = int(v) if v is not None else 0
        elif f == "is_published":
            out[f] = "TRUE" if _is_true(v) else "FALSE"
        else:
            out[f] = "" if v is None else str(v)
    return out


def normalize_group_key(raw: str) -> str:
    return (raw or "").strip().lower()


def is_valid_group_key(raw: str) -> bool:
    return bool(_GROUP_KEY_RE.match(normalize_group_key(raw)))


def list_groups(published_only: bool = False) -> list[dict]:
    """sort_order, group_key 순. published_only=True → 공개 중분류만."""
    from backend.db.models.document_group import DocumentGroup
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        stmt = select(DocumentGroup)
        if published_only:
            stmt = stmt.where(DocumentGroup.is_published == "TRUE")
        stmt = stmt.order_by(
            DocumentGroup.sort_order.asc(), DocumentGroup.group_key.asc()
        )
        rows = session.scalars(stmt).all()
    return [_row_to_dict(r) for r in rows]


def get_group(group_id: str) -> Optional[dict]:
    from backend.db.models.document_group import DocumentGroup
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(DocumentGroup).where(DocumentGroup.id == group_id)
        )
    return _row_to_dict(row) if row else None


def get_group_by_key(group_key: str) -> Optional[dict]:
    from backend.db.models.document_group import DocumentGroup
    from backend.db.session import get_sessionmaker

    key = normalize_group_key(group_key)
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(DocumentGroup).where(DocumentGroup.group_key == key)
        )
    return _row_to_dict(row) if row else None


def create_group(
    *,
    group_key: str,
    title: str = "",
    description: str = "",
    sort_order: Optional[int] = None,
    is_published: bool = True,
) -> dict:
    """신규 중분류. group_key 중복 시 ValueError."""
    from backend.db.models.document_group import DocumentGroup
    from backend.db.session import get_sessionmaker

    key = normalize_group_key(group_key)
    if not is_valid_group_key(key):
        raise ValueError("group_key 형식이 올바르지 않습니다 (소문자/숫자/하이픈).")

    now = datetime.datetime.now().isoformat()
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        exists = session.scalar(
            select(DocumentGroup).where(DocumentGroup.group_key == key)
        )
        if exists is not None:
            raise ValueError(f"이미 존재하는 중분류 키입니다: {key}")
        if sort_order is None:
            max_order = session.scalar(
                select(DocumentGroup.sort_order)
                .order_by(DocumentGroup.sort_order.desc())
                .limit(1)
            )
            sort_order = (int(max_order) + 1) if max_order is not None else 0
        row = DocumentGroup(
            id=str(uuid.uuid4()),
            group_key=key,
            title=str(title or ""),
            description=str(description or ""),
            sort_order=int(sort_order),
            is_published="TRUE" if is_published else "FALSE",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _row_to_dict(row)


def update_group(
    group_id: str,
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    sort_order: Optional[int] = None,
) -> Optional[dict]:
    """이름/설명/순서 수정. group_key 는 변경하지 않는다(글 연결 보존)."""
    from backend.db.models.document_group import DocumentGroup
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(DocumentGroup).where(DocumentGroup.id == group_id)
        )
        if row is None:
            return None
        if title is not None:
            row.title = str(title)
        if description is not None:
            row.description = str(description)
        if sort_order is not None:
            row.sort_order = int(sort_order)
        row.updated_at = datetime.datetime.now().isoformat()
        session.commit()
        session.refresh(row)
        return _row_to_dict(row)


def set_published(group_id: str, published: bool) -> Optional[dict]:
    from backend.db.models.document_group import DocumentGroup
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(DocumentGroup).where(DocumentGroup.id == group_id)
        )
        if row is None:
            return None
        row.is_published = "TRUE" if published else "FALSE"
        row.updated_at = datetime.datetime.now().isoformat()
        session.commit()
        session.refresh(row)
        return _row_to_dict(row)


def toggle_published(group_id: str) -> Optional[dict]:
    from backend.db.models.document_group import DocumentGroup
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.scalar(
            select(DocumentGroup).where(DocumentGroup.id == group_id)
        )
        if row is None:
            return None
        row.is_published = "FALSE" if _is_true(row.is_published) else "TRUE"
        row.updated_at = datetime.datetime.now().isoformat()
        session.commit()
        session.refresh(row)
        return _row_to_dict(row)
