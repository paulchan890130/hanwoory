"""배포 게이트 / 재발방지 — SEV-1(관리자 로그인 장애) 회귀 클래스 자동 차단.

사고 재발방지(코드 흐름에 바로 포함 가능한 정적 가드 + 인증 smoke):
1. import 이름 충돌 감지 — 로그인 라우터에서 import 별칭을 로컬 def 가 가리면 실패
   (회귀 ②: 로컬 `_is_system_admin(dict)` 이 import `is_system_admin(str)` 을 가려 성공경로 500).
2. deferred ORM 컬럼의 로그인 경로 접근 감지 — `find_account_for_login` 은 deferred 컬럼명을
   전혀 참조하지 않고, `_row_from_pg` 는 deferred 컬럼을 **직접 속성 접근**하지 않는다
   (회귀 ①: deferred getattr 가 lazy SELECT → 미적용 migration DB 에서 UndefinedColumn 500).
3. 인증 smoke — HTTP 로그인 성공 → /api/auth/me 200, 잘못된 자격증명 → 401.
"""
from __future__ import annotations

import ast
import inspect
import os

import pytest
from sqlalchemy import BigInteger, create_engine, inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker


# ── 1) import 이름 충돌(shadowing) 정적 감지 ────────────────────────────────────
def _module_file(modname: str) -> str:
    mod = __import__(modname, fromlist=["__file__"])
    return mod.__file__


def _imported_names_and_local_defs(path: str):
    """모듈 최상위에서 import 로 바인딩된 이름들과, def/class/대입으로 바인딩된 이름들."""
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    imported: dict[str, int] = {}
    local_defs: dict[str, int] = {}
    for node in tree.body:  # 최상위만(함수 내부 지역 import 는 충돌 아님)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imported.setdefault(name, node.lineno)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local_defs.setdefault(node.name, node.lineno)
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    local_defs.setdefault(tgt.id, node.lineno)
    return imported, local_defs


@pytest.mark.parametrize("modname", [
    "backend.routers.auth",
    "backend.services.accounts_service",
])
def test_no_import_name_shadowed_by_local_def(modname):
    """로그인 critical-path 모듈에서 import 별칭을 로컬 def/class/대입이 가리면 안 된다."""
    path = _module_file(modname)
    imported, local_defs = _imported_names_and_local_defs(path)
    collisions = {n: (imported[n], local_defs[n]) for n in imported.keys() & local_defs.keys()}
    assert not collisions, (
        f"{modname}: import 이름이 로컬 정의로 가려짐(shadowing) → 런타임 오호출 위험. "
        f"{ {n: f'import@L{i}, redef@L{d}' for n,(i,d) in collisions.items()} }"
    )


# ── 2) deferred 컬럼의 로그인 경로 접근 정적 감지 ───────────────────────────────
def _deferred_column_names():
    from backend.db.models.user import AccountUser
    from backend.db.models.tenant import Tenant
    names = set()
    for model in (AccountUser, Tenant):
        for attr in sa_inspect(model).column_attrs:
            if getattr(attr, "deferred", False):
                names.add(attr.key)
    return names


def test_deferred_columns_detected():
    """가드가 의미 있으려면 최소한 알려진 deferred 컬럼이 감지돼야 한다(회귀 앵커)."""
    d = _deferred_column_names()
    assert {"role", "source_application_id"} <= d, f"deferred set 예상과 다름: {sorted(d)}"


def test_find_account_for_login_never_names_deferred_columns():
    """로그인 전용 조회가 deferred 컬럼을 **속성으로 접근**하지 않아야 한다 — 명시 projection 이
    deferred 컬럼(예: AccountUser.role / Tenant.source_application_id)을 건드리면 lazy-load 500 재발.
    (docstring/주석의 컬럼명 언급은 무시하도록 AST Attribute 접근만 검사한다.)"""
    from backend.services.accounts_service import find_account_for_login
    deferred = _deferred_column_names()
    tree = ast.parse(inspect.getsource(find_account_for_login).lstrip())
    bad = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in deferred]
    assert not bad, (
        f"find_account_for_login 이 deferred 컬럼을 속성 접근함 → lazy-load 500 위험: {sorted(set(bad))}"
    )


def test_row_from_pg_has_no_bare_deferred_attribute_access():
    """_row_from_pg 는 deferred 컬럼을 **직접 속성 접근(u.role/t.source_application_id)** 하지
    않는다 — 값은 반드시 _loaded_attr(문자열 인자)로만 읽어 lazy-load 를 피한다."""
    from backend.services import accounts_service
    deferred = _deferred_column_names()
    src = inspect.getsource(accounts_service._row_from_pg)
    tree = ast.parse(src.lstrip())
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in deferred:
            # obj.<deferred> 형태의 직접 접근(예: u.role) — 금지
            bad.append(node.attr)
    assert not bad, (
        f"_row_from_pg 가 deferred 컬럼을 직접 속성 접근함(lazy-load 위험): {sorted(set(bad))}. "
        f"_loaded_attr(obj, '<name>') 로만 읽어야 함."
    )


# ── 3) 인증 smoke (HTTP login → /me) ────────────────────────────────────────────
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


@pytest.fixture
def client(monkeypatch, tmp_path):
    from backend.db.base import Base
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.models.user_session import UserSession
    from backend.db.models.activation_token import ActivationToken
    from backend.services.accounts_service import hash_password

    engine = create_engine(f"sqlite:///{tmp_path / 'gate.db'}", future=True)
    Base.metadata.create_all(engine, tables=[
        Tenant.__table__, AccountUser.__table__, UserSession.__table__, ActivationToken.__table__,
    ])
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "get_sessionmaker", lambda: SessionLocal)
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    # 로그인 부수효과(잠금/감사/보안)는 별도 테이블 → 이 smoke 범위 밖이므로 no-op 격리.
    monkeypatch.setattr("backend.services.login_guard_pg_service.check_locked", lambda *a, **k: None)
    monkeypatch.setattr("backend.services.login_guard_pg_service.record_failure", lambda *a, **k: False)
    monkeypatch.setattr("backend.services.login_guard_pg_service.record_success", lambda *a, **k: None)
    monkeypatch.setattr("backend.services.audit_service.log_event", lambda *a, **k: None)
    monkeypatch.setattr("backend.services.account_security_pg_service.record_event", lambda *a, **k: None)
    monkeypatch.setattr("backend.services.account_security_pg_service.is_security_blocked", lambda *a, **k: False)
    monkeypatch.setattr("backend.services.account_security_pg_service.evaluate_suspicion", lambda *a, **k: None)
    monkeypatch.setenv("FEATURE_APPROVED_SAAS", "0")
    monkeypatch.setenv("FEATURE_SINGLE_SESSION", "0")
    monkeypatch.setenv("JWT_SECRET_KEY", "gate-smoke-secret")

    with SessionLocal() as s:
        s.add(Tenant(tenant_id="of-1", office_name="office-smoke", is_active=True))
        s.add(AccountUser(login_id="admin@of1.kr", tenant_id="of-1",
                          password_hash=hash_password(_PW), is_admin=True, is_active=True))
        s.commit()

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.routers import auth as auth_router
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/auth")
    return TestClient(app)


def test_auth_smoke_login_then_me(client):
    r = client.post("/api/auth/login", json={"login_id": "admin@of1.kr", "password": _PW})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    assert token
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json().get("login_id") == "admin@of1.kr"


def test_auth_smoke_wrong_password_401(client):
    r = client.post("/api/auth/login", json={"login_id": "admin@of1.kr", "password": "nope"})
    assert r.status_code == 401
