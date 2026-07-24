"""고객 일괄추출(Excel) — tenant 고객 전체를 **일괄등록 양식과 동일한 단일 정본**으로 내보낸다.

설계 원칙:
  - 추출 workbook 은 customer_bulk_service 의 단일 빌더(build_customer_bulk_workbook_bytes)를
    재사용한다 — 추출 '고객' 시트 = 등록 양식(15열, 1행 안내·2행 헤더·3행 예시·4행~ 데이터).
    별도의 export 헤더 스키마를 유지하지 않는다(헤더 중복 선언 없음).
  - 하이코리아/소시넷 등 외부 사이트 계정(ID/PW)은 절대 포함하지 않는다.
  - 체류자격은 canonical resolver(V 우선)로 통일한다(고객카드/검색/quick-doc 과 동일 값).
  - 읽기 전용 — 이 모듈은 아무것도 저장/변경하지 않는다.
"""
from __future__ import annotations

from typing import Iterable

EXCEL_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_export_bytes_from_records(records: Iterable[dict]) -> tuple[bytes, int]:
    """이미 tenant-scoped 된 레코드로 고객 일괄추출 workbook(bytes, count)을 만든다.
    등록 양식과 동일한 '고객' 시트 + 읽기 전용 '추출 부가정보' 시트(고객ID/성명/위임내역/폴더)."""
    from backend.services.customer_bulk_service import build_export_workbook_bytes
    return build_export_workbook_bytes(list(records))


def build_tenant_export_bytes(tenant_id: str) -> tuple[bytes, int]:
    """현재 tenant의 비삭제 고객 전체(고객ID 내림차순, 기존 고객목록과 동일)를 추출.
    reveal=True 로 번호(reg_back)를 복호화해 넣는다(기존 정책 유지 — 감사 로그·PII 추출)."""
    from backend.services.customer_pg_service import list_customers

    records = list_customers(tenant_id, reveal=True)
    return build_export_bytes_from_records(records)
