# -*- coding: utf-8 -*-
"""최신 매뉴얼(260617 사증/260623 체류) 분석 결과를 실무지침 DB(JSON)에 반영.

Source of truth 확인 결과: 실무지침은 backend/data/immigration_guidelines_db_v2.json
(PostgreSQL 테이블 아님 — 프로세스 기동 시 1회 로드되는 정적 JSON). 따라서 본
스크립트는 이 JSON 파일을 직접 갱신한다.

입력: analysis/manual_update_260617_260623/manual_update_review_bundle.json
      (bundle_format=2, 9개 패키지·87개 항목 — 03/04/06 문서와 동일 근거)

동작 원칙(비파괴):
  - 기존 row_id/detailed_code/status/schema 는 그대로 둔다.
  - form_docs/supporting_docs 는 덮어쓰지 않고, 실제 서류변경이 확인된 항목만
    "[260617/23 추가]" 태그를 붙여 뒤에 추가한다(중복 방지).
  - practical_notes(기존 "|" 구분 불릿 목록)에 패키지 요약 또는 확인필요 개별
    문구를 새 불릿로 append 한다(기존 문구 삭제 없음).
  - 신규 필드 `manual_updates`(리스트, 행별 감사기록: manual_version/source_file/
    source_pages/section/confidence/review_note/change_kind/applied_at)를
    추가한다 — 기존 코드는 dict.get() 기반이라 신규 키를 무시하므로 안전.
  - H-2 는 삭제하지 않고 상태는 active 유지, practical_notes 최상단에 강한
    주의 문구를 prepend(신규 발급/변경 업무) 하거나 맥락 문구를 append(기존
    체류자 대상 업무)한다.
  - 신규 업무(F-1-4/F-1-51)는 새 row_id로 INSERT(기존 최대 번호 다음부터).
  - 동일 batch_id 재실행 시 이미 반영된 항목은 건너뛴다(idempotent).

사용법:
  python backend/scripts/apply_manual_update_260617_260623.py --dry-run
  python backend/scripts/apply_manual_update_260617_260623.py --apply
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(_ROOT, "backend", "data", "immigration_guidelines_db_v2.json")
BUNDLE_PATH = os.path.join(
    _ROOT, "analysis", "manual_update_260617_260623", "manual_update_review_bundle.json"
)
BACKUP_DIR = os.path.join(_ROOT, "backend", "data", "backups")

BATCH_ID = "manual_update_260617_260623_v1"
NEW_VERSION = "2.1"

ACTION_LABEL = {
    "quick_apply": "즉시 반영",
    "confirm_then_apply": "확인 후 반영",
    "needs_confirmation": "확인 필요",
    "hold": "보류 가능",
}

FAMILY_RE = re.compile(r"^([A-H]-\d{1,2})")
CODE_TOKEN_RE = re.compile(r"^[A-H]-")
CONFIRM_FAMILY_CAP = 15  # 확인필요 항목 — family 로의 무분별한 확산 방지
PACKAGE_FAMILY_CAP = 25  # 일반 패키지 항목 — 동질적인 중간 규모 family(예: E-9 20행)는 허용


def family_of(detailed_code: str) -> str:
    m = FAMILY_RE.match((detailed_code or "").strip())
    return m.group(1) if m else ""


def expand_codes(status_code: str) -> list:
    """'F-5-6/7/14' → ['F-5-6','F-5-7','F-5-14'], 'H-2/F-4' → ['H-2','F-4'].
    '동포 공통' 등 코드가 아닌 토큰은 제거."""
    tokens = [t.strip() for t in (status_code or "").split("/") if t.strip()]
    out, prefix = [], None
    for t in tokens:
        if CODE_TOKEN_RE.match(t):
            out.append(t)
            parts = t.split("-")
            prefix = "-".join(parts[:-1]) if len(parts) >= 3 else None
        elif re.match(r"^\d+[A-Z]?$", t) and prefix:
            out.append(f"{prefix}-{t}")
    return out


# 손수 확정한 매칭 override — 자동 규칙(코드 접두/family)이 부정확하거나
# 과도하게 넓어지는 소수의 고위험 항목만 명시 지정한다(키워드 유사도 같은
# 휴리스틱은 오탐 위험이 커서 채택하지 않음 — 근거 없는 매칭보다 "미매칭"이 안전).
# 값이 빈 리스트면 "이 항목은 어떤 기존 행에도 강제로 끼워 넣지 않는다"는 의미.
DELTA_ID_ROW_OVERRIDE = {
    # 국내출생 동포 자녀 F-1 부여대상 축소 — F-1 family(31행) 전체가 아니라
    # 실제 연관된 재외동포가족(F-1-9)·방문취업자가족(F-1-11) 행에만 한정.
    "SF-D3": ["M1-0213", "M1-0214", "M1-0215", "M1-0216", "M1-0217", "M1-0218"],
    "V-U3":  ["M1-0213", "M1-0214", "M1-0215", "M1-0216", "M1-0217", "M1-0218"],
    "SF-U1": ["M1-0213", "M1-0214", "M1-0215", "M1-0216", "M1-0217", "M1-0218"],
    # F-4-51/F-1-51 국제입양, F-2-8 등 신규코드/무대응 항목은 family 강제매칭 대신
    # 아래에서 unmatched 로 보고하고, 필요한 것은 별도 INSERT 로 처리한다.
    "V-B4": [],
}


def resolve_rows_for_code(code: str, rows: list, cap: int) -> list:
    """코드 1개 → 매칭 행.

    - 세부코드(2단 이상, 예: E-7-3): exact/prefix 정밀 매칭만 시도한다.
      매칭 0건이면 family 로 내리지 **않는다**(형제 세부코드로 오분류 방지 —
      예: D-4-5 미존재 시 D-4-1/D-4-2 로 새는 문제를 차단).
    - 가족단위(1단, 예: F-4/H-2/F-1): family 전체 매칭하되, 그 크기가 cap 을
      넘으면(F-1=31/F-2=39/E-7=47 처럼 이질적 하위업무가 섞인 대형 family)
      **적용하지 않는다**(휴리스틱 키워드 매칭은 오탐 위험이 커 채택하지 않음).
    """
    dash_n = code.count("-")
    if dash_n >= 2:
        return [r for r in rows if (r.get("detailed_code") or "") == code
               or (r.get("detailed_code") or "").startswith(code)]
    fam_rows = [r for r in rows if family_of(r.get("detailed_code", "")) == code]
    return fam_rows if len(fam_rows) <= cap else []


def manual_version_of(item: dict) -> str:
    return "260617" if item.get("manual") == "visa" else "260623"


def pages_label(pages: list) -> str:
    if not pages:
        return "-"
    if len(pages) == 1:
        return f"p.{pages[0]}"
    return f"p.{pages[0]}~{pages[-1]}" if len(pages) > 3 else "p." + ",".join(str(p) for p in pages)


def already_applied(row: dict, batch_id: str) -> bool:
    return any(u.get("batch_id") == batch_id for u in row.get("manual_updates", []))


def append_note(row: dict, text: str, prepend: bool = False) -> None:
    """practical_notes( '|' 구분 문자열)에 새 불릿 추가. 중복 방지."""
    cur = str(row.get("practical_notes") or "")
    bullets = [b.strip() for b in cur.split("|") if b.strip()]
    if text in bullets:
        return
    if prepend:
        bullets.insert(0, text)
    else:
        bullets.append(text)
    row["practical_notes"] = " | ".join(bullets)


def append_docs(row: dict, field: str, new_docs: list, tag: str) -> None:
    if not new_docs:
        return
    cur = str(row.get(field) or "")
    existing = {d.strip() for d in cur.split("|") if d.strip()}
    additions = [f"{d}{tag}" for d in new_docs if d and d not in existing]
    if not additions:
        return
    parts = [p for p in cur.split("|") if p.strip()] + additions
    row[field] = " | ".join(parts)


def add_audit(row: dict, item: dict, note_kind: str, review_note: str = "") -> None:
    row.setdefault("manual_updates", []).append({
        "batch_id": BATCH_ID,
        "delta_id": item.get("delta_id", ""),
        "manual_version": manual_version_of(item),
        "source_file": item.get("source_file", ""),
        "source_pages": item.get("source_pages", []),
        "section": item.get("section", ""),
        "confidence": item.get("confidence", ""),
        "change_kind": item.get("change_type", ""),
        "note_kind": note_kind,   # package_summary | confirm_item | h2_notice | insert
        "review_note": review_note,
        "applied_at": datetime.now().isoformat(timespec="seconds"),
    })


# ── H-2 전용 처리 (삭제 금지, active 유지 + 주의 문구 전환) ──────────────────
H2_STRONG_NOTICE_ROWS = {
    "M1-0276": "⚠ [중요][2026.2.12. 시행] 타 체류자격 → H-2(방문취업) 자격변경은 전면 불허됩니다. "
               "신규 H-2 발급 관련 신규 초청·신규 신청 안내를 중단하고, 재외동포(F-4) 경로로 안내하세요. "
               "(체류 매뉴얼 p.526)",
    "M1-0278": "⚠ [중요][2026.2.12. 시행] H-2(방문취업) 사증 신규 발급이 전면 중단되어 신규 입국·신규 등록 대상이 "
               "더 이상 발생하지 않습니다. 기 발급된 사증 소지자의 등록에 한해 적용 가능 여부를 확인하세요. "
               "(체류 매뉴얼 p.520~523)",
}
H2_CONTEXT_NOTICE_ROWS = {
    "M1-0277": "[2026.2.12.~] H-2 신규 발급은 중단되었으나 기존 H-2 체류자의 체류기간 연장 업무는 유지됩니다. "
               "단, '취업 외 목적' 특례연장(1회 1년) 제도는 폐지되었습니다. (체류 매뉴얼 p.526)",
    "M1-0279": "[2026.2.12.~] H-2 신규 발급은 중단되었으나 기존 H-2 체류자의 재입국허가 업무는 유지됩니다. "
               "(체류 매뉴얼 p.520~523)",
    "M1-0214": "[참고] H-2(방문취업) 신규 발급 중단('26.2.12.~)으로 신규 대상자는 발생하지 않으나, "
               "기존 H-2 체류자 가족의 방문동거 업무는 유지됩니다.",
    "M1-0216": "[참고] H-2 신규 발급 중단('26.2.12.~) — 기존 H-2 체류자 가족의 연장 업무는 유지됩니다.",
    "M1-0218": "[참고] H-2 신규 발급 중단('26.2.12.~) — 기존 H-2 체류자 가족의 재입국 업무는 유지됩니다.",
    "M1-0175": "[참고] 방문취업(H-2) 경유 경로는 신규 발급 중단('26.2.12.~)으로 기존 H-2 체류자에 한해 유효합니다.",
    "M1-0250": "[참고] 방문취업(H-2) 경유 경로는 신규 발급 중단('26.2.12.~)으로 기존 H-2 체류자에 한해 유효합니다.",
    "M1-0261": "⚠ [중요][2026.2.12.~] 방문취업(H-2) 사증 신규 발급이 중단되어, 신규 동포는 재외동포(F-4)로 "
               "직접 신청해야 합니다(H-2 경유 불필요/불가). 세부유형 코드 체계도 F-4-41/42로 개편되었습니다. "
               "구 F-4-13~99 세부대상표는 폐지되었습니다. (체류 매뉴얼 p.520~529)",
    "M1-0307": "[참고] 방문취업(H-2) 경유 경로는 신규 발급 중단('26.2.12.~)으로 기존 체류자에 한해 유효합니다.",
    "M1-0369": "[참고] 본 영주 변경 경로(H-2 제조업 4년 이상)는 기존 H-2 체류자에 한해 유효하며, "
               "H-2 신규 발급은 '26.2.12.부터 중단되었습니다.",
}


def apply_h2_notices(rows_by_id: dict) -> int:
    n = 0
    for rid, text in H2_STRONG_NOTICE_ROWS.items():
        row = rows_by_id.get(rid)
        if row is None:
            continue
        before = row.get("practical_notes", "")
        append_note(row, text, prepend=True)
        if row.get("practical_notes") != before:
            n += 1
        add_audit(row, {"delta_id": "H2-STRONG", "manual": "stay",
                        "source_file": "260623 체류민원 자격별 안내 매뉴얼.pdf",
                        "source_pages": [520, 526], "section": "H-2 방문취업",
                        "confidence": "high", "change_type": "삭제·약화"},
                 "h2_notice", "H-2 신규 발급/변경 전면 중단 — 삭제하지 않고 안내문으로 전환")
    for rid, text in H2_CONTEXT_NOTICE_ROWS.items():
        row = rows_by_id.get(rid)
        if row is None:
            continue
        before = row.get("practical_notes", "")
        append_note(row, text, prepend=False)
        if row.get("practical_notes") != before:
            n += 1
        add_audit(row, {"delta_id": "H2-CONTEXT", "manual": "stay",
                        "source_file": "260623 체류민원 자격별 안내 매뉴얼.pdf",
                        "source_pages": [520, 526], "section": "H-2 방문취업",
                        "confidence": "high", "change_type": "변경"},
                 "h2_notice", "")
    return n


# ── 신규 업무 삽입 (F-1-4 / F-1-51) ──────────────────────────────────────────
def build_new_rows(next_num: int) -> list:
    base = {
        "domain": "체류민원", "quickdoc_category": None, "quickdoc_minwon": None,
        "quickdoc_kind": None, "quickdoc_detail": None, "search_keys": [], "status": "active",
    }
    rows = [
        {
            **copy.deepcopy(base),
            "row_id": f"M1-{next_num:04d}",
            "major_action_std": "체류자격 변경허가", "action_type": "CHANGE",
            "business_name": "혼외 미성년 자녀 양육자", "detailed_code": "F-1-4",
            "overview_short": "대한민국 국적의 혼외 미성년 자녀를 양육하는 외국인의 방문동거(F-1-4) "
                             "체류자격 변경허가 및 자격외활동허가(단순노무 취업 허용).",
            "form_docs": "통합신청서 | 위임장", "supporting_docs": "여권 | 외국인등록증 | 자녀 가족관계증명서 | 양육사실 입증서류",
            "exceptions_summary": "체류관리과-139(2026.1.7.) 지침 신설 — [확인 필요] 세부 심사기준 원문 대조 권장",
            "fee_rule": "일반 수수료 기준 (매뉴얼 확인 필요)",
            "basis_file": "260623 체류민원 자격별 안내 매뉴얼.pdf", "basis_section": "F-1-4 신설",
            "practical_notes": "[260617/23 매뉴얼 반영] '26.1.7. 신설 — 대한민국 국적 혼외 미성년 자녀 양육자에 대한 "
                              "F-1-4 변경·자격외활동(단순노무 허용) 신설 (체류 매뉴얼 p.338~348) | "
                              "[확인 필요] 세부 심사기준은 매뉴얼 발췌 수준으로만 확인됨 — 원문(체류관리과-139) 대조 권장",
            "manual_ref": [{"manual": "체류민원", "page_from": 338, "page_to": 348,
                           "match_text": "F-1-4 혼외 미성년 자녀 양육자", "score": 0,
                           "match_kind": "manual_insert_260623", "match_type": "manual_override"}],
        },
        {
            **copy.deepcopy(base),
            "row_id": f"M1-{next_num + 1:04d}",
            "major_action_std": "체류자격 변경허가", "action_type": "CHANGE",
            "business_name": "국제입양 아동", "detailed_code": "F-1-51",
            "overview_short": "국제입양된 외국인 아동의 방문동거(F-1-51) 체류자격 변경허가 신설.",
            "form_docs": "통합신청서 | 위임장", "supporting_docs": "여권 | 입양관계증명서 | 가족관계증명서",
            "exceptions_summary": "[확인 필요] 세부 서류·심사기준 원문 대조 권장",
            "fee_rule": "일반 수수료 기준 (매뉴얼 확인 필요)",
            "basis_file": "260617 사증민원 자격별 안내 매뉴얼.pdf", "basis_section": "F-1-51 신설",
            "practical_notes": "[260617/23 매뉴얼 반영] 국제입양 아동 체류자격 변경허가(F-1-51) 신규 지침 "
                              "(사증 매뉴얼 F-1 절 / 체류 매뉴얼 p.338~348) | "
                              "[확인 필요] 세부 서류 목록은 매뉴얼 발췌 수준 — 원문 대조 권장",
            "manual_ref": [{"manual": "체류민원", "page_from": 338, "page_to": 348,
                           "match_text": "F-1-51 국제입양", "score": 0,
                           "match_kind": "manual_insert_260623", "match_type": "manual_override"}],
        },
        {
            # D-4-5(한식조리연수)는 기존 369행 중 어떤 D-4 세부코드에도 대응하지
            # 않아(D-4-1/2/7 은 각각 한국어/일반/외국어연수로 무관) family 로
            # 강제 매칭하지 않고 신규 행으로 분리한다.
            **copy.deepcopy(base),
            "row_id": f"M1-{next_num + 2:04d}",
            "major_action_std": "사증발급인정/체류기간 연장허가", "action_type": "EXTEND",
            "business_name": "한식조리연수", "detailed_code": "D-4-5",
            "overview_short": "한식조리연수(D-4-5) 사증발급·체류기간연장 — '26 개편(운영기관 한식진흥원/수라학교 "
                             "한정, 조리경력 요건 폐지, 타 자격→D-4-5 변경 불가, 연장 입국일부터 최대 2년).",
            "form_docs": "통합신청서 | 위임장",
            "supporting_docs": "여권 | 외국인등록증 | 한식진흥원(수라학교) 지정증 | 체류지 입증서류 "
                              "| 결핵진단서[260617/23 신규]",
            "exceptions_summary": "타 체류자격에서 D-4-5로의 자격변경 불가(사증발급인정서로 재입국 필요) "
                                 "[260617/23 반영]",
            "fee_rule": "일반 수수료 기준 (매뉴얼 확인 필요)",
            "basis_file": "260617 사증민원 자격별 안내 매뉴얼.pdf / 260623 체류민원 자격별 안내 매뉴얼.pdf",
            "basis_section": "D-4-5 한식조리연수 전면 개편",
            "practical_notes": "[즉시 반영][260617/23 매뉴얼 반영] 운영기관 aT→한식진흥원/수라학교 한정, "
                              "조리경력 요건 폐지, 체재비 USD 10,000 신설, 6개월 단수 (사증 매뉴얼 p.73~89) | "
                              "[즉시 반영][260617/23 매뉴얼 반영] 타 자격→D-4-5 변경 불가, 연장 입국일부터 "
                              "최대 2년, 연장·외국인등록 제출서류 전면 교체, 결핵 치료회피 시 연장불허·출국명령 "
                              "신설 (체류 매뉴얼 p.86, 91~93, 96) | "
                              "[확인 필요] 구판의 체류기간·단복수 명시 문구 대비 변경인지 신규 명시인지 "
                              "매뉴얼만으로 확인 불가 — 하이코리아 D-4-5 안내 대조 권장",
            "manual_ref": [{"manual": "체류민원", "page_from": 91, "page_to": 96,
                           "match_text": "D-4-5 한식조리연수", "score": 0,
                           "match_kind": "manual_insert_260623", "match_type": "manual_override"}],
        },
    ]
    for r in rows:
        pages = r["manual_ref"][0]["page_from"], r["manual_ref"][0]["page_to"]
        r["manual_updates"] = [{
            "batch_id": BATCH_ID, "delta_id": "insert:" + r["detailed_code"], "manual_version": "260623",
            "source_file": "260623 체류민원 자격별 안내 매뉴얼.pdf", "source_pages": list(pages),
            "section": r["basis_section"], "confidence": "medium", "change_kind": "추가",
            "note_kind": "insert", "review_note": "신규 업무 — 세부 심사기준 원문 대조 권장",
            "applied_at": datetime.now().isoformat(timespec="seconds"),
        }]
    return rows


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = json.load(open(DB_PATH, encoding="utf-8"))
    bundle = json.load(open(BUNDLE_PATH, encoding="utf-8"))
    rows = db["master_rows"]
    rows_by_id = {r["row_id"]: r for r in rows}

    # 이미 이 batch 가 반영된 행은 건너뛴다(idempotent 재실행)
    already = {r["row_id"] for r in rows if already_applied(r, BATCH_ID)}

    stats = {"update_rows": set(), "insert_rows": 0, "caution_rows": set(),
             "h2_notice_rows": set(), "missing_source_pages": 0, "skipped_already_applied": 0,
             "unmatched_items": []}
    eligible_rows = [r for r in rows if r["row_id"] not in already]

    def resolve_item_rows(it: dict, cap: int) -> list:
        """항목 1개 → 매칭 행. DELTA_ID_ROW_OVERRIDE 에 있으면 그것을 그대로
        쓴다(빈 리스트도 유효 — '강제 매칭 안 함'). 없으면 코드 기반 자동 해석."""
        did = it.get("delta_id", "")
        if did in DELTA_ID_ROW_OVERRIDE:
            ids = set(DELTA_ID_ROW_OVERRIDE[did])
            return [r for r in eligible_rows if r["row_id"] in ids]
        codes = expand_codes(it.get("status_code", ""))
        out, seen = [], set()
        for code in codes:
            for r in resolve_rows_for_code(code, eligible_rows, cap):
                if r["row_id"] not in seen:
                    seen.add(r["row_id"])
                    out.append(r)
        return out

    # ── 1) 패키지 요약 → 코드 매칭 행에 주입 (PKG_CONFIRM 제외) ────────────
    # 매칭은 패키지 전체 코드 합집합이 아니라 **항목(item) 단위**로 해석한다.
    # 세부코드(2단 이상, 예: E-7-3)는 정밀 매칭만(형제 세부코드로 새지 않음).
    # 가족단위(1단, 예: F-4/H-2) 코드는 family 크기가 PACKAGE_FAMILY_CAP 이하일
    # 때만 적용 — F-1(31)/F-2(39)/E-7(47) 처럼 이질적 하위업무가 섞인 대형
    # family 는 자동 적용하지 않고(휴리스틱 오탐 방지) unmatched 로 보고한다.
    for pkg in bundle["packages"]:
        if pkg["id"] == "PKG_CONFIRM":
            continue
        pages = sorted({p for it in pkg["items"] for p in (it.get("source_pages") or [])})
        note = (f"[{ACTION_LABEL.get(pkg['recommended_action'], '반영')}][260617/23 매뉴얼 반영] "
               f"{pkg['title']} — {' / '.join(pkg['summary_3_lines'])} ({pages_label(pages)})")
        target_ids: set = set()
        item_hits: dict = {}   # row_id -> [item, ...] (감사기록용)
        for it in pkg["items"]:
            item_rows = resolve_item_rows(it, PACKAGE_FAMILY_CAP)
            if not item_rows and it.get("delta_id") not in DELTA_ID_ROW_OVERRIDE:
                fam_codes = [c for c in expand_codes(it.get("status_code", "")) if c.count("-") < 2]
                if fam_codes:
                    fam_size = len([r for r in eligible_rows
                                   if family_of(r.get("detailed_code", "")) == fam_codes[0]])
                    if fam_size > PACKAGE_FAMILY_CAP:
                        stats["unmatched_items"].append(
                            (it.get("delta_id", ""), f"family {fam_size}행(> {PACKAGE_FAMILY_CAP}) 자동적용 보류"))
            for row in item_rows:
                target_ids.add(row["row_id"])
                item_hits.setdefault(row["row_id"], []).append(it)
        for row in eligible_rows:
            if row["row_id"] not in target_ids:
                continue
            append_note(row, note)
            stats["update_rows"].add(row["row_id"])
            for it in item_hits.get(row["row_id"], []):
                add_audit(row, it, "package_summary")
                if not it.get("source_pages"):
                    stats["missing_source_pages"] += 1
                docs = it.get("documents") or {}
                merged = sorted({d for v in docs.values() for d in (v or [])})
                if merged:
                    append_docs(row, "supporting_docs", merged,
                               f"[{manual_version_of(it)} 신규]")
    stats["skipped_already_applied"] = len(already)

    # ── 2) 확인 필요(PKG_CONFIRM) 항목: 개별 주의 문구 주입 (과도 확산 방지) ─
    confirm_pkg = next((p for p in bundle["packages"] if p["id"] == "PKG_CONFIRM"), None)
    if confirm_pkg:
        for it in confirm_pkg["items"]:
            did = it.get("delta_id", "")
            if not expand_codes(it.get("status_code", "")) and did not in DELTA_ID_ROW_OVERRIDE:
                stats["unmatched_items"].append((did, "코드 없음(예: 동포 공통)"))
                continue
            target_rows = resolve_item_rows(it, CONFIRM_FAMILY_CAP)
            if not target_rows:
                stats["unmatched_items"].append((did, "매칭 행 없음(DB 미모델링 또는 family 초과)"))
                continue
            tag = "[고시 원문 대조 필요]" if ("고시" in (it.get("new_content", "") + it.get("old_content", ""))) \
                else "[확인 필요]"
            note = (f"{tag}[매뉴얼 내부 표기 불일치 가능] {it.get('status_or_task', '')} — "
                   f"{it.get('new_content', '')[:120]} ({pages_label(it.get('source_pages') or [])})")
            seen_rids = set()
            for row in target_rows:
                if row["row_id"] in seen_rids:
                    continue
                seen_rids.add(row["row_id"])
                append_note(row, note)
                stats["update_rows"].add(row["row_id"])
                stats["caution_rows"].add(row["row_id"])
                add_audit(row, it, "confirm_item",
                         "운영 반영 후 추가 확인 필요 — 고시/공지 원문 대조 권장")
                if not it.get("source_pages"):
                    stats["missing_source_pages"] += 1

    # ── 3) H-2 안내문 전환 (삭제 금지) ───────────────────────────────────
    h2_touched = apply_h2_notices({rid: r for rid, r in rows_by_id.items() if rid not in already})
    for rid in list(H2_STRONG_NOTICE_ROWS) + list(H2_CONTEXT_NOTICE_ROWS):
        if rid in rows_by_id and rid not in already:
            stats["h2_notice_rows"].add(rid)
            stats["update_rows"].add(rid)

    # ── 4) 신규 업무 삽입 (F-1-4/F-1-51) ────────────────────────────────
    max_num = max(int(r["row_id"].split("-")[1]) for r in rows)
    new_rows_inserted = 0
    if not any(r.get("detailed_code") == "F-1-4" for r in rows):
        new_rows = build_new_rows(max_num + 1)
        stats["insert_rows"] = len(new_rows)
        if args.apply:
            rows.extend(new_rows)
            new_rows_inserted = len(new_rows)
    else:
        stats["insert_rows"] = 0  # 이미 존재

    # ── 리포트 ──────────────────────────────────────────────────────────
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== {mode}: {BATCH_ID} ===")
    print(f"update 대상 row: {len(stats['update_rows'])}")
    print(f"  - H-2 안내문 전환: {len(stats['h2_notice_rows'])}")
    print(f"  - 확인필요 caution 부여: {len(stats['caution_rows'])}")
    print(f"insert 예정 row: {stats['insert_rows']} (F-1-4, F-1-51, D-4-5)")
    print(f"source_pages 누락 항목: {stats['missing_source_pages']}")
    print(f"이미 반영되어 스킵: {len(already)}행 (batch_id={BATCH_ID})")
    print(f"전체 row 수(적용 전): {len(db['master_rows']) - new_rows_inserted}")
    if stats["unmatched_items"]:
        print(f"\n미매칭 확인필요 항목 {len(stats['unmatched_items'])}건 (DB에 대응 행 없음 — 별도 확인):")
        for did, reason in stats["unmatched_items"]:
            print(f"  - {did}: {reason}")

    if args.dry_run:
        print("\n[dry-run] 파일 변경 없음.")
        return

    # ── apply: 백업 후 저장 ──────────────────────────────────────────────
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"immigration_guidelines_db_v2_pre_{BATCH_ID}_{ts}.json")
    shutil.copy2(DB_PATH, backup_path)
    print(f"\n백업 저장: {backup_path}")

    db["버전"] = NEW_VERSION
    db["갱신일"] = datetime.now().strftime("%Y-%m-%d") + f" (manual update {BATCH_ID})"
    db["통계"] = db.get("통계", {})
    db["통계"]["업무항목"] = len(db["master_rows"])

    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    print(f"저장 완료: {DB_PATH}")
    print(f"최종 row 수: {len(db['master_rows'])} (신규 {new_rows_inserted}건 포함)")
    print(f"버전: {db['버전']} / 갱신일: {db['갱신일']}")


if __name__ == "__main__":
    main()
