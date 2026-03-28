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
    # Added: common card-label OCR noise found in benchmark
    "국가", "지역", "발금", "발금일", "발금일자", "체류자", "체류파", "제류자",
    "발급원", "받큼일", "소신고", "겁소고", "재위동", "재외등", "체등자", "체륭자",
    "개류자", "력재외", "송영지",
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
            m_nxt = re.search(r"<+", after_sep)
            given_raw = (after_sep[:m_nxt.start()] if m_nxt else after_sep).replace("<", " ").strip()
            sur = re.sub(r"\s+", " ", sur_raw).strip()
            given = re.sub(r"\s+", " ", given_raw).strip()
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
# 5) 여권 파서 (st.session_state 제거 — 디버그 로그를 로컬 리스트로 대체)
# ─────────────────────────────────────────────────────────────────────────────

def parse_passport(img):
    """
    여권 MRZ(TD3) 전용 파서.
    원본: pages/page_scan.py::parse_passport()
    변경: st.session_state 디버그 기록 4곳 → 로컬 리스트 _debug_log 로 교체.
    반환값 형식 동일.
    """
    if img is None:
        return {}

    # 디버그 로그 (FastAPI 환경에서는 사용되지 않음, Streamlit UI 용도만)
    _debug_log = []

    # 0) EXIF 방향 보정
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    # 1) 성능 보호: 너무 큰 이미지는 축소
    max_side = 1600
    w0, h0 = img.size
    scale = max_side / float(max(w0, h0))
    if scale < 1.0:
        img = img.resize((int(w0 * scale), int(h0 * scale)), resample=_PILImage.BILINEAR)

    # 2) 여백 제거
    try:
        img = _crop_to_content_bbox(img, pad_ratio=0.03)  # type: ignore[call-arg]
    except TypeError:
        img = _crop_to_content_bbox(img)

    def _ocr_mrz_band(band_img: Image.Image) -> str:
        try:
            proc = _prep_mrz(band_img)
        except Exception:
            proc = _binarize_soft(band_img)
        cfg_common = "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ<0123456789"
        for psm in (6, 7):
            txt = _tess_string(proc, lang="ocrb+eng", config=f"--oem 1 --psm {psm} {cfg_common}", timeout_s=2)
            if (txt or "").strip():
                return txt
            txt = _tess_string(proc, lang="eng", config=f"--oem 1 --psm {psm} {cfg_common}", timeout_s=2)
            if (txt or "").strip():
                return txt
        return ""

    rotations = (0, 90, 270, 180)
    best_L1, best_L2, best_score = None, None, -1
    best_meta = {}

    for rot in rotations:
        imr = img.rotate(rot, expand=True) if rot else img
        joined = ""
        w, h = imr.size

        # Priority-0: tight bottom strips covering the MRZ zone (bottom 16–24%).
        # These are tried BEFORE edge-density windows because MRZ is always in
        # the bottom portion of an upright/inverted passport image.
        priority_bands = []
        for _pct in (16, 20, 24):
            _y0 = int(h * (1.0 - _pct / 100.0))
            priority_bands.append((f"bottom{_pct}%_pri", imr.crop((0, _y0, w, h))))

        bands = list(_mrz_windows_by_edge_density(imr, top_k=3))
        band_iters = []
        for i, (y0, y1) in enumerate(bands, start=1):
            label = f"edge#{i} {int(100*y0/h)}-{int(100*y1/h)}%"
            band_iters.append((label, imr.crop((0, y0, w, y1))))

        fallback_added = False

        for label, band in priority_bands + band_iters:
            txt = _tess_string(
                _prep_mrz(band),
                lang="ocrb+eng",
                config="--oem 1 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ<0123456789",
                timeout_s=1,
            )
            if not (txt or "").strip():
                txt = _tess_string(
                    _prep_mrz(band),
                    lang="ocrb+eng",
                    config="--oem 1 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ<0123456789",
                    timeout_s=1,
                )

            # 디버그 로그 (Streamlit UI 미사용 환경에서는 무시됨)
            _debug_log.append({"rot": rot, "band": label, "text_head": (txt or "")[:120]})

            if (txt or "").strip():
                joined += "\n" + txt

            L1, L2, sc = find_best_mrz_pair_from_text(joined)
            if sc > best_score:
                best_score = sc
                best_L1, best_L2 = L1, L2
                best_meta = {"rot": rot, "band": label, "score": sc, "L1": L1, "L2": L2}

            if best_score >= 7:
                break

        if best_score < 7 and not fallback_added:
            fallback_added = True
            for label, band in _iter_mrz_candidate_bands(imr):
                if label.startswith("edge#"):
                    continue
                txt = _tess_string(
                    _prep_mrz(band),
                    lang="ocrb+eng",
                    config="--oem 1 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ<0123456789",
                    timeout_s=1,
                )
                _debug_log.append({"rot": rot, "band": label, "text_head": (txt or "")[:120]})
                if (txt or "").strip():
                    joined += "\n" + txt

                L1, L2, sc = find_best_mrz_pair_from_text(joined)
                if sc > best_score:
                    best_score = sc
                    best_L1, best_L2 = L1, L2
                    best_meta = {"rot": rot, "band": label, "score": sc, "L1": L1, "L2": L2}

                if best_score >= 7:
                    break

        if best_score >= 7:
            break

    # best_meta는 Streamlit UI용 디버그 정보 — FastAPI 환경에서는 사용 안 함
    _ = best_meta

    if not best_L1 or not best_L2:
        return {}

    out = _parse_mrz_pair(best_L1, best_L2)
    return {
        "성":       out.get("성", ""),
        "명":       out.get("명", ""),
        "성별":     out.get("성별", ""),
        "국가":     out.get("국가", ""),
        "국적":     out.get("국가", ""),
        "여권":     out.get("여권", ""),
        "발급":     out.get("발급", ""),
        "만기":     out.get("만기", ""),
        "생년월일": out.get("생년월일", ""),
        "_raw_L1":  best_L1,
        "_raw_L2":  best_L2,
    }


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
    # Province check is a plus but OCR often garbles province names;
    # require at least a city/district/road-level component.
    has_province = bool(re.search(
        r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)", s
    ))
    has_road = bool(re.search(r"(시|군|구|로|길|번길|대로)", s))
    if not has_road:
        return False
    # Without a province marker, require at least one number (street number) to
    # avoid accepting bare noise like "민원시".
    if not has_province and not re.search(r"\d", s):
        return False
    return True


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

    try:
        max_tries = 2 if fast else None
        t_top = ocr_try_all(top, langs=("kor", "kor+eng"), max_tries=max_tries)["text"]
    except Exception:
        t_top = ""
    tn_top = t_top

    def _collect_front_num_candidates(front_img: Image.Image, base_text: str):
        cand = []
        dense_chunks = []
        try:
            w, h = front_img.size
            rois = {
                "pair_line":  front_img.crop((int(w * 0.40), int(h * 0.05), int(w * 0.92), int(h * 0.24))),
                "front_only": front_img.crop((int(w * 0.08), int(h * 0.70), int(w * 0.40), int(h * 0.93))),
            }
            for src_name, roi in rois.items():
                txt = _ocr_digits_line(roi)
                dense = re.sub(r"(?<=\d)\s+(?=\d)", "", txt or "")
                if dense:
                    dense_chunks.append(dense)

                for m in re.finditer(r"(?<!\d)(\d{6})\D{0,8}(\d{7})(?!\d)", dense):
                    front, back = m.group(1), m.group(2)
                    score = 0
                    if _valid_yymmdd6(front):
                        score += 10
                    if src_name == "pair_line":
                        score += 8
                    if "-" in m.group(0) or "—" in m.group(0) or "–" in m.group(0):
                        score += 2
                    cand.append(("pair", score, front, back, src_name))

                for m in re.finditer(r"(?<!\d)(\d{6})(?!\d)", dense):
                    front = m.group(1)
                    if not _valid_yymmdd6(front):
                        continue
                    score = 12 if src_name == "front_only" else 5
                    cand.append(("front", score, front, "", src_name))

                for m in re.finditer(r"(?<!\d)(\d{7})(?!\d)", dense):
                    back = m.group(1)
                    score = 6 if src_name == "pair_line" else 2
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
        cands7 = [m for m in re.finditer(r"(?<!\d)(\d{7})(?!\d)", t_dense)]
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
                if _valid_yymmdd6(front):
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
        cands = []
        try:
            w, h = img.size
            rois = [
                img.crop((int(w * 0.26), int(h * 0.28), int(w * 0.70), int(h * 0.50))),
                img.crop((int(w * 0.22), int(h * 0.24), int(w * 0.74), int(h * 0.54))),
            ]
            for idx, roi in enumerate(rois):
                g = ImageOps.grayscale(roi)
                g = ImageOps.autocontrast(g)
                g = g.resize((max(1, g.width * 2), max(1, g.height * 2)), resample=_PILImage.LANCZOS)
                try:
                    g = g.filter(ImageFilter.SHARPEN)
                except Exception:
                    pass
                for psm in (7, 6):
                    txt = _ocr(g, lang="kor", config=f"--oem 3 --psm {psm}")
                    for tok in re.findall(r"[가-힣]{2,4}", txt or ""):
                        tok = _normalize_hangul_name(tok)
                        if tok:
                            score = 10 - idx
                            if len(tok) in (3, 4):
                                score += 3
                            cands.append((score, tok))
        except Exception:
            pass

        # Parentheses pattern "(홍길동)" is the most reliable ARC name signal — return immediately.
        # Score-pool approach let ROI noise (score ≤ 13) beat a correct parentheses match (score 5).
        text_name = _extract_kor_name_strict(text_top)
        if text_name:
            return text_name

        bad = {
            "방문취", "거주따", "매확청", "사격", "재태서", "외국", "국내", "거소", "신고", "주소",
            "체류", "만기", "발급", "번호", "등록", "증명", "유효", "취업", "가능",
            # Added: card-label OCR noise patterns found in benchmark
            "소신고", "국가", "지역", "발금일", "체류자", "체류파", "제류자",
            "인천출", "수원출", "안산출", "시흥출", "화성출", "부평출", "성남출",
            "재위동", "재외등", "겁소고",
        }
        # Also discard any token that ends with "출" (city+immigration-office abbreviation)
        # or starts with "발금" (OCR garble of 발급)
        score_map = {}
        for sc, tok in cands:
            if tok in bad:
                continue
            if tok.endswith("출") or tok.startswith("발금"):
                continue
            score_map[tok] = score_map.get(tok, 0) + sc

        if not score_map:
            return ""
        return sorted(score_map.items(), key=lambda kv: (kv[1], len(kv[0]), kv[0]), reverse=True)[0][0]

    name_ko = _extract_name_from_roi(top, t_top)
    if name_ko:
        out["한글"] = name_ko

    best_text, best_sc, best_deg = "", -1, 0
    for deg in (0, 90, 270):
        im = bot.rotate(deg, expand=True) if deg else bot
        t1 = _ocr(ImageOps.grayscale(im), lang="kor", config="--oem 3 --psm 6")
        t2 = _ocr(ImageOps.grayscale(im), lang="kor", config="--oem 3 --psm 4")
        t = t1 + "\n" + t2
        sc = _kor_count(t)
        if sc > best_sc:
            best_sc, best_text, best_deg = sc, t, deg
        # fast mode: ARC cards are nearly always right-side-up on a flatbed scanner.
        # Skip 90°/270° rotations when deg=0 already yields enough Korean content.
        if fast and best_sc >= 15:
            break
    tn_bot = best_text

    expiry = _pick_labeled_date(
        tn_bot,
        r"(만기|만료|유효|until|expiry|expiration|valid\s*until|까지)",
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

    def _clean_addr_line(s: str) -> str:
        s = (s or "").replace("|", " ").replace("｜", " ")
        s = re.sub(
            r"^\s*[\(\[]?(?:19|20)?\d{1,4}[.\-/]\d{1,2}[.\-/]\d{1,2}[\)\]]?\s*[:;|.,~\-]*\s*",
            "",
            s,
        )
        s = re.sub(r"^\s*(신고일|신고월|국내거소|체류지|Address)\s*[:;|.,~\-]*\s*", "", s, flags=re.I)
        s = re.sub(r"[^가-힣0-9A-Za-z\s\-\.,#()/~]", " ", s)
        if ARC_REMOVE_PAREN:
            s = re.sub(r"\((?![^)]*(동|호|층))[^)]*\)", " ", s)
        s = re.sub(r"\s{2,}", " ", s).strip(" ,")
        m = re.search(r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)", s)
        if m:
            s = s[m.start():].strip()
        s = re.sub(r"^(서투시|서투시흘일고|시흥시흘일고|자버르지|자버영로|자9버영로)+\s*", "", s)
        s = re.sub(r"(군서로)\s*(\d+)\s*번길", r"\1\2번길", s)
        s = re.sub(r"(새말로)\s*(\d+)", r"\1 \2", s)
        s = re.sub(r"(\d)\s*호", r"\1호", s)
        s = re.sub(r"(\d)\s*동", r"\1동", s)
        s = re.sub(r"\s*,\s*", ", ", s)
        s = re.sub(r"\s{2,}", " ", s).strip(" ,")
        if not _looks_like_korean_address(s):
            return ""
        return s

    def _is_addr_stop_line(s: str) -> bool:
        s = (s or "").strip()
        return bool(re.search(r"(유효|유호|취업가능|민원안내|하이코리아|일련번호)", s))

    def _is_addr_header_line(s: str) -> bool:
        s = (s or "").strip()
        return bool(re.search(r"(국내거소|체류지|신고일|신고월)", s))

    def _is_junk_addr_line(s: str) -> bool:
        s = (s or "").strip()
        if not s:
            return True
        if _ADDR_BAN_RE.search(s):
            return True
        if re.fullmatch(r"[\(\)\.\-/#\s]+", s):
            return True
        if _kor_count(s) < 2 and len(re.sub(r"[^\d]", "", s)) >= 6:
            return True
        return False

    def _addr_score(s: str) -> float:
        s = _clean_addr_line(s)
        if _is_junk_addr_line(s):
            return -1.0
        has_lvl  = bool(re.search(r"(도|시|군|구)", s))
        has_road = bool(re.search(r"(로|길|번길|대로)", s))
        has_num  = bool(re.search(r"\d", s))
        has_unit = bool(re.search(r"(동|호|층|#\d+)", s))
        score = 0.0
        score += _kor_count(s) * 2.0
        score += 6.0 if has_lvl else 0.0
        score += 9.0 if has_road else 0.0
        score += 4.0 if has_num else 0.0
        score += 3.0 if has_unit else 0.0
        score += 6.0 if re.search(r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)", s) else 0.0
        score += min(len(s), 60) / 12.0
        if len(s) < 8:
            score -= 5.0
        if re.match(r"^\d{1,4}[.\-/]\d{1,2}[.\-/]\d{1,2}", s):
            score -= 6.0
        return score

    def _merge_addr_lines(lines: list) -> list:
        merged = []
        i = 0
        while i < len(lines):
            cur = (lines[i] or "").strip()
            nxt = (lines[i + 1] or "").strip() if i + 1 < len(lines) else ""
            combined = cur
            if nxt:
                cur_has_date = bool(re.search(r"\d{1,4}[.\-/]\d{1,2}[.\-/]\d{1,2}", cur))
                cur_has_addr = bool(re.search(r"(도|시|군|구|로|길|번길|대로)", cur))
                nxt_is_cont = bool(re.match(r"^[\s:;,.~\-]*(\(?[가-힣0-9]|길|로|번길|대로|동|호|층)", nxt))
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

    def _extract_addr_region(text: str) -> list:
        lines = [re.sub(r"\s+", " ", l).strip() for l in (text or "").splitlines() if l.strip()]
        if not lines:
            return []
        start_idx = 0
        for i, l in enumerate(lines):
            if re.search(r"(국내거소|체류지)", l):
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
            m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", raw)
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
        if not re.search(r"(도|시|군|구|로|길|번길|대로)", addr):
            return True
        return False

    addr = _best_addr_latest(tn_bot)

    if _looks_weak_address(addr):
        addr2 = _best_addr_latest(t_top + "\n" + tn_bot)
        if addr2 and not _looks_weak_address(addr2):
            addr = addr2

    if _looks_weak_address(addr):
        try:
            rot_bot = bot.rotate(best_deg, expand=True)
            rw, rh = rot_bot.size
            addr_roi = rot_bot.crop((
                int(rw * 0.18),
                int(rh * 0.34),
                int(rw * 0.92),
                int(rh * 0.80),
            ))
            addr_txt = _ocr(ImageOps.grayscale(addr_roi), lang="kor", config="--oem 3 --psm 6")
            addr_retry = _best_addr_latest(addr_txt)
            if addr_retry and not _looks_weak_address(addr_retry):
                addr = addr_retry
        except Exception:
            pass

    # For right-side-up backs (best_deg=0, new-format cards), the 국내거소 section
    # sits in the bottom ~50-98% of the card — the standard 34-80% ROI can miss it.
    if _looks_weak_address(addr) and best_deg == 0:
        try:
            rw, rh = bot.size
            addr_roi2 = bot.crop((
                int(rw * 0.08),
                int(rh * 0.50),
                int(rw * 0.96),
                int(rh * 0.98),
            ))
            addr_txt2 = _ocr(ImageOps.grayscale(addr_roi2), lang="kor", config="--oem 3 --psm 6")
            addr_retry2 = _best_addr_latest(addr_txt2)
            if addr_retry2 and not _looks_weak_address(addr_retry2):
                addr = addr_retry2
        except Exception:
            pass

    if addr and _kor_count(addr) >= 3 and len(addr) >= 6:
        out["주소"] = addr
    else:
        lines_all = [l.strip() for l in (t_top + "\n" + tn_bot).splitlines() if l.strip()]
        cand_lines = _merge_addr_lines(lines_all)
        pair_lines = []
        for i, l in enumerate(lines_all[:-1]):
            pair_lines.append((l + " " + lines_all[i + 1]).strip())
        cand_lines.extend(_merge_addr_lines(pair_lines))
        best_line = ""
        best_score = -1.0
        for l in cand_lines:
            c = _clean_addr_line(l)
            if _kor_count(c) < 3:
                continue
            if not re.search(r"(도|시|군|구|로|길|번길|대로)", c):
                continue
            sc = _addr_score(c)
            if re.search(r"^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)", c):
                sc += 4.0
            if sc > best_score:
                best_score = sc
                best_line = c
        if best_line:
            out["주소"] = best_line

    # 여권 DOB가 있으면 등록증 앞번호는 여권 기준 우선
    front_from_passport = dob_to_arc_front(passport_dob)
    if front_from_passport:
        out["등록증"] = front_from_passport
    elif out.get("등록증") and not _valid_yymmdd6(out.get("등록증", "")):
        out.pop("등록증", None)

    # Remove duplicated address text (OCR artefact: same block read twice)
    if out.get("주소"):
        out["주소"] = _dedup_address(out["주소"])

    return out
