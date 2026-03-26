# K.ID 출입국업무관리 — GPT 에이전트 핸드오프 프롬프트

## 프로젝트 개요

Next.js 14 (App Router) + FastAPI + Google Sheets 기반 출입국 SaaS 앱.
레거시 Streamlit 코드(`pages/`)는 **읽기 전용 참고용**이며 수정 대상이 아님.
수정 대상은 `backend/`(FastAPI)와 `frontend/`(Next.js)만.

```
프로젝트 루트/
├── backend/
│   ├── routers/          # FastAPI 라우터 (admin.py, scan.py, search.py, ...)
│   ├── services/         # tenant_service.py, accounts_service.py 등
│   └── auth.py
├── frontend/
│   ├── app/(main)/       # Next.js App Router 페이지
│   │   ├── dashboard/page.tsx
│   │   ├── daily/page.tsx
│   │   └── ...
│   └── lib/
│       ├── api.ts        # dailyApi, eventsApi 등 API 클라이언트
│       └── utils.ts      # today(), safeInt(), formatNumber()
├── pages/                # ⚠️ Streamlit 레거시 — 읽기 전용, 수정 금지
│   └── page_scan.py      # OCR 엔진 (parse_passport, parse_arc)
├── config.py
└── ...
```

---

## 이슈 1: Drive `storageQuotaExceeded` 403 오류

**파일**: `backend/routers/admin.py`
**함수**: `create_workspace()`

**현상**: 신규 테넌트 워크스페이스 생성 시 Google Drive `files().copy()` 호출에서 403 `storageQuotaExceeded` 에러 발생.

**에러 로그**:
```
Drive 워크스페이스 생성 실패: <HttpError 403 ... storageQuotaExceeded>
| parent=1gkn93pxHcmHlDjBovS2durTUWDsv_Hle
| customer_template=1lyQGoWIkSDsPsCdZAoVx8Dba5O1dxfeHusi7Z1ZmUYo
| work_template=19sSfYARGnL3H8BM05PnrgFKJeCGEQU28dQG1BvU-flA
```

**현재 코드 위치**: `backend/routers/admin.py` → `create_workspace()` 내부에서
```python
drive.files().copy(fileId=CUSTOMER_DATA_TEMPLATE_ID, ...).execute()
drive.files().copy(fileId=WORK_REFERENCE_TEMPLATE_ID, ...).execute()
```

**배경**: 동일한 오류가 이전 Streamlit 빌드에서도 발생했었고 당시 해결됐음.
- `pages/` 폴더와 `수정 전/` 등 백업 폴더에 이전 Streamlit 워크스페이스 생성 코드가 있을 수 있음
- git log / git blame으로 해당 수정 이력 확인 후 동일 해결책을 FastAPI 버전에 적용할 것

**작업 지시**:
1. `git log --all --oneline -- pages/` 및 `git log --all --oneline -- backend/` 실행해서 워크스페이스 생성 관련 커밋 탐색
2. `pages/` 내 Streamlit 버전의 워크스페이스 생성 함수에서 `storageQuotaExceeded` 해결 로직 확인
3. 동일 로직을 `backend/routers/admin.py:create_workspace()`에 이식
4. 서비스 계정 Drive 용량 체크 또는 `supportsAllDrives`, `includeItemsFromAllDrives` 파라미터 등 Drive API 옵션도 검토

---

## 이슈 2: 파일 구조 정리 (Streamlit ↔ Next.js+FastAPI 혼재)

**현황**:
- `pages/page_scan.py` 등 Streamlit 레거시가 프로젝트 루트에 공존
- `backend/routers/scan.py`가 `from pages.page_scan import parse_arc, parse_passport`로 Streamlit 모듈을 직접 임포트
- 배포 환경(SaaS)에서 Streamlit 의존성이 포함되어 번들 과중

**목표**: 장기적으로 SaaS 배포 가능한 Clean Architecture.
- 단기: 임포트 경로 정리 및 불필요한 레거시 파일 목록 정리
- 중기: `pages/page_scan.py`의 OCR 핵심 로직을 `backend/services/ocr_service.py`로 이관

**⚠️ 제약**: `pages/page_scan.py`는 **현 시점에서 수정 금지** (Streamlit 기준선). 이관 작업 시 복사본을 만들어 `backend/`로 이동.

**작업 지시**:
1. `pages/` 하위에서 Next.js+FastAPI에서 실제로 임포트되는 파일 목록 파악
2. 임포트되는 파일은 `backend/services/` 또는 별도 경로로 복사 후 임포트 경로 수정
3. 완전히 Streamlit 전용이어서 FastAPI에서 사용하지 않는 `pages/` 파일은 삭제 후보 목록으로만 정리 (즉시 삭제 X, 목록만)
4. `backend/routers/scan.py`의 임포트 경로를 새 위치로 업데이트

---

## 이슈 3: 대시보드 캘린더 UX 개선

**파일**: `frontend/app/(main)/dashboard/page.tsx`

**현재 FullCalendar 설정 (line 407~446)**:
```tsx
<FullCalendar
  plugins={[dayGridPlugin, interactionPlugin]}
  initialView="dayGridMonth"
  locale="ko"
  aspectRatio={1.4}
  expandRows={true}
  events={calEvents}
  headerToolbar={{ left: "prev", center: "title", right: "next" }}
  dateClick={(info) => {
    const existing = (events as Record<string, string[]>)[info.dateStr] || [];
    setCalendarDate(info.dateStr);
    setCalendarMemo(existing.join("\n"));
    setCalModalIsEdit(existing.length > 0);
    setShowCalModal(true);
  }}
  eventColor="var(--hw-gold)"
  // ... dayHeaderContent, dayCellContent
/>
```

**문제점 3가지**:

### (A) 날짜 셀에 이벤트가 1줄만 표시됨
- 현재: `dayMaxEvents` 미설정 → 기본값 false → 이벤트가 1개 초과 시 "N more" 링크로 접힘
- **수정**: `dayMaxEvents={2}` 또는 `dayMaxEvents={3}` 추가

### (B) 이벤트 텍스트 클릭 시 모달이 열리지 않음
- 현재: `dateClick`만 있고 `eventClick` 핸들러 없음
- **수정**: `eventClick` 핸들러 추가:
```tsx
eventClick={(info) => {
  const dateStr = info.event.startStr.slice(0, 10);
  const existing = (events as Record<string, string[]>)[dateStr] || [];
  setCalendarDate(dateStr);
  setCalendarMemo(existing.join("\n"));
  setCalModalIsEdit(existing.length > 0);
  setShowCalModal(true);
}}
```

### (C) 이벤트에 cursor:pointer 없음
- **수정**: FullCalendar `eventDidMount` 또는 전역 CSS로 `.fc-event { cursor: pointer; }` 추가

---

## 이슈 4: 일일결산 UI 4가지 수정

**파일**: `frontend/app/(main)/daily/page.tsx`

### (가) 요약 카드 3분할 재배치

**현재 구조 (line 336~371)**:
```
[누적 현금 잔액] [오늘 수익 합계]     ← 2열 grid
[직전 3개월 평균 (avg3)]              ← 별도 블록 (아래)
```

**목표 구조**:
```
[이번달 누적 순수익] [오늘 수익 합계] [직전 3개월 평균]  ← 3열 grid
```

구체적으로:
- 왼쪽 카드: `누적 현금 잔액` → `이번달 누적 순수익`으로 교체
  - 값: `monthlySummary?.net_income` (이미 `monthlySummary` 쿼리 존재, `showMonthly`와 무관하게 항상 fetch)
  - `viewYear`/`viewMonth` 기준으로 `dailyApi.getMonthlySummary(viewYear, viewMonth)` 결과 사용
- 가운데 카드: `오늘 수익 합계` 그대로 유지
- 오른쪽 카드: `avg3` 블록을 카드 형태로 올려서 3열에 배치 (현재 아래에 따로 있는 `avg3` 블록 제거)
- 기존 `gridTemplateColumns: "1fr 1fr"` → `"1fr 1fr 1fr"` 변경

**주의**: `누적 현금 잔액` 카드(잔액 수동 입력 + `saveBalMut`)는 제거하거나 다른 위치로 이동. 사용하지 않는다면 제거해도 무방.

---

### (나) 누적 현금 잔액 항상 0 버그

**현재 코드 (line 68~71)**:
```tsx
const { data: balance = { cash: 0, profit: 0 } } = useQuery({
  queryKey: ["daily", "balance"],
  queryFn: () => dailyApi.getBalance().then((r) => r.data),
});
```

`balance.cash`가 항상 0으로 표시되는 버그.

**조사 지시**:
1. `frontend/lib/api.ts`의 `dailyApi.getBalance()` 구현 확인 — 엔드포인트 URL, 응답 필드명 확인
2. `backend/`에서 `/daily/balance` 엔드포인트 응답 구조 확인 — `cash` 필드가 실제로 내려오는지
3. 응답이 `{ balance: 0 }` 또는 `{ data: { cash: 0 } }` 등 다른 구조라면 `.then((r) => r.data)` 파싱 경로 수정
4. 백엔드에서 값을 저장/조회하는 로직 (Google Sheets 또는 DB) 확인 후 실제 저장된 값이 읽히도록 수정

> ※ (가)에서 `누적 현금 잔액` 카드를 제거하면 이 버그는 UI에서 사라지므로, (가) 완료 후 (나) 필요성 재평가 가능.

---

### (다) 새 항목 추가 폼 — 시간 필드를 맨 왼쪽으로 이동

**현재 레이아웃 (line 400~485)**:
```
[구분(60px)] [성명(72px)] [세부내용 flex: 시간(76px) | 세부내용 | 비고(72px)] [수입(90px)] [지출1(90px)] [지출2(90px)] [추가버튼(64px)]
```

**목표 레이아웃**:
```
[시간(76px)] [구분(60px)] [성명(72px)] [세부내용 flex: 세부내용 | 비고(72px)] [수입(90px)] [지출1(90px)] [지출2(90px)] [추가버튼(64px)]
```

구체적 수정:
- 현재 `세부내용` div (line 418~426) 안에 있는 `<input type="time">` (line 421~422)를 꺼내어 `구분` div 앞으로 이동
- `세부내용` flex 컨테이너에서 시간 input 제거 (세부내용 + 비고만 남김)
- 새로 추가된 시간 div에 라벨 `시간` 추가, `width: 76, flexShrink: 0`

---

### (라) 결산 테이블 — 순수익 컬럼 추가

**현재 테이블 헤더 (line 492~502)**:
```
구분 | 성명 | 세부내용 | 수입 | 지출1 | 지출2 | 수정 | 삭제
```

**목표**:
```
구분 | 성명 | 세부내용 | 수입 | 지출1 | 지출2 | 순수익 | 수정 | 삭제
```

**`<th>` 추가 위치**: `지출2` th 바로 다음, `수정` th 앞 (line 499 이후):
```tsx
<th style={{ width: 80, textAlign: "right" }}>순수익</th>
```

**각 행 `<td>` 추가**: `isEditing` 분기 양쪽 모두 `지출2` td 다음, 수정 버튼 td 앞에 추가.

일반 표시 행 (line 632 이후):
```tsx
<td style={{ textAlign: "right", fontSize: 12, fontWeight: 600,
  color: (dispInc - dispE1 - dispE2) >= 0 ? "#276749" : "#C53030" }}>
  {(dispInc - dispE1 - dispE2) !== 0 && formatNumber(dispInc - dispE1 - dispE2)}
</td>
```

수정 중인 행(isEditing): 빈 `<td />` 추가 (편집 중에는 표시 불필요)

**`<tfoot>` 합계 행**도 `colSpan` 조정 필요:
- 현재: `<td colSpan={2} />` (line 659) → `<td colSpan={3} />`로 변경 (순수익 + 수정 + 삭제)
- 또는 합계 행에도 순수익 합계 표시: `formatNumber(sumInCash + sumInEtc - sumExCash - sumExEtc - sumCashOut)`

---

## 작업 원칙

1. `pages/` 내 Streamlit 파일 (`page_scan.py` 등)은 **절대 수정 금지** — 읽기 참조만 허용
2. 수정 대상: `backend/` (FastAPI) 및 `frontend/` (Next.js)만
3. 각 이슈 수정 후 TypeScript 컴파일 에러 (`tsc --noEmit`) 확인
4. 이슈 간 의존성: 이슈 4-(가)에서 카드 구조 바꾸면 4-(나) 재평가 → 필요시 4-(나) 건너뜀
5. 이슈 1 (Drive 오류)는 git 이력 탐색이 전제 — git history 없이 독자 구현하지 말 것
