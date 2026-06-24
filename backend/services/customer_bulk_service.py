"""엑셀 일괄 고객등록 — 양식 생성 / 파싱·검증 / 커밋 (PG-only).

설계 원칙:
  - 고객ID 는 양식에 없음 — 시스템이 자동 발번(create_customer).
  - 민감정보(외국인등록번호 뒷자리)는 반드시 create_customer 경유 →
    기존 Fernet 암호화/HMAC/마스킹 로직을 동일하게 탄다(평문 별도 저장 금지).
  - 검증/오류 메시지·로그에 reg_back/passport/주소 평문을 절대 넣지 않는다.
  - 검증과 커밋은 모두 "파일 업로드"로 동작(stateless) — 평문 민감정보를 응답으로
    프론트에 돌려보내지 않는다(미리보기는 마스킹).
  - 트랜잭션 정책: 검증 통과 행만 등록(부분 성공). 중복 의심은 기본 제외(선택 시 등록).
  - 모델에 컬럼 없는 '중국명/한자명', '생년월일'은 양식에서 제외.
"""
from __future__ import annotations

import io
import re
from typing import Optional

# 엑셀 열(표시 헤더, 한글 표준키, 필수). 고객ID/중국명/생년월일 제외.
# 영문명 → 성+명 분해, 전화번호 → 연/락/처 분해(아래 _row_to_customer).
EXCEL_COLUMNS = [
    ("고객명", "한글", True),
    ("영문명", "_eng_name", False),
    ("성별", "성별", False),
    ("국적", "국적", False),
    ("전화번호", "_phone", False),
    ("외국인등록번호 앞자리", "등록증", False),
    ("외국인등록번호 뒷자리", "번호", False),
    ("등록증 발급일", "발급일", False),
    ("체류 만료일", "만기일", False),
    ("여권번호", "여권", False),
    ("여권 발급일", "발급", False),
    ("여권 만기일", "만기", False),
    ("체류자격", "체류자격", False),
    ("주소", "주소", False),
    ("메모", "비고", False),
]

HEADERS = [h for h, _, _ in EXCEL_COLUMNS]
DATE_HEADERS = {"등록증 발급일", "체류 만료일", "여권 발급일", "여권 만기일"}

SHEET_NAME = "고객"
HEADER_ROW = 2   # 1행 = 안내, 2행 = 헤더, 3행~ = 입력

_YMD = re.compile(r"^(\d{4})-(\d{2})-(\d{2})([ T].*)?$")
_DOTTED = re.compile(r"^(\d{4})[./](\d{2})[./](\d{2})([ T].*)?$")
_YYYYMMDD = re.compile(r"^\d{8}$")
_DIGITS = re.compile(r"\d")


def _norm_date(v: str) -> tuple[str, bool]:
    """(정규화값, ok). 빈값은 ('', True). 판독불가는 (원본, False)."""
    s = str(v or "").strip().replace(".", ".")
    if not s:
        return "", True
    m = _YMD.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", True
    m = _DOTTED.match(s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", True
    if _YYYYMMDD.match(s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}", True
    return s, False


def _split_name(value: str) -> tuple[str, str]:
    """영문명 → (성, 명). 공백 기준: 첫 토큰=성, 나머지=명. 단일 토큰은 명에."""
    parts = str(value or "").split()
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    if len(parts) == 1:
        return "", parts[0]
    return "", ""


def _split_phone(value: str) -> tuple[str, str, str]:
    """전화번호 → (연, 락, 처). '-' 구분 우선, 없으면 숫자만 추출해 3-4-4 분해."""
    s = str(value or "").strip()
    if not s:
        return "", "", ""
    if "-" in s:
        parts = [p.strip() for p in s.split("-")]
        parts = (parts + ["", "", ""])[:3]
        return parts[0], parts[1], parts[2]
    d = "".join(_DIGITS.findall(s))
    if len(d) >= 10:  # 010 1234 5678 / 011 ...
        return d[:3], d[3:-4], d[-4:]
    return s, "", ""


# ── 양식 생성 ──────────────────────────────────────────────────────────────────

def build_template_bytes() -> bytes:
    """입력 양식 xlsx(bytes). 1행 안내 + 2행 헤더 잠금, 입력행 해제, 시트 보호."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill, Protection
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME

    guide = (
        "※ 2행 헤더 아래(3행)부터 입력하세요. 고객ID는 입력하지 마세요(자동 생성). "
        "날짜는 yyyy-mm-dd 형식(예: 2026-06-24). '고객명'은 필수입니다. "
        "외국인등록번호 뒷자리는 안전하게 암호화되어 저장됩니다."
    )
    n = len(HEADERS)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    c = ws.cell(row=1, column=1, value=guide)
    c.font = Font(bold=True, color="7A5C10", size=10)
    c.alignment = Alignment(wrap_text=True, vertical="center")
    c.fill = PatternFill("solid", fgColor="FFF8E6")
    ws.row_dimensions[1].height = 46

    header_fill = PatternFill("solid", fgColor="F0E6C8")
    for i, (h, key, required) in enumerate(EXCEL_COLUMNS, start=1):
        cell = ws.cell(row=HEADER_ROW, column=i, value=(h + (" *" if required else "")))
        cell.font = Font(bold=True, size=10)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(i)].width = 18 if (h in DATE_HEADERS or len(h) > 6) else 12

    # 1·2행 잠금, 3행~ 1000행 입력영역 잠금 해제.
    for col in range(1, n + 1):
        ws.cell(row=1, column=col).protection = Protection(locked=True)
        ws.cell(row=HEADER_ROW, column=col).protection = Protection(locked=True)
    for r in range(HEADER_ROW + 1, HEADER_ROW + 1000):
        for col in range(1, n + 1):
            ws.cell(row=r, column=col).protection = Protection(locked=False)
    ws.freeze_panes = ws.cell(row=HEADER_ROW + 1, column=1)
    ws.protection.sheet = True
    ws.protection.formatColumns = False
    ws.protection.formatRows = False

    # 사용법 시트
    info = wb.create_sheet("사용법")
    lines = [
        "[엑셀 일괄 고객등록 사용법]",
        "",
        "1. '고객' 시트 2행 헤더 아래(3행)부터 한 행에 한 명씩 입력합니다.",
        "2. 고객ID는 입력하지 않습니다 — 시스템이 자동으로 부여합니다.",
        "3. 날짜는 yyyy-mm-dd 형식으로 입력합니다 (예: 2026-06-24).",
        "4. '고객명'은 필수입니다. 나머지는 비워둘 수 있습니다.",
        "5. 영문명은 '성 이름' 순서로 입력하면 성/이름으로 분리 저장됩니다.",
        "6. 전화번호는 010-1234-5678 형식 또는 숫자만 입력 가능합니다.",
        "7. 외국인등록번호 뒷자리는 암호화되어 저장되며 화면에는 마스킹됩니다.",
        "8. 업로드 후 미리보기에서 신규/중복의심/오류를 확인한 뒤 등록합니다.",
        "9. 중복 의심 행은 기본적으로 등록되지 않습니다(선택 시 신규로 추가).",
    ]
    for idx, line in enumerate(lines, start=1):
        cell = info.cell(row=idx, column=1, value=line)
        if idx == 1:
            cell.font = Font(bold=True, size=12)
    info.column_dimensions["A"].width = 80

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── 파싱 / 검증 ────────────────────────────────────────────────────────────────

def _read_rows(file_bytes: bytes) -> list[dict]:
    """업로드 xlsx → 행 dict 목록(표준 한글키). 빈 행은 건너뜀. row_no 포함(엑셀 행번호)."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    ws = wb[SHEET_NAME] if SHEET_NAME in wb.sheetnames else wb.worksheets[0]

    rows = []
    for r_idx, row in enumerate(ws.iter_rows(min_row=HEADER_ROW + 1, values_only=True), start=HEADER_ROW + 1):
        cells = list(row) if row else []
        # 셀 정렬을 헤더 수에 맞춤
        cells = (cells + [None] * len(HEADERS))[: len(HEADERS)]
        values = ["" if v is None else str(v).strip() for v in cells]
        if not any(values):
            continue
        raw = {HEADERS[i]: values[i] for i in range(len(HEADERS))}
        raw["_row_no"] = r_idx
        rows.append(raw)
    wb.close()
    return rows


def _row_to_customer(raw: dict) -> tuple[dict, list[str]]:
    """엑셀 행(헤더키) → 고객 표준키 dict + 검증 메시지(민감정보 비노출)."""
    msgs: list[str] = []
    data: dict = {}

    name = raw.get("고객명", "").strip()
    if not name:
        msgs.append("고객명(필수)이 비어 있습니다.")
    data["한글"] = name

    sur, given = _split_name(raw.get("영문명", ""))
    data["성"], data["명"] = sur, given
    data["성별"] = raw.get("성별", "")
    data["국적"] = raw.get("국적", "")
    yeon, rak, cheo = _split_phone(raw.get("전화번호", ""))
    data["연"], data["락"], data["처"] = yeon, rak, cheo
    data["등록증"] = raw.get("외국인등록번호 앞자리", "")
    data["번호"] = raw.get("외국인등록번호 뒷자리", "")  # create_customer 가 암호화
    data["여권"] = raw.get("여권번호", "")
    data["체류자격"] = raw.get("체류자격", "")
    data["주소"] = raw.get("주소", "")
    data["비고"] = raw.get("메모", "")

    for header, key in (("등록증 발급일", "발급일"), ("체류 만료일", "만기일"),
                        ("여권 발급일", "발급"), ("여권 만기일", "만기")):
        norm, ok = _norm_date(raw.get(header, ""))
        data[key] = norm
        if not ok:
            msgs.append(f"{header} 날짜 형식을 인식할 수 없습니다 (yyyy-mm-dd 필요).")

    # 외국인등록번호 뒷자리 형식(있을 때만): 숫자 7자리 권장 — 값은 메시지에 넣지 않음.
    rb = "".join(_DIGITS.findall(data["번호"]))
    if data["번호"] and len(rb) not in (0, 7):
        msgs.append("외국인등록번호 뒷자리는 숫자 7자리여야 합니다.")

    return data, msgs


def _existing_index(tenant_id: str):
    """(passport_no→cust_id, reg_back_hash→cust_id) 기존 고객 인덱스(비삭제)."""
    from backend.db.models.customer import Customer
    from backend.db.session import get_sessionmaker
    from sqlalchemy import select

    by_passport: dict = {}
    by_hash: dict = {}
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.execute(
            select(Customer.customer_id, Customer.passport_no, Customer.reg_back_hash).where(
                Customer.tenant_id == tenant_id, Customer.deleted_at.is_(None)
            )
        ).all()
    for cid, passport, h in rows:
        if passport:
            by_passport.setdefault(str(passport).strip(), str(cid))
        if h:
            by_hash.setdefault(str(h), str(cid))
    return by_passport, by_hash


def _find_duplicate(data: dict, tenant_id: str, by_passport: dict, by_hash: dict) -> Optional[str]:
    """중복 의심 기존 고객ID. ① reg_back_hash → ② passport. 없으면 None."""
    from backend.services import pii_crypto as _pii

    rb = "".join(_DIGITS.findall(data.get("번호", "")))
    if rb:
        try:
            h = _pii.hash_pii(tenant_id, rb)
        except Exception:
            h = ""
        if h and h in by_hash:
            return by_hash[h]
    passport = str(data.get("여권", "")).strip()
    if passport and passport in by_passport:
        return by_passport[passport]
    return None


def validate(file_bytes: bytes, tenant_id: str) -> dict:
    """파싱+검증(등록하지 않음). 미리보기용(민감정보 마스킹)."""
    rows = _read_rows(file_bytes)
    by_passport, by_hash = _existing_index(tenant_id)

    preview = []
    n_new = n_dup = n_err = 0
    for raw in rows:
        data, msgs = _row_to_customer(raw)
        if msgs:
            status = "error"
            n_err += 1
            dup_id = None
        else:
            dup_id = _find_duplicate(data, tenant_id, by_passport, by_hash)
            if dup_id:
                status = "duplicate"
                n_dup += 1
            else:
                status = "new"
                n_new += 1
        preview.append({
            "row_no": raw.get("_row_no"),
            "status": status,
            "name": data.get("한글", ""),
            "nationality": data.get("국적", ""),
            "visa": data.get("체류자격", ""),
            "passport_masked": _mask_tail(data.get("여권", "")),
            "messages": msgs,
            "dup_customer_id": dup_id,
        })

    return {
        "total": len(rows),
        "counts": {"new": n_new, "duplicate": n_dup, "error": n_err},
        "rows": preview,
    }


def _mask_tail(v: str) -> str:
    """여권번호 등 표시 마스킹: 앞 3자리만 노출."""
    s = str(v or "").strip()
    if len(s) <= 3:
        return s
    return s[:3] + "*" * (len(s) - 3)


def commit(file_bytes: bytes, tenant_id: str, include_duplicates: bool) -> dict:
    """검증 통과 행 등록(부분 성공). 신규는 항상, 중복 의심은 include_duplicates 시.

    오류 행은 등록하지 않는다. 각 행은 create_customer 경유(자동 발번 + 암호화).
    예외 메시지/로그에 민감정보를 넣지 않는다.
    """
    from backend.services.customer_pg_service import (
        create_customer, CustomerIdConflict, TenantNotProvisioned,
    )
    from backend.services.pii_crypto import PiiKeyMissing

    rows = _read_rows(file_bytes)
    by_passport, by_hash = _existing_index(tenant_id)

    registered = 0
    skipped_dup = 0
    skipped_err = 0
    failed = 0
    fail_rows: list[int] = []
    new_ids: list[str] = []

    for raw in rows:
        data, msgs = _row_to_customer(raw)
        if msgs:
            skipped_err += 1
            continue
        dup_id = _find_duplicate(data, tenant_id, by_passport, by_hash)
        if dup_id and not include_duplicates:
            skipped_dup += 1
            continue
        try:
            result = create_customer(tenant_id, data)
            registered += 1
            cid = result.get("고객ID", "")
            if cid:
                new_ids.append(cid)
                # 같은 업로드 내 후속 중복 판정을 위해 인덱스 갱신(평문 로그 없음).
                passport = str(data.get("여권", "")).strip()
                if passport:
                    by_passport.setdefault(passport, cid)
        except (CustomerIdConflict, TenantNotProvisioned, PiiKeyMissing):
            failed += 1
            fail_rows.append(raw.get("_row_no"))
        except Exception:
            failed += 1
            fail_rows.append(raw.get("_row_no"))

    return {
        "registered": registered,
        "skipped_duplicate": skipped_dup,
        "skipped_error": skipped_err,
        "failed": failed,
        "failed_rows": fail_rows,
        "new_customer_ids": new_ids,
    }
