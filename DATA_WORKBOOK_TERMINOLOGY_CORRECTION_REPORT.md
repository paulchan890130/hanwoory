# 데이터 워크북 용어 정정 보고서 (DATA_WORKBOOK_TERMINOLOGY_CORRECTION_REPORT.md)

> **작성일:** 2026-06-01
> **사유:** 사용자가 2026-06-01 메시지로 워크북 용어 4종을 명확히 정의. 직전 답변에서 본 도구가 "신"의 의미를 잘못 해석함 — 이를 정정하고 향후 모든 계획/보고서에 반영하기 위한 영구 참조 문서.
> **코드 변경 없음. Sheets/Drive 무수정. 마이그레이션 미실행. 미커밋.**

---

## 1. 어디서 용어를 잘못 썼나

### 1.1 직전 채팅 답변 (2026-06-01, 동일 세션)

본 도구가 "신 고객데이터·신 업무정리는 어떤 파일로 대체했고…" 질문에 답하면서 다음과 같이 **틀린 정의**로 답했습니다:

| 본 도구가 답한 (잘못된) 정의 | 정정된 의미 |
|---|---|
| "신 고객데이터 = 테넌트별 Google Sheets 워크북 (각 사무소마다 1개)" | **틀림.** "신 고객 데이터"는 hanwoory/admin의 실제 운영 워크북 1개를 의미. |
| "신 업무정리 = 테넌트별 Google Sheets 워크북" | **틀림.** "신 업무정리"는 hanwoory/admin의 실제 운영 업무정리 워크북 1개. |
| "기준 고객데이터 = 신규 사무소 생성 시 복사용 청사진" | ✅ 정확 (사용자 정의와 일치) |
| "기준 업무정리 = 신규 사무소 생성 시 복사용 청사진" | ✅ 정확 |
| (테넌트가 복사해서 받은 사본을 가리키는 용어를 사용 안 함 / "신"으로 잘못 부름) | 사본은 **"테넌트별 고객 데이터"**, **"테넌트별 업무정리"** 또는 **"{tenant_id}\_고객 데이터"**, **"{tenant_id}\_업무정리"** 로 부른다. |

> 채팅 답변은 파일로 영구화되지 않지만, 사용자의 향후 작업 맥락 형성에 영향. 본 보고서가 정정 기록.

### 1.2 마이그레이션 문서들 (전수 검사 결과: 모두 깨끗)

`grep -nE "신 ?고객|신 ?업무|기준 ?고객|기준 ?업무|테넌트별 고객|테넌트별 업무"` 를 모든 `.md` 파일에 대해 실행:
```
*.md → No matches found
```

즉 다음 문서들은 모두 이 용어 자체를 **단 한 번도 쓰지 않았음** — 따라서 잘못된 용어 기록 없음:
- `POSTGRES_MIGRATION_PLAN.md`
- `PHASE0_SAFETY_CHECK_REPORT.md`
- `PHASE0_GIT_AHEAD_CHECK_REPORT.md`
- `PHASE1_POSTGRES_FOUNDATION_REPORT.md`
- `PHASE1_LOCAL_DB_VERIFICATION_REPORT.md`
- `RENDER_POSTGRES_SETUP_GUIDE.md`
- `LOCAL_POSTGRES_BETA_PLAN.md`
- `LOCAL_POSTGRES_BETA_REPORT.md`
- `LOCAL_POSTGRES_BETA_USER_TEST_STEPS.md`

문서들은 모두 영문/구조적 용어(`SHEET_KEY`, `CUSTOMER_DATA_TEMPLATE_ID`, `customer_sheet_key`, "Customer workbook", "per-tenant workbook" 등)로 표기되어 있어 용어 오용은 없음. 다만 **개념적으로 "신 고객 데이터"가 무엇인지에 대한 잘못된 멘탈 모델**이 직전 답변에 반영되었으므로 향후 작성될 문서에는 본 보고서의 정의를 적용해야 함.

### 1.3 코드 (config.py 외)

```
config.py:43:# 신 고객 데이터 — Accounts, 고객 데이터, 시스템 마스터 탭 모두 이 파일에 있어야 합니다.
config.py:49:CUSTOMER_DATA_TEMPLATE_ID  = "1BzVTyjEq3or9kqbIKdQEQV3owSY-U57j0bcvD98Abl0"  # 기준 고객 데이터 (템플릿)
config.py:50:WORK_REFERENCE_TEMPLATE_ID = "1-0VPVgTXj4WavlSCWdpQ5TEEqUNNUV1twsZ0wrsRlek"  # 기준 업무정리 (템플릿)
```

| 위치 | 사용자 정의 기준 평가 |
|---|---|
| `config.py:43` 주석 (`SHEET_KEY` 위) | **모호.** 주석은 "신 고객 데이터 — Accounts, 고객 데이터, 시스템 마스터 탭 모두 이 파일에 있어야 합니다"라고 적혀 있어 `SHEET_KEY` 한 파일이 신 고객 데이터 + Accounts + 시스템 마스터 + 공용 탭을 **모두 겸한다**는 옛 통합 구조를 시사. 사용자 정의의 "hanwoory/admin의 실제 고객 데이터 워크북"과 일치할 수 있지만, 현재 운영 구조(Accounts가 별도 디렉터리, hanwoory의 `customer_sheet_key` 가 별도 워크북을 가리킬 수 있음)와 맞지 않을 가능성. **코드 수정은 본 단계에서 금지 — §4에서 별도 검토 권고.** |
| `config.py:49` 주석 | ✅ "기준 고객 데이터 (템플릿)" — 사용자 정의와 정확히 일치 |
| `config.py:50` 주석 | ✅ "기준 업무정리 (템플릿)" — 정확히 일치 |
| 영문 변수명 `CUSTOMER_DATA_TEMPLATE_ID`, `WORK_REFERENCE_TEMPLATE_ID` | ✅ "TEMPLATE" 접미사로 의미 명확. 정의와 일치. |

`backend/**/*.py` 에는 한국어 "신/기준 고객/업무" 용어 0건.

---

## 2. 정정된 정의 (사용자가 확정한 표준)

| 용어 | 정의 | 위치 / 식별 방법 |
|---|---|---|
| **신 고객 데이터** | hanwoory/admin의 **실제 운영 고객 데이터 워크북** (1개). 템플릿 아님. 테넌트 복사본 아님. | hanwoory tenant의 `customer_sheet_key` 값이 가리키는 워크북 (또는 `SHEET_KEY` 폴백 대상) |
| **신 업무정리** | hanwoory/admin의 **실제 운영 업무정리 워크북** (1개). 템플릿 아님. 테넌트 복사본 아님. | hanwoory tenant의 `work_sheet_key` 값이 가리키는 워크북 |
| **기준 고객 데이터** | 신규 테넌트 생성 시 복사되는 **템플릿 워크북**. **구조·탭·헤더만** 들어 있어야 하며, hanwoory 실데이터를 포함해서는 안 됨. | `config.py:49` `CUSTOMER_DATA_TEMPLATE_ID` |
| **기준 업무정리** | 신규 테넌트 생성 시 복사되는 **업무정리 템플릿**. 기본 참조 구조만. | `config.py:50` `WORK_REFERENCE_TEMPLATE_ID` |
| **테넌트별 고객 데이터** (또는 `{tenant_id}_고객 데이터`) | "기준 고객 데이터"가 한 테넌트용으로 복사된 사본. 각 테넌트마다 1개. | 해당 tenant의 `customer_sheet_key` 값이 가리키는 워크북 (hanwoory가 아닌 경우) |
| **테넌트별 업무정리** (또는 `{tenant_id}_업무정리`) | "기준 업무정리"가 한 테넌트용으로 복사된 사본. 각 테넌트마다 1개. | 해당 tenant의 `work_sheet_key` 값 |

### 2.1 6엔티티 관계도 (정정본)

```
[어드민 마스터 — SHEET_KEY]
├ Accounts                            ← 모든 테넌트 디렉터리
├ 게시판 / 게시판댓글 / 홈페이지게시물 / 행정사서명 / 서명임시저장   ← 공용 탭

[기준 고객 데이터 — CUSTOMER_DATA_TEMPLATE_ID]   ← 템플릿. 실데이터 없음
[기준 업무정리 — WORK_REFERENCE_TEMPLATE_ID]      ← 템플릿. 실데이터 없음

[신 고객 데이터]                                  ← hanwoory의 실제 운영 워크북 (한 개)
[신 업무정리]                                     ← hanwoory의 실제 운영 워크북 (한 개)

[테넌트A_고객 데이터] ... [테넌트N_고객 데이터]   ← 기준 고객 데이터에서 복사된 각 사무소 사본
[테넌트A_업무정리]   ... [테넌트N_업무정리]      ← 기준 업무정리에서 복사된 각 사무소 사본
```

### 2.2 잘못된 등치 (앞으로 금지)

| 금지된 등치 | 이유 |
|---|---|
| 신 고객 데이터 ≡ 테넌트별 고객 데이터 (사본) | "신"은 **hanwoory의 live 워크북**이며, 사본 일반이 아님 |
| 신 업무정리 ≡ 테넌트별 업무정리 (사본) | 동일한 이유 |
| 기준 고객 데이터 ≡ 신 고객 데이터 | 템플릿과 hanwoory live 워크북은 별개 |
| 기준 업무정리 ≡ 신 업무정리 | 동일 |

---

## 3. 정정이 필요한 문서 (Documents to Correct)

### 3.1 문서 본문 정정 필요: **없음**

전수 grep 결과 마이그레이션 .md 문서들은 한국어 용어를 쓰지 않았으므로 본문 수정은 불필요.

### 3.2 본 보고서 자체가 향후 참조 표준 역할
* 모든 향후 계획/보고서 작성 시 본 보고서의 §2 정의 표를 기준으로 사용
* 채팅 답변에서도 본 정의를 사용

### 3.3 (선택) 코드 주석 정정 검토
* `config.py:43` 의 주석 — 사용자가 별도로 코드 정정을 명시 지시할 경우에만 진행. **본 단계에서는 금지** (사용자 지시 "Do not modify code yet" 준수).

---

## 4. 코드가 잘못된 용어에 의존하는가?

**아니오 — 동작상 의존 없음.**

| 측면 | 평가 |
|---|---|
| 변수명 | `CUSTOMER_DATA_TEMPLATE_ID`, `WORK_REFERENCE_TEMPLATE_ID`, `customer_sheet_key`, `work_sheet_key`, `SHEET_KEY` — 모두 영문 / 구조적. 한국어 용어에 의존 안 함 |
| 라우팅 로직 (`backend/services/tenant_service.py`) | `_resolve_sheet_key()`가 탭 이름과 tenant_id 기준으로 워크북을 선택. 워크북을 "신"/"기준"으로 구분하지 않음 |
| 워크스페이스 생성 (`backend/routers/admin.py`) | `CUSTOMER_DATA_TEMPLATE_ID` / `WORK_REFERENCE_TEMPLATE_ID` 를 복사 원본으로 사용. "신"/"기준" 용어 미사용 |
| 한국어 주석 1건 (`config.py:43`) | 주석. 동작에 영향 없음. 단 사용자 정의 정착 시 명확화 필요할 수 있음 |

따라서 **이번 용어 정정은 본 도구의 멘탈 모델·향후 문서 작성을 정렬하는 것이며, 운영 코드 변경은 강제하지 않습니다.**

다만 **운영 상 추가로 확인할 가치가 있는 항목** (코드 수정 없이 사용자가 직접 확인하면 좋은 것):
- hanwoory tenant의 `Accounts` 시트 행에서 `customer_sheet_key` 값이 무엇으로 설정되어 있는가?
  - (a) `SHEET_KEY` 와 동일한 ID → "신 고객 데이터"가 `SHEET_KEY` 워크북 안의 일부 탭으로 존재 (옛 통합 구조)
  - (b) 별도 워크북 ID → "신 고객 데이터"가 진짜로 별도 워크북 (사용자 정의에 가장 부합)
  - (c) 빈 값 → `tenant_service.get_customer_sheet_key("hanwoory")` 가 `SHEET_KEY` 로 폴백 (DEFAULT_TENANT_ID 호환 모드)
- hanwoory의 `work_sheet_key` 도 동일하게 확인
- 위 답에 따라 `config.py:43` 주석을 "hanwoory의 신 고객 데이터는 별도 워크북" 또는 "SHEET_KEY 안에 통합" 으로 명확화 가능 (향후 별도 작업).

---

## 5. 향후 명명 권장 (Recommended Naming Going Forward)

### 5.1 문서 / 채팅 답변 작성 시
| 가리키려는 것 | 사용할 표현 |
|---|---|
| hanwoory의 운영 고객 데이터 | "신 고객 데이터" (hanwoory live) |
| hanwoory의 운영 업무정리 | "신 업무정리" (hanwoory live) |
| 신규 테넌트용 고객 템플릿 | "기준 고객 데이터" / `CUSTOMER_DATA_TEMPLATE_ID` |
| 신규 테넌트용 업무 템플릿 | "기준 업무정리" / `WORK_REFERENCE_TEMPLATE_ID` |
| 특정 테넌트의 고객 사본 (hanwoory 제외) | "테넌트별 고객 데이터" 또는 `{tenant_id}_고객 데이터` |
| 특정 테넌트의 업무 사본 (hanwoory 제외) | "테넌트별 업무정리" 또는 `{tenant_id}_업무정리` |
| 모든 테넌트의 사본을 가리키는 집합 표현 | "테넌트별 고객 데이터들" / "테넌트별 업무정리들" — "신" 사용 금지 |

### 5.2 코드 / 새 모듈 이름 (참고)
| 코드 측 컬럼/변수 | 가리키는 워크북 종류 |
|---|---|
| `customer_sheet_key` (Accounts 컬럼) | hanwoory이면 "신 고객 데이터", 그 외 테넌트이면 "테넌트별 고객 데이터" |
| `work_sheet_key` (Accounts 컬럼) | hanwoory이면 "신 업무정리", 그 외 테넌트이면 "테넌트별 업무정리" |
| `CUSTOMER_DATA_TEMPLATE_ID` | "기준 고객 데이터" (템플릿) — 1개 |
| `WORK_REFERENCE_TEMPLATE_ID` | "기준 업무정리" (템플릿) — 1개 |
| `SHEET_KEY` | 어드민 마스터 — Accounts + 공용 탭 |

### 5.3 미래 PostgreSQL 테이블에서
PG로 마이그레이션 시 워크북 단위 개념이 아닌 행 단위로 풀리지만, **메타데이터 컬럼** 으로 출처를 명확화 권장:
- `tenants.customer_sheet_key` 에 hanwoory의 "신 고객 데이터" 워크북 ID 보존
- 또는 별도 `tenants.live_workbook_kind ENUM('main_admin', 'tenant_copy')` 같은 명시 컬럼 (Phase 4 설계 시 결정)

---

## 6. PostgreSQL 마이그레이션 계획에 영향 있나? (Impact on PostgreSQL Migration)

### 결론: **계획서 본문 정정 불필요. 단, Phase 4 설계 시 본 정의를 반영해야 함.**

| 영역 | 영향 |
|---|---|
| `POSTGRES_MIGRATION_PLAN.md` 본문 | **없음** — 한국어 용어 미사용. 영문/구조적 표기만 사용. |
| Phase 1 (토대) | **없음** — `tenants`, `users`, `audit_logs` 만 다룸. 워크북 구분과 무관. |
| 로컬 베타 (현재) | **없음** — Phase 1 + 피처 플래그 + audit + 임포트 스크립트. 워크북 종류 구분 안 함. |
| Phase 3 (공존 설계) | **없음** — 피처 플래그·dual-write 패턴 결정. 워크북 종류와 독립. |
| **Phase 4 (customers)** | **영향 있음** — 고객 데이터를 PG로 옮길 때 "원본이 어느 워크북에서 왔는지"를 메타데이터로 보존할지 결정 필요. hanwoory("신 고객 데이터") vs 다른 테넌트("테넌트별 고객 데이터")가 동일 PG 테이블에 모이지만 출처는 `tenant_id` 로 충분히 구분되므로 추가 컬럼은 보통 불필요. **단 임포트 스크립트의 로그 메시지에 "신 고객 데이터" / "테넌트별 고객 데이터" 정확히 라벨링하도록 작성**. |
| Phase 5 (work data) | **영향 있음** — 동일 원리. "신 업무정리" 와 "테넌트별 업무정리" 를 라벨링 |
| Phase 6 (files) | **없음** — 파일 메타데이터만 옮김. 워크북 종류와 무관. |

### 작업 시점 가이드

* **본 시점 (베타)**: PG에 들어간 `tenants` 테이블이 hanwoory + 임포트된 테넌트들을 함께 담는다. 컬럼 `customer_sheet_key` 가 hanwoory 행에서는 "신 고객 데이터" ID 를 가리키고, 다른 행에서는 "테넌트별 고객 데이터" ID 를 가리킨다 — 같은 컬럼이지만 가리키는 워크북의 **성격**이 다름. 운영상으로는 동일하게 처리되지만 **로그·UI 메시지 작성 시 정확한 한국어 라벨링** 권장.
* **Phase 4 진입 시**: 임포트 스크립트 / 디버그 로그 / 관리자 대시보드 라벨에 본 보고서 §5.1 표 적용.
* **Phase 7 (운영 전환)**: Sheets 백업/내보내기 기능 라벨도 동일하게 정정.

---

## 7. 후속 조치 권장 (No Action Required Now)

본 보고서로 용어가 표준화되었으므로 추가 즉시 조치는 없음. 향후 자연스럽게:

1. **(자동)** 본 도구가 다음 답변/문서부터 §2 정의 적용
2. **(사용자 선택)** `config.py:43` 주석을 더 명확하게 정정하고 싶다면 별도 PR로 진행 — 본 단계 금지
3. **(Phase 4 시점)** Customer 임포트 스크립트 로그 라벨에 "신 고객 데이터" / "테넌트별 고객 데이터" 정확히 사용

---

## 8. 본 보고서가 보장하는 것 / 보장하지 않는 것

### 보장
- ✅ 본 보고서 §2 정의는 사용자가 확정한 표준이며 향후 모든 본 도구 산출물에 적용된다.
- ✅ 본 보고서 작성 동안 코드 / Sheets / Drive / 마이그레이션 / 커밋 / 푸시 일절 발생하지 않았다.

### 보장하지 않음 (사용자가 직접 결정)
- ❌ `config.py:43` 주석 정정 — 사용자 명시 지시 없으면 진행 안 함
- ❌ hanwoory의 `customer_sheet_key` / `work_sheet_key` 실제 값 점검 — 사용자가 직접 Accounts 시트 확인 필요 (운영 시트 read-only 조회)
- ❌ 본 정정이 운영 동작을 바꾸지는 않음 — 코드는 영문 변수명으로 동작

**END OF REPORT**
