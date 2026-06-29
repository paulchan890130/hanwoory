"""관리자 최신 PDF 업로드 파이프라인 (PG 전용, web 컨테이너 OOM 방지 설계).

핵심 원칙:
  * web 컨테이너에서 전체 PDF 합성/스플라이스/저장(save) 금지 — 업로드 PDF 는 '저장(blob) +
    페이지별 텍스트 추출 + 비교'만 한다. PyMuPDF 로 페이지 텍스트만 읽고(get_text) doc.close().
  * 변경 감지는 PDF-to-PDF (이전 deployed 업로드 PDF vs 새 업로드 PDF). HWP 기반 baseline 과
    섞지 않는다 → 추출기 차이로 인한 false positive 방지. 동일 추출기/정규화로 양쪽을 만든다.
  * 후보/검토/승인은 기존 로직(compute_candidates / save_version / merge_decisions) 재사용.
  * 운영 반영(promote) 전까지 업로드 PDF 는 source='manual_upload'(검토용/운영 미반영).
  * 외부 저장소/Git 저장 안 함. node/playwright/generate_pdf.mjs 미사용.
"""
from __future__ import annotations

import hashlib
from typing import Optional

# 매뉴얼 코드 정규화
_MANUAL_NORM = {
    "visa": "visa", "사증민원": "visa",
    "stay": "stay", "residence": "stay", "체류민원": "stay",
    "revision_history": "revision_history", "수정이력": "revision_history",
}
_MANUAL_KR = {"visa": "사증민원", "stay": "체류민원", "revision_history": "수정이력"}

MAX_UPLOAD_BYTES = 80 * 1024 * 1024   # 80MB — 체류민원급 전체 PDF 여유 + 폭주 방지
STAGING_ARTIFACT_TYPE = "staging_full_pdf"
DEPLOYED_ARTIFACT_TYPE = "deployed_full_pdf"
UPLOAD_SOURCE = "manual_upload"
DEPLOYED_SOURCE = "deployed"
PREVIOUS_SOURCE = "previous"


def normalize_manual(manual: str) -> Optional[str]:
    return _MANUAL_NORM.get((manual or "").strip())


def manual_kr(manual: str) -> str:
    return _MANUAL_KR.get(manual, manual)


def _norm_hashes(text: str) -> tuple[str, str]:
    """text_hash, normalized_text_hash — rhwp 파이프라인과 동일 normalize 로 일관 유지."""
    from backend.scripts.manual_update_local import normalize
    t = text or ""
    th = hashlib.sha256(t.encode("utf-8")).hexdigest()
    nh = hashlib.sha256(normalize(t).encode("utf-8")).hexdigest()
    return th, nh


def extract_pages(pdf_bytes: bytes, manual_label: str) -> list[dict]:
    """업로드 PDF 의 페이지별 텍스트만 추출(렌더링/합성 없음). OCR 미사용(텍스트 PDF 기준).

    반환 dict 는 diff_pages/compute_candidates 가 기대하는 키를 갖춘다."""
    import fitz  # PyMuPDF
    pages: list[dict] = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for i in range(doc.page_count):
            page = doc.load_page(i)
            text = page.get_text() or ""
            th, nh = _norm_hashes(text)
            first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
            pages.append({
                "manual_label": manual_label,
                "rhwp_page_index": i + 1,          # 1-based
                "printed_page_no": i + 1,
                "title_guess": first_line[:80],
                "text": text,
                "text_hash": th,
                "normalized_text_hash": nh,
                "keywords": [],
            })
    finally:
        doc.close()
    return pages


def validate_pdf_file(temp_path: str) -> int:
    """PyMuPDF 로 열 수 있는지 + page_count>0 검증. 반환 page_count. 실패 시 ValueError."""
    import fitz
    try:
        doc = fitz.open(temp_path)
    except Exception as e:
        raise ValueError(f"PDF 파일을 열 수 없습니다: {e}")
    try:
        pc = doc.page_count
    finally:
        doc.close()
    if pc <= 0:
        raise ValueError("0페이지 PDF 는 업로드할 수 없습니다.")
    return pc


def _ref_label_for(manual: str, refs: list[dict]) -> str:
    """refs(manual_base_refs)에서 이 manual 에 해당하는 manual_label 을 찾아 반환.

    후보 생성 시 changed 페이지의 manual_label 과 ref.manual_label 이 같아야 매칭되므로,
    실제 refs 가 쓰는 라벨 문자열에 맞춘다(없으면 정규화 코드로 폴백)."""
    for r in refs:
        lbl = (r.get("manual_label") or "").strip()
        if lbl and _MANUAL_NORM.get(lbl) == manual:
            return lbl
    return manual


def _latest_deployed_pages(manual: str) -> Optional[list[dict]]:
    """가장 최근 deployed 업로드 PDF blob 을 다시 추출해 비교 baseline 으로 사용(PDF-to-PDF).

    없으면 None(=초기 baseline)."""
    from backend.services import manual_update_pg_service as svc
    arts = [a for a in svc.get_pdf_artifacts(manual=manual)
            if a.get("artifact_type") == DEPLOYED_ARTIFACT_TYPE and a.get("source") == DEPLOYED_SOURCE]
    if not arts:
        return None
    arts.sort(key=lambda a: (a.get("created_at") or ""), reverse=True)
    blob = svc.get_pdf_artifact_blob(arts[0]["id"])
    if not blob:
        return None
    refs = svc.load_base_refs()
    label = _ref_label_for(manual, refs)
    return extract_pages(blob, label)


def _is_review_splice_artifact(a: dict) -> bool:
    note = (a.get("note") or "")
    return (a.get("source") == "review_splice"
            or "purpose=review_splice" in note or "generator=pymupdf_splice" in note)


def _cleanup_prior_uploads(manual_norm: str, keep_artifact_id: int) -> dict:
    """새 업로드 성공 후 호출 — 같은 manual 의 이전 업로드/검토 임시 PDF 만 정리.

    삭제: 다른 manual_upload staging artifact(이전 업로드본) + review_splice(검토용 합성) artifact.
    보존: deployed_full_pdf(운영본)·previous(이전 운영본)·baseline·refs·decision history.
    → 같은 manual 의 active staging 업로드가 1개만 남는다."""
    from backend.services import manual_update_pg_service as svc
    removed = 0
    for a in svc.get_pdf_artifacts(manual=manual_norm):
        aid = a.get("id")
        if aid == keep_artifact_id:
            continue
        is_old_upload = (a.get("artifact_type") == STAGING_ARTIFACT_TYPE and a.get("source") == UPLOAD_SOURCE)
        if is_old_upload or _is_review_splice_artifact(a):
            try:
                svc.delete_pdf_artifact(aid); removed += 1
            except Exception:
                pass
    return {"removed": removed}


def process_upload(*, manual: str, version: str, temp_path: str, orig_filename: str = "",
                   uploaded_by: str = "", memo: str = "") -> dict:
    """업로드 PDF 검증 → blob 저장(staging) 만 수행(저장 우선, OOM 안전).

    무거운 텍스트 추출/변경 감지는 별도 단계(run_change_detection)로 분리한다 — 이 요청에서는
    전체 페이지 추출/PDF 합성/스플라이스를 하지 않는다. 저장 성공 후에만 이전 업로드본을 정리해
    실패 시 기존 업로드본을 잃지 않는다. 실패는 ValueError(라우터가 400)."""
    from backend.services import manual_update_pg_service as svc

    manual_norm = normalize_manual(manual)
    if manual_norm is None:
        raise ValueError("manual 은 visa / stay / revision_history 중 하나여야 합니다.")
    version = (version or "").strip()
    if not version:
        raise ValueError("version 을 입력하세요 (예: 260616).")

    page_count = validate_pdf_file(temp_path)   # 0페이지/손상 차단(PyMuPDF open, page_count만)
    with open(temp_path, "rb") as f:
        pdf_bytes = f.read()                     # 검증 통과분만 1회 읽기(크기 제한은 라우터에서)
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    file_size = len(pdf_bytes)
    note = (f"purpose=review_staging;uploaded_by={uploaded_by};sha256={sha};"
            f"orig={orig_filename};memo={memo};change_detection=pending")[:1000]

    # 1) 새 staging blob 저장 (저장만 — 합성/추출 없음).
    art = svc.save_pdf_artifact(
        manual=manual_norm, artifact_type=STAGING_ARTIFACT_TYPE, version=version,
        source=UPLOAD_SOURCE, page_from=1, page_to=page_count, page_numbers=None,
        pdf_blob=pdf_bytes, pdf_path=None, page_count=page_count,
        status="generated", note=note,
    )
    # 2) 저장 성공 후에만 이전 업로드본/검토 합성본 정리(deployed 는 보존).
    cleanup = _cleanup_prior_uploads(manual_norm, art.get("id"))

    return {"manual": manual_norm, "manual_kr": manual_kr(manual_norm), "version": version,
            "page_count": page_count, "file_size": file_size,
            "artifact_id": art.get("id"), "review_only": True,
            "change_detection": "pending", "prior_uploads_removed": cleanup.get("removed", 0),
            "supports_change_detection": manual_norm in ("visa", "stay")}


def run_change_detection(manual: str, version: str) -> dict:
    """업로드된 staging PDF 로 변경 감지 실행(별도 단계). PDF-to-PDF 비교 → 후보 생성.

    업로드 PDF 는 유지된다(실패해도 viewer 사용 가능). 무거운 추출/비교는 이 단계에서만.
    DB 연결 오류(SSL EOF 등) 시 1회만 재시도(blob 과다조회는 이미 제거됨 — 재시도로 덮지 않음).
    save_version 은 멱등 upsert 라 재시도가 중복을 만들지 않는다."""
    from sqlalchemy.exc import OperationalError
    try:
        return _run_change_detection_once(manual, version)
    except OperationalError:
        return _run_change_detection_once(manual, version)


def _run_change_detection_once(manual: str, version: str) -> dict:
    from backend.services import manual_update_pg_service as svc
    manual_norm = normalize_manual(manual)
    if manual_norm is None:
        raise ValueError("manual 은 visa / stay / revision_history 중 하나여야 합니다.")
    version = (version or "").strip()
    res = get_staging_blob(manual_norm, version)
    if res is None:
        raise ValueError("업로드된 검토용 PDF 가 없습니다. 먼저 PDF 를 업로드하세요.")
    pdf_bytes, _meta = res

    if manual_norm == "revision_history":
        return {"status": "no_diff", "manual": manual_norm, "version": version,
                "changed": 0, "candidates": 0,
                "message": "revision_history 는 변경 감지 대상이 아닙니다(업로드 보관만)."}

    refs = svc.load_base_refs()
    label = _ref_label_for(manual_norm, refs)
    new_pages = extract_pages(pdf_bytes, label)
    extracted = len(new_pages)
    baseline_pages = _latest_deployed_pages(manual_norm)
    if not baseline_pages:
        return {"status": "baseline_init", "manual": manual_norm, "version": version,
                "extracted_pages": extracted, "changed": 0, "candidates": 0,
                "message": "초기 PDF baseline — 비교 대상(이전 운영 PDF) 없음. 운영 반영 후 비교 기준이 됩니다."}
    from backend.scripts.manual_update_local import diff_pages
    all_changed = diff_pages(baseline_pages, new_pages)
    non_same = [c for c in all_changed if c.get("change_type") != "same"]
    candidates = svc.compute_candidates(all_changed, {label: new_pages}, refs)
    svc.save_version(version, {manual_norm: version}, non_same, candidates, None)
    svc.merge_decisions_for_version(version, candidates)
    # 이 버전을 staging 으로 표시 → 검토 화면 뷰(versions[0])와 운영반영 게이트
    # (_review_status 의 last_staging_version)를 일치시킨다. 누락 시 검토완료해도
    # 미검토가 잔존(다른 버전 기준)해 운영반영이 영구 차단되는 버그가 발생한다.
    svc.mark_staging_version(version, changed_count=len(non_same), candidate_count=len(candidates))
    return {"status": "ok", "manual": manual_norm, "version": version,
            "extracted_pages": extracted, "changed": len(non_same), "candidates": len(candidates)}


def get_staging_blob(manual: str, version: str = "") -> Optional[tuple[bytes, dict]]:
    """검토용 staging 업로드 PDF blob + 메타. version 미지정 시 최신."""
    manual_norm = normalize_manual(manual)
    if manual_norm is None:
        return None
    from backend.services import manual_update_pg_service as svc
    arts = [a for a in svc.get_pdf_artifacts(manual=manual_norm, version=version or None)
            if a.get("artifact_type") == STAGING_ARTIFACT_TYPE and a.get("source") == UPLOAD_SOURCE]
    if not arts:
        return None
    arts.sort(key=lambda a: (a.get("created_at") or ""), reverse=True)
    meta = arts[0]
    blob = svc.get_pdf_artifact_blob(meta["id"])
    if not blob:
        return None
    return blob, meta


def _resolve_upload_artifact(manual_norm: str, version: str = "") -> Optional[dict]:
    """후보 상세/검토 viewer 가 쓸 업로드 PDF artifact 메타 선택.

    우선순위: ① 해당 version 의 staging(manual_upload) → ② 최신 deployed(승격본). 없으면 None.
    반환 dict 에 _source(upload_staging|upload_deployed) / _review_only 부여."""
    from backend.services import manual_update_pg_service as svc
    arts = svc.get_pdf_artifacts(manual=manual_norm, version=version or None)
    staging = [a for a in arts if a.get("artifact_type") == STAGING_ARTIFACT_TYPE
               and a.get("source") == UPLOAD_SOURCE]
    if staging:
        staging.sort(key=lambda a: (a.get("created_at") or ""), reverse=True)
        m = dict(staging[0]); m["_source"] = "upload_staging"; m["_review_only"] = True
        return m
    deployed = [a for a in svc.get_pdf_artifacts(manual=manual_norm)
                if a.get("artifact_type") == DEPLOYED_ARTIFACT_TYPE and a.get("source") == DEPLOYED_SOURCE]
    if deployed:
        deployed.sort(key=lambda a: (a.get("created_at") or ""), reverse=True)
        m = dict(deployed[0]); m["_source"] = "upload_deployed"; m["_review_only"] = False
        return m
    return None


def resolve_review_pdf_meta(manual: str, version: str = "") -> Optional[dict]:
    """업로드 PDF 메타(blob 제외) — source/page_count/review_only/artifact_id. 없으면 None."""
    manual_norm = normalize_manual(manual)
    if manual_norm is None:
        return None
    m = _resolve_upload_artifact(manual_norm, version)
    if m is None:
        return None
    return {"source": m["_source"], "review_only": m["_review_only"],
            "page_count": m.get("page_count"), "artifact_id": m.get("id"),
            "version": m.get("version")}


def resolve_review_pdf(manual: str, version: str = "") -> Optional[dict]:
    """업로드 PDF blob + 메타 — pg_pdf 스트리밍용. 없으면 None(기존 resolver 로 폴백)."""
    manual_norm = normalize_manual(manual)
    if manual_norm is None:
        return None
    m = _resolve_upload_artifact(manual_norm, version)
    if m is None:
        return None
    from backend.services import manual_update_pg_service as svc
    blob = svc.get_pdf_artifact_blob(m["id"])
    if not blob:
        return None
    return {"blob": blob, "source": m["_source"], "review_only": m["_review_only"],
            "page_count": m.get("page_count")}


def list_uploads(manual: str = "") -> list[dict]:
    """업로드(staging/deployed/previous) PDF artifact 목록(메타만, blob 제외)."""
    from backend.services import manual_update_pg_service as svc
    manual_norm = normalize_manual(manual) if manual else None
    arts = svc.get_pdf_artifacts(manual=manual_norm)
    return [a for a in arts if a.get("artifact_type") in (STAGING_ARTIFACT_TYPE, DEPLOYED_ARTIFACT_TYPE)]


def promote(manual: str, version: str) -> dict:
    """staging 업로드 PDF → deployed 승격. 기존 deployed 는 previous 로 보존(rollback 대비).

    승격된 PDF 가 다음 업로드의 PDF-to-PDF 비교 baseline 이 된다."""
    manual_norm = normalize_manual(manual)
    if manual_norm is None:
        raise ValueError("manual 은 visa / stay / revision_history 중 하나여야 합니다.")
    from sqlalchemy import select
    from backend.db.session import get_sessionmaker
    from backend.db.models.manual_update import ManualPdfArtifact

    with get_sessionmaker()() as s:
        staging = s.scalars(
            select(ManualPdfArtifact).where(
                ManualPdfArtifact.manual == manual_norm,
                ManualPdfArtifact.version == version,
                ManualPdfArtifact.artifact_type == STAGING_ARTIFACT_TYPE,
                ManualPdfArtifact.source == UPLOAD_SOURCE,
            ).order_by(ManualPdfArtifact.created_at.desc())
        ).first()
        if staging is None:
            raise ValueError("승격할 업로드 PDF(staging)가 없습니다. 먼저 업로드하세요.")
        # 기존 deployed → previous (보존)
        prev = s.scalars(
            select(ManualPdfArtifact).where(
                ManualPdfArtifact.manual == manual_norm,
                ManualPdfArtifact.artifact_type == DEPLOYED_ARTIFACT_TYPE,
                ManualPdfArtifact.source == DEPLOYED_SOURCE,
            )
        ).all()
        for p in prev:
            p.source = PREVIOUS_SOURCE
            p.status = "promoted"
            p.note = (p.note or "") + ";demoted=previous"
        # staging → deployed
        staging.artifact_type = DEPLOYED_ARTIFACT_TYPE
        staging.source = DEPLOYED_SOURCE
        staging.status = "promoted"
        staging.note = (staging.note or "") + ";promoted=deployed"
        s.commit()
        return {"ok": True, "manual": manual_norm, "version": version,
                "deployed_artifact_id": staging.id, "previous_count": len(prev)}
