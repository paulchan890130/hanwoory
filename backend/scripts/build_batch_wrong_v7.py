"""
Build fresh LLM judge batch for 15 target rows:
  - 13 WRONG NEEDS_MANUAL_CHECK (wrong current page)
  - 2 heuristic miss (confirmed-correct mapping flagged FAIL by QG)

Uses current DB state (post-v7) + live PDF extraction.
No DB modification. No LLM call.

Output: backend/data/manuals/llm_judge_batches/batch_wrong_v7_[timestamp].json
"""
from __future__ import annotations
import datetime as dt
import json
import re
import sys
from pathlib import Path

import fitz

ROOT    = Path(__file__).parent.parent.parent
MANUALS = ROOT / "backend" / "data" / "manuals"
DB_PATH = ROOT / "backend" / "data" / "immigration_guidelines_db_v2.json"
PDF_RES = MANUALS / "unlocked_체류민원.pdf"
PDF_VIS = MANUALS / "unlocked_사증민원.pdf"
QG_PATH = MANUALS / "manual_ref_quality_gate_v4.json"
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
}

NEGATIVE_EXAMPLES = [
    "자격 설명 페이지: 체류자격 해당자, 활동범위, 체류기간 상한, 세부약호만 있는 경우",
    "broad family 페이지: 여러 subtype을 묶은 개요 페이지",
    "body keyword only: 본문에 키워드만 등장하고 heading 없음",
    "next section start only: 다음 섹션 제목이 하단에만 등장",
]

# 13 WRONG rows + 2 heuristic miss
TARGET_IDS = [
    "M1-0086", "M1-0091", "M1-0112", "M1-0113", "M1-0124",
    "M1-0175", "M1-0198", "M1-0256", "M1-0320",
    "M1-0364", "M1-0365", "M1-0367", "M1-0369",
    "M1-0284", "M1-0366",  # heuristic miss
]
HEURISTIC_MISS = {"M1-0284", "M1-0366"}


def get_preferred_manual(action_type: str) -> str:
    if action_type == "VISA_CONFIRM":
        return "사증민원"
    return "체류민원"


def normalize_pdf_text(text: str) -> str:
    pats = [
        (r"체류자격\s*부\s*여", "체류자격부여"),
        (r"근무처의?\s*변경[·\s]*추가", "근무처변경추가"),
        (r"체류자격\s*외\s*활동", "체류자격외활동"),
        (r"사증\s*발급\s*인정서", "사증발급인정서"),
        (r"외국인\s*등록", "외국인등록"),
        (r"재입국\s*허가", "재입국허가"),
        (r"체류기간\s*연장", "체류기간연장"),
        (r"체류자격\s*변경", "체류자격변경"),
    ]
    import re
    out = text
    for pat, repl in pats:
        out = re.sub(pat, repl, out)
    out = re.sub(r"[ \t　]+", " ", out)
    return out


class PdfReader:
    def __init__(self):
        self._docs = {
            "체류민원": fitz.open(str(PDF_RES)),
            "사증민원": fitz.open(str(PDF_VIS)),
        }

    def text(self, manual: str, page_no: int) -> str:
        doc = self._docs.get(manual)
        if not doc or page_no < 1 or page_no > doc.page_count:
            return ""
        return normalize_pdf_text(doc.load_page(page_no - 1).get_text() or "")

    def neighbors(self, manual: str, page_no: int) -> dict[str, str]:
        out: dict[str, str] = {}
        for d in (-2, -1, 1, 2):
            key = f"page_N{'+' if d > 0 else ''}{d}"
            out[key] = self.text(manual, page_no + d)[:1200]
        return out


def manual_ref_sig(refs: list) -> tuple:
    return tuple(sorted(
        (e.get("manual", ""), e.get("page_from", 0), e.get("page_to", 0))
        for e in (refs or [])
    ))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    print("[build] Loading DB, QG...")
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    db_idx = {r["row_id"]: r for r in db["master_rows"]}

    qg = json.loads(QG_PATH.read_text(encoding="utf-8"))
    qg_idx = {r["row_id"]: r for r in qg["rows"]}

    # Cluster map for same_cluster_members
    sig_groups: dict[tuple, list[str]] = {}
    for r in db["master_rows"]:
        sig = manual_ref_sig(r.get("manual_ref"))
        if sig:
            sig_groups.setdefault(sig, []).append(r["row_id"])

    pdf = PdfReader()
    packets = []
    for rid in TARGET_IDS:
        db_row = db_idx.get(rid)
        qg_row = qg_idx.get(rid, {})
        if not db_row:
            print(f"  [skip] {rid} not in DB")
            continue

        refs = db_row.get("manual_ref") or []
        # Primary: prefer matching preferred_manual, then first
        action = db_row.get("action_type", "")
        pref_m = get_preferred_manual(action)
        prim = None
        for e in refs:
            if e.get("manual") == pref_m:
                prim = e
                break
        if not prim and refs:
            prim = refs[0]

        if not prim:
            print(f"  [skip-no-ref] {rid} has empty manual_ref")
            continue

        manual = prim.get("manual", "체류민원")
        page_from = int(prim.get("page_from") or 0)
        page_to   = int(prim.get("page_to") or page_from)

        cand_text = pdf.text(manual, page_from)
        neighbors = pdf.neighbors(manual, page_from)

        sig = manual_ref_sig(refs)
        cluster_others = [m for m in sig_groups.get(sig, []) if m != rid][:30]

        risk_types = list(qg_row.get("risk_types") or [])
        if rid in HEURISTIC_MISS:
            risk_types = ["HEURISTIC_MISS_CONFIRMED_CORRECT"]

        packets.append({
            "row_id":                 rid,
            "detailed_code":          db_row.get("detailed_code", ""),
            "action_type":            action,
            "action_type_definition": ACTION_TYPE_DEFINITION.get(action, ""),
            "title":                  db_row.get("business_name", ""),
            "preferred_manual":       pref_m,
            "current_manual":         manual,
            "current_page_from":      page_from,
            "current_page_to":        page_to,
            "candidate_page_text":    cand_text[:6000],
            "neighbor_pages":         neighbors,
            "same_cluster_members":   cluster_others,
            "quality_gate_risk_types": risk_types,
            "quality_gate_status":    qg_row.get("quality_status", "UNKNOWN"),
            "is_heuristic_miss":      rid in HEURISTIC_MISS,
            "negative_examples":      NEGATIVE_EXAMPLES,
        })

    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = BATCH_DIR / f"batch_wrong_v7_{ts}.json"
    out_doc = {
        "meta": {
            "stage":             "wrong_v7_judge_prepare",
            "version":           "v7",
            "total_packets":     len(packets),
            "wrong_packets":     len([p for p in packets if not p["is_heuristic_miss"]]),
            "heuristic_miss":    len([p for p in packets if p["is_heuristic_miss"]]),
            "db_path":           str(DB_PATH.relative_to(ROOT)),
            "qg_source":         str(QG_PATH.relative_to(ROOT)),
            "created_at":        dt.datetime.now().isoformat(timespec="seconds"),
            "no_db_modification": True,
            "no_llm_call":       True,
        },
        "packets": packets,
    }
    out_path.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OUT] {out_path.relative_to(ROOT)} ({out_path.stat().st_size:,} bytes)")

    # Verify packets
    non_empty = sum(1 for p in packets if p["candidate_page_text"])
    neighbor_ok = sum(1 for p in packets
                      if sum(1 for v in p["neighbor_pages"].values() if v) >= 2)
    print(f"  total packets            : {len(packets)}")
    print(f"  wrong rows               : {sum(1 for p in packets if not p['is_heuristic_miss'])}")
    print(f"  heuristic_miss rows      : {sum(1 for p in packets if p['is_heuristic_miss'])}")
    print(f"  non-empty candidate_text : {non_empty}")
    print(f"  ≥2 non-empty neighbors   : {neighbor_ok}")
    return out_path


if __name__ == "__main__":
    main()
