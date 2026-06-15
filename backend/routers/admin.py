"""관리자 라우터 - 계정 관리 + 워크스페이스 자동 생성"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.auth import get_current_user, require_admin
from backend.models import AccountUpdate, AccountCreate

router = APIRouter()

@router.post("/bootstrap")
def bootstrap_admin(body: AccountCreate):
    """
    최초 관리자 계정 생성 — 인증 불필요. **PG-only.**
    PG users 에 계정이 하나도 없을 때만 동작(중복 부트스트랩 방지). 1개라도 있으면 403.
    Google Sheets 미사용.
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
    # PG-only(Phase B): 계정 목록은 항상 PostgreSQL. Google Sheets fallback 제거.
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
    # PG-only(Phase B): 계정 수정은 항상 PostgreSQL. Google Sheets fallback 제거.
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


def _connected_data_summary(session, tenant_id: str) -> dict:
    """해당 tenant 에 연결된 업무 데이터 건수(0 이면 완전삭제 안전).

    information_schema 로 tenant_id 컬럼을 가진 테이블을 찾아 행 수를 센다(스키마 적응형).
    계정/세션/인프라 테이블은 제외(이들은 삭제 절차에서 직접 정리). 테이블명은
    information_schema 출처라 인젝션 위험 없음, tenant_id 는 파라미터 바인딩.
    """
    from sqlalchemy import text
    exclude = {"users", "tenants", "user_sessions", "signature_pad_tokens", "audit_logs"}
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
    # PG-only(Phase B): 비활성화는 항상 PostgreSQL. Google Sheets fallback 제거.
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


@router.delete("/accounts/{login_id}/hard")
def hard_delete_account(
    login_id: str,
    confirm_login_id: str = Query("", description="삭제 확인용 — 대상 login_id 와 동일해야 함"),
    user: dict = Depends(require_admin),
):
    """비활성 계정 **완전 삭제**(물리 삭제). 강한 안전검사 통과 시에만 수행.

    조건: 존재 / 자기 자신 아님 / is_active=False / 마지막 관리자 아님 /
    connect 확인 문자열 일치 / 연결된 업무 데이터 없음. 연결 데이터가 있으면 차단(409).
    """
    login_id = login_id.strip()
    if login_id == str(user.get("login_id", "")).strip():
        raise HTTPException(status_code=400, detail="자신의 계정은 완전 삭제할 수 없습니다.")
    if confirm_login_id.strip() != login_id:
        raise HTTPException(status_code=400, detail="확인용 계정 아이디가 일치하지 않습니다.")

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
        # 연결 업무 데이터 검사 — 있으면 물리 삭제 차단(임의 cascade 금지).
        connected = _connected_data_summary(session, tenant_id)
        if connected:
            summary = ", ".join(f"{k}={v}" for k, v in sorted(connected.items()))
            raise HTTPException(
                status_code=409,
                detail=f"연결된 업무 데이터가 있어 완전 삭제할 수 없습니다. 먼저 데이터 이관/정리 정책이 필요합니다. ({summary})",
            )

        # 같은 tenant 에 다른 user 가 남는지(있으면 tenant 행은 보존).
        other_users = int(session.scalar(
            select(func.count()).select_from(AccountUser)
            .where(AccountUser.tenant_id == tenant_id, AccountUser.login_id != login_id)
        ) or 0)

        # 세션/패드토큰 등 계정 부속 데이터 먼저 정리(연결 업무 데이터는 위에서 없음 확인됨).
        for tbl, col in (("user_sessions", "login_id"), ("signature_pad_tokens", "tenant_id")):
            val = login_id if col == "login_id" else tenant_id
            try:
                session.execute(text(f'delete from "{tbl}" where {col} = :v'), {"v": val})
            except Exception:
                pass

        session.delete(u)
        session.flush()   # 사용자 행을 먼저 삭제(users.tenant_id FK) 후 tenant 삭제 순서 보장
        deleted_tenant = False
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
                    "deleted_tenant": deleted_tenant})
    return {"ok": True, "login_id": login_id, "deleted_tenant": deleted_tenant}


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
    # Sheets Accounts 에만 계정이 생기고 PG tenant 가 없어 첫 고객 추가가
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

    PG-only(단계적 제거 2단계): PG 가 구성된 운영 환경에서는 Drive/Sheets 가짜키
    (``local-folder-*`` / ``local-sheet-*``)를 더 이상 생성하지 않는다. 고객/업무/
    결산/문서 등 모든 운영 데이터는 PostgreSQL 에 있으므로 이 키들은 어떤 읽기 경로
    에서도 사용되지 않는다. 워크스페이스 생성에 실제로 필요한 것은:
      (1) tenant/user 활성화(is_active=TRUE)
      (2) 온보딩 샘플 시드
    뿐이므로 이 둘만 수행한다. 기존 계정의 기존 folder_id/customer_sheet_key/
    work_sheet_key 값은 절대 건드리지 않는다(여기서 읽지도, 쓰지도 않음).

    (legacy) 순수 Sheets 설치(PG 미구성)에서만 아래쪽 실제 Drive 프로비저닝 경로가
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
            "message": "PostgreSQL workspace activated — Drive/Sheets 키를 생성하지 않습니다.",
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

    import config as _cfg
    from config import (
        ACCOUNTS_SHEET_NAME,
        PARENT_DRIVE_FOLDER_ID,
        CUSTOMER_DATA_TEMPLATE_ID,
        WORK_REFERENCE_TEMPLATE_ID,
    )
    # ── DIAGNOSTIC: prove which config.py the live process is using ──────────
    import os as _os
    log.warning(
        "[workspace:DIAG] pid=%s | config.__file__=%s | "
        "WORK_REFERENCE_TEMPLATE_ID=%s | CUSTOMER_DATA_TEMPLATE_ID=%s | "
        "PARENT_DRIVE_FOLDER_ID=%s",
        _os.getpid(),
        getattr(_cfg, "__file__", "(unknown)"),
        WORK_REFERENCE_TEMPLATE_ID,
        CUSTOMER_DATA_TEMPLATE_ID,
        PARENT_DRIVE_FOLDER_ID,
    )
    # ── END DIAGNOSTIC ────────────────────────────────────────────────────────
    from core.google_sheets import read_data_from_sheet, upsert_rows_by_id
    from backend.services.accounts_service import ACCOUNTS_SCHEMA

    login_id = body.login_id.strip()
    office_name = body.office_name.strip() or login_id

    # ── 현재 계정 상태 로드 ──────────────────────────────────────────────────
    current_folder_id = ""
    current_customer_key = ""
    current_work_key = ""
    target_record = None
    try:
        existing = read_data_from_sheet(ACCOUNTS_SHEET_NAME, default_if_empty=[]) or []
        for r in existing:
            if str(r.get("login_id", "")).strip() == login_id:
                target_record = r
                current_folder_id = str(r.get("folder_id", "")).strip()
                current_customer_key = str(r.get("customer_sheet_key", "")).strip()
                current_work_key = str(r.get("work_sheet_key", "")).strip()
                break
        log.info(
            "[workspace] %s 현재 상태: folder=%s, customer=%s, work=%s",
            login_id, bool(current_folder_id), bool(current_customer_key), bool(current_work_key),
        )
    except Exception as e:
        log.warning("[workspace] Accounts 상태 조회 실패: %s (계속 진행)", e)

    if target_record is None:
        raise HTTPException(
            status_code=404,
            detail=f"login_id='{login_id}' 계정을 찾을 수 없습니다. 먼저 계정을 생성하세요.",
        )

    # ── Drive 서비스 초기화 (admin user OAuth — templates live in admin My Drive) ─
    # Service account cannot copy files it does not own in the admin's My Drive.
    # Use the pre-existing admin user OAuth token (token.json) instead.
    try:
        from googleapiclient.discovery import build as _build
        from core.google_sheets import get_user_credentials

        _SCOPES = ["https://www.googleapis.com/auth/drive"]
        _oauth_creds = get_user_credentials(_SCOPES)
        drive = _build("drive", "v3", credentials=_oauth_creds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Google Drive 초기화 실패 (OAuth): {e}")

    # ── Drive 스토리지 쿼터 진단 (로그만, 에러 아님) ─────────────────────────
    try:
        about = drive.about().get(fields="user,storageQuota").execute()
        sa_email = about.get("user", {}).get("emailAddress", "(unknown)")
        quota = about.get("storageQuota", {})
        used = int(quota.get("usage", 0))
        limit = int(quota.get("limit", -1))
        log.info(
            "[workspace] Drive 사용자: %s | 사용: %d MB / 한도: %s MB",
            sa_email,
            used // (1024 * 1024),
            str(limit // (1024 * 1024)) if limit > 0 else "unlimited",
        )
    except Exception as e:
        log.warning("[workspace] Drive 쿼터 조회 실패: %s", e)
        sa_email = "(unknown)"
        quota = {}

    # ── 단계별 결과 추적 ─────────────────────────────────────────────────────
    stages: dict = {
        "folder_create":   {"status": "skipped", "id": current_folder_id, "error": None},
        "customer_copy":   {"status": "skipped", "id": current_customer_key, "error": None},
        "work_copy":       {"status": "skipped", "id": current_work_key, "error": None},
        "accounts_update": {"status": "pending", "error": None},
    }

    folder_id = current_folder_id
    customer_sheet_key = current_customer_key
    work_sheet_key = current_work_key

    # ── A. 폴더 생성/재사용 ──────────────────────────────────────────────────
    if folder_id:
        log.info("[workspace] 폴더 재사용: %s", folder_id)
        stages["folder_create"]["status"] = "reused"
    else:
        log.info("[workspace] 폴더 생성 시작 (parent=%s)", PARENT_DRIVE_FOLDER_ID)
        try:
            folder_meta = {
                "name": login_id,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [PARENT_DRIVE_FOLDER_ID],
            }
            folder = drive.files().create(
                body=folder_meta,
                fields="id",
                supportsAllDrives=True,
            ).execute()
            folder_id = folder["id"]
            stages["folder_create"] = {"status": "created", "id": folder_id, "error": None}
            log.info("[workspace] 폴더 생성 완료: %s", folder_id)
        except Exception as e:
            import traceback
            err_msg = str(e)
            stages["folder_create"] = {"status": "failed", "id": "", "error": err_msg}
            log.error(
                "[workspace] 폴더 생성 실패 | parent=%s | sa=%s | error=%s\n%s",
                PARENT_DRIVE_FOLDER_ID, sa_email, err_msg, traceback.format_exc(),
            )
            # 폴더 없으면 이후 단계 의미 없음 → 즉시 부분 결과 반환
            stages["customer_copy"]["status"] = "blocked"
            stages["work_copy"]["status"] = "blocked"
            stages["accounts_update"]["status"] = "blocked"
            return {
                "ok": False,
                "stages": stages,
                "folder_id": folder_id,
                "customer_sheet_key": customer_sheet_key,
                "work_sheet_key": work_sheet_key,
                "is_active": False,
                "drive_user": sa_email,
                "drive_quota": quota,
                "error": f"폴더 생성 실패: {err_msg}",
            }

    # ── shared probe helper (inline) ─────────────────────────────────────────
    import traceback as _tb
    import json as _json

    def _probe_template(file_id: str, label: str) -> dict:
        """
        files.get() the template before attempting a copy.
        Returns a dict with probe results; never raises.
        Distinguishes:
          - not_accessible : files.get() itself failed (404 / 403 at read level)
          - readable       : files.get() succeeded → check capabilities.canCopy
          - domain_policy  : error reason contains 'domainPolicy' / 'sharingNotSupported'
        """
        result = {"accessible": False, "can_copy": None, "metadata": None, "error": None, "reason": None}
        try:
            meta = drive.files().get(
                fileId=file_id,
                fields="id,name,mimeType,owners,sharingUser,capabilities,driveId,teamDriveId,parents",
                supportsAllDrives=True,
            ).execute()
            result["accessible"] = True
            result["metadata"] = {
                "id":       meta.get("id"),
                "name":     meta.get("name"),
                "mimeType": meta.get("mimeType"),
                "owners":   meta.get("owners"),
                "driveId":  meta.get("driveId") or meta.get("teamDriveId"),
                "parents":  meta.get("parents"),
            }
            caps = meta.get("capabilities", {})
            result["can_copy"] = caps.get("canCopy")
            result["capabilities"] = caps
            log.warning(
                "[workspace:PROBE] %s | file_id=%s | accessible=True | can_copy=%s | "
                "name=%r | mimeType=%s | driveId=%s | sa=%s | dest_folder=%s | caps=%s",
                label, file_id, caps.get("canCopy"), meta.get("name"), meta.get("mimeType"),
                meta.get("driveId") or meta.get("teamDriveId") or "(MyDrive)",
                sa_email, folder_id, _json.dumps(caps),
            )
        except Exception as probe_err:
            raw = str(probe_err)
            # Extract structured reason from googleapiclient HttpError if present
            reason = raw
            try:
                import googleapiclient.errors as _ge
                if isinstance(probe_err, _ge.HttpError):
                    body = _json.loads(probe_err.content.decode())
                    reason = (
                        body.get("error", {}).get("errors", [{}])[0].get("reason", raw)
                        + " | message: "
                        + body.get("error", {}).get("message", raw)
                    )
            except Exception:
                pass
            result["error"] = raw
            result["reason"] = reason
            log.warning(
                "[workspace:PROBE] %s | file_id=%s | accessible=False | "
                "raw_error=%s | reason=%s | sa=%s | dest_folder=%s",
                label, file_id, raw, reason, sa_email, folder_id,
            )
        return result

    # ── B. 고객 데이터 시트 복사/재사용 ─────────────────────────────────────
    if customer_sheet_key:
        log.info("[workspace] 고객 데이터 시트 재사용: %s", customer_sheet_key)
        stages["customer_copy"]["status"] = "reused"
    else:
        probe_c = _probe_template(CUSTOMER_DATA_TEMPLATE_ID, "customer_template")
        stages["customer_copy"]["probe"] = {
            "accessible": probe_c["accessible"],
            "can_copy":   probe_c["can_copy"],
            "reason":     probe_c["reason"],
            "metadata":   probe_c.get("metadata"),
        }
        log.info(
            "[workspace] 고객 데이터 시트 복사 시작 | template=%s | dest_parent=%s | sa=%s",
            CUSTOMER_DATA_TEMPLATE_ID, folder_id, sa_email,
        )
        try:
            customer_copy = drive.files().copy(
                fileId=CUSTOMER_DATA_TEMPLATE_ID,
                body={
                    "name": f"고객 데이터 - {office_name}",
                    "parents": [folder_id],
                },
                fields="id",
                supportsAllDrives=True,
            ).execute()
            customer_sheet_key = customer_copy["id"]
            stages["customer_copy"]["status"] = "created"
            stages["customer_copy"]["id"] = customer_sheet_key
            stages["customer_copy"]["error"] = None
            log.info("[workspace] 고객 데이터 시트 복사 완료: %s", customer_sheet_key)
        except Exception as e:
            err_msg = str(e)
            # Extract raw API reason
            try:
                import googleapiclient.errors as _ge
                if isinstance(e, _ge.HttpError):
                    body = _json.loads(e.content.decode())
                    api_reason = (
                        body.get("error", {}).get("errors", [{}])[0].get("reason", "")
                        + " | " + body.get("error", {}).get("message", "")
                    )
                else:
                    api_reason = err_msg
            except Exception:
                api_reason = err_msg
            stages["customer_copy"]["status"] = "failed"
            stages["customer_copy"]["id"] = ""
            stages["customer_copy"]["error"] = err_msg
            stages["customer_copy"]["api_reason"] = api_reason
            log.error(
                "[workspace] 고객 데이터 시트 복사 실패 | template=%s | dest_parent=%s | "
                "sa=%s | api_reason=%s | raw=%s\n%s",
                CUSTOMER_DATA_TEMPLATE_ID, folder_id, sa_email,
                api_reason, err_msg, _tb.format_exc(),
            )

    # ── C. 업무정리 시트 복사/재사용 ─────────────────────────────────────────
    if work_sheet_key:
        log.info("[workspace] 업무정리 시트 재사용: %s", work_sheet_key)
        stages["work_copy"]["status"] = "reused"
    else:
        probe_w = _probe_template(WORK_REFERENCE_TEMPLATE_ID, "work_template")
        stages["work_copy"]["probe"] = {
            "accessible": probe_w["accessible"],
            "can_copy":   probe_w["can_copy"],
            "reason":     probe_w["reason"],
            "metadata":   probe_w.get("metadata"),
        }
        log.info(
            "[workspace] 업무정리 시트 복사 시작 | template=%s | dest_parent=%s | sa=%s",
            WORK_REFERENCE_TEMPLATE_ID, folder_id, sa_email,
        )
        try:
            tasks_copy = drive.files().copy(
                fileId=WORK_REFERENCE_TEMPLATE_ID,
                body={
                    "name": f"업무정리 - {office_name}",
                    "parents": [folder_id],
                },
                fields="id",
                supportsAllDrives=True,
            ).execute()
            work_sheet_key = tasks_copy["id"]
            stages["work_copy"]["status"] = "created"
            stages["work_copy"]["id"] = work_sheet_key
            stages["work_copy"]["error"] = None
            log.info("[workspace] 업무정리 시트 복사 완료: %s", work_sheet_key)
        except Exception as e:
            err_msg = str(e)
            try:
                import googleapiclient.errors as _ge
                if isinstance(e, _ge.HttpError):
                    body = _json.loads(e.content.decode())
                    api_reason = (
                        body.get("error", {}).get("errors", [{}])[0].get("reason", "")
                        + " | " + body.get("error", {}).get("message", "")
                    )
                else:
                    api_reason = err_msg
            except Exception:
                api_reason = err_msg
            stages["work_copy"]["status"] = "failed"
            stages["work_copy"]["id"] = ""
            stages["work_copy"]["error"] = err_msg
            stages["work_copy"]["api_reason"] = api_reason
            log.error(
                "[workspace] 업무정리 시트 복사 실패 | template=%s | dest_parent=%s | "
                "sa=%s | api_reason=%s | raw=%s\n%s",
                WORK_REFERENCE_TEMPLATE_ID, folder_id, sa_email,
                api_reason, err_msg, _tb.format_exc(),
            )

    # ── D. Accounts 시트 업데이트 ────────────────────────────────────────────
    # 세 키가 모두 있을 때만 is_active=TRUE 설정
    all_ready = bool(folder_id and customer_sheet_key and work_sheet_key)

    try:
        if folder_id:
            target_record["folder_id"] = folder_id
        if customer_sheet_key:
            target_record["customer_sheet_key"] = customer_sheet_key
        if work_sheet_key:
            target_record["work_sheet_key"] = work_sheet_key
        if all_ready:
            target_record["is_active"] = "TRUE"
            log.info("[workspace] %s → is_active=TRUE (모든 키 확보)", login_id)

        # ACCOUNTS_SCHEMA 순서로 header 정렬 (컬럼 위치 오염 방지)
        header_list = ACCOUNTS_SCHEMA[:]
        for k in target_record:
            if k not in header_list:
                header_list.append(k)

        upsert_rows_by_id(
            ACCOUNTS_SHEET_NAME,
            header_list=header_list,
            records=[target_record],
            id_field="login_id",
        )
        stages["accounts_update"] = {"status": "saved", "error": None}
        log.info("[workspace] Accounts 업데이트 완료 (is_active=%s)", target_record.get("is_active"))

        # 캐시 초기화
        try:
            import backend.services.tenant_service as _ts
            _ts._TENANT_MAP_CACHE = {}
            _ts._TENANT_MAP_TIME = 0
        except Exception:
            pass

    except Exception as e:
        err_msg = str(e)
        stages["accounts_update"] = {"status": "failed", "error": err_msg}
        log.error("[workspace] Accounts 업데이트 실패: %s", err_msg)

    # ── 온보딩 샘플 데이터 시드 (PG 백엔드일 때만) ──────────────────────────
    # local-mock 분기와 동일하게, PG가 구성된 런타임에서는 신규 테넌트의
    # 업무참고/각종공인증(기타업무참고) 영역에 instructional 예시 데이터만 1회 시드한다.
    # empty-only·idempotent 이므로 기존/실데이터는 절대 건드리지 않는다.
    # 주의: 이 시드는 PG instructional 샘플만 넣는다. Google Sheets 템플릿
    # (WORK_REFERENCE_TEMPLATE_ID) 복사본의 탭 내용은 별도 데이터이며 여기서 변경하지 않는다.
    try:
        from backend.db.session import is_configured as _is_cfg
        if _is_cfg():
            from backend.services.tenant_sample_seed_service import seed_new_tenant_sample_data
            seed = seed_new_tenant_sample_data(login_id, work_sheet_key)
            stages["sample_seed"] = {
                "status": "seeded" if (seed.get("reference_rows") or
                                       any(seed.get("certification", {}).values()))
                          else "skipped-or-existing",
                "reference_rows": seed.get("reference_rows", 0),
                "certification": seed.get("certification", {}),
                "error": "; ".join(seed.get("errors", [])) or None,
            }
    except Exception as e:
        log.warning("[workspace] 샘플 시드 실패 (non-fatal): %s", e)
        stages["sample_seed"] = {"status": "failed", "error": str(e)}

    # ── 최종 응답 ────────────────────────────────────────────────────────────
    # sample_seed 는 비핵심(non-fatal) 온보딩 단계이므로 성공 판정에서 제외한다.
    any_failed = any(
        s.get("status") == "failed"
        for k, s in stages.items()
        if k != "sample_seed"
    )
    return {
        "ok": not any_failed,
        "stages": stages,
        "folder_id": folder_id,
        "customer_sheet_key": customer_sheet_key,
        "work_sheet_key": work_sheet_key,
        "is_active": all_ready,
        "drive_user": sa_email,
    }
