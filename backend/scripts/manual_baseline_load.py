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
# 적재 대상 라벨(고정). manifest 의 Windows 경로에 의존하지 않는다.
LABELS = ("residence", "visa", "revision_history")


def _load_jsonl(p: Path) -> list[dict]:
    return [json.loads(line) for line in p.open(encoding="utf-8") if line.strip()]


def _baseline_dir(version: str) -> Path:
    return MANUALS / "baseline" / version


def _resolve_rel(rel: str) -> list[Path]:
    """manifest 의 repo-relative 경로(백슬래시 포함 가능)를 pathlib 로 정규화하여
    가능한 해석 후보들을 반환한다. Windows 백슬래시 → '/' 정규화 필수(Linux 대응)."""
    norm = (rel or "").replace("\\", "/").strip()
    if not norm:
        return []
    cands = [ROOT / norm]
    idx = norm.find("manuals/")
    if idx >= 0:
        cands.append(MANUALS / norm[idx + len("manuals/"):])
    return cands


def _find_page_jsonl(version: str, label: str, manifest: dict) -> tuple[Path | None, str]:
    """라벨별 baseline JSONL 을 결정적 우선순위로 탐색한다. (Path|None, source 설명) 반환.

    우선순위:
      1) baseline/{version}/rhwp_text/{label}_pages.jsonl   (이미지 동봉 — 1순위)
      2) baseline/{version}/{label}_pages.jsonl
      3) manifest.json 의 rhwp_jsonl.path (백슬래시 정규화, 존재할 때만)
    """
    bdir = _baseline_dir(version)
    p1 = bdir / "rhwp_text" / f"{label}_pages.jsonl"
    if p1.exists():
        return p1, "rhwp_text/"
    p2 = bdir / f"{label}_pages.jsonl"
    if p2.exists():
        return p2, "baseline/"
    # manifest 경로 (label 키는 rhwp 라벨과 동일 가정; 아니면 무시)
    meta = (manifest.get("manuals") or {}).get(label) or {}
    rel = (meta.get("rhwp_jsonl") or {}).get("path")
    if rel:
        for cand in _resolve_rel(rel):
            if cand and cand.exists():
                return cand, f"manifest({rel})"
    return None, "MISSING"


def _generate_jsonl(version: str, hwp_dir: Path, labels_needed: list[str]) -> list[str]:
    """baseline HWP/HWPX 에서 rhwp extract 로 누락 JSONL 을 생성(이미지 동봉 경로에).

    HWP 원본이 없으면 해당 라벨은 건너뛰고 경고만 남긴다(생성 불가). 생성된 라벨 목록 반환.
    chromium 불필요(extract 전용)."""
    from backend.scripts.manual_update_local import NODE_TOOLS, run_node, classify_label
    out_dir = _baseline_dir(version) / "rhwp_text"
    out_dir.mkdir(parents=True, exist_ok=True)
    src_by_label: dict[str, Path] = {}
    if hwp_dir.exists():
        for p in sorted(hwp_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in (".hwp", ".hwpx"):
                lbl = classify_label(p.name)
                if lbl:
                    src_by_label.setdefault(lbl, p)
    generated: list[str] = []
    for lbl in labels_needed:
        src = src_by_label.get(lbl)
        if not src:
            print(f"[generate] {lbl}: no HWP/HWPX source in {hwp_dir} — cannot generate",
                  file=sys.stderr)
            continue
        print(f"[generate] {lbl}: extracting from {src.name} → rhwp_text/")
        run_node([
            str(NODE_TOOLS / "extract.mjs"),
            "--src", str(src), "--label", lbl, "--out-dir", str(out_dir),
        ], out_dir / f"extract_{lbl}.log")
        generated.append(lbl)
    return generated


def collect_pages(baseline_version: str, *, generate_missing: bool = False,
                  hwp_dir: Path | None = None) -> dict[str, list[dict]]:
    """라벨별 baseline 페이지(JSONL)를 결정적 우선순위로 로드. 누락 라벨은 명확히 표시.

    generate_missing=True 면 누락 라벨을 baseline HWP/HWPX 에서 rhwp extract 로 생성 시도."""
    bdir = _baseline_dir(baseline_version)
    manifest_p = bdir / "manifest.json"
    manifest = {}
    if manifest_p.exists():
        try:
            manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[warn] manifest 읽기 실패({manifest_p}): {e}", file=sys.stderr)

    # 1차 탐색
    found: dict[str, Path] = {}
    missing: list[str] = []
    for label in LABELS:
        jp, src = _find_page_jsonl(baseline_version, label, manifest)
        if jp:
            found[label] = jp
            print(f"[pages] {label}: {jp.relative_to(ROOT) if str(jp).startswith(str(ROOT)) else jp}  (source: {src})")
        else:
            missing.append(label)
            print(f"[ERROR] baseline pages missing: {label} "
                  f"(searched rhwp_text/, baseline/, manifest)", file=sys.stderr)

    # 누락분 생성 시도
    if missing and generate_missing:
        gen_dir = hwp_dir or (bdir / "src")
        print(f"[generate-missing-jsonl] HWP 탐색 경로: {gen_dir}")
        gen = _generate_jsonl(baseline_version, gen_dir, missing)
        for label in list(missing):
            jp, src = _find_page_jsonl(baseline_version, label, manifest)
            if jp:
                found[label] = jp
                missing.remove(label)
                print(f"[pages] {label}: generated → {jp.name}")

    out: dict[str, list[dict]] = {label: _load_jsonl(jp) for label, jp in found.items()}
    if missing:
        print(f"[warn] 여전히 누락된 라벨: {missing} — 해당 라벨 baseline pages 없음", file=sys.stderr)
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


def _diagnose(version: str) -> None:
    """이미지/디스크에 실제로 어떤 baseline 파일이 있는지 진단 출력(원인 즉시 파악용)."""
    bdir = _baseline_dir(version)
    print(f"[diagnose] baseline dir: {bdir} (exists={bdir.exists()})")
    if bdir.exists():
        for p in sorted(bdir.rglob("*")):
            if p.is_file():
                rel = p.relative_to(bdir)
                print(f"  - {rel}  ({p.stat().st_size} bytes)")


def main() -> int:
    ap = argparse.ArgumentParser(description="baseline → PostgreSQL 적재 (기본 dry-run)")
    ap.add_argument("--baseline-version", default="260414")
    ap.add_argument("--commit", action="store_true",
                    help="실제 PG 적재 (미지정 시 dry-run — DB 미변경)")
    ap.add_argument("--generate-missing-jsonl", action="store_true",
                    help="누락 라벨을 baseline HWP/HWPX 에서 rhwp extract 로 생성 시도")
    ap.add_argument("--hwp-dir", default=None,
                    help="--generate-missing-jsonl 시 HWP/HWPX 탐색 경로 (기본 baseline/{version}/src)")
    ap.add_argument("--diagnose", action="store_true",
                    help="baseline 디렉토리 파일 목록만 출력하고 종료")
    args = ap.parse_args()

    if args.diagnose:
        _diagnose(args.baseline_version)
        return 0

    hwp_dir = Path(args.hwp_dir) if args.hwp_dir else None
    pages_by_label = collect_pages(args.baseline_version,
                                   generate_missing=args.generate_missing_jsonl,
                                   hwp_dir=hwp_dir)
    refs = collect_refs()

    total_pages = sum(len(v) for v in pages_by_label.values())
    missing_labels = [L for L in LABELS if L not in pages_by_label or not pages_by_label[L]]

    print(f"[baseline] version={args.baseline_version}")
    for label in LABELS:
        n = len(pages_by_label.get(label, []))
        print(f"  - {label}: {n} pages")
    print(f"  - manual_base_refs: {len(refs)} rows (from immigration_guidelines_db_v2.json, read-only)")
    print(f"  - total pages: {total_pages}; missing labels: {missing_labels or '없음'}")

    if not args.commit:
        if total_pages == 0:
            print("\n[dry-run][ERROR] baseline pages 0건 — 적재 소스가 없습니다. "
                  "backend/data/manuals/baseline/{ver}/rhwp_text/*.jsonl 동봉 또는 "
                  "--generate-missing-jsonl(+--hwp-dir) 필요. --diagnose 로 파일 확인.",
                  file=sys.stderr)
        elif missing_labels:
            print(f"\n[dry-run][WARN] 누락 라벨 있음: {missing_labels} — --commit 시 차단됩니다.",
                  file=sys.stderr)
        print("\n[dry-run] DB 미적재. 실제 적재하려면 --commit 을 주세요 "
              "(DATABASE_URL + FEATURE_PG_MANUAL_UPDATE=true 필요).")
        return 0

    # ── commit guard: pages 0건/누락이면 hard fail (refs만 적재되는 사고 방지) ──
    if total_pages == 0:
        print("[FATAL] baseline pages 0건 — --commit 중단. manual_base_pages 가 비면 "
              "자동 diff 기준이 없어집니다. JSONL 동봉 또는 --generate-missing-jsonl 후 재시도.",
              file=sys.stderr)
        return 3
    if missing_labels:
        print(f"[FATAL] 누락 라벨 {missing_labels} — --commit 중단. 모든 라벨 baseline pages 가 "
              f"있어야 적재합니다 (부분 적재 금지).", file=sys.stderr)
        return 3

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
