"""
Stage 2 — LLM Judge Batch Preparation v1 (READ-ONLY, NO LLM, NO API CALL)

Builds structured judge packets for rows flagged LLM_JUDGE_REQUIRED or MANUAL_REVIEW
by Stage 1. Each packet contains the candidate page text, neighbor pages, and
metadata needed for the LLM to evaluate whether the manual_ref is correct.

Inputs (read-only):
  backend/data/manuals/manual_ref_quality_gate_v4.json
  backend/data/manuals/unlocked_체류민원.pdf
  backend/data/manuals/unlocked_사증민원.pdf

Output:
  backend/data/manuals/llm_judge_batches/batch_[YYYYMMDD_HHMMSS].json

ABSOLUTE PROHIBITIONS:
  - No LLM API call.
  - No DB modification.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

# Reuse normalize_pdf_text from Stage 1
sys.path.insert(0, str(Path(__file__).parent))
from manual_ref_quality_gate_v4 import (  # type: ignore
    normalize_pdf_text,
    get_preferred_manual,
    manual_ref_signature,
)

ROOT     = Path(__file__).parent.parent.parent
MANUALS  = ROOT / "backend" / "data" / "manuals"
QG_PATH  = MANUALS / "manual_ref_quality_gate_v4.json"
PDF_RES  = MANUALS / "unlocked_체류민원.pdf"
PDF_VIS  = MANUALS / "unlocked_사증민원.pdf"
BATCH_DIR = MANUALS / "llm_judge_batches"

ACTION_TYPE_DEFINITION = {
    "EXTRA_WORK":   "체류자격외활동허가. 신청요건·제출서류·허가기준이 직접 있어야 함.",
    "EXTEND":       "체류기간연장허가. 연장 신청요건·제출서류가 직접 있어야 함.",
    "CHANGE":       "체류자격변경허가. 변경 신청요건·제출서류가 직접 있어야 함.",
    "REGISTRATION": "외국인등록. 등록 신청요건·제출서류가 직접 있어야 함.",
    "REENTRY":      "재입국허가. 허가 신청요건·제출서류가 직접 있어야 함.",
    "GRANT":        "체류자격부여. 부여 신청요건·제출서류가 직접 있어야 함.",
    "VISA_CONFIRM": "사증발급인정서. 발급 신청요건·제출서류가 직접 있어야 함.",
    "WORKPLACE":    "근무처변경·추가. 신청요건·제출서류가 직접 있어야 함.",
    "ACTIVITY_EXTRA":            "활동범위 확대 / 단순노무 특례. 해당 카테고리의 신청요건·제출서류가 직접 있어야 함.",
    "DOMESTIC_RESIDENCE_REPORT": "국내거소신고. 신고 신청요건·제출서류가 직접 있어야 함.",
    "APPLICATION_CLAIM":         "사실증명·직접신청. 발급 신청요건·제출서류가 직접 있어야 함.",
}

NEGATIVE_EXAMPLES = [
    "자격 설명 페이지: 체류자격 해당자, 활동범위, 체류기간 상한, 세부약호만 있는 경우",
    "broad family 페이지: 여러 subtype을 묶은 개요 페이지",
    "body keyword only: 본문에 키워드만 등장하고 heading 없음",
    "next section start only: 다음 섹션 제목이 하단에만 등장",
]


class PdfReader:
    def __init__(self, paths: dict[str, Path]):
        self.docs = {name: fitz.open(str(p)) for name, p in paths.items()}

    def page_text(self, manual: str, page_no: int) -> str:
        doc = self.docs.get(manual)
        if not doc or page_no < 1 or page_no > doc.page_count:
            return ""
        raw = doc.load_page(page_no - 1).get_text() or ""
        return normalize_pdf_text(raw)

    def neighbor_pages(self, manual: str, page_no: int) -> dict[str, str]:
        out: dict[str, str] = {}
        for delta in (-2, -1, 1, 2):
            n = page_no + delta
            key = f"page_N{('+' if delta>0 else '')}{delta}"
            txt = self.page_text(manual, n)
            # truncate long pages — judge only needs context cues
            out[key] = txt[:1200] if txt else ""
        return out


def _trunc(s: str, limit: int) -> str:
    return s if len(s) <= limit else s[:limit] + "\n…(truncated)"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rows", type=int, default=0,
                    help="0=unlimited; testing limit on packet count")
    args = ap.parse_args()

    if not QG_PATH.exists():
        print(f"[ABORT] Stage 1 출력 없음: {QG_PATH}", file=sys.stderr)
        return 1

    print(f"[prepare] quality gate v4 로드: {QG_PATH.relative_to(ROOT)}")
    qg = json.loads(QG_PATH.read_text(encoding="utf-8"))
    rows = qg.get("rows") or []

    selected = [r for r in rows if r.get("recommended_next_action") in
                ("LLM_JUDGE_REQUIRED", "MANUAL_REVIEW")]
    if args.max_rows > 0:
        selected = selected[:args.max_rows]

    print(f"  total rows in qg : {len(rows)}")
    print(f"  selected         : {len(selected)} "
          f"(LLM_JUDGE_REQUIRED + MANUAL_REVIEW)")

    pdf = PdfReader({"체류민원": PDF_RES, "사증민원": PDF_VIS})

    # Build same-page cluster map
    cluster_members: dict[tuple, list[str]] = {}
    for r in rows:
        sig = manual_ref_signature(r.get("current_manual_ref"))
        if sig:
            cluster_members.setdefault(sig, []).append(r.get("row_id"))

    packets: list[dict] = []
    skipped_no_primary = 0
    for r in selected:
        primary = r.get("primary_entry") or None
        if not primary:
            skipped_no_primary += 1
            continue
        manual = primary.get("manual", "")
        page_from = int(primary.get("page_from") or 0)
        page_to = int(primary.get("page_to") or page_from)
        action = r.get("action_type", "")

        cand_text = pdf.page_text(manual, page_from)
        neighbors = pdf.neighbor_pages(manual, page_from)
        sig = manual_ref_signature(r.get("current_manual_ref"))
        cluster = cluster_members.get(sig, [])
        cluster_others = [m for m in cluster if m != r.get("row_id")][:30]

        packets.append({
            "row_id":                  r.get("row_id"),
            "detailed_code":           r.get("detailed_code"),
            "action_type":             action,
            "action_type_definition":  ACTION_TYPE_DEFINITION.get(action, ""),
            "title":                   r.get("title"),
            "preferred_manual":        get_preferred_manual(action),
            "current_manual":          manual,
            "current_page_from":       page_from,
            "current_page_to":         page_to,
            "candidate_page_text":     _trunc(cand_text, 6000),
            "neighbor_pages":          neighbors,
            "same_cluster_members":    cluster_others,
            "quality_gate_risk_types": r.get("risk_types") or [],
            "negative_examples":       NEGATIVE_EXAMPLES,
        })

    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = BATCH_DIR / f"batch_{ts}.json"

    out_doc = {
        "meta": {
            "stage":           "2_judge_prepare",
            "version":         "v1",
            "qg_source":       str(QG_PATH.relative_to(ROOT)),
            "created_at":      dt.datetime.now().isoformat(timespec="seconds"),
            "total_packets":   len(packets),
            "skipped_no_primary": skipped_no_primary,
            "no_db_modification": True,
            "no_llm_call":     True,
        },
        "packets": packets,
    }
    out_path.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OUT] {out_path.relative_to(ROOT)} ({out_path.stat().st_size:,} bytes)")

    # Verify counts
    nonempty_text = sum(1 for p in packets if p["candidate_page_text"])
    nonempty_neighbors = sum(1 for p in packets
                             if sum(1 for v in p["neighbor_pages"].values() if v) >= 2)
    print(f"\n  packets w/ candidate_page_text non-empty : {nonempty_text}/{len(packets)}")
    print(f"  packets w/ ≥2 non-empty neighbor_pages    : {nonempty_neighbors}/{len(packets)}")
    print(f"  skipped (no primary_entry)                : {skipped_no_primary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
