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
from backend.services.ocr_service import (
    _parse_mrz_pair,
    _strip_name_trailing_k,
    find_best_mrz_pair_from_text,
    _mrz_check_digit,
)


def _build_l2(doc, nat, birth, sex, exp, optional="<" * 14):
    """synthetic TD3 L2(44자) 생성 — check digit을 함수로 계산(하드코딩 아님)."""
    doc9 = (doc + "<" * 9)[:9]
    dcd = _mrz_check_digit(doc9)
    bcd = _mrz_check_digit(birth)
    ecd = _mrz_check_digit(exp)
    opt = (optional + "<" * 14)[:14]
    ocd = _mrz_check_digit(opt)
    comp = doc9 + dcd + birth + bcd + exp + ecd + opt + ocd
    ccd = _mrz_check_digit(comp)
    l2 = doc9 + dcd + nat + birth + bcd + sex + exp + ecd + opt + ocd + ccd
    assert len(l2) == 44
    return l2


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
    # 허용: 한글·영문·숫자·공백·하이픈·쉼표 / 제거: 세로줄·느낌표·대괄호·소괄호·점
    ("경기도 시흥시 군서마을로 12, 101호 ㅣ", "경기도 시흥시 군서마을로 12, 101호"),
    ("서울특별시 영등포구 63로 50-1 |", "서울특별시 영등포구 63로 50-1"),   # 하이픈 보존
    ("경기 도 시흥 시 군서마을로 12 (101호)", "경기 도 시흥 시 군서마을로 12 101호"),  # 소괄호 문자만 제거
    ("경기도 시흥시 군서마을로 12, 101호 ABCㅣ", "경기도 시흥시 군서마을로 12, 101호 ABC"),  # 영문 허용
    # 느낌표 + 대괄호(내용까지 제거)
    ("! 경기도 시흥시 큰솔공원로 28, 1번길 11, 103호 [잡음]",
     "경기도 시흥시 큰솔공원로 28, 1번길 11, 103호"),
    # 영문 빌딩명 포함 주소 유지
    ("경기도 시흥시 ABC빌딩 12, 101호", "경기도 시흥시 ABC빌딩 12, 101호"),
])
def test_clean_address(raw, expected):
    assert _clean_address_text(raw) == expected


@pytest.mark.parametrize("raw", [
    # province('경기')가 OCR 누락돼도 cleaned 후보를 빈값으로 만들지 않는다.
    "! 도 시흥시 큰솔공원로 미 .28 ㅣ ㅣ 103호",
])
def test_clean_address_weak_candidate_not_blank(raw):
    out = _clean_address_text(raw)
    assert out != ""                      # 빈값이 아니어야 함
    assert "시흥시" in out and "103호" in out
    assert "!" not in out and "ㅣ" not in out and "." not in out


# ── MRZ trailing-K 정리 ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("PARK", "PARK"),              # 단일 K 종료 → 보존
    ("MALIK", "MALIK"),
    ("NOVAK", "NOVAK"),
    ("KIM", "KIM"),               # K 시작 → 보존
    ("ERIKSSON", "ERIKSSON"),
    ("ANNA MARIAKKKK", "ANNA MARIA"),  # 끝의 반복 K(=filler) 제거
    ("WUKKKK", "WU"),
    ("KKK", "KKK"),               # 앞 실명 부족 → 보수적으로 보존
])
def test_strip_name_trailing_k(raw, expected):
    assert _strip_name_trailing_k(raw) == expected


# ICAO TD3 표준 명세 문자열(개인정보 아님). nat='UTO'.
_ICAO_L2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"


def test_mrz_trailing_k_cleaned():
    # 이름존 filler '<' 19자가 OCR에서 'K'로 오인된 경우.
    l1 = "P<UTOERIKSSON<<ANNA<MARIA" + "K" * 19
    assert len(l1) == 44
    out = _parse_mrz_pair(l1, _ICAO_L2)
    assert out.get("성") == "ERIKSSON"
    assert out.get("명") == "ANNA MARIA"   # trailing K filler 제거


def test_mrz_real_k_preserved():
    # 실제 K가 든 성/이름은 손상하지 않는다.
    l1 = "P<UTOKIM<<KOVAK" + "<" * 29
    assert len(l1) == 44
    out = _parse_mrz_pair(l1, _ICAO_L2)
    assert out.get("성") == "KIM"          # K-initial 성 보존
    assert out.get("명") == "KOVAK"        # 단일 K 종료 보존


def test_mrz_normal_filler_unaffected():
    # 정상 '<' filler는 그대로 통과.
    l1 = "P<UTOERIKSSON<<ANNA<MARIA" + "<" * 19
    assert len(l1) == 44
    out = _parse_mrz_pair(l1, _ICAO_L2)
    assert out.get("성") == "ERIKSSON"
    assert out.get("명") == "ANNA MARIA"


# ── L1 이름영역 패딩-K 잡음 제거(컴포넌트 단위, 일반화) ──────────────────────

@pytest.mark.parametrize("l1,sur,given", [
    # 패딩 구간 '<<<<K' → given에서 K 제거
    ("P<CHNPIAO<<MINGJUN<<<<K" + "<" * 21, "PIAO", "MINGJUN"),
    # 실제 K 보존
    ("P<KORKIM<<KOVAK" + "<" * 29, "KIM", "KOVAK"),
    ("P<KORPARK<<MALIK" + "<" * 28, "PARK", "MALIK"),
    ("P<GBRNOVAK<<ANNA" + "<" * 28, "NOVAK", "ANNA"),
    # 다중 컴포넌트 이름 보존
    ("P<UZBSHOHRUHBEK<<ABDIHAKIM<ABDIHA" + "<" * 11, "SHOHRUHBEK", "ABDIHAKIM ABDIHA"),
])
def test_mrz_name_filler_k(l1, sur, given):
    assert len(l1) == 44
    out = _parse_mrz_pair(l1, _ICAO_L2)
    assert out.get("성") == sur
    assert out.get("명") == given


# ── L1 prefix 'P<' 보정(2번째 문자 한정) ─────────────────────────────────────

@pytest.mark.parametrize("l1", [
    "POCHNPIAO<<MINGJUN" + "<" * 26,   # '<'가 O로 오인
    "P0CHNPIAO<<MINGJUN" + "<" * 26,   # '<'가 0으로 오인
])
def test_mrz_l1_prefix_fix(l1):
    assert len(l1) == 44
    out = _parse_mrz_pair(l1, _ICAO_L2)
    assert out.get("성") == "PIAO"
    assert out.get("명") == "MINGJUN"


# ── L2 후보 선택: 앞글자(E) 누락 후보보다 check-digit 통과 후보 우선 ──────────

def test_mrz_pair_selection_prefers_doc_checkdigit():
    # 정상 여권번호 'EF6806032'로 완전 유효한 L2 생성.
    good_l2 = _build_l2("EF6806032", "CHN", "791210", "M", "290312")
    l1 = "P<CHNPIAO<<MINGJUN" + "<" * 26
    # 앞글자 E가 누락된 잡음 후보(43자 → pad44로 'F68060322…<').
    bad_l2 = good_l2[1:]
    # 잡음 후보를 먼저, 좋은 후보를 뒤에 배치(인접 윈도우로는 못 고르던 케이스).
    text = "\n".join([l1, bad_l2, l1, good_l2])
    L1, L2, score = find_best_mrz_pair_from_text(text)
    parsed = _parse_mrz_pair(L1, L2)
    assert parsed.get("여권") == "EF6806032"   # 앞글자 E 보존
    assert not parsed.get("여권", "").startswith("F68")


def test_mrz_good_pair_passes_all_checkdigits():
    good_l2 = _build_l2("EF6806032", "CHN", "791210", "M", "290312")
    rep = _mrz_check_report("P<CHNPIAO<<MINGJUN" + "<" * 26, good_l2)
    assert rep["doc_check_ok"] and rep["birth_check_ok"] and rep["expiry_check_ok"]
    assert rep["doc_number"] == "EF6806032"
