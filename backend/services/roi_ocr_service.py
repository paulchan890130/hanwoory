import io
import re
from typing import Dict, Iterable, Optional

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


def _best_mrz_text(crop: Image.Image) -> str:
    prep = _prep_mrz(crop)
    configs = [
        ("ocrb", "--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"),
        ("eng", "--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"),
        ("eng", "--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"),
    ]
    texts: list[str] = []
    for lang, cfg in configs:
        try:
            txt = _ocr(prep, lang=lang, config=cfg)
        except Exception:
            txt = ""
        if txt:
            texts.append(txt)
    return "\n".join(texts)


def extract_passport_roi(img: Image.Image, roi: Dict[str, float]) -> Dict[str, str]:
    crop = crop_normalized(img, roi)
    text = _best_mrz_text(crop)
    L1, L2, score = find_best_mrz_pair_from_text(text)
    if not L1 or not L2:
        return {"error": "MRZ를 찾지 못했습니다."}
    parsed = _parse_mrz_pair(L1, L2)
    if not parsed.get("여권"):
        return {"error": "MRZ를 파싱하지 못했습니다."}
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

    if not _looks_like_korean_address(joined):
        return ""
    joined = _dedup_address(joined)
    joined = _apply_hierarchical_region_normalization(joined)
    return joined


def extract_arc_field(img: Image.Image, field: str, roi: Dict[str, float]) -> str:
    crop = crop_normalized(img, roi)

    if field == "한글":
        txt = _ocr(crop, lang="kor+eng", config="--oem 3 --psm 6")
        name = _extract_kor_name_strict(txt or "")
        if name:
            return name
        toks = [_normalize_hangul_name(t) for t in re.findall(r"[가-힣]{2,4}", txt or "")]
        toks = [t for t in toks if t]
        return toks[0] if toks else ""

    if field == "등록증":
        txt = _digits_ocr(crop, 7) + "\n" + _digits_ocr(crop, 6)
        cands = re.findall(r"(?<!\d)(\d{6})(?!\d)", txt)
        for cand in cands:
            if _valid_yymmdd6(cand):
                return cand
        return cands[0] if cands else ""

    if field == "번호":
        txt = _digits_ocr(crop, 7) + "\n" + _digits_ocr(crop, 6)
        cands = re.findall(r"(?<!\d)(\d{7})(?!\d)", txt)
        for cand in cands:
            if _valid_back7(cand):
                return cand
        return cands[0] if cands else ""

    if field == "발급일":
        txt = _ocr(crop, lang="kor+eng", config="--oem 3 --psm 6")
        return _pick_date(txt, prefer="earliest")

    if field == "만기일":
        txt = _ocr(crop, lang="kor+eng", config="--oem 3 --psm 6")
        return _pick_date(txt, prefer="latest")

    if field == "주소":
        txt1 = _ocr(crop, lang="kor", config="--oem 3 --psm 6")
        txt2 = _ocr(crop, lang="kor", config="--oem 3 --psm 4")
        return _clean_address_text((txt1 or "") + "\n" + (txt2 or ""))

    return ""


def extract_arc_fields(img: Image.Image, rois: Dict[str, Dict[str, float]], fields: Optional[Iterable[str]] = None) -> Dict[str, str]:
    wanted = list(fields) if fields else list(rois.keys())
    out: Dict[str, str] = {}
    for field in wanted:
        roi = rois.get(field)
        if not roi:
            continue
        try:
            value = extract_arc_field(img, field, roi)
        except Exception:
            value = ""
        if value:
            out[field] = value
    return out
