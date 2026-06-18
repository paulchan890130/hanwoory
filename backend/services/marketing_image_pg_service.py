"""Marketing 이미지 PG(BYTEA) 저장/조회 — Google Drive 대체.

- save_image: 검증된 이미지 바이트를 marketing_images 에 1건 저장하고 메타 반환.
- get_image: 단건 PK 조회로만 data(BYTEA) 로드(목록 조회에서 bulk 로드 금지).
- 삭제는 soft delete(deleted_at) — 서빙 시 404 처리.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Optional


def save_image(*, tenant_id: str, created_by: str, filename: str,
               content_type: str, data: bytes) -> dict:
    """이미지 1건 저장. 반환: {id, content_type, size_bytes}."""
    from backend.db.models.marketing_image import MarketingImage
    from backend.db.session import get_sessionmaker

    img_id = str(uuid.uuid4())
    sha = hashlib.sha256(data).hexdigest()
    SessionLocal = get_sessionmaker()
    with SessionLocal() as s:
        s.add(MarketingImage(
            id=img_id,
            tenant_id=(tenant_id or "")[:128],
            filename=(filename or "")[:255],
            content_type=content_type,
            size_bytes=len(data),
            sha256=sha,
            data=data,
            created_by=(created_by or "")[:128],
        ))
        s.commit()
    return {"id": img_id, "content_type": content_type, "size_bytes": len(data)}


def get_image(image_id: str) -> Optional[tuple[bytes, str]]:
    """단건 조회 → (data, content_type). 없음/soft-deleted → None."""
    iid = (image_id or "").strip()
    if not iid:
        return None
    from backend.db.models.marketing_image import MarketingImage
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as s:
        row = s.get(MarketingImage, iid)
        if row is None or row.deleted_at is not None or not row.data:
            return None
        return bytes(row.data), str(row.content_type or "application/octet-stream")
