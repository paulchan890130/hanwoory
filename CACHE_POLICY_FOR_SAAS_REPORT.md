# CACHE_POLICY_FOR_SAAS_REPORT.md

K.ID SaaS (로컬 PG / Next.js / React Query v5) 의 캐시 정책.

## 1. 5개 핵심 원칙

| # | 원칙 |
|---|---|
| 1 | 테넌트 데이터를 다루는 **모든 쿼리 키는 `tenant_id` 를 포함**한다. 키 모양: `["domain", tenantId, …]`. 같은 브라우저에서 테넌트를 전환해도 캐시 충돌이 발생하지 않게 한다. |
| 2 | **운영 데이터 (operational)** — 잦은 변경이 일어나는 데이터 — `staleTime: 0` 또는 매우 짧은 값. mutation 이후 즉시 invalidate. |
| 3 | **참조 데이터 (reference)** — 거의 변하지 않는 데이터 — 30초 ~ 5분 캐시 허용. |
| 4 | **인증 / 권한 / 워크스페이스 활성화** 관련 정보는 절대 길게 캐싱하지 않는다. token, is_admin, tenants.is_active 등이 stale 하면 권한 우회로 이어진다. |
| 5 | **임의 mutation 직후, 의존하는 모든 쿼리 키를 invalidate** 한다. 브라우저 새로고침 / 모달 재오픈 / 페이지 이동에 의존하지 않는다. **낙관적 업데이트 (`onMutate` → `setQueryData`)** 도 가능하면 적용 — UX 즉시성 + 백그라운드 refetch 의 belt-and-suspenders 결합. |

## 2. 도메인별 권장값

`gcTime` (구 `cacheTime`) 은 명시하지 않으면 React Query v5 기본값 5분. 아래에서 별도로 지정한 경우만 변경.

### 운영 (operational) — staleTime 짧음 + 잦은 invalidate

| 도메인 | 쿼리 키 모양 | staleTime | gcTime | 비고 |
|---|---|---|---|---|
| `customers` 목록 | `["customers", tenantId, page, pageSize, q]` | 0 ~ 5_000 | 5분 | drawer 안에 있어도 외부 수정이 반영되어야 함 |
| `customer` 단건 | `["customer", tenantId, customerId]` | 0 | 5분 | drawer open 중에도 외부 변경 즉시 반영 |
| `accommodation_provider` | `["accommodation", tenantId, customerId]` | 0 | 5분 | save / delete 후 즉시 갱신 |
| `guarantor_connection` | `["guarantor", tenantId, customerId]` | 0 | 5분 | 동일 |
| `customer_work_summary` | `["customer", "work-summary", tenantId, customerId]` | 0 | 5분 | 일일결산 / 진행업무 변경 시 invalidate 대상 |
| `daily_entries` | `["daily", "entries", tenantId, date]` | 0 | 5분 | 가장 잦은 변경 |
| `daily_balance` | `["daily", "balance", tenantId]` | 0 | 5분 | |
| `daily_summary` | `["daily", "summary", tenantId, year, month]` | 0 ~ 5_000 | 5분 | daily entry 변경 시 invalidate |
| `monthly_analysis` | `["monthly-analysis", tenantId, year, month]` | 0 ~ 5_000 | 5분 | 동일 |
| `tasks_active` | `["tasks", "active", tenantId]` | 0 ~ 2_000 | 5분 | 현재 2_000 — 유지 |
| `tasks_planned` | `["tasks", "planned", tenantId]` | 0 ~ 2_000 | 5분 | 동일 |
| `tasks_completed` | `["tasks", "completed", tenantId]` | 0 ~ 2_000 | 5분 | 동일 |
| `events` (캘린더) | `["events", tenantId]` | **0** | 5분 | 본 라운드에서 tenant-aware 키로 변경. mutation 시 `onMutate` 낙관적 업데이트 + `onSettled` invalidate (`dashboard/page.tsx`) |
| `memos.short/mid/long` | `["memo", kind, tenantId]` | 0 ~ 30_000 | 5분 | short/mid 는 빈번 변경, long 은 거의 안 변함 |
| `expiry-alerts` | `["expiry-alerts", tenantId]` | **5분** | 10분 | 만료일 알림은 사용자 작업으로 자주 변하지 않음 |
| `board_posts` | `["board", "posts", q]` | 0 ~ 5_000 | 5분 | 공유 데이터, tenant 무관 |
| `board_comments` | `["board", "comments", postId]` | 0 | 5분 | |
| `signature.customer/agent/temp` | `["signature", kind, tenantId, customerId?]` | 0 | 5분 | |

### 참조 (reference) — 변경이 드묾, 더 길게 캐시 가능

| 도메인 | 쿼리 키 모양 | staleTime | gcTime | 비고 |
|---|---|---|---|---|
| `reference.sheets` | `["reference", "sheets", tenantId]` | 30_000 | 10분 | 시트 목록은 거의 불변 |
| `reference.data` | `["reference", "data", tenantId, sheet]` | 30_000 | 10분 | 편집 시 invalidate |
| `certification.bootstrap` | `["cert", "bootstrap", tenantId]` | 60_000 | 10분 | |
| `cert.*` 개별 | `["cert", kind, tenantId]` | 30_000 | 10분 | |
| `documents.tree` (quick-doc) | `["quick-doc", "tree", tenantId]` | 5분 | 10분 | 매뉴얼 트리는 매뉴얼 업데이트가 있을 때만 갱신 |
| `guidelines.list` | `["guidelines", "list"]` | 10분 | 30분 | 정적 |
| `marketing.posts` (public) | `["marketing", "posts"]` | 60_000 | 5분 | 공개 게시물 |
| `roi-presets` | `["roi-presets", tenantId]` | 60_000 | 10분 | |

### 인증 / 권한 / 워크스페이스 — 짧게

| 도메인 | 쿼리 키 모양 | staleTime | gcTime | 비고 |
|---|---|---|---|---|
| `auth.me` | `["auth", "me", loginId]` | **0** | 1분 | `is_admin` / `tenant_id` / `is_active` 가 stale 이면 권한 우회 가능. 절대 길게 캐싱 금지. |
| `admin.accounts` | `["admin", "accounts"]` | **0** | 1분 | 관리자 페이지 — 가입신청 즉시 반영 |
| `admin.workspace.status` | (없음 — invalidate 트리거만) | — | — | `/api/admin/workspace` 호출 후 즉시 `admin.accounts` invalidate |
| `auth.bootstrap` | (호출 후 logout 권장) | — | — | bootstrap 1회성 |

### 토큰 / 세션

- JWT는 `access_token` 으로 localStorage 보관. **만료 8h** (`backend/auth.py`).
- 만료 시 axios interceptor 가 자동 redirect (`/login`). `sessionStorage["auth_expired"]` 로 로그인 페이지 메시지 표시.
- 비밀번호 변경 등 권한-영향 mutation 후 명시적 logout 권장.

## 3. Mutation 후 invalidate 매트릭스

mutation 의 onSuccess (또는 onSettled) 에서 invalidate 해야 할 키들. **`queryKey: ["A", "B"]` 는 `["A", "B", ...]` 로 시작하는 모든 키를 무효화**하므로 prefix 만 명시.

| 트리거 | invalidate 대상 |
|---|---|
| 일일결산 add/update/delete | `["daily"]`, `["tasks"]`, `["monthly-analysis"]`, `["customer", "work-summary"]` |
| 일정(events) add/update/delete | `["events", tenantId]` (낙관적 업데이트도 적용) |
| 진행업무 update/complete/delete | `["tasks"]`, `["customer", "work-summary"]`, 해당 고객 `["customer", customerId]` |
| 고객 update | `["customers"]`, `["customer", customerId]` |
| accommodation save/delete | `["accommodation", tenantId, customerId]`, `["customer", customerId]` |
| guarantor save/delete | `["guarantor", tenantId, customerId]`, `["customer", customerId]` |
| memo save | `["memo"]` (모든 kind 일괄) |
| signature save | `["signature"]` (모든 종류 일괄) |
| 게시판 post/comment | `["board"]` |
| 마케팅 게시물 | `["marketing"]` |
| reference 편집 (PG 모드 미구현) | `["reference"]` |
| admin /accounts PUT/DELETE | `["admin", "accounts"]` |
| admin /workspace 생성 | `["admin", "accounts"]` |
| 회원가입 (`/auth/signup`) | `["admin", "accounts"]` (즉시 pending 표시) |
| 로그인 | localStorage 갱신 + `queryClient.clear()` (계정 전환 시 stale 캐시 방지) |
| 비밀번호 변경 | logout → 재로그인 |

## 4. tenant_id 포함 규칙

### 왜?
- 같은 브라우저에서 admin 계정 ↔ 일반 계정 전환 시 캐시가 섞이면 안 됨.
- 멀티 사이트 / 멀티 사무소 SaaS 시나리오에서 tenant 분리가 캐시 레벨에서 보장돼야 함.
- 백엔드는 이미 JWT 의 tenant_id 로 격리하지만, 클라이언트 캐시도 동일 키 공간을 분리해야 함.

### 적용 규칙
- **테넌트 데이터**: 반드시 `["domain", tenantId, ...]`. `tenantId` 는 `getUser()?.tenant_id ?? "_anon_"` 로 추출.
- **공유 데이터** (게시판, 마케팅, manual 등): tenant_id 불필요. 그대로 `["board"]`, `["marketing"]`.
- **혼합**: 명시적으로 어느 쪽인지 결정. 모호하면 tenant 포함.

### 본 라운드 적용 사례
- `["events"]` → **`["events", tenantId]`** (`dashboard/page.tsx`)

### 미적용 (다음 라운드 후보)
- `["tasks", "active"]` → `["tasks", "active", tenantId]`
- `["daily", "entries", date]` → `["daily", "entries", tenantId, date]`
- `["customers"]` → `["customers", tenantId, …]`
- `["memo", kind]` → `["memo", kind, tenantId]`
- `["expiry-alerts"]` → `["expiry-alerts", tenantId]`

> **현재 상태**: 백엔드가 JWT 기반 tenant 격리를 강제하므로 실제 데이터 누출은 발생하지 않는다. 클라이언트 캐시 키에 tenant_id 가 없어도 같은 브라우저에서 동시에 두 테넌트로 로그인하지 않는 한 안전. 그러나 SaaS 모범 사례로 다음 라운드에서 일괄 적용 권장.

## 5. 낙관적 업데이트 가이드

`staleTime: 0` + invalidate 만으로도 정확성은 보장되지만 **네트워크 RTT 동안 UI 가 정지**. SaaS UX 에서는 mutation 직후 즉시 화면 갱신이 권장.

### 패턴

```ts
const mut = useMutation({
  mutationFn: (body) => api.save(body),
  onMutate: async (body) => {
    await qc.cancelQueries({ queryKey });
    const previous = qc.getQueryData(queryKey);
    qc.setQueryData(queryKey, (prev) => applyChange(prev, body));
    return { previous };
  },
  onError: (_e, _v, context) => {
    if (context?.previous) qc.setQueryData(queryKey, context.previous);
    toast.error("저장 실패");
  },
  onSettled: () => {
    qc.invalidateQueries({ queryKey });
  },
});
```

### 적용 우선순위
1. **events** (캘린더) — 본 라운드 적용 완료.
2. **active_tasks 진행도 / money draft** — 사용자가 한 번에 여러 행을 편집 → 즉시 반영 필요.
3. **memo short/mid/long** — 빠른 메모 작업.
4. **daily entries** — 추가 직후 즉시 리스트에 보여야 함.

## 6. drawer / open 상태에서도 갱신 보장

문제: useQuery 가 disable=true 되거나 useEffect 기반 fetch 인 경우, mutation 후 invalidate 가 와도 데이터가 갱신되지 않음.

해결:
- 가능하면 **useQuery 사용** (invalidate 가 자동 적용).
- useEffect 기반인 경우 mutation 의 onSettled 에서 동일 effect 의 dependency 를 트리거 (예: 별도 `refetchKey` state 를 bump).
- 현재 `customer_work_summary` 는 useEffect 기반 — `["customer", "work-summary", customerId]` invalidate 만으로는 부족. 다음 라운드에서 useQuery 로 전환 권장.

## 7. gcTime (garbage collection)

`gcTime` 은 쿼리가 unobserved 가 된 후 메모리에서 폐기될 때까지의 시간. 기본 5분. 다음 케이스에서 조정 권장:

- **자주 다시 보는 화면** (대시보드, 일일결산): 10분 정도로 늘려 페이지 이동 후 재진입 시 즉시 표시.
- **민감/큰 데이터** (admin accounts, customer 전체 목록): 1분 ~ 5분으로 짧게.
- **서명 / 인증**: 1분 짧게 — 권한 변경 후 stale 방지.

## 8. SaaS 운영 안전 가드

| 가드 | 적용 |
|---|---|
| API 401 → 자동 logout + redirect | `frontend/lib/api.ts` interceptor — 적용 완료 |
| 로그인 시 캐시 전체 클리어 | **추가 권장** — 계정 전환 시 stale 캐시 제거 |
| 로그아웃 시 캐시 전체 클리어 | **추가 권장** |
| token 만료 임박 시 silent refresh | 향후 작업 (JWT 만료 8h, 사용자 작업 중에 만료될 가능성) |
| 권한 검증 — 클라이언트 우회 방지 | 백엔드 `require_admin` 의존 — 캐시된 `is_admin` 만 믿지 않음 |

## 9. 검증 ✅ / 미적용 ☐

- ✅ `events` 캐시 tenant-aware 키 + 낙관적 업데이트 + invalidate (본 라운드)
- ✅ daily mutation 후 광범위 invalidate (`["daily"]`, `["tasks"]`, `["monthly-analysis"]`, `["customer","work-summary"]`)
- ✅ admin `/accounts` 쿼리 staleTime 짧음 (가입신청 즉시 반영)
- ☐ 모든 도메인의 키에 tenant_id 일괄 적용 (다음 라운드)
- ☐ 낙관적 업데이트 — events 외 다른 잦은-변경 도메인에 확장
- ☐ 로그인/로그아웃 시 `queryClient.clear()` 자동화
- ☐ work_summary 를 useQuery 로 전환

## 10. 결론

본 정책 문서는 **권장 기준선**. 한꺼번에 전 도메인을 변경하지 않고 다음 우선순위로 적용:

1. **이번 라운드 (완료)**: events tenant-aware + 낙관적 업데이트 — 캘린더 라이브 리프레시 충족.
2. **다음 라운드**: tenant_id 키 일괄 적용 + 로그인/로그아웃 캐시 클리어.
3. **그 다음**: 낙관적 업데이트 적용 도메인 확장 + work_summary useQuery 전환.

각 단계마다 별도 라운드/별도 보고서로 진행해 회귀 위험을 최소화.
