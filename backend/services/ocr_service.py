"""
backend/services/ocr_service.py

OCR 엔진 - pages/page_scan.py 에서 Streamlit UI 코드를 제거하고
FastAPI 백엔드에서 독립적으로 실행 가능한 형태로 추출.

원본 로직 100% 보존.
변경점:
  - `import streamlit as st` 제거
  - parse_passport() 내부의 st.session_state 디버그 기록 4줄 → 로컬 변수로 교체
  - Streamlit UI 관련 함수(_ensure_tesseract_ui, render) 미포함
  - config / customer_service 의존성 없음
"""

import os
import re
import math as _math
import platform
from datetime import datetime as _dt, timedelta as _td

from PIL import Image, ImageOps, ImageFilter, ImageStat, Image as _PILImage

try:
    import numpy as np
except Exception:
    np = None

try:
    import pytesseract
except Exception:
    pytesseract = None

# OmniMRZ singleton — PaddleOCR model is loaded on first access.
# Cached at module level so each uvicorn worker loads models once.
import threading as _threading

_omni_mrz_instance = None
_omni_mrz_lock = _threading.Lock()  # serialise init so prewarm and first real request don't race


def _get_omni_mrz():
    global _omni_mrz_instance
    with _omni_mrz_lock:
        if _omni_mrz_instance is None:
            from omnimrz import OmniMRZ  # type: ignore[import]
            _omni_mrz_instance = OmniMRZ()
    return _omni_mrz_instance


def _prewarm_omni_mrz() -> None:
    """Pre-load PaddleOCR models at worker startup so first-request cold-start is avoided."""
    try:
        _get_omni_mrz()
    except Exception:
        pass


# OmniMRZ 프리웜 비활성화 — Render 무료 플랜(512MB RAM)에서 PaddleOCR 4개 모델을
# 서버 시작 즉시 다운로드하면 OOM 킬이 발생한다.
# 여권 OCR은 Tesseract+ocrb 기반 _passport_tess_mrz()가 처리하므로 프리웜 불필요.
# _prewarm_omni_mrz() / _get_omni_mrz() 는 코드에 남겨두지만 호출하지 않는다.


# ── ARC 옵션 ────────────────────────────────────────────────────────────────
ARC_REMOVE_PAREN = True   # 주소에서 (신길동) 같은 괄호표기 제거
ARC_FAST_ONLY    = True   # 빠른 모드(필요 최소 조합만 시도)

# ── MRZ 변환 테이블 ──────────────────────────────────────────────────────────
_MRZ_CLEAN_TRANS = str.maketrans({
    '«': '<', '‹': '<', '>': '<', ' ': '', '—': '-', '–': '-',
    '£': '<', '€': '<', '¢': '<',
})
_MRZ_FIX_DIGIT_MAP = {
    'O': '0', 'Q': '0', 'D': '0',
    'I': '1', 'L': '1',
    'Z': '2',
    'S': '5',
    'G': '6',
    'B': '8',
}

# ── ARC 보조 상수 ────────────────────────────────────────────────────────────
_ADDR_BAN_RE = re.compile(
    r'(유효|취업|가능|확인|민원|국번없이|콜센터|call\s*center|www|http|1345|출입국|immigration|안내|관할|관계자|외|금지)',
    re.I,
)
_NAME_BAN = {
    "외국", "국내", "거소", "신고", "증", "재외동포", "재외동", "외동포",
    "재외", "동포", "국적", "주소", "발급", "발급일", "발급일자",
    "만기", "체류", "자격", "종류", "성명", "이름", "사력",
    # Common card-label OCR noise found in benchmark
    "국가", "지역", "발금", "발금일", "발금일자", "체류자", "체류파", "제류자",
    "발급원", "받큼일", "소신고", "겁소고", "재위동", "재외등", "체등자", "체륭자",
    "개류자", "력재외", "송영지",
    # Visa-status label fragments that OCR mistakes for names.
    # "방문취" = first 3 chars of 방문취업(H-2); "방문취업", "방문취" both must be banned.
    "방문취", "방문취업", "바서", "취업", "취업가", "비전문",
    "재외동", "동포비", "전문직",
}


# ─────────────────────────────────────────────────────────────────────────────
# 1) 공통 OCR 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _ocr(img, lang="kor", config=""):
    if pytesseract is None or img is None:
        return ""
    try:
        return pytesseract.image_to_string(img, lang=lang, config=config) or ""
    except Exception:
        return ""


def _binarize(img):
    g = ImageOps.grayscale(img)
    return g.point(lambda p: 255 if p > 128 else 0)


def _binarize_soft(img):
    g = ImageOps.grayscale(img)
    g = g.filter(ImageFilter.MedianFilter(size=3))
    g = ImageOps.autocontrast(g)
    return g


def _pre(img):
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g)
    return g


def ocr_try_all(
    img,
    langs=("kor", "kor+eng"),
    psms=(6, 7),
    pres=("raw", "binarize"),
    max_tries=None,
):
    best = {"text": "", "lang": None, "config": "", "pre": None, "score": -1}
    if pytesseract is None or img is None:
        return best

    tried = 0
    for lang in langs:
        for psm in psms:
            for pre in pres:
                proc = img
                if pre == "binarize":
                    proc = _binarize(img)
                cfg = f"--oem 3 --psm {psm}"
                try:
                    txt = pytesseract.image_to_string(proc, lang=lang, config=cfg) or ""
                except Exception:
                    txt = ""
                score = len(txt.strip())
                if score > best["score"]:
                    best.update(text=txt, lang=lang, config=cfg, pre=pre, score=score)
                tried += 1
                if max_tries is not None and tried >= max_tries:
                    return best
    return best


# ─────────────────────────────────────────────────────────────────────────────
# 2) 등록증 카드 분리
# ─────────────────────────────────────────────────────────────────────────────

def _detect_card_boxes_on_white_bg(img):
    if img is None or np is None:
        return []
    try:
        src = img.convert("RGB")
        w0, h0 = src.size
        max_side = 1200
        scale = min(1.0, max_side / float(max(w0, h0)))
        if scale < 1.0:
            sw, sh = max(1, int(w0 * scale)), max(1, int(h0 * scale))
            work = src.resize((sw, sh), resample=_PILImage.BILINEAR)
        else:
            work = src
            sw, sh = w0, h0

        gray = work.convert("L").filter(ImageFilter.MedianFilter(size=3))
        arr = np.asarray(gray)
        mask = arr < 242
        if mask.mean() < 0.002:
            return []

        row_ratio = mask.mean(axis=1)
        thr_row = max(0.01, row_ratio.max() * 0.12)
        ys = np.where(row_ratio > thr_row)[0]
        if len(ys) == 0:
            return []

        bands = []
        start = ys[0]
        prev = ys[0]
        for y in ys[1:]:
            if y - prev > max(8, sh // 80):
                bands.append((start, prev))
                start = y
            prev = y
        bands.append((start, prev))

        min_band_h = max(30, sh // 30)
        bands = [b for b in bands if (b[1] - b[0] + 1) >= min_band_h]
        if not bands:
            return []

        boxes = []
        for y1, y2 in bands[:4]:
            band = mask[y1:y2 + 1, :]
            col_ratio = band.mean(axis=0)
            thr_col = max(0.01, col_ratio.max() * 0.15)
            xs = np.where(col_ratio > thr_col)[0]
            if len(xs) == 0:
                continue
            x1, x2 = int(xs[0]), int(xs[-1])

            mx = max(12, int((x2 - x1 + 1) * 0.04))
            my = max(12, int((y2 - y1 + 1) * 0.08))
            x1 = max(0, x1 - mx)
            x2 = min(sw - 1, x2 + mx)
            y1m = max(0, y1 - my)
            y2m = min(sh - 1, y2 + my)

            bw = x2 - x1 + 1
            bh = y2m - y1m + 1
            area_ratio = (bw * bh) / float(sw * sh)
            if area_ratio < 0.01:
                continue
            if bw < sw * 0.12 or bh < sh * 0.06:
                continue

            rx1 = int(round(x1 / scale))
            ry1 = int(round(y1m / scale))
            rx2 = int(round((x2 + 1) / scale))
            ry2 = int(round((y2m + 1) / scale))
            boxes.append((rx1, ry1, rx2, ry2))

        boxes = sorted(boxes, key=lambda b: (b[1], b[0]))

        dedup = []
        for b in boxes:
            if not dedup:
                dedup.append(b)
                continue
            lx1, ly1, lx2, ly2 = dedup[-1]
            x1, y1, x2, y2 = b
            inter_w = max(0, min(lx2, x2) - max(lx1, x1))
            inter_h = max(0, min(ly2, y2) - max(ly1, y1))
            inter = inter_w * inter_h
            area1 = (lx2 - lx1) * (ly2 - ly1)
            area2 = (x2 - x1) * (y2 - y1)
            if inter > min(area1, area2) * 0.55:
                if area2 > area1:
                    dedup[-1] = b
            else:
                dedup.append(b)

        return dedup[:2]
    except Exception:
        return []


def _split_arc_front_back(img):
    w, h = img.size
    boxes = _detect_card_boxes_on_white_bg(img)
    if len(boxes) >= 2:
        boxes = sorted(boxes[:2], key=lambda b: b[1])
        front = img.crop(boxes[0])
        back = img.crop(boxes[1])
        return front, back
    return img.crop((0, 0, w, int(h * 0.5))), img.crop((0, int(h * 0.5), w, h))


# ─────────────────────────────────────────────────────────────────────────────
# 3) MRZ 여권 파싱 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _mrz_clean(s: str) -> str:
    raw = (s or "").strip().translate(_MRZ_CLEAN_TRANS).upper()
    raw = re.sub(r"[^A-Z0-9<]", "", raw)
    return raw


def _mrz_pad44(raw: str) -> str:
    raw = raw or ""
    if len(raw) < 44:
        raw = raw + ("<" * (44 - len(raw)))
    elif len(raw) > 44:
        raw = raw[:44]
    return raw


def _normalize_mrz_line(s: str) -> str:
    return _mrz_pad44(_mrz_clean(s))


def _fix_td3_line2_fields(L2: str) -> str:
    if not L2:
        return L2
    L2 = _mrz_pad44(_mrz_clean(L2))

    map_alpha = {"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"}
    map_digit = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6", "B": "8"}

    def fix_nat(nat3: str) -> str:
        nat3 = "".join(map_alpha.get(c, c) for c in nat3)
        nat3 = re.sub(r"[^A-Z]", "", nat3)
        return nat3 if len(nat3) == 3 else ""

    doc = L2[0:9]
    doc_cd = L2[9]
    nat = L2[10:13]

    nat_ok = bool(re.fullmatch(r"[A-Z]{3}", fix_nat(nat)))
    doc_cd_is_digit = doc_cd.isdigit()

    if (not doc_cd_is_digit) and (not nat_ok):
        nat_shift = fix_nat((doc_cd + nat[:2]))
        if nat_shift:
            L2 = L2[:9] + "<" + nat_shift + L2[12:]
    else:
        nat2 = fix_nat(L2[11:14])
        if doc_cd_is_digit and (not nat_ok) and nat2:
            L2 = L2[:10] + "<" + nat2 + L2[14:]

    nat = fix_nat(L2[10:13])
    if nat:
        L2 = L2[:10] + nat + L2[13:]

    birth = "".join(map_digit.get(c, c) for c in L2[13:19])
    exp = "".join(map_digit.get(c, c) for c in L2[21:27])
    L2 = L2[:13] + birth + L2[19:21] + exp + L2[27:]

    sx = L2[20]
    if sx not in "MF<":
        sx = "M" if sx in ("N", "H") else "<"
        L2 = L2[:20] + sx + L2[21:]

    return L2


def _is_td3_candidate(L1: str, L2: str) -> bool:
    raw1 = _mrz_clean(L1)
    raw2 = _mrz_clean(L2)
    if not raw1 or not raw2:
        return False
    p = raw1.find("P")
    if p == -1:
        return False
    raw1 = raw1[p:]
    if "<<" not in raw1:
        return False
    L1p = _mrz_pad44(raw1)
    L2p = _mrz_pad44(raw2)
    if not (re.fullmatch(r"[A-Z0-9<]{44}", L1p) and re.fullmatch(r"[A-Z0-9<]{44}", L2p)):
        return False
    if L1p[0] != "P":
        return False
    if L1p[1] not in "<ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
        return False
    if not re.fullmatch(r"[A-Z]{3}", L1p[2:5]):
        return False
    if L1p[5] == "<":
        return False
    if "<<" not in L1p[5:44]:
        return False
    return True


def _minus_years(d: _dt.date, years: int) -> _dt.date:
    y = d.year - years
    import calendar
    endday = calendar.monthrange(y, d.month)[1]
    return _dt(y, d.month, min(d.day, endday)).date()


def _mrz_char_value(ch: str) -> int:
    if ch == "<":
        return 0
    if "0" <= ch <= "9":
        return ord(ch) - ord("0")
    if "A" <= ch <= "Z":
        return ord(ch) - ord("A") + 10
    return 0


def _mrz_check_digit(data: str) -> str:
    weights = [7, 3, 1]
    s = 0
    for i, ch in enumerate(data):
        s += _mrz_char_value(ch) * weights[i % 3]
    return str(s % 10)


def _mrz_digitize(s: str) -> str:
    return "".join(_MRZ_FIX_DIGIT_MAP.get(c, c) for c in s)


def _realign_l1_by_nat(L1_raw: str, nat3: str) -> str:
    raw = _mrz_clean(L1_raw)
    if not raw:
        return ""
    p = raw.find("P")
    if p > 0:
        raw = raw[p:]
    if not nat3 or len(nat3) != 3 or (not nat3.isalpha()):
        return raw
    window = raw[2:12]
    k = window.find(nat3)
    if k == -1:
        return raw
    doc = raw[0] if len(raw) > 0 else "P"
    typ = raw[1] if len(raw) > 1 else "<"
    after = raw[2 + k + 3:]
    fixed = doc + typ + nat3 + after
    return fixed


def _mrz_score_td3(L1: str, L2: str) -> int:
    if not _is_td3_candidate(L1, L2):
        return -1
    L1 = _normalize_mrz_line(L1)
    L2 = _fix_td3_line2_fields(L2)

    score = 0
    doc = L2[0:9]
    doc_cd = L2[9]
    birth = _mrz_digitize(L2[13:19])
    birth_cd = L2[19]
    exp = _mrz_digitize(L2[21:27])
    exp_cd = L2[27]
    opt = L2[28:42]
    opt_cd = L2[42]
    comp_cd = L2[43]

    if doc_cd.isdigit() and _mrz_check_digit(doc) == doc_cd:
        score += 2
    if birth_cd.isdigit() and _mrz_check_digit(birth) == birth_cd:
        score += 2
    if exp_cd.isdigit() and _mrz_check_digit(exp) == exp_cd:
        score += 2
    if opt_cd.isdigit() and _mrz_check_digit(opt) == opt_cd:
        score += 1

    matches = 0
    if doc_cd.isdigit() and _mrz_check_digit(doc) == doc_cd:
        matches += 1
    if birth_cd.isdigit() and _mrz_check_digit(birth) == birth_cd:
        matches += 1
    if exp_cd.isdigit() and _mrz_check_digit(exp) == exp_cd:
        matches += 1
    if matches < 2:
        return -1

    comp_data = L2[0:10] + _mrz_digitize(L2[13:20]) + _mrz_digitize(L2[21:43])
    if comp_cd.isdigit() and _mrz_check_digit(comp_data) == comp_cd:
        score += 3

    score += min((L1 + L2).count("<") // 5, 3)
    return score


def _clean_mrz_k_runs(s: str, min_run: int = 5) -> str:
    """Replace runs of ≥5 identical non-< alpha chars with < (scanner background noise)."""
    if not s:
        return s
    result = []
    i = 0
    while i < len(s):
        c = s[i]
        run = 1
        while i + run < len(s) and s[i + run] == c:
            run += 1
        if c != '<' and c.isalpha() and run >= min_run:
            result.extend(['<'] * run)
        else:
            result.extend([c] * run)
        i += run
    return ''.join(result)


def find_best_mrz_pair_from_text(text: str):
    lines = [l for l in (text or "").splitlines() if l.strip()]
    norms = [_clean_mrz_k_runs(_normalize_mrz_line(l)) for l in lines]
    best = (None, None, -1)
    n = len(norms)
    for i in range(n):
        for j in range(i + 1, min(n, i + 3)):
            L1, L2 = norms[i], norms[j]
            sc = _mrz_score_td3(L1, L2)
            if sc > best[2]:
                best = (L1, L2, sc)
    return best


def _parse_mrz_pair(L1: str, L2: str) -> dict:
    out = {}
    L1 = _normalize_mrz_line(L1) if L1 else ""
    L2 = _fix_td3_line2_fields(L2) if L2 else ""
    nat3 = _mrz_clean(L2)[10:13] if L2 else ""
    if nat3 and re.fullmatch(r"[A-Z]{3}", nat3):
        L1_raw = _realign_l1_by_nat(L1, nat3)
        if L1_raw:
            L1 = _mrz_pad44(L1_raw)

    if L1 and len(L1) >= 6 and L1[0] == "P":
        nat = re.sub(r"[^A-Z]", "", L2[10:13] if len(L2) >= 13 else "")
        doc2 = L1[:2] if len(L1) >= 2 else "P<"
        rem = L1[2:]

        if nat and len(nat) == 3:
            head = rem[:10]
            pos = head.find(nat)
            if pos > 0:
                rem = nat + rem[pos + 3:]
            elif rem.startswith(nat[1:]) and not rem.startswith(nat):
                rem = nat[0] + rem
            elif not re.fullmatch(r"[A-Z]{3}", rem[:3] or ""):
                rem = nat + rem[3:]

        L1_fix = doc2 + rem
        name_block = L1_fix[5:] if len(L1_fix) > 5 else ""
        # Split on the FIRST run of one-or-more '<' in the name zone.
        # Preferring '<<' causes failures when the OCR-degraded separator is a single '<'
        # (e.g. true MRZ 'WU<<LINHU' → noisy read 'WUS<LINHUS<<<'; splitting on the later
        # '<<' filler swallows both tokens into surname and leaves given name empty).
        m_sep = re.search(r"<+", name_block)
        if m_sep:
            sur_raw = name_block[:m_sep.start()].replace("<", " ").strip()
            after_sep = name_block[m_sep.end():]
            # Preserve the FULL given-name field (ICAO: single '<' separates given name
            # components, trailing '<' is filler padding).  Stopping at the first '<'
            # was wrong for multi-token names like SHOHRUHBEK<ABDIHAKIMOVICH<<<<.
            given_raw = after_sep.rstrip("<").replace("<", " ").strip()
            sur = re.sub(r"\s+", " ", sur_raw).strip()
            given = re.sub(r"\s+", " ", given_raw).strip()
            sur = _strip_mrz_trail(sur)
            given = _strip_mrz_trail(given)
            if sur and not re.search(r"\d", sur):
                out["성"] = sur
            if given and not re.search(r"\d", given):
                out["명"] = given

    pn = re.sub(r"[^A-Z0-9]", "", L2[0:9])
    if pn:
        out["여권"] = pn

    nat = re.sub(r"[^A-Z]", "", L2[10:13])
    if nat:
        out["국가"] = nat

    b = re.sub(r"[^0-9]", "", L2[13:19])
    if len(b) == 6:
        yy, mm, dd = int(b[:2]), int(b[2:4]), int(b[4:6])
        yy += 2000 if yy < 30 else 1900  # DOB: <30 → 2000s (children), ≥30 → 1900s (adults)
        try:
            out["생년월일"] = _dt(yy, mm, dd).strftime("%Y-%m-%d")
        except Exception:
            pass

    sx = L2[20:21]
    out["성별"] = "남" if sx == "M" else ("여" if sx == "F" else "")

    e = re.sub(r"[^0-9]", "", L2[21:27])
    if len(e) == 6:
        yy, mm, dd = int(e[:2]), int(e[2:4]), int(e[4:6])
        yy += 2000 if yy < 80 else 1900
        try:
            out["만기"] = _dt(yy, mm, dd).strftime("%Y-%m-%d")
        except Exception:
            pass

    if out.get("만기"):
        try:
            exp = _dt.strptime(out["만기"], "%Y-%m-%d").date()
            issued = _minus_years(exp, 10) + _td(days=1)
            out["발급"] = issued.strftime("%Y-%m-%d")
        except Exception:
            pass

    return out


# ─────────────────────────────────────────────────────────────────────────────
# 4) MRZ 후보 밴드 탐색 유틸
# ─────────────────────────────────────────────────────────────────────────────

def _edge_density(pil_img: Image.Image) -> float:
    if pil_img is None:
        return 0.0
    g = ImageOps.grayscale(pil_img)
    g = g.copy()
    g.thumbnail((320, 320))
    e = g.filter(ImageFilter.FIND_EDGES)
    data = list(e.getdata())
    if not data:
        return 0.0
    thr = 40
    cnt = sum(1 for v in data if v > thr)
    return cnt / float(len(data))


def _crop_to_content_bbox_edges(img: Image.Image, pad: int = 20) -> Image.Image:
    if img is None:
        return img
    w, h = img.size
    work = img.copy()
    scale = 1.0
    if max(w, h) > 900:
        scale = 900.0 / float(max(w, h))
        work = work.resize((int(w * scale), int(h * scale)), resample=_PILImage.BILINEAR)

    g = ImageOps.grayscale(work).filter(ImageFilter.FIND_EDGES)
    px = g.load()
    ww, hh = g.size
    thr = 35
    minx, miny = ww, hh
    maxx, maxy = 0, 0
    found = False
    step = 2 if max(ww, hh) <= 600 else 3
    for y in range(0, hh, step):
        for x in range(0, ww, step):
            if px[x, y] > thr:
                found = True
                if x < minx: minx = x
                if y < miny: miny = y
                if x > maxx: maxx = x
                if y > maxy: maxy = y

    if not found:
        return img
    if (maxx - minx) < ww * 0.08 or (maxy - miny) < hh * 0.08:
        return img

    inv = 1.0 / scale
    x0 = int(minx * inv) - pad
    y0 = int(miny * inv) - pad
    x1 = int(maxx * inv) + pad
    y1 = int(maxy * inv) + pad
    x0 = max(0, x0); y0 = max(0, y0)
    x1 = min(w, x1); y1 = min(h, y1)
    return img.crop((x0, y0, x1, y1))


def _crop_to_content_bbox_thresh(img: Image.Image, pad_ratio: float = 0.03) -> Image.Image:
    if img is None:
        return img
    try:
        g = ImageOps.grayscale(img)
        g = ImageOps.autocontrast(g)
        bw = g.point(lambda p: 255 if p < 245 else 0)
        bbox = bw.getbbox()
        if not bbox:
            return img
        w, h = img.size
        pad_x = int(w * pad_ratio)
        pad_y = int(h * pad_ratio)
        x0 = max(bbox[0] - pad_x, 0)
        y0 = max(bbox[1] - pad_y, 0)
        x1 = min(bbox[2] + pad_x, w)
        y1 = min(bbox[3] + pad_y, h)
        return img.crop((x0, y0, x1, y1))
    except Exception:
        return img


def _crop_to_content_bbox(img: Image.Image) -> Image.Image:
    a = _crop_to_content_bbox_edges(img, pad=20)
    if a.size == img.size:
        return _crop_to_content_bbox_thresh(img, pad_ratio=0.03)
    return a


def _prep_mrz(img: Image.Image, target_w: int = 1200) -> Image.Image:
    g = ImageOps.grayscale(img)
    w, h = g.size
    if w > target_w:
        r = target_w / float(w)
        g = g.resize((int(w * r), int(h * r)), resample=_PILImage.BILINEAR)
    g = ImageOps.autocontrast(g)
    g = g.filter(ImageFilter.MedianFilter(size=3))
    g = g.filter(ImageFilter.SHARPEN)
    return g


def _tess_string(img: Image.Image, lang: str, config: str, timeout_s: int = 2) -> str:
    if pytesseract is None:
        return ""
    try:
        return pytesseract.image_to_string(img, lang=lang, config=config, timeout=timeout_s) or ""
    except TypeError:
        try:
            return pytesseract.image_to_string(img, lang=lang, config=config) or ""
        except Exception:
            return ""
    except Exception:
        return ""


def _mrz_windows_by_edge_density(im: Image.Image, top_k: int = 3):
    try:
        w, h = im.size
        if w < 200 or h < 200:
            return []

        y_base = int(h * 0.10)
        roi = im.crop((0, y_base, w, h))
        roi_w0, roi_h0 = roi.size

        target_w = min(700, roi_w0)
        if roi_w0 > target_w:
            s = target_w / float(roi_w0)
            roi = roi.resize((target_w, max(1, int(roi_h0 * s))), resample=_PILImage.BILINEAR)

        g = ImageOps.grayscale(roi)
        g = ImageOps.autocontrast(g)
        e = g.filter(ImageFilter.FIND_EDGES)

        ew, eh = e.size
        if ew < 50 or eh < 50:
            return []

        px = e.load()
        thr = 18
        step_x = 2 if ew >= 500 else 1
        step_y = 2

        scores = []
        for yy in range(0, eh, step_y):
            cnt = 0
            for xx in range(0, ew, step_x):
                if px[xx, yy] > thr:
                    cnt += 1
            scores.append((cnt, yy))

        scores.sort(reverse=True, key=lambda x: x[0])

        win_h = max(40, int(eh * 0.22))
        taken = []
        picked = []
        min_score = max(20, int(ew * 0.04))

        for sc, yy in scores:
            if sc < min_score:
                break
            y0r = max(0, yy - win_h // 2)
            y0r = int(min(y0r, max(0, eh - win_h)))
            y1r = min(eh, y0r + win_h)

            overlap = False
            for a, b in taken:
                if not (y1r < a or y0r > b):
                    overlap = True
                    break
            if overlap:
                continue

            taken.append((y0r, y1r))
            y0o = y_base + int(y0r * (roi_h0 / float(eh)))
            y1o = y_base + int(y1r * (roi_h0 / float(eh)))
            y0o = max(0, min(h - 1, y0o))
            y1o = max(y0o + 1, min(h, y1o))
            picked.append((y0o, y1o))
            if len(picked) >= top_k:
                break

        picked.sort(key=lambda x: x[0])
        return picked
    except Exception:
        return []


def _iter_mrz_candidate_bands(im: Image.Image):
    w, h = im.size
    wins = _mrz_windows_by_edge_density(im, top_k=3)
    for i, (y0, y1) in enumerate(wins, start=1):
        label = f"edge#{i} {int(100*y0/h)}-{int(100*y1/h)}%"
        yield label, im.crop((0, y0, w, y1))
    for pct in (55, 35, 25, 20, 18):
        y0 = int(h * (1 - pct / 100.0))
        yield f"{pct}%", im.crop((0, y0, w, h))


# ─────────────────────────────────────────────────────────────────────────────
# 5) 여권 파서
# ─────────────────────────────────────────────────────────────────────────────

def _passport_tess_mrz(img: Image.Image) -> dict | None:
    """
    Tesseract + ocrb 기반 여권 MRZ 파서 (빠른 경로, ~1-3s).

    _iter_mrz_candidate_bands / _prep_mrz / _tess_string / find_best_mrz_pair_from_text /
    _parse_mrz_pair 를 활용하는 기존 MRZ 파이프라인.

    반환: 파싱 성공(여권번호 확보) 시 표준 필드 dict, 실패 시 None.
    """
    if pytesseract is None:
        return None

    best_parsed: dict | None = None
    best_sc = -1

    for _, band in _iter_mrz_candidate_bands(img):
        prep = _prep_mrz(band)
        for lang in ("ocrb", "eng"):
            txt = _tess_string(prep, lang, "--oem 3 --psm 6", timeout_s=5)
            if not txt:
                continue
            L1, L2, sc = find_best_mrz_pair_from_text(txt)
            if sc > best_sc:
                parsed = _parse_mrz_pair(L1, L2) if (L1 and L2) else {}
                if parsed.get("여권"):
                    # 여권번호까지 확보된 경우만 최적 후보로 채택
                    best_sc = sc
                    best_parsed = parsed
                elif sc > best_sc:
                    # 여권번호 없어도 score 갱신은 유지 (다른 밴드 탐색 우선순위용)
                    best_sc = sc
            if best_parsed and best_sc >= 8:
                break  # 충분히 높은 score + 여권번호 확보 → 조기 종료
        if best_parsed and best_sc >= 8:
            break

    # ── Orientation + deskew fallback ────────────────────────────────────────
    # Triggers when main pass (original orientation) produced no confident result.
    #
    # Priority order:
    #   90°, 270° — passport placed 90° sideways on scanner (most common failure)
    #   180°       — upside-down placement
    #   ±5°, ±10°, ±3° — genuine slight tilt on otherwise correct orientation
    #
    # For major rotations (90/270/180): try both "ocrb" and "eng".
    # For fine tilts: ocrb only (lean path).
    if not best_parsed or best_sc < 6:
        _ROT_LANGS = {90: ("ocrb", "eng"), 270: ("ocrb", "eng"), 180: ("ocrb", "eng")}
        for angle in (90, 270, 180, -5, 5, -10, 10, -3, 3):
            if best_parsed and best_sc >= 6:
                break
            try:
                rotated = img.rotate(angle, expand=True, fillcolor=255)
            except Exception:
                try:
                    rotated = img.rotate(angle, expand=True)
                except Exception:
                    continue
            langs = _ROT_LANGS.get(angle, ("ocrb",))
            for _, band in _iter_mrz_candidate_bands(rotated):
                prep = _prep_mrz(band)
                for lang in langs:
                    txt = _tess_string(prep, lang, "--oem 3 --psm 6", timeout_s=4)
                    if not txt:
                        continue
                    L1, L2, sc = find_best_mrz_pair_from_text(txt)
                    if sc > best_sc:
                        parsed = _parse_mrz_pair(L1, L2) if (L1 and L2) else {}
                        if parsed.get("여권"):
                            best_sc = sc
                            best_parsed = parsed
                        elif sc > best_sc:
                            best_sc = sc
                    if best_parsed and best_sc >= 6:
                        break
                if best_parsed and best_sc >= 6:
                    break

    if not best_parsed:
        return None

    nat = best_parsed.get("국가", "") or best_parsed.get("국적", "")
    return {
        "성":       best_parsed.get("성", ""),
        "명":       best_parsed.get("명", ""),
        "성별":     best_parsed.get("성별", ""),
        "국가":     nat,
        "국적":     nat,
        "여권":     best_parsed.get("여권", ""),
        "발급":     best_parsed.get("발급", ""),
        "만기":     best_parsed.get("만기", ""),
        "생년월일": best_parsed.get("생년월일", ""),
        "_raw_L1":  None,
        "_raw_L2":  None,
    }


def _omni_mrz_from_data(data: dict) -> dict:
    """OmniMRZ parsed_data.data → 표준 필드 dict."""
    surname     = (data.get("surname")        or "").replace("<", "").strip()
    given_names = (data.get("given_names")    or "").replace("<", " ").strip()
    gender      = (data.get("gender")         or "").strip()
    country     = (data.get("issuing_country") or "").strip()
    nationality = (data.get("nationality")    or country).strip()
    doc_number  = (data.get("document_number") or "").replace("<", "").strip()
    expiry      = (data.get("expiry_date")    or "").strip()
    dob         = (data.get("date_of_birth")  or "").strip()
    return {
        "성":       surname,
        "명":       given_names,
        "성별":     gender,
        "국가":     country,
        "국적":     nationality,
        "여권":     doc_number,
        "발급":     "",
        "만기":     expiry,
        "생년월일": dob,
        "_raw_L1":  None,
        "_raw_L2":  None,
    }


def parse_passport(img, fast: bool = False):
    """
    여권 MRZ(TD3) 파서 — Tesseract+ocrb 전용 (~1-3s).

    Input:  PIL.Image (RGB)
    Output: dict with keys 성, 명, 성별, 국가, 국적, 여권, 발급, 만기, 생년월일
            or {"_no_mrz": True, ...} on failure.
    """
    if img is None:
        return {}

    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    w0, h0 = img.size
    max_side = 1600
    scale = max_side / float(max(w0, h0))
    if scale < 1.0:
        img = img.resize((int(w0 * scale), int(h0 * scale)), resample=_PILImage.BILINEAR)

    result = _passport_tess_mrz(img)
    if result:
        return result

    return {"_no_mrz": True, "_best_score": -1, "_rescue_band": "tess_no_mrz", "_rescue_band_alen": 0}


# ─────────────────────────────────────────────────────────────────────────────
# 6) ARC(등록증) 파서 보조 함수
# ─────────────────────────────────────────────────────────────────────────────

def _extract_kor_name_strict(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"\(([가-힣]{2,4})\)", text)
    if m:
        cand = m.group(1)
        if cand not in _NAME_BAN and not cand.endswith("출"):
            return cand
    m = re.search(r"(성명|이름)\s*[:\-]?\s*([가-힣]{2,3})", text)
    if m:
        cand = m.group(2)
        if cand not in _NAME_BAN and not cand.endswith("출"):
            return cand
    toks = re.findall(r"[가-힣]{2,3}", text)
    toks = [t for t in toks if t not in _NAME_BAN and not t.endswith("출")]
    if not toks:
        return ""
    label_pos_list = [p for p in (text.find("성명"), text.find("이름")) if p != -1]
    label_pos = min(label_pos_list) if label_pos_list else len(text) // 2
    best, best_d = "", 10 ** 9
    for t in toks:
        p = text.find(t)
        if p == -1:
            continue
        d = abs(p - label_pos)
        if d < best_d:
            best, best_d = t, d
    return best


def _kor_count(s: str) -> int:
    return len(re.findall(r"[가-힣]", s or ""))


def _kor_word_score(s: str) -> int:
    """Sum of lengths of Korean sequences that are ≥3 chars.
    Better rotation discriminator than raw _kor_count: garbled text produces many 1-2 char
    fragments (score stays low) while correctly-oriented text has long word runs (score high).
    Test results: wrong rotation → 6-12, correct rotation → 93-115."""
    return sum(len(m.group()) for m in re.finditer(r"[가-힣]{3,}", s or ""))


def _strip_mrz_trail(name: str) -> str:
    """Remove spurious single trailing S or C from an OCR'd MRZ name token.
    Causes: 'PIAO' → 'PIAOS', 'JINDAN' → 'JINDANC' due to noise in the filler zone.
    Only strips if the result would still be ≥2 chars and the last char is S or C."""
    if len(name) >= 3 and name[-1] in ("S", "C"):
        return name[:-1]
    return name


def _valid_yymmdd6(s: str) -> bool:
    s = re.sub(r"\D", "", s or "")
    if len(s) != 6:
        return False
    mm = int(s[2:4])
    dd = int(s[4:6])
    return 1 <= mm <= 12 and 1 <= dd <= 31


def _boost_digits(img: Image.Image, scale: int = 3) -> Image.Image:
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g)
    if scale and scale > 1:
        g = g.resize((g.width * scale, g.height * scale), resample=_PILImage.LANCZOS)
    try:
        g = g.filter(ImageFilter.SHARPEN)
    except Exception:
        pass
    return g


def _ocr_digits_line(img: Image.Image) -> str:
    try:
        proc = _boost_digits(img, scale=3)
        t1 = _ocr(proc, lang="eng", config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789-")
        t2 = _ocr(proc, lang="eng", config="--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789-")
        return (t1 or "") + "\n" + (t2 or "")
    except Exception:
        return ""


def dob_to_arc_front(dob: str) -> str:
    s = re.sub(r"\D", "", dob or "")
    if len(s) != 8:
        return ""
    yyyy, mm, dd = s[:4], s[4:6], s[6:8]
    try:
        if not (1 <= int(mm) <= 12 and 1 <= int(dd) <= 31):
            return ""
    except Exception:
        return ""
    return yyyy[2:] + mm + dd


def _normalize_hangul_name(s: str) -> str:
    s = re.sub(r"[^가-힣]", "", s or "")
    return s if 2 <= len(s) <= 4 else ""


def _looks_like_korean_address(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    has_province = bool(re.search(
        r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)", s
    ))
    # Require a word-ending token, not a bare syllable inside an unrelated word.
    # e.g. "군구" contains "구" but not "[가-힣]+구(\s|$|\d)" → correctly rejected.
    has_admin = bool(re.search(r'[가-힣]{1,6}[시군구](?:\s|$|\d)', s))
    has_road  = bool(re.search(r'[가-힣]{2,8}(?:대로|번길|로|길)(?:\s|$|\d)', s))
    if not (has_admin or has_road):
        return False
    if not has_province and not re.search(r"\d", s):
        return False
    return True


# Strong final-save gate: BOTH admin-unit AND road-name word-ending tokens required.
_ADDR_ADMIN_TOKEN_RE = re.compile(r'[가-힣]{1,6}[시군구](?:\s|$|\d)')
_ADDR_ROAD_TOKEN_RE  = re.compile(r'[가-힣]{2,8}(?:대로|번길|로|길)(?:\s|$|\d)')


def _is_valid_address_candidate(s: str) -> bool:
    """Reject any candidate that doesn't structurally look like a Korean address."""
    s = (s or '').strip()
    if not s or _kor_count(s) < 5 or len(s) < 8:
        return False
    if not re.search(r'(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)', s):
        return False
    return bool(_ADDR_ADMIN_TOKEN_RE.search(s)) and bool(_ADDR_ROAD_TOKEN_RE.search(s))


def _dedup_address(addr: str) -> str:
    """Remove duplicate address when OCR reads the same block twice.
    Detects: '경기도 시흥시 A ... 경기도 시흥시 A ...' → '경기도 시흥시 A ...'
    Trigger: same province/city marker appears a second time at least 8 chars
    after the first and at least 1/3 into the string."""
    if not addr or len(addr) < 16:
        return addr
    _prov = r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    m1 = re.search(_prov, addr)
    if not m1:
        return addr
    search_from = m1.end() + 8
    if search_from >= len(addr):
        return addr
    m2 = re.search(_prov, addr[search_from:])
    if not m2:
        return addr
    cut_pos = search_from + m2.start()
    if cut_pos < len(addr) // 3:
        return addr  # second marker too early — not a duplication pattern
    candidate = addr[:cut_pos].strip(" ,")
    return candidate if len(candidate) >= 8 else addr


# ─────────────────────────────────────────────────────────────────────────────
# 8) GEOMETRY HELPERS — ARC 카드 deskew + 뒷면 테이블 방향 결정
# ─────────────────────────────────────────────────────────────────────────────

def _card_tilt_from_top_edge(img: Image.Image) -> tuple[float, tuple | None]:
    """
    흰 배경 위 ARC 카드의 기울기를 상단 엣지 픽셀 선형 피팅으로 추정.
    Returns (tilt_deg, card_bbox_or_None).
      tilt_deg > 0: 오른쪽이 아래(CW 기울기) → PIL.rotate(+tilt) 로 보정.
    """
    if np is None or img is None:
        return 0.0, None
    try:
        w, h = img.size
        sc = min(1.0, 800 / max(w, h))
        work = img.resize((int(w * sc), int(h * sc)), resample=_PILImage.BILINEAR) if sc < 1.0 else img
        sw, sh = work.size
        arr  = np.asarray(ImageOps.grayscale(work))
        dark = arr < 200

        cx0, cx1 = int(sw * 0.10), int(sw * 0.90)
        half_h   = int(sh * 0.50)
        step     = max(1, (cx1 - cx0) // 60)
        cols_used: list[float] = []
        top_rows:  list[float] = []
        for c in range(cx0, cx1, step):
            idxs = np.where(dark[:half_h, c])[0]
            if len(idxs):
                cols_used.append(float(c))
                top_rows.append(float(idxs[0]))

        if len(cols_used) < 10:
            return 0.0, None

        ra  = np.array(top_rows)
        med = float(np.median(ra))
        std = float(np.std(ra))
        if std > 1:
            mask = np.abs(ra - med) <= 2.5 * std
            if mask.sum() >= 8:
                cols_used = [c for c, m in zip(cols_used, mask) if m]
                top_rows  = [r for r, m in zip(top_rows,  mask) if m]
        if len(cols_used) < 5:
            return 0.0, None

        # row = slope * col + intercept
        # slope > 0 → 오른쪽이 아래 → CW 기울기
        slope, _ = np.polyfit(np.array(cols_used), np.array(top_rows), 1)
        tilt = float(_math.degrees(_math.atan(float(slope))))

        ys, xs = np.where(dark)
        bbox = (int(xs.min() / sc), int(ys.min() / sc),
                int(xs.max() / sc), int(ys.max() / sc)) if len(ys) else None
        return tilt, bbox
    except Exception:
        return 0.0, None


def _deskew_card_image(img: Image.Image) -> tuple[Image.Image, float, tuple | None]:
    """
    ARC 카드 1회 deskew. |tilt| ∈ (0.3°, 10°) 일 때만 보정 적용.
    Returns (corrected_img, angle_applied_deg, card_bbox).
      angle_applied > 0 → CCW 회전으로 CW 기울기 보정.
    """
    tilt, bbox = _card_tilt_from_top_edge(img)
    if abs(tilt) < 0.3 or abs(tilt) > 10.0:
        return img, 0.0, bbox
    # tilt > 0 → CW 기울기 → CCW(PIL rotate +) 로 보정
    corrected = img.rotate(
        tilt, expand=False, resample=_PILImage.BILINEAR,
        fillcolor=(255, 255, 255),
    )
    return corrected, tilt, bbox


def _geometry_orient_back(bot: Image.Image) -> tuple[Image.Image, dict]:
    """
    등록증 뒷면 geometry-first 방향 결정.

    알고리즘:
      1. 다크픽셀 맵에서 내부(15%-85%) 영역의 컬럼/행 밀도를 계산.
      2. 가장 강한 수직선(컬럼 밀도 피크)과 수평선(행 밀도 피크)을 찾는다.
      3. 두 강도를 비교 → 수직 우세면 0°/180°, 수평 우세면 90°/270°.
      4. 위치 비율로 두 후보 중 하나 선택 (spec: 0.30–0.43 = 좁은쪽, 0.57–0.70 = 반대).
      5. 전체 해상도 이미지에 coarse 회전 적용.
      6. 보정 후 이미지에서 다시 디바이더 컬럼 탐지 → 기울기 측정 → fine deskew.

    Returns (oriented_image, debug_dict).
    """
    dbg: dict = {}
    if np is None or bot is None:
        return bot, dbg
    try:
        w0, h0 = bot.size
        sc = min(1.0, 800 / max(w0, h0))
        work = bot.resize((int(w0 * sc), int(h0 * sc)), resample=_PILImage.BILINEAR) if sc < 1.0 else bot
        sw, sh = work.size

        arr  = np.asarray(ImageOps.grayscale(work))
        dark = (arr < 160).astype(np.float32)

        # 내부 영역 [15%, 85%]
        mx0, mx1 = int(sw * 0.15), int(sw * 0.85)
        my0, my1 = int(sh * 0.15), int(sh * 0.85)
        interior = dark[my0:my1, mx0:mx1]
        iw = mx1 - mx0
        ih = my1 - my0

        def _sm(a: np.ndarray, k: int = 5) -> np.ndarray:
            return np.convolve(a, np.ones(k) / k, mode='same') if len(a) > k else a

        col_sm = _sm(interior.mean(axis=0))
        row_sm = _sm(interior.mean(axis=1))

        vs0, vs1 = int(iw * 0.20), int(iw * 0.80)
        hs0, hs1 = int(ih * 0.20), int(ih * 0.80)

        v_rel  = int(np.argmax(col_sm[vs0:vs1])) + vs0
        v_abs  = v_rel + mx0
        v_frac = v_abs / sw
        v_str  = float(col_sm[v_rel])

        h_rel  = int(np.argmax(row_sm[hs0:hs1])) + hs0
        h_abs  = h_rel + my0
        h_frac = h_abs / sh
        h_str  = float(row_sm[h_rel])

        dbg.update({
            "v_line_frac": round(v_frac, 3), "v_line_strength": round(v_str, 3),
            "h_line_frac": round(h_frac, 3), "h_line_strength": round(h_str, 3),
        })

        # 스펙 범위보다 약간 넓게 (edge case 흡수)
        LO, HI   = 0.30, 0.43
        LO2, HI2 = 0.57, 0.70

        is_vert = v_str >= h_str * 0.75
        coarse, confidence = 0, "ok"

        if is_vert:
            if   LO  <= v_frac <= HI:  coarse = 0
            elif LO2 <= v_frac <= HI2: coarse = 180
            else: confidence = "low_v"
        else:
            # 수평 디바이더 → 카드가 90° 또는 270° 회전된 상태
            if   LO  <= h_frac <= HI:  coarse = 90    # PIL CCW 90° → 올바른 방향
            elif LO2 <= h_frac <= HI2: coarse = 270
            else: confidence = "low_h"

        dbg.update({
            "coarse_rotation":     coarse,
            "coarse_confidence":   confidence,
            "is_vertical_divider": is_vert,
        })

        oriented = bot.rotate(coarse, expand=True) if coarse else bot

        # ── Fine deskew ──────────────────────────────────────────────────────
        fine_angle  = 0.0
        divider_frac = v_frac
        try:
            ow, oh = oriented.size
            sc2 = min(1.0, 800 / max(ow, oh))
            w2 = oriented.resize((int(ow * sc2), int(oh * sc2)), resample=_PILImage.BILINEAR) if sc2 < 1.0 else oriented
            sw2, sh2 = w2.size
            d2  = (np.asarray(ImageOps.grayscale(w2)) < 160).astype(np.float32)

            mx2 = int(sw2 * 0.15)
            my2 = int(sh2 * 0.15)
            int2 = d2[my2:sh2 - my2, mx2:sw2 - mx2]
            iw2  = (sw2 - mx2) - mx2

            cd2_raw = int2.mean(axis=0)
            cd2_sm  = _sm(cd2_raw)
            dv0, dv1 = int(iw2 * 0.20), int(iw2 * 0.80)
            dr = int(np.argmax(cd2_sm[dv0:dv1])) + dv0
            # 스무딩이 실제 peak 위치를 클러스터 중심으로 끌어당기는 것을 방지.
            # unsmoothed 밀도로 ±25컬럼 내 진짜 최댓값 컬럼을 찾는다.
            # (테이블 border 이중선 간격이 ~30px 이므로 ±12는 실제 peak 를 놓친다)
            ref_lo = max(dv0, dr - 25)
            ref_hi = min(dv1, dr + 26)
            dr = ref_lo + int(np.argmax(cd2_raw[ref_lo:ref_hi]))
            da = dr + mx2
            divider_frac = da / sw2
            dbg["divider_col_unsmoothed"] = da

            # ±3px 밴드 안의 다크픽셀 → 기울기 측정
            bl = max(0, da - 3)
            br = min(sw2, da + 4)
            band = d2[my2:sh2 - my2, bl:br]
            ys2, xs2 = np.where(band > 0.5)

            if len(ys2) >= 12:
                # col = slope * row + intercept;  완벽히 수직이면 slope ≈ 0
                # slope > 0 → 디바이더가 CW로 기울어짐 → 카드가 CCW 기울기
                # → CW 보정 = PIL.rotate(-fine_angle)
                slope2, _ = np.polyfit(
                    (ys2 + my2).astype(float),
                    (xs2 + bl ).astype(float),
                    1,
                )
                fine_angle = float(_math.degrees(_math.atan(float(slope2))))
                dbg["divider_slope"] = round(float(slope2), 4)

                if 0.3 <= abs(fine_angle) <= 8.0:
                    oriented = oriented.rotate(
                        -fine_angle, expand=False,
                        resample=_PILImage.BILINEAR,
                        fillcolor=(255, 255, 255),
                    )
        except Exception as _fe:
            dbg["fine_deskew_error"] = str(_fe)

        dbg.update({
            "fine_deskew_angle": round(fine_angle, 2),
            "divider_frac":      round(divider_frac, 3),
            "back_card_bbox":    (0, 0, w0, h0),
        })
        return oriented, dbg

    except Exception as e:
        return bot, {"back_geom_error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# 9) 계층적 행정구역 정규화 — Level1(시도) / Level2(시군구)
# ─────────────────────────────────────────────────────────────────────────────

LEVEL1_REGIONS: list[str] = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시",
    "광주광역시", "대전광역시", "울산광역시", "세종특별자치시",
    "경기도", "강원특별자치도", "충청북도", "충청남도",
    "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도",
]

# OCR 오인식 → 정규 시도명 (자주 나타나는 오류만, 보수적)
LEVEL1_ALIASES: dict[str, str] = {
    "서울특발시": "서울특별시",
    "서울룩별시": "서울특별시",
    "서올특별시": "서울특별시",
    "경기두":     "경기도",
    "경기로":     "경기도",
    "강원도":     "강원특별자치도",
    "전라북도":   "전북특별자치도",
    "전북도":     "전북특별자치도",
    "제주도":     "제주특별자치도",
}

_LEVEL1_SHORT_MAP: dict[str, str] = {
    "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시",
    "인천": "인천광역시", "광주": "광주광역시", "대전": "대전광역시",
    "울산": "울산광역시", "세종": "세종특별자치시", "경기": "경기도",
    "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
    "전북": "전북특별자치도", "전남": "전라남도",
    "경북": "경상북도", "경남": "경상남도", "제주": "제주특별자치도",
}

LEVEL2_BY_PARENT: dict[str, list[str]] = {
    "서울특별시": [
        "종로구","중구","용산구","성동구","광진구","동대문구","중랑구",
        "성북구","강북구","도봉구","노원구","은평구","서대문구","마포구",
        "양천구","강서구","구로구","금천구","영등포구","동작구","관악구",
        "서초구","강남구","송파구","강동구",
    ],
    "부산광역시": [
        "중구","서구","동구","영도구","부산진구","동래구","남구",
        "북구","해운대구","사하구","금정구","강서구","연제구",
        "수영구","사상구","기장군",
    ],
    "대구광역시": ["중구","동구","서구","남구","북구","수성구","달서구","달성군","군위군"],
    "인천광역시": [
        "중구","동구","미추홀구","연수구","남동구","부평구",
        "계양구","서구","강화군","옹진군",
    ],
    "광주광역시": ["동구","서구","남구","북구","광산구"],
    "대전광역시": ["동구","중구","서구","유성구","대덕구"],
    "울산광역시": ["중구","남구","동구","북구","울주군"],
    "세종특별자치시": [],
    "경기도": [
        "수원시","고양시","용인시","성남시","부천시","안산시","화성시",
        "남양주시","평택시","안양시","의정부시","파주시","시흥시",
        "김포시","광주시","광명시","군포시","하남시","오산시","이천시",
        "안성시","구리시","의왕시","포천시","양주시","여주시",
        "과천시","동두천시","가평군","양평군","연천군",
    ],
    "강원특별자치도": [
        "춘천시","원주시","강릉시","동해시","태백시","속초시","삼척시",
        "홍천군","횡성군","영월군","평창군","정선군",
        "철원군","화천군","양구군","인제군","고성군","양양군",
    ],
    "충청북도": [
        "청주시","충주시","제천시","보은군","옥천군","영동군",
        "증평군","진천군","괴산군","음성군","단양군",
    ],
    "충청남도": [
        "천안시","공주시","보령시","아산시","서산시","논산시",
        "계룡시","당진시","금산군","부여군","서천군","청양군",
        "홍성군","예산군","태안군",
    ],
    "전북특별자치도": [
        "전주시","군산시","익산시","정읍시","남원시","김제시",
        "완주군","진안군","무주군","장수군","임실군","순창군","고창군","부안군",
    ],
    "전라남도": [
        "목포시","여수시","순천시","나주시","광양시","담양군",
        "곡성군","구례군","고흥군","보성군","화순군","장흥군",
        "강진군","해남군","영암군","무안군","함평군","영광군",
        "장성군","완도군","진도군","신안군",
    ],
    "경상북도": [
        "포항시","경주시","김천시","안동시","구미시","영주시",
        "영천시","상주시","문경시","경산시","의성군","청송군",
        "영양군","영덕군","청도군","고령군","성주군","칠곡군",
        "예천군","봉화군","울진군","울릉군",
    ],
    "경상남도": [
        "창원시","진주시","통영시","사천시","김해시","밀양시",
        "거제시","양산시","의령군","함안군","창녕군","고성군",
        "남해군","하동군","산청군","함양군","거창군","합천군",
    ],
    "제주특별자치도": ["제주시","서귀포시"],
}

# Level2 OCR 오인식 alias — 실제 OCR 출력에서 확인된 오류만 (보수적)
LEVEL2_ALIASES_BY_PARENT: dict[str, dict[str, str]] = {
    "서울특별시": {
        "강남기": "강남구", "강남가": "강남구",   # 기/가 → 구 혼동
        "서초기": "서초구",
        "마프구": "마포구",                        # ㅗ→ㅡ 오인식
        "은평기": "은평구",
    },
    "경기도": {
        "시흥기": "시흥시", "시홍시": "시흥시",    # 홍/흥 혼동
        "수원기": "수원시", "수언시": "수원시",    # 언/원 혼동
        "부천기": "부천시",
        "안산기": "안산시",
    },
}


def _normalize_level1_region(text: str) -> tuple[str, float]:
    """Level1 시도명 탐색. 반환: (정규 시도명, 신뢰도 0~1)"""
    for lvl1 in LEVEL1_REGIONS:
        if lvl1 in text:
            return lvl1, 1.0
    for alias, canonical in LEVEL1_ALIASES.items():
        if alias in text:
            return canonical, 0.8
    for short, canonical in _LEVEL1_SHORT_MAP.items():
        if text.startswith(short):
            return canonical, 0.6
    return "", 0.0


def _normalize_level2_region(text: str, parent: str) -> tuple[str, float]:
    """Level1 확정 후 해당 parent의 Level2 목록에서만 시군구 탐색."""
    children = LEVEL2_BY_PARENT.get(parent, [])
    for child in children:
        if child in text:
            return child, 1.0
    aliases = LEVEL2_ALIASES_BY_PARENT.get(parent, {})
    for alias, canonical in aliases.items():
        if alias in text:
            return canonical, 0.8
    return "", 0.0


def _apply_hierarchical_region_normalization(addr: str) -> str:
    """
    Level1 → Level2 계층 정규화.
    신뢰도가 낮으면 원본 반환 (안전 최우선).
    전국 퍼지 검색 없음 — alias + 단축어 exact match 만 수행.
    """
    if not addr:
        return addr
    lvl1, conf1 = _normalize_level1_region(addr)
    if not lvl1 or conf1 < 0.6:
        return addr  # 시도 불명확 → 손대지 않음
    result = addr
    # Level1 alias 보정 (alias로 잡힌 경우만 교체)
    if conf1 == 0.8:
        for alias, canonical in LEVEL1_ALIASES.items():
            if alias in result:
                result = result.replace(alias, canonical, 1)
                break
    # Level2: 올바른 명칭이 이미 있으면 건드리지 않음
    _, conf2 = _normalize_level2_region(result, lvl1)
    if conf2 < 0.8:
        aliases2 = LEVEL2_ALIASES_BY_PARENT.get(lvl1, {})
        for alias, canonical in aliases2.items():
            if alias in result:
                result = result.replace(alias, canonical, 1)
                break
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 7) 등록증 파서 (원본 그대로 — st.session_state 사용 없음)
# ─────────────────────────────────────────────────────────────────────────────

def parse_arc(img, fast: bool = False, passport_dob: str = ""):
    """
    등록증 이미지 파서.
    원본: pages/page_scan.py::parse_arc()
    변경 없음 — 원본에 st.session_state 사용 없음.
    반환: {'한글', '등록증', '번호', '발급일', '만기일', '주소'}
    """
    out = {}
    if img is None:
        return out

    if fast:
        max_side = 1600
        w0, h0 = img.size
        scale = max_side / float(max(w0, h0))
        if scale < 1.0:
            img = img.resize(
                (int(w0 * scale), int(h0 * scale)),
                resample=_PILImage.LANCZOS,
            )

    top, bot = _split_arc_front_back(img)

    # ── 앞면 deskew (geometry-first) ─────────────────────────────────────────
    top, _front_deskew_angle, _front_bbox = _deskew_card_image(top)
    _debug_geom: dict = {
        "front_deskew_angle": round(_front_deskew_angle, 2),
        "front_card_bbox":    _front_bbox,
    }

    try:
        # fast=True: 1회(kor+eng, psm=6)만 시도 — 호출 수 2→1로 감소
        max_tries = 1 if fast else None
        t_top = ocr_try_all(top, langs=("kor+eng",) if fast else ("kor", "kor+eng"), max_tries=max_tries)["text"]
    except Exception:
        t_top = ""
    tn_top = t_top

    def _valid_arc_back7(s: str) -> bool:
        """Korean Alien Registration back-7 first digit must be 5–8 (foreign national codes).
        1–4 = Korean nationals; 5–8 = foreign residents. Rejects OCR noise like '1096860'."""
        return len(s) == 7 and s[0] in "56789"  # 9 included for newer provisional codes

    def _collect_front_num_candidates(front_img: Image.Image, base_text: str):
        cand = []
        dense_chunks = []
        try:
            w, h = front_img.size
            # Three ROIs covering different card designs:
            #   pair_line:   upper area — original ARC blue/pink cards put number near top
            #   mid_number:  middle area — yellow-design and newer cards put number ~35-58% height
            #   front_only:  lower-left — 6-digit front stamp area on some older layouts
            # fast=True: mid_number만 사용 (가중치 최고, Tesseract 호출 6→2회로 감소)
            if fast:
                rois = {
                    "mid_number": front_img.crop((int(w * 0.30), int(h * 0.33), int(w * 0.92), int(h * 0.58))),
                }
            else:
                rois = {
                    "pair_line":  front_img.crop((int(w * 0.35), int(h * 0.05), int(w * 0.92), int(h * 0.26))),
                    "mid_number": front_img.crop((int(w * 0.30), int(h * 0.33), int(w * 0.92), int(h * 0.58))),
                    "front_only": front_img.crop((int(w * 0.08), int(h * 0.68), int(w * 0.42), int(h * 0.93))),
                }
            # ROI priority weights: mid_number > pair_line > front_only
            roi_weights = {"pair_line": 8, "mid_number": 10, "front_only": 4}
            for src_name, roi in rois.items():
                txt = _ocr_digits_line(roi)
                dense = re.sub(r"(?<=\d)\s+(?=\d)", "", txt or "")
                if dense:
                    dense_chunks.append(dense)

                w_bonus = roi_weights.get(src_name, 4)
                for m in re.finditer(r"(?<!\d)(\d{6})\D{0,8}(\d{7})(?!\d)", dense):
                    front, back = m.group(1), m.group(2)
                    if not _valid_arc_back7(back):
                        continue  # back 7 fails foreign-code validation — skip
                    score = w_bonus
                    if _valid_yymmdd6(front):
                        score += 10
                    if "-" in m.group(0) or "—" in m.group(0) or "–" in m.group(0):
                        score += 2
                    cand.append(("pair", score, front, back, src_name))

                for m in re.finditer(r"(?<!\d)(\d{6})(?!\d)", dense):
                    front = m.group(1)
                    if not _valid_yymmdd6(front):
                        continue
                    score = 12 if src_name == "front_only" else w_bonus - 2
                    cand.append(("front", score, front, "", src_name))

                for m in re.finditer(r"(?<!\d)(\d{7})(?!\d)", dense):
                    back = m.group(1)
                    if not _valid_arc_back7(back):
                        continue  # reject any lone 7-digit that fails foreign-code check
                    # Lone back-7 only accepted from pair_line/mid_number with modest score
                    score = 5 if src_name in ("pair_line", "mid_number") else 1
                    cand.append(("back", score, "", back, src_name))
        except Exception:
            pass

        dense_all = re.sub(r"(?<=\d)\s+(?=\d)", "", base_text or "")
        if dense_all:
            dense_chunks.append(dense_all)

        for m in re.finditer(r"(?<!\d)(\d{6})\D{0,8}(\d{7})(?!\d)", dense_all):
            front, back = m.group(1), m.group(2)
            score = 0
            if _valid_yymmdd6(front):
                score += 6
            if "-" in m.group(0) or "—" in m.group(0) or "–" in m.group(0):
                score += 2
            cand.append(("pair", score, front, back, "top_text"))
        for m in re.finditer(r"(?<!\d)(\d{6})(?!\d)", dense_all):
            front = m.group(1)
            if _valid_yymmdd6(front):
                cand.append(("front", 2, front, "", "top_text"))
        for m in re.finditer(r"(?<!\d)(\d{7})(?!\d)", dense_all):
            if _valid_arc_back7(m.group(1)):  # same foreign-code rule as ROI paths
                cand.append(("back", 1, "", m.group(1), "top_text"))

        return cand, "\n".join([t for t in dense_chunks if t])

    num_cands, t_dense = _collect_front_num_candidates(top, tn_top)
    front_scores = {}
    back_scores = {}
    pair_scores = []

    for kind, score, front, back, src_name in num_cands:
        if kind == "pair" and front and back:
            pair_scores.append((score, front, back, src_name))
            front_scores[front] = front_scores.get(front, 0) + max(score, 1)
            back_scores[back] = back_scores.get(back, 0) + max(score, 1)
        elif kind == "front" and front:
            front_scores[front] = front_scores.get(front, 0) + max(score, 1)
        elif kind == "back" and back:
            back_scores[back] = back_scores.get(back, 0) + max(score, 1)

    best_front = ""
    best_back = ""

    if front_scores:
        best_front = sorted(front_scores.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)[0][0]

    if best_front and pair_scores:
        pair_for_front = [x for x in pair_scores if x[1] == best_front]
        if pair_for_front:
            pair_for_front.sort(key=lambda x: x[0], reverse=True)
            best_back = pair_for_front[0][2]

    if best_front and not best_back:
        # Only consider 7-digit candidates that pass the foreign-code check.
        cands7 = [m for m in re.finditer(r"(?<!\d)(\d{7})(?!\d)", t_dense)
                  if _valid_arc_back7(m.group(1))]
        if cands7:
            idx6 = t_dense.find(best_front)
            if idx6 >= 0:
                best7 = min(cands7, key=lambda m: abs(m.start() - idx6))
                best_back = best7.group(1)
            else:
                best_back = cands7[0].group(1)

    if not best_back and back_scores:
        best_back = sorted(back_scores.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)[0][0]

    if (not best_back) or (not best_front):
        for m in re.finditer(r"\d{11,14}", t_dense):
            s = m.group(0)
            if len(s) == 13:
                front, back = s[:6], s[6:]
                # Both halves must be independently valid — reject Korean-national back-7.
                if _valid_yymmdd6(front) and _valid_arc_back7(back):
                    if not best_front:
                        best_front = front
                    if not best_back:
                        best_back = back
                    break

    if best_front:
        out["등록증"] = best_front
    if best_back:
        out["번호"] = best_back

    def _find_all_dates(text: str):
        cands = set()
        if not text:
            return []
        for m in re.finditer(r"(\d{4})[.\-\/](\d{1,2})[.\-\/](\d{1,2})", text):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                cands.add(_dt(y, mo, d).strftime("%Y-%m-%d"))
            except Exception:
                pass
        MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                  "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
        for m in re.finditer(r"(\d{1,2})\s*([A-Z]{3})\s*(\d{4})", (text or "").upper()):
            d, mon, y = int(m.group(1)), MONTHS.get(m.group(2), 0), int(m.group(3))
            if mon:
                try:
                    cands.add(_dt(y, mon, d).strftime("%Y-%m-%d"))
                except Exception:
                    pass
        return sorted(cands)

    def _pick_labeled_date(text: str, labels_regex: str):
        if not text:
            return ""
        # Gap raised to 30 to handle bilingual labels like "발급일자 Issue Date 2024.04.30"
        m1 = re.search(labels_regex + r"[^\d]{0,30}(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})", text, re.I)
        if m1:
            # Use lastindex: labels_regex creates group 1, date pattern is group 2
            return m1.group(m1.lastindex).replace("/", "-").replace(".", "-")
        return ""

    issued = _pick_labeled_date(tn_top, r"(발\s*급|발\s*행|issue|issued)")
    if not issued:
        ds = _find_all_dates(tn_top)
        if ds:
            issued = ds[0]
    if issued:
        out["발급일"] = issued

    def _extract_name_from_text(text: str) -> str:
        ban = {
            "외국", "국내", "거소", "신고", "증", "재외동포",
            "재외", "동포", "국적", "주소", "발급", "발급일", "발급일자",
            "만기", "체류", "자격", "종류", "성명", "이름",
        }
        m = re.search(r"(성명|이름)\s*[:\-]?\s*([가-힣]{2,4})", text)
        if m and m.group(2) not in ban:
            return m.group(2)
        toks = re.findall(r"[가-힣]{2,4}", text)
        toks = [t for t in toks if t not in ban]
        if not toks:
            return ""
        pos_label = min(
            [p for p in [text.find("성명"), text.find("이름")] if p != -1] + [len(text) // 2]
        )
        best, best_d = "", 10 ** 9
        for t in toks:
            p = text.find(t)
            if p != -1:
                d = abs(p - pos_label)
                if d < best_d:
                    best, best_d = t, d
        return best

    def _extract_name_from_roi(img, text_top: str) -> str:
        """
        Korean name extraction from ARC front card. Priority order:
          1. Parenthesised name in name-line ROI OCR  — localised + structured
          2. Parenthesised name in full-card OCR text — full-scan match
          3. Label-adjacent name in full-card OCR text — "성명 홍길동" pattern
          4. Best Korean token within the name-line ROI only — geometrically constrained local
          5. Return ""                                 — never guess from full-card token pool
        fast=True: 1 ROI × 1 lang(kor+eng) × 1 PSM(6) = 1 Tesseract 호출만 사용
        """
        roi_texts = []  # collect for level-4 fallback
        try:
            w, h = img.size
            # ROI right boundary 0.95: parenthesised Korean name follows the English name on
            # the same line and starts at ≈74–80% card width for typical 9-char names.
            all_rois = [
                img.crop((int(w * 0.26), int(h * 0.25), int(w * 0.95), int(h * 0.46))),
                img.crop((int(w * 0.22), int(h * 0.20), int(w * 0.95), int(h * 0.53))),
            ]
            rois = all_rois[:1] if fast else all_rois
            psm_list = (6,) if fast else (7, 6)
            for roi in rois:
                g = ImageOps.grayscale(roi)
                g = ImageOps.autocontrast(g)
                g = g.resize((max(1, g.width * 2), max(1, g.height * 2)), resample=_PILImage.LANCZOS)
                try:
                    g = g.filter(ImageFilter.SHARPEN)
                except Exception:
                    pass
                for psm in psm_list:
                    # fast 모드: kor+eng 단일 호출로 parens 탐색
                    if fast:
                        txt2 = _ocr(g, lang="kor+eng", config=f"--oem 3 --psm {psm}") or ""
                        roi_texts.append(txt2)
                        m2 = re.search(r"\(([가-힣]{2,4})\)", txt2)
                        if m2:
                            cand2 = m2.group(1)
                            if cand2 not in _NAME_BAN and not cand2.endswith("출"):
                                return cand2
                        continue
                    txt = _ocr(g, lang="kor", config=f"--oem 3 --psm {psm}") or ""
                    roi_texts.append(txt)
                    m = re.search(r"\(([가-힣]{2,4})\)", txt)
                    if m:
                        cand = m.group(1)
                        if cand not in _NAME_BAN and not cand.endswith("출"):
                            return cand  # Level 1: ROI parentheses match
                    # kor+eng improves segmentation on bilingual lines
                    # (English name + Korean name in parentheses on the same line).
                    txt2 = _ocr(g, lang="kor+eng", config=f"--oem 3 --psm {psm}") or ""
                    if txt2 and txt2 != txt:
                        roi_texts.append(txt2)
                        m2 = re.search(r"\(([가-힣]{2,4})\)", txt2)
                        if m2:
                            cand2 = m2.group(1)
                            if cand2 not in _NAME_BAN and not cand2.endswith("출"):
                                return cand2  # Level 1b: ROI parens via kor+eng
        except Exception:
            pass

        # Level 2: parenthesised name in full-card OCR text
        m2 = re.search(r"\(([가-힣]{2,4})\)", text_top or "")
        if m2:
            cand = m2.group(1)
            if cand not in _NAME_BAN and not cand.endswith("출"):
                return cand

        # Level 3: "성명 홍길동" label-adjacent name in full-card OCR text
        m3 = re.search(r"(성명|이름)\s*[:\-]?\s*([가-힣]{2,4})", text_top or "")
        if m3:
            cand = m3.group(2)
            if cand not in _NAME_BAN and not cand.endswith("출"):
                return cand

        # Level 4: local ROI token fallback.
        # ONLY tokens from within the name-line ROI — geometrically constrained to the
        # name area. NOT full-card text. Prefers 3-char tokens (most Korean names).
        # This is structurally different from the old broad full-card token pool.
        roi_pool: list[tuple[int, str]] = []
        for txt in roi_texts:
            for tok in re.findall(r"[가-힣]{2,4}", txt):
                tok = _normalize_hangul_name(tok)
                if tok and tok not in _NAME_BAN and not tok.endswith("출"):
                    priority = 1 if len(tok) == 3 else 0  # 3-char names most common
                    roi_pool.append((priority, tok))
        if roi_pool:
            roi_pool.sort(key=lambda x: x[0], reverse=True)
            return roi_pool[0][1]

        return ""

    name_ko = _extract_name_from_roi(top, t_top)
    if name_ko:
        out["한글"] = name_ko

    # ── 뒷면 geometry-first 방향 결정 (OCR 회전 투표 제거) ────────────────────
    _rot_back, _back_geom_dbg = _geometry_orient_back(bot)
    _debug_geom.update(_back_geom_dbg)

    # 기하학적 신뢰도 낮을 때 OCR 기반 0°/180° 보완 (low_v / low_h)
    # geometry 가 ambiguous 하면 현재 방향과 +180° 회전 결과를 각 1회 OCR 비교
    if _back_geom_dbg.get("coarse_confidence") in ("low_v", "low_h") and not fast:
        _ambig_cur_gray = ImageOps.autocontrast(ImageOps.grayscale(_rot_back))
        _s0 = _kor_word_score(_ocr(_ambig_cur_gray, lang="kor", config="--oem 3 --psm 6"))
        _alt_deg = (_back_geom_dbg.get("coarse_rotation", 0) + 180) % 360
        _alt_back = bot.rotate(_alt_deg, expand=True)
        _s1 = _kor_word_score(_ocr(
            ImageOps.autocontrast(ImageOps.grayscale(_alt_back)),
            lang="kor", config="--oem 3 --psm 6",
        ))
        _debug_geom.update({
            "ambig_score_current": _s0,
            "ambig_score_alt":     _s1,
            "ambig_alt_rotation":  _alt_deg,
            "ambig_winner":        "alt" if _s1 > _s0 else "current",
        })
        if _s1 > _s0:
            _rot_back = _alt_back

    # 방향 확정된 뒷면 전체 OCR (날짜 추출 + 주소 fallback 용)
    _rb_gray = ImageOps.autocontrast(ImageOps.grayscale(_rot_back))
    tn_bot = _ocr(_rb_gray, lang="kor", config="--oem 3 --psm 6")
    if not fast:
        tn_bot += "\n" + _ocr(_rb_gray, lang="kor", config="--oem 3 --psm 4")

    # ── 만기일/주소: page_scan.py donor 로직 그대로 이식 ─────────────────────
    # 주의: 회전 선택은 현재 backend(_geometry_orient_back) 유지,
    #       그 이후 만기일/주소 추출 순서만 donor 기준으로 복원한다.

    # donor 디버그용 컬럼 OCR은 유지하되, 추출 로직에는 직접 사용하지 않는다.
    _rb_w, _rb_h = _rot_back.size
    _div_frac = float(_back_geom_dbg.get("divider_frac", 0.37))
    _div_x    = int(_rb_w * _div_frac)
    _upper_crop = _rot_back.crop((0, 0, _rb_w, int(_rb_h * 0.15)))
    _left_crop  = _rot_back.crop((
        int(_rb_w * 0.01),
        int(_rb_h * 0.10),
        min(_div_x + int(_rb_w * 0.02), int(_rb_w * 0.48)),
        int(_rb_h * 0.92),
    ))
    _right_x = max(_div_x, int(_rb_w * 0.30))
    _right_crop = _rot_back.crop((
        _right_x,
        int(_rb_h * 0.10),
        int(_rb_w * 0.99),
        int(_rb_h * 0.92),
    ))

    _debug_geom.update({
        "left_col_bbox":          (int(_rb_w * 0.01), int(_rb_h * 0.10),
                                    min(_div_x + int(_rb_w * 0.02), int(_rb_w * 0.48)),
                                    int(_rb_h * 0.92)),
        "right_col_bbox":         (_right_x, int(_rb_h * 0.10),
                                    int(_rb_w * 0.99), int(_rb_h * 0.92)),
        "upper_date_region_bbox": (0, 0, _rb_w, int(_rb_h * 0.15)),
        "divider_x_px":           _div_x,
    })

    def _oprep(im: Image.Image) -> Image.Image:
        g = ImageOps.autocontrast(ImageOps.grayscale(im))
        if g.width < 500 or g.height < 350:
            g = g.resize((g.width * 2, g.height * 2), resample=_PILImage.LANCZOS)
        return g

    _upper_txt = _ocr(_oprep(_upper_crop), lang="kor", config="--oem 3 --psm 6")
    _left_txt  = _ocr(_oprep(_left_crop),  lang="kor", config="--oem 3 --psm 6")
    _right_prep = _oprep(_right_crop)
    _right_t6   = _ocr(_right_prep, lang="kor", config="--oem 3 --psm 6")
    _right_t4   = _ocr(_right_prep, lang="kor", config="--oem 3 --psm 4")
    _right_txt  = max([_right_t6, _right_t4], key=_kor_word_score)

    _debug_geom.update({
        "raw_upper_text": _upper_txt,
        "raw_left_text":  _left_txt,
        "raw_right_text": _right_txt,
    })

    # 🔚 만기일: page_scan.py donor 그대로 — 하단에서 발견된 모든 날짜 중 가장 늦은 날짜
    expiry = _pick_labeled_date(
        tn_bot,
        r"(만기|유효|until|expiry|expiration|valid\s*until|까지)"
    )
    ds_bot = _find_all_dates(tn_bot)

    if issued and issued in ds_bot:
        try:
            ds_bot.remove(issued)
        except ValueError:
            pass

    if expiry:
        ds_bot.append(expiry)

    if ds_bot:
        ds_bot = sorted(set(ds_bot))
        out["만기일"] = ds_bot[-1]

    # ───────── 주소(국내거소) 추출: page_scan.py donor 그대로 이식 ─────────
    def _looks_like_korean_address_donor(s: str) -> bool:
        s = (s or "").strip()
        if not s:
            return False
        if not re.search(r'(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)', s):
            return False
        if not re.search(r'(시|군|구|로|길|번길|대로)', s):
            return False
        return True

    def _clean_addr_line(s: str) -> str:
        s = (s or "").replace("|", " ").replace("｜", " ")
        s = re.sub(
            r'^\s*[\(\[]?(?:19|20)?\d{1,4}[.\-/]\d{1,2}[.\-/]\d{1,2}[\)\]]?\s*[:;|.,~\-]*\s*',
            '',
            s,
        )
        s = re.sub(r'^\s*(신고일|신고월|국내거소|체류지|Address)\s*[:;|.,~\-]*\s*', '', s, flags=re.I)
        s = re.sub(r'[^가-힣0-9A-Za-z\s\-\.,#()/~]', ' ', s)
        if ARC_REMOVE_PAREN:
            s = re.sub(r'\((?![^)]*(동|호|층))[^)]*\)', ' ', s)
        s = re.sub(r'\s{2,}', ' ', s).strip(' ,')

        m = re.search(r'(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)', s)
        if m:
            s = s[m.start():].strip()

        s = re.sub(r'^(서투시|서투시흘일고|시흥시흘일고|자버르지|자버영로|자9버영로)+\s*', '', s)
        s = re.sub(r'(군서로)\s*(\d+)\s*번길', r'\1\2번길', s)
        s = re.sub(r'(새말로)\s*(\d+)', r'\1 \2', s)
        s = re.sub(r'(\d)\s*호', r'\1호', s)
        s = re.sub(r'(\d)\s*동', r'\1동', s)
        s = re.sub(r'\s*,\s*', ', ', s)
        s = re.sub(r'\s{2,}', ' ', s).strip(' ,')

        if not _looks_like_korean_address_donor(s):
            return ""
        return s

    def _is_addr_stop_line(s: str) -> bool:
        s = (s or "").strip()
        return bool(re.search(r'(유효|유호|취업가능|민원안내|하이코리아|일련번호)', s))

    def _is_addr_header_line(s: str) -> bool:
        s = (s or "").strip()
        return bool(re.search(r'(국내거소|체류지|신고일|신고월)', s))

    def _is_junk_addr_line(s: str) -> bool:
        s = (s or '').strip()
        if not s:
            return True
        if _ADDR_BAN_RE.search(s):
            return True
        if re.fullmatch(r'[\(\)\.\-/#\s]+', s):
            return True
        if _kor_count(s) < 2 and len(re.sub(r'[^\d]', '', s)) >= 6:
            return True
        return False

    def _addr_score(s: str) -> float:
        s = _clean_addr_line(s)
        if _is_junk_addr_line(s):
            return -1.0

        has_lvl  = bool(re.search(r'(도|시|군|구)', s))
        has_road = bool(re.search(r'(로|길|번길|대로)', s))
        has_num  = bool(re.search(r'\d', s))
        has_unit = bool(re.search(r'(동|호|층|#\d+)', s))

        score = 0.0
        score += _kor_count(s) * 2.0
        score += 6.0 if has_lvl else 0.0
        score += 9.0 if has_road else 0.0
        score += 4.0 if has_num else 0.0
        score += 3.0 if has_unit else 0.0
        score += 6.0 if re.search(r'(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)', s) else 0.0
        score += min(len(s), 60) / 12.0

        if len(s) < 8:
            score -= 5.0
        if re.match(r'^\d{1,4}[.\-/]\d{1,2}[.\-/]\d{1,2}', s):
            score -= 6.0

        return score

    def _merge_addr_lines(lines: list[str]) -> list[str]:
        merged = []
        i = 0
        while i < len(lines):
            cur = (lines[i] or "").strip()
            nxt = (lines[i + 1] or "").strip() if i + 1 < len(lines) else ""

            combined = cur
            if nxt:
                cur_has_date = bool(re.search(r'\d{1,4}[.\-/]\d{1,2}[.\-/]\d{1,2}', cur))
                cur_has_addr = bool(re.search(r'(도|시|군|구|로|길|번길|대로)', cur))
                nxt_is_cont = bool(re.match(r'^[\s:;,.~\-]*(\(?[가-힣0-9]|길|로|번길|대로|동|호|층)', nxt))
                nxt_header = _is_addr_header_line(nxt)
                nxt_stop = _is_addr_stop_line(nxt)

                if cur_has_date and nxt_is_cont and not nxt_header and not nxt_stop:
                    combined = cur + " " + nxt
                    i += 1
                elif cur_has_addr and nxt_is_cont and not nxt_header and not nxt_stop:
                    combined = cur + " " + nxt
                    i += 1

            merged.append(combined)
            i += 1

        return merged

    def _extract_addr_region(text: str) -> list[str]:
        lines = [re.sub(r'\s+', ' ', l).strip() for l in (text or "").splitlines() if l.strip()]
        if not lines:
            return []

        start_idx = 0
        for i, l in enumerate(lines):
            if re.search(r'(국내거소|체류지)', l):
                start_idx = i + 1
                break

        region = []
        for l in lines[start_idx:]:
            if _is_addr_stop_line(l):
                break
            region.append(l)

        return region if region else lines

    def _best_addr_latest(text: str) -> str:
        lines = _extract_addr_region(text)
        lines = _merge_addr_lines(lines)

        best_addr = ""
        best_date = None
        best_sc = -1.0

        for raw in lines:
            if _ADDR_BAN_RE.search(raw):
                continue

            m = re.search(r'(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})', raw)
            if not m:
                continue

            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                dt = _dt(y, mo, d)
            except ValueError:
                continue

            c = _clean_addr_line(raw)
            sc = _addr_score(c)
            if sc < 0:
                continue

            if (best_date is None) or (dt > best_date) or (dt == best_date and sc > best_sc):
                best_date, best_sc, best_addr = dt, sc, c

        if best_addr:
            return best_addr

        best_addr2 = ""
        best_sc2 = -1.0
        for raw in lines:
            c = _clean_addr_line(raw)
            sc = _addr_score(c)
            if sc > best_sc2:
                best_addr2, best_sc2 = c, sc

        return best_addr2

    def _looks_weak_address(addr: str) -> bool:
        addr = (addr or "").strip()
        if not addr:
            return True
        if _kor_count(addr) < 5:
            return True
        if not re.search(r'(도|시|군|구|로|길|번길|대로)', addr):
            return True
        return False

    addr = _best_addr_latest(tn_bot)

    if _looks_weak_address(addr):
        addr2 = _best_addr_latest(t_top + "\n" + tn_bot)
        if addr2 and not _looks_weak_address(addr2):
            addr = addr2

    if _looks_weak_address(addr):
        try:
            rot_bot = _rot_back
            rw, rh = rot_bot.size
            addr_roi = rot_bot.crop((
                int(rw * 0.18),
                int(rh * 0.34),
                int(rw * 0.92),
                int(rh * 0.80),
            ))
            addr_txt = _ocr(ImageOps.grayscale(addr_roi), lang="kor", config="--oem 3 --psm 6")
            _debug_geom["addr_crop_preview"] = (addr_txt or "")[:300]
            addr_retry = _best_addr_latest(addr_txt)
            if addr_retry and not _looks_weak_address(addr_retry):
                addr = addr_retry
                _debug_geom["addr_source"] = "roi_retry"
        except Exception:
            pass

    if addr and _kor_count(addr) >= 3 and len(addr) >= 6:
        out["주소"] = addr
        _debug_geom.setdefault("addr_source", "best_addr_latest_back")
    else:
        lines_all = [l.strip() for l in (t_top + "\n" + tn_bot).splitlines() if l.strip()]
        cand_lines = _merge_addr_lines(lines_all)
        pair_lines = []
        for i, l in enumerate(lines_all[:-1]):
            pair_lines.append((l + ' ' + lines_all[i + 1]).strip())
        cand_lines.extend(_merge_addr_lines(pair_lines))
        best_line = ""
        best_score = -1.0
        for l in cand_lines:
            c = _clean_addr_line(l)
            if _kor_count(c) < 3:
                continue
            if not re.search(r'(도|시|군|구|로|길|번길|대로)', c):
                continue
            sc = _addr_score(c)
            if re.search(r'^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)', c):
                sc += 4.0
            if sc > best_score:
                best_score = sc
                best_line = c
        if best_line:
            out["주소"] = best_line
            _debug_geom.setdefault("addr_source", "forced_best_line")

    # 여권 DOB가 있으면 등록증 앞번호는 여권 기준 우선
    front_from_passport = dob_to_arc_front(passport_dob)
    if front_from_passport:
        out["등록증"] = front_from_passport
    elif out.get("등록증") and not _valid_yymmdd6(out.get("등록증", "")):
        out.pop("등록증", None)

    # Remove duplicated address text (OCR artefact: same block read twice)
    if out.get("주소"):
        out["주소"] = _dedup_address(out["주소"])

    # 계층적 행정구역 정규화 (Level1 → Level2 alias 보정)
    if out.get("주소"):
        _addr_before_norm = out["주소"]
        out["주소"] = _apply_hierarchical_region_normalization(out["주소"])
        _debug_geom["region_normalization"] = (
            f"{_addr_before_norm!r} → {out['주소']!r}"
            if _addr_before_norm != out["주소"] else "no_change"
        )

    # DB-based address correction: correct OCR mis-reads in road/dong names
    if out.get("주소"):
        try:
            from .addr_service import correct_address as _correct_addr
            out["주소"] = _correct_addr(out["주소"])
        except Exception:
            pass

    out["_debug_geometry"] = _debug_geom
    return out
