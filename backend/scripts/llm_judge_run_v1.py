"""
Stage 3 — LLM Judge Runner v1

Calls Claude API per row to judge whether the current manual_ref is correct.

ABSOLUTE PROHIBITIONS:
  - Default mode = DRY-RUN (no API call). Only --run-llm enables API calls.
  - No DB modification. No apply.
  - No frontend / manual_watcher / manual_indexer_v6 modification.

CLI:
  python llm_judge_run_v1.py --batch FILE --tier WARN|FAIL|ALL
                              [--model haiku|sonnet]
                              [--run-llm]   # required to actually call API
                              [--dry-run]   # default — print prompts only
                              [--limit N]
                              [--rate-per-sec FLOAT]   # default 1.0

Tier model defaults (per spec):
  WARN  → claude-haiku-4-5-20251001 (cheap, sample noisy WARN tier)
  FAIL  → claude-sonnet-4-6        (better accuracy on broken rows)
  ALL   → use --model or default to sonnet

The prompt's system block is cached (ephemeral) — identical across every row,
so subsequent rows pay ~0.1× input cost on the cached prefix.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT      = Path(__file__).parent.parent.parent
MANUALS   = ROOT / "backend" / "data" / "manuals"
RESULTS_DIR = MANUALS / "llm_judge_results"

# Load root .env so ANTHROPIC_API_KEY can sit there alongside JWT_SECRET_KEY etc.
# (graceful fallback if python-dotenv is not installed)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

MODEL_HAIKU  = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-4-6"

SYSTEM_PROMPT = (
    "너는 출입국 매뉴얼 페이지 판정관이다.\n"
    "주어진 페이지가 해당 업무의 정답 페이지인지 판정하라.\n"
    "판정 기준을 엄격히 따르라.\n"
    "JSON만 출력하라. 설명, 주석, markdown 금지.\n"
    "즉시 JSON으로만 출력하라.\n"
    "'Looking at...', 'I need to...' 등 영문 내레이션 절대 금지.\n"
    "첫 글자가 반드시 { 이어야 한다.\n"
)


def _truthy_decision(s: str) -> bool:
    return s in {"EXACT", "BROAD", "WRONG", "NEEDS_REVIEW"}


def build_user_message(p: dict) -> str:
    nb = p.get("neighbor_pages") or {}
    p_minus2 = nb.get("page_N-2") or "(없음 또는 비어있음)"
    p_minus1 = nb.get("page_N-1") or "(없음 또는 비어있음)"
    p_plus1  = nb.get("page_N+1") or "(없음 또는 비어있음)"
    p_plus2  = nb.get("page_N+2") or "(없음 또는 비어있음)"
    page_from = p.get("current_page_from", 0)
    cluster = p.get("same_cluster_members") or []
    cluster_str = ", ".join(cluster[:20]) if cluster else "(없음)"
    risk = p.get("quality_gate_risk_types") or []
    risk_str = ", ".join(risk) if risk else "(없음)"
    return (
        f"업무: {p.get('detailed_code','')} {p.get('action_type','')} — {p.get('title','')}\n"
        f"업무 정의: {p.get('action_type_definition','')}\n"
        f"우선 매뉴얼: {p.get('preferred_manual','')}\n"
        f"현재 매핑: {p.get('current_manual','')} p.{page_from}\n"
        f"품질검사 위험 유형: {risk_str}\n\n"
        f"=== 후보 페이지 텍스트 ({p.get('current_manual','')} p.{page_from}) ===\n"
        f"{p.get('candidate_page_text','')}\n\n"
        f"=== 인접 페이지 ===\n"
        f"p.{page_from-2}: {p_minus2}\n\n"
        f"p.{page_from-1}: {p_minus1}\n\n"
        f"p.{page_from+1}: {p_plus1}\n\n"
        f"p.{page_from+2}: {p_plus2}\n\n"
        f"=== 같은 클러스터 멤버 ===\n"
        f"{cluster_str}\n\n"
        f"=== EXACT 판정 조건 (모두 충족해야 함) ===\n"
        f"1. 신청요건 또는 제출서류 또는 허가기준이 이 페이지에 직접 있음\n"
        f"2. 해당 세부코드({p.get('detailed_code','')}) 또는 업무명이 heading으로 등장\n"
        f"3. 다른 subtype 내용이 아님\n"
        f"4. positive_evidence를 구체적으로 쓸 수 있음\n\n"
        f"=== EXACT 금지 조건 (하나라도 해당하면 EXACT 불가) ===\n"
        f"1. 키워드만 본문에 등장 (heading 없음)\n"
        f"2. 자격 설명 / 활동범위 / 체류기간 상한 / 세부약호 목록 페이지\n"
        f"3. broad family 섹션 (여러 subtype 묶은 개요)\n"
        f"4. 다음 섹션 제목이 하단에만 등장\n"
        f"5. positive_evidence를 쓸 수 없음\n\n"
        f"위 조건에 따라 판정하라.\n"
        f"모르면 반드시 NEEDS_REVIEW로 판정하라.\n\n"
        f"출력 형식 (JSON만, 다른 텍스트 없음):\n"
        f"{{\n"
        f'  "row_id": "{p.get("row_id","")}",\n'
        f'  "decision": "EXACT|BROAD|WRONG|NEEDS_REVIEW",\n'
        f'  "confidence": "high|medium|low",\n'
        f'  "page_role": "EXACT_TASK_PAGE|BROAD_FAMILY_PAGE|QUALIFICATION_OVERVIEW|BODY_KEYWORD_ONLY|OTHER",\n'
        f'  "positive_evidence": "",\n'
        f'  "negative_evidence": "",\n'
        f'  "recommended_page": null\n'
        f"}}\n"
    )


def select_packets(batch: dict, tier: str, qg_index: dict[str, dict]) -> list[dict]:
    """Map quality_status → tier."""
    if tier == "ALL":
        return list(batch.get("packets") or [])
    if tier == "WARN":
        return [p for p in batch.get("packets") or []
                if qg_index.get(p["row_id"], {}).get("quality_status") == "WARN"]
    if tier == "FAIL":
        return [p for p in batch.get("packets") or []
                if qg_index.get(p["row_id"], {}).get("quality_status")
                in ("FAIL", "NEEDS_OVERRIDE")]
    return []


def parse_json_response(text: str) -> dict | None:
    """Extract first JSON object from response."""
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", required=True, help="Stage 2 batch JSON file path")
    ap.add_argument("--tier", required=True, choices=["WARN", "FAIL", "ALL"])
    ap.add_argument("--model", choices=["haiku", "sonnet"], default=None,
                    help="Model override. Default: haiku for WARN, sonnet for FAIL/ALL.")
    ap.add_argument("--run-llm", action="store_true",
                    help="Actually call Claude API. Default = dry-run.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print prompts only (default behavior; flag is for clarity).")
    ap.add_argument("--limit", type=int, default=0, help="0=unlimited; testing limit.")
    ap.add_argument("--rate-per-sec", type=float, default=1.0,
                    help="Max API requests per second (rate limit). Default 1.0.")
    args = ap.parse_args()

    # Resolve dry-run mode
    is_apply = args.run_llm and not args.dry_run

    # Resolve model
    if args.model == "haiku":
        model = MODEL_HAIKU
    elif args.model == "sonnet":
        model = MODEL_SONNET
    else:
        # Defaults per spec
        model = MODEL_HAIKU if args.tier == "WARN" else MODEL_SONNET

    # ── Load inputs ──
    batch_path = Path(args.batch)
    if not batch_path.is_absolute():
        batch_path = ROOT / batch_path
    if not batch_path.exists():
        print(f"[ABORT] batch 파일 없음: {batch_path}", file=sys.stderr)
        return 1
    batch = json.loads(batch_path.read_text(encoding="utf-8"))

    qg_path = MANUALS / "manual_ref_quality_gate_v4.json"
    qg = json.loads(qg_path.read_text(encoding="utf-8"))
    qg_index = {r["row_id"]: r for r in qg.get("rows") or []}

    # ── Select packets ──
    selected = select_packets(batch, args.tier, qg_index)
    if args.limit > 0:
        selected = selected[:args.limit]

    print(f"[judge] batch         : {batch_path.relative_to(ROOT)}")
    print(f"[judge] tier          : {args.tier}")
    print(f"[judge] model         : {model}")
    print(f"[judge] mode          : {'APPLY (--run-llm)' if is_apply else 'DRY-RUN'}")
    print(f"[judge] selected rows : {len(selected)}")
    print(f"[judge] rate limit    : {args.rate_per_sec} req/sec")

    if not selected:
        print("[judge] no rows selected — exit.")
        return 0

    if is_apply:
        try:
            import anthropic  # type: ignore
        except ImportError:
            print(f"[ABORT] anthropic SDK 미설치. pip install anthropic", file=sys.stderr)
            return 1
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("[ABORT] ANTHROPIC_API_KEY 환경변수 필요. "
                  "shell에서 'export ANTHROPIC_API_KEY=sk-ant-...' 또는 "
                  "root .env 파일에 ANTHROPIC_API_KEY=sk-ant-... 추가 후 재실행.",
                  file=sys.stderr)
            return 1

    results: list[dict] = []
    sample_prompt_shown = False
    min_interval = 1.0 / max(args.rate_per_sec, 0.01)
    last_call_ts = 0.0

    if is_apply:
        client = anthropic.Anthropic()  # ANTHROPIC_API_KEY env var
    else:
        client = None

    for i, p in enumerate(selected):
        rid = p["row_id"]
        user_msg = build_user_message(p)

        if not is_apply:
            # Dry-run: show first prompt as sample
            if not sample_prompt_shown:
                print("\n" + "=" * 60)
                print(f"SAMPLE PROMPT (row {rid}, model={model})")
                print("=" * 60)
                print("--- system ---")
                print(SYSTEM_PROMPT)
                print("--- user ---")
                # truncate user msg in display to avoid massive output
                preview = user_msg if len(user_msg) <= 1500 else user_msg[:1500] + "\n…(truncated)"
                print(preview)
                print("=" * 60)
                sample_prompt_shown = True
            results.append({
                "row_id":      rid,
                "decision":    None,
                "confidence":  None,
                "page_role":   None,
                "positive_evidence": "",
                "negative_evidence": "",
                "recommended_page":  None,
                "_dry_run":          True,
                "_user_msg_chars":   len(user_msg),
            })
            continue

        # ── Real API call ──
        # rate limit
        now = time.time()
        wait = min_interval - (now - last_call_ts)
        if wait > 0:
            time.sleep(wait)
        last_call_ts = time.time()

        try:
            response = client.messages.create(  # type: ignore
                model=model,
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_msg}],
            )
            text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
            parsed = parse_json_response(text)
            usage = getattr(response, "usage", None)
            cache_read = getattr(usage, "cache_read_input_tokens", 0) if usage else 0
            cache_create = getattr(usage, "cache_creation_input_tokens", 0) if usage else 0
            input_tok = getattr(usage, "input_tokens", 0) if usage else 0
            output_tok = getattr(usage, "output_tokens", 0) if usage else 0

            if parsed and _truthy_decision(parsed.get("decision", "")):
                # Force row_id to source-of-truth (ignore model echo if mismatched)
                parsed["row_id"] = rid
                parsed["_usage"] = {
                    "input_tokens":              input_tok,
                    "cache_read_input_tokens":   cache_read,
                    "cache_creation_input_tokens": cache_create,
                    "output_tokens":             output_tok,
                }
                results.append(parsed)
                status = "OK"
            else:
                results.append({
                    "row_id":     rid,
                    "decision":   "NEEDS_REVIEW",
                    "confidence": "low",
                    "page_role":  "OTHER",
                    "positive_evidence": "",
                    "negative_evidence": "응답 파싱 실패 또는 잘못된 형식",
                    "recommended_page":  None,
                    "_raw_response":     text[:500],
                    "_usage": {
                        "input_tokens":              input_tok,
                        "cache_read_input_tokens":   cache_read,
                        "cache_creation_input_tokens": cache_create,
                        "output_tokens":             output_tok,
                    },
                })
                status = "PARSE_FAIL"

            print(f"  [{i+1}/{len(selected)}] {rid} {status} "
                  f"input={input_tok} cache_read={cache_read} cache_write={cache_create} out={output_tok}")
        except Exception as e:
            print(f"  [{i+1}/{len(selected)}] {rid} ERROR {type(e).__name__}: {e}",
                  file=sys.stderr)
            results.append({
                "row_id":     rid,
                "decision":   "NEEDS_REVIEW",
                "confidence": "low",
                "page_role":  "OTHER",
                "positive_evidence": "",
                "negative_evidence": f"API error: {type(e).__name__}: {e}",
                "recommended_page":  None,
            })

    # ── Save output ──
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    model_short = "haiku" if "haiku" in model else "sonnet"
    out_path = RESULTS_DIR / f"llm_judge_results_{args.tier}_{model_short}_{ts}.json"

    out_doc = {
        "meta": {
            "stage":        "3_judge_run",
            "version":      "v1",
            "batch_file":   str(batch_path.relative_to(ROOT)),
            "tier":         args.tier,
            "model":        model,
            "run_timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "total_rows":   len(results),
            "api_called":   bool(is_apply),
            "rate_per_sec": args.rate_per_sec,
            "no_db_modification": True,
        },
        "results": results,
    }
    out_path.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OUT] {out_path.relative_to(ROOT)} ({out_path.stat().st_size:,} bytes)")

    # ── Summary ──
    if is_apply:
        decisions: dict[str, int] = {}
        for r in results:
            d = r.get("decision") or "NULL"
            decisions[d] = decisions.get(d, 0) + 1
        total_in = sum((r.get("_usage") or {}).get("input_tokens", 0) for r in results)
        total_creat = sum((r.get("_usage") or {}).get("cache_creation_input_tokens", 0) for r in results)
        total_read = sum((r.get("_usage") or {}).get("cache_read_input_tokens", 0) for r in results)
        total_out = sum((r.get("_usage") or {}).get("output_tokens", 0) for r in results)
        print("\n" + "=" * 60)
        print(f"  decisions: {decisions}")
        print(f"  cache: write={total_creat:,}  read={total_read:,}  uncached_in={total_in:,}  out={total_out:,}")
    else:
        print(f"\n[dry-run] would call {model} on {len(selected)} rows.")
        print(f"  re-run with: --run-llm --tier {args.tier}"
              + (f" --model {args.model}" if args.model else ""))

    return 0


if __name__ == "__main__":
    sys.exit(main())
