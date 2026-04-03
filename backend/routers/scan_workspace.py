import io
import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.auth import get_current_user
from backend.routers.scan import _ensure_tesseract
from backend.services.roi_ocr_service import (
    extract_arc_field,
    extract_arc_fields,
    extract_passport_roi,
    file_bytes_to_pil,
)

router = APIRouter()


@router.post("/render-pdf")
async def render_pdf_page(
    file: UploadFile = File(...),
    page: int = Form(default=0),
    dpi: int = Form(default=200),
    user: dict = Depends(get_current_user),
):
    """PDF 특정 페이지를 PNG 이미지로 렌더링하여 반환"""
    _ = user
    try:
        import fitz  # pymupdf
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="pymupdf가 설치되지 않았습니다.") from exc

    pdf_bytes = await file.read()
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF 열기 실패: {exc}") from exc

    total_pages = len(doc)
    if total_pages == 0:
        raise HTTPException(status_code=400, detail="페이지가 없는 PDF입니다.")
    if page >= total_pages:
        page = 0

    scale = dpi / 72.0  # PDF 기본 단위는 72dpi
    mat = fitz.Matrix(scale, scale)
    pix = doc.load_page(page).get_pixmap(matrix=mat, alpha=False)
    png_bytes = pix.tobytes("png")
    doc.close()

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

    try:
        img = file_bytes_to_pil(img_bytes, file.content_type or "")
        roi = _parse_json_dict(roi_json, DEFAULT_PASSPORT_MRZ_ROI)
        result = extract_passport_roi(img, roi, rotation_deg=rotation_deg)
        debug = result.pop("_debug", {})
        return {"result": result, "roi": roi, "debug": debug}
    except HTTPException:
        raise
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

    try:
        img = file_bytes_to_pil(img_bytes, file.content_type or "")

        # 1) 단일 필드 추출
        if field:
            field = field.strip()
            if field not in ARC_ALLOWED_FIELDS:
                raise HTTPException(status_code=400, detail=f"허용되지 않은 필드입니다: {field}")

            roi = _parse_json_dict(roi_json, DEFAULT_ARC_ROI)
            value, debug = extract_arc_field(img, field, roi, rotation_deg=rotation_deg)
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

        result = extract_arc_fields(img, rois, fields)
        return {"result": result, "rois": rois, "fields": fields or []}

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"등록증 작업판 OCR 실패: {exc}") from exc