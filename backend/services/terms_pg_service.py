"""약관/개인정보 동의 — PG(terms_versions, user_terms_acceptances, migration 0020).

**graceful**: PG 미구성/테이블 미적용(0020 미반영)/오류 시 빈 목록·no-op 으로 동작해
로그인/가입 등 기존 흐름을 절대 막지 않는다. 운영 0020 적용 전에도 앱은 정상.
"""
from __future__ import annotations

from typing import List, Optional

# 약관 종류
TERMS_TYPES = ("tos", "privacy", "unique_id", "no_share")
TYPE_LABELS = {
    "tos": "이용약관",
    "privacy": "개인정보처리방침",
    "unique_id": "고유식별정보 처리 동의",
    "no_share": "계정공유 금지 확인",
}


def _sl():
    from backend.db.session import get_sessionmaker
    return get_sessionmaker()()


def _configured() -> bool:
    try:
        from backend.db.session import is_configured
        return is_configured()
    except Exception:
        return False


def get_active_terms() -> List[dict]:
    """현행(is_active) 약관 버전 목록. 오류/미적용 시 빈 목록."""
    if not _configured():
        return []
    try:
        from sqlalchemy import select
        from backend.db.models.terms import TermsVersion
        with _sl() as s:
            rows = s.scalars(select(TermsVersion).where(TermsVersion.is_active.is_(True))).all()
            return [{
                "id": r.id, "type": r.type, "version": r.version,
                "title": r.title or TYPE_LABELS.get(r.type, r.type),
            } for r in rows]
    except Exception:
        return []


def pending_for(login_id: str) -> List[dict]:
    """이 사용자가 아직 동의하지 않은 현행 약관 목록. 오류/미적용 시 빈 목록(차단 안 함)."""
    lid = (login_id or "").strip()
    if not lid or not _configured():
        return []
    try:
        from sqlalchemy import select
        from backend.db.models.terms import TermsVersion, UserTermsAcceptance
        with _sl() as s:
            active = s.scalars(select(TermsVersion).where(TermsVersion.is_active.is_(True))).all()
            if not active:
                return []
            accepted = set(s.scalars(
                select(UserTermsAcceptance.terms_version_id).where(UserTermsAcceptance.login_id == lid)
            ).all())
            return [{
                "id": r.id, "type": r.type, "version": r.version,
                "title": r.title or TYPE_LABELS.get(r.type, r.type),
            } for r in active if r.id not in accepted]
    except Exception:
        return []


def record_acceptance(login_id: str, tenant_id: Optional[str], version_ids: List[int],
                      ip: Optional[str] = None, user_agent: Optional[str] = None) -> int:
    """동의 기록(멱등: 중복 (login_id, version_id)는 무시). 반환=신규 기록 수. 오류 시 0."""
    lid = (login_id or "").strip()
    if not lid or not version_ids or not _configured():
        return 0
    try:
        from sqlalchemy import select
        from backend.db.models.terms import UserTermsAcceptance
        n = 0
        with _sl() as s:
            existing = set(s.scalars(
                select(UserTermsAcceptance.terms_version_id).where(UserTermsAcceptance.login_id == lid)
            ).all())
            for vid in version_ids:
                if vid in existing:
                    continue
                s.add(UserTermsAcceptance(
                    login_id=lid, tenant_id=tenant_id, terms_version_id=int(vid),
                    ip=ip, user_agent=(user_agent or "")[:300],
                ))
                n += 1
            if n:
                s.commit()
        return n
    except Exception:
        return 0
