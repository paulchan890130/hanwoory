"""
등록증 OCR 필드별 정규화(sanitizer) 단위 테스트.

OCR 엔진(Tesseract) 불필요 — raw OCR 텍스트 문자열을 입력으로 받아
정리된 값을 검증한다(순수함수). 실행:

    .venv\\Scripts\\python.exe -m pytest backend/tests/test_ocr_normalizers.py -q
"""
import pytest

from backend.services.roi_ocr_service import (
    clean_korean_name,
    clean_reg_front,
    clean_reg_back,
    _clean_address_text,
)


@pytest.mark.parametrize("raw,expected", [
    ("(홍길동)", "홍길동"),
    ("홍길동ㅣ", "홍길동"),
    ("성명 홍길동", "홍길동"),
    ("姓名 홍길동", "홍길동"),
    ("김라파엘라", "김라파엘라"),   # 외국인 6자 한글이름
])
def test_clean_korean_name(raw, expected):
    assert clean_korean_name(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("900101ㅣ", "900101"),
    ("900101 |", "900101"),
    ("1990-01-01", "900101"),
    ("1990.01.01", "900101"),
    ("19900101", "900101"),
    ("9001011", "900101"),          # 뒤에 노이즈 숫자 1자
    ("2025-13-45 noise", ""),       # 월/일 범위 위반 → 빈값
])
def test_clean_reg_front(raw, expected):
    assert clean_reg_front(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("1234567ㅣ", "1234567"),
    ("1234567-", "1234567"),
    ("1 2 3 4 5 6 7", "1234567"),
    ("1 234567", "1234567"),
    ("foo 5678901 bar", "5678901"),  # 첫자리 5~9 유효 후보 우선
])
def test_clean_reg_back(raw, expected):
    assert clean_reg_back(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    # 허용: 한글·숫자·공백·하이픈·쉼표 / 제거: 세로줄·영문·괄호·점
    ("경기도 시흥시 군서마을로 12, 101호 ㅣ", "경기도 시흥시 군서마을로 12, 101호"),
    ("서울특별시 영등포구 63로 50-1 |", "서울특별시 영등포구 63로 50-1"),   # 하이픈 보존
    ("경기 도 시흥 시 군서마을로 12 (101호)", "경기 도 시흥 시 군서마을로 12 101호"),  # 괄호 제거
    ("경기도 시흥시 군서마을로 12, 101호 ABCㅣ", "경기도 시흥시 군서마을로 12, 101호"),  # 영문 제거
])
def test_clean_address(raw, expected):
    assert _clean_address_text(raw) == expected
