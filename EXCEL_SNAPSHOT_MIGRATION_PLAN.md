# EXCEL_SNAPSHOT_MIGRATION_PLAN.md

로컬 PostgreSQL 베타용 — Google Sheets API를 호출하지 않고 사용자가 미리 내려받아 `migration_input/`에 둔 Excel(.xlsx) 스냅샷만 사용해 데이터 임포트.

## 1. 안전 계약

- DATABASE_URL host 가 `localhost / 127.0.0.1 / ::1` 이 아니면 즉시 SystemExit (`backend/db/local_guard.py` 재사용)
- 기본 모드는 dry-run. `--execute` 가 있어야만 PG 쓰기
- Google Sheets API / Google Drive API 호출 코드 자체를 import하지 않음
- Render PG / 환경변수 / 배포 전혀 건드리지 않음
- git commit / push / merge 자동 수행 0건

## 2. 입력 폴더

```
C:\Users\윤찬\K.ID soft\migration_input\
├─ 신 고객 데이터.xlsx              hanwoory live customers
├─ 신 업무정리.xlsx                 hanwoory live work-reference
├─ 기준 고객 데이터.xlsx            TEMPLATE customers (no live import)
├─ 기준 업무정리.xlsx               TEMPLATE work-reference (no live import)
└─ tenants/
   ├─ 고객 데이터 - jpup.xlsx       jpup live customers
   └─ 업무정리 - jpup.xlsx          jpup live work-reference
```

`tenants/` 하위 파일명에서 `- {tenant_id}` 토큰을 추출해 tenant_id로 사용. 현재 jpup 1개만 처리. `asd` 등 다른 테넌트 파일이 존재할 때만 추가 처리.

`admin_master.xlsx` 는 요구되지 않음. 없어도 실패 금지.

## 3. 워크북 역할 매핑

| 파일명 | role | tenant_id | live? |
|---|---|---|---|
| 신 고객 데이터.xlsx | hanwoory_customers | hanwoory | YES |
| 신 업무정리.xlsx | hanwoory_work | hanwoory | YES |
| 기준 고객 데이터.xlsx | template_customers | (none) | NO — 메타데이터만 |
| 기준 업무정리.xlsx | template_work | (none) | NO — 메타데이터만 |
| tenants/고객 데이터 - jpup.xlsx | jpup_customers | jpup | YES |
| tenants/업무정리 - jpup.xlsx | jpup_work | jpup | YES |

## 4. 시트 → PG 테이블 매핑 (customers 워크북)

| 시트명 | PG 테이블 | 핵심 컬럼 매핑 |
|---|---|---|
| `고객 데이터` | `customers` | 고객ID→customer_id, 한글→korean_name, 국적→nationality, 성→surname_en, 명→given_en, 연/락/처→phone1/2/3, 등록증/번호→reg_front/reg_back, 발급일/V/만기일→card_issue_date/v_status/card_expiry_date, 여권/발급/만기→passport_no/passport_issue_date/passport_expiry_date, 주소→address, 위임내역→delegation_history, 비고+기타→memo |
| `일정` | `events` | date_str, event_text |
| `예정업무` | `planned_tasks` | id→task_id |
| `진행업무` | `active_tasks` | id→task_id + 14개 컬럼 |
| `완료업무` | `completed_tasks` | id→task_id + 10개 컬럼 (중복 헤더 `complete_date` 제거) |
| `일일결산` | `daily_entries` | id→entry_id + 11개 컬럼 |
| `잔액` | `daily_balances` | key='cash'/'profit' value=정수 |
| `장기메모` / `중기메모` / `단기메모` | `memos` | 시트의 A1 셀 1개를 long/mid/short content로 |
| `고객서명` | `customer_signatures` | 고객ID, 서명데이터, 등록일시 |
| `숙소제공자연결` | `accommodation_providers` | 1:1 컬럼 |
| `신원보증인연결` | `guarantor_connections` | 1:1 컬럼 |

추가 admin 공유 탭 (신 고객 데이터.xlsx 에만 존재):

| 시트명 | PG 테이블 |
|---|---|
| `Accounts` | `tenants` + `users` |
| `게시판` | `board_posts` |
| `게시판댓글` | `board_comments` |
| `홈페이지게시물` | `marketing_posts` |
| `행정사서명` | `agent_signatures` (tenant_id 별 1행) |
| `서명임시저장` | `temp_signature_slots` |

`고객 데이터(기존)` 시트는 **legacy**. 활성 `고객 데이터` 시트만 사용.
`ROI_프리셋` 시트는 본 임포터 범위 밖 (다른 도메인).

## 5. 시트 → PG 테이블 매핑 (work 워크북)

| 시트명 | PG 테이블 |
|---|---|
| `각종공인증_업체` | `cert_vendors` |
| `각종공인증_대분류` | `cert_directions` |
| `각종공인증_중분류` | `cert_groups` |
| `각종공인증_소분류지역` | `cert_regions` |
| `각종공인증_가격조건` | `cert_prices` |
| 그 외 모든 시트 (`공증`, `규제`, `혼인 사망`, `재발급 비자`, `기타`, `C-3 단기일반`, `D-2 유학 D-4 일반연수`, `H-2 방문취업`, `F-4 재외동포`, `F-2 영주권 가족`, `F-5 영주권`, `F-6 결혼`, `E-7`, `E-9`, `귀화2`, `F-1 F4가족 귀화대기`, `D-2`, `자동차`, `장차 할일` 등) | `work_reference_sheets` + `work_reference_rows` (JSONB) |

## 6. 템플릿 워크북 처리

`기준 고객 데이터.xlsx` / `기준 업무정리.xlsx`:
- live 행은 절대 import 하지 않음
- 시트명·헤더만 검사해서 보고서 §7 (Template workbook inspection result) 에 기록
- `--only templates` 옵션은 검사만 수행하고 끝

## 7. 멱등 / 중복 처리

- 모든 PG 쓰기는 upsert (PK / UniqueConstraint 기준)
- 소스 행 자체에서 (tenant_id, id) 중복 발생 시 첫 번째만 유지하고 나머지 skip + 사유 로그
- `완료업무` 행의 `id` 가 비어있거나 중복이면 결정적 task_id 생성:
  ```
  sha1("{tenant_id}|completed|{sheet_name}|{row_no}|{date}|{name}|{work}|{category}")[:12]
  ```
- `진행업무` / `예정업무` / `일일결산` 도 같은 방식으로 fallback

## 8. 로그인 계정 보장

import 후 다음 순서로 admin 계정 보장:

1. `Accounts` 시트가 import 되었으면 운영 password_hash 그대로 유지 (preserve)
2. `tenant_id=hanwoory` 에 `is_admin=true` 사용자가 0명이면:
   - `test_admin` 가 이미 있으면 그대로, 없으면 생성
   - 비밀번호 `beta_test_password_123` → `hash_password()` 적용
3. `tenant_id=jpup` 사용자가 0명이면 `jpup_admin / beta_test_password_123 / is_admin=true` 생성
4. 기존 row 는 절대 password 덮어쓰기 금지 (idempotency)

## 9. CLI 사양

```
python backend/scripts/import_excel_snapshot_to_pg_local.py
    [--execute]
    [--reset-local-pg]
    [--only {hanwoory|jpup|templates|all}]
    [--tenant TENANT_ID]
    [--input-dir migration_input]
```

`--reset-local-pg`: customers / events / memos / daily_entries / daily_balances / active_tasks / planned_tasks / completed_tasks / customer_signatures / accommodation_providers / guarantor_connections / agent_signatures / temp_signature_slots / board_posts / board_comments / marketing_posts / cert_* / work_reference_sheets / work_reference_rows 의 모든 행 DELETE. tenants / users / audit_logs 는 보존.

## 10. 출력

```
[INPUT]   migration_input/  exists=True  files=6
[ROLES]
  hanwoory_customers  신 고객 데이터.xlsx        sheets=20
  hanwoory_work       신 업무정리.xlsx           sheets=25
  jpup_customers      tenants/고객 데이터 - jpup.xlsx  sheets=15
  jpup_work           tenants/업무정리 - jpup.xlsx      sheets=20
  template_customers  기준 고객 데이터.xlsx       sheets=14
  template_work       기준 업무정리.xlsx          sheets=20
[hanwoory] 고객 데이터: source_rows=1474 inserted=1473 updated=0 skipped=1
[hanwoory] 일정       : source_rows=80   inserted=80   skipped=0
... (도메인별 출력) ...
[SUMMARY] inserted=N  updated=N  skipped=N
[ACCOUNTS] hanwoory admin=test_admin/wkdwhfl ... jpup admin=jpup_admin
```

## 11. 검증 명령

```powershell
# 컴파일
.venv\Scripts\python.exe -m compileall backend -q

# 타입체크
cd frontend; npx tsc --noEmit

# Docker
docker ps --filter "name=kid-postgres-local"

# DB 환경
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"

# 스키마
.venv\Scripts\python.exe -m alembic upgrade head

# Dry-run
.venv\Scripts\python.exe backend\scripts\import_excel_snapshot_to_pg_local.py

# Execute (reset + import)
.venv\Scripts\python.exe backend\scripts\import_excel_snapshot_to_pg_local.py --execute --reset-local-pg
```

## 12. 정지 조건

- 컴파일 + tsc + import + HTTP smoke 통과
- `EXCEL_SNAPSHOT_MIGRATION_REPORT.md` 작성
- commit / push / deploy 없이 정지
- 사용자 브라우저 검증 대기
