"""manual_baseline_load — 기준 매뉴얼(baseline)을 PostgreSQL 에 1회 적재.

데이터 출처:
* 페이지 텍스트/hash: 기존 baseline rhwp JSONL
  (backend/data/manuals/baseline/{version}/manifest.json 의 manuals.{label}.rhwp_jsonl.path)
* manual_ref 미러: immigration_guidelines_db_v2.json (읽기 전용 — 절대 수정 안 함)

대상 테이블: manual_base_versions, manual_base_pages, manual_base_refs

기본은 **dry-run**(요약만 출력, DB 미적재). 실제 적재는 --commit 을 줄 때만 수행한다.
(이번 작업에서는 적재를 실행하지 않는다 — 코드/사용법만 제공.)

사용법:
    # 미리보기(DB 미적재)
    python -m backend.scripts.manual_baseline_load --baseline-version 260414
    # 실제 적재 (PG 필요: DATABASE_URL + FEATURE_PG_MANUAL_UPDATE=true)
    python -m backend.scripts.manual_baseline_load --baseline-version 260414 --commit
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MANUALS = Path(os.environ.get("MANUALS_DATA_DIR", str(ROOT / "backend" / "data" / "manuals")))
DB_PATH = ROOT / "backend" / "data" / "immigration_guidelines_db_v2.json"  # 읽기 전용

# kr 매뉴얼명 → rhwp 라벨
KR_TO_LABEL = {"체류민원": "residence", "사증민원": "visa"}


def _load_jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.open(encoding="utf-8") if line.strip()]


def _resolve_under_manuals(rel: str) -> Path:
    """baseline manifest 의 repo-relative 경로를 MANUALS 기준으로도 해석."""
    p = ROOT / rel
    if p.exists():
        return p
    norm = rel.replace("\\", "/")
    idx = norm.find("manuals/")
    if idx >= 0:
        return MANUALS / norm[idx + len("manuals/"):]
    return p


def collect_pages(baseline_version: str) -> dict[str, list[dict]]:
    """baseline manifest 에서 라벨별 페이지 리스트(JSONL)를 로드."""
    manifest_p = MANUALS / "baseline" / baseline_version / "manifest.json"
    if not manifest_p.exists():
        raise FileNotFoundError(f"baseline manifest not found: {manifest_p}")
    manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
    out: dict[str, list[dict]] = {}
    for label, meta in (manifest.get("manuals") or {}).items():
        rel = (meta.get("rhwp_jsonl") or {}).get("path")
        if not rel:
            print(f"[warn] {label}: no rhwp_jsonl.path in manifest — skipped", file=sys.stderr)
            continue
        jp = _resolve_under_manuals(rel)
        if not jp.exists():
            print(f"[warn] {label}: jsonl missing ({jp}) — skipped", file=sys.stderr)
            continue
        out[label] = _load_jsonl(jp)
    return out


def collect_refs() -> list[dict]:
    """immigration_guidelines_db_v2.json(읽기 전용)에서 manual_ref 미러 행 생성."""
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    refs: list[dict] = []
    for row in db.get("master_rows", []):
        rid = row.get("row_id")
        for i, ref in enumerate(row.get("manual_ref") or []):
            kr = ref.get("manual")
            refs.append({
                "row_id": rid,
                "item_index": i,
                "manual_kr": kr,
                "manual_label": KR_TO_LABEL.get(kr),
                "page_from": int(ref.get("page_from") or 0) or None,
                "page_to": int(ref.get("page_to") or 0) or None,
                "match_text": ref.get("match_text"),
                "match_type": ref.get("match_type"),
                "detailed_code": row.get("detailed_code"),
                "business_name": row.get("business_name"),
                "major_action_std": row.get("major_action_std"),
            })
    return refs


def main() -> int:
    ap = argparse.ArgumentParser(description="baseline → PostgreSQL 적재 (기본 dry-run)")
    ap.add_argument("--baseline-version", default="260414")
    ap.add_argument("--commit", action="store_true",
                    help="실제 PG 적재 (미지정 시 dry-run — DB 미변경)")
    args = ap.parse_args()

    pages_by_label = collect_pages(args.baseline_version)
    refs = collect_refs()

    print(f"[baseline] version={args.baseline_version}")
    for label, pages in pages_by_label.items():
        print(f"  - {label}: {len(pages)} pages")
    print(f"  - manual_base_refs: {len(refs)} rows (from immigration_guidelines_db_v2.json, read-only)")

    if not args.commit:
        print("\n[dry-run] DB 미적재. 실제 적재하려면 --commit 을 주세요 "
              "(DATABASE_URL + FEATURE_PG_MANUAL_UPDATE=true 필요).")
        return 0

    # 실제 적재
    from backend.services import manual_update_pg_service as svc
    if not svc.pg_enabled():
        print("[FATAL] PG 비활성 — DATABASE_URL 및 FEATURE_PG_MANUAL_UPDATE=true 확인", file=sys.stderr)
        return 2
    for label, pages in pages_by_label.items():
        bid = svc.upsert_base_version(
            label=label, version=args.baseline_version, source_sha256=None,
            page_count=len(pages), pages=pages, note="loaded by manual_baseline_load",
        )
        print(f"  [load] {label}: base_version_id={bid}, {len(pages)} pages")
    n = svc.replace_base_refs(refs, snapshot_tag=args.baseline_version)
    print(f"  [load] manual_base_refs: {n} rows")
    print("[done] baseline 적재 완료. immigration_guidelines_db_v2.json 미수정.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
