"""PII(주민등록번호) 대칭 암호화 서비스 — Phase I-1J-6E.

행정사 주민등록번호(agent_rrn)를 **복호화 가능한 암호문**으로만 저장/조회하기 위한 모듈.
PDF 자동출력에 쓰려면 복호화가 가능해야 하므로 hash(단방향)가 아니라 Fernet(AES128-CBC+HMAC)
대칭 암호를 쓴다. agent_rrn_hash 는 검증/기록용으로 남길 수 있으나 **출력 소스가 될 수 없다.**

보안 원칙:
- 평문을 DB/로그/응답에 절대 남기지 않는다. 이 모듈도 예외 메시지에 평문을 넣지 않는다.
- 암호화 key 는 repo 에 커밋하지 않는다. 환경변수 ``KID_PII_ENCRYPTION_KEY`` (없으면 fallback
  ``AGENT_RRN_ENCRYPTION_KEY``) 로만 주입한다(로컬은 gitignored docker-compose.override.yml).
- key 가 없으면 fail-safe: 저장(encrypt)은 명확한 PiiKeyMissing 으로 거부, 출력(decrypt)은
  호출측에서 blank 처리하도록 PiiDecryptError 를 던진다(PDF 생성 전체를 죽이지 않음).
"""
from __future__ import annotations

import os
import re
from typing import Optional

_KEY_ENV = "KID_PII_ENCRYPTION_KEY"
_KEY_ENV_FALLBACK = "AGENT_RRN_ENCRYPTION_KEY"

_RRN_DIGITS = re.compile(r"\d")
_RRN_FULL = re.compile(r"^\d{6}-\d{7}$")


class PiiCryptoError(RuntimeError):
    """PII 암호화 일반 오류(메시지에 평문 금지)."""


class PiiKeyMissing(PiiCryptoError):
    """암호화 key 미설정 — 저장은 거부, 출력은 blank 처리."""


class PiiDecryptError(PiiCryptoError):
    """복호화 실패(잘못된 토큰/키 불일치 등) — 출력은 blank 처리."""


class RrnFormatError(PiiCryptoError):
    """주민등록번호 형식 오류 — 저장 거부."""


_fernet_cache: dict = {}


def _get_fernet():
    """환경변수 key 로 Fernet 인스턴스를 만든다(키 값별 캐시). key 없으면 PiiKeyMissing."""
    key = (os.environ.get(_KEY_ENV) or os.environ.get(_KEY_ENV_FALLBACK) or "").strip()
    if not key:
        raise PiiKeyMissing("PII encryption key is not configured")
    if key not in _fernet_cache:
        from cryptography.fernet import Fernet
        try:
            _fernet_cache[key] = Fernet(key.encode("utf-8"))
        except Exception:
            # 잘못된 형식의 key — 평문과 무관하므로 메시지에 민감정보 없음.
            raise PiiKeyMissing("PII encryption key is invalid")
    return _fernet_cache[key]


def crypto_available() -> bool:
    """key 가 설정되어 사용 가능한지(저장 UI 가드/진단용). 평문 노출 없음."""
    try:
        _get_fernet()
        return True
    except PiiCryptoError:
        return False


# ── 형식 검증/정규화 ──────────────────────────────────────────────────────────

def _only_digits(raw: str) -> str:
    return "".join(_RRN_DIGITS.findall(str(raw or "")))


def validate_rrn_format(plain: str) -> bool:
    """주민등록번호 형식 검증. 13자리 숫자 + 월(01-12)/일(01-31) + 성별코드(1-8) 만 본다.
    엄격한 체크섬은 적용하지 않는다(실무상 일부 번호가 막히는 것을 방지)."""
    d = _only_digits(plain)
    if len(d) != 13:
        return False
    mm, dd, g = d[2:4], d[4:6], d[6]
    if not ("01" <= mm <= "12"):
        return False
    if not ("01" <= dd <= "31"):
        return False
    if g not in "12345678":
        return False
    return True


def normalize_rrn(plain: str) -> str:
    """저장 전 ``000000-0000000`` 형태로 정규화. 형식 불일치 시 RrnFormatError."""
    d = _only_digits(plain)
    if len(d) != 13 or not validate_rrn_format(d):
        raise RrnFormatError("agent_rrn format invalid")
    return f"{d[:6]}-{d[6:]}"


def mask_rrn(plain: str) -> str:
    """표시용 마스킹: ``000000-*******``. 비정상 입력이면 빈 문자열."""
    d = _only_digits(plain)
    if len(d) != 13:
        return ""
    return f"{d[:6]}-*******"


def rrn_last4(plain: str) -> str:
    """마지막 4자리(표시 보조용). 비정상 입력이면 빈 문자열."""
    d = _only_digits(plain)
    return d[-4:] if len(d) == 13 else ""


# ── 암복호화 ──────────────────────────────────────────────────────────────────

def encrypt_agent_rrn(plain: str) -> str:
    """정규화된 평문 RRN → 암호문(str). 형식 오류 RrnFormatError / key 없음 PiiKeyMissing."""
    norm = normalize_rrn(plain)  # 형식 보장
    f = _get_fernet()
    token = f.encrypt(norm.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_agent_rrn(cipher: Optional[str]) -> str:
    """암호문 → 평문 RRN(str). 빈 입력은 빈 문자열. 실패 시 PiiDecryptError(메시지에 평문 없음)."""
    if not cipher:
        return ""
    f = _get_fernet()  # key 없으면 PiiKeyMissing(PiiDecryptError 의 형제) 전파
    try:
        return f.decrypt(str(cipher).encode("utf-8")).decode("utf-8")
    except PiiCryptoError:
        raise
    except Exception:
        raise PiiDecryptError("agent_rrn decrypt failed")
