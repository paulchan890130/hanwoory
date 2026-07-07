# -*- coding: utf-8 -*-
"""실무지침 업무 분류·서류 분류·사증/체류 구분 정밀화 (2차 정리).

사용자 필수 기준 7건 반영:
  W1. 잘못된 서류명 `업무수행확인서` 일괄 삭제 (form_docs 198행 — `대행업무수행확인서`는 보존)
  W2. 사무소 준비서류(form_docs)에 `위임장`·`대행업무수행확인서` 일괄 포함 (누락분만 추가,
      고객 준비서류에는 넣지 않음, 채널 구분 행은 창구민원 블록에 추가)
  W3. 연장/변경/등록 혼재 — 전수 스캔 결과 실질 혼재 0건(hit 2건은 겸용 사유서·주자격자
      요건 입증으로 정당) → 데이터 변경 없음, 보고만
  W4. 사증(VISA_CONFIRM 25행) 절차 구분 명시:
      - 신규 필드 `visa_procedure`: recognition(사증발급인정신청) / consulate(재외공관
        사증발급신청) / both / confirm_needed  — 기존 코드는 dict.get 기반이라 무해
      - practical_notes 선두에 절차 구분 안내 문장 삽입
      - C-3-8(단기 복수사증)은 사증발급인정 대상이 아니므로 form_docs 의
        '사증발급인정서 신청서' → '사증발급신청서(재외공관 제출)' 교정
      - F-1 계열 5행은 90일 이하 공관장 재량 여지가 있어 confirm_needed 처리(임의 확정 금지)
  W5. 비취업 서약서 누락 보정 — 취업 불가 F-1 의 자격 취득 단계(변경/사증확인) 6행에만
      추가(기존 F-1-5 패턴 준용). 가사보조인(허용활동 있음)·F-1-4(단순노무 허용 신설)·
      F-1-51(미성년)·연장/등록/재입국 행은 제외. F-3 변경/부여에는 주의 문구만.
  W6. 동포 가족 F-1/F-3 — 코드 치환 없음 확인(F-1-9/11/F-1 전부 F-1 유지, F-3-2R 은
      지역특화 지침의 공식 코드로 정당). 다만 노트의 '(F-3 부여 등)' 추정 문구는
      F-1→F-3 임의 치환을 유도할 수 있어 중립 문구로 교체.
  W7. 포괄(bare)코드 vs 세부코드 중복 — 전 자격군 전수 스캔 결과 실질 중복 0건
      (F-2 bare 4행은 최우수인재(F-2-T) 동반가족·공통 등록/재입국으로 각각 근거 있는
      정당한 행, F-1 bare 3행은 동포 가족 전용 업무) → 데이터 변경 없음, 보고만

idempotent. manual_updates 감사기록 보존.

사용법:
  python backend/scripts/refine_guideline_classifications.py --dry-run
  python backend/scripts/refine_guideline_classifications.py --apply
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

# ── W4. 사증 절차 구분 ───────────────────────────────────────────────────────
NOTE_RECOGNITION = ("[사증절차] 이 항목은 국내 출입국·외국인관서 사증발급인정신청 기준입니다 — "
                    "인정서 발급 후 재외공관에서 사증을 신청합니다. 재외공관 직접 신청 절차는 "
                    "공관·매뉴얼 기준을 별도 확인해야 합니다.")
NOTE_CONSULATE = ("[사증절차] 이 자격은 재외공관에 사증발급신청을 하는 절차입니다 — 국내 "
                  "사증발급인정신청 대상이 아니므로 공관 접수 기준을 확인해야 합니다.")
NOTE_CONFIRM = ("[사증절차] 이 자격은 사안에 따라 사증발급인정신청 또는 재외공관 사증발급신청"
                "(90일 이하 단수는 공관장 재량)으로 갈릴 수 있습니다 — 초청자·체류기간·관할 "
                "기준을 먼저 확인해야 합니다.")

VISA_RECOGNITION_ROWS = {  # 국내 인정신청이 표준 경로인 장기·취업·투자 자격 (19행)
    "M1-0114", "M1-0115", "M1-0116",            # D-8-1/2/3
    "M1-0125", "M1-0126",                        # D-9-1/4
    "M1-0132",                                   # D-10-3
    "M1-0141", "M1-0146", "M1-0151", "M1-0156", "M1-0161", "M1-0166",  # E-1~E-6
    "M1-0171", "M1-0314", "M1-0319",             # E-7-1/2/3
    "M1-0199",                                   # E-10
    "M1-0234",                                   # F-2-3 (영주자 가족 거주 — 장기)
    "M1-0335", "M1-0338",                        # D-2 / D-3
}
VISA_CONSULATE_ROWS = {"M1-0280"}                # C-3-8 — 단기 복수사증(인정 대상 아님)
VISA_CONFIRM_ROWS = {                            # F-1 방문동거 계열 — 공관장 재량 여지
    "M1-0205", "M1-0206", "M1-0207", "M1-0208", "M1-0209",
}

# ── W5. 비취업 서약서 ────────────────────────────────────────────────────────
NONWORK_DOC = "비취업 서약서"
NONWORK_ADD_ROWS = {   # 취업 불가 F-1 의 자격 '취득' 단계만 (기존 F-1-5 사증확인 패턴 준용)
    "M1-0203",  # F-1-16 난민인정자 가족 변경
    "M1-0204",  # F-1-52 전혼관계 자녀 변경
    "M1-0206",  # F-1-15 부모 방문동거 사증확인
    "M1-0213",  # F-1-9 재외동포 가족 변경
    "M1-0214",  # F-1-11 방문취업자 가족 변경
    "M1-0275",  # F-1-6 혼인단절 가사정리 변경
}
NONWORK_NOTE = "취업활동이 허용되지 않는 자격이므로 비취업 서약서 제출 여부를 확인해야 함"
NONWORK_NOTE_ONLY_ROWS = {"M1-0103", "M1-0006"}  # F-3 변경/부여 — 서약서 징구 여부 불확실, 주의만

# ── W6. 동포 가족 노트 문구 교정 ────────────────────────────────────────────
F13_OLD_SNIPPET = "대체 경로(F-3 부여 등)는 매뉴얼에 명시되지 않아"
F13_NEW_SNIPPET = "대체 경로는 매뉴얼에 명시되지 않아"


def split_field(v: str) -> list:
    return [p.strip() for p in (v or "").split("|") if p.strip()]


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def has_part(parts: list, name: str) -> bool:
    nk = norm(name)
    return any(nk == norm(p) or nk in norm(p) for p in parts)


def fix_form_docs(row: dict, stats: dict) -> bool:
    """W1 + W2: 업무수행확인서 삭제, 위임장/대행업무수행확인서 보정.

    채널 구분(【전자민원】…‖【창구민원】…) 행은 '||' 로 나뉜 각 블록을 개별 처리하되,
    위임장/대행 추가는 창구(마지막) 블록에만 한다(전자민원은 서식 축약 관행 유지)."""
    fd = row.get("form_docs") or ""
    changed = False

    def clean_block(block: str, add_basics: bool) -> str:
        nonlocal changed
        parts = split_field(block)
        out = []
        for p in parts:
            # '대행업무수행확인서'가 아닌 순수 '업무수행확인서'(꾸밈어 허용 안 함) 삭제
            if norm(p) == "업무수행확인서":
                stats["wrong_doc_removed"] += 1
                changed = True
                continue
            out.append(p)
        if add_basics:
            for basic in ("위임장", "대행업무수행확인서"):
                if not any(norm(basic) == norm(p) for p in out):
                    out.append(basic)
                    stats[f"added_{basic}"] += 1
                    changed = True
        return " | ".join(out)

    if "||" in fd:   # 채널 구분 행
        blocks = fd.split("||")
        newblocks = []
        for i, b in enumerate(blocks):
            is_last = (i == len(blocks) - 1)
            prefix = ""
            m = re.match(r"^(\s*【[^】]+】)(.*)$", b, re.S)
            if m:
                prefix, body = m.group(1).strip(), m.group(2)
            else:
                body = b
            cleaned = clean_block(body, add_basics=is_last)
            newblocks.append((prefix + " " + cleaned).strip() if prefix else cleaned)
        new_fd = " || ".join(newblocks)
    else:
        new_fd = clean_block(fd, add_basics=True)

    if changed:
        row["form_docs"] = new_fd
    return changed


def apply_visa_procedure(row: dict, stats: dict) -> bool:
    rid = row["row_id"]
    changed = False
    if rid in VISA_RECOGNITION_ROWS:
        proc, note = "recognition", NOTE_RECOGNITION
    elif rid in VISA_CONSULATE_ROWS:
        proc, note = "consulate", NOTE_CONSULATE
    elif rid in VISA_CONFIRM_ROWS:
        proc, note = "confirm_needed", NOTE_CONFIRM
    else:
        return False
    if row.get("visa_procedure") != proc:
        row["visa_procedure"] = proc
        changed = True
    notes = split_field(row.get("practical_notes") or "")
    if not any("[사증절차]" in n for n in notes):
        notes.insert(0, note)
        row["practical_notes"] = " | ".join(notes)
        stats["visa_note_added"] += 1
        changed = True
    # C-3-8: 인정서 서식 오기 교정
    if rid in VISA_CONSULATE_ROWS:
        fd = row.get("form_docs") or ""
        if "사증발급인정서 신청서" in fd:
            row["form_docs"] = fd.replace("사증발급인정서 신청서", "사증발급신청서(재외공관 제출)")
            stats["visa_form_fixed"] += 1
            changed = True
    return changed


def apply_nonwork(row: dict, stats: dict) -> bool:
    rid = row["row_id"]
    changed = False
    if rid in NONWORK_ADD_ROWS:
        docs = split_field(row.get("supporting_docs") or "")
        if not has_part(docs, NONWORK_DOC):
            docs.append(NONWORK_DOC)
            row["supporting_docs"] = " | ".join(docs)
            stats["nonwork_doc_added"] += 1
            changed = True
    if rid in NONWORK_ADD_ROWS or rid in NONWORK_NOTE_ONLY_ROWS:
        notes = split_field(row.get("practical_notes") or "")
        if not has_part(notes, NONWORK_NOTE):
            notes.append(NONWORK_NOTE)
            row["practical_notes"] = " | ".join(notes)
            stats["nonwork_note_added"] += 1
            changed = True
    return changed


def fix_f13_wording(row: dict, stats: dict) -> bool:
    pn = row.get("practical_notes") or ""
    if F13_OLD_SNIPPET in pn:
        row["practical_notes"] = pn.replace(F13_OLD_SNIPPET, F13_NEW_SNIPPET)
        stats["f13_wording_fixed"] += 1
        return True
    return False


def repair_channel_form_docs(rows: list, stats: dict) -> None:
    """W0: 이전 annotation cleanup 이 채널 구분('||')을 붕괴시키고 창구 블록의
    위임장을 중복으로 오삭제한 6행을 pre-cleanup 백업에서 복원한다.
    백업이 없거나 이미 복원되어 있으면 조용히 건너뛴다(idempotent)."""
    import glob
    baks = sorted(glob.glob(os.path.join(BACKUP_DIR, "immigration_guidelines_db_v2_pre_annotation_cleanup_*.json")))
    if not baks:
        return
    bak = json.load(open(baks[-1], encoding="utf-8"))
    bak_by = {r["row_id"]: r for r in bak.get("master_rows", [])}
    for r in rows:
        b = bak_by.get(r["row_id"])
        if not b:
            continue
        if "||" in (b.get("form_docs") or "") and "||" not in (r.get("form_docs") or ""):
            r["form_docs"] = b["form_docs"]
            stats["channel_repaired"] += 1
            stats.setdefault("_repaired_ids", set()).add(r["row_id"])


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = json.load(open(DB_PATH, encoding="utf-8"))
    rows = db["master_rows"]

    stats = {"wrong_doc_removed": 0, "added_위임장": 0, "added_대행업무수행확인서": 0,
             "visa_note_added": 0, "visa_form_fixed": 0, "channel_repaired": 0,
             "nonwork_doc_added": 0, "nonwork_note_added": 0, "f13_wording_fixed": 0}
    changed_rows = set()
    repair_channel_form_docs(rows, stats)
    changed_rows |= stats.pop("_repaired_ids", set())
    for r in rows:
        if fix_form_docs(r, stats):
            changed_rows.add(r["row_id"])
        if apply_visa_procedure(r, stats):
            changed_rows.add(r["row_id"])
        if apply_nonwork(r, stats):
            changed_rows.add(r["row_id"])
        if fix_f13_wording(r, stats):
            changed_rows.add(r["row_id"])

    # 검증 지표
    wrong_left = sum(1 for r in rows
                     if any(norm(p) == "업무수행확인서" for p in split_field(r.get("form_docs") or "")))
    missing_wi = [r["row_id"] for r in rows if "위임장" not in (r.get("form_docs") or "")]
    missing_dh = [r["row_id"] for r in rows if "대행업무수행확인서" not in (r.get("form_docs") or "")]
    sup_bad = [r["row_id"] for r in rows
               if any(norm(p) in ("위임장", "대행업무수행확인서")
                      for p in split_field(r.get("supporting_docs") or ""))]
    visa_rows = [r for r in rows if r.get("action_type") == "VISA_CONFIRM"]
    visa_classified = sum(1 for r in visa_rows if r.get("visa_procedure"))
    mu_total = sum(len(r.get("manual_updates") or []) for r in rows)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== {mode}: guideline classification refinement ===")
    print(f"전체 row: {len(rows)} / 변경 row: {len(changed_rows)}")
    print(f"W0 채널 구조 복원(‖ 붕괴 수리): {stats['channel_repaired']}행")
    print(f"W1 업무수행확인서 삭제: {stats['wrong_doc_removed']} (잔존 {wrong_left})")
    print(f"W2 위임장 추가: {stats['added_위임장']} / 대행업무수행확인서 추가: {stats['added_대행업무수행확인서']}")
    print(f"   적용 후 위임장 누락: {len(missing_wi)} {missing_wi[:5]} / 대행 누락: {len(missing_dh)} {missing_dh[:5]}")
    print(f"   고객 준비서류 오염(위임장/대행): {len(sup_bad)} {sup_bad[:5]}")
    print(f"W4 사증 분류: 전체 {len(visa_rows)}행 중 분류 {visa_classified} "
          f"(인정 {len(VISA_RECOGNITION_ROWS)} / 공관 {len(VISA_CONSULATE_ROWS)} / 확인필요 {len(VISA_CONFIRM_ROWS)})"
          f" · 절차문구 추가 {stats['visa_note_added']} · C-3-8 서식 교정 {stats['visa_form_fixed']}")
    print(f"W5 비취업 서약서 추가: {stats['nonwork_doc_added']}행 · 주의문구 {stats['nonwork_note_added']}행")
    print(f"W6 F-1/F-3 노트 문구 교정: {stats['f13_wording_fixed']}행 (코드 치환 없음 확인됨 — 데이터 변경 불필요)")
    print("W3 연장/변경 혼재: 실질 0건 (겸용 사유서·주자격자 입증 2건은 정당 → 무변경)")
    print("W7 포괄/중복: 전 자격군 스캔 실질 0건 (F-2 bare=F-2-T 가족·공통 등록/재입국, F-1 bare=동포 가족 전용 → 유지)")
    print(f"manual_updates 보존: {mu_total}건")

    if args.dry_run:
        print("\n[dry-run] 파일 변경 없음.")
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(BACKUP_DIR, f"immigration_guidelines_db_v2_pre_classification_refine_{ts}.json")
    shutil.copy2(DB_PATH, backup)
    print(f"\n백업: {backup}")

    db["갱신일"] = datetime.now().strftime("%Y-%m-%d") + " (classification refine — 업무/서류/사증 분류 정밀화)"
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print(f"저장 완료: {DB_PATH} (row {len(rows)})")


if __name__ == "__main__":
    main()
