"""v3 자격 중심 실무지침 — 관리자 API (읽기 + 오버레이 편집).

데이터 원천: backend/data/guidelines_v3/*.json (정본, 이미지 베이크 — 절대 수정 금지).
편집(FEATURE_GUIDELINES_V3_EDIT + PG): 엔터티 단위 오버레이(guideline_v3_edits,
migration 0030)를 읽기 시점에 병합한다. 플래그 off(기본) → 정본 JSON 그대로,
편집 API 는 409. 변경 이력은 audit_service(FEATURE_PG_AUDIT) best-effort 기록.

- FEATURE_GUIDELINES_V3 off(기본) → 전 엔드포인트 404.
- 조회 = 전 로그인 사용자(get_current_user). 편집(CRUD) = 마스터/관리자/준 관리자
  (require_guideline_editor — v2 실무지침 편집과 동일 권한, 일반 사용자 403).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from backend.auth import get_current_user, require_guideline_editor
from backend.db import feature_flags
from backend.routers.guidelines import _ROW_INDEX, _clean_row_display
from backend.services import guideline_v3_edit_service as edit_store
from backend.scripts.verify_guideline_route_integrity import (
    ALLOWED_DOC_ROLES, ALLOWED_ROUTE_TYPES, BANNED_PHRASES, REAL_ROUTE_TYPES,
)

router = APIRouter()

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "guidelines_v3")

_REAL_RECOG_TYPES = ("recognition",)
_REAL_VISA_TYPES = ("consulate", "evisa")

# 대분류(그룹) 기본값 — 기존 프론트 GROUP_LABEL 과 동일(오버레이로 편집 가능)
_BASE_GROUPS: list[dict] = [
    {"group_key": "A", "label": "A 계열 (외교·공무·협정)", "description": "", "sort_order": 10, "is_active": True},
    {"group_key": "B", "label": "B 계열 (사증면제·관광통과)", "description": "", "sort_order": 20, "is_active": True},
    {"group_key": "C", "label": "C 계열 (단기)", "description": "", "sort_order": 30, "is_active": True},
    {"group_key": "D", "label": "D 계열 (유학·투자·주재 등)", "description": "", "sort_order": 40, "is_active": True},
    {"group_key": "E", "label": "E 계열 (취업)", "description": "", "sort_order": 50, "is_active": True},
    {"group_key": "F", "label": "F 계열 (동거·거주·동포·영주·결혼)", "description": "", "sort_order": 60, "is_active": True},
    {"group_key": "G", "label": "G 계열 (기타)", "description": "", "sort_order": 70, "is_active": True},
    {"group_key": "H", "label": "H 계열 (관광취업·방문취업)", "description": "", "sort_order": 80, "is_active": True},
]


def _load(name: str) -> list | dict:
    path = os.path.join(_DATA_DIR, name)
    if not os.path.exists(path):
        return [] if name != "_meta.json" else {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def qual_code_sort_key(code: str) -> list:
    """자격코드 자연 정렬 키 — D-2 < D-10, E-7 < E-7-4 < E-7-S1, F-1-5 < F-1-15.
    프론트 ``components/qualifications/common.tsx`` 의 compareQualCode 와 로직 일치 유지."""
    parts = (code or "").split("-")
    key: list = [(1, parts[0], 0)] if parts else []
    for seg in parts[1:]:
        m = re.match(r"^(\d+)([A-Za-z]*)$", seg)
        if m:
            key.append((0, int(m.group(1)), m.group(2)))
            continue
        m = re.match(r"^([A-Za-z]+)(\d*)$", seg)
        if m:
            key.append((1, m.group(1), int(m.group(2) or 0)))
        else:
            key.append((2, seg, 0))
    return key


class _Dataset:
    """정본(또는 정본+오버레이 병합) 스냅숏 + 인덱스."""

    def __init__(self, masters: list, blocks: list, routes: list, programs: list,
                 aux: list, doc_reqs: list, groups: list, meta: dict):
        self.masters = masters
        self.blocks = blocks
        self.routes = routes
        self.programs = programs
        self.aux = aux
        self.doc_reqs = doc_reqs
        self.groups = sorted(groups, key=lambda g: (g.get("sort_order", 0), g.get("group_key", "")))
        self.meta = meta
        self.master_by_code = {m["code"]: m for m in masters}
        self.master_by_id = {m["qualification_id"]: m for m in masters}
        self.dr_by_target: dict = {}
        for d in sorted(doc_reqs, key=lambda d: (d.get("display_order") or 10**9, d.get("requirement_id", ""))):
            self.dr_by_target.setdefault(d["target_id"], []).append(d)
        self.blocks_by_qid: dict = {}
        for b in blocks:
            self.blocks_by_qid.setdefault(b["qualification_id"], []).append(b)
        self.routes_by_qid: dict = {}
        for r in sorted(routes, key=lambda r: (r.get("display_order") or 10**9, r.get("route_id", ""))):
            self.routes_by_qid.setdefault(r["qualification_id"], []).append(r)
        self.program_by_id = {p["program_id"]: p for p in programs}
        self.children_by_qid: dict = {}
        for m in masters:
            # deprecated 하위코드는 신규 선택 목록에서 제외(코드 직접 조회 이력 접근은 유지)
            if m.get("parent_qualification_id") and m.get("status") != "deprecated":
                self.children_by_qid.setdefault(m["parent_qualification_id"], []).append(m)

    def summary_for(self, qid: str, with_child_routes: bool = False) -> dict:
        own = self.blocks_by_qid.get(qid, [])
        counts = Counter(b["applicability"] for b in own if b.get("variant") is None)
        routes = list(self.routes_by_qid.get(qid, []))
        if with_child_routes:
            for c in self.children_by_qid.get(qid, []):
                routes.extend(self.routes_by_qid.get(c["qualification_id"], []))
        recog = sum(1 for r in routes if r.get("route_type") in _REAL_RECOG_TYPES)
        visa = sum(1 for r in routes if r.get("route_type") in _REAL_VISA_TYPES)
        return {
            "applicable": counts.get("applicable", 0),
            "not_applicable": counts.get("not_applicable", 0),
            "conditional": counts.get("conditional", 0),
            "unknown": counts.get("unknown", 0),
            "route_count": recog + visa,
            "recognition_count": recog,
            "visa_count": visa,
        }


def _normalize_masters(masters: list, all_masters_by_id: Optional[dict] = None) -> None:
    """sub_codes = 실제 하위 자격 코드와 항상 일치(양방향) + 자연 정렬."""
    children: dict = {}
    for m in masters:
        pid = m.get("parent_qualification_id")
        if pid and m.get("status") != "deprecated":
            children.setdefault(pid, set()).add(m["code"])
    for m in masters:
        m["sub_codes"] = sorted(children.get(m["qualification_id"], set()), key=qual_code_sort_key)


def _build_base() -> _Dataset:
    masters = _load("qualification_master.json")
    _normalize_masters(masters)
    return _Dataset(
        masters=masters,
        blocks=_load("stay_blocks.json"),
        routes=_load("visa_routes.json"),
        programs=_load("program_tags.json"),
        aux=_load("aux_civil.json"),
        doc_reqs=_load("document_requirements.json"),
        groups=[dict(g) for g in _BASE_GROUPS],
        meta=_load("_meta.json"),
    )


_BASE_DS: _Dataset = _build_base()

# 병합 캐시(단일 프로세스). 편집 저장 시 invalidate + TTL 재빌드(다중 worker 대비).
_MERGED_LOCK = threading.Lock()
_MERGED_DS: Optional[_Dataset] = None
_MERGED_AT: float = 0.0
_MERGE_TTL_SECONDS = 15.0


def invalidate_merged() -> None:
    global _MERGED_DS
    with _MERGED_LOCK:
        _MERGED_DS = None


def _apply_edits(base_rows: list[dict], edits: dict[str, dict], id_field: str) -> list[dict]:
    """오버레이 적용: upsert = 교체/신설, delete = 제외, is_active=false = 제외."""
    out: dict[str, dict] = {r[id_field]: r for r in base_rows}
    for eid, e in edits.items():
        if e["op"] == "delete":
            out.pop(eid, None)
        elif e["op"] == "upsert" and e.get("payload"):
            out[eid] = e["payload"]
    return [r for r in out.values() if r.get("is_active", True) is not False]


def _build_merged() -> _Dataset:
    edits = edit_store.load_all_edits()
    if not edits:
        return _BASE_DS
    groups_map = {g["group_key"]: dict(g) for g in _BASE_GROUPS}
    for gid, e in edits.get("group", {}).items():
        if e["op"] == "delete":
            groups_map.pop(gid, None)
        elif e.get("payload"):
            groups_map[gid] = e["payload"]
    groups = [g for g in groups_map.values() if g.get("is_active", True) is not False]

    masters = _apply_edits([dict(m) for m in _BASE_DS.masters], edits.get("qualification", {}), "qualification_id")
    _normalize_masters(masters)
    blocks = _apply_edits([dict(b) for b in _BASE_DS.blocks], edits.get("stay_block", {}), "block_id")
    routes = _apply_edits([dict(r) for r in _BASE_DS.routes], edits.get("visa_route", {}), "route_id")
    aux = _apply_edits([dict(a) for a in _BASE_DS.aux], edits.get("aux", {}), "aux_id")
    doc_reqs = _apply_edits([dict(d) for d in _BASE_DS.doc_reqs], edits.get("doc_requirement", {}), "requirement_id")
    # 고아 차단(안전망): 자격이 빠진(삭제·비활성) 블록/경로, 대상이 빠진 서류는 병합 결과에서 제외
    valid_qids = {m["qualification_id"] for m in masters}
    blocks = [b for b in blocks if b.get("qualification_id") in valid_qids]
    routes = [r for r in routes if r.get("qualification_id") in valid_qids]
    valid_targets = ({b["block_id"] for b in blocks} | {r["route_id"] for r in routes}
                     | {a["aux_id"] for a in aux})
    doc_reqs = [d for d in doc_reqs if d.get("target_id") in valid_targets]

    meta = dict(_BASE_DS.meta)
    counts = dict(meta.get("counts") or {})
    counts.update({
        "qualification_master": len(masters), "stay_blocks": len(blocks),
        "visa_routes": len(routes), "document_requirements": len(doc_reqs),
        "aux_civil": len(aux),
    })
    meta["counts"] = counts
    meta["edited_overlay"] = True
    return _Dataset(masters=masters, blocks=blocks, routes=routes, programs=_BASE_DS.programs,
                    aux=aux, doc_reqs=doc_reqs, groups=groups, meta=meta)


def get_dataset() -> _Dataset:
    if not edit_store.edit_enabled():
        return _BASE_DS
    global _MERGED_DS, _MERGED_AT
    with _MERGED_LOCK:
        now = time.monotonic()
        if _MERGED_DS is None or (now - _MERGED_AT) > _MERGE_TTL_SECONDS:
            _MERGED_DS = _build_merged()
            _MERGED_AT = now
        return _MERGED_DS


def _require_enabled() -> None:
    if not feature_flags.guidelines_v3_enabled():
        raise HTTPException(status_code=404, detail="v3 자격 중심 실무지침이 비활성 상태입니다.")
    if not _BASE_DS.masters:
        raise HTTPException(status_code=404, detail="v3 데이터 파일이 없습니다 (backend/data/guidelines_v3).")


def _editable_for(user: dict) -> bool:
    """편집 UI 노출 여부 — 편집 계층 활성 + 마스터/관리자/준 관리자(일반 사용자는 조회 전용).
    require_guideline_editor 와 동일 기준을 유지할 것(서버 editable = 프론트 버튼 노출 기준)."""
    return edit_store.edit_enabled() and bool(
        user.get("is_admin") or user.get("is_master") or user.get("is_sub_admin"))


def _v2_rows_for(ids: list[str]) -> list[dict]:
    out = []
    for rid in ids:
        row = _ROW_INDEX.get(rid)
        if row:
            out.append(_clean_row_display(row))
    return out


@router.get("/meta")
def get_meta(user: dict = Depends(get_current_user)):
    _require_enabled()
    return {"meta": get_dataset().meta, "flag": True,
            "editable": _editable_for(user)}


@router.get("/qualifications")
def list_qualifications(user: dict = Depends(get_current_user)):
    """기초 자격(부모 없음) 목록 + 상태 요약 + 그룹(대분류) + 프로그램 목록."""
    _require_enabled()
    ds = get_dataset()
    base = []
    for m in ds.masters:
        if m.get("parent_qualification_id"):
            continue
        qid = m["qualification_id"]
        base.append({**m, "summary": ds.summary_for(qid, with_child_routes=True),
                     "child_count": len(ds.children_by_qid.get(qid, []))})
    base.sort(key=lambda m: (m["group"], m.get("display_order") or 10**9, qual_code_sort_key(m["code"])))
    return {"total": len(base), "data": base, "programs": ds.programs,
            "groups": ds.groups, "editable": _editable_for(user)}


@router.get("/programs")
def list_programs(user: dict = Depends(get_current_user)):
    _require_enabled()
    ds = get_dataset()
    return {"total": len(ds.programs), "data": ds.programs}


@router.get("/aux")
def list_aux(user: dict = Depends(get_current_user)):
    """보조 민원(APPLICATION_CLAIM 별도 축) — 격자 밖 기타 신청·신고 + 연결 v2 행."""
    _require_enabled()
    ds = get_dataset()
    out = []
    for a in sorted(ds.aux, key=lambda a: (a.get("display_order") or 10**9, a.get("aux_id", ""))):
        row = _ROW_INDEX.get(a.get("v2_row_id"))
        out.append({**a, "v2_row": _clean_row_display(row) if row else None,
                    "requirements": ds.dr_by_target.get(a["aux_id"], [])})
    return {"total": len(out), "data": out, "editable": _editable_for(user)}


@router.get("/qualifications/{code}")
def get_qualification(code: str, user: dict = Depends(get_current_user)):
    """자격 대시보드 상세: 마스터 + 격자 + 경로 + 세부약호 + 프로그램 + 연결 v2 행."""
    _require_enabled()
    ds = get_dataset()
    master = ds.master_by_code.get(code)
    if not master:
        raise HTTPException(status_code=404, detail=f"자격 {code} 없음")
    qid = master["qualification_id"]

    blocks = sorted(ds.blocks_by_qid.get(qid, []),
                    key=lambda b: (b["block_order"], b.get("variant") or ""))
    routes = ds.routes_by_qid.get(qid, [])
    children = sorted(ds.children_by_qid.get(qid, []),
                      key=lambda m: (m.get("display_order") or 10**9, qual_code_sort_key(m["code"])))
    child_summaries = []
    for c in children:
        cid = c["qualification_id"]
        child_summaries.append({
            "code": c["code"], "name_ko": c["name_ko"], "confidence": c.get("confidence", ""),
            "program_ids": c.get("program_ids", []),
            "summary": ds.summary_for(cid),
            "routes": ds.routes_by_qid.get(cid, []),
        })

    program_ids = set(master.get("program_ids") or [])
    if master.get("delegated_to"):
        program_ids.add(master["delegated_to"])
    for b in blocks:
        program_ids.update(b.get("program_ids") or [])
    for r in routes:
        program_ids.update(r.get("program_ids") or [])
    programs = [ds.program_by_id[p] for p in sorted(program_ids) if p in ds.program_by_id]

    v2_ids: list[str] = []
    for b in blocks:
        v2_ids.extend(b.get("v2_row_ids") or [])
    for r in routes:
        if r.get("v2_row_id"):
            v2_ids.append(r["v2_row_id"])
    v2_ids = list(dict.fromkeys(v2_ids))  # 순서 보존 dedup

    parent: Optional[dict] = None
    if master.get("parent_qualification_id"):
        parent = ds.master_by_id.get(master["parent_qualification_id"])

    doc_reqs: dict = {}
    for b in blocks:
        if b["block_id"] in ds.dr_by_target:
            doc_reqs[b["block_id"]] = ds.dr_by_target[b["block_id"]]
    for r in routes:
        if r["route_id"] in ds.dr_by_target:
            doc_reqs[r["route_id"]] = ds.dr_by_target[r["route_id"]]

    return {
        "master": master,
        "parent": {"code": parent["code"], "name_ko": parent["name_ko"]} if parent else None,
        "summary": ds.summary_for(qid),
        "blocks": blocks,
        "routes": routes,
        "children": child_summaries,
        "programs": programs,
        "v2_rows": _v2_rows_for(v2_ids),
        "doc_requirements": doc_reqs,
        "editable": _editable_for(user),
    }


# ════════════════════════════════════════════════════════════════════════════
# 편집(CRUD) — FEATURE_GUIDELINES_V3_EDIT + PG. 오버레이 계층(정본 JSON 무수정).
# ════════════════════════════════════════════════════════════════════════════

_CODE_RE = re.compile(r"^[A-Z](-[0-9A-Z]{1,4}){1,3}$")
_BLOCK_TYPES = ("EXTRA_WORK", "WORKPLACE", "GRANT", "CHANGE", "EXTEND", "REENTRY", "REGISTRATION")
_BLOCK_ORDER = {t: i + 1 for i, t in enumerate(_BLOCK_TYPES)}
_ROUTE_SUFFIX = {
    "recognition": "RECOGNITION", "consulate": "CONSULATE", "evisa": "EVISA",
    "domestic_only": "DOMESTIC", "not_applicable": "NA",
    "alternative_route": "ALT", "discontinued": "DISCONTINUED",
}

_QUAL_FIELDS = {"qualification_id", "parent_qualification_id", "manual_type", "group", "code",
                "name_ko", "name_en", "activity_scope", "eligible_persons", "stay_limit",
                "delegated_to", "program_ids", "sub_codes", "confidence", "notes", "status",
                "display_order", "is_active"}
_BLOCK_FIELDS = {"block_id", "qualification_id", "block_type", "block_order", "variant",
                 "block_label", "applicability", "na_source", "na_reason", "redirect_to",
                 "redirect_route_id", "cases", "fee", "office_docs", "client_docs",
                 "conditional_docs", "exceptions", "refusal_redirect", "visa_docs_reference",
                 "quickdoc_links", "v2_row_ids", "program_ids", "confidence", "notes", "status",
                 "display_order", "is_active"}
_ROUTE_FIELDS = {"route_id", "qualification_id", "route_type", "route_label", "application_place",
                 "application_form", "fee", "requires_recognition_before_consulate",
                 "minister_approval_required", "office_docs", "client_docs", "conditional_docs",
                 "exceptions", "quickdoc_links", "v2_row_id", "program_ids", "confidence",
                 "notes", "status", "docs_notice", "alt_apply_as", "alt_relation",
                 "alt_follow_up", "alt_caution", "display_order", "is_active"}
_DR_FIELDS = {"requirement_id", "target_type", "target_id", "doc_name", "doc_kind", "doc_role",
              "condition", "display_condition", "is_required", "form_ref", "source_v2_row_id",
              "confidence", "notes", "template_candidate", "needs_human_review",
              "review_category", "final_disposition", "quickdoc_link", "added_from_manual",
              "display_order", "is_active", "reuse_of", "s_scope", "display_hint"}
_GROUP_FIELDS = {"group_key", "label", "description", "sort_order", "is_active"}
_AUX_FIELDS = {"aux_id", "name", "kind", "description", "application_place",
               "application_method", "application_form", "fee", "processing_note",
               "notes", "quickdoc_link", "v2_row_id", "display_order", "is_active"}


def _require_editable() -> None:
    _require_enabled()
    if not feature_flags.guidelines_v3_edit_enabled():
        raise HTTPException(status_code=409, detail="편집 기능이 비활성 상태입니다 (FEATURE_GUIDELINES_V3_EDIT).")
    if not edit_store.edit_enabled():
        raise HTTPException(status_code=503, detail="편집 저장소(PostgreSQL)가 구성되지 않았습니다.")


def _scan_banned(payload: dict, where: str) -> None:
    def _walk(v, path):
        if isinstance(v, str):
            for p in BANNED_PHRASES:
                if p in v:
                    raise HTTPException(status_code=400, detail=f"운영 금지 문구 포함: '{p}' ({where}.{path})")
        elif isinstance(v, dict):
            for k, x in v.items():
                _walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                _walk(x, f"{path}[{i}]")
    _walk(payload, "payload")


def _clean_fields(payload: dict, allowed: set, where: str) -> dict:
    bad = set(payload) - allowed
    if bad:
        raise HTTPException(status_code=400, detail=f"허용되지 않는 필드: {sorted(bad)} ({where})")
    return payload


def _req(payload: dict, field: str, where: str) -> None:
    v = payload.get(field)
    if v is None or (isinstance(v, str) and not v.strip()):
        raise HTTPException(status_code=400, detail=f"필수값 누락: {field} ({where})")


def _next_dr_id(ds: _Dataset, edits: dict) -> str:
    nums = [0]
    for d in ds.doc_reqs:
        m = re.match(r"^DR:E?(\d+)$", d.get("requirement_id", ""))
        if m:
            nums.append(int(m.group(1)))
    for eid in (edits.get("doc_requirement") or {}):
        m = re.match(r"^DR:E?(\d+)$", eid)
        if m:
            nums.append(int(m.group(1)))
    return f"DR:E{max(max(nums) + 1, 2000):04d}"


def _unique_route_id(ds: _Dataset, code: str, route_type: str) -> str:
    base = f"VR:{code}_{_ROUTE_SUFFIX.get(route_type, 'ROUTE')}"
    rid, n = base, 2
    existing = {r["route_id"] for r in ds.routes}
    while rid in existing:
        rid, n = f"{base}_{n}", n + 1
    return rid


def _validate_qualification(ds: _Dataset, payload: dict, creating: bool) -> dict:
    _clean_fields(payload, _QUAL_FIELDS, "qualification")
    _req(payload, "code", "자격")
    _req(payload, "name_ko", "자격")
    code = payload["code"].strip()
    if not _CODE_RE.match(code):
        raise HTTPException(status_code=400, detail=f"자격 코드 형식 오류: {code} (예: F-2, F-2-7S, E-7-S1)")
    qid = f"Q:{code}"
    payload["qualification_id"] = qid
    if creating and qid in ds.master_by_id:
        raise HTTPException(status_code=409, detail=f"중복 자격 코드: {code}")
    parent_id = payload.get("parent_qualification_id")
    if parent_id:
        pm = ds.master_by_id.get(parent_id)
        if pm is None or (creating and parent_id == qid):
            raise HTTPException(status_code=400, detail=f"존재하지 않는 상위 자격: {parent_id}")
        payload.setdefault("group", pm.get("group"))
        payload.setdefault("manual_type", pm.get("manual_type", "stay"))
    else:
        _req(payload, "group", "자격")
        if payload["group"] not in {g["group_key"] for g in ds.groups}:
            raise HTTPException(status_code=400, detail=f"존재하지 않는 대분류: {payload['group']}")
    defaults = {"manual_type": "stay", "parent_qualification_id": None, "activity_scope": "",
                "eligible_persons": "", "stay_limit": "", "delegated_to": None,
                "program_ids": [], "sub_codes": [], "confidence": "high", "notes": "",
                "status": "active"}
    merged = {**defaults, **({} if creating else dict(ds.master_by_id.get(qid) or {})), **payload}
    _scan_banned(merged, f"자격 {code}")
    return merged


def _validate_block(ds: _Dataset, payload: dict, creating: bool) -> dict:
    _clean_fields(payload, _BLOCK_FIELDS, "stay_block")
    _req(payload, "qualification_id", "체류업무")
    _req(payload, "block_type", "체류업무")
    _req(payload, "block_label", "체류업무")
    _req(payload, "applicability", "체류업무")
    if payload["qualification_id"] not in ds.master_by_id:
        raise HTTPException(status_code=400, detail=f"존재하지 않는 자격: {payload['qualification_id']}")
    if payload["block_type"] not in _BLOCK_TYPES:
        raise HTTPException(status_code=400, detail=f"업무 유형 오류: {payload['block_type']}")
    if payload["applicability"] not in ("applicable", "not_applicable", "conditional"):
        raise HTTPException(status_code=400, detail="상태는 가능/조건부/불가 중 하나여야 합니다 (unknown 저장 불가).")
    if payload["applicability"] == "not_applicable" and not (payload.get("na_reason") or "").strip():
        raise HTTPException(status_code=400, detail="불가(해당 없음) 업무는 사유(na_reason)가 필요합니다.")
    code = payload["qualification_id"].split(":", 1)[1]
    variant = payload.get("variant")
    bid = payload.get("block_id") or (f"SB:{code}_{payload['block_type']}" + (f"_{variant}" if variant else ""))
    payload["block_id"] = bid
    existing = {b["block_id"] for b in ds.blocks}
    if creating and bid in existing:
        raise HTTPException(status_code=409, detail=f"중복 업무: {bid} (해당 자격에 같은 업무가 이미 있습니다)")
    defaults = {"variant": None, "na_source": None, "na_reason": None, "redirect_to": None,
                "redirect_route_id": None, "cases": [], "fee": None, "office_docs": [],
                "client_docs": [], "conditional_docs": [], "exceptions": [],
                "refusal_redirect": None, "visa_docs_reference": None, "quickdoc_links": [],
                "v2_row_ids": [], "program_ids": [], "confidence": "high", "notes": "",
                "status": "active", "block_order": _BLOCK_ORDER.get(payload["block_type"], 99)}
    base = {} if creating else dict(next((b for b in ds.blocks if b["block_id"] == bid), {}) or {})
    merged = {**defaults, **base, **payload}
    if merged["applicability"] == "not_applicable":
        if not merged.get("na_source"):
            merged["na_source"] = "user_approved"
    else:
        merged["na_source"] = None
    _scan_banned(merged, f"업무 {bid}")
    return merged


def _validate_route(ds: _Dataset, payload: dict, creating: bool) -> dict:
    _clean_fields(payload, _ROUTE_FIELDS, "visa_route")
    _req(payload, "qualification_id", "사증 경로")
    _req(payload, "route_type", "사증 경로")
    _req(payload, "route_label", "사증 경로")
    if payload["qualification_id"] not in ds.master_by_id:
        raise HTTPException(status_code=400, detail=f"존재하지 않는 자격: {payload['qualification_id']}")
    rt = payload["route_type"]
    if rt not in ALLOWED_ROUTE_TYPES:
        raise HTTPException(status_code=400, detail=f"route 유형 오류: {rt}")
    code = payload["qualification_id"].split(":", 1)[1]
    rid = payload.get("route_id") or _unique_route_id(ds, code, rt)
    payload["route_id"] = rid
    if creating and any(r["route_id"] == rid for r in ds.routes):
        raise HTTPException(status_code=409, detail=f"중복 route id: {rid}")
    if rt in REAL_ROUTE_TYPES and not (payload.get("application_place") or "").strip():
        base_r = next((r for r in ds.routes if r["route_id"] == rid), None)
        if creating or not (base_r or {}).get("application_place"):
            raise HTTPException(status_code=400, detail="실제 신청 경로는 신청처(application_place)가 필요합니다.")
    if rt == "alternative_route":
        for f in ("alt_apply_as", "alt_follow_up"):
            base_r = next((r for r in ds.routes if r["route_id"] == rid), None)
            if not (payload.get(f) or (base_r or {}).get(f)):
                raise HTTPException(status_code=400, detail=f"대체 신청 경로는 {f} 가 필요합니다.")
    defaults = {"application_place": "", "application_form": "", "fee": None,
                "requires_recognition_before_consulate": rt == "recognition",
                "minister_approval_required": False, "office_docs": [], "client_docs": [],
                "conditional_docs": [], "exceptions": [], "quickdoc_links": [],
                "v2_row_id": None, "program_ids": [], "confidence": "high", "notes": "",
                "status": "active"}
    base = {} if creating else dict(next((r for r in ds.routes if r["route_id"] == rid), {}) or {})
    merged = {**defaults, **base, **payload}
    _scan_banned(merged, f"경로 {rid}")
    return merged


def _validate_dr(ds: _Dataset, payload: dict, creating: bool, edits: dict) -> dict:
    _clean_fields(payload, _DR_FIELDS, "doc_requirement")
    _req(payload, "target_id", "준비서류")
    _req(payload, "doc_name", "준비서류")
    _req(payload, "doc_role", "준비서류")
    if payload["doc_role"] not in ALLOWED_DOC_ROLES:
        raise HTTPException(status_code=400, detail=f"서류 구분 오류: {payload['doc_role']} (client/office/conditional)")
    target = payload["target_id"]
    block_ids = {b["block_id"] for b in ds.blocks}
    route_ids = {r["route_id"] for r in ds.routes}
    if target.startswith("SB:"):
        if target not in block_ids:
            raise HTTPException(status_code=400, detail=f"존재하지 않는 업무: {target}")
        payload["target_type"] = "stay_block"
    elif target.startswith("VR:"):
        if target not in route_ids:
            raise HTTPException(status_code=400, detail=f"존재하지 않는 사증 경로: {target}")
        payload["target_type"] = "visa_route"
    elif target.startswith("AUX:"):
        if target not in {a["aux_id"] for a in ds.aux}:
            raise HTTPException(status_code=400, detail=f"존재하지 않는 보조 민원: {target}")
        payload["target_type"] = "aux"
    else:
        raise HTTPException(status_code=400, detail=f"서류 대상 형식 오류: {target}")
    if payload["doc_name"].strip() == "수수료":
        raise HTTPException(status_code=400, detail="'수수료'는 서류가 아닙니다 — 수수료 필드를 사용하세요.")
    rid = payload.get("requirement_id") or _next_dr_id(ds, edits)
    payload["requirement_id"] = rid
    if creating and any(d["requirement_id"] == rid for d in ds.doc_reqs):
        raise HTTPException(status_code=409, detail=f"중복 서류 id: {rid}")
    if payload["doc_role"] == "conditional":
        if not (payload.get("condition") or "").strip():
            raise HTTPException(status_code=400, detail="해당 시 추가서류는 조건(condition)이 필요합니다.")
        payload["is_required"] = False
        payload.setdefault("display_condition", payload["condition"])
    else:
        payload["is_required"] = True
        payload["condition"] = None
    dup = [d for d in ds.dr_by_target.get(target, [])
           if d["doc_name"] == payload["doc_name"].strip() and d["requirement_id"] != rid]
    if dup:
        raise HTTPException(status_code=409, detail=f"같은 대상에 동일 서류명이 이미 있습니다: {payload['doc_name']}")
    defaults = {"doc_kind": "evidence", "condition": None, "form_ref": None,
                "source_v2_row_id": None, "confidence": "high", "notes": "",
                "template_candidate": None, "needs_human_review": False,
                "review_category": "sourced", "final_disposition": "confirmed",
                "quickdoc_link": None, "added_from_manual": False}
    base = {} if creating else dict(next((d for d in ds.doc_reqs if d["requirement_id"] == rid), {}) or {})
    merged = {**defaults, **base, **payload}
    _scan_banned(merged, f"서류 {rid}")
    return merged


def _validate_group(ds: _Dataset, payload: dict, creating: bool) -> dict:
    _clean_fields(payload, _GROUP_FIELDS, "group")
    _req(payload, "group_key", "대분류")
    _req(payload, "label", "대분류")
    key = payload["group_key"].strip()
    if not re.match(r"^[A-Z0-9_]{1,12}$", key):
        raise HTTPException(status_code=400, detail=f"대분류 키 형식 오류: {key}")
    payload["group_key"] = key
    if creating and key in {g["group_key"] for g in ds.groups}:
        raise HTTPException(status_code=409, detail=f"중복 대분류: {key}")
    defaults = {"description": "", "sort_order": 900, "is_active": True}
    base = {} if creating else dict(next((g for g in ds.groups if g["group_key"] == key), {}) or {})
    merged = {**defaults, **base, **payload}
    _scan_banned(merged, f"대분류 {key}")
    return merged


def _next_aux_id(ds: _Dataset, edits: dict) -> str:
    """편집 신설 보조 민원 ID — AUX:E0001+ (정본 M1-*/CIVIL-* 대역과 분리)."""
    used = {a["aux_id"] for a in ds.aux} | set((edits.get("aux") or {}).keys())
    n = 1
    while f"AUX:E{n:04d}" in used:
        n += 1
    return f"AUX:E{n:04d}"


def _validate_aux(ds: _Dataset, payload: dict, creating: bool) -> dict:
    _clean_fields(payload, _AUX_FIELDS, "aux")
    _req(payload, "name", "보조 민원")
    aid = str(payload.get("aux_id") or "").strip()
    if creating and not aid:
        aid = _next_aux_id(ds, edit_store.load_all_edits())
    if not re.match(r"^AUX:[A-Z0-9-]{1,24}$", aid):
        raise HTTPException(status_code=400, detail=f"보조 민원 ID 형식 오류: {aid}")
    payload["aux_id"] = aid
    if creating and any(a["aux_id"] == aid for a in ds.aux):
        raise HTTPException(status_code=409, detail=f"중복 보조 민원 ID: {aid}")
    name = payload["name"].strip()
    if any(a["name"] == name and a["aux_id"] != aid for a in ds.aux):
        raise HTTPException(status_code=409, detail=f"동일 이름의 보조 민원이 이미 있습니다: {name}")
    defaults = {"kind": "application_claim", "description": "", "notes": "",
                "quickdoc_link": None, "v2_row_id": None}
    base = {} if creating else dict(next((a for a in ds.aux if a["aux_id"] == aid), {}) or {})
    merged = {**defaults, **base, **payload}
    _scan_banned(merged, f"보조 민원 {aid}")
    return merged


def _impact_for(ds: _Dataset, entity_type: str, entity_id: str) -> dict:
    """삭제 전 영향 — 연결 데이터 목록(코드·건수)."""
    if entity_type == "group":
        quals = [m["code"] for m in ds.masters
                 if not m.get("parent_qualification_id") and m.get("group") == entity_id]
        return {"qualifications": quals, "blocks": [], "routes": [], "doc_requirements": [],
                "blocking": len(quals) > 0, "cascade_allowed": False}
    if entity_type == "qualification":
        m = ds.master_by_id.get(entity_id)
        if not m:
            return {"qualifications": [], "blocks": [], "routes": [], "doc_requirements": [],
                    "blocking": False, "cascade_allowed": True}
        qids = [entity_id] + [c["qualification_id"] for c in ds.children_by_qid.get(entity_id, [])]
        blocks = [b["block_id"] for q in qids for b in ds.blocks_by_qid.get(q, [])]
        routes = [r["route_id"] for q in qids for r in ds.routes_by_qid.get(q, [])]
        targets = set(blocks) | set(routes)
        drs = [d["requirement_id"] for d in ds.doc_reqs if d["target_id"] in targets]
        children = [c["code"] for c in ds.children_by_qid.get(entity_id, [])]
        return {"qualifications": children, "blocks": blocks, "routes": routes,
                "doc_requirements": drs,
                "blocking": bool(children or blocks or routes or drs), "cascade_allowed": True}
    if entity_type in ("stay_block", "visa_route", "aux"):
        drs = [d["requirement_id"] for d in ds.doc_reqs if d["target_id"] == entity_id]
        return {"qualifications": [], "blocks": [], "routes": [], "doc_requirements": drs,
                "blocking": bool(drs), "cascade_allowed": True}
    return {"qualifications": [], "blocks": [], "routes": [], "doc_requirements": [],
            "blocking": False, "cascade_allowed": True}


@router.get("/edit/overlay-status/{entity_type}/{entity_id:path}")
def edit_overlay_status(entity_type: str, entity_id: str, admin: dict = Depends(require_guideline_editor)):
    """'적용 이력 보기' — 이 엔터티에 현재 오버레이 편집이 있는지 + 언제/누가.
    guideline_v3_edits 는 엔터티당 최신 상태 1행만 보관하므로(과거 여러 버전은 audit_logs,
    FEATURE_PG_AUDIT 미설정 시 비어 있을 수 있음) 이 응답은 '현재 적용 상태' 기준이다."""
    _require_editable()
    row = edit_store.get_edit_row(entity_type, entity_id)
    if row is None:
        return {"has_overlay": False}
    return {"has_overlay": True, **row}


def _audit(request: Request, admin: dict, op: str, entity_type: str, entity_id: str,
           before: Optional[dict], after: Optional[dict]) -> None:
    try:
        from backend.services.audit_service import log_event
        log_event(action="GUIDELINE_V3_EDIT",
                  actor_login_id=admin.get("login_id"), tenant_id=admin.get("tenant_id"),
                  target_type=entity_type, target_id=entity_id,
                  payload={"op": op, "before": before, "after": after},
                  ip_address=(request.client.host if request.client else None))
    except Exception:  # noqa: BLE001 — 감사 실패가 편집을 막으면 안 됨(best-effort)
        pass


_VALIDATORS = {
    "qualification": _validate_qualification,
    "stay_block": _validate_block,
    "visa_route": _validate_route,
    "group": _validate_group,
    "aux": _validate_aux,
}
_ID_FIELD = {"group": "group_key", "qualification": "qualification_id",
             "stay_block": "block_id", "visa_route": "route_id",
             "doc_requirement": "requirement_id", "aux": "aux_id"}


def _current_entity(ds: _Dataset, entity_type: str, entity_id: str) -> Optional[dict]:
    if entity_type == "group":
        return next((g for g in ds.groups if g["group_key"] == entity_id), None)
    if entity_type == "qualification":
        return ds.master_by_id.get(entity_id)
    if entity_type == "stay_block":
        return next((b for b in ds.blocks if b["block_id"] == entity_id), None)
    if entity_type == "visa_route":
        return next((r for r in ds.routes if r["route_id"] == entity_id), None)
    if entity_type == "doc_requirement":
        return next((d for d in ds.doc_reqs if d["requirement_id"] == entity_id), None)
    if entity_type == "aux":
        return next((a for a in ds.aux if a["aux_id"] == entity_id), None)
    return None


@router.get("/edit/status")
def edit_status(user: dict = Depends(get_current_user)):
    """편집 계층 상태 + 호출자 기준 editable — 전 로그인 사용자 조회 가능(권한 진단용)."""
    _require_enabled()
    return {"enabled": edit_store.edit_enabled(),
            "flag": feature_flags.guidelines_v3_edit_enabled(),
            "editable": _editable_for(user),
            "role": user.get("role", ""),
            "is_admin": bool(user.get("is_admin")),
            "is_master": bool(user.get("is_master")),
            "is_sub_admin": bool(user.get("is_sub_admin"))}


@router.get("/edit/export")
def edit_export(admin: dict = Depends(require_guideline_editor)):
    """병합 결과 전체(JSON 파일 대응 형태) — 오프라인 검증·백업용."""
    _require_editable()
    ds = _build_merged()
    return {"qualification_master": ds.masters, "stay_blocks": ds.blocks,
            "visa_routes": ds.routes, "document_requirements": ds.doc_reqs,
            "groups": ds.groups, "_meta": ds.meta}


@router.get("/edit/impact/{entity_type}/{entity_id:path}")
def edit_impact(entity_type: str, entity_id: str, admin: dict = Depends(require_guideline_editor)):
    _require_editable()
    ds = get_dataset()
    ent = _current_entity(ds, entity_type, entity_id)
    if ent is None:
        raise HTTPException(status_code=404, detail=f"{entity_id} 없음")
    return {"entity_id": entity_id, "entity": ent, "impact": _impact_for(ds, entity_type, entity_id)}


@router.post("/edit/{entity_type}")
def edit_create(entity_type: str, request: Request,
                payload: dict = Body(...), admin: dict = Depends(require_guideline_editor)):
    _require_editable()
    ds = _build_merged()
    edits = edit_store.load_all_edits()
    if entity_type == "doc_requirement":
        merged = _validate_dr(ds, dict(payload), creating=True, edits=edits)
    elif entity_type in _VALIDATORS:
        merged = _VALIDATORS[entity_type](ds, dict(payload), creating=True)
    else:
        raise HTTPException(status_code=400, detail=f"entity_type 오류: {entity_type}")
    eid = merged[_ID_FIELD[entity_type]]
    if _current_entity(ds, entity_type, eid) is not None:
        raise HTTPException(status_code=409, detail=f"이미 존재합니다: {eid}")
    edit_store.save_edit(entity_type, eid, "upsert", merged, admin.get("login_id", ""))
    invalidate_merged()
    _audit(request, admin, "create", entity_type, eid, None, merged)
    return {"status": "ok", "entity_id": eid, "entity": merged}


@router.put("/edit/{entity_type}/{entity_id:path}")
def edit_update(entity_type: str, entity_id: str, request: Request,
                payload: dict = Body(...), admin: dict = Depends(require_guideline_editor)):
    _require_editable()
    ds = _build_merged()
    before = _current_entity(ds, entity_type, entity_id)
    if before is None:
        raise HTTPException(status_code=404, detail=f"{entity_id} 없음")
    body = {**before, **payload}
    body.pop("summary", None)
    edits = edit_store.load_all_edits()
    if entity_type == "doc_requirement":
        body["requirement_id"] = entity_id
        merged = _validate_dr(ds, body, creating=False, edits=edits)
    elif entity_type in _VALIDATORS:
        body[_ID_FIELD[entity_type]] = entity_id
        merged = _VALIDATORS[entity_type](ds, body, creating=False)
    else:
        raise HTTPException(status_code=400, detail=f"entity_type 오류: {entity_type}")
    if merged[_ID_FIELD[entity_type]] != entity_id:
        raise HTTPException(status_code=400, detail="식별 코드는 수정할 수 없습니다 (삭제 후 새로 추가).")
    edit_store.save_edit(entity_type, entity_id, "upsert", merged, admin.get("login_id", ""))
    invalidate_merged()
    _audit(request, admin, "update", entity_type, entity_id, before, merged)
    return {"status": "ok", "entity_id": entity_id, "entity": merged}


@router.delete("/edit/{entity_type}/{entity_id:path}")
def edit_delete(entity_type: str, entity_id: str, request: Request,
                cascade: bool = False, admin: dict = Depends(require_guideline_editor)):
    _require_editable()
    ds = _build_merged()
    before = _current_entity(ds, entity_type, entity_id)
    if before is None:
        raise HTTPException(status_code=404, detail=f"{entity_id} 없음")
    impact = _impact_for(ds, entity_type, entity_id)
    if impact["blocking"] and not cascade:
        raise HTTPException(status_code=409, detail={
            "message": "연결 데이터가 있어 바로 삭제할 수 없습니다. 영향 확인 후 연결 데이터 포함 삭제를 사용하세요.",
            "impact": impact})
    if impact["blocking"] and not impact["cascade_allowed"]:
        raise HTTPException(status_code=409, detail={
            "message": "이 항목은 하위 데이터 포함 삭제가 허용되지 않습니다. 하위 항목을 먼저 이동·삭제하세요.",
            "impact": impact})
    edits: list[tuple[str, str, str, Optional[dict]]] = []
    if cascade:
        for c in impact["qualifications"]:
            edits.append(("qualification", f"Q:{c}", "delete", None))
        for b in impact["blocks"]:
            edits.append(("stay_block", b, "delete", None))
        for r in impact["routes"]:
            edits.append(("visa_route", r, "delete", None))
        for d in impact["doc_requirements"]:
            edits.append(("doc_requirement", d, "delete", None))
    edits.append((entity_type, entity_id, "delete", None))
    edit_store.save_edits_bulk(edits, admin.get("login_id", ""))
    invalidate_merged()
    _audit(request, admin, "delete", entity_type, entity_id, before,
           {"cascade": cascade, "impact": impact})
    return {"status": "ok", "deleted": entity_id, "cascade": cascade, "impact": impact}


@router.post("/edit/{entity_type}/{entity_id:path}/revert")
def edit_revert(entity_type: str, entity_id: str, request: Request,
                admin: dict = Depends(require_guideline_editor)):
    """오버레이 제거 — 정본(JSON) 값으로 되돌리기. 편집으로 신설된 항목은 사라진다."""
    _require_editable()
    ds = _build_merged()
    before = _current_entity(ds, entity_type, entity_id)
    removed = edit_store.remove_edit(entity_type, entity_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"{entity_id} 에 대한 편집 내역이 없습니다.")
    invalidate_merged()
    _audit(request, admin, "revert", entity_type, entity_id, before, None)
    return {"status": "ok", "reverted": entity_id}


# ── 매뉴얼 후보 ↔ v3 편집 연결 추적(신규 테이블·migration 없음, audit_logs 재사용) ──────
# 위 edit_create/edit_update 와 완전히 동일한 검증기(_VALIDATORS/_validate_dr)·
# edit_store.save_edit 를 그대로 호출한다 — "동일한 정합성 검증" 요건을 별도
# 재구현 없이 만족시키기 위함. 차이는 저장 전/후 오버레이 스냅샷을 떠서
# manual_candidate_v3_link_service 에 적용 이력으로 남기는 것뿐이다.
from backend.services import manual_candidate_v3_link_service as cand_link  # noqa: E402


@router.get("/candidate-links/{candidate_row_id}")
def list_candidate_links(candidate_row_id: str, admin: dict = Depends(require_guideline_editor)):
    """이 매뉴얼 후보로 현재 적용(취소 안 된) 중인 v3 엔터티 목록."""
    _require_editable()
    return {"candidate_row_id": candidate_row_id, "links": cand_link.list_links_for_candidate(candidate_row_id)}


@router.post("/candidate-links/create/{entity_type}")
def candidate_link_create(entity_type: str, request: Request,
                          body: dict = Body(...), admin: dict = Depends(require_guideline_editor)):
    """매뉴얼 후보에서 새 엔터티 생성 + 후보 연결 기록. body = {candidate_row_id, payload}."""
    _require_editable()
    candidate_row_id = str(body.get("candidate_row_id") or "").strip()
    payload = body.get("payload") or {}
    if not candidate_row_id:
        raise HTTPException(status_code=400, detail="candidate_row_id 필요")
    ds = _build_merged()
    edits = edit_store.load_all_edits()
    if entity_type == "doc_requirement":
        merged = _validate_dr(ds, dict(payload), creating=True, edits=edits)
    elif entity_type in _VALIDATORS:
        merged = _VALIDATORS[entity_type](ds, dict(payload), creating=True)
    else:
        raise HTTPException(status_code=400, detail=f"entity_type 오류: {entity_type}")
    eid = merged[_ID_FIELD[entity_type]]
    if _current_entity(ds, entity_type, eid) is not None:
        raise HTTPException(status_code=409, detail=f"이미 존재합니다: {eid}")
    actor = admin.get("login_id", "")
    tenant = admin.get("tenant_id", "")
    edit_store.save_edit(entity_type, eid, "upsert", merged, actor)
    invalidate_merged()
    after = edit_store.get_edit_row(entity_type, eid)
    cand_link.record_apply(candidate_row_id=candidate_row_id, entity_type=entity_type, entity_id=eid,
                           actor_login_id=actor, tenant_id=tenant, before=None, after=after)
    _audit(request, admin, "create", entity_type, eid, None, merged)
    return {"status": "ok", "entity_id": eid, "entity": merged}


@router.put("/candidate-links/update/{entity_type}/{entity_id:path}")
def candidate_link_update(entity_type: str, entity_id: str, request: Request,
                          body: dict = Body(...), admin: dict = Depends(require_guideline_editor)):
    """매뉴얼 후보에서 기존 엔터티 수정 + 후보 연결 기록. body = {candidate_row_id, payload}.
    동일 (후보, 엔터티) 쌍이 이미 활성 적용 상태면 409(중복 적용 차단)."""
    _require_editable()
    candidate_row_id = str(body.get("candidate_row_id") or "").strip()
    payload = body.get("payload") or {}
    if not candidate_row_id:
        raise HTTPException(status_code=400, detail="candidate_row_id 필요")
    if cand_link.get_active_link(candidate_row_id, entity_type, entity_id) is not None:
        raise HTTPException(status_code=409, detail="이미 이 후보로 적용된 항목입니다. 먼저 적용 취소하세요.")
    ds = _build_merged()
    before_entity = _current_entity(ds, entity_type, entity_id)
    if before_entity is None:
        raise HTTPException(status_code=404, detail=f"{entity_id} 없음")
    body_merged = {**before_entity, **payload}
    body_merged.pop("summary", None)
    edits = edit_store.load_all_edits()
    if entity_type == "doc_requirement":
        body_merged["requirement_id"] = entity_id
        merged = _validate_dr(ds, body_merged, creating=False, edits=edits)
    elif entity_type in _VALIDATORS:
        body_merged[_ID_FIELD[entity_type]] = entity_id
        merged = _VALIDATORS[entity_type](ds, body_merged, creating=False)
    else:
        raise HTTPException(status_code=400, detail=f"entity_type 오류: {entity_type}")
    if merged[_ID_FIELD[entity_type]] != entity_id:
        raise HTTPException(status_code=400, detail="식별 코드는 수정할 수 없습니다 (삭제 후 새로 추가).")
    actor = admin.get("login_id", "")
    tenant = admin.get("tenant_id", "")
    before_overlay = edit_store.get_edit_row(entity_type, entity_id)
    edit_store.save_edit(entity_type, entity_id, "upsert", merged, actor)
    invalidate_merged()
    after_overlay = edit_store.get_edit_row(entity_type, entity_id)
    cand_link.record_apply(candidate_row_id=candidate_row_id, entity_type=entity_type, entity_id=entity_id,
                           actor_login_id=actor, tenant_id=tenant, before=before_overlay, after=after_overlay)
    _audit(request, admin, "update", entity_type, entity_id, before_entity, merged)
    return {"status": "ok", "entity_id": entity_id, "entity": merged}


@router.post("/candidate-links/revert")
def candidate_link_revert(request: Request, body: dict = Body(...),
                          admin: dict = Depends(require_guideline_editor)):
    """이 후보가 만든 특정 엔터티 적용만 취소. body = {candidate_row_id, entity_type, entity_id}.
    취소 시점의 오버레이가 적용 당시 after 스냅샷과 다르면(다른 관리자가 그 사이 추가로
    수정) 자동 취소하지 않고 409 — 정본/이전 상태로 임의 덮어쓰지 않는다."""
    _require_editable()
    candidate_row_id = str(body.get("candidate_row_id") or "").strip()
    entity_type = str(body.get("entity_type") or "").strip()
    entity_id = str(body.get("entity_id") or "").strip()
    if not (candidate_row_id and entity_type and entity_id):
        raise HTTPException(status_code=400, detail="candidate_row_id/entity_type/entity_id 필요")
    link = cand_link.get_active_link(candidate_row_id, entity_type, entity_id)
    if link is None:
        raise HTTPException(status_code=404, detail="이 후보로 적용된 이력이 없습니다.")
    current = edit_store.get_edit_row(entity_type, entity_id)
    before_overlay = link.get("before")
    after_overlay = link.get("after")
    ds = _build_merged()
    before_entity = _current_entity(ds, entity_type, entity_id)
    if current == before_overlay:
        # 이미 다른 경로(정본 복원 버튼 등)로 되돌려진 상태 — 덮어쓸 것 없음, 이력만 정리.
        pass
    elif current == after_overlay:
        if before_overlay is None:
            edit_store.remove_edit(entity_type, entity_id)
        else:
            edit_store.save_edit(entity_type, entity_id, before_overlay["op"], before_overlay["payload"],
                                 admin.get("login_id", ""))
    else:
        raise HTTPException(status_code=409, detail={
            "message": "이후 다른 관리자가 이 항목을 추가로 수정했습니다. 자동 취소할 수 없습니다 — 직접 확인 후 처리하세요.",
            "current": current, "recorded_after": after_overlay})
    invalidate_merged()
    cand_link.record_revert(candidate_row_id=candidate_row_id, entity_type=entity_type, entity_id=entity_id,
                            actor_login_id=admin.get("login_id", ""), tenant_id=admin.get("tenant_id", ""))
    after_entity = _current_entity(_build_merged(), entity_type, entity_id)
    _audit(request, admin, "candidate_revert", entity_type, entity_id, before_entity, after_entity)
    return {"status": "ok", "entity_type": entity_type, "entity_id": entity_id}
