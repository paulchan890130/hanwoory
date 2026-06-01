# 로컬 PostgreSQL 베타 구현 보고서 (LOCAL_POSTGRES_BETA_REPORT.md)

> **작업일시:** 2026-06-01
> **브랜치:** `feat/postgres-foundation` (미커밋 상태)
> **상태:** 구현 완료 + 자동 검증 통과. **사용자 매뉴얼 베타 테스트 대기 중.**
> **연관 문서:** `LOCAL_POSTGRES_BETA_PLAN.md`, `PHASE1_POSTGRES_FOUNDATION_REPORT.md`, `PHASE1_LOCAL_DB_VERIFICATION_REPORT.md`, `RENDER_POSTGRES_SETUP_GUIDE.md`

---

## 1. 변경된 파일 (Changed Files)

### 1.1 수정 (2개)
| 파일 | 변경 |
|---|---|
| `backend/db/__init__.py` | `from backend.db import models  # noqa: F401` 한 줄 — `Base.metadata` 등록 |
| `backend/main.py` | `RUN_ENV == "local"` 시에만 `dev_pg` 라우터 등록 (조건부 7줄) |

### 1.2 신규 (11개)
| 파일 | 라인 수(약) | 역할 |
|---|---|---|
| `backend/db/models/__init__.py` | 14 | 모델 패키지 진입점 — Tenant/AccountUser/AuditLog import |
| `backend/db/models/tenant.py` | 50 | `tenants` 테이블 ORM |
| `backend/db/models/user.py` | 65 | `users` 테이블 ORM (FK → tenants.tenant_id) |
| `backend/db/models/audit.py` | 50 | `audit_logs` 테이블 ORM (JSONB payload, INET ip) |
| `backend/db/feature_flags.py` | 45 | `pg_users_enabled()` / `pg_audit_enabled()` / `pg_customers_enabled()` / `snapshot()` |
| `backend/db/local_guard.py` | 50 | `assert_local_database_url()` — 비-localhost 거부 |
| `backend/services/audit_service.py` | 55 | `log_event()` — best-effort, 실패 silent |
| `backend/services/auth_pg_service.py` | 60 | `find_user_pg()` / `verify_login_pg()` |
| `backend/routers/dev_pg.py` | 140 | 로컬 베타 dev 엔드포인트 (`HANWOORY_ENV=local`에서만 등록) |
| `backend/scripts/migrate_accounts_to_pg.py` | 270 | Accounts → 로컬 PG 임포트 (dry-run 기본, `--seed-synthetic` 옵션) |
| `alembic/versions/f6e365d01243_0001_tenants_users_audit_logs.py` | autogen | Alembic 0001 리비전 (3 테이블 + 5 인덱스) |

### 1.3 변경하지 않음 (Files NOT Changed)

확인 완료 — 다음은 손대지 않음:
- `backend/routers/auth.py`, `customers.py`, `tasks.py`, `daily.py`, `events.py`, `memos.py`, `board.py`, `signature.py`, `quick_doc.py`, `admin.py`, ... (모든 비즈니스 라우터)
- `backend/services/tenant_service.py`, `accounts_service.py`(import만), `signature_service.py`, `certification_service.py`, ... (모든 비즈니스 서비스)
- `frontend/` 전체 (한 글자도 안 건드림)
- `.env`, `secrets/`, `config.py`
- `requirements.txt` (Phase 1에서 추가한 4개 의존성 그대로 사용)

---

## 2. 실행한 명령 (Commands Run)

| # | 명령 | 결과 |
|---|---|---|
| 1 | `git status / git log` (선행 상태 확인) | `feat/postgres-foundation`, Phase 1 커밋됨 |
| 2 | `python -m compileall backend -q` | EXIT=0 |
| 3 | `docker run --name kid-postgres-local -e POSTGRES_DB=kid_local -e POSTGRES_USER=kid_user -e POSTGRES_PASSWORD=kid_pass -p 5433:5432 -d postgres:16` | 컨테이너 시작 |
| 4 | `docker exec ... pg_isready` 폴링 | `PG_READY` |
| 5 | `DATABASE_URL=... alembic revision --autogenerate -m "0001 tenants users audit_logs"` | 3 테이블 + 2 인덱스 자동 감지 → `f6e365d01243_*.py` 생성 |
| 6 | `DATABASE_URL=... alembic upgrade head` | `Running upgrade -> f6e365d01243` |
| 7 | `psql -c "\dt"` | 4 테이블 (audit_logs, tenants, users, alembic_version) |
| 8 | `psql -c "\di"` | 9 인덱스 (pk × 4, unique × 2, audit × 2, fk × 1) |
| 9 | `migrate_accounts_to_pg.py --seed-synthetic --execute` | tenants: 3 inserted, users: 3 inserted |
| 10 | 가드 테스트: 비-localhost URL → EXIT=3 | ✅ 거부 |
| 11 | 가드 테스트: 미설정 URL → EXIT=2 | ✅ 거부 |
| 12 | 가드 테스트: localhost + no `--execute` → dry-run | ✅ "no DB changes made" |
| 13 | `uvicorn` 기동 (플래그 OFF) | `Application startup complete.` |
| 14 | `GET /api/dev/pg/users/count` (off) | HTTP 503, `FEATURE_PG_USERS is off` |
| 15 | `POST /api/dev/pg/login-test` (off) | HTTP 503, 플래그 off 안내 |
| 16 | `uvicorn` 재기동 (USERS+AUDIT on) | OK |
| 17 | `GET /api/dev/pg/users/count` | `{"count":3}` |
| 18 | `POST /api/dev/pg/login-test` (정상 자격증명) | `{"ok":true, ...}` |
| 19 | `POST /api/dev/pg/login-test` (잘못된 비밀번호 / 비활성 / 미존재) | 모두 `{"ok":false,"reason":"invalid_credentials_or_inactive"}` (단일 메시지) |
| 20 | `POST /api/dev/pg/audit-test` | `rows_before=0, rows_after=1, delta=1` |
| 21 | `GET /api/dev/pg/customers/ping` (CUSTOMERS flag off) | HTTP 503 |
| 22 | `HANWOORY_ENV=server` 로 재기동 → dev_pg 노출 확인 | **HTTP 404** + OpenAPI 0건 (운영 모드에서 비-노출) |
| 23 | `cd frontend && npx tsc --noEmit` | EXIT=0 |

---

## 3. 로컬에 생성된 테이블 (Database Tables Created)

```sql
                      List of relations
 Schema |      Name       | Type  |  Owner   
--------+-----------------+-------+----------
 public | alembic_version | table | kid_user   ← Alembic 버전 추적용 (1행)
 public | audit_logs      | table | kid_user
 public | tenants         | table | kid_user
 public | users           | table | kid_user
```

### 3.1 인덱스
| 인덱스 | 테이블 | 컬럼 |
|---|---|---|
| `tenants_pkey` | tenants | id (PK) |
| `tenants_tenant_id_key` | tenants | tenant_id (UNIQUE) |
| `users_pkey` | users | id (PK) |
| `users_login_id_key` | users | login_id (UNIQUE) |
| `ix_users_tenant_id` | users | tenant_id (FK 인덱스) |
| `audit_logs_pkey` | audit_logs | id (PK) |
| `idx_audit_tenant_time` | audit_logs | (tenant_id, created_at) |
| `idx_audit_target` | audit_logs | (target_type, target_id) |
| `alembic_version_pkc` | alembic_version | version_num (PK) |

### 3.2 외래키
- `users.tenant_id` → `tenants.tenant_id` (`ON UPDATE CASCADE`)

---

## 4. 마이그레이션 결과 (Migration Results)

| 항목 | 결과 |
|---|---|
| Alembic autogenerate | ✅ 모델 3개 + 인덱스 2개 모두 감지 |
| `alembic upgrade head` | ✅ 단일 트랜잭션으로 적용 |
| `alembic_version` 행 | `f6e365d01243` (단일 행) |
| 충돌·경고 | 없음 |

생성된 마이그레이션 파일: `alembic/versions/f6e365d01243_0001_tenants_users_audit_logs.py`

---

## 5. 테스트한 피처 플래그 (Feature Flags Tested)

| 플래그 | OFF 동작 | ON 동작 |
|---|---|---|
| `FEATURE_PG_USERS` | `/users/count` 503, `/login-test` 503, `/audit-test` 정상 동작과 무관 | `/users/count`=3, `/login-test`(정상)→ ok:true, (오답/비활성/미존재)→ ok:false |
| `FEATURE_PG_AUDIT` | `/audit-test` 503; `audit_service.log_event()` no-op | `/audit-test` 정상; `audit_logs` 행 +1 |
| `FEATURE_PG_CUSTOMERS` | `/customers/ping` 503 | 501 (Not implemented — 의도) |

### 환경별 라우터 등록
| `HANWOORY_ENV` | dev_pg 라우터 등록 | `/api/dev/pg/*` 응답 |
|---|---|---|
| `local` | ✅ 등록 | 플래그에 따라 200 / 503 |
| `server` | ❌ **미등록** | HTTP 404 (OpenAPI에 0건) |

---

## 6. 기존 Google Sheets 동작 무변경 확인 (Google Sheets Behavior)

| 항목 | 결과 |
|---|---|
| `backend/services/tenant_service.py` | 무변경 ✅ |
| `backend/services/accounts_service.py` | 무변경 (read-only `_get_ws_readonly()`만 import) ✅ |
| `backend/routers/auth.py` | 무변경 — 기존 `/api/auth/login` Sheets 흐름 그대로 ✅ |
| 비즈니스 라우터 (customers/tasks/daily/...) | 모두 무변경 ✅ |
| OpenAPI에 기존 라우트 노출 | ✅ 변화 없음 (admin/auth/board/certification/customers/... 그대로) |
| 임포트 스크립트의 Sheets 접근 | **read-only `get_all_records()` 만 호출**, 어떤 쓰기 메서드도 사용 안 함 |
| 운영 Sheets 행 수 / 내용 | 본 작업으로 변경된 흔적 0 (스크립트는 dry-run 기본, `--execute`는 로컬 PG에만 insert) |

---

## 7. 백엔드 컴파일 결과 (Backend Compile)

```
.venv/Scripts/python.exe -m compileall backend -q
EXIT=0
```

✅ 신규 11개 + 수정 2개 파일 전부 무에러.

---

## 8. 프론트엔드 타입체크 결과 (Frontend Typecheck)

```
cd frontend && npx tsc --noEmit
EXIT=0
```

✅ frontend 한 글자도 변경 안 함 → 무에러 (예상대로).

---

## 9. 로컬 백엔드 기동 결과 (Backend Startup)

3가지 시나리오 모두 정상 부팅:

| 시나리오 | 결과 | 비고 |
|---|---|---|
| `DATABASE_URL=local-pg`, 플래그 모두 OFF | `Application startup complete.` | 기본 운영 흐름 시뮬레이션 |
| `DATABASE_URL=local-pg` + `FEATURE_PG_USERS=true` + `FEATURE_PG_AUDIT=true` | `Application startup complete.` | PG 경로 활성 |
| `HANWOORY_ENV=server` + 위와 동일 | `Application startup complete.` | dev_pg 미등록 (404 확인됨) |

* `/health` 모든 시나리오에서 200
* `/health/db` cold 93ms → 정상 (PG에 실제 SELECT 1 성공)

---

## 10. 로컬 프론트엔드 기동 결과 (Frontend Startup)

본 작업 단계에서는 `npm run dev` 신규 기동 안 함 — frontend 코드 변경 0건이며 이전 검증(`PHASE1_LOCAL_DB_VERIFICATION_REPORT.md`)에서 4초 만에 ready 확인. **사용자 매뉴얼 베타 테스트 §11 항목에 포함**.

---

## 11. 사용자 매뉴얼 베타 테스트 체크리스트 (For You)

> 아래는 본 도구가 아닌 **사용자가 직접** 수행할 항목입니다. 본 시점에 Docker PG 컨테이너(`kid-postgres-local`)가 5433 포트에서 실행 중이며 3 tenant + 3 user + 1 audit row가 들어 있습니다.

### 11.1 사전 점검
- [ ] `git status` 로 의도된 파일만 변경되었는지 확인
- [ ] `git diff backend/main.py backend/db/__init__.py` — 변경 라인이 의도와 일치하는지
- [ ] 새 파일들 1차 검토 (`backend/db/models/*`, `backend/db/feature_flags.py`, `backend/db/local_guard.py`, `backend/services/audit_service.py`, `backend/services/auth_pg_service.py`, `backend/routers/dev_pg.py`, `backend/scripts/migrate_accounts_to_pg.py`)

### 11.2 인프라 상태 확인
- [ ] `docker ps --filter name=kid-postgres-local` — 컨테이너 살아있음
- [ ] 별도 PowerShell 세션에서:
  ```sh
  docker exec kid-postgres-local psql -U kid_user -d kid_local -c "SELECT COUNT(*) FROM users;"
  ```
  → `3`

### 11.3 플래그 OFF — 기존 동작 100% 유지
- [ ] PowerShell 새 세션:
  ```sh
  $env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
  # 플래그는 일부러 설정 안 함 (= OFF)
  .venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
  ```
- [ ] 다른 터미널에서 `curl http://127.0.0.1:8000/health` → `ok`
- [ ] `curl http://127.0.0.1:8000/health/db` → `db:"ok"`
- [ ] `curl http://127.0.0.1:8000/api/dev/pg/users/count` → **HTTP 503** (플래그 off)
- [ ] **(중요) `frontend/`에서 `npm run dev` → 브라우저에서 평소대로 로그인 → 대시보드/고객/진행업무가 평소처럼 동작**
- [ ] Google Sheets `Accounts` 시트는 한 글자도 안 바뀌었는지 확인

### 11.4 플래그 ON — PG 경로 검증
- [ ] uvicorn 종료(`Ctrl+C`) → 같은 세션에서:
  ```sh
  $env:FEATURE_PG_USERS = "true"
  $env:FEATURE_PG_AUDIT = "true"
  .venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
  ```
- [ ] `curl http://127.0.0.1:8000/api/dev/pg/flags` → `{"FEATURE_PG_USERS":true, ...}`
- [ ] `curl http://127.0.0.1:8000/api/dev/pg/users/count` → `{"count":3}`
- [ ] 로그인 성공 케이스:
  ```sh
  curl -X POST -H "Content-Type: application/json" `
    -d '{\"login_id\":\"test_admin\",\"password\":\"beta_test_password_123\"}' `
    http://127.0.0.1:8000/api/dev/pg/login-test
  ```
  → `{"ok":true,"login_id":"test_admin","tenant_id":"test_admin","is_admin":true}`
- [ ] 잘못된 비밀번호 / 비활성(`inactive_user`) / 미존재(`nope`) 모두 `{"ok":false,"reason":"invalid_credentials_or_inactive"}`
- [ ] audit 로그 추가:
  ```sh
  curl -X POST -H "Content-Type: application/json" `
    -d '{\"action\":\"user.smoke\"}' `
    http://127.0.0.1:8000/api/dev/pg/audit-test
  ```
  → `rows_before / rows_after / delta` 응답, delta=1
- [ ] **(중요) 같은 백엔드에서 기존 `/api/auth/login`이 평소처럼 Google Sheets로 로그인되는지 재확인** — PG 플래그가 켜져 있어도 기존 라우터는 Sheets만 사용

### 11.5 격리/안전 검증
- [ ] 잘못된 URL로 스크립트 실행 시도:
  ```sh
  $env:DATABASE_URL = "postgresql://user:pw@somehost.example.com:5432/db"
  .venv\Scripts\python.exe backend\scripts\migrate_accounts_to_pg.py --seed-synthetic --execute
  ```
  → 즉시 종료, "DATABASE_URL host '…' is NOT in ['127.0.0.1', '::1', 'localhost']"
- [ ] `HANWOORY_ENV=server` 시뮬레이션:
  ```sh
  $env:HANWOORY_ENV = "server"
  .venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
  curl http://127.0.0.1:8000/api/dev/pg/flags
  ```
  → HTTP 404 (운영 모드에서 라우트 미등록)
- [ ] Google Sheets / Drive 어떤 파일도 본 작업 동안 수정 흔적 없는지 운영자 시점 점검

### 11.6 (옵션) 실제 Accounts 시트 → 로컬 PG
> 본 도구는 이 단계를 자동 실행하지 않았습니다. 운영 시트 사본을 로컬 PG에 넣고 싶다면 사용자가 직접:
```sh
# dry-run 먼저 — 무엇이 import될지 확인
.venv\Scripts\python.exe backend\scripts\migrate_accounts_to_pg.py
# 결과 검토 후
.venv\Scripts\python.exe backend\scripts\migrate_accounts_to_pg.py --execute
```
* Sheets는 read-only로 접근, 운영 Sheets 미변경
* 로컬 PG의 기존 3 합성 행은 login_id 기준 upsert되어 충돌 시 update됨 (또는 새 별도 login_id면 그냥 추가)

### 11.7 정리
- [ ] uvicorn 종료
- [ ] `docker stop kid-postgres-local && docker rm kid-postgres-local`
- [ ] 새 PowerShell 세션 (또는 `$env:DATABASE_URL = $null`, `$env:FEATURE_PG_USERS = $null`, `$env:FEATURE_PG_AUDIT = $null`, `$env:HANWOORY_ENV = $null`)

---

## 12. 롤백 방법 (Rollback)

### 12.1 가장 안전 — 플래그 OFF만
PowerShell 환경변수 해제:
```sh
$env:FEATURE_PG_USERS = $null
$env:FEATURE_PG_AUDIT = $null
```
→ 다음 uvicorn 기동 시 Phase 1 머지 직후와 100% 동일 동작.

### 12.2 DB 수준
```sh
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
.venv\Scripts\alembic.exe downgrade base   # 모든 테이블 drop
# 또는 컨테이너 자체 삭제
docker rm -f kid-postgres-local
```

### 12.3 코드 수준
```sh
git restore backend/db/__init__.py backend/main.py
# 신규 파일 제거 — 본 도구는 자동 실행하지 않습니다. 사용자가 직접:
rm -rf backend/db/models backend/db/feature_flags.py backend/db/local_guard.py
rm backend/services/audit_service.py backend/services/auth_pg_service.py
rm backend/routers/dev_pg.py
rm backend/scripts/migrate_accounts_to_pg.py
rm alembic/versions/f6e365d01243_*.py
python -m compileall backend -q
```

> 또는 단순히 신규/수정 모두 미커밋이므로 `git stash` / `git restore .` 등으로 일괄 되돌리기 가능. 다만 Opus 4.8 마이그레이션 변경도 함께 들어 있으므로 stash 범위 주의.

---

## 13. 매뉴얼 베타 테스트 준비 완료 여부 (Ready for User Manual Beta Testing?)

### 결론: **YES — 사용자 매뉴얼 베타 테스트로 진행 가능.**

근거:
1. ✅ 모든 자동 검증 항목 통과 (컴파일, 타입체크, 백엔드 기동, alembic, 임포트, 가드, 엔드포인트, 플래그 OFF/ON, server-mode 비-노출)
2. ✅ 기존 비즈니스 라우터·서비스·UI 0건 변경
3. ✅ 피처 플래그 OFF가 기본값 — 평소 사용 시 동작 변화 없음
4. ✅ Google Sheets·Drive 쓰기 0건 (스크립트의 Sheets 접근은 read-only `_get_ws_readonly()`만 사용)
5. ✅ 로컬-only 가드가 작동 — 운영 DB로 실수 연결 자동 차단
6. ✅ `HANWOORY_ENV=server` 시 dev 엔드포인트 비-노출 — 운영 배포 시 공격면 0
7. ✅ 컨테이너 + 합성 데이터 미정리 상태 → 사용자가 즉시 `§11.3 / §11.4` 시나리오 실행 가능

### 본 도구가 자동 실행하지 **않은** 것
- ❌ git commit / push / merge
- ❌ Render PG 생성·연결·환경변수 등록·배포
- ❌ 운영 Sheets / Drive 쓰기
- ❌ 운영 `Accounts` 시트 → 로컬 PG 임포트 (사용자가 §11.6에서 직접 결정)
- ❌ 컨테이너 자동 정리 (사용자가 §11.7에서 정리)

### 다음 단계 결정 사항 (사용자)
1. §11 체크리스트 수행
2. 이상 없으면 의도된 파일만 커밋 (예: `git add backend/db/ backend/services/audit_service.py backend/services/auth_pg_service.py backend/routers/dev_pg.py backend/scripts/migrate_accounts_to_pg.py alembic/versions/ backend/main.py LOCAL_POSTGRES_BETA_PLAN.md LOCAL_POSTGRES_BETA_REPORT.md`)
3. (옵션) Opus 4.8 마이그레이션(`backend/scripts/llm_*.py`, `analyze_manual_structure.py`)은 별도 커밋 권장 — 본 작업과 무관
4. push / Render PG 생성은 별도 결정

**END OF REPORT**
