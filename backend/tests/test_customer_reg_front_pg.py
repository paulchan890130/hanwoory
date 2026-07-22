"""외국인등록번호 앞자리(reg_front) 선행 0 보존 — **실제 PostgreSQL** 통합 테스트.

``TEST_DATABASE_URL`` 설정 시에만 실행(미설정 → skip). 검증:
- 수동 API 로 ``"001010"`` / ``"1010"`` / int-형 저장 후 **DB raw 컬럼**이 ``"001010"``.
- 선행 0 이 손실된 레거시 행(raw ``"1010"``)을 직접 INSERT 한 뒤 ``find_customer`` 가
  읽기 방어선으로 ``"001010"`` 을 돌려주되 **DB 원문은 그대로**(비파괴)임을 확인.

실제 고객 원문은 사용하지 않고 합성 값만 쓴다.
"""
from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

os.environ.setdefault("CUSTOMER_PII_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("PII_HASH_SECRET", "reg-front-it-secret")

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="TEST_DATABASE_URL 미설정 — 실제 PostgreSQL 통합 테스트 skip")


def _ensure_database(url_str: str) -> None:
    url = make_url(url_str)
    admin_url = url.set(database="postgres")
    eng = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with eng.connect() as c:
            exists = c.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": url.database}).first()
            if not exists:
                c.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        eng.dispose()


@pytest.fixture(scope="module")
def engine():
    _ensure_database(TEST_DB_URL)
    eng = create_engine(TEST_DB_URL, future=True)
    from backend.db.base import Base
    from backend.db.models.customer import Customer
    from backend.db.models.tenant import Tenant
    tables = [Tenant.__table__, Customer.__table__]
    Base.metadata.drop_all(eng, tables=list(reversed(tables)))
    Base.metadata.create_all(eng, tables=tables)
    yield eng
    Base.metadata.drop_all(eng, tables=list(reversed(tables)))
    eng.dispose()


@pytest.fixture
def db(engine, monkeypatch):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "get_sessionmaker", lambda: SessionLocal)
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    with engine.begin() as c:
        c.execute(text("TRUNCATE customers, tenants RESTART IDENTITY CASCADE"))
    # 테넌트 seed(FK).
    from backend.db.models.tenant import Tenant
    with SessionLocal() as s:
        s.add(Tenant(tenant_id="t-regfront", office_name="T", is_active=True))
        s.commit()
    return SessionLocal


def _raw_reg_front(db, customer_id):
    with db() as s:
        return s.scalar(text("SELECT reg_front FROM customers WHERE customer_id = :c")
                        .bindparams(c=customer_id))


@pytest.mark.parametrize("value", ["001010", "1010"])
def test_new_write_stores_canonical_six_digits(db, value):
    from backend.services.customer_pg_service import create_customer

    out = create_customer("t-regfront", {"한글": "김합성", "등록증": value})
    cid = out["고객ID"]
    assert out["등록증"] == "001010"
    # DB raw 컬럼 자체가 6자리로 저장됐는지(쓰기 정규화).
    assert _raw_reg_front(db, cid) == "001010"


def test_legacy_row_read_defense_non_destructive(db):
    from backend.services.customer_pg_service import find_customer

    # 방어선을 우회해 손상된 레거시 원문('1010')을 직접 INSERT.
    with db() as s:
        s.execute(text(
            "INSERT INTO customers (tenant_id, customer_id, korean_name, reg_front) "
            "VALUES (:t, :c, :n, :r)"
        ).bindparams(t="t-regfront", c="9001", n="이레거시", r="1010"))
        s.commit()

    got = find_customer("t-regfront", "9001")
    assert got["등록증"] == "001010"          # 읽기 방어선으로 복구
    assert _raw_reg_front(db, "9001") == "1010"  # DB 원문은 불변(비파괴)
