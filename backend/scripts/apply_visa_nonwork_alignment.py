# -*- coding: utf-8 -*-
"""사증 절차 정합 + 비취업 문서 체계 정리 (사용자 확정 결정 반영).

결정 사항:
  V1. E-7-S(M1-0324): major=사증발급인데 action_type=GRANT 로 '체류자격 부여' 트리에
      들어가던 충돌 → VISA_CONFIRM 재분류, visa_procedure=confirm_needed
      (인정/공관 임의 확정 금지).
  V2. F-1 사증 5행(F-1-5/15/21/22/24): 절차 확인 필요 유지 + 사용자 지정 주의문구로
      기존 [사증절차] 불릿 교체.
  V3. D-4-5(M1-0372): major '사증발급인정/체류기간 연장허가' 혼합 → '체류기간
      연장허가'로 정리(사증 행 분리는 신규 row 생성 금지 원칙에 따라 확인 필요 보고).
  N1. 비취업 문서 명칭은 기존('비취업 서약서' 등) 유지 — 개명/alias 없음.
  N2. F-3(비취업 자격): 부여/변경/연장/등록 10행의 form_docs(사무소 준비서류)에
      '비취업 서약서' 추가 — 자체 문서자동작성 설정(quick_doc.py 하드코딩)에서
      F-3 등록/연장/변경 main 에 '비취업 서약서'를 쓰는 기존 실무 근거.
      제외: 자격외활동(0085 — 취업허가 신청 업무라 모순), 재입국(0360 — 순수 절차).
  N3. F-1: '비취업 서약서'가 supporting_docs(고객 준비서류)에 있던 7행 → form_docs
      (사무소 준비서류)로 이동(서식은 사무소 준비). 비취업 목적이 명확한 F-1
      연장/등록 8행에 form_docs 추가(문서자동작성 설정의 연장/등록 main 근거).
      제외: 가사보조인(활동성), F-1-4(자격외활동 허용 이슈 — 확인 필요), F-1-51
      (미성년), 재입국.

idempotent. manual_updates 보존. 신규 row 생성 없음.

사용법:
  python backend/scripts/apply_visa_nonwork_alignment.py --dry-run
  python backend/scripts/apply_visa_nonwork_alignment.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(_ROOT, "backend", "data", "immigration_guidelines_db_v2.json")
BACKUP_DIR = os.path.join(_ROOT, "backend", "data", "backups")

NONWORK_DOC = "비취업 서약서"

# F-1 사증 5행 + E-7-S 에 쓸 확인필요 문구 (사용자 지정 문구)
VISA_CONFIRM_NOTE = ("[사증절차] 확인 필요 — 사증절차는 재외공관 또는 출입국 기준에 따라 "
                     "달라질 수 있으므로 신청 전 관할 기준 확인 필요")

F1_VISA_ROWS = {"M1-0205", "M1-0206", "M1-0207", "M1-0208", "M1-0209"}

# F-3: form_docs 에 비취업 서약서 추가 (부여/변경/연장/등록)
F3_ADD_ROWS = {
    "M1-0006",  # F-3 부여
    "M1-0087",  # F-3-2R 변경
    "M1-0089",  # F-3-2R 연장
    "M1-0103",  # F-3 변경
    "M1-0104",  # F-3 연장
    "M1-0259",  # F-3-18 변경
    "M1-0260",  # F-3-18 연장
    "M1-0283",  # F-3-1R 변경
    "M1-0284",  # F-3-3R 변경
    "M1-0359",  # F-3 등록
}
# F-3 제외: M1-0085(자격외활동 — 취업허가 신청 업무), M1-0360(재입국 — 순수 절차)

# F-1: supporting → form 이동 대상(이미 보유 행)
F1_MOVE_ROWS = {
    "M1-0203", "M1-0204", "M1-0205", "M1-0206", "M1-0213", "M1-0214", "M1-0275",
}
# F-1: form_docs 신규 추가(연장/등록 — 문서자동작성 설정의 연장·등록 main 근거)
F1_ADD_ROWS = {
    "M1-0210",  # F-1-5 연장
    "M1-0211",  # F-1-15 연장
    "M1-0212",  # F-1-52 연장
    "M1-0215",  # F-1-9 연장
    "M1-0216",  # F-1-11 연장
    "M1-0219",  # F-1 동포가족 등록
    "M1-0220",  # F-1 동포가족 연장
    "M1-0222",  # F-1-15 등록
}
# F-1 제외: 가사보조인(F-1-21/22/24 전행), F-1-4(자격외활동 허용 — 확인 필요),
#           F-1-51(미성년), 재입국 행


def sf(v: str) -> list:
    return [p.strip() for p in (v or "").split("|") if p.strip()]


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def add_to_form_docs(row: dict, doc: str) -> bool:
    """form_docs 에 서식 추가. 채널 구분(‖) 행은 창구민원(마지막) 블록에 추가."""
    fd = row.get("form_docs") or ""
    if norm(doc) in norm(fd):
        return False
    if "||" in fd:
        blocks = fd.split("||")
        blocks[-1] = blocks[-1].rstrip() + " | " + doc
        row["form_docs"] = " || ".join(b.strip() for b in blocks)
    else:
        parts = sf(fd)
        parts.append(doc)
        row["form_docs"] = " | ".join(parts)
    return True


def remove_from_supporting(row: dict, doc: str) -> bool:
    docs = sf(row.get("supporting_docs") or "")
    kept = [d for d in docs if norm(d) != norm(doc)]
    if len(kept) != len(docs):
        row["supporting_docs"] = " | ".join(kept)
        return True
    return False


def replace_visa_note(row: dict) -> bool:
    """기존 [사증절차] 불릿을 사용자 지정 확인필요 문구로 교체(없으면 선두 삽입)."""
    notes = sf(row.get("practical_notes") or "")
    out, replaced = [], False
    for n in notes:
        if n.startswith("[사증절차]"):
            if not replaced:
                out.append(VISA_CONFIRM_NOTE)
                replaced = True
            # 중복 [사증절차] 불릿은 제거
            continue
        out.append(n)
    if not replaced:
        out.insert(0, VISA_CONFIRM_NOTE)
    new = " | ".join(out)
    if new != (row.get("practical_notes") or "").strip():
        row["practical_notes"] = new
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = json.load(open(DB_PATH, encoding="utf-8"))
    rows = db["master_rows"]
    byid = {r["row_id"]: r for r in rows}
    stats = {"e7s": [], "f1_visa_note": [], "d45": [], "f3_added": [], "f1_moved": [],
             "f1_added": [], "skipped_existing": []}

    # V1. E-7-S 재분류
    r = byid.get("M1-0324")
    if r:
        changed = False
        if r.get("action_type") != "VISA_CONFIRM":
            r["action_type"] = "VISA_CONFIRM"
            changed = True
        if r.get("visa_procedure") != "confirm_needed":
            r["visa_procedure"] = "confirm_needed"
            changed = True
        if replace_visa_note(r):
            changed = True
        if changed:
            stats["e7s"].append("M1-0324")

    # V2. F-1 사증 5행 문구 교체 (visa_procedure 는 confirm_needed 유지)
    for rid in sorted(F1_VISA_ROWS):
        r = byid.get(rid)
        if r and replace_visa_note(r):
            stats["f1_visa_note"].append(rid)

    # V3. D-4-5 major 정리
    r = byid.get("M1-0372")
    if r and r.get("major_action_std") != "체류기간 연장허가":
        r["major_action_std"] = "체류기간 연장허가"
        stats["d45"].append("M1-0372")

    # N2. F-3 form_docs 에 비취업 서약서 추가
    for rid in sorted(F3_ADD_ROWS):
        r = byid.get(rid)
        if not r:
            continue
        if add_to_form_docs(r, NONWORK_DOC):
            stats["f3_added"].append(rid)
        else:
            stats["skipped_existing"].append(rid)

    # N3-a. F-1 supporting → form 이동
    for rid in sorted(F1_MOVE_ROWS):
        r = byid.get(rid)
        if not r:
            continue
        removed = remove_from_supporting(r, NONWORK_DOC)
        added = add_to_form_docs(r, NONWORK_DOC)
        if removed or added:
            stats["f1_moved"].append(rid)

    # N3-b. F-1 연장/등록 form_docs 추가
    for rid in sorted(F1_ADD_ROWS):
        r = byid.get(rid)
        if not r:
            continue
        if add_to_form_docs(r, NONWORK_DOC):
            stats["f1_added"].append(rid)
        else:
            stats["skipped_existing"].append(rid)

    # 검증 지표
    grant_n = sum(1 for x in rows if x.get("action_type") == "GRANT")
    visa_n = sum(1 for x in rows if x.get("action_type") == "VISA_CONFIRM")
    f3_job = [x["row_id"] for x in rows if (x.get("detailed_code") or "").startswith("F-3")
              and "직업신고서" in ((x.get("form_docs") or "") + (x.get("supporting_docs") or ""))]
    nonwork_in_sup = [x["row_id"] for x in rows
                      if any(norm(NONWORK_DOC) == norm(d) for d in sf(x.get("supporting_docs")))]
    mu = sum(len(x.get("manual_updates") or []) for x in rows)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== {mode}: visa/nonwork alignment ===")
    print(f"V1 E-7-S 재분류(GRANT→VISA_CONFIRM+확인필요): {stats['e7s']}")
    print(f"V2 F-1 사증 5행 확인필요 문구 교체: {stats['f1_visa_note']}")
    print(f"V3 D-4-5 major 정리: {stats['d45']}")
    print(f"N2 F-3 비취업 서약서 form_docs 추가: {len(stats['f3_added'])}행 {stats['f3_added']}")
    print(f"N3 F-1 이동(supporting→form): {len(stats['f1_moved'])}행 {stats['f1_moved']}")
    print(f"N3 F-1 연장/등록 추가: {len(stats['f1_added'])}행 {stats['f1_added']}")
    print(f"이미 보유로 스킵: {stats['skipped_existing']}")
    print(f"검증: GRANT {grant_n}행 / VISA_CONFIRM {visa_n}행 / F-3 직업신고서 {len(f3_job)}행"
          f" / supporting에 남은 비취업서약서 {len(nonwork_in_sup)}행 / manual_updates {mu}")

    if args.dry_run:
        print("\n[dry-run] 파일 변경 없음.")
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(BACKUP_DIR, f"immigration_guidelines_db_v2_pre_visa_nonwork_{ts}.json")
    shutil.copy2(DB_PATH, backup)
    print(f"\n백업: {backup}")
    db["갱신일"] = datetime.now().strftime("%Y-%m-%d") + " (visa/nonwork alignment)"
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print(f"저장 완료: {DB_PATH}")


if __name__ == "__main__":
    main()
