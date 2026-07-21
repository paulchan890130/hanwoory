"""공통기준 자가점검 — **관리 설정만** 저장/조회하는 라우터.

개인정보 원칙:
- 사용자 답변/결과/경로를 받는 endpoint 는 **존재하지 않는다**(제출·결과저장 API 없음).
- 저장되는 것은 관리자 설정(질문 그래프/결과/주의문구/버전/국가목록/공개여부)뿐이다.
- 저장은 **기존 마케팅 저장 계층**(marketing_pg_service, marketing_posts 테이블)을 재사용한다
  — 신규 테이블/migration 없음. 고정 id 싱글턴 행 1개.
공개 GET 은 게시된 설정만 반환하고, 평가(판정)는 전적으로 프론트에서 수행한다.
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import require_admin

router = APIRouter()

CONFIG_ID = "common-criteria-self-check"
CONFIG_CATEGORY = "self_check_config"


class ConfigSave(BaseModel):
    config: dict[str, Any]
    is_published: bool = False


# ── 그래프 무결성 검증 (logic.ts 와 동일 개념) ────────────────────────────────
def _validate_config(cfg: dict, for_publish: bool) -> list[str]:
    errors: list[str] = []
    if not isinstance(cfg, dict):
        return ["설정 형식이 올바르지 않습니다."]
    questions = cfg.get("questions") or []
    results = cfg.get("results") or []
    qids = [q.get("id") for q in questions]
    rids = [r.get("id") for r in results]
    if len(qids) != len(set(qids)):
        errors.append("중복 question_id")
    if len(rids) != len(set(rids)):
        errors.append("중복 result_id")
    idset = set(qids) | set(rids)
    if set(qids) & set(rids):
        errors.append("question/result id 충돌")
    if not (cfg.get("logic_version") or "").strip():
        errors.append("로직 버전 누락")
    if not results:
        errors.append("결과가 없습니다.")
    qmap = {q.get("id"): q for q in questions}
    for q in questions:
        for br in ("yes", "no"):
            tgt = q.get(br)
            if not tgt or tgt not in idset:
                errors.append(f"질문 {q.get('id')}의 '{br}' 대상이 유효하지 않습니다.")
    start = cfg.get("start_question_id")
    if not start or start not in qmap:
        errors.append("시작 질문이 유효하지 않습니다.")
        return errors
    # 순환 감지 + 결과 도달성 (DFS 컬러링)
    color: dict[str, int] = {}
    reached_result = {"v": False}
    cycle = {"v": False}

    def dfs(node: str) -> None:
        if node in rids:
            reached_result["v"] = True
            return
        q = qmap.get(node)
        if not q:
            return
        if color.get(node) == 1:
            cycle["v"] = True
            return
        if color.get(node) == 2:
            return
        color[node] = 1
        for br in ("yes", "no"):
            tgt = q.get(br)
            if tgt in idset:
                dfs(tgt)
        color[node] = 2

    dfs(start)
    if cycle["v"]:
        errors.append("질문 순환(loop) 감지 — 모든 경로가 결과로 끝나야 합니다.")
    if not reached_result["v"] and not cycle["v"]:
        errors.append("어떤 경로에서도 결과에 도달하지 못합니다.")
    if for_publish and not start:
        errors.append("공개하려면 시작 질문이 필요합니다.")
    return errors


def _load_row() -> dict | None:
    from backend.services import marketing_pg_service as mk
    try:
        return mk.get_post(CONFIG_ID)
    except Exception:
        return None


def _envelope(row: dict | None) -> dict:
    if not row:
        return {"published": False, "config": None}
    published = str(row.get("is_published", "")).upper() in ("TRUE", "Y", "1")
    raw = row.get("content") or ""
    try:
        config = json.loads(raw) if raw else None
    except Exception:
        config = None
    return {"published": published, "config": config}


# ── 공개: 게시된 설정만 반환(사용자 답변 미수집) ──────────────────────────────
@router.get("/config")
def public_get_config():
    env = _envelope(_load_row())
    if not env["published"]:
        return {"published": False, "config": None}
    return env


# ── 관리자: 편집용 조회(게시 여부 무관) ───────────────────────────────────────
@router.get("/admin/config")
def admin_get_config(user: dict = Depends(require_admin)):
    return _envelope(_load_row())


# ── 관리자: 저장 + 게시(검증 통과 시에만) ─────────────────────────────────────
@router.put("/admin/config")
def admin_save_config(body: ConfigSave, user: dict = Depends(require_admin)):
    errors = _validate_config(body.config, for_publish=body.is_published)
    if body.is_published and errors:
        raise HTTPException(status_code=400, detail={"message": "게시하려면 오류를 먼저 수정하세요.", "errors": errors})
    from backend.services import marketing_pg_service as mk
    from backend.db.session import is_configured
    if not is_configured():
        raise HTTPException(status_code=503, detail="데이터베이스가 구성되지 않았습니다.")
    rec = {
        "id": CONFIG_ID,
        "title": "공통기준 자가점검",
        "slug": CONFIG_ID,
        "category": CONFIG_CATEGORY,
        "content": json.dumps(body.config, ensure_ascii=False),
        "is_published": "TRUE" if body.is_published else "FALSE",
        "created_by": user.get("login_id", ""),
    }
    try:
        mk.upsert_post(rec)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"저장 실패: {e}")
    return {"ok": True, "published": body.is_published, "warnings": [] if body.is_published else errors}
