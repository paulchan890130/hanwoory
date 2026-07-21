"""사업장(tenant) 전체 폐기 — 고위험. **시스템 관리자 전용**.

계정 완전 삭제(로그인 계정만 삭제, tenant/업무 데이터 보존)와는 **별개**의 기능이다.
이 서비스는 한 tenant 의 모든 tenant-scoped 데이터를 **명시적 순서·단일 트랜잭션**으로 삭제한다.

설계 원칙(회귀 금지):
- ``DELETE CASCADE`` 를 맹목적으로 쓰지 않는다. 삭제 대상·순서를 명시 관리한다.
- 폐기 대상은 ``service_status=='suspended'`` + ``is_active==False`` 인 tenant 만. active 즉시 폐기 금지.
- 마스터/현재 시스템 관리자 자신이 속한 tenant 는 폐기 금지.
- 확인 3값(tenant_id, office_name, 확인 문구)이 정확히 일치해야 실행.
- **외부 저장소(Drive folder / Google Sheets key)** 참조가 남아 있으면 DB 만 먼저 지우지 않는다 →
  fail-closed(``can_purge=False``, blocking reason 보고).
- ``tenant_id`` 컬럼을 가진 테이블 중 **plan 에 미분류**된 것이 있으면 fail-closed(신규 테이블 누락 방지).
- 감사로그에는 **PII 를 저장하지 않는다** — actor + tenant_id 해시 + 삭제 건수 요약만.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy import inspect, select, text


class PurgeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


CONFIRMATION_PHRASE = "사업장 전체 폐기"

# ── TENANT_PURGE_PLAN ─────────────────────────────────────────────────────────
# tenant_id 컬럼으로 DELETE 하는 테이블. tenants 를 마지막에 지우면 FK(자식→부모) 순서를
# 충족한다(이들 사이에는 tenants 외의 상호 FK 가 없다). doc_tree_nodes 는 DB FK
# (doc_required_documents.node_id ondelete=CASCADE)로 자식을 함께 삭제한다.
PURGE_BY_TENANT_ID: list[str] = [
    "customers",
    "active_tasks", "planned_tasks", "completed_tasks",
    "daily_entries", "daily_balances",
    "events", "memos",
    "accommodation_providers", "guarantor_connections",
    "document_metadata",
    "fixed_expenses", "monthly_tax_summaries",
    "roi_presets",
    "agent_signatures", "customer_signatures", "signature_pad_tokens", "temp_signature_slots",
    "work_reference_sheets", "work_reference_rows",
    "doc_tree_nodes",
    "cert_vendors", "cert_directions", "cert_groups", "cert_regions", "cert_prices",
    "board_posts", "board_comments",
    "marketing_images",
    "login_events", "account_security", "security_notifications",
    "user_terms_acceptances",
    "user_sessions",
    "activation_tokens",
    "users",
]

# tenant_id 컬럼이 있으나 **보존**하는 테이블(감사 이력 — FK 없음, 역사 보존).
PRESERVE_WITH_TENANT_ID: list[str] = ["audit_logs"]

# tenant_id 컬럼을 가진 target 자신(마지막에 삭제).
TARGET_TABLE = "tenants"

# tenant_id 컬럼은 없지만 tenant 에 간접 연결되어 함께 정리하는 테이블.
PURGE_BY_LOGIN_ID: list[str] = ["login_attempts"]            # login_id IN (tenant users)
PURGE_BY_APPROVED_TENANT: list[str] = ["office_applications"]  # approved_tenant_id = tenant (PII 제거)

# doc_tree_nodes 삭제 시 DB CASCADE 로 함께 지워지는 자식(집계·설명용).
CASCADE_CHILDREN = {"doc_tree_nodes": ["doc_required_documents"]}

# 폐기 대상에서 tenant_id 컬럼 기준으로 반드시 분류돼야 하는 집합(coverage 판정).
_CLASSIFIED_TENANT_ID_TABLES = set(PURGE_BY_TENANT_ID) | set(PRESERVE_WITH_TENANT_ID) | {TARGET_TABLE}


def _hash_tid(tenant_id: str) -> str:
    return hashlib.sha256((tenant_id or "").encode("utf-8")).hexdigest()[:16]


def tables_with_tenant_id(session) -> set[str]:
    """현재 스키마에서 ``tenant_id`` 컬럼을 가진 테이블 집합(inspector — 크로스 DB)."""
    insp = inspect(session.get_bind())
    out: set[str] = set()
    for tbl in insp.get_table_names():
        try:
            cols = {c["name"] for c in insp.get_columns(tbl)}
        except Exception:
            continue
        if "tenant_id" in cols:
            out.add(tbl)
    return out


def unclassified_tenant_tables(session) -> list[str]:
    """plan 에 분류되지 않은 tenant_id 테이블(신규 테이블 누락 감지)."""
    present = tables_with_tenant_id(session)
    return sorted(t for t in present if t not in _CLASSIFIED_TENANT_ID_TABLES)


def _external_storage_blocking(t) -> list[str]:
    """외부 저장소(Drive/Sheets) 참조 — 있으면 fail-closed(DB 만 먼저 지우지 않음)."""
    reasons: list[str] = []
    if (getattr(t, "folder_id", None) or "").strip():
        reasons.append("연결된 Google Drive 폴더(folder_id)가 있어 외부 파일을 안전하게 삭제할 수 없습니다.")
    if (getattr(t, "customer_sheet_key", None) or "").strip():
        reasons.append("연결된 고객 Google Sheets(customer_sheet_key)가 있어 외부 데이터를 안전하게 삭제할 수 없습니다.")
    if (getattr(t, "work_sheet_key", None) or "").strip():
        reasons.append("연결된 업무 Google Sheets(work_sheet_key)가 있어 외부 데이터를 안전하게 삭제할 수 없습니다.")
    return reasons


def _existing_tables(session) -> set[str]:
    try:
        return set(inspect(session.get_bind()).get_table_names())
    except Exception:
        return set()


def _count(session, table: str, where_col: str, value) -> int:
    # table/where_col 은 이 모듈의 상수에서만 온다(사용자 입력 아님 — injection 안전).
    return int(session.execute(
        text(f"SELECT count(*) FROM {table} WHERE {where_col} = :v"), {"v": value}
    ).scalar() or 0)


def tenant_data_counts(session, tenant_id: str) -> dict:
    """tenant-scoped 업무 데이터 건수(연결 현황·미리보기 공용). 존재하는 테이블만 집계."""
    present = _existing_tables(session)
    keys = {
        "customers": "customers",
        "active_tasks": "active_tasks",
        "planned_tasks": "planned_tasks",
        "completed_tasks": "completed_tasks",
        "daily_entries": "daily_entries",
        "events": "events",
        "memos": "memos",
        "categories": "cert_groups",
        "work_references": "work_reference_rows",
        "board_posts": "board_posts",
    }
    out: dict[str, int] = {}
    for friendly, tbl in keys.items():
        out[friendly] = _count(session, tbl, "tenant_id", tenant_id) if tbl in present else 0
    return out


def tenant_has_business_data(session, tenant_id: str) -> bool:
    """고객·업무·분류·업무참고 등 실데이터가 하나라도 있으면 True(연결이전 차단 판정용)."""
    c = tenant_data_counts(session, tenant_id)
    return any(c.get(k, 0) > 0 for k in
               ("customers", "active_tasks", "planned_tasks", "completed_tasks",
                "daily_entries", "events", "memos", "categories", "work_references", "board_posts"))


def _tenant_user_login_ids(session, tenant_id: str) -> list[str]:
    from backend.db.models.user import AccountUser
    return list(session.scalars(
        select(AccountUser.login_id).where(AccountUser.tenant_id == tenant_id)).all())


def _actor_or_master_in_tenant(session, tenant_id: str, actor_login: str) -> Optional[str]:
    """폐기 금지 사유 — 마스터 또는 현재 actor 가 이 tenant 소속이면 그 이유를 반환."""
    from backend.auth import is_master_login
    login_ids = _tenant_user_login_ids(session, tenant_id)
    for lid in login_ids:
        if is_master_login(lid):
            return "마스터 계정이 속한 사업장은 폐기할 수 없습니다."
    if actor_login and actor_login in login_ids:
        return "현재 로그인한 관리자 본인의 계정이 속한 사업장은 폐기할 수 없습니다."
    return None


def _is_pg(session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def _count_by_login_ids(session, table: str, login_ids: list[str]) -> int:
    if not login_ids:
        return 0
    if _is_pg(session):
        return int(session.execute(
            text(f"SELECT count(*) FROM {table} WHERE login_id = ANY(:ids)"),
            {"ids": login_ids}).scalar() or 0)
    import sqlalchemy as _sa
    stmt = text(f"SELECT count(*) FROM {table} WHERE login_id IN :ids").bindparams(
        _sa.bindparam("ids", expanding=True))
    return int(session.execute(stmt, {"ids": login_ids}).scalar() or 0)


def _delete_by_login_ids(session, table: str, login_ids: list[str]) -> int:
    if not login_ids:
        return 0
    if _is_pg(session):
        r = session.execute(text(f"DELETE FROM {table} WHERE login_id = ANY(:ids)"),
                            {"ids": login_ids})
    else:
        import sqlalchemy as _sa
        stmt = text(f"DELETE FROM {table} WHERE login_id IN :ids").bindparams(
            _sa.bindparam("ids", expanding=True))
        r = session.execute(stmt, {"ids": login_ids})
    return int(r.rowcount or 0)


# ── 미리보기 ─────────────────────────────────────────────────────────────────
def purge_preview(tenant_id: str, actor_login: str = "") -> dict:
    """폐기 영향 미리보기(읽기 전용). 테이블별 건수 + blocking 사유 + can_purge."""
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker

    tid = (tenant_id or "").strip()
    if not tid:
        raise PurgeError("BAD_REQUEST", "tenant_id 가 필요합니다.")
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tid))
        if t is None:
            raise PurgeError("NOT_FOUND", "사업장을 찾을 수 없습니다.")

        present = _existing_tables(session)
        counts: dict[str, int] = {}
        for tbl in PURGE_BY_TENANT_ID:
            if tbl in present:
                counts[tbl] = _count(session, tbl, "tenant_id", tid)
        # doc_tree cascade 자식 건수(설명용).
        for parent, children in CASCADE_CHILDREN.items():
            for child in children:
                if child in present and parent in present:
                    counts[child] = int(session.execute(
                        text(f"SELECT count(*) FROM {child} c WHERE EXISTS "
                             f"(SELECT 1 FROM {parent} p WHERE p.id = c.node_id AND p.tenant_id = :v)"),
                        {"v": tid}).scalar() or 0)
        login_ids = _tenant_user_login_ids(session, tid)
        for tbl in PURGE_BY_LOGIN_ID:
            if tbl in present:
                counts[tbl] = _count_by_login_ids(session, tbl, login_ids)
        for tbl in PURGE_BY_APPROVED_TENANT:
            if tbl in present:
                counts[tbl] = _count(session, tbl, "approved_tenant_id", tid)

        # blocking 판정.
        blocking: list[str] = []
        status = _tenant_status(t)
        if status != "suspended":
            blocking.append("정지(suspended) 상태의 사업장만 폐기할 수 있습니다. 먼저 사업장을 정지하세요.")
        if bool(getattr(t, "is_active", False)):
            blocking.append("사업장이 아직 활성(is_active) 상태입니다. 먼저 정지하세요.")
        actor_reason = _actor_or_master_in_tenant(session, tid, actor_login)
        if actor_reason:
            blocking.append(actor_reason)
        ext = _external_storage_blocking(t)
        blocking.extend(ext)
        unclassified = unclassified_tenant_tables(session)
        if unclassified:
            blocking.append("폐기 계획에 분류되지 않은 tenant 테이블이 있어 안전을 위해 폐기를 중단합니다: "
                            + ", ".join(unclassified))

        return {
            "tenant_id": t.tenant_id,
            "office_name": t.office_name or "",
            "service_status": status,
            "is_active": bool(getattr(t, "is_active", False)),
            # 대표 요약 키(프론트 편의) + 전체 테이블별 counts.
            "users": counts.get("users", 0),
            "customers": counts.get("customers", 0),
            "active_tasks": counts.get("active_tasks", 0),
            "planned_tasks": counts.get("planned_tasks", 0),
            "completed_tasks": counts.get("completed_tasks", 0),
            "work_references": counts.get("work_reference_rows", 0),
            "board_posts": counts.get("board_posts", 0),
            "sessions": counts.get("user_sessions", 0),
            "activation_tokens": counts.get("activation_tokens", 0),
            "applications": counts.get("office_applications", 0),
            "counts": counts,
            "external_storage": ext,
            "unclassified_tables": unclassified,
            "blocking_reasons": blocking,
            "can_purge": len(blocking) == 0,
        }


def _tenant_status(t) -> str:
    st = (getattr(t, "service_status", None) or "").strip().lower()
    if st in ("pending_activation", "active", "suspended", "terminated"):
        return st
    return "active" if bool(getattr(t, "is_active", False)) else "pending_activation"


# ── 실행 ─────────────────────────────────────────────────────────────────────
def purge_tenant(tenant_id: str, actor_login: str,
                 confirm_tenant_id: str, confirm_office_name: str,
                 confirmation_phrase: str) -> dict:
    """사업장 전체 폐기 — 단일 트랜잭션·명시적 순서. 성공 시 삭제 건수 요약 반환."""
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker

    tid = (tenant_id or "").strip()
    if not tid:
        raise PurgeError("BAD_REQUEST", "tenant_id 가 필요합니다.")

    SessionLocal = get_sessionmaker()
    deleted: dict[str, int] = {}
    office_name_final = ""
    with SessionLocal() as session:
        # 1) tenant FOR UPDATE.
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tid).with_for_update())
        if t is None:
            raise PurgeError("NOT_FOUND", "사업장을 찾을 수 없습니다.")
        office_name_final = t.office_name or ""

        # 확인 3값 정확 일치.
        if (confirm_tenant_id or "").strip() != tid:
            raise PurgeError("CONFIRM_MISMATCH", "확인용 사업장 ID가 일치하지 않습니다.")
        if (confirm_office_name or "").strip() != (t.office_name or "").strip():
            raise PurgeError("CONFIRM_MISMATCH", "확인용 사무소명이 일치하지 않습니다.")
        if (confirmation_phrase or "").strip() != CONFIRMATION_PHRASE:
            raise PurgeError("CONFIRM_MISMATCH", f"확인 문구가 일치하지 않습니다. '{CONFIRMATION_PHRASE}' 를 정확히 입력하세요.")

        # 2) 상태 재검증(잠금 이후).
        if _tenant_status(t) != "suspended":
            raise PurgeError("BAD_STATE", "정지(suspended) 상태의 사업장만 폐기할 수 있습니다.")
        if bool(getattr(t, "is_active", False)):
            raise PurgeError("BAD_STATE", "사업장이 아직 활성 상태입니다. 먼저 정지하세요.")

        # 3) 마스터·현재 actor 보호.
        actor_reason = _actor_or_master_in_tenant(session, tid, actor_login)
        if actor_reason:
            raise PurgeError("PROTECTED", actor_reason)

        # 4) 미분류 tenant 테이블 발견 시 중단.
        unclassified = unclassified_tenant_tables(session)
        if unclassified:
            raise PurgeError("UNCLASSIFIED_TABLES",
                             "폐기 계획에 분류되지 않은 tenant 테이블이 있어 중단합니다: " + ", ".join(unclassified))

        # 5) 외부 저장소 미해결 시 fail-closed(DB 만 먼저 지우지 않음).
        ext = _external_storage_blocking(t)
        if ext:
            raise PurgeError("EXTERNAL_STORAGE", "외부 저장소 참조가 남아 있어 폐기할 수 없습니다: " + " / ".join(ext))

        present = _existing_tables(session)
        login_ids = _tenant_user_login_ids(session, tid)

        # 6) 관련 세션 무효화(best-effort — 실제 삭제로 세션 행도 지워진다).
        try:
            from backend.services.session_pg_service import revoke_active_sessions
            for lid in login_ids:
                revoke_active_sessions(lid, reason="tenant_purged", only_non_kiosk=False)
        except Exception:
            pass

        # 7) 자식 데이터부터 명시적 순서로 삭제(같은 트랜잭션).
        #    login_attempts 는 users 삭제 전에 login_id 로 정리(간접 참조).
        if login_ids:
            for tbl in PURGE_BY_LOGIN_ID:
                if tbl in present:
                    deleted[tbl] = _delete_by_login_ids(session, tbl, login_ids)

        # office_applications: 이 tenant 를 만든 신청서 삭제(PII 제거).
        for tbl in PURGE_BY_APPROVED_TENANT:
            if tbl in present:
                r = session.execute(
                    text(f"DELETE FROM {tbl} WHERE approved_tenant_id = :v"), {"v": tid})
                deleted[tbl] = int(r.rowcount or 0)

        # tenant_id 컬럼 기준 삭제(자식 전부 → users 포함). tenants 는 마지막.
        for tbl in PURGE_BY_TENANT_ID:
            if tbl in present:
                r = session.execute(
                    text(f"DELETE FROM {tbl} WHERE tenant_id = :v"), {"v": tid})
                deleted[tbl] = int(r.rowcount or 0)

        # 8) tenant 삭제(마지막).
        r = session.execute(text("DELETE FROM tenants WHERE tenant_id = :v"), {"v": tid})
        deleted["tenants"] = int(r.rowcount or 0)

        session.commit()

    # 감사(커밋 후, PII 없음 — actor + tenant_id 해시 + 건수 요약만).
    try:
        from backend.services import audit_service
        total = sum(deleted.values())
        audit_service.log_event(
            action="tenant_purged",
            actor_login_id=actor_login or None,
            tenant_id=None,  # 삭제된 tenant 를 FK/식별로 남기지 않는다.
            target_type="tenant",
            target_id=_hash_tid(tid),  # tenant_id 해시(원문 미기록)
            payload={"tenant_id_hash": _hash_tid(tid), "deleted_total": total,
                     "deleted_counts": deleted},
        )
    except Exception:
        pass

    return {
        "ok": True,
        "tenant_id": tid,
        "office_name": office_name_final,
        "deleted_counts": deleted,
        "deleted_total": sum(deleted.values()),
    }
