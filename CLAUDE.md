# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

This is **K.ID SaaS** — an immigration office (출입국) operations platform being rebuilt from a legacy Streamlit app into a **Next.js (frontend) + FastAPI (backend)** architecture. The original Streamlit files in `pages/` and `app.py` are **reference specifications only** — they are not running in the current architecture and must not be imported or executed at runtime.

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
- Google service account key at the path in `config.KEY_PATH` (Windows: `C:\Users\66885\Documents\...hanwoory-9eaa1a4c54d7.json`, Linux: `/etc/secrets/hanwoory-9eaa1a4c54d7.json`)

**Tesseract OCR** must be installed separately for `backend/routers/scan.py` to work.

---

## Architecture

```
[Next.js :3000] ──/api/*──► [FastAPI :8000] ──► [Google Sheets / Drive]
                  (proxy via next.config.js)
```

The Next.js `next.config.js` proxies all `/api/*` requests to the FastAPI backend, so the frontend only ever calls relative `/api/...` URLs through `frontend/lib/api.ts`.

### Backend layout

```
backend/
  main.py               — FastAPI app, registers 13 routers
  auth.py               — JWT creation/verification, OAuth2PasswordBearer
  models.py             — All Pydantic request/response models
  routers/              — One file per domain (auth, tasks, customers, daily,
                          memos, events, board, scan, admin, search,
                          reference, quick_doc, manual)
  services/
    tenant_service.py   — Core Google Sheets abstraction (Streamlit-free)
    accounts_service.py — Accounts sheet CRUD + password hashing
    ocr_service.py      — Tesseract OCR, MRZ parsing
config.py               — Single source of truth for all resource IDs
core/
  google_sheets.py      — Legacy Streamlit-era sheet helpers (still used by
                          some routers; imports guarded against Streamlit)
  customer_service.py   — Customer data normalization utilities
```

### Multi-tenant data model

- Every user has a `tenant_id` (usually same as `login_id`) stored in their JWT.
- The **Accounts sheet** (tab `"Accounts"` inside `SHEET_KEY`) maps each tenant to:
  - `folder_id` — Google Drive folder for that office
  - `customer_sheet_key` — tenant's customer data spreadsheet ID
  - `work_sheet_key` — tenant's work summary spreadsheet ID
- `backend/services/tenant_service.py` resolves sheet keys from this map. It caches the mapping for 10 min (`_TENANT_MAP_CACHE`).
- **Do not fall back to admin/master sheet keys for non-default tenants.** A missing key must raise `ValueError` so the admin knows the workspace needs provisioning.

### Tenant workspace provisioning

`POST /api/admin/workspace` in `backend/routers/admin.py`:
1. Creates (or reuses) an office folder under `PARENT_DRIVE_FOLDER_ID`
2. Copies `CUSTOMER_DATA_TEMPLATE_ID` into the folder
3. Copies `WORK_REFERENCE_TEMPLATE_ID` into the folder
4. Writes `folder_id`, `customer_sheet_key`, `work_sheet_key` into Accounts
5. Sets `is_active=TRUE` only when all three are present

Each stage is independent. Partial success is preserved — existing values are never overwritten with empty strings.

### Key resource IDs (all in `config.py`)

| Constant | Purpose |
|---|---|
| `SHEET_KEY` | Admin master spreadsheet — contains the `Accounts` tab |
| `ADMIN_CUSTOMER_SHEET_KEY` | Admin customer data sheet (기준 고객 데이터) |
| `PARENT_DRIVE_FOLDER_ID` | Parent Drive folder for all tenant office folders (`offices/`) |
| `CUSTOMER_DATA_TEMPLATE_ID` | Template copied for new tenant customer sheet |
| `WORK_REFERENCE_TEMPLATE_ID` | Template copied for new tenant work sheet |

**Never use admin sheet IDs as template IDs.** They are separate files.

### Frontend layout

```
frontend/app/
  (auth)/login/         — Login page (no layout wrapper)
  (main)/layout.tsx     — Protected layout: checks isLoggedIn(), renders Sidebar + Topbar
  (main)/dashboard/     — Home
  (main)/customers/     — Customer management
  (main)/tasks/         — Tasks (planned / active / completed)
  (main)/daily/         — Daily settlement
  (main)/monthly/       — Monthly analysis
  (main)/quick-doc/     — Auto document generation
    quick-poa/          — Quick power of attorney sub-page
  (main)/scan/          — OCR passport/ARC scanning
  (main)/reference/     — Reference materials
  (main)/search/        — Global search
  (main)/memos/         — Notes
  (main)/board/         — Board
  (main)/manual/        — Manual search
  (main)/admin/         — Admin: account list + workspace button (admin only)
```

All API calls go through `frontend/lib/api.ts`, which:
- Attaches `Authorization: Bearer <token>` from `localStorage` on every request
- Redirects to `/login` on 401

Auth state helpers are in `frontend/lib/auth.ts` (`getUser`, `setUser`, `clearUser`, `isLoggedIn`).

---

## Critical Constraints

1. **No Streamlit at runtime.** `pages/` files are legacy specs. Never import them from FastAPI routers or services.
2. **No unconditional `import streamlit`** in `core/` modules. Guard with `try/except` or conditional checks.
3. **Google Sheets is the database.** Don't add a relational DB or replace sheet operations.
4. **`config.py` is the single source of truth** for all Drive/Sheets resource IDs. Never hardcode IDs elsewhere.
5. **`is_active=TRUE` only after all three keys** (`folder_id`, `customer_sheet_key`, `work_sheet_key`) are confirmed valid in Accounts.
6. **Tenant data isolation is strict.** `tenant_service.get_customer_sheet_key()` and `get_work_sheet_key()` must not fall back to admin sheets for non-default tenants.

---

## Google Sheets access patterns

- **FastAPI context:** use `backend/services/tenant_service.py` — no `st.session_state`, thread-safe gspread singleton with TTL.
- **Accounts sheet specifically:** use `backend/services/accounts_service._get_ws()` — opens `SHEET_KEY` and auto-creates the `Accounts` tab if missing.
- **Drive file operations (copy, create folder):** use `google.oauth2.service_account.Credentials` + `googleapiclient.discovery.build("drive", "v3", ...)` directly in the router, as in `admin.py`.
- Sheet tab names are constants in `config.py` (e.g. `CUSTOMER_SHEET_NAME = "고객 데이터"`). Always import from config, never hardcode Korean tab names.

---

## Migration status

These items are complete — do not redo:
- `backend/services/ocr_service.py` — OCR decoupled from Streamlit
- `core/customer_service.py` — Streamlit-safe
- `backend/routers/manual.py` + `frontend/app/(main)/manual/` — GPT manual search
- `backend/routers/quick_doc.py` + `frontend/app/(main)/quick-doc/quick-poa/` — Quick POA
- Tenant workspace provisioning hardened (partial success, folder reuse, stage-by-stage result)
