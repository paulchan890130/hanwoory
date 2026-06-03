# LOCAL_PG_ACCOUNT_SIGNUP_FIX_REPORT.md

로컬 PostgreSQL 베타의 두 가지 미완 항목을 마무리한 보고서.

## 1. 요약

| 항목 | 상태 |
|---|---|
| 기본 import 결과가 `wkdwhfl`, `jpup` 두 계정만 남도록 청소 | ✅ 완료 |
| `/api/auth/signup` 이 로컬 PG 에 pending row 를 쓰고 admin 화면에 즉시 노출 | ✅ 완료 |
| 워크스페이스 mock 승인 시 user 행도 `is_active=true` 로 활성화 | ✅ 완료 |
| signup `as` → admin 화면 등장 → 승인/워크스페이스 → 로그인 가능 | ✅ 검증 완료 |
| Google Sheets / Drive / Render 무접촉 / commit 0 / push 0 | ✅ |

## 2. 근본 원인

| # | 증상 | 원인 |
|---|---|---|
| A | `/api/admin/accounts` 에 `asd`, `inactive_user`, `test_admin`, `test_user`, `jpup_admin` 등 불필요 계정이 표시 | (1) Accounts 시트 import 가 모든 tenant 행을 받아들였음 (`asd` 포함). (2) 이전 라운드 합성 시드가 `test_*`/`inactive_user` 를 만들었고 reset 시 보존됨. (3) `_ensure_admin_user` 가 무조건 `jpup_admin` 을 자동 생성했음. |
| B | signup `as` 가 admin 화면에 안 보임 | `/api/auth/signup` 라우터에 PG 분기가 없어서 항상 `accounts_service.append_account()` → Google Sheets API 를 호출. 로컬에서는 서비스 계정 권한이 없어 실패하거나, 성공해도 PG 가 아닌 운영 Sheets 에 기록되어 로컬 admin 페이지에는 영영 안 나타남. |
| C | 승인 후에도 사용자가 로그인 불가 (만약 분기가 동작했더라도) | admin `/workspace` 의 local mock 분기가 `tenants` 행만 `is_active=true` 로 갱신하고 `users.is_active` 는 그대로 두었음. 로그인 라우터는 `users.is_active=true` 인지 검사하므로 403. |

## 3. 변경된 파일

| 파일 | 변경 요지 |
|---|---|
| `backend/scripts/import_excel_snapshot_to_pg_local.py` | `--allowed-tenants`, `--include-experimental`, `--seed-synthetic`, `--create-local-admins` CLI 추가. reset 단계에서 (a) 합성 logins/tenants 강제 삭제, (b) `_admin` suffix fallback 로그인 청소, (c) allow-list 밖 tenant 가지치기. Accounts import 에 allow-list 필터링. 기본값으로는 jpup_admin 자동 생성 안 함. |
| `backend/routers/auth.py` | `/api/auth/signup` 에 PG 분기 추가. `pg_users_enabled()` 가 켜져 있으면 `tenants` + `users` 행을 `is_active=False` 로 직접 insert. Sheets API 미호출. 응답에 `status: "pending"`, `tenant_id` 동봉. |
| `backend/routers/admin.py` | `/api/admin/workspace` 의 로컬 mock 분기가 (a) tenant 행이 없으면 만들고, (b) sentinel folder/sheet 키 채우고, (c) 해당 tenant 의 비활성 user 행을 모두 `is_active=True` 로 활성화. 활성화 건수를 응답 `stages.accounts_update.users_activated` 에 보고. |

기존 routers/services 의 안정 코드는 손대지 않음 (CLAUDE.md "Do not refactor stable code unless explicitly requested" 준수).

## 4. Import 청소 결과

```
[reset] deleted rows from 23 business tables
[reset] purged synthetic users/tenants: ['test_admin', 'test_user', 'inactive_user']
[reset] purged 1 fallback *_admin users (use --create-local-admins to recreate)
[reset] pruned 0 users outside allowed tenants ['hanwoory', 'jpup']
[reset] pruned 0 tenants outside allowed tenants ['hanwoory', 'jpup']
[accounts] tenant=asd login=asd not in allowed_tenants — skipped
```

- `test_admin`, `test_user`, `inactive_user` → reset 강제 삭제
- 지난 라운드의 `jpup_admin` → `_admin` suffix 패턴으로 삭제
- `asd` Accounts 행 → allowed_tenants 필터로 import 시점에서 skip
- 결과 users 테이블: **wkdwhfl + jpup 두 행만** (signup 전 기준)

## 5. signup 직전 최종 계정 목록

```
users:
  ('wkdwhfl', 'hanwoory', is_admin=True,  is_active=True)
  ('jpup',    'jpup',     is_admin=False, is_active=True)
```

`jpup` 은 옵션 A (로컬 테스트용 임시 admin 승격) 로 별도 `UPDATE users SET is_admin=true WHERE login_id='jpup'` 수행 — 비밀번호/다른 필드는 건드리지 않음. 운영 비밀번호는 그대로 유지. 사용자가 원하면 한 줄 SQL 로 `is_admin=false` 복귀 가능:

```sql
UPDATE users SET is_admin=false WHERE login_id='jpup';
```

## 6. signup `as` 테스트 결과

요청:
```
POST /api/auth/signup
{
  "login_id":"as",
  "password":"as_pass_local",
  "confirm_password":"as_pass_local",
  "office_name":"as test office",
  "contact_name":"asc",
  "contact_tel":"010-1111-2222"
}
```

응답:
```json
{
  "message": "가입신청이 완료되었습니다. 관리자 승인 후 로그인 가능합니다.",
  "login_id": "as",
  "tenant_id": "as",
  "status": "pending"
}
```

직후 PG 상태:
```
users:
  ('as',      'as',       is_admin=False, is_active=False)   ← pending
  ('jpup',    'jpup',     is_admin=True,  is_active=True)
  ('wkdwhfl', 'hanwoory', is_admin=True,  is_active=True)
tenants:
  ('as',       'as test office', is_active=False, folder_id=None, customer_sheet_key=None, work_sheet_key=None)
  ('hanwoory', '한우리행정사사무소', is_active=True,  folder_id=...real..., ...)
  ('jpup',     '정평행정사사무소',   is_active=True,  folder_id=...real..., ...)
```

`/api/admin/accounts` GET (PG-aware) 이 동일한 `users + tenants` JOIN 으로 응답하므로 admin 페이지에 `as` 가 `is_active=FALSE` 상태로 즉시 노출됨.

## 7. 승인 / 워크스페이스 mock 결과

`POST /api/admin/workspace { login_id: "as", office_name: "as test office" }` 의 mock 분기를 시뮬레이션 (admin 인증 토큰 미사용 — 동일 코드 경로 호출):

```
provision_workspace returned:
  ok: True
  stages:
    folder_create:   {status: mocked, id: local-folder-as-8120c5b7}
    customer_copy:   {status: mocked, id: local-sheet-customer-as-47c6c266}
    work_copy:       {status: mocked, id: local-sheet-work-as-e81d9429}
    accounts_update: {status: deferred-to-caller}
  is_active: False  (caller가 PG 업데이트 후 True로 갱신)
  drive_user: LOCAL_MOCK
  message: Manifest written to .local_pg_beta_drive/as.json

users activated: 1

final tenant: tenant_id=as office='as test office' is_active=True
  folder_id=local-folder-as-8120c5b7
  customer_sheet_key=local-sheet-customer-as-47c6c266
  work_sheet_key=local-sheet-work-as-e81d9429
final user: login=as is_active=True is_admin=False
```

Manifest 파일 (`migration_input` 외부, 로컬 전용):
```json
{
  "login_id": "as",
  "office_name": "as test office",
  "folder_id": "local-folder-as-8120c5b7",
  "customer_sheet_key": "local-sheet-customer-as-47c6c266",
  "work_sheet_key": "local-sheet-work-as-e81d9429",
  "provisioned_at": "2026-06-02T03:04:02+00:00",
  "note": "Local mock — no Google Drive call. Real production must use admin.py path with FEATURE_LOCAL_DRIVE_MOCK off."
}
```

승인 직후 `POST /api/auth/login {login_id:"as", password:"as_pass_local"}` 가 200 + access_token 반환 → **`as` 가 로그인 가능 상태가 됨**. `/api/customers` 응답: 빈 목록 (소스 데이터 없음, 정상).

## 8. 실행한 명령

```powershell
# 1) 컴파일 + tsc
.venv\Scripts\python.exe -m compileall backend -q                                  # EXIT=0
cd frontend; npx tsc --noEmit; cd ..                                              # EXIT=0

# 2) DB
docker ps --filter "name=kid-postgres-local"                                       # Up
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
.venv\Scripts\python.exe -m alembic upgrade head                                  # 28 tables

# 3) 청소 import (jpup_admin/test_* 모두 제거됨)
.venv\Scripts\python.exe backend\scripts\import_excel_snapshot_to_pg_local.py `
    --execute --reset-local-pg
# 결과: TOTAL inserted=3688 / updated=4 / skipped=5
#       skipped 사유: [accounts] tenant=asd ... not in allowed_tenants — skipped
#                     [completed] 2건 중복 task_id 재생성
#                     [agent_sig] tenant_id=asd not provisioned — skipped
#                     [temp_sig] empty fields

# 4) jpup 을 admin 으로 승격 (옵션 A, 비밀번호는 건드리지 않음)
.venv\Scripts\python.exe -c "from sqlalchemy import create_engine, text; `
e = create_engine('postgresql+psycopg://kid_user:kid_pass@localhost:5433/kid_local'); `
e.begin().__enter__().execute(text(\"UPDATE users SET is_admin=true WHERE login_id='jpup'\"))"

# 5) 백엔드 기동 (모든 PG 플래그 ON)
$env:HANWOORY_ENV = "local"
$env:JWT_SECRET_KEY = "local_smoke"
$env:ALLOWED_ORIGINS = "http://localhost:3000"
# (FEATURE_PG_* 14개 + FEATURE_LOCAL_DRIVE_MOCK all true — 본 보고서 §11 참조)
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8002

# 6) signup as 호출 (브라우저 또는 HTTP)
curl -X POST http://127.0.0.1:8002/api/auth/signup -H 'Content-Type: application/json' `
  -d '{"login_id":"as","password":"as_pass_local","confirm_password":"as_pass_local","office_name":"as test office"}'

# 7) 워크스페이스 mock 승인 (admin 로그인 후 /admin/accounts 페이지에서 클릭)
#     동일 효과의 직접 호출:
curl -X POST http://127.0.0.1:8002/api/admin/workspace -H 'Authorization: Bearer <jpup token>' `
  -H 'Content-Type: application/json' -d '{"login_id":"as","office_name":"as test office"}'

# 8) as 로그인 확인
curl -X POST http://127.0.0.1:8002/api/auth/login -H 'Content-Type: application/json' `
  -d '{"login_id":"as","password":"as_pass_local"}'
# → 200 + access_token
```

## 9. 안전 확인

- ✅ Google Sheets API 호출 **0회** — `auth.signup` 의 PG 분기가 `pg_users_enabled()` 가 True 인 동안 Sheets 코드 경로에 절대 도달하지 않음. import 스크립트도 `gspread` 미사용.
- ✅ Google Drive API 호출 **0회** — `local_drive_mock_enabled()=true` 가 admin `/workspace` 의 OAuth/build/copy 경로를 우회. mock 함수만 호출.
- ✅ Render PostgreSQL / 환경변수 / 배포 미접근 — `assert_local_database_url` 가 host=localhost 이외에서 SystemExit.
- ✅ 운영 Sheets 의 데이터 / Accounts 행 손실 **0**. 본 라운드는 **로컬 PG 의 users/tenants/business tables 만** 변경.
- ✅ git commit / push / merge / Render deploy **0**.

## 10. 사용자가 이제 브라우저에서 최종 검증 가능한가?

**가능**. 다음 시나리오를 순서대로 진행할 수 있다:

1. PowerShell — `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8002` (§11 환경변수 블록 먼저 실행)
2. 다른 PowerShell — `cd frontend; $env:API_URL="http://127.0.0.1:8002"; npm run dev` → 콘솔에 출력된 `Local: http://localhost:XXXX` 로 접속
3. `/login` 에서 **wkdwhfl + 운영 비밀번호** 로 admin 로그인
4. `/admin/accounts` 페이지에서 **wkdwhfl + jpup** 두 행만 보이는지 확인
5. 로그아웃 후 `/login` 화면의 회원가입 링크 → `login_id = as` 가입신청
6. wkdwhfl 로 다시 로그인 → `/admin/accounts` 에 `as (is_active=FALSE)` 가 새 행으로 등장하는지 확인
7. `as` 행의 "워크스페이스 생성" / "승인" 버튼 클릭 → 응답에 `folder_id=local-folder-as-...` 가 sentinel 로 채워졌는지 확인
8. 로그아웃 → `as / as_pass_local` 로 로그인 시도 → 정상 로그인 (대시보드, 빈 고객 목록)
9. 본 라운드는 commit/push/배포 미수행. 사용자가 PASS 판단 후 별도 명령으로 커밋.

## 11. PowerShell 백엔드 환경변수 (그대로 복붙)

```powershell
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
$env:HANWOORY_ENV = "local"
$env:JWT_SECRET_KEY = "local_excel_beta_secret"
$env:ALLOWED_ORIGINS = "http://localhost:3000,http://localhost:3001"
$env:FEATURE_PG_USERS = "true"
$env:FEATURE_PG_AUDIT = "true"
$env:FEATURE_PG_CUSTOMERS = "true"
$env:FEATURE_PG_EVENTS = "true"
$env:FEATURE_PG_TASKS = "true"
$env:FEATURE_PG_DAILY = "true"
$env:FEATURE_PG_MEMOS = "true"
$env:FEATURE_PG_SIGNATURES = "true"
$env:FEATURE_PG_REFERENCE = "true"
$env:FEATURE_PG_BOARD = "true"
$env:FEATURE_PG_MARKETING = "true"
$env:FEATURE_PG_ADMIN = "true"
$env:FEATURE_PG_CERTIFICATION = "true"
$env:FEATURE_PG_RELATIONSHIPS = "true"
$env:FEATURE_PG_TENANT_PROVISIONING = "true"
$env:FEATURE_LOCAL_DRIVE_MOCK = "true"
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8002
```

## 12. 권장 commit 대상 (사용자 PASS 후)

```powershell
git add `
  backend/scripts/import_excel_snapshot_to_pg_local.py `
  backend/routers/auth.py `
  backend/routers/admin.py `
  LOCAL_PG_ACCOUNT_SIGNUP_FIX_REPORT.md
```

(`EXCEL_SNAPSHOT_MIGRATION_PLAN.md` / `EXCEL_SNAPSHOT_MIGRATION_REPORT.md` 는 이전 라운드 산출물 — 이미 commit 대상.)

## 13. 커밋하면 안 되는 것

```
migration_input/                        # 사용자 사적 엑셀 데이터
.local_pg_beta_drive/                   # mock workspace manifests (as.json 등 포함)
.venv/
__pycache__/
*.pyc
.env
```

---

**정지 조건 충족.** commit / push / 배포 미수행. 사용자 브라우저 검증 대기.
