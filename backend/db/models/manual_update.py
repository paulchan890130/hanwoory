"""Manual Update v1 — PostgreSQL models (single source of truth).

매뉴얼 자동 업데이트의 baseline / 변경결과 / 검토결정 / 상태를 PG 에 저장한다.
파일/Persistent Disk 의존을 제거하기 위한 테이블 묶음이다.

저장하지 않는 것: HWP/PDF 원본·검토 PDF 등 바이너리(이들은 /tmp 임시 또는 파일 뷰어).
저장하는 것: 텍스트/hash/page 메타, 변경 페이지, manual_ref 후보, 검토 decision, 실행 상태.

decision 보존 규칙(요약): manual_review_decisions 는 row_id 당 1행(현재 유효본)만 둔다.
직전 version 까지만 병합 대상이며, 2세대 이상 사라진 orphaned 는
manual_review_decisions_archive 로 옮긴다(active 에서 제거). 자세한 로직은
backend/services/manual_update_pg_service.py 참고.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer,
    LargeBinary, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


# ── baseline (기준 매뉴얼) ─────────────────────────────────────────────────────
class ManualBaseVersion(Base):
    """기준 매뉴얼 버전. 라벨(residence/visa/revision_history)별 1개만 is_active=True."""
    __tablename__ = "manual_base_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    manual_label: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("manual_label", "version", name="uq_manual_base_versions_label_version"),
        Index("idx_manual_base_versions_label_active", "manual_label", "is_active"),
    )


class ManualBasePage(Base):
    """baseline 페이지별 텍스트/hash (rhwp extract 결과). diff 기준."""
    __tablename__ = "manual_base_pages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    base_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("manual_base_versions.id", ondelete="CASCADE"), nullable=False
    )
    manual_label: Mapped[str] = mapped_column(Text, nullable=False)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)  # rhwp_page_index
    printed_page_no: Mapped[int | None] = mapped_column(Integer)
    title_guess: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str | None] = mapped_column(Text)
    text_hash: Mapped[str | None] = mapped_column(Text)
    normalized_text_hash: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("idx_manual_base_pages_ver_page", "base_version_id", "page_index"),
        Index("idx_manual_base_pages_nhash", "normalized_text_hash"),
    )


class ManualBaseRef(Base):
    """baseline 시점 manual_ref 미러(읽기전용 스냅샷). 후보 생성의 diff 기준.
    immigration_guidelines_db_v2.json 은 절대 수정하지 않고 여기로 복사만 한다."""
    __tablename__ = "manual_base_refs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    row_id: Mapped[str] = mapped_column(Text, nullable=False)
    item_index: Mapped[int | None] = mapped_column(Integer)
    manual_label: Mapped[str | None] = mapped_column(Text)
    manual_kr: Mapped[str | None] = mapped_column(Text)  # 체류민원/사증민원
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    match_text: Mapped[str | None] = mapped_column(Text)
    match_type: Mapped[str | None] = mapped_column(Text)
    detailed_code: Mapped[str | None] = mapped_column(Text)
    business_name: Mapped[str | None] = mapped_column(Text)
    major_action_std: Mapped[str | None] = mapped_column(Text)
    snapshot_tag: Mapped[str | None] = mapped_column(Text)  # 적재 식별(예: 260414)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("idx_manual_base_refs_row", "row_id"),
        Index("idx_manual_base_refs_label", "manual_label"),
    )


# ── 실행/버전/변경결과 ────────────────────────────────────────────────────────
class ManualUpdateRun(Base):
    """매 자동 실행 1행(이력)."""
    __tablename__ = "manual_update_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    trigger: Mapped[str | None] = mapped_column(Text)  # cron|web|manual
    status: Mapped[str | None] = mapped_column(Text)   # running|no_change|staged|error
    detected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    detected_version: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    instance: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_manual_update_runs_run_at", "run_at"),
    )


class ManualUpdateVersion(Base):
    """감지된 업데이트 버전(admin 목록의 단위)."""
    __tablename__ = "manual_update_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    label_timestamps: Mapped[dict | None] = mapped_column(JSONB)  # {label: hikorea ts}
    changed_page_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str | None] = mapped_column(Text)  # staged|...
    run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("manual_update_runs.id", ondelete="SET NULL")
    )

    __table_args__ = (
        UniqueConstraint("version", name="uq_manual_update_versions_version"),
        Index("idx_manual_update_versions_detected", "detected_at"),
    )


class ManualUpdateChangedPage(Base):
    """버전별 변경 페이지(non-same)."""
    __tablename__ = "manual_update_changed_pages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    update_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("manual_update_versions.id", ondelete="CASCADE"), nullable=False
    )
    manual_label: Mapped[str | None] = mapped_column(Text)
    change_type: Mapped[str | None] = mapped_column(Text)  # modified|moved|added|deleted
    baseline_page: Mapped[int | None] = mapped_column(Integer)
    new_page: Mapped[int | None] = mapped_column(Integer)
    similarity: Mapped[float | None] = mapped_column(Float)
    new_snippet: Mapped[str | None] = mapped_column(Text)
    baseline_snippet: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("idx_manual_update_changed_ver", "update_version_id"),
    )


class ManualUpdateCandidate(Base):
    """버전별 영향 manual_ref 후보(변경 페이지에 연결된 항목만)."""
    __tablename__ = "manual_update_candidates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    update_version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("manual_update_versions.id", ondelete="CASCADE"), nullable=False
    )
    row_id: Mapped[str] = mapped_column(Text, nullable=False)
    item_index: Mapped[int | None] = mapped_column(Integer)
    manual_label: Mapped[str | None] = mapped_column(Text)
    old_page_from: Mapped[int | None] = mapped_column(Integer)
    old_page_to: Mapped[int | None] = mapped_column(Integer)
    candidate_page_from: Mapped[int | None] = mapped_column(Integer)
    candidate_page_to: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    change_type: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(Text)
    match_text: Mapped[str | None] = mapped_column(Text)
    new_snippet: Mapped[str | None] = mapped_column(Text)
    detailed_code: Mapped[str | None] = mapped_column(Text)
    business_name: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_manual_update_candidates_ver", "update_version_id"),
        Index("idx_manual_update_candidates_row", "row_id"),
    )


# ── 검토 decision (active + archive) ──────────────────────────────────────────
class ManualReviewDecision(Base):
    """현재 유효 검토결정 — row_id 당 1행. 직전 version 까지만 병합/보존."""
    __tablename__ = "manual_review_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    row_id: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str | None] = mapped_column(Text)
    decision_note: Mapped[str | None] = mapped_column(Text)
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    reviewed_candidate_page: Mapped[int | None] = mapped_column(Integer)
    manual_page_from: Mapped[int | None] = mapped_column(Integer)
    manual_page_to: Mapped[int | None] = mapped_column(Integer)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    source_version: Mapped[str | None] = mapped_column(Text)
    previous_version: Mapped[str | None] = mapped_column(Text)
    previous_decision_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    orphaned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    orphaned_at: Mapped[str | None] = mapped_column(Text)
    needs_recheck: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    candidate_changed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # 관리자 수동 페이지 지정(override) — 자동 추천(candidate/old page)과 별개로 보존(0013).
    # 값이 있으면 화면/diff/운영반영은 이 값을 '현재 검토 기준'으로 사용한다.
    reviewer_baseline_from: Mapped[int | None] = mapped_column(Integer)
    reviewer_baseline_to: Mapped[int | None] = mapped_column(Integer)
    reviewer_candidate_from: Mapped[int | None] = mapped_column(Integer)
    reviewer_candidate_to: Mapped[int | None] = mapped_column(Integer)
    reviewer_override_reason: Mapped[str | None] = mapped_column(Text)
    reviewer_override_by: Mapped[str | None] = mapped_column(Text)
    reviewer_override_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("row_id", name="uq_manual_review_decisions_row_id"),
        Index("idx_manual_review_decisions_source", "source_version"),
        Index("idx_manual_review_decisions_orphaned", "orphaned"),
    )


class ManualReviewDecisionArchive(Base):
    """2세대 이상 사라진 orphaned decision 보관소. admin 기본 화면 미표시(감사/복구용)."""
    __tablename__ = "manual_review_decisions_archive"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    row_id: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str | None] = mapped_column(Text)
    decision_note: Mapped[str | None] = mapped_column(Text)
    reviewed: Mapped[bool | None] = mapped_column(Boolean)
    reviewed_candidate_page: Mapped[int | None] = mapped_column(Integer)
    manual_page_from: Mapped[int | None] = mapped_column(Integer)
    manual_page_to: Mapped[int | None] = mapped_column(Integer)
    applied: Mapped[bool | None] = mapped_column(Boolean)
    source_version: Mapped[str | None] = mapped_column(Text)
    previous_version: Mapped[str | None] = mapped_column(Text)
    previous_decision_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    orphaned: Mapped[bool | None] = mapped_column(Boolean)
    orphaned_at: Mapped[str | None] = mapped_column(Text)
    needs_recheck: Mapped[bool | None] = mapped_column(Boolean)
    candidate_changed: Mapped[bool | None] = mapped_column(Boolean)
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    archived_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_manual_review_archive_row", "row_id"),
    )


# ── 상태(단일행) ──────────────────────────────────────────────────────────────
class ManualUpdateState(Base):
    """현재 자동화 상태(빠른 admin 읽기용 단일행, id=1)."""
    __tablename__ = "manual_update_state"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    status: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_date_kst: Mapped[str | None] = mapped_column(Text)
    last_checked_version: Mapped[str | None] = mapped_column(Text)
    last_detected_version: Mapped[str | None] = mapped_column(Text)
    last_staging_version: Mapped[str | None] = mapped_column(Text)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# ── PDF artifact 레지스트리 (변경 페이지 PDF 등 — viewer 우선사용 기반, Step 3) ──
class ManualPdfArtifact(Base):
    """생성된 PDF artifact 메타+blob. 변경 페이지 PDF 는 용량이 작아 PG bytea(pdf_blob)
    저장을 우선하고, full PDF 등 대용량은 pdf_path 로 둘 수 있게 둘 다 nullable.
    원본 HWP/HWPX 는 저장하지 않는다(처리 후 삭제)."""
    __tablename__ = "manual_pdf_artifacts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int | None] = mapped_column(BigInteger)          # manual_update_runs.id (느슨 참조)
    manual: Mapped[str] = mapped_column(Text, nullable=False)        # visa | stay
    version: Mapped[str | None] = mapped_column(Text)               # 예 260601
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)  # changed_page|changed_page_bundle|full_pdf
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'staging'"))  # staging|production|deployed_fallback
    page_from: Mapped[int | None] = mapped_column(Integer)
    page_to: Mapped[int | None] = mapped_column(Integer)
    page_numbers: Mapped[list | None] = mapped_column(JSONB)        # 비연속 페이지 목록
    pdf_blob: Mapped[bytes | None] = mapped_column(LargeBinary)     # bytea (changed-page PDF 우선)
    pdf_path: Mapped[str | None] = mapped_column(Text)              # 파일 저장소 확장 대비(nullable)
    page_count: Mapped[int | None] = mapped_column(Integer)
    file_size: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'generated'"))  # generated|failed|promoted
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_manual_pdf_artifacts_lookup", "manual", "version", "status"),
    )


# ── 매뉴얼 업데이트 알림 (첨부파일 제목 변동 → 전 사용자 최초 로그인 알림) ──────────
class ManualUpdateAlertEvent(Base):
    """첨부파일 제목 변동 감지 시 1건 생성되는 알림 이벤트.

    감지는 1일 1회(cron/admin 수동). 같은 manual+new_title_hash 는 멱등하게 1건만 둔다.
    로그인 시에는 이 테이블의 active 이벤트만 조회한다(무거운 감지 작업 미수행)."""
    __tablename__ = "manual_update_alert_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    manual: Mapped[str] = mapped_column(Text, nullable=False)          # visa | stay | revision_history
    old_title: Mapped[str | None] = mapped_column(Text)
    new_title: Mapped[str | None] = mapped_column(Text)
    old_title_hash: Mapped[str | None] = mapped_column(Text)
    new_title_hash: Mapped[str | None] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    version_label: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("manual", "new_title_hash", name="uq_manual_alert_manual_titlehash"),
        Index("idx_manual_alert_active", "is_active", "detected_at"),
    )


class ManualUpdateAlertDismissal(Base):
    """사용자별 '이번 업데이트 다시 알리지 않음'. login_id 당 event 1회.

    현재 event 만 숨긴다(전역 영구차단 아님). 새 alert_event 가 생기면 다시 대상이 된다."""
    __tablename__ = "manual_update_alert_dismissals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alert_event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("manual_update_alert_events.id", ondelete="CASCADE"), nullable=False
    )
    login_id: Mapped[str] = mapped_column(Text, nullable=False)
    dismissed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dismiss_type: Mapped[str | None] = mapped_column(Text)            # this_update

    __table_args__ = (
        UniqueConstraint("alert_event_id", "login_id", name="uq_manual_alert_dismissal"),
        Index("idx_manual_alert_dismissal_user", "login_id"),
    )
