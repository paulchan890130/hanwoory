# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

**K.ID SaaS** — an immigration office (출입국) operations platform. Architecture: **Next.js (frontend) + FastAPI (backend)**. All business data lives in **Google Sheets / Google Drive** — do not replace with a relational database.

The `pages/` directory and `app.py` are **legacy Streamlit reference specs** — never import them at runtime. `pages/page_scan.py` specifically is a **donor/reference file** for OCR logic: proven extraction ideas are transplanted from it into `backend/services/ocr_service.py`, but it is not the active runtime file.

---

## Running the Project

**Backend** (from repo root):
```bash
uvicorn backend.main:app --reload --port 8000
```
Swagger docs: `http://localhost:8000/docs`. Health check: `GET /health`.

**Frontend** (from `frontend/`):
```bash
npm run dev      # dev server on port 3000
npm run build    # production build
npm run lint     # ESLint
```

**No automated tests** (no pytest, no jest/vitest). Verify manually via the running app or Swagger UI.

**Required env:**
- Root `.env` — `JWT_SECRET_KEY`, `HANWOORY_ENV` (`local`/`server`), `ALLOWED_ORIGINS`
- Google service account key at `config.KEY_PATH` (Windows: `C:\Users\66885\Documents\...\hanwoory-9eaa1a4c54d7.json`, Linux: `/etc/secrets/hanwoory-9eaa1a4c54d7.json`)
- Tesseract OCR must be installed separately for `backend/routers/scan.py` to work

**Docker** (from repo root):
```bash
docker compose build --no-cache frontend   # required after next.config.js changes
docker compose up -d
```
`API_URL=http://backend:8000` is a build arg baked into Next.js rewrites at build time — runtime env injection is too late. Changing `API_URL` requires a full frontend rebuild.

---

## Architecture

```
[Next.js :3000] ──/api/*──► [FastAPI :8000] ──► [Google Sheets / Drive]
                  (proxy via next.config.js)
```

`next.config.js` proxies all `/api/*` to FastAPI. The frontend calls only relative `/api/...` URLs through `frontend/lib/api.ts` (`baseURL: ""` hardcoded — never add `NEXT_PUBLIC_API_URL`).

### Backend layout

```
backend/
  main.py               — FastAPI app, registers 14 routers
  auth.py               — JWT creation/verification (8h expiry); get_current_user / require_admin deps
  models.py             — All Pydantic request/response models
  routers/              — auth, tasks, customers, daily, memos, events, board,
                          scan, scan_workspace, admin, search, reference, quick_doc, manual
  services/
    tenant_service.py   — Core Google Sheets abstraction (thread-safe, TTL-cached gspread)
    accounts_service.py — Accounts sheet CRUD + password hashing; defines ACCOUNTS_SCHEMA (16 cols)
    ocr_service.py      — Passport OCR (Tesseract+ocrb); ARC OCR (geometry-first orientation)
    roi_ocr_service.py  — ROI-crop OCR for scan workspace; imports helpers from ocr_service
    addr_service.py     — Address correction using national road-name index
  data/
    addr_index.json     — Compact road/dong name index (~3MB, 256 regions, 172K roads)
  scripts/
    build_addr_index.py — Rebuilds addr_index.json from 주소정보 도로명 master file
config.py               — Single source of truth for all Drive/Sheets resource IDs and tab names
core/
  google_sheets.py      — Legacy Streamlit-era helpers (Streamlit imports guarded)
  customer_service.py   — Customer data normalization utilities
```

### Multi-tenant data model

Every user has a `tenant_id` (= `login_id` by default) embedded in their JWT. The **Accounts sheet** (tab `"Accounts"` in `SHEET_KEY`) maps each tenant to two workbooks:

| Column | Purpose |
|---|---|
| `customer_sheet_key` | Customer data workbook — 고객 데이터, 진행업무, 예정업무, 완료업무, 일일결산, 잔액, 일정, 메모 tabs |
| `work_sheet_key` | Work reference workbook — 업무참고, 업무정리 tabs |

`tenant_service._resolve_sheet_key()` routes each tab name to the correct workbook using `_CUSTOMER_WORKBOOK_SHEETS` and `_WORK_WORKBOOK_SHEETS` sets (cached 10 min). **Do not fall back to admin sheet keys for non-default tenants** — a missing key must raise `ValueError`. Exception: `DEFAULT_TENANT_ID` (`"hanwoory"`) falls back to `SHEET_KEY` for backwards compatibility.

### Tenant workspace provisioning

`POST /api/admin/workspace` in `backend/routers/admin.py` (idempotent, stage-by-stage):
1. Creates/reuses office folder under `PARENT_DRIVE_FOLDER_ID`
2. Copies `CUSTOMER_DATA_TEMPLATE_ID` → customer workbook
3. Copies `WORK_REFERENCE_TEMPLATE_ID` → work workbook
4. Writes `folder_id`, `customer_sheet_key`, `work_sheet_key` into Accounts
5. Sets `is_active=TRUE` only when all three are present

`POST /api/admin/bootstrap` — seeds the first admin account (no auth required, idempotent).

### Key resource IDs (all in `config.py`)

| Constant | Purpose |
|---|---|
| `SHEET_KEY` | Admin master spreadsheet (contains Accounts tab) |
| `ADMIN_CUSTOMER_SHEET_KEY` | Admin customer data sheet |
| `PARENT_DRIVE_FOLDER_ID` | Parent Drive folder for all tenant office folders |
| `CUSTOMER_DATA_TEMPLATE_ID` | Template copied for new tenant customer sheet |
| `WORK_REFERENCE_TEMPLATE_ID` | Template copied for new tenant work sheet |

**Never use admin sheet IDs as template IDs** — they are separate files.

### Frontend layout

```
frontend/app/
  (auth)/login/         — Login page (no layout wrapper)
  (main)/layout.tsx     — Protected layout: checks isLoggedIn(), renders Sidebar + Topbar
  (main)/dashboard/     — Active tasks, planned tasks, calendar, expiry alerts
  (main)/customers/     — Customer management
  (main)/tasks/         — Tasks (planned / active / completed)
  (main)/daily/         — Daily settlement
  (main)/monthly/       — Monthly analysis
  (main)/quick-doc/     — Auto document generation (PDF); quick-poa/ sub-page
  (main)/scan/          — OCR passport/ARC scanning
  (main)/reference/     — Reference materials
  (main)/search/        — Global search
  (main)/memos/         — Notes
  (main)/board/         — Board
  (main)/manual/        — GPT-powered manual search
  (main)/admin/         — Admin: account list + workspace provisioning
```

All API calls go through `frontend/lib/api.ts` (axios) — attaches `Authorization: Bearer <token>` on every request; on 401 clears auth state and redirects to `/login`.

Auth helpers: `frontend/lib/auth.ts` (`getUser`, `setUser`, `clearUser`, `isLoggedIn`). `setUser` stores two separate localStorage keys: `user_info` (full JSON object) and `access_token` (bare token string). `api.ts` reads `access_token` directly for the `Authorization` header.

**Auth guard — two layers:**
1. **`frontend/middleware.ts`** (Edge): checks `kid_auth` cookie, redirects before page renders
2. **`(main)/layout.tsx`** (client): `useEffect` checks `isLoggedIn()` via localStorage, keeps `ready=false` until confirmed

### Key frontend dependencies

- **@tanstack/react-query** — data fetching / cache
- **@fullcalendar/react** — calendar on dashboard
- **@radix-ui/*** — headless UI primitives
- **sonner** — toast notifications (`toast.success`, `toast.error`)
- **react-hook-form + zod** — form validation
- **react-zoom-pan-pinch** — still in package.json but no longer used in scan page; do not reintroduce in scan page

---

## Critical Constraints

1. **No Streamlit at runtime.** Never import `pages/` from FastAPI routers or services.
2. **No unconditional `import streamlit`** in `core/` modules — guard with `try/except`.
3. **Google Sheets is the database.** Don't add a relational DB.
4. **`config.py` is the single source of truth** for Drive/Sheets IDs and Korean tab names.
5. **`is_active=TRUE` only after all three keys** (`folder_id`, `customer_sheet_key`, `work_sheet_key`) are confirmed.
6. **Tenant data isolation is strict** — `get_customer_sheet_key()` / `get_work_sheet_key()` must not fall back to admin sheets for non-default tenants.

---

## Google Sheets access patterns

- **FastAPI context:** use `backend/services/tenant_service.py` — `tenant_id` always comes from the JWT, never from session state.
- **Accounts sheet:** use `backend/services/accounts_service._get_ws()` — opens `SHEET_KEY`, auto-creates `Accounts` tab if missing.
- **Drive file operations:** use `google.oauth2.service_account.Credentials` + `googleapiclient.discovery.build("drive", "v3", ...)` directly in the router (see `admin.py`).

### Canonical customer sheet columns

`backend/routers/customers.py` defines `_DEFAULT_CUSTOMER_HEADERS` — authoritative column order:
`고객ID, 한글, 성, 명, 여권, 국적, 성별, 등록증, 번호, 발급일, 만기일, 발급, 만기, 주소, 연, 락, 처, V, 체류자격, 비자종류, 메모, 폴더`

### Accounts sheet schema

`backend/services/accounts_service.py` defines `ACCOUNTS_SCHEMA` (16 columns, order fixed):
`login_id, password_hash, tenant_id, office_name, office_adr, contact_name, contact_tel, biz_reg_no, agent_rrn, is_admin, is_active, folder_id, work_sheet_key, customer_sheet_key, created_at, sheet_key`

---

## OCR subsystem

### Engine split

| Document | Engine | Notes |
|---|---|---|
| Passport | **Tesseract + ocrb** | `_passport_tess_mrz()` — MRZ TD3, ~1-3s, no model loading |
| ARC (외국인등록증) | **Tesseract** | Geometry-first orientation + column-based extraction |

OmniMRZ/PaddleOCR code exists in `ocr_service.py` but **is never called at runtime** — the prewarm thread is disabled (OOM on Render 512MB free tier). OmniMRZ is still installed in `Dockerfile.backend` from source (PyPI wheel is empty) but this is vestigial.

### Tesseract setup (`backend/routers/scan.py` — `_ensure_tesseract()`)

Called at the top of every OCR request. On Linux: probes candidate paths to find the system tessdata dir, copies `/app/tessdata/ocrb.traineddata` there if not present, then sets `TESSDATA_PREFIX` to the **system** tessdata dir. On Windows: uses `C:\Program Files\Tesseract-OCR\tessdata`.

Do **not** point `TESSDATA_PREFIX` at `/app/tessdata/` — it only contains `ocrb` and hides `eng`/`kor`.

### OCR service functions (`backend/services/ocr_service.py`)

```python
parse_passport(img: PIL.Image, fast: bool = False) -> dict
# Tesseract+ocrb only. Returns {성, 명, 성별, 국가, 국적, 여권, 발급, 만기, 생년월일}
# 발급 is always "" — MRZ TD3 does not encode issue date.
# Returns {"_no_mrz": True, ...} on failure.

parse_arc(img: PIL.Image, fast: bool = False) -> dict
# Returns {한글, 등록증, 번호, 발급일, 만기일, 주소, _debug_geometry}
# fast=True limits OCR passes; used by the /arc endpoint.
# 주소 pipeline: geometry orient → column OCR → dated-row parse →
#               hierarchical normalization → addr_service DB correction
```

### ARC back-side pipeline (`ocr_service.py`)

The back side uses a **geometry-first** approach — no OCR rotation voting:

1. **`_geometry_orient_back(bot)`** — column density scan on interior [15%–85%]; finds vertical divider peak (spec: 0.30–0.43 = 0°, 0.57–0.70 = 180°); fine deskew via divider angle polyfit. Returns `(oriented_img, debug_dict)`.
2. **Ambiguity fallback** — when `coarse_confidence == "low_v"` or `"low_h"`, tries +180° and picks winner by `_kor_word_score` (sum of ≥3-char Korean runs).
3. **Column OCR** — splits at `divider_frac`: left col (dates), right col (addresses). Both use `lang="kor"` only; right col selects PSM=6 vs PSM=4 by `_kor_word_score`, not string length.
4. **Address extraction** — `_extract_addr_section` + `_parse_dated_addr_rows` on right-col text first, then `tn_bot` (full back OCR) as fallback. Picks latest dated row whose address passes `_is_valid_address_candidate`.
5. **Hierarchical normalization** — `_apply_hierarchical_region_normalization`: Level1 (시도) exact→alias→short, then Level2 (시군구) within matched parent. Data tables: `LEVEL1_REGIONS`, `LEVEL1_ALIASES`, `LEVEL2_BY_PARENT`, `LEVEL2_ALIASES_BY_PARENT` (all in `ocr_service.py`).
6. **DB correction** — `addr_service.correct_address()` fixes road name OCR errors against 172K-entry index.
7. **Final gate** — `_is_valid_address_candidate`: requires province regex + word-boundary admin-unit token + word-boundary road-name token. Blank is saved instead of garbage.

All geometry fields are exposed in `out["_debug_geometry"]` for debugging.

### Address correction service (`backend/services/addr_service.py`)

Loads `backend/data/addr_index.json` (3MB, lazy, thread-safe) built from the national 주소정보 도로명 master file. Uses prefix-based matching to fix OCR road-name errors (e.g., `다운도 1` → `다운로 1`, `테헤란도 100` → `테헤란로 100`).

Key function: `correct_address(ocr_addr: str) -> str` — returns original string unchanged if no confident correction is found.

To regenerate the index after a new 주소 DB release:
```bash
python backend/scripts/build_addr_index.py PATH_TO_도로명마스터.txt
```

### Scan router endpoints (`backend/routers/scan.py` — legacy full-auto)

- `POST /api/scan/passport` — full passport parse via `ocr_service.parse_passport`, 25s timeout
- `POST /api/scan/arc` — full ARC parse via `ocr_service.parse_arc`, 25s timeout
- `POST /api/scan/register` — upsert customer from OCR result; matches by `여권` or `등록증+번호`

Both routes currently return a **debug-wrapped response**:
```json
{"debug": "passport-parse-done", "result": {...parsed fields...}, "raw_L1": null, "raw_L2": null}
```
The frontend handles this via `(res.data as any).result ?? res.data`. When OCR tuning is complete, remove the `debug` wrapper and return parsed fields directly.

`asyncio.Semaphore(1)` serialises passport+ARC jobs. Both routes check `sem.locked()` and return `{"debug": "passport-busy"|"arc-busy"}` immediately if another job is running.

### Scan workspace endpoints (`backend/routers/scan_workspace.py` — active UI path)

The `/scan` page uses these endpoints, not the full-auto scan endpoints above.

- `POST /api/scan-workspace/passport` — crops image to `roi_json` (normalised x/y/w/h), runs MRZ OCR via `roi_ocr_service.extract_passport_roi`. Returns `{"result": {...}, "roi": {...}}`.
- `POST /api/scan-workspace/arc` — single-field extraction via `roi_ocr_service.extract_arc_field`; or batch via `extract_arc_fields` when `fields_json` supplied. Returns `{"field": "...", "value": "..."}`.

`roi_ocr_service.py` imports low-level helpers directly from `ocr_service.py` (`_ocr`, `_prep_mrz`, `_parse_mrz_pair`, `find_best_mrz_pair_from_text`, etc.). Do not duplicate these helpers.

### Scan page architecture (`frontend/app/(main)/scan/page.tsx`)

The `/scan` page is a **semi-manual OCR workspace** — it never fires OCR on upload. Architecture:

- **`WorkspaceCanvas` component** — fixed-height (660 px) viewport. Image is a movable layer (drag-to-pan, button zoom/rotate, no wheel zoom). Guide boxes are a **separate fixed overlay layer** rendered above the image; they do not move with the image.
- **`computeRoi(guide, container, natural, tf)`** — converts a guide box position (container-space 0–1) to image-space crop coordinates accounting for scale, pan, and rotation (0°/90°/180°/270°). Called at the moment the user clicks an extract button. This is the single source of truth for what the backend crops — if visual alignment ≠ OCR crop, the bug is here.
- **`stateRef` pattern** — `WorkspaceCanvas` writes `{ tf, container, natural }` into a `MutableRefObject` on every render (not via `useEffect`). The OCR handlers in `ScanPage` read from that ref at click time to compute the ROI. No derived ROI state is stored.
- **Guide constants** — `PASSPORT_MRZ_GUIDE` (single gold box, `{x:0.160, y:0.635, w:0.630, h:0.085}`) and `ARC_GUIDE_BOXES` (6 field boxes). All coordinates are container-space (0–1). User moves the image to align document features with the fixed guide boxes, then clicks extract. Back-sticker guides (`만기일`, `주소`) are intentionally narrow+tall to match the rotated orientation of the back card before the user rotates it.
- Zoom: button-only (no wheel), range 0.05×–20×, no upscaling cap on initial fit.
- `POST /api/scan/register` is the save path. Field state (성, 명, 한글, 등록증, … 주소) is read directly from React state at submit time.

---

## Key Coding Patterns

### Task partial updates (backend)

All `PUT /tasks/{type}/{id}` use **read-merge-write** — never full overwrite:

```python
changes = {k: ("" if v is None else str(v))
           for k, v in task.model_dump(exclude_unset=True).items()}
existing = next((r for r in read_sheet(...) if r.get("id") == task_id), {})
merged = {**existing, **changes}
upsert_sheet(..., [merged], id_field="id")
```

`model_dump(exclude_unset=True)` returns only fields present in the request JSON — prevents a single-field edit from zeroing other columns.

### Active task row — controlled state (dashboard)

`ActiveTaskRow` in `dashboard/page.tsx` uses controlled inputs (`value` + `onChange`) for all 13+ fields, with a single `dirty` boolean. A `useEffect` keyed on `task.id` syncs state from server on refetch. The "저장" button renders only when `dirty === true`.

### Dropdown positioning inside overflow containers

Use `position: fixed` + `getBoundingClientRect` when a dropdown lives inside a parent with `overflow: auto`:

```tsx
const updateDropdownPos = () => {
  if (inputRef.current) {
    const r = inputRef.current.getBoundingClientRect();
    setDropdownPos({ top: r.bottom + 2, left: r.left, width: Math.max(r.width, 240) });
  }
};
// Render dropdown with position:"fixed", top/left/width from state, zIndex: 9999.
```

### Flex drawer / panel layout

Drawers filling viewport height must set `minHeight: 0` on `flex: 1` body children. Non-scrolling sections (header, footer) need `flexShrink: 0`. Grid cells inside flex rows need `minWidth: 0`.

### Internal navigation

Always use `router.push('/route')` for same-app routes. Never `<a href="/route" target="_blank">` — opens a new tab that may fail to load webpack chunks from a stale `.next/` cache.

### Daily settlement → active task field routing

`POST /api/daily/entries` triggers `_apply_daily_to_active()` in `backend/routers/daily.py`. The memo `[KID]inc=X;e1=Y;e2=Z[/KID]` tag controls which 진행업무 field is incremented:

| Memo type | Active task field | Source column |
|---|---|---|
| `inc=현금` | `cash` | `income_cash` |
| `inc=이체` | `transfer` | `income_etc` |
| `inc=카드` | `card` | `income_etc` |
| `inc=미수` | `receivable` | `income_etc` |
| `e1=인지` or `e2=인지` | `stamp` | `exp_etc` |

Other expense types (이체/현금/카드) do **not** increment active task fields — they appear only in daily totals. Matching an existing task uses the tuple `(category, date, name, work)`. No match → new task created. The `현금출금` category is always skipped.

**Active task header** — `ACTIVE_HEADER` in `backend/routers/tasks.py` is authoritative (17 columns). Any code writing to `ACTIVE_TASKS_SHEET_NAME` must use all 17 columns including `reception`, `processing`, `storage`. The `_ACTIVE_HEADER` in `daily.py` mirrors this — keep them in sync.

After each `POST /api/daily/entries`, the frontend must invalidate **both** `["daily", "entries"]` and `["tasks", "active"]` in React Query. Use `onSettled` (not `onSuccess`) so invalidation runs even if the response is slow or errors — the backend saves the daily entry before doing the delegation/task side effects, so the entry is in the sheet even when the overall request appears to fail.

### Quick-doc PDF pipeline

```
① GET /api/quick-doc/tree              — selection tree
② POST /api/quick-doc/required-docs    — returns main_docs + agent_docs
③ POST /api/quick-doc/generate-full    — fills PDF fields, merges, applies seals
```

`generate_full` accepts `direct_overrides: dict` (PDF widget name → value) applied after `build_field_values()` — use for post-generation field edits without changing customer data.

---

## Docker build architecture

```
Dockerfile.frontend (multi-stage):
  deps    — npm install only
  builder — ARG API_URL → ENV API_URL → npm run build (rewrites baked here)
  runner  — copies .next/ from builder, runs npm start

Dockerfile.backend:
  python:3.11-slim base
  apt: tesseract-ocr + kor pack, libglib2.0, libsm6, libgl1, libgomp1, poppler-utils, git
  pip install -r requirements.txt
  git clone OmniMRZ + patch pyproject.toml + pip install (PyPI wheel is empty)
  smoke test: python -c "from omnimrz import OmniMRZ; print('smoke test passed')"
  runs: uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

`docker-compose.yml` passes `build.args.API_URL: http://backend:8000` to the builder stage AND sets `environment:` for belt-and-suspenders. The build arg is the critical one.

---

## In-progress / known issues

- **OCR debug mode active** — `/api/scan/passport` and `/api/scan/arc` (full-auto endpoints) still wrap responses in `{"debug": ..., "result": {...}}`. The scan workspace endpoints (`/api/scan-workspace/*`) return clean `{"result": {...}}`. Remove the debug wrapper from the full-auto endpoints when tuning is complete.
- **ARC address accuracy** — geometry-first pipeline + dated-row parsing active in `ocr_service.parse_arc`. `_debug_geometry` key in response contains `divider_frac`, `coarse_confidence`, `addr_source`, `ambig_winner` for diagnosis.
- **OmniMRZ vestigial** — installed in `Dockerfile.backend` from source but never called at runtime (prewarm disabled). Can be removed once Tesseract-only path is confirmed sufficient.
- **Windows local dev** — `backend/main.py` forces stdout/stderr to UTF-8 on Windows to prevent Korean characters appearing as `???` in uvicorn logs. Do not remove this block.
- **`react-zoom-pan-pinch`** — still in `frontend/package.json` but unused. Safe to remove. Do not reintroduce it in the scan page.
