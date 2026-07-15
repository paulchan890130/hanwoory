"""실무지침 v3 편집 오버레이 저장 서비스 (migration 0030, FEATURE_GUIDELINES_V3_EDIT).

정본 JSON은 절대 수정하지 않는다. 엔터티 단위 오버레이(upsert 전체 payload /
delete 톰스톤)를 PG `guideline_v3_edits` 에 보관하고, 라우터가 읽기 시점에 병합한다.
엔터티당 최신 상태 1행 — 변경 이력은 audit_logs(audit_service.log_event) 몫.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from backend.db import feature_flags
from backend.db.session import get_sessionmaker, is_configured
from backend.db.models.guideline_v3_edit import GuidelineV3Edit

_log = logging.getLogger("hanwoory.guideline_v3_edit")

ENTITY_TYPES = ("group", "qualification", "stay_block", "visa_route", "doc_requirement", "aux")


def edit_enabled() -> bool:
    """편집 계층 사용 가능 여부 — 플래그 on + PG 구성. 둘 중 하나라도 아니면 기존 동작."""
    return feature_flags.guidelines_v3_edit_enabled() and is_configured()


def load_all_edits() -> dict[str, dict[str, dict]]:
    """{entity_type: {entity_id: {"op": .., "payload": dict|None}}} 형태로 전체 오버레이 로드.

    실패 시(테이블 미적용 등) 빈 오버레이 — 읽기는 정본 JSON 으로 자연 fallback."""
    if not edit_enabled():
        return {}
    try:
        maker = get_sessionmaker()
        with maker() as session:
            rows = session.query(GuidelineV3Edit).order_by(GuidelineV3Edit.id).all()
            out: dict[str, dict[str, dict]] = {}
            for r in rows:
                payload = json.loads(r.payload) if r.payload else None
                out.setdefault(r.entity_type, {})[r.entity_id] = {"op": r.op, "payload": payload}
            return out
    except Exception as exc:  # noqa: BLE001 — 편집 계층 오류가 읽기 화면을 죽이면 안 됨
        _log.warning("guideline_v3_edit: load 실패 — 정본 JSON 으로 fallback (%s)", exc)
        return {}


def get_edit_row(entity_type: str, entity_id: str) -> Optional[dict]:
    """단일 엔터티의 현재 오버레이 상태(있으면) — {op, payload, updated_by, updated_at}.
    '적용 이력 보기'의 기반: 이 테이블은 엔터티당 최신 상태만 보관하므로(0030 설계),
    과거 여러 버전이 아니라 '현재 오버레이가 있는지 + 언제/누가'를 보여준다."""
    if not edit_enabled():
        return None
    try:
        maker = get_sessionmaker()
        with maker() as session:
            row = (session.query(GuidelineV3Edit)
                   .filter(GuidelineV3Edit.entity_type == entity_type,
                           GuidelineV3Edit.entity_id == entity_id)
                   .one_or_none())
            if row is None:
                return None
            payload = json.loads(row.payload) if row.payload else None
            return {
                "op": row.op, "payload": payload,
                "updated_by": row.updated_by,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
    except Exception as exc:  # noqa: BLE001
        _log.warning("guideline_v3_edit: get_edit_row 실패 (%s)", exc)
        return None


def save_edit(entity_type: str, entity_id: str, op: str, payload: Optional[dict],
              updated_by: str) -> None:
    """오버레이 upsert(엔터티당 1행). op='upsert'|'delete'."""
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"entity_type 오류: {entity_type}")
    if op not in ("upsert", "delete"):
        raise ValueError(f"op 오류: {op}")
    maker = get_sessionmaker()
    with maker() as session:
        row = (session.query(GuidelineV3Edit)
               .filter(GuidelineV3Edit.entity_type == entity_type,
                       GuidelineV3Edit.entity_id == entity_id)
               .one_or_none())
        text = json.dumps(payload, ensure_ascii=False) if payload is not None else None
        if row is None:
            row = GuidelineV3Edit(entity_type=entity_type, entity_id=entity_id,
                                  op=op, payload=text, updated_by=updated_by)
            session.add(row)
        else:
            row.op = op
            row.payload = text
            row.updated_by = updated_by
        session.commit()


def save_edits_bulk(edits: list[tuple[str, str, str, Optional[dict]]], updated_by: str) -> None:
    """여러 오버레이를 단일 트랜잭션으로 반영 — 연결 데이터 포함 삭제(cascade)용.

    edits = [(entity_type, entity_id, op, payload), ...]. 전부 성공하거나 전부 롤백."""
    maker = get_sessionmaker()
    with maker() as session:
        for entity_type, entity_id, op, payload in edits:
            if entity_type not in ENTITY_TYPES or op not in ("upsert", "delete"):
                raise ValueError(f"edit 항목 오류: {entity_type}/{op}")
            row = (session.query(GuidelineV3Edit)
                   .filter(GuidelineV3Edit.entity_type == entity_type,
                           GuidelineV3Edit.entity_id == entity_id)
                   .one_or_none())
            text = json.dumps(payload, ensure_ascii=False) if payload is not None else None
            if row is None:
                session.add(GuidelineV3Edit(entity_type=entity_type, entity_id=entity_id,
                                            op=op, payload=text, updated_by=updated_by))
            else:
                row.op = op
                row.payload = text
                row.updated_by = updated_by
        session.commit()


def remove_edit(entity_type: str, entity_id: str) -> bool:
    """오버레이 행 자체를 제거(정본 기준으로 되돌리기 / 테스트 데이터 정리)."""
    maker = get_sessionmaker()
    with maker() as session:
        n = (session.query(GuidelineV3Edit)
             .filter(GuidelineV3Edit.entity_type == entity_type,
                     GuidelineV3Edit.entity_id == entity_id)
             .delete())
        session.commit()
        return n > 0


def remove_edits_bulk(keys: list[tuple[str, str]]) -> int:
    """여러 오버레이 행 제거(단일 트랜잭션) — cascade 되돌리기용."""
    maker = get_sessionmaker()
    with maker() as session:
        n = 0
        for entity_type, entity_id in keys:
            n += (session.query(GuidelineV3Edit)
                  .filter(GuidelineV3Edit.entity_type == entity_type,
                          GuidelineV3Edit.entity_id == entity_id)
                  .delete())
        session.commit()
        return n
