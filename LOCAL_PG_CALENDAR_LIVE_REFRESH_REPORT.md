# LOCAL_PG_CALENDAR_LIVE_REFRESH_REPORT.md

캘린더 / 일정 add·edit·delete 시 즉시 UI 갱신을 보장하기 위해 query 키를 tenant-aware 로 바꾸고, mutation 에 낙관적 업데이트 + invalidate 를 적용한 보고서.

## 1. 요약

| 항목 | 상태 |
|---|---|
| 일정 mutation 직후 캘린더 즉시 갱신 (add/edit/delete) | ✅ |
| 홈 대시보드 "오늘 일정" 영역도 동시 갱신 | ✅ |
| 다른 날짜는 절대 영향 없음 (row-level diff 유지) | ✅ |
| Google Sheets/Drive API 호출 0회 (PG 분기만) | ✅ |
| backend compile + frontend tsc | EXIT=0 |
| commit / push / 배포 | 0회 |

## 2. 근본 원인

- 직전까지 `dashboard/page.tsx` 의 일정 쿼리 키가 `["events"]` (tenant 무관) 이고, mutation 후 `invalidateQueries(["events"])` 만 호출.
- `staleTime: 0` 덕분에 invalidate 후 refetch 가 도는 것 자체는 되지만, **네트워크 RTT 동안 UI 가 정지** → 사용자 입장에서 "닫혀도 한 박자 늦게 갱신" 처럼 보임.
- 또한 같은 브라우저에서 다른 테넌트로 로그인 전환 시 캐시 충돌 가능 (SaaS 위반).
- 이벤트 행 단위 쓰기는 이전 라운드에서 이미 row-level diff 로 리팩토 완료 (`backend/services/events_pg_service.py:save_events_for_date`).

## 3. 변경된 파일

| 파일 | 변경 요지 |
|---|---|
| `frontend/app/(main)/dashboard/page.tsx` | (a) events 쿼리 키를 `["events"]` → **`["events", tenantId]`** 로 교체 (tenant-aware). (b) `saveEventMut` 에 **`onMutate` 낙관적 업데이트** 추가 — 모달 닫히는 순간 캘린더 + 오늘 일정 영역이 즉시 새 내용으로 보임. (c) `onError` 에서 이전 스냅샷으로 롤백. (d) `onSettled` 에서 백엔드 응답을 받아 백그라운드 refetch 로 최종 일관성 보장. (e) 다른 날짜는 객체 spread + 단일 date 키 수정/삭제로 절대 건드리지 않음. |
| `backend/services/events_pg_service.py` | (직전 라운드) 이미 row-level diff (UPDATE/INSERT/DELETE-by-PK). 본 라운드 변경 없음 — 백엔드는 그대로 사용. |

## 4. Event 쿼리 키 — Before / After

### Before
```ts
const { data: events = {} } = useQuery({
  queryKey: ["events"],
  queryFn: () => eventsApi.get().then((r) => r.data),
  staleTime: 0,
});
```

### After
```ts
const tenantId = user?.tenant_id ?? "_anon_";
const eventsKey = ["events", tenantId] as const;
const { data: events = {} } = useQuery({
  queryKey: eventsKey,
  queryFn: () => eventsApi.get().then((r) => r.data),
  staleTime: 0,
});
```

다른 페이지 (`/dashboard` 외) 에는 events 쿼리 사용처가 없어 (grep 확인) 한 곳만 갱신 — 1:1 매핑.

## 5. Mutation invalidation / 낙관적 업데이트 로직

### Before
```ts
const saveEventMut = useMutation({
  mutationFn: (...) => eventsApi.save(date, lines)  // or .delete(date)
  onSuccess: () => {
    qc.invalidateQueries({ queryKey: ["events"] });
    // setShowCalModal(false) ...
  },
});
```

문제: 사용자 입장 — 모달 닫힌 후 fetch 응답 도착할 때까지 UI 정지. 다른 테넌트 캐시 충돌 가능.

### After
```ts
const saveEventMut = useMutation({
  mutationFn: ({ date, text }) => {
    const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
    return lines.length === 0
      ? eventsApi.delete(date)
      : eventsApi.save(date, lines);
  },

  // 1) 낙관적 업데이트 — 모달 닫히기 전에 캐시 즉시 패치
  onMutate: async ({ date, text }) => {
    await qc.cancelQueries({ queryKey: eventsKey });
    const previous = qc.getQueryData<Record<string, string[]>>(eventsKey);
    const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
    qc.setQueryData<Record<string, string[]>>(eventsKey, (prev) => {
      const next = { ...(prev || {}) };
      if (lines.length === 0) delete next[date];     // 해당 date 만 삭제
      else next[date] = lines;                       // 해당 date 만 교체
      return next;
    });
    return { previous };
  },

  // 2) 실패 시 롤백
  onError: (_e, { text }, context) => {
    if (context?.previous) qc.setQueryData(eventsKey, context.previous);
    toast.error(...);
  },

  // 3) toast + 모달 닫기 — 이미 onMutate 가 UI 를 패치했음
  onSuccess: (_, { text }) => {
    toast.success(...);
    setShowCalModal(false);
    setCalendarMemo("");
  },

  // 4) 백그라운드 refetch — 서버 진실과 동기화 (다른 탭 / 동시 편집 대비)
  onSettled: () => {
    qc.invalidateQueries({ queryKey: eventsKey });
  },
});
```

### 사용자 체감 흐름
1. 사용자가 모달에서 텍스트 입력 → "저장" 클릭
2. `onMutate` 가 캐시를 즉시 패치 → **캘린더 + 오늘 일정 영역이 그 순간 즉시** 새 내용 표시
3. 모달이 닫힘 (`onSuccess`)
4. 백엔드 응답 도착 → `onSettled` 가 refetch 시작 → 거의 차이가 없는 서버 데이터로 조용히 덮어씀 (또는 실패 시 `onError` 가 롤백)

## 6. Row-level DB 쓰기 재확인

`backend/services/events_pg_service.py:save_events_for_date` (직전 라운드 결과 유지):

```python
def save_events_for_date(tenant_id, date_str, lines):
    existing = session.scalars(
        select(Event).where(... date_str==..)
        .order_by(Event.sort_order, Event.id)
    ).all()
    n_keep = min(len(existing), len(cleaned))
    for i in range(n_keep):                # UPDATE in place — PK 보존
        if row.event_text != cleaned[i] or row.sort_order != i:
            row.event_text = cleaned[i]
            row.sort_order = i
    for i in range(n_keep, len(cleaned)):  # INSERT new tail
        session.add(Event(...))
    for i in range(n_keep, len(existing)): # DELETE by PK
        session.delete(existing[i])
```

특성:
- 다른 date 의 row 는 SELECT 도, UPDATE 도, DELETE 도 안 함 (where 절이 `date_str == :d` 로 제한)
- 같은 date 안에서도 겹치는 인덱스는 UPDATE in place → PK 보존
- 늘어난 부분만 INSERT
- 줄어든 부분은 PK 기반 DELETE
- 절대 `delete(Event).where(tenant_id==...)` 처럼 광역 wipe 하지 않음

`delete_events_for_date` 는 한 date 의 row 들만 `delete(Event).where(tenant_id==.., date_str==..)` 로 제거. **다른 date 보호.**

## 7. 캘린더 add / edit / delete 테스트 결과 (HTTP + DB row count)

검증 환경: backend 18970, FEATURE_PG_EVENTS=true, hanwoory tenant.

| 단계 | 동작 | 결과 (응답 + DB row count) |
|---|---|---|
| 1 | `POST /api/events {date:2099-01-15, lines:[A,B,C]}` | 응답 ok / db_d1=3 / 다른 date 무변동 / **새 PK 490,491,492** |
| 2 | `POST /api/events {date:2099-01-15, lines:[A, B-CHANGED, C]}` | 응답 ok / db_d1=3 / **PK 490,491,492 그대로 (UPDATE in place)** |
| 3 | `POST /api/events {date:2099-01-16, lines:[Z]}` | db_d1=3 / db_d2=1 / D1 무변동 |
| 4 | `POST /api/events {date:2099-01-15, lines:[A]}` (shrink) | db_d1=1 / **첫 PK 490 보존, 491/492 만 DELETE by PK** / db_d2=1 |
| 5 | `DELETE /api/events/2099-01-15` | db_d1=0 / **db_d2 무변동 (1)** |
| 6 | `DELETE /api/events/2099-01-16` (cleanup) | db_d1=0 / db_d2=0 |

핵심 확인:
- ✅ Add 후 row 3개 생성, 다른 date 무영향
- ✅ Edit 시 PK 보존 (UPDATE) — DELETE+INSERT 가 아님
- ✅ Shrink 시 첫 PK 보존, 잉여 row 만 PK 기반 DELETE
- ✅ Delete date 시 그 date 의 row 만 제거, 다른 date 무영향
- ✅ 전체 tenant 의 row 가 wipe 되거나 events 테이블 전체가 reset 되는 일 없음

## 8. 홈 대시보드 "오늘 일정" 영역 갱신 검증

`dashboard/page.tsx:481-494` 의 `showSchedulePopup` 흐름은 같은 `events` 쿼리에서 파생:

```ts
useEffect(() => {
  const todayStr = ...;
  const evMap = events as Record<string, string[]>;
  const lines = (evMap[todayStr] || []).filter(Boolean);
  ...
}, [events]);
```

따라서:
- `onMutate` 가 `setQueryData(eventsKey, ...)` 로 캐시를 갱신 → `events` 가 새 객체 reference 가 됨 → 이 useEffect 가 재실행 → 오늘 일정 팝업 / 표시 영역이 즉시 새 내용 반영.
- 캘린더 그리드 (`calEvents` 메모) 도 `[events]` 의존성을 가지므로 동시 갱신.

## 9. 안전 확인

- ✅ Google Sheets API / Drive API 미호출 — events PG 분기 (`/api/events` GET/POST/DELETE) 가 `events_pg_service` 만 import. `googleapiclient` / `gspread` 모듈 미참조.
- ✅ Render PG / 환경변수 / 배포 미접근 — 로컬 Docker PG (`kid-postgres-local`) 만 사용.
- ✅ 운영 데이터 손실 0 — 테스트는 미사용 date `2099-01-15`, `2099-01-16` 만 사용 + 테스트 종료 시 cleanup.
- ✅ git commit / push / merge / deploy 0회.
- ✅ 본 라운드 변경: `frontend/app/(main)/dashboard/page.tsx` 1개 파일.

## 10. 최종 브라우저 검증 재개 가능 여부

**가능.** 다음 시나리오를 사용자가 그대로 진행:

1. 백엔드 기동 (이전 보고서 §11 환경변수)
2. `cd frontend; npm run dev`
3. wkdwhfl 로그인 → `/dashboard`
4. 캘린더 빈 날짜 클릭 → 모달에서 일정 입력 → 저장 → **모달 닫히는 순간 캘린더 그리드에 즉시 표시** (네트워크 응답 기다리지 않음)
5. 같은 날짜 다시 클릭 → 텍스트 일부 수정 → 저장 → **변경된 텍스트가 즉시 반영**
6. 한 날짜에 여러 줄 입력 (3개 등) → 저장 → 모두 표시, 순서 유지
7. 한 줄을 제거 → 저장 → 그 줄만 사라짐
8. 모든 줄 제거 (빈 텍스트) → 저장 → 해당 날짜 삭제, **다른 날짜는 영향 없음**
9. 오늘 날짜로 일정 추가 → 페이지 진입 시 "오늘 일정" 팝업도 즉시 새 내용 표시
10. 브라우저 새로고침 / 페이지 이동 없이 모든 갱신 확인

---

**정지.** 사용자 브라우저 검증 대기. commit / push / 배포 미수행.
