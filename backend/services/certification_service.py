"""
backend/services/certification_service.py

각종공인증 서비스 — 각 테넌트의 업무정리(work_sheet_key) 워크북 전용 탭에 저장.

중요: 이 서비스는 반드시 work_sheet_key를 사용합니다.
     customer_sheet_key / 고객 데이터 워크북에는 절대 쓰지 않습니다.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import threading
import time
from datetime import datetime
from typing import List, Dict, Optional
import uuid

from backend.services.tenant_service import (
    get_work_sheet_key, get_customer_sheet_key, _get_spreadsheet,
)
import config as _cfg

# ── 테넌트별 인메모리 캐시 (TTL 120초) ─────────────────────────────────────────
# 키: work_sheet_key, 값: {"data": {...}, "ts": float}
_CERT_CACHE: Dict[str, Dict] = {}
_CERT_CACHE_TTL = 120.0
_CERT_CACHE_LOCK = threading.Lock()

def _cache_get(sheet_key: str) -> Optional[Dict]:
    """캐시 히트면 data dict 반환, miss/expired면 None."""
    with _CERT_CACHE_LOCK:
        entry = _CERT_CACHE.get(sheet_key)
        if entry and (time.time() - entry["ts"]) < _CERT_CACHE_TTL:
            return entry["data"]
        return None

def _cache_put(sheet_key: str, data: Dict) -> None:
    with _CERT_CACHE_LOCK:
        _CERT_CACHE[sheet_key] = {"data": data, "ts": time.time()}

def _cache_invalidate(sheet_key: str) -> None:
    """쓰기 후 해당 테넌트 캐시 삭제."""
    with _CERT_CACHE_LOCK:
        _CERT_CACHE.pop(sheet_key, None)

# ── 탭 존재 보장 플래그 (프로세스 내 1회만 ensure_all_sheets 실행) ────────────
# 키: work_sheet_key. 한 번 확인된 워크북은 재확인하지 않음.
_ENSURED_WORKBOOKS: set = set()
_ENSURED_WB_LOCK = threading.Lock()

def _is_ensured(sheet_key: str) -> bool:
    with _ENSURED_WB_LOCK:
        return sheet_key in _ENSURED_WORKBOOKS

def _mark_ensured(sheet_key: str) -> None:
    with _ENSURED_WB_LOCK:
        _ENSURED_WORKBOOKS.add(sheet_key)

def _clear_ensured(sheet_key: str) -> None:
    """탭이 갑자기 사라진 경우(예: 수동 삭제) 플래그 리셋."""
    with _ENSURED_WB_LOCK:
        _ENSURED_WORKBOOKS.discard(sheet_key)

# ── 시트 이름 ──────────────────────────────────────────────────────────────────
SHEET_VENDORS    = "각종공인증_업체"
SHEET_DIRECTIONS = "각종공인증_대분류"
SHEET_GROUPS     = "각종공인증_중분류"
SHEET_REGIONS    = "각종공인증_소분류지역"
SHEET_PRICES     = "각종공인증_가격조건"

# ── 헤더 ───────────────────────────────────────────────────────────────────────
VENDORS_HEADER    = ["id", "name", "contact", "memo", "active", "created_at", "updated_at"]
DIRECTIONS_HEADER = ["id", "name", "sort_order", "active", "created_at", "updated_at"]
GROUPS_HEADER     = ["id", "group_name", "aliases", "default_direction", "applicable_directions", "sort_order", "active", "created_at", "updated_at"]
REGIONS_HEADER    = ["id", "name", "applicable_directions", "applicable_group_ids", "sort_order", "active", "created_at", "updated_at"]
PRICES_HEADER     = [
    "id", "vendor_id", "group_id", "direction", "region", "condition",
    "price", "possible", "documents", "lead_time", "strength", "risk",
    "source", "last_checked", "created_at", "updated_at",
]

HEADERS_MAP = {
    SHEET_VENDORS:    VENDORS_HEADER,
    SHEET_DIRECTIONS: DIRECTIONS_HEADER,
    SHEET_GROUPS:     GROUPS_HEADER,
    SHEET_REGIONS:    REGIONS_HEADER,
    SHEET_PRICES:     PRICES_HEADER,
}

_ENSURE_LOCK = threading.Lock()
_D = "2026-05-26"  # seed date

# ── 스키마 마이그레이션 플래그 (프로세스 내 1회) ───────────────────────────────
_MIGRATED_WORKBOOKS: set = set()
_MIGRATE_LOCK = threading.Lock()


class ReferenceConflictError(Exception):
    """Raised when a delete is blocked because price rows still reference the item."""
    pass


# ── 시드 데이터 ────────────────────────────────────────────────────────────────

SEED_VENDORS = [
    {"id": "vendor-yudam",       "name": "유담여행사",      "contact": "", "memo": "유담국제여행사", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "vendor-sindongbang", "name": "신동방국제여행사", "contact": "", "memo": "",              "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "vendor-hanseong",    "name": "한성국제여행사",   "contact": "", "memo": "",              "active": "true", "created_at": _D, "updated_at": _D},
]

SEED_DIRECTIONS = [
    {"id": "dir-china-korea", "name": "중국 → 한국",       "sort_order": "1", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "dir-korea-china", "name": "한국 → 중국",       "sort_order": "2", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "dir-korea-other", "name": "한국 → 기타국가",   "sort_order": "3", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "dir-china-local", "name": "중국 현지 내부처리", "sort_order": "4", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "dir-korea-local", "name": "한국 국내처리",     "sort_order": "5", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "dir-china-visa",  "name": "중국 비자/입국",    "sort_order": "6", "active": "true", "created_at": _D, "updated_at": _D},
]

SEED_GROUPS = [
    # applicable_directions: default_direction 외에 추가로 적용 가능한 대분류 (없으면 "")
    {"id": "grp-kinship",        "group_name": "친족·가족관계 공증",     "aliases": "친속,친속공증,친속관계공증,가족관계 공증,친족관계 공증",       "default_direction": "중국 → 한국",        "applicable_directions": "",             "sort_order": "1",  "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "grp-marriage",       "group_name": "혼인·결혼 공증",         "aliases": "결혼공증,혼인공증",                                          "default_direction": "중국 → 한국",        "applicable_directions": "",             "sort_order": "2",  "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "grp-single",         "group_name": "미혼·미재혼 공증",       "aliases": "미혼공증,미재혼공증",                                        "default_direction": "중국 → 한국",        "applicable_directions": "",             "sort_order": "3",  "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "grp-nocrime",        "group_name": "무범죄 공증/발급",       "aliases": "무범죄,무범죄공증",                                          "default_direction": "중국 → 한국",        "applicable_directions": "",             "sort_order": "4",  "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "grp-hukou-china",    "group_name": "호구부 중국 현지 공증",   "aliases": "호구부공증,호구부 원본공증,호구부 중국공증",                  "default_direction": "중국 → 한국",        "applicable_directions": "",             "sort_order": "5",  "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "grp-hukou-korea",    "group_name": "호구부 한국 번역공증",    "aliases": "호구부 번역공증,한국 호구부 번역공증,호구부 한국공증",         "default_direction": "한국 국내처리",      "applicable_directions": "한국 → 중국",  "sort_order": "6",  "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "grp-apostille",      "group_name": "한국서류 공증+Apostille", "aliases": "한국공인증,한국공증,아포스티유,한국공증아포스티유",            "default_direction": "한국 → 중국",        "applicable_directions": "한국 → 기타국가", "sort_order": "7",  "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "grp-license-notary", "group_name": "중국 운전면허증 공증",    "aliases": "운전면허,운전면허공증,운전면허증공증,면허증공증",              "default_direction": "중국 → 한국",        "applicable_directions": "",             "sort_order": "8",  "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "grp-license-renew",  "group_name": "중국 운전면허 갱신",      "aliases": "운전면허갱신,중국운전면허갱신,면허증갱신,C형,A형,B형,C종,A종,B종", "default_direction": "중국 현지 내부처리", "applicable_directions": "",             "sort_order": "9",  "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "grp-license-reissue","group_name": "중국 운전면허 분실 재발급","aliases": "운전면허분실,면허증분실재발급",                               "default_direction": "중국 현지 내부처리", "applicable_directions": "",             "sort_order": "10", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "grp-id-renew",       "group_name": "중국 신분증 갱신/재발급", "aliases": "신분증갱신,중국신분증,신분증분실,신분증발급",                  "default_direction": "중국 현지 내부처리", "applicable_directions": "",             "sort_order": "11", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "grp-hukou-cancel",   "group_name": "중국 호구말소/호구정리",  "aliases": "호구말소,중국호구말소,호구정리,호구부정리,호구부재발급",        "default_direction": "중국 현지 내부처리", "applicable_directions": "",             "sort_order": "12", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "grp-china-visa",     "group_name": "중국 비자",               "aliases": "L비자,M비자,Q2비자,Z비자,X1비자,X2비자,중국비자",             "default_direction": "중국 비자/입국",     "applicable_directions": "",             "sort_order": "13", "active": "true", "created_at": _D, "updated_at": _D},
]

SEED_REGIONS = [
    # applicable_directions: 이 지역이 유효한 대분류 목록 (없으면 모든 대분류에 표시)
    # applicable_group_ids:  이 지역이 유효한 중분류 id 목록 (없으면 해당 대분류 내 모두 표시)
    {"id": "rgn-all",              "name": "전국",                   "applicable_directions": "중국 → 한국,중국 비자/입국",                        "applicable_group_ids": "",                                    "sort_order": "1", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "rgn-jilin",            "name": "길림지역 및 외성",       "applicable_directions": "중국 → 한국,중국 현지 내부처리",                    "applicable_group_ids": "",                                    "sort_order": "2", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "rgn-yanbian",          "name": "연변주 및 장백조선족향", "applicable_directions": "중국 현지 내부처리",                                "applicable_group_ids": "grp-id-renew",                        "sort_order": "3", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "rgn-heilongjiang",     "name": "흑룡강성 및 로녕성",    "applicable_directions": "중국 현지 내부처리",                                "applicable_group_ids": "grp-id-renew",                        "sort_order": "4", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "rgn-china",            "name": "중국",                   "applicable_directions": "중국 → 한국,중국 현지 내부처리,중국 비자/입국",     "applicable_group_ids": "",                                    "sort_order": "5", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "rgn-other-national",   "name": "전국기타",               "applicable_directions": "중국 현지 내부처리",                                "applicable_group_ids": "grp-id-renew",                        "sort_order": "6", "active": "true", "created_at": _D, "updated_at": _D},
    {"id": "rgn-region-irrelevant","name": "지역상관없음",           "applicable_directions": "중국 현지 내부처리",                                "applicable_group_ids": "grp-license-renew,grp-license-reissue","sort_order": "7", "active": "true", "created_at": _D, "updated_at": _D},
]

SEED_PRICES = [
    {"id": "price-yudam-license-c",       "vendor_id": "vendor-yudam",    "group_id": "grp-license-renew",  "direction": "중국 현지 내부처리", "region": "지역상관없음",       "condition": "C형 면허증 갱신 / 최신 유담 기준",      "price": "220000", "possible": "가능", "documents": "면허증, 신분증, 증명사진 3매(2.5×3.5)",                                    "lead_time": "문의", "strength": "최신 유담 2025-06-01 가격표 기준 C형 22만원",   "risk": "서류 전체 원본+동영상 및 자세사진 필요. 자세사진 양식은 수시로 변동될 수 있음", "source": "최신 유담 2025-06-01 가격표", "last_checked": "2025-06-01", "created_at": _D, "updated_at": _D},
    {"id": "price-yudam-license-a",       "vendor_id": "vendor-yudam",    "group_id": "grp-license-renew",  "direction": "중국 현지 내부처리", "region": "지역상관없음",       "condition": "A형 면허증 갱신 / 최신 유담 기준",      "price": "240000", "possible": "가능", "documents": "면허증, 신분증, 증명사진 3매(2.5×3.5)",                                    "lead_time": "문의", "strength": "최신 유담 2025-06-01 가격표 기준 A형 24만원",   "risk": "서류 전체 원본+동영상 및 자세사진 필요. 자세사진 양식은 수시로 변동될 수 있음", "source": "최신 유담 2025-06-01 가격표", "last_checked": "2025-06-01", "created_at": _D, "updated_at": _D},
    {"id": "price-yudam-license-b",       "vendor_id": "vendor-yudam",    "group_id": "grp-license-renew",  "direction": "중국 현지 내부처리", "region": "지역상관없음",       "condition": "B형 면허증 갱신 / 최신 유담 기준",      "price": "240000", "possible": "가능", "documents": "면허증, 신분증, 증명사진 3매(2.5×3.5)",                                    "lead_time": "문의", "strength": "최신 유담 2025-06-01 가격표 기준 B형 24만원",   "risk": "서류 전체 원본+동영상 및 자세사진 필요. 자세사진 양식은 수시로 변동될 수 있음", "source": "최신 유담 2025-06-01 가격표", "last_checked": "2025-06-01", "created_at": _D, "updated_at": _D},
    {"id": "price-hanseong-license-c",    "vendor_id": "vendor-hanseong", "group_id": "grp-license-renew",  "direction": "중국 현지 내부처리", "region": "중국",               "condition": "C종 운전면허 갱신 / 최신 한성 PDF 기준", "price": "200000", "possible": "가능", "documents": "면허증 원본, 신분증 원본, 증명사진 3매(3.2cm×2.2cm), 적성검사 사진+동영상", "lead_time": "문의", "strength": "최신 한성국제 PDF 기준 C종 20만원",           "risk": "최신 업체자료 기준 우선. 업무정리 구버전의 사진규격과 다르면 최신 업체자료를 우선 적용", "source": "최신 한성국제 PDF", "last_checked": "2026-05-25", "created_at": _D, "updated_at": _D},
    {"id": "price-hanseong-license-ab",   "vendor_id": "vendor-hanseong", "group_id": "grp-license-renew",  "direction": "중국 현지 내부처리", "region": "중국",               "condition": "A/B증 갱신 / 세부조건 확인필요",        "price": "220000", "possible": "문의", "documents": "한성 PDF: 면허증 원본, 신분증 원본, 증명사진 3매, 적성검사 사진+동영상",    "lead_time": "문의", "strength": "",                                           "risk": "A/B증 조건은 접수 전 확인 필요",                                                  "source": "최신 한성국제 PDF", "last_checked": "2026-05-25", "created_at": _D, "updated_at": _D},
    {"id": "price-yudam-id-jilin",        "vendor_id": "vendor-yudam",    "group_id": "grp-id-renew",       "direction": "중국 현지 내부처리", "region": "길림지역 및 외성",   "condition": "신분증 갱신 / 최신 유담 기준",          "price": "400000", "possible": "가능", "documents": "전자파일 사진, 신분증 혹은 호구부 사본, 지문랩",                           "lead_time": "문의", "strength": "",                                           "risk": "유효기간 지난 신분증은 유효기한 지난 시간에 따라 추가요금 있을 수 있음",         "source": "최신 유담 2025-06-01 가격표", "last_checked": "2025-06-01", "created_at": _D, "updated_at": _D},
    {"id": "price-yudam-id-yanbian",      "vendor_id": "vendor-yudam",    "group_id": "grp-id-renew",       "direction": "중국 현지 내부처리", "region": "연변주 및 장백조선족향","condition": "신분증 갱신 / 최신 유담 기준",          "price": "500000", "possible": "가능", "documents": "전자파일 사진, 신분증 혹은 호구부 사본, 지문랩",                           "lead_time": "문의", "strength": "",                                           "risk": "유효기간 지난 신분증은 유효기한 지난 시간에 따라 추가요금 있을 수 있음",         "source": "최신 유담 2025-06-01 가격표", "last_checked": "2025-06-01", "created_at": _D, "updated_at": _D},
    {"id": "price-yudam-id-heilongjiang", "vendor_id": "vendor-yudam",    "group_id": "grp-id-renew",       "direction": "중국 현지 내부처리", "region": "흑룡강성 및 로녕성",  "condition": "신분증 갱신 / 최신 유담 기준",          "price": "400000", "possible": "가능", "documents": "전자파일 사진, 지문등록동영상, 지문랩",                                    "lead_time": "문의", "strength": "",                                           "risk": "추가요금 없음",                                                                   "source": "최신 유담 2025-06-01 가격표", "last_checked": "2025-06-01", "created_at": _D, "updated_at": _D},
    {"id": "price-hanseong-id-national",  "vendor_id": "vendor-hanseong", "group_id": "grp-id-renew",       "direction": "중국 현지 내부처리", "region": "전국기타",            "condition": "신분증 갱신/분실",                      "price": "380000", "possible": "가능", "documents": "신분증 사본, 여권 사본, 양손 엄지 지문, 전자상반신사진",                   "lead_time": "문의", "strength": "",                                           "risk": "연변/오상시는 추가서류 요구",                                                      "source": "최신 한성국제 PDF", "last_checked": "2026-05-25", "created_at": _D, "updated_at": _D},
    {"id": "price-yudam-license-notary",  "vendor_id": "vendor-yudam",    "group_id": "grp-license-notary", "direction": "중국 → 한국",        "region": "전국",               "condition": "운전면허 공증",                         "price": "40000",  "possible": "가능", "documents": "신분증 + 면허증 + 면허증 부본 스캔본",                                     "lead_time": "문의", "strength": "",                                           "risk": "공증만인지, 공증+인증인지 접수 전 확인",                                           "source": "",                         "last_checked": "2026-05-13", "created_at": _D, "updated_at": _D},
    {"id": "price-yudam-license-lost",    "vendor_id": "vendor-yudam",    "group_id": "grp-license-reissue","direction": "중국 현지 내부처리", "region": "중국",               "condition": "면허증 분실 재발급 / 구버전 업무정리 참고","price": "0",     "possible": "문의", "documents": "구버전 업무정리: 중국신분증, 면허증 사진, 1촌 흰판 3장, 흰배경 전신사진 + 사진파일", "lead_time": "문의", "strength": "구버전 업무정리에는 유담 원가 15만원으로 기재", "risk": "최신 유담 2025-06-01 가격표에는 면허증갱신 C/A/B만 있고 분실 재발급은 확인되지 않음. 최신 기준으로 가격 미사용", "source": "구버전 업무정리 참고", "last_checked": "구버전", "created_at": _D, "updated_at": _D},
]


# ── 내부 헬퍼 ──────────────────────────────────────────────────────────────────

def _col_letter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _ensure_worksheet(sh, sheet_name: str, headers: List[str], sheet_key: str = ""):
    """
    워크시트 가져오기.

    sheet_key가 이미 _ENSURED_WORKBOOKS에 있으면:
      sh._sheets(gspread 내부 캐시) 에서 직접 조회 → API 호출 없음.
    그렇지 않으면:
      sh.worksheets() 로 목록 조회(1 API 호출), 없으면 생성+헤더 write.
    """
    if sheet_key and _is_ensured(sheet_key):
        # gspread Spreadsheet 객체의 내부 캐시 사용 (worksheets() API 호출 없음)
        ws = next((s for s in getattr(sh, "_sheets", []) if s.title == sheet_name), None)
        if ws is not None:
            return ws, False
        # _sheets에 없음 → 탭이 수동 삭제됐을 가능성 → ensured 플래그 해제 후 재확인
        _clear_ensured(sheet_key)

    titles = [ws.title for ws in sh.worksheets()]  # API 호출 (최초 또는 미ensure 경우만)
    if sheet_name not in titles:
        ws = sh.add_worksheet(title=sheet_name, rows=500, cols=len(headers) + 2)
        ws.update("A1", [headers], value_input_option="RAW")
        return ws, True
    return sh.worksheet(sheet_name), False


def _read_all(ws) -> List[Dict]:
    """헤더 row를 키로 사용해 전체 행 반환."""
    values = ws.get_all_values()
    if not values or len(values) < 1:
        return []
    header = values[0]
    result = []
    for row in values[1:]:
        if not any(cell.strip() for cell in row):
            continue
        padded = row + [""] * (len(header) - len(row))
        result.append(dict(zip(header, padded)))
    return result


def _upsert_rows(ws, headers: List[str], records: List[Dict]):
    """
    id 기반 upsert.
    - 기존 id 있으면 해당 row range만 update (전체 overwrite 금지)
    - 신규 id면 append_rows
    - 헤더가 없는 완전 빈 시트일 때만 헤더 1행 write 후 append

    금지: ws.clear(), 전체 rows를 A1부터 재작성
    허용: 완전 빈 탭 최초 헤더+seed 쓰기 (1회), 특정 row range update, append_rows
    """
    if not records:
        return
    values = ws.get_all_values()
    last_col = _col_letter(len(headers))

    if not values:
        # 완전히 빈 시트(헤더조차 없음) — 헤더 1행만 write 후 데이터는 append
        ws.update("A1", [headers], value_input_option="RAW")
        row_vals = [[str(r.get(c, "")) for c in headers] for r in records]
        if row_vals:
            ws.append_rows(row_vals, value_input_option="RAW")
        return

    header = values[0]
    if header != headers:
        # 헤더 불일치 시 row 1만 update
        ws.update(f"A1:{last_col}1", [headers], value_input_option="RAW")

    id_idx = headers.index("id") if "id" in headers else -1
    existing: Dict[str, int] = {}
    if id_idx >= 0:
        for r_i, row in enumerate(values[1:], start=2):
            if id_idx < len(row):
                rid = str(row[id_idx]).strip()
                if rid:
                    existing[rid] = r_i

    updates = []
    appends = []
    for rec in records:
        rid = str(rec.get("id", "")).strip()
        row_vals = [str(rec.get(c, "")) for c in headers]
        if rid and rid in existing:
            row_no = existing[rid]
            # 해당 row range만 update — 전체 시트 overwrite 아님
            updates.append({"range": f"A{row_no}:{last_col}{row_no}", "values": [row_vals]})
        else:
            appends.append(row_vals)

    if updates:
        ws.batch_update(updates, value_input_option="RAW")
    if appends:
        ws.append_rows(appends, value_input_option="RAW")


def _delete_rows(ws, rids: List[str]):
    """id 목록에 해당하는 행 삭제 (역순)."""
    if not rids:
        return
    rids_set = set(str(r).strip() for r in rids)
    values = ws.get_all_values()
    if not values:
        return
    header = values[0]
    if "id" not in header:
        return
    id_idx = header.index("id")
    to_delete = []
    for r_i, row in enumerate(values[1:], start=2):
        if id_idx < len(row) and str(row[id_idx]).strip() in rids_set:
            to_delete.append(r_i)
    for row_no in sorted(to_delete, reverse=True):
        ws.delete_rows(row_no)


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── 공개 API ───────────────────────────────────────────────────────────────────

def _run_schema_migration(sh, sheet_key: str) -> None:
    """
    기존 각종공인증_중분류/소분류지역 탭에 applicable_directions/applicable_group_ids
    컬럼이 없으면 헤더 row만 확장하고 seed row만 업데이트.

    금지: 전체 시트 clear / 전체 rows rewrite
    허용: 헤더 row 1 update, 특정 id row batch_update
    프로세스 내 work_sheet_key 당 1회만 실행.
    """
    global _MIGRATED_WORKBOOKS
    if sheet_key in _MIGRATED_WORKBOOKS:
        return
    with _MIGRATE_LOCK:
        if sheet_key in _MIGRATED_WORKBOOKS:
            return

        # ── 중분류 탭: applicable_directions 컬럼 추가 ────────────────────────
        try:
            ws_grp = sh.worksheet(SHEET_GROUPS)
            header = ws_grp.row_values(1)  # 헤더 1행만 read
            if "applicable_directions" not in header:
                print(f"[cert_migrate] 중분류 탭 스키마 업그레이드: applicable_directions 컬럼 추가")
                _upsert_rows(ws_grp, GROUPS_HEADER, SEED_GROUPS)
            else:
                print(f"[cert_migrate] 중분류 탭 이미 최신 스키마")
        except Exception as e:
            print(f"[cert_migrate] 중분류 마이그레이션 오류: {e}")

        # ── 소분류지역 탭: applicable_directions + applicable_group_ids 컬럼 추가
        try:
            ws_rgn = sh.worksheet(SHEET_REGIONS)
            header = ws_rgn.row_values(1)  # 헤더 1행만 read
            if "applicable_directions" not in header or "applicable_group_ids" not in header:
                print(f"[cert_migrate] 소분류지역 탭 스키마 업그레이드: applicable_directions/group_ids 컬럼 추가")
                _upsert_rows(ws_rgn, REGIONS_HEADER, SEED_REGIONS)
            else:
                print(f"[cert_migrate] 소분류지역 탭 이미 최신 스키마")
        except Exception as e:
            print(f"[cert_migrate] 소분류지역 마이그레이션 오류: {e}")

        _MIGRATED_WORKBOOKS.add(sheet_key)
        print(f"[cert_migrate] ✅ 스키마 마이그레이션 완료: {sheet_key!r}")


def ensure_all_sheets(tenant_id: str) -> None:
    """
    5개 각종공인증 탭이 없으면 생성 + seed.
    프로세스 내에서 work_sheet_key 당 딱 1번만 실행 (_ENSURED_WORKBOOKS).
    """
    sheet_key = get_work_sheet_key(tenant_id)
    if _is_ensured(sheet_key):
        return

    with _ENSURE_LOCK:
        if _is_ensured(sheet_key):
            return

        sh = _get_spreadsheet(sheet_key)
        existing_titles = {ws.title for ws in sh.worksheets()}

        # ── 진단 로그 ──────────────────────────────────────────────────────────
        _is_tmpl = (sheet_key == _cfg.WORK_REFERENCE_TEMPLATE_ID)
        print(f"[cert_ensure] tenant_id={tenant_id!r}")
        print(f"[cert_ensure] TENANT_MODE={_cfg.TENANT_MODE}")
        print(f"[cert_ensure] work_sheet_key={sheet_key!r}")
        if _is_tmpl:
            print(f"[cert_ensure] ⚠️  FALLBACK: work_sheet_key == WORK_REFERENCE_TEMPLATE_ID (템플릿). "
                  "Accounts 시트에 work_sheet_key 미설정. 올바른 업무정리 시트 ID를 Accounts에 입력하세요.")
        print(f"[cert_ensure] spreadsheet title={sh.title!r}  id={sh.id!r}")
        print(f"[cert_ensure] existing tabs ({len(existing_titles)}): {sorted(existing_titles)!r}")
        # ── ─────────────────────────────────────────────────────────────────────

        seed_map = {
            SHEET_VENDORS:    SEED_VENDORS,
            SHEET_DIRECTIONS: SEED_DIRECTIONS,
            SHEET_GROUPS:     SEED_GROUPS,
            SHEET_REGIONS:    SEED_REGIONS,
            SHEET_PRICES:     SEED_PRICES,
        }

        for sheet_name, headers in HEADERS_MAP.items():
            if sheet_name not in existing_titles:
                print(f"[cert_ensure] 탭 없음 → 생성: {sheet_name!r}")
                ws = sh.add_worksheet(title=sheet_name, rows=500, cols=len(headers) + 2)
                ws.update("A1", [headers], value_input_option="RAW")
                seed = seed_map.get(sheet_name, [])
                if seed:
                    row_vals = [[str(r.get(c, "")) for c in headers] for r in seed]
                    ws.append_rows(row_vals, value_input_option="RAW")
                    print(f"[cert_ensure] seed {len(seed)}행 → {sheet_name!r}")
            else:
                print(f"[cert_ensure] 탭 이미 존재: {sheet_name!r}")

        # 기존 탭에 새 컬럼이 없으면 헤더만 확장 (row 단위 update, 전체 rewrite 금지)
        _run_schema_migration(sh, sheet_key)

        _mark_ensured(sheet_key)
        print(f"[cert_ensure] ✅ 완료. cert tabs ensured in {sh.title!r} ({sh.id!r})")


def bootstrap(tenant_id: str) -> Dict:
    """
    전체 데이터 반환.

    최적화:
    1. 캐시 히트(TTL 120s) → Sheets API 호출 0회
    2. 캐시 미스 → ensure_all_sheets (프로세스 최초 1회만 실제 동작)
                    → 5개 탭 각 1회 read (총 5 reads) → 결과 캐싱
    """
    sheet_key = get_work_sheet_key(tenant_id)
    _is_tmpl = (sheet_key == _cfg.WORK_REFERENCE_TEMPLATE_ID)
    print(f"[cert_bootstrap] tenant_id={tenant_id!r}  TENANT_MODE={_cfg.TENANT_MODE}")
    print(f"[cert_bootstrap] work_sheet_key={sheet_key!r}"
          + (" ← ⚠️ TEMPLATE FALLBACK" if _is_tmpl else ""))

    cached = _cache_get(sheet_key)
    if cached is not None:
        print(f"[cert_bootstrap] cache HIT — returning cached data")
        return cached

    # 탭 존재 보장 (프로세스 최초 1회만 실제 실행, 이후는 즉시 반환)
    ensure_all_sheets(tenant_id)

    sh = _get_spreadsheet(sheet_key)
    try:
        data = {
            "vendors":    _read_all(sh.worksheet(SHEET_VENDORS)),
            "directions": _read_all(sh.worksheet(SHEET_DIRECTIONS)),
            "groups":     _read_all(sh.worksheet(SHEET_GROUPS)),
            "regions":    _read_all(sh.worksheet(SHEET_REGIONS)),
            "prices":     _read_all(sh.worksheet(SHEET_PRICES)),
        }
    except Exception:
        # 워크시트를 찾을 수 없는 경우 (수동 삭제 등) → ensured 플래그 리셋
        _clear_ensured(sheet_key)
        raise

    print(f"[cert_bootstrap] ✅ loaded from {sh.title!r} ({sh.id!r}): "
          f"vendors={len(data['vendors'])} dirs={len(data['directions'])} "
          f"groups={len(data['groups'])} regions={len(data['regions'])} "
          f"prices={len(data['prices'])}")
    _cache_put(sheet_key, data)
    return data


def debug_storage_info(tenant_id: str, login_id: str = "") -> Dict:
    """
    진단용: 현재 테넌트가 실제로 어느 스프레드시트에 각종공인증 데이터를 저장하는지 반환.
    /api/certification-services/debug-storage 에서 호출.
    """
    work_key = get_work_sheet_key(tenant_id)
    is_tmpl = (work_key == _cfg.WORK_REFERENCE_TEMPLATE_ID)

    try:
        customer_key = get_customer_sheet_key(tenant_id)
    except Exception as e:
        customer_key = f"ERROR: {e}"

    # 업무정리 스프레드시트 열기
    work_title, work_tabs = "", []
    try:
        sh_work = _get_spreadsheet(work_key)
        work_title = sh_work.title
        work_tabs = [ws.title for ws in sh_work.worksheets()]
    except Exception as e:
        work_title = f"ERROR: {e}"

    # 고객 데이터 스프레드시트 제목만
    customer_title = ""
    if isinstance(customer_key, str) and not customer_key.startswith("ERROR"):
        try:
            sh_cust = _get_spreadsheet(customer_key)
            customer_title = sh_cust.title
        except Exception as e:
            customer_title = f"ERROR: {e}"

    cert_tabs_status = {
        name: (name in work_tabs)
        for name in [SHEET_VENDORS, SHEET_DIRECTIONS, SHEET_GROUPS, SHEET_REGIONS, SHEET_PRICES]
    }

    return {
        "login_id": login_id,
        "tenant_id": tenant_id,
        "tenant_mode": _cfg.TENANT_MODE,
        "default_tenant_id": _cfg.DEFAULT_TENANT_ID,
        # ── 업무정리 ───────────────────────────────────────────────────────────
        "work_sheet_key": work_key,
        "work_reference_template_id": _cfg.WORK_REFERENCE_TEMPLATE_ID,
        "is_using_template_as_work": is_tmpl,
        "work_spreadsheet_title": work_title,
        "existing_tabs_in_workbook": work_tabs,
        # ── 고객 데이터 ────────────────────────────────────────────────────────
        "customer_sheet_key": customer_key,
        "customer_spreadsheet_title": customer_title,
        # ── 각종공인증 탭 상태 ──────────────────────────────────────────────────
        "certification_target": "work_sheet_key",
        "certification_tabs_status": cert_tabs_status,
        # ── 진단 메시지 ────────────────────────────────────────────────────────
        "warning": (
            "⚠️ work_sheet_key가 Accounts 시트에 설정되지 않아 "
            f"WORK_REFERENCE_TEMPLATE_ID({_cfg.WORK_REFERENCE_TEMPLATE_ID})로 fallback됩니다. "
            "관리자 페이지 → 워크스페이스에서 해당 사무소의 업무정리 시트 ID를 입력하세요."
        ) if is_tmpl else "",
        "note": (
            "로컬 개발 모드(TENANT_MODE=False)에서 Accounts 시트에 work_sheet_key 컬럼이 "
            "비어 있으면 WORK_REFERENCE_TEMPLATE_ID로 fallback됩니다."
        ) if not _cfg.TENANT_MODE else "",
    }


def _get_cached_prices(tenant_id: str) -> List[Dict]:
    """
    reference 체크 전용: 캐시에서 prices를 가져옴.
    캐시 미스면 가격조건 탭만 1회 read.
    다른 4개 탭은 읽지 않음.
    """
    sheet_key = get_work_sheet_key(tenant_id)
    cached = _cache_get(sheet_key)
    if cached is not None:
        return cached.get("prices", [])
    # 캐시 없으면 가격조건 탭만 직접 읽음
    return get_prices(tenant_id)


def _get_cached_vendors(tenant_id: str) -> List[Dict]:
    """캐시에서 vendors 가져옴. 캐시 미스면 업체 탭만 read."""
    sheet_key = get_work_sheet_key(tenant_id)
    cached = _cache_get(sheet_key)
    if cached is not None:
        return cached.get("vendors", [])
    return get_vendors(tenant_id)


# ── Vendor CRUD ────────────────────────────────────────────────────────────────

def get_vendors(tenant_id: str) -> List[Dict]:
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    return _read_all(sh.worksheet(SHEET_VENDORS))


def save_vendor(tenant_id: str, vendor: Dict) -> Dict:
    if not vendor.get("id"):
        vendor["id"] = "vendor-" + str(uuid.uuid4())[:8]
    now = _now_str()
    vendor.setdefault("created_at", now)
    vendor["updated_at"] = now
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    ws, _ = _ensure_worksheet(sh, SHEET_VENDORS, VENDORS_HEADER, sheet_key)
    _upsert_rows(ws, VENDORS_HEADER, [vendor])
    _cache_invalidate(sheet_key)
    return vendor


def delete_vendor(tenant_id: str, vendor_id: str) -> Dict:
    """
    가격조건이 연결된 업체 → active=false (soft-delete).
    연결 없으면 hard-delete.
    참조 체크는 캐시 우선 사용 (캐시 미스 시만 Sheets read).
    """
    sheet_key = get_work_sheet_key(tenant_id)
    prices = _get_cached_prices(tenant_id)
    ref_count = sum(1 for p in prices if p.get("vendor_id") == vendor_id)
    if ref_count > 0:
        vendors = _get_cached_vendors(tenant_id)
        vendor = next((v for v in vendors if v.get("id") == vendor_id), None)
        if vendor:
            vendor["active"] = "false"
            sh = _get_spreadsheet(sheet_key)
            ws, _ = _ensure_worksheet(sh, SHEET_VENDORS, VENDORS_HEADER, sheet_key)
            _upsert_rows(ws, VENDORS_HEADER, [vendor])
            _cache_invalidate(sheet_key)
            return {"action": "deactivated", "ref_count": ref_count}
        return {"action": "not_found", "ref_count": 0}
    sh = _get_spreadsheet(sheet_key)
    ws, _ = _ensure_worksheet(sh, SHEET_VENDORS, VENDORS_HEADER, sheet_key)
    _delete_rows(ws, [vendor_id])
    _cache_invalidate(sheet_key)
    return {"action": "deleted", "ref_count": 0}


# ── Direction CRUD ─────────────────────────────────────────────────────────────

def get_directions(tenant_id: str) -> List[Dict]:
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    return _read_all(sh.worksheet(SHEET_DIRECTIONS))


def save_direction(tenant_id: str, direction: Dict) -> Dict:
    if not direction.get("id"):
        direction["id"] = "dir-" + str(uuid.uuid4())[:8]
    now = _now_str()
    direction.setdefault("created_at", now)
    direction["updated_at"] = now
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    ws, _ = _ensure_worksheet(sh, SHEET_DIRECTIONS, DIRECTIONS_HEADER, sheet_key)
    _upsert_rows(ws, DIRECTIONS_HEADER, [direction])
    _cache_invalidate(sheet_key)
    return direction


def delete_direction(tenant_id: str, direction_id: str) -> bool:
    sheet_key = get_work_sheet_key(tenant_id)
    # 대분류 이름 조회 (대분류 탭만 read)
    sh = _get_spreadsheet(sheet_key)
    ws_dir, _ = _ensure_worksheet(sh, SHEET_DIRECTIONS, DIRECTIONS_HEADER, sheet_key)
    directions = _read_all(ws_dir)
    direction = next((d for d in directions if d.get("id") == direction_id), None)
    if direction:
        direction_name = direction.get("name", "")
        # 캐시 우선 사용 — 캐시 없으면 가격조건 탭만 read
        prices = _get_cached_prices(tenant_id)
        ref_count = sum(1 for p in prices if p.get("direction") == direction_name)
        if ref_count > 0:
            raise ReferenceConflictError(
                f"이 대분류를 사용하는 가격조건이 {ref_count}건 있어 삭제할 수 없습니다. "
                "먼저 가격조건을 수정하거나 비활성 처리하세요."
            )
    _delete_rows(ws_dir, [direction_id])
    _cache_invalidate(sheet_key)
    return True


# ── Group CRUD ─────────────────────────────────────────────────────────────────

def get_groups(tenant_id: str) -> List[Dict]:
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    return _read_all(sh.worksheet(SHEET_GROUPS))


def save_group(tenant_id: str, group: Dict) -> Dict:
    if not group.get("id"):
        group["id"] = "grp-" + str(uuid.uuid4())[:8]
    now = _now_str()
    group.setdefault("created_at", now)
    group["updated_at"] = now
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    ws, _ = _ensure_worksheet(sh, SHEET_GROUPS, GROUPS_HEADER, sheet_key)
    _upsert_rows(ws, GROUPS_HEADER, [group])
    _cache_invalidate(sheet_key)
    return group


def delete_group(tenant_id: str, group_id: str) -> bool:
    # 캐시 우선 사용 — 캐시 없으면 가격조건 탭만 read
    prices = _get_cached_prices(tenant_id)
    ref_count = sum(1 for p in prices if p.get("group_id") == group_id)
    if ref_count > 0:
        raise ReferenceConflictError(
            f"이 중분류를 사용하는 가격조건이 {ref_count}건 있어 삭제할 수 없습니다. "
            "먼저 해당 가격조건을 수정하거나 삭제하세요."
        )
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    ws, _ = _ensure_worksheet(sh, SHEET_GROUPS, GROUPS_HEADER, sheet_key)
    _delete_rows(ws, [group_id])
    _cache_invalidate(sheet_key)
    return True


# ── Region CRUD ────────────────────────────────────────────────────────────────

def get_regions(tenant_id: str) -> List[Dict]:
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    return _read_all(sh.worksheet(SHEET_REGIONS))


def save_region(tenant_id: str, region: Dict) -> Dict:
    if not region.get("id"):
        region["id"] = "rgn-" + str(uuid.uuid4())[:8]
    now = _now_str()
    region.setdefault("created_at", now)
    region["updated_at"] = now
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    ws, _ = _ensure_worksheet(sh, SHEET_REGIONS, REGIONS_HEADER, sheet_key)
    _upsert_rows(ws, REGIONS_HEADER, [region])
    _cache_invalidate(sheet_key)
    return region


def delete_region(tenant_id: str, region_id: str) -> bool:
    sheet_key = get_work_sheet_key(tenant_id)
    # 소분류 이름 조회 (소분류 탭만 read)
    sh = _get_spreadsheet(sheet_key)
    ws_rgn, _ = _ensure_worksheet(sh, SHEET_REGIONS, REGIONS_HEADER, sheet_key)
    regions = _read_all(ws_rgn)
    region = next((r for r in regions if r.get("id") == region_id), None)
    if region:
        region_name = region.get("name", "")
        # 캐시 우선 사용
        prices = _get_cached_prices(tenant_id)
        ref_count = sum(1 for p in prices if p.get("region") == region_name)
        if ref_count > 0:
            raise ReferenceConflictError(
                f"이 소분류/지역을 사용하는 가격조건이 {ref_count}건 있어 삭제할 수 없습니다. "
                "먼저 해당 가격조건을 수정하거나 삭제하세요."
            )
    _delete_rows(ws_rgn, [region_id])
    _cache_invalidate(sheet_key)
    return True


# ── Price CRUD ─────────────────────────────────────────────────────────────────

def get_prices(tenant_id: str) -> List[Dict]:
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    return _read_all(sh.worksheet(SHEET_PRICES))


def save_price(tenant_id: str, price: Dict) -> Dict:
    if not price.get("id"):
        price["id"] = "price-" + str(uuid.uuid4())[:8]
    now = _now_str()
    price.setdefault("created_at", now)
    price["updated_at"] = now
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    ws, _ = _ensure_worksheet(sh, SHEET_PRICES, PRICES_HEADER, sheet_key)
    _upsert_rows(ws, PRICES_HEADER, [price])
    _cache_invalidate(sheet_key)
    return price


def delete_price(tenant_id: str, price_id: str) -> bool:
    sheet_key = get_work_sheet_key(tenant_id)
    sh = _get_spreadsheet(sheet_key)
    ws, _ = _ensure_worksheet(sh, SHEET_PRICES, PRICES_HEADER, sheet_key)
    _delete_rows(ws, [price_id])
    _cache_invalidate(sheet_key)
    return True
