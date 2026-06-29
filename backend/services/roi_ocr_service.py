import base64
import io
import re
from typing import Any, Dict, Iterable, List, Optional

from PIL import Image, ImageOps, ImageFilter, Image as _PILImage

from backend.services.ocr_service import (
    _ocr,
    _prep_mrz,
    _parse_mrz_pair,
    _mrz_check_report,
    find_best_mrz_pair_from_text,
    _extract_kor_name_strict,
    _normalize_hangul_name,
    _looks_like_korean_address,
    _dedup_address,
    _apply_hierarchical_region_normalization,
)


def file_bytes_to_pil(img_bytes: bytes, content_type: str = "") -> Image.Image:
    if not content_type.startswith("application/pdf"):
        try:
            return Image.open(io.BytesIO(img_bytes)).convert("RGB")
        except Exception:
            pass
    try:
        import fitz
        doc = fitz.open(stream=img_bytes, filetype="pdf")
        if doc.page_count == 0:
            raise ValueError("PDF에 페이지가 없습니다.")
        page = doc[0]
        pix = page.get_pixmap(dpi=250)
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    except Exception as e:
        raise ValueError(f"PDF 변환 실패: {e}")


def crop_normalized(img: Image.Image, roi: Dict[str, float]) -> Image.Image:
    w, h = img.size
    x = max(0.0, min(1.0, float(roi.get("x", 0))))
    y = max(0.0, min(1.0, float(roi.get("y", 0))))
    rw = max(0.001, min(1.0, float(roi.get("w", 1))))
    rh = max(0.001, min(1.0, float(roi.get("h", 1))))

    x1 = int(round(x * w))
    y1 = int(round(y * h))
    x2 = int(round(min(1.0, x + rw) * w))
    y2 = int(round(min(1.0, y + rh) * h))

    if x2 <= x1:
        x2 = min(w, x1 + 1)
    if y2 <= y1:
        y2 = min(h, y1 + 1)
    return img.crop((x1, y1, x2, y2))


def _img_to_base64(img: Image.Image, max_size: int = 400) -> str:
    """Encode a PIL image as a JPEG data-URL for debug preview (max 400 px side)."""
    thumb = img.copy()
    thumb.thumbnail((max_size, max_size), resample=_PILImage.LANCZOS)
    buf = io.BytesIO()
    thumb.save(buf, format="JPEG", quality=80)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _prep_mrz_for_workspace(crop: Image.Image, target_w: int = 1400) -> Image.Image:
    """Like _prep_mrz but always scales to target_w — upscales small crops too.
    Small crops from the workspace ROI need upscaling for Tesseract to read them."""
    g = ImageOps.grayscale(crop)
    w, h = g.size
    if w != target_w and w > 0:
        r = target_w / float(w)
        new_h = max(1, int(h * r))
        resample = _PILImage.LANCZOS if r >= 1.0 else _PILImage.BILINEAR
        g = g.resize((target_w, new_h), resample=resample)
    g = ImageOps.autocontrast(g)
    g = g.filter(ImageFilter.MedianFilter(size=3))
    g = g.filter(ImageFilter.SHARPEN)
    return g


def _best_mrz_text(crop: Image.Image) -> tuple[str, List[Dict[str, str]]]:
    """Returns (combined_text, ocr_attempts).
    Each attempt: {"lang": str, "psm": str, "text": str}."""
    prep = _prep_mrz_for_workspace(crop)
    configs: List[tuple[str, str, str]] = [
        ("ocrb", "psm6", "--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"),
        ("eng",  "psm6", "--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"),
        ("eng",  "psm7", "--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"),
    ]
    attempts: List[Dict[str, str]] = []
    texts: List[str] = []
    for lang, psm_label, cfg in configs:
        try:
            txt = _ocr(prep, lang=lang, config=cfg)
        except Exception:
            txt = ""
        attempts.append({"lang": lang, "psm": psm_label, "text": txt or ""})
        if txt:
            texts.append(txt)
    return "\n".join(texts), attempts


def _rotate_crop(crop: Image.Image, rotation_deg: int) -> Image.Image:
    """Rotate the crop to match the display orientation the user saw.
    CSS rotate(N deg) is clockwise; PIL.rotate is CCW, so we negate."""
    deg = rotation_deg % 360
    if deg == 0:
        return crop
    return crop.rotate(-deg, expand=True)


def extract_passport_roi(img: Image.Image, roi: Dict[str, float], rotation_deg: int = 0) -> Dict[str, Any]:
    crop = crop_normalized(img, roi)
    crop = _rotate_crop(crop, rotation_deg)
    crop_b64 = _img_to_base64(crop)
    # Generate prep thumbnail so debug shows what Tesseract actually receives
    prep_img = _prep_mrz_for_workspace(crop)
    prep_b64 = _img_to_base64(prep_img)
    text, attempts = _best_mrz_text(crop)
    L1, L2, score = find_best_mrz_pair_from_text(text)

    # ── Slight-angle correction fallback ─────────────────────────────────────
    # If the primary crop produced no valid MRZ (score < 4), the document may be
    # slightly tilted inside the ROI.  Try small CW/CCW rotations of the crop
    # until a valid passport-number-carrying pair is found.
    # This runs only on failure — zero cost for straight/well-aligned scans.
    if not L1 or not L2 or score < 4 or not _parse_mrz_pair(L1, L2).get("여권"):
        for _ang in (-5, 5, -10, 10, -3, 3):
            try:
                _rc = crop.rotate(_ang, expand=True, fillcolor=255)
            except Exception:
                try:
                    _rc = crop.rotate(_ang, expand=True)
                except Exception:
                    continue
            _rt, _ra = _best_mrz_text(_rc)
            _rL1, _rL2, _rsc = find_best_mrz_pair_from_text(_rt)
            if _rL1 and _rL2 and _rsc > score:
                _rp = _parse_mrz_pair(_rL1, _rL2)
                if _rp.get("여권"):
                    L1, L2, score, text, attempts = _rL1, _rL2, _rsc, _rt, _ra
                    break

    if not L1 or not L2:
        failure = (
            "OCR text is empty — no text produced by any attempt"
            if not text.strip()
            else "No valid MRZ pair (44-char lines) found in OCR text"
        )
        return {
            "error": "MRZ를 찾지 못했습니다.",
            "_debug": {
                "crop_preview_base64": crop_b64,
                "prep_preview_base64": prep_b64,
                "raw_ocr_text": text,
                "ocr_attempts": attempts,
                "mrz_candidates": {"L1": "", "L2": "", "score": 0, "found": False},
                "parse_result": None,
                "failure_reason": failure,
            },
        }

    parsed = _parse_mrz_pair(L1, L2)
    if not parsed.get("여권"):
        return {
            "error": "MRZ를 파싱하지 못했습니다.",
            "_debug": {
                "crop_preview_base64": crop_b64,
                "prep_preview_base64": prep_b64,
                "raw_ocr_text": text,
                "ocr_attempts": attempts,
                "mrz_candidates": {"L1": L1, "L2": L2, "score": score, "found": True},
                "parse_result": parsed,
                "failure_reason": "MRZ pair found but parsing failed — passport number field is empty",
            },
        }

    nat = parsed.get("국가", "") or parsed.get("국적", "")
    return {
        "성": parsed.get("성", ""),
        "명": parsed.get("명", ""),
        "국적": nat,
        "국가": nat,
        "성별": parsed.get("성별", ""),
        "여권": parsed.get("여권", ""),
        "발급": parsed.get("발급", ""),
        "만기": parsed.get("만기", ""),
        "생년월일": parsed.get("생년월일", ""),
        "_score": str(score),
        "_debug": {
            "crop_preview_base64": crop_b64,
            "prep_preview_base64": prep_b64,
            "raw_ocr_text": text,
            "ocr_attempts": attempts,
            "mrz_candidates": {
                "L1": L1, "L2": L2, "score": score, "found": True,
                "checks": _mrz_check_report(L1, L2),  # 개발자 debug: doc/birth/expiry check digit 통과 여부
            },
            "parse_result": {k: v for k, v in parsed.items() if not k.startswith("_")},
            "failure_reason": "",
        },
    }


def _digits_ocr(crop: Image.Image, psm: int = 7) -> str:
    g = ImageOps.grayscale(crop)
    g = ImageOps.autocontrast(g)
    g = g.resize((max(1, g.width * 3), max(1, g.height * 3)), resample=_PILImage.LANCZOS)
    try:
        g = g.filter(ImageFilter.SHARPEN)
    except Exception:
        pass
    return _ocr(g, lang="eng", config=f"--oem 3 --psm {psm} -c tessedit_char_whitelist=0123456789-")


def _prep_roi_crop(crop: Image.Image, scale: float) -> Image.Image:
    """ROI crop 경량 전처리(OCR 직전 1회): grayscale → autocontrast → scale배 LANCZOS 업스케일.

    **해당 crop 에만** 적용한다(전체 이미지 업스케일/멀티패스/재시도 아님 — OCR 호출 횟수 불변).
    등록증 작은 글자(발급일/만기일)·주소 인식률 보강용. 등록번호 숫자(_digits_ocr)·한글 이름은
    이미 자체 업스케일이 있어 여기서 건드리지 않는다."""
    g = ImageOps.grayscale(crop)
    g = ImageOps.autocontrast(g)
    if scale and scale != 1.0 and crop.width > 0 and crop.height > 0:
        g = g.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
                     resample=_PILImage.LANCZOS)
    return g


def _pick_date(text: str, prefer: str = "latest") -> str:
    dates = []
    for m in re.finditer(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", text or ""):
        y, mo, d = m.groups()
        try:
            dates.append(f"{int(y):04d}-{int(mo):02d}-{int(d):02d}")
        except Exception:
            pass
    if not dates:
        raw = re.sub(r"[^0-9]", "", text or "")
        for i in range(0, max(0, len(raw) - 7)):
            s = raw[i:i+8]
            if len(s) == 8 and s.startswith(("19", "20")):
                dates.append(f"{s[:4]}-{s[4:6]}-{s[6:8]}")
    if not dates:
        return ""
    dates = sorted(set(dates))
    return dates[-1] if prefer == "latest" else dates[0]


def _valid_yymmdd6(s: str) -> bool:
    s = re.sub(r"\D", "", s or "")
    if len(s) != 6:
        return False
    try:
        mm = int(s[2:4])
        dd = int(s[4:6])
        return 1 <= mm <= 12 and 1 <= dd <= 31
    except Exception:
        return False


def _valid_back7(s: str) -> bool:
    return len(s) == 7 and s[0] in "56789"


# ── 필드별 정규화(sanitizer) 계층 ────────────────────────────────────────────
# raw OCR 텍스트 → 필드 형식에 맞는 값만 "추출"한다(전체 문자열 일치가 아님).
# OCR 잡음(세로줄 ㅣ|, 괄호, 공백, 노이즈 숫자)에 강하고, 각 함수는 순수함수
# (문자열 in/out)라 단위 테스트가 가능하다. 실패해도 빈 문자열을 돌려주며,
# 호출부가 raw 텍스트를 함께 반환하므로 사용자가 직접 보정할 수 있다.

def clean_korean_name(raw: str) -> str:
    """한글 이름 추출: 괄호/라벨 우선 → 없으면 가장 긴 연속 한글(2~6자) 선택.
    예) '(홍길동)'→'홍길동', '홍길동ㅣ'→'홍길동', '성명 홍길동'→'홍길동'."""
    name = _extract_kor_name_strict(raw or "")
    if name:
        return name
    toks = [_normalize_hangul_name(t) for t in re.findall(r"[가-힣]{2,6}", raw or "")]
    toks = [t for t in toks if t]
    if not toks:
        return ""
    # 가장 긴 연속 한글 후보 우선(외국인 한글이름 길이 다양).
    toks.sort(key=len, reverse=True)
    return toks[0]


def clean_reg_front(raw: str) -> str:
    """등록증 앞 6자리(YYMMDD) 추출.
    - 숫자 사이 공백 제거 후 라인별 숫자열에서 유효 YYMMDD 6자를 슬라이스 탐색.
    - YYYYMMDD(8자)는 앞 2자를 잘라 YYMMDD로 변환.
    - 유효 범위 후보가 없으면 정확히 6자리인 첫 후보 반환(사용자 보정 가능).
    예) '900101ㅣ'→'900101', '1990-01-01'→'900101', '1990.01.01'→'900101'."""
    # 구분자(./-//)가 있는 YYYY-MM-DD 형태 우선 처리 → YYMMDD.
    m = re.search(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})", raw or "")
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y[2:]}{mo:02d}{d:02d}"
    collapsed = re.sub(r"(?<=\d)[ \t]+(?=\d)", "", raw or "")
    runs = re.findall(r"\d+", collapsed)
    for run in runs:
        if len(run) == 8 and run[:2] in ("19", "20"):
            cand = run[2:]
            if _valid_yymmdd6(cand):
                return cand
    for run in runs:
        for i in range(0, len(run) - 5):  # 6자 윈도우
            cand = run[i:i + 6]
            if _valid_yymmdd6(cand):
                return cand
    for run in runs:
        if len(run) == 6:
            return run
    return ""


def clean_reg_back(raw: str) -> str:
    """등록증 뒤 7자리 추출.
    - 숫자 사이 공백 제거 후 라인별 숫자열에서 유효(첫자리 5~9) 7자를 슬라이스 탐색.
    - 유효 후보가 없으면 정확히 7자리인 첫 후보 반환(사용자 보정 가능).
    예) '1234567ㅣ'→'1234567', '1234567-'→'1234567', '1 2 3 4 5 6 7'→'1234567'."""
    collapsed = re.sub(r"(?<=\d)[ \t]+(?=\d)", "", raw or "")
    runs = re.findall(r"\d+", collapsed)
    for run in runs:
        for i in range(0, len(run) - 6):  # 7자 윈도우
            cand = run[i:i + 7]
            if _valid_back7(cand):
                return cand
    for run in runs:
        if len(run) == 7:
            return run
    return ""


_PROVINCE_RE = r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"

# 주소 정규화 정적 패턴 — 모듈 로드 시 1회 컴파일(호출마다 재컴파일 방지).
_PROVINCE_PAT = re.compile(_PROVINCE_RE)
_ADDR_BRACKET_PAT = re.compile(r"\[[^\]]*\]|\{[^}]*\}")
_ADDR_DISALLOWED_PAT = re.compile(r"[^가-힣A-Za-z0-9\s,\-]")
_ADDR_COMMA_PAT = re.compile(r"\s*,\s*")
_ADDR_MULTISPACE_PAT = re.compile(r"\s{2,}")
_ADDR_SUFFIX_PAT = re.compile(r"(시|군|구|읍|면|동|리|로|길|번길|호|아파트)")
_ADDR_DETAIL_PAT = re.compile(r"(아파트|\d+\s*동|\d+\s*호)")
_ADDR_ADMIN_OR_ROAD_PAT = re.compile(r"[가-힣]{1,8}(?:시|군|구|동|읍|면|로|길|대로|번길)")
# 주소 '시작 줄'(head) 판별: 시/군/구 행정단위로 끝나는 토큰(단어 경계).
_ADDR_HEAD_PAT = re.compile(r"[가-힣]{1,6}[시군구](?:\s|$|\d|,)")
_ADDR_DATE_PAT = re.compile(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})")
_ADDR_KOR_PAT = re.compile(r"[가-힣]")
_ADDR_DIGIT_PAT = re.compile(r"\d")
_ADDR_WS_PAT = re.compile(r"\s+")
_ADDR_NOISE_CHARS = ("|", "｜", "ㅣ", "!", "(", ")")


def _sanitize_addr_line(line: str) -> str:
    """한 줄을 주소 허용 문자셋으로 정리한다(줄 단위 sanitizer).

    허용: 한글·영문·숫자·공백·하이픈(-)·쉼표(,). 그 외는 제거.
    여기서는 province-cut/validation을 하지 않는다(블록 단계에서 처리).
    """
    s = _ADDR_WS_PAT.sub(" ", line or "").strip()
    if not s:
        return ""
    # 대괄호/중괄호는 내용까지 제거([잡음] 등). 소괄호는 문자만 제거하고 내용 보존.
    s = _ADDR_BRACKET_PAT.sub(" ", s)
    for ch in _ADDR_NOISE_CHARS:
        s = s.replace(ch, " ")
    s = _ADDR_DISALLOWED_PAT.sub(" ", s)   # 허용 문자셋만 남김(하이픈/쉼표/영문 유지)
    s = _ADDR_COMMA_PAT.sub(", ", s)        # 쉼표 주변 공백 정규화
    s = _ADDR_MULTISPACE_PAT.sub(" ", s)
    return s.strip(" ,-")


def _addr_block_score(s: str) -> float:
    """가벼운 주소 후보 점수 — 설명 가능한 규칙만 사용(유사도/외부조회 없음)."""
    if not s:
        return -999.0
    score = 0.0
    if _PROVINCE_PAT.search(s):            # 시도(province) 인식 — 더 완성된 후보
        score += 1.0
    if _ADDR_KOR_PAT.search(s):
        score += 1.0
    if _ADDR_DIGIT_PAT.search(s):          # 도로명/지번 숫자
        score += 1.0
    suffix_hits = len(_ADDR_SUFFIX_PAT.findall(s))
    score += min(suffix_hits, 6) * 0.5     # 주소 접미어(시/군/구/…/호/아파트)
    if _ADDR_DETAIL_PAT.search(s):         # 상세주소(동/호/아파트)
        score += 1.0
    L = len(s)
    if L < 8:                              # 너무 짧으면 감점
        score -= 2.0
    elif L > 70:                           # 지나치게 길면 감점(여러 주소 합쳐졌을 가능성)
        score -= (L - 70) * 0.05
    return score


def _addr_block_passes(s: str) -> bool:
    """strong/weak validation — 빈값 방지를 위해 weak 후보도 허용(기존 동작 유지)."""
    has_province = bool(_PROVINCE_PAT.search(s))
    has_admin_or_road = bool(_ADDR_ADMIN_OR_ROAD_PAT.search(s))
    kor_count = len(_ADDR_KOR_PAT.findall(s))
    has_suffix = bool(_ADDR_SUFFIX_PAT.search(s))
    has_digit = bool(_ADDR_DIGIT_PAT.search(s))
    strong = has_province and has_admin_or_road
    weak = len(s) >= 8 and kor_count >= 3 and (has_digit or has_suffix)
    return strong or weak


def _clean_address_text(text: str) -> str:
    """주소 raw OCR → 줄 단위 정리 → 블록 후보화 → 가장 타당한 후보 1개 선택.

    핵심: raw OCR의 여러 줄/여러 attempt를 통째로 이어 붙이지 않는다. 줄을 정리한 뒤
    시도(province)/행정단위(시·군·구)로 시작하는 줄을 기준으로 블록으로 묶고, 가벼운
    점수로 가장 완성도 높은 블록 **1개만** 반환한다. 점수가 같으면 (안정적으로 날짜가
    잡히면)최신 날짜, 그다음 아래쪽(나중) 후보를 우선한다 — 등록증 주소 이력은 보통
    아래가 최신이기 때문. 무거운 유사도 계산·외부 조회·province 자동보정은 하지 않는다.
    """
    raw_lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not raw_lines:
        return ""

    # 1) 줄 단위 정리 — 빈 줄 제거. (cleaned, raw) 쌍 유지(raw는 날짜 보조점수용).
    cleaned: List[tuple[str, str]] = []
    for rl in raw_lines:
        cl = _sanitize_addr_line(rl)
        if cl:
            cleaned.append((cl, rl))
    if not cleaned:
        return ""

    # 2) 블록 묶기 — province 또는 시/군/구 head 줄에서 새 블록 시작.
    #    그 외(동/호 등 상세줄)는 직전 블록의 연속줄로 합친다. 첫 줄은 항상 블록 시작.
    blocks: List[Dict[str, Any]] = []
    for cl, rl in cleaned:
        is_head = bool(_PROVINCE_PAT.search(cl) or _ADDR_HEAD_PAT.search(cl))
        if is_head or not blocks:
            blocks.append({"lines": [cl], "raws": [rl]})
        else:
            blocks[-1]["lines"].append(cl)
            blocks[-1]["raws"].append(rl)

    # 3) 블록별 최종 후보 구성: 줄 합치기 → province-cut → 내부중복 dedup → 점수/날짜.
    candidates: List[Dict[str, Any]] = []
    for idx, blk in enumerate(blocks):
        joined = _ADDR_MULTISPACE_PAT.sub(" ", " ".join(blk["lines"])).strip(" ,-")
        m = _PROVINCE_PAT.search(joined)
        if m:
            joined = joined[m.start():].strip(" ,-")
        joined = _dedup_address(joined)   # 같은 줄 내부 중복(같은 province 2회) 보조 제거
        if not joined:
            continue
        latest_date = ""                  # 보조: 주소 이력 날짜(raw에서만 탐지)
        for rl in blk["raws"]:
            for dm in _ADDR_DATE_PAT.finditer(rl):
                y, mo, d = dm.groups()
                try:
                    iso = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
                except Exception:
                    continue
                if iso > latest_date:
                    latest_date = iso
        candidates.append({
            "text": joined,
            "score": _addr_block_score(joined),
            "date": latest_date,
            "idx": idx,
        })

    if not candidates:
        return ""

    # 4) validation 통과 후보 우선. 전부 실패하면 weak fallback로 후보 유지(빈값 방지).
    valid = [c for c in candidates if _addr_block_passes(c["text"])]
    pool = valid if valid else candidates

    # 5) 최종 선택: 점수 → (날짜 2개 이상 안정 인식 시)최신 날짜 → 아래쪽(idx 큰) 후보.
    use_date = len([c for c in pool if c["date"]]) >= 2
    best = max(pool, key=lambda c: (c["score"], c["date"] if use_date else "", c["idx"]))

    return _apply_hierarchical_region_normalization(best["text"])


def extract_arc_field(img: Image.Image, field: str, roi: Dict[str, float], rotation_deg: int = 0) -> tuple[str, Dict[str, Any]]:
    """Returns (value, debug_dict).
    debug_dict keys: crop_preview_base64, raw_ocr_text, normalized_text, failure_reason."""
    crop = crop_normalized(img, roi)
    crop = _rotate_crop(crop, rotation_deg)
    crop_b64 = _img_to_base64(crop)

    def _dbg(raw: str, value: str, reason: str = "") -> Dict[str, Any]:
        return {
            "crop_preview_base64": crop_b64,
            "raw_ocr_text": raw,
            "normalized_text": value,
            "failure_reason": reason if not value else "",
        }

    if field == "한글":
        # Upscale small crops — Tesseract Korean OCR fails below ~100px height.
        # Target at least 400px wide (≈4× for typical ARC name region ~94px wide).
        _kor_crop = ImageOps.grayscale(crop)
        _kor_crop = ImageOps.autocontrast(_kor_crop)
        _target_w = 400
        if _kor_crop.width < _target_w:
            _scale = max(2, _target_w // max(1, _kor_crop.width))
            _kor_crop = _kor_crop.resize(
                (_kor_crop.width * _scale, _kor_crop.height * _scale),
                resample=_PILImage.LANCZOS,
            )
        txt = _ocr(_kor_crop, lang="kor+eng", config="--oem 3 --psm 6")
        value = clean_korean_name(txt or "")
        reason = (
            "" if value
            else ("OCR returned empty text" if not (txt or "").strip()
                  else "No Korean name found after normalization")
        )
        return value, _dbg(txt or "", value, reason)

    if field == "등록증":
        txt = _digits_ocr(crop, 7) + "\n" + _digits_ocr(crop, 6)
        value = clean_reg_front(txt)
        reason = (
            "" if value
            else ("OCR returned no digits" if not txt.strip()
                  else "No valid 6-digit YYMMDD sequence found")
        )
        return value, _dbg(txt, value, reason)

    if field == "번호":
        txt = _digits_ocr(crop, 7) + "\n" + _digits_ocr(crop, 6)
        value = clean_reg_back(txt)
        reason = (
            "" if value
            else ("OCR returned no digits" if not txt.strip()
                  else "No valid 7-digit back number (first digit 5–9) found")
        )
        return value, _dbg(txt, value, reason)

    if field == "발급일":
        txt = _ocr(_prep_roi_crop(crop, 3), lang="kor+eng", config="--oem 3 --psm 6")
        value = _pick_date(txt, prefer="earliest")
        reason = (
            "" if value
            else ("OCR returned empty text" if not (txt or "").strip()
                  else "No date pattern found in text")
        )
        return value, _dbg(txt or "", value, reason)

    if field == "만기일":
        txt = _ocr(_prep_roi_crop(crop, 3), lang="kor+eng", config="--oem 3 --psm 6")
        value = _pick_date(txt, prefer="latest")
        reason = (
            "" if value
            else ("OCR returned empty text" if not (txt or "").strip()
                  else "No date pattern found in text")
        )
        return value, _dbg(txt or "", value, reason)

    if field == "주소":
        _addr_crop = _prep_roi_crop(crop, 2)   # 주소는 영역이 커서 2x 만(과도한 4x 금지)
        txt1 = _ocr(_addr_crop, lang="kor", config="--oem 3 --psm 6")
        txt2 = _ocr(_addr_crop, lang="kor", config="--oem 3 --psm 4")
        raw = (txt1 or "") + "\n" + (txt2 or "")
        value = _clean_address_text(raw)
        reason = (
            "" if value
            else ("OCR returned empty text" if not raw.strip()
                  else "Address text did not pass validation (no province/road pattern found)")
        )
        return value, _dbg(raw, value, reason)

    return "", {
        "crop_preview_base64": crop_b64,
        "raw_ocr_text": "",
        "normalized_text": "",
        "failure_reason": f"Unknown field: {field}",
    }


def extract_arc_fields(
    img: Image.Image,
    rois: Dict[str, Dict[str, float]],
    fields: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    wanted = list(fields) if fields else list(rois.keys())
    out: Dict[str, str] = {}
    for field in wanted:
        roi = rois.get(field)
        if not roi:
            continue
        try:
            value, _debug = extract_arc_field(img, field, roi)
        except Exception:
            value = ""
        if value:
            out[field] = value
    return out


def extract_arc_fields_detailed(
    img: Image.Image,
    rois: Dict[str, Dict[str, float]],
    fields: Optional[Iterable[str]] = None,
    rotation_deg: int = 0,
) -> Dict[str, Dict[str, str]]:
    """그룹(앞면/뒷면) 추출용: 요청된 필드들을 한 번에 처리해 필드별 {value, raw, reason} 반환.

    각 필드는 기존 단일 추출(extract_arc_field)을 **그대로** 호출한다(필드당 OCR 호출 횟수 불변).
    빈값도 포함해 반환한다(프론트가 실패 칸 안내를 표시할 수 있도록)."""
    wanted = list(fields) if fields else list(rois.keys())
    out: Dict[str, Dict[str, str]] = {}
    for field in wanted:
        roi = rois.get(field)
        if not roi:
            continue
        try:
            value, debug = extract_arc_field(img, field, roi, rotation_deg=rotation_deg)
        except Exception as exc:  # 한 필드 실패가 그룹 전체를 막지 않도록
            value, debug = "", {"raw_ocr_text": "", "failure_reason": f"error: {exc}"}
        out[field] = {
            "value": value,
            "raw": debug.get("raw_ocr_text", ""),
            "reason": debug.get("failure_reason", ""),
        }
    return out
