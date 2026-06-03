// generate_pdf.mjs — HWP/HWPX → per-page PDF (Chromium via rhwp SVG)
//
// usage:
//   node tools/rhwp_manual_pipeline/generate_pdf.mjs \
//        --src <HWP_PATH> --label <residence|visa|revision_history> \
//        --out-dir <DIR> [--skip-existing] [--range 1-50] [--pages 7,8,9] [--flat]
//
// --range a-b   : render a contiguous range (default: whole document)
// --pages a,b,c : render an explicit (possibly non-contiguous) page list — loads
//                 the doc once. Overrides --range. Used by changed-page review PDFs.
// --flat        : write p####.pdf directly under <out-dir>/<label>/ (no pdf_pages
//                 nesting). Used so changed-page review PDFs land in
//                 review_pdf_pages/<label>/ without creating a full rhwp_pdf/ tree.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { writeFile, mkdir, stat } from 'node:fs/promises';
import { rhwpReady, loadDoc, svgToPdf, browser, closeBrowser, parseArgs } from './_lib.mjs';

const args = parseArgs(process.argv.slice(2));
const src   = args.src;
const label = args.label;
const outDir = args['out-dir'];
const skipExisting = !!args['skip-existing'];
const flat = !!args.flat;
const range = args.range ? args.range.split('-').map(Number) : null;
const pagesArg = args.pages
  ? args.pages.split(',').map((s) => Number(s.trim())).filter((n) => Number.isFinite(n) && n >= 1)
  : null;
if (!src || !label || !outDir) {
  console.error('usage: generate_pdf.mjs --src <HWP> --label <label> --out-dir <DIR> [--skip-existing] [--range a-b] [--pages a,b,c] [--flat]');
  process.exit(1);
}

await rhwpReady();
const doc = await loadDoc(src);
const N = doc.pageCount();

// Build the 1-based page list to render.
let pageList;
if (pagesArg && pagesArg.length) {
  pageList = [...new Set(pagesArg)].filter((p) => p <= N).sort((a, b) => a - b);
} else {
  const [pStart, pEnd] = range ? [Math.max(1, range[0]), Math.min(N, range[1])] : [1, N];
  pageList = [];
  for (let i = pStart; i <= pEnd; i++) pageList.push(i);
}

const pdfDir = flat ? path.join(outDir, label) : path.join(outDir, 'pdf_pages', label);
await mkdir(pdfDir, { recursive: true });

console.log(JSON.stringify({ event: 'start', label, total_pages: N,
  render_count: pageList.length, pages: pageList.slice(0, 200) }));

const b = await browser();
const ctx = await b.newContext();
const page = await ctx.newPage();
const t0 = Date.now();
let done = 0, errs = 0, idx = 0;

for (const i of pageList) {
  idx++;
  const outPath = path.join(pdfDir, `p${String(i).padStart(4, '0')}.pdf`);
  if (skipExisting) {
    try { const s = await stat(outPath); if (s.size > 0) { done++; continue; } } catch {}
  }
  try {
    const svg = doc.renderPageSvg(i - 1);
    const pdfBuf = await svgToPdf(svg, page);
    await writeFile(outPath, pdfBuf);
    done++;
    if (idx % 50 === 0 || idx === pageList.length || idx === 1) {
      console.log(JSON.stringify({ event: 'progress', page: i, done, total: pageList.length,
        elapsed_sec: ((Date.now() - t0) / 1000).toFixed(1) }));
    }
  } catch (e) {
    errs++;
    console.log(JSON.stringify({ event: 'page_error', page: i, error: String(e?.message || e) }));
  }
}

await page.close(); await ctx.close(); await closeBrowser(); doc.free();
console.log(JSON.stringify({ event: 'done', label, done, errs,
  render_count: pageList.length,
  elapsed_sec: ((Date.now() - t0) / 1000).toFixed(1), per_page_dir: pdfDir }));
