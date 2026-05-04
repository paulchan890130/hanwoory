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
                          guidelines, marketing
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
`"게시판"`, `"게시판댓글"` — board/notice system is intentionally shared across all tenants. `"홈페이지게시물"` — marketing posts for the public homepage. `core/google_sheets.get_worksheet()` falls through to `sheet_key = SHEET_KEY` for any tab not in the customer or work workbook sets.

### Tenant workspace provisioning

`POST /api/admin/workspace` in `backend/routers/admin.py` (idempotent, stage-by-stage):
1. Creates/reuses office folder under `PARENT_DRIVE_FOLDER_ID`
2. Copies `CUSTOMER_DATA_TEMPLATE_ID` → customer workbook
3. Copies `WORK_REFERENCE_TEMPLATE_ID` → work workbook
4. Writes `folder_id`, `customer_sheet_key`, `work_sheet_key` into Accounts
5. Sets `is_active=TRUE` only when all three are present

`POST /api/admin/bootstrap` — seeds the first admin account (no auth required, idempotent).

`DELETE /api/admin/accounts/{login_id}` — 계정 소프트 삭제 (`is_active=FALSE`). 자신의 계정 삭제 불가(HTTP 400). 이미 비활성이면 idempotent 200 반환. Google Sheets/Drive 리소스 보존을 위해 행 자체는 삭제하지 않음. 프론트엔드에서 비활성 계정은 삭제 버튼 대신 "삭제됨" 배지 표시.

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
  page.tsx              — Public homepage (한우리행정사사무소 marketing site); NO auth required
  homepage.css          — Homepage-only CSS (Noto fonts, gold theme, sections); isolated from internal app
  sitemap.ts            — Dynamic sitemap.xml (fetches /api/marketing/posts, revalidate 1h)
  board/page.tsx        — Public post list (server component); fetches all published posts, passes to BoardClient; maxWidth 820
  board/BoardClient.tsx — Client component: BOARD_ONLY whitelist pre-filter, category filter (공지사항/업무 안내/제도 변경/기타), search, post list; /documents callout
  board/[id]/page.tsx   — Public post detail; NO auth required; renders MarkdownContent; injects Article + BreadcrumbList JSON-LD
  documents/page.tsx    — Public required-document guide hub; NO auth required; server component; injects BreadcrumbList JSON-LD
  documents/DocumentsClient.tsx — Client component: search + 9-group grid (F-1/F-2/F-3/F-4/F-5/F-6/H-2/귀화/중국공증); stable `id` attrs for anchor links
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
  (main)/noticeboard/   — Internal board + notice management (renamed from /board to free that URL for public use)
  (main)/manual/        — GPT-powered manual search (비활성; 사이드바에서 숨김)
  customer-popup/page.tsx — 고객카드 새 창 팝업 (인증 필요, 레이아웃 없음). `localStorage["pinned_customer"]` 에서 데이터 읽고 `storage` 이벤트로 실시간 갱신.
  (main)/guidelines/    — 출입국 실무지침 DB viewer; 4단계 트리(L1 진입점→L2 업무유형→L3 항목→L4 조건분기) + 직접검색 + TB배너 + quickdoc 딥링크
  (main)/admin/         — Admin: account list + workspace provisioning + 계정 소프트 삭제
  (main)/marketing/     — Admin-only: homepage post list, new, [id]/edit
```

All API calls go through `frontend/lib/api.ts` (axios) — attaches `Authorization: Bearer <token>` on every request; on 401 clears auth state and redirects to `/login`.

Auth helpers: `frontend/lib/auth.ts` (`getUser`, `setUser`, `clearUser`, `isLoggedIn`). `setUser` stores two separate localStorage keys: `user_info` (full JSON object) and `access_token` (bare token string). `api.ts` reads `access_token` directly for the `Authorization` header.

**Auth guard — two layers:**
1. **`frontend/middleware.ts`** (Edge): checks `kid_auth` cookie, redirects before page renders.
   - **Public paths** (no auth): `/`, `/board/*`, `/documents`, `/siheung-immigration-agent`, `/jeongwang-immigration-agent`, `/sitemap.xml`, `/robots.txt`
   - **Matcher** excludes extensions: `jpg|png|gif|svg|ico|webp|css|js|xml|txt` — `.xml`/`.txt` exclusion is what lets sitemap and robots.txt pass without auth.
   - **Adding a new public page:** add its `pathname` check in the `if` block at the top of `middleware()`, AND add it to `sitemap.ts` static entries.
2. **`(main)/layout.tsx`** (client): `useEffect` checks `isLoggedIn()` via localStorage, keeps `ready=false` until confirmed. 고객카드 고정 패널(`PinnedCustomerCard`) — `window.addEventListener("pin-customer", handler)` CustomEvent로 수신, 오른쪽 272px 고정 패널로 표시. `/customer-popup` 팝업 창과 공존: 팝업은 `localStorage["pinned_customer"]`를, 패널은 CustomEvent를 사용.

### Shared components (`frontend/components/`)

- **`MarkdownContent.tsx`** — 마크다운 → 시맨틱 HTML 렌더러 (`"use client"`, 외부 의존 없음). `board/[id]/page.tsx`와 `RichEditor` 미리보기에서 사용.
- **`RichEditor.tsx`** — 관리자용 마크다운 툴바 에디터 (`"use client"`). `marketing/new`, `marketing/[id]/edit`에서 사용. `onImageUpload` prop으로 이미지 업로드 핸들러 주입.
- **`PublicMobileNav.tsx`** + **`public-mobile.css`** — 공개 페이지 전용 모바일 고정 상단 헤더 + 하단 연락처 바. 두 요소 모두 데스크톱에서 `display: none`, 모바일(`≤768px`)에서만 표시. 모든 공개 페이지(`/`, `/board`, `/board/[id]`, `/documents`, `/siheung-immigration-agent`, `/jeongwang-immigration-agent`)에 `<PublicMobileNav />` 추가 필수.
  - `pathname === "/"` 이면 상단 헤더/스페이서는 렌더링하지 않음 (홈페이지의 기존 `.nav`가 담당). 하단 연락처 바는 모든 공개 페이지에 표시.
  - 새 공개 페이지 추가 시: `PAGE_MAP` 상수에 `{ label, href }` 추가.
  - 스페이서 `div.pmn-top-spacer` (높이 56px)가 DOM 흐름에 포함되어 고정 헤더 뒤로 컨텐츠가 가리지 않게 함. 별도 padding-top 필요 없음.

### 고객카드 팝업 (`customer-popup/page.tsx`)

고객 드로어의 **팝업창** 버튼(`<ExternalLink>`) 클릭 시:
1. `localStorage["pinned_customer"] = JSON.stringify(customer)` 저장
2. `window.open("/customer-popup", "customer_card_popup", "width=300,height=680,...")` 새 창 (같은 이름으로 재사용)
3. 팝업 차단 시 fallback: `window.dispatchEvent(new CustomEvent("pin-customer", { detail }))` → `(main)/layout.tsx`의 `PinnedCustomerCard` 오른쪽 패널 표시

`customer-popup/page.tsx` — 인증 필요(쿠키 기반), 레이아웃 없음. `storage` 이벤트로 다른 고객 선택 시 실시간 갱신. 미들웨어 별도 예외 추가 불필요(로그인 사용자의 `kid_auth` 쿠키로 자동 통과).

### Sidebar (`frontend/components/layout/sidebar.tsx`)

- `메뉴얼 검색` (`/manual`) — 코드는 유지, `NAV_ITEMS`에서 주석 처리하여 숨김 (추후 활성화 예정)
- `메뉴얼` — `<a target="_blank">` 외부 링크로 하이코리아 URL 직접 연결 (Next.js `router.push` 아님)
- `마케팅` (`/marketing`) — `user?.is_admin` 조건으로 관리자에게만 표시. `MARKETING_ITEM` 상수로 정의됨 (관리자 섹션 구분선 위)

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

## 홈페이지 공개 사이트 & 마케팅 게시물

### 공개 홈페이지 (`app/page.tsx`)

- `www.hanwory.com` 공개 마케팅 페이지 — 인증 없이 접근 가능
- 미들웨어 예외: `pathname === "/"` → 쿠키 검사 없이 통과
- CSS는 `frontend/app/homepage.css`에 분리 (전용 CSS 변수 `--hp-radius`, `--hp-radius-sm` 사용 — globals.css의 `--radius: 0.5rem`과 충돌 방지)
- "업무 안내" 섹션(#board)이 `/api/marketing/posts`를 동적 fetch하여 게시된 글 표시
- 로그인 버튼(`<Link href="/login">`) → 기존 내부 로그인 페이지로 이동

### 마케팅 라우터 (`backend/routers/marketing.py`)

Google Sheets 기반 (어드민 `SHEET_KEY`의 `"홈페이지게시물"` 탭). 탭이 없으면 첫 upsert 시 자동 생성됨.

**MARKETING_HEADER** (17 columns):
`id, title, slug, category, summary, content, thumbnail_url, is_published, is_featured, created_by, created_at, updated_at, image_file_id, image_url, image_alt, meta_description, tags`

The first 12 columns are the original schema; the last 5 were added in the 2026-04-25 session. Existing 12-column rows in the sheet remain readable — `get_all_records()` fills missing columns with empty strings. `upsert_rows_by_id` auto-updates the header row to 17 columns on first write after the code change.

`is_published = "TRUE"` 인 행만 공개 홈페이지에 노출됨.

### 엔드포인트 (prefix: `/api/marketing`)

| 엔드포인트 | 인증 | 설명 |
|---|---|---|
| `GET /posts` | **없음** | 게시된 홈페이지 포스트만 반환 (공개) |
| `GET /posts/{id}` | **없음** | 단건 공개 게시물 (slug 또는 id로 조회) |
| `GET /admin/posts` | 인증 + admin | 전체 목록 (미게시 포함) |
| `POST /admin/posts` | 인증 + admin | 새 게시물 생성 (기본 `is_published=FALSE`) |
| `PUT /admin/posts/{id}` | 인증 + admin | 게시물 수정 (read-merge-write) |
| `DELETE /admin/posts/{id}` | 인증 + admin | 게시물 삭제 |
| `PATCH /admin/posts/{id}/publish` | 인증 + admin | 게시/미게시 토글 |
| `POST /admin/upload-image` | 인증 + admin | 이미지 업로드 → Google Drive → 공개 URL 반환 |

이미지 업로드 흐름: `UploadFile` 수신 → `_MARKETING_IMG_FOLDER_ID` (하드코딩된 Drive 폴더) 에 저장 → `anyone reader` 권한 설정 → `{"url": "https://drive.google.com/uc?export=view&id=..."}` 반환. 제한: 5MB, jpg/png/gif/webp만 허용. (이전에는 폴더를 동적 생성했으나 지금은 상수 `_MARKETING_IMG_FOLDER_ID`로 고정.)

### 마케팅 콘텐츠 형식 — Markdown

`content` 필드는 **마크다운 텍스트**를 저장한다 (스키마 변경 없음 — 기존 plain-text 하위호환 유지).

**공개 렌더링** (`frontend/components/MarkdownContent.tsx`):
- 외부 라이브러리 의존 없는 자체 파서. `"use client"` 컴포넌트 (SSR + hydration으로 SEO 유지).
- 블록 요소: `## H2`, `### H3`, `> 인용`, `- 목록`, `1. 목록`, `![alt](src) 이미지`, `---`
- 인라인 요소: `**bold**`, `*italic*`, `` `code` ``, `[link](url)`, 단일 `\n` → `<br>` (plain-text 하위호환)
- 독립 이미지 줄 → `<figure><img alt="..."><figcaption>` 로 렌더링 (크롤러 alt 텍스트 보존)
- 모든 블록이 시맨틱 HTML 태그로 출력됨 — `dangerouslySetInnerHTML` 미사용, XSS 없음

**관리자 에디터** (`frontend/components/RichEditor.tsx`):
- 마크다운 툴바 + `<textarea>` 조합. 외부 에디터 라이브러리 없음.
- 툴바: H2 H3 | B I | •목록 1.목록 | ❝인용 🔗링크 🖼이미지 | 구분선 | 미리보기 토글
- 이미지 패널: URL 직접 입력 또는 파일 업로드 (`POST /api/marketing/admin/upload-image`), alt 텍스트 필드 포함
- 미리보기 토글 시 `MarkdownContent` 컴포넌트로 실시간 렌더링

### 공개 사이트 SEO 인프라

- **`frontend/app/sitemap.ts`** — Next.js App Router 동적 sitemap. 빌드/요청 시 `GET /api/marketing/posts` 호출하여 게시된 게시물을 `/board/{slug || id}` URL로 포함 (revalidate 1시간). API 접근 불가 시 정적 항목(`/`, `/board`)만 반환. 공개 API 자체가 `is_published=TRUE` 필터를 적용하므로 추가 필터 불필요.
- **`frontend/public/robots.txt`** — 정적 파일. `Allow: /`. 차단: `/login`, `/dashboard`, `/admin`, `/marketing`, `/private`. `Sitemap: https://www.hanwory.com/sitemap.xml` 포함. (단순 형식 — 보안은 미들웨어에서 담당)
- **JSON-LD 구조화 데이터**:
  - `app/page.tsx` — `LocalBusiness` JSON-LD (전화 010-4702-8886, 경기도 시흥시 정왕동, `areaServed`, `knowsAbout`). `"use client"` 컴포넌트이므로 `export const metadata` 불가 — 루트 `layout.tsx`의 default title/description이 홈페이지 메타로 사용됨.
  - `board/[id]/page.tsx` — `Article` (+ `mainEntityOfPage`) + `BreadcrumbList` JSON-LD. 게시물별 서버 렌더링.
  - `documents/page.tsx` — `BreadcrumbList` JSON-LD (홈 › 업무별 준비서류).
  - `siheung-immigration-agent/page.tsx` — `LocalBusiness` + `BreadcrumbList` JSON-LD (홈 › 시흥 행정사).
  - `jeongwang-immigration-agent/page.tsx` — `LocalBusiness` + `BreadcrumbList` JSON-LD (홈 › 정왕 행정사).
- **Sitemap** (`sitemap.ts`): `/` (1.0), `/board` (0.7), `/documents` (0.9), `/siheung-immigration-agent` (0.8), `/jeongwang-immigration-agent` (0.8), 전체 published `/board/{slug}` (0.6, dynamic)
- 공개 라우트: `/`, `/board/*`, `/documents`, `/siheung-immigration-agent`, `/jeongwang-immigration-agent`, `/sitemap.xml`, `/robots.txt` — 미들웨어 인증 없이 통과.

### 공개 사이트 구조 — 5개 주요 라우트

| 라우트 | 역할 | 메모 |
|---|---|---|
| `/` | 공개 홈페이지 | HERO / ABOUT(지역 SEO 문구 포함) / SERVICES / **업무별 준비서류 카드** / 업무 안내(BOARD) / FAQ / CTA |
| `/board` | 일반 게시판(업무 안내) | BOARD_ONLY 필터: 공지사항 / 업무 안내 / 제도 변경 / 기타 카테고리만 표시. 46개 준비서류 게시물 제외. |
| `/documents` | 준비서류 안내 허브 | 9개 체류자격 그룹 + 검색. `/board/{slug}` 상세 페이지로 연결. ID 앵커(`#f4` 등) 지원. |
| `/siheung-immigration-agent` | 시흥 지역 SEO 랜딩 | 서버 컴포넌트. 시흥 행정사 키워드 타겟. `LocalBusiness` + `BreadcrumbList` JSON-LD. |
| `/jeongwang-immigration-agent` | 정왕·정왕동 SEO 랜딩 | 서버 컴포넌트. 정왕 행정사 키워드 타겟. `LocalBusiness` + `BreadcrumbList` JSON-LD. |

### `/board` 페이지 — 카테고리 필터 관리

`board/BoardClient.tsx`의 주요 상수:
- **`BOARD_ONLY`** — `Set(["공지사항", "업무 안내", "제도 변경", "기타"])`. 서버에서 받은 전체 게시물 중 이 카테고리(또는 빈 카테고리)만 `/board`에 표시. 46개 준비서류 게시물(카테고리: 준비서류 안내 등)은 이 필터로 자동 제외됨.
- **`CATEGORIES`** — 카테고리 필터 버튼: `["공지사항", "업무 안내", "제도 변경", "기타"]`. `/board`에 새 일반 카테고리 추가 시 BOARD_ONLY 세트와 CATEGORIES 배열 둘 다 업데이트.

### `/documents` 페이지 — 준비서류 그룹 관리

`documents/DocumentsClient.tsx`의 `GROUPS` 배열:
- 각 그룹: `{ id, group, items: [{label, href}] }`. `id`는 앵커 ID (예: `"f4"`, `"nationality"`)
- 링크는 `/board/{slug}` 형식. 새 준비서류 게시물 추가 시 여기 항목도 추가해야 /documents에 표시됨.
- 그룹 순서: F-1 → F-2 → F-3 → F-4 → F-5(영주권) → F-6 → H-2 → 국적/귀화 → 중국공증
- 앵커 ID 매핑: F-1=`f1`, F-2=`f2`, F-3=`f3`, F-4=`f4`, F-5=`f5`, F-6=`f6`, H-2=`h2`, 국적/귀화=`nationality`, 중국공증=`china-notarization`
- `scrollMarginTop: 80` — 내비게이션 바에 의한 앵커 가림 방지

### 홈페이지 `업무별 준비서류` 섹션

`app/page.tsx`의 `DOCUMENT_GROUPS` 상수 — 9개 체류자격 카드. 각 카드: `{ label, anchor }`. 클릭 시 `/documents#${anchor}`로 이동. `/documents` 페이지의 `GROUPS[*].id`와 앵커가 일치해야 함. 두 파일을 수정할 때 앵커 ID 동기화 필수.

### 관리자 UI (`frontend/app/(main)/marketing/`)

- `/marketing` — 게시물 목록, 게시 토글(배지 클릭), 삭제
- `/marketing/new` — 새 게시물 작성: RichEditor 본문 + 썸네일 업로드 (저장 후 미게시 상태)
- `/marketing/[id]/edit` — 수정 및 게시 상태 직접 변경: RichEditor 본문 + 썸네일 업로드

**접근 제어**: 각 페이지 `useEffect`에서 `user?.is_admin` 확인 → 비관리자는 `/dashboard`로 리다이렉트. 백엔드도 `is_admin` 이중 검사.

### CSS 격리 주의사항

`homepage.css`를 `app/page.tsx`에서 import하면 Next.js는 해당 CSS를 페이지 이동 후에도 `<link>`로 유지한다. 내부 앱과 충돌하는 CSS 변수는 `--hp-` 접두사로 격리해야 함. 현재 격리된 변수: `--hp-radius` (12px), `--hp-radius-sm` (8px).

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
- `fee_rule` 표준 형식 (2026-04-19 전수 정규화 완료):
  - EXTEND: `"기본 6만원"` (일반), `"인지세 6만원"` (F-4), `"수수료 없음"` (특수 프로그램)
  - CHANGE: `"기본 10만원"` (일반), `"인지세 20만원"` (F-5), `"수수료 없음"` (K-STAR/최우수인재/지역특화형/난민/H-2)
  - REGISTRATION: `"외국인등록증 발급 및 재발급 3만5천원"`
  - REENTRY: `"단수 3만원 | 복수 5만원"` (일반), `"수수료 없음 (재입국허가)"` (G-1 등)

### 현재 F-5 영주 항목 (2026-04-19 기준)
기존 K-STAR·최우수인재 외 추가된 일반 영주 항목:
- `F-5-1` CHANGE — 국민의 배우자·자녀 (5년 이상 합법체류)
- `F-5-2` CHANGE — 미성년 자녀
- `F-5-6` CHANGE — 결혼이민자 (F-6 기반)
- `F-5-10` CHANGE — 재외동포(동포영주) — F-4로 2년 이상 체류
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
# 5. 서버 재시작 필수 — uvicorn --reload는 JSON 파일 변경을 감지하지 않음
```

**방법 B — JSON 직접 수정 (소규모 행 추가/수정 시):**

`analysis/클로드/서버설정/add_missing_rows_v*.py` 패턴의 스크립트를 작성해 JSON을 직접 패치한 뒤 migrate만 실행:
```bash
python "analysis/클로드/서버설정/fix_스크립트이름.py"
python backend/scripts/migrate_guidelines_v2.py
```
새 행 필수 필드: `row_id`, `domain`, `major_action_std`, `action_type`, `business_name`, `detailed_code`, `form_docs`, `supporting_docs`, `fee_rule`, `basis_section`, **`"status": "active"`** (영문 필수), `search_keys: []`, quickdoc 필드 4개(null로 초기화 후 migrate가 채움).

**실무 확장 필드** (선택, DetailPanel에서 자동 렌더링):
- `practical_notes` — 실무 주의사항 (`|` 구분). 최소 3항목. DetailPanel에서 파란 배경 목록으로 표시.
- `sub_types` — 조건별 분기 배열. 타입: `GuidelineSubType[]` (`frontend/lib/api.ts`에 정의). L4 분기 선택 UI 자동 표시.
- `step_after` — 허가 후 다음 단계 (`|` 구분). 초록 배경 번호 목록으로 표시.
- `apply_channel` — 신청 경로 안내 (예: `"전자민원 또는 창구민원"`). 헤더 뱃지로 표시.
- `form_docs` 채널 분기 형식: `"【전자민원】A|B||【창구민원】C|D"` → `parseChannelDocs()` 함수가 파싱하여 탭별 표시.

**방법 C — 브랜치 일괄 패치 스크립트 (권장):**
`backend/scripts/patch_donpo_v1.py`, `patch_donpo_v2_full.py` 패턴으로 스크립트 작성 후 실행:
```bash
python backend/scripts/patch_branchname_v1.py
python backend/scripts/migrate_guidelines_v2.py
# 서버 재시작 필수
```

### 실무지침 페이지 트리 탐색 구조 (`frontend/app/(main)/guidelines/page.tsx`)

4단계 드릴다운: **L1(진입점 그리드)** → **L2(업무유형 카드)** → **L3(항목 목록)** → **L4(조건 분기)**.

- `viewMode`: `"l1"` / `"l2"` / `"l3"` / `"search"` — 검색어 입력 시 별도 search 뷰
- `skipL2`: `treeL2Items.length <= 1`이면 L2 스킵 → L3 직행 (단일 action_type 진입점)
- **preload-all 아키텍처** — 마운트 시 `Promise.all([getEntryPoints(), list({ limit:500, status:"all" })])` 동시 호출. 두 API 모두 `.catch(() => [])` 로 감싸져 있어 실패 시 빈 배열 반환. `allRows`에 전체 rows 캐시. 진입점 클릭은 `getMatchingRows(allRows, entry)` 클라이언트 필터만 실행.
  - `loadEntryRows(entry, rows)` — `getMatchingRows(rows, entry)`를 호출하고 결과를 `setCurrentEntryRows`에 저장. 코드 기반 진입점(`/^[A-Z]-[0-9A-Z]/i`): `detailed_code.startsWith` 필터. 업무 기반: `action_types` Set 필터.
  - **카드 count와 클릭 결과 반드시 동일한 소스 사용**: `entryRowCounts`는 `allRows.length > 0`이면 `getMatchingRows(allRows, ep).length`로 계산, 로딩 중에만 `ep.count`를 임시 표시. 두 소스가 달라지면 "9건" 카드 클릭 시 0건이 표시되는 버그 발생 (2026-04-26 수정).
  - **`allRows` 비어있을 때 fallback**: `handleEntryClick`에서 `allRows.length === 0`이면 `list({ limit:500, status:"all" })`을 재요청한 뒤 `loadEntryRows` 실행. `list` API silent fail 시 카드 클릭이 0건을 표시하는 버그 방지.
- **`_ENTRY_POINTS_DATA`** (백엔드 `guidelines.py`): **14개** 진입점. 코드 기반 6개(F-5/F-4/E-7/D-2/H-2/F-6) + 업무 기반 7개(REG/REEN/EX/WP/GR/VC/DR) + AC(직접신청). **F-2는 백엔드에 없음** — 프론트엔드 fallback `ENTRY_POINTS`에는 있지만 API 응답이 오면 덮어씌워짐.
- 직접 검색 (`doSearch`)은 서버사이드 `GET /api/guidelines/search/query?q=...`를 호출하므로 `allRows` 상태와 무관하게 동작.
- **L4 조건 분기** — `row.sub_types?.length > 0`이면 DetailPanel 상단에 "어떤 경우인가요?" 분기 버튼 표시. 선택 시 해당 sub_type의 `form_docs`/`supporting_docs`/`practical_notes`로 교체. `selectedSubType` 상태로 관리.
- **`parseChannelDocs(raw)`** — `form_docs`에서 `【전자민원】`/`【창구민원】` 마커를 파싱하여 `{online, counter, simple}` 반환. 채널 구분 없는 기존 형식은 `simple` 배열로 반환.
- DetailPanel 섹션 렌더링 순서: 신청경로 뱃지 → 문서자동작성 버튼 → L4 분기 선택 → 사무소 준비서류(채널별) → 고객 준비서류 → 인지세 → 실무 주의사항(`practical_notes`) → 예외사항 → 공통 조건부 예외 → 다음 단계(`step_after`) → 근거 → 결핵 경고.

---

## In-progress / known issues

### 실무지침 DB
- **fee_rule 전수 정규화 완료** (2026-04-19)
- **동포 브랜치 Phase 1 완료** (2026-04-30) — H-2(4개) + F-4(9개) + F-5 동포경로(8개) 총 21개 rows에 `practical_notes`·`sub_types`·`step_after`·`apply_channel` 추가. F-5-10(재외동포 동포영주)에 5개 sub_types(4대보험·일용직·사업자·재산세·자산). 나머지 브랜치(F-6·E-7·D-2·REGISTRATION·EXTRA_WORK 등) 동일 기준 적용 예정.
- **완전성 체크리스트** — 각 row가 C1(대상자)~C9(신청경로) 9개 항목 충족해야 초급자 실무 사용 가능. `backend/scripts/patch_*` 스크립트로 브랜치별 일괄 패치.
- **JSON 변경 후 서버 재시작 필수** — `_MASTER_ROWS`는 모듈 임포트 시 1회 로드. `uvicorn --reload`는 `.json` 파일 변경을 감지하지 않으므로 수동 재시작 필요.

### manual_ref 매핑 정밀도
- **v3 apply 1차 완료** (2026-04-30): 369 row 중 139 row의 `manual_ref` 정밀화 적용. 백업: `backend/data/backups/immigration_guidelines_db_v2.manual_ref_backup_20260430_231933.json`.
- **잔여 후속 작업**:
  - 사용자 명시 4건 (F-1-15/21/22/24, 정답 = 체류 p.543 + 사증 p.404)을 `manual_indexer_v6.MANUAL_PAGE_OVERRIDE`에 추가 → 재빌드 → 별도 apply 사이클
  - 보호 카테고리 199 row (ROUTING_SAFE_REVIEW 21 / MANUAL_REVIEW 43 / LOW_CONFIDENCE 126 / NO_CANDIDATE 2 / APPLICATION_CLAIM_REVIEW 7) 사람 검토
  - 사후 이상치 188 row (HIGH priority 115)의 cluster별 정답 페이지 수집 + override 누적 (F-1 size-23 cluster, F-2/F-4 family cluster, H-1 wrong-primary-manual 등)
  - blocklist 12 row(D-2-X/D-4-1/D-4-7/M1-0005/M1-0085 모두 EXTRA_WORK false positive)는 자격 설명 페이지가 잘못 매핑된 케이스 — 정확한 EXTRA_WORK 페이지 확인 후 override 추가 또는 blocklist 해제 결정
- **manual_ref 외 필드 절대 미수정 보장**: apply 스크립트는 `db_row["manual_ref"] = ...` 한 줄만 수행, verify 스크립트가 369 row 전수 비교로 검증.

### OCR / 스캔
- **OCR debug mode active** — `/api/scan/passport` and `/api/scan/arc` (full-auto endpoints) still wrap responses in `{"debug": ..., "result": {...}}`. The scan workspace endpoints (`/api/scan-workspace/*`) return clean `{"result": {...}}`. Remove the debug wrapper from the full-auto endpoints when tuning is complete.
- **ARC address accuracy** — geometry-first pipeline + dated-row parsing active in `ocr_service.parse_arc`. `_debug_geometry` key in response contains `divider_frac`, `coarse_confidence`, `addr_source`, `ambig_winner` for diagnosis.
- **OmniMRZ vestigial** — installed in `Dockerfile.backend` from source but never called at runtime (prewarm disabled). Can be removed once Tesseract-only path is confirmed sufficient.

### 기타
- **Windows local dev** — `backend/main.py` forces stdout/stderr to UTF-8 on Windows to prevent Korean characters appearing as `???` in uvicorn logs. Do not remove this block.
- **`react-zoom-pan-pinch`** — still in `frontend/package.json` but unused. Safe to remove. Do not reintroduce it in the scan page.
- **메뉴얼 업데이트 자동감지** — `GET /api/board/check-manual`은 관리자가 게시판에서 수동 트리거. 스케줄러 없음. 하이코리아 페이지 스크랩(`requests`)으로 날짜 추출 — 페이지 구조 변경 시 정규식 수정 필요.

---

## 매뉴얼 자동화 파이프라인 (2026-04-30 구축)

하이코리아의 공식 HWP 매뉴얼을 자동 다운로드 → 잠금해제 → PDF 변환 → 페이지 매핑까지 처리하는 파이프라인. 매뉴얼 PDF는 `backend/data/manuals/`에 저장.

### Phase A — HWP 잠금해제 (`backend/services/hwp_unlock.py`)

배포용(distribution) HWP의 진짜 보호 메커니즘:
- `FileHeader` bit 2 = 1
- `BodyText/Section*` = 빈 stub (314바이트)
- `ViewText/Section*` = LEA-128 암호화된 본문 + `HWPTAG_DISTRIBUTE_DOC_DATA(0x1C)` 256바이트 키 record
- 단순 비트 토글로는 한컴이 손상으로 인식

해결: `OpenHwpExe.exe`(분석 폴더, .NET) 의 `Main.ConvertFile()` 메서드를 **subprocess + DoEvents 폴링**으로 호출.
- WinForms async Task는 메시지 펌프 필요 → `Application.DoEvents()` 폴링으로 처리
- subprocess 분리: Form 인스턴스 재사용 시 deadlock 방지
- 의존성: `pythonnet`, `olefile`, `OpenHwpExe.exe + HwpSharp.dll + OpenMcdf.dll` (analysis/클로드/배포용 한글문서 변환기/)

### Phase B — 워치독 + PDF 변환 (`backend/services/manual_watcher.py`, `hwp_to_pdf.py`)

```
[하이코리아 폴링] → [HWP 다운로드] → [잠금해제] → [한컴 COM PDF 변환] → [캐시 갱신] → [게시판 자동공지(옵션)]
```

- 캐시: `backend/data/manuals/.watcher_state.json` — 매뉴얼별 last timestamp, 변경 감지 시에만 처리
- 첨부파일 다운로드 URL: `POST /fileNewExistsChkAjax.pt` (하이코리아)
- 정규식 `_FN_PATTERN`은 `,` 와 `'` 사이 공백 처리 (`,\s*'...'` 패턴)
- HWP→PDF는 한컴 COM(`HWPFrame.HwpObject`) 사용. 자동화 보안 우회: `RegisterModule("FilePathCheckDLL", "AutomationModule")`
- **2-up 자동 분할**: HWP 문서 자체가 가로 A4(841×595pt)에 두 페이지 모아찍기로 설정된 경우 PyMuPDF로 페이지 좌/우 분할 (`split_2up_landscape`). 비율 1.3~1.5 (≈√2)인 landscape만 분할 대상.

### Phase C — 매뉴얼 페이지 인덱서 v6 (`backend/services/manual_indexer_v6.py`)

매뉴얼 코드 표기 패턴 차이:
- **〔F-X-Y〕 정식 표기** = sub-category 시작 (강한 시그널)
- **(F-X-Y) 일반괄호** = 본문 인용 (약한 시그널, 노이즈 多)

알고리즘:
1. 〔F-X-Y〕 등장 페이지 추출 → sub-category 시작점
2. sub-category 영역 = 자기 시작 ~ 다음 〔??〕 시작 직전 (max 30페이지)
3. 모든 sub-category에 `CHANGE` 자동 강제 등록 (영주 sub-category 등 대부분 변경 케이스)
4. 일반 자격(F-4, H-2)은 점수 가중치 + 본문 연속 3+ 페이지 보호

**중요한 제약 — DB와 매뉴얼 코드 체계 불일치:**
- DB는 일반/시행령 표기 (예: `F-5-2 미성년 자녀`)
- 매뉴얼은 시행령 별표 1의3 호수 (예: `〔F-5-4〕 일반 영주자의 배우자/미성년 자녀`)
- 두 체계가 다름 → `DB_TO_MANUAL_ALIAS` 테이블 + `MANUAL_PAGE_OVERRIDE` 누적 테이블 사용

### 매핑 정정 누적 시스템

`backend/services/manual_indexer_v6.py` 상단:
```python
DB_TO_MANUAL_ALIAS = {
    "F-5-2": "F-5-4",  # DB code → 매뉴얼 code
}

MANUAL_PAGE_OVERRIDE = {
    "F-5-1|CHANGE": [{"manual": "체류민원", "page_from": 445, "page_to": 452, "match_text": "..."}],
    # 사용자가 알려주는 정답 페이지 누적
}
```

`lookup()` 우선순위: **MANUAL_PAGE_OVERRIDE → DB_TO_MANUAL_ALIAS → action_index → prefix → code_index 폴백**

사용자가 "row XX → 매뉴얼 X p.Y" 형식으로 알려주면 즉시 등록 가능. **override 테이블은 절대 자동 덮어쓰지 말 것** — 영구 누적 자산.

### Phase D — DetailPanel PDF 임베드 (`frontend/app/(main)/guidelines/page.tsx`)

`ManualPdfViewer` 컴포넌트:
- DetailPanel 왼쪽 floating 패널 (또는 전체화면)
- 매뉴얼별 탭 (체류민원/사증민원), 매핑된 페이지 자동 이동
- iframe URL: `/api/guidelines/manual-pdf/{manual}?token=${jwt}#page=${pf}&navpanes=0&pagemode=none&toolbar=1&view=Fit`
- `navpanes=0` + `pagemode=none`: Chrome/Edge PDF 뷰어 좌측 썸네일 패널 숨김

백엔드 PDF 서빙 (`backend/routers/guidelines.py`):
- `GET /manual-pdf/{manual}` — JWT 쿼리토큰 또는 Authorization 헤더 인증 (iframe은 헤더 못 보내므로 query 지원)
- `Content-Disposition` 헤더의 한글 파일명은 **RFC 5987** 형식 필수 (`filename*=UTF-8''...`) — latin-1 인코딩 한계 우회

### LLM 기반 매뉴얼 분석 인프라 (Phase 1)

**`backend/scripts/analyze_manual_structure.py`** — 매뉴얼 통째로 LLM 분석 (Claude Sonnet 4.6, 1M context):
- 매뉴얼 PDF 1권 (60만~70만자 ≈ 200k~240k tokens)을 청크 분할 없이 전달
- 출력: 자격별 시작/끝 페이지, sub-category 정식 페이지, action별 페이지, code alias
- 산출물: `backend/data/manuals/structure/{체류민원,사증민원}_structure.{json,xlsx}`

핵심 구현 사항:
- **streaming API 필수** (`client.messages.stream`) — 응답이 10분 초과 가능 시 SDK가 streaming 강제
- **max_tokens=64000** — 매뉴얼 분석 결과 잘림 방지
- **prompt caching** (`cache_control: ephemeral`) — 재호출 시 입력 비용 90% 할인
- **raw 응답 점진 저장** — 5초마다 누적 텍스트를 .txt에 저장, 중단 시 복구 가능

비용 추산: 체류민원 ~$2.5, 사증민원 ~$1.5 (1회 분석, 이후 엑셀 영구 활용)

### 청크 빌더 + 매핑 스크립트

- `backend/scripts/build_llm_chunks_v2.py` — v6 인덱스 활용 자격별 통합 청크 (매뉴얼+편람 텍스트)
- `backend/scripts/llm_remap_all.py` — 자격별 일괄 LLM 호출 (매핑+팁+수정), 중간 저장
- `backend/scripts/apply_llm_results.py` — LLM 결과 DB 적용, 자동 백업
- `backend/scripts/rollback_manual_ref_keep_tips.py` — 매핑만 백업으로 복원, 추가된 팁/수정은 유지

**LLM 매핑의 한계 (실증):** 청크 분할(25k chars 한계)로 자격 섹션 일부만 보고 잘못된 페이지 답변. **사용자 누적 override 방식이 더 정확.** 청크 LLM 호출은 실무 팁 추출에만 활용 권장.

---

## manual_ref 정밀화 파이프라인 v3 (2026-04-30 적용 완료)

LLM 매핑·v6 인덱서가 만든 `manual_ref` 결과를 사람 검토 후 안전하게 DB에 적용하는 멀티-단계 파이프라인. **DB는 항상 read-only로 시작하여 사람이 명시적 `--apply` 실행 시에만 변경**.

### 파이프라인 단계 (모두 `backend/scripts/`)

```
audit (v1)              ─┐
audit_v2 (라우팅)       ─┤  → triage_v3 (6 카테고리)
                         │      → apply_v3 dry-run
                         │          → spotcheck (PNG + 텍스트 미리보기)
                         │          → review_extra_work (엄격 검증)
                         │          → final_spotcheck (비-EXTRA_WORK)
                         │          → blocklist 누적 (사람 결정)
                         │              → apply_v3 --apply (실제 DB 갱신)
                         │                  → verify (12개 검증 항목)
                         │                      → audit_post_apply_anomalies (사후 이상치)
                         └─ 산출물: backend/data/manuals/manual_mapping_*.json/.xlsx
```

### 핵심 스크립트

| 스크립트 | 역할 |
|---|---|
| `audit_manual_mapping.py` | DB의 현재 manual_ref vs PDF/structure/CSV 후보 비교, 신뢰도(`exact/high/medium/low/none`) 부여 |
| `audit_manual_mapping_v2.py` | **action_type 우선 라우팅** — VISA_CONFIRM→사증, 그 외→체류. v1의 매뉴얼 라우팅 false positive 해소 (E-9 conflict 20→0, F-1 17→6) |
| `triage_manual_mapping_v3.py` | 6 카테고리 분류: `AUTO_SAFE`(apply 후보) / `ROUTING_SAFE_REVIEW` / `MANUAL_REVIEW` / `LOW_CONFIDENCE` / `NO_CANDIDATE` / `APPLICATION_CLAIM_REVIEW` |
| `apply_manual_mapping_triage_v3.py` | **DEFAULT: dry-run.** `--apply` 명시 시 실제 DB 갱신. 백업 + JSON 사전·사후 검증 + master_rows 보존 검증. blocklist 자동 적용. |
| `build_spotcheck_v3.py` | AUTO_SAFE changed 행에서 검토용 표본 추출 + PDF 페이지 PNG 렌더링 (`spotcheck_pages_v3/<row_id>_<manual>_p<N>.png`) |
| `review_extra_work_v3.py` | EXTRA_WORK 엄격 검증 — 자격 설명 페이지(p.35형 false positive)를 BLOCK으로 자동 surfacing |
| `final_spotcheck_v3.py` | 비-EXTRA_WORK action_type(CHANGE/EXTEND/REGISTRATION/REENTRY/GRANT) 동일 검증 |
| `verify_apply_v3.py` | apply 직후 12개 항목 검증 (백업·DB 무결성·139 갱신·12 blocked 무변경·199 보호 카테고리 무변경·manual_ref 외 필드 무변경 등) |
| `audit_post_apply_manual_ref_anomalies_v3.py` | 적용 후 5개 이상치 패턴 검출 — `SAME_PAGE_CLUSTER` / `DUAL_MANUAL_SUSPICIOUS` / `WRONG_PRIMARY_MANUAL` / `BROAD_FAMILY_PAGE` + 사용자 명시 HIGH |

### blocklist 시스템 (`backend/data/manuals/manual_mapping_apply_blocklist_v3.json`)

```json
{
  "blocked_row_ids": ["M1-0029", "M1-0030", ...],
  "reason": "...",
  "notes": ["..."]
}
```

- apply 스크립트가 매 실행 시 자동 로드. JSON malformed면 abort.
- 사람 검토 결과 false positive로 확인된 row_id를 누적.
- **blocklist는 candidate에서 제외되지만 DB에서 삭제하지 않음** — 단순히 갱신을 보류.
- 현재 차단된 12 rows: D-2-1~D-2-8 EXTRA_WORK + D-4-1/D-4-7 EXTRA_WORK + M1-0005 D-2 EXTRA_WORK + M1-0085 F-3-2R EXTRA_WORK (모두 자격 설명 페이지로 매핑된 false positive).

### 백업 디렉토리 (`backend/data/backups/`)

`apply --apply` 실행 시마다 `immigration_guidelines_db_v2.manual_ref_backup_<YYYYMMDD_HHMMSS>.json` 생성. 복구 명령:
```bash
cp "backend/data/backups/immigration_guidelines_db_v2.manual_ref_backup_<TS>.json" "backend/data/immigration_guidelines_db_v2.json"
```

### 안전 보장 (apply 스크립트의 8중 검증)

apply candidate은 다음 모두 충족해야 함:
1. `triage_category == "AUTO_SAFE"` 2. `apply_candidate == true` 3. `comparison_status == "changed"` 4. `confidence ∈ {exact, high}` 5. `routing_warning` 비어있음 6. `comparison_reason ≠ "both_manuals_plausible"` 7. `action_type ≠ "APPLICATION_CLAIM"` + `detailed_code` 비어있지 않음 8. `proposed_manual_ref` 가 valid `{manual ∈ {체류,사증}, page_from > 0, page_to > 0}`

`--apply` 추가 안전망:
- 백업 생성 + JSON readback 검증 (실패 시 abort)
- 메모리상 갱신 후 직렬화 + master_rows 개수 보존 검증
- 디스크 쓰기 후 readback 재검증
- 어느 단계 실패라도 abort + 복구 명령 출력
- candidates에 blocked_id가 섞이면 즉시 abort (이중 안전망)

### `manual_ref` 외 다른 필드는 절대 변경되지 않음

apply 스크립트는 `db_row["manual_ref"] = t["proposed_manual_ref"]` 한 줄만 수행. `business_name`, `form_docs`, `supporting_docs`, `practical_notes`, `sub_types`, `step_after`, `apply_channel`, `quickdoc_*`, `search_keys`, `fee_rule`, `basis_section`, `status` 등 모두 무수정. verify 스크립트가 369 row 전수 비교로 보장.

### 적용 결과 (2026-04-30)

- **AUTO_SAFE 170 → blocklist 12 제외 → 139 row 갱신** (전부 `manual_ref` 페이지 정밀화)
- 19 row는 `comparison_status=same` (변경 불필요)
- 199 row는 보호 카테고리(ROUTING_SAFE_REVIEW 21 / MANUAL_REVIEW 43 / LOW_CONFIDENCE 126 / NO_CANDIDATE 2 / APPLICATION_CLAIM_REVIEW 7) — 모두 사람 추가 검토 대기 중

### 사후 이상치 (2026-04-30 검출)

- 사용자 명시 4건 (F-1-15/21/22/24 EXTEND/VISA_CONFIRM): 정답 = 체류 p.543 + 사증 p.404. **CREATE_MANUAL_OVERRIDE** 필요 — `manual_indexer_v6.MANUAL_PAGE_OVERRIDE` 테이블에 추가 후 재빌드 권장.
- 188 row가 `MANUAL_REVIEW` 권장 (115 HIGH priority): 대부분 F-1/F-2/F-4/E-7/E-9/D-1/H-1 family 클러스터로 같은 페이지 공유. 적용 안 된 legacy 부정확 매핑 + 적용된 일부 cluster 포함.
- `RESTORE_FROM_BACKUP` 권장: **0건** — apply는 일관되게 좁은 페이지로 정밀화함.

---

세션별 수정 이력: @docs/session-log.md

---

See CLAUDE_MANUAL_REF.md for manual_ref improvement pipeline status and next tasks.
