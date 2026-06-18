"""각종공인증 — PostgreSQL 전환 완료(Phase G).

운영 경로는 ``backend/services/certification_pg_service.py``(PostgreSQL)이며, 라우터
(``backend/routers/certification.py`` 의 ``_svc()``)는 PG 서비스만 호출한다.

과거 이 모듈에 있던 외부 저장소 기반 함수(저장·조회·시드·스키마 마이그레이션,
스프레드시트/워크시트 헬퍼 등)는 모두 **dead code** 였고
``bootstrap`` / ``get_*`` / ``save_*`` / ``delete_*`` 등)는 모두 **dead code** 였고
런타임 미사용이라 제거했다. 더 이상 외부 저장소를
import 하지 않는다.

다른 모듈이 재사용하는 예외 클래스 ``ReferenceConflictError`` 만 유지한다
(``routers/certification.py``, ``services/certification_pg_service.py`` 가 import).
"""


class ReferenceConflictError(Exception):
    """Raised when a delete is blocked because price rows still reference the item."""
    pass
