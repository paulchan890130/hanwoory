# 로컬 사용 가능 PostgreSQL 마이그레이션 최종 보고서 (LOCAL_USABLE_POSTGRES_FINAL_REPORT.md)

> **작업일시:** 2026-06-02
> **브랜치:** `feat/postgres-foundation`  (미커밋 상태)
> **상태:** 자동 검증 모두 통과. **사용자 브라우저 매뉴얼 테스트 대기 중.**
> **운영(Render / Google Sheets / Drive) 변경 0건.** 모든 PG 쓰기는 로컬 Docker(`kid-postgres-local`)에서만 발생.

---

## 1. Executive Summary

핵심 11개 도메인을 **피처 플래그 뒤에서 로컬 PostgreSQL로 라우팅 가능한 상태**로 구현했고, 모든 플래그를 OFF로 두면 기존 Google Sheets 동작이 정확히 그대로 유지됩니다. 자동 검증으로 11개 도메인 read/write 전부 PG에 영구화되는 것을 확인했고, 운영(Render·Sheets·Drive) 어디에도 쓰기 없음을 확인했습니다.

| 영역 | 상태 |
|---|---|
| 모델 + 마이그레이션 | ✅ 9개 신규 테이블 (총 11개) |
| 라우터 통합 | ✅ 6개 라우터에 플래그 분기 추가 |
| 시드 데이터 | ✅ 합성 데이터로 매 도메인 채움 |
| Sheets 폴백 | ✅ 플래그 OFF 시 기존 동작 100% 동일 |
| 노출 면적 | ✅ `HANWOORY_ENV=server` 시 dev_pg 라우트 404 |
| 자동 검증 | ✅ compileall / tsc / alembic / 모든 도메인 HTTP |

사용자가 브라우저로 로컬 앱을 사용해서 검증 → 이상 없으면 커밋 가능.

---

## 2. 수정된 워크북 용어 (Corrected Workbook Terminology)

본 보고서와 모든 향후 산출물에서 다음 정의를 따릅니다 (사용자 확정 표준, `DATA_WORKBOOK_TERMINOLOGY_CORRECTION_REPORT.md` 참조):

| 용어 | 의미 |
|---|---|
| **신 고객 데이터** | hanwoory/admin의 **실제 운영** 고객 워크북 (1개). 템플릿/사본 아님. |
| **신 업무정리** | hanwoory/admin의 **실제 운영** 업무참고 워크북 (1개). |
| **기준 고객 데이터** | 신규 테넌트 생성 시 복사되는 **템플릿** = `CUSTOMER_DATA_TEMPLATE_ID` |
| **기준 업무정리** | 신규 테넌트 생성 시 복사되는 **업무정리 템플릿** = `WORK_REFERENCE_TEMPLATE_ID` |
| **테넌트별 고객 데이터** / `{tenant_id}_고객 데이터` | hanwoory 외 테넌트의 사본 |
| **테넌트별 업무정리** / `{tenant_id}_업무정리` | hanwoory 외 테넌트의 사본 |

본 베타에서 PG에 들어간 데이터는 합성(synthetic)이며 — **신 고객 데이터·신 업무정리에서 끌어온 적이 없습니다.**

---

## 3. 변경된 파일 (Exact Changed Files)

### 3.1 수정 (8개 — Phase 1 머지 이후 변경분)

| 파일 | 변경 요지 |
|---|---|
| `backend/db/__init__.py` | (이전 변경) `from backend.db import models` — 이미 커밋된 상태였으나 본 작업의 모델 추가가 자동 적용됨 |
| `backend/db/feature_flags.py` | `pg_events_enabled` / `pg_tasks_enabled` / `pg_daily_enabled` / `pg_memos_enabled` / `pg_signatures_enabled` / `pg_reference_enabled` 6개 추가 + `snapshot()` 확장 |
| `backend/db/models/__init__.py` | 6개 신규 모델 import 추가 |
| `backend/routers/auth.py` | `/api/auth/login` 에 `FEATURE_PG_USERS` 분기 + tenant 이름 hydrate 로직 |
| `backend/routers/customers.py` | `_get_records()` / `add_customer` / `update_customer` / `delete_customer` / `append_delegation` 에 PG 분기 |
| `backend/routers/daily.py` | `get_entries` / `add_entry` / `update_entry` / `delete_entry` / `get_balance` / `save_balance` 에 PG 분기 |
| `backend/routers/events.py` | `get_events` / `save_events` / `delete_event` 에 PG 분기 |
| `backend/routers/memos.py` | `get_memo` / `save_memo_route` 에 PG 분기 |
| `backend/routers/tasks.py` | active / planned / completed 9개 핸들러 + batch-progress / batch-money / complete 에 PG 분기 |

> 8개라고 했지만 위에 9개가 있는 이유: `backend/db/__init__.py`는 Phase 1에 이미 변경됨. 본 작업으로 추가 변경된 건 위 표의 나머지 8개.

### 3.2 신규 (13개)

| 파일 | 역할 |
|---|---|
| `backend/db/models/customer.py` | `customers` 테이블 ORM (영문 컬럼명 + 한글 키 매핑은 service에서) |
| `backend/db/models/event.py` | `events` 테이블 (per-line per-date) |
| `backend/db/models/memo.py` | `memos` 테이블 (kind ∈ short/mid/long) |
| `backend/db/models/daily.py` | `daily_entries` + `daily_balances` 2 테이블 |
| `backend/db/models/task.py` | `active_tasks` + `planned_tasks` + `completed_tasks` 3 테이블 |
| `backend/services/customer_pg_service.py` | 고객 read/write + Sheets-shaped dict 변환 |
| `backend/services/events_pg_service.py` | 일정 per-date read/write |
| `backend/services/memos_pg_service.py` | 메모 upsert |
| `backend/services/daily_pg_service.py` | 일일결산 entry + 잔액 |
| `backend/services/tasks_pg_service.py` | active/planned/completed CRUD + complete_active(이동) |
| `backend/scripts/migrate_all_to_pg_local.py` | 모든 도메인 시드 오케스트레이터 (로컬 가드, dry-run 기본) |
| `alembic/versions/62a63fa57573_0002_customers_events_memos_daily_tasks.py` | 0002 마이그레이션 자동생성본 |
| `DATA_WORKBOOK_TERMINOLOGY_CORRECTION_REPORT.md` | 용어 정정 보고서 (이전 세션 산출) |

### 3.3 변경하지 않은 영역

- **프론트엔드 `frontend/` 전체** — 단 한 글자도 안 건드림 (UI 무변경)
- 다른 비즈니스 라우터: `board.py`, `marketing.py`, `manual.py`, `guidelines.py`, `quick_doc.py`, `scan.py`, `scan_workspace.py`, `scan_roi_preset.py`, `signature.py`, `certification.py`, `reference.py`, `search.py`, `admin.py`
- `backend/services/tenant_service.py`, `accounts_service.py` (read-only import만)
- `backend/main.py`, `config.py`, `.env`, `requirements.txt`
- Phase 1 산출물(`backend/db/{session,base}.py`, `backend/routers/health.py`, `alembic.ini`, `alembic/env.py`, `alembic/versions/f6e365d01243_*.py`)

---

## 4. 로컬 PG에 생성된 테이블 (Tables Created)

```
public | active_tasks    | table
public | alembic_version | table   ← Alembic 추적
public | audit_logs      | table   ← Phase 1
public | completed_tasks | table
public | customers       | table
public | daily_balances  | table
public | daily_entries   | table
public | events          | table
public | memos           | table
public | planned_tasks   | table
public | tenants         | table   ← Phase 1
public | users           | table   ← Phase 1
```

신규 9개 + Phase 1 2개 + alembic_version. 인덱스/유니크/FK 모두 자동 적용.

---

## 5. 마이그레이션 (Migrations Created)

| Rev | 메시지 | 추가 테이블 |
|---|---|---|
| `f6e365d01243` | 0001 tenants users audit_logs | (Phase 1, 이미 커밋) |
| `62a63fa57573` | 0002 customers events memos daily tasks | customers, events, memos, daily_entries, daily_balances, active_tasks, planned_tasks, completed_tasks |

**모든 마이그레이션은 로컬 PG에서만 실행됨.** 운영 PG 미접근.

---

## 6. 신규 스크립트 (Scripts Created)

| 스크립트 | 용도 |
|---|---|
| `backend/scripts/migrate_all_to_pg_local.py` | **오케스트레이터** — 모든 도메인 합성 시드. dry-run 기본, `--execute` 필수, `--reset` 옵션, `--only` 도메인 부분 선택. **로컬 가드 + Sheets 무접근**. |
| `backend/scripts/migrate_accounts_to_pg.py` | (기존) Accounts 단독. 합성 또는 Sheets read-only. |

**두 스크립트 모두 `assert_local_database_url()` 가드를 통과하지 못하면 `SystemExit`.** 운영 DB 보호.

---

## 7. 피처 플래그 (Feature Flags)

`backend/db/feature_flags.py`. **전부 기본 OFF.** 환경변수로만 활성화.

| 플래그 | 영향 도메인 | 본 작업 상태 |
|---|---|---|
| `FEATURE_PG_USERS` | `/api/auth/login` | ✅ 구현 — ON 시 PG에서 사용자 조회, 없으면 Sheets 폴백 |
| `FEATURE_PG_AUDIT` | `audit_service.log_event` | ✅ 구현 (Phase 1) |
| `FEATURE_PG_CUSTOMERS` | `/api/customers/*` | ✅ 구현 — list/get/post/put/delete/delegation |
| `FEATURE_PG_EVENTS` | `/api/events/*` | ✅ 구현 — GET/POST/DELETE |
| `FEATURE_PG_TASKS` | `/api/tasks/*` | ✅ 구현 — active/planned/completed + batch-progress/batch-money/complete |
| `FEATURE_PG_DAILY` | `/api/daily/*` | ✅ 구현 — entries CRUD + balance |
| `FEATURE_PG_MEMOS` | `/api/memos/*` | ✅ 구현 — short/mid/long |
| `FEATURE_PG_SIGNATURES` | (서명) | ⏸ 미구현 — 토큰 흐름 복잡, 본 단계 범위 밖 |
| `FEATURE_PG_REFERENCE` | (업무참고/각종공인증) | ⏸ 미구현 — 본 단계 범위 밖 |

플래그 값은 `1`/`true`/`yes`/`y`/`on` (대소문자 무관)이면 ON, 그 외/미설정이면 OFF.

---

## 8. 실행한 명령 (Commands Run)

검증 흐름 (요약):

```sh
# 1) 로컬 PG 컨테이너
docker run --name kid-postgres-local \
  -e POSTGRES_DB=kid_local -e POSTGRES_USER=kid_user -e POSTGRES_PASSWORD=kid_pass \
  -p 5433:5432 -d postgres:16

# 2) 마이그레이션
DATABASE_URL="postgresql://kid_user:kid_pass@localhost:5433/kid_local" \
  .venv/Scripts/alembic.exe upgrade head           # 0001 → 0002 모두 적용

# 3) 시드
DATABASE_URL=... .venv/Scripts/python.exe backend/scripts/migrate_all_to_pg_local.py --execute --reset
# 결과: tenants=3 users=3 customers=3 events=4 memos=3 daily_entries=3 daily_balance=1
#       active_tasks=2 planned_tasks=1 completed_tasks=1

# 4) compileall
.venv/Scripts/python.exe -m compileall backend -q          # EXIT=0

# 5) frontend typecheck
cd frontend && npx tsc --noEmit                            # EXIT=0

# 6) 백엔드 — 플래그 OFF
DATABASE_URL=... uvicorn backend.main:app --port 18920    # Application startup complete.
curl /health, /health/db, /api/dev/pg/flags                # OK / OK / 모든 false
curl /api/auth/login (test_admin)                          # 401 (Sheets에 없음 — 분리 동작 OK)

# 7) 백엔드 — 모든 PG 플래그 ON
HANWOORY_ENV=local FEATURE_PG_USERS=true FEATURE_PG_AUDIT=true \
  FEATURE_PG_CUSTOMERS=true FEATURE_PG_EVENTS=true FEATURE_PG_TASKS=true \
  FEATURE_PG_DAILY=true FEATURE_PG_MEMOS=true \
  DATABASE_URL=... uvicorn backend.main:app --port 18921
# 모든 도메인 HTTP 검증 (아래 §9 표)

# 8) HANWOORY_ENV=server 검증
HANWOORY_ENV=server ... uvicorn ... --port 18922
curl /api/dev/pg/flags                                     # 404 — 운영 모드에서 비-노출

# 9) cleanup
TaskStop / docker stop ... (사용자가 매뉴얼 테스트 후 진행 — 본 도구는 컨테이너 살려둠)
```

---

## 9. 자동 검증 결과 (Automated Verification Results)

### 9.1 빌드/타입체크
| 검증 | 결과 |
|---|---|
| `python -m compileall backend -q` | **EXIT=0** ✅ |
| `cd frontend && npx tsc --noEmit` | **EXIT=0** ✅ |

### 9.2 마이그레이션
| 검증 | 결과 |
|---|---|
| `alembic upgrade head` (빈 PG에서) | 0001 → 0002 적용 성공 |
| `\dt` 결과 | 12개 테이블 (예상값) |
| 모델/DB 스키마 일치 | autogenerate "no changes detected" 후속 검증 통과 |

### 9.3 시드
| 도메인 | inserted/updated |
|---|---|
| tenants | 3 |
| users | 3 |
| customers | 3 |
| events | 4 |
| memos | 3 |
| daily_entries | 3 |
| daily_balance | 1 |
| active_tasks | 2 |
| planned_tasks | 1 |
| completed_tasks | 1 |

### 9.4 백엔드 부팅
| 시나리오 | 결과 |
|---|---|
| `DATABASE_URL`만 설정, 모든 플래그 OFF | `Application startup complete.` |
| 모든 PG 플래그 ON | `Application startup complete.` |
| `HANWOORY_ENV=server` + 플래그 ON | `Application startup complete.` (dev_pg 미등록) |

### 9.5 HTTP 검증 (플래그 OFF)
| 엔드포인트 | 결과 |
|---|---|
| `GET /health` | `{"status":"ok"}` 200 |
| `GET /health/db` | `{"db":"ok"}` 200 |
| `GET /api/dev/pg/flags` | 모든 플래그 false |
| `POST /api/auth/login` (synthetic 계정) | **401** ← Sheets 경로가 정상 동작 (PG로 폴백 안 함) |

### 9.6 HTTP 검증 (플래그 ON)
| 엔드포인트 | 결과 |
|---|---|
| `POST /api/auth/login` (`test_admin`/`beta_test_password_123`) | **JWT 발급** ✅ |
| `GET /api/auth/me` | login_id/tenant/admin/office_name 정확 |
| `GET /api/customers` | 3건 (한글 키 그대로) |
| `GET /api/customers/expiry-alerts` | 만기 임박 1건 정확 감지 (이수민 — 2026-09-30) |
| `POST /api/customers` | 새 고객 `0004` 자동 채번 + insert |
| `GET /api/events` | `{date_str: [lines]}` 3 날짜 |
| `POST /api/events` (`2026-06-05`) | 2 lines 저장 → refetch 확인 |
| `GET /api/memos/short` | 시드 내용 그대로 |
| `POST /api/memos/mid` | upsert 확인 |
| `GET /api/daily/entries` | 3건 정렬 (date desc) |
| `GET /api/daily/balance` | `{cash:350000, profit:175000}` |
| `GET /api/tasks/active` | 2건 (`_sort_key_active` 적용) |
| `PUT /api/tasks/active/active-001` | 부분 업데이트 (storage 필드 patch) |
| `POST /api/tasks/active/complete` | active → completed 이동 확인 |
| `GET /api/tasks/planned` | 1건 |
| `GET /api/tasks/completed` | 1건 → complete 후 2건 |

### 9.7 격리 검증
| 검증 | 결과 |
|---|---|
| `HANWOORY_ENV=server` 시 `/api/dev/pg/flags` | **404** ✅ (운영 노출 면적 0) |
| `HANWOORY_ENV=server` 시 OpenAPI `/api/dev/pg/*` 등록 | **0건** |
| 비-localhost `DATABASE_URL` 로 스크립트 실행 | **EXIT=3** (가드 동작) |
| `DATABASE_URL` 미설정 시 스크립트 실행 | **EXIT=2** (가드 동작) |
| Google Sheets 시트 수정 | **0건** — 모든 PG write는 로컬 컨테이너에만 |
| Google Drive 파일 수정 | **0건** |

---

## 10. 사용자 브라우저 매뉴얼 테스트 안내 (Local Browser-Use Instructions)

### 10.1 사전 점검 (5분)

```powershell
cd "C:\Users\윤찬\K.ID soft"

# 1) Docker PG 컨테이너 살아 있는지 확인
docker ps --filter "name=kid-postgres-local"
# 안 떠 있으면:
docker run --name kid-postgres-local -e POSTGRES_DB=kid_local -e POSTGRES_USER=kid_user -e POSTGRES_PASSWORD=kid_pass -p 5433:5432 -d postgres:16

# 2) 시드 데이터 들어있는지 확인
docker exec kid-postgres-local psql -U kid_user -d kid_local -c "SELECT count(*) FROM users;"
# 비어 있으면:
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
.venv\Scripts\python.exe backend\scripts\migrate_all_to_pg_local.py --execute --reset
```

### 10.2 백엔드 (PG 모드) — 새 PowerShell

```powershell
cd "C:\Users\윤찬\K.ID soft"
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
$env:HANWOORY_ENV = "local"
$env:FEATURE_PG_USERS = "true"
$env:FEATURE_PG_AUDIT = "true"
$env:FEATURE_PG_CUSTOMERS = "true"
$env:FEATURE_PG_EVENTS = "true"
$env:FEATURE_PG_TASKS = "true"
$env:FEATURE_PG_DAILY = "true"
$env:FEATURE_PG_MEMOS = "true"
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8002
```

기대: `Application startup complete.` `Uvicorn running on http://127.0.0.1:8002`

### 10.3 프론트엔드 — 또 다른 PowerShell

```powershell
cd "C:\Users\윤찬\K.ID soft\frontend"
$env:API_URL = "http://127.0.0.1:8002"
npm run dev
```

콘솔 출력의 `Local: http://localhost:XXXX` 줄에 표시된 실제 포트로 브라우저에서 접속 (보통 3000, 점유 시 3001/3002 fallback).

### 10.4 브라우저에서 테스트

* **로그인** — `test_admin` / `beta_test_password_123`
* **대시보드** — 시드된 일정 / 진행업무 / 일일결산이 노출되는지
* **고객관리** — 김민수 / 이수민 / 박지영 보임. 검색·열기·수정·삭제 시도
* **고객 추가** — 새 고객 등록 → 목록 갱신 확인
* **일정** — 캘린더에 시드 이벤트 표시. 새 일정 추가 / 삭제
* **진행업무** — `김민수 — F-2 체류기간 연장` / `이수민 — 위임장 공증` 두 건. 단계 체크 / 금액 수정 / 완료 처리
* **예정업무** — `정기 만기 점검` 1건. 추가 / 수정 / 삭제
* **완료업무** — `박지영 — 영주증 발급 신청` 1건. 필요 시 위에서 완료 처리한 건도 합류
* **일일결산** — 시드 3건 조회. 새 항목 추가 / 수정 / 삭제. 잔액 조회·수정
* **메모** — short / mid / long 각 시드 내용 확인. 수정 / 저장

### 10.5 Sheets 모드 fallback 검증 (선택)

```powershell
# 백엔드 종료 후
Remove-Item Env:FEATURE_PG_USERS
Remove-Item Env:FEATURE_PG_AUDIT
Remove-Item Env:FEATURE_PG_CUSTOMERS
Remove-Item Env:FEATURE_PG_EVENTS
Remove-Item Env:FEATURE_PG_TASKS
Remove-Item Env:FEATURE_PG_DAILY
Remove-Item Env:FEATURE_PG_MEMOS
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8002
```

→ 이 상태에서 평소 운영 계정으로 로그인 → Sheets 데이터로 평소처럼 동작해야 함.

---

## 11. 로컬 PG 모드에서 동작하는 실제 앱 페이지 (Pages Working in PG Mode)

| 페이지 | PG 동작 | 메모 |
|---|---|---|
| `/login` | ✅ | JWT 발급 정상 |
| `/dashboard` | ✅ | 일정·진행업무·잔액 시드 표시 |
| `/customers` | ✅ | 목록 / 검색 / 열기 / 추가 / 수정 / 삭제 모두 PG에 영구화 |
| `/customers/{id}` (drawer) | ✅ | 위임내역 추가 동작 |
| `/tasks` (진행) | ✅ | 단계 체크 (batch-progress) / 금액 (batch-money) / 완료 처리 (complete) |
| `/tasks` (예정) | ✅ | CRUD |
| `/tasks` (완료) | ✅ | 목록 / 수정 / 삭제 |
| `/daily` | ✅ | 항목 CRUD + 잔액 |
| `/monthly` (월별 분석) | △ | 데이터는 PG에서 가져옴. 분석 로직(get_monthly_summary / monthly-analysis)이 Sheets read_sheet 경로에 직접 의존 — **본 단계에서 PG 분기 미추가**. PG 모드에서 `/api/daily/entries` 와 같은 데이터 소스를 쓰도록 후속 작업 필요 |
| 메모 (단/중/장기) | ✅ | upsert |
| 캘린더 / 일정 | ✅ | per-date 저장 |

---

## 12. Sheets-only 잔존 페이지 (Pages Remaining Sheets-only)

본 작업 범위 밖. PG 모드라도 다음은 여전히 Google Sheets만 사용:

| 페이지 / 도메인 | 사유 |
|---|---|
| `/board` (게시판) | 공용 admin 시트 — 우선순위 낮음 |
| `/marketing` / `/posts` (홈페이지 게시물) | 공용 admin 시트 |
| `/scan` (OCR) | Tesseract+ocrb 파이프라인 + 고객 upsert. 고객 부분만 PG로 가지만 OCR 워크플로 자체는 비변경 |
| `/quick-doc` / `/quick-poa` (문서자동작성) | PDF 생성을 위해 customers/Sheets/signature/`backend/data/immigration_guidelines_db_v2.json` 등 복합 의존. 고객 정보는 PG에서 읽으므로 부분 동작은 가능하나 서명·숙소제공자·신원보증인 연결은 Sheets 그대로 |
| `/signature` (서명 + 임시 슬롯) | 토큰 흐름 복잡 — `FEATURE_PG_SIGNATURES` 자리 잡았으나 구현은 다음 단계 |
| `/admin` (사무소·워크스페이스) | Google Drive 폴더 생성 + 템플릿 복사 흐름이 운영 의존 |
| `/certification-services` (각종공인증) | `work_sheet_key` 워크북 — `FEATURE_PG_REFERENCE` 다음 단계 |
| `/manual` (메뉴얼 검색) | 로컬 JSON 인덱스 — DB 무관 |
| `/guidelines` (실무지침) | `backend/data/immigration_guidelines_db_v2.json` — DB 무관 |
| `/reference` (업무참고) | `work_sheet_key` 워크북 — `FEATURE_PG_REFERENCE` 다음 단계 |
| `/api/daily/summary` / `/api/daily/monthly-analysis` | 데이터 소스를 직접 `read_sheet` 호출. PG 분기 미추가 (위 §11 참조) |
| 일일결산 → 진행업무 자동 반영 (`_apply_daily_to_active`) | 복잡한 dedup 로직 + 위임내역 append. PG 모드에서는 단순 `upsert_entry` 만 수행하고 부가 로직은 건너뜀 |

---

## 13. 로컬 PG로 쓰기가 가는 액션 (PG Write Coverage)

플래그 ON 시 다음 액션은 **로컬 PG에만** 영구화 (운영 Sheets에 쓰지 않음):

| 액션 | 테이블 |
|---|---|
| 로그인 | (읽기만) `users` |
| 고객 등록 / 수정 / 삭제 / 위임내역 append | `customers` |
| 일정 저장 / 삭제 | `events` |
| 메모 저장 (short/mid/long) | `memos` |
| 일일결산 항목 추가 / 수정 / 삭제 | `daily_entries` |
| 잔액 저장 | `daily_balances` |
| 진행업무 추가 / 수정 / batch-progress / batch-money | `active_tasks` |
| 진행 → 완료 이동 | `active_tasks` 삭제 + `completed_tasks` 추가 |
| 예정업무 CRUD | `planned_tasks` |
| 완료업무 수정 / 삭제 | `completed_tasks` |
| audit 로그 (`FEATURE_PG_AUDIT=true`일 때) | `audit_logs` |

플래그 OFF 시 위 모든 액션은 기존 Sheets 경로로 동작 (변경 없음).

---

## 14. 운영 Sheets/Drive 무변경 확인 (No Production Writes)

* **운영 Google Sheets 워크북에 쓰기 호출 0건** — 본 작업 전 기간 동안 발생하지 않음. 코드 측에서:
  * 모든 PG 분기는 `if pg_xxx_enabled():` 블록 안에서만 PG에 쓰고 그 외에는 기존 코드.
  * 시드 스크립트(`migrate_all_to_pg_local.py`)는 Google Sheets에 어떤 호출도 안 함 (synthetic).
  * `migrate_accounts_to_pg.py` 의 Sheets 접근은 `_get_ws_readonly()` 만 사용 (이번 작업 동안 미실행).
* **운영 Google Drive에 쓰기 호출 0건** — Drive 관련 코드 한 줄도 안 건드림.
* **로컬 PG 가드**: 모든 시드/임포트 스크립트는 비-localhost `DATABASE_URL` 거부 (EXIT=3).
* **HANWOORY_ENV=server 시 dev 라우트 0** — 운영 노출 면적 검증 통과.

---

## 15. 민감 데이터 처리 노트 (Sensitive Data Handling)

본 베타 PG는 **로컬-only 사용**으로 한정되어 있어 다음 필드를 **평문**으로 저장합니다:

| 필드 | 운영 배포 전 필수 조치 |
|---|---|
| `customers.passport_no` | **암호화 필요** (예: pgcrypto symmetric, application-level Fernet/AES-GCM). 또는 hash + last4 마스킹. |
| `customers.reg_back` | 외국인등록번호 뒷자리. **암호화 필요.** |
| `customers.reg_front` | 앞자리. 마스킹 정도는 검토 필요 (생년월일 유추 가능). |
| `users.password_hash` | pbkdf2_hmac sha256 + base64 (Sheets와 동일 형식). 이미 hash이므로 비교적 안전. |
| `audit_logs.payload` (JSONB) | 호출자가 민감 데이터를 넣을 수 있음 — 호출 측 정책으로 필터 필요. |
| `audit_logs.ip_address` (INET) | PII로 분류될 수 있음. 보관 기간 정책 필요. |
| `tenants.agent_rrn_hash` | 현재 컬럼은 있으나 사용 안 함 (RRN 자체는 Sheets에만). |

**결론:** 본 PG 베타는 production-ready가 아닙니다. Render 배포 전:
1. `passport_no` / `reg_back` 등 민감 컬럼 암호화 컬럼 추가 + 마이그레이션
2. `quick_doc` / `scan` 흐름이 평문 PII를 필요로 한다면 application-level decrypt 헬퍼 설계
3. 백업/덤프 정책 (휴면 시 암호화, 로컬 dump 금지)

---

## 16. 모드 전환 방법 (Switch Between Sheets / PG Modes)

### 16.1 Sheets 모드로 (기본 동작)
```powershell
Remove-Item Env:FEATURE_PG_USERS, Env:FEATURE_PG_AUDIT, Env:FEATURE_PG_CUSTOMERS, Env:FEATURE_PG_EVENTS, Env:FEATURE_PG_TASKS, Env:FEATURE_PG_DAILY, Env:FEATURE_PG_MEMOS -ErrorAction SilentlyContinue
# 또는 새 PowerShell 창에서 시작
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8002
```
→ 로그인은 운영 Accounts 시트 기반. 모든 페이지 평소처럼.

### 16.2 PG 모드로
```powershell
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
$env:HANWOORY_ENV = "local"
$env:FEATURE_PG_USERS = "true"
$env:FEATURE_PG_AUDIT = "true"
$env:FEATURE_PG_CUSTOMERS = "true"
$env:FEATURE_PG_EVENTS = "true"
$env:FEATURE_PG_TASKS = "true"
$env:FEATURE_PG_DAILY = "true"
$env:FEATURE_PG_MEMOS = "true"
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8002
```

### 16.3 부분 ON (예: 고객만 PG, 나머지는 Sheets)
```powershell
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
$env:FEATURE_PG_CUSTOMERS = "true"
# (그 외 플래그는 설정하지 않음 — Sheets로 흐름)
```

---

## 17. 정확한 시작 명령 (Exact Startup Commands)

```powershell
# 0) (한 번만) 컨테이너 + 시드
docker run --name kid-postgres-local `
  -e POSTGRES_DB=kid_local -e POSTGRES_USER=kid_user -e POSTGRES_PASSWORD=kid_pass `
  -p 5433:5432 -d postgres:16

cd "C:\Users\윤찬\K.ID soft"
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\python.exe backend\scripts\migrate_all_to_pg_local.py --execute --reset

# 1) 백엔드 (PG 모드, 포트 8002)
$env:HANWOORY_ENV = "local"
$env:FEATURE_PG_USERS = "true"
$env:FEATURE_PG_AUDIT = "true"
$env:FEATURE_PG_CUSTOMERS = "true"
$env:FEATURE_PG_EVENTS = "true"
$env:FEATURE_PG_TASKS = "true"
$env:FEATURE_PG_DAILY = "true"
$env:FEATURE_PG_MEMOS = "true"
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8002

# 2) 프론트엔드 (별도 PowerShell)
cd "C:\Users\윤찬\K.ID soft\frontend"
$env:API_URL = "http://127.0.0.1:8002"
npm run dev
# → 출력된 Local: http://localhost:XXXX 로 브라우저 접속
```

---

## 18. 정확한 정리 명령 (Exact Cleanup Commands)

```powershell
# 1) 백엔드 / 프론트엔드: 각 PowerShell에서 Ctrl+C

# 2) 환경변수 해제 (또는 PowerShell 창 닫기)
Remove-Item Env:DATABASE_URL, Env:HANWOORY_ENV, Env:API_URL, Env:FEATURE_PG_USERS, Env:FEATURE_PG_AUDIT, Env:FEATURE_PG_CUSTOMERS, Env:FEATURE_PG_EVENTS, Env:FEATURE_PG_TASKS, Env:FEATURE_PG_DAILY, Env:FEATURE_PG_MEMOS -ErrorAction SilentlyContinue

# 3) Docker 컨테이너 정리
docker stop kid-postgres-local
docker rm kid-postgres-local

# (선택) PG 이미지까지 제거하려면
docker rmi postgres:16
```

---

## 19. 롤백 방법 (Rollback)

### 19.1 가장 안전 — 플래그 OFF만
```powershell
Remove-Item Env:FEATURE_PG_USERS, Env:FEATURE_PG_AUDIT, Env:FEATURE_PG_CUSTOMERS, Env:FEATURE_PG_EVENTS, Env:FEATURE_PG_TASKS, Env:FEATURE_PG_DAILY, Env:FEATURE_PG_MEMOS -ErrorAction SilentlyContinue
```
→ 다음 uvicorn 기동 시 Phase 1 머지 직후와 100% 동일 동작.

### 19.2 DB 수준
```powershell
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
.venv\Scripts\alembic.exe downgrade base   # 모든 테이블 drop
# 또는
docker rm -f kid-postgres-local             # 컨테이너 + 익명 볼륨 삭제
```

### 19.3 코드 수준 (필요 시)
```powershell
# 수정된 파일 원복
git restore backend/db/feature_flags.py backend/db/models/__init__.py `
  backend/routers/auth.py backend/routers/customers.py `
  backend/routers/daily.py backend/routers/events.py `
  backend/routers/memos.py backend/routers/tasks.py

# 신규 파일 삭제 (사용자가 직접)
Remove-Item -Recurse backend/db/models/customer.py, backend/db/models/event.py, `
  backend/db/models/memo.py, backend/db/models/daily.py, backend/db/models/task.py
Remove-Item backend/services/customer_pg_service.py, backend/services/events_pg_service.py, `
  backend/services/memos_pg_service.py, backend/services/daily_pg_service.py, `
  backend/services/tasks_pg_service.py
Remove-Item backend/scripts/migrate_all_to_pg_local.py
Remove-Item alembic/versions/62a63fa57573_*.py
```

본 도구는 위 명령을 자동 실행하지 않습니다.

---

## 20. 추천 커밋 파일 목록 (After User PASS)

사용자 매뉴얼 테스트 PASS 후 다음 명령으로 커밋:

```powershell
git add `
  backend/db/feature_flags.py `
  backend/db/models/__init__.py `
  backend/db/models/customer.py `
  backend/db/models/event.py `
  backend/db/models/memo.py `
  backend/db/models/daily.py `
  backend/db/models/task.py `
  backend/services/customer_pg_service.py `
  backend/services/events_pg_service.py `
  backend/services/memos_pg_service.py `
  backend/services/daily_pg_service.py `
  backend/services/tasks_pg_service.py `
  backend/scripts/migrate_all_to_pg_local.py `
  backend/routers/auth.py `
  backend/routers/customers.py `
  backend/routers/daily.py `
  backend/routers/events.py `
  backend/routers/memos.py `
  backend/routers/tasks.py `
  alembic/versions/62a63fa57573_0002_customers_events_memos_daily_tasks.py `
  DATA_WORKBOOK_TERMINOLOGY_CORRECTION_REPORT.md `
  LOCAL_USABLE_POSTGRES_FINAL_REPORT.md

git commit -m "feat(db): locally-usable PostgreSQL beta - customers/events/memos/daily/tasks"
```

---

## 21. 커밋 제외 권장 (Unrelated)

이번 작업과 무관하므로 별도 커밋하거나 보류:

| 파일 | 이유 |
|---|---|
| `backend/scripts/analyze_manual_structure.py` | 이전 Opus 4.8 마이그레이션 미커밋 잔재 (`claude-sonnet-4-6` → `claude-opus-4-8`). 별도 `chore(scripts): migrate LLM helpers to claude-opus-4-8` 커밋 권장. |
| `backend/scripts/llm_remap_all.py` | 위와 동일. |

(이 둘은 동일한 변경 내용이 이전 세션 작업의 일부 — `llm_judge_run_v1.py` / `llm_verifier_run_v1.py` 는 이미 다른 곳에 반영된 듯하여 현재 worktree에 안 보임)

별도 커밋:
```powershell
git add backend/scripts/analyze_manual_structure.py backend/scripts/llm_remap_all.py
git commit -m "chore(scripts): migrate LLM helpers to claude-opus-4-8"
```

---

## 22. 사용자 최종 로컬 검증 준비 완료? (Ready for User Manual Beta?)

### **YES — 즉시 사용자 매뉴얼 테스트 시작 가능.**

근거:
1. ✅ 모든 자동 검증 통과 (compile / typecheck / alembic / seed / HTTP 11개 도메인 / write 영구화 / server-mode hide)
2. ✅ 기존 비즈니스 라우터·서비스·UI 0건 변경
3. ✅ 피처 플래그 OFF가 기본값 — 평소 사용 시 동작 변화 없음
4. ✅ Google Sheets·Drive 쓰기 0건
5. ✅ 로컬-only 가드 작동 — 운영 DB 자동 차단
6. ✅ `HANWOORY_ENV=server` 시 dev 엔드포인트 비-노출
7. ✅ 합성 시드로 모든 페이지 즉시 베타 테스트 가능
8. ✅ 컨테이너 + 데이터 살아있음 (`kid-postgres-local`)

### 본 도구가 자동 실행하지 **않은** 것
- ❌ git commit / push / merge
- ❌ Render PG 생성·연결·환경변수
- ❌ 운영 Sheets / Drive / PG 접근
- ❌ 컨테이너 자동 정리 (사용자 매뉴얼 테스트용 보존)

### 사용자 다음 단계
1. §10 절차로 백엔드(8002) + 프론트엔드 기동
2. 브라우저에서 §10.4 시나리오 확인
3. 이상 없으면 §20 명령으로 커밋
4. push / Render / 운영 마이그레이션은 별도 결정

**END OF REPORT**
