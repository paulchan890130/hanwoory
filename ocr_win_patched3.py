#!/usr/bin/env python3
# ocr_win_patched3.py
# ===========================================
# page_scan.py 실제 파서 직접 호출 (3차 — 최종 패치)
#
# [적용된 패치]
# [P2] parse_arc(fast=True): ARC OCR 조합 최대 2회 (8→2) — 유지
# [롤백] _prep_mrz max_h=200: 제거 (OCR 품질 저하로 여권 성능 오히려 악화)
#
# - 파일당 타임아웃: 3초 (하드 제한, threading 방식)
# - 결과: ocr_win_patched3.csv
#
# 실행:
#   .venv\Scripts\python.exe ocr_win_patched3.py

import os, sys, re, csv, time
import threading
from pathlib import Path
from collections import Counter

ROOT       = Path(__file__).resolve().parent
OCR_FOLDER = ROOT / "여권 및 등록증"
TESS_EXE   = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
OUT_CSV    = ROOT / "ocr_win_patched3.csv"
PER_FILE_TIMEOUT = 3   # seconds — 3초 하드 제한

# ── Streamlit mock ─────────────────────────────────────────────────────────
class _SessionState(dict):
    def __getattr__(self, k):
        if k not in self: self[k] = None
        return self[k]
    def __setattr__(self, k, v): self[k] = v

class _FakeSt:
    session_state = _SessionState()
    def __getattr__(self, _): return lambda *a, **kw: None
    def error(self, *a, **kw): pass
    def info(self, *a, **kw): pass
    def write(self, *a, **kw): pass

_fake_st = _FakeSt()
_fake_st.session_state["passport_mrz_debug"] = []
_fake_st.session_state["passport_mrz_best"]  = {}

sys.modules["streamlit"] = _fake_st           # type: ignore

def _reset_session():
    _fake_st.session_state["passport_mrz_debug"] = []
    _fake_st.session_state["passport_mrz_best"]  = {}

# ── Tesseract 경로 설정 ───────────────────────────────────────────────────
import pytesseract
pytesseract.pytesseract.tesseract_cmd = TESS_EXE

# ── page_scan 임포트 ──────────────────────────────────────────────────────
sys.path.insert(0, str(ROOT))
try:
    from pages import page_scan as _ps
    parse_passport_fn = _ps.parse_passport
    parse_arc_fn      = _ps.parse_arc
    open_image_fn     = _ps.open_image_safe
    print(f"page_scan 임포트 성공: {_ps.__file__}")
except Exception as e:
    print(f"page_scan 임포트 실패: {e}")
    sys.exit(1)

# ── 이미지 열기 래퍼 ─────────────────────────────────────────────────────
class _FakeUpload:
    def __init__(self, fp: Path):
        self._fp = fp
        self.name = fp.name
    def getvalue(self):
        return self._fp.read_bytes()
    def read(self, n=-1):
        return self._fp.read_bytes() if n == -1 else self._fp.read_bytes()[:n]

def open_img(fp: Path):
    return open_image_fn(_FakeUpload(fp))

# ── 파일 분류 ──────────────────────────────────────────────────────────────
PASSPORT_KW = {'여권', 'passport'}
ARC_KW      = {'등록증', 'arc', 'registration'}
SKIP_KW = {
    '결혼증','신분증','호구부','출생','신청서','방문예약','계약서',
    '고지서','체류','조기','흑뱃','접수증','확인서','민원','위임장',
    '보험','사진','배경','비번','mmexport','s22c','남편','아내',
    '서명','숙소','노무','직업','신고서','screenshot','관계',
    '사전평가','사통','반려','report','apev','등기부','비취업',
    '신원보증','화면 캡처','화면캡처','캡처','성적증명','단순',
}

def classify(name, folder):
    s = (name + ' ' + folder).lower()
    if any(k in s for k in PASSPORT_KW): return 'passport'
    if any(k in s for k in ARC_KW):      return 'arc'
    if any(k in s for k in SKIP_KW):     return 'skip'
    if re.match(r'^[0-9a-f]{30,}\.', name.lower()): return 'skip'
    return 'unknown'

def collect_files(folder: Path):
    rows = []
    fid = 0
    for f in sorted(folder.rglob('*')):
        if not f.is_file(): continue
        ext = f.suffix.lower()
        if ext not in {'.jpg','.jpeg','.png','.pdf','.webp','.bmp','.tiff','.tif'}: continue
        rel = f.parent.name if f.parent != folder else ''
        doc_type = classify(f.name, rel)
        rows.append({'file_id': fid, 'filepath': str(f), 'filename': f.name,
                     'folder_name': rel, 'doc_type': doc_type,
                     'file_ext': ext, 'file_size_kb': round(f.stat().st_size/1024, 1)})
        fid += 1
    return rows

# ── 점수 계산 ──────────────────────────────────────────────────────────────
def score_result(parsed, doc_type):
    if doc_type == 'passport':
        kn = sum(1 for k in ('여권','만기','생년월일','성','명') if str(parsed.get(k,'')).strip())
        if kn >= 4: return 'SUCCESS', kn
        if kn >= 2: return 'PARTIAL', kn
        return 'FAIL', kn
    elif doc_type == 'arc':
        kn = sum(1 for k in ('등록증','번호','만기일','발급일','한글') if str(parsed.get(k,'')).strip())
        if kn >= 3: return 'SUCCESS', kn
        if kn >= 1: return 'PARTIAL', kn
        return 'FAIL', kn
    else:
        n = sum(1 for v in parsed.values() if str(v).strip())
        if n >= 2: return 'PARTIAL', n
        return 'FAIL', n

# ── 타임아웃 wrapper ──────────────────────────────────────────────────────
def run_with_timeout(fn, args, timeout_s):
    result = [None]
    exc    = [None]
    def worker():
        try:   result[0] = fn(*args)
        except Exception as e: exc[0] = e
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        return None, 'TIMEOUT'
    if exc[0]:
        return None, f'ERROR:{exc[0]}'
    return result[0], None

# ── 메인 ──────────────────────────────────────────────────────────────────
def main():
    files = collect_files(OCR_FOLDER)
    cnt   = Counter(r['doc_type'] for r in files)
    ocr_targets = [r for r in files if r['doc_type'] != 'skip']

    print(f"총 {len(files)}개 | OCR 대상: {len(ocr_targets)} | SKIP: {cnt.get('skip',0)}")
    print(f"tesseract: {TESS_EXE}")
    print(f"패치: parse_arc(fast=True) | timeout={PER_FILE_TIMEOUT}s")
    print()

    results = []
    t_start = time.time()

    for i, row in enumerate(ocr_targets):
        if i % 10 == 0:
            elapsed = time.time() - t_start
            print(f"  [{i:3d}/{len(ocr_targets)}] {elapsed:5.0f}s | {row['filename'][:50]}")

        doc_type = row['doc_type']
        fp = Path(row['filepath'])

        t0 = time.time()
        _reset_session()

        try:
            img = open_img(fp)
        except Exception as e:
            img = None
            open_err = str(e)[:100]
        else:
            open_err = ''

        if img is None:
            results.append(_make_row(row, 'NO_OUTPUT', open_err or 'cannot_open', {}, 0,
                                     int((time.time()-t0)*1000)))
            continue

        if doc_type == 'passport':
            parsed, err = run_with_timeout(parse_passport_fn, (img,), PER_FILE_TIMEOUT)
        elif doc_type == 'arc':
            parsed, err = run_with_timeout(parse_arc_fn, (img,), PER_FILE_TIMEOUT)
        else:
            # unknown: passport 시도, 실패 시 arc
            parsed, err = run_with_timeout(parse_passport_fn, (img,), PER_FILE_TIMEOUT)
            if not parsed and err != 'TIMEOUT':
                parsed2, err2 = run_with_timeout(parse_arc_fn, (img,), PER_FILE_TIMEOUT)
                if parsed2:
                    parsed, err = parsed2, err2

        ocr_ms = int((time.time()-t0)*1000)

        if err == 'TIMEOUT':
            status, sc = 'TIMEOUT', 0
        elif err:
            status, sc = 'PARSE_ERROR', 0
        elif not parsed:
            status, sc = 'NO_OUTPUT', 0
        else:
            status, sc = score_result(parsed, doc_type)

        results.append(_make_row(row, status, err or '', parsed or {}, sc, ocr_ms))

    for row in files:
        if row['doc_type'] == 'skip':
            results.append(_make_row(row, 'SKIP', '', {}, 0, 0))

    elapsed = time.time() - t_start
    ocr_rows = [r for r in results if r['doc_type'] != 'skip']
    sc_cnt = Counter(r['status'] for r in ocr_rows)

    print()
    print(f"완료: {elapsed:.0f}s  (평균 {elapsed/max(len(ocr_rows),1)*1000:.0f}ms/파일)")
    print("결과 (skip 제외):")
    for s, n in sorted(sc_cnt.items()):
        print(f"  {s:12s}: {n}")

    fieldnames = [
        'file_id','filepath','filename','doc_type','status','error',
        '한글','성','명','성별','국가','국적',
        '여권','발급','만기','생년월일',
        '등록증','번호','발급일','만기일','주소',
        'score','ocr_ms','notes'
    ]
    with open(OUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        w.writerows(results)

    print(f"\n저장: {OUT_CSV}")
    print()
    print("다음 단계: ocr_win_patched3.csv 를 Claude에게 전달하면 최종 비교 분석합니다.")

def _make_row(row, status, err, parsed, sc, ocr_ms):
    return {
        'file_id':   row['file_id'],
        'filepath':  row['filepath'],
        'filename':  row['filename'],
        'doc_type':  row['doc_type'],
        'status':    status,
        'error':     str(err)[:200],
        '한글':      parsed.get('한글',''),
        '성':        parsed.get('성',''),
        '명':        parsed.get('명',''),
        '성별':      parsed.get('성별',''),
        '국가':      parsed.get('국가', parsed.get('국적','')),
        '국적':      parsed.get('국적',''),
        '여권':      parsed.get('여권',''),
        '발급':      parsed.get('발급',''),
        '만기':      parsed.get('만기',''),
        '생년월일':  parsed.get('생년월일',''),
        '등록증':    parsed.get('등록증',''),
        '번호':      parsed.get('번호',''),
        '발급일':    parsed.get('발급일',''),
        '만기일':    parsed.get('만기일',''),
        '주소':      parsed.get('주소',''),
        'score':     sc,
        'ocr_ms':    ocr_ms,
        'notes':     'patch: arc_fast=True | no_max_h',
    }

if __name__ == '__main__':
    main()
