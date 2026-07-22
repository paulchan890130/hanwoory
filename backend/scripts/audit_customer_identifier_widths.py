"""고객 고정폭 식별값 선행 0 손실 감사 (읽기 전용 · dry-run 전용).

외국인등록번호 앞자리(reg_front, YYMMDD 6자리)·뒷자리 폭·전화·여권의 선행 0
손실 위험을 **집계만** 한다. 이 스크립트는 절대 DB 를 수정하지 않으며 ``--apply``
옵션도 제공하지 않는다(실제 일괄 보정은 별도 승인 대상). 화면 정규화(읽기 방어선)는
이미 ``customer_pg_service._row_to_dict`` 에서 이뤄지므로, 이 보고서는 "원문(raw)"이
어떤 상태인지만 진단하기 위한 것이다.

분류(reg_front):
  reg_front_valid_6        정확히 6자리 & 유효 YYMMDD (정상)
  reg_front_recoverable    1~5자리(선행 0 손실 추정) → 좌측 0 채움 시 유효 YYMMDD
  reg_front_invalid        위 어디에도 해당 안 됨(7자리+/월·일 범위 위반 등)
기타 위험 지표(휴리스틱 — 검토 후보):
  phone1_leading_zero_risk   phone1 이 순수 숫자·0 으로 시작 안 함·길이 9~10 (앞 0 손실 추정)
  reg_back_width_risk        reg_back_last4 자릿수<4, 또는 평문 reg_back 자릿수≠7
  passport_numeric_risk      여권번호가 순수 숫자(숫자 강제 변환 시 앞 0 손실 위험)

원칙: 멱등 · dry-run 전용 · 운영 DB 실행 금지 ·
민감정보(reg_front/reg_back/여권 원문·이름·주소) 미출력. 고객ID(테넌트 로컬 순번)와
집계 수치만 출력한다.

사용:
  python -m backend.scripts.audit_customer_identifier_widths
  python -m backend.scripts.audit_customer_identifier_widths --tenant <tenant_id>
  python -m backend.scripts.audit_customer_identifier_widths --samples 5
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_CLASSES = (
    "reg_front_valid_6",
    "reg_front_recoverable",
    "reg_front_invalid",
    "phone1_leading_zero_risk",
    "reg_back_width_risk",
    "passport_numeric_risk",
)


def _classify_reg_front(raw) -> str:
    """reg_front 원문 → 분류. 값 자체는 반환하지 않는다."""
    from backend.services.customer_identifier_normalize import normalize_reg_front
    if raw is None or str(raw).strip() == "":
        return ""  # 빈 값은 위험 아님(집계 제외)
    strict = normalize_reg_front(raw, allow_numeric_recovery=False)
    if strict.valid and strict.canonical_value:
        return "reg_front_valid_6"
    loose = normalize_reg_front(raw, allow_numeric_recovery=True)
    if loose.valid and loose.canonical_value:
        # 엄격(정확 6자리)으로는 실패했으나 좌측 0 채움으로 유효 → 선행 0 손실 추정.
        return "reg_front_recoverable"
    return "reg_front_invalid"


def _phone_risk(raw) -> bool:
    # 구분자를 제거한 순수 숫자만 남았고(전형적 전화 구성), 0 으로 시작하지 않으며
    # 길이가 9~10 → 앞 0 하나가 빠졌을 가능성(정상은 010… 11자리 / 지역 0…).
    orig = str(raw or "").strip()
    s = re.sub(r"[\s\-().]", "", orig)
    return bool(s) and s.isdigit() and not s.startswith("0") and len(s) in (9, 10)


def _reg_back_width_risk(reg_back_plain, last4) -> bool:
    l4 = re.sub(r"\D", "", str(last4 or ""))
    if last4 and 0 < len(l4) < 4:
        return True
    plain = str(reg_back_plain or "")
    if plain and "*" not in plain:
        d = re.sub(r"\D", "", plain)
        if d and len(d) != 7:
            return True
    return False


def _passport_numeric_risk(raw) -> bool:
    s = str(raw or "").strip()
    return bool(s) and s.isdigit()


def run(tenant_filter: str | None, samples: int) -> None:
    from sqlalchemy import select
    from backend.db.models.customer import Customer
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    # tenant → {class: count}
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # tenant → {class: [customer_id, ...]} (원문 값 미포함, 위치 파악용)
    sample_ids: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    total_rows = 0

    with SessionLocal() as session:
        stmt = select(Customer).where(Customer.deleted_at.is_(None))
        if tenant_filter:
            stmt = stmt.where(Customer.tenant_id == tenant_filter)
        rows = session.scalars(stmt).all()
        total_rows = len(rows)
        for row in rows:
            tid = row.tenant_id
            hits = []
            rf = _classify_reg_front(getattr(row, "reg_front", None))
            if rf:
                hits.append(rf)
            if _phone_risk(getattr(row, "phone1", None)):
                hits.append("phone1_leading_zero_risk")
            if _reg_back_width_risk(getattr(row, "reg_back", None),
                                    getattr(row, "reg_back_last4", None)):
                hits.append("reg_back_width_risk")
            if _passport_numeric_risk(getattr(row, "passport_no", None)):
                hits.append("passport_numeric_risk")
            for cls in hits:
                counts[tid][cls] += 1
                if len(sample_ids[tid][cls]) < samples:
                    sample_ids[tid][cls].append(str(row.customer_id))

    # ── 출력 ──
    print(f"전체 고객 행(비삭제): {total_rows}")
    if tenant_filter:
        print(f"필터 테넌트: {tenant_filter}")
    print(f"테넌트 수: {len(counts)}")

    grand = defaultdict(int)
    for tid in sorted(counts):
        tc = counts[tid]
        line = " · ".join(f"{cls}={tc.get(cls, 0)}" for cls in _CLASSES if tc.get(cls, 0))
        if not line:
            continue
        print(f"\n[테넌트 {tid}]")
        print(f"  {line}")
        for cls in _CLASSES:
            ids = sample_ids[tid].get(cls)
            if ids:
                print(f"    {cls} 예시 고객ID(원문값 미포함): {', '.join(ids)}")
            grand[cls] += tc.get(cls, 0)

    print("\n[전체 합계]")
    any_hit = False
    for cls in _CLASSES:
        if grand[cls]:
            any_hit = True
            print(f"  {cls}: {grand[cls]}")
    if not any_hit:
        print("  위험 지표 없음(모든 reg_front 정상·기타 위험 0).")

    print("\n[DRY-RUN] 이 스크립트는 DB 를 수정하지 않습니다(--apply 미제공).")
    print("실제 일괄 보정은 별도 승인·런북 대상입니다. 화면/출력은 읽기 방어선에서 이미 복구됩니다.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="고객 고정폭 식별값 선행 0 손실 감사 (읽기 전용 · dry-run 전용)")
    parser.add_argument("--tenant", default=None, help="특정 tenant_id 만 감사")
    parser.add_argument("--samples", type=int, default=5,
                        help="분류별 예시 고객ID 최대 개수(원문값 미포함, 기본 5)")
    args = parser.parse_args()

    from backend.db import session as db_session
    if not db_session.is_configured():
        print("[ERROR] PostgreSQL 미구성 (DATABASE_URL 없음). 로컬 DB 설정 후 실행하세요.")
        sys.exit(1)

    print("=== 고객 고정폭 식별값 선행 0 손실 감사 (DRY-RUN · 읽기 전용) ===")
    run(args.tenant, max(0, args.samples))


if __name__ == "__main__":
    main()
