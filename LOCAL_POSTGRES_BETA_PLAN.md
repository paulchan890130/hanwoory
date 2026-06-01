# 로컬 PostgreSQL 베타 구현 계획 (LOCAL_POSTGRES_BETA_PLAN.md)

> **작성일:** 2026-06-01
> **브랜치:** `feat/postgres-foundation`
> **목적:** 운영(Render / Google Sheets / Google Drive)을 건드리지 않고 **로컬 Docker PostgreSQL** 한 곳에서만 PG 마이그레이션 코드를 베타 테스트할 수 있도록 구현.
> **선행 상태:** Phase 1 토대(`backend/db/`, `/health/db`, `alembic/`) 머지 완료, 로컬 검증 통과(`PHASE1_LOCAL_DB_VERIFICATION_REPORT.md`).

---

## 1. 구현 범위 (Implementation Scope)

| 영역 | 포함 | 비고 |
|---|---|---|
| SQLAlchemy 모델 | `tenants`, `users`(account_users), `audit_logs` | 3개만 |
| `customers` 스켈레톤 | **포함 안 함** | 본 단계에서는 위험. 별도 단계. |
| Alembic 마이그레이션 | `0001` 단일 리비전 (위 3 테이블) | autogenerate로 생성 |
| 피처 플래그 | `FEATURE_PG_USERS`, `FEATURE_PG_AUDIT`, `FEATURE_PG_CUSTOMERS` | **전부 기본값 OFF** |
| 감사 로그 서비스 | `backend/services/audit_service.py` | `FEATURE_PG_AUDIT` 가드, 실패 시 silent |
| PG 로그인 헬퍼 | `backend/services/auth_pg_service.py` | 기존 `auth.py` 변경 없음 |
| 로컬 베타용 dev 라우터 | `backend/routers/dev_pg.py` (prefix `/api/dev/pg`) | **`HANWOORY_ENV=local`일 때만 등록** |
| Accounts → PG 임포트 스크립트 | `backend/scripts/migrate_accounts_to_pg.py` | 로컬 DB 가드, dry-run 기본, `--seed-synthetic` 옵션 |
| 로컬 전용 가드 | `backend/db/local_guard.py` | `DATABASE_URL` 호스트가 localhost가 아니면 즉시 종료 |

---

## 2. 변경 / 신규 파일 (Files to Change)

### 2.1 신규 파일

| 파일 | 역할 |
|---|---|
| `backend/db/models/__init__.py` | 패키지 진입점. 3개 모델을 명시적 import → `Base.metadata` 등록 |
| `backend/db/models/tenant.py` | `Tenant` ORM 모델 |
| `backend/db/models/user.py` | `AccountUser` ORM 모델 (테이블명 `users`) |
| `backend/db/models/audit.py` | `AuditLog` ORM 모델 |
| `backend/db/feature_flags.py` | `pg_users_enabled()` / `pg_audit_enabled()` / `pg_customers_enabled()` |
| `backend/db/local_guard.py` | `assert_local_database_url(url)` — localhost 외 거부 |
| `backend/services/audit_service.py` | `log_event(...)` — best-effort, 실패 silent |
| `backend/services/auth_pg_service.py` | `find_user_pg(login_id)`, `verify_login_pg(login_id, password)` |
| `backend/routers/dev_pg.py` | `/api/dev/pg/{flags,users/count,login-test,...}` |
| `backend/scripts/migrate_accounts_to_pg.py` | Accounts → 로컬 PG 임포트 (dry-run 기본) |
| `alembic/versions/0001_*.py` | autogenerate 산출물 (tenants/users/audit_logs DDL) |

### 2.2 수정 파일

| 파일 | 변경 |
|---|---|
| `backend/db/__init__.py` | `from backend.db import models  # noqa: F401` 한 줄 추가 — `Base.metadata` 완성 |
| `backend/main.py` | `from backend.routers import dev_pg` + `RUN_ENV == "local"` 분기 등록 (조건부) |

### 2.3 절대 변경 안 함

- `backend/services/tenant_service.py` (Google Sheets 추상화)
- `backend/services/accounts_service.py` (해시/검증/Sheets 쓰기 — **읽기만 import로 재사용**)
- `backend/routers/auth.py` (현 로그인 흐름 완전 보존)
- `backend/routers/customers.py`, `tasks.py`, `daily.py`, `events.py`, ... (모든 비즈니스 라우터)
- `frontend/` 전체 (UI 변경 없음)
- `.env`, `secrets/`, `config.py` (시크릿/설정 무변경)
- `alembic/env.py`, `alembic.ini` (Phase 1에서 이미 완성)

---

## 3. 로컬 전용 DB 셋업 (Local-Only Setup)

```sh
# 1) Docker PG 16 컨테이너 (호스트 5433 ↔ 컨테이너 5432)
docker run --name kid-postgres-local \
  -e POSTGRES_DB=kid_local \
  -e POSTGRES_USER=kid_user \
  -e POSTGRES_PASSWORD=kid_pass \
  -p 5433:5432 \
  -d postgres:16

# 2) 환경변수 (현재 PowerShell 세션 한정)
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
```

> **가드:** `migrate_accounts_to_pg.py` 와 `alembic` 실행 시 `local_guard.assert_local_database_url()` 가 호출되어 호스트가 `localhost`/`127.0.0.1`/`::1` 가 아니면 즉시 `SystemExit`. 운영 DB 보호.

---

## 4. 마이그레이션 명령 순서 (Migration Commands)

```sh
# 0) Docker PG가 ready 상태인지 확인
docker exec kid-postgres-local pg_isready -U kid_user -d kid_local

# 1) (필요 시) alembic 리비전 자동생성 — 이미 0001을 생성해두면 이 단계 생략 가능
.venv\Scripts\alembic.exe revision --autogenerate -m "0001 tenants users audit_logs"

# 2) 마이그레이션 적용 (테이블 생성)
.venv\Scripts\alembic.exe upgrade head

# 3) (옵션) Accounts 시트 dry-run — 무엇이 import될지 출력만
.venv\Scripts\python.exe backend\scripts\migrate_accounts_to_pg.py

# 4) (옵션) 합성 데이터로 실제 insert — Sheets 미접근, 코드 경로 검증 전용
.venv\Scripts\python.exe backend\scripts\migrate_accounts_to_pg.py --seed-synthetic --execute

# 5) (옵션) 실제 Accounts 시트 → 로컬 PG (read-only로 Sheets 읽기)
.venv\Scripts\python.exe backend\scripts\migrate_accounts_to_pg.py --execute

# 6) 롤백 — 모든 테이블 제거
.venv\Scripts\alembic.exe downgrade base
```

> **시트 읽기 정책:** 본 스크립트의 시트 접근은 `backend/services/accounts_service.py:_get_ws_readonly()` 만 사용하며 **쓰기 호출 없음**. 운영 Sheets는 수정되지 않습니다. 다만 운영 데이터의 사본을 로컬에 만드는 것이므로 사전 인지 후 실행.

---

## 5. 피처 플래그 전략 (Feature Flag Strategy)

| 변수 | 기본값 | 켜졌을 때 효과 | 꺼졌을 때 효과 |
|---|---|---|---|
| `FEATURE_PG_USERS` | `false` | `/api/dev/pg/login-test`, `/api/dev/pg/users/count` 가 PG를 조회 | 위 엔드포인트가 503 응답 |
| `FEATURE_PG_AUDIT` | `false` | `audit_service.log_event()` 가 `audit_logs` 테이블에 insert | `log_event()` 가 no-op |
| `FEATURE_PG_CUSTOMERS` | `false` | (현재 사용처 없음 — Phase 4 대비) | (해당 없음) |

**핵심 보장:** 모든 플래그가 off일 때 운영 동작은 Phase 1 머지 직후와 동일하며, Google Sheets 흐름만 사용됩니다.

**플래그 토글 방법 (로컬 PowerShell):**
```sh
$env:FEATURE_PG_USERS = "true"
$env:FEATURE_PG_AUDIT = "true"
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
```

---

## 6. 로컬 베타 테스트 체크리스트 (User-Facing)

사용자가 직접 수행:

### 6.1 사전 점검
- [ ] `git status` — 의도된 파일만 변경되었는지 확인
- [ ] `python -m compileall backend -q` — EXIT=0
- [ ] `cd frontend && npx tsc --noEmit` — EXIT=0
- [ ] Docker Desktop 데몬 실행 중

### 6.2 인프라
- [ ] `docker run ... postgres:16` 으로 로컬 PG 시작
- [ ] `pg_isready` 통과 확인
- [ ] `$env:DATABASE_URL` 설정 (localhost:5433)

### 6.3 마이그레이션
- [ ] `alembic upgrade head` 성공 → 테이블 3개 생성
- [ ] `\dt` 또는 `SELECT tablename FROM pg_tables` 로 테이블 확인

### 6.4 플래그 OFF 검증 (기본 운영 흐름)
- [ ] `FEATURE_PG_USERS=` 비활성, uvicorn 기동
- [ ] `GET /health` → `{"status":"ok"}`
- [ ] `GET /health/db` → `db:"ok"`
- [ ] **기존 `/api/auth/login` 으로 정상 로그인** (Google Sheets 경로)
- [ ] 프론트엔드(`npm run dev`)에서 로그인 → 대시보드 진입 → 평소 동작과 동일

### 6.5 플래그 ON 검증 (PG 경로)
- [ ] 스크립트로 합성 데이터 임포트: `migrate_accounts_to_pg.py --seed-synthetic --execute`
- [ ] `FEATURE_PG_USERS=true` 로 uvicorn 재기동
- [ ] `GET /api/dev/pg/flags` → 모든 플래그 상태 확인
- [ ] `GET /api/dev/pg/users/count` → 합성 행 개수
- [ ] `POST /api/dev/pg/login-test` body `{"login_id":"test_admin","password":"beta_test_password_123"}` → `ok:true`
- [ ] 잘못된 비밀번호 → `ok:false`
- [ ] `FEATURE_PG_AUDIT=true` 로 다시 기동 → `log_event()` 호출 시 `audit_logs` 행 증가

### 6.6 격리 검증
- [ ] Google Sheets `Accounts` 시트의 행 수/내용 **변경 없음**
- [ ] Google Drive 어떤 파일도 **수정/추가/삭제 없음**
- [ ] `DATABASE_URL` 을 운영 URL로 바꾸는 시도 시 `migrate_accounts_to_pg.py` 가 즉시 `SystemExit` (가드 동작)

### 6.7 정리
- [ ] `docker stop kid-postgres-local && docker rm kid-postgres-local`
- [ ] `$env:DATABASE_URL = $null` (또는 새 PowerShell 세션)
- [ ] `$env:FEATURE_PG_USERS = $null` 등 플래그 해제

---

## 7. 롤백 방법 (Rollback)

### 7.1 즉시 롤백 (가장 안전)
환경변수만 제거:
```sh
$env:FEATURE_PG_USERS = $null
$env:FEATURE_PG_AUDIT = $null
$env:DATABASE_URL = $null
```
→ 다음 uvicorn 기동 시 Phase 1 머지 직후 동작으로 복귀.

### 7.2 DB 수준 롤백
```sh
.venv\Scripts\alembic.exe downgrade base   # 모든 테이블 drop
# 또는
docker rm -f kid-postgres-local            # 컨테이너+익명볼륨 삭제
```

### 7.3 코드 수준 롤백 (필요 시)
```sh
git restore backend/db/__init__.py backend/main.py
rm -rf backend/db/models backend/db/feature_flags.py backend/db/local_guard.py
rm -rf backend/services/audit_service.py backend/services/auth_pg_service.py
rm -rf backend/routers/dev_pg.py
rm -rf backend/scripts/migrate_accounts_to_pg.py
rm -rf alembic/versions/0001_*.py
python -m compileall backend -q
```
> 본 도구는 위 명령을 자동 실행하지 않습니다. 사용자가 직접 결정.

---

## 8. 절대 금지 (Hard Rules — 본 단계에서)

* ❌ 커밋 / 푸시 / 머지 / Render 배포
* ❌ 운영 PostgreSQL 접속 — 로컬 가드가 자동 차단
* ❌ Google Sheets / Drive 쓰기
* ❌ 기존 Sheets 로직 제거 / 라우터 수정 (auth.py 등)
* ❌ UI 변경 (frontend 무수정)
* ❌ `.env` / `secrets/` / `config.py` 수정
* ❌ 파괴적 Git 명령 (`reset --hard`, `clean -f`, `push --force`)
* ❌ `customers` 데이터 마이그레이션 (별도 Phase)

---

## 9. 다음 보고서

본 구현 완료 후 `LOCAL_POSTGRES_BETA_REPORT.md` 작성. 보고서에는:
1. 변경된 파일
2. 실행 명령
3. 로컬에 생성된 테이블
4. 마이그레이션 결과
5. 테스트한 플래그
6. Google Sheets 동작 무변경 확인
7. compile/typecheck 결과
8. 백엔드/프론트 기동 결과
9. 사용자 매뉴얼 베타 테스트 체크리스트
10. 롤백 방법
11. 매뉴얼 베타 테스트 준비 완료 여부

**END OF PLAN**
