"""OCR 스캔 라우터 - 여권/외국인등록증 + 기존 고객 upsert"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import io, datetime, asyncio
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException


def _file_to_pil(img_bytes: bytes, content_type: str = ""):
    """Convert uploaded file bytes → PIL RGB Image.
    Tries PIL directly first; falls back to PyMuPDF (fitz) for PDF files."""
    from PIL import Image
    # Fast path: plain image
    if not content_type.startswith("application/pdf"):
        try:
            return Image.open(io.BytesIO(img_bytes)).convert("RGB")
        except Exception:
            pass
    # PDF path: render first page at 200 dpi
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=img_bytes, filetype="pdf")
        if doc.page_count == 0:
            raise ValueError("PDF에 페이지가 없습니다.")
        page = doc[0]
        pix = page.get_pixmap(dpi=200)
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    except ImportError:
        raise ValueError("PyMuPDF(fitz)가 설치되지 않아 PDF를 처리할 수 없습니다.")
    except Exception as e:
        raise ValueError(f"PDF 변환 실패: {e}")
from pydantic import BaseModel
from typing import Optional
from backend.auth import get_current_user
from backend.services.ocr_service import parse_passport, parse_arc

router = APIRouter()

# ── OCR concurrency guard ─────────────────────────────────────────────────────
# Semaphore(1) serialises passport and ARC OCR so a lingering background thread
# from a timed-out request cannot overlap with the next request and OOM the worker.
# asyncio.Semaphore must be created inside an event loop; init lazily on first call.
_OCR_SEMAPHORE: asyncio.Semaphore | None = None


def _ocr_sem() -> asyncio.Semaphore:
    global _OCR_SEMAPHORE
    if _OCR_SEMAPHORE is None:
        _OCR_SEMAPHORE = asyncio.Semaphore(1)
    return _OCR_SEMAPHORE


# ── Tesseract 초기화 ──────────────────────────────────────────────────────────

_TESSERACT_INITIALIZED = False


def _find_linux_tessdata() -> str:
    """Return the system tessdata directory on Linux (contains eng/kor/osd)."""
    candidates = [
        "/usr/share/tesseract-ocr/5/tessdata",
        "/usr/share/tesseract-ocr/4/tessdata",
        "/usr/share/tessdata",
        "/usr/local/share/tessdata",
    ]
    for p in candidates:
        if os.path.isdir(p) and any(
            f.endswith(".traineddata") for f in os.listdir(p)
        ):
            return p
    # Last resort: ask tesseract itself
    try:
        import subprocess
        out = subprocess.check_output(
            ["tesseract", "--print-parameters", "tessedit"],
            stderr=subprocess.STDOUT, text=True
        )
        for line in out.splitlines():
            if "tessdata" in line.lower() and os.sep in line:
                parts = line.split()
                for part in parts:
                    if "tessdata" in part and os.path.isdir(part):
                        return part
    except Exception:
        pass
    return candidates[0]  # fallback — may not exist but won't hide eng/kor


def _ensure_tesseract():
    global _TESSERACT_INITIALIZED
    import platform
    import logging
    _log = logging.getLogger("scan.tesseract")

    try:
        import pytesseract

        # 프로젝트 tessdata 경로 (ocrb.traineddata 포함)
        _here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        project_tessdata = os.path.join(_here, "tessdata")

        if platform.system() == "Windows":
            TESSERACT_ROOT = r"C:\Program Files\Tesseract-OCR"
            pytesseract.pytesseract.tesseract_cmd = os.path.join(TESSERACT_ROOT, "tesseract.exe")
            sys_tessdata = os.path.join(TESSERACT_ROOT, "tessdata")
            ocrb_sys = os.path.join(sys_tessdata, "ocrb.traineddata")
            ocrb_proj = os.path.join(project_tessdata, "ocrb.traineddata")
            if not os.path.exists(ocrb_sys) and os.path.exists(ocrb_proj):
                try:
                    import shutil
                    shutil.copy2(ocrb_proj, ocrb_sys)
                except Exception:
                    pass
            os.environ["TESSDATA_PREFIX"] = sys_tessdata + os.sep
        else:
            pytesseract.pytesseract.tesseract_cmd = "tesseract"
            # Linux: use the SYSTEM tessdata so eng/kor/osd remain visible.
            # Copy ocrb.traineddata into system tessdata if not already there.
            sys_tessdata = _find_linux_tessdata()
            ocrb_proj = os.path.join(project_tessdata, "ocrb.traineddata")
            ocrb_sys = os.path.join(sys_tessdata, "ocrb.traineddata")
            if os.path.exists(ocrb_proj) and not os.path.exists(ocrb_sys):
                try:
                    import shutil
                    shutil.copy2(ocrb_proj, ocrb_sys)
                except Exception as copy_err:
                    _log.warning("ocrb copy failed (%s) — OCR may lack ocrb lang", copy_err)
            os.environ["TESSDATA_PREFIX"] = sys_tessdata + os.sep

        # Log tessdata state once at startup
        if not _TESSERACT_INITIALIZED:
            _TESSERACT_INITIALIZED = True
            prefix = os.environ.get("TESSDATA_PREFIX", "<unset>")
            try:
                langs = pytesseract.get_languages(config="")
            except Exception:
                langs = ["<failed to list>"]
            _log.warning(
                "[OCR] TESSDATA_PREFIX=%s  available_langs=%s", prefix, langs
            )

        return pytesseract
    except ImportError:
        return None


# ── OCR 엔드포인트 ────────────────────────────────────────────────────────────

@router.post("/passport")
async def scan_passport(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """여권 이미지 → MRZ 파싱 → 고객 정보 추출"""
    import logging, traceback as _tb
    _log = logging.getLogger("scan.passport")
    _ensure_tesseract()  # set TESSDATA_PREFIX + tesseract_cmd before any OCR call
    try:
        img_bytes = await file.read()
        try:
            img = _file_to_pil(img_bytes, file.content_type or "")
        except Exception as exc:
            return {"debug": "passport-file-to-pil-exception", "error_type": exc.__class__.__name__, "error_message": str(exc)}

        # Reject immediately if another OCR job is running.
        # wait_for cancels the coroutine but NOT the underlying thread — so a timed-out
        # passport job keeps its PaddleOCR thread alive. Without this guard the next
        # request would overlap and push RAM over the Render instance limit → worker kill.
        sem = _ocr_sem()
        if sem.locked():
            return {
                "debug": "passport-busy",
                "error_type": "Busy",
                "error_message": "OCR is currently processing another request. Please retry in a moment.",
            }

        async with sem:
            try:
                # 60s budget: PaddleOCR model load on a cold worker can take 20-40s.
                # With prewarm this should not be needed, but kept as a hard safety net.
                # Temporary — reduce back to 30s once prewarm proves stable on Render.
                result = await asyncio.wait_for(
                    asyncio.to_thread(parse_passport, img, True),
                    timeout=60.0,
                )
            except asyncio.TimeoutError:
                return {
                    "debug": "passport-timeout",
                    "error_type": "TimeoutError",
                    "error_message": "passport OCR exceeded 60s server time budget",
                }
            except Exception as exc:
                return {"debug": "passport-parse-exception", "error_type": exc.__class__.__name__, "error_message": str(exc), "traceback": _tb.format_exc()[-1000:]}
            return {
                "debug": "passport-parse-done",
                "result": result,
                "raw_L1": result.pop("_raw_L1", None) if result else None,
                "raw_L2": result.pop("_raw_L2", None) if result else None,
            }
    except Exception as exc:
        return {
            "debug": "passport-route-exception",
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
            "traceback": _tb.format_exc()[-2000:],
        }


@router.post("/arc")
async def scan_arc(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """외국인등록증 이미지 → 정보 추출"""
    import logging, traceback as _tb
    _log = logging.getLogger("scan.arc")
    _ensure_tesseract()  # set TESSDATA_PREFIX + tesseract_cmd before any OCR call
    try:
        img_bytes = await file.read()
        try:
            img = _file_to_pil(img_bytes, file.content_type or "")
        except Exception as exc:
            return {"debug": "arc-file-to-pil-exception", "error_type": exc.__class__.__name__, "error_message": str(exc)}

        # Same concurrency guard as passport route — prevents overlapping OCR threads
        # from pushing the Render worker over its memory limit.
        sem = _ocr_sem()
        if sem.locked():
            return {
                "debug": "arc-busy",
                "error_type": "Busy",
                "error_message": "OCR is currently processing another request. Please retry in a moment.",
            }

        async with sem:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(parse_arc, img, True),
                    timeout=30.0,
                )
            except asyncio.TimeoutError:
                return {
                    "debug": "arc-timeout",
                    "error_type": "TimeoutError",
                    "error_message": "ARC OCR exceeded 30s server time budget",
                }
            except Exception as exc:
                return {"debug": "arc-parse-exception", "error_type": exc.__class__.__name__, "error_message": str(exc), "traceback": _tb.format_exc()[-1000:]}
            return {"debug": "arc-parse-done", "result": result}
    except Exception as exc:
        return {
            "debug": "arc-route-exception",
            "error_type": exc.__class__.__name__,
            "error_message": str(exc),
            "traceback": _tb.format_exc()[-2000:],
        }


# ── upsert 요청 스키마 ────────────────────────────────────────────────────────

class ScanUpsertRequest(BaseModel):
    """
    OCR 결과를 고객 시트에 upsert.
    필드명은 실무 시트 축약형 컬럼과 일치시킨다.
    """
    # 여권 정보
    성: Optional[str] = ""        # 영문 성
    명: Optional[str] = ""        # 영문 이름
    국적: Optional[str] = ""
    성별: Optional[str] = ""
    여권: Optional[str] = ""      # 여권번호
    발급: Optional[str] = ""      # 여권 발급일
    만기: Optional[str] = ""      # 여권 만기일
    # 등록증 정보
    한글: Optional[str] = ""      # 한글이름
    등록증: Optional[str] = ""    # 등록번호 앞자리
    번호: Optional[str] = ""      # 등록번호 뒷자리
    발급일: Optional[str] = ""    # 등록증 발급일
    만기일: Optional[str] = ""    # 등록증 만기일
    주소: Optional[str] = ""
    # 기타
    연: Optional[str] = ""        # 전화번호 앞
    락: Optional[str] = ""        # 전화번호 중간
    처: Optional[str] = ""        # 전화번호 뒷
    V: Optional[str] = ""         # 비고


# ── 날짜 정규화 ───────────────────────────────────────────────────────────────

def _normalize_ymd(s: str) -> str:
    """'YYYYMMDD' / 'YYYY.MM.DD' / 'YYYY-MM-DD' → 'YYYY-MM-DD'"""
    if not s:
        return ""
    s = s.strip().replace(".", "-").replace("/", "-")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s[:10] if len(s) >= 10 else s


# ── 필드 alias 정규화 ─────────────────────────────────────────────────────────
# 프론트에서 풀네임 키가 오는 경우에도 수용.
# 우선순위: 실무 축약형 키 = 최종 저장 키.
_FIELD_ALIASES: dict = {
    "한글이름":          "한글",
    "korean_name":       "한글",
    "name":              "한글",
    "surname":           "성",
    "given_names":       "명",
    "영문이름":          "명",    # 축약형 "명"으로 단일 매핑 (성+명 합산 문자열이면 "성"이 비게 되는 문제를 방지)
    "여권번호":          "여권",
    "passport_no":       "여권",
    "passport":          "여권",
    "여권만기일":         "만기",
    "expiry_date":       "만기",
    "expiry":            "만기",
    "여권발급일":         "발급",
    "등록증만기일":       "만기일",
    "등록증발급일":       "발급일",
    "전화번호":          "__phone__",  # 단일 전화번호 문자열 → 분리 처리
    "phone":             "__phone__",
    "nationality":       "국적",
    "nation":            "국적",
    "gender":            "성별",
    "sex":               "성별",
    "생년월일":          "생년월일",  # 시트 컬럼 없음 — 저장 제외
    "birth_date":        "생년월일",
    "dob":               "생년월일",
}

# 저장하지 않을 필드 (시트 컬럼 없거나 내부 처리용)
_SKIP_FIELDS = {"생년월일", "raw_mrz", "error", "국가"}


def _split_phone_str(phone: str) -> dict:
    """전화번호 문자열 → {연, 락, 처}"""
    parts = phone.replace(" ", "").split("-")
    if len(parts) == 3:
        return {"연": parts[0], "락": parts[1], "처": parts[2]}
    if len(parts) == 2:
        return {"연": parts[0], "락": parts[1], "처": ""}
    d = phone.replace(r"\D", "")
    d = "".join(c for c in phone if c.isdigit())
    if len(d) == 11:
        return {"연": d[:3], "락": d[3:7], "처": d[7:]}
    if len(d) == 10:
        return {"연": d[:3], "락": d[3:6], "처": d[6:]}
    return {"연": phone, "락": "", "처": ""}


def _normalize_fields(raw: dict) -> dict:
    """
    alias 정규화 + 날짜 정규화.
    raw: {필드명: 값} (frontend에서 온 editForm 그대로)
    반환: {실무 축약형 컬럼명: 정규화된 값}
    """
    date_fields = {"발급", "만기", "발급일", "만기일"}
    out: dict = {}
    for k, v in raw.items():
        v = str(v or "").strip()
        if not v:
            continue
        # alias 변환
        canonical = _FIELD_ALIASES.get(k, k)
        # 저장 제외 필드
        if canonical in _SKIP_FIELDS:
            continue
        # 전화번호 분리
        if canonical == "__phone__":
            parts = _split_phone_str(v)
            for pk, pv in parts.items():
                if pv:
                    out[pk] = pv
            continue
        # 날짜 정규화
        if canonical in date_fields:
            v = _normalize_ymd(v) or v
        out[canonical] = v
    return out


# ── upsert 엔드포인트 ─────────────────────────────────────────────────────────

@router.post("/register")
def scan_register(
    body: dict,
    user: dict = Depends(get_current_user),
):
    """
    OCR 결과를 고객 시트에 upsert (tenant 격리).

    - body: 프론트 editForm 그대로 수신 (축약형 키 또는 풀네임 키 모두 수용)
    - _normalize_fields()가 alias 변환 + 날짜 정규화를 담당
    - 여권(여권) 또는 등록증 앞/뒤(등록증+번호)로 기존 고객 탐색
    - 기존 고객 → 변경 필드만 batch_update (만기일만 바뀐 경우 안전)
    - 신규 고객 → 고객ID 발급 후 append

    core/customer_service.py의 upsert_customer_from_scan()은 Streamlit
    session_state를 직접 참조하므로 FastAPI에서 직접 호출 불가.
    tenant_service.get_worksheet()로 동일 로직 구현.
    """
    import logging
    _log = logging.getLogger("scan.register")

    from backend.services.tenant_service import get_worksheet
    from config import CUSTOMER_SHEET_NAME
    import pandas as pd

    tenant_id = user.get("tenant_id") or user.get("sub", "")

    # ── [INSTRUMENT] log incoming raw body ──────────────────────────────────
    _log.warning("[SCAN][BE] incoming raw body 만기일=%r  여권만기(만기)=%r",
                 body.get("만기일", "<missing>"), body.get("만기", "<missing>"))
    _log.warning("[SCAN][BE] incoming raw body keys: %s", list(body.keys()))
    # ────────────────────────────────────────────────────────────────────────

    # ── alias 정규화 + 날짜 정규화 ──
    data = _normalize_fields(body)

    # ── [INSTRUMENT] log normalized data ────────────────────────────────────
    _log.warning("[SCAN][BE] normalized 만기일=%r  (absent=skipped by _normalize_fields because empty)",
                 data.get("만기일", "<absent – was empty or missing in body>"))
    _log.warning("[SCAN][BE] normalized 만기(여권만기)=%r",
                 data.get("만기", "<absent>"))
    _log.warning("[SCAN][BE] full normalized data: %s", data)
    # ────────────────────────────────────────────────────────────────────────

    if not data:
        raise HTTPException(status_code=400, detail="upsert할 데이터가 없습니다.")

    # ── 시트 데이터 로드 ──────────────────────────────────────────
    try:
        ws = get_worksheet(CUSTOMER_SHEET_NAME, tenant_id)
        all_values = ws.get_all_values()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"시트 접근 실패: {str(e)}")

    if not all_values:
        raise HTTPException(status_code=500, detail="고객 시트가 비어 있습니다.")

    headers = all_values[0]
    rows    = all_values[1:]
    df = pd.DataFrame(rows, columns=headers)

    def norm(s): return str(s or "").strip()

    # ── 기존 고객 탐색 ────────────────────────────────────────────
    key_passport  = norm(data.get("여권", ""))
    key_reg_front = norm(data.get("등록증", ""))
    key_reg_back  = norm(data.get("번호", ""))

    hit_idx = None
    match_reason = None

    if key_passport and "여권" in df.columns:
        matches = df.index[df["여권"].astype(str).str.strip() == key_passport].tolist()
        if matches:
            hit_idx = matches[0]
            match_reason = f"passport match: 여권={key_passport!r}"

    if hit_idx is None and key_reg_front and key_reg_back:
        if "등록증" in df.columns and "번호" in df.columns:
            matches = df.index[
                (df["등록증"].astype(str).str.strip() == key_reg_front) &
                (df["번호"].astype(str).str.strip()   == key_reg_back)
            ].tolist()
            if matches:
                hit_idx = matches[0]
                match_reason = f"reg-number match: 등록증={key_reg_front!r} 번호={key_reg_back!r}"

    # ── [INSTRUMENT] log match result ───────────────────────────────────────
    if hit_idx is not None:
        _log.warning("[SCAN][BE] EXISTING CUSTOMER FOUND — hit_idx=%d reason=%s", hit_idx, match_reason)
    else:
        _log.warning("[SCAN][BE] NO MATCH — will create new customer")
        _log.warning("[SCAN][BE] search keys: passport=%r reg_front=%r reg_back=%r",
                     key_passport, key_reg_front, key_reg_back)
    # ────────────────────────────────────────────────────────────────────────

    # ── 컬럼 인덱스 헬퍼 ─────────────────────────────────────────
    def _col_letter(n: int) -> str:
        s = ""
        while n > 0:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s

    # ── 1) 기존 고객 업데이트 ────────────────────────────────────
    if hit_idx is not None:
        rownum = hit_idx + 2   # 헤더 1행 + 0-index 보정
        customer_id = str(df.at[hit_idx, "고객ID"]) if "고객ID" in df.columns else ""
        existing_만기일 = str(df.at[hit_idx, "만기일"]) if "만기일" in df.columns else "<col missing>"

        # ── [INSTRUMENT] log UPDATE path ──────────────────────────────────────
        _log.warning("[SCAN][BE] PATH=updated  customer_id=%r  row=%d  match=%s",
                     customer_id, rownum, match_reason)
        _log.warning("[SCAN][BE] existing sheet 만기일=%r  incoming normalized 만기일=%r",
                     existing_만기일,
                     data.get("만기일", "<absent – NOT being written, old value preserved>"))
        # ──────────────────────────────────────────────────────────────────────

        batch  = []
        for col_name, val in data.items():
            if col_name in headers:
                col_idx = headers.index(col_name) + 1  # 1-based
                cell    = f"{_col_letter(col_idx)}{rownum}"
                batch.append({"range": cell, "values": [[val]]})

        if batch:
            try:
                ws.batch_update(batch)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"고객 업데이트 실패: {str(e)}")

        return {
            "status": "updated",
            "고객ID": customer_id,
            "message": f"기존 고객({customer_id}) 정보가 업데이트되었습니다.",
        }

    # ── 2) 신규 고객 추가 ────────────────────────────────────────
    today_str = datetime.date.today().strftime("%Y%m%d")
    if "고객ID" in df.columns:
        today_ids = df["고객ID"].astype(str).str.strip()
        today_count = today_ids[today_ids.str.startswith(today_str)].shape[0]
    else:
        today_count = 0
    new_id = today_str + str(today_count + 1).zfill(2)

    base = {h: "" for h in headers}
    base["고객ID"] = new_id
    for k, v in data.items():
        if k in base:
            base[k] = v

    # ── [INSTRUMENT] log CREATE path ──────────────────────────────────────
    _log.warning("[SCAN][BE] PATH=created  new_id=%r", new_id)
    _log.warning("[SCAN][BE] new row 만기일=%r  만기(여권)=%r",
                 base.get("만기일", ""), base.get("만기", ""))
    _log.warning("[SCAN][BE] full new row (non-empty only): %s",
                 {k: v for k, v in base.items() if v})
    # ──────────────────────────────────────────────────────────────────────

    try:
        ws.append_row([base.get(h, "") for h in headers])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"고객 추가 실패: {str(e)}")

    return {
        "status": "created",
        "고객ID": new_id,
        "message": f"신규 고객이 추가되었습니다 (고객ID: {new_id}).",
    }
