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


def _get_fernet_by_env(primary_env: str, fallback_env: Optional[str] = None):
    """주어진 환경변수(없으면 fallback_env)의 key 로 Fernet 인스턴스 생성(키 값별 캐시).

    key 없음/형식오류 → PiiKeyMissing. 메시지에 평문/키값을 넣지 않는다.
    """
    key = (os.environ.get(primary_env) or (os.environ.get(fallback_env) if fallback_env else "") or "").strip()
    if not key:
        raise PiiKeyMissing("PII encryption key is not configured")
    if key not in _fernet_cache:
        from cryptography.fernet import Fernet
        try:
            _fernet_cache[key] = Fernet(key.encode("utf-8"))
        except Exception:
            raise PiiKeyMissing("PII encryption key is invalid")
    return _fernet_cache[key]


def _get_fernet():
    """행정사 RRN 용 Fernet(기존 호환). key: KID_PII_ENCRYPTION_KEY (fallback AGENT_RRN_ENCRYPTION_KEY)."""
    return _get_fernet_by_env(_KEY_ENV, _KEY_ENV_FALLBACK)


def crypto_available() -> bool:
    """행정사 RRN key 가 설정되어 사용 가능한지(저장 UI 가드/진단용). 평문 노출 없음."""
    try:
        _get_fernet()
        return True
    except PiiCryptoError:
        return False


# ── 고객 외국인등록번호 뒷자리(reg_back) 범용 PII 암호화 ─────────────────────────
# 행정사 RRN(13자리 형식강제)과 달리 고객 reg_back(7자리)·기타 단순 식별번호를 위한
# 범용 함수. 키는 CUSTOMER_PII_ENCRYPTION_KEY 로 분리(미설정 시 KID_PII_ENCRYPTION_KEY
# 로 fallback — 로컬/전환기 호환). HMAC 검색키는 PII_HASH_SECRET.

_CUSTOMER_KEY_ENV = "CUSTOMER_PII_ENCRYPTION_KEY"
_CUSTOMER_KEY_FALLBACK = "KID_PII_ENCRYPTION_KEY"
_HASH_SECRET_ENV = "PII_HASH_SECRET"


def is_server_env() -> bool:
    """운영(server) 환경 여부. HANWOORY_ENV 또는 RUN_ENV 가 'server' 이면 True.

    운영에서는 키 미설정 시 평문 저장을 거부(fail-closed)하기 위한 판별.
    로컬/테스트(기본 'local')는 graceful fallback 을 허용한다.
    """
    v = (os.environ.get("HANWOORY_ENV") or os.environ.get("RUN_ENV") or "").strip().lower()
    return v == "server"


def hash_secret_available() -> bool:
    """HMAC 검색 비밀키(PII_HASH_SECRET) 설정 여부(검색 가드/진단용)."""
    return bool((os.environ.get(_HASH_SECRET_ENV) or "").strip())

# 암호화/알고리즘 버전 태그(향후 key rotation / 알고리즘 교체 시 분기용).
REG_BACK_ENC_VERSION = "v1"

_DIGITS = re.compile(r"\d")


def normalize_reg_back(value: Optional[str]) -> str:
    """저장/해시 전 정규화 — 숫자만 추출. 형식 강제는 하지 않는다(7자리 아님도 허용하되
    호출측이 last4/hash 산정에 사용). 빈 값은 빈 문자열."""
    return "".join(_DIGITS.findall(str(value or "")))


def mask_reg_back(value: Optional[str]) -> str:
    """표시용 마스킹(첫 자리 보존): ``1234567`` → ``1******``.

    - 만기조회 세기판별이 첫 자리에 의존하므로 첫 자리를 보존한다.
    - **멱등**: 이미 마스킹된 ``1******`` 를 다시 넣어도 그대로 반환(별 포함 시).
    - 빈 값/숫자 없음 → 빈 문자열.
    """
    s = str(value or "")
    if not s.strip():
        return ""
    if "*" in s:
        return s  # already masked (idempotent)
    d = normalize_reg_back(s)
    if not d:
        return ""
    return d[0] + ("*" * (len(d) - 1))


def last4_reg_back(value: Optional[str]) -> str:
    """뒤 4자리(검색/표시 보조). 4자리 미만이면 있는 만큼. 이미 마스킹된 값은 빈 문자열."""
    s = str(value or "")
    if "*" in s:
        return ""
    d = normalize_reg_back(s)
    return d[-4:] if d else ""


def _customer_fallback_env(key_env: str) -> Optional[str]:
    """고객 키 fallback 정책: **local/test 만** KID 키로 fallback. **server(운영)는 금지.**

    server 환경에서 CUSTOMER_PII_ENCRYPTION_KEY 가 없으면 KID 로 대체하지 않고
    PiiKeyMissing → 호출측 503(fail-closed).
    """
    if key_env != _CUSTOMER_KEY_ENV:
        return None
    return None if is_server_env() else _CUSTOMER_KEY_FALLBACK


def customer_pii_available() -> bool:
    """고객 PII 암호화 key 가 사용 가능한지(저장 가드/진단). 평문 노출 없음.

    server 환경에서는 KID fallback 을 적용하지 않으므로 CUSTOMER 키가 있어야 True.
    """
    try:
        _get_fernet_by_env(_CUSTOMER_KEY_ENV, _customer_fallback_env(_CUSTOMER_KEY_ENV))
        return True
    except PiiCryptoError:
        return False


def encrypt_pii(plain: Optional[str], key_env: str = _CUSTOMER_KEY_ENV) -> str:
    """범용 PII 평문 → 암호문(str). 빈 값은 빈 문자열. 키 없음 → PiiKeyMissing.

    형식 검증을 하지 않으므로 호출측에서 normalize 후 전달할 것.
    server 환경은 KID fallback 금지(fail-closed).
    """
    s = str(plain or "")
    if not s:
        return ""
    f = _get_fernet_by_env(key_env, _customer_fallback_env(key_env))
    return f.encrypt(s.encode("utf-8")).decode("utf-8")


def decrypt_pii(cipher: Optional[str], key_env: str = _CUSTOMER_KEY_ENV) -> str:
    """범용 암호문 → 평문(str). 빈 입력은 빈 문자열. 실패 시 PiiDecryptError(메시지에 평문 없음).

    server 환경은 KID fallback 금지.
    """
    if not cipher:
        return ""
    f = _get_fernet_by_env(key_env, _customer_fallback_env(key_env))
    try:
        return f.decrypt(str(cipher).encode("utf-8")).decode("utf-8")
    except PiiCryptoError:
        raise
    except Exception:
        raise PiiDecryptError("pii decrypt failed")


def hash_pii(tenant_id: str, plain: Optional[str], secret_env: str = _HASH_SECRET_ENV) -> str:
    """검색용 HMAC-SHA256(hex). 단순 SHA256은 7자리 무차별대입 위험 → 테넌트별 솔트 효과의 HMAC.

    비밀키(PII_HASH_SECRET) 미설정이면 빈 문자열(검색 비활성, fail-safe). 빈 값도 빈 문자열.
    """
    import hashlib
    import hmac as _hmac

    norm = normalize_reg_back(plain)
    if not norm:
        return ""
    secret = (os.environ.get(secret_env) or "").strip()
    if not secret:
        return ""
    msg = f"{tenant_id}:{norm}".encode("utf-8")
    return _hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()


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
