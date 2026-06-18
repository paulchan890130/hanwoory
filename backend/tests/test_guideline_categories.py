"""실무지침 분류 오버레이 — 내부코드/한글표시명 분리 + seed 보존 테스트.

SQLite 임시 DB. 운영 DB 불필요.
실행: pytest backend/tests/test_guideline_categories.py
"""
import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from backend.services import guideline_category_pg_service as svc


@compiles(BigInteger, "sqlite")
def _bigint_as_integer_on_sqlite(element, compiler, **kw):  # noqa: ANN001
    return "INTEGER"


@pytest.fixture
def db(monkeypatch, tmp_path):
    from backend.db.base import Base
    from backend.db.models.guideline_category import (  # noqa: F401
        GuidelineCategory, GuidelineCategoryOverride,
    )
    engine = create_engine(f"sqlite:///{tmp_path / 'gl.db'}", future=True)
    Base.metadata.create_all(engine, tables=[
        GuidelineCategory.__table__, GuidelineCategoryOverride.__table__,
    ])
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "get_sessionmaker", lambda: SessionLocal)
    return SessionLocal


_ROWS = [
    {"action_type": "CHANGE", "detailed_code": "F-2-1"},
    {"action_type": "ACTIVITY_EXTRA", "detailed_code": "A-1"},
]


# ── 순수 유닛: 내부코드 디코드 / 한글 추천 ────────────────────────────────────
def test_decode_source_key():
    assert svc.decode_source_key("M|CHANGE") == "CHANGE"
    assert svc.decode_source_key("m|CHANGE|F") == "F"
    assert svc.decode_source_key("s|CHANGE|F|F-2") == "F-2"
    assert svc.decode_source_key("") == ""
    assert svc.decode_source_key(None) == ""


def test_suggested_label_for():
    assert svc.suggested_label_for("major", "M|CHANGE") == "체류자격 변경"
    assert svc.suggested_label_for("major", "M|ACTIVITY_EXTRA") == "활동범위 추가"
    assert svc.suggested_label_for("major", "M|UNKNOWN") == "UNKNOWN"   # 매핑 없으면 코드
    assert svc.suggested_label_for("middle", "m|CHANGE|F") == "F"       # 주분류는 구조 코드 그대로
    assert svc.suggested_label_for("minor", "s|CHANGE|F|F-2") == "F-2"


# ── seed: 대분류 한글 / _to_dict 에 code·suggested_label 포함 ──────────────────
def test_seed_majors_korean_and_dict_fields(db):
    svc.seed_from_rows(_ROWS)
    cats = svc.list_categories(include_inactive=True)
    major = next(c for c in cats if c["source_key"] == "M|CHANGE")
    assert major["display_name"] == "체류자격 변경"     # 대분류는 한글로 시드
    assert major["code"] == "CHANGE"                    # 내부코드 노출(읽기전용)
    assert major["suggested_label"] == "체류자격 변경"
    middle = next(c for c in cats if c["source_key"] == "m|CHANGE|F")
    assert middle["code"] == "F" and middle["display_name"] == "F"  # 주분류는 구조 코드


# ── source_key(내부코드)는 표시명 수정 시 보존 ────────────────────────────────
def test_update_changes_display_name_not_source_key(db):
    svc.seed_from_rows(_ROWS)
    cats = svc.list_categories(include_inactive=True)
    major = next(c for c in cats if c["source_key"] == "M|CHANGE")
    updated = svc.update_category(major["id"], {"display_name": "체류자격 변경(수정)"})
    assert updated["display_name"] == "체류자격 변경(수정)"
    assert updated["source_key"] == "M|CHANGE"  # 내부코드 불변
    assert updated["code"] == "CHANGE"


# ── 기본 분류 생성(재시드) 이 사용자 수정 표시명을 덮어쓰지 않음 ──────────────
def test_reseed_preserves_user_edited_display_name(db):
    svc.seed_from_rows(_ROWS)
    cats = svc.list_categories(include_inactive=True)
    major = next(c for c in cats if c["source_key"] == "M|CHANGE")
    svc.update_category(major["id"], {"display_name": "사용자가 직접 지은 이름"})
    # 재시드(멱등) — 신규 생성 0건, 기존 사용자 값 보존
    res = svc.seed_from_rows(_ROWS)
    assert res["created"] == 0
    again = next(c for c in svc.list_categories(include_inactive=True) if c["source_key"] == "M|CHANGE")
    assert again["display_name"] == "사용자가 직접 지은 이름"  # 덮어쓰지 않음


# ── 영문코드로 남아있던 대분류는 재시드 시 한글로 backfill ────────────────────
def test_reseed_backfills_code_valued_major_to_korean(db):
    svc.seed_from_rows(_ROWS)
    cats = svc.list_categories(include_inactive=True)
    major = next(c for c in cats if c["source_key"] == "M|CHANGE")
    # 과거 영문코드 상태를 재현(display_name == action_type code)
    svc.update_category(major["id"], {"display_name": "CHANGE"})
    svc.seed_from_rows(_ROWS)
    again = next(c for c in svc.list_categories(include_inactive=True) if c["source_key"] == "M|CHANGE")
    assert again["display_name"] == "체류자격 변경"  # 코드값은 한글로 보정
