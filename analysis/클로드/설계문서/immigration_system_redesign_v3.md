# 출입국 업무 시스템 재설계 v3.0
## 직원용 상담 트리 모델 — 설계 문서

> **문서 목적**: 현재 키워드 검색 중심 구조를 직원 상담 트리(drill-down) 모델로 전환하기 위한 스키마·데이터·API 설계 제안서
> **대상 독자**: 개발자, 데이터 설계자

---

## 0. 핵심 설계 원칙

```
1. 직원이 고객과 대화하면서 단계적으로 좁혀 나간다 → 트리 탐색이 주(主)
2. 트리 탐색 결과로 나온 업무 항목에서 추가 검색을 허용 → 검색은 보조(補助)
3. 사증(비자) 쪽은 재입국 측 구조를 재사용하고 차이점만 오버레이로 관리
4. 결핵 규칙은 조건 데이터로 모델링 — 서술문으로 남기지 않는다
5. 기존 MASTER_ROWS 309건은 폐기하지 않고 result_mapping 의 target 으로 계속 사용
```

---

## 1. 용어 변경 (전 시스템 일괄 적용)

| 기존 용어 | 변경 후 한글 | 변경 후 영문 키 | 적용 범위 |
|---|---|---|---|
| 작성서류 | 사무소 준비서류 | `office_prepared_docs` | DB 컬럼, JSON 키, UI 라벨, API 응답 |
| 첨부서류 | 필요서류 | `required_docs` | DB 컬럼, JSON 키, UI 라벨, API 응답 |
| 수수료 | 인지세 | `fee_rule` | 이미 변경됨, 재확인 |

**마이그레이션 스크립트 적용 대상:**
- `정리.xlsx` → MASTER_ROWS 시트 컬럼 헤더 변경
- `immigration_guidelines_db_v2.json` → 전체 키 일괄 치환
- `backend/routers/guidelines.py` → 응답 필드명 변경
- `frontend/app/(main)/guidelines/page.tsx` → UI 라벨 변경
- `immigration_client_local.js` → 서류패키지() 반환 객체 키 변경

---

## 2. 스키마 수정 제안

### 2-1. MASTER_ROWS 컬럼 변경

```
기존 컬럼                      → 변경 후
─────────────────────────────────────────────────────
form_docs                      → office_prepared_docs
supporting_docs                → required_docs
major_action_std (자유 문자열)  → 아래 3개 컬럼으로 분리
```

**추가 컬럼:**

| 컬럼명 | 타입 | 설명 | 예시 |
|---|---|---|---|
| `major_action_std_code` | string | 내부 매칭용 표준 코드 | `EXTRA_WORK` |
| `major_action_std_label` | string | 데이터 정합성용 표준 라벨 | `체류자격외활동` |
| `display_label` | string | UI 표시용 (공백·기호 포함 허용) | `체류자격외 활동` |

**basis 필드 구조화 (기존 자유 텍스트 → 구조화):**

```json
"basis": {
  "authority_type": "manual",
  "authority_file": "하이코리아 메뉴얼",
  "authority_section": "3장 4절",
  "authority_summary": "체류자격 변경 절차 및 구비서류",
  "priority_rank": 4
}
```

`authority_type` 허용값: `law` | `decree` | `rule` | `manual` | `guideline` | `qa`
`priority_rank`: 1=법령, 2=시행령, 3=규칙·고시, 4=메뉴얼, 5=지침, 6=질의응답

> **주의**: `effective_date` 는 대외비 우려로 UI에 표시하지 않는다. 내부 기록용으로만 보존.

---

### 2-2. 신규 컬렉션 목록

```
immigration_guidelines_db_v3.json
├── master_rows                  [기존, 컬럼명 변경]
├── rules                        [기존 유지]
├── exceptions                   [기존 유지]
├── doc_dictionary               [기존 유지]
├── legacy_ui_map                [기존 유지]
│
├── [신규] basis_registry        ← 법적 근거 마스터 테이블
├── [신규] consultation_entry_points  ← 트리 진입점 목록
├── [신규] question_bank         ← 재사용 가능한 질문 풀
├── [신규] decision_nodes        ← 트리 노드 (질문·정보·결과)
├── [신규] decision_edges        ← 노드 간 연결 (분기 조건)
├── [신규] result_mapping        ← 트리 말단 → master_rows row_id 매핑
├── [신규] tb_rules              ← 결핵 규칙 (조건 데이터)
└── [신규] visa_overlay_rules    ← 사증 단계 오버레이 (차이점만)
```

---

### 2-3. 각 신규 컬렉션 스키마

#### `basis_registry`
```json
{
  "basis_id": "BASIS-001",
  "authority_type": "manual",
  "authority_file": "하이코리아 메뉴얼",
  "authority_section": "체류 > 체류자격 변경허가",
  "authority_summary": "체류자격 변경허가 구비서류 목록",
  "effective_date": "INTERNAL_ONLY",
  "priority_rank": 4,
  "status": "active"
}
```

#### `consultation_entry_points`
```json
{
  "entry_id": "EP-03",
  "display_label": "체류자격 변경",
  "icon": "shuffle",
  "description": "다른 체류자격으로 변경 신청",
  "action_type_filter": ["CHANGE"],
  "root_node_id": "DN-CHANGE-001",
  "sort_order": 3,
  "special_tracks": []
}
```

**전체 진입점 목록 (13개):**

| entry_id | display_label | action_type_filter | root_node_id |
|---|---|---|---|
| EP-01 | 사증 발급 | [VISA_CONFIRM] + visa_overlay | DN-VISA-001 |
| EP-02 | 체류기간 연장 | [EXTEND] | DN-EXTEND-001 |
| EP-03 | 체류자격 변경 | [CHANGE] | DN-CHANGE-001 |
| EP-04 | 체류자격 부여 | [GRANT] | DN-GRANT-001 |
| EP-05 | 체류자격외 활동 | [EXTRA_WORK, ACTIVITY_EXTRA] | DN-EXTRA-001 |
| EP-06 | 근무처 변경·추가 | [WORKPLACE] | DN-WORK-001 |
| EP-07 | 재입국허가 | [REENTRY] | DN-REENTRY-001 |
| EP-08 | 외국인등록·거소신고 | [REGISTRATION, DOMESTIC_RESIDENCE_REPORT] | DN-REG-001 |
| EP-09 | 각종 신고·증명·기타 | [APPLICATION_CLAIM] | DN-MISC-001 |
| EP-10 | 재외동포 트랙 | [CHANGE, EXTEND, EXTRA_WORK] | DN-F4-001 |
| EP-11 | 영주권 | [CHANGE, GRANT] | DN-F5-001 |
| EP-12 | 결혼이민 트랙 | [CHANGE, EXTEND, GRANT] | DN-F6-001 |
| EP-13 | 유학생 트랙 | [CHANGE, EXTEND, EXTRA_WORK] | DN-D2-001 |

#### `question_bank`
```json
{
  "q_id": "Q-001",
  "question_text": "현재 체류자격은 무엇입니까?",
  "question_key": "current_status_code",
  "input_type": "select",
  "options_source": "visa_code_list",
  "reusable": true,
  "used_in_nodes": ["DN-CHANGE-001", "DN-EXTEND-001", "DN-EXTRA-001"]
}
```

```json
{
  "q_id": "Q-005",
  "question_text": "외국인등록을 이미 했습니까?",
  "question_key": "is_registered",
  "input_type": "boolean",
  "options": [
    { "value": "yes", "display": "등록 완료" },
    { "value": "no",  "display": "미등록" }
  ],
  "reusable": true
}
```

```json
{
  "q_id": "Q-010",
  "question_text": "신청인 유형은 무엇입니까?",
  "question_key": "applicant_type",
  "input_type": "select",
  "options": [
    { "value": "self",     "display": "본인 직접" },
    { "value": "family",   "display": "가족" },
    { "value": "employee", "display": "고용된 근로자" },
    { "value": "invitee",  "display": "초청인" }
  ],
  "reusable": true
}
```

#### `decision_nodes`

노드 유형:
- `"question"` — 직원이 고객에게 물어야 할 질문
- `"info"` — 경고·안내 (분기 없이 다음 노드로 진행)
- `"result"` — 말단 노드, result_mapping 으로 연결

```json
{
  "node_id": "DN-CHANGE-001",
  "node_type": "question",
  "q_id": "Q-001",
  "question_text": "현재 체류자격 계열은?",
  "question_key": "current_status_family",
  "options": [
    { "value": "student",    "display": "학생 계열 (D-1, D-2, D-4, D-5, D-8)" },
    { "value": "employment", "display": "취업 계열 (E-1 ~ E-10)" },
    { "value": "residence",  "display": "거주 계열 (F-1 ~ F-6)" },
    { "value": "short",      "display": "단기 체류 (B-1, B-2, C-3)" },
    { "value": "other",      "display": "기타" }
  ],
  "entry_id": "EP-03"
}
```

```json
{
  "node_id": "DN-CHANGE-002",
  "node_type": "question",
  "question_text": "변경하려는 목표 체류자격은?",
  "question_key": "target_status_code",
  "options": [
    { "value": "E-7",  "display": "E-7 (특정활동)" },
    { "value": "F-2",  "display": "F-2 (거주)" },
    { "value": "F-4",  "display": "F-4 (재외동포)" },
    { "value": "F-5",  "display": "F-5 (영주)" },
    { "value": "F-6",  "display": "F-6 (결혼이민)" },
    { "value": "other","display": "기타" }
  ],
  "entry_id": "EP-03"
}
```

```json
{
  "node_id": "DN-CHANGE-INFO-TB",
  "node_type": "info",
  "info_level": "warning",
  "title": "결핵 검사 확인 필요",
  "body": "결핵 고위험국 국적자는 체류자격 변경 전 결핵검사 결과서 필요 여부를 확인하십시오.",
  "rule_refs": ["TB-002"],
  "next_node_id": "DN-CHANGE-RESULT-001"
}
```

```json
{
  "node_id": "DN-CHANGE-RESULT-001",
  "node_type": "result",
  "result_label": "F-4 체류자격 변경",
  "row_ids": ["M1-0261", "M1-0262", "M1-0263"]
}
```

#### `decision_edges`
```json
{
  "edge_id": "EDGE-001",
  "from_node_id": "DN-CHANGE-001",
  "answer_value": "student",
  "answer_display": "학생 계열",
  "to_node_id": "DN-CHANGE-002",
  "condition_expr": null
}
```

```json
{
  "edge_id": "EDGE-002",
  "from_node_id": "DN-CHANGE-001",
  "answer_value": "residence",
  "answer_display": "거주 계열",
  "to_node_id": "DN-CHANGE-002",
  "condition_expr": null
}
```

```json
{
  "edge_id": "EDGE-010",
  "from_node_id": "DN-CHANGE-002",
  "answer_value": "F-4",
  "answer_display": "F-4 (재외동포)",
  "to_node_id": "DN-CHANGE-INFO-TB",
  "condition_expr": {
    "check": "tb_high_risk_nationality",
    "if_true": "DN-CHANGE-INFO-TB",
    "if_false": "DN-CHANGE-RESULT-001"
  }
}
```

#### `result_mapping`
```json
{
  "mapping_id": "RM-001",
  "node_id": "DN-CHANGE-RESULT-001",
  "context_label": "F-4 체류자격 변경",
  "row_ids": ["M1-0261", "M1-0262", "M1-0263"],
  "primary_row_id": "M1-0261",
  "notes": "세부 코드(F-4-1, F-4-2 등)에 따라 구비서류 차이 있음"
}
```

---

## 3. 현재 JSON → v3 마이그레이션 계획

### 단계별 작업

**STEP 1: 컬럼명 일괄 치환 (자동화 가능)**
```python
# 정리.xlsx MASTER_ROWS 시트
rename_map = {
    "form_docs":        "office_prepared_docs",
    "supporting_docs":  "required_docs",
}
# JSON 전체 키 치환
# immigration_guidelines_db_v2.json → immigration_guidelines_db_v3.json
```

**STEP 2: major_action_std 표준화**

현재 불일치 패턴:

| 현재 값 (예시) | 표준 코드 | 표준 라벨 | 표시 라벨 |
|---|---|---|---|
| `체류자격외 활동`, `체류자격외활동` | `EXTRA_WORK` | `체류자격외활동` | `체류자격외 활동` |
| `근무처의 변경·추가`, `근무처 변경·추가` | `WORKPLACE` | `근무처 변경·추가` | `근무처 변경·추가` |
| `재입국허가`, `재입국` | `REENTRY` | `재입국허가` | `재입국허가` |
| `외국인등록` | `REGISTRATION` | `외국인등록` | `외국인등록` |
| `거소신고` | `DOMESTIC_RESIDENCE_REPORT` | `국내거소신고` | `국내거소신고` |

```python
# 마이그레이션 스크립트 예시
STD_ACTION_MAP = {
    "체류자격외 활동": ("EXTRA_WORK", "체류자격외활동", "체류자격외 활동"),
    "체류자격외활동": ("EXTRA_WORK", "체류자격외활동", "체류자격외 활동"),
    "근무처의 변경·추가": ("WORKPLACE", "근무처 변경·추가", "근무처 변경·추가"),
    "근무처 변경·추가": ("WORKPLACE", "근무처 변경·추가", "근무처 변경·추가"),
    # ... 전체 목록 작성
}
for row in master_rows:
    old = row.get("major_action_std", "")
    if old in STD_ACTION_MAP:
        code, std, display = STD_ACTION_MAP[old]
        row["major_action_std_code"] = code
        row["major_action_std_label"] = std
        row["display_label"] = display
```

**STEP 3: basis 구조화**

기존 `basis_section` 자유 텍스트를 파싱하여 `basis` 객체로 변환.
자동 파싱 불가능한 항목은 수동 검토 리스트로 추출.

```python
def parse_basis(raw: str) -> dict:
    # "하이코리아 메뉴얼 3장 4절" 형태 파싱
    if "법" in raw or "령" in raw:
        authority_type = "law"
        priority_rank = 1
    elif "고시" in raw or "규칙" in raw:
        authority_type = "rule"
        priority_rank = 3
    else:
        authority_type = "manual"
        priority_rank = 4
    return {
        "authority_type": authority_type,
        "authority_file": "하이코리아 메뉴얼",
        "authority_section": raw,
        "authority_summary": "",
        "priority_rank": priority_rank
    }
```

**STEP 4: 신규 컬렉션 추가**

트리 데이터는 별도 작업. 초기 버전은 최소 6개 진입점(EP-02~EP-08)에 대한 2레벨 트리만 구축.
EP-01(사증)은 visa_overlay_rules와 연동 후 추가.

---

## 4. 상담 트리 데이터 설계 — 실전 예시

### EP-08: 외국인등록 (가장 먼저 구현 권장)

```
DN-REG-001
  Q: 신청인 구분은?
  ├── 단기 입국 → 등록 대상 아님 안내 (info 노드)
  ├── 장기 입국 (91일 이상 체류 예정) →
  │     DN-REG-002
  │       Q: 결핵 고위험국 국적입니까?
  │       ├── 예 → DN-REG-003
  │       │     Q: 비자 발급 유형은?
  │       │     ├── 전자비자(e-비자) + 당시 결핵 서류 제출 → TB 결과서 필요 (TB-001 룰)
  │       │     ├── 장기 복수 비자 + 발급 후 6개월 이상 경과 후 입국 → TB 결과서 필요 (TB-001 룰)
  │       │     └── 해당 없음 → TB 서류 불필요 →
  │       └── 아니오 →
  │             DN-REG-RESULT-001 (일반 외국인등록)
  └── 재외동포(F-4, F-4-xx) →
        DN-REG-F4-001
          Q: 현재 거소신고 여부?
          ├── 미등록 → DN-REG-RESULT-F4 (재외동포 국내거소신고)
          └── 기등록 → 갱신 안내
```

### EP-03: 체류자격 변경 — 2레벨 예시

```
DN-CHANGE-001
  Q: 현재 체류자격 계열?
  ├── 학생 (D-2, D-4) →
  │     DN-CHANGE-D2-001
  │       Q: 변경 목표?
  │       ├── E-7 → 결핵 확인 → M1-0xxx (D→E 변경)
  │       ├── F-2 → M1-0xxx
  │       └── 기타 → 검색 모드 전환
  ├── 취업 (E-계열) →
  │     DN-CHANGE-E-001
  │       Q: 목표 자격?
  │       ├── F-2 → M1-0xxx
  │       ├── F-4 → 결핵 확인 → M1-0261~M1-0269
  │       └── F-5 → M1-0xxx
  └── 거주 (F-계열) →
        DN-CHANGE-F-001
          Q: 목표 자격?
          ├── F-5 (영주) → M1-0xxx
          └── 기타
```

---

## 5. 결핵(TB) 규칙 구현 구조

### 5-1. 결핵 고위험국 목록 (별도 관리)

```json
{
  "list_id": "TB_HIGH_RISK_COUNTRIES",
  "description": "결핵 고위험국 목록 (법무부 고시 기준)",
  "source": "법무부 고시",
  "countries": [
    "PHL", "CHN", "IDN", "VNM", "MMR", "KHM", "THA",
    "IND", "BGD", "PAK", "NPL", "LKA", "RUS", "UKR",
    "KAZ", "UZB", "KGZ", "TJK", "TKM", "MNG",
    "NGA", "ETH", "KEN", "TZA", "ZMB", "GHA"
  ],
  "note": "목록은 법무부 고시 개정 시 반드시 갱신"
}
```

### 5-2. 결핵 규칙 객체 (rule_code 기반)

**TB-001: 외국인등록 시 결핵 서류 요건 (입국 후 등록 단계)**

```json
{
  "rule_code": "TB-001",
  "rule_name": "결핵 고위험국 - 외국인등록 시 결핵 서류 요건",
  "trigger_scope": "REGISTRATION",
  "trigger_stage": "alien_registration",
  "condition_expr": {
    "AND": [
      { "field": "nationality", "op": "in", "value": "TB_HIGH_RISK_COUNTRIES" },
      {
        "OR": [
          {
            "AND": [
              { "field": "entry_visa_type", "op": "eq", "value": "e_visa" },
              { "field": "tb_cert_required_at_visa", "op": "eq", "value": true }
            ]
          },
          {
            "AND": [
              { "field": "visa_type", "op": "eq", "value": "long_term_multiple" },
              { "field": "months_since_visa_issuance", "op": "gte", "value": 6 }
            ]
          }
        ]
      }
    ]
  },
  "required_doc": "결핵검사 결과서",
  "doc_issuer": "보건복지부 지정 의료기관",
  "exemption_expr": {
    "field": "tb_cert_submitted_at_visa_stage",
    "op": "eq",
    "value": true
  },
  "exemption_display": "사증 발급 단계에서 결핵검사 결과서를 이미 제출한 경우 면제",
  "warning_text": "결핵 고위험국 출신 외국인은 외국인등록 시 결핵검사 결과서를 제출하여야 합니다. 단, 사증 발급 단계에서 이미 제출한 경우 면제됩니다.",
  "legal_basis": {
    "authority_type": "rule",
    "authority_file": "결핵예방법 시행규칙",
    "authority_section": "제4조의2",
    "priority_rank": 3
  },
  "status": "active"
}
```

**TB-002: 체류허가 단계 결핵 서류 요건 (연장·변경 신청 시)**

```json
{
  "rule_code": "TB-002",
  "rule_name": "결핵 고위험국 - 체류허가 신청 시 결핵 서류 요건",
  "trigger_scope": ["EXTEND", "CHANGE"],
  "trigger_stage": "stay_permission",
  "condition_expr": {
    "AND": [
      { "field": "nationality", "op": "in", "value": "TB_HIGH_RISK_COUNTRIES" },
      {
        "field": "continuous_stay_in_high_risk_country_months",
        "op": "gte",
        "value": 6,
        "within_days_before_application": 365
      }
    ]
  },
  "required_doc": "결핵검사 결과서",
  "doc_issuer": "보건복지부 지정 의료기관",
  "exemption_expr": null,
  "exemption_display": null,
  "warning_text": "신청일 기준 최근 1년 이내에 결핵 고위험국에 6개월 이상 연속 체류한 경우 결핵검사 결과서 제출이 필요합니다.",
  "legal_basis": {
    "authority_type": "rule",
    "authority_file": "결핵예방법 시행규칙",
    "authority_section": "제4조의2",
    "priority_rank": 3
  },
  "status": "active"
}
```

### 5-3. 결핵 규칙 평가 로직 (백엔드 의사 코드)

```python
def evaluate_tb_rule(rule_code: str, context: dict) -> dict:
    """
    context 예시:
    {
        "nationality": "PHL",
        "entry_visa_type": "e_visa",
        "tb_cert_required_at_visa": True,
        "tb_cert_submitted_at_visa_stage": False,
        "trigger_scope": "REGISTRATION"
    }
    """
    rule = TB_RULES[rule_code]
    
    # 트리거 확인
    if context["trigger_scope"] not in rule["trigger_scope"]:
        return {"required": False}
    
    # 조건 평가 (condition_expr 재귀 평가)
    required = evaluate_expr(rule["condition_expr"], context)
    
    if not required:
        return {"required": False}
    
    # 면제 조건 확인
    if rule["exemption_expr"]:
        exempted = evaluate_expr(rule["exemption_expr"], context)
        if exempted:
            return {"required": False, "exempted": True}
    
    return {
        "required": True,
        "doc": rule["required_doc"],
        "issuer": rule["doc_issuer"],
        "warning": rule["warning_text"],
        "basis": rule["legal_basis"]
    }
```

---

## 6. 사증(비자) 오버레이 설계 원칙

### 핵심 원칙

> **"사증 단계 분석은 체류 단계 구조를 최대한 재사용한다. 자격 판단 로직, 대상자 유형, 서류 구성이 실질적으로 동일한 경우에는 체류 측 master_row를 참조하고, 사증 특유의 차이점만 오버레이로 별도 관리한다."**

이 원칙은 CLAUDE.md 및 개발자 노트에 명시하여 이후 데이터 추가 시 중복 입력을 방지한다.

### 6-1. 체류 측과 공통인 항목 (재사용)

- 자격 요건 판단 (E-7 전문인력 기준, F-4 재외동포 자격 등)
- 대상자 유형 분류 (취업자, 유학생, 가족 등)
- 서류 구성 대부분 (사업자등록증, 졸업증명서 등)
- 결핵 규칙 (TB-001, TB-002 → 체류 측과 동일 규칙 참조)
- 예외 조건 대부분

### 6-2. 사증 특유 차이점 (오버레이로 관리)

| 차이 항목 | 설명 | 오버레이 필드 |
|---|---|---|
| 신청 장소 | 해외 공관 vs 국내 출입국사무소 | `application_location` |
| 발급 유형 | 사증발급 vs 사증발급인정서 | `visa_issuance_type` |
| 초청인·보증인 요건 | 입국 전 초청장, 신원보증서 | `sponsor_required`, `sponsor_docs` |
| 공문·외교 경로 | 공문·외교각서·초청 경로 | `official_route` |
| 서류 제출 시점 | 입국 전 제출 vs 입국 후 제출 | `doc_timing` |
| TB 사증-등록 연계 | 사증 발급 시 TB 제출 → 등록 면제 | `tb_cert_carries_over` |

### 6-3. `visa_overlay_rules` 스키마

```json
{
  "overlay_id": "VISA-F4-001",
  "base_row_id": "M1-0261",
  "base_action_type": "CHANGE",
  "visa_stage": "entry_visa",
  "visa_issuance_type": "visa_confirm",
  "application_location": "overseas_consulate",
  "sponsor_required": false,
  "sponsor_docs": [],
  "official_route": null,
  "doc_timing": "pre_entry",
  "additional_office_prepared_docs": [],
  "additional_required_docs": ["사증발급신청서", "여권"],
  "removed_docs": ["통합신청서"],
  "tb_cert_carries_over": true,
  "notes": "재외동포(F-4) 사증발급인정서는 체류자격 변경과 자격 요건이 동일하나 신청 장소·서류 시점이 다름"
}
```

### 6-4. 사증 트리 진입점 (EP-01) 설계 방향

```
DN-VISA-001
  Q: 신청 방식?
  ├── 국내에서 사증발급인정서 신청 → DN-VISA-CONFIRM-001
  │     Q: 목표 체류자격?
  │     └── (체류 측 EP-02~EP-04 트리와 동일 분기 재사용)
  │         → result: visa_overlay + base_row_id
  └── 해외 공관에서 사증 신청 → DN-VISA-OVERSEAS-001
        Q: 목표 체류자격?
        └── (체류 측 구조 재사용 + 초청인·공문 분기 추가)
```

---

## 7. 수정된 API 엔드포인트 제안

### 기존 유지 (prefix: `/api/guidelines`)

| 메서드 | 경로 | 변경사항 |
|---|---|---|
| GET | `/stats` | 변경 없음 |
| GET | `/search/query` | 응답 키 `form_docs`→`office_prepared_docs`, `supporting_docs`→`required_docs` |
| GET | `/code/{code}` | 동일 |
| GET | `/rules` | 동일 |
| GET | `/exceptions` | 동일 |
| GET | `/docs/lookup` | 동일 |
| GET | `/` | 동일 |
| GET | `/{row_id}` | 응답 키 변경, `basis` 구조화 |

### 신규 추가 (상담 트리)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/tree/entry-points` | 전체 진입점 목록 반환 |
| GET | `/tree/node/{node_id}` | 특정 노드 정보 + 연결된 엣지 반환 |
| GET | `/tree/edges/{node_id}` | 특정 노드의 출발 엣지 목록 반환 |
| POST | `/tree/navigate` | 현재 노드 + 선택값 → 다음 노드 계산 |
| GET | `/tree/result/{node_id}` | 말단 노드의 연결 master_rows 반환 |
| POST | `/tb/evaluate` | context 입력 → 결핵 규칙 평가 결과 반환 |
| GET | `/tb/rules` | 결핵 규칙 목록 반환 |
| GET | `/visa-overlay/{base_row_id}` | 특정 체류 row의 사증 오버레이 반환 |

### `/tree/navigate` 요청/응답 예시

```json
// 요청
POST /api/guidelines/tree/navigate
{
  "current_node_id": "DN-CHANGE-001",
  "answer_value": "student",
  "session_context": {
    "nationality": "PHL",
    "is_registered": true
  }
}

// 응답
{
  "next_node_id": "DN-CHANGE-D2-001",
  "next_node": {
    "node_type": "question",
    "question_text": "변경하려는 목표 체류자격은?",
    "options": [...]
  },
  "active_warnings": [],
  "breadcrumb": [
    { "node_id": "DN-CHANGE-001", "answer": "학생 계열" },
    { "node_id": "DN-CHANGE-D2-001", "answer": null }
  ]
}
```

### `/tb/evaluate` 요청/응답 예시

```json
// 요청
POST /api/guidelines/tb/evaluate
{
  "trigger_scope": "REGISTRATION",
  "nationality": "PHL",
  "entry_visa_type": "e_visa",
  "tb_cert_required_at_visa": true,
  "tb_cert_submitted_at_visa_stage": false
}

// 응답
{
  "rules_evaluated": ["TB-001"],
  "result": {
    "required": true,
    "doc": "결핵검사 결과서",
    "issuer": "보건복지부 지정 의료기관",
    "warning": "결핵 고위험국 출신 외국인은 외국인등록 시 결핵검사 결과서를 제출하여야 합니다.",
    "basis": {
      "authority_type": "rule",
      "authority_file": "결핵예방법 시행규칙",
      "authority_section": "제4조의2"
    }
  }
}
```

---

## 8. 검색 vs 트리 탐색 — 분리 원칙

### 트리 탐색이 주(主) — 이런 상황

- 고객이 "어떤 업무를 해야 할지 모르는" 상태로 내방
- 체류자격 변경·연장 등 복합 조건이 개입되는 업무
- 결핵 규칙, 예외 조건 등 단계적 확인이 필요한 업무
- 초보 직원이 빠짐없이 체크리스트를 따라야 하는 상황

**UI 형태**: 단계별 질문 → 선택 → 다음 질문 → 결과 페이지

### 검색이 보조(補助) — 이런 상황

- 직원이 이미 업무 종류를 알고 있고 서류만 빠르게 확인할 때
- 트리 탐색 결과 화면에서 "다른 유사 업무" 추가 확인 시
- 특정 서류명이 어느 업무에 쓰이는지 역방향 조회 시
- 고급 직원의 빠른 참조 모드

**UI 형태**: 현재 `/guidelines` 페이지의 검색창 + 결과 카드

### 프론트엔드 구현 권장 구조

```
/guidelines               ← 현재 검색 페이지 유지 (고급 직원 검색 모드)
/guidelines/consult       ← 신규: 상담 트리 진입 화면 (진입점 카드 13개)
/guidelines/consult/[...path]  ← 신규: 트리 탐색 (동적 라우팅)
/guidelines/[row_id]      ← 신규: 특정 업무 상세 (트리 결과 or 직접 링크)
```

---

## 9. 구현 우선순위 권장

| 우선순위 | 작업 | 예상 공수 |
|---|---|---|
| 1 | 용어 일괄 변경 (STEP 1) | 반나절 — 스크립트 자동화 |
| 2 | major_action_std 표준화 (STEP 2) | 반나절 |
| 3 | TB 규칙 데이터 작성 (TB-001, TB-002) | 1일 |
| 4 | 진입점 13개 + EP-08(외국인등록) 트리 1개 구현 | 2일 |
| 5 | EP-02(연장), EP-03(변경) 트리 구현 | 3일 |
| 6 | `/tree/navigate` API 구현 | 1일 |
| 7 | 프론트엔드 `/guidelines/consult` 페이지 | 3일 |
| 8 | 사증 오버레이 구조 데이터 작성 | 2일 |
| 9 | basis 구조화 (STEP 3) | 1일 |

---

## 부록: 현재 구조와 v3 대응 표

| 기존 | v3 변경 | 비고 |
|---|---|---|
| `form_docs` | `office_prepared_docs` | 일괄 치환 |
| `supporting_docs` | `required_docs` | 일괄 치환 |
| `major_action_std` (자유텍스트) | `major_action_std_code` + `major_action_std_label` + `display_label` | 분리 |
| `basis_section` (자유텍스트) | `basis` (구조화 객체) | 점진적 마이그레이션 |
| 없음 | `consultation_entry_points` | 신규 |
| 없음 | `question_bank` + `decision_nodes` + `decision_edges` | 신규 |
| 없음 | `result_mapping` | 신규 |
| 없음 | `tb_rules` | 신규 |
| 없음 | `visa_overlay_rules` | 신규 |
| `exceptions` (자유텍스트 위주) | `exceptions` + TB 규칙으로 분리 | 결핵 항목 이관 |

---

*작성일: 2026-04-14 | 버전: v3.0 설계 초안*
