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
- `frontend/.env.local` — `NEXT_PUBLIC_API_URL=http://localhost:8000`
- Google service account key at `config.KEY_PATH` (Windows: `C:\Users\66885\Documents\...\hanwoory-9eaa1a4c54d7.json`, Linux: `/etc/secrets/hanwoory-9eaa1a4c54d7.json`)

**Tesseract OCR** must be installed separately for `backend/routers/scan.py` to work.

---

## Architecture

```
[Next.js :3000] ──/api/*──► [FastAPI :8000] ──► [Google Sheets / Drive]
                  (proxy via next.config.js)
```

`next.config.js` proxies all `/api/*` requests to FastAPI, so the frontend only ever calls relative `/api/...` URLs via `frontend/lib/api.ts`.

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
    ocr_service.py      — Tesseract OCR, MRZ parsing
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

Each stage is independent. Existing values are never overwritten with empty strings (partial success is preserved).

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

All API calls go through `frontend/lib/api.ts`:
- Attaches `Authorization: Bearer <token>` from `localStorage` on every request
- Redirects to `/login` on 401

Auth state helpers are in `frontend/lib/auth.ts` (`getUser`, `setUser`, `clearUser`, `isLoggedIn`).
Frontend utilities are in `frontend/lib/utils.ts` (`safeInt`, `formatNumber`, `today`, `cn`).

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

- **FastAPI context:** use `backend/services/tenant_service.py` — no `st.session_state`, thread-safe gspread singleton with TTL.
- **Accounts sheet specifically:** use `backend/services/accounts_service._get_ws()` — opens `SHEET_KEY` and auto-creates `Accounts` tab if missing.
- **Drive file operations:** use `google.oauth2.service_account.Credentials` + `googleapiclient.discovery.build("drive", "v3", ...)` directly in the router (see `admin.py`).

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

### Frontend inline editing (dashboard)

Dashboard task rows use React **uncontrolled inputs** (`defaultValue`) with `onBlur` guards. Always compare before firing an update:

```tsx
onBlur={(e) => {
  if (e.target.value !== (task.field ?? "")) onUpdate(task.id, "field", e.target.value);
}}
```

For numeric fields, compare against `String(safeInt(task[f]) || "")`.

### Stage checkbox pattern (dashboard active tasks)

Stage fields (`reception`, `processing`, `storage`) are ISO timestamp strings stored in Google Sheets. In `ActiveTaskRow`:

- Local React state (`localReception`, `localProcessing`, `localStorage_`) mirrors the server values on mount/refetch via `useEffect`.
- Checkbox toggles update **local state only** — no API call fires.
- A "저장" button (always visible, orange when `stageDirty`, gray otherwise) triggers a single `PUT` with all three fields at once.
- The trailing underscore on `localStorage_` avoids shadowing the browser global `localStorage`.
- `latestStageTs` returns the most recent non-empty ISO string (lexicographic sort) and is used for D+ day counter display.

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
  - Customer drawer: `minHeight: 0` on body, `flexShrink: 0` on D-Day banner — no vertical clipping
  - Planned-task save button always visible (gray = clean, orange = dirty); explicit save only
  - Active-task stage checkboxes (접수/처리/보관중) use local state + explicit "저장" button — no immediate API call on check
  - Daily page customer name autocomplete uses `position: fixed` dropdown to escape overflow clipping
  - Daily page new-customer modal appends to `위임내역` on save; `POST /api/customers/{id}/delegation-append`
  - OCR button in new-customer modal uses `router.push('/scan')` — no broken `target="_blank"` new window
