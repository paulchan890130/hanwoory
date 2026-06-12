"""Central runtime guard against Google Sheets access.

운영 앱 런타임에서 Google Sheets(gspread) 호출은 **전면 금지**된다. 이 모듈은 그 정책을
강제하기 위한 단일 차단 지점이다. Sheets 를 만지는 코드 경로(또는 그 진입 함수)는 첫 줄에서
``assert_sheets_runtime_allowed()`` 를 호출해야 하며, 아래 두 환경변수가 모두 꺼져 있으면
즉시 ``SheetsRuntimeDisabled`` (RuntimeError 하위) 를 던진다 — 조용한 Sheets fallback 금지.

허용 예외(둘 중 하나라도 truthy 여야 통과):
- ``ALLOW_GOOGLE_SHEETS_RUNTIME`` : (개발/임시 디버그) 런타임 Sheets 접근 허용. **운영 기본 false.**
- ``ALLOW_SHEETS_MIGRATION``      : **일회성 이관/백업 스크립트 전용.** 운영 기본 false.

기본값(둘 다 미설정)은 **차단**이다. 라우터/서비스가 실수로 Sheets 를 호출하면 PG 로 조용히
넘어가는 대신 명확한 오류로 즉시 실패한다.

NOTE: 이 모듈 자체는 import 만으로는 아무 동작도 하지 않는다(inert). 각 도메인이 PG-only 로
전환 완료된 뒤, 해당 도메인의 Sheets 진입점에 ``assert_sheets_runtime_allowed`` 를 배선한다.
전환 전 도메인에 미리 배선하면 앱이 죽으므로, 배선은 도메인 전환과 함께 진행한다.
"""
from __future__ import annotations

import os

_TRUTHY = frozenset({"1", "true", "yes", "y", "on"})

_DISABLED_MSG = "Google Sheets runtime access is disabled. Use PostgreSQL service."


class SheetsRuntimeDisabled(RuntimeError):
    """런타임 Google Sheets 접근이 금지된 상태에서 호출됐을 때 발생."""


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in _TRUTHY


def sheets_runtime_allowed() -> bool:
    """런타임 Sheets 접근이 명시적으로 허용된 상태인지. 운영 기본은 False."""
    return _truthy("ALLOW_GOOGLE_SHEETS_RUNTIME") or _truthy("ALLOW_SHEETS_MIGRATION")


def assert_sheets_runtime_allowed(context: str = "") -> None:
    """런타임 Sheets 접근 차단 가드. 허용 env 가 없으면 즉시 예외.

    Args:
        context: 호출 위치 식별용(예: "signature_service.get_temp_slots"). 오류 메시지에 부가.
    """
    if sheets_runtime_allowed():
        return
    where = f" (blocked at: {context})" if context else ""
    raise SheetsRuntimeDisabled(_DISABLED_MSG + where)
