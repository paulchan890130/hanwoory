"""
자격별 청크를 Claude API로 일괄 처리:
  1. 매뉴얼 정답 페이지 매핑
  2. 편람 기반 실무 팁 추가
  3. DB row 오류 수정

입력:  backend/data/manuals/llm_chunks_v2.json
출력:  backend/data/manuals/llm_results.json
       (이후 apply_llm_results.py 로 DB 반영)

실행:
  export ANTHROPIC_API_KEY=sk-ant-...
  python backend/scripts/llm_remap_all.py [--codes F-5,F-4]
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

CHUNKS  = ROOT / "backend" / "data" / "manuals" / "llm_chunks_v2.json"
RESULTS = ROOT / "backend" / "data" / "manuals" / "llm_results.json"

SYSTEM_PROMPT = """\
당신은 한국 출입국·외국인정책본부 실무에 정통한 행정사입니다. 매뉴얼(공식)과 편람(상세지침)을 비교하여 실무 팁을 추출하고, DB의 잘못된 부분을 정확히 잡아내는 전문가입니다.

원칙:
1. 정답 페이지는 매뉴얼 본문에 명시적으로 해당 케이스를 다루는 페이지를 가리켜야 합니다. 인용/언급만 있는 페이지는 안 됨.
2. 실무 팁은 매뉴얼에는 없고 편람에만 있는 실무 노하우만 추출합니다. 편람 출처는 노출하지 않고 "실무 노하우"로 표기.
3. DB 수정사항은 매뉴얼/편람과 명확히 다른 잘못된 부분만 지정. 추측은 금지.
4. 모든 응답은 반드시 JSON 형식으로만 반환합니다."""

USER_TEMPLATE = """\
자격: {main_code}
DB rows ({n_rows}개):
{rows_json}

매뉴얼 [체류민원 p.{stay_pages}]:
{stay_text}

매뉴얼 [사증민원 p.{visa_pages}]:
{visa_text}

편람 [p.{pyeon_pages}]:
{pyeon_text}

작업:
각 row에 대해 다음을 결정하세요.

1. **manual_ref**: 매뉴얼 정답 페이지. 해당 row의 case가 본문에서 다뤄지는 정확한 페이지(시작-끝). 일반 인용 페이지 금지. 매뉴얼 페이지 표시 번호(예: -454-) 기준이 아닌 PDF 페이지(p.453 같이 위 텍스트의 ----- p.X ----- 표기) 기준.

2. **practical_tips_to_add**: 편람에만 있고 매뉴얼에 없는 실무 노하우. 매뉴얼에 이미 있는 내용은 추가하지 말 것. 각 팁은 한 줄(50~150자).

3. **corrections**: DB row의 잘못된 필드. 매뉴얼/편람 기준으로 명확히 다른 경우만 수정값 제시. 다음 필드만 가능: supporting_docs, form_docs, fee_rule, exceptions_summary, overview_short. (key가 빈 객체이면 수정 없음)

4. **confidence**: "high"(매뉴얼 명시) / "medium"(추론) / "low"(불확실). low면 사람 검토 필요.

5. **notes**: 참고사항 (선택).

응답은 반드시 다음 JSON 스키마만 반환:
```json
{{
  "row_updates": [
    {{
      "row_id": "M1-XXXX",
      "manual_ref": [
        {{"manual": "체류민원", "page_from": <int>, "page_to": <int>, "match_text": "<왜 이 페이지인지 짧게>"}},
        {{"manual": "사증민원", "page_from": <int>, "page_to": <int>, "match_text": "..."}}
      ],
      "practical_tips_to_add": ["팁1", "팁2"],
      "corrections": {{"key": "value"}},
      "confidence": "high",
      "notes": "선택"
    }}
  ]
}}
```
JSON 외 다른 텍스트 출력 금지."""


def build_prompt(chunk: dict) -> str:
    rows_min = [
        {
            "row_id": r["row_id"], "code": r["detailed_code"],
            "action": r["action_type"], "name": r["business_name"],
            "overview": r["overview_short"][:200],
            "form_docs": r["form_docs"][:300],
            "supp_docs": r["supporting_docs"][:300],
            "fee": r["fee_rule"][:100],
            "exceptions": r["exceptions_summary"][:200],
        }
        for r in chunk["rows"]
    ]
    return USER_TEMPLATE.format(
        main_code  = chunk["main_code"],
        n_rows     = len(chunk["rows"]),
        rows_json  = json.dumps(rows_min, ensure_ascii=False, indent=2),
        stay_pages = chunk.get("manual_체류민원", {}).get("pages", "(없음)"),
        stay_text  = chunk.get("manual_체류민원", {}).get("text", "(매핑 없음)"),
        visa_pages = chunk.get("manual_사증민원", {}).get("pages", "(없음)"),
        visa_text  = chunk.get("manual_사증민원", {}).get("text", "(매핑 없음)"),
        pyeon_pages= chunk.get("pyeonram", {}).get("pages", "(없음)"),
        pyeon_text = chunk.get("pyeonram", {}).get("text", "(매핑 없음)"),
    )


def extract_json(text: str) -> dict:
    """LLM 응답에서 JSON 추출 (markdown 코드블록 처리)."""
    text = text.strip()
    if text.startswith("```"):
        # ```json ... ``` 또는 ``` ... ```
        text = text.split("```", 2)[1]
        if text.startswith("json\n"):
            text = text[5:]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())


def call_anthropic(prompt: str, *, model: str = "claude-sonnet-4-6", max_tokens: int = 8192) -> dict:
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text
    try:
        return extract_json(text)
    except Exception as e:
        print(f"  [WARN] JSON 파싱 실패: {e}\n  raw: {text[:500]}")
        return {"row_updates": [], "_raw_error": str(e), "_raw_text": text[:2000]}


def process_all(only_codes: Optional[set[str]] = None) -> dict:
    if not CHUNKS.exists():
        raise FileNotFoundError(f"청크 파일 없음: {CHUNKS}\n  → python backend/scripts/build_llm_chunks_v2.py")

    chunks = json.loads(CHUNKS.read_text(encoding="utf-8"))
    # 이전 결과 로드 (재실행 시 이미 처리한 것 건너뛰기)
    results = {}
    if RESULTS.exists():
        try:
            results = json.loads(RESULTS.read_text(encoding="utf-8"))
            print(f"  이전 결과 로드: {len(results)}건")
        except Exception:
            pass

    targets = sorted(chunks.keys())
    if only_codes:
        targets = [c for c in targets if c in only_codes]
    print(f"\n=== LLM 처리 시작: {len(targets)} 자격 ===\n")

    for i, code in enumerate(targets, 1):
        if code in results:
            print(f"[{i}/{len(targets)}] {code} (이미 처리됨, 건너뜀)")
            continue
        chunk = chunks[code]
        prompt = build_prompt(chunk)
        prompt_size = len(prompt)
        print(f"[{i}/{len(targets)}] {code}: {len(chunk['rows'])} rows, prompt {prompt_size:,} chars")
        t0 = time.time()
        try:
            result = call_anthropic(prompt)
            elapsed = time.time() - t0
            n_updates = len(result.get("row_updates", []))
            print(f"  → {n_updates} updates ({elapsed:.1f}s)")
            results[code] = result
            # 매번 저장 (중단 안전)
            RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"  [ERROR] {type(e).__name__}: {e}")
            results[code] = {"_error": str(e)}
            RESULTS.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[OK] 결과 저장: {RESULTS}")
    return results


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--codes", default=None, help="쉼표 구분 자격코드 (예: F-5,F-4). 미지정 시 전체.")
    args = p.parse_args()
    only = set(args.codes.split(",")) if args.codes else None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[ERROR] ANTHROPIC_API_KEY 환경변수 필요", file=sys.stderr)
        sys.exit(1)
    process_all(only)
