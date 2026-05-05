"""서명 데이터 저장/조회 서비스 — Google Sheets 기반"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import base64
import datetime

AGENT_SIGN_SHEET    = "행정사서명"
CUSTOMER_SIGN_SHEET = "고객서명"

_AGENT_HEADERS    = ["tenant_id", "서명데이터", "등록일시"]
_CUSTOMER_HEADERS = ["고객ID",    "서명데이터", "등록일시"]


def _get_gspread_client():
    from backend.services.tenant_service import _get_gspread_client as _gc
    return _gc()


def _master_sh():
    from config import SHEET_KEY
    gc = _get_gspread_client()
    return gc.open_by_key(SHEET_KEY)


def _get_or_create_ws(sh, title: str, headers: list):
    try:
        ws = sh.worksheet(title)
    except Exception:
        ws = sh.add_worksheet(title=title, rows=500, cols=len(headers) + 1)
    first = ws.row_values(1) if ws.row_count > 0 else []
    if first != headers:
        ws.update("A1", [headers], value_input_option="RAW")
    return ws


def _tenant_customer_sh(customer_sheet_key: str):
    gc = _get_gspread_client()
    return gc.open_by_key(customer_sheet_key)


def _find_row(ws, id_col_idx: int, id_value: str):
    """행 전체 값을 반환. 없으면 None."""
    values = ws.get_all_values()
    if len(values) < 2:
        return None, None
    header = values[0]
    for i, row in enumerate(values[1:], start=2):
        if len(row) > id_col_idx and row[id_col_idx].strip() == id_value.strip():
            return i, dict(zip(header, row))
    return None, None


# ── 행정사 서명 ───────────────────────────────────────────────────────────────

def get_agent_signature(tenant_id: str) -> str | None:
    try:
        sh = _master_sh()
        ws = _get_or_create_ws(sh, AGENT_SIGN_SHEET, _AGENT_HEADERS)
        _, record = _find_row(ws, 0, tenant_id)
        if record is None:
            return None
        data = record.get("서명데이터", "").strip()
        return data if data else None
    except Exception as e:
        print(f"[signature_service.get_agent_signature] 오류: {e}")
        return None


def save_agent_signature(tenant_id: str, b64: str) -> None:
    sh = _master_sh()
    ws = _get_or_create_ws(sh, AGENT_SIGN_SHEET, _AGENT_HEADERS)
    row_idx, _ = _find_row(ws, 0, tenant_id)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_row = [tenant_id, b64, now]
    if row_idx:
        ws.update(f"A{row_idx}", [new_row], value_input_option="RAW")
    else:
        ws.append_row(new_row, value_input_option="RAW")


# ── 고객 서명 ─────────────────────────────────────────────────────────────────

def get_customer_signature(customer_sheet_key: str, customer_id: str) -> str | None:
    try:
        sh = _tenant_customer_sh(customer_sheet_key)
        ws = _get_or_create_ws(sh, CUSTOMER_SIGN_SHEET, _CUSTOMER_HEADERS)
        _, record = _find_row(ws, 0, customer_id)
        if record is None:
            return None
        data = record.get("서명데이터", "").strip()
        return data if data else None
    except Exception as e:
        print(f"[signature_service.get_customer_signature] 오류: {e}")
        return None


def save_customer_signature(customer_sheet_key: str, customer_id: str, b64: str) -> None:
    sh = _tenant_customer_sh(customer_sheet_key)
    ws = _get_or_create_ws(sh, CUSTOMER_SIGN_SHEET, _CUSTOMER_HEADERS)
    row_idx, _ = _find_row(ws, 0, customer_id)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_row = [customer_id, b64, now]
    if row_idx:
        ws.update(f"A{row_idx}", [new_row], value_input_option="RAW")
    else:
        ws.append_row(new_row, value_input_option="RAW")


def has_customer_signature(customer_sheet_key: str, customer_id: str) -> bool:
    try:
        sh = _tenant_customer_sh(customer_sheet_key)
        ws = _get_or_create_ws(sh, CUSTOMER_SIGN_SHEET, _CUSTOMER_HEADERS)
        _, record = _find_row(ws, 0, customer_id)
        if record is None:
            return False
        return bool(record.get("서명데이터", "").strip())
    except Exception:
        return False


# ── 압축 ─────────────────────────────────────────────────────────────────────

def compress_signature(b64: str) -> str:
    """
    base64 서명 이미지 → 400×150 이내 리사이즈 + 흑백 → 압축 base64 반환.
    50,000자 초과 시 ValueError.
    """
    from PIL import Image
    import io

    raw = b64
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[1]

    img_bytes = base64.b64decode(raw)
    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")

    # 흰 배경으로 합성 후 흑백 변환
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    bg.alpha_composite(img)
    gray = bg.convert("L")

    # 400×150 이내 비율 유지 리사이즈
    max_w, max_h = 400, 150
    w, h = gray.size
    if w > max_w or h > max_h:
        ratio = min(max_w / w, max_h / h)
        gray = gray.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    buf = io.BytesIO()
    gray.save(buf, format="PNG", optimize=True)
    compressed = base64.b64encode(buf.getvalue()).decode("ascii")
    result = f"data:image/png;base64,{compressed}"

    if len(result) > 50_000:
        raise ValueError(f"압축 후에도 서명 데이터가 너무 큽니다: {len(result)}자")

    return result
