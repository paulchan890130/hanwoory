"""관리자 라우터 - 계정 관리 + 워크스페이스 자동 생성"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.auth import (
    get_current_user, require_admin, is_master_login, MASTER_ADMIN_LOGIN_ID,
)
from backend.models import AccountUpdate, AccountCreate, AccountRoleUpdate

router = APIRouter()


def _assert_not_master(login_id: str, action: str) -> None:
    """마스터 계정 보호 — 비활성화/삭제/강등 등 위험 조작을 서버에서 강제 거부한다."""
    if is_master_login(login_id):
        raise HTTPException(
            status_code=403,
            detail={"code": "MASTER_ACCOUNT_PROTECTED",
                    "message": "마스터 계정은 비활성화할 수 없습니다."},
        )


def _user_role(session, u) -> str:
    """AccountUser 의 role 을 가드와 함께 읽는다(0024 미적용 DB → is_admin 기반 폴백)."""
    if is_master_login(u.login_id) or bool(u.is_admin):
        return "admin"
    try:
        from sqlalchemy import select
        from backend.db.models.user import AccountUser
        r = session.scalar(select(AccountUser.role).where(AccountUser.login_id == u.login_id))
        return str(r) if r else "user"
    except Exception:
        return "user"


def _account_role_label(login_id: str, is_admin: bool, role: str) -> str:
    """표시용 권한 라벨: 마스터 / 관리자 / 준 관리자 / 일반 사용자."""
    if is_master_login(login_id):
        return "master"
    if is_admin:
        return "admin"
    if role == "sub_admin":
        return "sub_admin"
    return "user"

@router.post("/bootstrap")
def bootstrap_admin(body: AccountCreate):
    """
    최초 관리자 계정 생성 — 인증 불필요. **PG-only.**
    PG users 에 계정이 하나도 없을 때만 동작(중복 부트스트랩 방지). 1개라도 있으면 403.
    """
    from sqlalchemy import select, func
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker, is_configured
    from backend.services.accounts_service import hash_password, build_account_dict, append_account

    if not is_configured():
        raise HTTPException(status_code=503, detail="PostgreSQL 미구성 — bootstrap 불가.")

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        existing = session.scalar(select(func.count(AccountUser.id)))
    if existing and existing > 0:
        raise HTTPException(
            status_code=403,
            detail="이미 계정이 존재합니다. bootstrap은 최초 1회만 사용 가능합니다. "
                   "계정 추가는 관리자 로그인 후 POST /api/admin/accounts 를 사용하세요.",
        )

    account = build_account_dict(
        login_id=body.login_id,
        password_hash=hash_password(body.password),
        tenant_id=body.tenant_id or "",
        office_name=body.office_name,
        office_adr=body.office_adr or "",
        contact_name=body.contact_name or "",
        contact_tel=body.contact_tel or "",
        biz_reg_no=body.biz_reg_no or "",
        agent_rrn=body.agent_rrn or "",
        is_admin=True,    # bootstrap = 항상 관리자
        is_active=True,
    )
    try:
        append_account(account)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"계정 생성 실패: {e}")

    try:
        import backend.services.tenant_service as _ts
        _ts._TENANT_MAP_CACHE = {}
        _ts._TENANT_MAP_TIME = 0
    except Exception:
        pass

    return {
        "ok": True,
        "login_id": body.login_id.strip(),
        "message": "최초 관리자 계정이 생성되었습니다. 이 엔드포인트는 더 이상 사용할 수 없습니다.",
    }

def _get_service_account_path() -> str:
    """기존 config.py KEY_PATH 구조와 동일한 방식으로 서비스 계정 경로 반환."""
    try:
        from config import KEY_PATH
        return KEY_PATH
    except ImportError:
        # config.py 없을 경우 환경변수 → 기본 경로 순서로 fallback
        return os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "/etc/secrets/hanwoory-9eaa1a4c54d7.json",
        )


class WorkspaceCreateRequest(BaseModel):
    login_id: str
    office_name: str


@router.get("/accounts")
def list_accounts(user: dict = Depends(require_admin)):
    # PG-only(Phase B): 계정 목록은 항상 PostgreSQL.
    from backend.db.feature_flags import local_drive_mock_enabled
    if True:
        from sqlalchemy import select, func
        from backend.db.models.tenant import Tenant
        from backend.db.models.user import AccountUser
        from backend.db.models.customer import Customer
        from backend.db.models.task import ActiveTask, CompletedTask
        from backend.db.models.daily import DailyEntry
        from backend.db.models.work_data import WorkReferenceSheet
        from backend.db.session import get_sessionmaker
        SessionLocal = get_sessionmaker()

        def _classify_file_storage(folder_id: str, customer_key: str, work_key: str) -> tuple[str, str]:
            """Return (status, label) for the file-storage column.

            ``status`` is one of:
              - ``"none"``        — no keys provisioned yet
              - ``"local-mock"``  — keys begin with ``local-`` (sentinel from local_drive_mock)
              - ``"google-drive"`` — looks like a real Google ID
              - ``"partial"``     — some keys are set, others empty
              - ``"mixed"``       — sentinel + real together (shouldn't happen in clean state)
            """
            keys = [folder_id or "", customer_key or "", work_key or ""]
            present = [k for k in keys if k]
            if not present:
                return ("none", "없음")
            local_count = sum(1 for k in present if k.startswith("local-"))
            real_count = len(present) - local_count
            if len(present) < 3:
                if local_count and not real_count:
                    return ("partial", f"로컬 모의 ({len(present)}/3)")
                if real_count and not local_count:
                    return ("partial", f"Google Drive ({len(present)}/3)")
                return ("partial", f"혼합 ({len(present)}/3)")
            if local_count == 3:
                return ("local-mock", "로컬 모의 저장소")
            if real_count == 3:
                return ("google-drive", "Google Drive")
            return ("mixed", f"혼합 (local {local_count} + real {real_count})")

        # Per-tenant business-data presence — single query each, grouped.
        with SessionLocal() as session:
            users = session.scalars(select(AccountUser).order_by(AccountUser.login_id)).all()
            tenants_by_id = {
                t.tenant_id: t for t in session.scalars(select(Tenant)).all()
            }
            # Counts per tenant for the most user-visible domains.
            cust_counts = dict(session.execute(
                select(Customer.tenant_id, func.count(Customer.id))
                .where(Customer.deleted_at.is_(None))
                .group_by(Customer.tenant_id)
            ).all())
            active_counts = dict(session.execute(
                select(ActiveTask.tenant_id, func.count(ActiveTask.id))
                .group_by(ActiveTask.tenant_id)
            ).all())
            completed_counts = dict(session.execute(
                select(CompletedTask.tenant_id, func.count(CompletedTask.id))
                .group_by(CompletedTask.tenant_id)
            ).all())
            daily_counts = dict(session.execute(
                select(DailyEntry.tenant_id, func.count(DailyEntry.id))
                .group_by(DailyEntry.tenant_id)
            ).all())
            ref_counts = dict(session.execute(
                select(WorkReferenceSheet.tenant_id, func.count(WorkReferenceSheet.id))
                .group_by(WorkReferenceSheet.tenant_id)
            ).all())

        is_mock_mode = local_drive_mock_enabled()
        storage_mode = "pg+local-mock" if is_mock_mode else "pg+google-drive"
        records = []
        for u in users:
            t = tenants_by_id.get(u.tenant_id)
            folder = (t.folder_id if t else "") or ""
            ckey = (t.customer_sheet_key if t else "") or ""
            wkey = (t.work_sheet_key if t else "") or ""

            cust = cust_counts.get(u.tenant_id, 0)
            actv = active_counts.get(u.tenant_id, 0)
            comp = completed_counts.get(u.tenant_id, 0)
            dail = daily_counts.get(u.tenant_id, 0)
            ref  = ref_counts.get(u.tenant_id, 0)
            row_total = cust + actv + comp + dail + ref
            pg_status = "ready" if row_total > 0 else "empty"
            pg_label = (
                f"고객 {cust} · 진행 {actv} · 완료 {comp} · 일일 {dail} · 업무참고 {ref}"
                if row_total else "비어있음"
            )

            file_status, file_label = _classify_file_storage(folder, ckey, wkey)
            _role = _user_role(session, u)

            records.append({
                "login_id": u.login_id,
                "tenant_id": u.tenant_id,
                "office_name": (t.office_name if t else "") or "",
                "office_adr": (t.office_adr if t else "") or "",
                "biz_reg_no": (t.biz_reg_no if t else "") or "",
                "agent_rrn": "",  # 원문 절대 미반환(암호문/평문 노출 금지)
                "has_agent_rrn": bool(t and t.agent_rrn_encrypted),
                "agent_rrn_last4": (t.agent_rrn_last4 if t else "") or "",
                "contact_name": u.contact_name or "",
                "contact_tel": u.contact_tel or "",
                "is_admin": "TRUE" if u.is_admin else "FALSE",
                "is_active": "TRUE" if u.is_active else "FALSE",
                "is_master": is_master_login(u.login_id),
                "role": _role,
                # 표시용 권한 라벨: master / admin / sub_admin / user.
                "account_role": _account_role_label(u.login_id, bool(u.is_admin), _role),
                # Raw keys remain in the payload so the workspace flow
                # (which still reads them) keeps working. UI hides them
                # in PG mode in favour of the new status columns.
                "folder_id": folder,
                "work_sheet_key": wkey,
                "customer_sheet_key": ckey,
                "sheet_key": "",
                "created_at": u.created_at.isoformat() if u.created_at else "",
                # Storage status — new fields for the PG-mode UI.
                "storage_mode": storage_mode,
                "pg_storage_status": pg_status,
                "pg_storage_label": pg_label,
                "pg_counts": {
                    "customers": cust, "active_tasks": actv,
                    "completed_tasks": comp, "daily_entries": dail,
                    "work_reference_sheets": ref,
                },
                "file_storage_status": file_status,
                "file_storage_label": file_label,
            })
        return records

    # 도달 불가(PG-only). 안전장치.
    raise HTTPException(status_code=500, detail="account listing misrouted")


@router.put("/accounts/{login_id}")
def update_account(
    login_id: str,
    update: AccountUpdate,
    user: dict = Depends(require_admin),
):
    # PG-only(Phase B): 계정 수정은 항상 PostgreSQL.
    if True:
        from sqlalchemy import select
        from backend.db.models.tenant import Tenant
        from backend.db.models.user import AccountUser
        from backend.db.session import get_sessionmaker
        SessionLocal = get_sessionmaker()
        with SessionLocal() as session:
            u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
            if u is None:
                raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
            # 마스터 계정 보호 — 비활성화/관리자 강등 요청은 서버에서 거부(프론트와 무관).
            if is_master_login(login_id) and (update.is_active is False or update.is_admin is False):
                _assert_not_master(login_id, "update")
            # 마지막 활성 관리자 보호 — 비활성화(is_active=false) 또는 관리자 해제(is_admin=false)가
            # 활성 관리자를 0으로 만들면 차단(인라인 토글 경로도 동일 가드).
            deactivating = update.is_active is False
            demoting = update.is_admin is False
            if (deactivating or demoting) and u.is_admin and u.is_active \
                    and _other_admin_count(session, login_id, active_only=True) == 0:
                raise HTTPException(status_code=409, detail="마지막 관리자 계정은 비활성화하거나 삭제할 수 없습니다.")
            will_deactivate = deactivating and u.is_active
            target_tenant_id = u.tenant_id
            if update.is_active is not None:
                u.is_active = bool(update.is_active)
            if update.is_admin is not None:
                u.is_admin = bool(update.is_admin)
            if update.tenant_id:
                u.tenant_id = update.tenant_id
            if update.contact_name is not None:
                u.contact_name = update.contact_name
            if update.contact_tel is not None:
                u.contact_tel = update.contact_tel
            t = session.scalar(select(Tenant).where(Tenant.tenant_id == u.tenant_id))
            if t is not None:
                if update.office_name is not None: t.office_name = update.office_name
                if update.office_adr is not None: t.office_adr = update.office_adr
                if update.biz_reg_no is not None: t.biz_reg_no = update.biz_reg_no
                if update.folder_id is not None: t.folder_id = update.folder_id
                if update.work_sheet_key is not None: t.work_sheet_key = update.work_sheet_key
                if update.customer_sheet_key is not None: t.customer_sheet_key = update.customer_sheet_key
                if update.is_active is not None: t.is_active = bool(update.is_active)
            session.commit()
        # 인라인 토글로 비활성화한 경우에도 기존 세션 즉시 revoke.
        if will_deactivate:
            try:
                from backend.services.session_pg_service import revoke_active_sessions
                revoke_active_sessions(login_id, reason="account_disabled", only_non_kiosk=False)
            except Exception:
                pass
            _audit_account("ACCOUNT_DISABLED", user, login_id, target_tenant_id, {"via": "update"})
        # tenant_service 맵 캐시 초기화
        try:
            import backend.services.tenant_service as _ts
            _ts._TENANT_MAP_CACHE = {}
            _ts._TENANT_MAP_TIME = 0
        except Exception:
            pass
        return {"ok": True}

    raise HTTPException(status_code=500, detail="account update misrouted")  # 도달 불가


# ── 행정사 주민등록번호(agent_rrn) — 암호화 저장 전용 (Phase I-1J-6E) ──────────────
# 원문은 절대 응답에 내려주지 않는다. 상태(has/last4)만 노출한다.
class AgentRrnUpdate(BaseModel):
    agent_rrn: Optional[str] = ""   # 빈 값/None → 삭제


def _agent_rrn_status(t) -> dict:
    return {
        "has_agent_rrn": bool(t and t.agent_rrn_encrypted),
        "agent_rrn_last4": (t.agent_rrn_last4 if t else "") or "",
    }


@router.get("/accounts/{login_id}/agent-rrn")
def get_agent_rrn_status(login_id: str, user: dict = Depends(require_admin)):
    """행정사 주민번호 등록 상태만 반환(원문/암호문 미노출)."""
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == u.tenant_id))
        return _agent_rrn_status(t)


@router.put("/accounts/{login_id}/agent-rrn")
def set_agent_rrn(login_id: str, body: AgentRrnUpdate, user: dict = Depends(require_admin)):
    """행정사 주민번호를 **암호화**해 저장하거나(빈 값이면) 삭제. 원문은 응답에 미포함.
    key 미설정 시 503, 형식 오류 시 400(메시지에 평문 없음)."""
    from sqlalchemy import select
    from datetime import datetime, timezone
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services.pii_crypto import (
        encrypt_agent_rrn, rrn_last4, validate_rrn_format,
        PiiKeyMissing, RrnFormatError,
    )

    raw = (body.agent_rrn or "").strip()
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == u.tenant_id))
        if t is None:
            raise HTTPException(status_code=404, detail="테넌트를 찾을 수 없습니다.")

        if not raw:
            # 삭제(빈 값 저장) — 암호문/표시값 제거.
            t.agent_rrn_encrypted = None
            t.agent_rrn_last4 = None
            t.agent_rrn_updated_at = datetime.now(timezone.utc)
            session.commit()
            return _agent_rrn_status(t)

        if not validate_rrn_format(raw):
            raise HTTPException(status_code=400, detail="주민등록번호 형식이 올바르지 않습니다.")
        try:
            cipher = encrypt_agent_rrn(raw)
        except PiiKeyMissing:
            raise HTTPException(status_code=503, detail="암호화 키가 설정되지 않아 저장할 수 없습니다.")
        except RrnFormatError:
            raise HTTPException(status_code=400, detail="주민등록번호 형식이 올바르지 않습니다.")
        t.agent_rrn_encrypted = cipher
        t.agent_rrn_last4 = rrn_last4(raw)
        t.agent_rrn_updated_at = datetime.now(timezone.utc)
        session.commit()
        return _agent_rrn_status(t)


def _other_admin_count(session, exclude_login_id: str, active_only: bool) -> int:
    """exclude_login_id 를 제외한 관리자 수. active_only=True 면 활성 관리자만."""
    from sqlalchemy import select, func
    from backend.db.models.user import AccountUser
    stmt = select(func.count()).select_from(AccountUser).where(
        AccountUser.is_admin.is_(True),
        AccountUser.login_id != exclude_login_id,
    )
    if active_only:
        stmt = stmt.where(AccountUser.is_active.is_(True))
    return int(session.scalar(stmt) or 0)


# 계정 라이프사이클/보안 메타데이터 — "업무 데이터"가 아니라 계정 자체에 딸린 상태라
# 연결데이터 차단 대상에서 제외하고, 완전삭제 시 함께 정리한다(감사 로그 audit_logs 는
# 별개로 항상 보존). login_attempts 는 tenant_id 컬럼이 없어 이 introspection 대상이 아니다.
_ACCOUNT_LIFECYCLE_TABLES = {"login_events", "account_security", "security_notifications",
                            "user_terms_acceptances"}
# 완전삭제 시 함께 삭제(감사 목적 보존 대상 아님). login_id 컬럼 기준.
_PERSONAL_CLEANUP_TABLES_BY_LOGIN_ID = ("user_sessions", "login_attempts", "account_security")
# recipient_login_id 기준(자신에게 온 알림만 — related_login_id 로 자신을 "언급"하는
# 다른 사람의 알림은 남긴다).
_PERSONAL_CLEANUP_TABLES_BY_RECIPIENT = ("security_notifications",)
# tenant_id 기준(로그인 이력 등, tenant 삭제 시 함께 정리).
_PERSONAL_CLEANUP_TABLES_BY_TENANT_ID = ("login_events", "user_terms_acceptances")

# 연결 업무 데이터 중 "이관 정책이 확정된" 테이블만 자동 이관한다. 나머지(tasks/daily/
# events/memos/documents/finance/signatures/roi_presets 등)는 정책이 없으므로 발견되면
# 완전삭제를 막고 구체적으로 보고한다(3-7) — 임의로 강제 이관하지 않는다.
# unique_cols: 이관 시 대상 tenant 와 충돌 가능한 자연키(있으면 사전 충돌검사).
MIGRATABLE_TENANT_TABLES: dict[str, list[str] | None] = {
    "cert_directions": None,
    "cert_groups": None,
    "cert_prices": None,
    "cert_regions": None,
    "cert_vendors": None,
    "customers": ["customer_id"],
    "work_reference_sheets": ["sheet_name"],
    "work_reference_rows": ["sheet_name", "row_index"],
}


def _connected_data_summary(session, tenant_id: str) -> dict:
    """해당 tenant 에 연결된 업무 데이터 건수(0 이면 완전삭제 안전).

    information_schema 로 tenant_id 컬럼을 가진 테이블을 찾아 행 수를 센다(스키마 적응형).
    계정/세션/인프라/계정 라이프사이클 테이블은 제외(이들은 삭제 절차에서 직접 정리하거나
    감사 목적으로 보존). 테이블명은 information_schema 출처라 인젝션 위험 없음, tenant_id
    는 파라미터 바인딩.
    """
    from sqlalchemy import text
    exclude = {"users", "tenants", "user_sessions", "signature_pad_tokens", "audit_logs"} | _ACCOUNT_LIFECYCLE_TABLES
    counts: dict = {}
    try:
        rows = session.execute(text(
            "select table_name from information_schema.columns "
            "where table_schema='public' and column_name='tenant_id'"
        )).fetchall()
    except Exception:
        return counts
    for (tbl,) in rows:
        if tbl in exclude:
            continue
        try:
            n = session.execute(
                text(f'select count(*) from "{tbl}" where tenant_id = :tid'),
                {"tid": tenant_id},
            ).scalar() or 0
        except Exception:
            n = 0
        if n:
            counts[tbl] = int(n)
    return counts


def _migration_candidates(session, exclude_login_id: str) -> list[dict]:
    """연결 데이터 이관 대상으로 선택 가능한 계정 — 활성 + 자기 자신 아님.
    tenant 제한 없음(삭제 대상이 자기 tenant 의 유일한 사용자일 때만 이관이 필요하므로,
    이관 대상은 필연적으로 다른 tenant 소속이다)."""
    from sqlalchemy import select
    from backend.db.models.user import AccountUser
    from backend.db.models.tenant import Tenant
    rows = session.execute(
        select(AccountUser.login_id, AccountUser.tenant_id, AccountUser.is_admin, Tenant.office_name)
        .join(Tenant, Tenant.tenant_id == AccountUser.tenant_id)
        .where(AccountUser.is_active.is_(True), AccountUser.login_id != exclude_login_id)
        .order_by(AccountUser.login_id)
    ).all()
    return [{"login_id": r[0], "tenant_id": r[1], "is_admin": bool(r[2]), "office_name": r[3]} for r in rows]


def _collision_check(session, table: str, unique_cols: list[str], old_tenant: str, new_tenant: str) -> list[dict]:
    """이관 시 대상 tenant 와 자연키가 충돌하는 행 나열(비어 있으면 이관 안전)."""
    from sqlalchemy import text
    cols_sql = ", ".join(f'a."{c}"' for c in unique_cols)
    join_cond = " AND ".join(f'a."{c}" = b."{c}"' for c in unique_cols)
    rows = session.execute(text(
        f'SELECT {cols_sql} FROM "{table}" a JOIN "{table}" b ON {join_cond} '
        f'WHERE a.tenant_id = :old_t AND b.tenant_id = :new_t'
    ), {"old_t": old_tenant, "new_t": new_tenant}).all()
    return [dict(zip(unique_cols, r)) for r in rows]


def _migrate_tenant_data(session, old_tenant: str, new_tenant: str) -> dict:
    """MIGRATABLE_TENANT_TABLES 를 old_tenant → new_tenant 로 이관(같은 트랜잭션 내 호출 전제).
    호출 전 충돌검사·비이관대상 테이블 검사가 끝났다고 가정한다(이 함수는 검사하지 않음)."""
    from sqlalchemy import text
    migrated: dict = {}
    for table in MIGRATABLE_TENANT_TABLES:
        n = session.execute(
            text(f'UPDATE "{table}" SET tenant_id = :new_t WHERE tenant_id = :old_t'),
            {"new_t": new_tenant, "old_t": old_tenant},
        ).rowcount
        if n:
            migrated[table] = n
    return migrated


def _audit_account(action: str, actor: dict, target_login_id: str, tenant_id: str, payload: dict | None = None) -> None:
    """계정 상태 변경 감사 로그(best-effort, FEATURE_PG_AUDIT off면 no-op)."""
    try:
        from backend.services.audit_service import log_event
        log_event(action=action, actor_login_id=str(actor.get("login_id", "")) or None,
                  tenant_id=tenant_id or None, target_type="account",
                  target_id=target_login_id, payload=payload)
    except Exception:
        pass


def _bust_tenant_cache() -> None:
    try:
        import backend.services.tenant_service as _ts
        _ts._TENANT_MAP_CACHE = {}
        _ts._TENANT_MAP_TIME = 0
    except Exception:
        pass


@router.delete("/accounts/{login_id}")
def delete_account(
    login_id: str,
    user: dict = Depends(require_admin),
):
    """계정 비활성화 (소프트 삭제). is_active=FALSE → 다음 요청부터 즉시 차단 + 세션 revoke."""
    login_id = login_id.strip()
    if login_id == str(user.get("login_id", "")).strip():
        raise HTTPException(status_code=400, detail="자신의 계정은 비활성화할 수 없습니다.")
    _assert_not_master(login_id, "deactivate")   # 마스터 계정 비활성화 금지(서버 강제)
    # PG-only(Phase B): 비활성화는 항상 PostgreSQL.
    from sqlalchemy import select
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        # 마지막 (활성) 관리자 보호 — 비활성화 시 활성 관리자가 0이 되면 차단.
        if u.is_admin and u.is_active and _other_admin_count(session, login_id, active_only=True) == 0:
            raise HTTPException(status_code=409, detail="마지막 관리자 계정은 비활성화하거나 삭제할 수 없습니다.")
        already = not u.is_active
        tenant_id = u.tenant_id
        u.is_active = False
        session.commit()
    # 기존 로그인 세션 즉시 무효화(단일세션 모드 토큰 포함) — kiosk 포함 전부.
    try:
        from backend.services.session_pg_service import revoke_active_sessions
        revoke_active_sessions(login_id, reason="account_disabled", only_non_kiosk=False)
    except Exception:
        pass
    _bust_tenant_cache()
    _audit_account("ACCOUNT_DISABLED", user, login_id, tenant_id, {"already_inactive": already})
    return {"ok": True, "login_id": login_id, "already_inactive": already}


@router.post("/accounts/{login_id}/restore")
def restore_account(login_id: str, user: dict = Depends(require_admin)):
    """비활성 계정 복구 (is_active=TRUE). 워크스페이스/시트키는 변경하지 않음."""
    login_id = login_id.strip()
    from sqlalchemy import select
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        was_active = u.is_active
        tenant_id = u.tenant_id
        u.is_active = True
        session.commit()
    _bust_tenant_cache()
    _audit_account("ACCOUNT_RESTORED", user, login_id, tenant_id, {"was_active": was_active})
    return {"ok": True, "login_id": login_id, "was_active": was_active}


@router.put("/accounts/{login_id}/role")
def set_account_role(login_id: str, body: AccountRoleUpdate, user: dict = Depends(require_admin)):
    """준 관리자 권한 부여/회수 — role 을 'sub_admin' 또는 'user' 로 설정한다(admin 전용).

    - full admin 승격/강등은 기존 is_admin 토글(PUT /accounts/{id})로 한다 → 여기선 불가.
    - 마스터 계정·자기 자신·full admin 계정의 role 변경은 거부한다.
    - role 컬럼(0024) 미적용 DB 면 503.
    """
    login_id = login_id.strip()
    role = (body.role or "").strip()
    if role not in ("sub_admin", "user"):
        raise HTTPException(status_code=400, detail="role 은 'sub_admin' 또는 'user' 만 허용합니다.")
    _assert_not_master(login_id, "set_role")   # 마스터 권한 변경 금지(서버 강제)
    if login_id == str(user.get("login_id", "")).strip():
        raise HTTPException(status_code=400, detail="자신의 권한은 변경할 수 없습니다.")

    from sqlalchemy import select
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        if bool(u.is_admin):
            raise HTTPException(status_code=409,
                                detail="관리자 계정의 권한은 '관리자' 토글로 변경하세요.")
        try:
            u.role = role
            session.commit()
        except Exception:
            session.rollback()
            raise HTTPException(status_code=503,
                                detail="권한 컬럼 마이그레이션(0024)이 적용되지 않아 저장할 수 없습니다.")
        tenant_id = u.tenant_id
    _audit_account("ACCOUNT_ROLE_CHANGED", user, login_id, tenant_id, {"role": role})
    return {"ok": True, "login_id": login_id, "role": role}


@router.get("/accounts/{login_id}/hard-delete-preview")
def hard_delete_preview(login_id: str, user: dict = Depends(require_admin)):
    """완전삭제 전 영향 미리보기 — 연결 데이터, tenant 공존 여부, 이관 필요 여부,
    이관 가능 대상 계정 목록. 실제 삭제는 하지 않는다."""
    login_id = login_id.strip()
    from sqlalchemy import select, func
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        tenant_id = u.tenant_id
        other_users = int(session.scalar(
            select(func.count()).select_from(AccountUser)
            .where(AccountUser.tenant_id == tenant_id, AccountUser.login_id != login_id)
        ) or 0)
        connected = _connected_data_summary(session, tenant_id) if other_users == 0 else {}
        migratable = {k: v for k, v in connected.items() if k in MIGRATABLE_TENANT_TABLES}
        unmigratable = {k: v for k, v in connected.items() if k not in MIGRATABLE_TENANT_TABLES}
        candidates = _migration_candidates(session, login_id) if (other_users == 0 and connected) else []
        return {
            "login_id": login_id, "tenant_id": tenant_id,
            "is_active": bool(u.is_active), "is_admin": bool(u.is_admin),
            "other_users_on_tenant": other_users,
            "needs_migration": other_users == 0 and bool(connected),
            "connected": connected, "migratable": migratable, "unmigratable": unmigratable,
            "candidates": candidates,
        }


@router.delete("/accounts/{login_id}/hard")
def hard_delete_account(
    login_id: str,
    confirm_login_id: str = Query("", description="삭제 확인용 — 대상 login_id 와 동일해야 함"),
    migrate_to_login_id: str = Query("", description="연결 데이터 이관 대상 계정(이관이 필요한 경우 필수)"),
    user: dict = Depends(require_admin),
):
    """비활성 계정 **완전 삭제**(물리 삭제). 강한 안전검사 통과 시에만 수행.

    조건: 존재 / 자기 자신 아님 / is_active=False / 마지막 관리자 아님 / confirm 문자열 일치.
    이 계정이 tenant 의 유일한 사용자면(tenant 도 함께 삭제) 연결 업무 데이터 존재 여부를 검사한다:
    - 다른 사용자가 tenant 에 남아 있으면 tenant/데이터는 그대로 보존 — 이관 불필요.
    - 이관 정책이 있는 8개 테이블(cert_*, customers, work_reference_*)은 자연키 충돌이 없으면
      migrate_to_login_id 의 tenant 로 이관.
    - 이관 정책이 없는 테이블에 연결 데이터가 있으면(tasks/daily/events/memos/documents/
      finance/signatures/roi_presets 등) 자동 이관하지 않고 완전삭제를 차단, 구체적으로 보고한다.
    """
    login_id = login_id.strip()
    if login_id == str(user.get("login_id", "")).strip():
        raise HTTPException(status_code=400, detail="자신의 계정은 완전 삭제할 수 없습니다.")
    _assert_not_master(login_id, "hard_delete")   # 마스터 계정 완전삭제 금지(서버 강제)
    if confirm_login_id.strip() != login_id:
        raise HTTPException(status_code=400, detail="확인용 계정 아이디가 일치하지 않습니다.")
    migrate_to_login_id = migrate_to_login_id.strip()
    if migrate_to_login_id and migrate_to_login_id == login_id:
        raise HTTPException(status_code=400, detail="삭제 대상 계정을 이관 대상으로 지정할 수 없습니다.")

    from sqlalchemy import select, text, func
    from backend.db.models.user import AccountUser
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다.")
        if u.is_active:
            raise HTTPException(status_code=409, detail="비활성 계정만 완전 삭제할 수 있습니다. 먼저 비활성화하세요.")
        if u.is_admin and _other_admin_count(session, login_id, active_only=False) == 0:
            raise HTTPException(status_code=409, detail="마지막 관리자 계정은 비활성화하거나 삭제할 수 없습니다.")

        tenant_id = u.tenant_id
        # 같은 tenant 에 다른 user 가 남는지 먼저 확인 — 남아 있으면 tenant/데이터 보존,
        # 연결 데이터 검사·이관 자체가 불필요(FK 위반 위험이 없음).
        other_users = int(session.scalar(
            select(func.count()).select_from(AccountUser)
            .where(AccountUser.tenant_id == tenant_id, AccountUser.login_id != login_id)
        ) or 0)

        migrated: dict = {}
        deleted_tenant = False
        target_tenant_id: Optional[str] = None
        if other_users == 0:
            connected = _connected_data_summary(session, tenant_id)
            if connected:
                unmigratable = {k: v for k, v in connected.items() if k not in MIGRATABLE_TENANT_TABLES}
                if unmigratable:
                    detail_rows = [{"table": k, "count": v, "column": "tenant_id",
                                    "reason": "이관 정책 미정의 — 자동 이관하지 않음",
                                    "manual_action": "수동으로 데이터를 이전하거나 정리한 뒤 다시 시도하세요."}
                                   for k, v in sorted(unmigratable.items())]
                    raise HTTPException(status_code=409, detail={
                        "message": "이관 정책이 없는 연결 데이터가 있어 완전 삭제할 수 없습니다.",
                        "unmigratable": detail_rows})
                if not migrate_to_login_id:
                    raise HTTPException(status_code=409, detail={
                        "message": "연결된 업무 데이터가 있어 이관 대상 계정을 지정해야 완전 삭제할 수 있습니다.",
                        "connected": connected})
                target = session.scalar(select(AccountUser).where(AccountUser.login_id == migrate_to_login_id))
                if target is None:
                    raise HTTPException(status_code=400, detail="이관 대상 계정을 찾을 수 없습니다.")
                if not target.is_active:
                    raise HTTPException(status_code=400, detail="이관 대상 계정은 활성 계정이어야 합니다.")
                target_tenant_id = target.tenant_id
                if target_tenant_id == tenant_id:
                    raise HTTPException(status_code=400, detail="이관 대상 계정이 같은 tenant 입니다(발생 불가 상태).")

                collisions: dict = {}
                for table, unique_cols in MIGRATABLE_TENANT_TABLES.items():
                    if unique_cols is None or table not in connected:
                        continue
                    hits = _collision_check(session, table, unique_cols, tenant_id, target_tenant_id)
                    if hits:
                        collisions[table] = hits
                if collisions:
                    raise HTTPException(status_code=409, detail={
                        "message": "이관 대상 계정과 데이터가 충돌해 완전 삭제할 수 없습니다.",
                        "collisions": collisions})

                migrated = _migrate_tenant_data(session, tenant_id, target_tenant_id)

        # 계정 개인 데이터/라이프사이클 정리(연결 업무 데이터는 위에서 이관/부재 확인됨).
        for tbl in _PERSONAL_CLEANUP_TABLES_BY_LOGIN_ID:
            try:
                session.execute(text(f'delete from "{tbl}" where login_id = :v'), {"v": login_id})
            except Exception:
                pass
        for tbl in _PERSONAL_CLEANUP_TABLES_BY_RECIPIENT:
            try:
                session.execute(text(f'delete from "{tbl}" where recipient_login_id = :v'), {"v": login_id})
            except Exception:
                pass
        try:
            session.execute(text('delete from "signature_pad_tokens" where tenant_id = :v'), {"v": tenant_id})
        except Exception:
            pass
        if other_users == 0:
            for tbl in _PERSONAL_CLEANUP_TABLES_BY_TENANT_ID:
                try:
                    session.execute(text(f'delete from "{tbl}" where tenant_id = :v'), {"v": tenant_id})
                except Exception:
                    pass

        session.delete(u)
        session.flush()   # 사용자 행을 먼저 삭제(users.tenant_id FK) 후 tenant 삭제 순서 보장
        if other_users == 0:
            t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
            if t is not None:
                session.delete(t)
                session.flush()
                deleted_tenant = True
        session.commit()

    _bust_tenant_cache()
    _audit_account("ACCOUNT_HARD_DELETED", user, login_id, tenant_id,
                   {"deleted_account_identifier": login_id, "tenant_id": tenant_id,
                    "deleted_tenant": deleted_tenant, "migrated_to_tenant_id": target_tenant_id,
                    "migrated": migrated})
    return {"ok": True, "login_id": login_id, "deleted_tenant": deleted_tenant,
            "migrated_to_tenant_id": target_tenant_id, "migrated": migrated}


@router.post("/accounts")
def create_account(
    body: AccountCreate,
    user: dict = Depends(require_admin),
):
    """신규 테넌트 계정 생성 (관리자 전용)"""
    from backend.services.accounts_service import (
        hash_password,
        find_account,
        build_account_dict,
        append_account,
    )

    # 중복 체크 (accounts_service → 서비스 계정 사용)
    if find_account(body.login_id.strip()):
        raise HTTPException(status_code=409, detail="이미 존재하는 login_id입니다.")

    # folder_id / customer_sheet_key / work_sheet_key가 이미 제공된 경우에만 즉시 활성화.
    # 미제공 시 is_active=FALSE → 워크스페이스 생성 후 자동으로 TRUE가 됨.
    provided_folder = bool((body.folder_id or "").strip())
    provided_customer = bool((body.customer_sheet_key or "").strip())
    provided_work = bool((body.work_sheet_key or "").strip())
    immediate_active = provided_folder and provided_customer and provided_work

    account = build_account_dict(
        login_id=body.login_id,
        password_hash=hash_password(body.password),
        tenant_id=body.tenant_id or "",
        office_name=body.office_name,
        office_adr=body.office_adr or "",
        contact_name=body.contact_name or "",
        contact_tel=body.contact_tel or "",
        biz_reg_no=body.biz_reg_no or "",
        agent_rrn=body.agent_rrn or "",
        folder_id=body.folder_id or "",
        work_sheet_key=body.work_sheet_key or "",
        customer_sheet_key=body.customer_sheet_key or "",
        sheet_key=body.sheet_key or "",
        is_admin=bool(body.is_admin),
        is_active=immediate_active,  # 워크스페이스 키가 모두 있을 때만 즉시 활성화
    )

    try:
        append_account(account)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"계정 생성 실패: {e}")

    # PG tenants 행 멱등 보장 — FEATURE_PG_CUSTOMERS 등 PG 저장을 쓰는 환경에서
    # 과거에는 계정만 있고 PG tenant 가 없어 첫 고객 추가가
    # customers_tenant_id_fkey 로 실패하는 것을 방지. PG 미구성 시 no-op.
    # 비치명적: 실패해도 계정 생성 자체는 성공 처리(기존 흐름 유지).
    try:
        from backend.services.tenant_provisioning_service import ensure_tenant_provisioned
        created = ensure_tenant_provisioned(
            str(account.get("tenant_id", "")).strip() or account["login_id"],
            account.get("office_name", ""),
        )
        if created:
            print(f"[admin.create_account] provisioned PG tenant for {account['login_id']!r}")
    except Exception as e:
        print(f"[admin.create_account] tenant provisioning skipped (non-fatal): {e}")

    # 캐시 초기화
    try:
        import backend.services.tenant_service as _ts
        _ts._TENANT_MAP_CACHE = {}
        _ts._TENANT_MAP_TIME = 0
    except Exception:
        pass

    return {"ok": True, "login_id": account["login_id"]}


@router.post("/seed-samples/{login_id}")
def seed_samples(login_id: str, user: dict = Depends(require_admin)):
    """선택한 테넌트에 온보딩 예시 데이터를 시드 (대상 영역이 비어 있을 때만).

    future-safe admin helper — "샘플 데이터 추가" 버튼용. 기존 데이터가 있으면
    각 영역은 자동으로 건너뛰므로 덮어쓰기/중복이 발생하지 않는다. 운영 데이터
    무수정. (호출 측 UI 는 확인 대화상자를 거치도록 권장.)
    """
    from backend.db.session import is_configured
    if not is_configured():
        raise HTTPException(status_code=400, detail="PostgreSQL이 구성되지 않아 시드할 수 없습니다.")
    from backend.services.tenant_sample_seed_service import seed_new_tenant_sample_data
    tenant_id = str(login_id).strip()
    result = seed_new_tenant_sample_data(tenant_id)
    return {"ok": not result.get("errors"), **result}


@router.post("/workspace")
def create_workspace(
    body: WorkspaceCreateRequest,
    user: dict = Depends(require_admin),
):
    """
    테넌트 워크스페이스 생성/재생성 (멱등성 보장).

    PG-only(단계적 제거 2단계): PG 가 구성된 운영 환경에서는 외부 가짜키
    (``local-folder-*`` / ``local-sheet-*``)를 더 이상 생성하지 않는다. 고객/업무/
    결산/문서 등 모든 운영 데이터는 PostgreSQL 에 있으므로 이 키들은 어떤 읽기 경로
    에서도 사용되지 않는다. 워크스페이스 생성에 실제로 필요한 것은:
      (1) tenant/user 활성화(is_active=TRUE)
      (2) 온보딩 샘플 시드
    뿐이므로 이 둘만 수행한다. 기존 계정의 기존 folder_id/customer_sheet_key/
    work_sheet_key 값은 절대 건드리지 않는다(여기서 읽지도, 쓰지도 않음).

    (legacy) PG 미구성 설치에서만 아래쪽 실제 프로비저닝 경로가
    살아 있다 — 운영(Render)에서는 PG 가 항상 구성되므로 도달하지 않는다.
    """
    import logging
    log = logging.getLogger("admin.workspace")

    # ── PG-only: 가짜키 미생성, 활성화 + 샘플 시드만 수행 ─────────────────────
    from backend.db.feature_flags import (
        local_drive_mock_enabled,
        pg_tenant_provisioning_enabled,
    )
    from backend.db.session import is_configured as _pg_configured
    # PG-only(Phase B): PG 가 구성된 환경은 항상 PG 프로비저닝 경로 사용(Accounts 시트/운영 Drive 미접촉).
    if local_drive_mock_enabled() or pg_tenant_provisioning_enabled() or _pg_configured():
        login_id = body.login_id.strip()
        office_name = body.office_name.strip() or login_id
        # 응답 형태는 기존 프론트(handleCreateWorkspace/handleRowWorkspace)와 호환 유지.
        # folder/customer/work 키는 더 이상 생성하지 않으므로 빈 값으로 둔다.
        result = {
            "ok": True,
            "stages": {
                "folder_create":   {"status": "skipped-pg", "id": "", "error": None},
                "customer_copy":   {"status": "skipped-pg", "id": "", "error": None},
                "work_copy":       {"status": "skipped-pg", "id": "", "error": None},
                "accounts_update": {"status": "deferred-to-caller", "error": None},
            },
            "folder_id": "",
            "customer_sheet_key": "",
            "work_sheet_key": "",
            "is_active": False,
            "drive_user": None,
            "drive_quota": None,
            "message": "PostgreSQL workspace activated — 외부 키를 생성하지 않습니다.",
        }

        # 로컬 PG의 tenants 행 + 가입신청한 user 행 활성화 (가짜키 기록 없음).
        # 가입신청 사용자도 로그인 가능 상태로 옮긴다 (is_active=True). 관리자 권한은
        # 별도로 PUT /accounts/{id} 로 부여한다 — 본 경로는 활성화만 책임진다.
        try:
            from sqlalchemy import select
            from backend.db.models.tenant import Tenant
            from backend.db.models.user import AccountUser
            from backend.db.session import get_sessionmaker, is_configured
            if is_configured():
                SessionLocal = get_sessionmaker()
                with SessionLocal() as session:
                    # tenant: activate (sheet 키는 생성/수정하지 않음 — 기존 값 보존)
                    t = session.scalar(select(Tenant).where(Tenant.tenant_id == login_id))
                    if t is None:
                        # signup → workspace 사이 tenant 행이 누락된 경우 생성
                        t = Tenant(tenant_id=login_id, office_name=office_name)
                        session.add(t)
                        session.flush()
                    t.office_name = office_name
                    t.is_active = True
                    # user: activate the signup row(s) belonging to this tenant
                    activated = 0
                    for u in session.scalars(select(AccountUser).where(
                        AccountUser.tenant_id == login_id
                    )).all():
                        if not u.is_active:
                            u.is_active = True
                            activated += 1
                    session.commit()
                    result["stages"]["accounts_update"] = {
                        "status": "applied-to-local-tenants",
                        "users_activated": activated,
                        "error": None,
                    }
                    result["is_active"] = True
        except Exception as e:
            log.warning("[workspace] 로컬 tenants/users 갱신 실패 (non-fatal): %s", e)

        # ── 온보딩 샘플 데이터 시드 (업무참고 / 각종공인증) ──────────────────
        # 신규 테넌트가 빈 화면을 보지 않도록 예시 데이터를 1회만 시드한다.
        # 대상 영역이 비어 있을 때만 동작하므로 기존 데이터/기존 테넌트는 영향 없음.
        try:
            from backend.db.session import is_configured as _is_cfg
            if _is_cfg():
                from backend.services.tenant_sample_seed_service import seed_new_tenant_sample_data
                seed = seed_new_tenant_sample_data(login_id, None)
                result["stages"]["sample_seed"] = {
                    "status": "seeded" if (seed.get("reference_rows") or
                                           any(seed.get("certification", {}).values()))
                              else "skipped-or-existing",
                    "reference_rows": seed.get("reference_rows", 0),
                    "certification": seed.get("certification", {}),
                    "error": "; ".join(seed.get("errors", [])) or None,
                }
        except Exception as e:
            log.warning("[workspace] 샘플 시드 실패 (non-fatal): %s", e)
            result["stages"]["sample_seed"] = {"status": "failed", "error": str(e)}

        log.info("[workspace] PG 활성화 완료 — 가짜키 미생성. result=%s", result)
        return result

    # ── 레거시 외부 프로비저닝 경로 제거 ──
    # 위 PG 분기에서 모든 PG 구성 환경(운영·로컬)은 이미 return 했다. 여기 도달 = PG 미구성
    # (= 더 이상 지원하지 않는 레거시 설치). 과거 이 아래에 있던 외부
    # 템플릿 복사 + Accounts 시트 read/upsert 코드는 운영에서 도달하지 않는 dead 경로였으므로
    # 제거하고, PG 미구성 시 조용한 fallback 대신 명확히 실패시킨다.
    raise HTTPException(
        status_code=503,
        detail=(
            "PostgreSQL이 구성되지 않아 워크스페이스를 생성할 수 없습니다. "
            "(레거시 외부 프로비저닝은 제거되었습니다.)"
        ),
    )
