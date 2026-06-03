// extract.mjs — HWP/HWPX → JSONL + per-page text files + meta.json
//
// usage:
//   node tools/rhwp_manual_pipeline/extract.mjs \
//        --src <HWP_PATH> --label <residence|visa|revision_history> --out-dir <DIR>
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { writeFile, mkdir, open } from 'node:fs/promises';
import crypto from 'node:crypto';
import { rhwpReady, loadDoc, flattenPageText, parseArgs } from './_lib.mjs';

const RE_CODE  = /\b([CDEFHKW]-\d+(?:-\d+)?)\b/g;
const RE_PMARK = /-\s*(\d{1,4})\s*-/;

function normalize(s) {
  return s.replace(/[\s　]+/g, '').replace(/[-‐‑‒–—―]/g, '-');
}

const args = parseArgs(process.argv.slice(2));
const src   = args.src;
const label = args.label;
const outDir = args['out-dir'];
const maxPages = args['max-pages'] ? Number(args['max-pages']) : null;
if (!src || !label || !outDir) {
  console.error('usage: extract.mjs --src <HWP> --label <label> --out-dir <DIR> [--max-pages N]');
  process.exit(1);
}

const { version } = await rhwpReady();
console.log(JSON.stringify({ event: 'start', rhwp_version: version, src, label, outDir, max_pages: maxPages }));

const doc = await loadDoc(src);
const full_page_count = doc.pageCount();
const pc = maxPages && maxPages > 0 ? Math.min(maxPages, full_page_count) : full_page_count;

await mkdir(outDir, { recursive: true });
const pageTextDir = path.join(outDir, 'page_text', label);
await mkdir(pageTextDir, { recursive: true });

const jsonlPath = path.join(outDir, `${label}_pages.jsonl`);
const fh = await open(jsonlPath, 'w');
let total_chars = 0;
const t0 = Date.now();

for (let i = 0; i < pc; i++) {
  const layout = doc.getPageTextLayout(i);
  const text = flattenPageText(layout);
  total_chars += text.length;
  const norm = normalize(text);
  const text_hash = crypto.createHash('sha1').update(text).digest('hex');
  const normalized_text_hash = crypto.createHash('sha1').update(norm).digest('hex');
  const codes = new Set();
  let m; const re = new RegExp(RE_CODE.source, 'g');
  while ((m = re.exec(text))) codes.add(m[1]);
  const pmark = text.match(RE_PMARK);
  const row = {
    manual_label: label,
    source_file: path.basename(src),
    rhwp_page_index: i + 1,
    printed_page_no: pmark ? Number(pmark[1]) : null,
    title_guess: text.trim().replace(/\s+/g, ' ').slice(0, 60),
    text,
    text_len: text.length,
    text_hash,
    normalized_text_hash,
    keywords: Array.from(codes).sort(),
  };
  await fh.write(JSON.stringify(row) + '\n', 'utf-8');
  await writeFile(path.join(pageTextDir, `p${String(i + 1).padStart(4, '0')}.txt`), text, 'utf-8');
}
await fh.close();

const meta = {
  label, source_file: path.basename(src), source_path: src,
  page_count: pc, full_page_count, total_text_chars: total_chars,
  elapsed_sec: (Date.now() - t0) / 1000,
  jsonl: path.relative(outDir, jsonlPath),
  page_text_dir: path.relative(outDir, pageTextDir),
};
await writeFile(path.join(outDir, `${label}_meta.json`), JSON.stringify(meta, null, 2), 'utf-8');
doc.free();
console.log(JSON.stringify({ event: 'done', ...meta }));
