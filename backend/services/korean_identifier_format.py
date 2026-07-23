"""한국 사업자등록번호 / 전화번호 / 주민등록번호 형식·검증 공통 helper.

원칙:
- **DB canonical 저장은 숫자만**(사업자번호 10자리, 전화번호 9~11자리). 주민등록번호는 평문 저장 금지
  (암호화는 backend.services.pii_crypto 담당 — 이 모듈은 형식/표시만).
- 하이픈은 **화면·문서 출력에서만** 넣는다.
- 기존 office_application_pg_service 의 로컬 helper 를 이 모듈로 통합(하위호환 별칭 제공).
"""
from __future__ import annotations

import re

__all__ = [
    "normalize_biz_reg_no", "format_biz_reg_no", "validate_biz_reg_no", "is_valid_biz_reg_no",
    "normalize_phone", "format_phone", "validate_phone", "is_valid_phone",
    "normalize_rrn", "format_rrn",
]


# ── 사업자등록번호 ────────────────────────────────────────────────────────────
def normalize_biz_reg_no(v: str | None) -> str:
    """구분자 제거 후 숫자만(digits-only 저장/비교용)."""
    return re.sub(r"[^0-9]", "", v or "")


def validate_biz_reg_no(v: str | None) -> bool:
    """숫자 10자리인지."""
    d = normalize_biz_reg_no(v)
    return len(d) == 10 and d.isdigit()


# 하위호환 별칭(기존 office_application_pg_service 호출부).
def is_valid_biz_reg_no(digits: str | None) -> bool:
    return len(digits or "") == 10 and (digits or "").isdigit()


def format_biz_reg_no(v: str | None) -> str:
    """표시/문서용 하이픈 형식(000-00-00000). 10자리가 아니면 원본 digits 반환."""
    d = normalize_biz_reg_no(v)
    return f"{d[:3]}-{d[3:5]}-{d[5:]}" if len(d) == 10 else d


# ── 전화번호 ──────────────────────────────────────────────────────────────────
def normalize_phone(v: str | None) -> str:
    return re.sub(r"[^0-9]", "", v or "")


def validate_phone(v: str | None) -> bool:
    """한국 전화 digits — 9~11자리, 0으로 시작."""
    d = normalize_phone(v)
    return 9 <= len(d) <= 11 and d.isdigit() and d[:1] == "0"


def is_valid_phone(digits: str | None) -> bool:
    d = digits or ""
    return 9 <= len(d) <= 11 and d.isdigit() and d[:1] == "0"


def format_phone(v: str | None) -> str:
    """표시/문서용 하이픈 형식. 규칙 밖이면 digits 원본."""
    d = normalize_phone(v)
    if d.startswith("02"):
        if len(d) == 9:
            return f"{d[:2]}-{d[2:5]}-{d[5:]}"      # 02-123-4567
        if len(d) == 10:
            return f"{d[:2]}-{d[2:6]}-{d[6:]}"      # 02-1234-5678
    else:
        if len(d) == 10:
            return f"{d[:3]}-{d[3:6]}-{d[6:]}"      # 010-123-4567 / 031-123-4567
        if len(d) == 11:
            return f"{d[:3]}-{d[3:7]}-{d[7:]}"      # 010-1234-5678
    return d


# ── 주민등록번호(표시/문서 형식만 — 저장/검증/암호화는 pii_crypto) ──────────────
def normalize_rrn(v: str | None) -> str:
    """숫자만(13자리). 문서/암호화 입력 정규화용."""
    return re.sub(r"[^0-9]", "", v or "")


def format_rrn(v: str | None) -> str:
    """문서용 하이픈 형식(000000-0000000). 13자리가 아니면 원본 digits 반환."""
    d = normalize_rrn(v)
    return f"{d[:6]}-{d[6:]}" if len(d) == 13 else d
