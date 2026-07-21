"""사무소 이용신청 단순화 — 정규화/검증/역할 고정/통계 (SQLite 단위).

프론트가 role 을 보내도 서버가 대표자=office_admin, 실무자=office_staff 로 고정하는지,
사업자번호/전화 정규화·검증, 대표자 이메일 기준 중복, 구버전 필드 fallback 을 검증한다.
"""
import pytest
from sqlalchemy import BigInteger, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker


@compiles(BigInteger, "sqlite")
def _bi(e, c, **k):  # noqa: ANN001
    return "INTEGER"


@compiles(JSONB, "sqlite")
def _jb(e, c, **k):  # noqa: ANN001
    return "JSON"


@compiles(INET, "sqlite")
def _in(e, c, **k):  # noqa: ANN001
    return "TEXT"


@pytest.fixture
def db(monkeypatch, tmp_path):
    from backend.db.base import Base
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.models.activation_token import ActivationToken
    from backend.db.models.office_application import OfficeApplication
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}", future=True)
    Base.metadata.create_all(engine, tables=[
        Tenant.__table__, AccountUser.__table__, ActivationToken.__table__,
        OfficeApplication.__table__,
    ])
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "get_sessionmaker", lambda: SessionLocal)
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    return SessionLocal


def _base(**over):
    d = {
        "office_name": "테스트사무소",
        "representative_name": "대표자",
        "representative_email": "rep@of.kr",
        "business_registration_number": "2131237464",
        "office_address": "서울시",
        "office_phone": "01094339280",
        "staff_name": "실무자",
        "staff_email": "staff@of.kr",
    }
    d.update(over)
    return d


# ── 정규화/형식화 ─────────────────────────────────────────────────────────────
def test_biz_normalize_and_format():
    from backend.services import office_application_pg_service as svc
    assert svc.normalize_biz_reg_no("213-12-37464") == "2131237464"
    assert svc.normalize_biz_reg_no("2131237464") == "2131237464"
    assert svc.is_valid_biz_reg_no("2131237464") is True
    assert svc.is_valid_biz_reg_no("213123746") is False
    assert svc.format_biz_reg_no("2131237464") == "213-12-37464"


def test_phone_normalize_and_format():
    from backend.services import office_application_pg_service as svc
    assert svc.normalize_phone("010-9433-9280") == "01094339280"
    assert svc.format_phone("01094339280") == "010-9433-9280"
    assert svc.format_phone("021234567") == "02-123-4567"
    assert svc.format_phone("0212345678") == "02-1234-5678"
    assert svc.format_phone("0311234567") == "031-123-4567"
    assert svc.format_phone("03112345678") == "031-1234-5678"
    assert svc.is_valid_phone("01094339280") is True
    assert svc.is_valid_phone("1234") is False
    assert svc.is_valid_phone("11234567890") is False  # 0 으로 시작하지 않음


# ── 생성: canonical 매핑 + digits 저장 ────────────────────────────────────────
def test_create_maps_rep_staff_and_stores_digits(db):
    from backend.services import office_application_pg_service as svc
    from backend.db.models.office_application import OfficeApplication
    r = svc.create_application(_base(business_registration_number="213-12-37464",
                                     office_phone="010-9433-9280"))
    with db() as s:
        a = s.scalar(select(OfficeApplication).where(
            OfficeApplication.application_id == r["application_id"]))
        assert a.requested_user_1_name == "대표자" and a.requested_user_1_email == "rep@of.kr"
        assert a.representative_name == "대표자"
        assert a.requested_user_2_name == "실무자" and a.requested_user_2_email == "staff@of.kr"
        assert a.business_registration_number == "2131237464"   # digits-only
        assert a.office_phone == "01094339280"                  # digits-only
        assert a.applicant_name is None and a.applicant_email is None and a.intended_use is None


def test_create_requires_fields(db):
    from backend.services import office_application_pg_service as svc
    for missing in ("representative_email", "representative_name", "staff_name", "staff_email"):
        with pytest.raises(svc.ApplicationError) as ei:
            svc.create_application(_base(**{missing: ""}))
        assert ei.value.code in ("MISSING_FIELD",), missing


def test_create_rejects_same_emails(db):
    from backend.services import office_application_pg_service as svc
    with pytest.raises(svc.ApplicationError) as ei:
        svc.create_application(_base(staff_email="rep@of.kr"))
    assert ei.value.code == "DUPLICATE_USER_EMAIL"


def test_create_rejects_bad_biz_and_phone(db):
    from backend.services import office_application_pg_service as svc
    with pytest.raises(svc.ApplicationError) as e1:
        svc.create_application(_base(business_registration_number="21312"))
    assert e1.value.code == "BAD_BIZ_REG_NO"
    with pytest.raises(svc.ApplicationError) as e2:
        svc.create_application(_base(office_phone="12"))
    assert e2.value.code == "BAD_PHONE"


def test_create_legacy_fallback_fields(db):
    """구버전 클라이언트: representative_email/staff_* 대신 requested_user_* 로 와도 동작."""
    from backend.services import office_application_pg_service as svc
    data = {
        "office_name": "구버전사무소",
        "representative_name": "대표",
        "business_registration_number": "2131237464",
        "requested_user_1_email": "rep2@of.kr",
        "requested_user_2_name": "직원",
        "requested_user_2_email": "staff2@of.kr",
    }
    r = svc.create_application(data)
    assert r["status"] == "pending"


def test_duplicate_pending_by_rep_email(db):
    from backend.services import office_application_pg_service as svc
    svc.create_application(_base())
    with pytest.raises(svc.ApplicationError) as ei:
        svc.create_application(_base())
    assert ei.value.code == "DUPLICATE_PENDING"


def test_to_dict_formatted(db):
    from backend.services import office_application_pg_service as svc
    r = svc.create_application(_base())
    a = svc.get_application(r["application_id"])
    assert a["business_registration_number_formatted"] == "213-12-37464"
    assert a["office_phone_formatted"] == "010-9433-9280"
    assert a["representative_email"] == "rep@of.kr"
    assert a["staff_email"] == "staff@of.kr"


# ── 승인: 역할 서버 고정 ──────────────────────────────────────────────────────
def test_approve_fixes_roles_regardless_of_input(db):
    from backend.services import office_application_pg_service as svc
    r = svc.create_application(_base())
    # 프론트가 역할을 뒤집어 보내도 서버가 대표자=admin, 실무자=staff 로 고정.
    res = svc.approve(r["application_id"], "wkdwhfl",
                      user1={"role": "office_staff"}, user2={"role": "office_admin"}, seat_limit=2)
    users = {u["login_id"]: u for u in res["users"]}
    assert users["rep@of.kr"]["role"] == "office_admin" and users["rep@of.kr"]["is_admin"] is True
    assert users["staff@of.kr"]["role"] == "office_staff" and users["staff@of.kr"]["is_admin"] is False


# ── 통계 ──────────────────────────────────────────────────────────────────────
def test_stats_counts_pending_and_reviewing(db):
    from backend.services import office_application_pg_service as svc
    svc.create_application(_base())
    r2 = svc.create_application(_base(office_name="B", representative_email="b@of.kr",
                                      staff_email="bs@of.kr"))
    svc.start_review(r2["application_id"], "wkdwhfl")
    st = svc.stats()
    assert st["pending"] == 1 and st["reviewing"] == 1 and st["unresolved"] == 2
