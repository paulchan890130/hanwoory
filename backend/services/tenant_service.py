"""
backend/services/tenant_service.py

테넌트별 sheet_key 라우팅 + (레거시) 읽기 캐시 무효화 helper.

Google 제거(2026-06):
  이 모듈의 외부 스프레드시트 접근 레이어 — 클라이언트 / 워크시트 /
  읽기/쓰기/삭제 래퍼 및 관련 import — 는 **전부 제거**되었다.

  운영 도메인은 PostgreSQL 전용이며 런타임 외부 접근 경로는 더 이상 존재하지 않는다.


남은 책임:
  - PG(tenants)에서 tenant_id → customer/work sheet_key 라우팅 정보 제공
    (아직 '데이터 워크북 위치'가 필요한 일부 경로용; 전환 완료 후 제거 예정).
  - read 캐시 무효화 helper(``invalidate_read_cache`` 등) — 외부(scan 등) import 호환용 no-op.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import threading
import time

# ── 설정 상수 (PG 기반 tenant→sheet_key 라우팅에 필요한 것만) ──────────────────
from config import SHEET_KEY, DEFAULT_TENANT_ID, WORK_REFERENCE_TEMPLATE_ID


# ── 테넌트 시트 키 매핑 캐시 ───────────────────────────────────────────────────
_TENANT_MAP_CACHE: dict = {}
_TENANT_MAP_TIME: float = 0
_TENANT_MAP_TTL = 600  # 10분


def _load_tenant_map() -> dict:
    """
    tenant_id → {customer, work} (sheet_key) 매핑 로드 — **PG tenants 전용(PG-only)**.
    계정 탭은 더 이상 읽지 않는다(Phase B). 여기서 반환하는 sheet_key 는
    아직 PG 전환 안 된 도메인(Phase C~H)의 '데이터 워크북 위치' 라우팅에만 사용된다 —
    전환 완료 후 라우팅 자체를 제거한다. TTL 캐싱 유지.
    """
    global _TENANT_MAP_CACHE, _TENANT_MAP_TIME
    now = time.time()
    if _TENANT_MAP_CACHE and (now - _TENANT_MAP_TIME) < _TENANT_MAP_TTL:
        return _TENANT_MAP_CACHE

    try:
        from sqlalchemy import select
        from backend.db.models.tenant import Tenant
        from backend.db.session import get_sessionmaker
        SessionLocal = get_sessionmaker()
        with SessionLocal() as session:
            rows = session.scalars(select(Tenant)).all()
    except Exception as e:
        print(f"[tenant_service] PG tenants 로드 실패: {e}")
        return _TENANT_MAP_CACHE  # 이전 캐시라도 반환(가용성)

    mapping: dict = {}
    for t in rows:
        tid = (t.tenant_id or "").strip()
        if not tid:
            continue
        if t.is_active is False:  # 비활성 테넌트 제외 (None/True 허용)
            continue
        mapping[tid] = {
            "customer": (t.customer_sheet_key or "").strip(),
            "work": (t.work_sheet_key or "").strip(),
        }

    _TENANT_MAP_CACHE = mapping
    _TENANT_MAP_TIME = time.time()
    return mapping


def get_customer_sheet_key(tenant_id: str) -> str:
    """
    tenant_id에 해당하는 고객 데이터 스프레드시트 ID 반환.

    - DEFAULT_TENANT_ID(한우리): 자기 키 없으면 SHEET_KEY로 폴백 (호환성 유지)
    - 다른 테넌트: 자기 키 없으면 ValueError 발생 (admin 데이터로 폴백 금지)
    """
    import logging
    mapping = _load_tenant_map()
    rec = mapping.get(tenant_id)
    if rec and rec.get("customer"):
        return rec["customer"]

    if tenant_id == DEFAULT_TENANT_ID:
        # 기본 테넌트는 마스터 시트로 폴백 허용
        return SHEET_KEY

    # 다른 테넌트는 워크스페이스가 아직 미생성 → 명시적 에러
    logging.getLogger("tenant_service").error(
        "[tenant_service] %s의 customer_sheet_key 없음 — 워크스페이스 미생성 또는 is_active=FALSE", tenant_id,
    )
    raise ValueError(
        f"tenant_id='{tenant_id}' 의 customer_sheet_key가 설정되지 않았습니다. "
        "관리자 페이지에서 워크스페이스를 먼저 생성하세요."
    )


def get_work_sheet_key(tenant_id: str) -> str:
    """
    tenant_id에 해당하는 업무정리 스프레드시트 ID 반환.

    - DEFAULT_TENANT_ID(한우리): 자기 키 없으면 WORK_REFERENCE_TEMPLATE_ID로 폴백
    - 다른 테넌트: 자기 키 없으면 ValueError 발생 (admin 데이터로 폴백 금지)
    """
    import logging
    mapping = _load_tenant_map()
    rec = mapping.get(tenant_id)
    if rec and rec.get("work"):
        return rec["work"]

    if tenant_id == DEFAULT_TENANT_ID:
        return WORK_REFERENCE_TEMPLATE_ID

    logging.getLogger("tenant_service").error(
        "[tenant_service] %s의 work_sheet_key 없음 — 워크스페이스 미생성 또는 is_active=FALSE", tenant_id,
    )
    raise ValueError(
        f"tenant_id='{tenant_id}' 의 work_sheet_key가 설정되지 않았습니다. "
        "관리자 페이지에서 워크스페이스를 먼저 생성하세요."
    )


# ── 읽기 캐시 무효화 helper (외부 import 호환 위해 유지) ──
# 과거 읽기 캐시를 무효화하던 helper. 해당 읽기 경로는 제거됐으나
# scan 라우터 등이 invalidate_read_cache 를 import 하므로, 데이터 무손실 no-op 으로 유지한다.
_READ_CACHE: dict = {}            # (tenant_id, sheet_name) → (timestamp, records) — 더 이상 채워지지 않음
_READ_CACHE_LOCK = threading.Lock()
_INVALIDATION_TOKENS: dict = {}   # (tenant_id, sheet_name) → float


def _invalidate_read_cache(sheet_name: str, tenant_id: str) -> None:
    key = (tenant_id, sheet_name)
    with _READ_CACHE_LOCK:
        _READ_CACHE.pop(key, None)
        _INVALIDATION_TOKENS[key] = time.time()


def invalidate_read_cache(tenant_id: str, sheet_name: str) -> None:
    """Public helper: evict one (tenant, sheet) entry from the read cache.
    Safe to call even if the key is absent. Logs only names, never data.
    """
    _invalidate_read_cache(sheet_name, tenant_id)
    print(f"[sheets] cache invalidated: sheet={sheet_name!r} tenant={tenant_id!r}")


def get_invalidation_token(tenant_id: str, sheet_name: str) -> float:
    """Return current invalidation token for (tenant, sheet)."""
    key = (tenant_id, sheet_name)
    with _READ_CACHE_LOCK:
        return _INVALIDATION_TOKENS.get(key, 0)
