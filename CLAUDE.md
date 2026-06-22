# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 출입국관리 v2 — 최신 확정 기준 (authoritative; 충돌 시 이 절이 우선)

이 절은 현재 확정된 v2 운영 기준을 요약한다. 아래 본문(상세)과 충돌하면 **이 절이 우선**한다.

### 1. 확정 스택
- **Next.js SSR (frontend) + FastAPI (backend) + PostgreSQL.** Render Docker 단일 컨테이너(`Dockerfile.combined`: `uvicorn backend.main:app` + `next start`, 현재 uvicorn worker 1개).
- **운영 source of truth = PostgreSQL.** Google Drive는 일부 파일/이미지 보조에만 사용.
- 인증 = JWT(8h) + PG 계정/세션 검증. PII는 Fernet 암호화(복호 가능) + HMAC 검색 + 마스킹.

### 2. 폐기된 과거 기준 (문서에 사실로 다시 쓰지 말 것 — "legacy/forbidden"로만 언급)
- "모든 비즈니스 데이터는 Google Sheets/Drive에 있다" / **Google Sheets 런타임 source** — 폐기. 운영 도메인은 PG-only.
- "marketing/board는 Sheets" / "Render PG marketing/board는 stale snapshot" — 폐기. **public marketing/`/board`는 PG-only (Phase H).**
- "지금 4분리한다" / "Frontend를 Static Site로 분리" — 폐기. 아래 단계 전략(A→B-1→B-2→C) 따른다.
- "OCR과 문서생성은 무조건 같은 Heavy로 묶는다" — 폐기. **Heavy는 OCR 전용으로 시작**, quick-doc은 섞지 않음.
- "quick-doc은 순수 처리기" — 폐기. quick-doc은 **DB + 복호화 키 + audit 바인딩**.
- Streamlit 런타임 / "Streamlit으로 되돌린다" — 금지. `pages/`·`app.py`는 reference 전용.
- Hancom watcher / OpenHwpExe / win32com / 로컬 HWP 상시저장 — 서버에서 금지(deprecated, server에서 env-gated OFF).
- "device fingerprint 기반 베타 사용제한" — 폐기. 계정공유 탐지는 distinct-device 게이트 + 로그인 이력 기반.

### 3. 서버 분리 단계 전략 (지금 바로 4분리하지 않는다)
- **A안 (현재/클로즈드 베타 우선):** combined 단일 컨테이너 유지 + uvicorn worker 2~3개 + OCR/DOC 동시수 제한. 4분리 안 함.
- **B-1 (유료 베타 직전 검토):** combined + **OCR Heavy(HTTP)** = 2 서비스. **Heavy는 OCR 전용** — quick-doc은 Heavy에 섞지 않는다.
- **B-2:** Frontend(SSR) / Backend(API) / Heavy = 3 분리.
- **C:** 4 분리(최종).
- **Heavy 인증 = 1안(DB 읽기 인증):** Heavy에는 `DATABASE_URL` + `JWT_SECRET_KEY`만 주고 DB로 토큰/계정 검증. **PII 복호화 키 불필요, DB write 없음.** JWT-only 검증(우회 위험)은 금지. 파일은 multipart 직접 전송.
- **DOC_GLOBAL_CONCURRENCY=1** (문서생성 전역 동시수 1).

### 4. Marketing / Board (PG-only)
- public 홈페이지 marketing + `/board`는 **PG-only (Phase H)**: `marketing_pg_service`(`MarketingPost`, `get_sessionmaker`). board 페이지·`sitemap.ts`는 SSR로 `/api/marketing/posts`를 읽음.
- 내부 게시판 `board_posts`/댓글(별개 기능)과 signatures만 여전히 flag-gated/Sheets-mixed.

### 5. OCR vs 문서생성 분리 원칙
- **OCR 엔드포인트**(`backend/routers/scan_workspace.py`: `/passport`, `/arc`, `/render-pdf`)는 **순수 처리기** — `get_current_user` + `roi_ocr_service` + Tesseract만. DB/복호화/PII 키 **없음** → Heavy로 떼어내기 적합.
- **quick-doc**(`backend/routers/quick_doc.py`)은 DB read + PII 복호화 + audit 바인딩 → Heavy로 보내지 않음. combined에 유지.

### 6. 보안 / 계정공유
- 계정공유 탐지(`account_security_pg_service`): SUSPICIOUS 카운트는 마지막 `ACCOUNT_SECURITY_UNBLOCKED` 이후만 집계, 기준 ①②는 `distinct_devices >= 2` 게이트(단일기기 재로그인 오탐 방지). login_events/account_security/security_notifications + 로그인 이력.
- 로그인 lockout, audit, 약관(terms), tenant guard, 외국인등록번호 뒷자리(reg_back) 암호화 적용.
- **비밀값(키/DB URL/비밀번호)은 이 문서에 절대 적지 않는다.** 환경변수 이름만 언급.

### 7. 운영 금지사항 (명시 승인 전 금지)
- 운영 DB 접속/`alembic upgrade`(운영) / Render 운영 호출 / 배포 / push / migration 실행 / env 변경 — 모두 **명시 승인 전 금지**.
- 실고객 PII·이미지를 테스트에 사용 금지. production `DATABASE_URL`을 파일/문서에 기록 금지.

---

## Project identity

**K.ID SaaS** — internal immigration office (출입국) management platform for Hanwory Administrative Office.  
Architecture (v2): **Next.js SSR (frontend) + FastAPI (backend) + PostgreSQL**, hosted on **Render Docker** (`Dockerfile.combined` single container running `uvicorn backend.main:app` + `next start`). **운영 source of truth = PostgreSQL.** Google Drive는 일부 파일/이미지 보조 저장에만 사용하며, **Google Sheets는 런타임 source가 아니다** (marketing 등 이전 Sheets 경로는 PG로 이관됨 — 아래 v2 기준 참조). Public domain: https://www.hanwory.com

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
- Containers: `kid-backend` (:8000, source **bind-mounted** `.:/app`, **no `--reload`** → run `docker compose restart backend` to load Python changes), `kid-frontend` (:3000, **built image** → `docker compose build frontend && docker compose up -d frontend` for FE changes), `kid-postgres-local` (host **:5433** → 5432).
- `DATABASE_URL` is injected via **git-untracked `docker-compose.override.yml`** (local dev value `<LOCAL_DB_SETTING_PLACEHOLDER>` — never record the actual value or a connection-string form in this doc), kept out of git via `.git/info/exclude`. The same override also injects **`KID_PII_ENCRYPTION_KEY`** (local-only Fernet key for `agent_rrn` — see PII encryption section). Container JWT secret defaults to a local placeholder `<LOCAL_AUTH_TOKEN_PLACEHOLDER>`.
- **git-bash gotcha:** `docker exec … python /app/…` rewrites `/app` to a Windows path — prefix with `MSYS_NO_PATHCONV=1`. Korean request bodies via `curl` on Windows can 400 ("error parsing the body") — prefer ASCII HTTP, or call router/service functions directly via `docker exec … python -c` for Korean-safe checks.

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

### Public SEO (`frontend/app/sitemap.ts`, `layout.tsx`)

`sitemap.ts` is `export const dynamic = "force-dynamic"` (was previously baked static-empty at build → only 5 URLs). At request time it fetches `${API_URL || "http://127.0.0.1:8000"}/api/marketing/posts` (the same call `/board` uses — must NOT fall back to `localhost`, which resolves to IPv6 `::1` and fails) and emits the 5 static public URLs + one **`encodeURIComponent`-encoded** `/board/{slug or id}` per *published* post. Board detail `canonical` is absolute via `metadataBase` in `layout.tsx`; `title` uses `{ absolute: ... }` to avoid double-suffixing the template. `/posts` 308-redirects to `/board` (`next.config.js`). `robots.txt` is static.

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

**Render modes** (`fill_and_append_pdf(..., render_mode=...)`, `FullDocGenRequest.render_mode`):
- **`acroform`** (default fallback) — native AcroForm: set `widget.field_value` (`/V`) + `widget.update()`. Fields stay live.
- **`field_ap`** — **the current "보기안정형" mode the frontend sends** (`QuickDocPanel` hardcodes `render_mode: "field_ap"`; the old "보기안정형/영문도장" checkboxes were removed). **Preserves Text widgets** (no flatten/delete) with clean `/V` (no injected spaces), and rewrites each Text field's **`/AP /N` content stream** with a unified appearance: short ASCII values → fixed-cell **standard pitch** (`_AP_STD_CELL_EM`, calibrated to the 통합신청서 `yyyy` box ≈ 13.4pt) centered as a block (NOT full-field-width); Korean/long/multiline (address family) → native AP; `AcroForm /NeedAppearances=false` so all viewers honor the custom AP. `generate_full` runs **`validate_field_ap_output()`** on the merged PDF and **500s if Text-field count is 0 or any `/V` has injected spaces** (PDF is not returned on failure). Survives `merged.insert_pdf`.
- **`overlay` / `overlay_legacy`** — **deprecated** flatten renderer in `backend/services/pdf_style.py` (`draw_overlay_text`): overlays text at widget coords then **deletes Text widgets** (fields die). Dev/rollback fallback only — never route the UI to it. (Earlier iterations' `letter_spacing` / `distribute` cell-layout live here.)

**Seal auto-detection** (`make_seal_bytes` + `_auto_role_seal`): when a role's "도장 넣기" is on, the seal type is auto-picked per role (not a user toggle): **Korean name present → Korean seal (priority even if English exists); else English initials present → English vertical-stacked seal (`_LATIN_X_SCALE` widens Latin glyphs); else skip** (normal, not an error). Applied uniformly to `applicant`/`accommodation`/`guarantor`/`guardian`/`aggregator` (English source = each role dict's `성`/`명`; applicant uses guardian when minor); `agent` uses the Korean office contact name only. Debug log emits per-role reason (`korean`/`english`/`no_name`/`disabled`) with **no PII**.

### Agent RRN encryption (PII, `backend/services/pii_crypto.py`)

행정사 주민등록번호(`agent_rrn`) is stored **encrypted, decryptable** (Fernet) — `tenants.agent_rrn_encrypted` is the **PDF output source**; the older `agent_rrn_hash` is one-way and **must NOT be used for output**. `agent_rrn_last4` is display-only. Key from env **`KID_PII_ENCRYPTION_KEY`** (fallback `AGENT_RRN_ENCRYPTION_KEY`), **never committed** (local: gitignored `docker-compose.override.yml`). Admin endpoints `GET/PUT /api/admin/accounts/{login_id}/agent-rrn` return **status only (`has_agent_rrn`/`last4`)** — never plaintext; empty value = delete; key missing → 503; bad format → 400. `quick_doc._load_account` decrypts into `field_values["agent_rrn"]`; **decrypt failure / missing key → blank, never crash the PDF, never log plaintext.**

**Signup (`auth.py` `_prepare_agent_rrn_fields`) is fail-closed**: if `agent_rrn` is provided it is validated + encrypted **before any account row is created** — bad format → **400**, key missing/encrypt fail → **503** ("주민등록번호 보안 저장 설정이 완료되지 않아…", no key name leaked), so a failed RRN never produces a half-created tenant/user. Empty `agent_rrn` → signup proceeds normally. Both `<YYMMDD>-<BACK7>` and `<YYMMDDBACK7>` forms are accepted (normalized to digits — no literal number example kept in this doc). Admin approval (`provision_workspace`) only flips `is_active`/sheet keys → the encrypted RRN persists through approval.

### Signature system (`backend/routers/signature.py`, `backend/services/signature_service.py`)

Three separate Sheets tabs:
- `"행정사서명"` in `SHEET_KEY` — agent signature, key: `tenant_id`. **Saved immediately on submit**.
- `"고객서명"` in `customer_sheet_key` — customer signature, key: `고객ID`. Also saved immediately. **Delete** via `DELETE /api/signature/customer/{customer_id}` (`signature_service.delete_customer_signature`, PG/Sheets dispatch) — removes only the applied signature row; **temp slots 1·2·3 and customer profile are untouched**. `customer_sheet_key` is resolved from the logged-in `tenant_id` only → no cross-tenant delete.
- `"서명임시저장"` in `SHEET_KEY` — temp slots 1–3, key: `(slot, tenant_id)`.

**Token architecture:** Customer tokens are stateless HMAC; agent tokens use an in-memory `_pending` dict.

`has_customer_signature()` raises `SignatureLookupError` on Sheets API failure (not silent False). The exists endpoint returns HTTP 503 on lookup failure — frontend must not interpret 503 as "no signature".

**Agent signature cache:** `signature_service.py` has a 60-second TTL cache (`_agent_sig_cache`) for `get_agent_signature()`. Cache is invalidated by `save_agent_signature()`. The `/api/signature/agent` route returns HTTP 503 (not `{"data": null}`) on Sheets failure so the frontend can distinguish real absence from errors.

### 전자명함 (business card, PG-only — `backend/routers/business_card.py`, `business_card_pg_service.py`)

계정별 공개 명함. 데이터는 `tenants.card_*`(migration 0015) + 로고 파일 `tenants.card_logo_*`(0016, `card_logo_bytes` BYTEA). **저장 즉시 공개 반영** — 개발자 커밋/배포 불필요(테넌트가 마이페이지에서 저장 → PG → 공개 페이지가 요청 시 PG read).
- 마이페이지 편집: `PATCH /api/my/business-card`. **응답·`get_my_card` 모두 `raw` 블록(card_phone/address/logo_url/work_fields)을 포함**해야 한다 — 프론트 편집칸이 `raw` 로 채워지므로 `raw` 누락 시 저장 직후 입력값이 사라진다(과거 버그).
- 로고는 **파일 업로드**(`POST /api/my/business-card/logo`, multipart). 서버 검증: JPG/PNG/WEBP만(Pillow 디코딩으로 실제 이미지 판별, 확장자/Content-Type 불신), ≤200KB, BYTEA 저장. 삭제 `DELETE …/logo`. 소유자 미리보기 `GET …/logo`(Bearer), 공개 `GET /api/public/business-card/{slug}/logo`(무인증). 한우리 fallback 금지 — 없으면 로고 영역 생략.
- 공개 페이지 `frontend/app/card/[slug]/page.tsx`: 표시용 `<img>`는 **상대경로**(어느 호스트에서나 로드), **og:image 만 절대 URL**(`https://www.hanwory.com/...`, 외부 메신저 접근). 우선순위 = 업로드 로고 > `card_logo_url`(외부, 하위호환) > 없음. slug 규칙 `^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$`(3~50자) — 프론트/백엔드 동일.

### 실무지침 + 매뉴얼 업데이트 (guidelines / Manual Update v1)

**실무지침 data is NOT in Sheets/PG.** `backend/routers/guidelines.py` loads `backend/data/immigration_guidelines_db_v2.json` **once at module import** into process memory (`_MASTER_ROWS`/`_ROW_INDEX`/…); `/api/guidelines/*` serves it. So the 실무지침 page shows whatever JSON is baked into the deployed image (`Dockerfile.combined` `COPY . .`) — it changes only on **redeploy** (or the ephemeral admin `PATCH /api/guidelines/{row_id}` edit). No TTL — fixed for the process lifetime.

**Two manual-update systems coexist — know which is which:**
- **Legacy Hancom watcher** (`services/manual_watcher.py` + `hwp_unlock.py` [OpenHwpExe.exe] + `hwp_to_pdf.py` [win32com]) — **Windows-only, deprecated.** `main.py`'s 12h APScheduler that ran it is **env-gated OFF when `RUN_ENV == "server"`** (logs "legacy … disabled on server"). Don't revive it, run it on the server, or re-add `win32com`/OpenHwpExe.
- **rhwp Manual Update v1** (server-friendly, going-forward path): `tools/rhwp_manual_pipeline/*.mjs` (Node; `@rhwp/core` is Rust+WASM and parses even hikorea **distribution-locked HWP without any unlock step**; `generate_pdf.mjs` also needs `playwright-core`+chromium) driven by `backend/scripts/manual_update_local.py`. Outputs `backend/data/manuals/staging/{version}/` (rhwp_text / diff/changed_pages / candidates / review_pdf_pages / manifest.json). Deps now live in `tools/rhwp_manual_pipeline/node_modules` (own `package.json`, `_lib.mjs` lazy-imports chromium). **Runtime constraint: the backend container & Render image have NO `node` — so any step that shells `node` (rhwp extract, `generate_pdf.mjs`) only completes on the host or a node-capable worker; detection/download (Python `requests`) works in-container.** `svgToPdf` in `_lib.mjs` sizes the chromium page to the SVG viewBox 1:1 (was `*96/72` → page bigger than SVG → content shrank to top-left); keep page==viewBox + `svg{width/height:100%}`.

**Operational manual_ref reflection = detect → staging review → explicit apply ONLY. Never auto-apply.**
- `backend/scripts/manual_ref_rematch.py` (`--report-only` writes `manuals/manual_update_review.json`) is the conservative page recommender. `_current_page_signals()` KEEPs the human page when **full `detailed_code`** (e.g. `F-1-15`, not just family `F-1`) OR **strong title** is on the current page, or candidate==current. **family code-prefix alone never KEEPs** → surfaced for review with `family_code_only` (+ `shared_generic_page` when many rows share one page). Human manual_ref is authoritative; candidates are reference-only. Prior review **decisions merge by `row_id`** on re-run (`_merge_prior_decisions`) — do not clobber them.
- Apply = `POST /api/manual/update-review/{row_id}/apply` (guard: only `REVIEWED_APPROVE_CANDIDATE`/`NEEDS_MANUAL_PAGE`; backs up DB then edits manual_ref `page_from/to` only). Staging review (read-only, admin): `/api/guidelines/manual-staging/*`. Admin UI tabs in `(main)/admin/page.tsx`: "매뉴얼 업데이트 검토" (rematch) + "매뉴얼 업데이트 v1 (staging)" (rhwp). Operational PDF viewer = `/api/guidelines/manual-pdf/{manual}` serving `manuals/unlocked_*.pdf` — **keep untouched**.

**Render filesystem caveat:** `analysis/` and root `backups/` are gitignored (not deployed). Render Cron Jobs run in a **separate instance with their own ephemeral FS** — artifacts a cron writes are not visible to the web service that serves the staging endpoints (drives the persistence/scheduling design).

### PG manual-update pipeline (`FEATURE_PG_MANUAL_UPDATE`, single source = PostgreSQL)

When the flag is on, the going-forward path is **PG, not files**. `backend/services/manual_auto_update.py:run_auto_update_pg()` = detect (hikorea fixed-post `NTCCTT_SEQ=1062` fetch → parse attachments → timestamp-compare vs `_seen_from_pg`) → **/tmp** download → `extract.mjs` (rhwp) → diff vs PG baseline → `svc.save_version()` (version/changed/candidates) → decision merge → **/tmp deleted** (source HWP never persisted). It NEVER touches operational `manual_ref`/PDF. Trigger: APScheduler daily 15:00 KST (`scheduled_job`, registered only when `FEATURE_MANUAL_AUTO_UPDATE` on) **plus** admin `POST /api/guidelines/manual-update/run-now {mode:"diagnose"|"record"|"generate_pdf_artifacts"}` (in-process lock → 409 on concurrent). `mode=diagnose` runs `run_auto_update_pg_dryrun()` (no PG write); `record`/`generate_pdf_artifacts` are gated by `GET /manual-update/capabilities` (`can_record_update`/`can_generate_pdf` require node — so they 409 in-container/Render, run on host/worker only).

- **Candidate classification** (`manual_update_pg_service._classify_candidate`): `change_kind` = new/page_moved/text_changed/uncertain/**noop**. A same-page `modified` candidate with overlapping-page similarity ≥ `NOOP_SIMILARITY` (0.95) is **noop** (실질 변경 없음 → excluded from `needs_review`). `needs_review`/state counts are recomputed from real pending review targets (not stale `state.needs_review`); `finish_no_change` resets the flag.
- **Reviewer page override** (migration `0013`, `manual_review_decisions.reviewer_*` cols): admin can override baseline/candidate page ranges + reason; auto-suggested pages (candidate table) are preserved separately. When set, diff/display/apply use the override pages. Decision save/apply NEVER edits the JSON until explicit `…/decisions/{row_id}/apply` (guard: APPLYABLE decisions only).
- **PDF artifacts** (migration `0014`, `manual_pdf_artifacts`, `pdf_blob` bytea + nullable `pdf_path`): `generate_pdf_artifacts_for_version()` renders changed pages ± neighbors via `generate_pdf.mjs --pages` (1 doc load), bundles per-candidate with PyMuPDF `insert_pdf` (1:1, preserves page size), stores blob. Served `GET /manual-update/pdf-artifacts/{id}/content` (`application/pdf`, `?token=` for iframe). **Viewer resolver**: whole-manual PDF = full_pdf artifact → staging file → `unlocked_*.pdf` fallback; candidate-detail PDF = changed_page(_bundle) covering the candidate range → full_pdf → fallback. No `full_pdf` artifact / page-replace into baseline yet (deferred) → whole-manual viewer still serves the deployed `unlocked_*.pdf`; `/manual-update/pdf-status` exposes this fallback reason transparently.
- Admin UI lives in `(main)/admin/page.tsx` `ManualUpdatePgView`: a 4-step workflow (① 업로드 → ② 변경감지 → ③ 검토 → ④ 운영 반영) with a 4-card status summary; developer/diagnostic cards (단계 진행·PDF 상태·자동실행) are in collapsed `🔧 고급·진단 정보` `<details>`, and the candidate table hides 신뢰도/매칭사유/row_id behind a `고급 컬럼` toggle.

**Admin PDF upload (the going-forward authoring path — `backend/services/manual_pdf_upload_service.py`).** Replaces HWP/node rendering on the server: admin uploads the latest PDF, the server only **stores + extracts text + diffs**. Endpoints (`backend/routers/guidelines.py`): `POST /manual-update/upload-pdf` (multipart; chunked temp-file write, ≤80MB, PyMuPDF open + page_count>0 validate, store blob as `staging_full_pdf`/`source=manual_upload`, then delete prior uploads/review_splice for that manual — **save-only, NO extract/diff**); `POST /manual-update/detect-changes` (the heavy step, **separate**: extract page text + **PDF-to-PDF** diff vs the previous **deployed** uploaded PDF, reuse `compute_candidates`/`save_version`); `POST /manual-update/promote-pdf` (staging→deployed, prior deployed→previous, rollback-able); `GET /manual-update/uploaded-pdf` (serve staging, iframe `?token=`). PDF-to-PDF (same Python extractor + same `normalize` both sides) avoids HWP-vs-PDF false positives; no deployed PDF baseline → `baseline_init` (no diff until first promote).
- **OOM hard rules (web container) — do not regress:** NEVER compose/splice a full PDF in a web request (`compose_full_pdf_blob`/`splice_changed_pages_into_full` must not be called from any router — `pg_pdf` serves uploaded→worker-artifact→deployed fallback, never auto-composes). NEVER bulk-`SELECT` `pdf_blob`: `get_pdf_artifacts`/`get_pdf_artifact`/`get_latest_pdf_artifact` use `defer(pdf_blob)`; `_artifact_to_dict.has_blob` uses the `file_size` proxy (must not touch `a.pdf_blob`); blob is fetched as a single row by id (`get_pdf_artifact_blob`). `generate_pdf.mjs`/node/playwright stay worker-only (node-gated → 409 in container).
- **Viewer resolver priority** (`pg_pdf`/`pg_pdf_source`/`pg_pdf_status`): admin **uploaded** PDF (staging `manual_upload` → promoted `deployed`) → worker `full_pdf` artifact blob → deployed `unlocked_*.pdf`. So the candidate-detail "전체 PDF 열기" opens the uploaded PDF at the candidate page; arbitrary-page validation uses the uploaded PDF's `page_count`. `review_splice` is **disabled in the web viewer** (`review_splice_web_disabled`).

### 매뉴얼 업데이트 알림 (`backend/services/manual_alert_service.py`, migration 0017)

첨부파일 **제목 변동**을 감지해 전 사용자가 **최초 로그인 시** 알림을 본다. Tables: `manual_update_alert_events`(`UNIQUE(manual, new_title_hash)` → 멱등), `manual_update_alert_dismissals`(`UNIQUE(alert_event_id, login_id)` → 사용자별 "이번 업데이트 다시 알리지 않음", 전역 차단 아님). 감지(무거움)는 daily APScheduler(`_alert_scheduler`, PG 구성 시) 또는 admin `POST /api/manual/alerts/run-detect` 에서만 — **로그인 시에는 active 이벤트만 조회**(`GET /api/manual/alerts/active`, dismiss `POST /api/manual/alerts/{id}/dismiss`). `0017` 미적용/오류 시 **graceful**(빈 목록, 앱 정상 — 운영 DB는 아직 0017 미적용). 로그인 모달은 `frontend/app/(main)/layout.tsx` `ManualUpdateAlertModal`(세션당 1회; 관리자→/admin 이동, 일반→안내만).

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

## PostgreSQL migration (operational domains + public marketing are PG-only)

The platform began as a Sheets-only app with a **feature-flagged dual-store** migration, but the **working tree has since moved the operational domains to PG-only** (Phases C/D/E/F/I). These paths **no longer read `FEATURE_PG_*`** and have **removed the Sheets read/fallback** — they always use PostgreSQL (PG must be configured):
- **Login / accounts** — `auth.py` PG-only (`find_account_by_tenant_pg`); *no Sheets Accounts fallback* — missing PG user = auth fail.
- **Customers + relationships** (숙소제공자/신원보증인) — Phase C/I, `list_customers()` etc. unconditional PG.
- **quick_doc reads** (문서자동작성 customer data) — Phase I, Sheets read removed.
- **Tasks** (Phase D), **Daily/finance** (Phase E), **Events + Memos** (Phase F) — PG-only.

So a **fresh/local env now requires PostgreSQL** for these domains (not "100% Sheets").

**Public marketing/homepage `/board` is now PG-only (Phase H) — NOT Sheets.** `backend/routers/marketing.py` `_read_posts()` → `marketing_pg_service.list_admin` (model `MarketingPost`, `get_sessionmaker`); admin save = `upsert_post`/`delete_post`; public `/api/marketing/posts(/{id})` reads PG (published only). `frontend/app/board/page.tsx`·`[id]/page.tsx`·`sitemap.ts` server-side fetch `/api/marketing/posts` (SSR). No gspread/`read_sheet`/`get_worksheet` calls remain for board/marketing. **(The prior "marketing/board still Sheets" + "Render PG copies are stale snapshots" notes were outdated — superseded by Phase H; see the v2 top section.)**

What is **still Sheets / mixed** (not migrated): **internal 게시판 `board_posts`/댓글** (separate feature from the public homepage; `search.py` still branches on `FEATURE_PG_BOARD`), and **signatures** (`FEATURE_PG_SIGNATURES` reserved/unwired — agent/customer/temp signatures + always-on pad token state use Sheets/PG as noted in their sections).

The `FEATURE_PG_*` flags below remain real for the **still-flagged** domains (internal `board_posts`) and are **inert for the PG-only domains above** (toggling them changes nothing there). When adding genuinely new dual-store work, the flag-gated pattern still applies; for the migrated domains, treat PG as the single store.

- **Flags:** `backend/db/feature_flags.py` — `_bool()` reads env **fresh on every call** (no import-time caching; toggle env + restart suffices). Truthy = `1/true/yes/y/on`. Domains: `FEATURE_PG_{USERS,AUDIT,CUSTOMERS,EVENTS,TASKS,DAILY,MEMOS,SIGNATURES,REFERENCE,BOARD,MARKETING,ADMIN,MANUAL_UPDATE,GUIDELINES,TENANT_PROVISIONING,QUICK_DOC_CONFIG}`, plus `FEATURE_SINGLE_SESSION`, `FEATURE_LOCAL_DRIVE_MOCK`, `FEATURE_MANUAL_AUTO_UPDATE`. `feature_flags.snapshot()` dumps current state for debug endpoints. `FEATURE_PG_SIGNATURES` is reserved/unwired.
- **PG service pattern:** services under `backend/services/*_pg_service.py` are pure functions using `get_sessionmaker()` (`backend/db/`) and return **Sheets-shaped, Korean-keyed dicts** so callers are storage-agnostic. Translation via `SHEET_TO_PG` / `PG_TO_SHEET` maps per service (e.g. `customer_pg_service.py`: both `"메모"` and `"비고"` → `memo`; `PG_TO_SHEET["memo"]="비고"`).
- **Alembic:** migrations in `alembic/versions/` (`0001`→`0017`). Applied **manually per environment** (`alembic upgrade head`) — **never auto-run on boot** (the Render `Dockerfile.combined` startup is just `uvicorn & next start`; no alembic). Creating a migration file is allowed; running `alembic upgrade` on the operational DB requires explicit instruction. A flag must not be enabled before its table migration is applied. Keep a **single alembic head** (`python -m alembic heads`). **Local head = `0017`. Render (operational) = `0016` (`0013`→`0016` applied during the business-card deploy). `0017` is local-only so far — apply to Render only with explicit instruction. All additive (columns + new tables, no data loss).**
  - Run alembic with the project venv (`.venv\Scripts\python.exe -c "from alembic.config import main; main(['upgrade','head'])"`) — bare `python -m alembic` fails (global python has no `psycopg`). For the operational DB, set `DATABASE_URL` to the Render **External Database URL** in the shell session only (never a file), `pg_dump -Fc` backup first (no native `pg_dump`? use a `postgres:18` docker container), then upgrade.
  - `0001` tenants/users/audit_logs · `0002` customers/events/memos/daily/tasks · `0003` signatures/relationships/board · `0004` manual-update tables · `0005` fixed_expenses + monthly_tax_summaries · `0006` guideline_categories + guideline_category_overrides · `0007` user_sessions · `0008` signature_pad_tokens · `0009` work_reference_meta · `0010` roi_presets · `0011` `tenants.agent_rrn_encrypted/last4/updated_at` (PII) · `0012` `doc_tree_nodes` + `doc_required_documents` (문서자동작성 편집형 트리 — `FEATURE_PG_QUICK_DOC_CONFIG`) · `0013` `manual_review_decisions.reviewer_*` (수동 페이지 override) · `0014` `manual_pdf_artifacts` (PDF blob 레지스트리) · `0015` `tenants.card_*` (전자명함) · `0016` `tenants.card_logo_*` (전자명함 로고 파일 BYTEA) · `0017` `manual_update_alert_events` + `manual_update_alert_dismissals` (매뉴얼 업데이트 알림).

### Customer create / 고객ID numbering + tenant provisioning (PG, `FEATURE_PG_CUSTOMERS`)

`add_customer` (PG path) calls `customer_pg_service.create_customer`:
- **Auto-numbering** (`next_customer_id`) takes `max(고객ID) + 1` (4-digit zero-pad) over **all rows including soft-deleted** — the unique index `uq_customer_per_tenant (tenant_id, customer_id)` holds tombstones, so counting only live rows would reissue a deleted id and collide. An explicit `고객ID` defers to `upsert_customer` (update/restore).
- **IntegrityError is classified by constraint name** (`_constraint_name`, psycopg `diag` or message scrape): `uq_customer_per_tenant` → retry with the next id (concurrency/race, up to 5×, else `CustomerIdConflict` → 409); `customers_tenant_id_fkey` → **no retry**, raise `TenantNotProvisioned` → 409 "테넌트 초기화가 완료되지 않았습니다. 관리자에게 문의하세요."; any other → re-raise. Never blanket-retry a FK violation.
- **FK root cause:** every PG `customers` row FKs `tenants.tenant_id`. Accounts created Sheets-only (admin `create_account`) had no PG `tenants` row → first PG insert failed. `admin.create_account` now calls `tenant_provisioning_service.ensure_tenant_provisioned(tenant_id, office_name)` (idempotent, no-op without PG, only inserts a missing row) to prevent recurrence. Login still falls back to Sheets accounts when no PG user exists.

### Monthly settlement finance (PG, `FEATURE_PG_DAILY`)

일일결산 entries encode payment method + amounts + tax flag in the memo: `[KID]inc=..;e1=..;e1a=..;e2=..;e2a=..;tax=..[/KID]`. In `backend/routers/daily.py`: `_entry_reported_sales()` counts an entry toward 신고매출 when it is **card income OR tax-invoice-flagged** (counted once, never double). **Card income must not be mixed into `active_task.card`** — 수입 합계 is daily-income-based only. `fixed_expenses` are **recurring** with an effective month-range (start/end); `_fixed_amount_for_month()` applies one only within its active term. Amounts surface in 만원 units via `_build_yearly_overview()`. Endpoints: card-expense-summary, income-summary, yearly-overview, fixed-expenses CRUD, tax-summary.

**월간결산 계산 기준** (`/yearly-overview`, page `(main)/monthly/page.tsx`): 매출 = `income_cash+income_etc`, 지출 = `exp_cash+exp_etc`, 순이익 = 매출−지출. **`현금출금` 카테고리는 제외**(cash_out은 순이익 미반영), 미수는 income 0이라 자연 제외. **전년 동월 비교는 "동일일자까지 누계"** — 진행 중인 월은 오늘 day, 과거월은 말일이 기준일(`ref_day`); 전년은 같은 day까지 자르되 `prev_ref_day = min(ref_day, 전년월 말일)`로 윤년/말일 보정(`_build_period_analysis`). 전체월 vs 전체월로 비교하지 말 것.

**업무군별 경영 진단 보고서** (`business_insights` in the same response): per-category 손익(건수/매출/순이익/순이익률/객단가/건당순익) + 전년 동기 비교 + 진단/개선 문장. **`normalize_business_category(category, aux)`** maps free-text/legacy `category` to the 7 standard buckets (출입국/전자민원/공증/여권/초청/영주권/기타) by keyword (legacy variants like `영주`·`체류`·`연장`·`공인증`·`전자` resolve correctly, not 기타). **F-5 정책**: category가 명확한 비-출입국 버킷이면 유지; category가 출입국/기타/빈값일 때만 `task`(보조)에서 강한 영주권 신호(영주/F-5/영주자격/permanent residence)면 영주권으로. `manual_issue` is a 3-state (linked/not_linked/error) advisory that links 출입국 to `manual_update_versions` detected in the month — full PDF↔체류자격 정밀 매칭은 아직 아님(문구로 명시).

### 실무지침 category overlay (PG, `FEATURE_PG_GUIDELINES`)

`backend/services/guideline_category_pg_service.py` layers an **editable category overlay** on top of the read-only JSON tree (the JSON 실무지침 data itself stays immutable — see the guidelines section above). `source_key` scheme: `M|`=대분류, `m|`=중분류, `s|`=소분류 — **never change a `source_key`**. `seed_from_rows()` is idempotent and only backfills English/empty `display_name`; **user-edited `display_name` is never overwritten**. `ACTION_KO` maps action codes to Korean (CHANGE→체류자격 변경, EXTEND→체류기간 연장, …). Overrides are **minor-level only** (`set_override` guard) and merge by `row_id`. Flag OFF → edit APIs return 409; the read tree is the existing JSON-derived one.

### Single active session (`FEATURE_SINGLE_SESSION`, table 0007)

`backend/auth.py` `get_current_user`: when on, the JWT carries a `sid`; a missing sid → 401 `SESSION_EXPIRED`, a revoked session → 401 `SESSION_REVOKED`. New login revokes prior **non-kiosk** sessions (`session_pg_service.revoke_active_sessions(only_non_kiosk=True)`). `user_sessions` stores **hashed** ip/user_agent (never raw IP) and an `is_kiosk` flag — **kiosk sessions are kept separate** from normal user sessions and are not auto-revoked. Logout = best-effort `authApi.logout()` (server no-op when flag off). Frontend distinguishes via `sessionStorage["session_revoked"]`. OFF → legacy token behavior, session table unused.

### 계정 비활성화/삭제 + 즉시 세션 차단 (account lifecycle)

`get_current_user` re-checks **`is_active` on every request** (PG `account_active_status(login_id)` in `auth_pg_service.py`), independent of `FEATURE_SINGLE_SESSION` — a JWT decode alone never passes. Disabled/deleted account (or missing row) → **401 `{code:"ACCOUNT_DISABLED"}`**, so an already-issued 8h token dies on the next request. PG unconfigured → skipped; lookup error → fail-open (availability). Frontend: `api.ts` 401 interceptor sets `sessionStorage["account_disabled"]` → `/login` shows the disabled notice; `(main)/layout.tsx` polls `authApi.me()` on mount + focus/visibility + every 45s so open tabs log out without a click.

Admin account endpoints (`backend/routers/admin.py`): **deactivate** (`DELETE /accounts/{id}`) and the inline `is_active` toggle (`PUT /accounts/{id}`) both set `is_active=false` + `revoke_active_sessions(only_non_kiosk=False)` + audit `ACCOUNT_DISABLED`, and both refuse to drop the **last active admin** (409) / self (400). **Restore** = `POST /accounts/{id}/restore`. **Hard delete** = `DELETE /accounts/{id}/hard?confirm_login_id=` — physical delete, guarded: exists / not self / `is_active=false` / not last admin / `confirm_login_id` matches / **no connected business data** (`_connected_data_summary` counts rows in every `tenant_id`-bearing table via `information_schema`, excluding account/session/infra tables → any row blocks with 409). Deletes user_sessions + signature_pad_tokens, then the user (flush before tenant — FK is a natural-key `users.tenant_id`→`tenants`, no ORM relationship so ordering isn't auto-inferred), then the tenant if no other users; audit `ACCOUNT_HARD_DELETED` with `deleted_account_identifier`. Frontend: active row → 비활성화 only; inactive row → 복구 + 완전삭제 (2-step modal requiring the login_id typed in).

### Always-on signature pad (`/sign/pad`)

A tablet/phone left permanently on a signing screen, decoupled from customer records. **Signature storage reuses the existing 임시서명 1·2·3** (`"서명임시저장"` tab in `SHEET_KEY`, via `save_temp_slot_first_empty()` → first empty slot 1→2→3, `{status:"ok",slot}` / `{status:"full"}`). Pending temp slots **lazily expire at 2h** (`_temp_is_expired`); **applied** signatures never auto-expire. Signature image is **transparent PNG** (`compress_signature` white→alpha 0, 400×150, ≤50KB) — **never white-background PNG / white PDF box**.

**Token state is in PostgreSQL, NOT Sheets** (do not create a `서명패드토큰` Sheets tab). Table `signature_pad_tokens` (migration `0008`, model in `backend/db/models/signature.py`, service `signature_pg_service.py`): **one active row per `tenant_id`** with a UUID4 `token_id`, 1-year `expires_at`. The pad URL is a stateless HMAC token whose payload is `{t:"p", tid, on, jti=token_id, exp}` — `jti` is matched against the row's current `token_id` to validate. **Gated on PG being configured** (`db.session.is_configured()`), not on a feature flag (`FEATURE_PG_SIGNATURES` stays unwired); endpoints return **503** when PG is absent.
- `GET /api/signature/pad/token` (login-only) → `ensure_pad_token` reuses the existing valid row (same URL re-rendered) or issues a new `token_id`; returns `{token, url}`.
- `POST /api/signature/pad/token/regenerate` (login-only) → `regenerate_pad_token` swaps `token_id` on the same row → **old URL/QR instantly invalid** (jti mismatch). Confirm dialog required in the issuer modal.
- `GET /api/signature/pad/info` (no auth) → `{valid, office_name}`; reflects jti/expiry via `pad_token_is_active`.
- `POST /api/signature/pad/save` → reads **tenant_id + jti from token only** (never trust frontend), validates against the active row (regenerated/expired → 401), then stores into the temp slot.

Frontend: `frontend/app/sign/pad/page.tsx` (canvas `backgroundColor:"rgba(0,0,0,0)"`), issuer modal `frontend/components/SignPadUrlModal.tsx` (notice text + copy / 새 창 / QR via `qrcode` + **재발급** with confirm), launched from topbar "서명패드" button. **Do not mix with `FEATURE_SINGLE_SESSION` or normal login sessions.** No customer info is ever shown on the pad.

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
- Operational domains (auth, customers, relationships, tasks, daily, events, memos, quick_doc reads) are **PG-only** — do not re-introduce Sheets reads/fallbacks there. For **genuinely new** dual-store work, the flag-gated pattern still applies (default OFF, don't change Sheets behavior when off).
- Never auto-run `alembic upgrade` on an operational DB, and never enable a flag before its migration is applied — both require explicit instruction.
- Signatures are transparent PNG only — never produce a white-background image or white PDF box.
- Manual-update PDF: never compose/splice a full PDF in a web request, never bulk-`SELECT` `pdf_blob` (defer it; fetch one blob by id), keep upload save-only with change-detection as a separate step, keep node/playwright/`generate_pdf.mjs` worker-only.
- Business card / cert region selects: source-of-truth is the editable master list (PG), not distinct values from existing rows; preserve an out-of-master current value as a `현재값` option rather than dropping it.

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
