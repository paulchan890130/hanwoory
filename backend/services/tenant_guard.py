"""테넌트 접근 가드 — 고객 리소스가 호출자 tenant 소유인지 단언.

현재 customer_pg_service 의 find/list/delete 는 모두 tenant_id 스코프라 교차 테넌트
접근이 구조적으로 차단되어 있다. 이 헬퍼는 **신규 엔드포인트/방어심화**용으로,
customer_id 가 해당 tenant 에 없으면 404(존재 비노출)로 통일한다.
"""
from __future__ import annotations

from fastapi import HTTPException


def assert_customer_in_tenant(tenant_id: str, customer_id: str) -> None:
    from backend.services.customer_pg_service import find_customer
    if find_customer(tenant_id, str(customer_id or "").strip()) is None:
        # 타 테넌트 리소스도 동일하게 404 — 존재 여부를 드러내지 않는다.
        raise HTTPException(status_code=404, detail="해당 고객을 찾을 수 없습니다.")
