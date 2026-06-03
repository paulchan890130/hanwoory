"""Integration test for migrate_account_password_hashes.py (simulated PG).

Run: python backend/scripts/test_account_pw_migration.py
Uses throwaway SQLite + monkeypatched session/guard; touches no real DB and
prints no raw password.
"""
from __future__ import annotations
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

from sqlalchemy import BigInteger, create_engine, select, text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

@compiles(BigInteger, "sqlite")
def _bi(t, c, **k): return "INTEGER"

import backend.db.session as dbsession
import backend.db.local_guard as guard
from backend.db.base import Base
from backend.db.models.tenant import Tenant
from backend.db.models.user import AccountUser
import backend.scripts.migrate_account_password_hashes as mig

_ok = {"v": True}
def check(n, c): print(("PASS" if c else "FAIL"), n); _ok["v"] = _ok["v"] and bool(c)

# legacy jpup hash from the snapshot (authoritative source)
src = mig._discover_source()
assert src, "snapshot with Accounts tab required for this test"
legacy = mig._read_legacy_hashes(src)
jpup_hash = legacy.get("jpup")
assert jpup_hash, "jpup legacy hash must exist"

def fresh_db():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng, tables=[Tenant.__table__, AccountUser.__table__])
    S = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
    with eng.begin() as c:
        c.execute(text("INSERT INTO tenants (id, tenant_id, office_name, is_active) VALUES (1,'jpup','JP',1)"))
    return eng, S, tmp.name

def patch(S):
    dbsession.get_sessionmaker = lambda: S
    dbsession.is_configured = lambda: True
    guard.assert_local_database_url = lambda url: None  # bypass loopback check in test
    os.environ["DATABASE_URL"] = "postgresql://localhost:5432/test"

def seed_user(S, ph):
    with S() as s:
        u = s.scalar(select(AccountUser).where(AccountUser.login_id=="jpup"))
        if u is None:
            s.add(AccountUser(login_id="jpup", tenant_id="jpup", password_hash=ph, is_admin=False, is_active=True))
        else:
            u.password_hash = ph
        s.commit()

def get_hash(S):
    with S() as s:
        return s.scalar(select(AccountUser).where(AccountUser.login_id=="jpup")).password_hash

def run(argv):
    old = sys.argv[:]
    sys.argv = ["migrate_account_password_hashes.py"] + argv
    try: return mig.main()
    finally: sys.argv = old

# Case A: WRONG hash -> dry-run plans update (rc 0, no change), apply fixes it
eng, S, path = fresh_db(); patch(S); seed_user(S, "WRONGPLACEHOLDERHASH====")
rc = run(["--login-id","jpup","--dry-run"])
check("A dry-run rc=0", rc == 0)
check("A dry-run did NOT change row", get_hash(S) == "WRONGPLACEHOLDERHASH====")
rc = run(["--login-id","jpup","--apply"])
check("A apply rc=0", rc == 0)
check("A apply restored legacy hash", get_hash(S) == jpup_hash)
eng.dispose(); 
try: os.unlink(path)
except OSError: pass

# Case B: EMPTY hash -> apply fills it
eng, S, path = fresh_db(); patch(S); seed_user(S, "")
rc = run(["--login-id","jpup","--apply"])
check("B empty filled with legacy", get_hash(S) == jpup_hash)
eng.dispose()
try: os.unlink(path)
except OSError: pass

# Case C: ALREADY correct -> idempotent skip (no plan)
eng, S, path = fresh_db(); patch(S); seed_user(S, jpup_hash)
rc = run(["--login-id","jpup","--apply"])
check("C idempotent rc=0", rc == 0)
check("C unchanged", get_hash(S) == jpup_hash)
eng.dispose()
try: os.unlink(path)
except OSError: pass

# Case D: login missing from source -> refuse (rc 3), no invention
eng, S, path = fresh_db(); patch(S)
rc = run(["--login-id","ghost_not_in_snapshot","--apply"])
check("D missing-source login refused (rc=3)", rc == 3)
eng.dispose()
try: os.unlink(path)
except OSError: pass

print("\nRESULT:", "ALL PASS" if _ok["v"] else "SOME FAILED")
sys.exit(0 if _ok["v"] else 1)
