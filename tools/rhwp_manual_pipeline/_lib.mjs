// 공유 헬퍼 — 자체 package.json 의존성(tools/rhwp_manual_pipeline/node_modules)을 사용한다.
// (이전: analysis/rhwp_pdf_poc_260414/node_modules 재사용 → 제거됨. 이제 npm ci 로 정식 설치.)
// @rhwp/core 는 즉시 로드(extract/diff 에 필수). playwright/chromium 은 PDF 생성 시에만
// lazy import 한다 → extract/diff/candidates/manifest 는 chromium 없이 동작한다.
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const requireSelf = createRequire(import.meta.url);

const rhwpPkgPath = requireSelf.resolve('@rhwp/core/package.json');
const rhwpRoot = path.dirname(rhwpPkgPath);
const rhwpEntry = path.join(rhwpRoot, 'rhwp.js');
const rhwpWasm  = path.join(rhwpRoot, 'rhwp_bg.wasm');

// ESM 동적 import — 경로를 file:// URL 로 변환 (@rhwp/core 만; playwright 는 아래 lazy)
const rhwpMod = await import(pathToFileURL(rhwpEntry).href);
const init = rhwpMod.default;
const { HwpDocument, version } = rhwpMod;

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

// chromium 실행파일 경로. CHROME_PATH env 로 주입 가능(서버/Docker). 미설정 시 로컬
// 기본값(Windows Chrome). 빈 문자열로 두면 playwright-core 번들 chromium 을 시도한다.
const CHROME_PATH = process.env.CHROME_PATH !== undefined
  ? process.env.CHROME_PATH
  : 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';

let _chromium = null;
async function _getChromium() {
  // lazy import — PDF 생성 경로에서만 playwright 를 로드한다. extract/diff 는 미호출.
  if (!_chromium) {
    const pw = await import('playwright-core');
    _chromium = pw.chromium;
  }
  return _chromium;
}

let _browser = null;
export async function browser() {
  if (!_browser) {
    const chromium = await _getChromium();
    const launchOpts = { headless: true, args: ['--disable-gpu', '--no-sandbox'] };
    if (CHROME_PATH) launchOpts.executablePath = CHROME_PATH;
    _browser = await chromium.launch(launchOpts);
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
  // 페이지를 viewBox 단위(원본 page 크기)와 1:1 로 맞추고, SVG 가 페이지 전체를 채우게 한다.
  // (이전: w*96/72 로 페이지를 키워 SVG(intrinsic=viewBox)가 좌상단에 작게 박히던 버그)
  const wPx = Math.round(w);
  const hPx = Math.round(h);
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;width:100%;height:100%}svg{display:block;width:100%;height:100%}</style></head><body>${svg}</body></html>`;
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
