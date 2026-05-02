## manual_ref 개선 작업 현황 (2026-05-02 최종)

### DB 상태

- 파일: `backend/data/immigration_guidelines_db_v2.json`
- byte: **990,594** / rows: 369 / 백업: v4~v23 (20개)

### quality gate 현황

| 상태 | 건수 | 비율 |
|---|---|---|
| PASS | 208건 | 56% — 검증 완료 |
| WARN | 112건 | 30% — legitimate cluster 대부분 |
| FAIL | 37건 | 10% — empty/NOT_IN_MANUAL 또는 confirmed_correct |
| NEEDS_OVERRIDE | **0건** | 0% — **완전 해소** |
| BLOCKED | 12건 | 3% — 의도적 유지 |

### 핵심 파일

```
backend/scripts/manual_ref_quality_gate_v4.py
  └ CONFIRMED_CORRECT_OVERRIDES: 43건 등록
backend/data/manuals/empty_ref_disposition.json
  └ NOT_IN_MANUAL / NEEDS_SEPARATE_LOOKUP 등록
backend/scripts/llm_judge_run_v1.py
backend/scripts/llm_verifier_run_v1.py
backend/scripts/generate_apply_candidates_v1.py
```

### 다음 세션 작업 (선택적)

1. **FAIL 5건 confirmed_correct false FAIL 잔류**
   - M1-0125 / M1-0214 / M1-0216 / M1-0244 / M1-0252
   - quality_gate rule 추가 조정으로 해소 가능

2. **WARN 112건 중 미확인 cluster 추가 검증**

3. **F-5-14 / E-7-S / F-4 NOT_IN_MANUAL 건들**
   - 별도 매뉴얼에서 탐색 필요시

### 파이프라인 실행

```bash
python backend/scripts/manual_ref_quality_gate_v4.py
python backend/scripts/llm_judge_prepare_v1.py
python backend/scripts/llm_judge_run_v1.py --batch [파일] --tier ALL --model sonnet --run-llm
python backend/scripts/llm_verifier_run_v1.py --results [파일] --run-verifier
python backend/scripts/generate_apply_candidates_v1.py
```

### 주의

- **DB 직접 수정 금지** (`immigration_guidelines_db_v2.json` — 반드시 patch 스크립트 경유)
- **apply는 dry-run 확인 후 실행**
- **LLM은 `--run-llm` / `--run-verifier` 명시 시에만 호출**
