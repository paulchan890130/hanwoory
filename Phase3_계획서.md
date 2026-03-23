# K.ID 출입국업무관리 — Phase 3 계획서

> 작성일: 2026-03-20
> 기준: Phase 2 승인 완료 기준
> 방향: 신규 기능 추가보다 **Phase 2에서 부분 완성된 기능을 실무 완성도로 끌어올리는 것**이 우선

---

## 1. Phase 3 목표

Phase 2는 핵심 기능의 골격을 완성했다. 그러나 아래 영역은 동작은 하지만 실무에서 매일 쓰기에는 빈틈이 있다.

Phase 3의 목표는 다음 4개 영역을 **"쓸 수 있음" → "믿고 쓸 수 있음"** 수준으로 끌어올리는 것이다.

| 영역 | Phase 2 상태 | Phase 3 목표 |
|---|---|---|
| quick-doc 문서 생성 | 44개 PDF 존재, 6개 누락, 양식 매핑 부분적 | 누락 6종 보완 + 비자별 전체 양식 매핑 완성 |
| 통합검색 | 5개 소스 검색 동작, 메뉴얼·일정·기준데이터 미포함 | 검색 소스 확장 + 결과 품질·정렬 개선 |
| OCR 스캔 | 여권/등록증 OCR 동작, 영문 full name 분리 부정확 | 영문 성/이름 분리 정확도 보완 + 예외 처리 강화 |
| quick-doc 비자별 매핑 | REQUIRED_DOCS 부분 정의 | 실제 접수 빈도 기준 전체 비자 조합 완성 |

---

## 2. 우선순위

```
P1 (즉시) : quick-doc 누락 템플릿 6종 보완
P1 (즉시) : 통합검색 소스 확장 — 메뉴얼, 일정, 기준데이터 추가
P2 (다음)  : OCR 영문 fullname 분리 정확도 보완
P2 (다음)  : quick-doc 비자별 REQUIRED_DOCS 전체 매핑 완성
P3 (이후)  : 검색 결과 정렬 품질 개선 (relevance scoring)
P3 (이후)  : quick-doc 비자 선택 UI 개선 (드롭다운 계층 구조)
```

우선순위 판단 기준: 실무에서 오류가 **눈에 보이는** 빈도. quick-doc 누락 파일은 생성 시 즉시 오류 메시지가 노출되므로 P1.

---

## 3. 기능 단위 작업 목록

### P1-A. quick-doc 누락 템플릿 6종 보완

**배경**: 다음 6개 파일이 `templates/` 에 없어 해당 문서 포함 조합에서 `X-Missing-Docs` 헤더가 반환됨.

| 문서명 | 영향 받는 비자 조합 |
|---|---|
| 결혼배경진술서.pdf | F-6 결혼이민 등록/연장 |
| 초청장.pdf | F-3 동반 등록, F-1 방문동거 등록 |
| 직업및연간소득금액신고서.pdf | F-2 거주 연장 |
| 신청자기본정보.pdf | F-4 재외동포 등록/연장 일부 조합 |
| 심사보고서.pdf | 내부 심사용 |
| 준비중.pdf | 플레이스홀더 (현재 DOC_TEMPLATES에 None 처리) |

**작업 내용**:
- 각 PDF 양식의 레이아웃 초안을 reportlab으로 생성 → 실제 서식과 비교 후 교체
- `DOC_TEMPLATES`에서 `None` → 실제 경로로 업데이트
- `준비중`은 "서식 준비 중" 안내 텍스트 PDF로 대체

**완료 기준**: `체류-등록-F-6` 조합 생성 시 `X-Missing-Docs` 헤더 없이 완전한 PDF 반환.

---

### P1-B. 통합검색 소스 확장

**배경**: `search.py`의 현재 검색 소스는 고객, 업무, 게시판, 업무참고, 메모 5개. 아래 3개가 빠져 있다.

| 누락 소스 | 현재 상태 | 추가 방법 |
|---|---|---|
| 메뉴얼 (매뉴얼) | `core/manual_search.py` 존재하나 FastAPI 미연결 | `tenant_service.read_sheet("메뉴얼", tenant_id)` 또는 로컬 파일 검색 |
| 일정 (Events) | `events.py` 라우터 존재, search.py 미포함 | `tenant_service.read_sheet(EVENTS_SHEET_NAME, tenant_id)` |
| 문서작성 기준 데이터 | `reference.py`에서 다루는 업무참고 시트 | 검색 범위에 전체 시트 탭 포함 여부 확인 및 확장 |

**검색 품질 개선**:
- 현재: 단순 `in` 연산 (contains)
- 개선: 검색어를 공백으로 split → 모든 토큰이 포함된 행만 반환 (AND 검색)
- 개선: 결과 정렬 — `고객이름`, `업무상태`, `날짜` 기준 정렬 옵션 추가
- 개선: 결과에 `source` 필드 추가 (어느 소스에서 나왔는지 프론트 표시용)

**완료 기준**:
- "홍길동 만기" 검색 시 고객 + 업무 + 일정 결과가 동시에 반환됨
- `total` 수치가 실제 매칭 건수와 일치

---

### P2-A. OCR 영문 fullname 분리 정확도 보완

**배경**: `page_scan.py`의 `parse_passport()`가 MRZ(기계판독영역)에서 `surname`과 `given_names`를 추출하는데, 아래 예외 케이스에서 분리가 틀림.

| 케이스 | MRZ 예시 | 현재 결과 | 올바른 결과 |
|---|---|---|---|
| 성이 2단어인 경우 | `VAN<<DER<<BERG<<JAN` | 성=VAN, 이름=DER BERG JAN | 성=VAN DER BERG, 이름=JAN |
| 이름 없음 | `KIM<<` | 성=KIM, 이름="" | 성=KIM, 이름="" (OK) |
| `<<` 구분자 연속 3개 이상 | `PARK<<<MINSU` | 파싱 오류 | 성=PARK, 이름=MINSU |
| 한국 여권 영문이름 (성 먼저) | `LEE<<JINHEE` | 성=LEE, 이름=JINHEE | ✅ 현재 OK |

**작업 내용**:
- `backend/routers/scan.py`의 `_normalize_fields()` 에 MRZ 재파싱 로직 추가
- `parse_passport()` 반환값의 `성`/`명` 필드에 대한 whitespace + `<` 정규화 강화
- 예외 케이스별 단위 테스트 3개 이상 작성

**완료 기준**: 상기 4개 케이스 모두 정상 파싱. 테스트 통과.

---

### P2-B. quick-doc REQUIRED_DOCS 전체 비자 매핑 완성

**배경**: 현재 `REQUIRED_DOCS`에 정의된 조합 수가 실제 접수 케이스를 전부 커버하지 않음. 누락 조합에서는 `generate_full`이 빈 리스트를 반환.

**작업 내용**:
- 실무에서 접수 빈도가 높은 상위 비자 조합 전체 망라:
  - `체류` 카테고리: 등록/연장/자격변경 × F1~F6, H2, E1~E7
  - `귀화` 카테고리: 간이귀화, 특별귀화
  - `영주` 카테고리: F5 영주권 신청
- 각 조합에 `main`, `agent` 문서 목록을 실무 서류 기준으로 매핑
- `ROLE_WIDGETS`에 따른 위임장·대행확인서 자동 포함 로직 검증

**완료 기준**:
- 상위 20개 접수 조합 모두 `generate_full` 호출 시 최소 1개 이상의 문서 생성
- `skipped` 리스트가 비어 있거나, 비어 있지 않을 경우 이유가 명확히 `X-Missing-Docs` 헤더에 반영

---

### P3-A. 검색 결과 relevance 정렬

**작업 내용**:
- 검색어와 일치하는 필드가 많을수록 상위에 노출
- `고객이름`, `업무제목` 완전일치는 부분일치보다 위에 표시
- 최근 수정일자 기준 동점 처리

---

### P3-B. quick-doc 비자 선택 UI 계층 구조 개선

**배경**: 현재 프론트 `/quick-doc` 페이지의 비자 선택이 flat list. 조합이 많아지면 사용자가 스크롤해서 찾기 어려움.

**작업 내용**:
- `카테고리(체류/귀화/영주)` → `민원 유형` → `비자 종류` 3단 드롭다운으로 재구성
- 선택 시 해당 조합에서 생성 가능한 문서 목록 미리보기 표시

---

## 4. 파일별 수정 대상

| 파일 | 수정 내용 | 작업 |
|---|---|---|
| `backend/routers/quick_doc.py` | `DOC_TEMPLATES` None 6종 → 실제 경로로 교체, `REQUIRED_DOCS` 비자 매핑 확장 | P1-A, P2-B |
| `templates/결혼배경진술서.pdf` | 신규 생성 (reportlab) | P1-A |
| `templates/초청장.pdf` | 신규 생성 (reportlab) | P1-A |
| `templates/직업및연간소득금액신고서.pdf` | 신규 생성 (reportlab) | P1-A |
| `templates/신청자기본정보.pdf` | 신규 생성 (reportlab) | P1-A |
| `templates/심사보고서.pdf` | 신규 생성 (reportlab) | P1-A |
| `backend/routers/search.py` | `_search_manual()`, `_search_events()` 함수 추가, AND 검색 적용, source 필드 추가 | P1-B |
| `frontend/app/(main)/search/page.tsx` | 결과에 source 배지 표시, 소스별 필터 탭 추가 | P1-B |
| `backend/routers/scan.py` | `_normalize_fields()` MRZ 예외 처리 강화 | P2-A |
| `pages/page_scan.py` (레거시) | `parse_passport()` MRZ 파싱 정규화 | P2-A |
| `frontend/app/(main)/quick-doc/page.tsx` | 3단 계층 드롭다운 UI | P3-B |

---

## 5. 완료 판정 기준

Phase 3는 아래 기준이 **모두** 충족될 때 최종 승인한다.

### 필수 기준 (P1 전부, P2 전부)

| 번호 | 기준 | 검증 방법 |
|---|---|---|
| 1 | `체류-등록-F-6` 조합 생성 시 `X-Missing-Docs` 헤더 없이 완전한 PDF 반환 | API 직접 호출 또는 UI에서 생성 |
| 2 | "홍길동 만기" 검색 시 고객 + 업무 + 일정 결과 포함 | `/api/search?q=홍길동+만기` 응답 확인 |
| 3 | 검색 결과 `source` 필드 존재 및 올바른 출처 표시 | 응답 JSON 확인 |
| 4 | 이중성(VAN DER BERG) 여권 MRZ 파싱 테스트 통과 | `pytest` 단위 테스트 |
| 5 | `REQUIRED_DOCS` 상위 20개 비자 조합 생성 가능 확인 | quick_doc 스크립트로 전체 순회 테스트 |

### 선택 기준 (P3, Phase 4 이관 가능)

| 번호 | 기준 |
|---|---|
| 6 | 검색 결과 relevance 정렬 적용 확인 |
| 7 | quick-doc 3단 계층 드롭다운 UI 완성 |

---

## 부록: Phase 2 백로그 → Phase 3 매핑

| Phase 2 백로그 항목 | Phase 3 작업 |
|---|---|
| quick-doc 누락 템플릿 6종 보완 | P1-A |
| 통합검색 — 메뉴얼, 일정, 문서작성 기준 데이터 추가 | P1-B |
| 통합검색 품질/정렬 개선 | P1-B, P3-A |
| OCR 영문 fullname 분리 정확도 보완 | P2-A |
| quick-doc 비자별 양식 매핑 추가 고도화 | P2-B |
