# -*- coding: utf-8 -*-
"""실무지침(immigration_guidelines_db_v2.json) 검토용·감사용 문구 정리.

배경: manual_update_260617_260623_v1 일괄 반영 시 패키지 요약·확인필요 상세·
[260617/23 신규] 태그 등 **분석/감사용 문구가 업무 화면용 필드**(practical_notes,
supporting_docs, exceptions_summary)에 그대로 주입되어, F-4 연장 화면에
자격변경·거소신고용 서류와 고시대조 장문이 노출되는 오염이 발생했다.

이 스크립트는 최신화 자체는 유지하면서:
  1) 업무 화면용 필드에서 감사 불릿([확인 후 반영]/[즉시 반영]/[보류 가능]/
     [확인 필요]/[고시 원문 대조 필요]/[매뉴얼 내부 표기 불일치 가능]/
     [260617/23 매뉴얼 반영] 포함 불릿)을 제거하고,
  2) supporting_docs/form_docs 의 [260617 신규]/[260623 신규] 태그 항목
     (대부분 서류가 아닌 변경 요지 문장 + 업무유형 무관 fan-out)을 제거한 뒤,
  3) 해당 row 의 업무유형에 실제로 맞는 **최종 실무 문장/실제 서류만** 손수
     선별한 매핑(NOTES_ADD / DOCS_ADD)으로 추가한다.
  4) manual_updates 감사기록은 그대로 보존한다(원문 근거는 여기에만).
  5) 명백히 시대착오가 된 구 안내 1건(H-2 '일반적 경로' 문구)만 제거한다.

idempotent: 제거는 결정적, 추가는 정규화 중복검사로 재실행 시 변화 없음.

사용법:
  python backend/scripts/clean_guideline_annotations.py --dry-run
  python backend/scripts/clean_guideline_annotations.py --apply
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

# 업무 화면용 필드에서 제거할 감사 불릿 판정 (H-2 안내문 ⚠/[중요]/[참고]/[2026… 는 유지)
AUDIT_BULLET_RE = re.compile(
    r"\[(확인 후 반영|즉시 반영|보류 가능|확인 필요|고시 원문 대조 필요)\]"
    r"|\[260617/23 매뉴얼 반영\]"
    r"|\[매뉴얼 내부 표기 불일치 가능\]"
    r"|\[운영 반영 후 추가 확인 필요\]"
)
DOC_TAG_RE = re.compile(r"\[2606(17|23) 신규\]|\[260617/23 신규\]")

# 명백히 시대착오가 된 구 안내 — H-2 신규 발급 중단('26.2.12.)과 직접 모순되는 문구만
OBSOLETE_BULLETS = {
    "M1-0276": ["C-3-8(단기방문)으로 입국한 후 국내에서 H-2로 변경하는 것이 일반적 경로"],
}

# ── 최종 실무 문장 (업무 화면용, 짧고 명확하게) ─────────────────────────────
F4_GOSI = ("F-4 취업활동 제한 고시가 '26.2.12.자로 전면 개정되어 건설·광업·하역 등 일부 "
           "단순노무 직종이 제한에서 제외됨 — 매뉴얼 내 고시번호 표기가 일부 불일치하므로 "
           "제한직종 판단 전 최신 고시 원문을 확인해야 함")
F4_CODE = ("('26.2.12. 개편) F-4 세부유형이 F-4-41·F-4-42 체계로 통합되고 구 세부유형표"
           "(F-4-13~99)·국가기술자격 경로는 폐지됨 — 기존 세부코드 소지자의 연장·변경 "
           "처리 기준은 관할 관서 확인 필요")
F4_CONDUCT = ("품행요건 제한 기산점이 형 집행종료·벌금(범칙금) 완납일 기준으로 변경되고, "
              "조기적응프로그램 이수가 의무화됨('26.2.12.)")
F4_TRANSL = ("해외 범죄경력증명서는 공증 번역본 대신 번역본+번역자 확인서+번역자 신분증 "
             "사본 제출로 갈음 가능(번역자 공인 요건 삭제)")
F4_REGION_EX = ("지역특화 취업 예외 요건('거소를 두거나 거소가 속한 광역시·도 내 취업')은 "
                "최신 고시 원문으로 문언을 확인한 후 적용할 것")
F1_BIRTH = ("국내출생 자녀에 대한 F-1 체류자격 부여 대상에서 H-2·F-4 동포가 제외됨('26 개편) — "
            "동포 자녀의 대체 경로(F-3 부여 등)는 매뉴얼에 명시되지 않아 관할 관서 확인 필요")
F1_25 = ("동포 미성년 자녀의 만 25세 미만 연장 특례 조항이 신판 매뉴얼에서 삭제됨 — 폐지인지 "
         "기재 생략인지 불명확하므로 연장 상담 시 관할 관서 확인 필요")
F27_NOTE = ("F-2-7 점수제 개정('26): 우수대학 가점은 최근 5개년 QS 500위 또는 THE 200위 중 "
            "하나 충족 시 인정, 사회봉사 가점은 누적 실적 기준으로 구체화·상향, 벌금 300만원 "
            "이상은 확정 후 3년 이내 불허로 명문화 — 점수 산정 전 개정 기준표 확인 필요")
E73_NOTE = ("조선업 3개 직종(용접·전기·도장) 완화 임금요건이 '26년 기준 2,588만원으로 갱신됨"
            "('24.10월 이후 신규 도입 인력 한정, 도입 3년차=입국일부터 만 3년) — 적용 시점은 "
            "최신 공지로 확인")
E74_NOTE = ("E-7-4 근속요건(1년/3년) 산정 시 근로자 귀책 없는 근무처 변경은 직전+현 근무처 "
            "근속 합산이 인정됨('26 개정)")
E74R_NOTE = "지역특화형 숙련기능인력(E-7-4R) 고용허용인원 특례에 농축어업이 추가됨('26 개정)"
F2R_CHANGE = ("지역특화형비자 개정('26.5.18. 시행): 소상공인 고용특례 신설(내국인 고용 0명이어도 "
              "F-2-R 1명 고용 허용, '27.12.31.까지 시범), 사업지역에 강원 태백·평창·양구·정선 추가")
F2R_EXTEND = ("F-2-R/F-4-R은 2년 경과 시 동일 광역 내 거주지 이전이 허용되고, 근로자 귀책 없는 "
              "이직 시 근무기간 합산이 인정됨('26.5.18. 개정)")
F4R_CHANGE = "F-4-R에서 일반 F-4로의 자격변경이 허용됨('26 개편)"
F419_NOTE = ("F-4-19 유형이 포함된 구 세부대상표는 '26.2.12. 개편으로 폐지됨 — 신규 신청은 "
             "통합 기준(F-4-41/42)으로 안내하고, 본 항목은 기존 소지자 참고용으로 활용")
F4_H2SITE = ("과거 H-2로 재직하던 사업장에서 계속 근무하려는 F-4 변경자에 대한 체류자격 외 "
             "활동허가 절차가 '26 매뉴얼에 신설·정비됨")
C38_NOTE = ("동포 체류자격 통합('26.2.12.)으로 방문취업(H-2) 연계 C-3-8 사증발급 절차·쿼터가 "
            "폐지됨 — 신규 동포는 재외동포(F-4) 사증으로 안내")
A1_NOTE = ("A-1 동반가족 인정 범위가 '26 매뉴얼에 명문화됨(배우자·미성년 자녀 등) — 가족 해당 "
           "여부 판단 시 최신 기준을 적용할 것")
A2_NOTE = ("A-2 동반가족 중 배우자는 파견국 법령상 배우자 기준으로 판단하며, 복수 배우자는 "
           "1명만 인정됨('26 개정)")
F5_DONGPO = ("동포 영주 생계유지능력 요건 완화('26): 사회통합프로그램 5단계 이수·국내 초중고 "
             "전과정 졸업·국내 학사 이상은 GNI 70%, 자원봉사 100시간 이상은 GNI 80% 인정")
F3_EXTRA = ("F-3 자격외활동 개편('26.3.30.~'27.3.29. 시범): 우수인재(D-2-3/4·E-1·E-3·E-4·E-5) "
            "성년 배우자는 포괄적 자격외활동(신고제) 허용, 단순노무 허용분야는 농·임·축산업만 "
            "존치(가사·육아·간병 삭제)")
F3_EXEMPT = ("E-7-T·E-7-S1·D-8 고액투자(50만불 이상) 등 우수인재 동반가족은 생계유지능력·"
             "주거지 입증서류가 면제됨('26 개정)")
F3_TRANSL = "번역자 확인서는 공인 번역 요건이 삭제되어 일반 번역자 확인서로 제출 가능('26 개정)"
F3_GRANT_DOC = "F-3 체류자격 부여 시 신원보증서가 제출서류에 추가됨('26 개정)"

# row_id → practical_notes 에 추가할 최종 실무 문장 (업무유형에 맞는 것만)
NOTES_ADD: dict = {
    # F-4 코어
    "M1-0261": [F4_CODE, F4_GOSI, F4_CONDUCT, F4_TRANSL],          # 변경
    "M1-0262": [F4_GOSI, F4_CODE],                                  # 연장
    "M1-0263": [F4_CONDUCT, F4_TRANSL, F4_CODE],                    # 거소신고
    "M1-0264": [F4_GOSI, F4_H2SITE],                                # 제한직업 계속근무 특례
    "M1-0084": [F4_GOSI, F4_REGION_EX],                             # 인구감소지역 자격외활동
    "M1-0007": [F419_NOTE, F4_CONDUCT],                             # F-4-19 변경
    "M1-0086": [F4R_CHANGE, F2R_CHANGE],                            # F-4-R 변경
    "M1-0088": [F2R_EXTEND],                                        # F-4-R 연장
    # F-2-R 지역특화
    "M1-0281": [F2R_CHANGE],                                        # F-2-R 변경
    "M1-0282": [F2R_EXTEND],                                        # F-2-R 연장
    # F-2-7 점수제 — 점수제 우수인재 본인(0242/0243)과 그 가족의 변경/연장(0254/0255)만.
    # K-STAR 계열(F-2-7S=0285/0286, F-2-71 K-STAR 가족=0090/0091/0092)과 국내출생
    # 자녀 부여(0256)는 점수제 개정과 무관하므로 제거만 하고 노트를 넣지 않는다.
    "M1-0242": [F27_NOTE], "M1-0243": [F27_NOTE],
    "M1-0254": [F27_NOTE], "M1-0255": [F27_NOTE],
    # F-1 동포 가족 (변경/연장 단계만)
    "M1-0213": [F1_BIRTH], "M1-0214": [F1_BIRTH],
    "M1-0215": [F1_25], "M1-0216": [F1_25],
    # E-7 계열
    "M1-0315": [E73_NOTE], "M1-0316": [E73_NOTE], "M1-0319": [E73_NOTE],
    "M1-0175": [E74_NOTE],
    "M1-0307": [E74R_NOTE],
    # A 계열 (재입국 제외)
    "M1-0004": [A1_NOTE],
    "M1-0297": [A2_NOTE], "M1-0298": [A2_NOTE], "M1-0299": [A2_NOTE],
    # C-3-8 동포방문 (사증확인)
    "M1-0280": [C38_NOTE],
    # F-5 동포 영주 — 이 DB 코드 체계에서 동포 영주는 F-5-10(F-4 2년 체류)과
    # F-5-14(H-2 제조업 4년)이다. 매뉴얼 델타의 'F-5-6'은 사증 매뉴얼상 동포 코드로,
    # 이 DB의 F-5-6(결혼이민자 영주)과 코드 의미가 달라 M1-0366에는 추가하지 않는다.
    "M1-0367": [F5_DONGPO, F4_TRANSL],
    "M1-0369": [F5_DONGPO, F4_TRANSL],
    # F-3 계열
    "M1-0006": [F3_GRANT_DOC, F3_EXEMPT, F3_TRANSL],               # 부여
    "M1-0085": [F3_EXTRA],                                          # 자격외활동
    "M1-0103": [F3_EXEMPT, F3_TRANSL],                              # 변경
    "M1-0104": [F3_EXEMPT],                                         # 연장
    "M1-0087": [F3_EXEMPT], "M1-0089": [F3_EXEMPT],
    "M1-0259": [F3_EXEMPT, F3_TRANSL], "M1-0260": [F3_EXEMPT],
    "M1-0283": [F3_EXEMPT, F3_TRANSL], "M1-0284": [F3_EXEMPT, F3_TRANSL],
}

# row_id → supporting_docs 에 추가할 실제 서류(조건부 표기 포함, 업무유형 맞는 것만)
DOCS_ADD: dict = {
    "M1-0262": [   # F-4 연장 — 고객이 실제 준비하는 서류만
        "한국어능력 입증서류 또는 면제자료",
        "취업 중인 경우: 근로계약서 또는 재직·소득 관련 입증자료",
        "사업자등록이 있는 경우: 사업자등록증",
        "단순노무 취업사실 확인이 필요한 경우: 건강보험 가입내역·소득금액증명원 등 공적서류(ICRM 확인 시 면제)",
    ],
    # F-4 변경(M1-0261): 동포입증·결핵·조기적응·한국어는 기존 서류 목록에 이미 있음 —
    # '26 개편으로 새로 명시된 해외 범죄경력증명서만 추가(번역 완화는 조건부 표기).
    "M1-0261": [
        "해외 범죄경력증명서(해당자 — 공증 번역본 대신 번역본+번역자 확인서+번역자 신분증 사본 가능)",
    ],
    # F-4 거소신고(M1-0263): 동포입증·무범죄증명은 기존 목록에 있음 — 조기적응 이수증만 추가
    # (의무화 '26.2.12.). 번역 완화는 실무 주의사항으로 안내.
    "M1-0263": [
        "조기적응프로그램 이수증",
    ],
    # F-4-19 변경(M1-0007): 결핵진단서는 기존 목록에 있음 — 조기적응 이수증만 추가
    "M1-0007": [
        "조기적응프로그램 이수증",
    ],
    # D-4-5(M1-0372): 태그 제거로 함께 삭제된 실제 서류(결핵진단서) 복원
    "M1-0372": [
        "결핵진단서",
    ],
}
FORM_DOCS_ADD: dict = {
    "M1-0006": ["신원보증서"],   # F-3 부여 — '26 개정으로 서식 추가
}

# 신규 행(일괄 반영 시 삽입) 필드 전체 교체 — 감사 문구 없는 최종 실무 문장으로
NEW_ROW_REWRITE: dict = {
    "M1-0370": {   # F-1-4
        "practical_notes": " | ".join([
            "'26.1.7. 신설(체류관리과-139): 대한민국 국적의 혼외 미성년 자녀를 양육하는 "
            "외국인에 대한 F-1-4 체류자격 변경허가·자격외활동허가(단순노무 취업 허용) 업무",
            "세부 심사기준은 지침 원문(체류관리과-139) 확인 후 안내할 것",
        ]),
        "exceptions_summary": "체류관리과-139(2026.1.7.) 신설 지침 — 세부 심사기준은 지침 원문 확인 필요",
    },
    "M1-0371": {   # F-1-51
        "practical_notes": " | ".join([
            "국제입양 아동에 대한 F-1-51 체류자격 변경허가가 '26 매뉴얼에 신설됨",
            "세부 서류·심사기준은 매뉴얼 원문 확인 후 안내할 것",
        ]),
        "exceptions_summary": "신설 지침 — 세부 서류·심사기준은 매뉴얼 원문 확인 필요",
    },
    "M1-0372": {   # D-4-5
        "practical_notes": " | ".join([
            "운영기관이 aT에서 한식진흥원(수라학교) 한정으로 변경되고 조리경력 요건은 폐지됨"
            "('26 개편) — 사증은 체재비 USD 10,000 입증, 6개월 이하 단수 발급",
            "타 체류자격에서 D-4-5로의 자격변경은 불가(사증발급인정서로 재입국 필요)하며, "
            "체류기간 연장은 입국일부터 최대 2년 한도",
            "연수 중 결핵 진단 후 치료를 회피하면 연장 불허·출국명령 대상이므로 결핵진단서 "
            "제출·치료 계획을 사전 안내할 것",
            "체류기간·단복수 기준은 하이코리아 D-4-5 최신 안내로 확인 권장",
        ]),
        "exceptions_summary": "타 체류자격에서 D-4-5로의 자격변경 불가(사증발급인정서로 재입국 필요)",
    },
}


def norm(s: str) -> str:
    return re.sub(r"[\s ]+", "", s or "")


def split_field(v: str) -> list:
    return [p.strip() for p in (v or "").split("|") if p.strip()]


def dedupe_keep_order(items: list) -> list:
    seen, out = set(), []
    for it in items:
        k = norm(it)
        if k and k not in seen:
            seen.add(k)
            out.append(it)
    return out


def contains_norm(items: list, candidate: str) -> bool:
    ck = norm(candidate)
    return any(ck == norm(it) or ck in norm(it) for it in items)


def clean_row(row: dict, stats: dict) -> bool:
    """내용(파트 단위) 변화가 있을 때만 필드를 재작성한다 — 오염 없는 행의
    순수 공백 정규화만으로 diff 가 생기지 않게(변경 범위 최소화)."""
    rid = row["row_id"]
    changed = False

    # 1) practical_notes — 감사 불릿 제거 + 시대착오 불릿 제거 + 중복 제거
    pn = split_field(row.get("practical_notes") or "")
    kept = []
    for b in pn:
        if AUDIT_BULLET_RE.search(b):
            stats["audit_bullets_removed"] += 1
            continue
        if any(norm(ob) in norm(b) for ob in OBSOLETE_BULLETS.get(rid, [])):
            stats["obsolete_removed"] += 1
            continue
        kept.append(b)
    before_dedupe = len(kept)
    kept = dedupe_keep_order(kept)
    stats["note_dups_removed"] += before_dedupe - len(kept)

    # 2) supporting_docs / form_docs — 태그 항목 제거 + 중복 제거 (+ 실제 서류 추가)
    for field in ("supporting_docs", "form_docs"):
        docs = split_field(row.get(field) or "")
        newdocs = []
        removed_here = 0
        for d in docs:
            if DOC_TAG_RE.search(d):
                removed_here += 1
                continue
            newdocs.append(DOC_TAG_RE.sub("", d).strip())
        b = len(newdocs)
        newdocs = dedupe_keep_order(newdocs)
        dups_here = b - len(newdocs)
        adds = DOCS_ADD.get(rid, []) if field == "supporting_docs" else FORM_DOCS_ADD.get(rid, [])
        added_here = 0
        for add in adds:
            if not contains_norm(newdocs, add):
                newdocs.append(add)
                added_here += 1
        # 내용 변화(제거/중복/추가)가 있을 때만 재작성 — 공백만 다른 행은 원본 유지
        if removed_here or dups_here or added_here:
            stats["tagged_docs_removed"] += removed_here
            stats["doc_dups_removed"] += dups_here
            stats["docs_added"] += added_here
            row[field] = " | ".join(newdocs)
            changed = True

    # 3) 최종 실무 문장 추가 (중복 방지)
    notes_added_here = 0
    for add in NOTES_ADD.get(rid, []):
        if not contains_norm(kept, add):
            kept.append(add)
            notes_added_here += 1
    # 내용 변화가 있을 때만 재작성
    if [norm(x) for x in kept] != [norm(x) for x in pn]:
        stats["notes_added"] += notes_added_here
        row["practical_notes"] = " | ".join(kept)
        changed = True

    # 4) 신규 행 재작성 (notes/exceptions)
    if rid in NEW_ROW_REWRITE:
        for f, v in NEW_ROW_REWRITE[rid].items():
            if row.get(f) != v:
                row[f] = v
                changed = True
                stats["new_row_rewritten"].add(rid)

    # 5) exceptions_summary 잔여 태그 정리 ("[260617/23 반영]" 등)
    ex = row.get("exceptions_summary") or ""
    ex2 = re.sub(r"\s*\[260617/23 반영\]", "", ex)
    ex2 = DOC_TAG_RE.sub("", ex2).strip()
    if ex2 != ex:
        row["exceptions_summary"] = ex2
        changed = True

    return changed


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = json.load(open(DB_PATH, encoding="utf-8"))
    rows = db["master_rows"]

    stats = {"audit_bullets_removed": 0, "tagged_docs_removed": 0, "docs_added": 0,
             "notes_added": 0, "note_dups_removed": 0, "doc_dups_removed": 0,
             "obsolete_removed": 0, "new_row_rewritten": set()}
    changed_rows = []
    empty_docs_rows = []
    for r in rows:
        if clean_row(r, stats):
            changed_rows.append(r["row_id"])
        if not (r.get("supporting_docs") or "").strip() and not (r.get("form_docs") or "").strip():
            empty_docs_rows.append(r["row_id"])

    mu_total = sum(len(r.get("manual_updates") or []) for r in rows)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== {mode}: guideline annotation cleanup ===")
    print(f"전체 row: {len(rows)} / 변경 row: {len(changed_rows)}")
    print(f"감사 불릿 제거: {stats['audit_bullets_removed']}")
    print(f"태그 서류 항목 제거: {stats['tagged_docs_removed']}")
    print(f"불릿 중복 제거: {stats['note_dups_removed']} / 서류 중복 제거: {stats['doc_dups_removed']}")
    print(f"시대착오 문구 제거: {stats['obsolete_removed']}")
    print(f"최종 실무 문장 추가: {stats['notes_added']} / 실제 서류 추가: {stats['docs_added']}")
    print(f"신규 행 재작성: {sorted(stats['new_row_rewritten'])}")
    print(f"manual_updates 총 기록(보존): {mu_total}")
    if empty_docs_rows:
        print(f"⚠ 서류 필드가 모두 빈 row: {empty_docs_rows}")
    else:
        print("서류 필드 빈 row: 없음")

    if args.dry_run:
        print("\n[dry-run] 파일 변경 없음.")
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(BACKUP_DIR, f"immigration_guidelines_db_v2_pre_annotation_cleanup_{ts}.json")
    shutil.copy2(DB_PATH, backup)
    print(f"\n백업: {backup}")

    db["갱신일"] = datetime.now().strftime("%Y-%m-%d") + " (annotation cleanup — 업무화면 문구 정리)"
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print(f"저장 완료: {DB_PATH} (row {len(rows)})")


if __name__ == "__main__":
    main()
