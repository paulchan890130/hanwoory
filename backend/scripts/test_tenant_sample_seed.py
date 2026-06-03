"""Targeted test for tenant onboarding sample seeding (PG path).

Run (repo root, venv active): python backend/scripts/test_tenant_sample_seed.py
Uses throwaway SQLite + monkeypatched sessionmaker; touches no real DB.
Covers: seed-when-empty, no-duplicate-on-rerun, existing-data-not-overwritten,
clear sample markers, link consistency, and sample removal.
"""
import sys, os, tempfile
sys.path.insert(0, os.getcwd())
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

from sqlalchemy import BigInteger, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

@compiles(BigInteger, "sqlite")
def _bi(t, c, **k): return "INTEGER"
@compiles(JSONB, "sqlite")
def _jb(t, c, **k): return "JSON"

import backend.db.session as dbsession
from backend.db.base import Base
from backend.db.models.tenant import Tenant
from backend.db.models.work_data import WorkReferenceSheet, WorkReferenceRow
from backend.db.models.certification import CertVendor, CertDirection, CertGroup, CertRegion, CertPrice

tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
engine = create_engine(f"sqlite:///{tmp.name}")
tables = [Tenant.__table__, WorkReferenceSheet.__table__, WorkReferenceRow.__table__,
          CertVendor.__table__, CertDirection.__table__, CertGroup.__table__,
          CertRegion.__table__, CertPrice.__table__]
Base.metadata.create_all(engine, tables=tables)
Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
with engine.begin() as conn:
    conn.execute(text("INSERT INTO tenants (id, tenant_id, office_name) VALUES (1,'newt','New'),(2,'realt','Real')"))
dbsession.get_sessionmaker = lambda: Session

from backend.services.tenant_sample_seed_service import (
    seed_new_tenant_sample_data, remove_tenant_sample_data,
    SAMPLE_SEED_VERSION, SAMPLE_NOTE,
)
from backend.services.reference_pg_service import list_sheets, get_sheet_data
from backend.services.certification_pg_service import bootstrap

ok = {"v": True}
def check(n, c):
    print(("PASS" if c else "FAIL"), n); ok["v"] = ok["v"] and bool(c)

# 1) New empty tenant -> seed
r = seed_new_tenant_sample_data("newt")
check("1 reference rows seeded", r["reference_rows"] == 7)
check("1 cert counts", r["certification"] == {"vendors":1,"directions":2,"groups":4,"regions":4,"prices":5})
sheets = set(list_sheets("newt")["sheets"])
check("1 two sample sheets", sheets == {"사용안내","체류민원 예시"})
b = bootstrap("newt")
check("1 cert seeded", len(b["directions"])==2 and len(b["groups"])==4 and len(b["regions"])==4 and len(b["prices"])==5)

# 5) clearly marked
guide = get_sheet_data("newt","사용안내")
check("5 guide note in 비고", all(row.get("비고")==SAMPLE_NOTE for row in guide["rows"]))
check("5 guide hidden marker", all(row.get("_sample_seed")==SAMPLE_SEED_VERSION for row in guide["rows"]))
check("5 group [예시] prefix", all(g["group_name"].startswith("[예시]") for g in b["groups"]))
check("5 price source marker", all(p["source"]==SAMPLE_SEED_VERSION for p in b["prices"]))
check("5 price blank (no misleading amount)", all(p["price"]=="" for p in b["prices"]))
# linking consistency: price.group_id must exist in groups; region/direction names exist
gids = {g["id"] for g in b["groups"]}; dnames={d["name"] for d in b["directions"]}; rnames={r2["name"] for r2 in b["regions"]}
check("5 price links valid", all(p["group_id"] in gids and p["direction"] in dnames and p["region"] in rnames for p in b["prices"]))

# 2) Re-run -> no duplicates
r2 = seed_new_tenant_sample_data("newt")
check("2 reference skip", r2["reference_rows"] == 0)
check("2 cert skip", all(v==0 for v in r2["certification"].values()))
check("2 still 2 sheets", set(list_sheets("newt")["sheets"]) == {"사용안내","체류민원 예시"})
check("2 still 5 prices", len(bootstrap("newt")["prices"]) == 5)

# 3/4) Existing tenant with real data -> not overwritten, seed skipped
with Session() as s:
    s.add(WorkReferenceSheet(tenant_id="realt", sheet_name="내자료", headers=["a"]))
    s.add(WorkReferenceRow(tenant_id="realt", sheet_name="내자료", row_index=0, data={"a":"진짜 데이터"}))
    s.add(CertVendor(id="rv1", tenant_id="realt", name="리얼업체", active="TRUE"))
    s.commit()
r3 = seed_new_tenant_sample_data("realt")
check("3 reference skipped (had data)", r3["reference_rows"] == 0)
check("3 cert skipped (had data)", all(v==0 for v in r3["certification"].values()))
rsheets = set(list_sheets("realt")["sheets"])
check("3 real sheet intact, no sample sheets", rsheets == {"내자료"})
check("3 real row preserved", get_sheet_data("realt","내자료")["rows"][0]["a"] == "진짜 데이터")
rb = bootstrap("realt")
check("3 real vendor preserved, no [예시]", len(rb["vendors"])==1 and rb["vendors"][0]["name"]=="리얼업체")

# 6) Removal
rem = remove_tenant_sample_data("newt")
check("6 removed 2 ref sheets", rem["reference_sheets"] == 2)
check("6 sample sheets gone", list_sheets("newt")["sheets"] == [])
nb = bootstrap("newt")
check("6 cert samples gone", all(len(nb[k])==0 for k in ("vendors","groups","regions","prices","directions")))

print("\nRESULT:", "ALL PASS" if ok["v"] else "SOME FAILED")
engine.dispose()
try: os.unlink(tmp.name)
except OSError: pass
sys.exit(0 if ok["v"] else 1)
