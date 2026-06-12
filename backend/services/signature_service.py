"""서명 데이터 저장/조회 서비스 — PostgreSQL 전용 (PG-only).

Phase A 전환: 행정사서명 / 고객서명 / 임시서명(1·2·3) 모두 **PostgreSQL 만** 사용한다.
Google Sheets 서명 탭(행정사서명·고객서명·서명임시저장)은 런타임에서 읽거나 쓰지 않으며,
이 모듈에는 더 이상 gspread/worksheet 호출이 존재하지 않는다. PG 미구성(DATABASE_URL 없음)
시 조용한 Sheets fallback 없이 ``get_sessionmaker()`` 가 명확한 RuntimeError 를 낸다.

공개 함수 시그니처/반환 구조는 기존과 100% 동일하게 유지한다(라우터·quick_doc 무변경 호환):
- 고객 서명 함수의 첫 인자는 과거 ``customer_sheet_key`` 였으나, 이제는 **tenant_id 또는 csk**
  어느 쪽이 와도 ``_resolve_tenant()`` 가 PG ``tenants`` 로 정규화한다(Sheets 미사용).
  호출측은 tenant_id 를 직접 넘기는 것을 권장(=Sheets 의 csk 조회 자체를 제거).
"""
import base64
import datetime

# pending 임시서명은 2시간 후 만료(빈 칸 취급). 적용 완료분은 '고객서명' 으로 이동·슬롯 삭제되므로
# 만료 대상은 항상 미적용 pending 임시서명뿐이다. (서명패드/sign/pad 슬롯 포함)
_TEMP_EXPIRY_SECONDS = 2 * 60 * 60


class SignatureLookupError(Exception):
    """서명 조회 자체가 실패한 경우 — '서명 없음'(정상)과 구별되는 오류."""


# ── tenant 정규화 (PG only) ────────────────────────────────────────────────────

def _csk_to_tenant_id(customer_sheet_key: str) -> "str | None":
    """customer_sheet_key → tenant_id (PG ``tenants`` 테이블). 매핑 없으면 None.
    Google Sheets 를 읽지 않는다."""
    try:
        from sqlalchemy import select
        from backend.db.models.tenant import Tenant
        from backend.db.session import get_sessionmaker
        SessionLocal = get_sessionmaker()
        with SessionLocal() as session:
            row = session.scalar(
                select(Tenant).where(Tenant.customer_sheet_key == customer_sheet_key)
            )
            return row.tenant_id if row else None
    except Exception as e:
        print(f"[signature_service._csk_to_tenant_id] {e}")
        return None


def _resolve_tenant(tenant_or_csk: str) -> str:
    """첫 인자를 tenant_id 로 정규화. tenant_id 가 직접 오면 그대로(매핑 미존재),
    과거식 csk 가 오면 PG 매핑으로 tenant_id 변환. 둘 다 Sheets 미사용."""
    return _csk_to_tenant_id(tenant_or_csk) or tenant_or_csk


# ── 행정사 서명 ───────────────────────────────────────────────────────────────

def get_agent_signature(tenant_id: str) -> "str | None":
    """행정사 서명 조회. 서명 없음(정상) → None. 조회 오류 → 예외 전파(None 금지)."""
    from backend.services.signature_pg_service import get_agent_signature as _pg
    return _pg(tenant_id)


def save_agent_signature(tenant_id: str, b64: str) -> None:
    from backend.services.signature_pg_service import save_agent_signature as _pg
    _pg(tenant_id, b64)


# ── 고객 서명 ─────────────────────────────────────────────────────────────────

def get_customer_signature(customer_sheet_key: str, customer_id: str) -> "str | None":
    from backend.services.signature_pg_service import get_customer_signature as _pg
    return _pg(_resolve_tenant(customer_sheet_key), customer_id)


def save_customer_signature(customer_sheet_key: str, customer_id: str, b64: str) -> None:
    from backend.services.signature_pg_service import save_customer_signature as _pg
    _pg(_resolve_tenant(customer_sheet_key), customer_id, b64)


def has_customer_signature(customer_sheet_key: str, customer_id: str) -> bool:
    """존재 여부. 조회 실패 시 SignatureLookupError(서명 없음과 구별)."""
    try:
        from backend.services.signature_pg_service import has_customer_signature as _pg
        return _pg(_resolve_tenant(customer_sheet_key), customer_id)
    except Exception as e:
        raise SignatureLookupError(f"고객서명 조회 실패: {e}") from e


def delete_customer_signature(customer_sheet_key: str, customer_id: str) -> bool:
    """적용된 고객서명만 삭제. 임시서명/고객정보 비접촉. 삭제 행 있으면 True."""
    from backend.services.signature_pg_service import delete_customer_signature as _pg
    return _pg(_resolve_tenant(customer_sheet_key), customer_id)


# ── 임시저장 슬롯 (1·2·3) ──────────────────────────────────────────────────────

def _temp_is_expired(saved_at: str) -> bool:
    """saved_at(ISO 문자열, PG)가 2시간 초과면 True. 빈값/파싱불가는 만료 아님(보수적)."""
    s = (saved_at or "").strip()
    if not s:
        return False
    try:
        dt = datetime.datetime.fromisoformat(s)
    except Exception:
        return False
    if dt.tzinfo is not None:
        now = datetime.datetime.now(datetime.timezone.utc)
    else:
        now = datetime.datetime.now()
    return (now - dt).total_seconds() > _TEMP_EXPIRY_SECONDS


def _pg_slots(tenant_id: str) -> dict:
    """{slot: {signature_data, note, saved_at}} (PG)."""
    from backend.services.signature_pg_service import get_temp_slots as _pg
    return {s["slot"]: s for s in _pg(tenant_id)}


def get_temp_slots(tenant_id: str) -> list:
    """슬롯 1~3 상태 반환: {slot, has_data, 비고, saved_at}. 만료(2h) pending 은 빈 칸 취급.
    서명데이터(base64)는 포함하지 않는다."""
    slots = _pg_slots(tenant_id)
    result = []
    for s in (1, 2, 3):
        rec = slots.get(s)
        if rec and (rec.get("signature_data") or "").strip() and not _temp_is_expired(rec.get("saved_at", "")):
            result.append({
                "slot": s,
                "has_data": True,
                "비고": rec.get("note", "") or "",
                "saved_at": rec.get("saved_at", "") or "",
            })
        else:
            result.append({"slot": s, "has_data": False, "비고": "", "saved_at": ""})
    return result


def save_temp_slot(tenant_id: str, slot: int, b64: str, memo: str) -> None:
    from backend.services.signature_pg_service import save_temp_slot as _pg
    _pg(tenant_id, slot, b64, memo)


def save_temp_slot_first_empty(tenant_id: str, b64: str, memo: str = "") -> "int | None":
    """비어 있는(만료 포함) 가장 앞 슬롯(1→2→3)에 저장. 저장된 slot 반환.
    1·2·3 모두 차 있으면 None(저장 안 함, 덮어쓰기 금지). 서명패드(/sign/pad) 전용."""
    slots = get_temp_slots(tenant_id)  # 만료 반영된 has_data
    target = next((s["slot"] for s in slots if not s["has_data"]), None)
    if target is None:
        return None
    save_temp_slot(tenant_id, target, b64, memo)
    return target


def get_temp_slot_data(tenant_id: str, slot: int) -> "str | None":
    """슬롯의 서명데이터. 만료된 pending 은 None(적용 차단)."""
    rec = _pg_slots(tenant_id).get(slot)
    if not rec:
        return None
    data = (rec.get("signature_data") or "").strip()
    if not data:
        return None
    if _temp_is_expired(rec.get("saved_at", "")):
        return None
    return data


def clear_temp_slot(tenant_id: str, slot: int) -> None:
    from backend.services.signature_pg_service import delete_temp_slot as _pg
    _pg(tenant_id, slot)


# ── 압축 ─────────────────────────────────────────────────────────────────────

def compress_signature(b64: str) -> str:
    """
    base64 서명 이미지 → 흰색/밝은 픽셀 투명 처리 + 400×150 이내 리사이즈 → 압축 base64 반환.
    50,000자 초과 시 ValueError.
    """
    from PIL import Image
    import io

    raw = b64
    if raw.startswith("data:"):
        raw = raw.split(",", 1)[1]

    img_bytes = base64.b64decode(raw)
    img = Image.open(io.BytesIO(img_bytes))
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    # 흰색/밝은 픽셀 → 투명 처리
    data = img.getdata()
    new_data = []
    for pixel in data:
        r, g, b, a = pixel
        if r > 200 and g > 200 and b > 200:
            new_data.append((255, 255, 255, 0))
        else:
            new_data.append(pixel)
    img.putdata(new_data)

    # 400×150 이내 비율 유지 리사이즈
    img.thumbnail((400, 150), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    compressed = base64.b64encode(buf.getvalue()).decode("ascii")
    result = f"data:image/png;base64,{compressed}"

    if len(result) > 50_000:
        raise ValueError(f"압축 후에도 서명 데이터가 너무 큽니다: {len(result)}자")

    return result
