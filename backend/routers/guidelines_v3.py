"""v3 자격 중심 실무지침 — read-only 관리자 API.

데이터 원천: backend/data/guidelines_v3/*.json (1~2단계 산출물).
- v2 JSON(immigration_guidelines_db_v2.json)은 '연결된 기존 지침' 표시용으로
  guidelines 모듈의 인덱스를 read-only 참조만 한다(수정 없음).
- FEATURE_GUIDELINES_V3 off(기본) → 전 엔드포인트 404.
- 관리자 전용(require_admin). 쓰기 엔드포인트 없음.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import require_admin
from backend.db import feature_flags
from backend.routers.guidelines import _ROW_INDEX, _clean_row_display

router = APIRouter()

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "guidelines_v3")


def _load(name: str) -> list | dict:
    path = os.path.join(_DATA_DIR, name)
    if not os.path.exists(path):
        return [] if name != "_meta.json" else {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_META: dict = _load("_meta.json")
_MASTERS: list = _load("qualification_master.json")
_BLOCKS: list = _load("stay_blocks.json")
_ROUTES: list = _load("visa_routes.json")
_PROGRAMS: list = _load("program_tags.json")
_MAPPING: list = _load("v2_mapping.json")
_AUX: list = _load("aux_civil.json")
_DOC_REQS: list = _load("document_requirements.json")

_DR_BY_TARGET: dict = {}
for _dr in _DOC_REQS:
    _DR_BY_TARGET.setdefault(_dr["target_id"], []).append(_dr)

_MASTER_BY_CODE: dict = {m["code"]: m for m in _MASTERS}
_BLOCKS_BY_QID: dict = {}
for _b in _BLOCKS:
    _BLOCKS_BY_QID.setdefault(_b["qualification_id"], []).append(_b)
_ROUTES_BY_QID: dict = {}
for _r in _ROUTES:
    _ROUTES_BY_QID.setdefault(_r["qualification_id"], []).append(_r)
_PROGRAM_BY_ID: dict = {p["program_id"]: p for p in _PROGRAMS}
_CHILDREN_BY_QID: dict = {}
for _m in _MASTERS:
    if _m.get("parent_qualification_id"):
        _CHILDREN_BY_QID.setdefault(_m["parent_qualification_id"], []).append(_m)


def qual_code_sort_key(code: str) -> list:
    """자격코드 자연 정렬 키 — D-2 < D-10, E-7 < E-7-4 < E-7-S1, F-1-5 < F-1-15.
    단순 문자열 정렬 금지(D-10 이 D-2 앞에 오는 문제). 프론트
    ``components/qualifications/common.tsx`` 의 compareQualCode 와 로직 일치 유지."""
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


# 데이터 정규화(로드 시 1회): sub_codes 자연 정렬 — 문자열 정렬로 저장된 과거 데이터 방어
for _m in _MASTERS:
    _m["sub_codes"] = sorted(_m.get("sub_codes") or [], key=qual_code_sort_key)


def _require_enabled() -> None:
    if not feature_flags.guidelines_v3_enabled():
        raise HTTPException(status_code=404, detail="v3 자격 중심 실무지침이 비활성 상태입니다.")
    if not _MASTERS:
        raise HTTPException(status_code=404, detail="v3 데이터 파일이 없습니다 (backend/data/guidelines_v3).")


def _summary_for(qid: str) -> dict:
    own = _BLOCKS_BY_QID.get(qid, [])
    counts = Counter(b["applicability"] for b in own if b.get("variant") is None)
    routes = _ROUTES_BY_QID.get(qid, [])
    return {
        "applicable": counts.get("applicable", 0),
        "not_applicable": counts.get("not_applicable", 0),
        "conditional": counts.get("conditional", 0),
        "unknown": counts.get("unknown", 0),
        "route_count": len(routes),
    }


def _v2_rows_for(ids: list[str]) -> list[dict]:
    out = []
    for rid in ids:
        row = _ROW_INDEX.get(rid)
        if row:
            out.append(_clean_row_display(row))
    return out


@router.get("/meta")
def get_meta(admin: dict = Depends(require_admin)):
    _require_enabled()
    return {"meta": _META, "flag": True}


@router.get("/qualifications")
def list_qualifications(admin: dict = Depends(require_admin)):
    """기초 자격(부모 없음) 목록 + 상태 요약 + 프로그램 목록."""
    _require_enabled()
    base = []
    for m in _MASTERS:
        if m.get("parent_qualification_id"):
            continue
        qid = m["qualification_id"]
        base.append({**m, "summary": _summary_for(qid),
                     "child_count": len(_CHILDREN_BY_QID.get(qid, []))})
    base.sort(key=lambda m: (m["group"], qual_code_sort_key(m["code"])))
    return {"total": len(base), "data": base, "programs": _PROGRAMS}


@router.get("/programs")
def list_programs(admin: dict = Depends(require_admin)):
    _require_enabled()
    return {"total": len(_PROGRAMS), "data": _PROGRAMS}


@router.get("/aux")
def list_aux(admin: dict = Depends(require_admin)):
    """보조 민원(APPLICATION_CLAIM 별도 축) — 격자 밖 기타 신청·신고 6건 + 연결 v2 행."""
    _require_enabled()
    out = []
    for a in _AUX:
        row = _ROW_INDEX.get(a["v2_row_id"])
        out.append({**a, "v2_row": _clean_row_display(row) if row else None,
                    "requirements": _DR_BY_TARGET.get(a["aux_id"], [])})
    return {"total": len(out), "data": out}


@router.get("/qualifications/{code}")
def get_qualification(code: str, admin: dict = Depends(require_admin)):
    """자격 대시보드 상세: 마스터 + 격자 + 경로 + 세부약호 + 프로그램 + 연결 v2 행."""
    _require_enabled()
    master = _MASTER_BY_CODE.get(code)
    if not master:
        raise HTTPException(status_code=404, detail=f"자격 {code} 없음")
    qid = master["qualification_id"]

    blocks = sorted(_BLOCKS_BY_QID.get(qid, []),
                    key=lambda b: (b["block_order"], b.get("variant") or ""))
    routes = _ROUTES_BY_QID.get(qid, [])
    children = sorted(_CHILDREN_BY_QID.get(qid, []), key=lambda m: qual_code_sort_key(m["code"]))
    child_summaries = []
    for c in children:
        cid = c["qualification_id"]
        child_summaries.append({
            "code": c["code"], "name_ko": c["name_ko"], "confidence": c["confidence"],
            "program_ids": c.get("program_ids", []),
            "summary": _summary_for(cid),
            "routes": _ROUTES_BY_QID.get(cid, []),
        })

    program_ids = set(master.get("program_ids") or [])
    if master.get("delegated_to"):
        program_ids.add(master["delegated_to"])
    for b in blocks:
        program_ids.update(b.get("program_ids") or [])
    for r in routes:
        program_ids.update(r.get("program_ids") or [])
    programs = [_PROGRAM_BY_ID[p] for p in sorted(program_ids) if p in _PROGRAM_BY_ID]

    v2_ids: list[str] = []
    for b in blocks:
        v2_ids.extend(b.get("v2_row_ids") or [])
    for r in routes:
        if r.get("v2_row_id"):
            v2_ids.append(r["v2_row_id"])
    v2_ids = list(dict.fromkeys(v2_ids))  # 순서 보존 dedup

    parent: Optional[dict] = None
    if master.get("parent_qualification_id"):
        pid = master["parent_qualification_id"]
        parent = next((m for m in _MASTERS if m["qualification_id"] == pid), None)

    # v3 document_requirements — 이 자격의 블록/경로 target 별 서류(정독 기준). 없으면 빈 dict.
    doc_reqs: dict = {}
    for b in blocks:
        if b["block_id"] in _DR_BY_TARGET:
            doc_reqs[b["block_id"]] = _DR_BY_TARGET[b["block_id"]]
    for r in routes:
        if r["route_id"] in _DR_BY_TARGET:
            doc_reqs[r["route_id"]] = _DR_BY_TARGET[r["route_id"]]

    return {
        "master": master,
        "parent": {"code": parent["code"], "name_ko": parent["name_ko"]} if parent else None,
        "summary": _summary_for(qid),
        "blocks": blocks,
        "routes": routes,
        "children": child_summaries,
        "programs": programs,
        "v2_rows": _v2_rows_for(v2_ids),
        "doc_requirements": doc_reqs,
    }
