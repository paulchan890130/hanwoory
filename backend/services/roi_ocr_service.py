import base64
import io
import re
from typing import Any, Dict, Iterable, List, Optional

from PIL import Image, ImageOps, ImageFilter, Image as _PILImage

from backend.services.ocr_service import (
    _ocr,
    _prep_mrz,
    _parse_mrz_pair,
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
            "mrz_candidates": {"L1": L1, "L2": L2, "score": score, "found": True},
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


def _clean_address_text(text: str) -> str:
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    joined = " ".join(lines)
    joined = joined.replace("|", " ").replace("｜", " ")
    joined = re.sub(r"[^가-힣0-9A-Za-z\s\-\.,#()/~]", " ", joined)
    joined = re.sub(r"\s{2,}", " ", joined).strip(" ,")

    m = re.search(r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)", joined)
    if m:
        joined = joined[m.start():].strip()

    # Relaxed gate for workspace ROI path: _looks_like_korean_address requires
    # road/admin tokens at strict word-boundaries (?:\s|$|\d), but OCR output
    # from small crops often lacks spaces (e.g. "시흥시정왕동로"), causing false
    # blanks. Accept text that has a province marker + any admin/road syllable.
    has_province = bool(re.search(
        r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)", joined
    ))
    has_admin_or_road = bool(re.search(
        r'[가-힣]{1,8}(?:시|군|구|동|읍|면|로|길|대로|번길)', joined
    ))
    if not (has_province and has_admin_or_road):
        return ""
    joined = _dedup_address(joined)
    joined = _apply_hierarchical_region_normalization(joined)
    return joined


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
        name = _extract_kor_name_strict(txt or "")
        if name:
            return name, _dbg(txt or "", name)
        toks = [_normalize_hangul_name(t) for t in re.findall(r"[가-힣]{2,4}", txt or "")]
        toks = [t for t in toks if t]
        value = toks[0] if toks else ""
        reason = (
            "" if value
            else ("OCR returned empty text" if not (txt or "").strip()
                  else "No Korean name found after normalization")
        )
        return value, _dbg(txt or "", value, reason)

    if field == "등록증":
        txt = _digits_ocr(crop, 7) + "\n" + _digits_ocr(crop, 6)
        cands = re.findall(r"(?<!\d)(\d{6})(?!\d)", txt)
        for cand in cands:
            if _valid_yymmdd6(cand):
                return cand, _dbg(txt, cand)
        value = cands[0] if cands else ""
        reason = (
            "" if value
            else ("OCR returned no digits" if not txt.strip()
                  else "No valid 6-digit YYMMDD sequence found")
        )
        return value, _dbg(txt, value, reason)

    if field == "번호":
        txt = _digits_ocr(crop, 7) + "\n" + _digits_ocr(crop, 6)
        cands = re.findall(r"(?<!\d)(\d{7})(?!\d)", txt)
        for cand in cands:
            if _valid_back7(cand):
                return cand, _dbg(txt, cand)
        value = cands[0] if cands else ""
        reason = (
            "" if value
            else ("OCR returned no digits" if not txt.strip()
                  else "No valid 7-digit back number (first digit 5–9) found")
        )
        return value, _dbg(txt, value, reason)

    if field == "발급일":
        txt = _ocr(crop, lang="kor+eng", config="--oem 3 --psm 6")
        value = _pick_date(txt, prefer="earliest")
        reason = (
            "" if value
            else ("OCR returned empty text" if not (txt or "").strip()
                  else "No date pattern found in text")
        )
        return value, _dbg(txt or "", value, reason)

    if field == "만기일":
        txt = _ocr(crop, lang="kor+eng", config="--oem 3 --psm 6")
        value = _pick_date(txt, prefer="latest")
        reason = (
            "" if value
            else ("OCR returned empty text" if not (txt or "").strip()
                  else "No date pattern found in text")
        )
        return value, _dbg(txt or "", value, reason)

    if field == "주소":
        txt1 = _ocr(crop, lang="kor", config="--oem 3 --psm 6")
        txt2 = _ocr(crop, lang="kor", config="--oem 3 --psm 4")
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
