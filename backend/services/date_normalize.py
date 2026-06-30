"""날짜형 필드 공통 정규화 — 시스템 전체에서 ``YYYY-MM-DD`` 로 통일.

날짜만 의미하는 고객정보 필드(여권 발급/만기, 등록증 발급/만기, 체류만료 등)는
**저장 전·응답 전** 모두 이 함수를 통과시켜 ``YYYY-MM-DD`` 로 통일한다.
그래야 ``YYYY-MM-DD 00:00:00`` 같은 datetime 문자열이 API/화면에 새지 않는다.

허용 입력 → 출력::

    '2025-05-28'            → '2025-05-28'   (그대로)
    '2025-05-28 00:00:00'   → '2025-05-28'
    '2025-05-28T00:00:00'   → '2025-05-28'
    '2025-05-28T00:00:00Z'  → '2025-05-28'
    '2025.05.28'            → '2025-05-28'
    '2025/05/28'            → '2025-05-28'
    '20250528'              → '2025-05-28'
    date / datetime 객체     → 'YYYY-MM-DD'
    None                    → None          (기존 정책 유지)
    '' / 공백               → ''            (빈값 보존)
    판독 불가/이상 포맷       → 원문 그대로     (임의 변환 금지)

설계 원칙:
- 멱등하다 — 이미 ``YYYY-MM-DD`` 면 그대로.
- 잘못된 날짜를 임의로 변환하지 않는다(오류/빈값 처리 정책 유지).
- 시간/타임존을 절대 보존하지 않는다(날짜만 의미하는 필드 전용).
"""
from __future__ import annotations

import datetime as _dt
import re

# 'YYYY-MM-DD' 뒤에 ' ...' 또는 'T...'(시간/타임존)가 붙어도 날짜부만 취한다.
_YMD = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?$")
# 'YYYY.MM.DD' / 'YYYY/MM/DD' (뒤 시간 허용)
_DOTTED = re.compile(r"^(\d{4})[./](\d{1,2})[./](\d{1,2})(?:[ T].*)?$")
# 'YYYYMMDD'
_YYYYMMDD = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def _valid_ymd(y: int, m: int, d: int) -> bool:
    try:
        _dt.date(y, m, d)
        return True
    except ValueError:
        return False


def normalize_date_only(value):
    """날짜형 값을 ``YYYY-MM-DD`` 문자열로 정규화한다.

    - ``None`` → ``None`` / 빈 문자열 → 그대로(빈값) — 기존 빈값 정책 유지.
    - ``date``/``datetime`` 객체 → ``YYYY-MM-DD``.
    - 판독 불가능한 문자열 → **원문 그대로 반환**(임의 변환 금지).
    """
    if value is None:
        return None
    # datetime 은 date 의 하위 클래스이므로 datetime 먼저 검사할 필요는 없다.
    if isinstance(value, (_dt.date, _dt.datetime)):
        d = value.date() if isinstance(value, _dt.datetime) else value
        return d.strftime("%Y-%m-%d")

    s = str(value).strip()
    if not s:
        return s  # 빈값 보존

    m = _YMD.match(s) or _DOTTED.match(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid_ymd(y, mo, d):
            return f"{y:04d}-{mo:02d}-{d:02d}"
        return s  # 형식은 맞지만 실재하지 않는 날짜 → 임의 변환 금지
    m = _YYYYMMDD.match(s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if _valid_ymd(y, mo, d):
            return f"{y:04d}-{mo:02d}-{d:02d}"
        return s
    return s  # 판독 불가 → 원문 그대로


def normalize_date_fields(data: dict, keys) -> dict:
    """``data`` 의 주어진 ``keys`` 만 in-place 로 날짜 정규화하고 ``data`` 반환.

    키가 없으면 건너뛴다(부분 업데이트 시 기존 값 보존).
    """
    for k in keys:
        if k in data:
            data[k] = normalize_date_only(data[k])
    return data
