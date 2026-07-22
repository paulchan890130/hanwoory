"""외국인등록번호 앞자리(reg_front, YYMMDD) 정규화 — 선행 0 손실 복구·검증 단일 소스.

reg_front 는 **정확히 6자리 숫자 문자열**(YYMMDD)이어야 한다. Excel 숫자 셀·정수 입력·과거
이관 과정에서 선행 0 이 사라져 ``1010``(=001010) 처럼 저장/전달되는 문제를 이 모듈 한 곳에서
복구·검증한다. 산술 변환(int/float/Number)은 하지 않으며, 결과는 항상 문자열이다.

정책:
- 빈 값은 빈 값(valid).
- 정확한 6자리 숫자 + 유효한 YYMMDD → 그대로.
- int/float(예: 1010, 1010.0) 및 1~5자리 문자열 → 좌측 0 채움 후 YYMMDD 검증(allow_numeric_recovery).
- 7자리 이상/월·일 범위 위반/소수부 0 아님/음수/영숫자 혼합 → invalid(자동 절단·추측 없음).
세기(1900/2000)는 앞자리만으로 판정하지 않고 **등록번호 뒷자리 첫 숫자**로 판정한다.
원문(등록번호 전체)을 로그/예외 메시지에 남기지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_DAYS_IN_MONTH = (31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)  # Feb=29 허용(세기 미상)


@dataclass
class RegFrontResult:
    canonical_value: str
    changed: bool
    valid: bool
    reason: str


def _valid_yymmdd(d6: str) -> bool:
    if len(d6) != 6 or not d6.isdigit():
        return False
    mm = int(d6[2:4]); dd = int(d6[4:6])
    if not (1 <= mm <= 12):
        return False
    return 1 <= dd <= _DAYS_IN_MONTH[mm - 1]


def _coerce_to_digits(value) -> tuple[Optional[str], str]:
    """입력을 순수 숫자 문자열로 환원. (digits|None, reason). None 이면 invalid."""
    if value is None:
        return "", "empty"
    # bool 은 int 하위형 — reg_front 로 부적절.
    if isinstance(value, bool):
        return None, "bad_type"
    if isinstance(value, int):
        if value < 0:
            return None, "negative"
        return str(value), "from_int"
    if isinstance(value, float):
        if value < 0:
            return None, "negative"
        if not value.is_integer():
            return None, "fractional"
        return str(int(value)), "from_float"
    s = str(value).strip()
    if s == "":
        return "", "empty"
    # "1010.0" 형태(문자열) 허용, "1010.5" 거부.
    m = re.fullmatch(r"(\d+)(?:\.(\d+))?", s)
    if not m:
        return None, "bad_chars"
    if m.group(2) is not None and int(m.group(2)) != 0:
        return None, "fractional"
    return m.group(1), "from_str"


def normalize_reg_front(value, *, source: str = "unknown",
                        allow_numeric_recovery: bool = True) -> RegFrontResult:
    """reg_front 정규화. source 는 감사/디버깅용 라벨(원문 미포함).

    allow_numeric_recovery=True: 1~6자리를 좌측 0 채움 후 YYMMDD 검증(Excel/이관/레거시 읽기).
    allow_numeric_recovery=False: 정확히 6자리만 허용(엄격 웹 입력) — 그 외 invalid.
    """
    original = "" if value is None else str(value).strip()
    digits, why = _coerce_to_digits(value)
    if digits is None:
        return RegFrontResult(original, False, False, why)
    if digits == "":
        return RegFrontResult("", False, True, "empty")
    if len(digits) > 6:
        return RegFrontResult(original, False, False, "too_long")
    if len(digits) < 6:
        if not allow_numeric_recovery:
            return RegFrontResult(original, False, False, "too_short")
        candidate = digits.zfill(6)
    else:
        candidate = digits
    if not _valid_yymmdd(candidate):
        return RegFrontResult(original, False, False, "invalid_date")
    changed = candidate != original
    reason = "ok" if not changed else ("recovered" if why in ("from_int", "from_float") or len(digits) < 6 else "normalized")
    return RegFrontResult(candidate, changed, True, reason)


class RegFrontValidationError(ValueError):
    """웹/API 신규·수정 입력이 reg_front 정책(빈 값 또는 정확한 6자리 YYMMDD)을 위반.

    라우터가 구조화된 400/422 로 변환한다. 원문 값은 담지 않는다(PII 로그 방지)."""

    code = "INVALID_REG_FRONT"

    def __init__(self, reason: str = "invalid"):
        self.reason = reason
        super().__init__(
            "외국인등록번호 앞자리는 생년월일 6자리로 입력하세요. "
            "예: 2000년 10월 10일 → 001010"
        )


# ── 경계 A: 레거시 DB 읽기 방어(느슨 — 복구 가능하면 복구, 불가하면 원문 보존) ──────
def canonical_reg_front_for_legacy_read(value) -> str:
    """레거시 읽기 전용. 1~5자리/숫자형은 좌측 0 채움 복구, 실패 시 원문 보존(비파괴).

    **쓰기 검증에 사용하지 말 것** — 잘못된 값을 그대로 통과시킨다."""
    r = normalize_reg_front(value, source="legacy_read", allow_numeric_recovery=True)
    return r.canonical_value if r.valid else ("" if value is None else str(value).strip())


# 하위호환 alias(기존 호출부) — 의미는 레거시 읽기 복구.
def canonical_reg_front(value, *, allow_numeric_recovery: bool = True) -> str:
    r = normalize_reg_front(value, allow_numeric_recovery=allow_numeric_recovery)
    return r.canonical_value if r.valid else ("" if value is None else str(value).strip())


# ── 경계 C: 웹/API 신규·수정 엄격 검증(복구 금지 — 빈 값 또는 정확한 6자리만) ──────
def validate_reg_front_for_write(value) -> str:
    """신규 등록/사용자 직접 수정용. 빈 값 또는 정확한 6자리 유효 YYMMDD만 허용.

    반환: canonical 문자열('' 포함). 그 외(1~5자리·7자리+·범위위반·소수·문자) →
    :class:`RegFrontValidationError`. **4자리 '1010' 을 조용히 '001010' 으로 바꾸지 않는다.**"""
    r = normalize_reg_front(value, source="write", allow_numeric_recovery=False)
    if not r.valid:
        raise RegFrontValidationError(r.reason)
    return r.canonical_value


# ── 경계 B: Excel 숫자 셀/이관 입력(복구 허용, 유효성은 호출부가 오류로 처리) ──────
def normalize_reg_front_from_excel(value) -> RegFrontResult:
    """Excel 숫자 셀(1010/1010.0)·문자열('001010')을 복구 시도. 결과 객체 반환.

    valid=False 이면 호출부(_row_to_customer)가 **경고가 아닌 오류**로 행을 차단한다."""
    return normalize_reg_front(value, source="excel_import", allow_numeric_recovery=True)


# ── 세기 판정(등록번호 뒷자리 첫 숫자) — 프론트 birth.ts 와 동일 규칙 ────────────
def century_prefix_from_reg_back(reg_back, yy: Optional[str] = None) -> str:
    """뒷자리 첫 숫자 → '19'|'20'. 9/0/미상은 yy 보수적 휴리스틱(현재 두자리 이하→2000)."""
    d = re.sub(r"\D", "", "" if reg_back is None else str(reg_back))
    code = d[0] if d else ""
    if code in ("1", "2", "5", "6"):
        return "19"
    if code in ("3", "4", "7", "8"):
        return "20"
    yn = re.sub(r"\D", "", (yy or ""))[:2]
    if yn:
        from datetime import date
        return "20" if int(yn) <= (date.today().year % 100) else "19"
    return "19"


def derive_birth_date(front, reg_back) -> str:
    """canonical(또는 복구 가능한) 앞자리 + 뒷자리 세기코드 → 'YYYY-MM-DD'.

    구조적 YYMMDD 검증(세기 미상, Feb29 후보 허용)을 통과해도 **세기 결합 후 실제
    그레고리력 날짜가 존재하지 않으면 빈 값**을 반환한다(예: 1900-02-29, 1999-02-29).
    복구 불가/무효 → ''."""
    from datetime import date

    r = normalize_reg_front(front, allow_numeric_recovery=True)
    if not r.valid or not r.canonical_value:
        return ""
    f = r.canonical_value
    cen = century_prefix_from_reg_back(reg_back, f[:2])
    yyyy, mm, dd = int(cen + f[:2]), int(f[2:4]), int(f[4:6])
    try:
        date(yyyy, mm, dd)  # 실제 존재하는 날짜인지(윤년 포함) 검증
    except ValueError:
        return ""
    return f"{yyyy:04d}-{mm:02d}-{dd:02d}"
