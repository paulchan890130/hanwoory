"""Targeted test for the OCR scan → customer add PG path.

Validates ``backend/routers/scan.py::scan_register`` when
``FEATURE_PG_CUSTOMERS=true`` (the current PostgreSQL runtime). Uses a
throwaway SQLite DB and monkeypatches the sessionmaker, so it touches no
real database and writes no production data.

Run (from repo root, venv active)::

    python backend/scripts/test_scan_register_pg.py

Covers: new-by-passport, new-by-passport+ARC, update-by-passport (no
duplicate, empty field doesn't overwrite), update-by-ARC, tenant isolation,
and empty-payload rejection (400, no row inserted).
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ["FEATURE_PG_CUSTOMERS"] = "true"

from sqlalchemy import BigInteger, create_engine, text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker


# SQLite doesn't autoincrement BIGINT primary keys; render BigInteger as INTEGER
# for the test DB only (real Postgres handles BIGINT identity natively).
@compiles(BigInteger, "sqlite")
def _bigint_as_integer_sqlite(type_, compiler, **kw):  # noqa: ANN001
    return "INTEGER"


import backend.db.session as dbsession
from backend.db.base import Base
from backend.db.models.tenant import Tenant
from backend.db.models.customer import Customer


def _setup():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(engine, tables=[Tenant.__table__, Customer.__table__])
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO tenants (id, tenant_id, office_name) "
            "VALUES (1,'t1','Office1'),(2,'t2','Office2')"
        ))
    dbsession.get_sessionmaker = lambda: Session
    return engine, tmp.name


def main() -> int:
    engine, dbpath = _setup()
    from backend.routers.scan import scan_register
    from backend.services.customer_pg_service import list_customers
    from fastapi import HTTPException

    U1 = {"tenant_id": "t1", "sub": "u1"}
    U2 = {"tenant_id": "t2", "sub": "u2"}
    state = {"ok": True}

    def check(name, cond):
        print(("PASS" if cond else "FAIL"), name)
        state["ok"] = state["ok"] and bool(cond)

    # 1) New customer by passport-only OCR
    r = scan_register({"여권": "M12345678", "성": "KIM", "명": "MINSU",
                       "한글": "김민수", "만기": "2030-01-01"}, U1)
    check("1 passport-only created", r["status"] == "created" and bool(r["고객ID"]))
    cid1 = r["고객ID"]
    rows = list_customers("t1")
    check("1 customer in DB", any(c["여권"] == "M12345678" and c["고객ID"] == cid1 for c in rows))
    c1 = [c for c in rows if c["고객ID"] == cid1][0]
    check("1 fields stored", c1["한글"] == "김민수" and c1["만기"] == "2030-01-01")

    # 2) New customer by passport + ARC OCR
    r = scan_register({"여권": "P99", "등록증": "123456", "번호": "7654321",
                       "한글": "이영희", "발급일": "2025-05-05", "만기일": "2028-05-05"}, U1)
    check("2 passport+ARC created", r["status"] == "created")
    cid2 = r["고객ID"]
    check("2 unique id", cid2 != cid1)
    arc = [c for c in list_customers("t1") if c["고객ID"] == cid2][0]
    check("2 ARC fields stored",
          arc["등록증"] == "123456" and arc["번호"] == "7654321" and arc["만기일"] == "2028-05-05")

    # 3) Existing customer update by passport — no duplicate, empty doesn't overwrite
    before = len(list_customers("t1"))
    r = scan_register({"여권": "M12345678", "만기": "2031-12-31", "주소": "Seoul", "한글": ""}, U1)
    check("3 updated status", r["status"] == "updated" and r["고객ID"] == cid1)
    check("3 no duplicate", before == len(list_customers("t1")))
    upd = [c for c in list_customers("t1") if c["고객ID"] == cid1][0]
    check("3 expiry updated", upd["만기"] == "2031-12-31")
    check("3 address added", upd["주소"] == "Seoul")
    check("3 empty korean-name did NOT overwrite", upd["한글"] == "김민수")

    # 3b) Update by ARC match
    r = scan_register({"등록증": "123456", "번호": "7654321", "만기일": "2029-09-09"}, U1)
    check("3b ARC update", r["status"] == "updated" and r["고객ID"] == cid2)
    check("3b ARC expiry updated",
          [c for c in list_customers("t1") if c["고객ID"] == cid2][0]["만기일"] == "2029-09-09")

    # 4) Tenant isolation
    t1c = len(list_customers("t1"))
    r = scan_register({"여권": "M12345678", "한글": "다른테넌트"}, U2)
    check("4 created under t2", r["status"] == "created")
    check("4 t2 has row", any(c["여권"] == "M12345678" for c in list_customers("t2")))
    check("4 t1 count unchanged", len(list_customers("t1")) == t1c)
    check("4 t1 not polluted", all(c["한글"] != "다른테넌트" for c in list_customers("t1")))

    # 5) Empty payload → 400, no row inserted
    t1b = len(list_customers("t1"))
    try:
        scan_register({"국가": "", "생년월일": ""}, U1)
        check("5 empty payload rejected", False)
    except HTTPException as e:
        check("5 empty payload 400", e.status_code == 400)
    check("5 no row inserted", len(list_customers("t1")) == t1b)

    print("\nRESULT:", "ALL PASS" if state["ok"] else "SOME FAILED")
    engine.dispose()
    try:
        os.unlink(dbpath)
    except OSError:
        pass  # Windows may still hold the handle briefly; harmless.
    return 0 if state["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
