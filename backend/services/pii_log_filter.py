"""로그 PII 자동 마스킹 필터.

로그 메시지/인자에 실수로 남는 **주민등록번호/외국인등록번호 전체형(13자리)**을
출력 직전에 마스킹한다. 과마스킹을 피하기 위해 단독 7자리는 건드리지 않고, 전체형만 대상:

- ``000000-0000000`` → ``000000-*******``
- 연속 13자리 ``0000000000000`` → ``000000*******``

루트 로거에 1회 부착(backend/main.py). 방어선이며, 코드에서 평문 PII 로깅 자체를
하지 않는 원칙과 병행한다.
"""
from __future__ import annotations

import logging
import re

_RRN_DASH = re.compile(r"(\d{6})-\d{7}")
_RRN_13 = re.compile(r"(?<!\d)(\d{6})\d{7}(?!\d)")

# 민감 key 에 붙은 값은 7자리라도 마스킹(전역 7자리 마스킹은 하지 않음 — 과마스킹 방지).
# 매칭 예: 번호=1234567 / "reg_back": "1234567" / 'rnumber': '1234567' / provider_reg_back=1234567
_SENSITIVE_KEYS = ("reg_back", "alien_reg_back", "번호", "rnumber",
                   "provider_reg_back", "guarantor_reg_back")
_KEY_ALT = "|".join(re.escape(k) for k in _SENSITIVE_KEYS)
_KEY_VALUE = re.compile(
    r"(?P<key>(?:" + _KEY_ALT + r"))(?P<sep>[\"']?\s*[:=]\s*[\"']?)(?P<digit>\d)(?P<rest>\d{3,})"
)


def _mask_key_value(m: "re.Match") -> str:
    # 첫 자리 보존 + 나머지 마스킹(별 개수는 자리수 유지). 따옴표/구분자는 원형 유지.
    return f"{m.group('key')}{m.group('sep')}{m.group('digit')}{'*' * len(m.group('rest'))}"


def _mask(text: str) -> str:
    if not text or not isinstance(text, str):
        return text
    text = _RRN_DASH.sub(r"\1-*******", text)
    text = _RRN_13.sub(r"\1*******", text)
    text = _KEY_VALUE.sub(_mask_key_value, text)
    return text


class PiiMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = _mask(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: (_mask(v) if isinstance(v, str) else v) for k, v in record.args.items()}
                else:
                    record.args = tuple(_mask(a) if isinstance(a, str) else a for a in record.args)
        except Exception:
            # 필터가 로깅을 깨뜨리면 안 됨 — 실패해도 레코드는 통과.
            return True
        return True


def install_pii_log_filter() -> None:
    """루트 로거 + uvicorn 로거에 PII 마스킹 필터 부착(중복 부착 방지)."""
    f = PiiMaskingFilter()
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "audit"):
        logger = logging.getLogger(name)
        if not any(isinstance(x, PiiMaskingFilter) for x in logger.filters):
            logger.addFilter(f)
