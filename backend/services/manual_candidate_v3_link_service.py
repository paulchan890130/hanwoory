"""매뉴얼 검토 후보(manual_update_candidates.row_id) ↔ v3 오버레이 편집
(guideline_v3_edits: entity_type/entity_id) 연결 추적.

기존 컬럼 재사용을 먼저 검토했으나 전부 안전하지 않았다:
- manual_review_decisions.applied(bool) — 이미 "manual_ref 페이지 반영" 뜻으로
  선점됨(mark_decision_applied, 구 manual_ref_rematch.py 흐름). 재사용하면 그
  가드 로직이 깨진다.
- manual_review_decisions.decision_note — POST /manual-update/decisions/{row_id}
  가 검토완료/보류/무시를 누를 때마다 body.note or "" 로 무조건 덮어쓴다(실증
  확인). 구조적 데이터를 담기에 안전하지 않다.
- guideline_v3_edits.payload — 편집 API(_clean_fields)가 화이트리스트 밖 필드를
  HTTP 400 으로 거부한다(의도된 방어). 메타 키를 끼워 넣을 수 없다.

대신 이미 마이그레이션되어 있는 audit_logs 테이블(신규 컬럼/테이블 없음)에
전용 action 2종으로 기록한다. audit_service.log_event()는 FEATURE_PG_AUDIT
미설정 시 조용히 no-op 하는 "참고용" 로깅이라 이 기능(중복 적용 차단·취소
대상 식별)의 정합성 보장 수단으로 쓸 수 없으므로, 이 모듈은 그 래퍼를
거치지 않고 PG 구성 여부만 확인해 직접 기록한다 — v3 편집 자체도 PG 필수라
신뢰성 수준은 동일하다.

이벤트 소싱 방식: (candidate_row_id, entity_type, entity_id) 키별로 APPLY/REVERT
이벤트가 쌓이고, 가장 최근 이벤트가 APPLY면 "현재 적용 중", REVERT면 "취소됨".
"""
from __future__ import annotations

from typing import Optional

from backend.db.session import get_sessionmaker, is_configured

ACTION_APPLY = "MANUAL_CANDIDATE_V3_APPLY"
ACTION_REVERT = "MANUAL_CANDIDATE_V3_REVERT"


def enabled() -> bool:
    return is_configured()


def _latest_event(session, candidate_row_id: str, entity_type: str, entity_id: str):
    from sqlalchemy import select, desc
    from backend.db.models.audit import AuditLog
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.action.in_([ACTION_APPLY, ACTION_REVERT]),
            AuditLog.target_type == entity_type,
            AuditLog.target_id == entity_id,
            AuditLog.payload["candidate_row_id"].astext == candidate_row_id,
        )
        .order_by(desc(AuditLog.created_at), desc(AuditLog.id))
        .limit(1)
    )
    return session.scalars(stmt).first()


def get_active_link(candidate_row_id: str, entity_type: str, entity_id: str) -> Optional[dict]:
    """이 (후보, 엔터티) 쌍에 취소되지 않은 적용 이력이 있으면 반환, 없으면 None."""
    if not enabled():
        return None
    maker = get_sessionmaker()
    with maker() as session:
        ev = _latest_event(session, candidate_row_id, entity_type, entity_id)
        if ev is None or ev.action != ACTION_APPLY:
            return None
        payload = ev.payload or {}
        return {
            "candidate_row_id": candidate_row_id, "entity_type": entity_type, "entity_id": entity_id,
            "applied_by": ev.actor_login_id,
            "applied_at": ev.created_at.isoformat() if ev.created_at else None,
            "before": payload.get("before"), "after": payload.get("after"),
        }


def list_links_for_candidate(candidate_row_id: str) -> list[dict]:
    """이 후보로 현재 활성 상태(취소되지 않은)인 모든 적용 이력."""
    if not enabled():
        return []
    from sqlalchemy import select
    from backend.db.models.audit import AuditLog
    maker = get_sessionmaker()
    with maker() as session:
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.action.in_([ACTION_APPLY, ACTION_REVERT]),
                AuditLog.payload["candidate_row_id"].astext == candidate_row_id,
            )
            .order_by(AuditLog.created_at, AuditLog.id)
        )
        rows = session.scalars(stmt).all()
        latest: dict[tuple, object] = {}
        for r in rows:
            latest[(r.target_type, r.target_id)] = r  # 오름차순이라 마지막 대입이 최신
        out = []
        for (etype, eid), ev in latest.items():
            if ev.action == ACTION_APPLY:
                out.append({
                    "entity_type": etype, "entity_id": eid,
                    "applied_by": ev.actor_login_id,
                    "applied_at": ev.created_at.isoformat() if ev.created_at else None,
                })
        return out


def record_apply(*, candidate_row_id: str, entity_type: str, entity_id: str,
                  actor_login_id: str, tenant_id: str,
                  before: Optional[dict], after: Optional[dict]) -> None:
    from backend.db.models.audit import AuditLog
    maker = get_sessionmaker()
    with maker() as session:
        session.add(AuditLog(
            action=ACTION_APPLY, actor_login_id=actor_login_id, tenant_id=tenant_id,
            target_type=entity_type, target_id=entity_id,
            payload={"candidate_row_id": candidate_row_id, "before": before, "after": after},
        ))
        session.commit()


def record_revert(*, candidate_row_id: str, entity_type: str, entity_id: str,
                   actor_login_id: str, tenant_id: str) -> None:
    from backend.db.models.audit import AuditLog
    maker = get_sessionmaker()
    with maker() as session:
        session.add(AuditLog(
            action=ACTION_REVERT, actor_login_id=actor_login_id, tenant_id=tenant_id,
            target_type=entity_type, target_id=entity_id,
            payload={"candidate_row_id": candidate_row_id},
        ))
        session.commit()
