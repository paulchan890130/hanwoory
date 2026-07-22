"""사무소 이용신청 + 수동 승인 — PostgreSQL 서비스(승인형 SaaS).

원칙:
- 공개 신청은 신청서(office_applications)만 저장한다. **승인 전까지 tenants/users 미생성.**
- 승인은 **하나의 DB 트랜잭션**으로 tenant 1개 + user 2개 + activation 토큰 2개를 원자적으로 만든다.
  중복 클릭/재시도에도 tenant/user 가 중복 생성되지 않도록 상태잠금 + 멱등 반환으로 보장한다.
- 승인 여부는 항상 사람이 결정한다. 시스템은 중복 위험 **경고만** 계산하고 자동 반려하지 않는다.

audit 는 트랜잭션 커밋 이후에만 기록한다(롤백된 승인이 로그로 남지 않도록).
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy import select, func, text

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


# ── 사업자등록번호 / 전화번호 정규화·형식화 (프론트/백엔드 공통 규칙) ──────────────
def normalize_biz_reg_no(v: Optional[str]) -> str:
    """구분자 제거 후 숫자만 남긴다(digits-only 저장/비교용)."""
    return re.sub(r"[^0-9]", "", v or "")


def is_valid_biz_reg_no(digits: str) -> bool:
    return len(digits or "") == 10 and (digits or "").isdigit()


def format_biz_reg_no(v: Optional[str]) -> str:
    """관리자 표시용 하이픈 형식(213-12-37464). 10자리가 아니면 원본 digits 반환."""
    d = normalize_biz_reg_no(v)
    return f"{d[:3]}-{d[3:5]}-{d[5:]}" if len(d) == 10 else d


def normalize_phone(v: Optional[str]) -> str:
    return re.sub(r"[^0-9]", "", v or "")


def is_valid_phone(digits: str) -> bool:
    """한국 전화 digits — 9~11자리, 0으로 시작."""
    d = digits or ""
    return 9 <= len(d) <= 11 and d.isdigit() and d[:1] == "0"


def format_phone(v: Optional[str]) -> str:
    """관리자 표시용 하이픈 형식. 규칙 밖이면 digits 원본."""
    d = normalize_phone(v)
    if d.startswith("02"):
        if len(d) == 9:
            return f"{d[:2]}-{d[2:5]}-{d[5:]}"      # 02-123-4567
        if len(d) == 10:
            return f"{d[:2]}-{d[2:6]}-{d[6:]}"      # 02-1234-5678
    else:
        if len(d) == 10:
            return f"{d[:3]}-{d[3:6]}-{d[6:]}"      # 010-123-4567 / 031-123-4567
        if len(d) == 11:
            return f"{d[:3]}-{d[3:7]}-{d[7:]}"      # 010-1234-5678
    return d


def _biz_match_forms(v: Optional[str]) -> list[str]:
    """digits + 표준 하이픈형 — 구버전(하이픈 저장) 행과도 중복 감지되도록 두 형태로 비교."""
    d = normalize_biz_reg_no(v)
    if not d:
        return []
    forms = {d}
    if len(d) == 10:
        forms.add(format_biz_reg_no(d))
    return list(forms)


def _phone_match_forms(v: Optional[str]) -> list[str]:
    d = normalize_phone(v)
    if not d:
        return []
    forms = {d}
    f = format_phone(d)
    if f:
        forms.add(f)
    return list(forms)


def _canonical_application_input(data: dict) -> dict:
    """공개 신청 입력을 하나의 canonical 구조로 변환한다.

    신규 필드(representative_email / staff_name / staff_email)를 우선 사용하되,
    롤링 배포·구버전 클라이언트 호환을 위해 기존 requested_user_* fallback 을 허용한다.
    """
    rep_name = (data.get("representative_name") or data.get("requested_user_1_name") or "").strip()
    rep_email = _norm_email(data.get("representative_email") or data.get("requested_user_1_email"))
    staff_name = (data.get("staff_name") or data.get("requested_user_2_name") or "").strip()
    staff_email = _norm_email(data.get("staff_email") or data.get("requested_user_2_email"))
    return {
        "office_name": (data.get("office_name") or "").strip(),
        "representative_name": rep_name,
        "representative_email": rep_email,
        "staff_name": staff_name,
        "staff_email": staff_email,
        "business_registration_number": normalize_biz_reg_no(data.get("business_registration_number")),
        "office_address": (data.get("office_address") or "").strip(),
        "office_phone": normalize_phone(data.get("office_phone")),
    }


# ── 중복 방지 지문(fingerprint) + 동시성 직렬화 ───────────────────────────────
def _norm_office_name(v: Optional[str]) -> str:
    """대소문자·연속 공백을 정규화(중복 판정용)."""
    return re.sub(r"\s+", " ", (v or "").strip()).lower()


def _application_fingerprint(c: dict) -> str:
    """정규화된 사무소명 | 사업자번호(digits) | 대표자 이메일 | 실무자 이메일. 로그에 남기지 않는다."""
    return "|".join([
        _norm_office_name(c.get("office_name")),
        c.get("business_registration_number") or "",
        c.get("representative_email") or "",
        c.get("staff_email") or "",
    ])


def _advisory_key(fp: str) -> int:
    """fingerprint → signed 64-bit advisory lock key(SHA-256 앞 8바이트)."""
    val = int.from_bytes(hashlib.sha256(fp.encode("utf-8")).digest()[:8], "big", signed=False)
    return val - (1 << 64) if val >= (1 << 63) else val


def _acquire_fingerprint_lock(session, fp: str) -> None:
    """PostgreSQL 에서만 pg_advisory_xact_lock 으로 같은 fingerprint 요청을 직렬화한다.
    트랜잭션 종료 시 자동 해제. SQLite 등에서는 no-op(단위 테스트는 단일 스레드)."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _advisory_key(fp)})


def _find_pending_by_fingerprint(session, c: dict, exclude_id: Optional[int] = None):
    """동일 fingerprint(정확 일치)의 pending/reviewing 신청 행들(id 오름차순)."""
    from backend.db.models.office_application import OfficeApplication
    stmt = (
        select(OfficeApplication)
        .where(
            func.lower(func.trim(OfficeApplication.office_name)) == _norm_office_name(c.get("office_name")),
            OfficeApplication.business_registration_number == (c.get("business_registration_number") or None),
            OfficeApplication.requested_user_1_email == (c.get("representative_email") or None),
            OfficeApplication.requested_user_2_email == (c.get("staff_email") or None),
            OfficeApplication.status.in_([ST_PENDING, ST_REVIEWING]),
        )
        .order_by(OfficeApplication.id.asc())
    )
    if exclude_id is not None:
        stmt = stmt.where(OfficeApplication.id != exclude_id)
    return list(session.scalars(stmt).all())


# ── 신청 생성 ────────────────────────────────────────────────────────────────
def create_application(data: dict, ip_hash: Optional[str] = None) -> dict:
    """공개 신청서를 저장한다. tenants/users 는 만들지 않는다.

    canonical 구조: 사무소 정보 + 대표자(승인 시 office_admin) + 실무자(office_staff) 1명.
    저장은 기존 컬럼을 재사용한다(신규 migration 없음):
      representative_email → requested_user_1_email, representative_name → requested_user_1_name,
      staff_name/email → requested_user_2_*. applicant_*/intended_use 는 null.
    """
    from backend.db.models.office_application import OfficeApplication
    from backend.db.session import get_sessionmaker

    c = _canonical_application_input(data)

    # 필수값 서버 재검증(공백 문자열 차단).
    if not c["office_name"]:
        raise ApplicationError("MISSING_OFFICE_NAME", "사무소명을 입력해 주세요.")
    if not c["representative_name"]:
        raise ApplicationError("MISSING_FIELD", "대표자명을 입력해 주세요.")
    if not c["representative_email"]:
        raise ApplicationError("MISSING_FIELD", "대표자 이메일을 입력해 주세요.")
    if not c["staff_name"]:
        raise ApplicationError("MISSING_FIELD", "실무자 이름을 입력해 주세요.")
    if not c["staff_email"]:
        raise ApplicationError("MISSING_FIELD", "실무자 이메일을 입력해 주세요.")
    if not _EMAIL_RE.match(c["representative_email"]):
        raise ApplicationError("BAD_EMAIL", "대표자 이메일 형식이 올바르지 않습니다.")
    if not _EMAIL_RE.match(c["staff_email"]):
        raise ApplicationError("BAD_EMAIL", "실무자 이메일 형식이 올바르지 않습니다.")
    if c["representative_email"] == c["staff_email"]:
        raise ApplicationError("DUPLICATE_USER_EMAIL", "대표자와 실무자의 이메일이 동일합니다. 서로 다른 이메일을 입력해 주세요.")
    if not is_valid_biz_reg_no(c["business_registration_number"]):
        raise ApplicationError("BAD_BIZ_REG_NO", "사업자등록번호 10자리를 입력해 주세요.")
    if c["office_phone"] and not is_valid_phone(c["office_phone"]):
        raise ApplicationError("BAD_PHONE", "전화번호 형식이 올바르지 않습니다. 숫자 9~11자리로 입력해 주세요.")

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # 동시 제출 직렬화 — 같은 fingerprint(사무소명·사업자번호·대표자/실무자 이메일) 요청을
        # advisory lock 으로 순서화한 뒤 중복 조회+insert 를 수행한다. 이 lock 이 없으면 동시 요청
        # 두 개가 모두 SELECT 를 통과해 신청 행이 2개 생성된다(중복 신청 근본 원인).
        _acquire_fingerprint_lock(session, _application_fingerprint(c))

        # 중복 제출 방지 — 정확 일치 fingerprint 의 미결(pending/reviewing) 신청이 이미 있으면 차단.
        # (§7-1: 순차/동시 중복은 1행만 남기고 나머지는 DUPLICATE_PENDING.)
        dup = _find_pending_by_fingerprint(session, c)
        if dup:
            raise ApplicationError(
                "DUPLICATE_PENDING",
                f"이미 같은 내용의 신청이 접수되어 심사 중입니다. 기존 접수번호: {dup[0].application_id}")

        flags = _compute_duplicate_flags(session, c, ip_hash)
        app = OfficeApplication(
            application_id=_gen_application_id(),
            status=ST_PENDING,
            office_name=c["office_name"],
            representative_name=c["representative_name"] or None,
            business_registration_number=c["business_registration_number"] or None,  # digits-only
            office_address=c["office_address"] or None,
            office_phone=c["office_phone"] or None,                                  # digits-only
            # applicant_*/intended_use 는 신규 신청에서 사용하지 않음(구조 단순화).
            applicant_name=None,
            applicant_email=None,
            applicant_phone=None,
            intended_use=None,
            # 대표자를 requested_user_1(승인 시 office_admin), 실무자를 requested_user_2 로 매핑.
            requested_user_1_name=c["representative_name"] or None,
            requested_user_1_email=c["representative_email"] or None,
            requested_user_2_name=c["staff_name"] or None,
            requested_user_2_email=c["staff_email"] or None,
            submitted_at=_now(),
            duplicate_flags=flags or None,
            submit_ip_hash=ip_hash,
        )
        session.add(app)
        session.commit()
        return {"application_id": app.application_id, "status": app.status}


# ── 중복/위험 경고 계산 (자동 반려 아님 — 사람 판단 보조) ──────────────────────
def _compute_duplicate_flags(session, c: dict, ip_hash: Optional[str]) -> dict:
    """중복·위험 경고(자동 반려 아님 — 사람 판단 보조). canonical 입력 c 를 받는다.

    사업자번호·전화번호는 digits/하이픈 두 형태로 비교해 구버전(하이픈 저장) 행과도 감지된다.
    대표자 이메일(requested_user_1_email) 기준으로 이메일 중복을 계산한다.
    """
    from backend.db.models.office_application import OfficeApplication
    from backend.db.models.tenant import Tenant

    flags: dict[str, Any] = {}
    biz_forms = _biz_match_forms(c.get("business_registration_number"))
    phone_forms = _phone_match_forms(c.get("office_phone"))
    email = c.get("representative_email") or ""
    addr = (c.get("office_address") or "").strip()
    rep = (c.get("representative_name") or "").strip()
    office = (c.get("office_name") or "").strip()

    if biz_forms:
        if session.scalar(select(Tenant.id).where(Tenant.biz_reg_no.in_(biz_forms))) is not None:
            flags["existing_tenant_biz_reg_no"] = True
        n = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            OfficeApplication.business_registration_number.in_(biz_forms)))
        if n and n > 0:
            flags["duplicate_biz_reg_no_applications"] = int(n)
    if phone_forms:
        n = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            OfficeApplication.office_phone.in_(phone_forms)))
        if n and n > 0:
            flags["duplicate_office_phone"] = int(n)
    if email:
        # 대표자 이메일은 requested_user_1_email 에 저장된다(구조 단순화 후 canonical).
        n = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            OfficeApplication.requested_user_1_email == email))
        if n and n > 0:
            flags["duplicate_representative_email"] = int(n)
        # 전역 계정(users.login_id) 과 이미 충돌하는지도 경고.
        try:
            from backend.db.models.user import AccountUser
            if session.scalar(select(AccountUser.id).where(AccountUser.login_id == email)) is not None:
                flags["existing_account_representative_email"] = True
        except Exception:
            pass
    if addr:
        n = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            OfficeApplication.office_address == addr))
        if n and n > 0:
            flags["duplicate_office_address"] = int(n)
    if rep:
        n = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            OfficeApplication.representative_name == rep))
        if n and n > 0:
            flags["duplicate_representative_name"] = int(n)
    if office:
        n = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            func.lower(OfficeApplication.office_name) == office.lower(),
            OfficeApplication.status == ST_REJECTED))
        if n and n > 0:
            flags["matches_rejected_office"] = int(n)
    if biz_forms:
        try:
            n = session.scalar(select(func.count()).select_from(Tenant).where(
                Tenant.biz_reg_no.in_(biz_forms), Tenant.service_status.in_(["suspended", "terminated"])))
            if n and n > 0:
                flags["matches_suspended_tenant"] = int(n)
        except Exception:
            pass  # service_status 컬럼 미적용(0031 전) — 조용히 건너뜀
    if ip_hash:
        since = _now() - timedelta(hours=1)
        n = session.scalar(select(func.count()).select_from(OfficeApplication).where(
            OfficeApplication.submit_ip_hash == ip_hash,
            OfficeApplication.created_at >= since))
        if n and n > 1:
            flags["repeated_ip_1h"] = int(n)
    return flags


# ── 조회 ────────────────────────────────────────────────────────────────────
def _to_dict(app) -> dict:
    # canonical 대표자/실무자 — 신규 행은 requested_user_1(대표자)/requested_user_2(실무자).
    # 구버전 행 호환: 대표자 이메일이 없으면 applicant_email 로 fallback 표시.
    rep_name = app.representative_name or app.requested_user_1_name
    rep_email = app.requested_user_1_email or app.applicant_email
    staff_name = app.requested_user_2_name
    staff_email = app.requested_user_2_email
    return {
        "id": app.id,
        "application_id": app.application_id,
        "status": app.status,
        "office_name": app.office_name,
        "representative_name": rep_name,
        "representative_email": rep_email,
        "staff_name": staff_name,
        "staff_email": staff_email,
        "business_registration_number": app.business_registration_number,
        "business_registration_number_formatted": format_biz_reg_no(app.business_registration_number),
        "office_address": app.office_address,
        "office_phone": app.office_phone,
        "office_phone_formatted": format_phone(app.office_phone),
        # 구버전 신청 열람 호환(신규 신청에서는 null).
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
        apps = list(session.scalars(stmt).all())
        dicts = [_to_dict(a) for a in apps]
        # 미결(pending/reviewing) 신청들 사이의 정확 일치 중복 그룹을 **추가 쿼리 없이** in-memory
        # 로 계산해 각 dict 에 표시한다(§3-4). 승인 시 나머지는 자동 취소된다.
        groups: dict[str, list[dict]] = {}
        for a, d in zip(apps, dicts):
            d["duplicate_pending_count"] = 0
            d["duplicate_pending_ids"] = []
            if a.status in (ST_PENDING, ST_REVIEWING):
                fp = _application_fingerprint({
                    "office_name": a.office_name,
                    "business_registration_number": a.business_registration_number,
                    "representative_email": _norm_email(a.requested_user_1_email or a.applicant_email),
                    "staff_email": _norm_email(a.requested_user_2_email),
                })
                groups.setdefault(fp, []).append(d)
        for members in groups.values():
            if len(members) > 1:
                ids = [m["application_id"] for m in members]
                for m in members:
                    m["duplicate_pending_count"] = len(members) - 1
                    m["duplicate_pending_ids"] = [x for x in ids if x != m["application_id"]]
        return dicts


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

        # 정확 일치 중복 신청 정리 준비(§3-3) — canonical fingerprint 로 advisory lock 을 잡아
        # 동시 create/approve 와 직렬화하고, 같은 fingerprint 의 다른 pending/reviewing 행을
        # deterministic order(id 오름차순)로 FOR UPDATE 잠근다. 승인 확정 후 cancelled 처리한다.
        _c_appr = {
            "office_name": a.office_name,
            "business_registration_number": a.business_registration_number,
            "representative_email": _norm_email(a.requested_user_1_email or a.applicant_email),
            "staff_email": _norm_email(a.requested_user_2_email),
        }
        _acquire_fingerprint_lock(session, _application_fingerprint(_c_appr))
        dup_rows = session.scalars(
            select(OfficeApplication)
            .where(
                func.lower(func.trim(OfficeApplication.office_name)) == _norm_office_name(a.office_name),
                OfficeApplication.business_registration_number == a.business_registration_number,
                OfficeApplication.requested_user_1_email == a.requested_user_1_email,
                OfficeApplication.requested_user_2_email == a.requested_user_2_email,
                OfficeApplication.status.in_([ST_PENDING, ST_REVIEWING]),
                OfficeApplication.id != a.id,
            )
            .order_by(OfficeApplication.id.asc())
            .with_for_update()
        ).all()

        # 계정 2명 정보 확정(요청 override > 신청서 값). 이름·이메일 오탈자만 정정 가능.
        # **역할은 서버가 고정한다** — user1=대표자=office_admin, user2=실무자=office_staff.
        # 프론트가 role 을 보내더라도 신뢰하지 않는다(권한 상승 방지).
        u1 = {
            "name": ((user1 or {}).get("name") or a.requested_user_1_name or "").strip(),
            "email": _norm_email((user1 or {}).get("email") or a.requested_user_1_email
                                 or a.applicant_email),
            "role": "office_admin",
        }
        u2 = {
            "name": ((user2 or {}).get("name") or a.requested_user_2_name or "").strip(),
            "email": _norm_email((user2 or {}).get("email") or a.requested_user_2_email),
            "role": "office_staff",
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

        # tenant 생성. lifecycle 불변식 = (is_active True ⟺ service_status 'active').
        # 승인 직후는 pending_activation 이므로 is_active=False 로 두고, 최초 activation 완료
        # (complete_activation)에서 active + is_active=True 로 승격한다. 이로써 엄격 상태 판정
        # (activation_capable_tenant_block_reason: pending+비활성 / active+활성만 허용)과 일치한다.
        t = Tenant(
            tenant_id=tenant_id,
            office_name=a.office_name,
            office_adr=a.office_address,
            biz_reg_no=a.business_registration_number,
            is_active=False,
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

        # 초대 좌석 예약 원자 검증(§5) — 방금 flush 한 초대 계정 2개가 reserved 에 포함되므로 +0.
        # tenant 는 신규(reserved==발급 계정 수)라 위 `2 > effective_seat` 가드와 동치지만, 초대
        # 계정 생성 경로 전반에서 동일 규칙을 강제하기 위해 여기서도 확인한다(회귀 방어).
        from backend.services.account_lifecycle_pg_service import (
            assert_invitation_capacity, LifecycleError as _LcErr)
        try:
            assert_invitation_capacity(session, tenant_id, additional_invites=0)
        except _LcErr as e:
            raise ApplicationError("SEAT_LIMIT", e.message)

        # 신청 승인 처리.
        a.status = ST_APPROVED
        a.reviewed_at = now
        a.reviewed_by = reviewer
        a.approved_tenant_id = tenant_id

        # 정확 일치 중복 신청 자동 취소(같은 트랜잭션) — canonical application_id 기록.
        cancelled_ids: list[str] = []
        for d in dup_rows:
            d.status = ST_CANCELLED
            d.reviewed_at = now
            d.reviewed_by = reviewer
            d.duplicate_flags = {**(d.duplicate_flags or {}),
                                 "cancelled_as_duplicate_of": application_id}
            note = (d.review_note_internal or "").strip()
            d.review_note_internal = (note + f" [중복 접수 → {application_id} 승인으로 자동 취소]").strip()
            cancelled_ids.append(d.application_id)

        session.commit()  # ← 여기서 tenant+user2+token2+application+중복취소 가 원자적으로 확정
        result = {
            "already_approved": False,
            "application_id": application_id,
            "tenant_id": tenant_id,
            "seat_limit": int(seat_limit or SEAT_LIMIT_DEFAULT),
            "users": raw_tokens,
            "cancelled_duplicate_ids": cancelled_ids,
            "cancelled_duplicate_count": len(cancelled_ids),
        }

    # 커밋 성공 후에만 감사 기록(롤백된 승인이 로그로 남지 않도록).
    _audit("tenant_created_from_application", reviewer, application_id, result["tenant_id"],
           {"application_id": application_id})
    for action, actor, target, tid, payload in audit_events:
        _audit(action, actor, target, tid, payload)
    _audit("office_application_approved", reviewer, application_id, result["tenant_id"],
           {"application_id": application_id, "user_count": len(result["users"])})
    if result.get("cancelled_duplicate_count"):
        # PII 없이 건수·canonical id 만 기록(원문 이메일·개인정보 미저장).
        _audit("office_application_duplicates_cancelled", reviewer, application_id, result["tenant_id"],
               {"canonical_application_id": application_id,
                "cancelled_count": result["cancelled_duplicate_count"],
                "cancelled_application_ids": result["cancelled_duplicate_ids"]})
    return result


def stats() -> dict:
    """시스템 관리자 배지·알림용 신청 건수 요약. pending/reviewing 만 미처리로 집계."""
    from backend.db.models.office_application import OfficeApplication
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        def _count(st: str) -> int:
            return int(session.scalar(select(func.count()).select_from(OfficeApplication).where(
                OfficeApplication.status == st)) or 0)
        pending = _count(ST_PENDING)
        reviewing = _count(ST_REVIEWING)
        return {"pending": pending, "reviewing": reviewing, "unresolved": pending + reviewing}


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
