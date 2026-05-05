"""
accounts_service.py — Accounts 시트 공용 helper
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
bootstrap / signup / admin create_account 이 모두 이 모듈에서만
Accounts 시트를 읽고 씁니다.

설계 원칙
─────────
1. 스키마 고정  : ACCOUNTS_SCHEMA 한 곳에만 정의.
                  bootstrap·signup·create_account 모두 이 순서를 공유.
2. 헤더 1행 보장: append_account() / ensure_header() 가 항상 확인·수정.
3. 위치 독립    : 컬럼 번호(position) 기반 읽기/쓰기 금지 — 헤더명 기준.
4. 서비스 계정  : gspread 클라이언트는 반드시 tenant_service._get_gspread_client()
                  (OAuth가 아닌 서비스 계정 JSON 사용).
5. 해시 통일    : hash_password / verify_password 를 여기서 정의.
                  auth.py 는 이 함수를 import 해서만 사용.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import hashlib
import base64
import hmac
import datetime

# ── Accounts 표준 스키마 (16컬럼, 순서 고정) ──────────────────────────────────
ACCOUNTS_SCHEMA: list[str] = [
    "login_id",          # 로그인 ID (= 기본 tenant_id)
    "password_hash",     # pbkdf2_hmac(sha256)+base64 해시
    "tenant_id",         # 테넌트 구분자 (기본값: login_id)
    "office_name",       # 사무실명
    "office_adr",        # 사무실 주소
    "contact_name",      # 담당자 이름
    "contact_tel",       # 담당자 연락처
    "biz_reg_no",        # 사업자등록번호
    "agent_rrn",         # 행정사 주민등록번호
    "is_admin",          # 관리자 여부 (TRUE/FALSE)
    "is_active",         # 활성 여부 (TRUE/FALSE)
    "folder_id",         # Google Drive 폴더 ID
    "work_sheet_key",    # 업무정리 스프레드시트 ID
    "customer_sheet_key",# 고객 데이터 스프레드시트 ID
    "created_at",        # 생성일 (YYYY-MM-DD)
    "sheet_key",         # 전용 업무정리 스프레드시트 ID (tenant별 신규 생성 시 사용)
]


# ── 비밀번호 해시/검증 ────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """
    pbkdf2_hmac(sha256, 100_000회) + base64 인코딩.
    salt 16바이트를 앞에 붙여서 하나의 문자열로 반환.
    """
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return base64.b64encode(salt + dk).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    """hash_password 결과와 평문 비밀번호를 대조."""
    try:
        raw = base64.b64decode(hashed.encode("ascii"))
        salt, dk = raw[:16], raw[16:]
        new_dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return hmac.compare_digest(dk, new_dk)
    except Exception:
        return False


# ── gspread 내부 helper ───────────────────────────────────────────────────────

def _get_ws():
    """
    서비스 계정으로 Accounts 워크시트를 반환.
    시트가 없으면 자동 생성 (쓰기 경로 전용).
    읽기 경로에서는 _get_ws_readonly() 를 사용할 것.
    """
    from config import SHEET_KEY, ACCOUNTS_SHEET_NAME
    from backend.services.tenant_service import _get_gspread_client
    gc = _get_gspread_client()
    sh = gc.open_by_key(SHEET_KEY)
    try:
        ws = sh.worksheet(ACCOUNTS_SHEET_NAME)
    except Exception:
        ws = sh.add_worksheet(title=ACCOUNTS_SHEET_NAME, rows=500, cols=len(ACCOUNTS_SCHEMA) + 2)
    return ws


def _get_ws_readonly():
    """
    서비스 계정으로 Accounts 워크시트를 읽기 전용으로 반환.
    시트가 존재하지 않으면 add_worksheet 를 호출하지 않고 예외를 그대로 전파.
    find_account 등 읽기 경로에서만 사용. 절대 쓰기/생성 경로에서 사용하지 말 것.
    """
    from config import SHEET_KEY, ACCOUNTS_SHEET_NAME
    from backend.services.tenant_service import _get_gspread_client
    gc = _get_gspread_client()
    sh = gc.open_by_key(SHEET_KEY)
    return sh.worksheet(ACCOUNTS_SHEET_NAME)  # raises WorksheetNotFound if missing — intentional


def ensure_header(ws=None) -> None:
    """
    Accounts 워크시트 1행이 ACCOUNTS_SCHEMA 와 다르면 강제 덮어씀.
    인자 없이 호출하면 내부적으로 _get_ws() 를 사용.
    """
    if ws is None:
        ws = _get_ws()
    try:
        first_row = ws.row_values(1)
    except Exception:
        first_row = []

    if first_row != ACCOUNTS_SCHEMA:
        ws.update("A1", [ACCOUNTS_SCHEMA], value_input_option="RAW")


# ── 공용 read/write ───────────────────────────────────────────────────────────

def dict_to_row(account_dict: dict) -> list:
    """
    ACCOUNTS_SCHEMA 순서대로 dict → list 변환.
    없는 컬럼은 빈 문자열로 채움.
    """
    return [str(account_dict.get(col, "")) for col in ACCOUNTS_SCHEMA]


def find_account(login_id: str) -> dict | None:
    """
    Accounts 시트에서 login_id 로 계정을 찾아 반환.
    get_all_values() 직접 파싱 → 헤더 중복 오류 면역.
    없으면 None 반환.

    주의: _get_ws_readonly() 사용 — 시트가 없어도 add_worksheet 절대 호출 안 함.
    """
    try:
        ws = _get_ws_readonly()
        values = ws.get_all_values()
    except Exception as e:
        print(f"[accounts_service.find_account] Sheets 읽기 실패: {e}")
        return None

    if not values or len(values) < 2:
        return None

    header = values[0]
    for row in values[1:]:
        if not any(c.strip() for c in row):
            continue
        r = dict(zip(header, row))
        if r.get("login_id", "").strip() == login_id.strip():
            return r
    return None


def get_office_name(tenant_id: str) -> str:
    """Accounts 시트에서 tenant_id 행의 office_name 반환. 없으면 빈 문자열."""
    try:
        ws = _get_ws_readonly()
        values = ws.get_all_values()
    except Exception:
        return ""
    if not values or len(values) < 2:
        return ""
    header = values[0]
    for row in values[1:]:
        if not any(c.strip() for c in row):
            continue
        r = dict(zip(header, row))
        if r.get("tenant_id", "").strip() == tenant_id.strip():
            return r.get("office_name", "").strip()
    return ""


def append_account(account_dict: dict) -> None:
    """
    Accounts 시트에 계정 1행을 추가.
    ─ 1행 헤더가 없거나 다르면 먼저 수정
    ─ append_row 는 항상 마지막 빈 행 다음에 추가 (gspread 기본 동작)
    ─ value_input_option="USER_ENTERED" 로 한글 포함 모든 값 안전하게 저장
    """
    ws = _get_ws()
    ensure_header(ws)
    row = dict_to_row(account_dict)
    ws.append_row(row, value_input_option="USER_ENTERED")


def build_account_dict(
    *,
    login_id: str,
    password_hash: str,
    office_name: str,
    office_adr: str = "",
    contact_name: str = "",
    contact_tel: str = "",
    biz_reg_no: str = "",
    agent_rrn: str = "",
    is_admin: bool = False,
    is_active: bool = True,
    folder_id: str = "",
    work_sheet_key: str = "",
    customer_sheet_key: str = "",
    sheet_key: str = "",
    tenant_id: str = "",
    created_at: str = "",
) -> dict:
    """
    16컬럼 계정 dict 를 생성.
    tenant_id 미제공 시 login_id 로 설정.
    created_at 미제공 시 오늘 날짜.
    """
    return {
        "login_id":           login_id.strip(),
        "password_hash":      password_hash,
        "tenant_id":          (tenant_id or login_id).strip(),
        "office_name":        office_name,
        "office_adr":         office_adr,
        "contact_name":       contact_name,
        "contact_tel":        contact_tel,
        "biz_reg_no":         biz_reg_no,
        "agent_rrn":          agent_rrn,
        "is_admin":           "TRUE" if is_admin else "FALSE",
        "is_active":          "TRUE" if is_active else "FALSE",
        "folder_id":          folder_id,
        "work_sheet_key":     work_sheet_key,
        "customer_sheet_key": customer_sheet_key,
        "created_at":         created_at or datetime.date.today().isoformat(),
        "sheet_key":          sheet_key,
    }
