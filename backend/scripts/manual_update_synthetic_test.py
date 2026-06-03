"""Synthetic-change test for the local manual update pipeline.

Picks a single residence page (default p.741 — same page involved in M1-0088)
and simulates a content edit by mutating its ``normalized_text_hash`` in the
JSONL copy. Runs diff + affected-only candidate generation, and (unless
``--no-pdf``) generates changed-page review PDFs for the affected page ± 1.

Goal: prove that **only** the manual_ref entries whose page range overlaps
the synthetic-change page appear in the candidate list, and that changed-page
review PDFs are generated only for affected pages + neighbors — never a full
365-entry review and never a full-document PDF.

Outputs:
  backend/data/manuals/staging/synthetic_test/diff/...
  backend/data/manuals/staging/synthetic_test/candidates/...
  backend/data/manuals/staging/synthetic_test/review_pdf_pages/...
  backend/data/manuals/staging/synthetic_test/manifest.json

This script does NOT mutate any source HWP or any official file.
"""
from __future__ import annotations
import argparse, datetime, json, pathlib, re, sys

sys.stdout.reconfigure(encoding='utf-8')  # type: ignore[union-attr]

ROOT = pathlib.Path(__file__).resolve().parents[2]
BASELINE = ROOT / 'backend/data/manuals/baseline/260414/manifest.json'
INCOMING = ROOT / 'backend/data/manuals/incoming'
sys.path.insert(0, str(ROOT))
from backend.scripts.manual_update_local import (
    diff_pages, make_ref_candidates, write_candidates, load_jsonl,
    collect_affected_pages, generate_changed_page_pdfs, classify_label,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--mutate-residence-page', type=int, default=741,
                    help='which residence rhwp page to flag as modified')
    ap.add_argument('--neighbor', type=int, default=1, help='changed page ± N')
    ap.add_argument('--no-pdf', action='store_true',
                    help='skip changed-page review PDF generation (diff-only)')
    args = ap.parse_args()

    staging = ROOT / 'backend/data/manuals/staging/synthetic_test'
    for sub in ('diff', 'candidates', 'reports', 'review_pdf_pages', 'logs'):
        (staging / sub).mkdir(parents=True, exist_ok=True)

    base = json.loads(BASELINE.read_text(encoding='utf-8'))
    base_manuals = base['manuals']

    # Load baseline pages
    res_baseline_jsonl = ROOT / base_manuals['residence']['rhwp_jsonl']['path']
    res_pages = load_jsonl(res_baseline_jsonl)
    visa_baseline_jsonl = ROOT / base_manuals['visa']['rhwp_jsonl']['path']
    visa_pages = load_jsonl(visa_baseline_jsonl)

    # Mutate the chosen page's normalized_text_hash so diff sees it as 'modified'
    target = args.mutate_residence_page
    new_res = [dict(p) for p in res_pages]
    for p in new_res:
        if p['rhwp_page_index'] == target:
            p['normalized_text_hash'] = 'synthetic_modified_' + (p.get('normalized_text_hash') or '')
            p['text'] = '【SYNTHETIC CHANGE】 ' + p.get('text', '')
            break

    # Diff
    changed_res  = diff_pages(res_pages, new_res)
    changed_visa = diff_pages(visa_pages, visa_pages)  # zero change for visa
    changed = changed_res + changed_visa

    non_same = [c for c in changed if c['change_type'] != 'same']
    print(f'[synthetic] non-same pages: {len(non_same)}')
    for c in non_same[:10]:
        print(f'  {c["manual_label"]}  baseline_p{c["baseline_page"]} → new_p{c["new_page"]}  {c["change_type"]}')

    # combined changed_pages.json = non-same only (matches manual_update_local
    # and the /changed-pages endpoint contract)
    (staging / 'diff' / 'changed_pages.json').write_text(
        json.dumps(non_same, ensure_ascii=False, indent=2), encoding='utf-8')

    # Candidates — affected only
    new_pages_by_label = {'residence': new_res, 'visa': visa_pages}
    candidates = make_ref_candidates(changed, new_pages_by_label)
    print(f'[candidates] {len(candidates)} affected manual_ref rows (out of 365 total)')
    for c in candidates:
        print(f'  {c["row_id"]} ({c["detailed_code"]}) {c["manual_label"]} '
              f'p.{c["old_page_from"]}-{c["old_page_to"]} → '
              f'p.{c["candidate_page_from"]}-{c["candidate_page_to"]} [{c["confidence"]}]')

    write_candidates(candidates, staging / 'candidates')

    # ── changed-page review PDFs (affected page ± neighbor only) ──────────────
    pdf_mode = 'none'
    review_pdf_pages: dict[str, list[int]] = {}
    if not args.no_pdf:
        page_counts = {'residence': len(new_res), 'visa': len(visa_pages)}
        affected = collect_affected_pages(non_same, args.neighbor, page_counts)
        # locate the residence source HWP in incoming/
        src_by_label: dict[str, pathlib.Path] = {}
        if INCOMING.exists():
            for p in INCOMING.iterdir():
                if p.is_file() and p.suffix.lower() in ('.hwp', '.hwpx'):
                    lbl = classify_label(p.name)
                    if lbl:
                        src_by_label[lbl] = p
        if affected and src_by_label:
            print(f'[pdf] rendering changed pages ± {args.neighbor}: '
                  + ', '.join(f'{k}={v}' for k, v in affected.items()))
            review_pdf_pages = generate_changed_page_pdfs(
                affected, src_by_label,
                staging / 'review_pdf_pages', staging / 'logs')
            pdf_mode = 'changed-pages-only'
            for label, pages in review_pdf_pages.items():
                print(f'  {label}: review pages {pages}')
        else:
            print('[pdf] no affected pages or source HWP — skipping review PDFs')

    manifest = {
        'version': 'synthetic_test',
        'baseline_version': '260414',
        'created_at': datetime.datetime.now().isoformat(timespec='seconds'),
        'status': 'SYNTHETIC_DIFF_ONLY',
        'mutation': {'manual_label': 'residence', 'modified_page': target},
        'changed_pages_summary': {
            'residence': {'modified': sum(1 for c in changed_res if c['change_type']=='modified'),
                          'same':     sum(1 for c in changed_res if c['change_type']=='same')},
            'visa':      {'same':     sum(1 for c in changed_visa if c['change_type']=='same')},
        },
        'changed_page_count': len(non_same),
        'manual_ref_candidate_count': len(candidates),
        'pdf_mode': pdf_mode,
        'review_pdf_pages': review_pdf_pages,
        'note': 'Synthetic — no HWP/HWPX mutated, no full PDF generated. '
                'Diff + affected-only candidates + changed-page review PDFs.',
    }
    (staging / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    rep = [f'# synthetic_test report\n', f'mutation: residence p.{target} normalized_text_hash modified\n',
           f'changed pages: {len(non_same)} (residence)',
           f'manual_ref candidates: **{len(candidates)}** (affected only)',
           '',
           '## affected rows']
    for c in candidates:
        rep.append(f'- {c["row_id"]} `{c["detailed_code"]}` ({c["business_name"]}) '
                   f'p.{c["old_page_from"]}-{c["old_page_to"]} → '
                   f'p.{c["candidate_page_from"]}-{c["candidate_page_to"]}  [{c["confidence"]} / {c["action"]}]')
    (staging / 'reports' / 'synthetic_report.md').write_text('\n'.join(rep) + '\n', encoding='utf-8')

    print(f'\n[manifest] {staging / "manifest.json"}')
    print('[done] synthetic test complete. No production data changed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
