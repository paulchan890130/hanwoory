"""Onboarding sample-data seeding for newly created tenants.

When a new tenant workspace is provisioned, the 업무참고 (work-reference) and
각종공인증 (certification) areas are empty, which makes the system hard to learn.
This service seeds a small set of **clearly-marked example rows** into PG so a
new user can see how the structure works.

Guarantees
----------
* **Empty-only**: each area is seeded only when it currently has no rows for the
  tenant. Existing data is never overwritten or duplicated.
* **Idempotent**: re-running workspace creation / seeding does nothing once the
  area is non-empty (so repeated approval/regeneration is safe).
* **Clearly marked**: every sample row carries ``[예시]`` in a name/title and/or
  the note "예시 데이터입니다. 실제 업무에 맞게 수정하거나 삭제하세요.", plus the
  version marker ``new_tenant_sample_v1`` for precise filtering/removal.
* **No production data touched**: writes go only into the new tenant's own
  (empty) PG rows. Existing tenants are never seeded automatically.

This module is PG-only by design (the current local runtime). The Google Sheets
template path already ships tab structure and is out of scope here.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

_log = logging.getLogger("tenant.sample_seed")

SAMPLE_SEED_VERSION = "new_tenant_sample_v1"
SAMPLE_NOTE = "예시 데이터입니다. 실제 업무에 맞게 수정하거나 삭제하세요."
SAMPLE_PRICE_NOTE = "샘플 금액입니다. 실제 사무소 기준에 맞게 수정하세요."

# Work-reference sheets created by the seeder (used by removal).
_SAMPLE_REF_SHEETS = ["사용안내", "체류민원 예시"]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ── 업무참고 (work-reference) ────────────────────────────────────────────────
def _reference_is_empty(tenant_id: str) -> bool:
    from backend.services.reference_pg_service import list_sheets
    return not (list_sheets(tenant_id).get("sheets") or [])


def _ref_row(values: dict) -> dict:
    """Attach the hidden seed marker (not a visible header column)."""
    row = dict(values)
    row["_sample_seed"] = SAMPLE_SEED_VERSION
    return row


def seed_reference_samples(tenant_id: str) -> int:
    """Seed 업무참고 sample sheets. Returns number of rows seeded (0 = skipped)."""
    from backend.services.reference_pg_service import replace_sheet

    if not _reference_is_empty(tenant_id):
        _log.info("[seed] 업무참고 already has data for tenant=%s — skip", tenant_id)
        return 0

    seeded = 0

    # 1) 사용안내
    guide_headers = ["구분", "제목", "내용", "비고"]
    guide_rows = [
        _ref_row({"구분": "[예시] 안내", "제목": "이 시트는 사무소별 업무 기준을 정리하는 곳입니다.",
                  "내용": "체류자격별 준비서류·수임료 기준·내부 메모 등 우리 사무소만의 업무 기준을 자유롭게 정리하세요.",
                  "비고": SAMPLE_NOTE}),
        _ref_row({"구분": "[예시] 활용", "제목": "자주 쓰는 항목을 모아두면 상담·서류 작성이 빨라집니다.",
                  "내용": "탭(시트)을 업무 종류별로 추가하고, 행을 늘려가며 우리 사무소 표준을 만들어 보세요.",
                  "비고": SAMPLE_NOTE}),
        _ref_row({"구분": "[예시] 정리", "제목": "실제 업무에 맞게 행을 수정하거나 삭제하세요.",
                  "내용": "이 예시 행들은 온보딩용입니다. 필요 없으면 삭제해도 됩니다.",
                  "비고": SAMPLE_NOTE}),
    ]
    seeded += replace_sheet(tenant_id, "사용안내", guide_headers, guide_rows)

    # 2) 체류민원 예시
    stay_headers = ["업무구분", "체류자격", "준비서류(예시)", "수임료기준(예시)", "비고"]
    stay_rows = [
        _ref_row({"업무구분": "[예시] 체류기간 연장", "체류자격": "F-4",
                  "준비서류(예시)": "여권, 외국인등록증, 신청서, 체류지 입증자료",
                  "수임료기준(예시)": "사무소 기준으로 입력", "비고": SAMPLE_NOTE}),
        _ref_row({"업무구분": "[예시] 체류기간 연장", "체류자격": "H-2",
                  "준비서류(예시)": "여권, 외국인등록증, 신청서, 고용/체류 입증자료",
                  "수임료기준(예시)": "사무소 기준으로 입력", "비고": SAMPLE_NOTE}),
        _ref_row({"업무구분": "[예시] 영주 신청", "체류자격": "F-5",
                  "준비서류(예시)": "요건별 상이 — 소득·체류기간·자격요건 입증자료",
                  "수임료기준(예시)": "사무소 기준으로 입력", "비고": SAMPLE_NOTE}),
        _ref_row({"업무구분": "[예시] 체류자격 변경", "체류자격": "예: D-2 → E-7",
                  "준비서류(예시)": "변경 사유별 상이 — 자격요건 입증자료",
                  "수임료기준(예시)": "사무소 기준으로 입력", "비고": SAMPLE_NOTE}),
    ]
    seeded += replace_sheet(tenant_id, "체류민원 예시", stay_headers, stay_rows)

    _log.info("[seed] 업무참고 seeded %d rows for tenant=%s (version=%s)",
              seeded, tenant_id, SAMPLE_SEED_VERSION)
    return seeded


# ── 각종공인증 (certification) ───────────────────────────────────────────────
def _certification_is_empty(tenant_id: str) -> bool:
    from backend.services.certification_pg_service import bootstrap
    b = bootstrap(tenant_id)
    return not any(b.get(k) for k in ("vendors", "directions", "groups", "regions", "prices"))


def seed_certification_samples(tenant_id: str) -> dict:
    """Seed 각종공인증 sample structure (대분류/중분류/소분류/조건/가격).

    Returns counts per entity (all 0 = skipped because area not empty)."""
    from backend.services.certification_pg_service import (
        save_vendor, save_direction, save_group, save_region, save_price,
    )

    if not _certification_is_empty(tenant_id):
        _log.info("[seed] 각종공인증 already has data for tenant=%s — skip", tenant_id)
        return {"vendors": 0, "directions": 0, "groups": 0, "regions": 0, "prices": 0}

    # 모든 명칭에 [예시] 접두어 → 명확한 샘플 표시 + 일관된 삭제 기준.
    # 교차참조(group.default_direction / region.applicable_directions / price.direction·region)는
    # 접두어가 붙은 동일 명칭을 사용해 내부 정합성을 유지한다.
    DIR_CN_KR = "[예시] 중국 → 한국"
    DIR_KR_CN = "[예시] 한국 → 중국"

    # 업체 (vendor)
    vendor = save_vendor(tenant_id, {
        "name": "[예시] 샘플 공증업체", "contact": "예: 02-000-0000",
        "memo": SAMPLE_NOTE, "active": "TRUE",
    })
    vid = vendor["id"]

    # 대분류 (directions)
    save_direction(tenant_id, {"name": DIR_CN_KR, "sort_order": "1", "active": "TRUE"})
    save_direction(tenant_id, {"name": DIR_KR_CN, "sort_order": "2", "active": "TRUE"})

    # 중분류 (groups)
    g_single = save_group(tenant_id, {"group_name": "[예시] 미혼/미재혼", "default_direction": DIR_CN_KR,
                                      "applicable_directions": DIR_CN_KR, "sort_order": "1", "active": "TRUE"})
    g_kin = save_group(tenant_id, {"group_name": "[예시] 친족관계", "default_direction": DIR_CN_KR,
                                   "applicable_directions": DIR_CN_KR, "sort_order": "2", "active": "TRUE"})
    g_birth = save_group(tenant_id, {"group_name": "[예시] 출생", "default_direction": DIR_CN_KR,
                                     "applicable_directions": DIR_CN_KR, "sort_order": "3", "active": "TRUE"})
    g_trans = save_group(tenant_id, {"group_name": "[예시] 번역/공증", "default_direction": DIR_KR_CN,
                                     "applicable_directions": DIR_KR_CN, "sort_order": "4", "active": "TRUE"})

    # 소분류/지역 (regions) — 소분류 명칭으로 사용
    r_single = save_region(tenant_id, {"name": "[예시] 미혼공증", "applicable_directions": DIR_CN_KR,
                                       "applicable_group_ids": g_single["id"], "sort_order": "1", "active": "TRUE"})
    r_kin = save_region(tenant_id, {"name": "[예시] 친족관계공증", "applicable_directions": DIR_CN_KR,
                                    "applicable_group_ids": g_kin["id"], "sort_order": "2", "active": "TRUE"})
    r_birth = save_region(tenant_id, {"name": "[예시] 출생공증", "applicable_directions": DIR_CN_KR,
                                      "applicable_group_ids": g_birth["id"], "sort_order": "3", "active": "TRUE"})
    r_trans = save_region(tenant_id, {"name": "[예시] 가족관계증명서 번역공증", "applicable_directions": DIR_KR_CN,
                                      "applicable_group_ids": g_trans["id"], "sort_order": "4", "active": "TRUE"})

    # 가격조건 (prices) — direction=name, group_id=id, region=name. price blank (오해 방지),
    # source=버전 마커(정확한 삭제용), documents=안내문.
    def _price(group_id, direction, region, condition):
        return save_price(tenant_id, {
            "vendor_id": vid, "group_id": group_id, "direction": direction,
            "region": region, "condition": condition,
            "price": "", "possible": "TRUE",
            "documents": f"[예시] {SAMPLE_PRICE_NOTE}",
            "source": SAMPLE_SEED_VERSION, "active": "TRUE",
        })

    _price(g_single["id"], DIR_CN_KR, r_single["name"], "자료완비")
    _price(g_single["id"], DIR_CN_KR, r_single["name"], "자료부족")
    _price(g_kin["id"],    DIR_CN_KR, r_kin["name"],    "기본")
    _price(g_birth["id"],  DIR_CN_KR, r_birth["name"],  "기본")
    _price(g_trans["id"],  DIR_KR_CN, r_trans["name"],  "기본")

    counts = {"vendors": 1, "directions": 2, "groups": 4, "regions": 4, "prices": 5}
    _log.info("[seed] 각종공인증 seeded %s for tenant=%s (version=%s)",
              counts, tenant_id, SAMPLE_SEED_VERSION)
    return counts


# ── Orchestrator ─────────────────────────────────────────────────────────────
def seed_new_tenant_sample_data(tenant_id: str, work_sheet_key: Optional[str] = None) -> dict:
    """Seed onboarding samples for a freshly provisioned tenant (PG path).

    Safe to call unconditionally after workspace creation: each area is seeded
    only if empty. ``work_sheet_key`` is accepted for signature parity with the
    provisioning flow but is unused in the PG path (data is keyed by tenant_id).
    """
    result: dict = {"tenant_id": tenant_id, "version": SAMPLE_SEED_VERSION,
                    "reference_rows": 0, "certification": {}, "errors": []}
    try:
        result["reference_rows"] = seed_reference_samples(tenant_id)
    except Exception as e:  # non-fatal — onboarding nicety must not block provisioning
        _log.warning("[seed] 업무참고 seed failed for tenant=%s: %s", tenant_id, e)
        result["errors"].append(f"reference: {e}")
    try:
        result["certification"] = seed_certification_samples(tenant_id)
    except Exception as e:
        _log.warning("[seed] 각종공인증 seed failed for tenant=%s: %s", tenant_id, e)
        result["errors"].append(f"certification: {e}")
    return result


# ── Rollback / removal helper ────────────────────────────────────────────────
def remove_tenant_sample_data(tenant_id: str) -> dict:
    """Remove seeded sample rows for a tenant (rollback).

    Deletes the two sample reference sheets and every certification row carrying
    the sample marker (``[예시]`` name or ``source == new_tenant_sample_v1``).
    Only marked sample rows are removed — user-edited/real rows are preserved.
    """
    from sqlalchemy import delete, select

    from backend.db.session import get_sessionmaker
    from backend.db.models.work_data import WorkReferenceRow, WorkReferenceSheet
    from backend.db.models.certification import (
        CertVendor, CertDirection, CertGroup, CertRegion, CertPrice,
    )

    removed = {"reference_sheets": 0, "reference_rows": 0,
               "vendors": 0, "directions": 0, "groups": 0, "regions": 0, "prices": 0}
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # work-reference: remove sample sheets that consist solely of marked rows
        for sheet_name in _SAMPLE_REF_SHEETS:
            rows = session.scalars(select(WorkReferenceRow).where(
                WorkReferenceRow.tenant_id == tenant_id,
                WorkReferenceRow.sheet_name == sheet_name,
            )).all()
            if rows and all((r.data or {}).get("_sample_seed") == SAMPLE_SEED_VERSION for r in rows):
                rc = session.execute(delete(WorkReferenceRow).where(
                    WorkReferenceRow.tenant_id == tenant_id,
                    WorkReferenceRow.sheet_name == sheet_name,
                )).rowcount or 0
                session.execute(delete(WorkReferenceSheet).where(
                    WorkReferenceSheet.tenant_id == tenant_id,
                    WorkReferenceSheet.sheet_name == sheet_name,
                ))
                removed["reference_rows"] += rc
                removed["reference_sheets"] += 1

        # certification: name startswith "[예시]" (vendors/directions/groups/regions),
        # prices by source marker. Only marked sample rows are removed.
        for model, key, attr in (
            (CertVendor, "vendors", "name"),
            (CertDirection, "directions", "name"),
            (CertGroup, "groups", "group_name"),
            (CertRegion, "regions", "name"),
        ):
            col = getattr(model, attr)
            rc = session.execute(delete(model).where(
                model.tenant_id == tenant_id, col.like("[예시]%"),
            )).rowcount or 0
            removed[key] += rc
        rc = session.execute(delete(CertPrice).where(
            CertPrice.tenant_id == tenant_id, CertPrice.source == SAMPLE_SEED_VERSION,
        )).rowcount or 0
        removed["prices"] += rc
        session.commit()

    _log.info("[seed] removed sample data for tenant=%s: %s", tenant_id, removed)
    return removed
