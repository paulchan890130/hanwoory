"""
immigration_guidelines_db_v2.json 마이그레이션 스크립트
- quickdoc_category / quickdoc_minwon / quickdoc_kind / quickdoc_detail 필드 추가
- 문서자동작성 딥링크용 매핑 (quick_doc.py 트리 구조 기준)
"""

import json
import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH  = os.path.join(BASE_DIR, "data", "immigration_guidelines_db_v2.json")

# ── quick-doc 트리 구조 (quick_doc.py 기준) ────────────────────────────────────
# (category, minwon) → kind 목록
VALID_KINDS: dict[tuple, list[str]] = {
    ("체류", "변경"): ["F", "H2", "E7", "국적", "D"],
    ("체류", "연장"): ["F", "H2", "E7", "D"],
    ("체류", "등록"): ["F", "H2", "E7", "D"],
    ("체류", "부여"): ["F", "D"],
}

# (category, minwon, kind) → detail 목록
VALID_DETAILS: dict[tuple, list[str]] = {
    ("체류", "변경", "F"):  ["1","2","3","4","5","6"],
    ("체류", "변경", "H2"): ["1","2"],
    ("체류", "변경", "E7"): ["1","4"],
    ("체류", "변경", "D"):  ["1","2","3","4","5","6","7","8","9","10"],
    ("체류", "연장", "F"):  ["1","2","3","4","5","6"],
    ("체류", "연장", "H2"): ["1","2"],
    ("체류", "연장", "E7"): ["1","4"],
    ("체류", "연장", "D"):  ["1","2","3","4","5","6","7","8","9","10"],
    ("체류", "등록", "F"):  ["1","2","3","4","5","6"],
    ("체류", "등록", "H2"): ["1","2"],
    ("체류", "등록", "E7"): ["1","4"],
    ("체류", "등록", "D"):  ["1","2","3","4","5","6","7","8","9","10"],
    ("체류", "부여", "F"):  ["2","3","5"],
    ("체류", "부여", "D"):  ["1"],
}


def action_type_to_minwon(at: str) -> str | None:
    """action_type → quick-doc minwon 매핑. 매핑 없으면 None."""
    return {
        "CHANGE":       "변경",
        "EXTEND":       "연장",
        "REGISTRATION": "등록",
        "GRANT":        "부여",
        # 아래는 quick-doc 문서생성 대상 아님 → None
        "EXTRA_WORK":                None,
        "WORKPLACE":                 None,
        "REENTRY":                   None,
        "APPLICATION_CLAIM":         None,
        "DOMESTIC_RESIDENCE_REPORT": None,
        "ACTIVITY_EXTRA":            None,
        "VISA_CONFIRM":              None,  # 별도 처리
    }.get(at)


def code_to_kind_detail(code: str, minwon: str) -> tuple[str | None, str | None]:
    """
    detailed_code → (kind, detail) 추론.
    F-4-1 → ('F', '4')
    H-2   → ('H2', None)
    E-7-1 → ('E7', '1')  ※ E7 detail은 sub-suffix 아닌 dash-2번째 숫자
    D-2-3 → ('D', '2')
    """
    code = code.strip()
    if not code:
        return None, None

    # F 계열
    m = re.match(r"^F-(\d+)", code)
    if m:
        detail_num = m.group(1)
        kind = "F"
        # detail은 F-숫자 의 숫자 (1~6)
        if detail_num in ("1","2","3","4","5","6"):
            detail = detail_num
        else:
            detail = None
        # detail이 valid한지 확인
        key = ("체류", minwon, kind)
        valid = VALID_DETAILS.get(key, [])
        if detail not in valid:
            detail = None
        return kind, detail

    # H-2 계열
    if re.match(r"^H-?2", code):
        kind = "H2"
        # H2 detail: H-2 → None (첫 진입), H-2-1/H-2-2 등 없음 (quick-doc에 H2 detail 1,2만 있음)
        m2 = re.match(r"^H-?2-(\d+)", code)
        detail = m2.group(1) if m2 else "1"
        key = ("체류", minwon, kind)
        valid = VALID_DETAILS.get(key, [])
        if detail not in valid:
            detail = "1"  # 기본 첫번째
        return kind, detail

    # E-7 계열
    if re.match(r"^E-7", code):
        kind = "E7"
        # E-7-1 → detail=1, E-7-4 → detail=4
        m3 = re.match(r"^E-7-(\d+)", code)
        if m3:
            d = m3.group(1)
            key = ("체류", minwon, kind)
            valid = VALID_DETAILS.get(key, [])
            detail = d if d in valid else None
        else:
            detail = None
        return kind, detail

    # D 계열 (D-1 ~ D-10)
    m4 = re.match(r"^D-(\d+)", code)
    if m4:
        kind = "D"
        d_num = m4.group(1)
        key = ("체류", minwon, kind)
        valid = VALID_DETAILS.get(key, [])
        detail = d_num if d_num in valid else None
        return kind, detail

    return None, None


def compute_quickdoc(row: dict) -> tuple[str | None, str | None, str | None, str | None]:
    """
    row → (quickdoc_category, quickdoc_minwon, quickdoc_kind, quickdoc_detail)
    매핑 불가능하면 모두 None.
    """
    at   = row.get("action_type", "")
    code = row.get("detailed_code", "")

    # 사증발급인정서
    if at == "VISA_CONFIRM":
        return "사증", None, None, None  # minwon=준비중이지만 아직 사증 트리 미구현

    minwon = action_type_to_minwon(at)
    if not minwon:
        return None, None, None, None

    kind, detail = code_to_kind_detail(code, minwon)

    # kind가 valid한지 체크
    if kind:
        valid_kinds = VALID_KINDS.get(("체류", minwon), [])
        if kind not in valid_kinds:
            kind = None
            detail = None

    return "체류", minwon, kind, detail


def migrate() -> None:
    with open(DB_PATH, encoding="utf-8") as f:
        db = json.load(f)

    rows = db.get("master_rows", [])
    mapped = 0
    partial = 0   # category+minwon만
    unmapped = 0

    for row in rows:
        cat, min_, kind, detail = compute_quickdoc(row)
        row["quickdoc_category"] = cat
        row["quickdoc_minwon"]   = min_
        row["quickdoc_kind"]     = kind
        row["quickdoc_detail"]   = detail

        if cat and min_ and kind:
            mapped += 1
        elif cat and min_:
            partial += 1
        elif cat:
            partial += 1
        else:
            unmapped += 1

    db["master_rows"] = rows

    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=None, separators=(",", ":"))

    total = len(rows)
    print(f"마이그레이션 완료: 총 {total}건")
    print(f"  완전 매핑 (category+minwon+kind): {mapped}건")
    print(f"  부분 매핑 (category 또는 minwon까지): {partial}건")
    print(f"  미매핑: {unmapped}건")
    print(f"  저장 경로: {DB_PATH}")


if __name__ == "__main__":
    migrate()
