// 공유 헬퍼 — 기존 PoC 의 node_modules (analysis/rhwp_pdf_poc_260414/node_modules) 를 재사용.
// 본 폴더에는 node_modules 가 없음. 추가 npm install 미발생.
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const POC = path.resolve(here, '..', '..', 'analysis', 'rhwp_pdf_poc_260414');
const requireFromPoc = createRequire(path.join(POC, 'package.json'));

const rhwpPkgPath = requireFromPoc.resolve('@rhwp/core/package.json');
const rhwpRoot = path.dirname(rhwpPkgPath);
const rhwpEntry = path.join(rhwpRoot, 'rhwp.js');
const rhwpWasm  = path.join(rhwpRoot, 'rhwp_bg.wasm');

const playwrightPkgPath = requireFromPoc.resolve('playwright-core/package.json');
const playwrightRoot = path.dirname(playwrightPkgPath);

// ESM 동적 import — 경로를 file:// URL 로 변환
const rhwpMod = await import(pathToFileURL(rhwpEntry).href);
const init = rhwpMod.default;
const { HwpDocument, version } = rhwpMod;
const playwrightMod = await import(pathToFileURL(path.join(playwrightRoot, 'index.mjs')).href);
const { chromium } = playwrightMod;

let _ready = null;
export async function rhwpReady() {
  if (!_ready) {
    const bytes = await readFile(rhwpWasm);
    const mod = await WebAssembly.compile(bytes);
    await init({ module_or_path: mod });
    _ready = { HwpDocument, version: version() };
  }
  return _ready;
}

export async function loadDoc(hwpPath) {
  await rhwpReady();
  const buf = await readFile(hwpPath);
  return new HwpDocument(new Uint8Array(buf));
}

const SYSTEM_CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

let _browser = null;
export async function browser() {
  if (!_browser) {
    _browser = await chromium.launch({
      executablePath: SYSTEM_CHROME,
      headless: true,
      args: ['--disable-gpu', '--no-sandbox'],
    });
  }
  return _browser;
}

export async function closeBrowser() {
  if (_browser) {
    await _browser.close();
    _browser = null;
  }
}

export function flattenPageText(layoutJson) {
  try {
    const obj = JSON.parse(layoutJson);
    const out = [];
    function walk(node) {
      if (!node) return;
      if (Array.isArray(node)) return node.forEach(walk);
      if (typeof node === 'object') {
        if (typeof node.text === 'string') out.push(node.text);
        for (const k of Object.keys(node)) if (typeof node[k] === 'object') walk(node[k]);
      }
    }
    walk(obj);
    return out.join('');
  } catch { return ''; }
}

export function parseSvgSize(svg) {
  const vb = svg.match(/viewBox\s*=\s*"([\d.\-\s]+)"/);
  if (vb) {
    const a = vb[1].trim().split(/\s+/).map(Number);
    return { w: a[2], h: a[3] };
  }
  return { w: 595, h: 842 };
}

// Convert one SVG into a 1-page PDF via Chromium.
// Reuses a single chromium page across calls when given.
export async function svgToPdf(svg, sharedPage) {
  const { w, h } = parseSvgSize(svg);
  const wPx = Math.round(w * 96 / 72);
  const hPx = Math.round(h * 96 / 72);
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0}svg{display:block}</style></head><body>${svg}</body></html>`;
  if (sharedPage) {
    await sharedPage.setContent(html, { waitUntil: 'domcontentloaded' });
    return await sharedPage.pdf({
      width: `${wPx}px`, height: `${hPx}px`,
      printBackground: true, preferCSSPageSize: false,
      margin: { top: 0, right: 0, bottom: 0, left: 0 },
    });
  }
  const b = await browser();
  const ctx = await b.newContext();
  const page = await ctx.newPage();
  try {
    await page.setContent(html, { waitUntil: 'domcontentloaded' });
    return await page.pdf({
      width: `${wPx}px`, height: `${hPx}px`,
      printBackground: true, preferCSSPageSize: false,
      margin: { top: 0, right: 0, bottom: 0, left: 0 },
    });
  } finally {
    await page.close(); await ctx.close();
  }
}

export function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (!next || next.startsWith('--')) { args[key] = true; }
      else { args[key] = next; i++; }
    }
  }
  return args;
}
