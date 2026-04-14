# 출입국 업무 시스템 재설계 v3.1
## 직원용 상담 트리 모델 — 종합 설계 문서

> **목적**: 현재 검색 중심 구조를 직원 상담 트리(drill-down) 모델로 전환  
> **대상**: 개발자, 데이터 설계자  
> **기준 날짜**: 2026-04-14

---

## 목차

1. 용어 정의 (Terminology)
2. 스키마 수정 제안
3. 현재 JSON → v3 마이그레이션 계획
4. 상담 트리 데이터 설계
5. 결핵(TB) 규칙 구현 구조
6. 사증 발급 vs 사증발급인정서 구분
7. 사증 오버레이 설계 원칙
8. API 엔드포인트 제안
9. 검색 모드 vs 트리 모드 행동 명세
10. 문서자동작성 딥링크 설계
11. 검색 vs 트리 탐색 분리 원칙

---

## 1. 용어 정의

### 1-1. 전 시스템 일괄 적용 용어 변경

| 기존 | 변경 후 한글 | 영문 키 | 적용 범위 |
|---|---|---|---|
| 작성서류 | 사무소 준비서류 | `office_prepared_docs` | DB, JSON, UI, API, HTML |
| 첨부서류 | 필요서류 | `required_docs` | DB, JSON, UI, API, HTML |
| 수수료 | **인지세** (유지) | `fee_rule` | UI 표시는 `인지세` 고정 |

**인지세 주의**: UI 표시 라벨은 `인지세`로 고정한다. 내부 필드명은 `fee_rule`을 유지하며 금액·조건 구조는 별도로 관리할 수 있다. "수수료"로 되돌리지 않는다.

### 1-2. 사증 관련 개념 구분 (신규 표준화)

| 개념 | 한글 표준 라벨 | 내부 코드 | 설명 |
|---|---|---|---|
| 사증 발급 | 사증 발급 | `VISA_ISSUANCE` | 해외 신청인이 재외공관에 직접 신청하여 사증을 발급받는 절차 |
| 사증발급인정서 | 사증발급인정서 | `VISA_CONFIRMATION` | 국내 초청인이 먼저 출입국사무소에 인정서를 신청하고, 해외 신청인이 그 인정서를 가지고 재외공관에서 사증을 받는 절차 |

이 두 개념을 하나의 "사증" 범주로 합치지 않는다. 트리, 스키마, API, UI 전 구간에서 별도로 취급한다.

---

## 2. 스키마 수정 제안

### 2-1. MASTER_ROWS 컬럼 변경 목록

```
기존 컬럼명               → v3 컬럼명
──────────────────────────────────────────
form_docs               → office_prepared_docs
supporting_docs         → required_docs
major_action_std        → (아래 3개로 분리)
basis_section (자유텍스트) → basis (구조화 객체)
```

**추가 컬럼:**

| 컬럼명 | 타입 | 설명 | 예시 값 |
|---|---|---|---|
| `major_action_std_code` | string | 내부 매칭용 코드 | `"CHANGE"` |
| `major_action_std_label` | string | 데이터 정합성용 표준 라벨 | `"체류자격 변경"` |
| `display_label` | string | UI 표시용 | `"체류자격 변경허가"` |
| `quickdoc_category` | string | 문서자동작성 매핑: 대분류 | `"체류"` |
| `quickdoc_minwon` | string | 문서자동작성 매핑: 민원 | `"변경"` |
| `quickdoc_kind` | string | 문서자동작성 매핑: 종류 | `"F"` |
| `quickdoc_detail` | string | 문서자동작성 매핑: 세부 | `"4"` |

`quickdoc_*` 필드는 딥링크 생성 시 직접 사용한다. MASTER_ROWS에 미리 채워두면 런타임 매핑 로직 불필요.

### 2-2. `basis` 구조화 객체

기존 자유 텍스트 `basis_section`을 아래 구조로 대체한다.

```json
"basis": {
  "authority_type": "manual",
  "authority_file": "체류 메뉴얼",
  "authority_section": "3장 4절 체류자격 변경허가",
  "authority_summary": "체류자격 변경 신청 구비서류 및 절차",
  "effective_date": null,
  "ui_expose": false,
  "priority_rank": 4
}
```

**필드 규칙:**
- `authority_type`: `"law"` | `"decree"` | `"rule"` | `"manual"` | `"guideline"` | `"qa"`
- `priority_rank`: 1=법령, 2=시행령, 3=규칙·고시, 4=메뉴얼, 5=지침, 6=질의응답
- `effective_date`: 실제 날짜 문자열(`"2024-01-01"`) 또는 `null`. **절대 `"INTERNAL_ONLY"` 같은 플레이스홀더 문자열을 날짜 필드에 넣지 않는다.**
- `ui_expose`: `true`이면 UI에 표시, `false`이면 내부 참조용으로만 보관

### 2-3. 신규 컬렉션 목록

```
immigration_guidelines_db_v3.json
│
├── master_rows              [기존, 컬럼명 변경]
├── rules                    [기존 유지]
├── exceptions               [기존 유지]
├── doc_dictionary           [기존 유지]
├── legacy_ui_map            [기존 유지]
│
├── [신규] basis_registry         ← 법적 근거 마스터 테이블
├── [신규] consultation_entry_points
├── [신규] question_bank
├── [신규] decision_nodes
├── [신규] decision_edges
├── [신규] result_mapping         ← 말단 노드 → master_rows 매핑
├── [신규] tb_rules               ← 결핵 규칙 (조건 데이터)
├── [신규] tb_high_risk_countries ← 결핵 고위험국 목록 (공식 목록 전체)
└── [신규] visa_overlay_rules     ← 사증 단계 오버레이
```

### 2-4. `result_mapping` 상세 스키마

```json
{
  "mapping_id": "RM-CHANGE-F4-001",
  "node_id": "DN-CHANGE-F4-RESULT",
  "context_label": "F-4 재외동포 체류자격 변경",
  "primary_row_id": "M1-0261",
  "secondary_row_ids": ["M1-0262", "M1-0263", "M1-0264"],
  "disambiguation_question_ids": ["Q-F4-SUBTYPE"],
  "result_confidence": "high",
  "notes": "세부 코드(F-4-1~F-4-99)에 따라 서류 차이. 세부 질문으로 좁혀야 함.",
  "quickdoc_params": {
    "category": "체류",
    "minwon": "변경",
    "kind": "F",
    "detail": "4"
  }
}
```

`result_confidence`: `"high"` | `"medium"` | `"low"`
- `"high"`: 하나의 row로 확정
- `"medium"`: 2~3개 row 후보, 추가 질문 1개로 좁힘
- `"low"`: 다수 후보, 직접 목록 제시

`disambiguation_question_ids`가 비어있지 않으면 UI는 결과를 보여주기 전에 추가 좁히기 질문을 한 번 더 제시한다.

### 2-5. `action_type` ENUM 표준화

현재 불일치 패턴과 표준값:

| 기존 값 (혼용) | 표준 코드 | 표준 라벨 | 표시 라벨 |
|---|---|---|---|
| `체류자격외 활동`, `체류자격외활동` | `EXTRA_WORK` | `체류자격외활동` | `체류자격외 활동` |
| `근무처의 변경·추가`, `근무처 변경·추가` | `WORKPLACE` | `근무처 변경·추가` | `근무처 변경·추가` |
| `재입국허가`, `재입국` | `REENTRY` | `재입국허가` | `재입국허가` |
| `사증발급인정서` | `VISA_CONFIRMATION` | `사증발급인정서` | `사증발급인정서` |
| (신규) 사증 발급 | `VISA_ISSUANCE` | `사증 발급` | `사증 발급` |

---

## 3. 마이그레이션 계획 (v2 → v3)

### STEP 1 — 컬럼명 일괄 치환 (자동화)

```python
# migrate_v2_to_v3.py

COLUMN_RENAMES = {
    "form_docs":       "office_prepared_docs",
    "supporting_docs": "required_docs",
}

STD_ACTION_MAP = {
    "체류자격외 활동":      ("EXTRA_WORK",  "체류자격외활동",    "체류자격외 활동"),
    "체류자격외활동":       ("EXTRA_WORK",  "체류자격외활동",    "체류자격외 활동"),
    "근무처의 변경·추가":   ("WORKPLACE",   "근무처 변경·추가",  "근무처 변경·추가"),
    "근무처 변경·추가":     ("WORKPLACE",   "근무처 변경·추가",  "근무처 변경·추가"),
    "재입국허가":           ("REENTRY",     "재입국허가",        "재입국허가"),
    "재입국":              ("REENTRY",     "재입국허가",        "재입국허가"),
    "체류자격 변경허가":    ("CHANGE",      "체류자격 변경",     "체류자격 변경허가"),
    "체류기간 연장허가":    ("EXTEND",      "체류기간 연장",     "체류기간 연장허가"),
    "외국인등록":          ("REGISTRATION","외국인등록",        "외국인등록"),
    "국내거소신고":        ("DOMESTIC_RESIDENCE_REPORT","국내거소신고","국내거소신고"),
    "사증발급인정서":      ("VISA_CONFIRMATION","사증발급인정서","사증발급인정서"),
}

def migrate_row(row: dict) -> dict:
    # 1. 컬럼명 치환
    for old, new in COLUMN_RENAMES.items():
        if old in row:
            row[new] = row.pop(old)
    # 2. major_action_std 분리
    old_std = row.get("major_action_std", "")
    if old_std in STD_ACTION_MAP:
        code, label, display = STD_ACTION_MAP[old_std]
        row["major_action_std_code"]  = code
        row["major_action_std_label"] = label
        row["display_label"]          = display
    else:
        row["major_action_std_code"]  = row.get("action_type", "")
        row["major_action_std_label"] = old_std
        row["display_label"]          = old_std
    # 3. basis 구조화
    raw_basis = row.pop("basis_section", "")
    row["basis"] = parse_basis_text(raw_basis)
    # 4. quickdoc 매핑 추가
    row.update(resolve_quickdoc_params(row))
    return row
```

### STEP 2 — `quickdoc_*` 필드 일괄 채우기

아래 매핑 테이블 기준으로 각 row에 `quickdoc_category`, `quickdoc_minwon`, `quickdoc_kind`, `quickdoc_detail`을 채운다.

```python
# action_type + detailed_code 접두어 → (category, minwon, kind, detail)
QUICKDOC_MAP = {
    ("CHANGE",      "F-1"):  ("체류", "변경", "F", "1"),
    ("CHANGE",      "F-2"):  ("체류", "변경", "F", "2"),
    ("CHANGE",      "F-3"):  ("체류", "변경", "F", "3"),
    ("CHANGE",      "F-4"):  ("체류", "변경", "F", "4"),
    ("CHANGE",      "F-5"):  ("체류", "변경", "F", "5"),
    ("CHANGE",      "F-6"):  ("체류", "변경", "F", "6"),
    ("CHANGE",      "H-2"):  ("체류", "변경", "H2", ""),
    ("CHANGE",      "E-7"):  ("체류", "변경", "E7", ""),
    ("CHANGE",      "D-2"):  ("체류", "변경", "D", "2"),
    ("CHANGE",      "D-4"):  ("체류", "변경", "D", "4"),
    ("CHANGE",      "D-8"):  ("체류", "변경", "D", "8"),
    ("CHANGE",      "D-10"): ("체류", "변경", "D", "10"),
    ("EXTEND",      "F-1"):  ("체류", "연장", "F", "1"),
    ("EXTEND",      "F-2"):  ("체류", "연장", "F", "2"),
    ("EXTEND",      "F-3"):  ("체류", "연장", "F", "3"),
    ("EXTEND",      "F-4"):  ("체류", "연장", "F", "4"),
    ("EXTEND",      "F-6"):  ("체류", "연장", "F", "6"),
    ("EXTEND",      "H-2"):  ("체류", "연장", "H2", ""),
    ("EXTEND",      "E-7"):  ("체류", "연장", "E7", ""),
    ("REGISTRATION","F-1"):  ("체류", "등록", "F", "1"),
    ("REGISTRATION","F-2"):  ("체류", "등록", "F", "2"),
    ("REGISTRATION","F-3"):  ("체류", "등록", "F", "3"),
    ("REGISTRATION","F-4"):  ("체류", "등록", "F", "4"),
    ("REGISTRATION","F-6"):  ("체류", "등록", "F", "6"),
    ("REGISTRATION","H-2"):  ("체류", "등록", "H2", ""),
    ("REGISTRATION","E-7"):  ("체류", "등록", "E7", ""),
    ("GRANT",       "F-2"):  ("체류", "부여", "F", "2"),
    ("GRANT",       "F-3"):  ("체류", "부여", "F", "3"),
    ("GRANT",       "F-5"):  ("체류", "부여", "F", "5"),
    ("EXTRA_WORK",  "D-2"):  ("체류", "기타", "D", "2"),
    ("EXTRA_WORK",  "D-4"):  ("체류", "기타", "D", "4"),
    ("DOMESTIC_RESIDENCE_REPORT", "F-4"): ("체류", "신고", "등록사항", ""),
}

def resolve_quickdoc_params(row: dict) -> dict:
    action = row.get("action_type", "")
    code   = row.get("detailed_code", "")
    # F-4-25 → F-4 접두어 추출
    prefix = "-".join(code.split("-")[:2]) if code else ""
    key    = (action, prefix)
    if key in QUICKDOC_MAP:
        cat, min_, kind, detail = QUICKDOC_MAP[key]
        return {"quickdoc_category": cat, "quickdoc_minwon": min_,
                "quickdoc_kind": kind, "quickdoc_detail": detail}
    return {"quickdoc_category": "", "quickdoc_minwon": "",
            "quickdoc_kind": "", "quickdoc_detail": ""}
```

### STEP 3 — basis 구조화 (반자동)

```python
def parse_basis_text(raw: str) -> dict:
    raw = raw.strip()
    if not raw:
        return {"authority_type": "manual", "authority_file": "하이코리아 메뉴얼",
                "authority_section": "", "authority_summary": "",
                "effective_date": None, "ui_expose": False, "priority_rank": 4}
    
    if any(k in raw for k in ["법 제", "시행령", "시행규칙"]):
        auth_type, rank = "law", 1
    elif "고시" in raw:
        auth_type, rank = "rule", 3
    elif "메뉴얼" in raw or "지침" in raw:
        auth_type, rank = "manual", 4
    else:
        auth_type, rank = "manual", 4
    
    return {
        "authority_type": auth_type,
        "authority_file": "하이코리아 메뉴얼",
        "authority_section": raw,
        "authority_summary": "",
        "effective_date": None,
        "ui_expose": False,
        "priority_rank": rank
    }
```

**자동 파싱이 불확실한 항목**은 별도 목록으로 추출하여 수동 검토 후 `ui_expose: true`로 전환한다. 확인되지 않은 법령 인용을 `ui_expose: true`로 노출하지 않는다.

---

## 4. 상담 트리 데이터 설계

### 4-1. `consultation_entry_points` (13개)

| entry_id | display_label | action_type_filter | root_node_id | sort |
|---|---|---|---|---|
| EP-01 | 사증 발급 | [VISA_ISSUANCE, VISA_CONFIRMATION] | DN-VISA-001 | 1 |
| EP-02 | 체류기간 연장 | [EXTEND] | DN-EXTEND-001 | 2 |
| EP-03 | 체류자격 변경 | [CHANGE] | DN-CHANGE-001 | 3 |
| EP-04 | 체류자격 부여 | [GRANT] | DN-GRANT-001 | 4 |
| EP-05 | 체류자격외 활동 | [EXTRA_WORK, ACTIVITY_EXTRA] | DN-EXTRA-001 | 5 |
| EP-06 | 근무처 변경·추가 | [WORKPLACE] | DN-WORK-001 | 6 |
| EP-07 | 재입국허가 | [REENTRY] | DN-REENTRY-001 | 7 |
| EP-08 | 외국인등록·거소신고 | [REGISTRATION, DOMESTIC_RESIDENCE_REPORT] | DN-REG-001 | 8 |
| EP-09 | 각종 신고·증명·기타 | [APPLICATION_CLAIM] | DN-MISC-001 | 9 |
| EP-10 | 재외동포 트랙 | [CHANGE, EXTEND, EXTRA_WORK] | DN-F4-001 | 10 |
| EP-11 | 영주권 | [CHANGE, GRANT] | DN-F5-001 | 11 |
| EP-12 | 결혼이민 트랙 | [CHANGE, EXTEND, GRANT] | DN-F6-001 | 12 |
| EP-13 | 유학생 트랙 | [CHANGE, EXTEND, EXTRA_WORK] | DN-D2-001 | 13 |

특별 트랙(EP-10~EP-13)은 빠른 접근용이며, 메인 카테고리(EP-02~EP-09)와 내용이 겹친다. UI에서는 "특별 트랙" 섹션으로 시각적 구분만 하고 중복 혼동을 방지한다.

### 4-2. `decision_nodes` 스키마

```json
{
  "node_id": "DN-CHANGE-001",
  "node_type": "question",
  "entry_id": "EP-03",
  "question_text": "현재 체류자격 계열을 선택하세요",
  "question_key": "current_status_family",
  "options": [
    { "value": "F",       "display": "거주 계열 (F-1 ~ F-6, H-2)" },
    { "value": "student", "display": "유학생 계열 (D-2, D-4)" },
    { "value": "E",       "display": "취업 계열 (E-1 ~ E-10, E-7)" },
    { "value": "short",   "display": "단기 체류 (B-1, B-2, C-3)" },
    { "value": "other",   "display": "기타·불명확" }
  ]
}
```

```json
{
  "node_id": "DN-CHANGE-F-TARGET",
  "node_type": "question",
  "entry_id": "EP-03",
  "question_text": "변경하려는 목표 체류자격은?",
  "question_key": "target_status_code",
  "options": [
    { "value": "F-2",  "display": "F-2 (거주)" },
    { "value": "F-4",  "display": "F-4 (재외동포)" },
    { "value": "F-5",  "display": "F-5 (영주)" },
    { "value": "F-6",  "display": "F-6 (결혼이민)" },
    { "value": "H-2",  "display": "H-2 (방문취업)" },
    { "value": "other","display": "기타" }
  ]
}
```

```json
{
  "node_id": "DN-CHANGE-F4-TB-CHECK",
  "node_type": "info",
  "entry_id": "EP-03",
  "info_level": "warning",
  "title": "결핵 검사 확인 필요",
  "body": "F-4로 변경하는 경우 결핵 고위험국 국적자는 결핵검사 결과서 필요 여부를 반드시 확인하십시오. (TB-002 규칙 참조)",
  "rule_refs": ["TB-002"],
  "next_node_id": "DN-CHANGE-F4-RESULT"
}
```

```json
{
  "node_id": "DN-CHANGE-F4-RESULT",
  "node_type": "result",
  "entry_id": "EP-03",
  "mapping_id": "RM-CHANGE-F4-001"
}
```

### 4-3. `decision_edges` 스키마

```json
{
  "edge_id": "EDGE-CHANGE-001",
  "from_node_id": "DN-CHANGE-001",
  "answer_value": "F",
  "answer_display": "거주 계열",
  "to_node_id": "DN-CHANGE-F-TARGET",
  "condition_expr": null
}
```

```json
{
  "edge_id": "EDGE-CHANGE-F4-001",
  "from_node_id": "DN-CHANGE-F-TARGET",
  "answer_value": "F-4",
  "answer_display": "F-4 (재외동포)",
  "to_node_id": "DN-CHANGE-F4-TB-CHECK",
  "condition_expr": {
    "if": { "field": "nationality", "op": "in", "value": "TB_HIGH_RISK_COUNTRIES" },
    "then_node": "DN-CHANGE-F4-TB-CHECK",
    "else_node": "DN-CHANGE-F4-RESULT"
  }
}
```

조건부 엣지는 `condition_expr`에 평가 로직을 담는다. `condition_expr`이 `null`이면 무조건 다음 노드로 진행.

### 4-4. EP-08 외국인등록 트리 (완전 예시)

```
DN-REG-001
  Q: 신청인 유형?
  ├── [단기 체류] → DN-REG-SHORT (info: 등록 대상 아님 안내)
  ├── [장기 체류 외국인] → DN-REG-002
  │     Q: 결핵 고위험국 국적?
  │     ├── [예] → DN-REG-TB-001
  │     │     Q: 입국 비자 유형?
  │     │     ├── [전자비자, 비자 발급 시 TB 서류 제출] → DN-REG-TB-RESULT (결과: TB 결과서 필요)
  │     │     ├── [장기복수비자 + 발급 후 6개월 이상 경과 입국] → DN-REG-TB-RESULT
  │     │     └── [해당 없음] → DN-REG-RESULT-GENERAL
  │     └── [아니오] → DN-REG-RESULT-GENERAL
  └── [재외동포(F-4 계열)] → DN-REG-F4-001
        Q: 현재 거소신고 여부?
        ├── [미등록] → DN-REG-F4-RESULT (국내거소신고)
        └── [기등록] → DN-REG-F4-RENEW (갱신 안내)
```

---

## 5. 결핵(TB) 규칙 구현 구조

### 5-1. 설계 원칙

결핵 규칙의 법적 근거는 **현재 사용 중인 공식 메뉴얼(체류 메뉴얼, 사증 메뉴얼)을 1차 출처**로 한다.  
법령(결핵예방법, 시행규칙 등) 조항 번호가 메뉴얼에서 명확히 확인된 경우에만 `authority_type: "law"`로 기재한다.  
확인되지 않은 법령 번호를 추정으로 기입하지 않는다.

### 5-2. `tb_high_risk_countries` (공식 목록 전체)

```json
{
  "list_id": "TB_HIGH_RISK_COUNTRIES",
  "source_file": "출입국 체류 메뉴얼",
  "source_section": "결핵 고위험국가 지정 고시",
  "last_verified": "2024-01",
  "ui_expose": false,
  "countries": [
    { "name_ko": "필리핀",             "iso": "PHL" },
    { "name_ko": "중국",               "iso": "CHN" },
    { "name_ko": "인도네시아",          "iso": "IDN" },
    { "name_ko": "베트남",             "iso": "VNM" },
    { "name_ko": "미얀마",             "iso": "MMR" },
    { "name_ko": "캄보디아",           "iso": "KHM" },
    { "name_ko": "태국",               "iso": "THA" },
    { "name_ko": "인도",               "iso": "IND" },
    { "name_ko": "방글라데시",          "iso": "BGD" },
    { "name_ko": "파키스탄",           "iso": "PAK" },
    { "name_ko": "네팔",               "iso": "NPL" },
    { "name_ko": "스리랑카",           "iso": "LKA" },
    { "name_ko": "러시아",             "iso": "RUS" },
    { "name_ko": "우크라이나",          "iso": "UKR" },
    { "name_ko": "카자흐스탄",          "iso": "KAZ" },
    { "name_ko": "우즈베키스탄",        "iso": "UZB" },
    { "name_ko": "키르기스스탄",        "iso": "KGZ" },
    { "name_ko": "타지키스탄",          "iso": "TJK" },
    { "name_ko": "투르크메니스탄",      "iso": "TKM" },
    { "name_ko": "아제르바이잔",        "iso": "AZE" },
    { "name_ko": "몽골",               "iso": "MNG" },
    { "name_ko": "나이지리아",          "iso": "NGA" },
    { "name_ko": "에티오피아",          "iso": "ETH" },
    { "name_ko": "케냐",               "iso": "KEN" },
    { "name_ko": "탄자니아",           "iso": "TZA" },
    { "name_ko": "잠비아",             "iso": "ZMB" },
    { "name_ko": "가나",               "iso": "GHA" },
    { "name_ko": "카메룬",             "iso": "CMR" },
    { "name_ko": "앙골라",             "iso": "AGO" },
    { "name_ko": "콩고민주공화국",      "iso": "COD" },
    { "name_ko": "코트디부아르",        "iso": "CIV" },
    { "name_ko": "남아프리카공화국",    "iso": "ZAF" },
    { "name_ko": "짐바브웨",           "iso": "ZWE" },
    { "name_ko": "말라위",             "iso": "MWI" },
    { "name_ko": "모잠비크",           "iso": "MOZ" },
    { "name_ko": "수단",               "iso": "SDN" },
    { "name_ko": "남수단",             "iso": "SSD" },
    { "name_ko": "소말리아",           "iso": "SOM" },
    { "name_ko": "에리트레아",          "iso": "ERI" },
    { "name_ko": "라이베리아",          "iso": "LBR" },
    { "name_ko": "시에라리온",          "iso": "SLE" },
    { "name_ko": "기니",               "iso": "GIN" },
    { "name_ko": "말리",               "iso": "MLI" },
    { "name_ko": "부르키나파소",        "iso": "BFA" },
    { "name_ko": "니제르",             "iso": "NER" },
    { "name_ko": "차드",               "iso": "TCD" },
    { "name_ko": "중앙아프리카공화국",  "iso": "CAF" },
    { "name_ko": "파푸아뉴기니",       "iso": "PNG" },
    { "name_ko": "동티모르",           "iso": "TLS" }
  ],
  "note": "이 목록은 법무부 고시 개정 시 즉시 갱신해야 함. 마지막 공식 메뉴얼 확인 후 빠진 국가가 있으면 추가할 것."
}
```

### 5-3. TB 규칙 객체

**TB-001: 외국인등록 단계**

```json
{
  "rule_code": "TB-001",
  "rule_name": "결핵 고위험국 외국인 — 외국인등록 시 결핵검사 결과서 요건",
  "trigger_scope": ["REGISTRATION"],
  "trigger_stage": "alien_registration",
  "condition_expr": {
    "AND": [
      { "field": "nationality_iso", "op": "in_list", "list_id": "TB_HIGH_RISK_COUNTRIES" },
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
              { "field": "months_between_visa_issue_and_entry", "op": "gte", "value": 6 }
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
  "warning_text": "결핵 고위험국 출신 외국인은 외국인등록 시 결핵검사 결과서를 제출하여야 합니다. 단, 사증 발급 단계에서 이미 제출한 경우에는 면제됩니다.",
  "legal_basis": {
    "authority_type": "manual",
    "authority_file": "체류 메뉴얼",
    "authority_section": "결핵 관련 외국인등록 첨부서류 안내",
    "authority_summary": "결핵 고위험국 국적자 외국인등록 시 결핵검사 결과서 제출 의무",
    "effective_date": null,
    "ui_expose": false,
    "priority_rank": 4
  },
  "status": "active"
}
```

**TB-002: 체류허가 신청 단계 (연장·변경)**

```json
{
  "rule_code": "TB-002",
  "rule_name": "결핵 고위험국 외국인 — 체류허가 신청 시 결핵검사 결과서 요건",
  "trigger_scope": ["EXTEND", "CHANGE"],
  "trigger_stage": "stay_permission",
  "condition_expr": {
    "AND": [
      { "field": "nationality_iso", "op": "in_list", "list_id": "TB_HIGH_RISK_COUNTRIES" },
      {
        "field": "continuous_stay_days_in_high_risk_country",
        "op": "gte",
        "value": 183,
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
    "authority_type": "manual",
    "authority_file": "체류 메뉴얼",
    "authority_section": "결핵 고위험국 국적자 체류허가 신청 시 첨부서류",
    "authority_summary": "결핵 고위험국 국적자가 연장·변경 신청 시 최근 1년 내 6개월 이상 고위험국 체류 시 결핵 결과서 제출 의무",
    "effective_date": null,
    "ui_expose": false,
    "priority_rank": 4
  },
  "status": "active"
}
```

### 5-4. TB 규칙 평가 함수 (백엔드 의사 코드)

```python
def evaluate_tb_rules(context: dict) -> list[dict]:
    """
    context = {
        "trigger_scope": "REGISTRATION",  # 또는 "EXTEND", "CHANGE"
        "nationality_iso": "PHL",
        "entry_visa_type": "e_visa",        # TB-001용
        "tb_cert_required_at_visa": True,   # TB-001용
        "tb_cert_submitted_at_visa_stage": False,
        "continuous_stay_days_in_high_risk_country": 0  # TB-002용
    }
    """
    triggered = []
    high_risk_isos = {c["iso"] for c in TB_HIGH_RISK_COUNTRIES["countries"]}
    
    if context.get("nationality_iso") not in high_risk_isos:
        return []  # 고위험국 아니면 조기 종료
    
    for rule in TB_RULES:
        if context["trigger_scope"] not in rule["trigger_scope"]:
            continue
        if evaluate_expr(rule["condition_expr"], context):
            # 면제 조건 확인
            if rule.get("exemption_expr") and evaluate_expr(rule["exemption_expr"], context):
                triggered.append({"rule_code": rule["rule_code"], "result": "EXEMPTED",
                                   "exemption_reason": rule["exemption_display"]})
            else:
                triggered.append({"rule_code": rule["rule_code"], "result": "REQUIRED",
                                   "doc": rule["required_doc"],
                                   "issuer": rule["doc_issuer"],
                                   "warning": rule["warning_text"]})
    return triggered
```

---

## 6. 사증 발급 vs 사증발급인정서 구분

### 6-1. 개념 정의 (공식 구분 기준)

**사증 발급 (VISA_ISSUANCE)**
- 해외 신청인이 해당국 소재 한국 재외공관에 직접 신청하여 사증을 발급받는 절차
- 초청인이 국내에서 사전 신청하는 과정 없음
- 신청 주체: 해외 외국인 본인

**사증발급인정서 (VISA_CONFIRMATION)**
- 국내 초청인(또는 본인)이 먼저 출입국사무소에 사증발급인정서를 신청하여 발급받고,
- 해외의 신청인(피초청인)이 그 인정서를 가지고 재외공관에서 사증을 받는 절차
- 신청 주체: 국내 초청인 (초청 목적에 따라 본인 가능)

### 6-2. 트리 분기 설계 (EP-01)

```
DN-VISA-001
  Q: 사증 처리 유형을 선택하세요
  ├── [사증 발급] → DN-VISA-ISSUANCE-001
  │     Q: 목표 체류자격 계열?
  │     ├── F-계열 → (체류 측 구조 재사용 + VISA 오버레이)
  │     ├── E-계열 → (체류 측 구조 재사용 + VISA 오버레이)
  │     └── D-계열 → ...
  └── [사증발급인정서] → DN-VISA-CONFIRM-001
        Q: 초청 대상 유형?
        ├── 가족·친지 → DN-VISA-CONFIRM-FAMILY
        ├── 취업 초청 → DN-VISA-CONFIRM-EMPLOY
        └── 유학 초청 → DN-VISA-CONFIRM-STUDENT
```

모든 사증 관련 result 노드에는 `consulate_notice_required: true`를 자동 설정하고 아래 고지문을 표시한다.

### 6-3. 공관 안내 고지 (모든 사증 결과에 필수)

```json
{
  "consulate_notice_required": true,
  "consulate_notice_text": "실제 사증 요건(구비서류, 신청 양식, 제출 방법 등)은 국가 및 재외공관에 따라 다를 수 있습니다. 최종 제출 전 반드시 해당 재외공관 공식 홈페이지에서 최신 요건을 확인하십시오."
}
```

이 고지문은 API 응답과 UI에 모두 자동 포함된다. 개별 결과 노드에 `consulate_notice_required: true`가 있으면 UI 컴포넌트가 자동으로 렌더링한다.

---

## 7. 사증 오버레이 설계 원칙

### 핵심 설계 원칙 (CLAUDE.md 및 개발자 노트에 명시)

> **"사증 단계 분석은 체류 단계 구조를 최대한 재사용한다. 자격 요건 판단, 대상자 유형, 서류 구성이 실질적으로 동일한 경우 체류 측 master_row를 base로 참조하고, 사증 특유의 차이점만 visa_overlay_rules에 별도 관리한다. 사증 내용을 처음부터 중복 작성하지 않는다."**

### 7-1. 체류 측과 공통인 항목 (재사용)

- 자격 요건 판단 (E-7 전문인력, F-4 재외동포 자격 등)
- 대상자 유형 분류 (취업자, 유학생, 가족 등)
- 필요서류의 대부분 (여권사본, 사진, 기관 서류 등)
- 결핵 규칙 (TB-001 연계: 사증 발급 시 TB 서류 제출 → 등록 시 면제)
- 예외 조건 대부분

### 7-2. 사증 특유 차이점 (오버레이로만 관리)

| 항목 | 사증 측 특이사항 |
|---|---|
| 신청 장소 | 해외 재외공관 (vs 국내 출입국사무소) |
| 발급 유형 | 사증발급 vs 사증발급인정서 |
| 초청인·보증인 | 국내 초청인 서류 추가 (VISA_CONFIRMATION만) |
| 공문·외교 경로 | 공문·외교각서·초청 경로 (해당 자격만) |
| 서류 제출 시점 | 입국 전 제출 (vs 입국 후) |
| 공관별 추가 요건 | 공관마다 상이 → 고지 필수 |
| TB 연계 | 사증 발급 시 TB 제출 → 외국인등록 시 면제 적용 |

### 7-3. `visa_overlay_rules` 스키마

```json
{
  "overlay_id": "VISA-CHANGE-F4-001",
  "base_row_id": "M1-0261",
  "base_action_type": "CHANGE",
  "visa_stage": "entry_stage",
  "visa_type_code": "VISA_CONFIRMATION",
  "application_location": "domestic_immigration_office",
  "inviter_required": true,
  "inviter_docs": ["초청장", "신원보증서", "재직증명서 또는 사업자등록증"],
  "official_route": null,
  "doc_timing": "pre_entry",
  "additional_office_prepared_docs": ["사증발급인정신청서"],
  "additional_required_docs": [],
  "removed_docs": ["통합신청서"],
  "tb_cert_carries_over": true,
  "consulate_notice_required": true,
  "consulate_notice_text": "실제 사증 요건은 국가 및 재외공관에 따라 다를 수 있습니다. 반드시 해당 재외공관 공식 홈페이지에서 확인하십시오.",
  "notes": "F-4 사증발급인정서는 변경 자격 요건과 동일하나 신청 장소(국내 청), 서류 시점(입국 전)이 다름"
}
```

---

## 8. 수정된 API 엔드포인트

### 기존 엔드포인트 (prefix: `/api/guidelines`) — 응답 키 변경만

| 경로 | 변경 사항 |
|---|---|
| `GET /` | 응답 키: `office_prepared_docs`, `required_docs` |
| `GET /search/query` | 동일 |
| `GET /code/{code}` | 동일 |
| `GET /{row_id}` | `basis` 구조화, `quickdoc_*` 필드 포함 |
| `GET /rules` | 동일 |
| `GET /exceptions` | 동일 |
| `GET /docs/lookup` | 동일 |
| `GET /stats` | 동일 |

### 신규 엔드포인트

```
GET  /api/guidelines/tree/entry-points
  → 전체 진입점 목록 (13개)
  → 응답: [{ entry_id, display_label, icon, sort_order, root_node_id }]

GET  /api/guidelines/tree/node/{node_id}
  → 노드 정보 + 연결된 엣지 목록
  → 응답: { node, edges: [{ edge_id, answer_value, answer_display, to_node_id }] }

POST /api/guidelines/tree/navigate
  → 현재 노드 + 선택값 + 세션 컨텍스트 → 다음 노드 계산
  → 요청: { current_node_id, answer_value, session_context: { nationality_iso?, ... } }
  → 응답: { next_node, active_warnings: [], breadcrumb: [...] }

GET  /api/guidelines/tree/result/{node_id}
  → 말단 결과 노드의 master_rows 데이터
  → 응답: { primary_row, secondary_rows, disambiguation_questions, consulate_notice? }

POST /api/guidelines/tb/evaluate
  → context 입력 → 결핵 규칙 평가 결과
  → 요청: { trigger_scope, nationality_iso, entry_visa_type?, ... }
  → 응답: [{ rule_code, result: "REQUIRED"|"EXEMPTED"|"NOT_APPLICABLE", doc?, warning? }]

GET  /api/guidelines/tb/rules
  → 결핵 규칙 전체 목록

GET  /api/guidelines/tb/countries
  → 결핵 고위험국 목록 (display용 name_ko 포함)

GET  /api/guidelines/visa-overlay/{base_row_id}
  → 특정 체류 row의 사증 오버레이 반환
  → 응답: { overlay | null }
```

---

## 9. 검색 모드 vs 트리 모드 행동 명세

### 9-1. 모드 전환 규칙

| 상태 | 모드 | 화면 |
|---|---|---|
| 검색어 없음 (empty) | `tree_mode` | 진입점 카드 13개 표시 |
| 검색어 1글자 | `tree_mode` | 검색 실행 안 함, 진입점 카드 유지 |
| 검색어 2글자 이상 | `search_mode` | 검색 결과 표시 |
| 검색 결과 0건 | `search_mode` (no results) | "결과 없음" 메시지 + 아래에 진입점 카드 유지 |

### 9-2. 프론트엔드 상태 설계

```typescript
type UiMode = "tree_mode" | "search_mode";

// 모드 판단 함수
function resolveMode(inputValue: string): UiMode {
  return inputValue.trim().length >= 2 ? "search_mode" : "tree_mode";
}

// 검색 실행 조건
function shouldSearch(inputValue: string): boolean {
  return inputValue.trim().length >= 2;
}
```

### 9-3. 렌더링 구조

```tsx
{/* 항상 표시: 검색창 */}
<SearchBar value={inputValue} onChange={setInputValue} onSearch={handleSearch} />

{/* 업무유형 탭 필터 (tree_mode에서도 항상 표시) */}
<ActionTypeTabs active={activeType} onChange={handleTypeChange} />

{mode === "tree_mode" && (
  <>
    {/* 진입점 카드 13개 */}
    <ConsultationEntryPoints onSelect={enterTree} />
    {/* 특별 트랙 섹션 */}
    <SpecialTracks onSelect={enterTree} />
  </>
)}

{mode === "search_mode" && (
  <>
    {results.length > 0 ? (
      <SearchResults results={results} />
    ) : (
      <>
        <EmptySearchMessage query={query} />
        {/* 결과 없을 때도 트리 표시 */}
        <ConsultationEntryPoints onSelect={enterTree} />
      </>
    )}
  </>
)}
```

### 9-4. 검색창 보조 동작

- 검색어 지우면(`""`) → 즉시 `tree_mode`로 전환
- 검색어 1글자 → 검색 실행 없음, 트리 유지, 입력창 하단에 힌트 뱃지 표시: `"2글자 이상 입력 시 검색"`
- Enter / 검색 버튼 → `shouldSearch()`가 false면 아무 동작 안 함

---

## 10. 문서자동작성 딥링크 설계

### 10-1. quick-doc 파라미터 체계 (현재 시스템 기준)

```
/quick-doc?category=체류&minwon=변경&kind=F&detail=4
```

`category`, `minwon`, `kind`, `detail` 4개 파라미터가 현재 quick-doc의 업무 선택 트리를 구동한다.

### 10-2. 딥링크 URL 생성 로직

```typescript
// guidelines 상세 화면에서 딥링크 생성
function buildQuickDocUrl(row: GuidelineRow): string | null {
  const { quickdoc_category, quickdoc_minwon, quickdoc_kind, quickdoc_detail } = row;
  
  if (!quickdoc_category || !quickdoc_minwon) return null;  // 매핑 없음
  
  const params = new URLSearchParams({
    category:    quickdoc_category,
    minwon:      quickdoc_minwon,
    kind:        quickdoc_kind    || "",
    detail:      quickdoc_detail  || "",
    from_row_id: row.row_id,
    from_code:   row.detailed_code,
    from_action: row.action_type,
    from_label:  row.display_label || row.business_name,
  });
  
  return `/quick-doc?${params.toString()}`;
}
```

`from_*` 파라미터는 quick-doc 페이지가 "어디서 왔는지" 표시하는 데 사용한다.

### 10-3. quick-doc 페이지 수정 (파라미터 수신)

```typescript
// /quick-doc/page.tsx 상단에 추가
import { useSearchParams } from "next/navigation";

// QuickDocPage 내부
const searchParams = useSearchParams();

// 마운트 시 URL 파라미터로 자동 선택 세팅
useEffect(() => {
  const cat    = searchParams.get("category");
  const min_   = searchParams.get("minwon");
  const knd    = searchParams.get("kind")   || "";
  const det    = searchParams.get("detail") || "";
  const fromLabel = searchParams.get("from_label") || "";
  
  if (cat && min_) {
    setCategory(cat);
    setMinwon(min_);
    setKind(knd);
    setDetail(det);
    if (fromLabel) setDeepLinkContext(fromLabel);  // 배너 표시용
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, []);  // 마운트 시 1회만 실행

// 딥링크 출처 배너 (선택적 표시)
const [deepLinkContext, setDeepLinkContext] = useState("");
// JSX에서:
{deepLinkContext && (
  <div style={{ background: "#FFFBF0", border: "1px solid #F6E05E",
    borderRadius: 8, padding: "8px 14px", marginBottom: 12, fontSize: 12, color: "#744210" }}>
    📋 실무지침에서 연결됨: <strong>{deepLinkContext}</strong>
  </div>
)}
```

### 10-4. guidelines 상세 패널 — 딥링크 버튼 추가

```tsx
// DetailPanel 컴포넌트 하단에 추가
{buildQuickDocUrl(row) ? (
  <button
    onClick={() => router.push(buildQuickDocUrl(row)!)}
    style={{
      width: "100%", padding: "10px 0",
      background: "var(--hw-gold)", color: "#fff",
      border: "none", borderRadius: 8,
      fontSize: 13, fontWeight: 700,
      cursor: "pointer", display: "flex",
      alignItems: "center", justifyContent: "center", gap: 6,
    }}
  >
    <FileEdit size={14} /> 문서자동작성 →
  </button>
) : (
  <button
    onClick={() => router.push("/quick-doc")}
    style={{ /* 동일 스타일, opacity 0.6 */ }}
    title="이 업무는 자동 연동이 준비되지 않아 수동 선택이 필요합니다"
  >
    <FileEdit size={14} /> 문서자동작성 (수동 선택)
  </button>
)}
```

### 10-5. 전체 딥링크 매핑 테이블

| action_type | detailed_code 접두어 | category | minwon | kind | detail |
|---|---|---|---|---|---|
| CHANGE | F-1 | 체류 | 변경 | F | 1 |
| CHANGE | F-2 | 체류 | 변경 | F | 2 |
| CHANGE | F-3 | 체류 | 변경 | F | 3 |
| CHANGE | F-4 | 체류 | 변경 | F | 4 |
| CHANGE | F-5 | 체류 | 변경 | F | 5 |
| CHANGE | F-6 | 체류 | 변경 | F | 6 |
| CHANGE | H-2 | 체류 | 변경 | H2 | (없음) |
| CHANGE | E-7 | 체류 | 변경 | E7 | (없음) |
| CHANGE | D-2 | 체류 | 변경 | D | 2 |
| CHANGE | D-4 | 체류 | 변경 | D | 4 |
| CHANGE | D-8 | 체류 | 변경 | D | 8 |
| CHANGE | D-10 | 체류 | 변경 | D | 10 |
| EXTEND | F-1 | 체류 | 연장 | F | 1 |
| EXTEND | F-2 | 체류 | 연장 | F | 2 |
| EXTEND | F-3 | 체류 | 연장 | F | 3 |
| EXTEND | F-4 | 체류 | 연장 | F | 4 |
| EXTEND | F-6 | 체류 | 연장 | F | 6 |
| EXTEND | H-2 | 체류 | 연장 | H2 | (없음) |
| EXTEND | E-7 | 체류 | 연장 | E7 | (없음) |
| REGISTRATION | F-1 | 체류 | 등록 | F | 1 |
| REGISTRATION | F-2 | 체류 | 등록 | F | 2 |
| REGISTRATION | F-3 | 체류 | 등록 | F | 3 |
| REGISTRATION | F-4 | 체류 | 등록 | F | 4 |
| REGISTRATION | F-6 | 체류 | 등록 | F | 6 |
| REGISTRATION | H-2 | 체류 | 등록 | H2 | (없음) |
| REGISTRATION | E-7 | 체류 | 등록 | E7 | (없음) |
| GRANT | F-2 | 체류 | 부여 | F | 2 |
| GRANT | F-3 | 체류 | 부여 | F | 3 |
| GRANT | F-5 | 체류 | 부여 | F | 5 |
| EXTRA_WORK | D-2 | 체류 | 기타 | D | 2 |
| EXTRA_WORK | D-4 | 체류 | 기타 | D | 4 |
| EXTRA_WORK | D-8 | 체류 | 기타 | D | 8 |
| EXTRA_WORK | D-10 | 체류 | 기타 | D | 10 |
| DOMESTIC_RESIDENCE_REPORT | (모두) | 체류 | 신고 | 등록사항 | (없음) |

매핑이 없는 행(REENTRY, WORKPLACE, APPLICATION_CLAIM 등)은 `quickdoc_*` 필드를 빈 문자열로 두고, UI에서 "수동 선택" 버튼을 표시한다.

---

## 11. 검색 vs 트리 탐색 — 분리 원칙 요약

### 트리 탐색이 주(主)

이런 상황에서 트리 탐색을 사용한다:
- 고객이 "어떤 업무인지 모른다"
- 조건 분기가 있다 (등록 여부, 국적, 체류자격 등)
- 결핵·예외 등 단계별 체크가 필요하다
- 초보 직원이 빠짐없이 체크리스트를 따라야 한다
- 사증 발급 vs 사증발급인정서처럼 개념 분기가 선행되어야 한다

**UI 진입**: 페이지 진입 시 기본으로 표시되는 진입점 카드

### 검색이 보조(補助)

이런 상황에서 검색을 사용한다:
- 직원이 이미 업무 종류를 알고 서류만 빠르게 확인할 때
- 체류자격 코드를 이미 알고 있을 때 (F-4-25, E-7 등)
- 특정 서류명이 어느 업무에 쓰이는지 역방향 조회 시
- 숙련 직원의 빠른 참조 모드

**UI 진입**: 검색창에 2글자 이상 입력

### 프론트엔드 라우트 구조 (권장)

```
/guidelines                      ← 현재 페이지: 검색 + 트리 통합 (tree_mode 기본)
/guidelines/consult              ← (미래) 상담 트리 전용 진입 화면
/guidelines/consult/[...path]    ← (미래) 트리 단계별 탐색 (동적 라우팅)
/guidelines/[row_id]             ← (미래) 특정 업무 상세 영구 링크
```

현재 단계에서는 `/guidelines` 단일 페이지에서 `tree_mode` / `search_mode` 토글로 구현.  
트리 탐색량이 많아지면 `/guidelines/consult` 분리를 검토한다.

---

*작성일: 2026-04-14 | 버전: v3.1 | 이전 버전: v3.0*
