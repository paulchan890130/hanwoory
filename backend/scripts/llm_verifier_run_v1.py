"""
Stage 4 — LLM Verifier Runner v1

Challenges Stage 3's EXACT decisions. Rejects if broad / keyword-only / wrong manual /
next-section-only / no-direct-evidence. Always uses Sonnet 4.6 (max accuracy).

ABSOLUTE PROHIBITIONS:
  - Default mode = DRY-RUN. Only --run-verifier enables API call.
  - No DB modification. No apply.

CLI:
  python llm_verifier_run_v1.py --results FILE
                                 [--run-verifier]
                                 [--limit N]
                                 [--rate-per-sec FLOAT]
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

ROOT          = Path(__file__).parent.parent.parent
MANUALS       = ROOT / "backend" / "data" / "manuals"
RESULTS_DIR   = MANUALS / "llm_judge_results"
VERIFIER_DIR  = MANUALS / "llm_verifier_results"
BATCH_DIR     = MANUALS / "llm_judge_batches"

# Load root .env so ANTHROPIC_API_KEY can sit there alongside JWT_SECRET_KEY etc.
# (graceful fallback if python-dotenv is not installed)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

MODEL_SONNET = "claude-sonnet-4-6"

VERIFIER_SYSTEM = (
    "너는 반박 검토자다.\n"
    "1차 판정관이 EXACT라고 한 결정이 틀렸을 가능성을 찾아라.\n"
    "다음 오류 유형이 있으면 반드시 REJECT하라:\n"
    "- broad family page: 여러 subtype을 묶은 개요 페이지\n"
    "- body keyword only: heading 없이 본문 키워드만 있음\n"
    "- wrong manual: preferred manual이 아닌 매뉴얼로 매핑됨\n"
    "- next section only: 다음 섹션 시작이 페이지 하단에만 등장\n"
    "- no direct evidence: 신청요건·제출서류·허가기준이 직접 없음\n"
    "확신이 없으면 REJECT하라. 관대하게 보지 마라.\n"
    "JSON만 출력하라.\n"
    "즉시 JSON으로만 출력하라.\n"
    "'검토합니다', '페이지 텍스트를 확인합니다', 'Looking at...' 등 모든 내레이션 절대 금지.\n"
    "첫 글자가 반드시 { 이어야 한다.\n"
)


def parse_json_response(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def find_packet(batch: dict, row_id: str) -> dict | None:
    for p in (batch.get("packets") or []):
        if p.get("row_id") == row_id:
            return p
    return None


def build_user_message(packet: dict, judge_result: dict) -> str:
    nb = packet.get("neighbor_pages") or {}
    page_from = packet.get("current_page_from", 0)
    return (
        f"=== 1차 판정관의 EXACT 결정 ===\n"
        f"row_id: {judge_result.get('row_id','')}\n"
        f"decision: EXACT\n"
        f"confidence: {judge_result.get('confidence','?')}\n"
        f"page_role: {judge_result.get('page_role','?')}\n"
        f"positive_evidence: {judge_result.get('positive_evidence','')}\n"
        f"negative_evidence: {judge_result.get('negative_evidence','')}\n\n"
        f"=== 검증 대상 ===\n"
        f"업무: {packet.get('detailed_code','')} {packet.get('action_type','')} — {packet.get('title','')}\n"
        f"업무 정의: {packet.get('action_type_definition','')}\n"
        f"우선 매뉴얼: {packet.get('preferred_manual','')}\n"
        f"현재 매핑: {packet.get('current_manual','')} p.{page_from}\n\n"
        f"=== 페이지 텍스트 ({packet.get('current_manual','')} p.{page_from}) ===\n"
        f"{packet.get('candidate_page_text','')}\n\n"
        f"=== 인접 페이지 ===\n"
        f"p.{page_from-2}: {nb.get('page_N-2','')}\n\n"
        f"p.{page_from-1}: {nb.get('page_N-1','')}\n\n"
        f"p.{page_from+1}: {nb.get('page_N+1','')}\n\n"
        f"p.{page_from+2}: {nb.get('page_N+2','')}\n\n"
        f"=== 너의 임무 ===\n"
        f"위 EXACT 판정이 다음 5개 오류 패턴 중 하나에 해당하는지 검사하라:\n"
        f"  broad family page / body keyword only / wrong manual / next section only / no direct evidence\n"
        f"하나라도 해당하면 REJECT. 확신이 없으면 REJECT. 관대하게 보지 마라.\n\n"
        f"출력 형식 (JSON만):\n"
        f"{{\n"
        f'  "row_id": "{judge_result.get("row_id","")}",\n'
        f'  "verifier_decision": "ACCEPTED|REJECTED",\n'
        f'  "reject_reason": "REJECTED 일 때만 채우고, ACCEPTED 면 null",\n'
        f'  "confidence": "high|medium|low"\n'
        f"}}\n"
    )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, help="Stage 3 judge result JSON")
    ap.add_argument("--run-verifier", action="store_true",
                    help="Actually call API. Default = dry-run.")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rate-per-sec", type=float, default=1.0)
    args = ap.parse_args()

    is_apply = args.run_verifier

    results_path = Path(args.results)
    if not results_path.is_absolute():
        results_path = ROOT / results_path
    if not results_path.exists():
        print(f"[ABORT] judge results 없음: {results_path}", file=sys.stderr)
        return 1

    judge_doc = json.loads(results_path.read_text(encoding="utf-8"))
    batch_relpath = (judge_doc.get("meta") or {}).get("batch_file") or ""
    batch_path = ROOT / batch_relpath if batch_relpath else None
    if not batch_path or not batch_path.exists():
        print(f"[ABORT] referenced batch 없음: {batch_path}", file=sys.stderr)
        return 1
    batch = json.loads(batch_path.read_text(encoding="utf-8"))

    exact_rows = [r for r in (judge_doc.get("results") or []) if r.get("decision") == "EXACT"]
    if args.limit > 0:
        exact_rows = exact_rows[:args.limit]

    print(f"[verify] judge results : {results_path.relative_to(ROOT)}")
    print(f"[verify] batch source  : {batch_path.relative_to(ROOT)}")
    print(f"[verify] model         : {MODEL_SONNET}")
    print(f"[verify] mode          : {'APPLY (--run-verifier)' if is_apply else 'DRY-RUN'}")
    print(f"[verify] EXACT rows    : {len(exact_rows)}")

    if not exact_rows:
        print("[verify] no EXACT rows to verify — exit.")
        # Still write empty output for pipeline consistency
        VERIFIER_DIR.mkdir(parents=True, exist_ok=True)
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = VERIFIER_DIR / f"llm_verifier_results_{ts}.json"
        out_path.write_text(json.dumps({
            "meta": {
                "stage": "4_verifier",
                "judge_results_file": str(results_path.relative_to(ROOT)),
                "model": MODEL_SONNET,
                "api_called": False,
                "total_rows": 0,
            },
            "results": [],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OUT] {out_path.relative_to(ROOT)} (empty)")
        return 0

    if is_apply:
        try:
            import anthropic  # type: ignore
        except ImportError:
            print(f"[ABORT] anthropic SDK 미설치", file=sys.stderr)
            return 1
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("[ABORT] ANTHROPIC_API_KEY 환경변수 필요. "
                  "shell에서 'export ANTHROPIC_API_KEY=sk-ant-...' 또는 "
                  "root .env 파일에 ANTHROPIC_API_KEY=sk-ant-... 추가 후 재실행.",
                  file=sys.stderr)
            return 1
        client = anthropic.Anthropic()
    else:
        client = None

    out_results: list[dict] = []
    sample_shown = False
    min_interval = 1.0 / max(args.rate_per_sec, 0.01)
    last_ts = 0.0

    for i, jr in enumerate(exact_rows):
        rid = jr.get("row_id")
        packet = find_packet(batch, rid)
        if not packet:
            out_results.append({
                "row_id": rid,
                "verifier_decision": "REJECTED",
                "reject_reason": "packet not found in batch",
                "confidence": "low",
            })
            continue
        user_msg = build_user_message(packet, jr)

        if not is_apply:
            if not sample_shown:
                print("\n" + "=" * 60)
                print(f"SAMPLE VERIFIER PROMPT (row {rid})")
                print("=" * 60)
                print("--- system ---")
                print(VERIFIER_SYSTEM)
                print("--- user ---")
                preview = user_msg if len(user_msg) <= 1500 else user_msg[:1500] + "\n…(truncated)"
                print(preview)
                print("=" * 60)
                sample_shown = True
            out_results.append({
                "row_id": rid,
                "verifier_decision": None,
                "reject_reason": None,
                "confidence": None,
                "_dry_run": True,
            })
            continue

        # rate limit
        now = time.time()
        wait = min_interval - (now - last_ts)
        if wait > 0:
            time.sleep(wait)
        last_ts = time.time()

        try:
            response = client.messages.create(  # type: ignore
                model=MODEL_SONNET,
                max_tokens=1024,
                system=[
                    {
                        "type": "text",
                        "text": VERIFIER_SYSTEM,
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

            if parsed and parsed.get("verifier_decision") in ("ACCEPTED", "REJECTED"):
                parsed["row_id"] = rid
                parsed["_usage"] = {
                    "input_tokens": input_tok,
                    "cache_read_input_tokens": cache_read,
                    "cache_creation_input_tokens": cache_create,
                    "output_tokens": output_tok,
                }
                out_results.append(parsed)
                status = parsed["verifier_decision"]
            else:
                out_results.append({
                    "row_id": rid,
                    "verifier_decision": "REJECTED",
                    "reject_reason": "응답 파싱 실패",
                    "confidence": "low",
                    "_raw_response": text[:300],
                })
                status = "PARSE_FAIL→REJECT"
            print(f"  [{i+1}/{len(exact_rows)}] {rid} {status}")
        except Exception as e:
            print(f"  [{i+1}/{len(exact_rows)}] {rid} ERROR {type(e).__name__}: {e}",
                  file=sys.stderr)
            out_results.append({
                "row_id": rid,
                "verifier_decision": "REJECTED",
                "reject_reason": f"API error: {type(e).__name__}: {e}",
                "confidence": "low",
            })

    # Save
    VERIFIER_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = VERIFIER_DIR / f"llm_verifier_results_{ts}.json"
    out_doc = {
        "meta": {
            "stage": "4_verifier",
            "version": "v1",
            "judge_results_file": str(results_path.relative_to(ROOT)),
            "batch_file": batch_relpath,
            "model": MODEL_SONNET,
            "run_timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "total_rows": len(out_results),
            "api_called": bool(is_apply),
            "no_db_modification": True,
        },
        "results": out_results,
    }
    out_path.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OUT] {out_path.relative_to(ROOT)} ({out_path.stat().st_size:,} bytes)")

    if is_apply:
        decisions = {}
        for r in out_results:
            d = r.get("verifier_decision") or "NULL"
            decisions[d] = decisions.get(d, 0) + 1
        print(f"  decisions: {decisions}")
    else:
        print(f"\n[dry-run] would call sonnet on {len(exact_rows)} EXACT rows.")
        print(f"  re-run with: --run-verifier")

    return 0


if __name__ == "__main__":
    sys.exit(main())
