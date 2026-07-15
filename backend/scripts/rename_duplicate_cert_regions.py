# -*- coding: utf-8 -*-
"""cert_regions 신구 taxonomy 중복 표시명 3쌍 — legacy(무제한 노출)와 신규(rgn-*, 특정
대분류/그룹에만 국한)가 완전히 같은 이름을 써서 드롭다운에 같은 라벨이 두 번 뜨는 문제.

병합하지 않는다 — legacy는 6개 대분류/전체 그룹에 무제한 노출되고, 신규는 그중 일부
(전국 2/6, 중국 3/6, 지역상관없음 1/6+그룹 2종)에만 국한되어 실질적으로 다른 규칙이다.
대신 legacy 3건 + 신규(rgn-*) 3건 전부의 표시명(name)에 접미사를 붙여 구분한다
(사용자 확정 정책 — legacy="(공통)", 신규="(지정 업무)"; "지역상관없음"은 "지역 무관"으로
표기 정리). scope·code·연결 업무·활성 상태·cert_prices(이름 기준 저장)는 건드리지 않는다.

사용법(기본 dry-run — 실제 반영은 --apply 필요):
    python -m backend.scripts.rename_duplicate_cert_regions
    python -m backend.scripts.rename_duplicate_cert_regions --apply --tenant hanwoory

운영 DB 적용은 이 스크립트 실행만으로는 되지 않는다 — DATABASE_URL을 운영으로
향하게 하는 것은 명시 승인 없이는 하지 않는다(이 스크립트는 로컬 검증용).
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import text

from backend.db.session import get_sessionmaker

# id -> 새 표시명. 병합/삭제/scope 변경 없음 — name 컬럼 6행만 변경.
RENAMES: dict[str, str] = {
    "region-02": "전국(공통)",
    "region-04": "중국(공통)",
    "region-05": "지역 무관(공통)",
    "rgn-all": "전국(지정 업무)",
    "rgn-china": "중국(지정 업무)",
    "rgn-region-irrelevant": "지역 무관(지정 업무)",
}


def find_targets(session, tenant: str | None) -> list[dict]:
    q = "SELECT id, tenant_id, name FROM cert_regions WHERE id = ANY(:ids)"
    params: dict = {"ids": list(RENAMES.keys())}
    if tenant:
        q += " AND tenant_id = :tenant"
        params["tenant"] = tenant
    rows = session.execute(text(q), params).mappings().all()
    return [dict(r) for r in rows if r["name"] != RENAMES.get(r["id"])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 UPDATE 실행(기본은 dry-run)")
    ap.add_argument("--tenant", default=None, help="특정 tenant_id만(기본: 전체)")
    args = ap.parse_args()

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        targets = find_targets(session, args.tenant)
        if not targets:
            print("변경 대상 없음(이미 원하는 이름이거나 해당 id가 없음).")
            return 0

        print(f"이름 변경 대상 {len(targets)}건:")
        for r in targets:
            print(f"  {r['id']:24} {r['tenant_id']:10} {r['name']!r} -> {RENAMES[r['id']]!r}")

        if not args.apply:
            print("\ndry-run 모드입니다. 실제 반영하려면 --apply 를 추가하세요.")
            return 0

        for r in targets:
            session.execute(text(
                "UPDATE cert_regions SET name = :name WHERE id = :id AND tenant_id = :tenant_id"
            ), {"name": RENAMES[r["id"]], "id": r["id"], "tenant_id": r["tenant_id"]})
        session.commit()
        print(f"\n{len(targets)}건 변경 완료.")

        remaining = find_targets(session, args.tenant)
        print(f"재검사: 남은 대상 {len(remaining)}건 (0이어야 정상).")
        return 0 if not remaining else 1


if __name__ == "__main__":
    sys.exit(main())
