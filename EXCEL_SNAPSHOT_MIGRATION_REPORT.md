# EXCEL_SNAPSHOT_MIGRATION_REPORT.md

## 1. 요약

운영 Google Sheets / Drive API 를 **단 한 번도** 호출하지 않고, 사용자가 `migration_input/` 폴더에 직접 내려놓은 Excel 스냅샷 6개만을 입력으로 받아 로컬 Docker PostgreSQL 에 임포트를 마쳤다. hanwoory + jpup 두 테넌트의 실제 데이터가 로컬 PG 에 저장되어 있고, 백엔드/프론트엔드를 모두 PG 플래그 ON 으로 기동해 평소 사용하던 화면들을 그대로 테스트할 수 있다.

- 신규 스크립트: `backend/scripts/import_excel_snapshot_to_pg_local.py` (~750줄)
- 신규 문서: `EXCEL_SNAPSHOT_MIGRATION_PLAN.md`, 본 보고서
- backend compile EXIT=0, frontend `tsc --noEmit` EXIT=0
- alembic upgrade head 정상 (27개 비즈니스 테이블 + alembic_version = 28)
- TOTAL inserted=3689 / updated=6 / skipped=3
- Google Sheets / Google Drive / Render 무접촉
- commit / push 0회

## 2. 발견된 파일

| 경로 | 크기 | role |
|---|---|---|
| `migration_input/신 고객 데이터.xlsx` | 709 KB | hanwoory_customers (live) |
| `migration_input/신 업무정리.xlsx` | 1.65 MB | hanwoory_work (live) |
| `migration_input/기준 고객 데이터.xlsx` | 111 KB | template_customers (metadata only) |
| `migration_input/기준 업무정리.xlsx` | 1.32 MB | template_work (metadata only) |
| `migration_input/tenants/고객 데이터 - jpup.xlsx` | 115 KB | jpup_customers (live) |
| `migration_input/tenants/업무정리 - jpup.xlsx` | 1.32 MB | jpup_work (live) |

## 3. 누락된 파일

없음. `admin_master.xlsx` 는 요구되지 않으며 존재하지 않음 (스크립트도 이를 요구하지 않음).

`tenants/` 폴더에는 jpup 파일만 존재. `asd` 등 다른 테넌트 파일 없음 → 처리 대상에서 제외.

## 4. 워크북 역할 매핑

| 파일 | role | tenant_id | live? |
|---|---|---|---|
| 신 고객 데이터.xlsx | `hanwoory_customers` | hanwoory | YES |
| 신 업무정리.xlsx | `hanwoory_work` | hanwoory | YES |
| 기준 고객 데이터.xlsx | `template_customers` | — | NO (메타데이터만) |
| 기준 업무정리.xlsx | `template_work` | — | NO (메타데이터만) |
| tenants/고객 데이터 - jpup.xlsx | `jpup_customers` | jpup | YES |
| tenants/업무정리 - jpup.xlsx | `jpup_work` | jpup | YES |

## 5. 올바른 워크북 용어 (사용자 확정)

- **신 고객 데이터.xlsx** = hanwoory/admin 의 **실 운영** 고객 워크북. 템플릿 아님.
- **신 업무정리.xlsx** = hanwoory/admin 의 **실 운영** 업무참고 워크북. 템플릿 아님.
- **기준 고객 데이터.xlsx** = 새 테넌트 생성 시 복사되는 **템플릿**. 실데이터 임포트 금지.
- **기준 업무정리.xlsx** = 새 테넌트 업무참고 **템플릿**. 실데이터 임포트 금지.
- **고객 데이터 - jpup.xlsx** = `tenant_id=jpup` 전용 고객 워크북.
- **업무정리 - jpup.xlsx** = `tenant_id=jpup` 전용 업무참고 워크북.

## 6. 워크북별 감지된 시트

### 신 고객 데이터.xlsx (21 시트)

`고객 데이터(기존)` *(legacy, 스킵)*, `게시판`, `게시판댓글`, `Accounts`, `고객 데이터`, `일정`, `예정업무`, `진행업무`, `장기메모`, `중기메모`, `단기메모`, `일일결산`, `잔액`, `완료업무`, `ROI_프리셋` *(범위 외)*, `고객서명`, `홈페이지게시물`, `행정사서명`, `서명임시저장`, `숙소제공자연결`, `신원보증인연결`

### 신 업무정리.xlsx (24 시트)

`공증`, `규제`, `혼인 사망`, `재발급, 비자`, `기타`, `C-3 단기일반`, `D-2 유학, D-4 일반연수`, `H-2 방문취업`, `F-4 재외동포`, `F-2 영주권 가족`, `F-5 영주권`, `F-6 결혼`, `E-7`, `E-9`, `귀화2`, `F-1 F4가족, 귀화대기`, `D-2`, `자동차`, `장차 할일`, `각종공인증_업체`, `각종공인증_대분류`, `각종공인증_중분류`, `각종공인증_소분류지역`, `각종공인증_가격조건`

### 고객 데이터 - jpup.xlsx (15 시트)

`고객 데이터`, `일정`, `예정업무`, `진행업무`, `장기메모`, `중기메모`, `단기메모`, `일일결산`, `잔액`, `완료업무`, `ROI_프리셋` *(범위 외)*, `고객서명`, `서명임시저장`, `숙소제공자연결`, `신원보증인연결`

### 업무정리 - jpup.xlsx (15 시트)

`공증`, `규제`, `혼인 사망`, `재발급, 비자`, `기타`, `C-3 단기일반`, `D-2 유학, D-4 일반연수`, `H-2 방문취업`, `F-4 재외동포`, `F-2 영주권 가족`, `F-5 영주권`, `F-6 결혼`, `E-7`, `E-9`, `귀화2`  
(각종공인증_* 탭 없음)

## 7. 템플릿 워크북 검사 결과

라이브 데이터로 import 하지 않음. 시트명·헤더·예시 행 수만 보고서에 기록.

### template_customers (14 시트)

| 시트 | rows | cols |
|---|---|---|
| 고객 데이터 | 1 (example row) | 27 |
| 일정 | 0 | 26 |
| 예정업무 | 0 | 26 |
| 진행업무 | 0 | 26 |
| 장기/중기/단기메모 | 0 | 0 |
| 일일결산 | 0 | 26 |
| 잔액 | 2 | 2 |
| 완료업무 | 0 | 26 |
| 고객서명 | 0 | 3 |
| 서명임시저장 | 0 | 5 |
| ROI_프리셋 | 3 | 5 |
| 숙소제공자연결 | 0 | 18 |

기대 탭 누락: `신원보증인연결` 이 템플릿에는 없음. 라이브 (hanwoory / jpup) 에는 존재 — 추후 템플릿 동기화 필요.

### template_work (15 시트)

`공증` 29행, `규제` 7행, `혼인 사망` 7행, `재발급, 비자` 22행, `기타` 22행, `C-3 단기일반` 10행, `D-2 유학, D-4 일반연수` 2행, `H-2 방문취업` 10행, `F-4 재외동포` 12행, `F-2 영주권 가족` 4행, `F-5 영주권` 9행, `F-6 결혼` 6행, `E-7` 4행, `E-9` 3행, `귀화2` 4행

기대 탭 누락: `F-1 F4가족, 귀화대기`, `D-2`, `자동차`, `장차 할일`, `각종공인증_*` 5개 — 모두 라이브에는 있고 템플릿에는 없음.

## 8. hanwoory 임포트 결과

| 도메인 | inserted | updated | skipped |
|---|---|---|---|
| customers (고객) | 1473 | 0 | 0 |
| events (일정) | 79 | 0 | 0 |
| memos (장/중/단기) | 3 | 0 | 0 |
| customer_signatures | 13 | 0 | 0 |
| active_tasks (진행업무) | 55 | 0 | 0 |
| planned_tasks (예정업무) | 5 | 0 | 0 |
| completed_tasks (완료업무) | 578 | 0 | 2 |
| daily_entries (일일결산) | 773 | 0 | 0 |
| daily_balances (잔액) | 1 | 0 | 0 |
| accommodation_providers | 13 | 0 | 0 |
| guarantor_connections | 8 | 0 | 0 |
| cert_vendors | 3 | 0 | 0 |
| cert_directions | 6 | 0 | 0 |
| cert_groups | 24 | 0 | 0 |
| cert_regions | 25 | 0 | 0 |
| cert_prices | 174 | 0 | 0 |
| work_reference_sheets | 19 | 0 | 0 |
| work_reference_rows | 195 | 0 | 0 |
| board_posts (admin 공유) | 4 | 0 | 0 |
| board_comments (admin 공유) | 2 | 0 | 0 |
| marketing_posts (admin 공유) | 56 | 0 | 0 |
| agent_signatures (admin 공유) | 3 | 0 | 0 |
| temp_signature_slots | 0 | 0 | 1 (빈 행) |
| tenants (Accounts) | 0 | 3 | 0 |
| users (Accounts) | 0 | 3 | 0 |

## 9. jpup 임포트 결과

| 도메인 | inserted | updated | skipped |
|---|---|---|---|
| customers (고객) | 5 | 0 | 0 |
| events (일정) | 0 | 0 | 0 |
| memos (장/중/단기) | 3 | 0 | 0 |
| customer_signatures | 0 | 0 | 0 |
| active_tasks (진행업무) | 0 | 0 | 0 |
| planned_tasks (예정업무) | 0 | 0 | 0 |
| completed_tasks (완료업무) | 0 | 0 | 0 |
| daily_entries (일일결산) | 0 | 0 | 0 |
| daily_balances (잔액) | 1 | 0 | 0 |
| accommodation_providers | 1 | 0 | 0 |
| guarantor_connections | 1 | 0 | 0 |
| cert_* | 0 | 0 | 0 (jpup_work 에 각종공인증 탭 없음) |
| work_reference_sheets | 15 | 0 | 0 |
| work_reference_rows | 151 | 0 | 0 |

## 10. 시트별 행 수 (소스 → 임포트)

| 워크북 | 시트 | 소스 rows | inserted |
|---|---|---|---|
| hanwoory_customers | 고객 데이터 | 1474 | 1473 |
| hanwoory_customers | 일정 | 80 | 79 |
| hanwoory_customers | 진행업무 | 56 | 55 |
| hanwoory_customers | 예정업무 | 6 | 5 |
| hanwoory_customers | 완료업무 | 579 | 578 (2 중복 task_id 결정적 ID 재생성) |
| hanwoory_customers | 일일결산 | 774 | 773 |
| hanwoory_customers | 숙소제공자연결 | 14 | 13 |
| hanwoory_customers | 신원보증인연결 | 9 | 8 |
| hanwoory_customers | 고객서명 | 14 | 13 |
| hanwoory_customers | Accounts | 4 | 3 tenants + 3 users |
| hanwoory_customers | 게시판 | 5 | 4 |
| hanwoory_customers | 게시판댓글 | 3 | 2 |
| hanwoory_customers | 홈페이지게시물 | 57 | 56 |
| hanwoory_customers | 행정사서명 | 4 | 3 |
| hanwoory_customers | 서명임시저장 | 2 | 0 (양쪽 모두 빈 행) |
| hanwoory_work | 각종공인증_* (5탭) | 562 | 232 (헤더 행 제외, 빈 행 제외) |
| hanwoory_work | 그 외 19탭 | 19000 | 195 (빈 행 제외) |
| jpup_customers | 고객 데이터 | 1295 | 5 (실데이터 행 외 모두 빈 행) |
| jpup_customers | 숙소제공자연결 | 2 | 1 |
| jpup_customers | 신원보증인연결 | 2 | 1 |
| jpup_work | 15탭 | 15000 | 151 |

소스 rows ≠ inserted 인 경우는 모두 빈 행 / 헤더 행 / 중복 행 필터링으로 설명됨.

## 11. inserted / updated / skipped 총계

```
TOTAL inserted = 3689
TOTAL updated  =    6   (Accounts re-import 시 3 tenants + 3 users update)
TOTAL skipped  =    3
```

## 12. 중복 처리 결과

- 모든 PG 쓰기는 (tenant_id, key) 단위 **upsert**
- 소스 행 자체에 (tenant_id, id) 중복이 있으면 첫 행만 채택, 나머지는 skip + 사유 로그
- 재실행 시 inserted=0 / updated=N 으로 멱등성 보장

## 13. 완료업무 중복 task_id 처리 결과

`완료업무` 시트에 동일 task_id 가 2건 있었음:

```
[completed[hanwoory]] duplicate task_id=274d262f-a1ed-496e-9cf8-385577a44173 row=31 → regenerated
[completed[hanwoory]] duplicate task_id=ed9b8401-8ce1-44fa-b62b-74829d01cc47 row=41 → regenerated
```

각 행은 `det-<sha1(tenant|completed|sheet|row|date|name|work|category|dup)[:12]>` 형태의 **결정적 ID** 로 재생성되어 정상 INSERT. PK 충돌 발생 없음. UniqueConstraint `uq_completed_task_per_tenant` 위배 0건.

## 14. 임포트 후 테이블 카운트

```
users                          7   (실 3 + 합성 3 + jpup_admin 1)
tenants                        6   (실 3 + 합성 3)
customers                   1478   (hanwoory 1473 + jpup 5)
active_tasks                  55
planned_tasks                  5
completed_tasks              578
daily_entries                773
daily_balances                 2
events                        79
memos                          6   (hanwoory 3 + jpup 3)
customer_signatures           13
agent_signatures               3
temp_signature_slots           0
accommodation_providers       14
guarantor_connections          9
board_posts                    4
board_comments                 2
marketing_posts               56
work_reference_sheets         34   (hanwoory 19 + jpup 15)
work_reference_rows          346   (hanwoory 195 + jpup 151)
cert_vendors                   3
cert_directions                6
cert_groups                   24
cert_regions                  25
cert_prices                  174
```

## 15. 실행 명령

```powershell
# 1. backend 컴파일
.venv\Scripts\python.exe -m compileall backend -q

# 2. frontend typecheck
cd frontend; npx tsc --noEmit; cd ..

# 3. Docker 확인
docker ps --filter "name=kid-postgres-local"

# 4. DATABASE_URL (PowerShell)
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"

# 5. alembic
.venv\Scripts\python.exe -m alembic upgrade head

# 6. dry-run
.venv\Scripts\python.exe backend\scripts\import_excel_snapshot_to_pg_local.py

# 7. 실 임포트 (clean reset 포함)
.venv\Scripts\python.exe backend\scripts\import_excel_snapshot_to_pg_local.py --execute --reset-local-pg

# 8. 도메인 한정 실행 예
.venv\Scripts\python.exe backend\scripts\import_excel_snapshot_to_pg_local.py --execute --only hanwoory
.venv\Scripts\python.exe backend\scripts\import_excel_snapshot_to_pg_local.py --execute --only jpup
.venv\Scripts\python.exe backend\scripts\import_excel_snapshot_to_pg_local.py --only templates  # 검사만
```

## 16. 안전 확인 (다시 한 번)

- ✅ Google Sheets API 호출 **0회** — `gspread` / `google.oauth2` import 자체 없음
- ✅ Google Drive API 호출 **0회** — `googleapiclient` import 자체 없음
- ✅ Render PostgreSQL 미접속 — `local_guard.assert_local_database_url()` 가 host 가 localhost / 127.0.0.1 / ::1 가 아니면 즉시 SystemExit
- ✅ Render 환경변수 / 배포 미접근
- ✅ 로컬 Docker PostgreSQL (`kid-postgres-local`, 호스트 포트 5433) 에만 쓰기
- ✅ git commit / push / merge 0회

## 17. 로컬 테스트용 로그인 계정

| login_id | tenant_id | is_admin | password | 비고 |
|---|---|---|---|---|
| **wkdwhfl** | hanwoory | ✅ | (실 운영 비밀번호) | Accounts 시트에서 그대로 임포트 — 사용자가 평소 쓰던 패스워드 |
| **jpup_admin** | jpup | ✅ | `beta_test_password_123` | 임포터가 자동 생성 (jpup 테넌트 admin 없었음) |
| jpup | jpup | ❌ | (실 운영 비밀번호) | 일반 사용자 |
| asd | asd | ❌ | (실 운영 비밀번호) | 일반 사용자 |
| test_admin | test_admin | ✅ | `beta_test_password_123` | 합성 데이터 (이전 라운드, tenant=test_admin) |
| test_user | test_user | ❌ | `beta_test_password_123` | 합성 |
| inactive_user | inactive_user | ❌ | — | 비활성 |

> hanwoory 의 빈 비밀번호 fallback (`test_admin` 을 hanwoory 테넌트로) 은 **생성하지 않음** — 실 admin `wkdwhfl` 이 이미 존재하여 "실 사용자 보존" 규칙에 따라 건너뜀. wkdwhfl 비밀번호를 모를 경우, 아래 SQL 로 임시 admin 추가:
>
> ```sql
> INSERT INTO users (login_id, tenant_id, password_hash, is_admin, is_active)
> VALUES ('hanwoory_local', 'hanwoory',
>   /* hash_password('beta_test_password_123') 결과 */ '<hash>',
>   true, true);
> ```
>
> 또는 Python 한 줄:
> ```powershell
> .venv\Scripts\python.exe -c "from backend.services.accounts_service import hash_password; print(hash_password('beta_test_password_123'))"
> ```

## 18. 백엔드 시작 명령

PowerShell 한 번에 복붙:

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

Swagger: `http://localhost:8002/docs`

## 19. 프론트엔드 시작 명령

새 PowerShell 창에서:

```powershell
cd frontend
$env:API_URL = "http://127.0.0.1:8002"
npm run dev
```

- 기본 포트 3000. 포트가 사용 중이면 Next.js 가 자동으로 3001 등으로 옮김 — 콘솔의 `Local: http://localhost:XXXX` 줄에 표시된 포트로 접속.
- Docker 컨테이너 `kid-frontend` 가 3000 을 점유 중이라면 그쪽이 운영 코드라 3001 등으로 자동 fallback 됨 (예전 사례와 동일).

## 20. 사용자가 브라우저에서 검증할 페이지

### hanwoory (wkdwhfl 로그인)

1. `/login` → wkdwhfl + 운영 비밀번호 → 대시보드 진입
2. `/dashboard` — 진행업무 카드 55건, 예정업무 5건 표시 확인
3. `/customers` — 고객 1473명 페이지네이션, 검색 기능
4. `/customers` 에서 고객 1건 열어 드로어 — 숙소제공자/신원보증인 탭 데이터 확인
5. `/tasks/completed` — 완료업무 578건
6. `/daily` — 일일결산 773건, 잔액 표시
7. `/events` (캘린더) — 일정 79건
8. `/board` — 공지/게시판 4건
9. `/reference` — 시트 탭 19개 (공증/규제/F-4 등)
10. `/admin/accounts` — Accounts 목록 (tenants 3건)
11. `/marketing` (또는 홈페이지 게시물 관리) — 56건
12. `/quick-poa` (원클릭 작성) — 위임장 PDF 생성 시도 (실제 PDF 생성은 Drive Mock 영향 받음)

### jpup (jpup_admin / beta_test_password_123)

1. `/login` → jpup_admin
2. `/customers` — 5명 표시
3. `/reference` — 시트 15개 (각종공인증 탭은 없음)
4. 메모 탭 — 모두 비어있음 (소스 sheet 가 비어있음)

## 21. 알려진 제약

1. **OCR / passport scan / 이미지 업로드** — 기능 자체는 정상이지만 Drive Mock 모드에서는 실제 파일이 Local manifest 만 남기고 클라우드로 가지 않음.
2. **마케팅 글 이미지 업로드** — 위와 동일 (Drive Mock 모드에서 image_url 이 sentinel).
3. **Reference 시트 셀 단위 편집** — `/api/reference/cell PATCH`, 행 추가/삭제 등 편집 엔드포인트는 **여전히 Sheets gspread** 를 사용. PG 모드에서 편집 시도 시 "테넌트의 customer_sheet_key/work_sheet_key 없음" 으로 실패. 보기 (`/api/reference/sheets`, `/api/reference/data`) 만 PG.
4. **PDF quick_doc / 원클릭 작성** — 다단계 fetch (서명/숙소/보증 모두 필요) — 데이터 자체는 PG 에 있으나 일부 라우터 분기 미점검. PDF 생성 시 hanwoory 데이터로 1건 시연을 권장.
5. **회원가입 / 워크스페이스 신규 생성** — Drive Mock 으로 sentinel ID 반환만 됨. 실제 Sheets 워크북은 생성되지 않으므로 신규 테넌트는 Excel snapshot 으로만 추가 가능.
6. **민감 필드 평문 저장** — `passport_no`, `reg_back` 은 로컬 베타 한정으로 평문. 외부 배포 시 암호화 필수.
7. **하나의 hanwoory 비밀번호 fallback** — `wkdwhfl` 가 실 운영 password_hash 그대로 import 됨. 비밀번호를 모를 경우 §17 의 SQL/Python 한 줄로 임시 admin 추가 필요.
8. **고객 데이터(기존) legacy 시트** — `신 고객 데이터.xlsx` 의 `고객 데이터(기존)` 1225행은 의도적으로 스킵. 활성 `고객 데이터` (1474행) 만 사용.

## 22. 사용자 PASS 후 권장 commit 파일 목록

```powershell
git add `
  backend/scripts/import_excel_snapshot_to_pg_local.py `
  EXCEL_SNAPSHOT_MIGRATION_PLAN.md `
  EXCEL_SNAPSHOT_MIGRATION_REPORT.md
```

기존 PG 마이그레이션 라운드의 산출물 (모델, 라우터 분기, alembic migrations, drive mock 등) 은 이미 별도 커밋 대상. 본 라운드는 **Excel 스냅샷 임포터 + 계획서 + 보고서 3개 파일만** 신규.

## 23. 커밋하지 말아야 할 파일

```
migration_input/                        # 사용자 사적 엑셀 데이터
migration_input/tenants/
.local_pg_beta_drive/                   # Drive Mock manifest
.venv/
__pycache__/
*.pyc
.env                                    # 로컬 비밀
```

`.gitignore` 에 `migration_input/` 항목 이미 포함되어 있는지 확인 권장. 만약 없으면 다음 한 줄 추가:

```
migration_input/
```

---

**정지 조건 충족.** commit / push / deploy 미수행. 사용자 브라우저 검증 대기.
