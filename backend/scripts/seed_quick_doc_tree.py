"""seed_quick_doc_tree.py — 문서자동작성 하드코딩 트리 → PG 설정 시드(Phase I-1J-6O).

quick_doc.py 의 하드코딩 상수(CATEGORY_OPTIONS / MINWON_OPTIONS / TYPE_OPTIONS /
SUBTYPE_OPTIONS / REQUIRED_DOCS)를 ``doc_tree_nodes`` / ``doc_required_documents`` 로
이관한다. **idempotent** — 같은 (parent, level, name) 노드와 (node, doc_group, name)
서류는 중복 생성하지 않고 재사용한다. 필요서류 템플릿은 자동매핑한다.

내부 구조는 기존과 동일: category → petition(민원) → type(종류) → subtype(세부).
세부가 없는 종류(H2/E7/국적 외/신고)는 종류 노드에, 사증 준비중은 민원 노드에 서류 연결
(REQUIRED_DOCS 의 kind=='' / detail=='' 정규화와 동일한 위치).

CLI:
  python backend/scripts/seed_quick_doc_tree.py --dry-run   # 변경 미적용, 계획만 출력/파일저장
  python backend/scripts/seed_quick_doc_tree.py --apply     # 로컬 DB 에 적용

주의: 운영 DB 에 적용 금지. DATABASE_URL 이 로컬을 가리키는지 확인 후 --apply.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

ANALYSIS_DIR = ROOT / "analysis"


def _plan():
    """하드코딩 상수에서 (nodes, docs) 시드 계획을 구성. DB 접근 없음."""
    from backend.routers.quick_doc import (
        CATEGORY_OPTIONS, MINWON_OPTIONS, TYPE_OPTIONS, SUBTYPE_OPTIONS, REQUIRED_DOCS,
    )

    # 노드 계획: 경로 튜플 → level. 순서 보존 위해 리스트로.
    node_plan: list[tuple] = []  # (path_tuple, level, name, sort_order)
    for ci, cat in enumerate(CATEGORY_OPTIONS):
        node_plan.append(((cat,), "category", cat, ci))
        for pi, pet in enumerate(MINWON_OPTIONS.get(cat, [])):
            node_plan.append(((cat, pet), "petition", pet, pi))
            for ti, typ in enumerate(TYPE_OPTIONS.get((cat, pet), [])):
                node_plan.append(((cat, pet, typ), "type", typ, ti))
                for si, sub in enumerate(SUBTYPE_OPTIONS.get((cat, pet, typ), [])):
                    node_plan.append(((cat, pet, typ, sub), "subtype", sub, si))

    # 필요서류 계획: REQUIRED_DOCS key (cat, minwon, kind, detail) → 노드 경로.
    # kind=='' → 종류 단계 생략(사증 준비중 등). detail=='' → 세부 생략.
    doc_plan: list[tuple] = []  # (node_path_tuple, doc_group, name, sort_order)
    for (cat, minwon, kind, detail), groups in REQUIRED_DOCS.items():
        path = (cat, minwon)
        if kind:
            path = path + (kind,)
            if detail:
                path = path + (detail,)
        for grp in ("main", "agent"):
            for di, name in enumerate(groups.get(grp, [])):
                doc_plan.append((path, grp, name, di))
    return node_plan, doc_plan


def _auto_map(name: str):
    from backend.services.quick_doc_config_pg_service import auto_map_template
    return auto_map_template(name)


def dry_run() -> str:
    node_plan, doc_plan = _plan()
    lines = []
    lines.append("=== seed_quick_doc_tree DRY-RUN ===")
    lines.append(f"노드(node) 계획: {len(node_plan)}개")
    by_level: dict[str, int] = {}
    for _, level, _, _ in node_plan:
        by_level[level] = by_level.get(level, 0) + 1
    for lv in ("category", "petition", "type", "subtype"):
        lines.append(f"  - {lv}: {by_level.get(lv, 0)}")
    lines.append("")
    lines.append(f"필요서류(required_document) 계획: {len(doc_plan)}개")
    mapped = missing = 0
    miss_names = []
    seen_names = set()
    for path, grp, name, _ in doc_plan:
        if name not in seen_names:
            seen_names.add(name)
            if _auto_map(name):
                mapped += 1
            else:
                missing += 1
                miss_names.append(name)
    lines.append(f"  - 고유 서류명: {len(seen_names)}  (템플릿 매핑됨 {mapped} / 없음 {missing})")
    if miss_names:
        lines.append(f"  - 템플릿 없음(missing): {', '.join(sorted(set(miss_names)))}")
    lines.append("")
    lines.append("--- 노드 트리(경로) ---")
    for path, level, name, so in node_plan:
        indent = "  " * (len(path) - 1)
        lines.append(f"{indent}[{level}] {name} (sort={so})")
    lines.append("")
    lines.append("--- 필요서류(노드경로 → 그룹: 서류[템플릿]) ---")
    for path, grp, name, so in doc_plan:
        tf = _auto_map(name) or "—(없음)"
        lines.append(f"  {' > '.join(path)} | {grp} | {name} [{tf}]")
    return "\n".join(lines)


def apply() -> str:
    from sqlalchemy import select
    from backend.db.session import get_sessionmaker, is_configured
    if not is_configured():
        return "[ERROR] DATABASE_URL 미구성 — 적용 불가."
    from backend.db.models.doc_tree import DocTreeNode, DocRequiredDocument

    node_plan, doc_plan = _plan()
    created_nodes = reused_nodes = created_docs = reused_docs = 0
    path_to_id: dict[tuple, int] = {}

    SL = get_sessionmaker()
    with SL() as s:
        # 노드 upsert (전역 트리: tenant_id NULL)
        for path, level, name, so in node_plan:
            parent_id = path_to_id.get(path[:-1]) if len(path) > 1 else None
            existing = s.scalar(
                select(DocTreeNode).where(
                    DocTreeNode.parent_id.is_(None) if parent_id is None
                    else DocTreeNode.parent_id == parent_id,
                    DocTreeNode.level == level,
                    DocTreeNode.name == name,
                ).limit(1)
            )
            if existing is None:
                node = DocTreeNode(parent_id=parent_id, level=level, name=name,
                                   sort_order=so, is_active=True)
                s.add(node)
                s.flush()
                path_to_id[path] = node.id
                created_nodes += 1
            else:
                path_to_id[path] = existing.id
                reused_nodes += 1

        # 필요서류 upsert
        for path, grp, name, so in doc_plan:
            node_id = path_to_id.get(path)
            if node_id is None:
                continue  # 경로 노드가 없으면(이론상 없음) 건너뜀
            existing = s.scalar(
                select(DocRequiredDocument).where(
                    DocRequiredDocument.node_id == node_id,
                    DocRequiredDocument.doc_group == grp,
                    DocRequiredDocument.name == name,
                ).limit(1)
            )
            if existing is None:
                tf = _auto_map(name)
                doc = DocRequiredDocument(
                    node_id=node_id, name=name, doc_group=grp, sort_order=so,
                    is_active=True, template_filename=tf,
                    template_status="mapped" if tf else "missing",
                )
                s.add(doc)
                created_docs += 1
            else:
                reused_docs += 1
        s.commit()

    return (f"[APPLY 완료] 노드 생성 {created_nodes} / 재사용 {reused_nodes}, "
            f"필요서류 생성 {created_docs} / 재사용 {reused_docs}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="변경 없이 계획만(기본)")
    ap.add_argument("--apply", action="store_true", help="로컬 DB 에 적용")
    args = ap.parse_args()

    if args.apply:
        print(apply())
        return
    # 기본: dry-run + analysis 저장
    report = dry_run()
    print(report)
    try:
        ANALYSIS_DIR.mkdir(exist_ok=True)
        out = ANALYSIS_DIR / "i1j6o_seed_dry_run.txt"
        out.write_text(report, encoding="utf-8")
        print(f"\n[저장] {out}")
    except OSError as e:
        print(f"[경고] analysis 저장 실패: {e}")


if __name__ == "__main__":
    main()
