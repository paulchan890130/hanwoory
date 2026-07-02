"""문서 자동작성 라우터 - 체류/사증 선택 트리 + 필요서류 + PDF 생성 (full injection)"""
import sys, os, io, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from backend.auth import get_current_user, require_admin
from backend.services.global_concurrency import DOC_LOCK_KEY, global_limit_sync

router = APIRouter()

# ── 기본 경로 ─────────────────────────────────────────────────────────────────
_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TEMPLATES_DIR = os.path.join(_BASE, "templates")
_CIRCLE_PATH   = os.path.join(_TEMPLATES_DIR, "원형 배경.png")
_FONT_PATH     = os.path.join(_BASE, "fonts", "HJ한전서B.ttf")
_SEAL_SIZE     = 200
# 영문도장 전용: 라틴 글자는 한글보다 좁아 보이므로 좌우 폭만 넓힌다(가로 x-scale).
# 한글도장에는 적용하지 않는다. I-1J-6G: 1.45 는 체감이 약해 1.8 로 상향(원형 테두리 미접촉).
_LATIN_X_SCALE = 1.8

# ── 선택 트리 데이터 ──────────────────────────────────────────────────────────

CATEGORY_OPTIONS = ["체류", "사증"]

MINWON_OPTIONS: dict = {
    "체류": ["등록", "연장", "변경", "부여", "신고", "기타"],
    "사증": ["준비중"],
}

TYPE_OPTIONS: dict = {
    ("체류", "등록"): ["F", "H2", "E7"],
    ("체류", "연장"): ["F", "H2", "E7", "D"],
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
    ("체류", "연장", "D"): ["2", "4", "8", "10"],
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
    # 체류-연장-D (서류 정의 미확정 → "준비중", 자동 선택 흐름만 보장)
    ("체류", "연장", "D", "2"): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "연장", "D", "4"): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "연장", "D", "8"): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
    ("체류", "연장", "D", "10"): {"main": ["준비중"], "agent": ["위임장", "대행업무수행확인서"]},
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
    "소시넷(등록증)":         "templates/소시넷(등록증).pdf",
    "소시넷(여권)":           "templates/소시넷(여권).pdf",
    "대행업무수행확인서":      "templates/대행업무수행확인서.pdf",
    "대행업무수행확인서1":     "templates/대행업무수행확인서1.pdf",
    "심사보고서":             "templates/심사보고서.pdf",
    "신청자 기본정보":         "templates/신청자 기본정보.pdf",
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
    "준비중":                 None,   # 해당 민원 유형 미구현 (템플릿 없음)
}

# ── 편집형 DB 설정(Phase I-1J-6O) 우선 사용 여부 / 템플릿 경로 해석 ─────────────
# 위 CATEGORY_OPTIONS / MINWON_OPTIONS / TYPE_OPTIONS / SUBTYPE_OPTIONS / REQUIRED_DOCS /
# DOC_TEMPLATES 는 이제 "fallback/seed" 전용이다. FEATURE_PG_QUICK_DOC_CONFIG 가 켜지고
# PG 가 구성되어 있으며 doc_tree_nodes 에 활성 데이터가 있으면 DB 설정을 우선 사용한다.
# 테이블 미적용/PG 미구성/예외 시에는 항상 위 하드코딩으로 안전하게 fallback 한다.

def _db_config_active() -> bool:
    """DB 설정 트리를 사용할 수 있으면 True. 예외/미구성/빈 트리면 False(→ 하드코딩)."""
    try:
        from backend.db import feature_flags
        if not feature_flags.pg_quick_doc_config_enabled():
            return False
        from backend.db import session as _dbsession
        if not _dbsession.is_configured():
            return False
        from backend.services import quick_doc_config_pg_service as cfg
        return cfg.has_active_nodes()
    except Exception:
        return False


def _resolve_template_path(doc_name: str) -> Optional[str]:
    """서류명 → templates/ 상대경로. DB 매핑 우선, 없으면 DOC_TEMPLATES, 그래도 없으면
    자동매핑(파일명 후보) 시도. 반환 ``None`` = 템플릿 없음(missing).

    DOC_TEMPLATES 에 키는 있으나 값이 ``None`` 인 항목(준비중 등)도 None 으로 처리.
    """
    # 1) DB 매핑(활성 + template_filename 존재)
    if _db_config_active():
        try:
            from backend.services import quick_doc_config_pg_service as cfg
            p = cfg.template_for(doc_name)
            if p:
                return p
        except Exception:
            pass
    # 2) 하드코딩 DOC_TEMPLATES
    if doc_name in DOC_TEMPLATES:
        return DOC_TEMPLATES[doc_name]  # None 일 수 있음(파일 미준비)
    # 3) 자동매핑(파일명 후보)
    try:
        from backend.services import quick_doc_config_pg_service as cfg
        fn = cfg.auto_map_template(doc_name)
        if fn:
            return f"templates/{fn}"
    except Exception:
        pass
    return None


# 역할별 도장 필드 이름 (PDF 위젯)
ROLE_WIDGETS: dict = {
    "applicant":     "yin",   # 신청인 (미성년자면 대리인 이름)
    "accommodation": "hyin",  # 숙소제공자
    "guarantor":     "byin",  # 신원보증인
    "guardian":      "gyin",  # 법정대리인 (별도 필드)
    "aggregator":    "pyin",  # 합산자(소득합산자/행정정보 제공자) 원본
    "spouse":        "syin",  # 통합신청서 배우자칸 alias(합산자가 배우자일 때만 채움)
    "agent":         "ayin",  # 행정사
}

# 역할별 서명 필드 이름 (PDF 위젯) — ROLE_WIDGETS와 별도
ROLE_SIGN_WIDGETS: dict = {
    "applicant":     "ysign",
    "accommodation": "hysign",
    "guarantor":     "bysign",
    "guardian":      "gysign",
    "aggregator":    "pysign",
    "spouse":        "ssign",  # 통합신청서 배우자칸 서명 alias
    "agent":         "aysign",
}

# ── 유틸 함수 ─────────────────────────────────────────────────────────────────

def _load_account(tenant_id: str) -> Optional[dict]:
    """행정사/사무소 계정 조회 — **PG-only(Phase B)**.

    PG(tenants + 대표 user)에서 office_name/office_adr/biz_reg_no/contact_name/contact_tel 을
    조회한다. 행정사 주민번호(``agent_rrn``)는 tenants.agent_rrn_encrypted(암호문)를 **복호화**해
    채운다(Phase I-1J-6E). 미저장이면 빈 값. key 없음/복호화 실패 시에도 PDF 생성을 막지 않고
    agent_rrn 만 빈 값으로 둔다(로그에 평문 미기록). 반환 shape 는 build_field_values 매핑과 호환.
    PG 미존재/오류 시 None(문서는 사무소정보 없이 생성)."""
    try:
        from backend.services.auth_pg_service import find_account_by_tenant_pg
        acc = find_account_by_tenant_pg(tenant_id)
        if not acc:
            return None
        cipher = str(acc.pop("agent_rrn_encrypted", "") or "")
        agent_rrn = ""
        if cipher:
            try:
                from backend.services.pii_crypto import decrypt_agent_rrn
                agent_rrn = decrypt_agent_rrn(cipher)
            except Exception:
                # 민감정보 없는 경고만(평문/암호문 미기록). PDF 는 agent_rrn 빈 값으로 계속 진행.
                print("[quick_doc._load_account] agent_rrn decrypt failed → blank")
                agent_rrn = ""
        acc["agent_rrn"] = agent_rrn
        return acc
    except Exception:
        return None


def _split_phone(phone: str) -> tuple:
    """전화번호 문자열 → (phone1, phone2, phone3). 구분자 무관."""
    import re
    phone = str(phone or "").strip()
    cleaned = re.sub(r"[\s\-\.]", "", phone)
    if len(cleaned) == 11 and cleaned.isdigit():
        return cleaned[:3], cleaned[3:7], cleaned[7:]
    if len(cleaned) == 10 and cleaned.isdigit():
        return cleaned[:3], cleaned[3:6], cleaned[6:]
    parts = re.split(r"[-\s\.]+", phone)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return cleaned, "", ""


def _split_date(date_str: str) -> tuple:
    """날짜 문자열 → (year, month, day). month/day는 앞 0 제거."""
    import re
    m = re.match(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})", str(date_str or "").strip())
    if m:
        return m.group(1), m.group(2).lstrip("0") or "0", m.group(3).lstrip("0") or "0"
    return "", "", ""


def _add_years(d: "datetime.date", n: int) -> "datetime.date":
    """date + n년. 2/29 처럼 대상 연도에 없는 날짜는 28일로 보정."""
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def _doc_date_field_values(include_date: bool, custom_date) -> dict:
    """작성년/월/일 + **종료년/월/일(= 작성일 + 4년)** 을 함께 만든다(PDF·HWPX 공용).

    작성일자 규칙(기존 유지):
      · include_date=False → 빈 dict(날짜 미설정)
      · custom_date is None → 오늘
      · custom_date == ""   → 작성·종료 모두 공란(명시적 비움)
      · custom_date 지정     → 해당일(파싱 실패 시 오늘)
    종료일자(신규): 작성일이 존재하면 **그 작성일로부터 +4년**(자동/임의지정 동일 규칙). 작성일이
    공란이면 종료도 공란. 종료년/월/일 누름틀이 없는 템플릿이면 값은 무시되어 무해(있는 곳만 채워짐)."""
    if not include_date:
        return {}
    blank = {"작성년": "", "월": "", "일": "", "종료년": "", "종료월": "", "종료일": ""}
    if custom_date == "":
        return blank
    base = None
    if custom_date is None:
        base = datetime.date.today()
    else:
        y, m, d = _split_date(custom_date)
        if y:
            try:
                base = datetime.date(int(y), int(m or 1), int(d or 1))
            except Exception:
                base = datetime.date.today()
        else:
            base = datetime.date.today()
    end = _add_years(base, 4)
    return {"작성년": str(base.year), "월": str(base.month), "일": str(base.day),
            "종료년": str(end.year), "종료월": str(end.month), "종료일": str(end.day)}


# ── 소득합산자(p) ↔ 배우자칸(s) 문서별 overlay ─────────────────────────────────────
# 소득합산자(aggregator)는 정보제공동의서에서는 **대상자 본인(p)** 으로 그대로 쓰고,
# 통합신청서에서는 **p_relation** 에 따라 배우자칸(s) 또는 부/모칸(p)으로 **분기**한다.
# 전역 field_values 하나로 모든 문서를 동일 처리하지 않고, 통합신청서 생성 시점에만 아래 overlay 를
# 적용(문서별 매핑). 신원보증인(b)/관계는 여기에 관여하지 않는다.
#
# 통합신청서 필드/ marker (템플릿에 존재할 때만 채워짐 — 없으면 무해):
#   배우자칸: skoreanname/ssurname/sgiven names/syyyy/smm/sdd/sfnumber/srnumber/sphone1~3, [[syin]]/[[ssign]]
#   부·모칸: pkoreanname/… (합산자 원본 p 그대로), [[pyin]]/[[pysign]]
_UNIFIED_APP_NORM = "통합신청서"   # _normalize_doc_name 결과 기준(공백 제거)

# p 필드 → s(배우자칸) 필드 매핑
_P_TO_S_FIELD: dict = {
    "pkoreanname": "skoreanname", "psurname": "ssurname", "pgiven names": "sgiven names",
    "pyyyy": "syyyy", "pmm": "smm", "pdd": "sdd",
    "pfnumber": "sfnumber", "prnumber": "srnumber",
    "pphone1": "sphone1", "pphone2": "sphone2", "pphone3": "sphone3",
}


def _is_unified_application(doc_name: str) -> bool:
    return _normalize_doc_name(doc_name) == _UNIFIED_APP_NORM


def _unified_sp_field_overlay(field_values: dict, has_aggregator: bool, p_relation: str) -> dict:
    """통합신청서 전용 field_values 사본 — p_relation 에 따라 배우자(s)/부모(p) 분기.

    - 배우자: s* ← p*, 부모칸 p* 공백.
    - 부/모: p*(부모칸) 유지, s* 공백.
    - 관계 없음/합산자 없음: s*·부모칸 p* 모두 공백(자동출력 금지).
    빈 값은 상위 채움 단계에서 공백 " " 로 처리되어 누름틀 이름이 노출되지 않는다.
    """
    fv = dict(field_values)
    for s_key in _P_TO_S_FIELD.values():   # s* 기본 공백(초기화)
        fv[s_key] = ""
    # 통합신청서 부/모 칸은 소득합산자(p) 전용 — 신청인 부모/법정대리인(guardian) 자동입력 방지.
    # parents 는 guardian(미성년)/신청인 부모에서 채워지므로 통합신청서에선 공백 처리(part 5 원칙).
    fv["parents"] = ""
    rel = (p_relation or "").strip()
    if has_aggregator and rel == "배우자":
        for p_key, s_key in _P_TO_S_FIELD.items():
            fv[s_key] = field_values.get(p_key, "")
            fv[p_key] = ""                 # 부모칸 비움
        # 개별 pfnumber{i} 자리도 비움(부모칸)
        for i in range(1, 14):
            if f"pfnumber{i}" in fv:
                fv[f"pfnumber{i}"] = ""
    elif has_aggregator and rel in ("부", "모"):
        pass                               # p*(부모칸) 유지, s* 공백
    else:
        for p_key in list(_P_TO_S_FIELD.keys()):   # 관계 미지정 → 부모칸도 공백
            fv[p_key] = ""
        for i in range(1, 14):
            if f"pfnumber{i}" in fv:
                fv[f"pfnumber{i}"] = ""
    return fv


def _unified_sp_role_bytes(by_role: Optional[dict], has_aggregator: bool, p_relation: str) -> dict:
    """통합신청서 전용 seal/sign 역할→bytes 사본. 합산자(aggregator) 이미지를 관계에 따라
    배우자(spouse) 또는 부모(aggregator)로 라우팅하고 반대칸은 None(투명/미삽입). 교차 fallback 없음."""
    src = dict(by_role or {})
    agg = src.get("aggregator")
    rel = (p_relation or "").strip()
    if has_aggregator and rel == "배우자":
        src["spouse"] = agg
        src["aggregator"] = None
    elif has_aggregator and rel in ("부", "모"):
        src["spouse"] = None               # 부모칸(aggregator) 유지
    else:
        src["spouse"] = None
        src["aggregator"] = None
    return src


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


def _customer_address(row: Optional[dict]) -> str:
    """고객 dict 에서 주소를 가져온다. 표준 키는 '주소'이며, 과거/타 경로에서
    들어온 별칭(체류지/address)도 흡수한다. 파괴적 변경 없음 — 읽기 전용 normalize."""
    if not row:
        return ""
    for key in ("주소", "체류지", "address", "adress"):
        v = row.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def build_field_values(
    row: dict,
    prov: Optional[dict] = None,
    accommodation_provider: Optional[dict] = None,
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
    """PDF 텍스트 필드 값 전체 구성"""
    field_values: dict = {}

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
        "adress":         _customer_address(row),
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

    for i, digit in enumerate(str(row.get("등록증", "")).strip(), 1):
        field_values[f"fnumber{i}"] = digit
    for i, digit in enumerate(str(row.get("번호", "")).strip(), 1):
        field_values[f"rnumber{i}"] = digit

    if prov:
        # hadress는 PDF 필드로 존재하지 않으므로 제거 (버그 수정)
        # adress는 신청인 주소/숙소소재지 겸용 — 신청인 row["주소"]로 이미 설정됨
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
        })

    # ── 숙소제공자연결 탭 데이터로 h* 필드 보완 + 관계/날짜/체크박스 매핑 ──────
    if accommodation_provider:
        ptype = accommodation_provider.get("provider_type", "")

        # 수동 입력이거나 DB 고객이 조회 안 된 경우: 저장된 필드로 h* 직접 채움
        if ptype == "manual" or not prov:
            field_values.update({
                "hkoreanname":  accommodation_provider.get("provider_name", ""),
                "hsurname":     accommodation_provider.get("provider_last_name", ""),
                "hgiven names": accommodation_provider.get("provider_first_name", ""),
                "hfnumber":     accommodation_provider.get("provider_reg_front", ""),
                "hrnumber":     accommodation_provider.get("provider_reg_back", ""),
                "hnation":      accommodation_provider.get("provider_nation", ""),
            })
            ph1, ph2, ph3 = _split_phone(accommodation_provider.get("provider_phone", ""))
            field_values.update({"hphone1": ph1, "hphone2": ph2, "hphone3": ph3})

        # 관계 → PDF "관계" 필드
        relation = accommodation_provider.get("provider_relation", "")
        if relation:
            field_values["관계"] = relation

        # 제공 시작일 → PDF 제공년/제공월/제공일
        start = accommodation_provider.get("provide_start_date", "")
        if start:
            syyyy, smm, sdd = _split_date(start)
            field_values.update({"제공년": syyyy, "제공월": smm, "제공일": sdd})

        # 숙소 유형 체크박스 (PDF에 확인된 필드명 기준)
        _housing_checkbox = {
            "자가":    "Check Box자가",
            "임대":    "Check Box임대",
            "개인주택": "Check Box개인주택",
            "기타":    "Check Box기타",
        }
        ht = accommodation_provider.get("housing_type", "")
        cb = _housing_checkbox.get(ht)
        if cb:
            field_values[cb] = "Yes"

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

    if account:
        field_values.update({
            "agency_name":  str(account.get("office_name", "") or "").strip(),
            "agent_name":   str(account.get("contact_name", "") or "").strip(),
            "agent_rrn":    str(account.get("agent_rrn", "") or "").strip(),
            "agent_biz_no": str(account.get("biz_reg_no", "") or "").strip(),
            "agent_tel":    str(account.get("contact_tel", "") or "").strip(),
            "office_adr":   str(account.get("office_adr", "") or "").strip(),
        })

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
            # 희망 자격(hope) — 통합신청서 "(희망 자격 : ___)" 칸은 **부여 전용**.
            # 변경 시 목표 자격은 changew 에, 부여 시 목표 자격은 hope 에만 나오도록 분리한다
            # (둘이 동시에 표시되지 않게 함). 포맷은 changew 규칙과 동일(F+5·(F,5)→"F5", H2→"H2").
            s = str(kind or "").strip()
            d_val = str(detail or "").strip()
            if s:
                if "+" in s:
                    field_values["hope"] = s.replace("+", "")
                elif d_val and s == "F":
                    field_values["hope"] = f"{s}{d_val}"
                else:
                    field_values["hope"] = s
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


def english_initials(surname, given) -> str:
    """영문 도장용 이니셜: 성 첫 글자 + 명 첫 글자(대문자, A-Z만). 둘 다 없으면 빈 문자열.

    예) KIM/CHULSOO→KC, ZHANG/MEIYING→ZM, ABDURAHMAN/ALI→AA, PARK/MIN-JUN→PM, ALI/""→A.
    분리 필드(성/명)가 비면 호출측에서 fallback(여권 영문명 공백분리) 처리."""
    def _az(s):
        return "".join(c for c in str(s or "").upper() if "A" <= c <= "Z")
    su, gi = _az(surname), _az(given)
    return (su[:1] + gi[:1])


def make_seal_bytes(name: Optional[str], english: bool = False) -> Optional[bytes]:
    """도장 이미지 생성 → PNG bytes. 실패 시 None 반환.

    english=False(기본): 기존 한글 도장(세로 배치) — 동작 100% 보존.
    english=True: name 을 영문 이니셜(A-Z 대문자)로 보고 한글 도장과 동일한 세로 배치
                  (1자=중앙, 2자=상하 2칸, 3자 이상=세로 3칸). 한글 fallback 없음.
    """
    if english:
        name_norm = "".join(c for c in str(name or "").upper() if "A" <= c <= "Z")
    else:
        name_norm = normalize_seal_name(name)
    if not name_norm:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io as _io

        canvas_size = _SEAL_SIZE
        base = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))

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
            # 한글·영문 공통 세로 배치(1자=중앙, 2자=상하 2칸, 3자 이상=세로 3칸).
            # 영문 이니셜도 한글 도장과 동일한 세로 규칙을 사용한다(한글 fallback 없음).
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
            if english:
                # 라틴 문자: 세로배치/높이는 그대로 두고 좌우 폭만 넓힌다(한글 글자칸 수준).
                # 각 글자를 타일로 렌더 → 가로로만 x-scale 확대 후 가운데 합성.
                for idx, ch in enumerate(name_disp):
                    w, h = char_sizes[idx]
                    bb = font.getbbox(ch)
                    gw = max(1, bb[2] - bb[0])
                    gh = max(1, bb[3] - bb[1])
                    tile = Image.new("RGBA", (gw, gh), (0, 0, 0, 0))
                    ImageDraw.Draw(tile).text((-bb[0], -bb[1]), ch, fill=border_color, font=font)
                    nw = max(1, int(gw * _LATIN_X_SCALE))
                    if nw != gw:
                        tile = tile.resize((nw, gh), Image.LANCZOS)
                    base.alpha_composite(
                        tile, dest=(int((canvas_size - nw) / 2), int(current_y + bb[1]))
                    )
                    current_y += h + line_gap
            else:
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


def _auto_role_seal(korean_name, surname, given, enabled: bool):
    """역할별 도장 자동판단(I-1J-6N): 한글이름 우선 → 영문 이니셜 → 생략.
    반환 (bytes|None, reason). reason ∈ disabled/korean/english/no_name — 개인정보 없음(로그용)."""
    if not enabled:
        return None, "disabled"
    kn = normalize_seal_name(korean_name)
    if kn:
        return make_seal_bytes(kn), "korean"            # 한글 우선(영문 있어도 한글)
    ini = english_initials(surname, given)
    if ini:
        return make_seal_bytes(ini, english=True), "english"  # 한글 없고 영문만 → 영문도장(세로)
    return None, "no_name"                              # 둘 다 없음 → 생략(정상)


def _insert_role_images(page, widget, base, seal_bytes_by_role, sign_bytes_by_role):
    """도장/서명 이미지 삽입 — 기존 ROLE_WIDGETS / ROLE_SIGN_WIDGETS 좌표·로직 그대로(보존)."""
    for role, widget_name in ROLE_WIDGETS.items():
        if base == widget_name:
            img_bytes = seal_bytes_by_role.get(role)
            if img_bytes:
                page.insert_image(widget.rect, stream=img_bytes)
    if sign_bytes_by_role:
        for role, widget_name in ROLE_SIGN_WIDGETS.items():
            if base == widget_name:
                sig_bytes = sign_bytes_by_role.get(role)
                if sig_bytes:
                    page.insert_image(widget.rect, stream=sig_bytes)


# ── field_ap (필드 유지형 Custom Appearance) PoC 헬퍼 ─────────────────────────────
# AcroForm Text field 를 살린 채(/T·/V·widget 유지), /AP appearance stream 만 통일 규칙으로
# 직접 생성한다. flatten/삭제 없음. /V 에는 공백 없는 실제 값만 들어간다(표시 통일은 /AP 에서만).
_AP_STD_CELL_EM = 1.35          # 표준 칸 폭(통합신청서 yyyy 칸 ≈ 13.4pt @ ~10pt) = font_size * 1.35
_AP_ADDRESS_FIELDS = {"adress", "address", "hadress", "badress", "gadress", "padress",
                      "office_adr", "agent_address", "why", "hope", "reason", "details"}
_AP_MULTILINE_FLAG = 1 << 12    # PDF Text field Multiline 플래그


def _ap_is_ascii(value: str) -> bool:
    """값이 ASCII(영문/숫자/하이픈/공백/기호)만 → 고정칸 /AP 대상. 한글 등 비ASCII면 native."""
    try:
        value.encode("ascii")
        return True
    except Exception:
        return False


def _ap_esc(c: str) -> str:
    return c.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_fixed_cell_ap(doc, widget, value: str) -> bool:
    """widget 의 /AP /N content stream 을 '표준 칸 폭·가운데 묶음' 고정칸 레이아웃으로 덮어쓴다.
    widget.update()로 /V(공백 없는 실제 값)+기본 Helv AP 를 먼저 만든 뒤 stream 만 교체.
    성공 True. 실패(구조 불일치 등) 시 False(호출측이 native 로 둠)."""
    import fitz
    try:
        widget.field_value = value
        widget.update()                       # /V 세팅 + /AP /N (Helv) 생성
        ap = doc.xref_get_key(widget.xref, "AP")
        if ap[0] != "dict" or "/N" not in ap[1]:
            return False
        nx = int(ap[1].split("/N")[1].split("0 R")[0].strip())
        obj = doc.xref_object(nx)
        bb = obj.split("/BBox")[1].split("[")[1].split("]")[0].split()
        W = float(bb[2]) - float(bb[0]); H = float(bb[3]) - float(bb[1])
        helv = fitz.Font("helv")
        n = len(value)
        if n == 0:
            return False
        pad = 2.0
        avail = max(1.0, W - 2 * pad)
        size = 12.0
        nonspace = [c for c in value if not c.isspace()]
        while size >= 5.0:
            cell = min(size * _AP_STD_CELL_EM, avail / n)
            maxg = max((helv.text_length(c, size) for c in nonspace), default=0.0)
            if maxg <= cell and size * 1.2 <= H:
                break
            size -= 0.5
        cell = min(size * _AP_STD_CELL_EM, avail / n)
        block = cell * n
        x0 = pad + (avail - block) / 2          # 글자 묶음을 필드 가운데로(과확산 방지)
        base_y = (H - size) / 2 + size * 0.2
        parts = ["/Tx BMC", "q", "BT", "/Helv %.2f Tf" % size, "0 g"]
        for i, ch in enumerate(value):
            if ch.isspace():
                continue                        # cell 은 차지하되 그리지 않음
            gw = helv.text_length(ch, size)
            x = x0 + i * cell + (cell - gw) / 2
            parts.append("1 0 0 1 %.2f %.2f Tm (%s) Tj" % (x, base_y, _ap_esc(ch)))
        parts += ["ET", "Q", "EMC"]
        doc.update_stream(nx, ("\n".join(parts) + "\n").encode())
        return True
    except Exception:
        return False


def _write_native_ap(doc, widget, value: str, center: bool) -> None:
    """한글/장문 필드: 고정칸 없이 native AcroForm appearance 로 채운다(필드/V 유지).
    center=True 면 /Q=1(가운데). 장문은 템플릿 /Q·Multiline 그대로 둬 wrap 유지."""
    try:
        if center:
            try:
                doc.xref_set_key(widget.xref, "Q", "1")
            except Exception:
                pass
        widget.field_value = value
        widget.update()
    except Exception:
        pass


def _set_need_appearances(doc, value: bool) -> None:
    """AcroForm /NeedAppearances 설정. False 면 뷰어가 우리 /AP 를 그대로 사용(Custom AP 유지)."""
    try:
        root = doc.pdf_catalog()
        af = doc.xref_get_key(root, "AcroForm")
        if af and af[0] == "xref":
            afx = int(af[1].split()[0])
            doc.xref_set_key(afx, "NeedAppearances", "true" if value else "false")
    except Exception:
        pass


def _looks_space_injected(value: str) -> bool:
    """/V 에 인위적 자간 공백이 들어갔는지(예: 'P I A O'). 실제 공백 포함 이름('PIAO CHENGJUN')은 정상.
    판정: 공백 분리 토큰이 3개 이상이면서 전부 1글자면 인위적 삽입으로 본다."""
    toks = value.split(" ")
    return len(toks) >= 3 and all(len(t) == 1 for t in toks if t != "")


def validate_field_ap_output(pdf_bytes: bytes) -> dict:
    """field_ap 최종(merged) PDF 자동검사. Text widget 생존·CheckBox·/V 공백삽입 확인.
    반환 stats. Text widget 0개면 ok=False(호출측에서 실패 처리). 개인정보 원문 로그 금지."""
    import fitz
    d = fitz.open("pdf", pdf_bytes)
    text_count = checkbox_count = 0
    v_present = 0
    spaced_fields = []
    try:
        for pg in d:
            for w in (pg.widgets() or []):
                ft = w.field_type_string
                if ft == "Text":
                    text_count += 1
                    v = w.field_value or ""
                    if v:
                        v_present += 1
                        if _looks_space_injected(v):
                            spaced_fields.append(w.field_name)
                elif ft == "CheckBox":
                    checkbox_count += 1
    finally:
        d.close()
    return {
        "ok": text_count > 0 and not spaced_fields,
        "text_count": text_count,
        "checkbox_count": checkbox_count,
        "v_present": v_present,
        "space_injected_fields": spaced_fields,
    }


def fill_and_append_pdf(template_path: str, field_values: dict,
                        seal_bytes_by_role: dict, merged_doc,
                        sign_bytes_by_role: Optional[dict] = None,
                        render_mode: str = "acroform") -> None:
    """PyMuPDF로 PDF 필드 채우기 + 도장/서명 삽입 + merged_doc에 추가.

    render_mode="field_ap"(PoC): Text field 를 **유지**한 채 /V=실제값, /AP=통일 appearance.
      · 짧은 ASCII 값 → 고정칸(표준 칸 폭·가운데) Custom /AP. 한글/장문 → native AcroForm AP.
      · flatten/삭제 없음, CheckBox·도장/서명은 기존 방식. NeedAppearances=false.

    render_mode="acroform"(기본): 기존 AcroForm field_value 방식 — 동작 100% 보존(rollback 경로).
    render_mode="overlay": **Text 필드만** 좌표 overlay + 폰트 embed + Text 위젯 flatten.
      · CheckBox 는 overlay 하지 않고 기존 AcroForm 처리(값 설정 + 위젯 유지) 보존.
      · 도장/서명(ROLE_WIDGETS/ROLE_SIGN_WIDGETS)은 위치·이미지 삽입 로직 그대로.
      · style 은 backend.services.pdf_style(GLOBAL_STYLE + STYLE_OVERRIDE), keep_field 예외 지원.
    """
    if not template_path:
        return
    abs_path = template_path if os.path.isabs(template_path) else os.path.join(_BASE, template_path)
    if not os.path.exists(abs_path):
        return
    try:
        import fitz
        doc = fitz.open(abs_path)

        if render_mode in ("overlay", "overlay_legacy"):
            # legacy 보기안정형: Text widget 제거/flatten(필드 사망). field_ap 로 대체됨 — dev fallback 전용.
            from backend.services.pdf_style import style_for, draw_overlay_text
            role_names = set(ROLE_WIDGETS.values()) | set(ROLE_SIGN_WIDGETS.values())
            # 중복 draw 방지: 같은 page + 같은 normalized field + 거의 같은 rect 면 1회만 그린다.
            # rounded rect(약 3pt tolerance)로 미세 차이는 같은 칸으로 본다. 단 rect 가 실제로
            # 다른 위치면(예: 위임장의 agent_name 2곳) 키가 달라 둘 다 그려진다(문서 보존).
            drawn_cells = set()
            def _cell_key(pno, base, rect):
                return (pno, base, round(rect.x0 / 3), round(rect.y0 / 3),
                        round(rect.x1 / 3), round(rect.y1 / 3))
            for page in doc:
                widgets = list(page.widgets() or [])
                # 1) Text overlay(비-role) / CheckBox 기존 처리 / keep_field 유지
                for widget in widgets:
                    base = normalize_field_name(widget.field_name)
                    ftype = widget.field_type_string
                    if ftype == "Text" and widget.field_name not in role_names:
                        if base in field_values:
                            st = style_for(widget.field_name, getattr(widget, "text_align", 0) or 0)
                            val = str(field_values[base] or "")
                            if st.get("keep_field"):
                                widget.field_value = val
                                widget.update()  # 예외: AcroForm 위젯 유지(편집 가능)
                            elif val:
                                key = _cell_key(page.number, base, widget.rect)
                                if key in drawn_cells:
                                    continue  # 같은 칸 중복 draw 방지(글자 겹침 방지)
                                drawn_cells.add(key)
                                draw_overlay_text(page, widget.rect, val, st)
                    elif ftype == "CheckBox":
                        if base in field_values:
                            widget.field_value = str(field_values[base] or "")
                            widget.update()
                # 2) 도장/서명 이미지 (텍스트 overlay 이후 삽입 → 덮이지 않음)
                for widget in widgets:
                    base = normalize_field_name(widget.field_name)
                    _insert_role_images(page, widget, base, seal_bytes_by_role, sign_bytes_by_role)
                # 3) flatten: Text 위젯 제거(keep_field 제외). CheckBox/그 외 위젯 유지.
                for widget in list(page.widgets() or []):
                    if widget.field_type_string == "Text":
                        st = style_for(widget.field_name, 0)
                        if not st.get("keep_field"):
                            page.delete_widget(widget)
        elif render_mode == "field_ap":
            # 필드 유지형 Custom Appearance: Text widget 유지(삭제·flatten 없음).
            role_names = set(ROLE_WIDGETS.values()) | set(ROLE_SIGN_WIDGETS.values())
            for page in doc:
                widgets = list(page.widgets() or [])
                for widget in widgets:
                    base = normalize_field_name(widget.field_name)
                    ftype = widget.field_type_string
                    if ftype == "Text" and widget.field_name not in role_names:
                        if base not in field_values:
                            continue
                        val = str(field_values[base] or "")
                        if not val:
                            continue
                        ff = getattr(widget, "field_flags", 0) or 0
                        is_long = (
                            base in _AP_ADDRESS_FIELDS
                            or bool(ff & _AP_MULTILINE_FLAG)
                            or (widget.rect.height > 30)
                        )
                        if is_long:
                            _write_native_ap(doc, widget, val, center=False)   # 장문/주소: native wrap 유지
                        elif _ap_is_ascii(val):
                            if not _write_fixed_cell_ap(doc, widget, val):     # 고정칸 실패 → native fallback
                                _write_native_ap(doc, widget, val, center=True)
                        else:
                            _write_native_ap(doc, widget, val, center=True)    # 한글 짧은 값: native 가운데
                    elif ftype == "CheckBox":
                        if base in field_values:
                            widget.field_value = str(field_values[base] or "")
                            widget.update()
                # 도장/서명 이미지(기존 방식). Text widget 은 유지(삭제 안 함).
                for widget in widgets:
                    base = normalize_field_name(widget.field_name)
                    _insert_role_images(page, widget, base, seal_bytes_by_role, sign_bytes_by_role)
            _set_need_appearances(doc, False)   # 뷰어가 우리 /AP 를 그대로 사용
        else:
            for page in doc:
                widgets = list(page.widgets() or [])
                for widget in widgets:
                    base = normalize_field_name(widget.field_name)
                    if base in field_values:
                        widget.field_value = str(field_values[base] or "")
                        widget.update()
                for widget in widgets:
                    base = normalize_field_name(widget.field_name)
                    _insert_role_images(page, widget, base, seal_bytes_by_role, sign_bytes_by_role)

        merged_doc.insert_pdf(doc)
        doc.close()
    except Exception:
        pass


# ── Pydantic 요청 모델 ────────────────────────────────────────────────────────

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
    applicant_id: Optional[str] = None
    accommodation_id: Optional[str] = None
    guarantor_id: Optional[str] = None
    guardian_id: Optional[str] = None
    aggregator_id: Optional[str] = None
    applicant_name: Optional[str] = None
    accommodation_name: Optional[str] = None
    guarantor_name: Optional[str] = None
    guardian_name: Optional[str] = None
    aggregator_name: Optional[str] = None
    aggregator_relation: Optional[str] = None   # 소득합산자 관계: 배우자 / 부 / 모 (통합신청서 배우자·부모칸 분기)
    selected_docs: list = []
    seal_applicant: bool = True
    seal_accommodation: bool = True
    seal_guarantor: bool = True
    seal_guardian: bool = True
    seal_aggregator: bool = True
    seal_agent: bool = True
    sign_applicant: bool = False
    sign_accommodation: bool = False
    sign_guarantor: bool = False
    sign_guardian: bool = False
    sign_aggregator: bool = False
    sign_agent: bool = False
    direct_overrides: Optional[dict] = None
    accommodation_provider: Optional[dict] = None  # 숙소제공자연결 탭 전체 데이터
    guarantor_connection: Optional[dict] = None    # 신원보증인연결 탭 전체 데이터
    include_date: bool = True                      # 작성년/월/일 삽입 여부
    custom_date: Optional[str] = None              # 직접 지정 날짜 (YYYY-MM-DD); None = 오늘
    use_english_stamp: bool = False                # True 면 신청인 도장에 영문 이니셜(성+명 첫글자) 사용. 기본 False=한글 도장
    render_mode: str = "acroform"                  # "acroform"(기본, 기존 방식) | "overlay"(Text 좌표 overlay+flatten, 보기 안정형)


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

def _hardcoded_tree() -> dict:
    return {
        "categories": CATEGORY_OPTIONS,
        "minwon": MINWON_OPTIONS,
        "types": {f"{k[0]}|{k[1]}": v for k, v in TYPE_OPTIONS.items()},
        "subtypes": {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in SUBTYPE_OPTIONS.items()},
    }


@router.get("/tree")
def get_selection_tree(_: dict = Depends(get_current_user)):
    # DB 설정이 활성(플래그+PG+데이터)이면 DB 트리, 아니면 하드코딩 fallback.
    if _db_config_active():
        try:
            from backend.services import quick_doc_config_pg_service as cfg
            return cfg.build_tree()
        except Exception:
            pass
    return _hardcoded_tree()


@router.post("/required-docs")
def get_required_docs(req: RequiredDocsRequest, _: dict = Depends(get_current_user)):
    kind = req.kind if req.kind and req.kind != "x" else ""
    detail = req.detail or ""
    docs = None
    # DB 설정 우선(활성 시). 매칭 실패 시 하드코딩 fallback.
    if _db_config_active():
        try:
            from backend.services import quick_doc_config_pg_service as cfg
            docs = cfg.required_docs(req.category, req.minwon, req.kind, detail)
        except Exception:
            docs = None
    if docs is None:
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


# ── 관리자 전용: 문서자동작성 설정(편집형 트리/필요서류) — Phase I-1J-6O ────────
# require_admin 으로 보호. PG 미구성 시 503. 코드 파일을 고치지 않고 DB 설정만 수정한다.

def _cfg_service():
    """quick_doc_config_pg_service 반환. PG 미구성/임포트 실패 시 503."""
    from backend.db import session as _dbsession
    if not _dbsession.is_configured():
        raise HTTPException(status_code=503, detail="PostgreSQL 이 구성되지 않았습니다(문서자동작성 설정은 DB 필요).")
    from backend.services import quick_doc_config_pg_service as cfg
    return cfg


class NodeCreateReq(BaseModel):
    parent_id: Optional[int] = None
    level: str                       # category | petition | type | subtype
    name: str
    sort_order: Optional[int] = None


class NodeUpdateReq(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


class ReqDocCreateReq(BaseModel):
    node_id: int
    name: str
    doc_group: str = "main"          # main | agent
    sort_order: Optional[int] = None
    template_filename: Optional[str] = None


class ReqDocUpdateReq(BaseModel):
    name: Optional[str] = None
    doc_group: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    template_filename: Optional[str] = None


@router.get("/admin/tree")
def admin_get_tree(_: dict = Depends(require_admin)):
    """관리자용 전체 트리(비활성 포함 + 필요서류 + 템플릿 상태)."""
    cfg = _cfg_service()
    return cfg.admin_tree()


@router.get("/admin/templates")
def admin_list_templates(_: dict = Depends(require_admin)):
    """templates/ 폴더의 PDF 파일 목록(자동/수동 매핑 선택용)."""
    cfg = _cfg_service()
    files = cfg.list_template_files()
    return {"templates": [{"filename": f, "display_name": f[:-4], "exists": True} for f in files]}


@router.post("/admin/nodes")
def admin_create_node(req: NodeCreateReq, _: dict = Depends(require_admin)):
    cfg = _cfg_service()
    try:
        return cfg.create_node(req.parent_id, req.level, req.name, req.sort_order)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/admin/nodes/{node_id}")
def admin_update_node(node_id: int, req: NodeUpdateReq, _: dict = Depends(require_admin)):
    cfg = _cfg_service()
    try:
        return cfg.update_node(node_id, name=req.name, sort_order=req.sort_order,
                               is_active=req.is_active)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/admin/nodes/{node_id}")
def admin_delete_node(node_id: int, _: dict = Depends(require_admin)):
    """soft delete(is_active=False)."""
    cfg = _cfg_service()
    try:
        return cfg.delete_node(node_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/admin/required-documents")
def admin_create_required_doc(req: ReqDocCreateReq, _: dict = Depends(require_admin)):
    cfg = _cfg_service()
    try:
        return cfg.create_required_document(req.node_id, req.name, req.doc_group,
                                            req.sort_order, req.template_filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/admin/required-documents/{doc_id}")
def admin_update_required_doc(doc_id: int, req: ReqDocUpdateReq, _: dict = Depends(require_admin)):
    cfg = _cfg_service()
    try:
        return cfg.update_required_document(
            doc_id, name=req.name, doc_group=req.doc_group, sort_order=req.sort_order,
            is_active=req.is_active, template_filename=req.template_filename)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/admin/required-documents/{doc_id}")
def admin_delete_required_doc(doc_id: int, _: dict = Depends(require_admin)):
    """soft delete(is_active=False)."""
    cfg = _cfg_service()
    try:
        return cfg.delete_required_document(doc_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/admin/required-documents/{doc_id}/auto-map-template")
def admin_remap_required_doc(doc_id: int, _: dict = Depends(require_admin)):
    """서류명 기준 templates/ PDF 자동매핑 재계산."""
    cfg = _cfg_service()
    try:
        return cfg.remap_required_document(doc_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/generate-full")
def generate_full(req: FullDocGenRequest, user: dict = Depends(get_current_user)):
    """[로컬 PoC] DOC 전역 동시수 1 게이트 후 실제 생성 로직 실행(combined+workers>=2 직렬화)."""
    with global_limit_sync(DOC_LOCK_KEY):
        return _generate_full_impl(req, user)


def _generate_full_impl(req: FullDocGenRequest, user: dict):
    """
    역할별 고객 데이터 + 행정사 정보 기반 PDF 필드 자동 주입 + 도장 삽입 후 병합 PDF 반환.
    템플릿 파일 없는 서류는 무시(건너뜀).
    """
    print(f"[DEBUG] sign_agent={req.sign_agent} seal_agent={req.seal_agent} docs={req.selected_docs}")
    if not req.selected_docs:
        raise HTTPException(status_code=400, detail="선택된 서류가 없습니다.")
    if not req.applicant_id and not (req.applicant_name or "").strip():
        raise HTTPException(status_code=400, detail="신청인을 선택하거나 이름을 입력해 주세요.")

    tenant_id = user.get("tenant_id") or user.get("sub", "")

    # ── 고객 데이터 조회 ──
    # 저장 경로(고객관리)와 동일한 저장소를 읽어야 한다. FEATURE_PG_CUSTOMERS=true 이면
    # 주소 등 최신 편집분이 PG 기준이므로,
    # 검색 엔드포인트와 동일 분기.
    # PG-only(Phase I): 고객 데이터는 항상 PostgreSQL(Phase C 전환).
    from backend.services.customer_pg_service import list_customers, find_customer as _svc_find_customer
    customers = list_customers(tenant_id) or []

    def find_customer(cid: Optional[str]) -> Optional[dict]:
        # 문서출력은 reg_back(번호) 평문이 필요 → 단건만 reveal=True 로 복호화 조회.
        # (list_customers 는 번호가 마스킹되어 있어 문서에 1****** 가 박힌다.)
        if not cid:
            return None
        return _svc_find_customer(tenant_id, str(cid).strip(), reveal=True)

    if req.applicant_id:
        applicant = find_customer(req.applicant_id)
        if not applicant:
            raise HTTPException(status_code=404, detail=f"신청인(ID={req.applicant_id})을 찾을 수 없습니다.")
    else:
        # 직접 이름 입력: 한글 이름만 있는 최소 row 생성 (도장/이름 필드만 채움)
        applicant = {"한글": (req.applicant_name or "").strip()}

    prov = find_customer(req.accommodation_id)
    # accommodation_provider가 있고 DB 타입이면 provider_customer_id로도 조회
    if prov is None and req.accommodation_provider:
        ap = req.accommodation_provider
        if ap.get("provider_type") == "customer_db":
            prov = find_customer(ap.get("provider_customer_id"))

    guarantor  = find_customer(req.guarantor_id)
    if req.guarantor_connection:
        gc_data = req.guarantor_connection
        if guarantor is None:
            # guarantor_id 없거나 DB 조회 실패 → guarantor_connection 전체 사용
            if gc_data.get("guarantor_type") == "customer_db" and gc_data.get("guarantor_customer_id"):
                guarantor = find_customer(gc_data["guarantor_customer_id"])
            if guarantor is None and gc_data.get("guarantor_name"):
                # manual 또는 DB 조회 실패 → 저장된 필드로 보증인 dict 구성
                ph1, ph2, ph3 = _split_phone(gc_data.get("guarantor_phone", ""))
                guarantor = {
                    "성":    gc_data.get("guarantor_last_name", ""),
                    "명":    gc_data.get("guarantor_first_name", ""),
                    "한글":  gc_data.get("guarantor_name", ""),
                    "등록증": gc_data.get("guarantor_reg_front", ""),
                    "번호":  gc_data.get("guarantor_reg_back", ""),
                    "주소":  gc_data.get("guarantor_address", ""),
                    "국적":  gc_data.get("guarantor_nation", ""),
                    "연":    ph1,
                    "락":    ph2,
                    "처":    ph3,
                }
        else:
            # DB 고객을 찾았지만 주소가 비어 있으면 연결 탭 저장값으로 보완
            # (보증인 DB 고객 주소가 없는 경우 → badress 빈값 방지)
            if not str(guarantor.get("주소", "") or "").strip():
                addr = str(gc_data.get("guarantor_address", "") or "").strip()
                if addr:
                    guarantor["주소"] = addr
    guardian   = find_customer(req.guardian_id)
    aggregator = find_customer(req.aggregator_id)

    # ── 행정사(account) 정보 조회 ──
    account = _load_account(tenant_id)

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

    # ── 보증인/숙소제공자 도장/서명 정규화 ─────────────────────────────────
    # 규칙: 둘 다 true → 서명 우선 (상호 배타 보정)
    # 둘 다 false = 프론트엔드에서 사용자가 명시적으로 "없음"을 선택한 것 → 그대로 유지
    if req.sign_accommodation and req.seal_accommodation:
        req.seal_accommodation = False

    if req.sign_guarantor and req.seal_guarantor:
        req.seal_guarantor = False

    # 도장 자동판단(I-1J-6N): 역할별로 한글이름 우선 → 영문이니셜 → 생략. use_english_stamp 의존 폐기.
    # 신청인 영문 소스는 미성년이면 대리인(guardian). 영문 이름은 role dict 의 "성"/"명"(=Surname/Given names).
    _app_src = guardian if (is_minor and guardian) else applicant
    def _en_names(d):
        d = d or {}
        return d.get("성", ""), d.get("명", "")
    _seal_reasons: dict = {}
    seal_bytes_by_role: dict = {}
    for _role, _korean, _src, _enabled in (
        ("applicant",     applicant_seal_name,     _app_src,   req.seal_applicant),
        ("accommodation", accommodation_seal_name, prov,       req.seal_accommodation),
        ("guarantor",     guarantor_seal_name,     guarantor,  req.seal_guarantor),
        ("guardian",      guardian_seal_name,      guardian,   req.seal_guardian),
        ("aggregator",    aggregator_seal_name,    aggregator, req.seal_aggregator),
    ):
        _su, _gi = _en_names(_src)
        _b, _reason = _auto_role_seal(_korean, _su, _gi, _enabled)
        seal_bytes_by_role[_role] = _b
        _seal_reasons[_role] = _reason
    # 행정사(agent): 사무소 담당자 한글명만(영문 도장 없음, 별도 유지).
    _agent_kn = normalize_seal_name(account.get("contact_name") if account else None)
    seal_bytes_by_role["agent"] = make_seal_bytes(_agent_kn) if (req.seal_agent and _agent_kn) else None
    _seal_reasons["agent"] = (
        "disabled" if not req.seal_agent else ("korean" if _agent_kn else "no_name")
    )
    english_stamp_skipped = (_seal_reasons.get("applicant") == "no_name" and req.seal_applicant)
    print("[seal][auto] " + " ".join(f"{r}={_seal_reasons[r]}" for r in _seal_reasons))  # PII 없음

    # ── 서명 이미지 준비 ──
    from backend.services.signature_service import (
        get_agent_signature as _get_agent_sign,
        get_customer_signature as _get_cust_sign,
    )
    import base64 as _b64

    def _sign_b64_to_bytes(b64: Optional[str]) -> Optional[bytes]:
        if not b64:
            return None
        try:
            raw = b64.split(",", 1)[1] if b64.startswith("data:") else b64
            return _b64.b64decode(raw)
        except Exception:
            return None

    def _cust_sign_bytes(customer_obj: Optional[dict]) -> Optional[bytes]:
        if not customer_obj:
            return None
        cid = str(customer_obj.get("고객ID", "")).strip()
        if not cid:
            return None
        try:
            # PG-only: 서명은 tenant 단위로 PG 에 저장 → tenant_id 로 직접 조회.
            return _sign_b64_to_bytes(_get_cust_sign(tenant_id, cid))
        except Exception:
            return None

    sign_bytes_by_role: dict = {
        "applicant":     _cust_sign_bytes(applicant)     if req.sign_applicant     else None,
        "accommodation": _cust_sign_bytes(prov)          if req.sign_accommodation else None,
        "guarantor":     _cust_sign_bytes(guarantor)     if req.sign_guarantor     else None,
        "guardian":      _cust_sign_bytes(guardian)      if req.sign_guardian      else None,
        "aggregator":    _cust_sign_bytes(aggregator)    if req.sign_aggregator    else None,
        "agent":         _sign_b64_to_bytes(_get_agent_sign(tenant_id)) if req.sign_agent else None,
    }

    # ── 필드 값 구성 ──
    kind   = req.kind   if req.kind   and req.kind   != "x" else ""
    detail = req.detail if req.detail                       else ""

    field_values = build_field_values(
        row=applicant,
        prov=prov,
        accommodation_provider=req.accommodation_provider,
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

    # ── 신원보증인 관계 → PDF 필드 rela 매핑 ──────────────────────────────────
    # build_field_values는 guarantor dict(고객 row 구조)만 받으므로 관계(rela)는 별도 처리
    # guarantor_connection에서 사용자가 입력한 관계 사용
    if req.guarantor_connection:
        rel = str(req.guarantor_connection.get("guarantor_relation", "") or "").strip()
        if rel:
            field_values["rela"] = rel

    # ── 작성년/월/일 + 종료년/월/일(작성일 +4년) 삽입 ─────────────────────────────
    # include_date=False → 날짜 필드 미설정(공란) / custom_date None=오늘 / ""=공란 / 지정=해당일.
    # 종료년/월/일 = 작성일 + 4년(자동/임의지정 동일). 종료 필드 없는 템플릿은 무시(무해).
    field_values.update(_doc_date_field_values(req.include_date, req.custom_date))

    # ── 편집 후 재생성: direct_overrides를 build_field_values 결과에 최종 적용 ──
    if req.direct_overrides:
        field_values.update({k: str(v) for k, v in req.direct_overrides.items() if v is not None})

    # 소득합산자(p) 문서별 분기 준비 — 통합신청서에서만 p_relation 에 따라 배우자(s)/부모(p)로 라우팅.
    has_aggregator = bool(aggregator) or bool((req.aggregator_name or "").strip())
    p_relation = (req.aggregator_relation or "").strip()

    # ── PDF 병합 ──
    try:
        import fitz
        merged  = fitz.open()
        skipped = []   # DOC_TEMPLATES 미등록 또는 파일 없는 항목
        missing = []   # None으로 명시적 미완성 항목 (파일 준비 필요)

        for doc_name in req.selected_docs:
            # DB 매핑 → DOC_TEMPLATES → 자동매핑 순으로 템플릿 경로 해석.
            rel_path = _resolve_template_path(doc_name)
            if rel_path is None:
                # 매핑/파일 없음. 이름이 알려진 서류면 missing(템플릿 없음), 완전 미등록이면 skipped.
                if doc_name in DOC_TEMPLATES:
                    missing.append(doc_name)
                else:
                    skipped.append(doc_name)
                continue
            # 경로가 있지만 실제 파일이 없는 경우
            abs_path = rel_path if os.path.isabs(rel_path) else os.path.join(_BASE, rel_path)
            if not os.path.exists(abs_path):
                missing.append(f"{doc_name}(파일없음:{rel_path})")
                continue
            # 통합신청서만 p→s/p 분기(문서별 overlay). 그 외(정보제공동의서 등)는 p 원본 그대로.
            if _is_unified_application(doc_name):
                doc_fv = _unified_sp_field_overlay(field_values, has_aggregator, p_relation)
                doc_seal = _unified_sp_role_bytes(seal_bytes_by_role, has_aggregator, p_relation)
                doc_sign = _unified_sp_role_bytes(sign_bytes_by_role, has_aggregator, p_relation)
            else:
                doc_fv, doc_seal, doc_sign = field_values, seal_bytes_by_role, sign_bytes_by_role
            fill_and_append_pdf(rel_path, doc_fv, doc_seal, merged, doc_sign,
                                render_mode=req.render_mode)

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

        # field_ap: 최종 PDF 에서 Text field 생존·/V 공백삽입 자동검사. 실패 시 PDF 반환 안 함.
        if req.render_mode == "field_ap":
            stats = validate_field_ap_output(buf.getvalue())
            print(f"[generate_full][field_ap] text={stats['text_count']} "
                  f"checkbox={stats['checkbox_count']} v_present={stats['v_present']} "
                  f"space_injected={stats['space_injected_fields']}")
            if stats["text_count"] == 0:
                raise HTTPException(status_code=500,
                                    detail="field_ap 검증 실패: 최종 PDF 에 Text field 가 없습니다(필드 유실).")
            if stats["space_injected_fields"]:
                raise HTTPException(status_code=500,
                                    detail="field_ap 검증 실패: /V 에 인위적 공백이 삽입되었습니다.")
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

        try:
            from backend.services import audit_service as _audit
            _audit.log_event(action="QUICK_DOC_GENERATE", actor_login_id=user.get("sub"), tenant_id=tenant_id,
                             target_type="document", target_id=",".join(req.selected_docs or [])[:200],
                             payload={"customer_id": str(req.applicant_id or ""), "success": True,
                                      "pii_accessed": True, "doc_count": len(req.selected_docs or [])})
        except Exception:
            pass
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}",
                "X-Skipped-Docs":  skipped_encoded,
                "X-Missing-Docs":  missing_encoded,
                "X-English-Stamp-Skipped": "true" if english_stamp_skipped else "false",
                "X-Render-Mode": req.render_mode,
            },
        )
    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(status_code=500, detail="PyMuPDF(fitz) 미설치. pip install pymupdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF 생성 실패: {e}")


# ── HWPX 자동작성 (추가 기능, PDF 와 완전 독립) ────────────────────────────────────
# 기존 PDF 로직(_generate_full_impl)·필드명·템플릿 경로를 일절 건드리지 않는다.
# field_values 는 PDF 와 **동일한** build_field_values() 로 만들고(같은 데이터 → 같은 값),
# HWPX 누름틀(CLICK_HERE) name 기준으로 텍스트만 채운다. 도장/서명은 marker 기반으로
# 템플릿에 실제 존재하는 marker 만 repoint(없으면 투명 PNG). 서버 PDF 변환은 하지 않는다.
#
# 템플릿 매핑은 **PDF DOC_TEMPLATES 처럼 서류명 기준**이되, 하드코딩 대신 디렉터리의
# .hwpx 파일을 자동 탐색해 레지스트리를 구성한다(파일 추가만으로 매핑 확장 — 추후 관리자
# 매핑 UI 도 같은 레지스트리 위에 얹을 수 있다). templates/hwpx/ 를 우선 스캔하고,
# 보조로 templates/ 루트의 .hwpx 도 포함한다(같은 이름이면 templates/hwpx/ 가 우선).

# HWPX 템플릿 탐색 디렉터리 (앞쪽 우선)
_HWPX_TEMPLATE_DIRS = (
    os.path.join(_BASE, "templates", "hwpx"),
    os.path.join(_BASE, "templates"),
)
# 디렉터리 mtime 기반 캐시 — 파일 추가/삭제 시 자동 갱신(서버 재시작 불필요)
_HWPX_REGISTRY_CACHE: dict = {"sig": None, "map": {}, "stems": {}}


def _normalize_doc_name(name: str) -> str:
    """서류명/파일명 정규화 — 공백 제거. 필요서류명은 띄어쓰기('거주숙소 제공 확인서'),
    파일명은 붙여쓰기('거주숙소제공확인서.hwpx')인 경우가 많아 공백을 지워 매칭한다."""
    import re as _re
    return _re.sub(r"\s+", "", (name or "")).strip()


def _hwpx_dirs_signature() -> tuple:
    sig = []
    for d in _HWPX_TEMPLATE_DIRS:
        try:
            sig.append((d, os.path.getmtime(d)))
        except OSError:
            sig.append((d, None))
    return tuple(sig)


def _is_valid_hwpx(path: str) -> bool:
    """실제 HWPX(zip + Contents/content.hpf)인지 검증. 구형 HWP 바이너리를 .hwpx 확장자로
    저장한 파일은 zip 이 아니라 엔진이 처리할 수 없으므로 레지스트리에서 제외한다."""
    import zipfile as _zf
    try:
        with _zf.ZipFile(path) as z:
            names = z.namelist()
        return "Contents/content.hpf" in names
    except Exception:
        return False


def _build_hwpx_registry() -> dict:
    """{정규화된 서류명: 절대경로} 레지스트리. templates/hwpx/ 우선, templates/ 루트 보조.
    하드코딩 없이 *.hwpx 파일명에서 자동 구성하되, **유효한 HWPX(zip) 파일만** 등록한다."""
    sig = _hwpx_dirs_signature()
    if _HWPX_REGISTRY_CACHE["sig"] == sig:
        return _HWPX_REGISTRY_CACHE["map"]
    registry: dict = {}
    stems: dict = {}
    for d in _HWPX_TEMPLATE_DIRS:
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith(".hwpx"):
                continue
            stem = os.path.splitext(fn)[0]
            key = _normalize_doc_name(stem)
            if not key or key in registry:
                continue   # 먼저 스캔된 디렉터리(templates/hwpx/) 우선
            path = os.path.join(d, fn)
            if not _is_valid_hwpx(path):
                continue   # HWP 바이너리(.hwpx 확장자)·손상 파일 제외
            registry[key] = path
            stems[key] = stem
    _HWPX_REGISTRY_CACHE["sig"] = sig
    _HWPX_REGISTRY_CACHE["map"] = registry
    _HWPX_REGISTRY_CACHE["stems"] = stems
    return registry


def _resolve_hwpx_template(doc_name: str) -> Optional[str]:
    """필요서류명 → HWPX 템플릿 절대경로(없으면 None). 공백 정규화 매칭."""
    return _build_hwpx_registry().get(_normalize_doc_name(doc_name))


def _collect_full_field_values(req: "FullDocGenRequest", user: dict) -> dict:
    """역할별 고객/행정사 데이터를 모아 build_field_values() 결과(field_values)를 만든다.

    `_generate_full_impl` 의 데이터 수집 + field_values 구성 부분을 **그대로 미러링**한 읽기 전용
    헬퍼다(기존 PDF 함수는 변경하지 않는다). PDF 와 HWPX 가 동일 데이터로 동일 값을 쓰도록 보장한다.
    날짜(작성년/월/일)·rela·direct_overrides 까지 PDF 와 동일하게 적용한다.
    """
    tenant_id = user.get("tenant_id") or user.get("sub", "")

    from backend.services.customer_pg_service import find_customer as _svc_find_customer

    def find_customer(cid: Optional[str]) -> Optional[dict]:
        if not cid:
            return None
        return _svc_find_customer(tenant_id, str(cid).strip(), reveal=True)

    if req.applicant_id:
        applicant = find_customer(req.applicant_id)
        if not applicant:
            raise HTTPException(status_code=404, detail=f"신청인(ID={req.applicant_id})을 찾을 수 없습니다.")
    else:
        applicant = {"한글": (req.applicant_name or "").strip()}

    prov = find_customer(req.accommodation_id)
    if prov is None and req.accommodation_provider:
        ap = req.accommodation_provider
        if ap.get("provider_type") == "customer_db":
            prov = find_customer(ap.get("provider_customer_id"))

    guarantor = find_customer(req.guarantor_id)
    if req.guarantor_connection:
        gc_data = req.guarantor_connection
        if guarantor is None:
            if gc_data.get("guarantor_type") == "customer_db" and gc_data.get("guarantor_customer_id"):
                guarantor = find_customer(gc_data["guarantor_customer_id"])
            if guarantor is None and gc_data.get("guarantor_name"):
                ph1, ph2, ph3 = _split_phone(gc_data.get("guarantor_phone", ""))
                guarantor = {
                    "성":    gc_data.get("guarantor_last_name", ""),
                    "명":    gc_data.get("guarantor_first_name", ""),
                    "한글":  gc_data.get("guarantor_name", ""),
                    "등록증": gc_data.get("guarantor_reg_front", ""),
                    "번호":  gc_data.get("guarantor_reg_back", ""),
                    "주소":  gc_data.get("guarantor_address", ""),
                    "국적":  gc_data.get("guarantor_nation", ""),
                    "연": ph1, "락": ph2, "처": ph3,
                }
        else:
            if not str(guarantor.get("주소", "") or "").strip():
                addr = str(gc_data.get("guarantor_address", "") or "").strip()
                if addr:
                    guarantor["주소"] = addr
    guardian   = find_customer(req.guardian_id)
    aggregator = find_customer(req.aggregator_id)

    account = _load_account(tenant_id)
    is_minor = calc_is_minor(str(applicant.get("등록증", "")))

    kind   = req.kind   if req.kind   and req.kind   != "x" else ""
    detail = req.detail if req.detail                       else ""

    field_values = build_field_values(
        row=applicant, prov=prov, accommodation_provider=req.accommodation_provider,
        guardian=guardian, guarantor=guarantor, aggregator=aggregator,
        is_minor=is_minor, account=account,
        category=req.category, minwon=req.minwon, kind=kind, detail=detail,
    )

    if req.guarantor_connection:
        rel = str(req.guarantor_connection.get("guarantor_relation", "") or "").strip()
        if rel:
            field_values["rela"] = rel

    # 작성년/월/일 + 종료년/월/일(작성일 +4년) — PDF 와 동일 공용 헬퍼.
    field_values.update(_doc_date_field_values(req.include_date, req.custom_date))

    if req.direct_overrides:
        field_values.update({k: str(v) for k, v in req.direct_overrides.items() if v is not None})

    return {"field_values": field_values, "applicant": applicant, "prov": prov,
            "guarantor": guarantor, "guardian": guardian, "aggregator": aggregator,
            "account": account, "is_minor": is_minor, "tenant_id": tenant_id,
            "kind": kind, "detail": detail}


_TRANSPARENT_PNG_CACHE: Optional[bytes] = None


def _transparent_png() -> bytes:
    """완전 투명 PNG bytes(역할 이미지가 없을 때 marker 셀 repoint용). 1회 생성 후 캐시.

    borderFill imgBrush 가 이 투명 이미지를 참조하면 셀 배경이 비어 보인다(원본 샘플 도장 제거).
    """
    global _TRANSPARENT_PNG_CACHE
    if _TRANSPARENT_PNG_CACHE is None:
        try:
            from PIL import Image
            import io as _io
            im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
            buf = _io.BytesIO(); im.save(buf, format="PNG")
            _TRANSPARENT_PNG_CACHE = buf.getvalue()
        except Exception:
            # PIL 실패 시 최소 1x1 투명 PNG(고정 바이트)
            _TRANSPARENT_PNG_CACHE = bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
                "890000000d49444154789c6360000002000001e221bc330000000049454e44ae426082")
    return _TRANSPARENT_PNG_CACHE


def _compute_hwpx_marker_pngs(req: "FullDocGenRequest", ctx: dict) -> tuple:
    """역할별 도장/서명 이미지를 만들어 ``{marker_text: png_bytes}`` 매핑을 반환한다.

    **PDF(`_generate_full_impl`)의 도장/서명 산출 규칙을 미러링**(동일 데이터→동일 도장/서명).
    정책(확정): **모든 marker 셀은 반드시 repoint** — 이미지가 없다고 skip 하지 않는다(원본 샘플 잔존 금지).
    우선순위(도장란·서명란 분리, **교차 fallback 금지**):
      · 도장 marker(yin/hyin/byin/gyin/pyin/ayin):           도장 이미지 → 투명 PNG
      · 서명 marker(ysign/hysign/bysign/gysign/pysign/aysign): 실제 서명 이미지 → 투명 PNG
    서명 marker 에 도장 이미지를, 도장 marker 에 서명 이미지를 **대체로 넣지 않는다**(없으면 투명).
    반환: (marker_pngs: {marker: bytes}, transparent_markers: [marker, ...])  — 모든 marker 값은 non-None."""
    applicant = ctx["applicant"]; prov = ctx["prov"]; guarantor = ctx["guarantor"]
    guardian = ctx["guardian"]; aggregator = ctx["aggregator"]; account = ctx["account"]
    is_minor = ctx["is_minor"]; tenant_id = ctx["tenant_id"]

    applicant_seal_name = guardian.get("한글", "") if (is_minor and guardian) else applicant.get("한글", "")
    accommodation_seal_name = prov.get("한글", "") if prov else req.accommodation_name
    guarantor_seal_name = guarantor.get("한글", "") if guarantor else (req.guarantor_name or "")
    guardian_seal_name = guardian.get("한글", "") if guardian else (req.guardian_name or "")
    aggregator_seal_name = aggregator.get("한글", "") if aggregator else (req.aggregator_name or "")

    # 도장/서명 상호배타(서명 우선) — PDF 와 동일(둘 다 True 면 도장 끔). 지역변수만 사용.
    seal_acc = req.seal_accommodation and not req.sign_accommodation
    seal_gua = req.seal_guarantor and not req.sign_guarantor

    _app_src = guardian if (is_minor and guardian) else applicant

    def _en(d):
        d = d or {}
        return d.get("성", ""), d.get("명", "")

    seal: dict = {}
    for role, korean, src, enabled in (
        ("applicant",     applicant_seal_name,     _app_src,   req.seal_applicant),
        ("accommodation", accommodation_seal_name, prov,       seal_acc),
        ("guarantor",     guarantor_seal_name,     guarantor,  seal_gua),
        ("guardian",      guardian_seal_name,      guardian,   req.seal_guardian),
        ("aggregator",    aggregator_seal_name,    aggregator, req.seal_aggregator),
    ):
        su, gi = _en(src)
        b, _reason = _auto_role_seal(korean, su, gi, enabled)
        seal[role] = b
    _agent_kn = normalize_seal_name(account.get("contact_name") if account else None)
    seal["agent"] = make_seal_bytes(_agent_kn) if (req.seal_agent and _agent_kn) else None

    # 서명 — PG 고객/행정사 서명(PDF 와 동일 경로)
    import base64 as _b64
    from backend.services.signature_service import (
        get_agent_signature as _gas, get_customer_signature as _gcs)

    def _b2b(b64):
        if not b64:
            return None
        try:
            raw = b64.split(",", 1)[1] if b64.startswith("data:") else b64
            return _b64.b64decode(raw)
        except Exception:
            return None

    def _cust(obj):
        if not obj:
            return None
        cid = str(obj.get("고객ID", "")).strip()
        if not cid:
            return None
        try:
            return _b2b(_gcs(tenant_id, cid))
        except Exception:
            return None

    sign = {
        "applicant":     _cust(applicant)  if req.sign_applicant     else None,
        "accommodation": _cust(prov)       if req.sign_accommodation else None,
        "guarantor":     _cust(guarantor)  if req.sign_guarantor     else None,
        "guardian":      _cust(guardian)   if req.sign_guardian      else None,
        "aggregator":    _cust(aggregator) if req.sign_aggregator    else None,
        "agent":         (_b2b(_gas(tenant_id)) if req.sign_agent    else None),
    }

    # 정책(변경): 도장란/서명란을 명확히 분리하고 **교차 fallback 금지**.
    #   · 도장 marker = 도장 이미지만 → 없으면 투명 PNG (서명 이미지로 대체 금지)
    #   · 서명 marker = 실제 서명 이미지만 → 없으면 투명 PNG (도장 이미지로 대체 금지)
    # 모든 marker 는 반드시 값(투명 포함)으로 repoint(원본 placeholder 잔존 금지).
    trans = _transparent_png()

    def seal_only(role):   # 도장 marker — 도장 이미지만, 없으면 투명
        return seal.get(role) or trans

    def sign_only(role):   # 서명 marker — 실제 서명 이미지만, 없으면 투명
        return sign.get(role) or trans

    marker_pngs = {
        "[[yin]]":  seal_only("applicant"),     "[[ysign]]":  sign_only("applicant"),
        "[[hyin]]": seal_only("accommodation"), "[[hysign]]": sign_only("accommodation"),
        # 템플릿 변형 호환: 숙소제공자 서명을 `[[hsign]]` 로 쓰는 템플릿(거주숙소 제공 확인서 등).
        # 미제공 시 원본 샘플 서명 이미지가 남지 않도록 반드시 서명(없으면 투명)으로 repoint.
        "[[hsign]]": sign_only("accommodation"),
        "[[byin]]": seal_only("guarantor"),     "[[bysign]]": sign_only("guarantor"),
        "[[gyin]]": seal_only("guardian"),      "[[gysign]]": sign_only("guardian"),
        "[[pyin]]": seal_only("aggregator"),    "[[pysign]]": sign_only("aggregator"),
        # 통합신청서 배우자칸 alias. 기본은 투명 — 통합신청서 생성 시 p_relation 에 따라
        # _unified_sp_marker_pngs 가 합산자 도장/서명을 여기로 라우팅한다(그 외 문서는 투명 유지).
        "[[syin]]": trans,                      "[[ssign]]": trans,  "[[sysign]]": trans,
        "[[ayin]]": seal_only("agent"),         "[[aysign]]": sign_only("agent"),
    }
    transparent_markers = [m for m, v in marker_pngs.items() if v is trans]
    return marker_pngs, transparent_markers   # 모든 marker non-None(투명 포함)


def _unified_sp_marker_pngs(marker_pngs: dict, has_aggregator: bool, p_relation: str) -> dict:
    """통합신청서 전용 marker_pngs 사본 — 합산자 도장/서명(p)을 관계에 따라 배우자(s)/부모(p)로 라우팅.

    - 배우자: [[syin]]/[[ssign]]/[[sysign]] ← 합산자 도장/서명, [[pyin]]/[[pysign]] 투명.
    - 부/모: 배우자칸 투명, [[pyin]]/[[pysign]] 유지(부모칸).
    - 관계 없음/합산자 없음: 배우자·부모칸 모두 투명.
    모든 marker 는 non-None(투명 포함) 유지 → 원본 placeholder 이미지 잔존 0."""
    trans = _transparent_png()
    mp = dict(marker_pngs)
    p_seal = marker_pngs.get("[[pyin]]", trans)
    p_sign = marker_pngs.get("[[pysign]]", trans)
    rel = (p_relation or "").strip()
    if has_aggregator and rel == "배우자":
        mp["[[syin]]"] = p_seal; mp["[[ssign]]"] = p_sign; mp["[[sysign]]"] = p_sign
        mp["[[pyin]]"] = trans;  mp["[[pysign]]"] = trans
    elif has_aggregator and rel in ("부", "모"):
        mp["[[syin]]"] = trans;  mp["[[ssign]]"] = trans; mp["[[sysign]]"] = trans
    else:
        mp["[[syin]]"] = trans;  mp["[[ssign]]"] = trans; mp["[[sysign]]"] = trans
        mp["[[pyin]]"] = trans;  mp["[[pysign]]"] = trans
    return mp


@router.get("/hwpx-templates")
def list_hwpx_templates(_: dict = Depends(get_current_user)):
    """HWPX 템플릿이 존재하는 서류 목록(정규화 키 + 표시명). 프론트가 checkedDocs 중
    HWPX 생성 가능한 서류 수를 계산하는 데 사용한다(공백 제거 후 키 매칭)."""
    reg = _build_hwpx_registry()
    stems = _HWPX_REGISTRY_CACHE.get("stems", {})
    return {
        "normalized": sorted(reg.keys()),
        "templates": sorted(stems.values()),
    }


def _fn_part(s: Optional[str], maxlen: int = 40) -> str:
    """파일명 1구획 정리: 금지문자(/ \\ : * ? " < > |) → '_', 공백 제거, 양끝 정리, truncate.

    HWPX 다운로드 파일명(YYMMDD_업무_이름[_서류명])의 각 구획에 사용. 빈 입력 → ''."""
    import re
    s = (s or "").strip()
    s = re.sub(r'[\\/:*?"<>|]+', "_", s)   # 파일명 금지문자 → _
    s = re.sub(r"\s+", "", s)               # 공백 제거
    s = s.strip("_. ")
    return s[:maxlen]


@router.post("/generate-hwpx")
def generate_hwpx(req: FullDocGenRequest, user: dict = Depends(get_current_user)):
    """[추가 기능] HWPX 자동작성. DOC 전역 동시수 1 게이트 후 실행. PDF 경로와 독립."""
    with global_limit_sync(DOC_LOCK_KEY):
        return _generate_hwpx_impl(req, user)


def _generate_hwpx_impl(req: FullDocGenRequest, user: dict):
    """선택 서류 중 **HWPX 템플릿이 있는 모든 문서**를 HWPX 로 생성해 다운로드로 반환.

    PDF 자동작성과 동일하게 checkedDocs 기준으로 동작한다(서류명 → HWPX 템플릿 매핑은
    `_resolve_hwpx_template`, 디렉터리 자동 탐색). 결과가 1개면 단일 .hwpx, 2개 이상이면 ZIP.

    **방식 C(통합신청서에서 검증된 공통 함수 `render_hwpx_reference_swap` 재사용)**: PDF 와
    동일한 field_values·도장/서명 데이터를 사용하고, 텍스트는 CLICK_HERE 누름틀에 채운다(빈 값은
    공백 " " → 한컴 안내문 억제). 각 문서는 그 문서에 **실제 존재하는 marker 만** repoint 하며
    (엔진이 템플릿을 진단), 이미지가 없는 marker 는 투명 PNG 로 repoint(원본 placeholder 잔존 0).
    서버에서 PDF 변환하지 않는다.
    """
    if not req.selected_docs:
        raise HTTPException(status_code=400, detail="선택된 서류가 없습니다.")
    if not req.applicant_id and not (req.applicant_name or "").strip():
        raise HTTPException(status_code=400, detail="신청인을 선택하거나 이름을 입력해 주세요.")

    # HWPX 템플릿이 있는 문서만 처리. 나머지는 unsupported 로 보고.
    resolved: list = []     # [(doc_name, abs_path), ...]
    unsupported: list = []
    for d in req.selected_docs:
        p = _resolve_hwpx_template(d)
        if p and os.path.exists(p):
            resolved.append((d, p))
        else:
            unsupported.append(d)
    if not resolved:
        raise HTTPException(
            status_code=422,
            detail={"message": "선택한 서류 중 HWPX 템플릿이 있는 서류가 없습니다. "
                               "PDF 생성을 사용하거나 HWPX 템플릿을 매핑하세요.",
                    "unsupported": unsupported},
        )

    ctx = _collect_full_field_values(req, user)        # PDF 와 동일 데이터/field_values
    field_values = ctx["field_values"]
    # PDF 와 동일 규칙의 도장/서명 이미지(전 역할). 각 템플릿엔 존재하는 marker 만 엔진이 repoint.
    marker_pngs, transparent_markers = _compute_hwpx_marker_pngs(req, ctx)
    # 소득합산자(p) 문서별 분기 — 통합신청서에서만 p_relation 에 따라 배우자(s)/부모(p) 라우팅.
    has_aggregator = bool(ctx.get("aggregator")) or bool((req.aggregator_name or "").strip())
    p_relation = (req.aggregator_relation or "").strip()

    # 다운로드 파일명 구획: YYMMDD_업무_이름[_서류명].
    #  · 날짜 = 생성일 YYMMDD(하드코딩 금지)  · 이름 = 한글명 > 영문명(성+명) > '신청인'
    #  · 업무 = 사용자가 선택한 민원종류 > 카테고리 > 첫 서류명
    ymd = datetime.date.today().strftime("%y%m%d")
    _ko = _fn_part(ctx["applicant"].get("한글"))
    _en = _fn_part((ctx["applicant"].get("성") or "") + (ctx["applicant"].get("명") or ""))
    name_part = _ko or _en or "신청인"
    work_part = _fn_part(req.minwon) or _fn_part(req.category) or _fn_part(resolved[0][0]) or "서류"
    from urllib.parse import quote
    from utils.hwpx_document import render_hwpx_reference_swap

    outputs: list = []      # [(filename, hwpx_bytes), ...]
    total_filled = 0
    total_repointed = 0
    dev_log: list = []      # 개발자 진단(서버 로그 전용) — marker 명 등 상세, 사용자 미노출
    blank_boxes = 0         # 등록 이미지가 없어 빈칸(투명) 처리된 도장/서명 칸 수
    failed: list = []
    for doc_name, abs_path in resolved:
        try:
            # 통합신청서만 p→s/p 분기(문서별 overlay). 그 외는 p 원본 그대로.
            if _is_unified_application(doc_name):
                doc_fv = _unified_sp_field_overlay(field_values, has_aggregator, p_relation)
                doc_marker_pngs = _unified_sp_marker_pngs(marker_pngs, has_aggregator, p_relation)
            else:
                doc_fv, doc_marker_pngs = field_values, marker_pngs
            # empty_placeholder=" " (기본) → 빈 누름틀 안내문 억제. marker 유지(삭제/공백치환 안 함).
            hwpx_bytes, report = render_hwpx_reference_swap(abs_path, doc_fv, marker_pngs=doc_marker_pngs)
        except Exception as e:
            # 한 문서 실패가 전체를 막지 않도록 — 문서명만 사용자 안내, 상세는 서버 로그.
            failed.append(doc_name)
            dev_log.append(f"[{doc_name}] 생성 실패: {e}")
            continue
        filled = report["text"]["filled"]
        repointed = report["swap"]["repointed"]
        total_filled += len(filled)
        total_repointed += len(repointed)
        # 진단 상세(marker 명 포함)는 서버 로그에만 — 사용자 토스트에 노출하지 않는다.
        dev_log += [f"[{doc_name}] {w}" for w in report.get("warnings", [])]
        dev_log += [f"[{doc_name}] borderFill 공유: {c}" for c in report.get("conflicts", [])]
        for sk in report["swap"].get("skipped", []):
            dev_log.append(f"[{doc_name}] 도장 repoint 실패: {sk.get('marker')}({sk.get('이유')})")
        # 역할 이미지 없어 투명 처리된 칸: 사용자에겐 '개수'만, marker 명은 로그에만.
        _present = {r["marker"] for r in repointed}
        _trans_present = sorted(_present & set(transparent_markers))
        if _trans_present:
            blank_boxes += len(_trans_present)
            dev_log.append(f"[{doc_name}] 빈칸(투명) 처리: " + ",".join(_trans_present))
        outputs.append((doc_name, hwpx_bytes))   # 파일명은 마지막에 일괄 구성
        print(f"[generate_hwpx][방식C] doc={doc_name} filled={len(filled)} "
              f"repointed={len(repointed)} new_bindata={report['swap']['new_bindata']} "
              f"conflicts={len(report.get('conflicts', []))}")

    if dev_log:
        print("[generate_hwpx][detail] " + " | ".join(dev_log))   # 서버 로그 전용

    if not outputs:
        # 모든 지원 문서 생성 실패 → 500(상세는 위 서버 로그, 사용자에겐 일반 메시지)
        raise HTTPException(status_code=500, detail="HWPX 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.")

    # 사용자 안내(짧게, marker 명 미노출): 미지원/실패 문서명 + 빈칸 안내(있을 때만)
    notices: list = []
    if failed:
        notices.append("생성 실패 문서: " + ",".join(failed))
    if unsupported:
        notices.append("HWPX 미지원으로 제외: " + ",".join(unsupported))
    if blank_boxes:
        notices.append("일부 도장/서명란은 등록된 이미지가 없어 빈칸으로 처리되었습니다.")

    try:
        from backend.services import audit_service as _audit
        _audit.log_event(action="QUICK_DOC_GENERATE_HWPX", actor_login_id=user.get("sub"),
                         tenant_id=user.get("tenant_id") or user.get("sub", ""),
                         target_type="document",
                         target_id=",".join(d for d, _ in resolved)[:200],
                         payload={"customer_id": str(req.applicant_id or ""), "success": True,
                                  "pii_accessed": True, "format": "hwpx",
                                  "doc_count": len(outputs)})
    except Exception:
        pass

    common_headers = {
        "X-Hwpx-Count": str(len(outputs)),
        "X-Hwpx-Filled": str(total_filled),
        "X-Hwpx-Repointed": str(total_repointed),
        "X-Hwpx-Blank-Boxes": str(blank_boxes),
        "X-Hwpx-Notice": quote(" / ".join(notices), safe=""),
    }

    # 결과 1개 → 단일 .hwpx(YYMMDD_업무_이름.hwpx), 2개 이상 → ZIP
    # (ZIP 파일명 YYMMDD_업무_이름.zip · 내부 파일명 YYMMDD_업무_이름_서류명.hwpx).
    if len(outputs) == 1:
        _doc_name, data = outputs[0]
        fname = f"{ymd}_{work_part}_{name_part}.hwpx"
        return StreamingResponse(
            io.BytesIO(data),
            media_type="application/octet-stream",
            headers={**common_headers,
                     "Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname, safe='')}"},
        )

    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc_name, data in outputs:
            inner = f"{ymd}_{work_part}_{name_part}_{_fn_part(doc_name) or '서류'}.hwpx"
            zi = zipfile.ZipInfo(inner)
            zi.flag_bits |= 0x800   # UTF-8 파일명 플래그(한글 파일명)
            zf.writestr(zi, data)
    buf.seek(0)
    zip_name = f"{ymd}_{work_part}_{name_part}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={**common_headers,
                 "Content-Disposition": f"attachment; filename*=UTF-8''{quote(zip_name, safe='')}"},
    )


def _birth_from_reg_front(reg_front: str) -> str:
    """등록증 앞 6자리 (YYMMDD) → ``YYYY-MM-DD``.

    Heuristic: ``yy >= 50`` → 19xx, otherwise 20xx. Empty / short input
    returns ``""``. Used purely for disambiguating same-name results.
    """
    s = "".join(ch for ch in (reg_front or "") if ch.isdigit())
    if len(s) < 6:
        return ""
    yy, mm, dd = s[:2], s[2:4], s[4:6]
    century = "19" if int(yy) >= 50 else "20"
    return f"{century}{yy}-{mm}-{dd}"


_HANGUL_RE = None  # lazy compile


def _classify_query(q: str) -> tuple[int, int, int]:
    """Return ``(korean_count, english_count, digit_count)`` for the query.

    Counts only the characters that drive each search dimension. Whitespace
    and other punctuation are ignored — they don't unlock a dimension.
    """
    import re as _re
    global _HANGUL_RE
    if _HANGUL_RE is None:
        _HANGUL_RE = _re.compile(r"[가-힯]")
    kor = len(_HANGUL_RE.findall(q))
    eng = sum(1 for ch in q if ch.isascii() and ch.isalpha())
    digits = sum(1 for ch in q if ch.isdigit())
    return kor, eng, digits


def _query_passes_minlen(q: str) -> tuple[bool, str]:
    """Return ``(allowed, reason)`` for whether ``q`` reaches the search floor.

    Floors:
      - Korean: 2 characters
      - English: 2 characters
      - Digits: 3 characters

    A query passes if *any* dimension reaches its floor (mixed queries are
    accepted as long as one component qualifies).
    """
    q_trimmed = q.strip()
    if not q_trimmed:
        return False, "검색어가 비어 있습니다."
    kor, eng, digits = _classify_query(q_trimmed)
    if kor >= 2 or eng >= 2 or digits >= 3:
        return True, ""
    if kor == 1:
        return False, "한글은 2글자 이상 입력하세요."
    if eng == 1:
        return False, "영문은 2글자 이상 입력하세요."
    if digits and digits < 3:
        return False, "숫자는 3자리 이상 입력하세요."
    return False, "검색어를 입력하세요."


@router.get("/customers/search")
def search_customers(q: str = "", user: dict = Depends(get_current_user)):
    """고객 이름 검색 (역할 선택 UI용).

    Minimum query length:
      - Korean (한글) — **2 characters** (single 글자는 결과 너무 많아 차단)
      - English (성 / 명 / 풀네임) — 2 characters
      - 숫자 (전화 / 등록증) — 3 digits

    A mixed query qualifies if at least one dimension meets its floor. When
    the floor is not met the endpoint returns an empty list with a
    ``message`` field — the frontend shows it to the user instead of running
    the search and is also our defense-in-depth: even if a future caller
    forgets the client-side guard, no rows leak out.

    In local PG mode (``FEATURE_PG_CUSTOMERS=true``) reads from
    ``customers`` via ``customer_pg_service``; uses the default path in
    production. Result rows include 생년월일 (등록증 앞 6자리에서 추정) and
    전화 so callers can disambiguate same-name people.
    """
    tenant_id = user.get("tenant_id") or user.get("sub", "")

    # ── min-length gate (defense in depth) ─────────────────────────────
    # If the query is too short the backend MUST NOT search — even if the
    # frontend skipped its own guard. The response shape stays a list so
    # the existing axios call (.then(r => r.data: T[])) still works.
    allowed, _msg = _query_passes_minlen(q)
    if not allowed:
        return []

    # PG-only(Phase I): 고객 데이터는 항상 PostgreSQL(Phase C 전환).
    from backend.services.customer_pg_service import list_customers
    customers = list_customers(tenant_id) or []

    q_stripped = q.strip()
    q_lower = q_stripped.lower()
    q_digits = "".join(ch for ch in q_stripped if ch.isdigit())
    kor_count, eng_count, dig_count = _classify_query(q_stripped)

    def _match(c: dict) -> bool:
        kor = str(c.get("한글", "")).strip().lower()
        sur = str(c.get("성", "")).strip().lower()
        giv = str(c.get("명", "")).strip().lower()
        eng_full = f"{sur} {giv}".strip()
        p_digits = (
            str(c.get("연", "")).strip()
            + str(c.get("락", "")).strip()
            + str(c.get("처", "")).strip()
        )
        reg_front = str(c.get("등록증", "")).strip()

        # Korean — 2+
        if kor_count >= 2 and kor and q_lower in kor:
            return True
        # English — 2+
        if eng_count >= 2 and (
            (sur and q_lower in sur)
            or (giv and q_lower in giv)
            or (eng_full and q_lower in eng_full)
        ):
            return True
        # Digit substring — 3+
        if dig_count >= 3 and (q_digits in p_digits or q_digits in reg_front):
            return True
        return False

    customers = [c for c in customers if _match(c)]

    results = []
    for c in customers[:30]:
        p1 = str(c.get("연", "")).strip()
        p2 = str(c.get("락", "")).strip()
        p3 = str(c.get("처", "")).strip()
        phone = "-".join(x for x in [p1, p2, p3] if x)
        reg_front = str(c.get("등록증", "")).strip()
        birth = _birth_from_reg_front(reg_front)
        sur = str(c.get("성", "")).strip()
        giv = str(c.get("명", "")).strip()
        name_en = f"{sur} {giv}".strip()
        kor = str(c.get("한글", "")).strip()

        bits = [kor or "(이름없음)"]
        if name_en:
            bits.append(name_en)
        if birth:
            bits.append(birth)
        if phone:
            bits.append(phone)
        label = " · ".join(bits)

        results.append({
            "id":      str(c.get("고객ID", "")),
            "label":   label,
            "name":    kor,
            "name_en": name_en,
            "birth":   birth,
            "phone":   phone,
            "reg_no":  reg_front,
        })
    return results


# ── 원클릭 작성 ────────────────────────────────────────────────────────────────
# Output types the one-click generator knows about.
# Add to IMPLEMENTED_OUTPUTS when a new type has a working backend path.
_ALL_OUTPUTS = {"위임장", "건강보험(세대합가)", "건강보험(피부양자)", "하이코리아", "소시넷(등록증)", "소시넷(여권)"}
_IMPLEMENTED_OUTPUTS = {"위임장", "하이코리아", "소시넷(등록증)", "소시넷(여권)"}
# 출력 순서 (다중 선택 시 페이지 순서)
_OUTPUT_ORDER = ["위임장", "하이코리아", "소시넷(등록증)", "소시넷(여권)"]


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
    customer_id: Optional[str] = None  # 고객 DB ID (서명 조회용)
    site_id: Optional[str] = ""        # 하이코리아/소시넷 사이트 ID → PDF 필드 `ID`
    old_passport: Optional[str] = ""   # 소시넷(여권) 구여권번호 → PDF 필드 `opassport`
    # 도장 옵션
    apply_applicant_seal: bool = True
    apply_agent_seal: bool = True
    # 서명 옵션
    apply_applicant_sign: bool = False
    apply_agent_sign: bool = False
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
    """[로컬 PoC] DOC 전역 동시수 1 게이트 후 실제 원클릭 생성 로직 실행."""
    with global_limit_sync(DOC_LOCK_KEY):
        return _quick_poa_impl(req, user)


def _quick_poa_impl(req: QuickPoaRequest, user: dict):
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
    account = _load_account(tenant_id)

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
        # 하이코리아/소시넷 공통 사이트 ID → PDF 필드 `ID`
        "ID":          str(req.site_id or "").strip(),
        # 소시넷(여권) 구여권 → PDF 필드 `opassport`
        "opassport":   str(req.old_passport or "").strip(),
        # agent_tel 명시적 보장: _load_account 실패 시에도 항상 field_values에 포함
        "agent_tel":   str((account or {}).get("contact_tel", "") or "").strip(),
    })

    # ── 도장/서명 상호 배타 정규화 (서명 우선) ─────────────────────────────────
    # 규칙: 둘 다 true → 서명 우선 / 둘 다 false → 서명 존재 여부로 결정

    # 신청인
    if req.apply_applicant_sign and req.apply_applicant_seal:
        req.apply_applicant_seal = False
    elif not req.apply_applicant_sign and not req.apply_applicant_seal:
        _has_cust_sign = False
        if req.customer_id:
            try:
                from backend.services.signature_service import has_customer_signature
                _has_cust_sign = has_customer_signature(tenant_id, req.customer_id)  # PG-only
            except Exception:
                _has_cust_sign = False
        if _has_cust_sign:
            req.apply_applicant_sign = True
        else:
            req.apply_applicant_seal = True

    # 행정사
    if req.apply_agent_sign and req.apply_agent_seal:
        req.apply_agent_seal = False
    elif not req.apply_agent_sign and not req.apply_agent_seal:
        _has_agent_sign = False
        try:
            from backend.services.signature_service import get_agent_signature as _gas_check
            _has_agent_sign = bool(_gas_check(tenant_id))
        except Exception:
            _has_agent_sign = False
        if _has_agent_sign:
            req.apply_agent_sign = True
        else:
            req.apply_agent_seal = True

    agent_name = (account.get("contact_name", "") if account else "").strip()
    applicant_seal_name = row.get("한글", "")
    seal_bytes_by_role = {
        "applicant":     make_seal_bytes(applicant_seal_name) if req.apply_applicant_seal else None,
        "agent":         make_seal_bytes(agent_name)          if (req.apply_agent_seal and agent_name) else None,
        "accommodation": None,
        "guarantor":     None,
        "guardian":      None,
        "aggregator":    None,
    }

    # quick-poa 서명 합성
    _poa_sign_bytes: dict = {"accommodation": None, "guarantor": None, "guardian": None, "aggregator": None}
    try:
        from backend.services.signature_service import (
            get_agent_signature as _gas,
            get_customer_signature as _get_cust_sign,
        )
        import base64 as _b64poa
        def _b64tobytes(b64: Optional[str]) -> Optional[bytes]:
            if not b64: return None
            raw = b64.split(",", 1)[1] if b64.startswith("data:") else b64
            return _b64poa.b64decode(raw)
        # 고객 서명: customer_id가 있으면 DB에서 조회
        if req.apply_applicant_sign and req.customer_id:
            try:
                # PG-only: tenant_id 로 직접 조회.
                _poa_sign_bytes["applicant"] = _b64tobytes(_get_cust_sign(tenant_id, req.customer_id))
            except Exception:
                _poa_sign_bytes["applicant"] = None
        else:
            _poa_sign_bytes["applicant"] = None
        _poa_sign_bytes["agent"] = _b64tobytes(_gas(tenant_id)) if req.apply_agent_sign else None
    except Exception:
        _poa_sign_bytes["applicant"] = None
        _poa_sign_bytes["agent"] = None

    # ── 최종 방어: 서명 데이터 없는데 서명 선택 → 도장 fallback ─────────────
    for role, seal_name in (("applicant", applicant_seal_name), ("agent", agent_name)):
        if _poa_sign_bytes.get(role) is None and not seal_bytes_by_role.get(role):
            # 서명도 없고 도장도 없으면 도장 생성 (이름이 있는 경우)
            if seal_name:
                seal_bytes_by_role[role] = make_seal_bytes(seal_name)
    # 같은 역할에 도장+서명 동시 존재 → 서명 우선, 도장 제거
    for role in ("applicant", "agent"):
        if seal_bytes_by_role.get(role) and _poa_sign_bytes.get(role):
            seal_bytes_by_role[role] = None

    try:
        import fitz
        merged_doc = fitz.open()
        for out_type in ordered_outputs:
            fill_and_append_pdf(template_paths[out_type], field_values, seal_bytes_by_role, merged_doc, _poa_sign_bytes)
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


# 기존 /generate 엔드포인트 유지 (하위 호환).
# 현재 프론트에서 직접 호출하는 화면은 없으나(quickDocApi.generate 미사용), 외부에서 호출
# 가능한 상태이므로 문서생성 계열과 동일하게 DOC 전역 동시수 1(대기) 정책으로 묶는다.
@router.post("/generate")
def generate_documents(req: DocGenRequest, user: dict = Depends(get_current_user)):
    """[로컬 PoC] DOC 전역 동시수 1 게이트 후 실제 병합 로직 실행."""
    with global_limit_sync(DOC_LOCK_KEY):
        return _generate_documents_impl(req, user)


def _generate_documents_impl(req: DocGenRequest, user: dict):
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
