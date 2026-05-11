# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project identity

**K.ID SaaS** — internal immigration office (출입국) management platform for Hanwory Administrative Office.  
Architecture: **Next.js (frontend) + FastAPI (backend)**. All business data lives in **Google Sheets / Google Drive**. Public domain: https://www.hanwory.com

`pages/` and `app.py` are **legacy Streamlit reference files** — never import them at runtime. `pages/page_scan.py` is a donor/reference for OCR logic only; the active runtime is `backend/services/ocr_service.py`.

---

## Dev commands

**Backend** (from repo root, activate `.venv` first):
```bash
uvicorn backend.main:app --reload --port 8000
```
Swagger: `http://localhost:8000/docs`

**Frontend** (from `frontend/`):
```bash
npm run dev      # port 3000
npm run build
npx tsc --noEmit  # type-check only (no jest/vitest — no automated tests)
```

**Python compile check:**
```bash
python -m compileall backend -q
```

**Docker (로컬 개발, 두 컨테이너):**
```bash
docker compose build --no-cache frontend   # next.config.js 변경 후 필요
docker compose up -d
```

**Docker (Render 단일 컨테이너):** `Dockerfile.combined` — FastAPI(internal :8000) + Next.js(external :3000). `API_URL=http://localhost:8000` must be baked into image.

**Required env:**
- Root `.env`: `JWT_SECRET_KEY`, `HANWOORY_ENV` (`local`/`server`), `ALLOWED_ORIGINS`
- Google service account key at `config.KEY_PATH`
- Tesseract must be installed separately for `backend/routers/scan.py`

---

## Architecture

```
[Next.js :3000] ──/api/*──► [FastAPI :8000] ──► [Google Sheets / Drive]
                  (proxy via next.config.js)
```

`next.config.js` proxies all `/api/*` to FastAPI. Frontend calls only relative `/api/...` URLs via `frontend/lib/api.ts` (`baseURL: ""` — never add `NEXT_PUBLIC_API_URL`).

### Routing split

- `/`, `/board/*`, `/documents`, `/siheung-immigration-agent`, `/jeongwang-immigration-agent` = **public** (no auth)
- `/login` = login page
- `/(main)/*` = **authenticated internal app**

`frontend/middleware.ts` (Edge) enforces auth via `kid_auth` cookie. **Adding a new public page:** add its pathname to the `if` block in `middleware()` AND to `sitemap.ts` static entries.

### Backend layout

```
backend/
  main.py           — FastAPI app, registers all routers
  auth.py           — JWT (8h expiry); get_current_user / require_admin deps
  models.py         — All Pydantic models
  routers/          — auth, tasks, customers, daily, memos, events, board,
                      scan, admin, search, reference, quick_doc, guidelines, marketing, signature
  services/
    tenant_service.py   — Core Google Sheets abstraction (TTL-cached, thread-safe)
    accounts_service.py — Accounts sheet CRUD; defines ACCOUNTS_SCHEMA (16 cols)
    signature_service.py — Customer/agent signature storage (Google Sheets tabs)
    ocr_service.py      — Passport OCR (Tesseract+ocrb); ARC OCR
    cache_service.py    — In-memory TTL cache; use cache_get/cache_set/cache_invalidate
  data/
    immigration_guidelines_db_v2.json — 출입국 실무지침 DB (369 업무항목)
config.py           — Single source of truth for all Drive/Sheets IDs and tab names
```

### Multi-tenant data model

Every user has `tenant_id` (= `login_id` by default) in their JWT. The **Accounts sheet** (tab `"Accounts"` in `SHEET_KEY`) maps each tenant to:

| Column | Purpose |
|---|---|
| `customer_sheet_key` | Customer workbook: 고객 데이터, 진행업무, 예정업무, 완료업무, 일일결산, 잔액, 일정, 메모, **숙소제공자연결**, **신원보증인연결**, **고객서명** tabs |
| `work_sheet_key` | Work workbook: 업무참고, 업무정리 tabs |

**`tenant_service._resolve_sheet_key()`** routes each tab to the correct workbook. **Never fall back to admin sheet keys for non-default tenants** — missing key must raise `ValueError`. Exception: `DEFAULT_TENANT_ID` (`"hanwoory"`) falls back to `SHEET_KEY` for backwards compatibility.

Tabs that always route to admin `SHEET_KEY` (shared): `"게시판"`, `"게시판댓글"`, `"홈페이지게시물"`, `"행정사서명"`, `"서명임시저장"`.

### Key resource IDs (all in `config.py`)

| Constant | Purpose |
|---|---|
| `SHEET_KEY` | Admin master spreadsheet (Accounts + shared tabs) |
| `CUSTOMER_DATA_TEMPLATE_ID` | Template copied for new tenant customer sheet |
| `WORK_REFERENCE_TEMPLATE_ID` | Template copied for new tenant work sheet |

**Never use admin sheet IDs as template IDs.**

### PDF document generation (`backend/routers/quick_doc.py`)

`build_field_values()` constructs a flat dict of PDF field names → values, then `fill_and_append_pdf()` writes them via PyMuPDF. Key field name prefixes:
- `b*` = 신원보증인 (e.g. `bkoreanname`, `bsurname`, `badress`, `bphone1/2/3`, `byin`, `bysign`)
- `h*` = 숙소제공자 (e.g. `hkoreanname`, `hsurname`)
- `a*` = 행정사 (e.g. `ayin`, `aysign`, `agent_tel`)
- `yin`/`ysign` = 신청인 도장/서명
- `rela` = 신원보증인 관계

`FullDocGenRequest` supports `accommodation_provider` (dict from 숙소제공자연결 tab) and `guarantor_connection` (dict from 신원보증인연결 tab) — these are passed in addition to `*_id` fields and override empty DB values.

**원클릭 작성** (`/quick-poa`): `_ALL_OUTPUTS` / `_IMPLEMENTED_OUTPUTS` / `_OUTPUT_ORDER` constants control which one-click types are available (위임장, 하이코리아, 소시넷(등록증), 소시넷(여권)).

### Signature system (`backend/routers/signature.py`, `backend/services/signature_service.py`)

Three separate Sheets tabs:
- `"행정사서명"` in `SHEET_KEY` — agent signature, key: `tenant_id`. **Saved immediately on submit** (not waiting for `/save/{token}`).
- `"고객서명"` in `customer_sheet_key` — customer signature, key: `고객ID`. Also saved immediately on submit.
- `"서명임시저장"` in `SHEET_KEY` — temp slots 1–3, key: `(slot, tenant_id)`.

`has_customer_signature()` raises `SignatureLookupError` on Sheets API failure (not silent False). The exists endpoint returns HTTP 503 on lookup failure — frontend must not interpret 503 as "no signature".

### Frontend key patterns

**Auth:** `frontend/lib/auth.ts` — `getUser`, `setUser`, `clearUser`, `isLoggedIn`. Stores `user_info` (JSON) and `access_token` (bare token) as separate localStorage keys. `api.ts` reads `access_token` for `Authorization` header.

**Customer card useEffect deps:** All Google Sheets API calls in `CustomerDrawer` use `customerId` string (not the full `customer` object) as their dependency. This prevents unnecessary re-fetches when the object reference changes after save.

**Worksheet header cache:** `backend/routers/customers.py` maintains `_VALIDATED_CUSTOMER_WORKSHEETS: set` (process-level). Only validates headers on first access per `(sheet_key, worksheet_name)` pair. Catches only `gspread.exceptions.WorksheetNotFound` — not `Exception` — to prevent re-creating existing sheets.

**429 handling:** `_raise_if_quota(e)` in `customers.py` converts `"429"` / `"Quota exceeded"` gspread errors to HTTP 503 with a user-readable message.

**overlay layout:** `docOverlayOpen` / `quickPoaOverlayOpen` panels use `position: fixed; top: 56; left: var(--hw-main-left)` — the CSS variable is set by `(main)/layout.tsx` and tracks the sidebar width automatically.

**`FullCalendar` eventContent:** always wrap in `useCallback` to prevent React error #185 (max update depth).

---

## Absolute rules

- Do not refactor stable code unless explicitly requested.
- Do not change UI layout unless the task requires it.
- Prefer minimal localized patches.
- Never overwrite entire Google Sheets data. Persistence must be ID-based upsert.
- Deletion requires explicit confirmation.
- Do not auto-save user edits.
- Do not mix public homepage routes with authenticated internal routes.
- Do not fall back to `SHEET_KEY` or `CUSTOMER_DATA_TEMPLATE_ID` for non-default tenant data storage.
- `customer_sheet_key` missing → raise `ValueError`, not silent fallback.
- Do not convert this project back to Streamlit.
- Do not say "fixed" without showing changed files.
- Do not silently create a new architecture or remove working logic.

## Work style

1. Inspect relevant files before editing.
2. Explain the root cause.
3. Propose a minimal patch plan.
4. Modify only necessary files.
5. Show changed files and provide verification commands.

## Important docs

Read these only when relevant:
- `docs/AI_HANDOVER.md`
- `docs/ARCHITECTURE.md`
- `docs/DEV_COMMANDS.md`
- `docs/BUSINESS_RULES.md`
- `docs/KNOWN_BUGS.md`
- `docs/OCR_CONTEXT.md`
- `docs/HOMEPAGE_CONTEXT.md`
