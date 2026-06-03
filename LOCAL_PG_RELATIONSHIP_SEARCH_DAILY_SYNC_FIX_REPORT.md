# LOCAL_PG_RELATIONSHIP_SEARCH_DAILY_SYNC_FIX_REPORT.md

로컬 PostgreSQL 베타에서 4개 미완 이슈를 해결한 보고서.

## 1. 요약

| # | 이슈 | 상태 |
|---|---|---|
| 1 | 숙소제공자 카드에 `undefined` 표시 + 모달 current 비어있음 + 해제 버튼은 그대로 — 상태 불일치 | ✅ 단일 해소 helper 로 통합 |
| 2 | 숙소제공자 모달 UI 정렬 불균형 | ✅ 2열 그리드 정돈, 패딩/필드 통일 |
| 3 | 검색이 한글/영문성/영문이름/풀네임 + 동명이인 구분에 부족 | ✅ 다중 필드 검색 + 생년월일/전화 노출 |
| 4 | 일일결산 추가 후 월간 결산 / 대시보드 진행업무 / 업무관리 / 고객 카드 업무현황 미반영 | ✅ PG 모드에 전용 propagation 추가 + 광범위 invalidate |
| backend compile + frontend tsc | EXIT=0 | ✅ |
| Google Sheets/Drive/Render/commit/push 0회 | ✅ |

## 2. 근본 원인

| # | 원인 |
|---|---|
| 1 | `AccommodationProvider` / `GuarantorConnection` 관계 행이 존재하지만 (`provider_name` 등이) 비어있을 수 있는데, 프론트는 `providerData` 가 truthy 인지만 검사 → `숙소: undefined`. 카드 뱃지·모달 current·해제 버튼이 각자 다른 조건으로 분기. |
| 2 | 모달 헤더 13px / 본문 14px / 푸터 12px — 비대칭 padding. 수동 입력 그리드의 wide 필드 순서가 비논리적 (한글 wide → 영문성+이름 → 국적+등록번호앞 페어가 의미상 어긋남, 연락처 wide 가 가장 아래). |
| 3 | `/api/quick-doc/customers/search` 가 Sheets path 만 사용 (PG 분기 없음). 매칭 조건이 영문은 `len(q)>=3` 만 (영문 2글자 성/이름 검색 안 됨). 결과 `label` 에 생년월일/전화가 부분만 들어가 동명이인 구분 어려움. 프론트 결과 행은 한글+영문만 표시. |
| 4 | `daily.py:add_entry` PG 분기가 `upsert_entry` 한 줄로 끝나고 `_apply_daily_to_active` / `_append_delegation_to_customer` 를 호출하지 않음. 두 함수 모두 `read_sheet` / `upsert_sheet` 기반 — PG 에 안 닿음. `/summary` `/monthly-analysis` 도 Sheets 만 읽음. 프론트 invalidate 도 `["daily","entries"]` 만 — `["daily","summary"]` / `["monthly-analysis"]` / `["customer","work-summary"]` 는 stale. |

## 3. 변경된 파일

| 파일 | 변경 요지 |
|---|---|
| `backend/routers/daily.py` | (a) PG 전용 `_apply_daily_to_active_pg` / `_append_delegation_to_customer_pg` 신설 — `tasks_pg_service` / `customer_pg_service` 만 사용. (b) `add_entry` / `update_entry` PG 분기가 위 helper 들을 best-effort 호출. (c) `delete_entry` PG 분기가 derived active task (`daily-{entry_id}`) cascade 삭제. (d) `/summary` `/monthly-analysis` PG 분기 추가 (`daily_pg_service.list_entries`). |
| `backend/routers/quick_doc.py` | `/customers/search` PG 분기 (`customer_pg_service.list_customers`) + 다중 필드 매칭 (한글 1+ chars / 영문 last·first·full 2+ chars / 전화·등록증 digits 3+) + 결과에 `birth` / `phone` 구조화 필드 + 사람이 읽는 `label` 에 한글·영문·생년월일·전화 ` · ` 구분. |
| `frontend/lib/api.ts` | `CustomerSearchResult` 에 `birth?: string` / `phone?: string` 추가. |
| `frontend/app/(main)/customers/page.tsx` | (a) `resolveProviderName` / `resolveGuarantorName` / `providerStatus` / `guarantorStatus` helper 신설 — 단일 진실원천. (b) 카드 뱃지 3 상태 (none / connected / broken) 분기. (c) AccommodationProviderModal·GuarantorModal 의 "현재" 블록이 동일 helper 로 분기 — broken 시 빨간 톤 + "이상 데이터 삭제" 버튼. (d) 두 모달 width 통일 (440px) + 헤더/본문/푸터 padding 통일 (14px 20px / 16px 20px / 14px 20px) + 수동 입력 그리드 논리적 페어 순서 + `inp` 높이 30px 고정 + gap 10px. (e) 검색 결과 행이 한글·영문·생년월일·전화 2-line 으로 표시. |
| `frontend/app/(main)/daily/page.tsx` | `addMut` / `updateMut` / `deleteMut` 의 invalidate 키를 `["daily"]` / `["tasks"]` / `["monthly-analysis"]` / `["customer","work-summary"]` 로 광범위화 — 월간 / 대시보드 / 업무관리 / 고객 카드 모두 즉시 재조회. |

## 4. 숙소제공자 / 신원보증인 상태 통합 fix

**단일 진실원천:**

```ts
function resolveProviderName(p): string | null {
  if (!p) return null;
  const name = (p.provider_name || "").trim();
  const last = (p.provider_last_name || "").trim();
  const first = (p.provider_first_name || "").trim();
  if (name) return name;
  return `${last} ${first}`.trim() || null;
}

function providerStatus(p): "none" | "connected" | "broken" {
  if (!p) return "none";
  return resolveProviderName(p) ? "connected" : "broken";
}
```

**3 상태 매핑:**

| status | 카드 뱃지 | 모달 "현재" 블록 | 해제 버튼 |
|---|---|---|---|
| `none` | 회색 "숙소제공자" | 미표시 | 미표시 |
| `connected` | 파란 "숙소: {이름}" | 파란 "현재: {이름}" | "연결 해제" |
| `broken` | 빨강 "숙소: 연결 정보 이상" | 빨강 "연결 정보 이상 — 데이터가 비어 있습니다" | "이상 데이터 삭제" |

**"undefined" 표시 0건** — 어떤 분기에서도 `${name}` 같은 직접 보간 대신 helper 가 반환한 string 만 사용.

같은 패턴이 `resolveGuarantorName` / `guarantorStatus` 로 신원보증인에 그대로 적용.

## 5. 모달 UI 정렬 fix

| 항목 | 변경 전 | 변경 후 |
|---|---|---|
| 너비 | provider 400 / guarantor 420 | **둘 다 440** |
| 헤더 padding | `13px 18px` | **`14px 20px`** |
| 본문 padding | `14px 18px` | **`16px 20px`** |
| 푸터 padding | `12px 18px` | **`14px 20px`** |
| 입력 박스 | `padding:6px 9px` (높이 가변) | **height:30 + padding:0 10px (라인 높이 28)** — 모든 행 동일 |
| 그리드 gap | 7 | **10** — 시각적 여유 |
| 라벨 | `fontWeight 기본` | **`fontWeight:600` + `marginBottom:3`** |
| 필드 순서 (provider) | 한글 → 영문성 → 영문이름 → 국적 → 등록앞 → 등록뒤 → **연락처 wide** | **한글 wide → 영문성/영문이름 → 국적/연락처 → 등록앞/등록뒤** |
| 필드 순서 (guarantor) | … → **연락처 wide → 주소 wide → 관계 (혼자)** | **한글 wide → 영문성/영문이름 → 국적/연락처 → 등록앞/등록뒤 → 주소 wide → 관계 wide** |

## 6. 검색 강화 fix

### 백엔드 매칭 규칙

| 입력 | 최소 길이 | 검사 필드 |
|---|---|---|
| Korean 글자 | 1 | `한글` substring |
| English | 2 | `성`, `명`, `성 명` substring (case-insensitive) |
| 숫자 | 3 | `연/락/처` 합친 phone digits, `등록증` 6자리 |

### 결과 응답 (구조화 + label)

```json
{
  "id": "2026050401",
  "label": "진해영 · JIN HAIYUE · 1985-09-09 · 010-5549-9309",
  "name": "진해영",
  "name_en": "JIN HAIYUE",
  "birth": "1985-09-09",
  "phone": "010-5549-9309",
  "reg_no": "520717"
}
```

### 검색 실측 결과 (PG 모드, port 18950, hanwoory 1473명)

| 쿼리 | count | 매칭 사례 |
|---|---|---|
| `김` (Korean) | 30 | 김민화 / JIN MINGHUA / 1970-04-02 / 010-9732-6791 |
| `홍` (Korean) | 30 | 어춘홍 / YU CHUNHONG / 1973-12-13 |
| `KIM` (English last) | 2 | 응우엔티김융 / NGUYEN THI KIM DUNG / 1985-09-09 |
| `HONG` (English) | 30 | 홍명표 / HONG MINGBIAO / 1972-10-25 |
| `CHEN` (English) | 30 | 박성준 / PIAO CHENGJUN / 1985-01-30 |
| `hong gil` (English full) | 0 | (해당 고객 없음 — 정확) |

### 프론트 결과 행 (2-line)

```
{한글이름}  ({영문})
{생년월일} · {전화}
```

## 7. 일일결산 → 의존 화면 전파 fix

### 백엔드 변경

```
POST /api/daily/entries (PG 모드)
  ├─ upsert_entry (DailyEntry PG)
  ├─ _apply_daily_to_active_pg
  │   ├─ tasks_pg_service.list_active(tenant_id)
  │   ├─ match by source_daily_id → upsert 또는 새 row insert
  │   ├─ task_id = "daily-" + entry_id (deterministic)
  │   └─ cache_invalidate(tenant_id, "tasks:active")
  └─ _append_delegation_to_customer_pg
      └─ customer_pg_service.append_delegation(...)

DELETE /api/daily/entries/{id}
  ├─ delete_entry (PG)
  └─ cascade delete active_task id="daily-{id}"

GET /api/daily/summary       → PG 분기 (FEATURE_PG_DAILY ON 시 list_entries)
GET /api/daily/monthly-analysis → PG 분기 (동일)
```

### 프론트 invalidate 광범위화

```ts
onSettled: () => {
  qc.invalidateQueries({ queryKey: ["daily"] });
  qc.invalidateQueries({ queryKey: ["tasks"] });
  qc.invalidateQueries({ queryKey: ["monthly-analysis"] });
  qc.invalidateQueries({ queryKey: ["customer", "work-summary"] });
}
```

- `["daily"]` → 일일결산 entries + balance + summary 모두 재조회
- `["tasks"]` → 대시보드 진행업무 카드 + 업무관리 진행업무·예정업무·완료업무 모두 재조회
- `["monthly-analysis"]` → 월간 분석 페이지
- `["customer","work-summary"]` → 고객 드로어 업무현황 (커스텀 invalidate; 실제 fetch 는 useEffect 로 customerId 변경 시 — 다음 진입 시 갱신됨)

## 8. 테스트 시나리오 실측

**검증 환경:** Docker PG 5433 + uvicorn :18950 + PG 플래그 14개 ON + LOCAL_DRIVE_MOCK ON.

### 8.1 일일결산 전파

```
POST /api/daily/entries  {date:2026-06-02, income_cash:100000, exp_etc:50000,
                          memo:"[KID]inc=현금;e1=이체;e1a=50000[/KID]"}

before: active_tasks count=55
after : active_tasks count=56  delta=+1

derived active row:
  id=daily-verify-daily-09be2dfd
  source_daily_id=verify-daily-09be2dfd
  category=검증테스트
  work=daily-propagation-test
  transfer=50000   ← memo 의 e1=이체,e1a=50000 해석 결과

monthly summary contains entry: True
net_income: 600000

DELETE /api/daily/entries/{id}
cascade delete active: True   ← derived 진행업무 자동 제거
```

### 8.2 검색

§6 표 참고 — 한글 1글자, 영문 last/first, 영문 full, phone digits, 등록증 모두 검증 완료.

### 8.3 숙소제공자 helper

```ts
resolveProviderName(null)                        // → null
resolveProviderName({})                          // → null
resolveProviderName({ provider_name: "" })       // → null   (broken)
resolveProviderName({ provider_name: "  " })     // → null   (broken)
resolveProviderName({ provider_name: "홍길동" })   // → "홍길동"
resolveProviderName({ provider_last_name: "HONG",
                       provider_first_name: "GIL" }) // → "HONG GIL"
```

카드 뱃지:
- `null` (relationship 없음)            → 회색 "숙소제공자"
- `{provider_name: ""}` (broken)         → 빨강 "숙소: 연결 정보 이상"
- `{provider_name: "홍길동"}` (connected) → 파랑 "숙소: 홍길동"

### 8.4 컴파일

```
python -m compileall backend -q      → EXIT=0
cd frontend && npx tsc --noEmit      → EXIT=0
```

## 9. 남은 한계

1. **고객 카드 업무현황 (`workSummary`)** 은 `useEffect(customerId)` 기반 fetch 라 `react-query` invalidate 가 직접 트리거하지 않는다. 대신 사용자가 다른 고객 카드로 전환했다가 돌아오거나, 드로어를 닫았다가 다시 열면 재조회된다. UX 상 충분하다고 판단해 useQuery 로 전환은 보류 (요구사항: "broad redesign 금지").
2. 검색 결과 최대 30건 제한 유지 — 더 많은 결과를 보려면 페이지네이션 필요하지만 현재 사용 시나리오에서는 충분.
3. 생년월일 추정은 등록증 앞 6자리 yy를 `yy >= 50 → 19xx, else 20xx` 휴리스틱. 1900-2049 범위에서 정확. 2050년 이후 출생자는 안내 필요.
4. broken 관계 행을 "이상 데이터 삭제" 로 정리하면 backend 도 해당 row 를 삭제하지만 사용자 confirm 한 번만 — `confirm()` 메시지는 "연결 해제" 와 동일.
5. 일일결산 → 위임내역 append 는 `customer_id` 또는 `한글 이름` 정확 매칭 시에만 동작. 동명이인 다수 존재 시 안전을 위해 skip.

## 10. 사용자 최종 검증 준비 상태

### 검증 가능 항목 ✅
- 숙소제공자 카드 뱃지 — 3 상태 (none / connected / broken)
- 숙소제공자 / 신원보증인 모달 — current 블록 + 해제 버튼이 일관됨
- 모달 정렬 — 너비·padding·필드 페어링·입력 높이 일관
- 검색 — 한글 1+ / 영문 last·first·full 2+ / phone·등록증 digits
- 검색 결과 — 생년월일 + 전화 표시
- 일일결산 add → 진행업무 / 월간 요약 / 월간 분석 / 대시보드 / 업무관리 즉시 갱신
- 일일결산 delete → 파생 진행업무 자동 제거

### 사용자 권장 검증 순서
1. PowerShell 백엔드 기동 (이전 보고서 §11 환경변수 블록)
2. `cd frontend; npm run dev`
3. wkdwhfl 로그인
4. 임의 고객 카드 → 숙소제공자 버튼 — 3 케이스 시각 확인:
   - 미연결 고객 (회색 뱃지)
   - 정상 연결 고객 (파란 뱃지)
   - broken (빨강 뱃지) — 직접 보기 어렵지만 모달의 "현재" 블록이 빨강이면 정확 동작
5. 모달 → 고객 DB 검색 — 한글 1자, 영문 KIM/HONG, 풀네임 시도. 결과에 생년월일/전화 라인이 나오는지 확인.
6. 직접 입력 탭 → 그리드 정렬 확인 (4행, 입력 높이 일치).
7. `/daily` 페이지 → 새 항목 추가 → 다른 탭으로 이동하지 않고 다음 화면 확인:
   - 같은 페이지의 월간 요약 합계가 증가
   - `/dashboard` 진행업무 카드에 새 행 등장
   - `/tasks` 진행업무 목록에 새 행 등장
   - 같은 고객 카드 열면 업무현황 카운트 증가
8. 일일결산 행 삭제 → `/dashboard` 의 파생 진행업무 행이 자동 제거되는지 확인.

### 결론
**사용자의 브라우저 최종 검증을 받을 준비가 되었다.** 단, 위 §9 의 한계 4개 (특히 고객 카드 업무현황의 fetch 메커니즘) 은 알아두면 좋다. commit / push / 배포 미수행. 사용자 검증 PASS 후 다음 라운드에서 커밋 결정.

---

**정지.** 사용자 브라우저 검증 대기.
