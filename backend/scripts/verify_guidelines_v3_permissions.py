# -*- coding: utf-8 -*-
"""실무지침 v3 편집 권한 역할별 수용검사 (회귀검증용, 로컬/테스트 서버 전용).

권한 정책(확정):
  - 마스터 / full admin / 준 관리자(sub_admin) = 조회 + 편집(추가·수정·삭제) 가능
  - 일반 사용자(user)                          = 조회만, 편집 API 403
  - 무인증                                     = 조회·편집 전부 401

검사 항목:
  1) 무인증: 조회 401 · 편집 401
  2) 역할별 /edit/status: editable = master/admin/sub_admin true, user false
  3) 역할별 목록/상세 editable 필드 동일 기준
  4) user: POST/PUT/DELETE/impact/export 전부 403, 조회 200
  5) master·sub_admin: 대분류 테스트 CRUD 사이클(추가→수정→impact→삭제) 성공 + 잔존 0
     (테스트 키는 zz-perm-test-* — 실데이터와 충돌 없음, 종료 시 완전 제거)

사용법(대상 서버는 FEATURE_GUIDELINES_V3=1, FEATURE_GUIDELINES_V3_EDIT=1,
FEATURE_SINGLE_SESSION off, PG 구성 상태여야 하며 JWT_SECRET_KEY 가 이 프로세스와
동일해야 토큰 발급이 유효하다. 계정은 대상 DB 에 실재하는 활성 계정일 것):

  python -m backend.scripts.verify_guidelines_v3_permissions \
      --base-url http://127.0.0.1:8010 \
      --master-id wkdwhfl --sub-admin-id <sub_admin 계정> --user-id <일반 계정>

전부 통과 시 exit 0, 실패 1건이라도 있으면 exit 1.
"""
from __future__ import annotations

import argparse
import sys

import requests

from backend.auth import create_access_token

V3 = "/api/guidelines/v3"
# 대분류 키 규칙(^[A-Z0-9_]{1,12}$)에 맞는 테스트 전용 키 — 실데이터(A~H)와 충돌 없음
TEST_GROUP_KEY_MASTER = "ZPERMTEST_M"
TEST_GROUP_KEY_SUB = "ZPERMTEST_S"

_results: list[tuple[bool, str]] = []


def check(ok: bool, label: str) -> None:
    _results.append((bool(ok), label))
    print(("[PASS] " if ok else "[FAIL] ") + label)


def mint(login_id: str) -> dict:
    """실계정 login_id 로 최소 payload 토큰 발급 — 권한은 서버가 PG에서 재조회한다."""
    token = create_access_token({"sub": login_id, "tenant_id": login_id})
    return {"Authorization": f"Bearer {token}"}


def crud_cycle(base: str, hdr: dict, role_label: str, group_key: str) -> None:
    """대분류 테스트 CRUD 사이클 — 성공 후 오버레이 행(톰스톤 포함) 완전 제거까지 확인."""
    # 이전 실행 잔존 정리(있으면) — 실패해도 무시
    requests.delete(f"{base}{V3}/edit/group/{group_key}", headers=hdr, timeout=15)
    requests.post(f"{base}{V3}/edit/group/{group_key}/revert", headers=hdr, timeout=15)

    r = requests.post(f"{base}{V3}/edit/group", headers=hdr, timeout=15,
                      json={"group_key": group_key, "label": f"권한검사용 {role_label}",
                            "sort_order": 990, "is_active": True})
    check(r.status_code == 200, f"{role_label}: 대분류 추가 200 (실제 {r.status_code})")

    r = requests.put(f"{base}{V3}/edit/group/{group_key}", headers=hdr, timeout=15,
                     json={"label": f"권한검사용 {role_label} 수정"})
    check(r.status_code == 200, f"{role_label}: 대분류 수정 200 (실제 {r.status_code})")

    r = requests.get(f"{base}{V3}/edit/impact/group/{group_key}", headers=hdr, timeout=15)
    check(r.status_code == 200, f"{role_label}: impact 조회 200 (실제 {r.status_code})")

    r = requests.get(f"{base}{V3}/qualifications", headers=hdr, timeout=15)
    present = any(g.get("group_key") == group_key for g in r.json().get("groups", []))
    check(r.status_code == 200 and present, f"{role_label}: 저장 후 목록에 반영(재조회 유지)")

    r = requests.delete(f"{base}{V3}/edit/group/{group_key}", headers=hdr, timeout=15)
    check(r.status_code == 200, f"{role_label}: 대분류 삭제 200 (실제 {r.status_code})")

    r = requests.get(f"{base}{V3}/qualifications", headers=hdr, timeout=15)
    gone = all(g.get("group_key") != group_key for g in r.json().get("groups", []))
    check(r.status_code == 200 and gone, f"{role_label}: 삭제 후 화면 잔존 0")

    # 편집 신설 항목의 delete 는 톰스톤 행을 남긴다 → revert 로 오버레이 행 자체를 제거
    r = requests.post(f"{base}{V3}/edit/group/{group_key}/revert", headers=hdr, timeout=15)
    check(r.status_code == 200, f"{role_label}: revert(톰스톤 제거) 200 (실제 {r.status_code})")
    r = requests.post(f"{base}{V3}/edit/group/{group_key}/revert", headers=hdr, timeout=15)
    check(r.status_code == 404, f"{role_label}: 재revert 404 = 오버레이 행 완전 제거 (실제 {r.status_code})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--master-id", required=True, help="마스터 또는 full admin 계정")
    ap.add_argument("--sub-admin-id", required=True, help="role=sub_admin 계정")
    ap.add_argument("--user-id", required=True, help="일반(user) 계정")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    # 1) 무인증
    r = requests.get(f"{base}{V3}/qualifications", timeout=15)
    check(r.status_code == 401, f"무인증: 조회 401 (실제 {r.status_code})")
    r = requests.post(f"{base}{V3}/edit/group", json={}, timeout=15)
    check(r.status_code == 401, f"무인증: 편집 401 (실제 {r.status_code})")

    roles = [("master", args.master_id, True), ("sub_admin", args.sub_admin_id, True),
             ("user", args.user_id, False)]

    # 2)·3) 역할별 editable
    for label, login_id, want in roles:
        hdr = mint(login_id)
        r = requests.get(f"{base}{V3}/edit/status", headers=hdr, timeout=15)
        body = r.json() if r.status_code == 200 else {}
        check(r.status_code == 200 and body.get("editable") is want,
              f"{label}({login_id}): edit-status 200 editable={want} "
              f"(실제 {r.status_code} {body.get('editable')} role={body.get('role')})")
        r = requests.get(f"{base}{V3}/qualifications", headers=hdr, timeout=15)
        check(r.status_code == 200 and r.json().get("editable") is want,
              f"{label}: 목록 200 editable={want}")
        r = requests.get(f"{base}{V3}/qualifications/F-1", headers=hdr, timeout=15)
        check(r.status_code == 200 and r.json().get("editable") is want,
              f"{label}: 상세 200 editable={want}")

    # 4) 일반 사용자 — 편집 전부 403
    hdr = mint(args.user_id)
    denied = [
        ("POST", f"{base}{V3}/edit/group", {"json": {"group_key": "ZUSERTRY", "label": "x"}}),
        ("PUT", f"{base}{V3}/edit/group/A", {"json": {"label": "x"}}),
        ("DELETE", f"{base}{V3}/edit/group/A", {}),
        ("GET", f"{base}{V3}/edit/impact/group/A", {}),
        ("GET", f"{base}{V3}/edit/export", {}),
        ("POST", f"{base}{V3}/edit/group/A/revert", {}),
    ]
    for method, url, kw in denied:
        r = requests.request(method, url, headers=hdr, timeout=15, **kw)
        check(r.status_code == 403, f"user: {method} {url.split(V3)[1]} 403 (실제 {r.status_code})")

    # 5) 편집 역할 CRUD 사이클
    crud_cycle(base, mint(args.master_id), "master", TEST_GROUP_KEY_MASTER)
    crud_cycle(base, mint(args.sub_admin_id), "sub_admin", TEST_GROUP_KEY_SUB)

    passed = sum(1 for ok, _ in _results if ok)
    print(f"\nRESULT: {passed}/{len(_results)} " +
          ("ALL PASS" if passed == len(_results) else "FAIL"))
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    sys.exit(main())
