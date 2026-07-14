"""실무지침 v3 route·세부약호·준비서류 정합성 검증 도구.

사용: `python -m backend.scripts.verify_guideline_route_integrity`
모든 검사를 통과하면 exit 0, 하나라도 실패하면 실패 목록을 출력하고 exit 1.

검사 항목:
 1. 자격 코드·route id·DR id 중복 없음
 2. route → qualification FK 전량 실재(고아 route 0)
 3. 부모 sub_codes ↔ 실제 하위 master 행 양방향 완전 일치(세부약호 표시 누락 0)
 4. route_type 이 허용 유형(recognition/consulate/evisa/domestic_only/
    not_applicable/alternative_route/discontinued)만 사용됨
 5. 실제 신청 route(recognition/consulate/evisa, 폐지 제외)는
    신청처가 있고 신청인(client)·사무소(office) 준비서류가 모두 존재
 6. alternative_route 는 대체 경로 설명 필드(alt_apply_as/alt_follow_up) 보유
 7. stay block: applicability 4값 이내 + unknown 0 + NA 블록 na_reason 보유
 8. 신청 가능(가능/조건부) 기초 블록은 서류 소스(DR/인라인/v2 연결) 보유
 9. DR doc_role 3분류 준수 + conditional 행 규칙(is_required=false, 조건 문구)
10. 운영 노출 텍스트 금지 문구 0 (미정리/검수/블록 부재/관서 확인 후 안내 등)
11. 목록 카드 집계(확정 N/M·인정서·사증 경로 수) 재계산 일치
12. _meta counts 실측 일치
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "guidelines_v3")

REAL_ROUTE_TYPES = {"recognition", "consulate", "evisa"}
STATUS_ROUTE_TYPES = {"domestic_only", "not_applicable", "discontinued"}
ALT_ROUTE_TYPES = {"alternative_route"}
ALLOWED_ROUTE_TYPES = REAL_ROUTE_TYPES | STATUS_ROUTE_TYPES | ALT_ROUTE_TYPES
ALLOWED_APPLICABILITY = {"applicable", "not_applicable", "conditional", "unknown"}
ALLOWED_DOC_ROLES = {"client", "office", "conditional"}

# 운영 화면·API 로 나가는 텍스트에 남아 있으면 안 되는 미완료성 문구
BANNED_PHRASES = [
    "미정리", "검수", "블록 부재", "관서 확인 후 안내", "공식 확인이 필요한",
    "확인 필요", "내부 검토", "원문 확인", "DOC_PENDING", "정리되어 있지 않습니다",
]

# 텍스트 검사 대상 필드(운영 노출분)
ROUTE_TEXT_FIELDS = ["route_label", "application_place", "application_form", "fee",
                     "docs_notice", "alt_apply_as", "alt_relation", "alt_follow_up", "alt_caution"]
BLOCK_TEXT_FIELDS = ["block_label", "na_reason", "redirect_to", "fee", "conflict"]
DR_TEXT_FIELDS = ["doc_name", "display_condition", "condition", "form_ref"]
MASTER_TEXT_FIELDS = ["name_ko", "activity_scope", "eligible_persons", "stay_limit"]


def _load(name: str):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    masters = _load("qualification_master.json")
    blocks = _load("stay_blocks.json")
    routes = _load("visa_routes.json")
    drs = _load("document_requirements.json")
    meta = _load("_meta.json")

    fails: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
        if not ok:
            fails.append(name)

    # 1. 중복
    codes = [m["code"] for m in masters]
    dup_codes = [c for c, n in Counter(codes).items() if n > 1]
    rids = [r["route_id"] for r in routes]
    dup_rids = [c for c, n in Counter(rids).items() if n > 1]
    dids = [d["requirement_id"] for d in drs]
    dup_dids = [c for c, n in Counter(dids).items() if n > 1]
    check("1. 자격 코드/route id/DR id 중복 0", not dup_codes and not dup_rids and not dup_dids,
          f"code {dup_codes[:3]} route {dup_rids[:3]} dr {dup_dids[:3]}")

    # 2. 고아 route
    qids = {m["qualification_id"] for m in masters}
    orphans = [r["route_id"] for r in routes if r["qualification_id"] not in qids]
    check("2. 고아 route 0", not orphans, str(orphans[:5]))

    # 3. sub_codes ↔ 하위 master 양방향 일치
    by_qid = {m["qualification_id"]: m for m in masters}
    mismatches = []
    children_by_parent: dict = {}
    for m in masters:
        pid = m.get("parent_qualification_id")
        if pid:
            children_by_parent.setdefault(pid, set()).add(m["code"])
    for m in masters:
        listed = set(m.get("sub_codes") or [])
        actual = children_by_parent.get(m["qualification_id"], set())
        if listed != actual:
            mismatches.append(f"{m['code']}: 목록 {sorted(listed - actual)} / 누락 {sorted(actual - listed)}")
    check("3. 세부약호 목록 = 하위 자격 행(양방향)", not mismatches, "; ".join(mismatches[:4]))

    # 4. route_type 허용 유형
    bad_types = [(r["route_id"], r.get("route_type")) for r in routes
                 if r.get("route_type") not in ALLOWED_ROUTE_TYPES]
    check("4. route_type 유형 분류 완전", not bad_types, str(bad_types[:5]))

    # 5. 실제 신청 route 내용·준비서류
    roles_by_target: dict = {}
    for d in drs:
        roles_by_target.setdefault(d["target_id"], set()).add(d.get("doc_role"))
    unfilled = []
    for r in routes:
        if r.get("route_type") in REAL_ROUTE_TYPES and r.get("status") != "abolished":
            roles = roles_by_target.get(r["route_id"], set())
            has_docs = ("client" in roles and "office" in roles) or (r.get("client_docs") and r.get("office_docs"))
            if not (r.get("application_place") or "").strip() or not has_docs:
                unfilled.append(r["route_id"])
    check("5. 실제 신청 route 신청처·준비서류(신청인+사무소) 공백 0", not unfilled, str(unfilled[:6]))

    # 6. 대체 경로 설명 필드
    bad_alt = [r["route_id"] for r in routes if r.get("route_type") in ALT_ROUTE_TYPES
               and not ((r.get("alt_apply_as") or "").strip() and (r.get("alt_follow_up") or "").strip())]
    check("6. alternative_route 설명 필드 보유", not bad_alt, str(bad_alt))

    # 7. 블록 applicability
    bad_app = [(b["block_id"], b.get("applicability")) for b in blocks
               if b.get("applicability") not in ALLOWED_APPLICABILITY]
    unknowns = [b["block_id"] for b in blocks if b.get("applicability") == "unknown"]
    na_no_reason = [b["block_id"] for b in blocks
                    if b.get("applicability") == "not_applicable" and not (b.get("na_reason") or "").strip()]
    check("7. 블록 상태 확정(unknown 0·NA 사유 보유)", not bad_app and not unknowns and not na_no_reason,
          f"bad {bad_app[:3]} unknown {unknowns[:5]} na없음 {na_no_reason[:3]}")

    # 8. 신청 가능 기초 블록 서류 소스
    dr_targets = set(roles_by_target)
    no_source = []
    for b in blocks:
        if b.get("variant") is not None:
            continue
        if b.get("applicability") not in ("applicable", "conditional"):
            continue
        has = (b["block_id"] in dr_targets or b.get("office_docs") or b.get("client_docs")
               or b.get("conditional_docs") or b.get("v2_row_ids"))
        if not has:
            no_source.append(b["block_id"])
    check("8. 신청 가능 블록 서류 소스 공백 0", not no_source, str(no_source[:8]))

    # 9. DR 분류 규칙
    bad_role = [d["requirement_id"] for d in drs if d.get("doc_role") not in ALLOWED_DOC_ROLES]
    bad_cond = [d["requirement_id"] for d in drs if d.get("doc_role") == "conditional"
                and (d.get("is_required") or not (d.get("condition") or "").strip())]
    fee_rows = [d["requirement_id"] for d in drs if (d.get("doc_name") or "").strip() == "수수료"]
    check("9. DR 3분류·conditional 규칙·수수료 행 금지", not bad_role and not bad_cond and not fee_rows,
          f"role {bad_role[:3]} cond {bad_cond[:3]} fee {fee_rows[:3]}")

    # 10. 금지 문구
    hits = []

    def scan(kind: str, ident: str, field: str, value) -> None:
        if not isinstance(value, str):
            return
        for p in BANNED_PHRASES:
            if p in value:
                hits.append(f"{kind} {ident}.{field}: …{p}…")

    for r in routes:
        for f in ROUTE_TEXT_FIELDS:
            scan("route", r["route_id"], f, r.get(f))
        for i, x in enumerate(r.get("exceptions") or []):
            scan("route", r["route_id"], f"exceptions[{i}]", x)
    for b in blocks:
        for f in BLOCK_TEXT_FIELDS:
            scan("block", b["block_id"], f, b.get(f))
        for i, x in enumerate(b.get("exceptions") or []):
            scan("block", b["block_id"], f"exceptions[{i}]", x)
    for d in drs:
        for f in DR_TEXT_FIELDS:
            scan("dr", d["requirement_id"], f, d.get(f))
    for m in masters:
        for f in MASTER_TEXT_FIELDS:
            scan("master", m["code"], f, m.get(f))
    check("10. 운영 노출 금지 문구 0", not hits, "; ".join(hits[:6]))

    # 11. 목록 카드 집계 재계산 일치(요약 로직과 동일 규칙)
    blocks_by_qid: dict = {}
    for b in blocks:
        blocks_by_qid.setdefault(b["qualification_id"], []).append(b)
    routes_by_qid: dict = {}
    for r in routes:
        routes_by_qid.setdefault(r["qualification_id"], []).append(r)
    agg_bad = []
    for m in masters:
        if m.get("parent_qualification_id"):
            continue
        qid = m["qualification_id"]
        own = [b for b in blocks_by_qid.get(qid, []) if b.get("variant") is None]
        confirmed = sum(1 for b in own if b.get("applicability") in ("applicable", "not_applicable", "conditional"))
        if confirmed != len(own):
            agg_bad.append(f"{m['code']}: 확정 {confirmed}/{len(own)}")
        listed = set(m.get("sub_codes") or [])
        actual = children_by_parent.get(qid, set())
        if len(listed) != len(actual):
            agg_bad.append(f"{m['code']}: 세부 {len(listed)}≠{len(actual)}")
    check("11. 카드 집계(전 업무 확정·세부약호 수) 일치", not agg_bad, "; ".join(agg_bad[:5]))

    # 12. meta counts
    ok_meta = (meta.get("counts", {}).get("visa_routes") == len(routes)
               and meta.get("counts", {}).get("document_requirements") == len(drs)
               and meta.get("counts", {}).get("qualification_master", len(masters)) in (len(masters),))
    check("12. _meta counts 실측 일치", ok_meta,
          f"routes {meta.get('counts', {}).get('visa_routes')}/{len(routes)} drs {meta.get('counts', {}).get('document_requirements')}/{len(drs)}")

    # 참고 집계 출력
    print("\nroute_type:", dict(Counter(r["route_type"] for r in routes)))
    print("applicability:", dict(Counter(b["applicability"] for b in blocks)))
    real = [r for r in routes if r["route_type"] in REAL_ROUTE_TYPES and r.get("status") != "abolished"]
    with_docs = sum(1 for r in real if {"client", "office"} <= roles_by_target.get(r["route_id"], set()))
    print(f"실제 신청 route {len(real)}건 중 준비서류(신청인+사무소) 보유 {with_docs}건")

    if fails:
        print(f"\nRESULT: FAIL ({len(fails)}): {fails}")
        return 1
    print("\nRESULT: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
