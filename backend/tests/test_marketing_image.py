"""마케팅 이미지 업로드/조회 스모크 테스트 (PG BYTEA, migration 0022).

SQLite 임시 DB + FastAPI TestClient. 운영 DB 불필요. PG(marketing_images) 경로만 검증.
실행: pytest backend/tests/test_marketing_image.py
"""
import io

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _png_bytes() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2, 2), (200, 100, 50)).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def env(monkeypatch, tmp_path):
    from backend.db.base import Base
    from backend.db.models.marketing_image import MarketingImage  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path / 'mkt.db'}", future=True)
    Base.metadata.create_all(engine, tables=[MarketingImage.__table__])
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)

    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    monkeypatch.setattr(dbs, "get_sessionmaker", lambda: SessionLocal)

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.auth import get_current_user
    from backend.routers import marketing as r

    app = FastAPI()
    app.include_router(r.router, prefix="/api/marketing")
    holder = {"user": {"login_id": "adm", "tenant_id": "t1", "is_admin": True}}
    app.dependency_overrides[get_current_user] = lambda: holder["user"]
    return TestClient(app), holder


def test_upload_then_serve(env):
    client, _ = env
    png = _png_bytes()
    up = client.post("/api/marketing/admin/upload-image",
                     files={"file": ("logo.png", png, "image/png")})
    assert up.status_code == 200, up.text
    body = up.json()
    assert body["content_type"] == "image/png" and body["size_bytes"] == len(png)
    assert body["url"].startswith("/api/marketing/images/")

    img_id = body["id"]
    got = client.get(f"/api/marketing/images/{img_id}")
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"
    assert got.content == png  # round-trips byte-for-byte


def test_non_admin_rejected(env):
    client, holder = env
    holder["user"] = {"login_id": "u", "tenant_id": "t1", "is_admin": False}
    up = client.post("/api/marketing/admin/upload-image",
                     files={"file": ("logo.png", _png_bytes(), "image/png")})
    assert up.status_code == 403


def test_non_image_rejected(env):
    client, _ = env
    up = client.post("/api/marketing/admin/upload-image",
                     files={"file": ("x.png", b"this is not an image", "image/png")})
    assert up.status_code == 415


def test_missing_image_404(env):
    client, _ = env
    assert client.get("/api/marketing/images/nonexistent-id").status_code == 404
