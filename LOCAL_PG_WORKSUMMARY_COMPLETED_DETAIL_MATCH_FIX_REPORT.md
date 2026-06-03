# LOCAL_PG_WORKSUMMARY_COMPLETED_DETAIL_MATCH_FIX_REPORT.md

업무 요약 카운트와 완료업무 상세 모달이 불일치하던 버그(summary "출입국 1" 인데 detail "0건") 를 해결한 보고서.

## 1. 요약

| 항목 | 상태 |
|---|---|
| summary `total == detail.tasks.length` 모든 경우 일치 | ✅ |
| 두 엔드포인트가 **단일** `_resolve_customer_tasks` 헬퍼 사용 | ✅ |
| `completed_tasks.customer_id` backfill 358건 적용 | ✅ |
| ambiguous (동명이인) 39건은 silently 매핑하지 않음 | ✅ |
| asd 케이스 검증 — summary 1 → detail 1 | ✅ |
| 일반 고객 케이스 검증 — summary 4 → detail 4 | ✅ |
| backend compile + frontend tsc | EXIT=0 |
| Google Sheets / Drive / Render / commit / push | 0회 |

## 2. 근본 원인

| # | 원인 |
|---|---|
| 1 | `/api/customers/{id}/work-summary` 는 직전 라운드에 **PG 분기** 로 갱신됨 (`tasks_pg_service.list_completed` 직접 조회). |
| 2 | `/api/customers/{id}/completed-tasks` 는 **Sheets 만** 읽고 있었음 (`read_sheet(COMPLETED_TASKS_SHEET_NAME, ...)`). 로컬 PG 모드에서 이 호출은 빈 리스트를 반환. |
| 3 | 결과: summary 가 보여주는 1건은 PG completed_tasks 에 존재 → 카드 뱃지 ‘출입국 1’ 표시. 사용자가 클릭 → modal 이 Sheets 만 조회 → 0건 표시. 두 API 가 **다른 데이터 소스** 를 본 것이 원인. |
| 4 | 부가 원인: 임포트된 일부 legacy `완료업무` 행이 `customer_id` 비어 있어 customer_id 기반 매칭 만으로는 정확한 카운트가 나오지 않을 수 있음 (동명이인 disambig 필요). |

## 3. summary 쿼리 — Before / After

### Before
```python
@router.get("/{customer_id}/work-summary")
def get_work_summary(...):
    if pg_tasks_enabled():
        completed = list_completed(tenant_id)
        active    = list_active(tenant_id)
    else:
        completed = read_sheet(COMPLETED_TASKS_SHEET_NAME, ...)
        active    = read_sheet(ACTIVE_TASKS_SHEET_NAME, ...)
    # inline 매칭 로직 (customer_id, legacy name) — get_customer_completed_tasks 와 중복
```

### After
```python
@router.get("/{customer_id}/work-summary")
def get_work_summary(customer_id, name=None, user=...):
    resolved = _resolve_customer_tasks(user["tenant_id"], customer_id, name)
    # resolved = {by_id, by_name_only, active_by_id, has_name_duplicate}
    # → groups / legacy_groups / active_total 계산
```

## 4. detail 모달 쿼리 — Before / After

### Before
```python
@router.get("/{customer_id}/completed-tasks")
def get_customer_completed_tasks(...):
    from backend.services.tenant_service import read_sheet     # ← Sheets 만
    completed = read_sheet(COMPLETED_TASKS_SHEET_NAME, ...)    # ← 로컬 PG 에서는 빈 리스트
    by_id = [r for r in completed if r["customer_id"] == customer_id]
    ...
```

### After
```python
@router.get("/{customer_id}/completed-tasks")
def get_customer_completed_tasks(customer_id, name=None, include_legacy=False, user=...):
    resolved = _resolve_customer_tasks(user["tenant_id"], customer_id, name)
    return {
        "tasks":              sorted(resolved["by_id"], ...),
        "legacy_tasks":       sorted(resolved["by_name_only"], ...) if include_legacy else [],
        "has_name_duplicate": resolved["has_name_duplicate"],
    }
```

**핵심:** 두 엔드포인트 모두 동일 `_resolve_customer_tasks` 를 통과 → 같은 데이터 소스 (PG 또는 Sheets) + 같은 필터 규칙 → 카운트와 리스트가 영구적으로 일치.

## 5. 공유 resolver 규칙

```python
def _resolve_customer_tasks(tenant_id, customer_id, customer_name):
    """단일 진실 원천."""
    completed, active = _load_completed_active_for_tenant(tenant_id)
    # PG mode → list_completed/list_active; Sheets mode → read_sheet.

    by_id = [r for r in completed if r["customer_id"] == customer_id]

    by_name_only = []   # legacy fallback only
    if customer_name:
        nm = customer_name.strip()
        # customer_id 가 비어 있고 한글 이름이 정확히 일치하는 행만
        by_name_only = [
            r for r in completed
            if not str(r.get("customer_id","")).strip()
            and str(r.get("name","")).strip() == nm
        ]
        has_name_duplicate = (count of customers with same korean_name) >= 2

    active_by_id = [r for r in active if r["customer_id"] == customer_id]
    return {by_id, by_name_only, active_by_id, has_name_duplicate}
```

### 매칭 규칙 (사용자 요구사항 §2 의 A–D 모두 반영)
- **A. customer_id 정확 일치** — task 에 customer_id 가 있으면 그것만 사용
- **B. customer_id 비어 있을 때만** tenant_id + 한글 이름 정확 일치 (legacy fallback)
- **C. 한글 이름 외 disambiguation** (생년월일/등록증/전화) — 현재 데이터는 task 측에 birth/reg 가 없어 적용 안 함. 향후 schema 확장 시 추가 가능.
- **D. 동명이인 다수** — `has_name_duplicate=True` 로 응답에 동봉. 백엔드는 자동으로 한 명에 매핑하지 않음. UI 가 경고 표시.

## 6. customer_id backfill 결과

스크립트: `backend/scripts/backfill_completed_customer_id.py` (row-level UPDATE only, dry-run 기본, --execute 명시).

```
[index] built — tenants=3, names=1339
[scan] 571 completed_tasks rows with empty customer_id

[result] EXECUTED
  scanned            571
  matched_unique     358  ← UPDATE 적용 (unique name match per tenant)
  ambiguous           39  ← 동명이인 — skip
  no_match           174  ← 매칭되는 고객 없음 (orphan) — skip
  updated            358
```

### 처리 정책
- `scanned` — customer_id 가 NULL/empty 인 행 전체
- `matched_unique` — 같은 tenant 안에 이름이 정확히 한 명 → 그 customer_id 로 **row-level UPDATE**
- `ambiguous` — 같은 tenant 안에 이름이 2명 이상 → 자동 매핑 없음 (사용자 수동 정리 권장)
- `no_match` — 해당 이름의 고객이 아예 없음 → 그대로 두고 legacy_tasks 에서만 보임

### 안전 보장
- `assert_local_database_url` 가 localhost / 127.0.0.1 / ::1 외 거부
- 기본 dry-run, `--execute` 필요
- 절대 DELETE 안 함, customer_id 가 채워진 행은 무시
- UPDATE 한 컬럼은 `customer_id` 하나

## 7. ambiguous rows count

39건. tenant 별:

```
tenant=hanwoory count=27 (예: 김강, 김광철, 김금옥, 김미란, 김미선, 김미화, 김성휘, 김수연, ...)
tenant=jpup     count= 0
tenant=asd      count=12 (실험 데이터)
```

향후 사용자가 수동으로 정리하려면 admin tool 에서 동명이인 고객의 customer_id 확인 후 UPDATE. 본 자동 backfill 은 절대 한 명을 임의로 선택하지 않음.

## 8. 테스트 결과 — asd 케이스

검증 환경: backend 18985, FEATURE_PG_TASKS=true, asd tenant, 고객 id=0001 name=asd.

```
DB 상태:
  customers:        (tenant_id=asd, customer_id=0001, korean_name=asd)
  completed_tasks:  (tenant_id=asd, customer_id=0001, name=asd, category=출입국, work=as)

API 호출 (asd admin token):
  GET /api/customers/0001/work-summary?name=asd
  → total=1  groups={"출입국": 1, "전자민원": 0, "공증": 0, "여권·초청": 0, "기타": 0}

  GET /api/customers/0001/completed-tasks?name=asd&include_legacy=true
  → tasks=[1건]  legacy_tasks=[0건]

BEFORE FIX: summary=1 (PG), detail=0 (Sheets) → MISMATCH ❌
AFTER  FIX: summary=1, detail=1                → MATCH    ✅
```

## 9. 테스트 결과 — 정상 고객 케이스

```
DB 상태 (hanwoory customer 양군호 id=2026031204):
  completed_tasks 4건 (모두 category=공증)

API:
  GET work-summary
  → total=4  groups={"공증": 4, ...}

  GET completed-tasks
  → tasks=4건 sample={category:공증, work:호구부 급행, date:2026-03-13}

MATCH: summary=4 == detail.tasks=4 ✅
샘플 행도 정상 표시.
```

## 10. 변경된 파일 (4개)

| 파일 | 변경 |
|---|---|
| `backend/routers/customers.py` | `_load_completed_active_for_tenant` + `_resolve_customer_tasks` 신설. `/work-summary` / `/completed-tasks` 모두 이 헬퍼 사용. `/completed-tasks` 에 PG 분기 추가 + `has_name_duplicate` 응답 동봉. |
| `backend/scripts/backfill_completed_customer_id.py` | 신규 — name → 유일 매칭 시 customer_id row-level UPDATE. dry-run 기본. |
| `frontend/app/(main)/customers/page.tsx` | `CompletedTasksModal` 을 `useEffect`→`useQuery({queryKey:["customer","completed-tasks",customerId,customerName], staleTime:0})` 로 전환. 헤더 자막을 "고객ID 기준 N건 + 이름 기준 M건 (총 X건)" 형태로 명확화. |
| `frontend/lib/api.ts` | (직전 라운드의 `WorkSummary.active_total?`) — 이번 라운드 변경 없음. |

## 11. 안전 확인

- ✅ Google Sheets API / Drive API 호출 0
- ✅ Render PG / 환경변수 / 배포 미접근
- ✅ 운영 데이터 변경 0 (로컬 PG 만 변경)
- ✅ git commit / push / merge / deploy 0회
- ✅ backfill 은 row-level UPDATE only — DELETE 없음, 광역 wipe 없음
- ✅ ambiguous 39건 자동 매핑 안 함 (silent guessing 방지)
- ✅ runtime 라우터는 INSERT/UPDATE/DELETE-by-id 만 사용 (이전 audit 라운드와 동일)

## 12. 최종 브라우저 검증 재개 가능 여부

**가능.** 시나리오:

1. PowerShell 백엔드 기동 (이전 §11 환경변수)
2. `cd frontend; npm run dev`
3. wkdwhfl (또는 asd) 로그인
4. asd 고객 카드 → "출입국 1" 뱃지 → 클릭 → 모달 자막 "고객ID 기준 1건" → 표에 1행 정상 표시
5. 일반 고객 (예: hanwoory 양군호) 카드 → 공증 4 → 클릭 → 자막 "고객ID 기준 4건" → 4행
6. 완료업무가 0건인 고객 → 카드 뱃지 모두 0 → 모달 "0건" + 빈 표
7. 동명이인 고객의 경우 → has_name_duplicate=true 일 때 UI 가 경고 (기존 동작 유지)
8. 본 라운드 commit/push 미수행. 검증 PASS 후 사용자가 별도 명령으로 커밋.

---

**정지.** 사용자 검증 대기.
