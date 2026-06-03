# LOCAL_PG_STORAGE_STATUS_UI_REPORT.md

PG 모드 admin accounts 화면을 "Google Sheets 키 노출" 에서 "PostgreSQL 저장소 / 파일 저장소 상태" 로 정리하고, 로컬 PG 모드 워크스페이스 생성이 Google API 를 호출하지 않음을 결정적으로 재검증한 보고서.

## 1. 요약

| 항목 | 상태 |
|---|---|
| `/api/admin/accounts` 응답에 PG 저장소 / 파일 저장소 상태 필드 추가 | ✅ |
| Admin 화면이 PG 모드 시 4개 시트키 입력 컬럼 → 2개 상태 칩으로 교체 | ✅ |
| 신규 계정 생성 / 상세 편집 모달도 PG 모드 분기 | ✅ |
| Sheets 모드 (운영) 의 기존 UI 는 변경 없음 (backward compat) | ✅ |
| Local PG 모드에서 워크스페이스 생성이 Google API import 0건임을 결정적으로 증명 | ✅ |
| backend compile + frontend tsc EXIT=0 | ✅ |
| Google Sheets API / Drive API / Render / commit / push | 0회 |

## 2. 변경된 파일 (2개)

| 파일 | 변경 요지 |
|---|---|
| `backend/routers/admin.py` | `list_accounts` PG 분기에 `storage_mode` / `pg_storage_status` / `pg_storage_label` / `pg_counts` / `file_storage_status` / `file_storage_label` 6개 필드 추가. 테넌트별 customer/active/completed/daily/work_reference 카운트를 단발 GROUP BY 5건으로 조회. file_storage 분류: `local-*` prefix → `local-mock`, 실제 Google 키 → `google-drive`, 누락 조합 → `partial`/`mixed`/`none`. |
| `frontend/app/(main)/admin/page.tsx` | (a) 응답에 `storage_mode` 가 `pg+` 로 시작하면 `pgMode = true` (b) 테이블 헤더가 "고객시트키/업무시트키/폴더/마스터시트" 4컬럼 → "PG 저장소/파일 저장소" 2컬럼으로 교체 (c) `PgStorageChip` / `FileStorageChip` 컴포넌트 신설 (d) `CreateAccountModal`, `AccountDetailPanel` 도 동일 분기 — Google Sheets 입력 폼 대신 상태 설명 표시 (e) 페이지 헤더 옆에 `🧪 PG + 로컬 모의` 배지 |

기존 Sheets-only 운영 환경 응답 (`storage_mode` 미존재) 은 그대로 보존 — `pgMode=false` 이면 원래 4컬럼 입력 UI 가 표시된다.

## 3. 새 응답 필드 스펙

`GET /api/admin/accounts` PG 분기 각 행:

```json
{
  "login_id": "as",
  "tenant_id": "as",
  "office_name": "as test office",
  "is_admin": "FALSE",
  "is_active": "TRUE",
  "folder_id": "local-folder-as-8120c5b7",
  "customer_sheet_key": "local-sheet-customer-as-47c6c266",
  "work_sheet_key": "local-sheet-work-as-e81d9429",

  "storage_mode": "pg+local-mock",
  "pg_storage_status": "empty",
  "pg_storage_label": "비어있음",
  "pg_counts": {"customers": 0, "active_tasks": 0, "completed_tasks": 0,
                "daily_entries": 0, "work_reference_sheets": 0},
  "file_storage_status": "local-mock",
  "file_storage_label": "로컬 모의 저장소"
}
```

- `storage_mode` ∈ `{pg+local-mock, pg+google-drive}` — `FEATURE_LOCAL_DRIVE_MOCK` 켜져 있으면 전자.
- `pg_storage_status` ∈ `{ready, empty}` — `pg_counts` 합산이 1 이상이면 ready.
- `file_storage_status` ∈ `{none, local-mock, google-drive, partial, mixed}`:
  - `none` — 키 3개 모두 비어있음
  - `local-mock` — 3개 모두 `local-` 으로 시작
  - `google-drive` — 3개 모두 실제 Google ID (운영 Sheets 가져온 케이스)
  - `partial` — 일부만 채워짐 (3개 중 N개)
  - `mixed` — 일부는 local sentinel, 일부는 실제 Google ID (정상 상태에서 안 나옴)

raw key 필드 (`folder_id`/`customer_sheet_key`/`work_sheet_key`) 는 응답에 그대로 남는다 — 워크스페이스 생성 흐름이 여전히 이 키들을 PG `tenants` 행에 저장하기 때문. UI 만 PG 모드에서 숨김.

## 4. 실측 응답 (현재 로컬 PG 상태)

`GET /api/admin/accounts` 결과:

```
as         tenant=as         pg=empty  file=local-mock     로컬 모의 저장소
  pg_label: 비어있음
jpup       tenant=jpup       pg=ready  file=google-drive   Google Drive
  pg_label: 고객 5 · 진행 0 · 완료 0 · 일일 0 · 업무참고 15
wkdwhfl    tenant=hanwoory   pg=ready  file=google-drive   Google Drive
  pg_label: 고객 1473 · 진행 55 · 완료 578 · 일일 773 · 업무참고 19
```

`jpup`, `wkdwhfl` 의 `file=google-drive` 는 Excel 스냅샷 안에 들어있던 운영 Sheets ID 가 `tenants` 행에 보존되어 있기 때문이다 — **로컬 PG 모드에서는 이 ID 들이 어떤 API 호출에도 사용되지 않는다.** 라우터 분기들이 모두 PG flag 가 켜져 있을 때 PG 경로만 실행한다.

`as` 만이 깨끗한 로컬 mock 사례: signup → 워크스페이스 mock 호출 → sentinel ID 3개 채워짐 → `file_storage_status=local-mock`.

## 5. UI 변경 시각 요약

### 변경 전 (Sheets 모드 / PG 미감지)

```
| ID | 테넌트ID | ... | 고객시트키           | 업무시트키           | 폴더              | 마스터시트 | 워크스페이스 |
| as | as      |     | (입력) local-sheet… | (입력) local-sheet… | (입력) local-fol… | (입력)    | 자동생성    |
```

### 변경 후 (PG 모드 / `FEATURE_LOCAL_DRIVE_MOCK=true`)

```
| ID | 테넌트ID | ... | PG 저장소         | 파일 저장소           | 워크스페이스 |
| as | as      |     | 비어있음          | 🧪 로컬 모의 저장소   | ✅ 완료      |
| jp.| jpup    |     | ✓ PG 데이터 있음  | ☁️ Google Drive       | ✅ 완료      |
| wk.| hanwoory|     | ✓ PG 데이터 있음  | ☁️ Google Drive       | ✅ 완료      |
```

페이지 헤더 옆에 PG 모드 배지: `🧪 PG + 로컬 모의`

### 신규 계정 생성 모달 (PG 모드)

`Google Sheets 연동` 섹션 → `워크스페이스 (로컬 모의)` 로 라벨 교체. 4개 입력 칸 제거하고 다음 안내문 표시:

> 로컬 PG 모드에서는 Google Sheets / Drive 키를 직접 입력하지 않습니다.  
> 위 버튼을 누르면 backend의 `local_drive_mock` 이 sentinel ID (local-folder-… / local-sheet-…) 를 생성하고 PostgreSQL `tenants` 행에 저장합니다. Google API는 호출되지 않습니다.

버튼 라벨도 "워크스페이스 자동 생성" → "로컬 모의 생성" 으로 교체.

### 상세 편집 드로어 (PG 모드)

`Google Sheets 연동` 섹션 제거하고 다음 형태로 표시:

```
저장소 상태 (PostgreSQL 모드)
PostgreSQL: 고객 1473 · 진행 55 · 완료 578 · 일일 773 · 업무참고 19
파일 저장소: Google Drive

로컬 PG 모드에서는 Google Sheets / Drive 키를 직접 편집하지 않습니다.
워크스페이스가 필요하면 계정 행의 '워크스페이스 자동 생성' 버튼을 사용하세요.
```

## 6. 워크스페이스 mock 재검증 — 결정적 증거

### 6.1 새 가입 + mock 승인 흐름 검증

```
POST /api/auth/signup {"login_id":"as2","password":"...","office_name":"as2 office"}
→ {"status":"pending","tenant_id":"as2"}

POST /api/admin/workspace {"login_id":"as2","office_name":"as2 office"}
→ {
  "ok": true,
  "stages": {
    "folder_create":   {"status":"mocked", "id":"local-folder-as2-84f61be5"},
    "customer_copy":   {"status":"mocked", "id":"local-sheet-customer-as2-970eba94"},
    "work_copy":       {"status":"mocked", "id":"local-sheet-work-as2-c85365cd"},
    "accounts_update": {"status":"applied-to-local-tenants", "users_activated": 1}
  },
  "drive_user": "LOCAL_MOCK",
  "drive_quota": null,
  "message": "Local mock workspace created. Manifest: .local_pg_beta_drive/as2.json"
}
```

모든 단계 status=`mocked`, `drive_user=LOCAL_MOCK`, sentinel ID 3개 발급, user `as2` 자동 활성화.

### 6.2 process import 검증

신규 Python process 에서 백엔드 코드를 import → mock workspace 호출 → `sys.modules` 스냅샷 비교:

```
Mock flag enabled: True
Mock workspace ok: True
  folder_id starts local-: True
  customer_sheet_key starts local-: True
  work_sheet_key starts local-: True
  drive_user: LOCAL_MOCK

Google-related modules imported during backend.routers.admin import: 0
Google-related modules newly imported during provision_workspace call: 0
```

- `backend.routers.admin` 모듈 import 시 `googleapiclient` / `gspread` / `google.oauth` / `google.auth` / `google.api` 패밀리 모듈 **0개** 로드
- `provision_workspace()` 호출 후 추가로 import 된 Google 패밀리 모듈 **0개**

이는 `admin.py` 의 mock 분기가 `from googleapiclient.discovery import build` 라인을 절대 실행하지 않음을 의미한다. (해당 import 는 mock 분기 통과 후 ~~470 라인 부근에 있고, mock 분기는 ~435 라인에서 early-return.)

### 6.3 코드 위치

```python
# backend/routers/admin.py — create_workspace()
if local_drive_mock_enabled() or pg_tenant_provisioning_enabled():
    from backend.services.local_drive_mock import provision_workspace
    ...
    return result        # ← early return, googleapiclient 라인 도달 불가
```

`FEATURE_LOCAL_DRIVE_MOCK=true` (또는 `FEATURE_PG_TENANT_PROVISIONING=true`) 가 켜져 있는 한, 코드 흐름이 Google import 라인까지 가지 않는다. Process-level 증거 + 코드 정독 + 응답 본문 (`drive_user: "LOCAL_MOCK"`) — 세 가지 독립 증명 모두 일치.

## 7. 안전 확인

- ✅ Google Sheets API 호출 **0회**
- ✅ Google Drive API 호출 **0회**
- ✅ `googleapiclient` / `gspread` 모듈 process import **0건** (mock 모드에서)
- ✅ Render PG / 환경변수 / 배포 미접근
- ✅ 운영 Sheets / Drive 데이터 변경 **0건**
- ✅ 로컬 PG 의 `users` / `tenants` 행 손실 **0** — `wkdwhfl` (hanwoory), `jpup`, `as` 모두 보존. 본 검증 라운드에서 추가된 행은 `as2` 1개 (signup + workspace mock 테스트용).
- ✅ git commit / push / merge / deploy **0**

## 8. 실행 명령 요약

```powershell
# 1) 컴파일
.venv\Scripts\python.exe -m compileall backend -q              # EXIT=0
cd frontend; npx tsc --noEmit; cd ..                          # EXIT=0

# 2) DB
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"

# 3) 백엔드 (PG + LOCAL_DRIVE_MOCK 플래그 ON)
$env:FEATURE_PG_ADMIN = "true"
$env:FEATURE_LOCAL_DRIVE_MOCK = "true"
# ... 나머지 PG 플래그 (이전 보고서 §11)
.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8002

# 4) /api/admin/accounts 검증 (admin 토큰 필요)
curl -H "Authorization: Bearer <admin token>" http://127.0.0.1:8002/api/admin/accounts

# 5) signup + workspace mock 흐름
curl -X POST http://127.0.0.1:8002/api/auth/signup `
  -d '{"login_id":"as2","password":"as2pw","confirm_password":"as2pw","office_name":"as2"}' `
  -H 'Content-Type: application/json'

curl -X POST http://127.0.0.1:8002/api/admin/workspace `
  -H "Authorization: Bearer <admin token>" `
  -H 'Content-Type: application/json' `
  -d '{"login_id":"as2","office_name":"as2 office"}'
```

## 9. 현재 PG 상태 (정리 후)

```
users:
  ('as',      'as',       is_admin=False, is_active=True)    ← signup + workspace 통과
  ('as2',     'as2',      is_admin=False, is_active=True)    ← 본 검증 라운드에서 추가
  ('jpup',    'jpup',     is_admin=True,  is_active=True)    ← 임시 admin (option A 유지)
  ('wkdwhfl', 'hanwoory', is_admin=True,  is_active=True)    ← 실 admin

tenants:
  ('as',       'as test office',  is_active=True,  folder_id=local-folder-as-...)
  ('as2',      'as2 office',      is_active=True,  folder_id=local-folder-as2-...)
  ('hanwoory', '한우리행정사사무소', is_active=True,  folder_id=<운영 Drive ID — 미사용>)
  ('jpup',     '정평행정사사무소',  is_active=True,  folder_id=<운영 Drive ID — 미사용>)
```

## 10. 사용자 검증 흐름

1. PowerShell — `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8002` (이전 보고서의 환경변수 블록 그대로)
2. `cd frontend; $env:API_URL="http://127.0.0.1:8002"; npm run dev`
3. wkdwhfl 로 로그인 → `/admin` 진입
4. 헤더 옆에 `🧪 PG + 로컬 모의` 배지 표시 확인
5. 계정 테이블에서 4개 시트키 컬럼 → 2개 상태 칩 ("PG 저장소" / "파일 저장소") 으로 표시 확인
6. `as` 행: `🧪 로컬 모의 저장소` 칩
7. `jpup`/`wkdwhfl` 행: `☁️ Google Drive` 칩 (실 키는 보존되어 있되 호출되지 않음)
8. "신규 계정 생성" 모달의 워크스페이스 섹션 — 시트키 입력 칸 사라지고 "로컬 모의 생성" 버튼만 남음
9. 행 "편집" 클릭 → 드로어 내 "Google Sheets 연동" 섹션이 "저장소 상태 (PostgreSQL 모드)" 로 변경

## 11. 권장 commit 대상

```powershell
git add `
  backend/routers/admin.py `
  frontend/app/(main)/admin/page.tsx `
  LOCAL_PG_STORAGE_STATUS_UI_REPORT.md
```

(이전 라운드의 import 스크립트 / auth 라우터 / 첫 admin.py mock 분기 수정 / signup 수정 산출물 등은 별도 커밋 대상으로 이미 존재.)

## 12. 커밋 제외 대상

```
migration_input/
.local_pg_beta_drive/            # mock workspace manifests (as.json, as2.json 등)
.venv/  __pycache__/  *.pyc  .env
```

---

**정지 조건 충족.** commit / push / 배포 없음. 사용자 브라우저 검증 대기.
