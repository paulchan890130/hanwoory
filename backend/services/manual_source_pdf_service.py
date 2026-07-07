"""원문 매뉴얼 PDF 저장소 서비스 (migration 0029, PG BYTEA).

정책: manual_type(visa/stay)별 **최신 1개 + 직전 1개만** 보관.
새 업로드 → 새 행 is_current=True, 기존 최신 → 직전(is_current=False),
2개 초과분(가장 오래된 것)은 삭제. 전 과정 단일 트랜잭션.

OOM 규칙(웹 컨테이너): 목록 조회는 ``defer(pdf_data)`` — blob 을 bulk SELECT 하지
않는다. blob 은 ``get_blob(id)`` 단건 조회로만 가져온다.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import defer

from backend.db.models.manual_source_pdf import ManualSourcePdf

ALLOWED_TYPES = ("visa", "stay")
MAX_FILE_SIZE = 50 * 1024 * 1024   # 50MB — 매뉴얼 PDF 실측 ≈ 12MB
KEEP_PER_TYPE = 2                  # 최신 + 직전


class SourcePdfError(ValueError):
    """업로드 검증 실패 (라우터가 400 으로 변환)."""


def _SL():
    from backend.db.session import get_sessionmaker
    return get_sessionmaker()()


def _to_meta(r: ManualSourcePdf) -> dict:
    return {
        "id": r.id,
        "manual_type": r.manual_type,
        "version_label": r.version_label or "",
        "original_filename": r.original_filename,
        "content_type": r.content_type,
        "file_size": r.file_size,
        "sha256": r.sha256,
        "page_count": r.page_count,
        "is_current": bool(r.is_current),
        "uploaded_by": r.uploaded_by or "",
        "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else "",
        "notes": r.notes or "",
    }


def _validate_pdf(data: bytes, original_filename: str) -> int:
    """PDF 검증(확장자 + magic + PyMuPDF open) 후 page_count 반환. 실패 시 SourcePdfError."""
    if not (original_filename or "").lower().endswith(".pdf"):
        raise SourcePdfError("PDF 파일(.pdf)만 업로드할 수 있습니다.")
    if not data:
        raise SourcePdfError("빈 파일입니다.")
    if len(data) > MAX_FILE_SIZE:
        raise SourcePdfError(f"파일이 너무 큽니다 (최대 {MAX_FILE_SIZE // (1024*1024)}MB).")
    if not data.startswith(b"%PDF-"):
        raise SourcePdfError("PDF 형식이 아닙니다 (magic header 불일치).")
    try:
        import fitz
        with fitz.open(stream=data, filetype="pdf") as doc:
            n = doc.page_count
        if n <= 0:
            raise SourcePdfError("페이지가 없는 PDF 입니다.")
        return n
    except SourcePdfError:
        raise
    except Exception:
        raise SourcePdfError("PDF 를 열 수 없습니다 (손상/암호화 여부 확인).")


def upload_pdf(manual_type: str, data: bytes, original_filename: str,
               version_label: str = "", uploaded_by: str = "",
               notes: str = "") -> dict:
    """새 원문 PDF 저장 + retention(최신/직전 2개만) 강제. 반환 = 저장된 행 메타."""
    mt = (manual_type or "").strip().lower()
    if mt not in ALLOWED_TYPES:
        raise SourcePdfError(f"manual_type 은 {ALLOWED_TYPES} 만 허용됩니다.")
    page_count = _validate_pdf(data, original_filename)
    digest = hashlib.sha256(data).hexdigest()

    with _SL() as s:
        # 기존 최신 → 직전
        prev_current = s.scalars(
            select(ManualSourcePdf)
            .options(defer(ManualSourcePdf.pdf_data))
            .where(ManualSourcePdf.manual_type == mt, ManualSourcePdf.is_current.is_(True))
        ).all()
        for r in prev_current:
            r.is_current = False

        row = ManualSourcePdf(
            manual_type=mt,
            version_label=(version_label or "").strip() or None,
            original_filename=original_filename.strip(),
            content_type="application/pdf",
            file_size=len(data),
            sha256=digest,
            page_count=page_count,
            pdf_data=data,
            is_current=True,
            uploaded_by=(uploaded_by or "").strip() or None,
            notes=(notes or "").strip() or None,
        )
        s.add(row)
        s.flush()   # id 채번 (retention 정렬에 필요)

        # retention: 같은 manual_type 에서 최신 KEEP_PER_TYPE 개만 유지 (id 내림차순)
        rows = s.scalars(
            select(ManualSourcePdf)
            .options(defer(ManualSourcePdf.pdf_data))
            .where(ManualSourcePdf.manual_type == mt)
            .order_by(ManualSourcePdf.id.desc())
        ).all()
        for old in rows[KEEP_PER_TYPE:]:
            s.delete(old)

        s.commit()
        s.refresh(row)
        return _to_meta(row)


def list_pdfs() -> dict:
    """{visa: [최신, 직전], stay: [...]} — blob 제외(defer)."""
    out: dict = {t: [] for t in ALLOWED_TYPES}
    with _SL() as s:
        rows = s.scalars(
            select(ManualSourcePdf)
            .options(defer(ManualSourcePdf.pdf_data))
            .order_by(ManualSourcePdf.manual_type.asc(), ManualSourcePdf.id.desc())
        ).all()
        for r in rows:
            if r.manual_type in out:
                out[r.manual_type].append(_to_meta(r))
    return out


def resolve_meta(manual_type: str, which: str) -> Optional[dict]:
    """manual_type + current|previous → 행 메타 (blob 제외). 없으면 None."""
    mt = (manual_type or "").strip().lower()
    if mt not in ALLOWED_TYPES or which not in ("current", "previous"):
        return None
    with _SL() as s:
        rows = s.scalars(
            select(ManualSourcePdf)
            .options(defer(ManualSourcePdf.pdf_data))
            .where(ManualSourcePdf.manual_type == mt)
            .order_by(ManualSourcePdf.id.desc())
            .limit(KEEP_PER_TYPE)
        ).all()
        idx = 0 if which == "current" else 1
        if len(rows) <= idx:
            return None
        return _to_meta(rows[idx])


def get_blob(pdf_id: int) -> Optional[tuple[dict, bytes]]:
    """id 단건으로 (메타, blob) 조회 — bulk SELECT 금지 규칙 준수."""
    with _SL() as s:
        r = s.get(ManualSourcePdf, int(pdf_id))
        if r is None:
            return None
        return _to_meta(r), r.pdf_data
