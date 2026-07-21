"""사무소 이용신청 + 수동 승인 — PostgreSQL 서비스(승인형 SaaS).

원칙:
- 공개 신청은 신청서(office_applications)만 저장한다. **승인 전까지 tenants/users 미생성.**
- 승인은 **하나의 DB 트랜잭션**으로 tenant 1개 + user 2개 + activation 토큰 2개를 원자적으로 만든다.
  중복 클릭/재시도에도 tenant/user 가 중복 생성되지 않도록 상태잠금 + 멱등 반환으로 보장한다.
- 승인 여부는 항상 사람이 결정한다. 시스템은 중복 위험 **경고만** 계산하고 자동 반려하지 않는다.

audit 는 트랜잭션 커밋 이후에만 기록한다(롤백된 승인이 로그로 남지 않도록).
"""
from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy import select, func

# 상태
ST_PENDING = "pending"
ST_REVIEWING = "reviewing"
ST_APPROVED = "approved"
ST_REJECTED = "rejected"
ST_CANCELLED = "cancelled"

SERVICE_TIER_DEFAULT = "managed_basic"
SEAT_LIMIT_DEFAULT = 2


class ApplicationError(Exception):
    """도메인 오류 — 라우터가 code 로 HTTP 상태를 결정한다."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _gen_application_id() -> str:
    # 공개 접수번호 — 추측 불가 + 사람이 읽을 수 있는 형태.
    return "APP-" + secrets.token_hex(4).upper()


def _gen_tenant_id(session) -> str:
    from backend.db.models.tenant import Tenant
    for _ in range(10):
        tid = "of-" + secrets.token_hex(5)
        if session.scalar(select(Tenant.id).where(Tenant.tenant_id == tid)) is None:
            return tid
    raise ApplicationError("TENANT_ID_GEN", "테넌트 ID 생성에 실패했습니다.")


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _norm_email(v: Optional[str]) -> str:
    return (v or "").strip().lower()


# ── 신청 생성 ────────────────────────────────────────────────────────────────
def create_application(data: dict, ip_hash: Optional[str] = None) -> dict:
    """공개 신청서를 저장한다. tenants/users 는 만들지 않는다."""
    from backend.db.models.office_application import OfficeApplication
    from backend.db.session import get_sessionmaker

    office_name = (data.get("office_name") or "").strip()
    if not office_name:
        raise ApplicationError("MISSING_OFFICE_NAME", "사무소명을 입력해 주세요.")
    applicant_email = _norm_email(data.get("applicant_email"))
    if applicant_email and not _EMAIL_RE.match(applicant_email):
        raise ApplicationError("BAD_EMAIL", "신청 담당자 이메일 형식이 올바르지 않습니다.")
    for key in ("requested_user_1_email", "requested_user_2_email"):
        v = _norm_email(data.get(key))
        if v and not _EMAIL_RE.match(v):
            raise ApplicationError("BAD_EMAIL", "계정 사용자 이메일 형식이 올바르지 않습니다.")

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # 중복 제출 방지 — 동일 사무소명 + 동일 신청 이메일이 이미 미결(pending/reviewing)이면 차단.
        if applicant_email:
            dup = session.scalar(
                select(OfficeApplication.id).where(
                    func.lower(OfficeApplication.office_name) == office_name.lower(),
                    OfficeApplication.applicant_email == applicant_email,
                    OfficeApplication.status.in_([ST_PENDING, ST_REVIEWING]),
                )
            )
            if dup is not None:
                raise ApplicationError("DUPLICATE_PENDING", "이미 접수되어 심사 중인 신청이 있습니다.")

        flags = _compute_duplicate_flags(session, data, ip_hash)
        app = OfficeApplication(
            application_id=_gen_application_id(),
            status=ST_PENDING,
            office_name=office_name,
            representative_name=(data.get("representative_name") or "").strip() or None,
            business_registration_number=(data.get("business_registration_number") or "").strip() or None,
            office_address=(data.get("office_address") or "").strip() or None,
            office_phone=(data.get("office_phone") or "").strip() or None,
            applicant_name=(data.get("applicant_name") or "").strip() or None,
            applicant_email=applicant_email or None,
            applicant_phone=(data.get("applicant_phone") or "").strip() or None,
            intended_use=(data.get("intended_use") or "").strip() or None,
            requested_user_1_name=(data.get("requested_user_1_name") or "").strip() or None,
            requested_user_1_email=_norm_email(data.get("requested_user_1_email")) or None,
            requested_user_2_name=(data.get("requested_user_2_name") or "").strip() or None,
            requested_user_2_email=_norm_email(data.get("requested_user_2_email")) or None,
            submitted_at=_now(),
            duplicate_flags=flags or None,
            submit_ip_hash=ip_hash,
        )
        session.add(app)
        session.commit()
        return {"application_id": app.application_id, "status": app.status}


# ── 중복/위험 경고 계산 (자동 반려 아님 — 사람 판단 보조) ──────────────────────
def _compute_duplicate_flags(session, data: dict, ip_hash: Optional[str]) -> dict:
    from backend.db.models.office_application import OfficeApplication
    from backend.db.models.tenant import Tenant

    flags: dict[str, Any] = {}
    biz = (data.get("business_registration_number") or "").strip()
    phone = (data.get("office_phone") or "").strip()
    email = _norm_email(data.get("applicant_email"))
    addr = (data.get("office_address") or "").strip()
    rep = (data.get("representative_name") or "").strip()
    office = (data.get("office_name") or "").strip()

    if biz:
        if session.scalar(select(Tenant.id).where(Tenant.biz_reg_no == biz)) is not None:
            flags["existing_tenant_biz_reg_no"] = True
        c = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            OfficeApplication.business_registration_number == biz))
        if c and c > 0:
            flags["duplicate_biz_reg_no_applications"] = int(c)
    if phone:
        c = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            OfficeApplication.office_phone == phone))
        if c and c > 0:
            flags["duplicate_office_phone"] = int(c)
    if email:
        c = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            OfficeApplication.applicant_email == email))
        if c and c > 0:
            flags["duplicate_applicant_email"] = int(c)
    if addr:
        c = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            OfficeApplication.office_address == addr))
        if c and c > 0:
            flags["duplicate_office_address"] = int(c)
    if rep:
        c = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            OfficeApplication.representative_name == rep))
        if c and c > 0:
            flags["duplicate_representative_name"] = int(c)
    if office:
        c = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            func.lower(OfficeApplication.office_name) == office.lower(),
            OfficeApplication.status == ST_REJECTED))
        if c and c > 0:
            flags["matches_rejected_office"] = int(c)
    # suspended/terminated tenant 와 일치(사업자번호 기준)
    if biz:
        try:
            c = session.scalar(select(func.count()).select_from(Tenant).where(
                Tenant.biz_reg_no == biz, Tenant.service_status.in_(["suspended", "terminated"])))
            if c and c > 0:
                flags["matches_suspended_tenant"] = int(c)
        except Exception:
            pass  # service_status 컬럼 미적용(0031 전) — 조용히 건너뜀
    if ip_hash:
        since = _now() - timedelta(hours=1)
        c = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            OfficeApplication.submit_ip_hash == ip_hash,
            OfficeApplication.created_at >= since))
        if c and c > 1:
            flags["repeated_ip_1h"] = int(c)
    # 필수정보 누락
    missing = [k for k in ("office_name", "representative_name", "business_registration_number",
                           "applicant_email") if not (data.get(k) or "").strip()]
    if missing:
        flags["missing_fields"] = missing
    return flags


# ── 조회 ────────────────────────────────────────────────────────────────────
def _to_dict(app) -> dict:
    return {
        "id": app.id,
        "application_id": app.application_id,
        "status": app.status,
        "office_name": app.office_name,
        "representative_name": app.representative_name,
        "business_registration_number": app.business_registration_number,
        "office_address": app.office_address,
        "office_phone": app.office_phone,
        "applicant_name": app.applicant_name,
        "applicant_email": app.applicant_email,
        "applicant_phone": app.applicant_phone,
        "intended_use": app.intended_use,
        "requested_user_1_name": app.requested_user_1_name,
        "requested_user_1_email": app.requested_user_1_email,
        "requested_user_2_name": app.requested_user_2_name,
        "requested_user_2_email": app.requested_user_2_email,
        "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        "review_started_at": app.review_started_at.isoformat() if app.review_started_at else None,
        "reviewed_at": app.reviewed_at.isoformat() if app.reviewed_at else None,
        "reviewed_by": app.reviewed_by,
        "rejection_reason_public": app.rejection_reason_public,
        "review_note_internal": app.review_note_internal,
        "approved_tenant_id": app.approved_tenant_id,
        "duplicate_flags": app.duplicate_flags or {},
        "created_at": app.created_at.isoformat() if app.created_at else None,
    }


def list_applications(status: Optional[str] = None) -> list[dict]:
    from backend.db.models.office_application import OfficeApplication
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        stmt = select(OfficeApplication).order_by(OfficeApplication.created_at.desc())
        if status:
            stmt = stmt.where(OfficeApplication.status == status)
        return [_to_dict(a) for a in session.scalars(stmt).all()]


def get_application(application_id: str) -> Optional[dict]:
    from backend.db.models.office_application import OfficeApplication
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        a = session.scalar(select(OfficeApplication).where(
            OfficeApplication.application_id == application_id))
        return _to_dict(a) if a else None


# ── 심사 전환 ────────────────────────────────────────────────────────────────
def start_review(application_id: str, reviewer: str) -> dict:
    from backend.db.models.office_application import OfficeApplication
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        a = session.scalar(select(OfficeApplication).where(
            OfficeApplication.application_id == application_id))
        if a is None:
            raise ApplicationError("NOT_FOUND", "신청을 찾을 수 없습니다.")
        if a.status not in (ST_PENDING, ST_REVIEWING):
            raise ApplicationError("BAD_STATE", "이미 처리된 신청입니다.")
        a.status = ST_REVIEWING
        if a.review_started_at is None:
            a.review_started_at = _now()
        a.reviewed_by = reviewer
        session.commit()
        result = _to_dict(a)
    _audit("office_application_review_started", reviewer, application_id, None,
           {"application_id": application_id})
    return result


def update_review_note(application_id: str, reviewer: str,
                       note_internal: Optional[str]) -> dict:
    from backend.db.models.office_application import OfficeApplication
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        a = session.scalar(select(OfficeApplication).where(
            OfficeApplication.application_id == application_id))
        if a is None:
            raise ApplicationError("NOT_FOUND", "신청을 찾을 수 없습니다.")
        if note_internal is not None:
            a.review_note_internal = note_internal
        session.commit()
        return _to_dict(a)


def reject(application_id: str, reviewer: str, reason_public: str,
           note_internal: Optional[str] = None) -> dict:
    from backend.db.models.office_application import OfficeApplication
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        a = session.scalar(select(OfficeApplication).where(
            OfficeApplication.application_id == application_id))
        if a is None:
            raise ApplicationError("NOT_FOUND", "신청을 찾을 수 없습니다.")
        if a.status == ST_APPROVED:
            raise ApplicationError("ALREADY_APPROVED", "이미 승인된 신청은 반려할 수 없습니다.")
        if a.status in (ST_REJECTED, ST_CANCELLED):
            raise ApplicationError("BAD_STATE", "이미 종료된 신청입니다.")
        a.status = ST_REJECTED
        a.reviewed_at = _now()
        a.reviewed_by = reviewer
        a.rejection_reason_public = (reason_public or "").strip() or None
        if note_internal is not None:
            a.review_note_internal = note_internal
        session.commit()
        result = _to_dict(a)
    _audit("office_application_rejected", reviewer, application_id, None,
           {"application_id": application_id})
    return result


# ── 승인 (원자적 트랜잭션) ────────────────────────────────────────────────────
def approve(application_id: str, reviewer: str,
            user1: Optional[dict] = None, user2: Optional[dict] = None,
            seat_limit: int = SEAT_LIMIT_DEFAULT) -> dict:
    """신청 승인 — tenant 1개 + user 2개 + activation 토큰 2개를 하나의 트랜잭션으로 생성.

    멱등: 이미 승인된 신청이면 재생성하지 않고 기존 tenant 정보를 반환한다.
    한 단계라도 실패하면 전체 롤백된다.
    user1/user2 = {"name","email","role"} — 미지정 시 신청서의 requested_user_* 사용.
    role: 'office_admin'(=is_admin true) | 'office_staff'(=일반). 기존 역할체계 재사용.
    """
    from backend.db.models.office_application import OfficeApplication
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker
    from backend.services.accounts_service import hash_password
    from backend.services import activation_pg_service as _act

    SessionLocal = get_sessionmaker()
    audit_events: list[tuple] = []
    result: dict

    with SessionLocal() as session:
        # 트랜잭션 시작 — 신청 행 잠금(중복 승인 차단).
        a = session.scalar(
            select(OfficeApplication)
            .where(OfficeApplication.application_id == application_id)
            .with_for_update()
        )
        if a is None:
            raise ApplicationError("NOT_FOUND", "신청을 찾을 수 없습니다.")
        # 멱등: 이미 승인됨 → 재생성하지 않고 기존 결과 반환.
        if a.status == ST_APPROVED and a.approved_tenant_id:
            return {
                "already_approved": True,
                "application_id": application_id,
                "tenant_id": a.approved_tenant_id,
                "users": [],
            }
        if a.status in (ST_REJECTED, ST_CANCELLED):
            raise ApplicationError("BAD_STATE", "반려/취소된 신청은 승인할 수 없습니다.")

        # 계정 2명 정보 확정(요청 override > 신청서 값).
        u1 = {
            "name": ((user1 or {}).get("name") or a.requested_user_1_name or "").strip(),
            "email": _norm_email((user1 or {}).get("email") or a.requested_user_1_email),
            "role": ((user1 or {}).get("role") or "office_admin").strip(),
        }
        u2 = {
            "name": ((user2 or {}).get("name") or a.requested_user_2_name or "").strip(),
            "email": _norm_email((user2 or {}).get("email") or a.requested_user_2_email),
            "role": ((user2 or {}).get("role") or "office_staff").strip(),
        }
        for u in (u1, u2):
            if not u["name"] or not u["email"]:
                raise ApplicationError("MISSING_USER", "계정 2명의 이름과 이메일이 모두 필요합니다.")
            if not _EMAIL_RE.match(u["email"]):
                raise ApplicationError("BAD_EMAIL", "계정 이메일 형식이 올바르지 않습니다.")
        if u1["email"] == u2["email"]:
            raise ApplicationError("DUPLICATE_USER_EMAIL", "두 계정의 이메일이 동일합니다.")

        # 좌석 한도 원자 검증 — 승인은 초대 계정 2개를 만든다. seat_limit 이 이보다 작으면
        # 활성화 시점에 2번째 계정이 반드시 막히므로(모순 상태) 승인 자체를 거부한다.
        effective_seat = int(seat_limit or SEAT_LIMIT_DEFAULT)
        if 2 > effective_seat:
            raise ApplicationError(
                "SEAT_LIMIT",
                f"좌석 한도({effective_seat})가 발급 계정 수(2)보다 적습니다. 좌석 한도를 2 이상으로 설정하세요.")

        # 전역 login_id(=email) 중복 방지.
        for u in (u1, u2):
            if session.scalar(select(AccountUser.id).where(AccountUser.login_id == u["email"])) is not None:
                raise ApplicationError("EMAIL_IN_USE", f"이미 사용 중인 이메일입니다: {u['email']}")

        tenant_id = _gen_tenant_id(session)
        now = _now()

        # tenant 생성.
        t = Tenant(
            tenant_id=tenant_id,
            office_name=a.office_name,
            office_adr=a.office_address,
            biz_reg_no=a.business_registration_number,
            is_active=True,
        )
        t.service_tier = SERVICE_TIER_DEFAULT
        t.seat_limit = int(seat_limit or SEAT_LIMIT_DEFAULT)
        t.service_status = "pending_activation"
        t.approved_at = now
        t.approved_by = reviewer
        t.source_application_id = application_id
        session.add(t)
        session.flush()

        raw_tokens: list[dict] = []
        for u in (u1, u2):
            is_admin = (u["role"] == "office_admin")
            row = AccountUser(
                login_id=u["email"],
                tenant_id=tenant_id,
                password_hash=hash_password(secrets.token_urlsafe(32)),  # 사용 불가 임시값 — activation 전 로그인 불가
                contact_name=u["name"],
                is_admin=is_admin,
                is_active=False,  # activation 완료 전 로그인 차단
            )
            row.role = "admin" if is_admin else "user"
            row.account_status = "invited"
            row.invited_at = now
            row.approved_at = now
            row.approved_by = reviewer
            session.add(row)
            session.flush()
            raw = _act.issue_activation_token(session, u["email"], tenant_id)
            raw_tokens.append({
                "login_id": u["email"], "name": u["name"], "role": u["role"],
                "is_admin": is_admin, "activation_token": raw,
            })
            audit_events.append(("user_invited", reviewer, u["email"], tenant_id,
                                 {"role": u["role"]}))
            audit_events.append(("user_role_assigned", reviewer, u["email"], tenant_id,
                                 {"role": u["role"], "is_admin": is_admin}))

        # 신청 승인 처리.
        a.status = ST_APPROVED
        a.reviewed_at = now
        a.reviewed_by = reviewer
        a.approved_tenant_id = tenant_id

        session.commit()  # ← 여기서 tenant+user2+token2+application 이 원자적으로 확정
        result = {
            "already_approved": False,
            "application_id": application_id,
            "tenant_id": tenant_id,
            "seat_limit": int(seat_limit or SEAT_LIMIT_DEFAULT),
            "users": raw_tokens,
        }

    # 커밋 성공 후에만 감사 기록(롤백된 승인이 로그로 남지 않도록).
    _audit("tenant_created_from_application", reviewer, application_id, result["tenant_id"],
           {"application_id": application_id})
    for action, actor, target, tid, payload in audit_events:
        _audit(action, actor, target, tid, payload)
    _audit("office_application_approved", reviewer, application_id, result["tenant_id"],
           {"application_id": application_id, "user_count": len(result["users"])})
    return result


def _audit(action: str, actor: Optional[str], target_id: Optional[str],
           tenant_id: Optional[str], payload: Optional[dict]) -> None:
    try:
        from backend.services import audit_service
        audit_service.log_event(
            action=action, actor_login_id=actor, tenant_id=tenant_id,
            target_type="office_application" if action.startswith("office_application") else "tenant",
            target_id=target_id, payload=payload,
        )
    except Exception:
        pass
