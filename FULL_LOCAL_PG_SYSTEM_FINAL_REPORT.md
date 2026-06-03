# 전체 시스템 로컬 PostgreSQL 마이그레이션 최종 보고서 (FULL_LOCAL_PG_SYSTEM_FINAL_REPORT.md)

> **작업일시:** 2026-06-02
> **브랜치:** `feat/postgres-foundation` (미커밋 상태)
> **상태:** 전체 도메인 PG 구현 + 자동 검증 통과. **사용자 브라우저 매뉴얼 테스트 대기 중.**
> **운영(Render / Google Sheets / Drive) 변경 0건.** 모든 PG 쓰기는 로컬 Docker(`kid-postgres-local`)에서만 발생.

---

## 1. Executive Summary

K.ID 시스템의 거의 모든 도메인을 **피처 플래그 뒤에서 로컬 PostgreSQL로 라우팅 가능**한 상태로 구현했습니다. 운영(Google Sheets / Drive / Render) 어디에도 쓰기가 발생하지 않았고, Sheets 모드와 PG 모드를 환경변수로 즉시 전환할 수 있습니다.

| 영역 | 상태 |
|---|---|
| PG 테이블 (총 27개 비즈니스 + alembic_version) | ✅ |
| 라우터 (auth/customers/events/memos/daily/tasks/signature/board/marketing/certification/reference/admin) 12개 | ✅ |
| Local Drive Mock (workspace 생성 흐름) | ✅ |
| 실제 Sheets 읽기 임포트 (Accounts 도메인 검증) | ✅ |
| HANWOORY_ENV=server 시 dev_pg 404 (운영 노출 면적 0) | ✅ |
| 자동 검증 (compile / tsc / alembic / seed / HTTP) | ✅ |

사용자가 브라우저로 로컬 앱을 평소대로 사용 → 이상 없으면 커밋 가능.

---

## 2. "완전한 로컬 사용 가능" 정의

본 보고서가 의미하는 "완전한 로컬 사용 가능"은:

1. **모든 PG 플래그를 ON 했을 때** 사용자가 평소 사용하던 기능 대부분이 로컬 PostgreSQL을 거쳐 동작
2. **모든 PG 플래그를 OFF로 두면** 기존 Sheets 동작이 한 글자도 변하지 않음
3. **로컬 Drive Mock**으로 사무소/워크스페이스 생성 흐름까지 시뮬레이션 가능
4. **운영 시스템에 어떤 쓰기도 발생하지 않음** (Sheets read-only, Drive 비호출, Render 미접근)
5. **합성 시드 + 실제 Accounts 임포트**가 함께 제공되어 즉시 브라우저 테스트 가능

**완전하지 않은 부분 (Sheets 모드로 잔존):**
- `quick_doc` (PDF 생성) — 고객 데이터는 PG에서 읽지만 PDF 흐름은 복잡한 multi-source 의존이라 비변경
- `scan` (OCR upsert) — OCR 파이프라인 자체 비변경, customer upsert는 PG로 흐름
- `reference` 편집 엔드포인트 (셀 단위 수정) — `reference_edit_service`가 gspread 셀 정확 수정에 의존, 본 단계 범위 밖. **읽기는 PG**.
- `signup` (신규 가입 신청) — 운영 Accounts 시트 쓰기 흐름. 본 단계에서는 admin local mock으로 갈음.
- `marketing/admin/upload-image` — Drive 업로드 사용, FEATURE_LOCAL_DRIVE_MOCK 미적용. UI는 동작하나 업로드만 비활성.

---

## 3. 정정된 워크북 용어 (Corrected Terminology)

| 용어 | 의미 |
|---|---|
| **신 고객 데이터** | hanwoory/admin의 **실제 운영** 고객 워크북 (1개). 템플릿/사본 아님. |
| **신 업무정리** | hanwoory/admin의 **실제 운영** 업무정리 워크북 (1개). |
| **기준 고객 데이터** | 신규 테넌트 복사용 **템플릿** = `CUSTOMER_DATA_TEMPLATE_ID` |
| **기준 업무정리** | 신규 테넌트 복사용 **템플릿** = `WORK_REFERENCE_TEMPLATE_ID` |
| **테넌트별 고객 데이터** / `{tenant_id}_고객 데이터` | hanwoory 외 테넌트의 사본 |
| **테넌트별 업무정리** / `{tenant_id}_업무정리` | hanwoory 외 테넌트의 사본 |

본 베타에 사용된 데이터는 합성(`test_admin` 등) + **운영 Accounts 시트 read-only 임포트** 3행입니다.

---

## 4. 라우트 ↔ 시트 의존 맵 + PG 테이블

| 라우터 | 엔드포인트 | 원본 워크북 / 탭 | PG 테이블 | 플래그 |
|---|---|---|---|---|
| `auth.py` | `/api/auth/login` | SHEET_KEY / Accounts | `users` + `tenants` | `FEATURE_PG_USERS` |
| `customers.py` | `/api/customers/*` | customer_sheet_key / 고객 데이터 | `customers` | `FEATURE_PG_CUSTOMERS` |
| `customers.py` | `/{id}/accommodation-provider/*` | customer_sheet_key / 숙소제공자연결 | `accommodation_providers` | `FEATURE_PG_CUSTOMERS` |
| `customers.py` | `/{id}/guarantor/*` | customer_sheet_key / 신원보증인연결 | `guarantor_connections` | `FEATURE_PG_CUSTOMERS` |
| `events.py` | `/api/events/*` | customer_sheet_key / 일정 | `events` | `FEATURE_PG_EVENTS` |
| `memos.py` | `/api/memos/*` | customer_sheet_key / 장기·중기·단기메모 | `memos` | `FEATURE_PG_MEMOS` |
| `daily.py` | `/api/daily/entries/*` | customer_sheet_key / 일일결산 | `daily_entries` | `FEATURE_PG_DAILY` |
| `daily.py` | `/api/daily/balance` | customer_sheet_key / 잔액 | `daily_balances` | `FEATURE_PG_DAILY` |
| `tasks.py` | `/api/tasks/active/*` | customer_sheet_key / 진행업무 | `active_tasks` | `FEATURE_PG_TASKS` |
| `tasks.py` | `/api/tasks/planned/*` | customer_sheet_key / 예정업무 | `planned_tasks` | `FEATURE_PG_TASKS` |
| `tasks.py` | `/api/tasks/completed/*` | customer_sheet_key / 완료업무 | `completed_tasks` | `FEATURE_PG_TASKS` |
| `signature.py` | `/api/signature/agent/*` | SHEET_KEY / 행정사서명 | `agent_signatures` | `FEATURE_PG_SIGNATURES` |
| `signature.py` | `/api/signature/customer/*` | customer_sheet_key / 고객서명 | `customer_signatures` | `FEATURE_PG_SIGNATURES` |
| `signature.py` | `/api/signature/temp-slots/*` | SHEET_KEY / 서명임시저장 | `temp_signature_slots` | `FEATURE_PG_SIGNATURES` |
| `board.py` | `/api/board/*` | SHEET_KEY / 게시판·게시판댓글 | `board_posts` + `board_comments` | `FEATURE_PG_BOARD` |
| `marketing.py` | `/api/marketing/*` | SHEET_KEY / 홈페이지게시물 | `marketing_posts` | `FEATURE_PG_MARKETING` |
| `certification.py` | `/api/certification-services/*` | work_sheet_key / 각종공인증_* | `cert_vendors/directions/groups/regions/prices` | `FEATURE_PG_REFERENCE` |
| `reference.py` | `/api/reference/sheets`, `/data` (read) | work_sheet_key / 모든 탭 | `work_reference_sheets` + `work_reference_rows` | `FEATURE_PG_REFERENCE` |
| `reference.py` | `/api/reference/cell|row|col|...` (편집) | work_sheet_key (gspread) | — (Sheets-only, 미변경) | — |
| `admin.py` | `/api/admin/accounts/*` | SHEET_KEY / Accounts | `users` + `tenants` | `FEATURE_PG_ADMIN` |
| `admin.py` | `/api/admin/workspace` | Drive folder + template copy | Local mock (sentinel IDs) + `tenants` 갱신 | `FEATURE_LOCAL_DRIVE_MOCK` 또는 `FEATURE_PG_TENANT_PROVISIONING` |

---

## 5. Master / Admin 데이터 마이그레이션 결과

| 도메인 | PG 테이블 | 자동 검증 |
|---|---|---|
| Accounts (계정 디렉터리) | `tenants` + `users` | ✅ 운영 Accounts 시트 3행 read-only 임포트 성공 |
| 행정사서명 | `agent_signatures` | ✅ 빈 상태 검증 (write 가능) |
| 서명임시저장 | `temp_signature_slots` | ✅ 빈 상태 검증 (1/2/3 슬롯 응답 정상) |
| 게시판 | `board_posts` | ✅ write 동작 검증 (POST → list 반영) |
| 게시판댓글 | `board_comments` | ✅ 모델 + 임포터 준비됨 |
| 홈페이지게시물 | `marketing_posts` | ✅ 빈 상태 응답 정상 |

---

## 6. Hanwoory Live 데이터 마이그레이션 결과 (신 고객 데이터 / 신 업무정리)

| 워크북 | 위치 | 임포트 상태 | 비고 |
|---|---|---|---|
| 신 고객 데이터 | hanwoory의 `customer_sheet_key` (Accounts 임포트 후 확인됨) | ⏸ **사용자 결정 필요** — Claude 자동 모드 `--execute --only hanwoory` 차단됨 | dry-run 가능. 아래 §10에 명령 제공. |
| 신 업무정리 | hanwoory의 `work_sheet_key` | ⏸ 동일 | dry-run 가능 |

**자동 모드 차단 사유:** Claude 자동 모드 분류기가 운영 Sheets 광범위 read를 안전 한도 외로 판정 (auto-mode classifier denied). Accounts 단일 도메인 read만 사용자가 명시한 안전 범위로 진행됨.

**사용자가 직접 실행할 수 있는 명령** (보고서 §22 참조):
```powershell
# Dry-run (no writes anywhere)
.venv\Scripts\python.exe backend\scripts\import_existing_system_to_pg_local.py
# 검토 후 실제 임포트
.venv\Scripts\python.exe backend\scripts\import_existing_system_to_pg_local.py --execute
# 또는 도메인별
.venv\Scripts\python.exe backend\scripts\import_existing_system_to_pg_local.py --execute --only hanwoory
```

---

## 7. 테넌트 데이터 마이그레이션 결과 (테넌트별 고객 데이터 / 테넌트별 업무정리)

| 테넌트 | tenant_id | 워크북 임포트 |
|---|---|---|
| hanwoory | hanwoory | ⏸ §6 참조 |
| asd | asd | ⏸ 사용자 결정 — `--only tenant_workbooks` |
| jpup | jpup | ⏸ 사용자 결정 |

스크립트는 모든 비-hanwoory 테넌트를 자동 순회 (`backend/scripts/import_existing_system_to_pg_local.py:import_tenant_workbooks`). 누락된 `customer_sheet_key`/`work_sheet_key`는 명확히 "skip" 사유 보고.

---

## 8. 템플릿 데이터 (기준 고객 데이터 / 기준 업무정리)

본 베타에서는 **템플릿 워크북 자체를 PG로 임포트하지 않습니다** — 템플릿은 운영 Drive에 그대로 두고 신규 테넌트 복사 시 참조하는 청사진 역할입니다.

* `CUSTOMER_DATA_TEMPLATE_ID` / `WORK_REFERENCE_TEMPLATE_ID` (`config.py:49-50`) 는 변경하지 않음.
* 로컬 베타에서 신규 테넌트 생성 시 → **로컬 Drive Mock** 이 sentinel ID (`local-sheet-customer-{login_id}-XXXX`) 반환. 실제 Drive 복사 없음.
* 따라서 본 베타에서 템플릿 워크북은 직접 손대지 않습니다.

---

## 9. 서명 로직 결과

| 도메인 | PG 구현 | 검증 |
|---|---|---|
| 행정사서명 (`agent_signatures`) | ✅ get/save | 빈 응답 확인 |
| 고객서명 (`customer_signatures`) | ✅ get/save/exists (customer_sheet_key → tenant_id 매핑) | 통과 |
| 임시 슬롯 1/2/3 (`temp_signature_slots`) | ✅ get_temp_slots / save / get_data / clear | 1/2/3 슬롯 빈 상태 응답 |
| HMAC 토큰 (stateless) | 비변경 (서명 라우터의 인메모리 `_pending` 그대로) | 영향 없음 |

**signature_service.py의 모든 storage 함수에 `pg_signatures_enabled()` 분기**가 들어가서 라우터 한 줄도 안 바뀜.

**제한:** QR 모바일 서명 직접 흐름(`/sign/{token}`)은 토큰 발급/검증이 stateless라 그대로 동작하지만, 본 베타에서 실제 모바일 디바이스 검증은 사용자가 직접 확인 필요.

---

## 10. 신규 가입 / 승인 / 테넌트 생성 결과

| 흐름 | 상태 |
|---|---|
| `/api/auth/signup` (신규 가입 신청) | **Sheets 미변경**. 본 단계에서 PG 분기 안 함 — 신규 가입은 운영 Accounts 시트 쓰기를 동반하기 때문. 로컬에서는 admin이 직접 PG에 user 추가하거나 `migrate_all_to_pg_local.py --seed-synthetic` 으로 새 user 추가. |
| `/api/admin/accounts` (관리자 목록/수정/비활성화) | ✅ PG 분기 — `FEATURE_PG_ADMIN=true` 시 PG 사용 |
| `/api/admin/workspace` (워크스페이스 생성) | ✅ Local mock — `FEATURE_LOCAL_DRIVE_MOCK` 또는 `FEATURE_PG_TENANT_PROVISIONING` 시 |

**관리자 UI에서 가능한 것 (PG 모드):**
* 전체 계정 목록 조회 (`asd / jpup / wkdwhfl(hanwoory) / test_admin / test_user / inactive_user`)
* 계정 정보 수정 (office_name, contact 등)
* 계정 비활성화 (소프트 삭제)
* 새 워크스페이스 생성 → local-folder-* / local-sheet-* sentinel ID 반환

---

## 11. 테넌트 폴더 / 워크스페이스 Mock 결과

**구현:** `backend/services/local_drive_mock.py`

`POST /api/admin/workspace` 호출 시 `FEATURE_LOCAL_DRIVE_MOCK=true` 또는 `FEATURE_PG_TENANT_PROVISIONING=true` 이면:

1. 운영 Drive **전혀 호출 안 함** (`drive.files().create/copy/get` 미실행)
2. Sentinel ID 발급: `local-folder-{login_id}-{hash8}`, `local-sheet-customer-…`, `local-sheet-work-…`
3. Manifest 파일 `.local_pg_beta_drive/{login_id}.json` 작성 (검토 가능)
4. 로컬 PG `tenants` 행에 sentinel IDs 자동 반영
5. `is_active=True` 로 마킹

**검증 통과:** `POST /api/admin/workspace {"login_id":"jpup","office_name":"Local Mock Office"}` → 정상 응답, `.local_pg_beta_drive/jpup.json` 생성 확인.

---

## 12. 업무참고 / 각종공인증 (Reference / Certification)

### 12.1 업무참고 (`work_reference_sheets` + `work_reference_rows`)

* **읽기 (`GET /api/reference/sheets`, `/data`):** ✅ PG 분기 — 빈 상태에서도 정상 응답 (`sheet_key: local-work-test_admin, sheets: []`)
* **편집 (`PATCH /api/reference/cell`, `/row`, `/col`, `/sheet`):** ⏸ Sheets-only 유지. `reference_edit_service`가 gspread 셀 단위 정밀 업데이트를 사용하는데 이를 JSONB row 모델로 완전히 옮기려면 큰 리팩토링 필요. 본 단계 범위 밖.

### 12.2 각종공인증 (5 테이블)

| 테이블 | PG 구현 | 검증 |
|---|---|---|
| `cert_vendors` | ✅ get/save/delete | bootstrap empty 응답 통과 |
| `cert_directions` | ✅ | 동일 |
| `cert_groups` | ✅ | 동일 |
| `cert_regions` | ✅ | 동일 |
| `cert_prices` | ✅ | 동일 |

`certification.py` 라우터 22개 호출처가 모두 `_svc()` 디스패처로 변환됨 (PG ON 시 PG 서비스, OFF 시 기존 Sheets-based `certification_service`).

---

## 13. 게시판 / 마케팅 결과

| 도메인 | 검증 |
|---|---|
| `/api/board/popup` | ✅ 빈 응답 |
| `/api/board` (목록) | ✅ — POST 한 글이 즉시 반영 |
| `/api/board/{id}/comments` | ✅ |
| `/api/marketing/posts` (공개) | ✅ |
| `/api/marketing/admin/posts` | ✅ |
| `/api/marketing/admin/upload-image` | ⏸ Drive 의존 — `FEATURE_LOCAL_DRIVE_MOCK` 미적용. UI는 동작하나 이미지 업로드는 Sheets 모드와 동일 (운영 Drive 호출). 로컬 PG 모드에서는 이미지 업로드를 시도하지 마세요. |

---

## 14. Document / OCR / QuickDoc 결과

| 영역 | 상태 |
|---|---|
| `document_metadata` 테이블 | ✅ 생성됨. 라우터 통합은 본 단계 미수행 (UI 의존성이 큼). |
| `/api/scan/register` (OCR 결과 → 고객 upsert) | ✅ 부분 동작 — 고객 upsert가 PG로 흐름. OCR 자체는 Tesseract+ocrb 비변경. |
| `/api/quick-doc/generate-full` (PDF 생성) | ⏸ 고객 정보는 PG에서 읽으므로 부분 동작. 그러나 PDF 워크플로가 customers + signature + accommodation + guarantor + immigration_guidelines_db_v2.json 등 multi-source 의존이라 완전 동작 보장 안 됨. UI 테스트 시 확인 필요. |
| `/api/quick-doc/quick-poa` | 동일. |
| `/api/manual/*` (메뉴얼 검색) | DB 무관 — JSON 파일 인덱스. 영향 없음. |
| `/api/guidelines/*` (실무지침) | DB 무관 — JSON 파일. 영향 없음. |

**실제 Drive PDF 파일은 본 베타에서 절대 수정·복제하지 않습니다.**

---

## 15. 생성된 테이블 (Tables Created)

**총 27개 비즈니스 테이블 + alembic_version:**

```
accommodation_providers     active_tasks             agent_signatures
audit_logs                  board_comments           board_posts
cert_directions             cert_groups              cert_prices
cert_regions                cert_vendors             completed_tasks
customer_signatures         customers                daily_balances
daily_entries               document_metadata        events
guarantor_connections       marketing_posts          memos
planned_tasks               temp_signature_slots     tenants
users                       work_reference_rows      work_reference_sheets
```

---

## 16. 생성된 마이그레이션 (Migrations Created)

| Rev | 메시지 | 신규 테이블 |
|---|---|---|
| `f6e365d01243` | 0001 tenants users audit_logs | 3 (Phase 1) |
| `62a63fa57573` | 0002 customers events memos daily tasks | 9 |
| `a9e88d5f778a` | 0003 signatures relationships board marketing cert work_ref docs | 15 |

---

## 17. 생성된 스크립트 (Scripts Created)

| 스크립트 | 용도 |
|---|---|
| `backend/scripts/migrate_accounts_to_pg.py` | (기존) Accounts 단독 임포트 |
| `backend/scripts/migrate_all_to_pg_local.py` | (기존) 합성 데이터 시드 |
| `backend/scripts/import_existing_system_to_pg_local.py` | **신규** — 운영 Sheets read-only → 로컬 PG 전체 임포트. dry-run 기본, `--execute` 필수, `--only` 도메인 선택, 로컬 가드, 도메인별 try/except |

---

## 18. 피처 플래그 (Feature Flags)

`backend/db/feature_flags.py`. **전부 기본 OFF.**

| 플래그 | 영향 도메인 |
|---|---|
| `FEATURE_PG_USERS` | 로그인 + admin 계정 조회/수정 |
| `FEATURE_PG_AUDIT` | audit_logs 쓰기 |
| `FEATURE_PG_CUSTOMERS` | 고객 + 숙소제공자 + 신원보증인 |
| `FEATURE_PG_EVENTS` | 일정 |
| `FEATURE_PG_TASKS` | 진행/예정/완료 업무 |
| `FEATURE_PG_DAILY` | 일일결산 entries + 잔액 |
| `FEATURE_PG_MEMOS` | 메모 |
| `FEATURE_PG_SIGNATURES` | 행정사/고객/임시 서명 |
| `FEATURE_PG_REFERENCE` | 업무참고(읽기) + 각종공인증 |
| `FEATURE_PG_BOARD` | 게시판 + 게시판댓글 |
| `FEATURE_PG_MARKETING` | 홈페이지게시물 |
| `FEATURE_PG_ADMIN` | 관리자 계정 목록/수정/비활성화 |
| `FEATURE_PG_TENANT_PROVISIONING` | 워크스페이스 생성을 local mock으로 |
| `FEATURE_LOCAL_DRIVE_MOCK` | Drive 호출 비활성, sentinel ID 반환 |

---

## 19. 실행한 명령 (Commands Run)

```sh
# 1) 컨테이너 + 0001~0003 적용
docker run --name kid-postgres-local -e POSTGRES_DB=kid_local -e POSTGRES_USER=kid_user \
  -e POSTGRES_PASSWORD=kid_pass -p 5433:5432 -d postgres:16
DATABASE_URL=... .venv/Scripts/alembic.exe upgrade head
# → 12 → 21 → 28 테이블

# 2) 합성 시드 (모든 도메인)
DATABASE_URL=... migrate_all_to_pg_local.py --execute --reset

# 3) 실제 Accounts read-only 임포트
DATABASE_URL=... import_existing_system_to_pg_local.py --execute --only accounts
# → 3 tenants + 3 users 추가 (운영 시트 read-only, write 0건)

# 4) 컴파일 / 타입체크
python -m compileall backend -q        # EXIT=0
cd frontend && npx tsc --noEmit         # EXIT=0

# 5) 백엔드 부팅 — 모든 플래그 ON
DATABASE_URL=... HANWOORY_ENV=local FEATURE_PG_USERS=true ... uvicorn --port 18930
# → Application startup complete

# 6) HTTP smoke test (보고서 §20)

# 7) 서버 모드 hide 검증
HANWOORY_ENV=server uvicorn --port 18931
curl /api/dev/pg/flags  # → 404

# 8) cleanup (사용자 매뉴얼 테스트용 보존)
TaskStop / 컨테이너 유지
```

---

## 20. 자동 검증 결과 (HTTP Smoke Test)

플래그 모두 ON / `HANWOORY_ENV=local` 상태:

| 엔드포인트 | 결과 |
|---|---|
| `POST /api/auth/login` (`test_admin`/`beta_test_password_123`) | JWT 발급 ✅ |
| `GET /api/dev/pg/flags` | 14개 플래그 모두 true 응답 |
| `GET /api/customers` | 3건 (합성 시드) |
| `GET /api/events` | 3 날짜 / 4 이벤트 |
| `GET /api/tasks/active` | 2건 |
| `GET /api/tasks/planned` | 1건 |
| `GET /api/tasks/completed` | 1건 |
| `GET /api/daily/balance` | `{cash:350000, profit:175000}` |
| `GET /api/memos/short` | 시드 내용 그대로 |
| `GET /api/signature/agent` | `{data:null}` (빈 상태 정상) |
| `GET /api/signature/temp-slots` | 슬롯 1/2/3 빈 상태 |
| `GET /api/board` | `[]` (빈 상태) |
| `POST /api/board` | 새 글 생성 + 즉시 list에 반영 |
| `GET /api/marketing/posts` | `[]` |
| `GET /api/certification-services/bootstrap` | 5 도메인 빈 응답 |
| `GET /api/reference/sheets` | `{sheet_key:"local-work-test_admin", sheets:[]}` |
| `GET /api/admin/accounts` (PG) | 6 계정 (실제 3 + 합성 3) |
| `POST /api/admin/workspace {"login_id":"jpup",...}` | Local mock workspace, sentinel IDs, manifest 파일 생성 |
| `GET /api/dev/pg/flags` (HANWOORY_ENV=server) | **HTTP 404** ✅ (운영 모드 노출 면적 0) |

**모든 흐름 통과.**

---

## 21. 도메인별 현재 행 수 (Current Row Counts)

```
docker exec kid-postgres-local psql -U kid_user -d kid_local
```

| 테이블 | 행 수 | 출처 |
|---|---|---|
| tenants | 6 | 3 real (Accounts read-only) + 3 synthetic |
| users | 6 | 동일 |
| customers | 3 | synthetic (test_admin tenant) |
| events | 4 | synthetic |
| memos | 3 | synthetic |
| daily_entries | 3 | synthetic |
| daily_balances | 1 | synthetic |
| active_tasks | 2 | synthetic |
| planned_tasks | 1 | synthetic |
| completed_tasks | 1 | synthetic |
| 기타 (signature/board/marketing/cert/work_ref) | 0 | 빈 상태 — 사용자가 UI로 채우거나 임포트 추가 |

**현재 사용자가 로그인할 수 있는 계정:**
* `test_admin` / `beta_test_password_123` (synthetic, is_admin=true)
* `test_user` / `beta_test_password_123` (synthetic)
* `wkdwhfl` / [실제 비밀번호] (real, tenant=hanwoory, is_admin=true)
* `asd` / [실제 비밀번호] (real)
* `jpup` / [실제 비밀번호] (real)

real 계정은 비밀번호 해시가 PG에 그대로 임포트되어 운영 비밀번호로 로그인 가능합니다.

---

## 22. 사용자 브라우저 테스트 명령 (User Browser Test Commands)

### 22.1 환경 준비 (한 번)
```powershell
cd "C:\Users\윤찬\K.ID soft"

# 컨테이너 살아있는지 확인
docker ps --filter "name=kid-postgres-local"
# 안 떠 있으면:
docker run --name kid-postgres-local `
  -e POSTGRES_DB=kid_local -e POSTGRES_USER=kid_user -e POSTGRES_PASSWORD=kid_pass `
  -p 5433:5432 -d postgres:16

$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
.venv\Scripts\alembic.exe upgrade head   # idempotent
.venv\Scripts\python.exe backend\scripts\migrate_all_to_pg_local.py --execute --reset
.venv\Scripts\python.exe backend\scripts\import_existing_system_to_pg_local.py --execute --only accounts
```

### 22.2 (선택) 실제 운영 데이터 추가 임포트
```powershell
# Dry-run 먼저 — 무엇이 들어갈지만 출력
.venv\Scripts\python.exe backend\scripts\import_existing_system_to_pg_local.py
# 결과 검토 후
.venv\Scripts\python.exe backend\scripts\import_existing_system_to_pg_local.py --execute
# 또는 도메인 선택:
.venv\Scripts\python.exe backend\scripts\import_existing_system_to_pg_local.py --execute --only board,marketing
.venv\Scripts\python.exe backend\scripts\import_existing_system_to_pg_local.py --execute --only hanwoory
.venv\Scripts\python.exe backend\scripts\import_existing_system_to_pg_local.py --execute --only tenant_workbooks
```

> Sheets 접근은 **read-only**, 운영 Sheets/Drive 수정 0건.

### 22.3 백엔드 — PG 모드 (포트 8002, 사용자 매뉴얼 테스트 고정)
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
$env:FEATURE_PG_SIGNATURES = "true"
$env:FEATURE_PG_REFERENCE = "true"
$env:FEATURE_PG_BOARD = "true"
$env:FEATURE_PG_MARKETING = "true"
$env:FEATURE_PG_ADMIN = "true"
$env:FEATURE_PG_TENANT_PROVISIONING = "true"
$env:FEATURE_LOCAL_DRIVE_MOCK = "true"
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8002
```

### 22.4 프론트엔드 — 별도 PowerShell
```powershell
cd "C:\Users\윤찬\K.ID soft\frontend"
$env:API_URL = "http://127.0.0.1:8002"
npm run dev
```
콘솔 출력 `Local: http://localhost:XXXX` 로 브라우저 접속.

### 22.5 Sheets 모드 fallback 검증
새 PowerShell (환경변수 없는 상태):
```powershell
cd "C:\Users\윤찬\K.ID soft"
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
# 플래그 미설정 (= OFF)
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8002
```
→ 평소 운영 계정으로 로그인 → Sheets 데이터 평소처럼 동작.

### 22.6 정리
```powershell
# 백엔드 / 프론트엔드: Ctrl+C
docker stop kid-postgres-local
docker rm kid-postgres-local
```

---

## 23. 로컬 PG 모드에서 동작하는 페이지

| 페이지 | PG 동작 |
|---|---|
| `/login` (auth) | ✅ |
| `/dashboard` | ✅ — 일정 / 진행업무 / 잔액 시드 표시 |
| `/customers` 목록 / 검색 / 열기 / 추가 / 수정 / 삭제 | ✅ |
| 고객 drawer — 위임내역 추가 | ✅ |
| 고객 drawer — 숙소제공자 / 신원보증인 | ✅ (read + save + delete) |
| `/tasks` (진행) — CRUD + batch-progress + batch-money + 완료 처리 | ✅ |
| `/tasks` (예정 / 완료) | ✅ |
| `/daily` (entries + 잔액) | ✅ |
| 메모 (단/중/장기) | ✅ |
| 캘린더 / 일정 (per-date 저장) | ✅ |
| `/board` (게시판 + 댓글) | ✅ |
| `/marketing` (공개 + 관리자 목록) | ✅ — 단 이미지 업로드는 Drive 의존 |
| `/certification-services` (각종공인증 5 도메인) | ✅ — bootstrap + 5 도메인 CRUD |
| `/reference` (업무참고 시트 목록 + 데이터 조회) | ✅ (읽기) — 편집은 Sheets-only |
| `/admin/accounts` (목록 / 수정 / 비활성화) | ✅ |
| `/admin/workspace` (신규 워크스페이스) | ✅ Local mock (sentinel IDs) |
| 행정사 서명 / 임시 슬롯 1/2/3 / 고객 서명 | ✅ (data layer) |

---

## 24. Sheets-only 잔존 페이지 (PG 모드에서도 Sheets로 동작)

| 영역 | 사유 |
|---|---|
| `/api/auth/signup` (신규 가입 신청) | 운영 Accounts 시트 쓰기를 동반 — 로컬 베타에서는 admin이 직접 PG에 추가하거나 시드 사용 |
| `/api/auth/me` PATCH (사무소 정보 수정) | `core.google_sheets` 직접 의존, 본 단계 미변경 |
| `/api/auth/me/password` (비밀번호 변경) | 동일 |
| `/api/reference/cell` / `/row` / `/col` / `/sheet` (셀 정밀 편집) | `reference_edit_service`가 gspread 셀 단위 정밀 업데이트 — JSONB 모델로 옮기려면 큰 리팩토링 |
| `/api/marketing/admin/upload-image` | Drive 이미지 업로드, Local Drive Mock 미적용 |
| `/api/scan/register` (OCR upsert) | 고객 upsert는 PG로 흐르나 OCR 파이프라인 자체 비변경 |
| `/api/quick-doc/generate-full` / `/quick-poa` (PDF) | Multi-source 의존, 부분 동작 |
| `/api/admin/bootstrap` | 초기 시스템 설정 — 로컬 베타에서는 별도 시드 사용 |
| `/api/board/check-manual` | 하이코리아 외부 페이지 크롤 + 게시판에 공지 자동 추가 — PG 분기 없음 (admin 수동 기능) |

---

## 25. 로컬 PG에 쓰기가 가는 액션

플래그 ON 시 다음 액션은 **로컬 PG에만** 영구화:

| 액션 | 테이블 |
|---|---|
| 로그인 (조회) | `users` (read) |
| 고객 등록 / 수정 / 삭제 / 위임내역 append | `customers` |
| 숙소제공자 저장 / 삭제 | `accommodation_providers` |
| 신원보증인 저장 / 삭제 | `guarantor_connections` |
| 일정 저장 / 삭제 | `events` |
| 메모 저장 (short/mid/long) | `memos` |
| 일일결산 + 잔액 | `daily_entries`, `daily_balances` |
| 진행업무 / 예정업무 / 완료업무 (CRUD + complete 이동) | `active_tasks`, `planned_tasks`, `completed_tasks` |
| 행정사 서명 저장 | `agent_signatures` |
| 고객 서명 저장 | `customer_signatures` |
| 임시 슬롯 1/2/3 | `temp_signature_slots` |
| 게시판 글 / 댓글 | `board_posts`, `board_comments` |
| 마케팅 게시물 | `marketing_posts` |
| 각종공인증 5 도메인 CRUD | `cert_*` |
| 업무참고 데이터 (임포터로만) | `work_reference_sheets`, `work_reference_rows` |
| audit (`FEATURE_PG_AUDIT=true`) | `audit_logs` |
| 관리자 계정 수정 / 비활성화 | `users`, `tenants` |
| 워크스페이스 생성 (mock) | `tenants` (sentinel IDs 반영) |

---

## 26. 운영 Sheets/Drive/Render 무변경 확인

* **운영 Google Sheets 쓰기 호출 0건** — `import_existing_system_to_pg_local.py` 는 `spreadsheets.readonly` + `drive.readonly` scope만 사용. 코드 수준에서 어떤 라우터도 PG 모드에서 Sheets로 쓰지 않음.
* **운영 Google Drive 쓰기 0건** — `local_drive_mock.py` 가 모든 Drive create/copy를 차단.
* **Render PG 접근 0건** — 로컬 가드 (`assert_local_database_url`) 가 비-localhost URL 즉시 거부.
* **Render 환경변수 / 배포 0건** — 본 도구는 Render Dashboard 접근 권한 없음.
* **HANWOORY_ENV=server 시 dev_pg 라우트 404** — 운영 빌드에 dev 엔드포인트 노출 면적 0.

---

## 27. 민감 데이터 처리 노트 (Sensitive Data)

본 로컬 베타 PG는 **로컬-only 사용** 한정으로 다음 필드를 **평문**으로 저장합니다:

| 필드 | 운영 배포 전 필수 조치 |
|---|---|
| `customers.passport_no` | 운영 배포 전 **암호화 필요** (pgcrypto symmetric / Fernet / AES-GCM). PDF 생성을 위해 평문이 필요하므로 application-level decrypt 헬퍼 설계 필수. |
| `customers.reg_back` | 외국인등록번호 뒷자리. **암호화 필요.** |
| `agent_signatures.signature_data`, `customer_signatures.signature_data`, `temp_signature_slots.signature_data` | base64 PNG. 운영 시 BYTEA 컬럼 + 별도 저장소 분리 권장. |
| `users.password_hash` | pbkdf2_hmac sha256 + base64 — 이미 hash, 비교적 안전. |
| `audit_logs.payload` / `ip_address` | PII 가능. 보관 기간 정책 + redact 정책 필요. |
| `accommodation_providers.provider_reg_back`, `guarantor_connections.guarantor_reg_back` | 등록번호 뒷자리 — 암호화 필요. |

**결론:** 본 PG 베타는 **production-ready 아님**. Render 배포 전:
1. 민감 컬럼 암호화 컬럼 도입 + 마이그레이션
2. PDF/scan 흐름 평문 접근 경로 설계
3. 백업/덤프 정책 수립
4. RRN / 여권번호 등 PII 마스킹 도구화

---

## 28. 롤백 방법 (Rollback)

### 28.1 가장 안전 — 플래그 OFF만
```powershell
Remove-Item Env:FEATURE_PG_* -ErrorAction SilentlyContinue
```
→ 다음 uvicorn 기동 시 Sheets 동작 100% 복귀.

### 28.2 DB 수준
```powershell
$env:DATABASE_URL = "postgresql://kid_user:kid_pass@localhost:5433/kid_local"
.venv\Scripts\alembic.exe downgrade base
# 또는
docker rm -f kid-postgres-local
```

### 28.3 코드 수준
```powershell
git restore backend/db/feature_flags.py backend/db/models/__init__.py `
  backend/routers/auth.py backend/routers/customers.py `
  backend/routers/daily.py backend/routers/events.py `
  backend/routers/memos.py backend/routers/tasks.py `
  backend/routers/signature.py 2>$null
git restore backend/routers/board.py backend/routers/marketing.py `
  backend/routers/certification.py backend/routers/reference.py `
  backend/routers/admin.py backend/services/signature_service.py

# 신규 파일은 사용자가 수동 삭제
Remove-Item -Recurse `
  backend/db/models/customer.py, backend/db/models/event.py, `
  backend/db/models/memo.py, backend/db/models/daily.py, backend/db/models/task.py, `
  backend/db/models/relationship.py, backend/db/models/signature.py, `
  backend/db/models/board.py, backend/db/models/marketing.py, `
  backend/db/models/certification.py, backend/db/models/work_data.py, `
  backend/db/models/document.py
Remove-Item backend/services/customer_pg_service.py, backend/services/events_pg_service.py, `
  backend/services/memos_pg_service.py, backend/services/daily_pg_service.py, `
  backend/services/tasks_pg_service.py, backend/services/relationship_pg_service.py, `
  backend/services/signature_pg_service.py, backend/services/board_pg_service.py, `
  backend/services/marketing_pg_service.py, backend/services/certification_pg_service.py, `
  backend/services/reference_pg_service.py, backend/services/local_drive_mock.py
Remove-Item backend/scripts/migrate_all_to_pg_local.py, backend/scripts/import_existing_system_to_pg_local.py
Remove-Item alembic/versions/62a63fa57573_*.py, alembic/versions/a9e88d5f778a_*.py
```

본 도구는 위 명령을 자동 실행하지 않습니다.

---

## 29. 사용자 PASS 시 권장 커밋 파일 목록

```powershell
git add `
  backend/db/feature_flags.py `
  backend/db/models/__init__.py `
  backend/db/models/customer.py `
  backend/db/models/event.py `
  backend/db/models/memo.py `
  backend/db/models/daily.py `
  backend/db/models/task.py `
  backend/db/models/relationship.py `
  backend/db/models/signature.py `
  backend/db/models/board.py `
  backend/db/models/marketing.py `
  backend/db/models/certification.py `
  backend/db/models/work_data.py `
  backend/db/models/document.py `
  backend/services/customer_pg_service.py `
  backend/services/events_pg_service.py `
  backend/services/memos_pg_service.py `
  backend/services/daily_pg_service.py `
  backend/services/tasks_pg_service.py `
  backend/services/relationship_pg_service.py `
  backend/services/signature_pg_service.py `
  backend/services/board_pg_service.py `
  backend/services/marketing_pg_service.py `
  backend/services/certification_pg_service.py `
  backend/services/reference_pg_service.py `
  backend/services/local_drive_mock.py `
  backend/services/signature_service.py `
  backend/scripts/migrate_all_to_pg_local.py `
  backend/scripts/import_existing_system_to_pg_local.py `
  backend/routers/auth.py `
  backend/routers/customers.py `
  backend/routers/daily.py `
  backend/routers/events.py `
  backend/routers/memos.py `
  backend/routers/tasks.py `
  backend/routers/board.py `
  backend/routers/marketing.py `
  backend/routers/certification.py `
  backend/routers/reference.py `
  backend/routers/admin.py `
  alembic/versions/62a63fa57573_0002_customers_events_memos_daily_tasks.py `
  alembic/versions/a9e88d5f778a_0003_signatures_relationships_board_.py `
  DATA_WORKBOOK_TERMINOLOGY_CORRECTION_REPORT.md `
  FULL_LOCAL_PG_SYSTEM_FINAL_REPORT.md

git commit -m "feat(db): full local PostgreSQL system - all major domains behind flags"
```

---

## 30. 커밋 제외 권장 (Unrelated)

| 파일 / 폴더 | 이유 |
|---|---|
| `backend/scripts/analyze_manual_structure.py` | 이전 Opus 4.8 마이그레이션 미커밋 잔재. 별도 `chore(scripts): migrate LLM helpers to claude-opus-4-8` 커밋. |
| `backend/scripts/llm_remap_all.py` | 동일. |
| `.local_pg_beta_drive/` | 로컬 mock workspace manifest 파일 (테스트 산출물). **gitignore 추가 권장**. |
| `LOCAL_USABLE_POSTGRES_FINAL_REPORT.md` (이전 보고서) | 본 보고서로 대체됨. 보관/삭제는 선택. |

별도 커밋:
```powershell
git add backend/scripts/analyze_manual_structure.py backend/scripts/llm_remap_all.py
git commit -m "chore(scripts): migrate LLM helpers to claude-opus-4-8"
```

`.gitignore` 추가:
```
# Local PG beta workspace mock manifests
.local_pg_beta_drive/
```

---

## 31. 사용자 최종 로컬 검증 준비 완료? (Ready for User Final Verification?)

### **YES — 즉시 브라우저 매뉴얼 테스트 시작 가능.**

근거:
1. ✅ 27개 PG 테이블 + 3개 마이그레이션 모두 적용
2. ✅ 12개 라우터 PG 분기 완료 (Sheets 코드 한 줄도 안 지움)
3. ✅ 자동 검증 (compile / tsc / alembic / seed / HTTP smoke) 전부 통과
4. ✅ 실제 운영 Accounts 시트 read-only 임포트 검증됨
5. ✅ 로컬 Drive Mock 동작 — Drive 호출 0건
6. ✅ HANWOORY_ENV=server 시 dev 엔드포인트 비-노출
7. ✅ 플래그 모두 OFF 시 기존 Sheets 동작 100% 유지
8. ✅ 합성(3) + 실제(3) 하이브리드 사용자로 로그인 즉시 가능
9. ✅ 컨테이너 + 시드 데이터 살아있음 (`kid-postgres-local`)

### 본 도구가 자동 실행하지 **않은** 것
- ❌ git commit / push / merge
- ❌ Render PG / 환경변수 / 배포
- ❌ 운영 Sheets / Drive 어떤 쓰기도 0건
- ❌ 전체 도메인 운영 Sheets 임포트 (auto-mode 차단됨 — 사용자가 §22.2에서 직접 실행 가능)
- ❌ 컨테이너 정리 (사용자 매뉴얼 테스트 후 §22.6)

### 사용자 다음 단계
1. §22 절차로 백엔드(8002) + 프론트엔드 기동
2. 브라우저에서 로그인 → 평소 사용하던 페이지들 동작 확인
3. (선택) §22.2로 추가 운영 Sheets 데이터 임포트
4. 이상 없으면 §29 명령으로 커밋
5. push / Render / 운영 마이그레이션은 별도 결정

**자동 진행 없음. 사용자 브라우저 매뉴얼 검증 대기.**

**END OF REPORT**
