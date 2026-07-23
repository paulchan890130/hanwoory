"""SEV-1 회귀 방지 — 로그인을 optional/deferred 프로필 컬럼과 분리한다.

배경(사고): 배포에서 ``_row_from_pg`` 가 로그인 조회 중 deferred 컬럼(``users.role`` [0024],
``tenants.source_application_id`` [0031])을 ``getattr`` 로 접근했다. deferred 컬럼의 getattr 은
default 를 반환하지 않고 **개별 SELECT SQL** 을 발생시키므로, 그 migration 이 아직 적용되지
않은 운영 DB 에서 ``UndefinedColumn`` → 500 → 모든 계정 로그인 불가(프론트엔 "로그인 실패").

핵심 검증:
  - 로그인 전용 조회(``find_account_for_login``)의 SQL 에 role/source_application_id/onboarding 없음.
  - 0032/0031/0030(및 role 부재) 스키마 매트릭스에서 관리자·일반 사용자 로그인 200.
  - 자격증명/상태/잠금/백엔드오류가 각각 401/403/429/503 로 정확히 분기.
  - password / password_hash 가 로그에 남지 않음.

SQLite + get_sessionmaker monkeypatch. create_all 은 모델의 모든 컬럼(= 0032 head 상당)을
만들므로, 특정 컬럼을 ``ALTER TABLE … DROP COLUMN`` 으로 제거해 이전 migration 상태를 재현한다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import BigInteger, create_engine, event, text
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from fastapi import HTTPException


@compiles(BigInteger, "sqlite")
def _bi(e, c, **k):  # noqa: ANN001
    return "INTEGER"


@compiles(JSONB, "sqlite")
def _jb(e, c, **k):  # noqa: ANN001
    return "JSON"


@compiles(INET, "sqlite")
def _in(e, c, **k):  # noqa: ANN001
    return "TEXT"


_PW = "Secret123!"

# migration 별로 추가되는(=드롭하면 그 이전 상태가 되는) 컬럼.
# 로그인 critical-path 가 건드리던 deferred 컬럼만 정밀히 재현한다.
_DROP_FOR = {
    "0032": [],  # head — 전부 존재
    "0031": [("users", "onboarding_completed_version"), ("users", "onboarding_completed_at")],  # 0032 미적용
    "0030": [("users", "onboarding_completed_version"), ("users", "onboarding_completed_at"),
             ("tenants", "source_application_id")],                                             # 0031 미적용
    "pre_0024": [("users", "onboarding_completed_version"), ("users", "onboarding_completed_at"),
                 ("tenants", "source_application_id"), ("users", "role")],                      # role(0024)도 부재
}


def _build_engine(tmp_path, name):
    """항상 full 스키마(= 0032 head 상당)로 생성 — drift 는 seed 이후 DROP 으로 재현한다."""
    from backend.db.base import Base
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.models.user_session import UserSession
    from backend.db.models.activation_token import ActivationToken
    engine = create_engine(f"sqlite:///{tmp_path / name}", future=True)
    Base.metadata.create_all(engine, tables=[
        Tenant.__table__, AccountUser.__table__, UserSession.__table__, ActivationToken.__table__,
    ])
    return engine


def _simulate_drift(engine, level):
    """seed 이후 호출 — 해당 migration 미적용 상태를 컬럼 DROP 으로 재현한다.
    (ORM INSERT 는 매핑된 컬럼을 모두 쓰므로 반드시 seed 뒤에 드롭한다.)"""
    drop = _DROP_FOR[level]
    if not drop:
        return
    with engine.begin() as c:
        for tbl, col in drop:
            try:
                c.execute(text(f'ALTER TABLE {tbl} DROP COLUMN {col}'))
            except Exception as exc:  # SQLite < 3.35 → DROP COLUMN 미지원
                pytest.skip(f"SQLite DROP COLUMN 미지원 — 스키마 drift 재현 불가: {exc}")


def _bind(monkeypatch, engine):
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "get_sessionmaker", lambda: SessionLocal)
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    return SessionLocal


def _seed(SessionLocal, *, login_id="admin@of1.kr", tid="of-1", is_admin=True,
          is_active=True, account_status="active", password=_PW):
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.services.accounts_service import hash_password
    with SessionLocal() as s:
        if s.scalar(text("SELECT 1 FROM tenants WHERE tenant_id=:t").bindparams(t=tid)) is None:
            t = Tenant(tenant_id=tid, office_name="테스트사무소", is_active=True)
            s.add(t)
        u = AccountUser(login_id=login_id, tenant_id=tid,
                        password_hash=hash_password(password) if password else "x",
                        is_admin=is_admin, is_active=is_active)
        # account_status 는 deferred(0031) — 컬럼 있을 때만 세팅(없으면 lazy-load 회피).
        try:
            u.account_status = account_status
        except Exception:
            pass
        s.add(u)
        s.commit()


@pytest.fixture(autouse=True)
def _isolate_side_effects(monkeypatch):
    """로그인 부수효과(잠금/감사/보안 이벤트)는 다른 테이블을 쓰므로 no-op 로 격리 —
    이 테스트의 관심사(스키마 drift 로부터 로그인 분리)만 검증한다."""
    monkeypatch.setattr("backend.services.login_guard_pg_service.check_locked", lambda *a, **k: None)
    monkeypatch.setattr("backend.services.login_guard_pg_service.record_failure", lambda *a, **k: False)
    monkeypatch.setattr("backend.services.login_guard_pg_service.record_success", lambda *a, **k: None)
    monkeypatch.setattr("backend.services.audit_service.log_event", lambda *a, **k: None)
    monkeypatch.setattr("backend.services.account_security_pg_service.record_event", lambda *a, **k: None)
    monkeypatch.setattr("backend.services.account_security_pg_service.is_security_blocked", lambda *a, **k: False)
    monkeypatch.setattr("backend.services.account_security_pg_service.evaluate_suspicion", lambda *a, **k: None)
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "0")
    monkeypatch.setenv("FEATURE_SINGLE_SESSION", "0")


def _login(login_id, password):
    from backend.routers.auth import login
    from backend.models import LoginRequest
    return login(LoginRequest(login_id=login_id, password=password), request=None)


# ── 1) find_account_for_login 의 SQL 에 deferred/optional 컬럼이 없음 (tests 4·5·6) ─────
def test_login_query_never_references_deferred_columns(tmp_path, monkeypatch):
    eng = _build_engine(tmp_path, "sql.db")
    SessionLocal = _bind(monkeypatch, eng)
    _seed(SessionLocal)

    seen: list[str] = []

    @event.listens_for(eng, "before_cursor_execute")
    def _cap(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
        seen.append(statement.lower())

    from backend.services.accounts_service import find_account_for_login
    acc = find_account_for_login("admin@of1.kr")
    assert acc and acc["login_id"] == "admin@of1.kr"

    joined = "\n".join(seen)
    assert seen, "SQL 이 한 건도 캡처되지 않음"
    for forbidden in (".role", " role", "source_application_id",
                      "onboarding_completed_version", "onboarding_completed_at",
                      "account_status"):
        assert forbidden not in joined, f"로그인 조회 SQL 이 금지 컬럼 참조: {forbidden}\n{joined}"


# ── 2) 스키마 매트릭스: 0032 / 0031 / 0030 / role 부재 모두 로그인 성공 (tests 1·2·3·14) ──
@pytest.mark.parametrize("level", ["0032", "0031", "0030", "pre_0024"])
def test_schema_matrix_admin_login_ok(tmp_path, monkeypatch, level):
    eng = _build_engine(tmp_path, f"m_{level}.db")
    SessionLocal = _bind(monkeypatch, eng)
    _seed(SessionLocal, login_id="admin@of1.kr", is_admin=True)
    _simulate_drift(eng, level)  # seed 이후 migration 미적용 상태 재현

    res = _login("admin@of1.kr", _PW)
    assert res.access_token
    assert res.is_admin is True
    assert res.is_system_admin is False  # 이름충돌 회귀(성공 경로 500)도 방지됨
    assert res.login_id == "admin@of1.kr"


@pytest.mark.parametrize("level", ["0032", "0031", "0030", "pre_0024"])
def test_schema_matrix_staff_login_ok(tmp_path, monkeypatch, level):
    eng = _build_engine(tmp_path, f"s_{level}.db")
    SessionLocal = _bind(monkeypatch, eng)
    _seed(SessionLocal, login_id="staff@of1.kr", is_admin=False)
    _simulate_drift(eng, level)

    res = _login("staff@of1.kr", _PW)
    assert res.access_token and res.is_admin is False


# ── 3) find_account (프로필 경로)도 drift DB 에서 500 나지 않음 ─────────────────────────
def test_find_account_survives_schema_drift(tmp_path, monkeypatch):
    eng = _build_engine(tmp_path, "fa.db")
    SessionLocal = _bind(monkeypatch, eng)
    _seed(SessionLocal)
    _simulate_drift(eng, "pre_0024")
    from backend.services.accounts_service import find_account
    acc = find_account("admin@of1.kr")  # role/source_application_id 부재에도 예외 없음
    assert acc and acc["login_id"] == "admin@of1.kr"
    assert acc["role"] == "" and acc["source_application_id"] == ""  # 미적용 → 빈 값


def test_find_account_enriches_optional_columns_when_present(tmp_path, monkeypatch):
    eng = _build_engine(tmp_path, "fa2.db")
    SessionLocal = _bind(monkeypatch, eng)
    _seed(SessionLocal)
    # role/source_application_id 를 실제로 채운다(head 스키마 → 컬럼 존재).
    with SessionLocal() as s:
        s.execute(text("UPDATE users SET role='sub_admin' WHERE login_id='admin@of1.kr'"))
        s.execute(text("UPDATE tenants SET source_application_id='app-77' WHERE tenant_id='of-1'"))
        s.commit()
    from backend.services.accounts_service import find_account
    acc = find_account("admin@of1.kr")
    assert acc["role"] == "sub_admin" and acc["source_application_id"] == "app-77"


# ── 4) 자격증명/상태/잠금/백엔드오류 분기 (tests 7·8·9·10·12·13) ───────────────────────
def test_correct_password_returns_token(tmp_path, monkeypatch):
    eng = _build_engine(tmp_path, "ok.db")
    _seed(_bind(monkeypatch, eng))
    assert _login("admin@of1.kr", _PW).access_token


def test_wrong_password_401(tmp_path, monkeypatch):
    eng = _build_engine(tmp_path, "bad.db")
    _seed(_bind(monkeypatch, eng))
    with pytest.raises(HTTPException) as ei:
        _login("admin@of1.kr", "wrong-password")
    assert ei.value.status_code == 401


def test_unknown_account_401(tmp_path, monkeypatch):
    eng = _build_engine(tmp_path, "unk.db")
    _bind(monkeypatch, eng)
    with pytest.raises(HTTPException) as ei:
        _login("nobody@of1.kr", _PW)
    assert ei.value.status_code == 401


def test_inactive_account_403(tmp_path, monkeypatch):
    eng = _build_engine(tmp_path, "inact.db")
    _seed(_bind(monkeypatch, eng), is_active=False, account_status="active")
    with pytest.raises(HTTPException) as ei:
        _login("admin@of1.kr", _PW)
    assert ei.value.status_code == 403


def test_invited_account_not_activated(tmp_path, monkeypatch):
    eng = _build_engine(tmp_path, "inv.db")  # head 스키마(account_status 존재)
    _seed(_bind(monkeypatch, eng), is_active=False, account_status="invited", password="")
    with pytest.raises(HTTPException) as ei:
        _login("admin@of1.kr", _PW)
    assert ei.value.status_code == 403
    assert isinstance(ei.value.detail, dict)
    assert ei.value.detail.get("code") == "ACCOUNT_NOT_ACTIVATED"


def test_locked_account_429(tmp_path, monkeypatch):
    eng = _build_engine(tmp_path, "lock.db")
    _seed(_bind(monkeypatch, eng))
    import datetime as _dt
    monkeypatch.setattr("backend.services.login_guard_pg_service.check_locked",
                        lambda *a, **k: _dt.datetime.now())
    with pytest.raises(HTTPException) as ei:
        _login("admin@of1.kr", _PW)
    assert ei.value.status_code == 429


def test_backend_unavailable_503_structured(tmp_path, monkeypatch):
    eng = _build_engine(tmp_path, "down.db")
    _bind(monkeypatch, eng)
    from backend.services.accounts_service import AuthBackendUnavailable
    monkeypatch.setattr("backend.routers.auth._find_account_for_login",
                        lambda _lid: (_ for _ in ()).throw(AuthBackendUnavailable("ProgrammingError")))
    with pytest.raises(HTTPException) as ei:
        _login("admin@of1.kr", _PW)
    assert ei.value.status_code == 503
    assert isinstance(ei.value.detail, dict)
    assert ei.value.detail.get("code") == "AUTH_BACKEND_UNAVAILABLE"


def test_find_account_for_login_raises_on_db_error(monkeypatch):
    """DB 세션 획득 실패 → AuthBackendUnavailable (계정 없음/401 로 위장 금지)."""
    import backend.db.session as dbs
    from backend.services.accounts_service import find_account_for_login, AuthBackendUnavailable
    def _boom():
        raise RuntimeError("connection refused")
    monkeypatch.setattr(dbs, "get_sessionmaker", _boom)
    with pytest.raises(AuthBackendUnavailable):
        find_account_for_login("admin@of1.kr")


# ── 5) 개인정보/비밀값이 로그에 남지 않음 (test 15) ─────────────────────────────────────
def test_no_secret_in_logs_on_backend_error(tmp_path, monkeypatch, capsys):
    eng = _build_engine(tmp_path, "log.db")
    _bind(monkeypatch, eng)
    from backend.services.accounts_service import AuthBackendUnavailable
    monkeypatch.setattr("backend.routers.auth._find_account_for_login",
                        lambda _lid: (_ for _ in ()).throw(AuthBackendUnavailable("ProgrammingError")))
    with pytest.raises(HTTPException):
        _login("admin@of1.kr", _PW)
    out = capsys.readouterr()
    blob = (out.out + out.err)
    assert _PW not in blob            # 비밀번호 평문 없음
    assert "password_hash" not in blob
    # 오류 클래스명만 남는다(진단 가능, PII 없음).
    assert "AUTH_BACKEND_UNAVAILABLE" in blob
