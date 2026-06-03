# New Tenant Onboarding Sample Data — Plan

작성일: 2026-06-03 · 브랜치: `feat/postgres-foundation`

## Where new account creation happens

`backend/routers/admin.py` → `create_workspace()` (POST `/api/admin/.../create-workspace`).
Two paths:
- **PG / local-mock path** (active local runtime): when `local_drive_mock_enabled()` or
  `pg_tenant_provisioning_enabled()`, calls `local_drive_mock.provision_workspace()`, then
  (inside `if is_configured():`) upserts the PG `tenants` row + activates the signup user, and
  returns early (admin.py:523–572). **← seed trigger goes here.**
- **Google Sheets path** (admin.py:574+): copies `WORK_REFERENCE_TEMPLATE_ID` via Drive. The
  template already carries 업무참고/각종공인증 tab structure → out of scope for this task
  (documented as next step; the template itself can ship samples).

## Where 업무참고 data is stored

- **PG (active when `FEATURE_PG_REFERENCE`):** tables `work_reference_sheets` (per tenant+sheet,
  `headers` JSONB) and `work_reference_rows` (per tenant+sheet+row_index, `data` JSONB).
  Service `backend/services/reference_pg_service.py`: `list_sheets`, `get_sheet_data`,
  `replace_sheet`. Router `backend/routers/reference.py` `GET /api/reference/sheets|/data`
  dispatches to PG via `pg_reference_enabled()`.
- Sheets path: freeform tabs in the `work_sheet_key` workbook (edit-side only).

## Where 각종공인증 data is stored

- **PG (active when `FEATURE_PG_REFERENCE`):** 5 tables `cert_vendors / cert_directions /
  cert_groups / cert_regions / cert_prices` (model `backend/db/models/certification.py`).
  Service `backend/services/certification_pg_service.py`: `bootstrap`, `save_vendor/direction/
  group/region/price`, `delete_*`. Router `backend/routers/certification.py`
  `GET /api/certification-services/bootstrap` dispatches to PG via `pg_reference_enabled()`.
- Cross-references (from frontend `certification-services/page.tsx`):
  - `price.direction` = direction **name** (대분류, e.g. "중국 → 한국")
  - `price.group_id`  = group **id** (중분류)
  - `price.region`    = region **name** (소분류/지역)
  - `group.default_direction` / `region.applicable_directions` = direction **names**
  - `region.applicable_group_ids` = group **ids**
  - `price.vendor_id` = vendor id

## Safest place to seed examples

A new reusable service `backend/services/tenant_sample_seed_service.py`, invoked from the
**PG/local-mock branch** of `create_workspace()` right after the `tenants` row is committed,
gated on `is_configured()`. Seeds **only when the target area is empty** (no work-reference
sheets; empty cert bootstrap), so existing tenants/data are never touched and re-running
workspace creation never duplicates rows.

## Exact files to change

1. **NEW** `backend/services/tenant_sample_seed_service.py` — seeding + removal + emptiness checks.
2. `backend/routers/admin.py` — call `seed_new_tenant_sample_data(login_id)` in the PG/mock path
   (non-fatal, adds a `sample_seed` stage to the result).
3. `backend/routers/admin.py` — add admin-only `POST .../seed-samples/{login_id}` helper
   (seeds only if empty; for future "샘플 데이터 추가" button).
4. `frontend/app/(main)/reference/page.tsx` — small notice when sample rows present.
5. `frontend/app/(main)/certification-services/page.tsx` — small notice when sample rows present.

## Sample markers (for easy filter/delete)

- `SAMPLE_SEED_VERSION = "new_tenant_sample_v1"`
- Reference rows: 비고 column = sample note + hidden `_sample_seed` key in JSONB.
- Cert vendors/groups/regions: name prefixed `[예시]`; price rows: `source = new_tenant_sample_v1`.
- `remove_tenant_sample_data(tenant_id)` deletes the two sample reference sheets and all cert
  rows carrying the marker.

## Rollback plan

- Code: `git restore` the changed files / revert the focused commit (no schema migration added).
- Data: `remove_tenant_sample_data(tenant_id)` removes seeded sample rows for a tenant; or the
  admin can simply edit/delete the clearly-marked `[예시]` rows in the UI. No production data is
  modified — seeding writes only into the new tenant's own empty PG rows.
