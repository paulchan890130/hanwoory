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

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from backend.auth import require_system_admin

router = APIRouter()

CONFIG_ID = "common-criteria-self-check"
CONFIG_CATEGORY = "self_check_config"


class ConfigSave(BaseModel):
    # 다중 항목 번들(schema v2). 레거시 단일 config 저장도 계속 허용(하위호환).
    bundle: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    is_published: bool = False


# ── 그래프 무결성 검증 (frontend lib/selfcheck/logic.ts validateConfig 와 동일 개념) ──
# 반환: {"errors": [...], "warnings": [...]}. errors 는 게시 차단, warnings 는 안내.
# 프론트/백엔드 결과가 동일하도록 검사 항목·판정 기준을 맞춘다.
def _validate_config_report(cfg: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(cfg, dict):
        return {"errors": ["설정 형식이 올바르지 않습니다."], "warnings": []}
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
        for br, ko in (("yes", "예"), ("no", "아니오")):
            tgt = q.get(br)
            if not tgt or tgt not in idset:
                errors.append(f"질문 {q.get('id')}의 '{ko}' 대상({tgt or '없음'})이 존재하지 않습니다.")
    start = cfg.get("start_question_id")
    if not start or start not in qmap:
        errors.append("시작 질문이 없거나 유효하지 않습니다.")
        return {"errors": errors, "warnings": warnings}  # 시작 없으면 도달성/순환 분석 불가

    # 순환 감지 + 도달성(DFS 컬러링). 도달한 질문/결과 집계.
    color: dict[str, int] = {}
    reachable_q: set = set()
    reachable_r: set = set()
    cycle = {"v": False}

    def dfs(node: str) -> None:
        if node in rids:
            reachable_r.add(node)
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
        reachable_q.add(node)
        for br in ("yes", "no"):
            tgt = q.get(br)
            if tgt in idset:
                dfs(tgt)
        color[node] = 2

    dfs(start)
    if cycle["v"]:
        errors.append("질문 순환(loop)이 감지되었습니다. 모든 경로가 결과로 끝나야 합니다.")
    # 도달 불가 경고
    for q in questions:
        if q.get("id") not in reachable_q:
            warnings.append(f"도달 불가능한 질문: {q.get('id')}")
    for r in results:
        if r.get("id") not in reachable_r:
            warnings.append(f"도달 불가능한 결과: {r.get('id')}")
    if not cycle["v"] and len(reachable_r) == 0:
        errors.append("어떤 경로에서도 결과에 도달하지 못합니다.")
    return {"errors": errors, "warnings": warnings}


# 하위호환 + 간결 호출용 — errors 리스트만 반환.
def _validate_config(cfg: dict, for_publish: bool = False) -> list[str]:
    return _validate_config_report(cfg)["errors"]


def _load_row() -> dict | None:
    from backend.services import marketing_pg_service as mk
    try:
        return mk.get_post(CONFIG_ID)
    except Exception:
        return None


def _parse_content(row: dict | None) -> tuple[Any, bool]:
    """(parsed_json | None, row_published)."""
    if not row:
        return None, False
    published = str(row.get("is_published", "")).upper() in ("TRUE", "Y", "1")
    raw = row.get("content") or ""
    try:
        return (json.loads(raw) if raw else None), published
    except Exception:
        return None, published


def _normalize_bundle(raw: Any, legacy_published: bool = False) -> dict:
    """저장 content(신규 번들 | 레거시 단일 config) → {schema_version:2, items:[...]}.

    프론트 lib/selfcheck/logic.ts normalizeBundle 과 동일 개념. 파괴적 변경 없음."""
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        items = []
        for i, it in enumerate(raw["items"]):
            if not isinstance(it, dict) or not isinstance(it.get("config"), dict):
                continue
            items.append({
                "item_id": str(it.get("item_id") or "").strip(),
                "title": it.get("title") or "",
                "description": it.get("description"),
                "sort_order": it.get("sort_order") if isinstance(it.get("sort_order"), (int, float)) else i,
                "is_published": bool(it.get("is_published")),
                "popup_enabled": it.get("popup_enabled") is not False,
                "placement": it.get("placement") if isinstance(it.get("placement"), list) else [],
                "config": it["config"],
            })
        return {"schema_version": 2, "items": items}
    if isinstance(raw, dict) and isinstance(raw.get("questions"), list) and isinstance(raw.get("results"), list):
        return {"schema_version": 2, "items": [{
            "item_id": "legacy", "title": raw.get("item_name") or "기존 설정", "description": None,
            "sort_order": 0, "is_published": bool(legacy_published), "popup_enabled": True,
            "placement": [], "config": raw,
        }]}
    return {"schema_version": 2, "items": []}


def _public_items(bundle: dict) -> list[dict]:
    """게시 + 팝업 + 그래프 유효 항목만, sort_order 정렬(공개 노출용)."""
    out = []
    for it in bundle.get("items", []):
        if not it.get("is_published") or it.get("popup_enabled") is False:
            continue
        if _validate_config_report(it.get("config") or {})["errors"]:
            continue
        out.append(it)
    out.sort(key=lambda x: x.get("sort_order", 0))
    return out


# ── 공개: 게시된 유효 항목만 반환(사용자 답변 미수집) ─────────────────────────
# no-store 로 응답 → 관리자가 비공개 전환 시 프록시/브라우저 캐시로 늦게 반영되지 않음.
# 손상/미게시 → 빈 items(런처가 숨김). 잘못된 설정을 공개로 흘리지 않는다.
@router.get("/config")
def public_get_config(response: Response):
    response.headers["Cache-Control"] = "no-store"
    raw, published = _parse_content(_load_row())
    bundle = _normalize_bundle(raw, legacy_published=published)
    return {"schema_version": 2, "items": _public_items(bundle)}


# ── 관리자: 편집용 조회(게시 여부 무관) — 전체 번들 반환 ───────────────────────
@router.get("/admin/config")
def admin_get_config(user: dict = Depends(require_system_admin)):
    raw, published = _parse_content(_load_row())
    return _normalize_bundle(raw, legacy_published=published)


# ── 관리자: 저장 + 게시(검증 통과 시에만) ─────────────────────────────────────
@router.put("/admin/config")
def admin_save_config(body: ConfigSave, user: dict = Depends(require_system_admin)):
    # 번들 우선. 레거시 {config,is_published} 는 item 1개 번들로 감싼다(하위호환).
    if body.bundle is not None:
        bundle = _normalize_bundle(body.bundle)
    elif body.config is not None:
        bundle = {"schema_version": 2, "items": [{
            "item_id": "legacy", "title": body.config.get("item_name") or "기존 설정",
            "description": None, "sort_order": 0, "is_published": bool(body.is_published),
            "popup_enabled": True, "placement": [], "config": body.config,
        }]}
    else:
        raise HTTPException(status_code=400, detail={"message": "bundle 또는 config 가 필요합니다.", "errors": ["빈 요청"]})

    # item_id 중복 차단.
    ids = [it["item_id"] for it in bundle["items"]]
    if len(ids) != len(set(ids)):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        raise HTTPException(status_code=400, detail={"message": "item_id 가 중복되었습니다.", "errors": [f"중복 item_id: {', '.join(dup)}"]})
    if any(not i for i in ids):
        raise HTTPException(status_code=400, detail={"message": "item_id 가 비어 있는 항목이 있습니다.", "errors": ["빈 item_id"]})

    # 게시하려는 항목은 그래프 오류가 없어야 한다(비공개 항목은 draft 허용).
    item_errors: dict[str, list[str]] = {}
    for it in bundle["items"]:
        rep = _validate_config_report(it.get("config") or {})
        if rep["errors"]:
            item_errors[it["item_id"]] = rep["errors"]
    publish_blocked = {iid: errs for iid, errs in item_errors.items()
                       if next((it for it in bundle["items"] if it["item_id"] == iid), {}).get("is_published")}
    if publish_blocked:
        raise HTTPException(status_code=400, detail={
            "message": "게시하려는 항목의 오류를 먼저 수정하세요.", "item_errors": publish_blocked})

    from backend.services import marketing_pg_service as mk
    from backend.db.session import is_configured
    if not is_configured():
        raise HTTPException(status_code=503, detail="데이터베이스가 구성되지 않았습니다.")
    any_published = any(it.get("is_published") for it in bundle["items"])
    rec = {
        "id": CONFIG_ID,
        "title": "공통기준 자가점검",
        "slug": CONFIG_ID,
        "category": CONFIG_CATEGORY,
        "content": json.dumps(bundle, ensure_ascii=False),
        "is_published": "TRUE" if any_published else "FALSE",
        "created_by": user.get("login_id", ""),
    }
    try:
        mk.upsert_post(rec)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"저장 실패: {e}")
    return {"ok": True, "published_items": [it["item_id"] for it in bundle["items"] if it.get("is_published")],
            "item_errors": item_errors}
