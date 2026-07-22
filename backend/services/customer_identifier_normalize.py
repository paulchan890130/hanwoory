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


def canonical_reg_front(value, *, allow_numeric_recovery: bool = True) -> str:
    """정규화 성공 시 canonical 6자리, 실패 시 원문 문자열(파괴적 변경 없음)."""
    r = normalize_reg_front(value, allow_numeric_recovery=allow_numeric_recovery)
    return r.canonical_value if r.valid else ("" if value is None else str(value).strip())


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
    """canonical(또는 복구 가능한) 앞자리 + 뒷자리 → 'YYYY-MM-DD'. 불가하면 ''."""
    r = normalize_reg_front(front, allow_numeric_recovery=True)
    if not r.valid or not r.canonical_value:
        return ""
    f = r.canonical_value
    cen = century_prefix_from_reg_back(reg_back, f[:2])
    return f"{cen}{f[:2]}-{f[2:4]}-{f[4:6]}"
