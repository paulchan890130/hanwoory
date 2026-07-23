"""한국 식별자 형식/검증 공통 helper 테스트."""
from backend.services.korean_identifier_format import (
    normalize_biz_reg_no, format_biz_reg_no, validate_biz_reg_no,
    normalize_phone, format_phone, validate_phone,
    normalize_rrn, format_rrn,
)


def test_biz_normalize_and_validate():
    assert normalize_biz_reg_no("213-12-37464") == "2131237464"
    assert validate_biz_reg_no("213-12-37464") is True
    assert validate_biz_reg_no("21312") is False
    assert validate_biz_reg_no("") is False


def test_biz_format():
    assert format_biz_reg_no("2131237464") == "213-12-37464"
    assert format_biz_reg_no("213-12-37464") == "213-12-37464"
    assert format_biz_reg_no("21312") == "21312"   # 규칙 밖 → digits 원본


def test_phone_normalize_and_validate():
    assert normalize_phone("010-1234-5678") == "01012345678"
    assert validate_phone("010-1234-5678") is True
    assert validate_phone("02-123-4567") is True
    assert validate_phone("1234") is False
    assert validate_phone("11012345678") is False   # 0 으로 시작 안 함


def test_phone_format():
    assert format_phone("01012345678") == "010-1234-5678"
    assert format_phone("0212345678") == "02-1234-5678"
    assert format_phone("021234567") == "02-123-4567"
    assert format_phone("0311234567") == "031-123-4567"


def test_rrn_format():
    assert normalize_rrn("900101-1234567") == "9001011234567"
    assert format_rrn("9001011234567") == "900101-1234567"
    assert format_rrn("900101-1234567") == "900101-1234567"
    assert format_rrn("9001") == "9001"   # 규칙 밖 → digits 원본


def test_office_application_backcompat_reexports():
    # 기존 호출부 하위호환 — office_application_pg_service 가 재노출.
    from backend.services import office_application_pg_service as oa
    assert oa.normalize_biz_reg_no("213-12-37464") == "2131237464"
    assert oa.format_phone("01012345678") == "010-1234-5678"
    assert oa.is_valid_biz_reg_no("2131237464") is True
    assert oa.is_valid_phone("01012345678") is True
