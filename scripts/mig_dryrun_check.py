"""PostgreSQL 전용 migration dry-run 검증 (0030 → head=0031, fixture + partial-unique + idempotency).

**실제 PostgreSQL 에서만** 의미가 있다(SQLite 대체 아님). CI(postgres:16 서비스 컨테이너)에서
빈 DB 를 대상으로 실행한다. 운영/실데이터 DB 에는 실행하지 않는다.

절차:
  1. 0030(f8a9b0c10030)까지 upgrade
  2. 기존 tenant(active) + active user 3 + inactive user 1 fixture 삽입 (0031 이전 컬럼만)
  3. head(0031)까지 upgrade
  4. 검증: tenant/user 수 불변, seat_limit=max(2, active user 수)=3, service_status='active',
     inactive user account_status='disabled'
  5. partial unique(uq_office_app_approved_tenant): approved_tenant_id NULL 다중 허용,
     동일 non-null 값 2건은 충돌
  6. downgrade -1(0031→0030) 후 재 upgrade head → 멱등성 + seat_limit 재backfill 동일(3)

환경변수 DATABASE_URL(postgresql+psycopg://...) 필요. 종료코드 0=성공.
"""
import os
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

REV_0030 = "f8a9b0c10030"


def _fail(msg: str):
    print(f"[DRYRUN][FAIL] {msg}")
    sys.exit(1)


def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        _fail("DATABASE_URL not set")
    cfg = Config("alembic.ini")
    engine = create_engine(url, future=True)

    print("[DRYRUN] upgrade -> 0030")
    command.upgrade(cfg, REV_0030)

    print("[DRYRUN] insert fixture at 0030")
    with engine.begin() as c:
        c.execute(text("INSERT INTO tenants (tenant_id, office_name, is_active) "
                       "VALUES ('legacy', '레거시사무소', true)"))
        for i in range(3):  # active user 3명
            c.execute(text("INSERT INTO users (login_id, tenant_id, password_hash, is_admin, is_active) "
                           f"VALUES ('legacy-u{i}', 'legacy', 'x', {'true' if i == 0 else 'false'}, true)"))
        c.execute(text("INSERT INTO users (login_id, tenant_id, password_hash, is_admin, is_active) "
                       "VALUES ('legacy-off', 'legacy', 'x', false, false)"))  # inactive 1명

    with engine.begin() as c:
        t_before = c.execute(text("SELECT count(*) FROM tenants")).scalar()
        u_before = c.execute(text("SELECT count(*) FROM users")).scalar()

    print("[DRYRUN] upgrade -> head (0031)")
    command.upgrade(cfg, "head")

    with engine.begin() as c:
        t_after = c.execute(text("SELECT count(*) FROM tenants")).scalar()
        u_after = c.execute(text("SELECT count(*) FROM users")).scalar()
        if (t_before, u_before) != (t_after, u_after):
            _fail(f"row counts changed: tenants {t_before}->{t_after}, users {u_before}->{u_after}")
        seat = c.execute(text("SELECT seat_limit FROM tenants WHERE tenant_id='legacy'")).scalar()
        if seat != 3:
            _fail(f"seat_limit backfill expected 3 (max(2,active=3)), got {seat}")
        sstatus = c.execute(text("SELECT service_status FROM tenants WHERE tenant_id='legacy'")).scalar()
        if sstatus != "active":
            _fail(f"service_status backfill expected 'active', got {sstatus!r}")
        off_status = c.execute(text("SELECT account_status FROM users WHERE login_id='legacy-off'")).scalar()
        if off_status != "disabled":
            _fail(f"inactive user account_status expected 'disabled', got {off_status!r}")
        act_status = c.execute(text("SELECT account_status FROM users WHERE login_id='legacy-u0'")).scalar()
        if act_status != "active":
            _fail(f"active user account_status expected 'active', got {act_status!r}")
    print("[DRYRUN] fixture backfill OK (counts unchanged, seat_limit=3, statuses correct)")

    print("[DRYRUN] partial unique index check")
    with engine.begin() as c:
        c.execute(text("INSERT INTO office_applications (application_id, status, office_name) "
                       "VALUES ('A1','approved','o1'), ('A2','approved','o2')"))  # approved_tenant_id NULL 다중 허용
        c.execute(text("UPDATE office_applications SET approved_tenant_id='dup' WHERE application_id='A1'"))
    conflict = False
    try:
        with engine.begin() as c:
            c.execute(text("UPDATE office_applications SET approved_tenant_id='dup' WHERE application_id='A2'"))
    except IntegrityError:
        conflict = True
    if not conflict:
        _fail("partial unique uq_office_app_approved_tenant did NOT reject duplicate non-null tenant")
    print("[DRYRUN] partial unique OK (NULL multi allowed, duplicate non-null rejected)")

    print("[DRYRUN] downgrade -1 then re-upgrade head (idempotency)")
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")
    with engine.begin() as c:
        seat2 = c.execute(text("SELECT seat_limit FROM tenants WHERE tenant_id='legacy'")).scalar()
        if seat2 != 3:
            _fail(f"seat_limit after re-upgrade expected 3, got {seat2}")
    print("[DRYRUN] idempotency OK")
    print("[DRYRUN][PASS] 0030->0031 PostgreSQL dry-run passed")


if __name__ == "__main__":
    main()
