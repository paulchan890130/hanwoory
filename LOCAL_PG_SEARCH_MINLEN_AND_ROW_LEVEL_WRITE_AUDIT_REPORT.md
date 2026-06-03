# LOCAL_PG_SEARCH_MINLEN_AND_ROW_LEVEL_WRITE_AUDIT_REPORT.md

로컬 PostgreSQL 베타의 두 가지 규칙을 추가 적용한 최종 감사 보고서.

## 1. 요약

| 항목 | 상태 |
|---|---|
| 한글 검색 최소 길이 2자 강제 (백엔드 + 프론트 양쪽) | ✅ |
| 영문 2자, 숫자 3자, 혼합 안전 처리 | ✅ |
| 모든 도메인의 add/update/delete가 row-level 만 사용함 (run-time) | ✅ |
| import script 의 reset 만 예외 — 명시 실행 시에만 작동 | ✅ |
| backend compile + frontend tsc | EXIT=0 |
| Google Sheets / Drive / Render / commit / push | 0회 |

## 2. 근본 원인

| # | 원인 |
|---|---|
| 1 | 직전 라운드 보고서가 "Korean 1+ chars OK" 로 명시. 백엔드 `_match` 가 `len(q_lower) >= 1` 에서 Korean 검색을 허용 + 프론트 디바운스도 `searchQ.length < 1` 만 가드. 사용자는 명시적으로 한글 2자 이상을 원함. |
| 2 | 한 도메인(`events_pg_service.save_events_for_date`) 이 per-date 전체 삭제 후 재삽입 패턴을 사용. 운영 의미 (한 날짜 = 이벤트 텍스트 리스트) 는 보존되어야 하지만 row-level 쓰기 규칙 (`No delete-all-and-reinsert`) 과 불일치. |

## 3. 한글 검색 min length fix

### 검색 floor 명세

| 입력 종류 | 최소 길이 | 안내 메시지 |
|---|---|---|
| 한글 (가-힯) | **2** | "한글은 2글자 이상 입력하세요." |
| 영문 (A-Z/a-z) | **2** | "영문은 2글자 이상 입력하세요." |
| 숫자 (0-9) | **3** | "숫자는 3자리 이상 입력하세요." |
| 혼합 | 한 dimension 만 통과해도 OK | — |

### 백엔드 (`backend/routers/quick_doc.py`)

```python
def _classify_query(q):
    kor = len(re.findall(r"[가-힯]", q))
    eng = sum(1 for ch in q if ch.isascii() and ch.isalpha())
    digits = sum(1 for ch in q if ch.isdigit())
    return kor, eng, digits

def _query_passes_minlen(q):
    if kor >= 2 or eng >= 2 or digits >= 3: return True, ""
    ...returns specific Korean/English/digits msg

@router.get("/customers/search")
def search_customers(q, user):
    allowed, _msg = _query_passes_minlen(q)
    if not allowed:
        return []   # ← 백엔드도 floor 강제. 응답 shape는 list 그대로 유지.
    ...
    if kor_count >= 2 and q_lower in kor: ...    # 한글 substring (2+)
    if eng_count >= 2 and (... q_lower in sur/giv/eng_full ...): ...
    if dig_count >= 3 and (q_digits in p_digits or q_digits in reg_front): ...
```

방어 깊이(defense-in-depth): 프론트가 우회되어도 backend 가 빈 list 반환 → 결과 노출 0.

### 프론트엔드 (`frontend/app/(main)/customers/page.tsx`)

```ts
function classifyCustomerQuery(q): { korean, english, digits } { ... }
function customerQueryFloorMessage(q): string | null {
  if (!t) return null;
  if (korean >= 2 || english >= 2 || digits >= 3) return null;
  if (korean === 1) return "한글은 2글자 이상 입력하세요.";
  if (english === 1) return "영문은 2글자 이상 입력하세요.";
  if (digits > 0 && digits < 3) return "숫자는 3자리 이상 입력하세요.";
  return "한글 2자 · 영문 2자 · 숫자 3자 이상 입력하세요.";
}

// 디바운스
const floorMessage = customerQueryFloorMessage(searchQ);
useEffect(() => {
  if (floorMessage !== null || !searchQ.trim()) { setSearchResults([]); return; }
  // ... 300ms 디바운스 후 API 호출
}, [searchQ, tab, floorMessage]);
```

검색창 placeholder 도 "이름 / 전화번호 / 고객ID 검색" → "**한글 2자 · 영문 2자 · 숫자 3자 이상**" 으로 교체. floor 미달 시 노란 배너로 안내 문구 표시.

이 가드는 AccommodationProviderModal + GuarantorModal 의 검색 디바운스 한 곳을 `replace_all` 로 동시에 패치 → **숙소제공자 / 신원보증인 / quick-doc / 기타 동일 API 사용 모달 모두 자동 적용**.

## 4. 검색 테스트 결과 (PG 모드, hanwoory 1473 고객)

| 입력 | 분류 | 기대 | 실측 |
|---|---|---|---|
| `김` | Korean 1자 | 0건 | **0** ✅ |
| `홍` | Korean 1자 | 0건 | **0** ✅ |
| `K` | English 1자 | 0건 | **0** ✅ |
| `1` | digits 1자 | 0건 | **0** ✅ |
| `12` | digits 2자 | 0건 | **0** ✅ |
| `김민` | Korean 2자 | 검색 OK | **2** ✅ |
| `홍명` | Korean 2자 | 검색 OK | **2** ✅ |
| `KIM` | English 3자 | 검색 OK | **2** ✅ |
| `HO` | English 2자 | 검색 OK | **30** ✅ |
| `010` | digits 3자 | 검색 OK | **30** ✅ |
| `(빈 입력)` | — | 0건 | **0** ✅ |
| `a 가` | English 1 + Korean 1 | 0건 (혼합 미충족) | **0** ✅ |

## 5. Row-level 쓰기 감사 — 도메인별 표

운영 런타임 (Normal app) 만 평가. import script (`backend/scripts/import_excel_snapshot_to_pg_local.py`) 의 `--reset-local-pg` / `replace_sheet` 는 사용자 명시 실행 시에만 동작 — 본 감사 범위 외 (예외 카테고리).

| 도메인 | add | update | delete | 패턴 | 판정 |
|---|---|---|---|---|---|
| customers | upsert (tenant, customer_id) | upsert | **soft** by (tenant, customer_id) | row-level | ✅ safe |
| accommodation_providers | upsert (tenant, target_customer_id) | upsert | delete by (tenant, target_customer_id) | row-level | ✅ safe |
| guarantor_connections | 동일 | 동일 | 동일 | row-level | ✅ safe |
| events | row-level INSERT/UPDATE/DELETE (per-date diff) | 동일 | delete by (tenant, date_str) (한 날짜 단위 — 다른 날짜 비건드) | row-level diff | ✅ safe (§6 참고) |
| daily_entries | upsert by entry_id | upsert | delete by entry_id + cascade derived active_task `daily-{id}` | row-level + 결정적 cascade | ✅ safe |
| daily_balances | upsert (tenant) — 한 row | upsert | (삭제 없음) | row-level | ✅ safe |
| active_tasks | upsert by task_id | upsert / patch by task_id | delete by task_id 리스트 | row-level | ✅ safe |
| planned_tasks | upsert by task_id | upsert | delete by task_id 리스트 | row-level | ✅ safe |
| completed_tasks | upsert by task_id | upsert | delete by task_id 리스트 | row-level | ✅ safe |
| memos | upsert (tenant, kind) — 한 row | upsert | (삭제 없음 — 빈 content 로 비움) | row-level | ✅ safe |
| agent_signatures | upsert (tenant) | upsert | (삭제 없음) | row-level | ✅ safe |
| customer_signatures | upsert (tenant, customer_id) | upsert | (삭제 없음) | row-level | ✅ safe |
| temp_signature_slots | upsert (tenant, slot) | upsert | delete by (tenant, slot) | row-level | ✅ safe |
| board_posts | upsert by id | upsert | delete by id + cascade comments by post_id (결정적) | row-level + cascade | ✅ safe |
| board_comments | INSERT by id | (update 없음) | delete by id | row-level | ✅ safe |
| marketing_posts | upsert by id | upsert | delete by id | row-level | ✅ safe |
| cert_vendors / directions / groups / regions / prices | upsert by (tenant, id) | upsert | delete by (tenant, id) | row-level | ✅ safe |
| work_reference_sheets / rows | (편집 라우터는 여전히 Sheets 사용 — PG 모드 편집 미구현) | — | — | read-only at PG | ✅ safe (write path 비활성) |
| users / tenants / audit_logs | upsert by login_id / tenant_id | upsert (admin PUT) | soft (is_active=False) | row-level | ✅ safe |
| admin /workspace mock | upsert tenant + activate user(s) by tenant_id | upsert | (없음) | row-level | ✅ safe |

**런타임 unsafe pattern: 0건**.

### 예외 (import-only)

| 함수 | 위치 | 호출자 | 보호 |
|---|---|---|---|
| `replace_sheet` | reference_pg_service.py | import script 만 | 사용자가 `--execute` 로 명시 실행 + local-loopback DB 가드 |
| `_reset_local_pg` | import script | 사용자 `--reset-local-pg` 만 | 동일 |

## 6. 발견된 unsafe 패턴 + 수정

### events: per-date wipe-and-reinsert → row-level diff

**변경 전:**
```python
def save_events_for_date(tenant_id, date_str, lines):
    session.execute(delete(Event).where(tenant_id==.., date_str==..))
    for i, text in enumerate(cleaned):
        session.add(Event(...))
```

**변경 후 (`backend/services/events_pg_service.py`):**
```python
def save_events_for_date(tenant_id, date_str, lines):
    existing = session.scalars(select(Event).where(...).order_by(sort_order, id)).all()
    n_keep = min(len(existing), len(cleaned))
    for i in range(n_keep):
        # UPDATE in place — primary key 보존
        if row.event_text != cleaned[i] or row.sort_order != i:
            row.event_text = cleaned[i]
            row.sort_order = i
    for i in range(n_keep, len(cleaned)):
        session.add(Event(...))             # INSERT 새 row
    for i in range(n_keep, len(existing)):
        session.delete(existing[i])         # DELETE by primary key
```

겹치는 영역은 UPDATE, 늘어난 부분은 INSERT, 줄어든 부분은 PK 기반 DELETE. 동일 row 의 PK 가 보존되어 외부 참조나 추후 cascade 가 안전.

**검증 (e2e via HTTP):**

```
test_date = "2099-12-31"
before: []
add ['a','b','c']  → ['a','b','c']                      (3 INSERT)
edit ['a','b-CHANGED','c','d']
                   → ['a','b-CHANGED','c','d']           (1 UPDATE + 1 INSERT)
shrink ['a','b-CHANGED']
                   → ['a','b-CHANGED']                   (2 DELETE by PK)
DELETE /api/events/2099-12-31
                   → []
```

## 7. 남은 한계

1. **`/api/search`** (통합검색 토픽바) 는 본 감사 대상 외 — 사용자 요구 (relationship / quick-doc customer search) 와 별개 UX. min-length floor 미적용. 다음 라운드 작업으로 분리.
2. work_reference 편집 (`/api/reference/cell` PATCH 등) 은 여전히 Sheets gspread 사용. PG 모드 read-only — 편집 시도하면 PG 미구현 에러. 운영 도입 전 별도 라운드 필요.
3. memo 는 `kind` 별 한 row 가 통째로 한 단위 — 줄 단위 row 가 아니므로 "한 row 통째 update" 가 정상. 그래도 row-level upsert.
4. `add_event_to_date` / `remove_one_event_from_date` 같은 single-event 라우터는 없음 — 현재 모달이 "그 날짜 전체 리스트"를 한 번에 보내는 UX 라 diff 방식이 자연스러움.
5. 모달 검색에 floor 안내 배너는 표시되지만, 다른 화면 (예: 통합검색 페이지) 에는 동일 가드 미적용.

## 8. 안전 확인

- ✅ Google Sheets API / Drive API / Render 미접근
- ✅ 운영 데이터 손실 0
- ✅ git commit / push / merge / deploy 0
- ✅ DB 가드: `assert_local_database_url` 가 localhost / 127.0.0.1 / ::1 외 거부 (import script 만 사용)
- ✅ 모든 런타임 쓰기는 select-then-mutate / `session.add` / `session.delete(row)` / `delete(model).where(stable_pk)` 패턴 — 광역 wipe 없음
- ✅ 검색 floor 는 백엔드 + 프론트 양쪽에서 강제 (defense-in-depth)
- ✅ backend compile EXIT=0, frontend tsc EXIT=0

## 9. 최종 브라우저 검증 재개 가능 여부

**가능.** 사용자가 다음 시나리오를 그대로 진행하면 된다:

1. PowerShell — 백엔드 기동 (이전 보고서 §11 환경변수 그대로)
2. 프론트 — `cd frontend; npm run dev`
3. wkdwhfl 로그인 → 임의 고객 카드 → 숙소제공자 / 신원보증인 버튼 클릭
4. 검색 입력에서 `김`, `K`, `1` 각각 한 글자만 입력 — 노란 안내 ("한글은 2글자 이상 입력하세요." 등) 표시, 결과 리스트 비어있음 확인
5. `김민`, `KI`, `010` — 결과 표시 + 생년월일/전화 라인 표시 확인
6. 일일결산 항목 추가 → 다른 화면 (대시보드, 월간 요약, 업무관리, 고객 카드) 자동 갱신 확인
7. 일일결산 항목 삭제 → 파생 진행업무 자동 cascade 제거 확인
8. 캘린더 / 일정 — 한 날짜에서 항목 편집 시 다른 날짜는 절대 영향 받지 않음
9. 본 라운드 commit/push/배포 미수행. 검증 PASS 후 사용자가 별도 명령으로 커밋.

---

**정지.** 사용자 검증 대기.
