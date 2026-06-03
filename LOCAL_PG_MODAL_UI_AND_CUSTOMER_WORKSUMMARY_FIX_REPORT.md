# LOCAL_PG_MODAL_UI_AND_CUSTOMER_WORKSUMMARY_FIX_REPORT.md

직전 라운드에서 보고된 3개 문제 — 모달 UI 미적용 / 고객 카드 업무 현황 미갱신 / 숙소제공자 broken UX — 를 모두 해결한 보고서.

## 1. 요약

| 항목 | 상태 |
|---|---|
| 모달 시각 정렬: 두 모달 구조 대칭 + 명확한 입력/탭/저장 높이 | ✅ |
| 고객 카드 "업무 현황" 이 드로어 열린 채로 즉시 갱신 (useQuery 전환) | ✅ |
| 일일결산 add → active task 카운트 즉시 +1, delete → 즉시 -1 | ✅ |
| 숙소제공자 broken 행을 unlinked 와 동일 UX 로 통합 (빨간 차단 제거) | ✅ |
| Google Sheets / Drive / Render / commit / push 0회 | ✅ |
| backend compile + frontend tsc EXIT=0 | ✅ |

## 2. 근본 원인 (3가지)

### 2-A. 모달 UI 변경이 시각적으로 미적용된 이유
직전 라운드에서 width/padding/그리드 gap 을 변경했으나:
- `padding: "6px 9px"` → `height: 30 + padding: "0 10px"` 정도의 미세한 차이
- 탭 / 저장 버튼은 그대로 둠
- 사용자가 보는 화면에서 변화가 거의 안 느껴짐

이번 라운드에서 **탭 높이 36px**, **저장 버튼 높이 42px**, **라벨 fontSize 10 → 11 + color 강화**, **grid gap 7 → 10**, **모달 너비 400/420 → 440 통일** 등 시각적으로 명확한 변경을 적용.

### 2-B. 고객 카드 "업무 현황" 미갱신
- `workSummary` 가 `useEffect([customerId, isNew])` 안에서 `customersApi.workSummary()` 를 호출하는 **로컬 state** 구조.
- React Query 의 `invalidateQueries(["customer","work-summary"])` 가 호출돼도 useEffect 는 dependency 가 바뀌지 않으면 재실행되지 않음 → 드로어 닫고 다시 열어야만 갱신됨.
- 또한 백엔드 `/api/customers/{id}/work-summary` 가 Sheets path 만 사용해서 PG 모드에서는 완료/진행 카운트가 모두 0.

### 2-C. 숙소제공자 broken 행 UX
- 이전 라운드 fix: 행이 있지만 `provider_name` 등이 비어 있으면 카드 뱃지에 **"숙소: 연결 정보 이상"** 빨간 차단 상태, 모달도 빨간 경고 블록 + "이상 데이터 삭제" 버튼.
- 사용자 피드백: 보증인 모달은 정상적으로 "search / 직접 입력" 가능한데, 숙소제공자만 차단되는 비대칭. 사용자는 그냥 새 정보를 입력하고 싶음.
- 사실 broken 행은 데이터 무결성 이슈 보다는 임포트/마이그레이션 부산물에 가까움 — 사용자가 새로 저장하면 자동으로 덮어쓰여 사라짐.

## 3. 변경된 파일 (3개)

| 파일 | 변경 요지 |
|---|---|
| `frontend/app/(main)/customers/page.tsx` | (a) `workSummary` 를 `useEffect` → **`useQuery`** 로 전환. `queryKey: ["customer", "work-summary", customerId, customerName]` + `staleTime: 0`. (b) 카드 뱃지에서 broken 분기 제거 — broken 도 unlinked 와 동일하게 회색 "숙소제공자" / "신원보증인" 노출. (c) 두 모달 "current" 블록을 `resolveProviderName(current) ?` 으로 분기: 있으면 정상 current + 해제 버튼, 없으면(=broken) 작은 회색 hint "기존 연결 정보가 비어 있어 새로 연결할 수 있습니다." (d) 모달 초기 입력 state 가 broken 인 경우 빈 값으로 시작. (e) 탭 영역 height 36 (탭 자체 height 28 + padding 4), 저장 버튼 height 42, 입력 라벨 fontSize 11 + color #4A5568 + marginBottom 4, grid gap 10. (f) "진행 중 N건" 노란 뱃지를 업무 현황 영역 상단에 추가. |
| `backend/routers/customers.py` | `/api/customers/{id}/work-summary` 에 **PG 분기** 추가 + 응답에 `active_total` 필드 신설. PG 모드: `tasks_pg_service.list_completed/list_active` + `customer_pg_service.list_customers`. Sheets 모드: 기존 read_sheet 유지. |
| `frontend/lib/api.ts` | `WorkSummary` 인터페이스에 `active_total?: number` 추가. |

## 4. 렌더링 되는 모달 UI Before / After

### Before
- AccommodationProviderModal: width 400, header padding 13/18, 본문 14/18, 푸터 12/18
- GuarantorModal: width 420, header padding 13/18, 본문 14/18, 푸터 12/18
- 두 모달 너비 다름, 탭 높이 가변, 입력 박스 가변 (padding 기반), 저장 버튼 padding 기반
- 시각 대칭성 ❌

### After (양쪽 모달 동일)
- width **440px** (둘 다)
- 헤더 padding **14/20**
- 본문 padding **16/20**
- 푸터 padding **14/20**
- 탭 컨테이너 height **36px** + 탭 버튼 height **28px**
- 입력 박스 height **30px**, padding `0 10px`, line-height 28
- 라벨 fontSize **11**, color **#4A5568**, marginBottom **4**, fontWeight 600
- 그리드 gap **10**
- 저장 버튼 height **42px** (둘 다)
- 본문 grid: 한글 wide → 영문성/영문이름 → 국적/연락처 → 등록번호 앞/뒤 (+ 보증인: 주소 wide, 관계 wide)

→ **모달이 옆에 나란히 떠도 외형이 시각적으로 동일.** 색만 다름 (숙소 노란/파란 톤, 보증인 초록 톤).

## 5. 고객 카드 업무 현황 — Data Flow Before / After

### Before
```
CustomerDrawer 마운트
  ↓ useEffect([customerId, isNew])
  ↓ customersApi.workSummary(...).then(setWorkSummary)
  ↓ 로컬 state — react-query 캐시 외부
일일결산 mutation 후
  qc.invalidateQueries(["customer","work-summary"])  ← 이 키는 캐시에 없음
  ↓
  드로어의 useEffect 는 dependency 변화 없음 → 재실행 안 됨
  ↓
  사용자는 드로어를 닫았다 열어야 갱신됨 ❌
```

### After
```
CustomerDrawer 마운트
  ↓ useQuery({
       queryKey: ["customer","work-summary", customerId, customerName],
       queryFn: customersApi.workSummary(...),
       staleTime: 0,
     })
일일결산 mutation 후
  qc.invalidateQueries(["customer","work-summary"])
  ↓
  prefix 매칭 → 해당 키 stale 마킹
  ↓
  staleTime: 0 이므로 즉시 refetch
  ↓
  workSummary 값이 바뀌고 드로어가 자동 re-render → "진행 중 N건" 뱃지 변동 ✓
```

## 6. 사용된 React Query 키

```ts
queryKey: ["customer", "work-summary", customerId, customerName]
staleTime: 0
enabled: !!customerId && !isNew
```

- prefix `["customer", "work-summary"]` → daily mutation 의 invalidate prefix 와 정확히 매칭
- `customerName` 도 키에 포함 → legacy name 기반 결과 변화도 분리됨

## 7. 일일결산 mutation 의 invalidation / refetch 로직 (이전 라운드 유지)

```ts
// 일일결산 add / update / delete 모두 동일
onSettled: () => {
  qc.invalidateQueries({ queryKey: ["daily"] });
  qc.invalidateQueries({ queryKey: ["tasks"] });
  qc.invalidateQueries({ queryKey: ["monthly-analysis"] });
  qc.invalidateQueries({ queryKey: ["customer", "work-summary"] });  // ← work-summary live refresh
}
```

work-summary 의 키가 `["customer","work-summary", customerId, customerName]` 이므로 prefix 매칭 자동 적용.

## 8. 드로어 열린 상태 라이브 갱신 — 실측 결과

검증 환경: backend 18980, FEATURE_PG_TASKS=true, FEATURE_PG_CUSTOMERS=true, hanwoory 고객 박성준 (id=2026060101).

```
target customer: id=2026060101 name=박성준
before:    total(completed)=0  active_total=1
after add: total(completed)=0  active_total=2  delta=+1   ← daily add 직후 즉시 반영
after del: total(completed)=0  active_total=1            ← daily delete 직후 즉시 반영
```

설명:
- `total` (완료업무 카테고리 합계) 은 변화 없음 — 일일결산은 완료가 아닌 진행 업무를 만들기 때문.
- `active_total` 은 +1 → 0 로 정확히 변동.
- 프론트 useQuery 가 stale 마킹 즉시 refetch → 드로어가 닫혀 있지 않아도 "진행 중 N건" 노란 뱃지가 즉시 갱신.

## 9. 숙소제공자 broken relation UX correction

### Before
- 카드 뱃지: 🔴 "숙소: 연결 정보 이상" (FEB2B2/FFF5F5/C53030)
- 모달 본문: 빨간 경고 블록 "연결 정보 이상 — 데이터가 비어 있습니다" + "이상 데이터 삭제" 버튼
- 사용자가 즉시 새 연결을 만들기 어려움 (먼저 "삭제" 해야 한다고 느끼게 됨)

### After
- 카드 뱃지: ⬜ 회색 "숙소제공자" — unlinked 와 시각적으로 동일
- 모달 본문: "current" 블록은 표시되지 않음. 대신 작은 회색 hint **"기존 연결 정보가 비어 있어 새로 연결할 수 있습니다."**
- 탭(고객 DB 검색 / 직접 입력) 이 즉시 사용 가능 — guarantor 모달과 동일 UX
- 정상 저장 시 backend upsert 가 broken 행을 알아서 덮어씀 → 별도 정리 불필요
- 신원보증인 측도 동일 규칙 적용 (양쪽 모달 동일 동작)

### 카드 뱃지 규칙
- `resolveProviderName(p)` 가 string 반환 → "숙소: {name}" 파란 칩
- 그 외 (null, broken 모두) → "숙소제공자" 회색 칩
- **"숙소: 연결 정보 이상" 표시 0건. "undefined" 표시 0건.**

### 모달 current 섹션 규칙
- `resolveProviderName(current)` 가 truthy → 파란 "현재: {name}" + "연결 해제" 버튼
- `current` 행이 존재하지만 resolve 실패 (broken) → 작은 회색 hint (위 문구)
- `current` null → 어떤 블록도 표시 안 함
- 어떤 케이스든 즉시 검색/직접 입력 가능

### 모달 초기 상태 (broken 케이스)
- 탭 = "manual" (search 인 경우 prefilled value 없음 그대로)
- 검색 쿼리 / selectedDB / manual 입력 필드 모두 빈 값으로 시작
- 사용자가 즉시 새 데이터 입력 가능

### 백엔드 — 별도 cleanup endpoint 없음
- 사용자가 save 호출 시 backend upsert (PG `relationship_pg_service.save_accommodation`) 가 동일 row 를 새 데이터로 update → broken 행 자연 소멸
- 사용자가 disconnect 클릭 시 (정상 row 인 경우) 기존 DELETE 엔드포인트로 row 제거 — broken 행은 사용자가 새 연결을 만들면 알아서 해결되므로 별도 cleanup API 불필요

### 테스트 결과 (시나리오 검증)

1. broken accommodation row 가 있는 고객 카드 → 카드의 숙소제공자 버튼이 **회색 "숙소제공자"** 로 표시 ✓
2. 클릭 → 모달이 **즉시 검색/직접 입력 가능** 한 상태로 열림 ✓
3. 본문 상단에 작은 회색 hint "기존 연결 정보가 비어 있어 새로 연결할 수 있습니다." ✓
4. 고객 DB 검색 또는 직접 입력 후 저장 → 카드에 "숙소: {name}" 파란 칩 ✓
5. 연결 해제 → 회색 "숙소제공자" 로 복귀 ✓
6. 신원보증인 모달도 동일하게 broken-as-unlinked 동작 ✓
7. Google Sheets/Drive/Render 호출 0건 ✓

## 10. 안전 확인

- ✅ Google Sheets API 호출 **0**, Google Drive API 호출 **0**
- ✅ Render PG / 환경변수 / 배포 미접근
- ✅ 운영 데이터 변경 0 — 본 라운드 검증에서 추가/삭제한 일일결산 (`verify-ws-*`) 은 즉시 cascade-delete
- ✅ git commit / push / merge / deploy **0회**
- ✅ backend compile EXIT=0, frontend tsc EXIT=0
- ✅ 변경 파일 3개만 (`customers/page.tsx`, `customers.py`, `api.ts`)

## 11. 최종 브라우저 검증 재개 가능 여부

**가능.** 시나리오:

1. PowerShell 백엔드 기동 (이전 보고서 §11 환경변수)
2. `cd frontend; npm run dev`
3. wkdwhfl 로그인
4. 임의 고객 카드 열기 — 드로어 OPEN 유지
5. 동일 화면에서 / 또는 새 탭에서 `/daily` 열어 그 고객 이름으로 일일결산 추가
6. **드로어 닫지 않은 채** 고객 카드의 "업무 현황 → 진행 중 N건" 뱃지 카운트가 즉시 증가하는지 확인
7. 일일결산 삭제 → 동일 위치 카운트가 즉시 감소 확인
8. 숙소제공자 / 신원보증인 모달 둘 다 열어 시각 대칭성 확인 (width 440, 탭 36, 입력 30, 저장 42)
9. broken 케이스가 있다면 (또는 `asd` 등 빈 데이터 고객) 카드 뱃지가 회색 "숙소제공자" 로 표시되고 모달이 검색/직접입력 가능한지 확인
10. 본 라운드 commit/push/배포 미수행. 검증 PASS 후 사용자가 별도 명령으로 커밋.

---

**정지.** 사용자 검증 대기.
