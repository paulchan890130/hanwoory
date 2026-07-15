# -*- coding: utf-8 -*-
"""각종공인증 소분류/지역(cert_regions) 컬럼 밀림 복구 — idempotent, 기본 dry-run.

원인: `import_excel_snapshot_to_pg_local.py`의 `imp_certification()`이 신 스키마
헤더(id,name,applicable_directions,applicable_group_ids,sort_order,active,
created_at,updated_at — 8열)를 구 스키마 원본 데이터(id,name,sort_order,active,
created_at,updated_at — 6열)에 그대로 zip해, region-01~region-18(레거시 소분류
18건)의 값이 두 칸씩 밀려 저장됐다:

    (손상) applicable_directions ← 원래 sort_order 값 (예: "6")
    (손상) applicable_group_ids  ← 원래 active 값 ("TRUE")
    (손상) sort_order            ← 원래 created_at 값 (날짜문자열)
    (손상) active                ← 원래 updated_at 값 (날짜문자열, created_at과 동일)
    created_at / updated_at      ← 비어서 NULL

이 밀림 때문에 검색화면 종속 드롭다운(`visibleRegions`)이 "선택된 대분류/중분류에
`applicable_directions`/`applicable_group_ids`가 없으면 제외" 규칙에 걸려, 대분류나
중분류를 하나라도 고르면 레거시 18개 지역(길림성 등 실제 사용 데이터 대부분)이
드롭다운에서 사라진다.

복구: 밀린 값을 원위치로 되돌리고(sort_order/active/created_at/updated_at 복원),
applicable_directions/applicable_group_ids는 원래 존재하지 않던 필드이므로
빈 문자열(= 필터 미적용, 모든 대분류/중분류에서 노출)로 되돌린다.

감지 조건(재실행해도 안전 — 복구 후에는 매칭되지 않음):
    id LIKE 'region-%' AND applicable_group_ids = 'TRUE'
    AND sort_order ~ '^\\d{4}-\\d{2}-\\d{2}'  (날짜 형태)

사용법(기본 dry-run — 실제 반영은 --apply 필요):
    python -m backend.scripts.repair_cert_regions_corruption
    python -m backend.scripts.repair_cert_regions_corruption --apply
    python -m backend.scripts.repair_cert_regions_corruption --apply --tenant hanwoory

운영 DB 적용은 이 스크립트를 실행하는 것만으로는 되지 않는다 — DATABASE_URL을
운영으로 향하게 하는 것은 명시 승인 없이는 하지 않는다(이 스크립트는 로컬 검증용).
"""
from __future__ import annotations

import argparse
import re
import sys

from sqlalchemy import text

from backend.db.session import get_sessionmaker

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def find_corrupted(session, tenant: str | None) -> list[dict]:
    q = "SELECT id, tenant_id, name, applicable_directions, applicable_group_ids, sort_order, active FROM cert_regions WHERE id LIKE 'region-%'"
    params = {}
    if tenant:
        q += " AND tenant_id = :tenant"
        params["tenant"] = tenant
    rows = session.execute(text(q), params).mappings().all()
    out = []
    for r in rows:
        if (r["applicable_group_ids"] or "") == "TRUE" and _DATE_RE.match(r["sort_order"] or ""):
            out.append(dict(r))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 UPDATE 실행(기본은 dry-run)")
    ap.add_argument("--tenant", default=None, help="특정 tenant_id만(기본: 전체)")
    args = ap.parse_args()

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        corrupted = find_corrupted(session, args.tenant)
        if not corrupted:
            print("복구 대상 없음(이미 정리된 상태이거나 손상 행이 없음).")
            return 0

        print(f"손상 행 {len(corrupted)}건 발견:")
        plans = []
        for r in corrupted:
            new_sort_order = r["applicable_directions"] or "0"
            new_active = "TRUE" if (r["applicable_group_ids"] or "") == "TRUE" else "FALSE"
            new_created_at = r["sort_order"]
            new_updated_at = r["active"]
            plans.append({
                "id": r["id"], "tenant_id": r["tenant_id"], "name": r["name"],
                "new_sort_order": new_sort_order, "new_active": new_active,
                "new_created_at": new_created_at, "new_updated_at": new_updated_at,
            })
            print(f"  {r['id']:12} {r['name']:20} sort_order {r['applicable_directions']!r}->{new_sort_order!r} "
                  f"active TRUE->{new_active!r} applicable_directions/group_ids -> ''")

        if not args.apply:
            print("\ndry-run 모드입니다. 실제 반영하려면 --apply 를 추가하세요.")
            return 0

        for p in plans:
            session.execute(text(
                "UPDATE cert_regions SET applicable_directions = '', applicable_group_ids = '', "
                "sort_order = :sort_order, active = :active, created_at = :created_at, updated_at = :updated_at "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ), {
                "sort_order": p["new_sort_order"], "active": p["new_active"],
                "created_at": p["new_created_at"], "updated_at": p["new_updated_at"],
                "id": p["id"], "tenant_id": p["tenant_id"],
            })
        session.commit()
        print(f"\n{len(plans)}건 복구 완료.")

        remaining = find_corrupted(session, args.tenant)
        print(f"재검사: 남은 손상 행 {len(remaining)}건 (0이어야 정상).")
        return 0 if not remaining else 1


if __name__ == "__main__":
    sys.exit(main())
