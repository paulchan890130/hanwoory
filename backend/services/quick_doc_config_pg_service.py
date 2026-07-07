"""문서자동작성 선택 트리 + 필요서류 — PostgreSQL 설정 서비스(Phase I-1J-6O).

quick_doc.py 의 하드코딩 상수를 대체하는 편집형 DB 설정. 내부 구조는 기존과 동일하게
**category → petition(민원) → type(종류) → subtype(세부)** 4단계를 유지한다.

핵심:
- ``build_tree()`` — 기존 ``GET /tree`` 와 **동일한 dict 모양**을 DB 에서 재구성
  (categories / minwon / types / subtypes). 프론트 QuickDocPanel 무수정 호환.
- ``required_docs(category, minwon, kind, detail)`` — 기존 ``/required-docs`` 와
  동일한 {main, agent} 반환. kind=="x" → "" 정규화(사증 준비중 호환).
- 관리자 CRUD: 노드/필요서류 추가·수정·soft delete, 템플릿 자동매핑.
- 템플릿 자동매핑: templates/ 폴더의 PDF 파일명을 서류명에서 후보 생성해 매칭.

PG 미구성 시 ``get_sessionmaker()`` 가 RuntimeError → 호출부(라우터)가 하드코딩
fallback 으로 전환한다. 트리가 비었으면(``has_active_nodes()`` False) 역시 fallback.
"""
from __future__ import annotations

import os
import re
from typing import Optional

from sqlalchemy import select

from backend.db.models.doc_tree import DocTreeNode, DocRequiredDocument


_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TEMPLATES_DIR = os.path.join(_BASE, "templates")


def _SL():
    from backend.db.session import get_sessionmaker
    return get_sessionmaker()()


# ── 템플릿 자동매핑 ──────────────────────────────────────────────────────────

def list_template_files() -> list[str]:
    """templates/ 폴더의 .pdf 파일명 목록(정렬). PDF 없으면 빈 리스트."""
    try:
        names = [f for f in os.listdir(_TEMPLATES_DIR) if f.lower().endswith(".pdf")]
    except OSError:
        return []
    return sorted(names)


def _strip_special(s: str) -> str:
    # 공백/특수문자 제거, 한글·영숫자만 남김(괄호 등 제거)
    return re.sub(r"[^0-9A-Za-z가-힣]", "", s)


def _template_candidates(doc_name: str) -> list[str]:
    """서류명 → templates/ PDF 파일명 후보(우선순위 순, 확장자 포함)."""
    n = (doc_name or "").strip()
    cands: list[str] = []
    seen: set[str] = set()
    for stem in (n, n.replace(" ", ""), _strip_special(n)):
        fn = f"{stem}.pdf"
        if stem and fn not in seen:
            seen.add(fn)
            cands.append(fn)
    return cands


def auto_map_template(doc_name: str) -> Optional[str]:
    """서류명에 매칭되는 templates/ PDF 파일명 반환(없으면 None).

    1) 서류명 그대로  2) 공백 제거  3) 특수문자 제거 후보를 순서대로 시도.
    실제 파일 존재(대소문자 무시)를 확인한다.
    """
    files = list_template_files()
    lower_map = {f.lower(): f for f in files}
    for cand in _template_candidates(doc_name):
        hit = lower_map.get(cand.lower())
        if hit:
            return hit
    return None


# ── HWPX 템플릿 (0028) ───────────────────────────────────────────────────────

_HWPX_DIRS = (
    os.path.join(_TEMPLATES_DIR, "hwpx"),   # 우선
    _TEMPLATES_DIR,                          # 보조(루트 .hwpx)
)


def _is_valid_hwpx_file(path: str) -> bool:
    """실제 HWPX(zip + Contents/content.hpf)인지 검증 — 구형 HWP 바이너리 제외.
    (quick_doc._is_valid_hwpx 와 동일 기준; 순환 import 방지를 위해 서비스에도 둔다.)"""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            return "Contents/content.hpf" in z.namelist()
    except Exception:
        return False


def list_hwpx_template_files() -> list[dict]:
    """Git 관리 HWPX 템플릿 목록 — [{filename, dir, display_name}] (유효 HWPX만).

    templates/hwpx/ 우선, templates/ 루트 보조. 같은 파일명이면 hwpx/ 가 우선.
    관리자 화면의 HWPX 템플릿 선택 드롭다운 소스."""
    out: list[dict] = []
    seen: set[str] = set()
    for d in _HWPX_DIRS:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        rel_dir = "templates/hwpx" if d.endswith("hwpx") else "templates"
        for fn in names:
            if not fn.lower().endswith(".hwpx") or fn in seen:
                continue
            path = os.path.join(d, fn)
            if not _is_valid_hwpx_file(path):
                continue
            seen.add(fn)
            out.append({"filename": fn, "dir": rel_dir,
                        "display_name": os.path.splitext(fn)[0]})
    return out


def resolve_hwpx_filename_path(filename: str) -> Optional[str]:
    """HWPX 파일명(확장자 포함) → 절대경로. 디렉터리 탈출 방지: basename 만 허용,
    _HWPX_DIRS 안에서만 찾는다. 유효 HWPX 가 아니면 None."""
    fn = os.path.basename((filename or "").strip())
    if not fn or not fn.lower().endswith(".hwpx"):
        return None
    for d in _HWPX_DIRS:
        path = os.path.join(d, fn)
        if os.path.isfile(path) and _is_valid_hwpx_file(path):
            return path
    return None


def output_formats_map() -> dict:
    """활성 필요서류 중 output_format 이 설정된 것만 {서류명: format} 으로 반환.

    generate-full(PDF)/generate-hwpx 가 문서별 출력방식을 강제하는 데 사용:
      hwpx=HWPX 우선 / pdf=PDF만 / both=둘 다 / disabled=비활성 / 미설정=자동(기존 동작).
    """
    with _SL() as s:
        rows = s.scalars(
            select(DocRequiredDocument).where(
                DocRequiredDocument.is_active.is_(True),
                DocRequiredDocument.output_format.is_not(None),
            )
        ).all()
        return {r.name: r.output_format for r in rows if r.output_format}


def hwpx_template_for(doc_name: str) -> Optional[str]:
    """DB 필요서류(활성)에 명시 매핑된 HWPX 절대경로 반환. 없으면 None(→ 레지스트리 fallback)."""
    with _SL() as s:
        row = s.scalar(
            select(DocRequiredDocument).where(
                DocRequiredDocument.name == doc_name,
                DocRequiredDocument.is_active.is_(True),
                DocRequiredDocument.hwpx_template_filename.is_not(None),
            ).limit(1)
        )
        if row and row.hwpx_template_filename:
            return resolve_hwpx_filename_path(row.hwpx_template_filename)
    return None


def _doc_to_dict(d: DocRequiredDocument) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "doc_group": d.doc_group,
        "sort_order": d.sort_order,
        "is_active": bool(d.is_active),
        "template_filename": d.template_filename or "",
        "template_status": d.template_status or "missing",
        "hwpx_template_filename": d.hwpx_template_filename or "",
        "output_format": d.output_format or "",   # "" = 자동(기존 동작)
    }


def _node_to_dict(n: DocTreeNode) -> dict:
    return {
        "id": n.id,
        "parent_id": n.parent_id,
        "level": n.level,
        "name": n.name,
        "sort_order": n.sort_order,
        "is_active": bool(n.is_active),
    }


# ── 읽기: 공개 트리/필요서류 (활성만) ────────────────────────────────────────

def has_active_nodes() -> bool:
    """활성 category 노드가 하나라도 있으면 True(=DB 트리 사용 가능)."""
    with _SL() as s:
        row = s.scalar(
            select(DocTreeNode.id).where(
                DocTreeNode.level == "category", DocTreeNode.is_active.is_(True)
            ).limit(1)
        )
        return row is not None


def _children(s, parent_id, level, active_only: bool) -> list[DocTreeNode]:
    stmt = select(DocTreeNode).where(
        DocTreeNode.parent_id == parent_id, DocTreeNode.level == level
    )
    if active_only:
        stmt = stmt.where(DocTreeNode.is_active.is_(True))
    rows = list(s.scalars(stmt).all())
    rows.sort(key=lambda r: (r.sort_order, r.id))
    return rows


def build_tree() -> dict:
    """기존 GET /tree 와 동일 모양: categories / minwon / types / subtypes (활성만)."""
    with _SL() as s:
        cats = _children(s, None, "category", True)
        categories = [c.name for c in cats]
        minwon: dict[str, list[str]] = {}
        types: dict[str, list[str]] = {}
        subtypes: dict[str, list[str]] = {}
        for c in cats:
            pets = _children(s, c.id, "petition", True)
            minwon[c.name] = [p.name for p in pets]
            for p in pets:
                tps = _children(s, p.id, "type", True)
                types[f"{c.name}|{p.name}"] = [t.name for t in tps]
                for t in tps:
                    subs = _children(s, t.id, "subtype", True)
                    subtypes[f"{c.name}|{p.name}|{t.name}"] = [su.name for su in subs]
    return {"categories": categories, "minwon": minwon, "types": types, "subtypes": subtypes}


def _find_child(s, parent_id, name, level, active_only: bool) -> Optional[DocTreeNode]:
    stmt = select(DocTreeNode).where(
        DocTreeNode.parent_id == parent_id,
        DocTreeNode.level == level,
        DocTreeNode.name == name,
    )
    if active_only:
        stmt = stmt.where(DocTreeNode.is_active.is_(True))
    return s.scalar(stmt.limit(1))


def _resolve_leaf(s, category, minwon, kind, detail, active_only: bool) -> Optional[DocTreeNode]:
    """(구분,민원,종류,세부) → 가장 깊은 매칭 노드. kind=='x' → '' 정규화."""
    k = "" if (kind or "") == "x" else (kind or "")
    cat = _find_child(s, None, category, "category", active_only)
    if not cat:
        return None
    pet = _find_child(s, cat.id, minwon, "petition", active_only)
    if not pet:
        return None
    node = pet
    if k:
        t = _find_child(s, pet.id, k, "type", active_only)
        if t:
            node = t
            if detail:
                su = _find_child(s, t.id, detail, "subtype", active_only)
                if su:
                    node = su
    return node


def _docs_of_node(s, node_id, active_only: bool) -> dict:
    stmt = select(DocRequiredDocument).where(DocRequiredDocument.node_id == node_id)
    if active_only:
        stmt = stmt.where(DocRequiredDocument.is_active.is_(True))
    rows = list(s.scalars(stmt).all())
    rows.sort(key=lambda r: (r.sort_order, r.id))
    main = [r.name for r in rows if r.doc_group != "agent"]
    agent = [r.name for r in rows if r.doc_group == "agent"]
    return {"main": main, "agent": agent}


def required_docs(category, minwon, kind, detail) -> Optional[dict]:
    """{main:[...], agent:[...]} 또는 매칭 노드 없으면 None(→ 라우터 fallback)."""
    with _SL() as s:
        node = _resolve_leaf(s, category, minwon, kind, detail, active_only=True)
        if node is None:
            return None
        docs = _docs_of_node(s, node.id, active_only=True)
        # 세부까지 내려갔는데 서류가 없으면 종류 노드 docs 로 fallback(기존 key2 동작과 동일)
        if not docs["main"] and not docs["agent"] and node.level == "subtype" and node.parent_id:
            docs = _docs_of_node(s, node.parent_id, active_only=True)
        return docs


def template_for(doc_name: str) -> Optional[str]:
    """DB 필요서류(활성)에 매핑된 templates/ 상대경로 반환. 없으면 None."""
    with _SL() as s:
        row = s.scalar(
            select(DocRequiredDocument).where(
                DocRequiredDocument.name == doc_name,
                DocRequiredDocument.is_active.is_(True),
                DocRequiredDocument.template_filename.is_not(None),
            ).limit(1)
        )
        if row and row.template_filename:
            return f"templates/{row.template_filename}"
    return None


# ── 관리자: 전체 트리(비활성 포함) ───────────────────────────────────────────

def admin_tree() -> dict:
    """관리자용 전체 트리(비활성 포함, id/sort_order/필요서류 포함)."""
    with _SL() as s:
        cats = _children(s, None, "category", False)
        out_cats = []
        for c in cats:
            pets = _children(s, c.id, "petition", False)
            out_pets = []
            for p in pets:
                tps = _children(s, p.id, "type", False)
                out_tps = []
                for t in tps:
                    subs = _children(s, t.id, "subtype", False)
                    out_subs = [
                        {**_node_to_dict(su), "docs": _node_docs_admin(s, su.id)}
                        for su in subs
                    ]
                    out_tps.append({**_node_to_dict(t), "docs": _node_docs_admin(s, t.id),
                                    "subtypes": out_subs})
                out_pets.append({**_node_to_dict(p), "docs": _node_docs_admin(s, p.id),
                                 "types": out_tps})
            out_cats.append({**_node_to_dict(c), "petitions": out_pets})
        return {"categories": out_cats}


def _node_docs_admin(s, node_id) -> list[dict]:
    rows = list(s.scalars(
        select(DocRequiredDocument).where(DocRequiredDocument.node_id == node_id)
    ).all())
    rows.sort(key=lambda r: (r.sort_order, r.id))
    return [_doc_to_dict(r) for r in rows]


# ── 관리자: 노드 CRUD ────────────────────────────────────────────────────────

_CHILD_LEVEL = {"category": "petition", "petition": "type", "type": "subtype"}


def create_node(parent_id: Optional[int], level: str, name: str,
                sort_order: Optional[int] = None) -> dict:
    """노드 추가. parent_id=None → category. level 은 부모 level 의 자식이어야 함."""
    name = (name or "").strip()
    if not name:
        raise ValueError("이름을 입력해 주세요.")
    if level not in ("category", "petition", "type", "subtype"):
        raise ValueError(f"잘못된 level: {level}")
    with _SL() as s:
        if parent_id is None:
            if level != "category":
                raise ValueError("최상위 노드는 level=category 여야 합니다.")
        else:
            parent = s.get(DocTreeNode, parent_id)
            if parent is None:
                raise ValueError("상위 노드를 찾을 수 없습니다.")
            expected = _CHILD_LEVEL.get(parent.level)
            if expected != level:
                raise ValueError(f"'{parent.level}' 하위는 level='{expected}' 여야 합니다.")
        if sort_order is None:
            sibs = _children(s, parent_id, level, active_only=False)
            sort_order = (max([x.sort_order for x in sibs], default=-1) + 1)
        node = DocTreeNode(parent_id=parent_id, level=level, name=name,
                           sort_order=sort_order, is_active=True)
        s.add(node)
        s.commit()
        s.refresh(node)
        return _node_to_dict(node)


def update_node(node_id: int, name: Optional[str] = None,
                sort_order: Optional[int] = None,
                is_active: Optional[bool] = None) -> dict:
    with _SL() as s:
        node = s.get(DocTreeNode, node_id)
        if node is None:
            raise ValueError("노드를 찾을 수 없습니다.")
        if name is not None:
            nm = name.strip()
            if not nm:
                raise ValueError("이름을 비울 수 없습니다.")
            node.name = nm
        if sort_order is not None:
            node.sort_order = sort_order
        if is_active is not None:
            node.is_active = bool(is_active)
        s.commit()
        s.refresh(node)
        return _node_to_dict(node)


def delete_node(node_id: int) -> dict:
    """soft delete(is_active=False). 하위 노드/서류는 보존(조회 시 활성만 노출)."""
    return update_node(node_id, is_active=False)


# ── 관리자: 필요서류 CRUD ────────────────────────────────────────────────────

def create_required_document(node_id: int, name: str, doc_group: str = "main",
                             sort_order: Optional[int] = None,
                             template_filename: Optional[str] = None) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("서류명을 입력해 주세요.")
    if doc_group not in ("main", "agent"):
        doc_group = "main"
    with _SL() as s:
        node = s.get(DocTreeNode, node_id)
        if node is None:
            raise ValueError("연결할 노드를 찾을 수 없습니다.")
        if sort_order is None:
            rows = _node_docs_admin(s, node_id)
            same = [r for r in rows if r["doc_group"] == doc_group]
            sort_order = (max([r["sort_order"] for r in same], default=-1) + 1)
        tf = (template_filename or "").strip() or None
        if tf is None:
            tf = auto_map_template(name)
        status = "mapped" if tf else "missing"
        doc = DocRequiredDocument(node_id=node_id, name=name, doc_group=doc_group,
                                  sort_order=sort_order, is_active=True,
                                  template_filename=tf, template_status=status)
        s.add(doc)
        s.commit()
        s.refresh(doc)
        return _doc_to_dict(doc)


def update_required_document(doc_id: int, name: Optional[str] = None,
                             doc_group: Optional[str] = None,
                             sort_order: Optional[int] = None,
                             is_active: Optional[bool] = None,
                             template_filename: Optional[str] = None,
                             hwpx_template_filename: Optional[str] = None,
                             output_format: Optional[str] = None) -> dict:
    with _SL() as s:
        doc = s.get(DocRequiredDocument, doc_id)
        if doc is None:
            raise ValueError("필요서류를 찾을 수 없습니다.")
        if name is not None:
            nm = name.strip()
            if not nm:
                raise ValueError("서류명을 비울 수 없습니다.")
            doc.name = nm
        if doc_group is not None and doc_group in ("main", "agent"):
            doc.doc_group = doc_group
        if sort_order is not None:
            doc.sort_order = sort_order
        if is_active is not None:
            doc.is_active = bool(is_active)
        if template_filename is not None:
            tf = template_filename.strip() or None
            doc.template_filename = tf
            doc.template_status = "mapped" if tf else "missing"
        if hwpx_template_filename is not None:
            # "" = 명시 매핑 해제(자동매칭으로 복귀). 파일명은 basename + 존재/유효 검증.
            hf = os.path.basename(hwpx_template_filename.strip()) or None
            if hf and resolve_hwpx_filename_path(hf) is None:
                raise ValueError(f"HWPX 템플릿을 찾을 수 없습니다: {hf}")
            doc.hwpx_template_filename = hf
        if output_format is not None:
            of = output_format.strip().lower() or None
            if of and of not in ("pdf", "hwpx", "both", "disabled"):
                raise ValueError("출력방식은 pdf/hwpx/both/disabled 중 하나여야 합니다.")
            doc.output_format = of
        s.commit()
        s.refresh(doc)
        return _doc_to_dict(doc)


def delete_required_document(doc_id: int) -> dict:
    """soft delete(is_active=False)."""
    return update_required_document(doc_id, is_active=False)


def remap_required_document(doc_id: int) -> dict:
    """서류명 기준 템플릿 자동매핑 재계산."""
    with _SL() as s:
        doc = s.get(DocRequiredDocument, doc_id)
        if doc is None:
            raise ValueError("필요서류를 찾을 수 없습니다.")
        tf = auto_map_template(doc.name)
        doc.template_filename = tf
        doc.template_status = "mapped" if tf else "missing"
        s.commit()
        s.refresh(doc)
        return _doc_to_dict(doc)
