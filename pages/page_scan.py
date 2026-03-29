# pages/page_scan.py

import os
import re
import platform
import hashlib

from datetime import datetime as _dt, timedelta as _td

import streamlit as st
from PIL import Image, ImageOps, ImageFilter, ImageStat, Image as _PILImage

try:
    import numpy as np
except Exception:
    np = None

try:
    import pytesseract
except Exception:
    pytesseract = None

# ==== Tesseract 실행 파일 경로 (로컬/서버 겸용) ====
if platform.system() == "Windows":
    # 로컬 PC (Windows)에서는 기본 설치 경로 사용
    TESSERACT_ROOT = r"C:\Program Files\Tesseract-OCR"
    TESSERACT_EXE  = os.path.join(TESSERACT_ROOT, "tesseract.exe")
else:
    # Render 같은 리눅스 서버에서는 PATH 에 있는 tesseract 사용
    # (예: apt-get install tesseract-ocr 로 설치된 바이너리)
    TESSERACT_ROOT = ""
    TESSERACT_EXE  = "tesseract"


from config import (
    SESS_CURRENT_PAGE,
    PAGE_CUSTOMER,
)

from core.customer_service import (
    upsert_customer_from_scan,
)

# -----------------------------
# 1) Tesseract 기본 유틸 (간단 버전)
# -----------------------------

def _ensure_tesseract() -> bool:
    """Tesseract 실행파일 & pytesseract 연결 확인 (로컬/서버 겸용).

    - Windows: C:\Program Files\Tesseract-OCR\tesseract.exe 사용
    - Linux/서버(Render 등): PATH 에 있는 `tesseract` 사용
    """
    import streamlit as st
    import platform
    global pytesseract

    # 1) 모듈 체크
    if pytesseract is None:
        st.error("❌ pytesseract 모듈이 없습니다. `pip install pytesseract` 후 다시 실행해주세요.")
        return False

    system = platform.system()

    # 2) OS별 실행 파일 확인
    if system == "Windows":
        if not os.path.exists(TESSERACT_EXE):
            st.error(
                "❌ Tesseract 실행파일을 찾을 수 없습니다.\n"
                f"기대 경로: {TESSERACT_EXE}"
            )
            return False
        cmd = TESSERACT_EXE
    else:
        # 리눅스/맥: PATH 에 있는 tesseract 사용
        cmd = TESSERACT_EXE  # 보통 'tesseract'

    # 3) 연결 + 버전 확인
    try:
        pytesseract.pytesseract.tesseract_cmd = cmd
        ver = pytesseract.get_tesseract_version()
        st.info(f"✅ Tesseract 연결 성공: {ver} (cmd={cmd})")
        return True
    except Exception as e:
        if system == "Windows":
            more = "Tesseract-OCR 설치 및 환경변수를 다시 확인해주세요."
        else:
            more = "Render 서버에 `tesseract-ocr` 패키지가 설치되어 있는지 확인해주세요."
        st.error(f"❌ Tesseract 실행 중 오류: {e}\n{more}")
        return False



def _ocr(img, lang="kor", config=""):
    """
    공통 OCR 래퍼.
    """
    if pytesseract is None or img is None:
        return ""
    try:
        return pytesseract.image_to_string(img, lang=lang, config=config) or ""
    except Exception:
        return ""


def _binarize(img):
    """
    단순 이진화(디버그/보조용).
    """
    g = ImageOps.grayscale(img)
    return g.point(lambda p: 255 if p > 128 else 0)


def _binarize_soft(img):
    """
    MRZ용 '부드러운' 이진화:
    - 그레이스케일
    - 약한 노이즈 제거
    - 자동 대비 조정
    """
    g = ImageOps.grayscale(img)
    g = g.filter(ImageFilter.MedianFilter(size=3))
    g = ImageOps.autocontrast(g)
    return g


def _pre(img):
    """
    MRZ용 기본 전처리:
    - 그레이스케일 + 자동 대비
    """
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g)
    return g


def ocr_try_all(
    img,
    langs=("kor", "kor+eng"),
    psms=(6, 7),
    pres=("raw", "binarize"),
    max_tries: int | None = None,
):
    """
    디버그용 ‘베스트 OCR’ 탐색 (간이 버전).
    - text 길이를 score로 사용.
    - max_tries 가 None 이면: langs×psms×pres 모든 조합 시도 (기존과 동일)
    - max_tries 가 1,2,... 이면: 앞에서부터 최대 그 횟수만 시도
      (langs/psms/pres 값 자체는 그대로 유지하고, '조합 수'만 줄인다)
    """
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
                    # 빠른 모드일 때: 앞에서부터 max_tries개 조합만 시도
                    return best

    return best



def open_image_safe(uploaded_file):
    """
    업로드된 파일을 안전하게 이미지(RGB)로 여는 함수.
    - 이미지(jpg/png/webp 등): 그대로 PIL로 로드
    - PDF: 1페이지를 렌더링하여 PIL 이미지로 변환
    """
    if uploaded_file is None:
        return None

    name = getattr(uploaded_file, "name", "") or ""
    ext = os.path.splitext(name.lower())[1]

    # PDF 처리: 1페이지 렌더
    if ext == ".pdf":
        try:
            import fitz  # PyMuPDF
        except Exception:
            return None

        try:
            pdf_bytes = uploaded_file.getvalue()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            if doc.page_count < 1:
                return None
            page = doc[0]
            # 속도 유지: 과도한 고해상도 금지 (zoom 2.0 정도면 MRZ 충분)
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            return img
        except Exception:
            return None

    # 일반 이미지
    try:
        return ImageOps.exif_transpose(Image.open(uploaded_file)).convert("RGB")
    except Exception:
        return None


def _detect_card_boxes_on_white_bg(img):
    """
    흰 배경 위에 배치된 등록증 카드(앞/뒤) 1~2개를 빠르게 찾는다.
    - 속도 유지를 위해 축소본에서만 탐지
    - 실패하면 빈 리스트 반환
    반환: [(x1,y1,x2,y2), ...]  (원본 기준, 위에서 아래 순)
    """
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

        # 약한 잡음을 줄이기 위해 아주 가벼운 블러 후 threshold
        gray = work.convert("L").filter(ImageFilter.MedianFilter(size=3))
        arr = np.asarray(gray)
        # 흰 배경에서 벗어난 픽셀 마스크
        mask = arr < 242
        if mask.mean() < 0.002:
            return []

        row_ratio = mask.mean(axis=1)
        thr_row = max(0.01, row_ratio.max() * 0.12)
        ys = np.where(row_ratio > thr_row)[0]
        if len(ys) == 0:
            return []

        # 연속 row band 생성
        bands = []
        start = ys[0]
        prev = ys[0]
        for y in ys[1:]:
            if y - prev > max(8, sh // 80):
                bands.append((start, prev))
                start = y
            prev = y
        bands.append((start, prev))

        # 너무 작은 band 제거
        min_band_h = max(30, sh // 30)
        bands = [b for b in bands if (b[1] - b[0] + 1) >= min_band_h]
        if not bands:
            return []

        boxes = []
        for y1, y2 in bands[:4]:
            band = mask[y1:y2+1, :]
            col_ratio = band.mean(axis=0)
            thr_col = max(0.01, col_ratio.max() * 0.15)
            xs = np.where(col_ratio > thr_col)[0]
            if len(xs) == 0:
                continue
            x1, x2 = int(xs[0]), int(xs[-1])

            # margin 추가
            mx = max(12, int((x2 - x1 + 1) * 0.04))
            my = max(12, int((y2 - y1 + 1) * 0.08))
            x1 = max(0, x1 - mx)
            x2 = min(sw - 1, x2 + mx)
            y1m = max(0, y1 - my)
            y2m = min(sh - 1, y2 + my)

            bw = x2 - x1 + 1
            bh = y2m - y1m + 1
            area_ratio = (bw * bh) / float(sw * sh)
            # 카드처럼 생긴 충분히 큰 사각형만 채택
            if area_ratio < 0.01:
                continue
            if bw < sw * 0.12 or bh < sh * 0.06:
                continue

            # 원본 좌표로 환산
            rx1 = int(round(x1 / scale))
            ry1 = int(round(y1m / scale))
            rx2 = int(round((x2 + 1) / scale))
            ry2 = int(round((y2m + 1) / scale))
            boxes.append((rx1, ry1, rx2, ry2))

        boxes = sorted(boxes, key=lambda b: (b[1], b[0]))

        # 겹치는 박스 정리
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
                # 더 큰 박스 유지
                if area2 > area1:
                    dedup[-1] = b
            else:
                dedup.append(b)

        return dedup[:2]
    except Exception:
        return []


def _split_arc_front_back(img):
    """
    등록증 스캔본에서 앞/뒤 카드 이미지를 분리한다.
    - 카드 2개가 탐지되면: 위 카드=front, 아래 카드=back
    - 아니면 기존처럼 상/하 절반 분리
    """
    w, h = img.size
    boxes = _detect_card_boxes_on_white_bg(img)
    if len(boxes) >= 2:
        boxes = sorted(boxes[:2], key=lambda b: b[1])
        front = img.crop(boxes[0])
        back = img.crop(boxes[1])
        return front, back

    return img.crop((0, 0, w, int(h * 0.5))), img.crop((0, int(h * 0.5), w, h))


# -----------------------------
# 2) 스캔용 OCR 유틸 (기존 코드 그대로)
# -----------------------------

# ── 속도/옵션 ─────────────────────────────────────────────
ARC_REMOVE_PAREN = True   # 주소에서 (신길동) 같은 괄호표기 제거
ARC_FAST_ONLY    = True   # 빠른 모드(필요 최소 조합만 시도)

# ── MRZ(여권) 보조 ────────────────────────────────────────
_MRZ_CLEAN_TRANS = str.maketrans({'«':'<','‹':'<','>':'<',' ':'', '—':'-', '–':'-','£':'<','€':'<','¢':'<'})

def _mrz_clean(s: str) -> str:
    """MRZ 라인 클린(패딩 금지)."""
    raw = (s or '').strip().translate(_MRZ_CLEAN_TRANS).upper()
    raw = re.sub(r'[^A-Z0-9<]', '', raw)
    return raw

def _mrz_pad44(raw: str) -> str:
    """TD3 표준 길이(44)로 절단/패딩."""
    raw = raw or ""
    if len(raw) < 44:
        raw = raw + ('<' * (44 - len(raw)))
    elif len(raw) > 44:
        raw = raw[:44]
    return raw

def _normalize_mrz_line(s: str) -> str:
    """호환용: 클린 후 44자 패딩."""
    return _mrz_pad44(_mrz_clean(s))


def _fix_td3_line2_fields(L2: str) -> str:
    """
    TD3 line2(44자)에서 OCR 흔들림/자리밀림을 최대한 복구.
    - 숫자/문자 혼동 보정 (0/O, 1/I, 2/Z, 5/S, 6/G, 8/B)
    - 성별(N/H 등) 보정
    - ✅ 가장 중요: 체크디짓 누락 등으로 국적 필드가 한 칸 밀리는 케이스 보정
    """
    if not L2:
        return L2
    L2 = _mrz_pad44(_mrz_clean(L2))  # 44자 클린/패딩(패딩 전 조작 금지)

    map_alpha = {'0':'O','1':'I','2':'Z','5':'S','6':'G','8':'B'}
    map_digit = {'O':'0','Q':'0','D':'0','I':'1','L':'1','Z':'2','S':'5','G':'6','B':'8'}

    def fix_nat(nat3: str) -> str:
        nat3 = ''.join(map_alpha.get(c, c) for c in nat3)
        nat3 = re.sub(r'[^A-Z]', '', nat3)
        return nat3 if len(nat3) == 3 else ""

    # -------------------------
    # 1) ✅ 자리 밀림(shift) 보정
    # -------------------------
    # 정상이라면:
    #  - doc: 0:9
    #  - doc_cd: 9 (digit)
    #  - nat: 10:13 (AAA)
    doc = L2[0:9]
    doc_cd = L2[9]
    nat = L2[10:13]

    nat_ok = bool(re.fullmatch(r'[A-Z]{3}', fix_nat(nat)))
    doc_cd_is_digit = doc_cd.isdigit()

    # 케이스 A: 체크디짓(9번)이 숫자가 아니라 문자고, 그 문자 포함해서 3글자 국적이 만들어지는 경우
    # 예) 135655635VNM...  -> doc_cd='V', nat='NM0'  (실제로는 doc_cd+nat[:2] = 'VNM')
    if (not doc_cd_is_digit) and (not nat_ok):
        nat_shift = fix_nat((doc_cd + nat[:2]))
        if nat_shift:
            # doc_cd를 '<'로 두고 국적을 복구
            L2 = L2[:9] + '<' + nat_shift + L2[12:]  # 9번부터 재구성

    # 케이스 B: 국적이 1칸 오른쪽으로 밀린 경우(드물지만 있음)
    # 예) doc_cd는 숫자인데 nat가 깨지고, nat를 (L2[11:14])로 읽으면 정상인 경우
    else:
        nat2 = fix_nat(L2[11:14])
        if doc_cd_is_digit and (not nat_ok) and nat2:
            # 10번을 '<'로 두고 nat2를 11~13에 맞춘 형태로 강제
            L2 = L2[:10] + '<' + nat2 + L2[14:]

    # -------------------------
    # 2) 국적(10-12) 숫자→문자 혼동 보정 (자리 보정 이후 다시)
    # -------------------------
    nat = fix_nat(L2[10:13])
    if nat:
        L2 = L2[:10] + nat + L2[13:]

    # -------------------------
    # 3) 생년/만기 숫자 자리 문자→숫자 보정(필요 시 _mrz_digitize가 하긴 하지만, 여기서도 한번)
    # -------------------------
    birth = ''.join(map_digit.get(c, c) for c in L2[13:19])
    exp   = ''.join(map_digit.get(c, c) for c in L2[21:27])
    L2 = L2[:13] + birth + L2[19:21] + exp + L2[27:]

    # -------------------------
    # 4) 성별(20) 보정
    # -------------------------
    sx = L2[20]
    if sx not in 'MF<':
        sx = 'M' if sx in ('N','H') else '<'
        L2 = L2[:20] + sx + L2[21:]

    return L2




def _is_td3_candidate(L1: str, L2: str) -> bool:
    """TD3 MRZ 후보 판정(전 국가 공통/속도 우선)."""
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

def find_mrz_pair_from_text(text: str):
    lines = [l for l in (text or '').splitlines() if l.strip()]
    norms = [(i, _normalize_mrz_line(l)) for i, l in enumerate(lines)]
    best = None
    for (i, L1) in norms:
        if i+1 < len(norms):
            _, L2 = norms[i+1]
            if _is_td3_candidate(L1, L2):
                score = (L1+L2).count('<')
                if not best or score > best[0]:
                    best = (score, L1, L2)
    return (best[1], best[2]) if best else (None, None)

def _minus_years(d: _dt.date, years: int) -> _dt.date:
    y = d.year - years
    import calendar
    endday = calendar.monthrange(y, d.month)[1]
    return _dt(y, d.month, min(d.day, endday)).date()

# === PATCH: MRZ check digit & scoring (TD3) =========================
_MRZ_FIX_DIGIT_MAP = {
    'O': '0', 'Q': '0', 'D': '0',
    'I': '1', 'L': '1',
    'Z': '2',
    'S': '5',
    'G': '6',
    'B': '8',
}

def _mrz_char_value(ch: str) -> int:
    if ch == '<':
        return 0
    if '0' <= ch <= '9':
        return ord(ch) - ord('0')
    if 'A' <= ch <= 'Z':
        return ord(ch) - ord('A') + 10
    return 0

def _mrz_check_digit(data: str) -> str:
    weights = [7, 3, 1]
    s = 0
    for i, ch in enumerate(data):
        s += _mrz_char_value(ch) * weights[i % 3]
    return str(s % 10)

def _mrz_digitize(s: str) -> str:
    # OCR이 숫자 자리에 O/I/S 등을 뱉는 경우를 제한적으로 교정
    return ''.join(_MRZ_FIX_DIGIT_MAP.get(c, c) for c in s)

def _realign_l1_by_nat(L1_raw: str, nat3: str) -> str:
    """L1에서 국적코드(nat3)를 이용해 발급국 위치(2:5)를 재정렬.
    예: P<POCHNBI<<...  -> P<CHNBI<<...
    - 속도: 문자열 조작만(추가 OCR 없음)
    """
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
    """
    TD3 2줄 MRZ의 '그럴듯함' 점수.
    - 패턴 만족(기본) + 체크디짓 일치 개수로 스코어링
    """
    if not _is_td3_candidate(L1, L2):
        return -1

    L1 = _normalize_mrz_line(L1)
    L2 = _fix_td3_line2_fields(L2)

    # TD3 line2 positions (0-index):
    # 0-8 doc number, 9 cd
    # 13-18 birth, 19 cd
    # 21-26 expiry, 27 cd
    # 28-41 optional, 42 cd
    # 43 composite cd
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

    # 개별 체크디짓
    if doc_cd.isdigit() and _mrz_check_digit(doc) == doc_cd: score += 2
    if birth_cd.isdigit() and _mrz_check_digit(birth) == birth_cd: score += 2
    if exp_cd.isdigit() and _mrz_check_digit(exp) == exp_cd: score += 2
    if opt_cd.isdigit() and _mrz_check_digit(opt) == opt_cd: score += 1

    # --- 개별 체크디짓 점수 계산 직후에 추가 ---
    matches = 0
    if doc_cd.isdigit() and _mrz_check_digit(doc) == doc_cd: matches += 1
    if birth_cd.isdigit() and _mrz_check_digit(birth) == birth_cd: matches += 1
    if exp_cd.isdigit() and _mrz_check_digit(exp) == exp_cd: matches += 1

    # ✅ 최소 2개 이상 맞아야만 "진짜 후보"로 인정 (가짜 MRZ 대량 차단)
    if matches < 2:
        return -1

    # Composite check digit: doc+cd + birth+cd + exp+cd + opt+cd
    comp_data = L2[0:10] + _mrz_digitize(L2[13:20]) + _mrz_digitize(L2[21:43])
    if comp_cd.isdigit() and _mrz_check_digit(comp_data) == comp_cd: score += 3

    # '<' 밀도 가산 (MRZ 특징)
    score += min((L1 + L2).count('<') // 5, 3)

    return score

def find_best_mrz_pair_from_text(text: str):
    lines = [l for l in (text or '').splitlines() if l.strip()]
    norms = [_normalize_mrz_line(l) for l in lines]

    best = (None, None, -1)  # L1, L2, score
    n = len(norms)

    # ✅ 연속만 보지 말고, i 다음 1~2줄 떨어진 후보까지 검사
    for i in range(n):
        for j in range(i + 1, min(n, i + 3)):  # i+1, i+2
            L1, L2 = norms[i], norms[j]
            sc = _mrz_score_td3(L1, L2)
            if sc > best[2]:
                best = (L1, L2, sc)

    return best

# ===================================================================

def _parse_mrz_pair(L1: str, L2: str) -> dict:
    out = {}

    # None 방지 + 정규화
    L1 = _normalize_mrz_line(L1) if L1 else ""
    L2 = _fix_td3_line2_fields(L2) if L2 else ""
    nat3 = _mrz_clean(L2)[10:13] if L2 else ""
    if nat3 and re.fullmatch(r"[A-Z]{3}", nat3):
        L1_raw = _realign_l1_by_nat(L1, nat3)
        if L1_raw:
            L1 = _mrz_pad44(L1_raw)

    # 🔹 이름 파싱(사용자 규칙):
    #   - TD3 1줄은: P< + (발급국 3) + SURNAME<<GIVEN...
    #   - 성: L1 5번째부터 '<<' 전까지
    #   - 명: '<<' 이후
    #   - 중간의 '<' 하나는 공백
    #
    # ✅ 현실 보정(중요): OCR이 발급국 코드에서 1글자를 누락하는 경우가 있어
    #   예) P<HN... (원래 CHN) 처럼 2글자만 남으면 성 앞에 'HN'이 붙는 현상이 생김.
    #   이때는 L2의 국적(10~13)을 이용해 1글자를 보정한다.
    # --- TD3 line1 이름 파싱(전 국가 공통) ---
    # 사용자 원칙:
    #  - TD3 line1: P? + (발급국 3) + SURNAME<<GIVEN...
    #  - 성: L1 5번째부터 '<<' 전까지
    #  - 명: '<<' 이후
    #  - 중간의 '<' 하나는 공백

    if L1 and len(L1) >= 6 and L1[0] == "P":
        nat = re.sub(r"[^A-Z]", "", L2[10:13] if len(L2) >= 13 else "")
        doc2 = L1[:2] if len(L1) >= 2 else "P<"
        rem = L1[2:]

        # ✅ 발급국(3글자) 정렬/보정 (nat 기준)
        #  - 예: P<POCHNBI<<...  -> P<CHNBI<<...
        if nat and len(nat) == 3:
            head = rem[:10]
            pos = head.find(nat)
            if pos > 0:
                rem = nat + rem[pos + 3:]
            elif rem.startswith(nat[1:]) and not rem.startswith(nat):
                # 1글자 누락 (예: CHN → HN...)
                rem = nat[0] + rem
            elif not re.fullmatch(r"[A-Z]{3}", rem[:3] or ""):
                rem = nat + rem[3:]

        L1_fix = doc2 + rem

        name_block = L1_fix[5:] if len(L1_fix) > 5 else ""

        sep = "<<" if "<<" in name_block else ("<" if "<" in name_block else None)
        if sep:
            sur, given = name_block.split(sep, 1)
            sur = sur.replace("<", " ").strip()
            given = given.replace("<", " ").strip()

            # ✅ 안전검증: 숫자 섞이면 이름으로 인정하지 않음(노이즈 차단)
            if sur and not re.search(r"\d", sur):
                out["성"] = re.sub(r"\s+", " ", sur).strip()
            if given and not re.search(r"\d", given):
                out["명"] = re.sub(r"\s+", " ", given).strip()


    # 여권, 국적, 생년, 성별, 만기 (기존 로직 그대로)
    pn = re.sub(r"[^A-Z0-9]", "", L2[0:9])
    if pn:
        out["여권"] = pn

    nat = re.sub(r"[^A-Z]", "", L2[10:13])
    if nat:
        out["국가"] = nat

    b = re.sub(r"[^0-9]", "", L2[13:19])
    if len(b) == 6:
        yy, mm, dd = int(b[:2]), int(b[2:4]), int(b[4:6])
        yy += 2000 if yy < 80 else 1900
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

    # 👉 발급일: 10년짜리 기준 역산 (+1일) 그대로 유지
    if out.get("만기"):
        try:
            exp = _dt.strptime(out["만기"], "%Y-%m-%d").date()
            issued = _minus_years(exp, 10) + _td(days=1)
            out["발급"] = issued.strftime("%Y-%m-%d")
        except Exception:
            pass

    return out


# ── MRZ(여권) 고정밀/고속 추출 유틸 ────────────────────────


def _edge_density(pil_img: Image.Image) -> float:
    """빠른 엣지(텍스트) 밀도 스코어. (numpy 없이)"""
    if pil_img is None:
        return 0.0
    g = ImageOps.grayscale(pil_img)
    # 속도 위해 축소
    g = g.copy()
    g.thumbnail((320, 320))
    e = g.filter(ImageFilter.FIND_EDGES)
    # 픽셀 중 임계값 초과 비율
    data = list(e.getdata())
    if not data:
        return 0.0
    thr = 40
    cnt = 0
    for v in data:
        if v > thr:
            cnt += 1
    return cnt / float(len(data))


def _crop_to_content_bbox_edges(img: Image.Image, pad: int = 20) -> Image.Image:
    """
    여백이 큰 스캔본에서 '내용 영역'만 남기기 (속도형).
    실패하면 원본 반환.
    """
    if img is None:
        return img

    w, h = img.size
    # 너무 크면 bbox 탐색용으로만 축소
    work = img.copy()
    scale = 1.0
    if max(w, h) > 900:
        scale = 900.0 / float(max(w, h))
        work = work.resize((int(w * scale), int(h * scale)), resample=_PILImage.BILINEAR)

    g = ImageOps.grayscale(work).filter(ImageFilter.FIND_EDGES)
    # 임계값 초과 좌표 찾기
    px = g.load()
    ww, hh = g.size
    thr = 35
    minx, miny = ww, hh
    maxx, maxy = 0, 0
    found = False

    # 샘플링 간격(속도)
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

    # 너무 작은 bbox면 의미 없음
    if (maxx - minx) < ww * 0.08 or (maxy - miny) < hh * 0.08:
        return img

    # 원본 좌표로 환산
    inv = 1.0 / scale
    x0 = int(minx * inv) - pad
    y0 = int(miny * inv) - pad
    x1 = int(maxx * inv) + pad
    y1 = int(maxy * inv) + pad

    x0 = max(0, x0); y0 = max(0, y0)
    x1 = min(w, x1); y1 = min(h, y1)
    return img.crop((x0, y0, x1, y1))


def _split_regions(img: Image.Image):
    """상/하/좌/우/전체 후보 생성"""
    w, h = img.size
    top = img.crop((0, 0, w, h // 2))
    bottom = img.crop((0, h // 2, w, h))
    left = img.crop((0, 0, w // 2, h))
    right = img.crop((w // 2, 0, w, h))
    return {
        "full": img,
        "top": top,
        "bottom": bottom,
        "left": left,
        "right": right,
    }


def _crop_mrz_band(img: Image.Image, band_ratio: float = 0.42) -> Image.Image:
    """MRZ는 여권 하단에 위치하므로, 후보 영역의 '하단 띠'만 잘라 OCR"""
    w, h = img.size
    y0 = int(h * (1.0 - band_ratio))
    return img.crop((0, y0, w, h))


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
        # 구버전 pytesseract timeout 미지원
        try:
            return pytesseract.image_to_string(img, lang=lang, config=config) or ""
        except Exception:
            return ""
    except Exception:
        return ""


def _ocr_mrz(img: Image.Image) -> str:
    cfg = "--oem 1 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
    # ocrb 우선
    for lang in ("ocrb", "eng+ocrb", "eng"):
        txt = _tess_string(img, lang=lang, config=cfg, timeout_s=2)
        if txt and len(txt.strip()) >= 10:
            return txt
    return ""


def _extract_mrz_pair(raw: str):
    """
    raw OCR 결과에서 '<'가 충분하고 길이가 긴 라인 2개를 MRZ 후보로 선택.
    (엄격 TD3 검증은 기존 _is_td3_candidate 재사용)
    """
    if not raw:
        return (None, None)

    lines = []
    for ln in raw.splitlines():
        s = (ln or "").strip().replace(" ", "")
        s = re.sub(r"[^A-Z0-9<]", "", s.upper())
        if len(s) >= 25 and "<" in s:
            lines.append(s)

    if len(lines) < 2:
        return (None, None)

    # 기존 정규화/검증 사용
    norms = [_normalize_mrz_line(l) for l in lines]
    best = None
    for i in range(len(norms) - 1):
        L1, L2 = norms[i], norms[i + 1]
        if _is_td3_candidate(L1, L2):
            sc = (L1 + L2).count("<")
            if best is None or sc > best[0]:
                best = (sc, L1, L2)

    if best:
        return (best[1], best[2])

    # fallback: '<' 많은 상위 2개
    scored = sorted(((n.count("<") + len(n), n) for n in norms), reverse=True)
    return (scored[0][1], scored[1][1])


def _crop_to_content_bbox_thresh(img: Image.Image, pad_ratio: float = 0.03) -> Image.Image:
    """
    OpenCV 없이 '대충 가장 큰 내용 사각형'을 잡기 위한 빠른 bbox crop.
    - 하얀 여백이 큰 스캔(여권이 상단/하단에 치우침)에서 효과 큼.
    """
    if img is None:
        return img

    try:
        g = ImageOps.grayscale(img)
        g = ImageOps.autocontrast(g)
        # 밝은 배경(거의 흰색)을 제외하고 내용이 있는 픽셀만 남김
        # threshold는 너무 빡세면 글자가 날아가므로 245 정도로 완만하게
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
    # 1) 엣지 기반 먼저
    a = _crop_to_content_bbox_edges(img, pad=20)
    # 2) 엣지 기반이 의미 없으면(thumbnail 비슷하게 그대로면) threshold 기반
    if a.size == img.size:
        return _crop_to_content_bbox_thresh(img, pad_ratio=0.03)
    return a



def _mrz_windows_by_edge_density(im: Image.Image, top_k: int = 3):
    """
    빠른 MRZ 후보 밴드 탐색:
    - 전체 이미지를 OpenCV 없이(PIL만) 간단한 edge density로 스캔
    - 가장 '글자/선'이 조밀한 가로 밴드(top_k)를 반환
    반환: [(y0, y1), ...] (원본 좌표)
    """
    try:
        w, h = im.size
        if w < 200 or h < 200:
            return []

        # 여권 스캔이 위/아래로 치우친 경우를 고려해, 상단 10%~하단까지 탐색
        y_base = int(h * 0.10)
        roi = im.crop((0, y_base, w, h))
        roi_w0, roi_h0 = roi.size

        # 속도 보호: ROI를 가로 700px 수준으로 축소
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
            # ✅ 하단 클램프 때문에 window가 잘려 MRZ 2줄 중 1줄만 잡히는 문제 방지
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
    """MRZ 후보 밴드를 (label, band_img)로 순회.
    1) edge-density 기반 후보(top 3)
    2) 고정 하단 밴드들(여권 MRZ 2줄이 아주 아래쪽에 붙는 케이스 강화)
    """
    w, h = im.size

    wins = _mrz_windows_by_edge_density(im, top_k=3)
    for i, (y0, y1) in enumerate(wins, start=1):
        label = f"edge#{i} {int(100*y0/h)}-{int(100*y1/h)}%"
        yield label, im.crop((0, y0, w, y1))

    # ✅ 고정 밴드: 너무 넓으면 MRZ가 묻히고, 너무 좁으면 2줄 중 1줄만 잡힐 수 있어 여러 폭으로 순회
    for pct in (55, 35, 25, 20, 18):
        y0 = int(h * (1 - pct / 100.0))
        yield f"{pct}%", im.crop((0, y0, w, h))


def parse_passport(img):
    """
    여권 MRZ(TD3) 전용 파서.
    - 변수가 많은 스캔본(회전/여백/치우침/가로스캔)을 견디도록:
      1) EXIF 보정
      2) 내용 bbox로 빠르게 crop(여백 제거)
      3) 회전(0/180/90/270) 후보에서 MRZ 후보 밴드만 OCR (edge 기반 + fallback 밴드)
      4) ICAO 체크디짓 기반 스코어링으로 최적 MRZ 선택
    """
    if img is None:
        return {}

    # 디버그 버퍼 초기화
    if "passport_mrz_debug" not in st.session_state:
        st.session_state["passport_mrz_debug"] = []
    else:
        st.session_state["passport_mrz_debug"].clear()

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

    # 2) 여백 제거(“여권이 위/아래 50%에만 들어간 스캔” 대응)
    try:
        img = _crop_to_content_bbox(img, pad_ratio=0.03)  # 새 버전 호환
    except TypeError:
        img = _crop_to_content_bbox(img)

    def _ocr_mrz_band(band_img: Image.Image) -> str:
        """
        MRZ 전용 OCR:
        - ROI를 가볍게 전처리(_prep_mrz) 후 whitelist 적용
        - timeout으로 '멈춤' 방지
        """
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

    # ✅ 회전 순서 최적화: 0 → 90 → 270 → 180
    rotations = (0, 90, 270, 180)

    best_L1, best_L2, best_score = None, None, -1
    best_meta = {}

    for rot in rotations:
        imr = img.rotate(rot, expand=True) if rot else img
        joined = ""

        # ✅ 1) edge 후보 먼저
        bands = list(_mrz_windows_by_edge_density(imr, top_k=3))
        band_iters = []
        w, h = imr.size
        for i, (y0, y1) in enumerate(bands, start=1):
            label = f"edge#{i} {int(100*y0/h)}-{int(100*y1/h)}%"
            band_iters.append((label, imr.crop((0, y0, w, y1))))

        # ✅ 2) edge에서 아무것도 못 읽을 때만 fallback 밴드 추가
        # (초기엔 fallback을 붙이지 않아서 호출 수를 줄임)
        fallback_added = False

        for label, band in band_iters:
            # ✅ psm 6만 먼저 (빠르게)
            txt = _tess_string(
                _prep_mrz(band),
                lang="ocrb+eng",
                config="--oem 1 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ<0123456789",
                timeout_s=1
            )

            # psm6 실패 시에만 psm7 시도
            if not (txt or "").strip():
                txt = _tess_string(
                    _prep_mrz(band),
                    lang="ocrb+eng",
                    config="--oem 1 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ<0123456789",
                    timeout_s=1
                )

            st.session_state["passport_mrz_debug"].append({
                "rot": rot,
                "band": label,
                "text_head": (txt or "")[:120],
            })

            if (txt or "").strip():
                joined += "\n" + txt

            L1, L2, sc = find_best_mrz_pair_from_text(joined)
            if sc > best_score:
                best_score = sc
                best_L1, best_L2 = L1, L2
                best_meta = {"rot": rot, "band": label, "score": sc, "L1": L1, "L2": L2}

            if best_score >= 7:
                break

        # edge에서 실패했고, 아직 fallback을 안 붙였으면 여기서 한 번만 수행
        if best_score < 7 and not fallback_added:
            fallback_added = True
            for label, band in _iter_mrz_candidate_bands(imr):
                if label.startswith("edge#"):
                    continue  # 이미 edge는 했음
                txt = _tess_string(
                    _prep_mrz(band),
                    lang="ocrb+eng",
                    config="--oem 1 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ<0123456789",
                    timeout_s=1
                )
                st.session_state["passport_mrz_debug"].append({
                    "rot": rot,
                    "band": label,
                    "text_head": (txt or "")[:120],
                })
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

    # ✅ render에서 st.write로 보고 싶다 했으니, 여기서 세션에 저장
    st.session_state["passport_mrz_best"] = best_meta

    if not best_L1 or not best_L2:
        return {}
    
    out = _parse_mrz_pair(best_L1, best_L2)
    return {
        "성":       out.get("성", ""),
        "명":       out.get("명", ""),
        "성별":     out.get("성별", ""),
        "국가":     out.get("국가", ""),
        "국적":     out.get("국가", ""),  # 호환용
        "여권":     out.get("여권", ""),
        "발급":     out.get("발급", ""),
        "만기":     out.get("만기", ""),
        "생년월일": out.get("생년월일", ""),
    }

# 등록증(ARC) 관련 보조 정규식/함수들 (사용하던 버전 그대로)
_ADDR_BAN_RE = re.compile(
    r'(유효|취업|가능|확인|민원|국번없이|콜센터|call\s*center|www|http|1345|출입국|immigration|안내|관할|관계자|외|금지)',
    re.I
)
# ── 이름 추출 보조 ─────────────────────────

_NAME_BAN = {
    "외국", "국내", "거소", "신고", "증", "재외동포", "재외동","외동포",
    "재외", "동포", "국적", "주소", "발급", "발급일", "발급일자",
    "만기", "체류", "자격", "종류", "성명", "이름", "사력"
}

def _extract_kor_name_strict(text: str) -> str:
    """
    등록증 앞면 전체 텍스트에서 한글 이름 2~3글자를 최대한 안전하게 추출
    0순위: 괄호 안 한글 이름 2~4글자  (예: LI FENZI(이분자))
    1순위: '성명' / '이름' 뒤의 2~3글자
    2순위: 전체에서 2~3글자 토큰 중 라벨 근처에 있는 것
    """
    if not text:
        return ""

    # 0) 괄호 안 한글 이름 예: LI FENZI(이분자)
    m = re.search(r"\(([가-힣]{2,4})\)", text)
    if m:
        cand = m.group(1)
        if cand not in _NAME_BAN:
            return cand

    # 1) '성명: 이분' / '성명 이분' 패턴
    m = re.search(r"(성명|이름)\s*[:\-]?\s*([가-힣]{2,3})", text)
    if m:
        cand = m.group(2)
        if cand not in _NAME_BAN:
            return cand

    # 2) 전체에서 한글 2~3글자 토큰 후보
    toks = re.findall(r"[가-힣]{2,3}", text)
    toks = [t for t in toks if t not in _NAME_BAN]
    if not toks:
        return ""

    # '성명' / '이름' 라벨 위치 기준으로 가장 가까운 토큰 선택
    label_pos_list = [p for p in (text.find("성명"), text.find("이름")) if p != -1]
    label_pos = min(label_pos_list) if label_pos_list else len(text) // 2

    best, best_d = "", 10**9
    for t in toks:
        p = text.find(t)
        if p == -1:
            continue
        d = abs(p - label_pos)
        if d < best_d:
            best, best_d = t, d

    return best

def _kor_count(s: str) -> int:
    return len(re.findall(r'[가-힣]', s or ''))


def _valid_yymmdd6(s: str) -> bool:
    s = re.sub(r'\D', '', s or '')
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
        t1 = _ocr(proc, lang='eng', config='--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789-')
        t2 = _ocr(proc, lang='eng', config='--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789-')
        return (t1 or '') + '\n' + (t2 or '')
    except Exception:
        return ''


def dob_to_arc_front(dob: str) -> str:
    s = re.sub(r'\D', '', dob or '')
    if len(s) != 8:
        return ''
    yyyy, mm, dd = s[:4], s[4:6], s[6:8]
    try:
        if not (1 <= int(mm) <= 12 and 1 <= int(dd) <= 31):
            return ''
    except Exception:
        return ''
    return yyyy[2:] + mm + dd


def _normalize_hangul_name(s: str) -> str:
    s = re.sub(r'[^가-힣]', '', s or '')
    return s if 2 <= len(s) <= 4 else ''


def _looks_like_korean_address(s: str) -> bool:
    """
    Weak gate: used inside _clean_addr_line to filter obvious non-addresses.
    Requires a city/province abbreviation PLUS at least one word-ending
    admin-unit token (시/군/구) or road-name token (대로/번길/로/길).
    Mere presence of the syllable inside a longer word is not enough.
    """
    s = (s or '').strip()
    if not s:
        return False
    if not re.search(r'(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)', s):
        return False
    has_admin = bool(re.search(r'[가-힣]{1,6}[시군구](?:\s|$|\d)', s))
    has_road  = bool(re.search(r'[가-힣]{2,8}(?:대로|번길|로|길)(?:\s|$|\d)', s))
    return has_admin or has_road


# Strong gate: BOTH a plausible admin-unit token AND a road-name token must be present.
# Used at the final out["주소"] save point to reject garbage OCR candidates.
_ADDR_ADMIN_TOKEN_RE = re.compile(r'[가-힣]{1,6}[시군구](?:\s|$|\d)')
_ADDR_ROAD_TOKEN_RE  = re.compile(r'[가-힣]{2,8}(?:대로|번길|로|길)(?:\s|$|\d)')


def _is_valid_address_candidate(s: str) -> bool:
    """
    Strong acceptance gate for the final out["주소"] assignment.
    Rejects candidates that merely contain stray syllables.
    """
    s = (s or '').strip()
    if not s or _kor_count(s) < 5 or len(s) < 8:
        return False
    if not re.search(r'(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)', s):
        return False
    return bool(_ADDR_ADMIN_TOKEN_RE.search(s)) and bool(_ADDR_ROAD_TOKEN_RE.search(s))


# ──────────────────────────────────────────────────────────────────────────────
# 계층적 행정구역 정규화 (Level1 시도 / Level2 시군구)
# ──────────────────────────────────────────────────────────────────────────────

LEVEL1_REGIONS = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시",
    "광주광역시", "대전광역시", "울산광역시", "세종특별자치시",
    "경기도", "강원특별자치도", "충청북도", "충청남도",
    "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도",
]

# OCR 오인식 → 정규 시도명 보정 (보수적, 자주 나타나는 오류만)
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

# 상위 시도 확정 후에만 적용하는 Level2 OCR 오인식 보정
LEVEL2_ALIASES_BY_PARENT: dict[str, dict[str, str]] = {
    "서울특별시": {
        "강남기": "강남구", "강남가": "강남구",
        "서초기": "서초구", "마프구": "마포구",
        "은평기": "은평구",
    },
    "경기도": {
        "시흥기": "시흥시", "수원기": "수원시",
        "부천기": "부천시", "안산기": "안산시",
    },
}


def _normalize_level1_region(text: str) -> tuple[str, float]:
    """Level1 시도명 탐색. 반환: (정규화_시도명, 신뢰도 0~1)"""
    for lvl1 in LEVEL1_REGIONS:
        if lvl1 in text:
            return lvl1, 1.0
    for alias, canonical in LEVEL1_ALIASES.items():
        if alias in text:
            return canonical, 0.8
    short_map = {
        "서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시",
        "인천": "인천광역시", "광주": "광주광역시", "대전": "대전광역시",
        "울산": "울산광역시", "세종": "세종특별자치시", "경기": "경기도",
        "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
        "전북": "전북특별자치도", "전남": "전라남도",
        "경북": "경상북도", "경남": "경상남도", "제주": "제주특별자치도",
    }
    for short, canonical in short_map.items():
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
    추출된 주소 문자열에 Level1/Level2 계층 정규화 적용.
    신뢰도가 낮으면 원본 반환 (안전 최우선).
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


# ──────────────────────────────────────────────────────────────────────────────
# 한글 이름 성씨 우선 정규화
# ──────────────────────────────────────────────────────────────────────────────

KOREAN_SURNAMES_1 = frozenset([
    "김","이","박","최","정","강","조","윤","장","임",
    "한","오","서","신","권","황","안","송","전","홍",
    "유","고","문","양","손","배","백","허","남","심",
    "노","하","곽","성","차","주","우","구","민","진",
    "지","엄","채","원","천","방","공","현","함","변",
    "염","여","추","도","소","석","선","설","마","길",
    "연","위","표","명","기","반","왕","금","옥","육",
    "인","맹","제","모",
])

KOREAN_SURNAMES_2 = frozenset([
    "남궁","황보","제갈","사공","선우","서문","독고","동방","어금","망절",
])

KOREAN_NAME_BAN_EXTRA = frozenset([
    "국적","주소","발급","만기","체류","자격","종류","성명","이름",
    "외국","국내","거소","신고","등록","증명","유효","취업","가능",
    "방문취","거주따","재외동포","재외","동포",
])


def _split_korean_name_by_surname(name: str) -> tuple[str, str, float]:
    """
    한글 이름에서 성씨를 분리.
    반환: (성씨, 이름부분, 신뢰도)  1.0=2글자성씨 / 0.9=1글자성씨 / 0.0=미발견
    """
    name = re.sub(r'[^가-힣]', '', name or '')
    if len(name) < 2:
        return '', '', 0.0
    if len(name) >= 3:
        if name[:2] in KOREAN_SURNAMES_2:
            return name[:2], name[2:], 1.0
    if name[0] in KOREAN_SURNAMES_1:
        return name[0], name[1:], 0.9
    return '', '', 0.0


def _score_korean_name_candidate(name: str, source_text: str = '') -> float:
    """한글 이름 후보의 타당성 점수 (0.0~1.0)."""
    name = re.sub(r'[^가-힣]', '', name or '')
    if not name or len(name) < 2 or len(name) > 4:
        return 0.0
    if name in KOREAN_NAME_BAN_EXTRA:
        return 0.0
    score = 0.0
    _, _, conf = _split_korean_name_by_surname(name)
    score += 0.5 if conf >= 1.0 else (0.4 if conf >= 0.9 else 0.1)
    score += 0.3 if len(name) in (3, 4) else 0.1
    if source_text:
        for lbl in ('성명', '이름'):
            pos = source_text.find(lbl)
            if pos != -1:
                npos = source_text.find(name)
                if npos != -1 and abs(npos - pos) < 30:
                    score += 0.2
                    break
        if re.search(r'\(' + re.escape(name) + r'\)', source_text):
            score += 0.3
    return min(score, 1.0)


def _normalize_korean_name_candidate(name: str, source_text: str = '') -> str:
    """
    OCR 이름 후보를 성씨 우선으로 정규화.
    신뢰도 낮으면 원본 반환, 금지어면 빈 문자열 반환.
    """
    if not name:
        return name
    cleaned = re.sub(r'[^가-힣]', '', name)
    if not cleaned or len(cleaned) < 2:
        return name
    if cleaned in KOREAN_NAME_BAN_EXTRA:
        return ''
    _, _, conf = _split_korean_name_by_surname(cleaned)
    if conf < 0.9:
        sc = _score_korean_name_candidate(cleaned, source_text)
        if sc < 0.2:
            return ''
    return cleaned


# ──────────────────────────────────────────────────────────────────────────────
# 외국인 등록번호 뒷자리 성별 일관성 보정
# ──────────────────────────────────────────────────────────────────────────────

def _validate_foreigner_back_digit(back7: str, gender: str = '') -> float:
    """
    외국인 등록번호 뒷자리 첫 번째 숫자의 성별 일관성 점수.
    1.0=일치 / 0.0=불일치 / 0.5=판단불가
    규칙(사용자 제공): 남→5 또는 7 / 여→6 또는 8
    """
    if not back7:
        return 0.5
    first = back7[0]
    if gender in ('남', 'M', 'm'):
        if first in ('5', '7'):
            return 1.0
        if first in ('6', '8'):
            return 0.0
    elif gender in ('여', 'F', 'f'):
        if first in ('6', '8'):
            return 1.0
        if first in ('5', '7'):
            return 0.0
    return 0.5


def _repair_foreigner_back_digit(back7: str, gender: str = '') -> str:
    """
    뒷자리 7자리 첫 번째 숫자를 성별 일관성 기준으로 최소 보정.
    - 나머지 6자리가 모두 숫자일 때만 시도.
    - 5↔6, 7↔8 전환만 허용 (보수적 OCR 오인식 쌍).
    - 신뢰도 낮으면 원본 반환.
    """
    if not back7 or not gender:
        return back7
    if len(back7) < 7 or not re.fullmatch(r'\d{6}', back7[1:]):
        return back7  # 나머지 6자리 불안정 → 손대지 않음
    if _validate_foreigner_back_digit(back7, gender) >= 1.0:
        return back7  # 이미 올바름
    if _validate_foreigner_back_digit(back7, gender) == 0.0:
        if gender in ('남', 'M', 'm'):
            sub = {'6': '5', '8': '7'}
        else:
            sub = {'5': '6', '7': '8'}
        new_first = sub.get(back7[0], '')
        if new_first:
            return new_first + back7[1:]
    return back7


def parse_arc(img, fast: bool = False, passport_dob: str = '', gender: str = ''):
    """
    등록증 이미지 파서.
    - fast=True  이면:
        * 등록증 전체 이미지를 한 변 최대 1600px로 리사이즈
        * 상단 OCR 시 ocr_try_all 을 최대 2회까지만 시도
    - fast=False 이면:
        * 리사이즈 없이 원본 크기
        * ocr_try_all 이 langs×psms×pres 전체 조합을 모두 시도 (기존과 동일)
    반환값 예:
    {'한글','등록증','번호','발급일','만기일','주소'}
    """
    out = {}
    if img is None:
        return out

    # 🔹 FAST 모드일 때만: 등록증 이미지 리사이즈 (한 변 최대 1600px)
    if fast:
        max_side = 1600
        w0, h0 = img.size
        scale = max_side / float(max(w0, h0))
        if scale < 1.0:
            img = img.resize(
                (int(w0 * scale), int(h0 * scale)),
                resample=_PILImage.LANCZOS,
            )

    # 리사이즈 반영된 크기로 등록증 앞/뒤 분리
    top, bot = _split_arc_front_back(img)

    # 상단: 기본 OCR
    try:
        # FAST 모드면: 앞 조합 2개까지만 시도, 아니면 전체 조합
        max_tries = 2 if fast else None
        t_top = ocr_try_all(top, langs=("kor","kor+eng"), max_tries=max_tries)["text"]
    except Exception:
        t_top = ""
    tn_top = t_top

    # 등록증 앞6/뒤7
    def _collect_front_num_candidates(front_img: Image.Image, base_text: str):
        cand = []
        dense_chunks = []
        try:
            w, h = front_img.size
            rois = {
                "pair_line": front_img.crop((int(w * 0.40), int(h * 0.05), int(w * 0.92), int(h * 0.24))),
                "front_only": front_img.crop((int(w * 0.08), int(h * 0.70), int(w * 0.40), int(h * 0.93))),
            }
            for src_name, roi in rois.items():
                txt = _ocr_digits_line(roi)
                dense = re.sub(r'(?<=\d)\s+(?=\d)', '', txt or '')
                if dense:
                    dense_chunks.append(dense)

                for m in re.finditer(r'(?<!\d)(\d{6})\D{0,8}(\d{7})(?!\d)', dense):
                    front, back = m.group(1), m.group(2)
                    score = 0
                    if _valid_yymmdd6(front):
                        score += 10
                    if src_name == "pair_line":
                        score += 8
                    if '-' in m.group(0) or '—' in m.group(0) or '–' in m.group(0):
                        score += 2
                    cand.append(("pair", score, front, back, src_name))

                for m in re.finditer(r'(?<!\d)(\d{6})(?!\d)', dense):
                    front = m.group(1)
                    if not _valid_yymmdd6(front):
                        continue
                    score = 12 if src_name == "front_only" else 5
                    cand.append(("front", score, front, "", src_name))

                for m in re.finditer(r'(?<!\d)(\d{7})(?!\d)', dense):
                    back = m.group(1)
                    score = 6 if src_name == "pair_line" else 2
                    cand.append(("back", score, "", back, src_name))
        except Exception:
            pass

        dense_all = re.sub(r'(?<=\d)\s+(?=\d)', '', base_text or '')
        if dense_all:
            dense_chunks.append(dense_all)

        for m in re.finditer(r'(?<!\d)(\d{6})\D{0,8}(\d{7})(?!\d)', dense_all):
            front, back = m.group(1), m.group(2)
            score = 0
            if _valid_yymmdd6(front):
                score += 6
            if '-' in m.group(0) or '—' in m.group(0) or '–' in m.group(0):
                score += 2
            cand.append(("pair", score, front, back, "top_text"))
        for m in re.finditer(r'(?<!\d)(\d{6})(?!\d)', dense_all):
            front = m.group(1)
            if _valid_yymmdd6(front):
                cand.append(("front", 2, front, "", "top_text"))
        for m in re.finditer(r'(?<!\d)(\d{7})(?!\d)', dense_all):
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

    # 스캔1의 뒷번호 선택 방식 이식:
    # 1) 앞번호와 짝으로 잡힌 7자리가 있으면 그 중 최고점 우선
    # 2) 없으면 전체 dense 텍스트에서 앞번호에 가장 가까운 7자리 선택
    # 3) 그래도 없으면 다득표 back 후보 fallback
    if best_front and pair_scores:
        pair_for_front = [x for x in pair_scores if x[1] == best_front]
        if pair_for_front:
            pair_for_front.sort(key=lambda x: x[0], reverse=True)
            best_back = pair_for_front[0][2]

    if best_front and not best_back:
        cands7 = [m for m in re.finditer(r'(?<!\d)(\d{7})(?!\d)', t_dense)]
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
        for m in re.finditer(r'\d{11,14}', t_dense):
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
        out['등록증'] = best_front
    if best_back:
        # 성별 일관성 보정: 뒷자리 첫 번째 숫자가 성별과 맞지 않으면 최소 보정 (5↔6, 7↔8)
        if gender:
            best_back = _repair_foreigner_back_digit(best_back, gender)
        out['번호'] = best_back

    # 발급일
    def _find_all_dates(text: str):
        cands = set()
        if not text: return []
        for m in re.finditer(r'(\d{4})[.\-\/](\d{1,2})[.\-\/](\d{1,2})', text):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try: cands.add(_dt(y, mo, d).strftime('%Y-%m-%d'))
            except: pass
        MONTHS = {'JAN':1,'FEB':2,'MAR':3,'APR':4,'MAY':5,'JUN':6,'JUL':7,'AUG':8,'SEP':9,'OCT':10,'NOV':11,'DEC':12}
        for m in re.finditer(r'(\d{1,2})\s*([A-Z]{3})\s*(\d{4})', (text or '').upper()):
            d, mon, y = int(m.group(1)), MONTHS.get(m.group(2),0), int(m.group(3))
            if mon:
                try: cands.add(_dt(y, mon, d).strftime('%Y-%m-%d'))
                except: pass
        return sorted(cands)

    def _pick_labeled_date(text: str, labels_regex: str):
        if not text: return ''
        m1 = re.search(labels_regex + r'[^\d]{0,10}(\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})', text, re.I)
        if m1:
            return m1.group(1).replace('/', '-').replace('.', '-')
        return ''

    issued = _pick_labeled_date(tn_top, r"(발\s*급|발\s*행|issue|issued)")
    if not issued:
        ds = _find_all_dates(tn_top)
        if ds:
            issued = ds[0]
    if issued:
        out["발급일"] = issued

    # ───────── 한글 이름 추출 ─────────
    def _extract_name_from_text(text: str) -> str:
        ban = {
            "외국", "국내", "거소", "신고", "증", "재외동포",
            "재외", "동포", "국적", "주소", "발급", "발급일", "발급일자",
            "만기", "체류", "자격", "종류", "성명", "이름"
        }
        m = re.search(r"(성명|이름)\s*[:\-]?\s*([가-힣]{2,4})", text)
        if m and m.group(2) not in ban:
            return m.group(2)
        toks = re.findall(r"[가-힣]{2,4}", text)
        toks = [t for t in toks if t not in ban]
        if not toks:
            return ""
        pos_label = min(
            [p for p in [text.find("성명"), text.find("이름")] if p != -1] + [len(text)//2]
        )
        best, best_d = "", 10**9
        for t in toks:
            p = text.find(t)
            if p != -1:
                d = abs(p - pos_label)
                if d < best_d:
                    best, best_d = t, d
        return best

    def _extract_name_from_roi(img, text_top: str) -> str:
        """
        등록증 앞면 이름 칸을 여러 ROI/PSM으로 읽고 가장 그럴듯한 2~4글자 한글 이름을 고른다.
        """
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

        # 0순위: text_top 괄호 이름 (예: LI FENZI(이분자)) → 압도적 우선순위
        paren_m = re.search(r'\(([가-힣]{2,4})\)', text_top or '')
        if paren_m and paren_m.group(1) not in _NAME_BAN:
            cands.append((50, paren_m.group(1)))
        else:
            # 1순위: 소형 카드 대응 — 앞면을 800px 기준으로 업스케일 후 kor+eng 재OCR
            # 소형 카드에서는 t_top 자체에 (괄호이름)이 없을 수 있으므로 재시도
            try:
                _w_fi, _h_fi = img.size
                _up_fi = max(1, min(4, 800 // max(_w_fi, 1)))
                if _up_fi >= 2:
                    _big_fi = img.resize(
                        (_w_fi * _up_fi, _h_fi * _up_fi), resample=_PILImage.LANCZOS
                    )
                    _g_fi = ImageOps.autocontrast(ImageOps.grayscale(_big_fi))
                    try:
                        _g_fi = _g_fi.filter(ImageFilter.SHARPEN)
                    except Exception:
                        pass
                    _t_fi = _ocr(_g_fi, lang="kor+eng", config="--oem 3 --psm 6")
                    _pm_fi = re.search(r'\(([가-힣]{2,4})\)', _t_fi or '')
                    if _pm_fi and _pm_fi.group(1) not in _NAME_BAN:
                        cands.append((45, _pm_fi.group(1)))
                    elif _t_fi:
                        _n_fi = _extract_kor_name_strict(_t_fi)
                        if _n_fi:
                            cands.append((8, _n_fi))
            except Exception:
                pass
            # 2순위: text_top 라벨 기반
            text_name = _extract_kor_name_strict(text_top)
            if text_name:
                cands.append((5, text_name))

        bad = {
            "방문취","거주따","매확청","사격","재태서","외국","국내","거소","신고","주소",
            "체류","만기","발급","번호","등록","증명","유효","취업","가능"
        }
        score_map = {}
        for sc, tok in cands:
            if tok in bad:
                continue
            score_map[tok] = score_map.get(tok, 0) + sc

        if not score_map:
            return ""
        return sorted(score_map.items(), key=lambda kv: (kv[1], len(kv[0]), kv[0]), reverse=True)[0][0]

    # --- 이름 추출 ---
    name_ko = _extract_name_from_roi(top, t_top)
    name_ko = _normalize_korean_name_candidate(name_ko, t_top)
    if name_ko:
        out["한글"] = name_ko

    # ───────── 뒷면: 소형 카드 대응 고해상도 회전 탐지 + 주소 테이블 추출 ─────────
    # 핵심 변경: bot 이미지를 먼저 업스케일 후 회전 탐지 → 주소 섹션 전용 크롭 OCR
    _bw0, _bh0 = bot.size
    _bot_up = max(1, min(4, 1200 // max(_bw0, _bh0, 1)))
    bot_big = (
        bot.resize((_bw0 * _bot_up, _bh0 * _bot_up), resample=_PILImage.LANCZOS)
        if _bot_up > 1 else bot
    )

    # 회전 탐지: PSM 6 단일 패스 × 3 (PSM 4 제거 → 3 calls 절약)
    best_text, best_sc, best_deg = "", -1, 0
    for deg in (0, 90, 270):
        _im_r = bot_big.rotate(deg, expand=True)
        _g_r = ImageOps.autocontrast(ImageOps.grayscale(_im_r))
        _t_r = _ocr(_g_r, lang="kor", config="--oem 3 --psm 6")
        _sc_r = _kor_count(_t_r)
        if _sc_r > best_sc:
            best_sc, best_text, best_deg = _sc_r, _t_r, deg
    tn_bot = best_text

    # 만기일: 뒷면 전체 텍스트에서 가장 늦은 날짜
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

    # ── 주소: 체류지 테이블 기반 추출 ─────────────────────────────────────────

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
        s = re.sub(r'\s{2,}', ' ', s).strip(' ,')
        if not _looks_like_korean_address(s):
            return ""
        return s

    def _is_addr_stop_line(s: str) -> bool:
        return bool(re.search(r'(유효|유호|취업가능|민원안내|하이코리아|일련번호)', (s or "")))

    def _addr_score_back(s: str) -> float:
        """뒷면 주소 후보 선택용 점수."""
        if not s:
            return -1.0
        if _ADDR_BAN_RE.search(s):
            return -1.0
        score = _kor_count(s) * 2.0
        score += 6.0 if re.search(r'[가-힣]{1,6}[시군구](?:\s|$|\d)', s) else 0.0
        score += 9.0 if re.search(r'[가-힣]{2,8}(?:대로|번길|로|길)(?:\s|$|\d)', s) else 0.0
        score += 4.0 if re.search(r'\d', s) else 0.0
        score += 3.0 if re.search(r'(동|호|층|#\d+)', s) else 0.0
        score += 6.0 if re.search(
            r'(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)', s
        ) else 0.0
        score += min(len(s), 60) / 12.0
        if len(s) < 8:
            score -= 5.0
        return score

    _DATE_ROW_RE = re.compile(r'(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})')

    def _extract_addr_section(text: str) -> list:
        """
        체류지(Address) 헤더 이후 라인 목록 반환.
        헤더를 찾지 못하면 전체 라인 반환.
        """
        lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
        start = 0
        for i, l in enumerate(lines):
            if re.search(r'체류지|Address|국내거소', l, re.I):
                start = i + 1
                break
        result = []
        for l in lines[start:]:
            if _is_addr_stop_line(l):
                break
            result.append(l)
        return result if result else lines

    def _parse_dated_addr_rows(lines: list) -> list:
        """
        날짜로 시작하는 행을 기준으로 (datetime, cleaned_addr) 쌍 추출.
        다음 날짜 행 전까지 연속 행을 주소에 병합.
        최신 날짜 우선 정렬.
        """
        rows = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            dm = _DATE_ROW_RE.match(line)
            if dm:
                try:
                    row_dt = _dt(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))
                except ValueError:
                    i += 1
                    continue
                parts = [line[dm.end():].strip()]
                j = i + 1
                while j < len(lines):
                    nxt = lines[j].strip()
                    if _DATE_ROW_RE.match(nxt) or _is_addr_stop_line(nxt):
                        break
                    if nxt and not _ADDR_BAN_RE.search(nxt):
                        parts.append(nxt)
                    j += 1
                addr_raw = " ".join(p for p in parts if p)
                addr_c = _clean_addr_line(addr_raw)
                if addr_c:
                    rows.append((row_dt, addr_c))
                i = j
            else:
                i += 1
        rows.sort(key=lambda x: x[0], reverse=True)
        return rows

    # uprighted 고해상도 뒷면 준비
    rot_bot_big = bot_big.rotate(best_deg, expand=True)
    _rbw, _rbh = rot_bot_big.size

    # 체류지 헤더 위치 추정 → 주소 섹션 Y 시작점 계산
    _lines_tb = [l.strip() for l in tn_bot.splitlines() if l.strip()]
    _hdr_frac = 0.28  # 기본값: 뒷면 상단 28%부터 주소 섹션 시작
    for _hi, _hl in enumerate(_lines_tb):
        if re.search(r'체류지|Address|국내거소', _hl, re.I):
            _hdr_frac = max(0.18, min(0.70, (_hi + 1) / max(len(_lines_tb), 1)))
            break

    # 주소 섹션 크롭 → 전용 OCR (1 call)
    _addr_y0 = int(_rbh * _hdr_frac)
    addr_crop_img = rot_bot_big.crop((int(_rbw * 0.02), _addr_y0, int(_rbw * 0.98), _rbh))
    _g_addr = ImageOps.autocontrast(ImageOps.grayscale(addr_crop_img))
    addr_crop_txt = _ocr(_g_addr, lang="kor", config="--oem 3 --psm 6")

    # 1차: 주소 섹션 전용 OCR → dated rows 파싱
    _sec_lines_hi = _extract_addr_section(addr_crop_txt)
    dated_rows = _parse_dated_addr_rows(_sec_lines_hi)

    # 2차 fallback: 회전 탐지 전체 텍스트에서 재시도
    if not dated_rows:
        _sec_lines_lo = _extract_addr_section(tn_bot)
        dated_rows = _parse_dated_addr_rows(_sec_lines_lo)
    else:
        _sec_lines_lo = []

    # 디버그 정보 (기존 debug 패널 → arc JSON에 포함됨)
    _arc_dbg = {
        "back_deg": best_deg,
        "bot_upscale": _bot_up,
        "hdr_frac": round(_hdr_frac, 2),
        "addr_crop_preview": (addr_crop_txt or "")[:500],
        "dated_rows": [(str(dt.date()), a) for dt, a in dated_rows],
    }

    # 최신 유효 주소 선택
    final_addr = ""
    for _row_dt, _row_addr in dated_rows:
        if _is_valid_address_candidate(_row_addr):
            final_addr = _row_addr
            _arc_dbg["selected"] = (str(_row_dt.date()), _row_addr)
            break

    # 3차 fallback: dated rows 없거나 모두 invalid → 섹션 라인 score 기반 선택
    if not final_addr:
        _cand_lines = _sec_lines_hi or _sec_lines_lo
        _best_sc_fb = -1.0
        for _fb_l in _cand_lines:
            _fb_c = _clean_addr_line(_fb_l)
            if not _is_valid_address_candidate(_fb_c):
                continue
            _fb_sc = _addr_score_back(_fb_c)
            if _fb_sc > _best_sc_fb:
                _best_sc_fb = _fb_sc
                final_addr = _fb_c
        if final_addr:
            _arc_dbg["selected"] = ("score_fallback", final_addr)

    out["_arc_debug"] = _arc_dbg

    if final_addr:
        out["주소"] = _apply_hierarchical_region_normalization(final_addr)



    # 여권 DOB가 있으면 등록증 앞번호는 여권 기준을 우선 사용
    front_from_passport = dob_to_arc_front(passport_dob)
    if front_from_passport:
        out['등록증'] = front_from_passport
    elif out.get('등록증') and not _valid_yymmdd6(out.get('등록증', '')):
        out.pop('등록증', None)

    return out


# -----------------------------
# 3) 페이지 렌더 함수
# -----------------------------
def render():
    """
    스캔으로 고객 추가/수정 페이지 (기존 PAGE_SCAN 코드 모듈화 버전)
    """

    # ✅ 0) file signature helper를 "사용 전에" 먼저 정의 (핵심)
    def _file_sig(_f):
        if _f is None:
            return None
        name = getattr(_f, "name", None)
        size = getattr(_f, "size", None)
        digest = None
        try:
            b = _f.getvalue()
            digest = hashlib.md5(b).hexdigest()
        except Exception:
            pass
        return (name, size, digest)

    st.subheader("📷 스캔으로 고객 추가/수정")
    st.caption("여권 1장만 또는 여권+등록증 2장을 업로드하세요.")

    show_debug = st.checkbox(
        "🧪 디버그 패널 보기(느림)", value=False,
        help="체크하면 원문/베스트OCR/파싱결과/테서랙트 진단을 표시합니다. (속도 저하)"
    )

    fast_arc = st.checkbox(
        "⚡ 등록증 빠른 모드 (리사이즈 + OCR 최대 2회)",
        value=True,
        help=(
            "체크 시: 등록증 이미지를 적당히 줄이고, 상단 OCR 조합을 앞에서부터 최대 2번까지만 시도합니다. "
            "해제 시: 이미지를 원본 크기로 두고, langs/psm/전처리 모든 조합을 시도해 인식률을 최대화합니다."
        ),
    )

    if not _ensure_tesseract():
        st.error("pytesseract가 감지되지 않았습니다. `Tesseract-OCR` 설치 및 환경설정을 확인하세요.")
        st.stop()

    cc0, cc1 = st.columns(2)
    with cc0:
        passport_file = st.file_uploader("여권 이미지 (필수)", type=["jpg", "jpeg", "png", "webp", "pdf"])
    with cc1:
        arc_file = st.file_uploader("등록증/스티커 이미지 (선택)", type=["jpg", "jpeg", "png", "webp", "pdf"])

    if show_debug:
        with st.expander("🔧 Tesseract 진단 정보"):
            try:
                ver = pytesseract.get_tesseract_version()
            except Exception as e:
                ver = f"(에러: {e})"
            st.write(f"Tesseract 버전: {ver}")
            st.write(f"tesseract_cmd: {getattr(pytesseract.pytesseract, 'tesseract_cmd', '')}")
            st.write(f"TESSDATA_PREFIX: {os.environ.get('TESSDATA_PREFIX')}")
            try:
                langs = pytesseract.get_languages()
            except Exception as e:
                langs = f"(에러: {e})"
            st.write(f"탐지된 언어들: {langs}")

    parsed_passport, parsed_arc = {}, {}

    # ✅ 1) 파일 바뀌었을 때만 파싱/채우기를 안정적으로 수행하기 위한 시그니처
    cur_sig = (_file_sig(passport_file), _file_sig(arc_file))
    last_sig = st.session_state.get("_scan_prefill_sig")

    # 이미지/파싱
    img_p = None
    if passport_file:
        img_p = open_image_safe(passport_file)
        parsed_passport = parse_passport(img_p)

    img_a = None
    if arc_file:
        img_a = open_image_safe(arc_file)
        parsed_arc = parse_arc(img_a, fast=fast_arc, passport_dob=(parsed_passport.get("생년월일") or ""), gender=(parsed_passport.get("성별") or ""))

    if show_debug:
        with st.expander("🧪 OCR 원문(베스트 설정)", expanded=False):
            if img_p is not None:
                bp = ocr_try_all(img_p)
                st.write({"lang": bp["lang"], "config": bp["config"], "pre": bp["pre"], "score": bp["score"]})
                st.code(bp["text"][:2000])
            if img_a is not None:
                ba = ocr_try_all(img_a)
                st.write({"lang": ba["lang"], "config": ba["config"], "pre": ba["pre"], "score": ba["score"]})
                st.code(ba["text"][:2000])

    if show_debug and img_p is not None:
        with st.expander("🧾 여권 MRZ 디버그(회전/밴드)"):
            st.json(st.session_state.get("passport_mrz_debug", []), expanded=1)

            # ✅ parse_passport()가 best를 세션에 저장하도록(아래 2번 패치) 해두면 여기서 바로 확인 가능
            if "passport_mrz_best" in st.session_state:
                st.write(st.session_state["passport_mrz_best"])

        with st.expander("🧪 OCR 파싱 결과(디버그)"):
            st.json({"passport": parsed_passport, "arc": parsed_arc})

    # OCR 결과 → 세션 채우기
    def _prefill_from_ocr(p, a):
        changed = False

        def setk(field, val):
            nonlocal changed
            k = f"scan_{field}"
            v = (val or "").strip()
            if not v:
                return
            cur = str(st.session_state.get(k, "")).strip()
            if cur != v:
                st.session_state[k] = v
                changed = True

        setk("한글",     a.get("한글"))
        setk("성",       p.get("성"))
        setk("명",       p.get("명"))
        setk("국적",     p.get("국가") or p.get("국적"))
        setk("성별",     p.get("성별"))
        setk("여권",     p.get("여권"))
        setk("여권발급", p.get("발급"))
        setk("여권만기", p.get("만기"))
        setk("등록증",   a.get("등록증"))
        setk("번호",     a.get("번호"))
        setk("발급일",   a.get("발급일"))
        setk("만기일",   a.get("만기일"))
        setk("주소",     a.get("주소"))

        # 여권 생년월일이 있으면 등록증 앞자리는 항상 여권값을 우선 사용
        birth = (p.get("생년월일") or "").strip()
        yymmdd = dob_to_arc_front(birth)
        if yymmdd:
            cur = str(st.session_state.get("scan_등록증", "")).strip()
            if cur != yymmdd:
                st.session_state["scan_등록증"] = yymmdd
                changed = True

        return changed

    # ✅ 2) 파일이 바뀐 경우에만 prefill + rerun (무한루프 방지)
    if cur_sig != last_sig:
        st.session_state["_scan_prefill_sig"] = cur_sig
        if _prefill_from_ocr(parsed_passport, parsed_arc):
            st.rerun()

    # 폼 기본값
    if "scan_연" not in st.session_state or not str(st.session_state["scan_연"]).strip():
        st.session_state["scan_연"] = "010"

    st.markdown("### 🔎 스캔 결과 확인 및 수정")

    with st.form(key="scan_confirm_form_v2"):
        row1_img_col, row1_info_col = st.columns([7, 3])

        with row1_img_col:
            st.markdown("#### 여권 이미지")
            if img_p is not None:
                st.image(img_p, caption="여권", use_container_width=True)
            else:
                st.info("여권 이미지를 업로드하세요.")

        with row1_info_col:
            st.markdown("<div style='height: 240px'></div>", unsafe_allow_html=True)
            st.markdown("#### 여권 정보")
            성   = st.text_input("성(영문)", key="scan_성")
            명   = st.text_input("명(영문)", key="scan_명")
            c_nat, c_sex = st.columns(2)
            with c_nat:
                국적 = st.text_input("국적(3자리)", key="scan_국적")
            with c_sex:
                성별 = st.selectbox("성별", ["", "남", "여"], key="scan_성별")
            여권     = st.text_input("여권번호", key="scan_여권")
            여권발급 = st.text_input("여권 발급일(YYYY-MM-DD)", key="scan_여권발급")
            여권만기 = st.text_input("여권 만기일(YYYY-MM-DD)", key="scan_여권만기")

        row2_img_col, row2_info_col = st.columns([7, 3])

        with row2_img_col:
            st.markdown("#### 등록증 / 스티커 이미지")
            if img_a is not None:
                st.image(img_a, caption="등록증/스티커", use_container_width=True)
            else:
                st.info("등록증/스티커 이미지를 업로드하지 않아도 됩니다.")

        with row2_info_col:
            st.markdown("<div style='height: 160px'></div>", unsafe_allow_html=True)
            st.markdown("#### 등록증 / 연락처 정보")
            한글   = st.text_input("한글 이름", key="scan_한글")
            등록증 = st.text_input("등록증 앞(YYMMDD)", key="scan_등록증")
            번호   = st.text_input("등록증 뒤 7자리",   key="scan_번호")
            발급일 = st.text_input("등록증 발급일(YYYY-MM-DD)", key="scan_발급일")
            만기일 = st.text_input("등록증 만기일(YYYY-MM-DD)", key="scan_만기일")
            주소   = st.text_input("주소", key="scan_주소")

            p1, p2, p3, p4 = st.columns([1, 1, 1, 0.7])
            연   = p1.text_input("연(앞 3자리)", key="scan_연")
            락   = p2.text_input("락(중간 4자리)", key="scan_락")
            처   = p3.text_input("처(끝 4자리)", key="scan_처")
            V    = p4.text_input("V", key="scan_V")

        submitted = st.form_submit_button("💾 고객관리 반영", use_container_width=True)
        if submitted:
            passport_data = {
                "성":   성.strip(),
                "명":   명.strip(),
                "국적": (국적 or "").strip(),
                "성별": (성별 or "").strip(),
                "여권": 여권.strip(),
                "발급": 여권발급.strip(),
                "만기": 여권만기.strip(),
            }
            arc_data = {
                "한글":   한글.strip(),
                "등록증": 등록증.strip(),
                "번호":   번호.strip(),
                "발급일": 발급일.strip(),
                "만기일": 만기일.strip(),
                "주소":   주소.strip(),
            }
            extra_data = {
                "연": 연.strip(),
                "락": 락.strip(),
                "처": 처.strip(),
                "V":  V.strip(),
            }

            ok, msg = upsert_customer_from_scan(passport_data, arc_data, extra_data)

            if ok:
                st.session_state["scan_saved_ok"] = True
                st.success(f"✅ {msg}")
            else:
                st.error(f"❌ {msg}")

            if st.session_state.get("scan_saved_ok"):
                st.success("✅ 고객관리 데이터에 반영이 완료되었습니다.")

    if st.button("← 고객관리로 돌아가기", use_container_width=True):
        st.session_state[SESS_CURRENT_PAGE] = PAGE_CUSTOMER
        st.rerun()

