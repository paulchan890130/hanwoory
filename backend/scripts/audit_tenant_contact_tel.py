"""기존 승인 tenant 대표 연락처(contact_tel) 복구 후보 dry-run 감사 (읽기 전용).

목적: 승인형 SaaS 이전/초기 승인 건 중, 대표자(office_admin) 계정의 contact_tel 이 비어 있으나
원 신청서(office_phone)에는 유효한 전화가 있는 tenant 를 찾아 복구 후보로 보고한다.

원칙:
- **운영 DB 를 절대 수정하지 않는다**(SELECT 만). 실제 backfill 은 별도 명령 + 명시 승인 필요.
- 평문 주민등록번호 / 전체 이메일을 출력하지 않는다(login_id 는 마스킹).

사용:
    DATABASE_URL=... .venv/Scripts/python -m backend.scripts.audit_tenant_contact_tel
    (DATABASE_URL 미설정이면 '미구성' 안내 후 종료 — 운영 접속은 명시 승인 전 금지)
"""
from __future__ import annotations


def _mask_login(login_id: str) -> str:
    """login_id(이메일) 마스킹 — 전체 이메일 미노출. 예: chan@hanwory.com → c***@h***."""
    lid = (login_id or "").strip()
    if "@" in lid:
        local, _, domain = lid.partition("@")
        ml = (local[:1] + "***") if local else "***"
        md = (domain[:1] + "***") if domain else "***"
        return f"{ml}@{md}"
    return (lid[:1] + "***") if lid else "***"


def run() -> int:
    from backend.db.session import get_sessionmaker, is_configured
    if not is_configured():
        print("[audit] DATABASE_URL 미구성 — 운영 접속은 명시 승인 전 금지. 종료.")
        return 0

    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.services.office_application_pg_service import get_application_office_phone
    from backend.services.korean_identifier_format import validate_phone, format_phone, normalize_phone

    Session = get_sessionmaker()
    candidates = 0
    scanned = 0
    with Session() as s:
        tenants = s.scalars(select(Tenant)).all()
        for t in tenants:
            app_id = getattr(t, "source_application_id", "") or ""
            if not app_id:
                continue
            scanned += 1
            # 대표자(office_admin) 우선, 없으면 is_admin 대표 계정.
            rep = s.scalar(
                select(AccountUser).where(AccountUser.tenant_id == t.tenant_id)
                .order_by(AccountUser.is_admin.desc(), AccountUser.id.asc())
            )
            if rep is None:
                continue
            if normalize_phone(rep.contact_tel):
                continue  # 이미 연락처 있음 → 복구 불필요
            app_phone = get_application_office_phone(app_id)
            recoverable = validate_phone(app_phone)
            print(
                f"tenant_id={t.tenant_id} rep={_mask_login(rep.login_id)} "
                f"recoverable={'YES' if recoverable else 'no'} "
                f"app_phone={format_phone(app_phone) if recoverable else '(없음/무효)'}"
            )
            if recoverable:
                candidates += 1
    print(f"[audit] scanned(with source_application_id)={scanned} recovery_candidates={candidates}")
    print("[audit] 이 스크립트는 읽기 전용입니다. 실제 backfill 은 별도 명령 + 명시 승인 후에만 수행하십시오.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
