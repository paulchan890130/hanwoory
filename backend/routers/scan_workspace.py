import asyncio
import io
import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.auth import get_current_user
from backend.routers.scan import _ensure_tesseract
from backend.services.global_concurrency import (
    OCR_LOCK_KEY,
    OCR_WAIT_SECONDS,
    ConcurrencyBusy,
    global_limit,
)
from backend.services.roi_ocr_service import (
    extract_arc_field,
    extract_arc_fields,
    extract_passport_roi,
    file_bytes_to_pil,
)

router = APIRouter()

# [로컬 PoC — A안 보강] 동기 Tesseract OCR(pytesseract subprocess, CPU 바운드)이
# async 핸들러 안에서 직접 호출되면 이벤트루프 전체가 블로킹된다. 아래 OCR 엔드포인트는
# - asyncio.to_thread 로 워커스레드에 offload(이벤트루프 비블로킹),
# - asyncio.wait_for(25s) 로 한 건의 OCR 처리시간 상한,
# - global_limit(OCR_LOCK_KEY, wait_timeout=OCR_WAIT_SECONDS) 로 전역 동시수 1 + 대기:
#   스캔이 겹치면 즉시 거절하지 않고 앞 스캔이 끝날 때까지 순서를 기다렸다가 이어서 처리한다.
#   대기 시간을 넘긴 경우에만 사용자 친화 안내를 반환한다.
# 을 적용한다. 기존 backend/routers/scan.py(/api/scan/*)와 동일한 처리기 정책.
_OCR_TIME_BUDGET = 25.0
# PDF 미리보기 렌더링 한 건의 시간 상한(OCR 잠금과 무관).
_PDF_RENDER_TIME_BUDGET = 20.0
# 대기 초과 시 사용자에게 보일 친절한 안내(딱딱한 "작업 중"식 표현 지양).
_OCR_BUSY_MESSAGE = "스캔 요청이 겹쳐 잠시 대기 중입니다. 보통 몇 초 안에 이어서 처리됩니다."


@router.post("/render-pdf")
async def render_pdf_page(
    file: UploadFile = File(...),
    page: int = Form(default=0),
    dpi: int = Form(default=200),
    user: dict = Depends(get_current_user),
):
    """PDF 특정 페이지를 PNG 이미지로 렌더링하여 반환.

    [로컬 PoC] PyMuPDF 렌더링은 동기 CPU 작업이므로 async 핸들러에서 직접 돌리면
    이벤트루프를 잠깐 막는다 → asyncio.to_thread 로 offload(이벤트루프 비블로킹) +
    시간 상한. OCR 전역 잠금에는 묶지 않는다(미리보기는 잦은 가벼운 작업).
    """
    _ = user
    try:
        import fitz  # pymupdf
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="pymupdf가 설치되지 않았습니다.") from exc

    pdf_bytes = await file.read()

    def _render():
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            total = len(doc)
            if total == 0:
                raise ValueError("페이지가 없는 PDF입니다.")
            pg = page if 0 <= page < total else 0
            scale = dpi / 72.0  # PDF 기본 단위는 72dpi
            mat = fitz.Matrix(scale, scale)
            pix = doc.load_page(pg).get_pixmap(matrix=mat, alpha=False)
            return pix.tobytes("png"), total
        finally:
            doc.close()

    try:
        png_bytes, total_pages = await asyncio.wait_for(
            asyncio.to_thread(_render), timeout=_PDF_RENDER_TIME_BUDGET
        )
    except (asyncio.TimeoutError, asyncio.CancelledError):
        raise HTTPException(status_code=504, detail="PDF 미리보기 렌더링 시간이 초과되었습니다.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF 열기 실패: {exc}") from exc

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"X-PDF-Total-Pages": str(total_pages)},
    )


DEFAULT_PASSPORT_MRZ_ROI = {"x": 0.05, "y": 0.80, "w": 0.90, "h": 0.15}
DEFAULT_ARC_ROI = {"x": 0.10, "y": 0.10, "w": 0.80, "h": 0.18}
ARC_ALLOWED_FIELDS = {"한글", "등록증", "번호", "발급일", "만기일", "주소"}


def _parse_json_dict(raw: str | None, default: dict[str, Any]) -> dict[str, Any]:
    if not raw:
        return default.copy()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON 파싱 실패: {exc}") from exc

    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="JSON 객체 형식이어야 합니다.")

    return value


@router.post("/passport")
async def scan_workspace_passport(
    file: UploadFile = File(...),
    roi_json: str | None = Form(default=None),
    rotation_deg: int = Form(default=0),
    user: dict = Depends(get_current_user),
):
    _ = user

    _ensure_tesseract()
    img_bytes = await file.read()
    content_type = file.content_type or ""

    try:
        roi = _parse_json_dict(roi_json, DEFAULT_PASSPORT_MRZ_ROI)

        def _work():
            img = file_bytes_to_pil(img_bytes, content_type)
            return extract_passport_roi(img, roi, rotation_deg=rotation_deg)

        async with global_limit(OCR_LOCK_KEY, wait_timeout=OCR_WAIT_SECONDS):
            result = await asyncio.wait_for(asyncio.to_thread(_work), timeout=_OCR_TIME_BUDGET)
        debug = result.pop("_debug", {})
        return {"result": result, "roi": roi, "debug": debug}
    except HTTPException:
        raise
    except ConcurrencyBusy:
        raise HTTPException(status_code=503, detail=_OCR_BUSY_MESSAGE)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        raise HTTPException(status_code=504, detail="여권 OCR이 25초 서버 시간예산을 초과했습니다.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"여권 작업판 OCR 실패: {exc}") from exc


@router.post("/arc")
async def scan_workspace_arc(
    file: UploadFile = File(...),
    field: str | None = Form(default=None),
    roi_json: str | None = Form(default=None),
    rois_json: str | None = Form(default=None),
    fields_json: str | None = Form(default=None),
    rotation_deg: int = Form(default=0),
    user: dict = Depends(get_current_user),
):
    _ = user

    _ensure_tesseract()
    img_bytes = await file.read()
    content_type = file.content_type or ""

    try:
        # 1) 단일 필드 추출
        if field:
            field = field.strip()
            if field not in ARC_ALLOWED_FIELDS:
                raise HTTPException(status_code=400, detail=f"허용되지 않은 필드입니다: {field}")

            roi = _parse_json_dict(roi_json, DEFAULT_ARC_ROI)

            def _work_single():
                img = file_bytes_to_pil(img_bytes, content_type)
                return extract_arc_field(img, field, roi, rotation_deg=rotation_deg)

            async with global_limit(OCR_LOCK_KEY, wait_timeout=OCR_WAIT_SECONDS):
                value, debug = await asyncio.wait_for(
                    asyncio.to_thread(_work_single), timeout=_OCR_TIME_BUDGET
                )
            return {"field": field, "value": value, "roi": roi, "debug": debug}

        # 2) 다중 필드 추출 (확장용)
        rois = _parse_json_dict(rois_json, {})
        fields = None

        if fields_json:
            try:
                parsed_fields = json.loads(fields_json)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"fields_json 파싱 실패: {exc}") from exc

            if not isinstance(parsed_fields, list):
                raise HTTPException(status_code=400, detail="fields_json은 배열이어야 합니다.")

            fields = [str(v).strip() for v in parsed_fields if str(v).strip()]
            invalid = [v for v in fields if v not in ARC_ALLOWED_FIELDS]
            if invalid:
                raise HTTPException(
                    status_code=400,
                    detail=f"허용되지 않은 필드입니다: {', '.join(invalid)}",
                )

        def _work_multi():
            img = file_bytes_to_pil(img_bytes, content_type)
            return extract_arc_fields(img, rois, fields)

        async with global_limit(OCR_LOCK_KEY, wait_timeout=OCR_WAIT_SECONDS):
            result = await asyncio.wait_for(
                asyncio.to_thread(_work_multi), timeout=_OCR_TIME_BUDGET
            )
        return {"result": result, "rois": rois, "fields": fields or []}

    except HTTPException:
        raise
    except ConcurrencyBusy:
        raise HTTPException(status_code=503, detail=_OCR_BUSY_MESSAGE)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        raise HTTPException(status_code=504, detail="등록증 OCR이 25초 서버 시간예산을 초과했습니다.")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"등록증 작업판 OCR 실패: {exc}") from exc