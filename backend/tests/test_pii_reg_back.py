"""고객 reg_back 암호화 유틸 + _row_to_dict 마스킹/복호화 단위테스트.

DB 불필요(crypto + _row_to_dict 는 ORM row 대신 SimpleNamespace 로 검증).
실행: pytest backend/tests/test_pii_reg_back.py
"""
import os
from types import SimpleNamespace

from cryptography.fernet import Fernet

# 테스트용 키/시크릿 주입(모듈 import 전에).
os.environ.setdefault("CUSTOMER_PII_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("PII_HASH_SECRET", "unit-test-secret")

from backend.services import pii_crypto as p  # noqa: E402
from backend.services.customer_pg_service import _row_to_dict  # noqa: E402


def test_normalize_reg_back():
    assert p.normalize_reg_back("1-234567") == "1234567"
    assert p.normalize_reg_back("123 4567") == "1234567"
    assert p.normalize_reg_back("") == ""


def test_encrypt_decrypt_roundtrip():
    norm = "1234567"
    c = p.encrypt_pii(norm)
    assert c and c != norm
    assert p.decrypt_pii(c) == norm
    # 같은 입력도 암호문은 매번 다름(Fernet IV)
    assert p.encrypt_pii(norm) != p.encrypt_pii(norm)


def test_mask_first_digit_preserved_and_idempotent():
    assert p.mask_reg_back("1234567") == "1******"
    assert p.mask_reg_back("1******") == "1******"   # idempotent
    assert p.mask_reg_back("") == ""


def test_last4():
    assert p.last4_reg_back("1234567") == "4567"
    assert p.last4_reg_back("1******") == ""


def test_hash_tenant_salted():
    h1 = p.hash_pii("t1", "1234567")
    h2 = p.hash_pii("t2", "1234567")
    assert h1 and h2 and h1 != h2          # 테넌트별 솔트
    assert p.hash_pii("t1", "1234567") == h1  # 결정적


def _row(**kw):
    base = dict(customer_id="0001", tenant_id="t1", korean_name="홍길동",
                reg_front="900101", reg_back="", reg_back_encrypted=None,
                reg_back_last4=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_row_to_dict_masks_plaintext_fallback():
    # 평문 reg_back(미변환 행) → 목록은 마스킹(첫자리 보존)
    row = _row(reg_back="1234567")
    out = _row_to_dict(row, reveal=False)
    assert out["번호"] == "1******"
    assert out["번호_last4"] == "4567"


def test_row_to_dict_reveal_decrypts():
    norm = "1234567"
    row = _row(reg_back=norm, reg_back_encrypted=p.encrypt_pii(norm),
               reg_back_last4="4567")
    # reveal=False → 마스킹
    assert _row_to_dict(row, reveal=False)["번호"] == "1******"
    # reveal=True → 평문
    assert _row_to_dict(row, reveal=True)["번호"] == norm


def test_search_hash_equality_basis():
    # 검색(7자리 HMAC)은 동일 입력에 대해 동일 해시로 매칭된다.
    stored = p.hash_pii("t1", "1234567")
    query = p.hash_pii("t1", "1-234567")   # 정규화 후 동일
    assert stored and stored == query


def test_server_env_blocks_kid_fallback():
    import pytest
    saved_cust = os.environ.pop("CUSTOMER_PII_ENCRYPTION_KEY", None)
    os.environ["KID_PII_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    os.environ["HANWOORY_ENV"] = "server"
    try:
        # server: CUSTOMER 키 없으면 KID fallback 금지 → PiiKeyMissing(fail-closed)
        with pytest.raises(p.PiiKeyMissing):
            p.encrypt_pii("1234567")
        assert p.customer_pii_available() is False
    finally:
        os.environ.pop("HANWOORY_ENV", None)
        os.environ.pop("KID_PII_ENCRYPTION_KEY", None)
        if saved_cust is not None:
            os.environ["CUSTOMER_PII_ENCRYPTION_KEY"] = saved_cust
    # local(기본): CUSTOMER 키 복원 → 정상 사용 가능
    assert p.customer_pii_available() is True


def test_log_filter_masks_sensitive_keys_and_full_rrn():
    from backend.services.pii_log_filter import _mask
    # 민감 key 에 붙은 7자리 → 첫자리 보존 마스킹(뒤 6자리 마스킹)
    assert _mask("reg_back=1234567") == "reg_back=1******"
    assert _mask('"번호": "1234567"') == '"번호": "1******"'
    assert _mask("provider_reg_back='7654321'") == "provider_reg_back='7******'"
    # 전체형 주민/외국인등록번호(13자리, dash 포함) 마스킹
    assert _mask("900101-1234567") == "900101-*******"
    # 무관한 7자리(키 없음)는 마스킹하지 않음(과마스킹 방지)
    assert _mask("order 1234567 done") == "order 1234567 done"
