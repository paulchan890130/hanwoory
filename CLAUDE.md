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

**Docker — two options:**

*두 컨테이너 (로컬 개발용):*
```bash
docker compose build --no-cache frontend   # next.config.js 변경 후 필요
docker compose up -d
```

`docker-compose.yml`에 Google 서비스 계정 키 마운트가 반드시 필요 (없으면 Google Sheets 연결 불가 → 로그인 시 "계정이 존재하지 않습니다"):
```yaml
environment:
  GOOGLE_APPLICATION_CREDENTIALS: /etc/secrets/hanwoory-9eaa1a4c54d7.json
volumes:
  - "C:/Users/66885/Documents/.../hanwoory-9eaa1a4c54d7.json:/etc/secrets/hanwoory-9eaa1a4c54d7.json:ro"
```

*단일 컨테이너 (Render 배포용):*
```bash
# 빌드
docker build -f Dockerfile.combined -t kid-combined .

# 실행 (Google 서비스 계정 키 마운트 필요)
docker run -p 3000:3000 \
  -e JWT_SECRET_KEY=... -e HANWOORY_ENV=server \
  -e GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/hanwoory-9eaa1a4c54d7.json \
  -v "/path/to/hanwoory-9eaa1a4c54d7.json:/etc/secrets/hanwoory-9eaa1a4c54d7.json:ro" \
  kid-combined
```

`Dockerfile.combined`: FastAPI(`localhost:8000`, 내부전용) + Next.js(`0.0.0.0:3000`, 외부노출) 동시 실행. `API_URL=http://localhost:8000`이 baked-in되므로 Render에서 포트 3000 단일 서비스로 운용 가능.

`next.config.js`의 `API_URL`은 `process.env.API_URL`을 런타임에 읽으므로 `ENV API_URL=http://localhost:8000`을 이미지에 포함시켜야 함 (빌드 arg만으로는 부족).

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
  main.py               — FastAPI app, registers 15 routers
  auth.py               — JWT creation/verification (8h expiry); get_current_user / require_admin deps
  models.py             — All Pydantic request/response models
  routers/              — auth, tasks, customers, daily, memos, events, board,
                          scan, scan_workspace, admin, search, reference, quick_doc, manual,
                          guidelines
  services/
    tenant_service.py   — Core Google Sheets abstraction (thread-safe, TTL-cached gspread)
    accounts_service.py — Accounts sheet CRUD + password hashing; defines ACCOUNTS_SCHEMA (16 cols)
    ocr_service.py      — Passport OCR (Tesseract+ocrb); ARC OCR (geometry-first orientation)
    roi_ocr_service.py  — ROI-crop OCR for scan workspace; imports helpers from ocr_service
    addr_service.py     — Address correction using national road-name index
    cache_service.py    — In-memory TTL cache (tenant-safe, thread-safe); use cache_get/cache_set/cache_invalidate
  data/
    addr_index.json            — Compact road/dong name index (~3MB, 256 regions, 172K roads)
    immigration_guidelines_db_v2.json — 출입국 실무지침 DB (369 업무항목)
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

**Tabs that route to admin `SHEET_KEY` for all tenants (shared global data):**
`"게시판"`, `"게시판댓글"` — board/notice system is intentionally shared across all tenants. `core/google_sheets.get_worksheet()` falls through to `sheet_key = SHEET_KEY` for any tab not in the customer or work workbook sets.

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
| `SHEET_KEY` | Admin master spreadsheet (contains Accounts tab + shared board tabs) |
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
  (main)/dashboard/     — Active tasks, planned tasks, calendar, expiry alerts, notice popup
  (main)/customers/     — Customer management
  (main)/tasks/         — Tasks (planned / active / completed)
  (main)/daily/         — Daily settlement
  (main)/monthly/       — Monthly analysis
  (main)/quick-doc/     — Auto document generation (PDF); quick-poa/ sub-page
  (main)/scan/          — OCR passport/ARC scanning
  (main)/reference/     — Reference materials
  (main)/search/        — Global search
  (main)/memos/         — Notes
  (main)/board/         — Board + notice management
  (main)/manual/        — GPT-powered manual search (비활성; 사이드바에서 숨김)
  (main)/guidelines/    — 출입국 실무지침 DB viewer; 3단계 트리 탐색(L1 진입점→L2 업무유형→L3 항목) + 직접검색 + TB배너 + quickdoc 딥링크
  (main)/admin/         — Admin: account list + workspace provisioning
```

All API calls go through `frontend/lib/api.ts` (axios) — attaches `Authorization: Bearer <token>` on every request; on 401 clears auth state and redirects to `/login`.

Auth helpers: `frontend/lib/auth.ts` (`getUser`, `setUser`, `clearUser`, `isLoggedIn`). `setUser` stores two separate localStorage keys: `user_info` (full JSON object) and `access_token` (bare token string). `api.ts` reads `access_token` directly for the `Authorization` header.

**Auth guard — two layers:**
1. **`frontend/middleware.ts`** (Edge): checks `kid_auth` cookie, redirects before page renders
2. **`(main)/layout.tsx`** (client): `useEffect` checks `isLoggedIn()` via localStorage, keeps `ready=false` until confirmed

### Sidebar (`frontend/components/layout/sidebar.tsx`)

- `메뉴얼 검색` (`/manual`) — 코드는 유지, `NAV_ITEMS`에서 주석 처리하여 숨김 (추후 활성화 예정)
- `메뉴얼` — `<a target="_blank">` 외부 링크로 하이코리아 URL 직접 연결 (Next.js `router.push` 아님)

### Key frontend dependencies

- **@tanstack/react-query** — data fetching / cache
- **@fullcalendar/react** — calendar on dashboard
- **@radix-ui/*** — headless UI primitives
- **sonner** — toast notifications (`toast.success`, `toast.error`)
- **react-hook-form + zod** — form validation
- **react-zoom-pan-pinch** — still in package.json but no longer used in scan page; do not reintroduce in scan page

### FullCalendar `eventContent` — 무한 루프 주의

`eventContent`에 인라인 함수(`(arg) => <div>...`)를 직접 전달하면 React error #185 (Maximum update depth exceeded)가 발생한다. 반드시 `useCallback`으로 메모이제이션된 참조를 전달할 것:

```tsx
const renderEventContent = useCallback((arg: { event: { title: string } }) => (
  <div style={{ whiteSpace: "pre-line" }}>{arg.event.title}</div>
), []);
// ...
<FullCalendar eventContent={renderEventContent} />
```

### 모바일 반응형 레이아웃

`(main)/layout.tsx`에서 `window.innerWidth < 768`로 `isMobile` 감지 (resize 이벤트 포함).
- 모바일: `mainMarginLeft = 0`, 사이드바는 transform 드로어 (`translateX(-100%/0)`) + backdrop
- 데스크톱: `mainMarginLeft = leftOffset` (사이드바 너비)
- 뷰포트 메타: `app/layout.tsx`에서 `export const viewport: Viewport = { width: "device-width", initialScale: 1 }` (Next.js Viewport export 방식 — `<meta>` 직접 삽입 금지)

---

## Critical Constraints

1. **No Streamlit at runtime.** Never import `pages/` from FastAPI routers or services.
2. **No unconditional `import streamlit`** in `core/` modules — guard with `try/except`.
3. **Google Sheets is the database.** Don't add a relational DB.
4. **`config.py` is the single source of truth** for Drive/Sheets IDs and Korean tab names.
5. **`is_active=TRUE` only after all three keys** (`folder_id`, `customer_sheet_key`, `work_sheet_key`) are confirmed.
6. **Tenant data isolation is strict** — `get_customer_sheet_key()` / `get_work_sheet_key()` must not fall back to admin sheets for non-default tenants.
7. **UI 변경 금지** — 기능 변경 시 기존 레이아웃/배치 구조를 임의로 바꾸지 말 것. 데이터·로직만 수정.

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

## Board / Notice system (`backend/routers/board.py`)

### POST_HEADER (12 columns)
`id, tenant_id, author_login, office_name, is_notice, category, title, content, created_at, updated_at, popup_yn, link_url`

`popup_yn="Y"` → 대시보드 일일 팝업에 표시. 관리자만 설정 가능.
`link_url` → 공지 상세에서 "🔗 바로 가기" 버튼으로 노출. 시스템 자동생성 공지에 사용.

### Endpoints
- `GET /api/board` — 전체 목록 (시스템 내부 행 `__manual_check__` 제외, 공지 상단)
- `GET /api/board/popup` — `popup_yn=Y`인 공지만 반환 (대시보드 팝업용)
- `GET /api/board/check-manual` — 하이코리아 메뉴얼 페이지 스크랩 → 첨부파일 날짜 변경 감지 → 자동 공지 생성 (관리자 전용)
- `POST /api/board` — 글 작성 (관리자만 `is_notice`, `popup_yn` 설정 가능)
- `PUT /api/board/{id}` — 수정 (작성자 or 관리자)
- `DELETE /api/board/{id}` — 삭제 (작성자 or 관리자, 댓글 연쇄 삭제)

### 시스템 예약 category
- `"__manual_check__"` — 마지막으로 감지한 하이코리아 첨부 날짜를 `content`에 저장 (목록에서 숨김)
- `"__manual_notice__"` — 자동 생성된 메뉴얼 업데이트 공지 (`popup_yn=Y`, `link_url=하이코리아URL`)

### 대시보드 팝업 (`dashboard/page.tsx`)

**공지 팝업** (`showPopup`):
- 마운트 시 `/api/board/popup` 호출 → `updated_at` 기준 최신값을 `localStorage.notice_popup_seen_at` (ISO timestamp)와 비교
- 새 공지가 있으면 모달 표시: 목록 → 클릭 → 상세 (`link_url` 있으면 "🔗 바로 가기")
- "오늘 하루 보지 않기" 클릭 시 `localStorage.notice_popup_seen_at = new Date().toISOString()`

**오늘 일정 팝업** (`showSchedulePopup`):
- `events` 쿼리 로드 후 오늘 날짜(`YYYY-MM-DD`) 키로 일정 존재 여부 확인
- `localStorage.today_schedule_seen`에 오늘 날짜가 없으면 팝업 표시
- "오늘 하루 보지 않기" 클릭 시 `localStorage.today_schedule_seen = 오늘(YYYY-MM-DD)` (ISO timestamp 아님)

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
7. **Final gate** — `_is_valid_address_candidate`: requires province regex + admin/road syllable token. Blank is saved instead of garbage. (완화됨: 단어경계 대신 음절 패턴 사용)

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

- `POST /api/scan-workspace/passport` — crops image to `roi_json` (normalised x/y/w/h), applies `rotation_deg`, runs MRZ OCR. Returns `{"result": {...}, "roi": {...}}`.
- `POST /api/scan-workspace/arc` — single-field extraction via `roi_ocr_service.extract_arc_field(img, field, roi, rotation_deg)`; or batch via `extract_arc_fields`. Returns `{"field": "...", "value": "..."}`.

Both accept `rotation_deg: int = Form(default=0)` (0/90/180/270). Rotation is applied **after** cropping: `crop.rotate(-deg, expand=True)` (PIL은 CCW, CSS는 CW이므로 부호 반전).

**Korean name upscaling** (`roi_ocr_service.py`): 한글 필드 크롭이 작을 경우 최소 width 400px 기준으로 최소 2× upscale 후 Tesseract `kor+eng PSM=6` 실행.

- `POST /api/scan-workspace/render-pdf` — PDF 파일을 받아 지정 페이지(기본 0)를 PNG로 렌더링하여 반환. `pymupdf(fitz)` 사용, `dpi` 파라미터(기본 200). 응답 헤더 `X-PDF-Total-Pages`에 전체 페이지 수 포함.

**PDF 처리 흐름**: 프론트엔드 `handlePassportFile`/`handleArcFile`에서 `file.type === "application/pdf"` 감지 → `render-pdf` 호출 → PNG `File` 객체로 변환 → 이후 이미지와 동일한 워크스페이스 흐름. `WorkspaceCanvas`에 PDF 분기 없음 — PDF는 항상 변환 후 진입.

`roi_ocr_service.py` imports low-level helpers directly from `ocr_service.py` (`_ocr`, `_prep_mrz`, `_parse_mrz_pair`, `find_best_mrz_pair_from_text`, etc.). Do not duplicate these helpers.

### Scan page architecture (`frontend/app/(main)/scan/page.tsx`)

The `/scan` page is a **semi-manual OCR workspace** — it never fires OCR on upload. Architecture:

- **`WorkspaceCanvas` component** — fixed-height (660 px) viewport. Image is a movable layer (drag-to-pan, button zoom/rotate, no wheel zoom). Guide boxes are a **separate fixed overlay layer** rendered above the image; they do not move with the image.
- **`computeRoi(guide, container, natural, tf)`** — converts a guide box position (container-space 0–1) to image-space crop coordinates accounting for scale, pan, and rotation (0°/90°/180°/270°). Called at the moment the user clicks an extract button. This is the single source of truth for what the backend crops — if visual alignment ≠ OCR crop, the bug is here.
- **`stateRef` pattern** — `WorkspaceCanvas` writes `{ tf, container, natural }` into a `MutableRefObject` on every render (not via `useEffect`). The OCR handlers in `ScanPage` read from that ref at click time to compute the ROI. No derived ROI state is stored.
- **Guide constants** — `PASSPORT_MRZ_GUIDE` (single gold box, `{x:0.160, y:0.635, w:0.630, h:0.085}`) and `ARC_GUIDE_BOXES` (6 field boxes). All coordinates are container-space (0–1). User moves the image to align document features with the fixed guide boxes, then clicks extract.
- **Mode** — `이동식` (guides shown, move image to align) / `선택식` (guides hidden, user draws custom ROI box). 두 모드는 배타적. 선택식에서 새 필드 선택 시 이전 customRois 전체 초기화.
- Zoom: button-only (no wheel), range 0.05×–20×.
- `POST /api/scan/register` is the save path.

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

### Active task D+ display (dashboard)

3단계(접수/처리/보관중) 각각에 독립 D+ 뱃지 표시. 다음 단계가 체크되면 해당 D+는 회색 고정:

- 접수 D+ = `daysBetween(접수ts, 처리ts || null)` — 처리 체크 시 회색
- 처리 D+ = `daysBetween(처리ts, 보관중ts || null)` — 보관중 체크 시 회색
- 보관중 D+ = `dPlusFromTs(보관중ts)` — 항상 카운트 중

기존 단일 D+ 표시(`latestStageTs` 함수)는 제거됨.

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

Always use `router.push('/route')` for same-app routes. Never `<a href="/route" target="_blank">` — opens a new tab that may fail to load webpack chunks from a stale `.next/` cache. (외부 URL은 예외: `<a target="_blank" rel="noopener noreferrer">` 사용)

### Daily settlement → active task field routing

`POST /api/daily/entries` triggers `_apply_daily_to_active()` in `backend/routers/daily.py`.

**수입(inc) 측은 진행업무 필드에 절대 반영하지 않는다.** 지출(e1/e2) 측만 반영.

KID 메모 태그 형식 (현재):
```
[KID]inc=이체;e1=인지;e1a=60000;e2=인지;e2a=39000[/KID]
```

| 메모 키 | 진행업무 필드 |
|---|---|
| `e1=이체` or `e2=이체` | `transfer` |
| `e1=현금` or `e2=현금` | `cash` |
| `e1=카드` or `e2=카드` | `card` |
| `e1=인지` or `e2=인지` | `stamp` |

`e1a`/`e2a`: 각 지출 슬롯의 개별 금액. 존재하면 정확히 해당 금액만 해당 필드에 반영. 없으면 legacy 단일 타입 감지로 폴백.

Matching an existing task uses the tuple `(category, date, name, work)`. No match → new task created. The `현금출금` category is always skipped.

**Active task header** — `ACTIVE_HEADER` in `backend/routers/tasks.py` is authoritative (17 columns). Any code writing to `ACTIVE_TASKS_SHEET_NAME` must use all 17 columns including `reception`, `processing`, `storage`. The `_ACTIVE_HEADER` in `daily.py` mirrors this — keep them in sync.

After each `POST /api/daily/entries`, the frontend must invalidate **both** `["daily", "entries"]` and `["tasks", "active"]` in React Query. Use `onSettled` (not `onSuccess`) so invalidation runs even if the response is slow or errors.

### Quick-doc PDF pipeline

```
① GET /api/quick-doc/tree              — selection tree
② POST /api/quick-doc/required-docs    — returns main_docs + agent_docs
③ POST /api/quick-doc/generate-full    — fills PDF fields, merges, applies seals
```

`generate_full` accepts `direct_overrides: dict` (PDF widget name → value) applied after `build_field_values()` — use for post-generation field edits without changing customer data.

### 원클릭 작성 (`POST /api/quick-doc/quick-poa`)

구현된 출력: `위임장`, `하이코리아`, `소시넷` (templates/ 폴더의 PDF 파일).
`_OUTPUT_ORDER = ["위임장", "하이코리아", "소시넷"]` 순서로 `fill_and_append_pdf` 호출 → 단일 merged PDF → 1페이지면 JPG, 다페이지면 ZIP.
`build_field_values()`의 동일한 `field_values` + `seal_bytes_by_role`을 모든 출력에 재사용.

프론트엔드 필드 표시 규칙:
- `체류자격`, `여권번호` 필드: `위임장`이 `selectedOutputs`에 있을 때만 표시
- `위임업무` 체크박스 섹션: `위임장`이 `selectedOutputs`에 있을 때만 표시

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

Dockerfile.combined (단일 서비스용):
  Stage 1: node:20-alpine — Next.js 빌드 (API_URL=http://localhost:8000 baked)
  Stage 2: python:3.11-slim + Node.js 20 apt 설치 + Tesseract + OmniMRZ
  start.sh: uvicorn(127.0.0.1:8000, background) + next start(0.0.0.0:3000, foreground/PID1)
  Render 설정: Dockerfile=Dockerfile.combined, Port=3000
```

`docker-compose.yml` passes `build.args.API_URL: http://backend:8000` to the builder stage AND sets `environment:` for belt-and-suspenders. The build arg is the critical one.

**Render 배포 설정:**
- Dockerfile Path: `Dockerfile.combined` (선행 공백 없이 정확히 입력 — 공백 있으면 "no such file" 에러)
- Port: `3000`
- Auto-Deploy: enabled → git push 시 자동 빌드/배포

---

## 출입국 실무지침 라우터 (`backend/routers/guidelines.py`)

Google Sheets가 아닌 **로컬 JSON 파일** 기반 정적 참조 데이터. 테넌트별 차이 없음 (공유 데이터).

### 데이터 소스
- `backend/data/immigration_guidelines_db_v2.json`
- 원본 엑셀(`정리.xlsx`) → `엑셀_json_변환.py` 스크립트로 재생성 가능
- 포함 시트: MASTER_ROWS(369건), RULES(38건), EXCEPTIONS(32건), DOC_DICTIONARY(36건), SEARCH_KEYS, LEGACY_UI_MAP
- **master_rows 키는 소문자**. 백엔드가 `_DB.get("master_rows", [])` 로 읽음 — MASTER_ROWS(대문자)로 바꾸면 빈 배열 반환됨
- **모든 행의 `status` 필드는 반드시 `"active"` (영문)**. `"정상"` 등 한글 값을 넣으면 `GET /api/guidelines/` 필터에서 제외됨

### 모듈 임포트 시 인덱스 빌드 (1회)
- `_CODE_INDEX`: `detailed_code` → rows 매핑
- `_SEARCH_INDEX`: keyword → row_id 매핑
- `_ROW_INDEX`: `row_id` → row 매핑

### 엔드포인트 (prefix: `/api/guidelines`)
| 엔드포인트 | 설명 |
|---|---|
| `GET /stats` | DB 통계 (버전, 갱신일, 항목수) |
| `GET /search/query?q=...` | 키워드 검색 (코드/업무명/서류명) |
| `GET /code/{code}` | 체류자격 코드별 조회 (F-4 → F-4, F-4-1, F-4-2... 모두 반환) |
| `GET /rules` | 공통 규칙 목록 |
| `GET /exceptions` | 예외 조건 목록 |
| `GET /docs/lookup?name=...` | 서류명 표준화 조회 |
| `GET /tree/entry-points` | 상담 진입점 14개 + 각 업무 건수 |
| `GET /tree/results` | quickdoc 파라미터(category/minwon/kind/detail)로 해당 rows 반환 |
| `POST /tb/evaluate` | 결핵 검사 필요 여부 평가 (국적 ISO3 + action_type → TB-001/TB-002) |
| `GET /tb/high-risk-countries` | 결핵 고위험국 ISO3 목록 (~70개국) |
| `GET /` | MASTER_ROWS 목록 (action_type/domain/major_action 필터 + 페이징) |
| `GET /{row_id}` | 단건 상세 + 연관 RULES/EXCEPTIONS |

**라우터 순서 주의**: FastAPI 경로 충돌 방지를 위해 모든 고정 경로(`/search/query`, `/code/{code}`, `/tree/*`, `/tb/*` 등)가 `/{row_id}` 보다 **앞에** 등록되어 있어야 함. 현재 파일 순서 유지할 것.

### action_type ENUM
`CHANGE` | `EXTEND` | `EXTRA_WORK` | `WORKPLACE` | `REGISTRATION` | `REENTRY` | `GRANT` | `VISA_CONFIRM` | `APPLICATION_CLAIM` | `DOMESTIC_RESIDENCE_REPORT` | `ACTIVITY_EXTRA`

### 핵심 데이터 규칙
- `form_docs` (사무소 준비서류): 업체 준비 서류 — `|` 구분, 표준 순서: `통합신청서 | 위임장 | 대행업무수행확인서 | [기타]`
- `supporting_docs` (필요서류/고객 준비): 고객 준비 서류 — **절대 form_docs와 합치지 말 것**
- UI 레이블: `form_docs` → "사무소 준비서류", `supporting_docs` → "필요서류 (고객 준비)"
- 인지세(`fee_rule`): 수수료라고 표현하지 말 것
- `fee_rule` 형식: `"인지세 6만원"` / `"인지세 20만원"` / `"단수 3만원 | 복수 5만원"` / `"수수료 없음"`. F-5 CHANGE는 `"인지세 20만원"`, F-4 EXTEND는 `"인지세 6만원"` (수수료 없음 아님)

### 현재 F-5 영주 항목 (2026-04-19 기준)
기존 K-STAR·최우수인재 외 추가된 일반 영주 항목:
- `F-5-1` CHANGE — 국민의 배우자·자녀 (5년 이상 합법체류)
- `F-5-2` CHANGE — 미성년 자녀
- `F-5-6` CHANGE — 결혼이민자 (F-6 기반)
- `F-5-10` CHANGE — 재외동포(동포영주) — F-4로 5년 이상 체류
- `F-5-11` CHANGE — 점수제 우수인재 (60점 이상)
- `F-5-14` CHANGE — 5년 이상 합법체류 일반 (소득·자산 요건)
- `F-5` REGISTRATION — 영주 외국인등록
- `F-5` REENTRY — 영주 재입국허가

### quickdoc 딥링크 필드 (`backend/scripts/migrate_guidelines_v2.py` 실행 결과)
각 row에 추가된 필드:
- `quickdoc_category`: `"체류"` | `"사증"` | null
- `quickdoc_minwon`: `"변경"` | `"연장"` | `"등록"` | `"부여"` | null
- `quickdoc_kind`: `"F"` | `"H2"` | `"E7"` | `"D"` | null
- `quickdoc_detail`: `"1"`~`"6"` 등 | null

프론트엔드 `buildQuickDocUrl(row)` 함수가 이 필드를 읽어 `/quick-doc?category=...&minwon=...` URL을 생성. 필드가 없으면 `detailed_code` 패턴으로 추론.

### TB 결핵 평가 (`POST /tb/evaluate`)
- 입력: `{ nationality_iso3: "VNM", action_type: "REGISTRATION", detailed_code: "F-4" }`
- 출력: `{ required: bool, stage: "registration"|"stay_permission"|null, rule_id: "TB-001"|"TB-002"|null, reason: str }`
- TB-001: REGISTRATION 단계 / TB-002: CHANGE·EXTEND·GRANT 단계
- 면제: A-/B-/C- 계열 체류자격
- UI: DetailPanel에서 REGISTRATION/CHANGE/EXTEND/GRANT 업무 조회 시 정적 TB 경고 배너 표시

### 데이터 업데이트

**방법 A — 엑셀 전체 재생성 (대규모 수정 시):**
```bash
# 1. 원본 엑셀 수정: analysis/클로드/정리.xlsx (MASTER_ROWS 시트)
# 2. JSON 재생성 (엑셀_json_변환.py는 analysis/클로드/서버설정/ 에 위치)
#    주의: 스크립트가 ../정리.xlsx 로 읽음 (서버설정/ 기준 부모 폴더)
python "analysis/클로드/서버설정/엑셀_json_변환.py"
# 3. 생성된 JSON을 backend/data/로 복사
cp "analysis/클로드/서버설정/immigration_guidelines_db_v2.json" backend/data/immigration_guidelines_db_v2.json
# 4. quickdoc 매핑 필드 재생성 (repo root에서 실행)
python backend/scripts/migrate_guidelines_v2.py
# 5. 서버 재시작 (uvicorn --reload 모드이면 자동 반영)
```

**방법 B — JSON 직접 수정 (소규모 행 추가/수정 시):**

`analysis/클로드/서버설정/add_missing_rows_v*.py` 패턴의 스크립트를 작성해 JSON을 직접 패치한 뒤 migrate만 실행:
```bash
python "analysis/클로드/서버설정/fix_스크립트이름.py"
python backend/scripts/migrate_guidelines_v2.py
```
새 행 필수 필드: `row_id`, `domain`, `major_action_std`, `action_type`, `business_name`, `detailed_code`, `form_docs`, `supporting_docs`, `fee_rule`, `basis_section`, **`"status": "active"`** (영문 필수), `search_keys: []`, quickdoc 필드 4개(null로 초기화 후 migrate가 채움).

### 실무지침 페이지 트리 탐색 구조 (`frontend/app/(main)/guidelines/page.tsx`)

3단계 드릴다운: **L1(진입점 그리드)** → **L2(업무유형 카드)** → **L3(항목 목록)**.

- `viewMode`: `"l1"` / `"l2"` / `"l3"` / `"search"` — 검색어 입력 시 별도 search 뷰
- `skipL2`: 로딩 완료 후 treeL2Items.length ≤ 1이면 L2 스킵 → L3 직행 (단일 action_type 진입점)
- **`loadEntryRows(entry)`** — 진입점 클릭 시 lazy load:
  - 코드 기반(`/^[A-Z]-\d/` 패턴): `GET /api/guidelines/code/{code}` — status 필터 없음
  - 업무 기반(한글 search_query): `GET /api/guidelines/?action_type=...&limit=500&status=all` — 여러 action_type 병렬 fetch 후 중복 제거
- **`_ENTRY_POINTS_DATA`** (백엔드 `guidelines.py`): 14개 진입점. 코드 기반 7개(F-5/F-4/E-7/D-2/H-2/F-6/F-2) + 업무 기반 7개(REG/REEN/EX/WP/GR/VC/DR) + AC(직접신청)

---

## In-progress / known issues

- **OCR debug mode active** — `/api/scan/passport` and `/api/scan/arc` (full-auto endpoints) still wrap responses in `{"debug": ..., "result": {...}}`. The scan workspace endpoints (`/api/scan-workspace/*`) return clean `{"result": {...}}`. Remove the debug wrapper from the full-auto endpoints when tuning is complete.
- **ARC address accuracy** — geometry-first pipeline + dated-row parsing active in `ocr_service.parse_arc`. `_debug_geometry` key in response contains `divider_frac`, `coarse_confidence`, `addr_source`, `ambig_winner` for diagnosis.
- **OmniMRZ vestigial** — installed in `Dockerfile.backend` from source but never called at runtime (prewarm disabled). Can be removed once Tesseract-only path is confirmed sufficient.
- **Windows local dev** — `backend/main.py` forces stdout/stderr to UTF-8 on Windows to prevent Korean characters appearing as `???` in uvicorn logs. Do not remove this block.
- **`react-zoom-pan-pinch`** — still in `frontend/package.json` but unused. Safe to remove. Do not reintroduce it in the scan page.
- **메뉴얼 업데이트 자동감지** — `GET /api/board/check-manual`은 관리자가 게시판에서 수동 트리거. 스케줄러 없음. 하이코리아 페이지 스크랩(`requests`)으로 날짜 추출 — 페이지 구조 변경 시 정규식 수정 필요.
