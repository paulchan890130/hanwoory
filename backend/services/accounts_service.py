"""
accounts_service.py — 계정(Accounts) 공용 helper
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase B 전환: 계정 조회/생성/사무소명은 **PostgreSQL(users + tenants) 전용**이다.
런타임에서 Google Sheets Accounts 탭을 읽거나 쓰지 않는다. PG 미구성 시 조용한 Sheets
fallback 없이 ``get_sessionmaker()`` 가 명확한 RuntimeError 를 낸다.

Sheets 접근 helper(``_get_ws`` / ``_get_ws_readonly`` / ``ensure_header``)는 **일회성 이관
스크립트 전용**으로만 남겨두며, ``sheets_guard.assert_sheets_runtime_allowed()`` 로 보호된다
(``ALLOW_SHEETS_MIGRATION=1`` 없이는 호출 시 즉시 실패). 운영/일반 런타임에서는 호출 금지.

설계 원칙
─────────
1. 스키마 고정  : ACCOUNTS_SCHEMA — 이관/관리 UI 호환용 키 순서(읽기 dict 키도 이 이름 사용).
2. 해시 통일    : hash_password / verify_password 를 여기서 정의. auth.py 는 이것만 사용.
3. 저장소       : 계정/테넌트 = PostgreSQL(users / tenants). agent_rrn 원본은 PG 미보관.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import hashlib
import base64
import hmac
import datetime

# ── Accounts 표준 스키마 (이관/관리 호환용 키 순서) ───────────────────────────
ACCOUNTS_SCHEMA: list[str] = [
    "login_id", "password_hash", "tenant_id", "office_name", "office_adr",
    "contact_name", "contact_tel", "biz_reg_no", "agent_rrn", "is_admin",
    "is_active", "folder_id", "work_sheet_key", "customer_sheet_key",
    "created_at", "sheet_key",
]


# ── 비밀번호 해시/검증 ────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """pbkdf2_hmac(sha256, 100_000) + base64(salt[16]+dk)."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return base64.b64encode(salt + dk).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    """저장된 해시와 평문 대조. PBKDF2 base64(표준) + bcrypt(전방호환) 지원. 손상 해시는 False."""
    h = (hashed or "").strip()
    if not h:
        return False
    if h.startswith("$2"):
        try:
            import bcrypt
            return bcrypt.checkpw(password.encode("utf-8"), h.encode("utf-8"))
        except Exception:
            return False
    try:
        raw = base64.b64decode(h.encode("ascii"))
        if len(raw) < 17:
            return False
        salt, dk = raw[:16], raw[16:]
        new_dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return hmac.compare_digest(dk, new_dk)
    except Exception:
        return False


# ── PG → Accounts-shaped dict ─────────────────────────────────────────────────

def _bool_str(v) -> str:
    return "TRUE" if bool(v) else "FALSE"


def _row_from_pg(u, t) -> dict:
    """AccountUser(u) + Tenant(t, 없을 수 있음) → 과거 Accounts 시트와 같은 키의 dict.
    agent_rrn 원본은 PG 미보관 → 빈 문자열(PDF 는 수동입력)."""
    return {
        "login_id":           u.login_id,
        "password_hash":      u.password_hash,
        "tenant_id":          u.tenant_id,
        "office_name":        (t.office_name if t else "") or "",
        "office_adr":         (t.office_adr if t else "") or "",
        "contact_name":       u.contact_name or "",
        "contact_tel":        u.contact_tel or "",
        "biz_reg_no":         (t.biz_reg_no if t else "") or "",
        "agent_rrn":          "",
        "is_admin":           _bool_str(u.is_admin),
        "is_active":          _bool_str(u.is_active),
        "folder_id":          (t.folder_id if t else "") or "",
        "work_sheet_key":     (t.work_sheet_key if t else "") or "",
        "customer_sheet_key": (t.customer_sheet_key if t else "") or "",
        "created_at":         u.created_at.isoformat() if getattr(u, "created_at", None) else "",
        "sheet_key":          "",
    }


def find_account(login_id: str) -> dict | None:
    """login_id 로 계정 조회 (PG users + tenants). 없으면 None. Google Sheets 미사용."""
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id.strip()))
        if u is None:
            return None
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == u.tenant_id))
        return _row_from_pg(u, t)


def get_office_name(tenant_id: str) -> str:
    """tenant_id 의 사무소명 (PG tenants). 없으면 빈 문자열. Google Sheets 미사용."""
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id.strip()))
        return (t.office_name if t else "") or ""


def build_account_dict(
    *, login_id: str, password_hash: str, office_name: str,
    office_adr: str = "", contact_name: str = "", contact_tel: str = "",
    biz_reg_no: str = "", agent_rrn: str = "", is_admin: bool = False,
    is_active: bool = True, folder_id: str = "", work_sheet_key: str = "",
    customer_sheet_key: str = "", sheet_key: str = "", tenant_id: str = "",
    created_at: str = "",
) -> dict:
    """계정 dict 생성(키는 ACCOUNTS_SCHEMA 호환). tenant_id 미제공 시 login_id."""
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
        "is_admin":           _bool_str(is_admin),
        "is_active":          _bool_str(is_active),
        "folder_id":          folder_id,
        "work_sheet_key":     work_sheet_key,
        "customer_sheet_key": customer_sheet_key,
        "created_at":         created_at or datetime.date.today().isoformat(),
        "sheet_key":          sheet_key,
    }


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("true", "1", "y", "활성", "active")


def append_account(account_dict: dict) -> None:
    """계정 1건을 PG(users + tenants)에 upsert. Google Sheets 미사용.
    tenants: office_name/adr/biz_reg_no/folder_id/sheet_keys/is_active.
    users:   login_id/tenant_id/password_hash/contact_name/contact_tel/is_admin/is_active.
    agent_rrn 원본은 저장하지 않는다(PDF 는 수동입력)."""
    from sqlalchemy import select
    from backend.db.models.tenant import Tenant
    from backend.db.models.user import AccountUser
    from backend.db.session import get_sessionmaker

    a = account_dict
    login_id = str(a.get("login_id", "")).strip()
    tenant_id = str(a.get("tenant_id", "")).strip() or login_id
    is_active = _truthy(a.get("is_active", ""))
    is_admin = _truthy(a.get("is_admin", ""))

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        t = session.scalar(select(Tenant).where(Tenant.tenant_id == tenant_id))
        if t is None:
            t = Tenant(tenant_id=tenant_id, office_name=a.get("office_name", "") or login_id)
            session.add(t)
        else:
            if a.get("office_name"):
                t.office_name = a["office_name"]
        t.office_adr = a.get("office_adr", "") or t.office_adr
        t.biz_reg_no = a.get("biz_reg_no", "") or t.biz_reg_no
        if a.get("folder_id"):
            t.folder_id = a["folder_id"]
        if a.get("customer_sheet_key"):
            t.customer_sheet_key = a["customer_sheet_key"]
        if a.get("work_sheet_key"):
            t.work_sheet_key = a["work_sheet_key"]
        t.is_active = is_active

        u = session.scalar(select(AccountUser).where(AccountUser.login_id == login_id))
        if u is None:
            session.add(AccountUser(
                login_id=login_id, tenant_id=tenant_id,
                password_hash=a.get("password_hash", ""),
                contact_name=(a.get("contact_name", "") or None),
                contact_tel=(a.get("contact_tel", "") or None),
                is_admin=is_admin, is_active=is_active,
            ))
        else:
            u.tenant_id = tenant_id
            if a.get("password_hash"):
                u.password_hash = a["password_hash"]
            u.contact_name = a.get("contact_name", "") or u.contact_name
            u.contact_tel = a.get("contact_tel", "") or u.contact_tel
            u.is_admin = is_admin
            u.is_active = is_active
        session.commit()


# ── 이관 스크립트 전용 Sheets helper (런타임 차단) ───────────────────────────────
# ALLOW_SHEETS_MIGRATION=1 (또는 ALLOW_GOOGLE_SHEETS_RUNTIME=1) 없이 호출되면 즉시 실패한다.
# migrate_accounts_to_pg.py 등 일회성 이관 도구에서만 사용.

def dict_to_row(account_dict: dict) -> list:
    """ACCOUNTS_SCHEMA 순서 list (이관/내보내기용 — 순수 변환, Sheets 미접근)."""
    return [str(account_dict.get(col, "")) for col in ACCOUNTS_SCHEMA]


def _get_ws():
    from backend.services.sheets_guard import assert_sheets_runtime_allowed
    assert_sheets_runtime_allowed("accounts_service._get_ws")
    from config import SHEET_KEY, ACCOUNTS_SHEET_NAME
    from backend.services.tenant_service import _get_gspread_client
    gc = _get_gspread_client()
    sh = gc.open_by_key(SHEET_KEY)
    try:
        return sh.worksheet(ACCOUNTS_SHEET_NAME)
    except Exception:
        return sh.add_worksheet(title=ACCOUNTS_SHEET_NAME, rows=500, cols=len(ACCOUNTS_SCHEMA) + 2)


def _get_ws_readonly():
    from backend.services.sheets_guard import assert_sheets_runtime_allowed
    assert_sheets_runtime_allowed("accounts_service._get_ws_readonly")
    from config import SHEET_KEY, ACCOUNTS_SHEET_NAME
    from backend.services.tenant_service import _get_gspread_client
    gc = _get_gspread_client()
    sh = gc.open_by_key(SHEET_KEY)
    return sh.worksheet(ACCOUNTS_SHEET_NAME)


def ensure_header(ws=None) -> None:
    from backend.services.sheets_guard import assert_sheets_runtime_allowed
    assert_sheets_runtime_allowed("accounts_service.ensure_header")
    if ws is None:
        ws = _get_ws()
    try:
        first_row = ws.row_values(1)
    except Exception:
        first_row = []
    if first_row != ACCOUNTS_SCHEMA:
        ws.update("A1", [ACCOUNTS_SCHEMA], value_input_option="RAW")
