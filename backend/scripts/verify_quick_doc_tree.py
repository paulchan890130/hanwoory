"""verify_quick_doc_tree.py — DB 트리/필요서류가 하드코딩과 동일한지 + 관리자 CRUD 검증.

읽기 검증은 운영 데이터를 변경하지 않는다. CRUD 검증은 임시 노드/서류를 만들고
soft-delete 후 hard-delete 로 정리한다(시드 데이터 불변).
"""
from __future__ import annotations
import os, sys
from pathlib import Path
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from backend.routers.quick_doc import (
    _hardcoded_tree, REQUIRED_DOCS, calc_is_minor,
)
from backend.services import quick_doc_config_pg_service as cfg

out = []
def p(s=""): out.append(str(s))

# ── 1. 트리 동일성 ───────────────────────────────────────────────────────────
db_tree = cfg.build_tree()
hc_tree = _hardcoded_tree()
tree_ok = True
for key in ("categories", "minwon", "types", "subtypes"):
    if db_tree.get(key) != hc_tree.get(key):
        tree_ok = False
        p(f"[트리 불일치] {key}")
        p(f"  DB: {db_tree.get(key)}")
        p(f"  HC: {hc_tree.get(key)}")
p(f"1) 트리 동일성: {'OK ✅' if tree_ok else 'MISMATCH ❌'}")

# ── 2. 필요서류 동일성 (모든 REQUIRED_DOCS 조합) ──────────────────────────────
docs_ok = True
mismatches = 0
for (cat, minwon, kind, detail), groups in REQUIRED_DOCS.items():
    # 라우터와 동일하게 kind 정규화 입력으로 호출(kind '' → 'x' 도 검사)
    db = cfg.required_docs(cat, minwon, kind or "x", detail) or {"main": [], "agent": []}
    exp_main = list(groups.get("main", []))
    exp_agent = list(groups.get("agent", []))
    if db.get("main") != exp_main or db.get("agent") != exp_agent:
        docs_ok = False
        mismatches += 1
        if mismatches <= 10:
            p(f"[서류 불일치] ({cat},{minwon},{kind},{detail})")
            p(f"  DB main={db.get('main')} agent={db.get('agent')}")
            p(f"  HC main={exp_main} agent={exp_agent}")
p(f"2) 필요서류 동일성: {'OK ✅' if docs_ok else f'{mismatches} MISMATCH ❌'}  (검사 {len(REQUIRED_DOCS)} 조합)")

# 대표 케이스 명시 출력
for label, args in [("체류>등록>F>1", ("체류","등록","F","1")),
                    ("체류>연장>F>4", ("체류","연장","F","4")),
                    ("체류>변경>F>5", ("체류","변경","F","5"))]:
    d = cfg.required_docs(*args)
    p(f"   - {label}: main={d['main']} agent={d['agent']}")

# ── 3. 템플릿 자동매핑 ───────────────────────────────────────────────────────
p("3) 템플릿 자동매핑:")
for nm in ["통합신청서", "거주숙소 제공 확인서", "직업 및 연간 소득금액 신고서", "신원보증서"]:
    p(f"   - '{nm}' → {cfg.auto_map_template(nm) or '(없음=missing)'}")

# ── 4. 관리자 CRUD (임시 데이터, 검증 후 정리) ───────────────────────────────
p("4) 관리자 CRUD:")
from sqlalchemy import select
from backend.db.session import get_sessionmaker
from backend.db.models.doc_tree import DocTreeNode, DocRequiredDocument
created_node_ids = []
created_doc_ids = []
try:
    # 민원 추가(체류 하위)
    db_tree2 = cfg.build_tree()
    # category 노드 id 찾기
    with get_sessionmaker()() as s:
        cat_row = s.scalar(select(DocTreeNode).where(DocTreeNode.level=="category", DocTreeNode.name=="체류").limit(1))
        cat_id = cat_row.id
    pet = cfg.create_node(cat_id, "petition", "__검증민원__")
    created_node_ids.append(pet["id"])
    p(f"   - 민원 추가: id={pet['id']} name={pet['name']}")
    # 하위 종류 추가
    typ = cfg.create_node(pet["id"], "type", "__검증종류__")
    created_node_ids.append(typ["id"])
    p(f"   - 종류 추가(새 민원 하위): id={typ['id']}")
    # 종류 하위 세부 추가
    sub = cfg.create_node(typ["id"], "subtype", "__검증세부__")
    created_node_ids.append(sub["id"])
    p(f"   - 세부 추가: id={sub['id']}")
    # 필요서류 추가(자동매핑) — 통합신청서는 매핑되어야 함
    doc = cfg.create_required_document(sub["id"], "통합신청서", "main")
    created_doc_ids.append(doc["id"])
    p(f"   - 필요서류 추가: id={doc['id']} template={doc['template_filename']} status={doc['template_status']}")
    # 새 조합이 공개 트리/서류에 노출되는지
    t2 = cfg.build_tree()
    appears = "__검증민원__" in t2["minwon"].get("체류", [])
    rd = cfg.required_docs("체류","__검증민원__","__검증종류__","__검증세부__")
    p(f"   - 새 민원 공개트리 노출: {appears},  필요서류 조회: {rd}")
    # 이름 수정
    cfg.update_node(pet["id"], name="__검증민원수정__")
    # soft delete
    cfg.delete_node(pet["id"])
    t3 = cfg.build_tree()
    hidden = "__검증민원수정__" not in t3["minwon"].get("체류", [])
    p(f"   - 이름수정+soft delete 후 공개트리에서 숨김: {hidden}")
    crud_ok = appears and bool(rd["main"]) and hidden and doc["template_status"]=="mapped"
    p(f"   CRUD: {'OK ✅' if crud_ok else 'FAIL ❌'}")
finally:
    # 정리: 임시 데이터 hard delete (시드 불변 보장)
    with get_sessionmaker()() as s:
        for did in created_doc_ids:
            r = s.get(DocRequiredDocument, did)
            if r: s.delete(r)
        for nid in reversed(created_node_ids):
            r = s.get(DocTreeNode, nid)
            if r: s.delete(r)
        s.commit()
    p("   - 임시 검증 데이터 정리 완료")

report = "\n".join(out)
print(report)
try:
    (ROOT/"analysis").mkdir(exist_ok=True)
    (ROOT/"analysis"/"i1j6o_verification.txt").write_text(report, encoding="utf-8")
    print(f"\n[저장] {ROOT/'analysis'/'i1j6o_verification.txt'}")
except OSError as e:
    print(f"[경고] {e}")
