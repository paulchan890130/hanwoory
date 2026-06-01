# PostgreSQL 마이그레이션 계획서 (POSTGRES_MIGRATION_PLAN.md)

> **작성일:** 2026-06-01
> **대상 프로젝트:** K.ID SaaS (한우리 행정사 출입국업무관리)
> **대상 DB:** Render PostgreSQL
> **현재 단계:** 계획 수립만 — 코드 구현 금지
> **본 문서의 모든 작업은 단계별로 분리되어야 하며, 한 단계가 완전히 검증되기 전에 다음 단계로 진행하지 않는다.**

---

## 0. 본 문서를 읽는 사람에게

이 문서는 “지금 당장 마이그레이션을 시작하지 않는다”는 것을 전제로 한다.
구현 단계에 들어가기 전에:

1. 본 문서를 끝까지 읽는다.
2. `절대 금지사항` 섹션을 별도로 확인한다.
3. Phase 0 안전 점검(저장소 위생, 백업, 현 상태 작동 확인)을 먼저 완료한다.

본 문서는 **체크리스트 형식**이며, 각 단계는:
* objective(목표)
* files likely to change(변경 가능성 있는 파일)
* files that must not be changed(절대 건드리지 말아야 할 파일)
* commands to run(실행할 명령)
* expected result(기대 결과)
* verification method(검증 방법)
* rollback method(롤백 방법)

순서대로 채워져 있다.

---

## 1. 현재 아키텍처 요약 (Current Architecture Summary)

### 1.1 런타임 구성

```
[브라우저]
   │
   ▼
[Next.js 14.2.5 (frontend) :3000]
   │  (next.config.js rewrites — /api/* → ${API_URL}/api/*)
   ▼
[FastAPI 2.0.0 (backend) :8000]
   │   ├── gspread (Google Sheets v4)
   │   └── googleapiclient (Google Drive v3)
   ▼
[Google Sheets 워크북들]   [Google Drive 폴더들]
```

* **프론트엔드:** Next.js 14.2.5 + React 18 + Tailwind + Radix UI + FullCalendar + signature_pad + axios
* **백엔드:** FastAPI + uvicorn + gspread + google-api-python-client + python-jose(JWT) + apscheduler + pymupdf + pytesseract
* **데이터 저장소(현재):** 100% Google Sheets / Google Drive
* **로컬 DB:** `database.py`에 sqlite 코드가 있지만 **사실상 사용되지 않는 레거시** (Streamlit 시절 잔재로 추정)
* **배포(목표):** Render
  * 단일 컨테이너(`Dockerfile.combined`): FastAPI(127.0.0.1:8000) + Next.js(0.0.0.0:3000)
  * 또는 분리형(`docker-compose.yml`): frontend/backend 두 컨테이너

### 1.2 인증 / 멀티테넌시

* JWT(HS256), TTL 8시간, `backend/auth.py`
* JWT payload: `sub=login_id`, `tenant_id`, `is_admin`, `office_name`, `contact_name`
* 테넌트 식별: `Accounts` 시트(어드민 마스터 `SHEET_KEY`의 한 탭)에서 `tenant_id → customer_sheet_key / work_sheet_key / folder_id` 매핑
* 기본 테넌트 `hanwoory`만 마스터 시트로 폴백 허용. **다른 테넌트는 키 부재 시 `ValueError`** (admin 데이터 폴백 금지) — `backend/services/tenant_service.py`

### 1.3 현재 데이터 흐름

| 도메인 | 저장 위치 | 키/탭 |
|---|---|---|
| 계정/테넌트 | `SHEET_KEY` / `Accounts` 탭 | `login_id` |
| 고객 데이터 | `customer_sheet_key` / `고객 데이터` 탭 | `고객ID` |
| 진행업무 / 예정업무 / 완료업무 | `customer_sheet_key` / 각 탭 | `id` |
| 일일결산 / 잔액 | `customer_sheet_key` / `일일결산`, `잔액` | `id` / `key` |
| 일정 | `customer_sheet_key` / `일정` | `date_str` |
| 메모 (장/중/단기) | `customer_sheet_key` / `장기메모/중기메모/단기메모` | A1 셀 단일 |
| 숙소제공자 / 신원보증인 | `customer_sheet_key` / `숙소제공자연결`, `신원보증인연결` | `target_customer_id` |
| 고객 서명 | `customer_sheet_key` / `고객서명` | `고객ID` |
| 행정사 서명 | `SHEET_KEY` / `행정사서명` | `tenant_id` |
| 임시 서명 슬롯 | `SHEET_KEY` / `서명임시저장` | `(slot, tenant_id)` |
| 업무참고 / 업무정리 | `work_sheet_key` / `업무참고`, `업무정리` | row id |
| 각종공인증 | `work_sheet_key` / `각종공인증_*` 5개 탭 | `id` |
| 게시판 / 댓글 | `SHEET_KEY` / `게시판`, `게시판댓글` (공용) | `id` / `post_id` |
| 마케팅 게시물 | `SHEET_KEY` / `홈페이지게시물` (공용) | `id` |
| 출입국 실무지침 DB | `backend/data/immigration_guidelines_db_v2.json` (파일) | `row_id` |

---

## 2. 점검한 파일 / 폴더 (Confirmed Files / Folders Inspected)

### 2.1 루트
* [x] `.gitignore`
* [x] `.env` (키 이름만 확인 — 값 미열람)
* [x] `Dockerfile.combined`, `Dockerfile.backend`, `Dockerfile.frontend`, `docker-compose.yml`
* [x] `requirements.txt`
* [x] `config.py`
* [x] `database.py` (레거시 sqlite — 사실상 미사용)
* [x] `google_drive_service.py` (레거시 Streamlit 시절 코드)
* [x] `CLAUDE.md`, `docs/`

### 2.2 백엔드
* [x] `backend/main.py` (FastAPI 진입점)
* [x] `backend/auth.py` (JWT)
* [x] `backend/models.py` (Pydantic)
* [x] `backend/services/tenant_service.py` (Sheets 추상화 핵심)
* [x] `backend/services/accounts_service.py` (Accounts CRUD, 비밀번호 해시)
* [x] `backend/services/signature_service.py`
* [x] `backend/services/certification_service.py`
* [x] `backend/services/cache_service.py`
* [x] `backend/routers/` 전체 디렉터리 구조 (admin, auth, board, certification, customers, daily, events, guidelines, manual, marketing, memos, quick_doc, reference, scan, scan_workspace, scan_roi_preset, search, signature, tasks)

### 2.3 프론트엔드
* [x] `frontend/package.json` (Next.js 14.2.5)
* [x] `frontend/next.config.js` (`/api/*` rewrites → `process.env.API_URL`)
* [x] `frontend/middleware.ts` (Edge 인증 가드 — `kid_auth` 쿠키)
* [x] `frontend/lib/api.ts` (axios 클라이언트, `baseURL=""`)
* [x] `frontend/.env.local.example`
* [x] `frontend/app/(main)/*`, `frontend/app/(auth)/login`, `frontend/app/board/*`, `frontend/app/documents`, `frontend/app/sign/*`

### 2.4 인스펙트하지 않은 영역 (의도적 제외)
* `샘플/`, `analysis/`, `.tmp.driveupload/`, `.tmp.drivedownload/`, `.venv/`, `frontend/node_modules/`, `secrets/` — 본 단계에서 불필요
* Tesseract OCR / OmniMRZ 내부 동작 — 본 마이그레이션 범위 밖

---

## 3. 현재 데이터 흐름 (Current Data Flow)

```
[프론트] → axios(/api/*) → next.config.js rewrites
   → FastAPI 라우터
   → backend/services/tenant_service.py
       ├─ _get_gspread_client() (서비스 계정 JSON; 10분 TTL)
       ├─ _load_tenant_map() (Accounts 시트 10분 TTL 캐시)
       ├─ _resolve_sheet_key(sheet_name, tenant_id) — workbook 라우팅
       ├─ get_worksheet() → gspread Worksheet 반환
       ├─ read_sheet() — 120초 TTL + per-key lock + 무효화 토큰
       ├─ upsert_sheet() — id 기반 batch_update / append_rows
       ├─ delete_from_sheet() — 행번호 역순 삭제
       ├─ read_memo() / save_memo() — A1 단일 셀
   → 라우터별 추가 캐시 (cache_service.py, certification_service._CERT_CACHE 등)
```

### 핵심 패턴
1. **ID 기반 upsert** (`upsert_sheet`): 헤더 → ID 컬럼 인덱스 → 매치되면 UPDATE, 없으면 APPEND. 전체 덮어쓰기 아님.
2. **읽기 캐시 + per-key lock**: 동시 요청이 cold cache를 동시에 뚫지 못하도록 `_READ_KEY_LOCKS`로 직렬화.
3. **무효화 토큰**: 읽기 중간에 다른 스레드가 쓰기로 캐시를 무효화했을 경우 stale 결과 캐싱 방지.
4. **테넌트 분리**: 모든 비-공용 데이터는 `customer_sheet_key` 또는 `work_sheet_key`로 격리. 공용 4탭(`게시판`, `게시판댓글`, `홈페이지게시물`, `행정사서명`, `서명임시저장`)만 마스터 시트.

---

## 4. 현재 Google Sheets / Drive 의존 맵 (Dependency Map)

### 4.1 Google Sheets — read/write 진입점

| 함수 | 파일 | 역할 |
|---|---|---|
| `_get_gspread_client()` | `backend/services/tenant_service.py:71` | 서비스 계정 인증 싱글턴 (TTL 10분) |
| `get_worksheet(sheet_name, tenant_id)` | `tenant_service.py:215` | 워크북 라우팅 + 워크시트 반환 |
| `read_sheet(sheet_name, tenant_id)` | `tenant_service.py:286` | 전체 레코드 읽기 (120초 캐시) |
| `upsert_sheet(...)` | `tenant_service.py:353` | ID 기반 upsert |
| `delete_from_sheet(...)` | `tenant_service.py:418` | ID 기반 삭제 |
| `read_memo` / `save_memo` | `tenant_service.py:459/470` | A1 단일 셀 |
| `_load_tenant_map()` | `tenant_service.py:98` | Accounts 시트 → tenant_id 매핑 (10분 캐시) |
| `_get_ws()` / `_get_ws_readonly()` | `backend/services/accounts_service.py:74/91` | Accounts 워크시트 (쓰기/읽기 분리) |
| `_get_or_create_ws(sh, title, headers)` | `backend/services/signature_service.py:49` | 서명 탭 lazy-create |
| 각 라우터 내 직접 호출 | `routers/customers.py`, `routers/quick_doc.py`, `routers/scan.py`, `routers/reference.py`, `routers/events.py`, `routers/daily.py`, `routers/admin.py`, `services/certification_service.py`, `services/roi_preset_sheet.py` | `get_all_values()`, `append_rows()`, `delete_rows()`, `batch_update()` 등 직접 호출 — 12개 파일에서 37회 |

### 4.2 Google Drive — read/write 진입점

| 함수 | 파일 | 역할 |
|---|---|---|
| `drive.about().get(...)` | `backend/routers/admin.py:407` | 서비스 계정 quota / sa email 조회 |
| `drive.files().create(...)` | `backend/routers/admin.py:447` | 사무소 폴더 생성 (parent = `PARENT_DRIVE_FOLDER_ID`) |
| `drive.files().get(...)` | `backend/routers/admin.py:494` | 템플릿 파일 메타데이터 조회 |
| `drive.files().copy(...)` | `backend/routers/admin.py:559/616` | 고객/업무 템플릿 시트 복사 |
| 마케팅 이미지 업로드 | `backend/routers/marketing.py` | 게시물 썸네일/본문 이미지 |
| 고객 폴더 | `backend/routers/customers.py` (관련 컬럼 `폴더`) + `config.CUSTOMER_PARENT_FOLDER_ID` | 고객별 PDF/스캔 보관 |

### 4.3 고위험 패턴 (HIGH-RISK PATTERNS) — 본 단계에서 **수정 금지, 기록만**

| 위험도 | 위치 | 내용 |
|---|---|---|
| **HIGH** | `backend/routers/daily.py:390` | `ws.clear()` 후 `ws.update("A1", ...)` — `잔액` 저장이 시트 전체 삭제 후 재작성. 잔액 시트는 2행짜리지만 동시 요청 시 데이터 손실 가능성 존재. |
| HIGH | `frontend/.env.local.example` 와 `CLAUDE.md` 충돌 | `.env.local.example`은 `NEXT_PUBLIC_API_URL`을 안내하지만 `CLAUDE.md`는 “**never add `NEXT_PUBLIC_API_URL`**”이라고 명시. 실제로 `lib/api.ts`는 `baseURL=""`. 예시 파일이 오해를 유발. (수정 금지 — 기록만) |
| HIGH | `frontend/lib/auth.ts` (간접 확인) — JWT를 localStorage에 평문 저장 | XSS 발생 시 토큰 탈취 위험. 마이그레이션 후 httpOnly 쿠키 전환을 권장하나 본 마이그레이션 범위 아님. |
| MED | 12개 파일에서 `get_all_values()` 37회 호출 | 시트 행수 증가 시 페이지 로드당 API 호출 비용 선형 증가. 캐시는 있으나 cold-cache 시 전체 시트 fetch. |
| MED | `database.py` (루트) | 사용되지 않는 sqlite 코드. Postgres 도입 시 혼동 유발 가능 — 삭제하지 말고 명시적으로 deprecate 주석만 추가 후보. |
| MED | `google_drive_service.py` (루트) | Streamlit 시절 잔재. 현재 백엔드에서 import하지 않음. 삭제 금지(레퍼런스), Postgres 작업과 무관. |
| MED | `Drive folder 생성 후 sheet 복사`는 비-원자적 | `admin.py`의 워크스페이스 생성 흐름은 폴더 → 고객 시트 복사 → 업무 시트 복사 → Accounts 업데이트가 단계별 실패 보고 구조. 일부만 성공 시 일관성 깨짐. **현재 정상 작동 중이므로 손대지 말 것.** |

---

## 5. GitHub / 대용량 파일 / 비밀 위험 점검 (GitHub / Large File / Secret Risk Check)

### 5.1 추적되지 않아야 할 폴더 — `.gitignore` 매칭 결과

| 폴더 | `.gitignore` 매칭 | 현재 git 추적 여부 |
|---|---|---|
| `.venv/` | ✅ ignored | ✅ untracked |
| `frontend/node_modules/` | ✅ ignored | ✅ untracked |
| `frontend/.next/` | ✅ ignored | ✅ untracked |
| `샘플/` | ✅ ignored | ✅ untracked (HEAD에서) |
| `analysis/` | ✅ ignored | ✅ untracked (HEAD에서) |
| `.tmp.driveupload/` | ✅ ignored | ✅ untracked (HEAD에서) |
| `.tmp.drivedownload/` | ✅ ignored | ✅ untracked (HEAD에서) |
| `secrets/` | ✅ ignored | ✅ untracked |
| `*.env` / `.env.*` | ✅ ignored | ✅ untracked |
| `hanwoory-*.json` (서비스 계정 키) | ✅ ignored | ✅ untracked |
| `client_secret*.json`, `token.json` | ✅ ignored | ✅ untracked |

### 5.2 `.git` 디렉터리 비대 (HIGH-RISK FINDING)

* `.git` 크기: **약 991MB** — 작업트리 대비 매우 큼.
* `git rev-list --objects --all` 결과, **과거 커밋에 포함된 거대 blob들이 그대로 보관**되어 있음:
  * `frontend/node_modules/@next/swc-win32-x64-msvc/next-swc.win32-x64-msvc.node` — 약 **135MB**
  * `샘플/_addr_db_inspect/*.txt` 다수 — 개별 **40MB~100MB**
  * `analysis/스크린샷/정리된 분석자료 일부.pdf` — 약 **77MB**
  * `.tmp.driveupload/706716`, `669560` — 각 약 **58MB**
  * `analysis/스크린샷/221230 체류관리편람.pdf` — 약 **39MB**
* **현재 `.gitignore`로는 이미 추적 중단된 상태이나, 과거 히스토리에 영구 보관되어 있음.** GitHub로 push할 경우 push가 거부되거나 LFS 강제 변환 압박.

### 5.3 비밀(Secrets) 노출 점검

* 추적 파일에서 `client_secret`, `service_account`, `hanwoory-*.json`, `token.json` 패턴 발견되지 않음.
* `frontend/.env.local.example` 만 추적됨 (안전 — 예시 파일, 실제 값 없음).
* `frontend/public/arc-sample.jpg`, `passport-sample.jpg`는 OCR 샘플 이미지로 의도적 추적 — 개인정보 포함 시 점검 필요(본 단계 범위 아님).

### 5.4 권장 조치 (실행 금지 — 기록만)

* [ ] `.git` 히스토리에서 거대 blob 제거 (BFG Repo-Cleaner 또는 `git filter-repo` 사용)
   ```bash
   # ⚠️ 절대 본 단계에서 실행 금지 — 사용자 명시적 승인 후에만 진행
   # 사전 풀백업 필수: 별도 폴더로 전체 .git 복사
   # 예시 (실행 X):
   #   git filter-repo --strip-blobs-bigger-than 10M
   #   또는
   #   java -jar bfg.jar --strip-blobs-bigger-than 10M
   ```
* [ ] 새 origin remote에 force-push 전 협업자 통보
* [ ] 권장: 클린 히스토리 만든 후 새 GitHub repo로 이전, 기존 repo는 read-only 보관

---

## 6. PostgreSQL 목표 아키텍처 (Target Architecture)

```
[브라우저]
   ▼
[Next.js (Render Web Service)]
   ▼
[FastAPI (Render Web Service)]
   ├── SQLAlchemy 2.x + psycopg[binary] → [Render PostgreSQL] (PRIMARY DB)
   ├── gspread → [Google Sheets] (백업/내보내기/수동확인 전용; 일정 기간 듀얼라이트)
   └── googleapiclient → [Google Drive] (PDF/이미지/고객폴더 — 그대로 유지)
```

### 6.1 단계적 목표

| 단계 | Sheets | PostgreSQL | Drive |
|---|---|---|---|
| 현재 | PRIMARY | — | 파일 저장소 |
| 전환 중기 | DUAL-WRITE (정합성 검증) | DUAL-WRITE | 파일 저장소 (변경 없음) |
| 전환 말기 | READ-ONLY 백업 | PRIMARY | 파일 저장소 (변경 없음) |
| 최종 | 수동 내보내기 / 어드민 검수용 | PRIMARY | 파일 저장소 (변경 없음) |

### 6.2 마이그레이션 후에도 Drive에 남는 것
* 고객별 폴더 (`config.CUSTOMER_PARENT_FOLDER_ID`)
* 사무소별 폴더 (`config.PARENT_DRIVE_FOLDER_ID`)
* 마케팅 이미지
* OCR/문서 자동 작성 결과 PDF
* HWP 메뉴얼 파일

Drive 파일은 **PostgreSQL의 `documents` 테이블에 메타데이터만 저장**하고, 바이너리는 Drive에 그대로 둔다.

---

## 7. Render PostgreSQL 권장 구성 (Recommended Configuration)

### 7.1 Render 측 설정

| 항목 | 권장값 |
|---|---|
| 플랜 | Starter ($7/월) 또는 Standard | (실제 운영은 Standard 이상 권장 — 자동 백업 7일) |
| 리전 | 백엔드 Web Service와 **동일 리전** (필수) |
| PostgreSQL 버전 | 16 (최신 LTS) |
| Connection limit | 시작값 97 (Starter), 신청 시 확장 |
| 자동 백업 | 활성 (플랜에 따라 자동) |
| `INTERNAL_DATABASE_URL` | FastAPI Web Service 환경변수에 주입 (Render 내부망, 빠르고 안전) |
| `EXTERNAL_DATABASE_URL` | 로컬 Alembic 마이그레이션·검수용으로만 사용. 프로덕션 트래픽에 사용하지 말 것. |

### 7.2 환경변수 (Render Dashboard에서 수동 설정)

| 변수명 | 용도 | 우선순위 |
|---|---|---|
| `DATABASE_URL` | 코드에서 읽는 표준 변수. Render는 `INTERNAL_DATABASE_URL` 값을 여기에 자동 매핑하도록 설정. | 1순위 |
| `DATABASE_POOL_SIZE` | SQLAlchemy 풀 크기. 기본 5, 운영 시 10 권장 | 2순위 |
| `DATABASE_MAX_OVERFLOW` | 기본 10 | 2순위 |
| `DATABASE_SSLMODE` | Render는 SSL 강제. URL에 `?sslmode=require` 또는 별도 변수 | 1순위 |

> `.env`, secret JSON, JWT 키 등은 **본 마이그레이션에서 절대 수정하지 않는다.** 신규 DB 환경변수만 추가.

---

## 8. 신규 백엔드 모듈 (Required New Backend Modules)

본 단계에서는 **존재 여부 확인용 명세만** 작성한다. 실제 파일 생성은 Phase 1에서 수행.

```
backend/
  db/
    __init__.py
    session.py          ── SQLAlchemy engine + SessionLocal + get_db() FastAPI dep
    base.py             ── declarative_base() / Base = DeclarativeBase
    models/
      __init__.py
      tenant.py         ── Tenant, AccountUser, Role(추후)
      audit.py          ── AuditLog
      customer.py       ── Customer (Phase 4)
      task.py           ── ActiveTask / CompletedTask / PlannedTask (Phase 5)
      daily.py          ── DailyEntry / Balance (Phase 5)
      event.py          ── EventDate (Phase 5)
      memo.py           ── Memo (Phase 5)
      signature.py      ── AgentSignature / CustomerSignature / TempSignatureSlot
      document.py       ── DocumentMetadata (Drive 메타데이터, Phase 6)
      marketing.py      ── MarketingPost (Phase 5/6)
  routers/
    health.py           ── /health/db 추가
alembic/
  env.py
  script.py.mako
  versions/
    0001_initial_tenants_users.py
    0002_audit_logs.py
    ... (단계별)
alembic.ini
```

### 8.1 새 라우터/엔드포인트
* `GET /health/db` — DB 연결 확인용. SELECT 1, 응답 시간 측정 포함.
* Phase 2 이후: 기존 라우터에 “PG 백엔드” 옵션을 추가하는 게 아니라, **service 레이어를 추가**해서 라우터가 Sheets/PG 어느 쪽이든 호출할 수 있게 한다. 라우터 시그니처는 변경하지 않는다.

---

## 9. 필요한 Python 의존성 (Required Dependencies)

`requirements.txt`에 **추가**할 항목 (기존 줄 수정 금지):

```
SQLAlchemy>=2.0,<2.1
psycopg[binary]>=3.1
alembic>=1.13
pydantic-settings>=2.0
```

### 9.1 버전 선정 이유
* **SQLAlchemy 2.x**: 타이핑 개선, `Mapped[]`, FastAPI와 통합 사례 풍부.
* **psycopg 3 (binary)**: psycopg2-binary 대신 권장. Render의 Python 3.11 환경에서 wheels 제공.
* **alembic 1.13+**: SQLAlchemy 2.x 완전 지원.
* **pydantic-settings**: `BaseSettings` 통한 환경변수 검증 (Pydantic v2).

### 9.2 호환성
* 현재 `requirements.txt`에는 `streamlit`, `pandas`, `paddleocr` 등이 있으나 마이그레이션과 무관. **줄 삭제 금지.**

---

## 10. Alembic 마이그레이션 계획 (Alembic Migration Plan)

### 10.1 초기 설정 (Phase 1)

```
alembic init alembic
```

`alembic.ini` 와 `alembic/env.py` 수정 포인트:
* `sqlalchemy.url`을 빈 값으로 두고, `env.py`에서 `os.environ["DATABASE_URL"]`로 주입
* `target_metadata = Base.metadata` 설정
* 모든 모델을 `env.py`에서 import (autogenerate가 인식하도록)

### 10.2 마이그레이션 파일 순서

| Revision | 내용 | Phase |
|---|---|---|
| 0001 | `tenants` 테이블 | 2 |
| 0002 | `users` (= account_users) 테이블 + UNIQUE(login_id) | 2 |
| 0003 | `audit_logs` 테이블 | 2 |
| 0004 | `roles`, `user_roles` (필요 시) | 2 |
| 0005 | `customers` (tenant_id FK, 고객ID UNIQUE, soft delete) | 4 |
| 0006 | `customer_passport_hash`, `customer_reg_hash` (또는 컬럼 추가) | 4 |
| 0007 | `accommodation_providers` / `guarantor_connections` | 4 |
| 0008 | `events` (per-date 일정) | 5 |
| 0009 | `active_tasks` / `completed_tasks` / `planned_tasks` | 5 |
| 0010 | `daily_entries` / `daily_balances` | 5 |
| 0011 | `memos` (장/중/단기) | 5 |
| 0012 | `agent_signatures`, `customer_signatures`, `temp_signature_slots` | 5/6 |
| 0013 | `documents` (Drive 메타데이터) | 6 |
| 0014 | `marketing_posts`, `board_posts`, `board_comments` | 5/6 |
| 0015 | `certification_*` 5개 테이블 | 6 |

### 10.3 명령
```bash
# Phase 1 (구현 시점에 실행)
alembic init alembic
alembic revision --autogenerate -m "0001 initial tenants users"
alembic upgrade head
# 롤백: alembic downgrade -1
```

---

## 11. 초기 테이블 스키마 제안 (Proposed Initial Table Schemas)

> 모든 테이블은 `id BIGSERIAL PRIMARY KEY`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`, 가능한 경우 `deleted_at TIMESTAMPTZ NULL` (soft delete)을 가진다.

### 11.1 `tenants`
```sql
CREATE TABLE tenants (
  id              BIGSERIAL PRIMARY KEY,
  tenant_id       TEXT UNIQUE NOT NULL,        -- 기존 Accounts.tenant_id
  office_name     TEXT NOT NULL,
  office_adr      TEXT,
  biz_reg_no      TEXT,
  agent_rrn_hash  TEXT,                         -- 평문 저장 금지
  folder_id       TEXT,                         -- Google Drive 사무소 폴더
  customer_sheet_key TEXT,                      -- Sheets 백업기간 동안 유지
  work_sheet_key  TEXT,
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_tenants_active ON tenants(is_active);
```

### 11.2 `users`
```sql
CREATE TABLE users (
  id              BIGSERIAL PRIMARY KEY,
  login_id        TEXT UNIQUE NOT NULL,
  tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id) ON UPDATE CASCADE,
  password_hash   TEXT NOT NULL,                -- pbkdf2_hmac sha256 (현 방식 유지)
  contact_name    TEXT,
  contact_tel     TEXT,
  is_admin        BOOLEAN NOT NULL DEFAULT FALSE,
  is_active       BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at   TIMESTAMPTZ
);
CREATE INDEX idx_users_tenant ON users(tenant_id);
```

### 11.3 `audit_logs`
```sql
CREATE TABLE audit_logs (
  id              BIGSERIAL PRIMARY KEY,
  tenant_id       TEXT,                         -- NULL 가능 (시스템 이벤트)
  actor_login_id  TEXT,
  action          TEXT NOT NULL,                -- e.g. 'customer.update', 'task.delete'
  target_type     TEXT,                         -- e.g. 'customer', 'task'
  target_id       TEXT,
  payload         JSONB,                        -- 변경 전후 데이터 또는 요청 payload
  ip_address      INET,
  user_agent      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_tenant_time ON audit_logs(tenant_id, created_at DESC);
CREATE INDEX idx_audit_target ON audit_logs(target_type, target_id);
```

### 11.4 `customers` (Phase 4 — 본 단계에서 마이그레이션 금지)
```sql
CREATE TABLE customers (
  id                  BIGSERIAL PRIMARY KEY,
  tenant_id           TEXT NOT NULL REFERENCES tenants(tenant_id) ON UPDATE CASCADE,
  customer_id         TEXT NOT NULL,            -- 기존 고객ID (sheet 시절 ID 보존)
  korean_name         TEXT,
  surname_en          TEXT,
  given_en            TEXT,
  passport_no_hash    TEXT,                     -- SHA-256 해시; 마스킹 표시
  passport_no_last4   TEXT,                     -- "******1234"
  foreign_reg_hash    TEXT,                     -- 외국인등록번호 해시
  foreign_reg_last4   TEXT,
  nationality         TEXT,
  gender              TEXT,
  birth_date          DATE,
  card_issue_date     DATE,
  card_expiry_date    DATE,
  passport_issue_date DATE,
  passport_expiry_date DATE,
  address             TEXT,
  phone               TEXT,
  visa_status         TEXT,                     -- 체류자격 (예: F-2, D-10)
  visa_type           TEXT,
  memo                TEXT,
  drive_folder_id     TEXT,                     -- Google Drive 고객 폴더 ID
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at          TIMESTAMPTZ,
  CONSTRAINT uq_customer_per_tenant UNIQUE (tenant_id, customer_id)
);
CREATE INDEX idx_customers_tenant ON customers(tenant_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_customers_passport_hash ON customers(passport_no_hash);
CREATE INDEX idx_customers_card_expiry ON customers(card_expiry_date) WHERE deleted_at IS NULL;
CREATE INDEX idx_customers_passport_expiry ON customers(passport_expiry_date) WHERE deleted_at IS NULL;
```

> **여권번호/외국인등록번호 정책 (Phase 4 결정 필요):**
> 1) `passport_no` 평문 저장은 **금지** — 대신 `*_hash` + `*_last4`
> 2) 그러나 OCR 자동 작성·PDF 채움에서 평문이 필요하므로 **별도 암호화 컬럼**(예: `passport_no_encrypted bytea` + `pgcrypto`) 도입 고려
> 3) 본 단계에서 결정하지 않음. Phase 4 시작 전 별도 의사결정.

### 11.5 `events`, `active_tasks`, `daily_entries`, `memos`, `signatures` 등
스키마 초안은 기존 Sheets 컬럼을 1:1 매핑한다(`id`, `category`, `date`, `name`, `work`, ...). Phase 5 시작 시 라우터별로 확정.

### 11.6 `documents`
```sql
CREATE TABLE documents (
  id              BIGSERIAL PRIMARY KEY,
  tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id),
  customer_id     BIGINT REFERENCES customers(id),
  drive_file_id   TEXT NOT NULL,
  filename        TEXT NOT NULL,
  mime_type       TEXT,
  size_bytes      BIGINT,
  doc_type        TEXT,                         -- 위임장 / 하이코리아 / 신청서 등
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at      TIMESTAMPTZ
);
CREATE INDEX idx_documents_customer ON documents(customer_id);
```

---

## 12. 데이터 마이그레이션 전략 (Data Migration Strategy)

### 12.1 원칙
1. **고객 데이터는 마이그레이션 마지막에 한다.** 먼저 마이그레이션할 것은 인증/감사로그 같이 의존성 없는 도메인.
2. **모든 마이그레이션은 idempotent 해야 한다.** 재실행해도 동일 결과.
3. **마이그레이션 중에도 기존 Sheets 경로는 100% 작동해야 한다.**
4. **검증 단계 없이 Sheets 측 데이터 삭제 금지.**

### 12.2 단계별 전략

| Phase | 도메인 | 전략 |
|---|---|---|
| 2 | tenants/users/audit_logs | 1회성 임포트 (Accounts 시트 → PG). 그 후 가입/계정수정만 PG에 dual-write. 로그인은 일정 기간 Sheets 폴백 유지. |
| 3 | (전환 설계) | 도메인별로 dual-write or shadow-read 결정 |
| 4 | customers | dual-write (Sheets primary, PG shadow) → 동일 데이터 보장 확인 → PG primary 전환 |
| 5 | tasks/daily/events/memos | dual-write |
| 6 | documents | PG 신규 작성; Drive 메타만 PG에 기록 |
| 7 | 마케팅/게시판 | dual-write |

### 12.3 임포트 스크립트 위치
* `backend/scripts/migrate_*_to_postgres.py` (새 폴더 아님, 기존 `backend/scripts/` 활용)
* 본 단계에서 작성 금지. Phase별 시작 시 작성.

---

## 13. Sheets와의 공존 전략 (Coexistence Strategy)

### 13.1 핵심 원칙
* **Sheets 코드는 절대 제거하지 않는다.** Phase 7 종료 후에도 “읽기 전용 백업/내보내기”로 유지.
* **service 레이어 추가**: 라우터는 그대로 두고, `backend/services/<domain>_service.py`에 두 가지 경로를 모두 가진 함수 추가.

```python
# 예시 (의사 코드 — 실제 구현은 Phase별)
def get_customer(tenant_id, customer_id):
    if FEATURE_PG_CUSTOMERS:
        return _pg_get_customer(tenant_id, customer_id)
    return _sheets_get_customer(tenant_id, customer_id)

def save_customer(tenant_id, data):
    if FEATURE_PG_CUSTOMERS_WRITE:
        _pg_upsert_customer(tenant_id, data)   # primary write
    if FEATURE_SHEETS_WRITE_MIRROR:
        try:
            _sheets_upsert_customer(tenant_id, data)
        except Exception as e:
            log_mirror_failure(...)             # 미러 실패가 메인 트랜잭션을 깨면 안 됨
```

### 13.2 피처 플래그
* 환경변수로 제어 (기본 OFF):
  * `FEATURE_PG_USERS` (Phase 2 켜기)
  * `FEATURE_PG_CUSTOMERS` (Phase 4 켜기)
  * `FEATURE_PG_TASKS` (Phase 5 켜기)
* 모든 플래그는 OFF 시 현재와 100% 동일하게 동작해야 한다.

### 13.3 정합성 검증
* 야간 작업: `scripts/diff_sheets_vs_pg_<domain>.py` 작성 (Phase별).
* 결과를 audit_logs 또는 별도 `reconciliation_reports`에 저장.

---

## 14. 롤백 전략 (Rollback Strategy)

### 14.1 단계별 롤백

| Phase | 롤백 방식 |
|---|---|
| 1 (foundation) | `requirements.txt`에서 신규 라이브러리 제거, `backend/db/` 폴더 삭제. 배포 영향 없음. |
| 2 (auth tables) | 피처 플래그 OFF → 로그인이 Sheets로 폴백. PG 테이블은 둔다(`alembic downgrade` 안 함). |
| 3 (coexistence) | dual-write의 PG 쓰기만 끄면 즉시 Sheets-only 복귀. |
| 4-5 (data) | 동일 — 피처 플래그 OFF. |
| 6 (documents) | PG 메타만 끄고 Drive 파일은 그대로. |
| 7 (production) | Render에서 환경변수 `FEATURE_PG_*=false` 설정 → 이전 빌드 동작 복원. |

### 14.2 데이터 손실 방지
* PG → Sheets 역방향 동기화는 안 만든다. 대신 Sheets는 항상 PG와 함께 쓰여 있으므로 PG 장애 시 Sheets가 source of truth.
* Phase 7 직전까지 “Sheets primary, PG shadow” 모드 유지를 권장.

---

## 15. Render 배포 계획 (Deployment Plan)

### 15.1 사전 점검 (Phase 0)
* [ ] 현재 배포가 Render 상에서 정상 작동 확인 (`/health` 200)
* [ ] 현재 `.env` 백업 (개인 저장소, 절대 git에 올리지 않음)
* [ ] DB 마이그레이션 전 트래픽이 가장 적은 시간대 결정 (한국 새벽)

### 15.2 Phase 1 배포
* [ ] requirements.txt 변경 → 신규 빌드
* [ ] `backend/db/session.py` + `/health/db` 라우터 포함
* [ ] Render 환경변수 `DATABASE_URL` 추가
* [ ] 빌드 → 배포 → `/health/db` 호출해서 PG 연결 확인
* [ ] 비즈니스 라우터에 영향 없음 확인

### 15.3 Phase 2 배포
* [ ] alembic upgrade head (Render Shell 또는 release command)
* [ ] 한 테넌트(테스트용) 임포트 → PG로 로그인 시도 → 성공 확인
* [ ] 피처 플래그 ON 후 모니터링

### 15.4 Phase 4-7 배포
* 각 Phase는 별도 PR + 별도 배포 + 별도 모니터링 윈도우.

---

## 16. 검증 체크리스트 (Verification Checklist)

### Phase 0 — 안전 점검
* [ ] `.gitignore` 검토 완료
* [ ] `frontend/node_modules` 미추적 확인
* [ ] `.venv` 미추적 확인
* [ ] `샘플/`, `analysis/`, `.tmp.driveupload/`, `.tmp.drivedownload/`, `secrets/` 미추적 확인
* [ ] `.git` 크기 991MB 사실 인지
* [ ] 현재 `uvicorn backend.main:app --reload --port 8000` 정상 기동
* [ ] 현재 `npm run dev` 정상 기동
* [ ] 현재 `npx tsc --noEmit` 무에러
* [ ] `python -m compileall backend -q` 무에러
* [ ] 현재 로그인 / 고객조회 / 진행업무 작동 확인

### Phase 1 — Postgres 토대
* [ ] `requirements.txt`에 SQLAlchemy/psycopg/alembic/pydantic-settings 추가
* [ ] `pip install -r requirements.txt` 성공
* [ ] `backend/db/session.py` 작성
* [ ] `backend/db/base.py` 작성
* [ ] `alembic init alembic` 실행 및 `env.py` 설정
* [ ] `GET /health/db` 응답 200, latency 기록
* [ ] 기존 라우터 모두 그대로 작동 (smoke test)

### Phase 2 — 핵심 SaaS 테이블
* [ ] 0001 마이그레이션(`tenants`) 적용
* [ ] 0002 마이그레이션(`users`) 적용
* [ ] 0003 마이그레이션(`audit_logs`) 적용
* [ ] Accounts 시트 → PG 임포트 스크립트 dry-run
* [ ] dry-run 결과 검토
* [ ] 실제 임포트 실행
* [ ] 행 수 비교 (Sheets vs PG)
* [ ] 비밀번호 해시 동일성 확인 (한 명 로그인 테스트)

### Phase 3 — 공존 설계
* [ ] FEATURE 플래그 환경변수 명세 확정
* [ ] dual-write helper 패턴 결정

### Phase 4 — Customers
* [ ] 여권/외국인등록번호 암호화·해시 정책 결정
* [ ] `customers` 테이블 마이그레이션
* [ ] 임포트 스크립트 dry-run / 실제 임포트
* [ ] dual-write 활성 후 24시간 모니터링
* [ ] 야간 reconciliation 리포트 차이 0건 확인

### Phase 5 — 업무/일정/메모/결산
* [ ] 도메인별 dual-write
* [ ] 도메인별 reconciliation

### Phase 6 — 파일
* [ ] `documents` 테이블 + Drive 메타데이터 연결
* [ ] Drive 파일 자체는 이동 없음 확인

### Phase 7 — 운영 전환
* [ ] FEATURE_PG_*=true 전환
* [ ] 1주일 관찰 후 Sheets write를 read-only로 전환
* [ ] 1개월 관찰 후 Sheets 백업 주기 결정

---

## 17. 위험 / 불확실성 (Risks / Unknowns)

| 항목 | 위험 | 완화책 |
|---|---|---|
| `.git` 991MB | GitHub push 실패, clone 시간 폭증 | BFG / git filter-repo (별도 작업, 본 마이그레이션과 분리) |
| 비밀번호 해시 호환성 | `accounts_service.hash_password()`는 pbkdf2_hmac+base64. PG로 가져갈 때 동일 함수 재사용해야 검증 가능. | hash_password 모듈을 그대로 import해서 사용 |
| 캐릭터 인코딩 | 한글 컬럼명(`한글`, `여권`, `만기` 등)을 그대로 PG 컬럼명으로 쓰면 가독성/SQL 작성 부담 | PG에서는 영문 컬럼명으로 매핑 (예: `korean_name`, `passport_no_hash`) |
| 일정 시트 `일정` 특성 | 단일 셀에 줄단위로 일정을 저장 — 정규화 필요 | per-date events 테이블로 분해 |
| 메모 단일 셀 | A1 셀 한 곳에 자유 텍스트 — 그대로 컬럼 한 줄로 보관 | `memos(tenant_id, kind, content)` |
| 진행업무 ID 형식 | `daily-{uuid}` 같이 deterministic. 마이그레이션 시 충돌 방지 위해 그대로 유지 | `customer_id`처럼 TEXT 보존 |
| OCR 자동작성 PDF 필드명 | 백엔드에서 평문 여권번호 등을 PDF에 채움 → 해시 저장 시 평문 접근 경로 필요 | pgcrypto encrypted 컬럼 or 컨테이너 KMS 결정 (Phase 4) |
| Sheets 캐시 무효화 | dual-write 시 PG write 성공 + Sheets cache invalidation 누락 시 stale 가능 | 기존 `_invalidate_read_cache()` 호출을 dual-write helper에 포함 |
| Render PG SSL | 기본 SSL 강제. URL에 `sslmode=require` 누락 시 연결 거부 | DATABASE_URL 검수 체크리스트 |
| Render 리전 불일치 | DB와 Web Service 리전 불일치 시 매 쿼리 수십~수백 ms 지연 | 동일 리전 생성 |
| `잔액` 시트 `ws.clear()` | 본 마이그레이션과 무관하지만 잠재 데이터 손실 패턴 — 기록만 | 향후 별도 PR로 ID 기반 upsert로 전환 권장 |
| Streamlit 잔재 파일 (`app.py`, `pages/`, `database.py`, `google_drive_service.py`) | 실수로 import할 위험 | CLAUDE.md에 명시되어 있음. 삭제 금지(레퍼런스). |
| `pages/`가 git에 추적됨 | Streamlit 시절 파일이 여전히 트래킹 중. 새 페이지를 잘못 만들 위험 | 본 단계에서 손대지 말 것. 별도 cleanup PR. |

---

## 18. 절대 금지사항 (Do-Not-Touch List)

* [ ] **Google Sheets 로직을 제거하지 마라.** 본 마이그레이션 전 기간 동안 Sheets 코드는 그대로 유지된다.
* [ ] **고객 데이터를 첫 단계에서 마이그레이션하지 마라.** Phase 4 이후에만.
* [ ] **UI를 변경하지 마라.** 본 작업은 데이터 계층 작업이다.
* [ ] **파괴적 Git 명령을 실행하지 마라** (`git reset --hard`, `git push --force`, `git filter-repo` 등). `.git` 정리는 별도 작업.
* [ ] **비밀(.env, service_account, client_secret, hanwoory-*.json)을 커밋하지 마라.**
* [ ] **`샘플/`, `analysis/`, `.venv/`, `node_modules/`, `.next/`, `secrets/`를 Git에 포함시키지 마라.**
* [ ] **Streamlit 파일(`app.py`, `pages/*`, `database.py`, `google_drive_service.py`)을 현재 프로덕션 아키텍처의 근거로 삼지 마라.** 레퍼런스/레거시일 뿐.
* [ ] **테넌트 데이터를 admin sheet 또는 template sheet로 폴백하지 마라.** `tenant_service`의 ValueError 패턴을 유지.
* [ ] **PostgreSQL 작업의 일환으로 시트 전체 clear/overwrite를 도입하지 마라.** 기존 ID 기반 upsert 패턴을 유지.
* [ ] **본 단계(계획 작성)에서 데이터베이스를 생성하지 마라.** Render 대시보드 작업도 금지.
* [ ] **본 단계에서 alembic 마이그레이션을 실행하지 마라.**
* [ ] **로컬에서 PG를 띄우는 것조차 본 단계에서는 하지 마라.** Phase 1 시작 시점에 사용자 확인 후 진행.

---

## 19. 단계별 구현 순서 (Step-by-Step Implementation Order)

### Phase 0 — 안전 점검 및 저장소 위생

**Objective:** 마이그레이션 시작 전 현재 상태가 안전한지 확인.

**Files likely to change:** 없음 (read-only).
**Files that must not be changed:** 전부.

**Commands:**
```bash
git status
git ls-files | grep -E "node_modules|\.venv|\.next|secrets/|샘플/|analysis/" || echo "OK: 보호 대상 폴더가 추적되지 않음"
du -sh .git
uvicorn backend.main:app --reload --port 8000  # 정상 기동 확인
cd frontend && npm run dev                       # 정상 기동 확인
cd frontend && npx tsc --noEmit                  # 무에러
python -m compileall backend -q
```

**Expected result:** 모든 명령 무에러. `.git`은 991MB. 보호 대상 폴더는 untracked.
**Verification:** 위 명령 출력 캡처.
**Rollback:** 없음 (변경 없음).

---

### Phase 1 — PostgreSQL 토대만 추가

**Objective:** DB 연결 및 세션 모듈 추가. 비즈니스 로직 변경 없음.

**Files likely to change:**
* `requirements.txt` (의존성 4줄 추가)
* `backend/db/__init__.py` (신규)
* `backend/db/session.py` (신규)
* `backend/db/base.py` (신규)
* `backend/routers/health.py` (신규 — `/health/db` 추가)
* `backend/main.py` (health 라우터 등록 한 줄)
* `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako` (신규)

**Files that must not be changed:**
* `backend/services/tenant_service.py`
* `backend/services/accounts_service.py`
* `backend/routers/auth.py`, `customers.py`, `tasks.py`, ... (전체)
* `frontend/**`
* `.env`

**Commands:**
```bash
pip install SQLAlchemy psycopg[binary] alembic pydantic-settings
alembic init alembic
# session.py / base.py 작성
uvicorn backend.main:app --reload --port 8000
curl http://localhost:8000/health/db
```

**Expected result:** `/health/db`가 200 + `{"db": "ok", "latency_ms": <number>}` 반환. 기존 모든 엔드포인트 정상.
**Verification:** smoke test (로그인 → 고객 목록 → 진행업무 조회).
**Rollback:** 신규 파일 삭제, requirements.txt 4줄 제거, `main.py` 라우터 등록 한 줄 제거.

---

### Phase 2 — 핵심 SaaS 테이블

**Objective:** tenants / users / audit_logs 테이블 생성 + Accounts 시트 임포트.

**Files likely to change:**
* `backend/db/models/tenant.py`, `user.py`, `audit.py` (신규)
* `alembic/versions/0001_*.py`, `0002_*.py`, `0003_*.py` (신규)
* `backend/scripts/migrate_accounts_to_pg.py` (신규)

**Files that must not be changed:**
* 기존 로그인 라우터 `backend/routers/auth.py` (Phase 3에서 dual-read 추가 예정)
* `backend/services/accounts_service.py`의 hash 함수는 그대로 import만

**Commands:**
```bash
alembic revision --autogenerate -m "0001 tenants users audit_logs"
alembic upgrade head
python backend/scripts/migrate_accounts_to_pg.py --dry-run
python backend/scripts/migrate_accounts_to_pg.py --execute
```

**Expected result:** PG에 tenants/users 테이블 존재, Accounts 시트와 동일 행수.
**Verification:** `SELECT count(*) FROM users` == Accounts 시트 row count - 1(헤더). 한 계정 비밀번호 검증을 Python에서 hash_password 호출로 확인.
**Rollback:** `alembic downgrade -3` 또는 테이블 DROP.

---

### Phase 3 — 공존 설계

**Objective:** dual-write/shadow-read 패턴 결정 및 helper 모듈 작성.

**Files likely to change:**
* `backend/services/coexistence.py` (신규 — feature flag, dual-write helper)
* `backend/services/auth_service.py` (신규 — login flow 분리)

**Files that must not be changed:**
* 라우터 시그니처
* tenant_service.py

**Commands:** 없음 (설계 + 단위 테스트만).
**Expected result:** 피처 플래그 OFF 시 모든 기존 동작 그대로.
**Verification:** 전체 라우터 smoke test.
**Rollback:** 신규 모듈 삭제.

---

### Phase 4 — Customers 마이그레이션

**Objective:** customers 테이블 + Phase별 dual-write.

**Files likely to change:**
* `alembic/versions/0005_*.py`, `0006_*.py`, `0007_*.py`
* `backend/db/models/customer.py`, `relationship.py`
* `backend/services/customer_service.py` (신규)
* `backend/scripts/migrate_customers_to_pg.py`

**Files that must not be changed:**
* `backend/routers/customers.py` 라우터 시그니처
* `backend/services/tenant_service.py`

**Commands:**
```bash
alembic upgrade head
python backend/scripts/migrate_customers_to_pg.py --tenant <test_tenant> --dry-run
python backend/scripts/migrate_customers_to_pg.py --tenant <test_tenant> --execute
```

**Expected result:** PG의 customers 행수 = Sheets 행수. 모든 컬럼 1:1.
**Verification:** reconciliation script 차이 0건.
**Rollback:** 피처 플래그 OFF (PG 테이블은 그대로 유지).

---

### Phase 5 — 업무/일정/메모/결산 마이그레이션

**Objective:** 도메인별로 순차적 dual-write.

**Files:** 각 도메인별 service + script.
**Order:** events → memos → daily → planned_tasks → active_tasks → completed_tasks
**Rollback:** 도메인별 피처 플래그 OFF.

---

### Phase 6 — 파일 메타데이터

**Objective:** `documents` 테이블에 Drive 파일 메타 기록.
**파일 자체는 이동하지 않는다.**

---

### Phase 7 — 운영 전환

**Objective:** Render에서 PG primary로 전환.

**Commands (Render Dashboard):**
* `FEATURE_PG_USERS=true`
* `FEATURE_PG_CUSTOMERS=true`
* ... (도메인별)
* Sheets write는 mirror 모드로 일정 기간 유지
* 모니터링 후 Sheets write를 read-only로 점진적 종료

---

## 20. 나중에 실행할 명령 모음 (Commands to Run Later)

> 본 단계에서는 **절대 실행하지 않는다.** 각 Phase 시작 시점에 사용자 명시적 승인 후 실행.

```bash
# Phase 1
pip install SQLAlchemy "psycopg[binary]" alembic pydantic-settings
alembic init alembic
alembic revision --autogenerate -m "0001 tenants users audit_logs"
alembic upgrade head

# Phase 2
python backend/scripts/migrate_accounts_to_pg.py --dry-run
python backend/scripts/migrate_accounts_to_pg.py --execute

# Phase 4
python backend/scripts/migrate_customers_to_pg.py --tenant <id> --dry-run
python backend/scripts/migrate_customers_to_pg.py --tenant <id> --execute

# 검수
psql "$DATABASE_URL" -c "SELECT count(*) FROM tenants;"
psql "$DATABASE_URL" -c "SELECT count(*) FROM users;"
psql "$DATABASE_URL" -c "SELECT count(*) FROM customers WHERE tenant_id='<id>';"

# 롤백 (피처 플래그)
# Render Dashboard에서 FEATURE_PG_* = false 로 변경 → 자동 재배포
```

---

## 21. 최종 권고 (Final Recommendation)

### 21.1 지금 권장하는 **첫 번째 구현 과제**

**Phase 0 — 안전 점검**을 사용자와 함께 수행한 뒤,
**Phase 1 — Postgres 토대(read-only `/health/db`만)** 를 시작한다.

이유:
1. `.git` 991MB 문제는 마이그레이션과 분리해서 별도 작업으로 처리해야 한다 (BFG/filter-repo).
2. 데이터 마이그레이션 전에 PG 연결 자체가 안정적인지 먼저 확인해야 후속 단계가 의미 있다.
3. Phase 1은 비즈니스 코드를 건드리지 않으므로 가장 안전한 시작점.

### 21.2 본 단계에서 사용자에게 다시 확인이 필요한 사항

1. **`.git` 거대화 해결 시점** — 본 마이그레이션과 별도로 별도 PR/시점에 진행할지, 마이그레이션 전에 끝낼지.
2. **Render PostgreSQL 플랜** — Starter vs Standard.
3. **여권/외국인등록번호 암호화 정책** (Phase 4 시작 전에 결정).
4. **Sheets 백업 종료 시점** — Phase 7 종료 후에도 6개월/1년/영구 유지할지.
5. **`잔액` 시트 `ws.clear()` 패턴 수정** — 본 마이그레이션 범위에 포함할지, 별도 PR로 분리할지.

### 21.3 구현 시작 가능 여부

* **현재 상태:** 계획만 작성됨. 구현은 시작되지 않음.
* **다음 단계 진행 가능 여부:** Phase 0 안전 점검은 비파괴적이므로 즉시 진행 가능. Phase 1 이후는 **사용자 명시적 승인 후에만** 진행.

---

**END OF PLAN**
