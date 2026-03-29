# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

This is **K.ID SaaS** — an immigration office (출입국) operations platform rebuilt from a legacy Streamlit app into a **Next.js (frontend) + FastAPI (backend)** architecture. The original Streamlit files in `pages/` and `app.py` are **reference specifications only** — they are not running in the current architecture and must not be imported or executed at runtime.

All business data lives in **Google Sheets / Google Drive** and stays there. Do not replace this with a database-first design.

---

## Running the Project

**Backend** (from repo root):
```bash
uvicorn backend.main:app --reload --port 8000
```
Swagger docs at `http://localhost:8000/docs`. Health check: `GET /health`.

**Frontend** (from `frontend/`):
```bash
npm run dev      # dev server on port 3000
npm run build    # production build
npm run lint     # ESLint
```

**Required env files:**
- Root `.env` — `JWT_SECRET_KEY`, `HANWOORY_ENV` (`local`/`server`), `ALLOWED_ORIGINS`
- `frontend/.env.local` — not required for local dev (axios uses relative `""` base URL; Next.js proxy handles routing)
- Google service account key at `config.KEY_PATH` (Windows: `C:\Users\66885\Documents\...\hanwoory-9eaa1a4c54d7.json`, Linux: `/etc/secrets/hanwoory-9eaa1a4c54d7.json`)

**Tesseract OCR** must be installed separately for `backend/routers/scan.py` to work.

**Docker** (from repo root):
```bash
docker compose build --no-cache frontend   # must rebuild after next.config.js changes
docker compose up -d
```
`API_URL=http://backend:8000` is passed as a build arg to the frontend builder stage so that `next.config.js` rewrites bake in the correct Docker-internal hostname. Changing this value requires a full frontend rebuild — runtime env injection is too late because Next.js bakes rewrites into `.next/routes-manifest.json` at build time.

There are **no automated tests** in this project (no pytest, no jest/vitest). Verification is done manually via the running app or the Swagger UI.

---

## Architecture

```
[Next.js :3000] ──/api/*──► [FastAPI :8000] ──► [Google Sheets / Drive]
                  (proxy via next.config.js)
```

`next.config.js` proxies all `/api/*` requests to FastAPI, so the frontend only ever calls relative `/api/...` URLs via `frontend/lib/api.ts`. `api.ts` uses `baseURL: ""` (hardcoded) — never add a `NEXT_PUBLIC_API_URL` env var; it was removed because it caused confusion with the Docker build-arg `API_URL` used by the proxy layer.

### Backend layout

```
backend/
  main.py               — FastAPI app, registers 13 routers
  auth.py               — JWT creation/verification (8h expiry); get_current_user / require_admin deps
  models.py             — All Pydantic request/response models
  routers/              — auth, tasks, customers, daily, memos, events, board,
                          scan, admin, search, reference, quick_doc, manual
  services/
    tenant_service.py   — Core Google Sheets abstraction (Streamlit-free, thread-safe)
    accounts_service.py — Accounts sheet CRUD + password hashing
    ocr_service.py      — Passport OCR via OmniMRZ (PaddleOCR); ARC OCR via Tesseract
config.py               — Single source of truth for all resource IDs and sheet tab names
core/
  google_sheets.py      — Legacy Streamlit-era helpers (imports guarded against Streamlit)
  customer_service.py   — Customer data normalization utilities
```

### Multi-tenant data model

Every user has a `tenant_id` (equal to `login_id` by default) embedded in their JWT.

The **Accounts sheet** (tab `"Accounts"` in `SHEET_KEY`) maps each tenant to two workbooks:

| Accounts column | Purpose |
|---|---|
| `customer_sheet_key` | Customer data workbook — holds tabs: 고객 데이터, 진행업무, 예정업무, 완료업무, 일일결산, 잔액, 일정, 단기/중기/장기메모 |
| `work_sheet_key` | Work reference workbook — holds tabs: 업무참고, 업무정리 |

`tenant_service._resolve_sheet_key()` routes each sheet tab name to the correct workbook automatically. The tenant map is cached for 10 min (`_TENANT_MAP_CACHE`).

**Do not fall back to admin/master sheet keys for non-default tenants.** A missing key must raise `ValueError`.

Exception: `DEFAULT_TENANT_ID` (`"hanwoory"`) falls back to `SHEET_KEY` / `WORK_REFERENCE_TEMPLATE_ID` for backwards compatibility.

### Tenant workspace provisioning

`POST /api/admin/workspace` in `backend/routers/admin.py`:
1. Creates (or reuses) an office folder under `PARENT_DRIVE_FOLDER_ID`
2. Copies `CUSTOMER_DATA_TEMPLATE_ID` → new customer workbook
3. Copies `WORK_REFERENCE_TEMPLATE_ID` → new work workbook
4. Writes `folder_id`, `customer_sheet_key`, `work_sheet_key` into Accounts
5. Sets `is_active=TRUE` only when all three are present

Each stage is independent. Existing values are never overwritten with empty strings (partial success is preserved). The endpoint is idempotent — re-running it skips stages where values already exist.

`POST /api/admin/bootstrap` creates the **first admin account only** (no auth required, idempotent — fails if any account already exists). Use this to seed a fresh deployment.

### Key resource IDs (all in `config.py`)

| Constant | Purpose |
|---|---|
| `SHEET_KEY` | Admin master spreadsheet — contains the `Accounts` tab |
| `ADMIN_CUSTOMER_SHEET_KEY` | Admin customer data sheet (기준 고객 데이터) |
| `PARENT_DRIVE_FOLDER_ID` | Parent Drive folder for all tenant office folders |
| `CUSTOMER_DATA_TEMPLATE_ID` | Template copied for new tenant customer sheet |
| `WORK_REFERENCE_TEMPLATE_ID` | Template copied for new tenant work sheet |

**Never use admin sheet IDs as template IDs.** They are separate files.

### Frontend layout

```
frontend/app/
  (auth)/login/         — Login page (no layout wrapper)
  (main)/layout.tsx     — Protected layout: checks isLoggedIn(), renders Sidebar + Topbar
  (main)/dashboard/     — Home: active tasks, planned tasks, calendar, expiry alerts
  (main)/customers/     — Customer management
  (main)/tasks/         — Tasks (planned / active / completed)
  (main)/daily/         — Daily settlement
  (main)/monthly/       — Monthly analysis
  (main)/quick-doc/     — Auto document generation (PDF)
    quick-poa/          — Quick power of attorney sub-page
  (main)/scan/          — OCR passport/ARC scanning
  (main)/reference/     — Reference materials
  (main)/search/        — Global search
  (main)/memos/         — Notes
  (main)/board/         — Board
  (main)/manual/        — GPT-powered manual search
  (main)/admin/         — Admin: account list + workspace provisioning (admin only)
```

All API calls go through `frontend/lib/api.ts` (axios):
- Attaches `Authorization: Bearer <token>` from `localStorage.getItem("access_token")` on every request
- On 401: clears `access_token`, `user_info` from localStorage, clears `kid_auth` cookie, redirects to `/login`

Auth state helpers are in `frontend/lib/auth.ts` (`getUser`, `setUser`, `clearUser`, `isLoggedIn`). The `user_info` localStorage key stores the full `UserInfo` object (`login_id`, `tenant_id`, `is_admin`, `office_name`, `access_token`).

**Auth guard — two layers:**
1. **`frontend/middleware.ts` (Edge, first layer):** checks for `kid_auth` cookie; redirects to `/login` before the page renders if absent. Cannot read localStorage — uses a presence cookie set by `setUser()` and cleared by `clearUser()`.
2. **`(main)/layout.tsx` (client, second layer):** `useEffect` checks `isLoggedIn()` via localStorage; keeps `ready=false` (blank div, not app content) until auth confirmed; calls `router.replace("/login")` if not logged in.

Public routes: `/login`, `/_next/*`, `/api/*`, static assets. Everything else requires the `kid_auth` cookie. The cookie is not httpOnly — it is a presence signal only; real auth is the JWT validated by FastAPI on every request.

Frontend utilities are in `frontend/lib/utils.ts` (`safeInt`, `formatNumber`, `today`, `cn`).

### Key frontend dependencies

- **@tanstack/react-query** — data fetching / cache
- **@fullcalendar/react** — calendar on dashboard
- **@radix-ui/*** — headless UI primitives (dialog, dropdown, tabs, checkbox, select, etc.)
- **sonner** — toast notifications (`toast.success`, `toast.error`)
- **react-hook-form + zod** — form validation
- **axios** — HTTP client (all calls via `frontend/lib/api.ts`)

### JWT payload fields

`get_current_user` in `backend/auth.py` extracts these from the token:

| Field | Source claim | Notes |
|---|---|---|
| `login_id` | `sub` | User's login ID |
| `tenant_id` | `tenant_id` | Determines which workbooks to open |
| `is_admin` | `is_admin` | Boolean — gates `require_admin` routes |
| `office_name` | `office_name` | Display name |
| `contact_name` | `contact_name` | Contact person name |

---

## Critical Constraints

1. **No Streamlit at runtime.** `pages/` files are legacy specs. Never import them from FastAPI routers or services.
2. **No unconditional `import streamlit`** in `core/` modules. Guard with `try/except`.
3. **Google Sheets is the database.** Don't add a relational DB or replace sheet operations.
4. **`config.py` is the single source of truth** for all Drive/Sheets resource IDs and sheet tab names. Never hardcode Korean tab names or Drive IDs elsewhere.
5. **`is_active=TRUE` only after all three keys** (`folder_id`, `customer_sheet_key`, `work_sheet_key`) are confirmed valid.
6. **Tenant data isolation is strict.** `get_customer_sheet_key()` / `get_work_sheet_key()` must not fall back to admin sheets for non-default tenants.

---

## Google Sheets access patterns

- **FastAPI context:** use `backend/services/tenant_service.py` — no `st.session_state`, thread-safe gspread singleton with TTL. `tenant_id` always comes from the JWT (`get_current_user`), never from session state.
- **Accounts sheet specifically:** use `backend/services/accounts_service._get_ws()` — opens `SHEET_KEY` and auto-creates `Accounts` tab if missing.
- **Drive file operations:** use `google.oauth2.service_account.Credentials` + `googleapiclient.discovery.build("drive", "v3", ...)` directly in the router (see `admin.py`).

### Canonical customer sheet columns

`backend/routers/customers.py` defines `_DEFAULT_CUSTOMER_HEADERS` — the authoritative column order used when a new tenant's sheet is empty. Any code that constructs customer rows must follow this order: `고객ID, 한글, 성, 명, 여권, 국적, 성별, 등록증, 번호, 발급일, 만기일, 발급, 만기, 주소, 연, 락, 처, V, 체류자격, 비자종류, 메모, 폴더`.

---

## OCR subsystem

### Engine split

| Document | Engine | Notes |
|---|---|---|
| Passport | **OmniMRZ** (PaddleOCR) | MRZ TD3 extraction; no Tesseract required |
| ARC (외국인등록증) | **Tesseract** | `kor+eng+ocrb` multi-config pipeline |

### Tesseract setup (`backend/routers/scan.py` — `_ensure_tesseract()`)

Called at the top of every OCR request (ARC uses it; passport does not, but the call is harmless). On Linux it:
1. Probes candidate paths (`/usr/share/tesseract-ocr/5/tessdata`, etc.) to find the system tessdata dir containing `eng`/`kor`/`osd`.
2. Copies `/app/tessdata/ocrb.traineddata` (bundled in repo) into that system dir if not already present.
3. Sets `TESSDATA_PREFIX` to the **system** tessdata dir so all four langs are visible together.

On Windows it uses `C:\Program Files\Tesseract-OCR\tessdata` and copies `ocrb.traineddata` there the same way.

Do **not** point `TESSDATA_PREFIX` at the project's `/app/tessdata/` directory — it only contains `ocrb` and will hide `eng`/`kor` from tesseract.

### OmniMRZ setup (`backend/services/ocr_service.py`)

`_get_omni_mrz()` is a thread-safe singleton (guarded by `_omni_mrz_lock`). A daemon thread `_prewarm_omni_mrz` fires **at module import time** (i.e. uvicorn worker startup) to load PaddleOCR models before the first real request arrives. Without prewarm, model loading (~20-40 s on Render) eats the entire request timeout budget.

**OmniMRZ PyPI wheel is broken** (`omnimrz-0.2.1` ships only a `py.typed` marker — no source files). `Dockerfile.backend` installs it from source with a patched `pyproject.toml`:
```dockerfile
RUN git clone --depth=1 https://github.com/AzwadFawadHasan/OmniMRZ.git /tmp/OmniMRZ && \
    sed -i 's|include = \["omnimrz/py.typed"\]|include = ["omnimrz*"]|' /tmp/OmniMRZ/pyproject.toml && \
    pip install --no-cache-dir /tmp/OmniMRZ && \
    rm -rf /tmp/OmniMRZ
```
Do **not** add `omnimrz` to `requirements.txt` — it is installed directly in the Dockerfile step above.

### OCR concurrency guard (`backend/routers/scan.py`)

`asyncio.wait_for` + `asyncio.to_thread` cancels the coroutine on timeout but does **not** kill the background thread. A timed-out PaddleOCR or Tesseract thread keeps consuming RAM. To prevent overlapping OCR jobs from OOM-killing the Render worker:

```python
# Module-level — lazy-init inside first async context
_OCR_SEMAPHORE: asyncio.Semaphore | None = None

def _ocr_sem() -> asyncio.Semaphore:
    global _OCR_SEMAPHORE
    if _OCR_SEMAPHORE is None:
        _OCR_SEMAPHORE = asyncio.Semaphore(1)
    return _OCR_SEMAPHORE
```

Both `/passport` and `/arc` check `sem.locked()` before acquiring — if another OCR job is running they return `{"debug": "passport-busy"|"arc-busy", ...}` immediately rather than queueing.

### OCR service functions (`backend/services/ocr_service.py`)

```python
parse_passport(img: PIL.Image, fast: bool = False) -> dict
# Engine: Tesseract+ocrb (primary, ~1-3s) → OmniMRZ/PaddleOCR (secondary, only if already loaded).
# Tesseract path uses _passport_tess_mrz() which calls existing _iter_mrz_candidate_bands /
# _prep_mrz / _tess_string / find_best_mrz_pair_from_text / _parse_mrz_pair pipeline.
# OmniMRZ skipped entirely if _omni_mrz_instance is None (non-blocking check).
# Returns: {성, 명, 성별, 국가, 국적, 여권, 발급, 만기, 생년월일}
# 발급 is always "" — MRZ TD3 does not encode issue date.
# _raw_L1/_raw_L2 are always None.
# Returns {"_no_mrz": True, "_parse_error": "..."} on failure.

parse_arc(img: PIL.Image, fast: bool = False) -> dict
# Engine: Tesseract (kor+eng+ocrb multi-config).
# Returns: {한글, 등록증, 번호, 발급일, 만기일, 주소}
# fast=True caps OCR attempts to 2 combinations (used by the /arc endpoint).
```

### Scan router endpoints

- `POST /api/scan/passport` — OmniMRZ passport parse → returns parsed fields (60s timeout, temporary)
- `POST /api/scan/arc` — Tesseract ARC parse → returns parsed fields (30s timeout)
- `POST /api/scan/register` — upsert customer from OCR result; matches by `여권` or `등록증+번호`; returns `{status: "created"|"updated", 고객ID, message}`

The frontend scan page (`frontend/app/(main)/scan/page.tsx`) reads OCR fields from both the normal response shape (`res.data.성`) and the debug shape (`res.data.result.성`) via:
```ts
const d = (res.data as any).result ?? res.data;
```

`isDebugError` on the passport side checks `d._no_mrz` (not `d.debug`) because `d` is the inner result dict where `debug` is undefined.

---

## Key Coding Patterns

### Task partial updates (backend)

All `PUT /tasks/{type}/{id}` endpoints must use **read-merge-write**, never full overwrite:

```python
changes = {k: ("" if v is None else str(v))
           for k, v in task.model_dump(exclude_unset=True).items()}
changes["id"] = task_id
existing = next((r for r in read_sheet(...) if r.get("id") == task_id), {})
merged = {**existing, **changes}
upsert_sheet(..., [merged], id_field="id")
```

`model_dump(exclude_unset=True)` returns only fields explicitly present in the request JSON — Pydantic defaults for unset fields are excluded. This prevents a single-field edit from zeroing other columns.

### Active task row — unified controlled state (dashboard)

`ActiveTaskRow` in `dashboard/page.tsx` uses **controlled inputs** (`value` + `onChange`) for every field, not `defaultValue`. All 13+ fields are individual `useState` variables. A single `dirty` boolean tracks whether any field has changed.

- `useEffect` keyed on `task.id` + every field value syncs all state from server on refetch and resets `dirty = false`.
- Every `onChange` / checkbox toggle calls `mark()` which sets `dirty = true`.
- A **"저장" button renders only when `dirty === true`** (hidden when clean). It sends all fields in a single `PUT` and then sets `dirty = false`.
- Stage fields (`reception`, `processing`, `storage`) are ISO timestamp strings. Checkbox toggles update local state only; no API call fires until "저장" is clicked.
- The trailing underscore on `localStorage_` avoids shadowing the browser global `localStorage`.

```tsx
// Only render save button when there are unsaved changes:
{dirty && <button onClick={handleSave}>저장</button>}
```

### Dropdown positioning inside overflow containers

When a dropdown or autocomplete lives inside a parent with `overflow: auto` (or `overflow-x: auto`, which also forces `overflow-y: auto`), `position: absolute` will be clipped. Use `position: fixed` with `getBoundingClientRect`:

```tsx
const [dropdownPos, setDropdownPos] = useState<{ top: number; left: number; width: number } | null>(null);

const updateDropdownPos = () => {
  if (inputRef.current) {
    const r = inputRef.current.getBoundingClientRect();
    setDropdownPos({ top: r.bottom + 2, left: r.left, width: Math.max(r.width, 240) });
  }
};
// Call from onFocus and onChange on the input.
// Render dropdown with position:"fixed", top/left/width from state, zIndex: 9999.
```

`position: fixed` is NOT affected by ancestor `overflow` settings (only by ancestor `transform`/`filter`).

### Flex drawer / panel layout

Drawers that fill the viewport height (`position: fixed; top:0; bottom:0`) must set `minHeight: 0` on any `flex: 1` body child, otherwise the child won't shrink below its content height and `overflow: hidden` on the outer container will clip it. All non-scrolling sections (header, D-Day bar, footer) need `flexShrink: 0`.

### CSS class vs inline style precedence

`flex: 1` in a CSS class overrides an inline `width` style because flex-grow dominates in flex containers. When you need a fixed-width element inside a flex row, use inline `flexShrink: 0` instead of a CSS class that sets `flex: 1`. Grid cells need `minWidth: 0` to prevent overflow past their `1fr` allocation (grid items default to `min-width: auto`).

### Internal navigation — never `target="_blank"` for same-app routes

Using `<a href="/route" target="_blank">` for routes inside the Next.js app opens a new browser tab that must re-initialise webpack chunks from `.next/`. If the `.next/` cache has stale or mismatched bundles this causes `TypeError: __webpack_modules__[moduleId] is not a function`. Always use `router.push('/route')` for same-app navigation. Reserve `target="_blank"` for external URLs only.

After clearing or modifying `.next/` (or after dependency changes), delete the folder and run `npm run build` before restarting the dev server.

### Quick-doc PDF pipeline

```
① GET /api/quick-doc/tree              — category/minwon/kind/detail selection tree
② POST /api/quick-doc/required-docs    — returns main_docs + agent_docs for the selection
③ POST /api/quick-doc/generate-full    — fills PDF fields via build_field_values(), merges PDFs, applies seals
```

`generate_full` accepts an optional `direct_overrides: dict` (PDF widget name → value). Overrides are applied **after** `build_field_values()` so they always win. Use this for post-generation field edits without changing customer data.

### Quick-doc checkbox preservation

`docsUserModified` (a `useRef`) tracks whether the user has manually changed checkboxes. Two separate `useEffect`s:
- **Work-type change** (`category/minwon/kind/detail` deps): always resets checkboxes and clears `docsUserModified`.
- **Applicant change** (`applicant.customer?.reg_no` dep): re-fetches required docs but only resets checkboxes if `docsUserModified.current === false`.

---

## Docker build architecture

```
Dockerfile.frontend (multi-stage):
  deps    — npm install only
  builder — receives ARG API_URL → ENV API_URL → npm run build (rewrites baked here)
  runner  — copies .next/ from builder, runs npm start

Dockerfile.backend:
  python:3.11-slim base
  apt: tesseract-ocr + kor pack, libglib2.0, libsm6, libgl1, libgomp1, poppler-utils, git
  pip install -r requirements.txt          (no omnimrz here — see below)
  git clone OmniMRZ + patch pyproject.toml + pip install from source
  smoke test: python -c "from omnimrz import OmniMRZ; print('smoke test passed')"
  runs: uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

`git` is required in the image because OmniMRZ must be cloned and installed from source (the PyPI wheel is empty). The smoke test fails the build immediately if the install produces a broken package, catching the issue before deployment.

`docker-compose.yml` passes `build.args.API_URL: http://backend:8000` to the builder stage AND sets it in `environment:` for the runner (belt-and-suspenders). The critical one is the build arg — the runtime env has no effect on already-built rewrites.

---

## Migration status

These items are complete — do not redo:
- `backend/services/ocr_service.py` — OCR decoupled from Streamlit
- `core/customer_service.py` — Streamlit-safe
- `backend/routers/manual.py` + `frontend/app/(main)/manual/` — GPT manual search
- `backend/routers/quick_doc.py` + `frontend/app/(main)/quick-doc/quick-poa/` — Quick POA (renamed "원클릭 작성")
- Tenant workspace provisioning hardened (partial success, folder reuse, stage-by-stage result)
- Task update endpoints (active + planned) — partial update only, no full-row overwrite
- Quick-doc: checkbox state preserved on applicant change; accommodation warning gated on doc selection; edit-before-download via `direct_overrides`
- UX/workflow patch (8 items):
  - Search page input no longer capped at 520px (inline styles, bypasses `.hw-search-bar` CSS class)
  - Customer table uses `table-layout: fixed` + `<colgroup>` for predictable column density
  - Customer drawer: `minHeight: 0` on body, `flexShrink: 0` on D-Day banner — no vertical clipping; `overflow:"hidden"` removed from outer drawer div; grid cells have `minWidth:0`
  - Planned-task save button always visible (gray = clean, orange = dirty); explicit save only
  - Active-task rows: all fields use controlled state + single row-level "저장" button; button hidden when clean, visible only when dirty
  - Daily page customer name autocomplete uses `position: fixed` dropdown to escape overflow clipping
  - Daily page new-customer modal appends to `위임내역` on save; `POST /api/customers/{id}/delegation-append`
  - OCR button in new-customer modal uses `router.push('/scan')` — no broken `target="_blank"` new window
- Docker inter-container routing fixed: `API_URL` build arg in `Dockerfile.frontend` + `docker-compose.yml`; `api.ts` now uses hardcoded `baseURL: ""`
- Route auth guard: `frontend/middleware.ts` (cookie-based Edge guard) + `kid_auth` cookie lifecycle in `auth.ts`
- Tesseract tessdata fix: Linux `_ensure_tesseract()` now uses system tessdata dir and copies `ocrb.traineddata` there, instead of pointing `TESSDATA_PREFIX` at the project-only dir (which hid `eng`/`kor`)
- Passport OCR migrated from Tesseract MRZ to **OmniMRZ** (PaddleOCR-based); `Dockerfile.backend` installs OmniMRZ from GitHub source (PyPI wheel is broken)
- OCR concurrency guard: `asyncio.Semaphore(1)` in `scan.py` serialises passport+ARC to prevent overlapping threads from OOM-killing the Render worker
- OmniMRZ prewarm thread **disabled** — was causing OOM on Render free tier (512MB) by downloading 4 PaddleOCR models at startup
- Passport OCR redesigned: Tesseract+ocrb only via `_passport_tess_mrz()` (~1-3s, no model loading, 90% accuracy on 30-sample benchmark); OmniMRZ/PaddleOCR never called at runtime
- `_ensure_tesseract()` moved inside try block in both routes; `asyncio.CancelledError` caught with TimeoutError (no re-raise) to prevent 500 on Render gateway timeout
- PDF DPI raised 200→250 for better MRZ readability in scanned PDFs

## In-progress / temporary debug state

**`backend/routers/scan.py` OCR routes are currently in debug mode** (as of 2026-03-29). Both `/api/scan/passport` and `/api/scan/arc` run the full pipeline but return a debug-wrapped response:

```json
{"debug": "passport-parse-done", "result": {...parsed fields...}, "raw_L1": null, "raw_L2": null}
```

The frontend scan page already handles this via `(res.data as any).result ?? res.data`, so the form still populates correctly. When OCR tuning is complete, remove the `debug` wrapper and restore the routes to return parsed fields directly. `_raw_L1`/`_raw_L2` are always `null` for passport (OmniMRZ does not expose raw MRZ lines) and can be removed from the return dict at the same time.

**Passport timeout is 25s** — Tesseract primary path completes in 1-3s (avg 1.4s on 30-sample benchmark), so 25s is safe even for worst-case scans.

**ARC OCR quality** — route is alive and returns structured JSON, but field accuracy needs improvement: Korean name extraction and address parsing produce garbled results on some ARC back images. This is the next active work item.
