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
- `/customer-popup`, `/customer-copy-popup`, `/sign/*`, `/sign-test` = **standalone popup routes** (no sidebar/topbar)

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
- `g*` = 법정대리인 (e.g. `gyin`, `gysign`) — only when `is_minor=True`
- `p*` = 합산자 — 체류변경 F5 only (`need_aggregator()` returns True only for (체류, 변경, F, 5))
- `a*` = 행정사 (e.g. `ayin`, `aysign`, `agent_tel`)
- `yin`/`ysign` = 신청인 도장/서명
- `rela` = 신원보증인 관계

`FullDocGenRequest` supports:
- `accommodation_provider` (dict from 숙소제공자연결 tab) and `guarantor_connection` (dict from 신원보증인연결 tab) — passed in addition to `*_id` fields and override empty DB values.
- `direct_overrides: dict` — applied last over `build_field_values()` output; used by the "편집 후 재다운로드" panel to patch individual PDF widget values without re-fetching Sheets data.
- `document_date: str | None` — if empty string `""`, date fields are blank; if `None` (old callers), backend falls back to today; if non-empty string, parses and uses.

**Sign/seal normalization in `generate_full()`:** Only one rule: if both `sign_*` and `seal_*` are True for the same role, `seal_*` is forced False (sign wins). **Both False is intentional** — it means the user explicitly selected "없음". The backend never auto-enables a signature or seal when both are False. Guardian and aggregator have no normalization.

**원클릭 작성** (`/quick-poa`): `_ALL_OUTPUTS` / `_IMPLEMENTED_OUTPUTS` / `_OUTPUT_ORDER` constants control which one-click types are available. Currently implemented: 위임장, 하이코리아, 소시넷(등록증), 소시넷(여권). `건강보험(세대합가)` and `건강보험(피부양자)` are in `_ALL_OUTPUTS` but **not** `_IMPLEMENTED_OUTPUTS` — PDF templates are missing.

### Signature system (`backend/routers/signature.py`, `backend/services/signature_service.py`)

Three separate Sheets tabs:
- `"행정사서명"` in `SHEET_KEY` — agent signature, key: `tenant_id`. **Saved immediately on submit**.
- `"고객서명"` in `customer_sheet_key` — customer signature, key: `고객ID`. Also saved immediately.
- `"서명임시저장"` in `SHEET_KEY` — temp slots 1–3, key: `(slot, tenant_id)`.

**Token architecture:** Customer tokens are stateless HMAC; agent tokens use an in-memory `_pending` dict.

`has_customer_signature()` raises `SignatureLookupError` on Sheets API failure (not silent False). The exists endpoint returns HTTP 503 on lookup failure — frontend must not interpret 503 as "no signature".

**Agent signature cache:** `signature_service.py` has a 60-second TTL cache (`_agent_sig_cache`) for `get_agent_signature()`. Cache is invalidated by `save_agent_signature()`. The `/api/signature/agent` route returns HTTP 503 (not `{"data": null}`) on Sheets failure so the frontend can distinguish real absence from errors.

### Sheets read cache (`backend/services/tenant_service.py`)

`read_sheet()` uses a two-level locking strategy to prevent thundering-herd 429s:
1. **Global lock** for fast cache-hit path.
2. **Per-`(tenant_id, sheet_name)` lock** for slow path — double-checked locking.

`_READ_CACHE_TTL = 120` seconds. Writes invalidate the relevant key immediately via `_INVALIDATION_TOKENS`.

**Relationship sheet read cache** (`backend/routers/customers.py`): `숙소제공자연결` and `신원보증인연결` worksheets have their own 60-second TTL cache (`_RELATIONSHIP_READ_TTL`) in `_read_accommodation_record()` / `_read_guarantor_record()`. Cache is invalidated on save/delete. Uses a per-key lock (`_get_relationship_lock()`) to prevent thundering-herd 429s on concurrent reads.

### 일일결산 → 진행업무 dedup (`backend/routers/daily.py`)

`_apply_daily_to_active()` creates an active task when a 일일결산 entry is saved. To prevent duplicate rows from gspread retry races:
- Each active task stores `source_daily_id = rec["id"]` (the daily entry's UUID).
- Active task `id` is **deterministic**: `"daily-" + source_daily_id` (not random UUID). This ensures upsert on retry updates rather than appends.
- After upsert, `_dedupe_active_rows_by_source()` reads the sheet and deletes extras by **row index** (safe even when duplicate IDs share the same UUID).
- `_DedupeResult.matched_count == 0` after a non-quota upsert exception → re-raise the error (write genuinely failed).

### 진행업무 money draft pattern (frontend)

Money fields (`transfer`, `cash`, `card`, `stamp`, `receivable`, `planned_expense`) on active task cards are **draft-only** — changes don't save immediately.

- **State**: `moneyDrafts: Record<string, MoneyDraft>` and `moneyDirtyIds: Set<string>` live in `dashboard/page.tsx`, passed down to `TaskCardView`.
- **Display**: `moneyDraft[field] ?? safeInt(task[field])` — draft takes priority over server value.
- **0 button**: sets draft to 0, does NOT call backend. Card shows "저장 대기" badge.
- **선택처리**: calls `PATCH /api/tasks/active/batch-money` with only changed fields for dirty rows. Payload: `[{id, changes: {field: "value"}}]`. Backend returns HTTP 409 if any ID has duplicates or is not found (fail-fast before any write).
- `doGenerate` in `QuickDocPanel.tsx` must include `customDate` and `includeDate` in its `useCallback` dep array (they were previously missing and caused stale closures).

### QuickDocPanel preload gating (`frontend/components/QuickDocPanel.tsx`)

Uses explicit status types to prevent early generation with stale empty roles:

```ts
type LinkStatus = "unknown" | "loading" | "none" | "linked" | "error";
type AgentSignatureStatus = "unknown" | "loading" | "exists" | "none" | "error";
```

**Readiness rules:**
- `accommodationReady = status === "none" || status === "error" || (status === "linked" && roleIsSet(accommodation))`
- `error` status does NOT permanently block generation — it passes `accommodationReady` and is handled by the existing `confirmMissing` dialog flow.
- `unknown` / `loading` always block the PDF button.
- Agent signature "서명" radio is disabled while `agentSignatureStatus === "unknown" || "loading"` — prevents falsely showing "없음" during initial load.

### Dual popup (`frontend/app/(main)/customers/page.tsx`)

Three helper panel buttons (체류만료조회 열기, 하이코리아 ID찾기 열기, 소시넷 ID찾기 열기) use `openDualPopup()` inside `CustomerDrawer` to open two windows simultaneously:

- **Left**: external site (하이코리아/소시넷), larger (≈68% of screen width).
- **Right**: `/customer-copy-popup?customerId=...&mode=...&nonce=...` (≈32% of screen width).

Data passing uses a per-popup localStorage key: `customer_copy_popup_data_${id}_${mode}_${nonce}`. The popup validates `customerId`, `mode`, and timestamp (max 2 min) before displaying, then **immediately removes the key** from localStorage. A `useRef` guard prevents double-load in React Strict Mode. If either window fails to open, both are closed and the storage key is removed.

Left window close → right auto-closes (500ms interval watcher). Right window close → left stays open.

### Frontend key patterns

**Auth:** `frontend/lib/auth.ts` — `getUser`, `setUser`, `clearUser`, `isLoggedIn`. Stores `user_info` (JSON) and `access_token` (bare token) as separate localStorage keys. `api.ts` reads `access_token` for `Authorization` header.

**401 handling:** `api.ts` response interceptor clears localStorage + the `kid_auth` cookie, then redirects to `/login`. Sets `sessionStorage["auth_expired"] = "1"` so the login page shows "장시간 미이용으로 로그아웃". Use `X-Skip-Auth-Redirect: 1` header on requests that must NOT trigger auto-redirect on 401.

**Topbar** (`frontend/components/layout/topbar.tsx`): No integrated global search (removed). Shows direct shortcut buttons (하이코리아, 비자포털, 사회통합, 이민재단) that open `window.open(_blank)`. Order: 알람 → 임시서명 × 3 → shortcuts → 사무소명 → 로그아웃.

**CustomerDrawer overlay layout:** `docOverlayOpen` / `quickPoaOverlayOpen` panels use `position: fixed; top: 120` (not 56) so the customer search toolbar (at ~80–116px) remains visible and clickable. The toolbar itself has `marginTop: -10` to reduce visual gap from the 24px main padding. The overlay's `onFocus` on the search input and row `onClick` both close open overlays.

**QuickDocPanel preload dedup:** The `[initId]` preload effect uses a per-run `signatureStatusCache: Map<string, Promise<SignatureStatus>>` so multiple roles sharing the same `customer_id` send only one `/api/signature/customer/{id}/exists` request.

**Customer card useEffect deps:** All Google Sheets API calls in `CustomerDrawer` use `customerId` string (not the full `customer` object) as their dependency. This prevents unnecessary re-fetches when the object reference changes after save.

**Worksheet header cache:** `backend/routers/customers.py` maintains `_VALIDATED_CUSTOMER_WORKSHEETS: set` (process-level). Only validates headers on first access per `(sheet_key, worksheet_name)` pair.

**429 handling:** `_raise_if_quota(e)` in `customers.py` converts `"429"` / `"Quota exceeded"` gspread errors to HTTP 503.

**`FullCalendar` eventContent:** always wrap in `useCallback` to prevent React error #185 (max update depth).

### TaskCardView D+ display (`frontend/components/tasks/TaskCardView.tsx`)

`computeCardDDay()` determines the D+ badge base date by priority: `storage > processing > reception > task.date`. D+0 is explicitly rendered (not hidden). Missing base date shows "기준일 없음". The labeled base date (e.g. "보관 2026-04-28") replaces the unlabeled `task.date` display in the card's second row, eliminating the confusing mismatch between the displayed date and the D+ count.

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
