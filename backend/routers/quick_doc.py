"""문서 자동작성 라우터 - 체류/사증 선택 트리 + 필요서류 + PDF 생성 (full injection)"""
import sys, os, io, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from backend.auth import get_current_user

router = APIRouter()

# ── 기본 경로 ─────────────────────────────────────────────────────────────────
_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TEMPLATES_DIR = os.path.join(_BASE, "templates")
_CIRCLE_PATH   = os.path.join(_TEMPLATES_DIR, "원형 배경.png")
_FONT_PATH     = os.path.join(_BASE, "fonts", "HJ한전서B.ttf")
_SEAL_SIZE     = 200

# ── 선택 트리 데이터 ──────────────────────────────────────────────────────────

CATEGORY_OPTIONS = ["체류", "사증"]

MINWON_OPTIONS: dict = {
    "체류": ["등록", "연장", "변경", "부여", "신고", "기타"],
    "사증": ["준비중"],
}

TYPE_OPTIONS: dict = {
    ("체류", "등록"): ["F", "H2", "E7"],
    ("체류", "연장"): ["F", "H2", "E7"],
    ("체류", "변경"): ["F", "H2", "E7", "국적", "D"],
    ("체류", "부여"): ["F"],
    ("체류", "신고"): ["주소", "등록사항"],
    ("체류", "기타"): ["D"],
    ("사증", "준비중"): ["x"],
}

SUBTYPE_OPTIONS: dict = {
    ("체류", "등록", "F"): ["1", "2", "3", "4", "5", "6"],
    ("체류", "등록", "H2"): [],
    ("체류", "등록", "E7"): [],
    ("체류", "연장", "F"): ["1", "2", "3", "4", "5", "6"],
    ("체류", "연장", "H2"): [],
    ("체류", "연장", "E7"): [],
    ("체류", "변경", "F"): ["1", "2", "3", "4", "5", "6"],
    ("체류", "변경", "H2"): [],
    ("체류", "변경", "E7"): [],
    ("체류", "변경", "국적"): ["일반", "간이", "특별"],
    ("체류", "변경", "D"): ["2", "4", "8", "10"],
    ("체류", "부여", "F"): ["2", "3", "5"],
    ("체류", "신고", "주소"): [],
    ("체류", "신고", "등록사항"): [],
    ("체류", "기타", "D"): ["2", "4", "8", "10"],
    ("사증", "준비중", "x"): [],
}

REQUIRED_DOCS: dict = {
    # 체류-등록-F
    ("체류", "등록", "F", "1"): {"main": ["통합신청서", "비취업 서약서", "신원보증서", "거주숙소 제공 확인서", "재학신고서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "등록", "F", "2"): {"main": ["통합신청서", "직업신고서", "신원보증서", "거주숙소 제공 확인서", "재학신고서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "등록", "F", "3"): {"main": ["통합신청서", "비취업 서약서", "신원보증서", "거주숙소 제공 확인서", "재학신고서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "등록", "F", "4"): {"main": ["통합신청서", "직업신고서", "단순노무 비취업 서약서", "한글성명 병기 신청서", "거주숙소 제공 확인서", "재학신고서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "등록", "F", "6"): {"main": ["통합신청서", "직업신고서", "신원보증서", "거주숙소 제공 확인서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "등록", "H2", ""): {"main": ["통합신청서", "직업신고서", "한글성명 병기 신청서", "거주숙소 제공 확인서", "치료예정 서약서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "등록", "E7", ""): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
    # 체류-연장
    ("체류", "연장", "F", "1"): {"main": ["통합신청서", "비취업 서약서", "신원보증서", "거주숙소 제공 확인서", "재학신고서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "연장", "F", "2"): {"main": ["통합신청서", "직업신고서", "신원보증서", "거주숙소 제공 확인서", "재학신고서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "연장", "F", "3"): {"main": ["통합신청서", "비취업 서약서", "신원보증서", "거주숙소 제공 확인서", "재학신고서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "연장", "F", "4"): {"main": ["통합신청서", "직업신고서", "한글성명 병기 신청서", "거주숙소 제공 확인서", "재학신고서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "연장", "F", "6"): {"main": ["통합신청서", "직업신고서", "신원보증서", "거주숙소 제공 확인서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "연장", "H2", ""): {"main": ["통합신청서", "직업신고서", "한글성명 병기 신청서", "거주숙소 제공 확인서", "치료예정 서약서", "법령준수 확인서", "비취업 확인서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "연장", "E7", ""): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
    # 체류-변경
    ("체류", "변경", "F", "1"): {"main": ["통합신청서", "비취업 서약서", "신원보증서", "거주숙소 제공 확인서", "재학신고서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "변경", "F", "2"): {"main": ["통합신청서", "직업신고서", "결혼배경진술서", "초청장", "직업 및 연간 소득금액 신고서", "신원보증서", "거주숙소 제공 확인서", "재학신고서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "변경", "F", "3"): {"main": ["통합신청서", "비취업 서약서", "신원보증서", "거주숙소 제공 확인서", "재학신고서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "변경", "F", "4"): {"main": ["통합신청서", "직업신고서", "단순노무 비취업 서약서", "한글성명 병기 신청서", "거주숙소 제공 확인서", "재학신고서", "법령준수 확인서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "변경", "F", "5"): {"main": ["통합신청서", "직업신고서", "한글성명 병기 신청서", "신원보증서", "거주숙소 제공 확인서", "재학신고서", "정보제공동의서", "신청자 기본정보", "심사보고서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "변경", "F", "6"): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "변경", "H2", ""): {"main": ["통합신청서", "직업신고서", "한글성명 병기 신청서", "거주숙소 제공 확인서", "치료예정 서약서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "변경", "E7", ""): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "변경", "국적", "일반"): {"main": ["준비중"], "agent": []},
    ("체류", "변경", "국적", "간이"): {"main": ["준비중"], "agent": []},
    ("체류", "변경", "국적", "특별"): {"main": ["준비중"], "agent": []},
    ("체류", "변경", "D", "2"): {"main": ["통합신청서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "변경", "D", "4"): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "변경", "D", "8"): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "변경", "D", "10"): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
    # 체류-부여
    ("체류", "부여", "F", "2"): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "부여", "F", "3"): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "부여", "F", "5"): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
    # 체류-신고
    ("체류", "신고", "주소", ""): {"main": ["통합신청서", "거주숙소 제공 확인서"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "신고", "등록사항", ""): {"main": ["통합신청서"], "agent": ["위임장", "대행업무수행확인서"]},
    # 사증
    ("사증", "준비중", "", ""): {"main": ["준비중"], "agent": []},
}

DOC_TEMPLATES: dict = {
    # ── 공통 양식 (실제 파일 존재 확인 완료) ──────────────────────────────
    "통합신청서":             "templates/통합신청서.pdf",
    "통합신청서1":            "templates/통합신청서1.pdf",
    "비취업 서약서":           "templates/비취업서약서.pdf",
    "신원보증서":             "templates/신원보증서.pdf",
    "거주숙소 제공 확인서":    "templates/거주숙소제공확인서.pdf",
    "재학신고서":             "templates/재학신고서.pdf",
    "직업신고서":             "templates/직업신고서.pdf",
    "한글성명 병기 신청서":    "templates/한글성명병기신청서.pdf",
    "단순노무 비취업 서약서":  "templates/단순노무비취업서약서.pdf",
    "치료예정 서약서":         "templates/치료예정서약서.pdf",
    "법령준수 확인서":         "templates/법령준수확인서.pdf",
    "비취업 확인서":           "templates/비취업확인서.pdf",
    "정보제공동의서":          "templates/정보제공동의서.pdf",
    "위임장":                 "templates/위임장.pdf",
    "위임장1":                "templates/위임장1.pdf",
    "하이코리아":             "templates/하이코리아.pdf",
    "소시넷":                 "templates/소시넷.pdf",
    "대행업무수행확인서":      "templates/대행업무수행확인서.pdf",
    "대행업무수행확인서1":     "templates/대행업무수행확인서1.pdf",
    # ── 비자별 통합신청서 (F계열) ─────────────────────────────────────────
    "F1_등록":               "templates/F1_등록.pdf",
    "F1_연장":               "templates/F1_연장.pdf",
    "F1_연장_전자":           "templates/F1_연장 전자.pdf",
    "F1_자격변경":            "templates/F1_자격변경.pdf",
    "F1_등록사항변경":         "templates/F1_등록사항 변경.pdf",
    "F2_연장":               "templates/F2_연장.pdf",
    "F2_자격변경":            "templates/F2_자격변경.pdf",
    "F3_등록":               "templates/F3_등록.pdf",
    "F3_자격변경":            "templates/F3_자격변경.pdf",
    "F4_등록":               "templates/F4_등록.pdf",
    "F4_연장":               "templates/F4_연장.pdf",
    "F4_연장_전자":           "templates/F4_연장 전자.pdf",
    "F4_자격변경":            "templates/F4_자격변경.pdf",
    "F4_자격변경_전자":        "templates/F4_자격변경 전자.pdf",
    "F4_등록사항변경":         "templates/F4_등록사항 변경.pdf",
    "F4_체류지변경":           "templates/F4_체류지 변경.pdf",
    "F5_자격변경":            "templates/F5_자격변경.pdf",
    "F5_등록사항변경":         "templates/F5_등록사항 변경.pdf",
    # ── 비자별 통합신청서 (H2계열) ────────────────────────────────────────
    "H2_등록":               "templates/H2_등록.pdf",
    "H2_연장":               "templates/H2_연장.pdf",
    "H2_연장_전자":           "templates/H2_연장 전자.pdf",
    "H2_자격변경":            "templates/H2_자격변경.pdf",
    "H2_등록사항변경":         "templates/H2_등록사항 변경.pdf",
    # ── 파일 없음 — 명시적 None (추후 파일 추가 시 경로 입력) ─────────────
    # 아래 항목은 실제 PDF 파일이 없으므로 generate-full 요청 시
    # missing_docs 목록에 포함되어 사용자에게 명시적으로 알림.
    "결혼배경진술서":          None,   # templates/결혼배경진술서.pdf 필요
    "초청장":                 None,   # templates/초청장.pdf 필요
    "직업 및 연간 소득금액 신고서": None,  # templates/직업및연간소득금액신고서.pdf 필요
    "신청자 기본정보":         None,   # templates/신청자기본정보.pdf 필요
    "심사보고서":             None,   # templates/심사보고서.pdf 필요
    "준비중":                 None,   # 해당 민원 유형 미구현 (템플릿 없음)
}

# 역할별 도장 필드 이름 (PDF 위젯)
ROLE_WIDGETS: dict = {
    "applicant":     "yin",   # 신청인 (미성년자면 대리인 이름)
    "accommodation": "hyin",  # 숙소제공자
    "guarantor":     "byin",  # 신원보증인
    "guardian":      "gyin",  # 법정대리인 (별도 필드)
    "aggregator":    "pyin",  # 합산자
    "agent":         "ayin",  # 행정사
}

# ── 유틸 함수 ─────────────────────────────────────────────────────────────────

def normalize_field_name(name: str) -> str:
    if not name:
        return ""
    base = name.split("#")[0]
    if " [" in base:
        base = base.split(" [", 1)[0]
    return base.strip()


def normalize_step(v: str) -> str:
    v = (v or "").strip()
    return "" if v.lower() == "x" else v


def need_guarantor(category: str, minwon: str, kind: str, detail: str) -> bool:
    if category != "체류" or kind != "F":
        return False
    if minwon in ("등록", "연장"):
        return detail in ("1", "2", "3", "6")
    if minwon == "변경":
        return detail in ("1", "2", "3", "5", "6")
    if minwon == "부여":
        return detail in ("2", "3", "5")
    return False


def need_aggregator(category: str, minwon: str, kind: str, detail: str) -> bool:
    return (category, minwon, kind, detail) == ("체류", "변경", "F", "5")


def calc_is_minor(reg_no: str) -> bool:
    reg = str(reg_no or "").replace("-", "")
    if len(reg) < 6 or not reg[:6].isdigit():
        return False
    yy = int(reg[:2])
    current_short = datetime.date.today().year % 100
    century = 2000 if yy <= current_short else 1900
    try:
        birth = datetime.date(century + yy, int(reg[2:4]), int(reg[4:6]))
    except ValueError:
        return False
    age = (datetime.date.today() - birth).days // 365
    return age < 18


def _parse_birth(reg_no: str) -> tuple:
    """등록증 번호 앞 6자리에서 yyyy, mm, dd 추출"""
    reg = str(reg_no or "").replace("-", "")
    birth_raw = reg[:6]
    if len(birth_raw) == 6 and birth_raw.isdigit():
        yy = int(birth_raw[:2])
        current_short = datetime.date.today().year % 100
        century = 2000 if yy <= current_short else 1900
        return str(century + yy), birth_raw[2:4], birth_raw[4:6]
    return "", "", ""


def _parse_gender(id_no: str) -> tuple:
    """번호 첫 자리로 성별 판별 → (gender, man, girl)"""
    num = str(id_no or "").replace("-", "").strip()
    gdigit = num[0] if num else ""
    if gdigit in ("5", "7"):
        return "남", "V", ""
    if gdigit in ("6", "8"):
        return "여", "", "V"
    return "", "", ""


def build_field_values(
    row: dict,
    prov: Optional[dict] = None,
    guardian: Optional[dict] = None,
    guarantor: Optional[dict] = None,
    aggregator: Optional[dict] = None,
    is_minor: bool = False,
    account: Optional[dict] = None,
    category: str = "",
    minwon: str = "",
    kind: str = "",
    detail: str = "",
) -> dict:
    """PDF 텍스트 필드 값 전체 구성 (page_document.py build_field_values 완전 이식)"""
    field_values: dict = {}

    # ── 1) 신청인 기본정보 ──
    yyyy, mm, dd = _parse_birth(str(row.get("등록증", "")))
    gender, man, girl = _parse_gender(str(row.get("번호", "")))

    field_values.update({
        "Surname":        row.get("성", ""),
        "Given names":    row.get("명", ""),
        "yyyy":           yyyy,
        "mm":             mm,
        "dd":             dd,
        "gender":         gender,
        "man":            man,
        "girl":           girl,
        "V":              row.get("V", ""),
        "fnumber":        row.get("등록증", ""),
        "rnumber":        row.get("번호", ""),
        "passport":       row.get("여권", ""),
        "issue":          row.get("발급", ""),
        "expiry":         row.get("만기", ""),
        "nation":         row.get("국적", ""),
        "adress":         row.get("주소", ""),
        "phone1":         row.get("연", ""),
        "phone2":         row.get("락", ""),
        "phone3":         row.get("처", ""),
        "koreanname":     row.get("한글", ""),
        "bankaccount":    row.get("환불계좌", ""),
        "why":            row.get("신청이유", ""),
        "hope":           row.get("희망자격", ""),
        "partner":        row.get("배우자", ""),
        "parents":        guardian.get("한글", "") if is_minor and guardian else row.get("부모", ""),
        "registration":   "",
        "card":           "",
        "extension":      "",
        "change":         "",
        "granting":       "",
        "adresscheck":    "",
        "partner yin":    "",
        "parents yin":    "",
        "changeregist":   "",
    })

    # 등록증/번호 한 칸씩
    for i, digit in enumerate(str(row.get("등록증", "")).strip(), 1):
        field_values[f"fnumber{i}"] = digit
    for i, digit in enumerate(str(row.get("번호", "")).strip(), 1):
        field_values[f"rnumber{i}"] = digit

    # ── 2) 숙소제공자 ──
    if prov:
        field_values.update({
            "hsurname":     prov.get("성", ""),
            "hgiven names": prov.get("명", ""),
            "hfnumber":     prov.get("등록증", ""),
            "hrnumber":     prov.get("번호", ""),
            "hphone1":      prov.get("연", ""),
            "hphone2":      prov.get("락", ""),
            "hphone3":      prov.get("처", ""),
            "hnation":      prov.get("국적", ""),
            "hkoreanname":  prov.get("한글", ""),
            "hadress":      prov.get("주소", ""),
        })

    # ── 3) 신원보증인 ──
    if guarantor:
        g = guarantor
        byyyy, bmm, bdd = _parse_birth(str(g.get("등록증", "")))
        bgender, bman, bgirl = _parse_gender(str(g.get("번호", "")))
        g_reg = str(g.get("등록증", "")).replace("-", "")
        field_values.update({
            "bsurname":     g.get("성", ""),
            "bgiven names": g.get("명", ""),
            "byyyy":        byyyy,
            "bmm":          bmm,
            "bdd":          bdd,
            "bgender":      bgender,
            "bman":         bman,
            "bgirl":        bgirl,
            "bfnumber":     g.get("등록증", ""),
            "brnumber":     g.get("번호", ""),
            "badress":      g.get("주소", ""),
            "bnation":      g.get("국적", ""),
            "bphone1":      g.get("연", ""),
            "bphone2":      g.get("락", ""),
            "bphone3":      g.get("처", ""),
            "bkoreanname":  g.get("한글", ""),
        })
        for i, digit in enumerate(g_reg, 1):
            field_values[f"bfnumber{i}"] = digit

    # ── 4) 법정대리인(guardian) ──
    if guardian:
        d = guardian
        dyyyy, dmm, ddd = _parse_birth(str(d.get("등록증", "")))
        dgender, dman, dgirl = _parse_gender(str(d.get("번호", "")))
        d_reg = str(d.get("등록증", "")).replace("-", "")
        field_values.update({
            "gsurname":     d.get("성", ""),
            "ggiven names": d.get("명", ""),
            "gyyyy":        dyyyy,
            "gmm":          dmm,
            "gdd":          ddd,
            "ggender":      dgender,
            "gman":         dman,
            "ggirl":        dgirl,
            "gfnumber":     d.get("등록증", ""),
            "grnumber":     d.get("번호", ""),
            "gadress":      d.get("주소", ""),
            "gphone1":      d.get("연", ""),
            "gphone2":      d.get("락", ""),
            "gphone3":      d.get("처", ""),
            "gkoreanname":  d.get("한글", ""),
        })
        for i, digit in enumerate(d_reg, 1):
            field_values[f"gfnumber{i}"] = digit

    # ── 5) 합산자(aggregator) ──
    if aggregator:
        a = aggregator
        ayyyy, amm, addd = _parse_birth(str(a.get("등록증", "")))
        agender, aman, agirl = _parse_gender(str(a.get("번호", "")))
        a_reg = str(a.get("등록증", "")).replace("-", "")
        field_values.update({
            "psurname":     a.get("성", ""),
            "pgiven names": a.get("명", ""),
            "pyyyy":        ayyyy,
            "pmm":          amm,
            "pdd":          addd,
            "pgender":      agender,
            "pman":         aman,
            "pgirl":        agirl,
            "pfnumber":     a.get("등록증", ""),
            "prnumber":     a.get("번호", ""),
            "padress":      a.get("주소", ""),
            "pphone1":      a.get("연", ""),
            "pphone2":      a.get("락", ""),
            "pphone3":      a.get("처", ""),
            "pkoreanname":  a.get("한글", ""),
        })
        for i, digit in enumerate(a_reg, 1):
            field_values[f"pfnumber{i}"] = digit

    # ── 6) 행정사 계정 정보 ──
    if account:
        field_values.update({
            "agency_name":  str(account.get("office_name", "") or "").strip(),
            "agent_name":   str(account.get("contact_name", "") or "").strip(),
            "agent_rrn":    str(account.get("agent_rrn", "") or "").strip(),
            "agent_biz_no": str(account.get("biz_reg_no", "") or "").strip(),
            "agent_tel":    str(account.get("contact_tel", "") or "").strip(),
            "office_adr":   str(account.get("office_adr", "") or "").strip(),
        })

    # ── 7) 민원 종류 체크박스 자동 설정 ──
    if category == "체류":
        if minwon == "등록":
            field_values["registration"] = "V"
        elif minwon == "연장":
            field_values["extension"] = "V"
        elif minwon == "변경":
            field_values["change"] = "V"
            s = str(kind or "").strip()
            d_val = str(detail or "").strip()
            if s:
                if "+" in s:
                    field_values["changew"] = s.replace("+", "")
                elif d_val and s == "F":
                    field_values["changew"] = f"{s}{d_val}"
                else:
                    field_values["changew"] = s
        elif minwon == "부여":
            field_values["granting"] = "V"
        elif minwon == "신고":
            if kind == "주소":
                field_values["adrc"] = "V"
            elif kind == "등록사항":
                field_values["ant"] = "V"

    return field_values


def normalize_seal_name(raw) -> Optional[str]:
    if raw is None:
        return None
    name = str(raw).strip()
    if not name:
        return None
    hangul_only = "".join(ch for ch in name if "가" <= ch <= "힣")
    return hangul_only or name


def make_seal_bytes(name: Optional[str]) -> Optional[bytes]:
    """도장 이미지 생성 → PNG bytes. 실패 시 None 반환"""
    name_norm = normalize_seal_name(name)
    if not name_norm:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io as _io

        canvas_size = _SEAL_SIZE
        base = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))

        # 원형 배경
        try:
            circle_img = Image.open(_CIRCLE_PATH).convert("RGBA")
        except Exception:
            circle_img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
            d_tmp = ImageDraw.Draw(circle_img)
            margin = int(canvas_size * 0.08)
            d_tmp.ellipse(
                (margin, margin, canvas_size - margin, canvas_size - margin),
                outline=(180, 0, 0, 255),
                width=int(canvas_size * 0.05),
            )

        scale = 1.05
        circle_size = int(canvas_size * scale)
        circle_img = circle_img.resize((circle_size, circle_size), Image.LANCZOS)
        offset_x = (canvas_size - circle_size) // 2
        offset_y = (canvas_size - circle_size) // 2
        base.alpha_composite(circle_img, dest=(offset_x, offset_y))

        # 테두리 색상 샘플링
        border_color = (180, 0, 0, 255)
        cx = canvas_size // 2
        for y in range(offset_y, offset_y + canvas_size // 2):
            r, g, b, a = base.getpixel((cx, y))
            if a > 0:
                border_color = (r, g, b, a)
                break

        draw = ImageDraw.Draw(base)
        n_chars = len(name_norm)

        if n_chars > 0:
            name_disp = name_norm[:4]
            n_chars = len(name_disp)

            if n_chars == 1:
                cover_ratio, line_gap_ratio = 0.70, 0.0
            elif n_chars == 2:
                cover_ratio, line_gap_ratio = 0.80, 0.25
            elif n_chars == 3:
                cover_ratio, line_gap_ratio = 0.90, 0.12
            else:
                cover_ratio, line_gap_ratio = 0.98, 0.15

            max_inner_height = canvas_size * cover_ratio
            denom = n_chars + (n_chars - 1) * line_gap_ratio
            font_size = max(10, int(max_inner_height / denom))

            try:
                font = ImageFont.truetype(_FONT_PATH, font_size)
            except Exception:
                font = ImageFont.load_default()

            char_sizes = []
            for ch in name_disp:
                bbox = draw.textbbox((0, 0), ch, font=font)
                char_sizes.append((bbox[2] - bbox[0], bbox[3] - bbox[1]))

            total_h = sum(h for _, h in char_sizes)
            line_gap = int(font_size * line_gap_ratio) if n_chars > 1 else 0
            total_h += line_gap * (n_chars - 1)

            current_y = (canvas_size - total_h) / 2
            for idx, ch in enumerate(name_disp):
                w, h = char_sizes[idx]
                draw.text(((canvas_size - w) / 2, current_y), ch, fill=border_color, font=font)
                current_y += h + line_gap

        rotated = base.rotate(5, resample=Image.BICUBIC, expand=True)
        final_img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
        rw, rh = rotated.size
        final_img.alpha_composite(rotated, dest=((canvas_size - rw) // 2, (canvas_size - rh) // 2))

        buf = _io.BytesIO()
        final_img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def fill_and_append_pdf(template_path: str, field_values: dict,
                        seal_bytes_by_role: dict, merged_doc) -> None:
    """PyMuPDF로 PDF 필드 채우기 + 도장 삽입 + merged_doc에 추가"""
    if not template_path:
        return
    abs_path = template_path if os.path.isabs(template_path) else os.path.join(_BASE, template_path)
    if not os.path.exists(abs_path):
        return
    try:
        import fitz
        doc = fitz.open(abs_path)
        for page in doc:
            widgets = list(page.widgets() or [])
            # 1) 텍스트 필드 채우기
            for widget in widgets:
                base = normalize_field_name(widget.field_name)
                if base in field_values:
                    widget.field_value = str(field_values[base] or "")
                    widget.update()
            # 2) 도장 넣기
            for widget in widgets:
                base = normalize_field_name(widget.field_name)
                for role, widget_name in ROLE_WIDGETS.items():
                    if base == widget_name:
                        img_bytes = seal_bytes_by_role.get(role)
                        if img_bytes:
                            page.insert_image(widget.rect, stream=img_bytes)
        merged_doc.insert_pdf(doc)
        doc.close()
    except Exception:
        pass


# ── Pydantic 모델 ─────────────────────────────────────────────────────────────

class RequiredDocsRequest(BaseModel):
    category: str
    minwon: str
    kind: str = ""
    detail: str = ""
    reg_no: str = ""   # 신청인 등록증 앞번호 → calc_is_minor로 재학신고서 필터링


class DocGenRequest(BaseModel):
    category: str
    minwon: str
    kind: str = ""
    detail: str = ""
    customer_id: Optional[str] = None
    selected_docs: list = []


class FullDocGenRequest(BaseModel):
    category: str
    minwon: str
    kind: str = ""
    detail: str = ""
    # 역할별 고객 ID
    applicant_id: Optional[str] = None
    accommodation_id: Optional[str] = None
    guarantor_id: Optional[str] = None
    guardian_id: Optional[str] = None
    aggregator_id: Optional[str] = None
    # DB에 없을 때 직접 입력한 이름 (도장용)
    applicant_name: Optional[str] = None    # 신청인 직접입력
    accommodation_name: Optional[str] = None  # 숙소제공자 직접입력
    guarantor_name: Optional[str] = None      # 신원보증인 직접입력
    guardian_name: Optional[str] = None       # 대리인 직접입력
    aggregator_name: Optional[str] = None     # 합산자 직접입력
    selected_docs: list = []
    # 도장 적용 플래그
    seal_applicant: bool = True
    seal_accommodation: bool = True
    seal_guarantor: bool = True
    seal_guardian: bool = True
    seal_aggregator: bool = True
    seal_agent: bool = True
    # 편집 후 재생성용: PDF 위젯 이름 → 덮어쓸 값. build_field_values 결과에 최종 적용.
    # 빈 문자열("")도 유효한 재정의로 처리한다. None 값은 무시.
    direct_overrides: Optional[dict] = None


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.get("/tree")
def get_selection_tree(_: dict = Depends(get_current_user)):
    return {
        "categories": CATEGORY_OPTIONS,
        "minwon": MINWON_OPTIONS,
        "types": {f"{k[0]}|{k[1]}": v for k, v in TYPE_OPTIONS.items()},
        "subtypes": {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in SUBTYPE_OPTIONS.items()},
    }


@router.post("/required-docs")
def get_required_docs(req: RequiredDocsRequest, _: dict = Depends(get_current_user)):
    kind = req.kind if req.kind and req.kind != "x" else ""
    detail = req.detail or ""
    key = (req.category, req.minwon, kind, detail)
    docs = REQUIRED_DOCS.get(key)
    if docs is None:
        key2 = (req.category, req.minwon, kind, "")
        docs = REQUIRED_DOCS.get(key2, {"main": [], "agent": []})

    main_docs = list(docs.get("main", []))
    agent_docs = list(docs.get("agent", []))

    # 성인(미성년자 아닌 경우) → 재학신고서 제외 (Streamlit 원본 로직 동일)
    if req.reg_no:
        is_minor = calc_is_minor(req.reg_no)
        if not is_minor and "재학신고서" in main_docs:
            main_docs.remove("재학신고서")

    return {
        "key": f"{req.category} {req.minwon} {kind} {detail}".strip(),
        "main_docs": main_docs,
        "agent_docs": agent_docs,
    }


@router.post("/generate-full")
def generate_full(req: FullDocGenRequest, user: dict = Depends(get_current_user)):
    """
    역할별 고객 데이터 + 행정사 정보 기반 PDF 필드 자동 주입 + 도장 삽입 후 병합 PDF 반환.
    템플릿 파일 없는 서류는 무시(건너뜀).
    """
    if not req.selected_docs:
        raise HTTPException(status_code=400, detail="선택된 서류가 없습니다.")
    if not req.applicant_id and not (req.applicant_name or "").strip():
        raise HTTPException(status_code=400, detail="신청인을 선택하거나 이름을 입력해 주세요.")

    tenant_id = user.get("tenant_id") or user.get("sub", "")

    # ── 고객 데이터 조회 ──
    from backend.services.tenant_service import read_sheet
    CUSTOMER_SHEET_NAME = "고객 데이터"

    try:
        customers = read_sheet(CUSTOMER_SHEET_NAME, tenant_id) or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"고객 데이터 조회 실패: {e}")

    def find_customer(cid: Optional[str]) -> Optional[dict]:
        if not cid:
            return None
        cid = cid.strip()
        for c in customers:
            if str(c.get("고객ID", "")).strip() == cid:
                return c
        return None

    if req.applicant_id:
        applicant = find_customer(req.applicant_id)
        if not applicant:
            raise HTTPException(status_code=404, detail=f"신청인(ID={req.applicant_id})을 찾을 수 없습니다.")
    else:
        # 직접 이름 입력: 한글 이름만 있는 최소 row 생성 (도장/이름 필드만 채움)
        applicant = {"한글": (req.applicant_name or "").strip()}

    prov       = find_customer(req.accommodation_id)
    guarantor  = find_customer(req.guarantor_id)
    guardian   = find_customer(req.guardian_id)
    aggregator = find_customer(req.aggregator_id)

    # ── 행정사(account) 정보 조회 ──
    account: Optional[dict] = None
    try:
        from config import ACCOUNTS_SHEET_NAME
        from core.google_sheets import read_data_from_sheet
        records = read_data_from_sheet(ACCOUNTS_SHEET_NAME, default_if_empty=[]) or []
        for r in records:
            if str(r.get("tenant_id", "")).strip() == tenant_id:
                account = r
                break
    except Exception:
        pass

    # ── 미성년 판별 ──
    is_minor = calc_is_minor(str(applicant.get("등록증", "")))

    # ── 도장 이미지 준비 ──
    # 신청인 위치 도장: 미성년이면 대리인 이름 사용
    applicant_seal_name = (
        guardian.get("한글", "") if is_minor and guardian else applicant.get("한글", "")
    )
    accommodation_seal_name = (
        prov.get("한글", "") if prov else req.accommodation_name
    )

    guarantor_seal_name  = guarantor.get("한글", "") if guarantor else (req.guarantor_name or "")
    guardian_seal_name   = guardian.get("한글", "") if guardian else (req.guardian_name or "")
    aggregator_seal_name = aggregator.get("한글", "") if aggregator else (req.aggregator_name or "")

    seal_bytes_by_role = {
        "applicant":     make_seal_bytes(applicant_seal_name)     if req.seal_applicant     else None,
        "accommodation": make_seal_bytes(accommodation_seal_name) if req.seal_accommodation else None,
        "guarantor":     make_seal_bytes(guarantor_seal_name)     if req.seal_guarantor     else None,
        "guardian":      make_seal_bytes(guardian_seal_name)      if req.seal_guardian      else None,
        "aggregator":    make_seal_bytes(aggregator_seal_name)    if req.seal_aggregator    else None,
        "agent":         make_seal_bytes(account.get("contact_name") if account else None) if req.seal_agent    else None,
    }

    # ── 필드 값 구성 ──
    kind   = req.kind   if req.kind   and req.kind   != "x" else ""
    detail = req.detail if req.detail                       else ""

    field_values = build_field_values(
        row=applicant,
        prov=prov,
        guardian=guardian,
        guarantor=guarantor,
        aggregator=aggregator,
        is_minor=is_minor,
        account=account,
        category=req.category,
        minwon=req.minwon,
        kind=kind,
        detail=detail,
    )

    # ── 편집 후 재생성: direct_overrides를 build_field_values 결과에 최종 적용 ──
    if req.direct_overrides:
        field_values.update({k: str(v) for k, v in req.direct_overrides.items() if v is not None})

    # ── PDF 병합 ──
    try:
        import fitz
        merged  = fitz.open()
        skipped = []   # DOC_TEMPLATES 미등록 또는 파일 없는 항목
        missing = []   # None으로 명시적 미완성 항목 (파일 준비 필요)

        for doc_name in req.selected_docs:
            # DOC_TEMPLATES에 아예 없는 경우
            if doc_name not in DOC_TEMPLATES:
                skipped.append(doc_name)
                continue
            rel_path = DOC_TEMPLATES[doc_name]
            # None: 파일이 아직 준비되지 않은 항목
            if rel_path is None:
                missing.append(doc_name)
                continue
            # 경로가 있지만 실제 파일이 없는 경우
            abs_path = rel_path if os.path.isabs(rel_path) else os.path.join(_BASE, rel_path)
            if not os.path.exists(abs_path):
                missing.append(f"{doc_name}(파일없음:{rel_path})")
                continue
            fill_and_append_pdf(rel_path, field_values, seal_bytes_by_role, merged)

        # 누락 파일이 있으면 422로 명시적 안내 (일부라도 있으면 생성은 계속)
        if missing and merged.page_count == 0:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "생성할 수 있는 서류 템플릿이 없습니다.",
                    "missing_templates": missing,
                    "skipped": skipped,
                }
            )

        if merged.page_count == 0:
            raise HTTPException(
                status_code=422,
                detail=f"선택된 서류 중 유효한 템플릿이 없습니다. 건너뜀: {skipped}"
            )

        buf = io.BytesIO()
        merged.save(buf)
        merged.close()
        buf.seek(0)

        applicant_name = applicant.get("한글", "고객")
        filename = f"{applicant_name}_{req.category}_{req.minwon}_{kind}_{detail or 'x'}.pdf"
        # RFC 5987: filename*=UTF-8''<percent-encoded>
        # HTTP 헤더는 latin-1만 허용하므로 한국어 파일명은 반드시 URL 인코딩해야 함
        from urllib.parse import quote
        filename_encoded = quote(filename, safe="")
        # HTTP 헤더는 latin-1만 허용 → 한국어 값은 모두 percent-encode
        skipped_encoded = quote(",".join(skipped), safe=",")
        missing_encoded = quote(",".join(missing), safe=",")

        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}",
                "X-Skipped-Docs":  skipped_encoded,
                "X-Missing-Docs":  missing_encoded,
            },
        )
    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(status_code=500, detail="PyMuPDF(fitz) 미설치. pip install pymupdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 생성 실패: {e}")


@router.get("/customers/search")
def search_customers(q: str = "", user: dict = Depends(get_current_user)):
    """고객 이름 검색 (역할 선택 UI용)"""
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    CUSTOMER_SHEET_NAME = "고객 데이터"
    try:
        from backend.services.tenant_service import read_sheet
        customers = read_sheet(CUSTOMER_SHEET_NAME, tenant_id) or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"고객 데이터 조회 실패: {e}")

    q = q.strip()
    if q:
        customers = [c for c in customers if q in str(c.get("한글", ""))]

    results = []
    for c in customers[:30]:
        p1 = str(c.get("연", "")).strip()
        p2 = str(c.get("락", "")).strip()
        p3 = str(c.get("처", "")).strip()
        phone = "-".join(x for x in [p1, p2, p3] if x)
        birth = str(c.get("등", "")).strip()
        name_part = f"{c.get('한글', '')} ({birth})" if birth else str(c.get("한글", ""))
        label_parts = [name_part]
        if c.get("등록증"):
            label_parts.append(str(c["등록증"]))
        if phone:
            label_parts.append(phone)
        results.append({
            "id":    str(c.get("고객ID", "")),
            "label": " / ".join(label_parts),
            "name":  str(c.get("한글", "")),
            "reg_no": str(c.get("등록증", "")),
        })
    return results


# ── 원클릭 작성 ────────────────────────────────────────────────────────────────
# Output types the one-click generator knows about.
# Add to IMPLEMENTED_OUTPUTS when a new type has a working backend path.
_ALL_OUTPUTS = {"위임장", "건강보험(세대합가)", "건강보험(피부양자)", "하이코리아", "소시넷"}
_IMPLEMENTED_OUTPUTS = {"위임장", "하이코리아", "소시넷"}
# 출력 순서 (다중 선택 시 페이지 순서)
_OUTPUT_ORDER = ["위임장", "하이코리아", "소시넷"]


class QuickPoaRequest(BaseModel):
    # 신청인 정보
    kor_name: str                      # 한글명 (도장명)
    surname: str = ""                  # 영문 성
    given: str = ""                    # 영문 이름
    stay_status: str = ""              # 체류자격 (V 필드)
    reg6: str = ""                     # 등록증 앞 6자리
    no7: str = ""                      # 등록증 뒤 7자리
    addr: str = ""                     # 주소
    phone1: str = "010"
    phone2: str = ""
    phone3: str = ""
    passport: str = ""
    # 도장 옵션
    apply_applicant_seal: bool = True
    apply_agent_seal: bool = True
    # 해상도
    dpi: int = 200
    # 위임업무 체크
    ck_extension: bool = False
    ck_registration: bool = False
    ck_card: bool = False
    ck_adrc: bool = False
    ck_change: bool = False
    ck_granting: bool = False
    ck_ant: bool = False
    # 원클릭 출력 선택 (기본: 위임장만)
    selected_outputs: list[str] = ["위임장"]


def _pdf_bytes_to_jpg_or_zip(pdf_bytes: bytes, dpi: int = 200):
    """PDF → 1페이지면 JPEG bytes, 다페이지면 ZIP(JPEGs) bytes 반환."""
    import fitz, zipfile
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        n = doc.page_count
        if n <= 0:
            return ("jpg", b"")
        if n == 1:
            pix = doc.load_page(0).get_pixmap(dpi=dpi, alpha=False)
            return ("jpg", pix.tobytes("jpeg"))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for i in range(n):
                pix = doc.load_page(i).get_pixmap(dpi=dpi, alpha=False)
                zf.writestr(f"page_{i+1:03d}.jpg", pix.tobytes("jpeg"))
        return ("zip", buf.getvalue())
    finally:
        doc.close()


@router.post("/quick-poa")
def quick_poa(req: QuickPoaRequest, user: dict = Depends(get_current_user)):
    """
    원클릭 작성: selected_outputs에 따라 해당 서류를 빠르게 생성해 반환.
    현재 구현된 출력: 위임장 (JPG/ZIP).
    """
    if not req.kor_name.strip():
        raise HTTPException(status_code=400, detail="신청인 한글명은 필수입니다.")

    # Validate selected outputs
    requested = set(req.selected_outputs or ["위임장"])
    unknown = requested - _ALL_OUTPUTS
    if unknown:
        raise HTTPException(status_code=400, detail=f"알 수 없는 출력 유형: {unknown}")
    not_impl = requested - _IMPLEMENTED_OUTPUTS
    if not_impl:
        raise HTTPException(status_code=400, detail=f"미구현 출력 유형: {not_impl}")

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # 각 출력 유형의 템플릿 경로 사전 검증
    ordered_outputs = [o for o in _OUTPUT_ORDER if o in requested]
    template_paths: dict[str, str] = {}
    for out_type in ordered_outputs:
        rel = DOC_TEMPLATES.get(out_type)
        if not rel:
            raise HTTPException(status_code=500, detail=f"DOC_TEMPLATES에 '{out_type}' 경로가 없습니다.")
        abs_p = os.path.join(base_dir, rel)
        if not os.path.exists(abs_p):
            raise HTTPException(status_code=500, detail=f"템플릿 파일이 없습니다: {abs_p}")
        template_paths[out_type] = abs_p

    # 행정사 계정 정보 조회
    tenant_id = user.get("tenant_id") or user.get("sub", "")
    account: Optional[dict] = None
    try:
        from config import ACCOUNTS_SHEET_NAME
        from core.google_sheets import read_data_from_sheet
        records = read_data_from_sheet(ACCOUNTS_SHEET_NAME, default_if_empty=[]) or []
        for r in records:
            if str(r.get("tenant_id", "")).strip() == tenant_id:
                account = r
                break
    except Exception:
        pass

    row = {
        "한글": req.kor_name.strip(),
        "성": req.surname.strip(),
        "명": req.given.strip(),
        "V": req.stay_status.strip(),
        "등록증": req.reg6.strip(),
        "번호": req.no7.strip(),
        "주소": req.addr.strip(),
        "연": req.phone1.strip(),
        "락": req.phone2.strip(),
        "처": req.phone3.strip(),
        "여권": req.passport.strip(),
    }

    is_minor = calc_is_minor(row.get("등록증", ""))

    field_values = build_field_values(
        row=row,
        prov=None,
        guardian=None,
        guarantor=None,
        aggregator=None,
        is_minor=is_minor,
        account=account,
        category="체류",
        minwon="기타",
    )

    today = datetime.date.today()
    field_values.update({
        "작성년": str(today.year),
        "월":    str(today.month),
        "일":    str(today.day),
        "extension":   "V" if req.ck_extension   else "",
        "registration":"V" if req.ck_registration else "",
        "adrc":        "V" if req.ck_adrc         else "",
        "change":      "V" if req.ck_change       else "",
        "granting":    "V" if req.ck_granting     else "",
        "ant":         "V" if req.ck_ant          else "",
        "card":        "0" if req.ck_card         else "",
    })

    agent_name = (account.get("contact_name", "") if account else "").strip()
    seal_bytes_by_role = {
        "applicant":     make_seal_bytes(row["한글"]) if req.apply_applicant_seal else None,
        "agent":         make_seal_bytes(agent_name)  if (req.apply_agent_seal and agent_name) else None,
        "accommodation": None,
        "guarantor":     None,
        "guardian":      None,
        "aggregator":    None,
    }

    try:
        import fitz
        merged_doc = fitz.open()
        for out_type in ordered_outputs:
            fill_and_append_pdf(template_paths[out_type], field_values, seal_bytes_by_role, merged_doc)
        out = io.BytesIO()
        merged_doc.save(out)
        merged_doc.close()
        pdf_bytes = out.getvalue()
    except ImportError:
        raise HTTPException(status_code=500, detail="PyMuPDF(fitz) 미설치")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 생성 실패: {e}")

    kind, data_bytes = _pdf_bytes_to_jpg_or_zip(pdf_bytes, dpi=req.dpi)
    ymd = today.strftime("%Y%m%d")
    outputs_label = "_".join(ordered_outputs)
    base_name = f"{ymd}_{row['한글']}_{outputs_label}"

    # HTTP headers must be latin-1 encoded; use RFC 5987 for non-ASCII filenames.
    from urllib.parse import quote as _quote
    ext = "jpg" if kind == "jpg" else "zip"
    encoded_name = _quote(f"{base_name}.{ext}", safe="")
    cd = f"attachment; filename*=UTF-8''{encoded_name}"

    if kind == "jpg":
        return StreamingResponse(
            io.BytesIO(data_bytes),
            media_type="image/jpeg",
            headers={"Content-Disposition": cd},
        )
    else:
        return StreamingResponse(
            io.BytesIO(data_bytes),
            media_type="application/zip",
            headers={"Content-Disposition": cd},
        )


# 기존 /generate 엔드포인트 유지 (하위 호환)
@router.post("/generate")
def generate_documents(req: DocGenRequest, user: dict = Depends(get_current_user)):
    if not req.selected_docs:
        raise HTTPException(status_code=400, detail="선택된 서류가 없습니다.")
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    available = []
    missing = []
    for doc in req.selected_docs:
        rel = DOC_TEMPLATES.get(doc)
        if rel:
            abs_p = os.path.join(base_dir, rel)
            if os.path.exists(abs_p):
                available.append({"doc": doc, "path": abs_p})
            else:
                missing.append(doc)
        else:
            missing.append(doc)

    if not available:
        return {"status": "checklist_only", "selected_docs": req.selected_docs,
                "available": [], "missing": missing, "message": "PDF 템플릿 파일이 없어 체크리스트만 반환합니다."}

    try:
        import fitz
        merged = fitz.open()
        for item in available:
            doc_pdf = fitz.open(item["path"])
            merged.insert_pdf(doc_pdf)
            doc_pdf.close()
        buf = io.BytesIO()
        merged.save(buf)
        merged.close()
        buf.seek(0)
        filename = f"서류_{'_'.join(req.selected_docs[:3])}.pdf"
        from urllib.parse import quote as _quote
        cd = f"attachment; filename*=UTF-8''{_quote(filename, safe='')}"
        return StreamingResponse(buf, media_type="application/pdf",
                                  headers={"Content-Disposition": cd})
    except ImportError:
        return {"status": "fitz_missing", "selected_docs": req.selected_docs,
                "message": "PyMuPDF 미설치"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 생성 실패: {e}")
