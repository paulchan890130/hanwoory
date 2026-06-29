"""manual_update_pg_service — PostgreSQL repository for Manual Update v1.

manual update 의 단일 출처(PG)에 대한 모든 읽기/쓰기를 담당한다. 모든 함수는
DATABASE_URL 미설정 또는 FEATURE_PG_MANUAL_UPDATE=off 이면 안전하게 skip/no-op.

핵심 책임:
* run/state/version/changed_pages/candidates CRUD (+ bulk insert, transaction)
* 중복 실행 방지: state 단일행에 SELECT ... FOR UPDATE 행 잠금 + today-guard
* decision 병합/orphaned/archive (직전 version 까지만 보존)
* baseline 적재(upsert) 헬퍼 (CLI 가 사용)
* 후보 계산(compute_candidates) — manual_base_refs 기준

운영 manual_ref(immigration_guidelines_db_v2.json)는 절대 수정하지 않는다.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

KST = timezone(timedelta(hours=9))

# decision active 행에서 복제해 보존/archive 에 쓰는 필드 집합
_DECISION_FIELDS = (
    "row_id", "decision", "decision_note", "reviewed", "reviewed_candidate_page",
    "manual_page_from", "manual_page_to", "applied", "source_version",
    "previous_version", "previous_decision_snapshot", "orphaned", "orphaned_at",
    "needs_recheck", "candidate_changed",
)


# ── 가용성 ────────────────────────────────────────────────────────────────────
def pg_enabled() -> bool:
    """PG 연결됨 + FEATURE_PG_MANUAL_UPDATE=true 일 때만 True."""
    try:
        from backend.db.session import is_configured
        from backend.db.feature_flags import pg_manual_update_enabled
        return is_configured() and pg_manual_update_enabled()
    except Exception:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today_kst() -> str:
    return datetime.now(timezone.utc).astimezone(KST).strftime("%Y-%m-%d")


# ── state 단일행 ──────────────────────────────────────────────────────────────
def _get_or_create_state(session, *, for_update: bool = False):
    from sqlalchemy import select
    from backend.db.models.manual_update import ManualUpdateState
    stmt = select(ManualUpdateState).order_by(ManualUpdateState.id).limit(1)
    if for_update:
        stmt = stmt.with_for_update()
    row = session.scalars(stmt).first()
    if row is None:
        row = ManualUpdateState(status="never_run", needs_review=False)
        session.add(row)
        session.flush()
    return row


def get_baseline_summary() -> dict:
    """활성 baseline 요약: 라벨별 버전/페이지수 + manual_base_refs 건수.

    admin 화면이 '기준 DB 적재 완료'를 표시하는 데 사용. PG off 면 빈 요약."""
    if not pg_enabled():
        return {"loaded": False, "versions": [], "refs_count": 0, "total_pages": 0}
    from sqlalchemy import select, func as safunc
    from backend.db.models.manual_update import ManualBaseVersion, ManualBaseRef
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(ManualBaseVersion)
            .where(ManualBaseVersion.is_active.is_(True))
            .order_by(ManualBaseVersion.manual_label)
        ).all()
        versions = [{
            "manual_label": r.manual_label,
            "version": r.version,
            "page_count": r.page_count or 0,
        } for r in rows]
        refs_count = session.scalar(select(safunc.count()).select_from(ManualBaseRef)) or 0
        total_pages = sum(v["page_count"] for v in versions)
        return {
            "loaded": bool(versions),
            "versions": versions,
            "refs_count": int(refs_count),
            "total_pages": int(total_pages),
        }


# 사람이 "결정 완료"로 본 decision 들(검토 필요 집계에서 제외). UNRESOLVED/NEW_CANDIDATE/빈값은 pending.
_DECIDED = {
    "REVIEWED_APPROVE_CANDIDATE", "REVIEWED_KEEP_EXISTING",
    "REJECTED_BAD_CANDIDATE", "NEEDS_MANUAL_PAGE", "APPLIED",
}


def _review_status(session) -> dict:
    """최신 staging 버전 기준 검토 진행 상황을 실데이터로 재계산.

    needs_review(표시용)는 '미검토(pending) 후보 수 > 0' 으로 산출한다.
    - status 가 no_change/never_run/pg_disabled 면 항상 False.
    - 후보가 0건이면(영향 manual_ref 없음) 변경 페이지가 있어도 검토 필요 아니오 + 사유 표시.
    반환 키: latest_version, candidate_count, changed_count, reviewed_count, applied_count,
            pending_count, needs_review, review_reason.
    """
    from sqlalchemy import select, func as safunc
    from backend.db.models.manual_update import (
        ManualUpdateState, ManualUpdateVersion, ManualUpdateCandidate,
        ManualUpdateChangedPage, ManualReviewDecision,
    )
    st = session.scalars(
        select(ManualUpdateState).order_by(ManualUpdateState.id).limit(1)
    ).first()
    status = st.status if st else "never_run"
    latest = st.last_staging_version if st else None
    out = {
        "latest_version": latest, "candidate_count": 0, "changed_count": 0,
        "review_target_count": 0, "noop_count": 0,
        "reviewed_count": 0, "applied_count": 0, "pending_count": 0,
        "approved_pending_apply": 0, "needs_review": False, "review_reason": "",
        "source_status": status,
    }
    # 미검토 후보가 실제로 남아 있으면 status 와 무관하게 검토 필요로 본다(req 6/8).
    # latest staging 버전이 아예 없을 때만 즉시 '검토 필요 없음'으로 단정한다(req 7).
    if not latest or status in ("never_run", "pg_disabled"):
        out["review_reason"] = ("감지 이력 없음" if status == "never_run"
                                else "변경 없음 — 검토 필요 항목 없음" if status == "no_change"
                                else "")
        return out
    ver = session.scalars(
        select(ManualUpdateVersion).where(ManualUpdateVersion.version == latest)
    ).first()
    if not ver:
        out["review_reason"] = "최신 staging 버전 정보 없음"
        return out
    cand_rows = session.scalars(
        select(ManualUpdateCandidate).where(ManualUpdateCandidate.update_version_id == ver.id)
    ).all()
    changed_rows = session.scalars(
        select(ManualUpdateChangedPage).where(ManualUpdateChangedPage.update_version_id == ver.id)
    ).all()
    changed_count = len(changed_rows)
    # 분류용 인덱스((label, baseline_page) → changed dict)
    changed_idx = {}
    for cp in changed_rows:
        if cp.manual_label and cp.baseline_page is not None:
            changed_idx[(cp.manual_label, cp.baseline_page)] = {
                "change_type": cp.change_type, "similarity": cp.similarity}
    dec_by_row = {d.row_id: d for d in session.scalars(select(ManualReviewDecision)).all()}

    # 실질 검토 대상(=noop 아님) 기준으로 집계(req 10).
    review_targets = noop = reviewed = applied = pending = approved_pending = 0
    for c in cand_rows:
        cd = {
            "manual_label": c.manual_label, "old_page_from": c.old_page_from,
            "old_page_to": c.old_page_to, "candidate_page_from": c.candidate_page_from,
            "confidence": c.confidence, "action": c.action, "change_type": c.change_type,
        }
        cls = _classify_candidate(cd, changed_idx)
        d = dec_by_row.get(c.row_id)
        if not cls["needs_review"]:
            noop += 1
            continue
        review_targets += 1
        if d and d.applied:
            applied += 1; reviewed += 1
        elif d and d.decision in _DECIDED:
            reviewed += 1
            if d.decision in ("REVIEWED_APPROVE_CANDIDATE", "NEEDS_MANUAL_PAGE"):
                approved_pending += 1  # 승인했으나 아직 운영 반영 전
        else:
            pending += 1
    out.update({
        "candidate_count": len(cand_rows), "changed_count": int(changed_count),
        "review_target_count": review_targets, "noop_count": noop,
        "reviewed_count": reviewed, "applied_count": applied, "pending_count": pending,
        "approved_pending_apply": approved_pending,
        "needs_review": pending > 0,
    })
    if pending > 0:
        out["review_reason"] = f"실질 검토 대상 {review_targets}건 중 미검토 {pending}건 (no-op {noop}건 제외)"
    elif review_targets == 0:
        out["review_reason"] = (f"후보 {len(cand_rows)}건 모두 실질 변경 없음(no-op) — 검토 불필요"
                                if cand_rows else
                                (f"변경 페이지 {int(changed_count)}건 감지(영향 manual_ref 없음)"
                                 if changed_count else "변경 없음"))
    else:
        out["review_reason"] = (f"검토 대상 {review_targets}건 검토 완료"
                                + (f", 운영 반영 대기 {approved_pending}건" if approved_pending else f" (반영 {applied}건)"))
    return out


def get_review_status() -> dict:
    if not pg_enabled():
        return {"needs_review": False, "review_reason": "", "candidate_count": 0,
                "pending_count": 0, "reviewed_count": 0, "applied_count": 0,
                "changed_count": 0, "latest_version": None}
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        return _review_status(session)


def get_state_dict() -> dict:
    """admin 상태 조회용 dict. PG off 면 {'status':'pg_disabled'}.

    needs_review/review_reason 등은 최신 staging 버전의 실제 미검토 후보 수로 재계산해
    반환한다(저장된 state.needs_review 의 stale 값에 의존하지 않음)."""
    if not pg_enabled():
        return {"status": "pg_disabled", "needs_review": False, "review_reason": ""}
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        st = _get_or_create_state(session)
        rev = _review_status(session)
        session.commit()
        return {
            "status": st.status,
            "last_run_at": st.last_run_at.isoformat() if st.last_run_at else None,
            "last_success_at": st.last_success_at.isoformat() if st.last_success_at else None,
            "last_run_date_kst": st.last_run_date_kst,
            "last_checked_version": st.last_checked_version,
            "last_detected_version": st.last_detected_version,
            "last_staging_version": st.last_staging_version,
            # 표시용 needs_review 는 실데이터 재계산값을 사용(req 6/7/8).
            "needs_review": rev["needs_review"],
            "needs_review_stored": bool(st.needs_review),
            "review_reason": rev["review_reason"],
            "candidate_count": rev["candidate_count"],
            "changed_count": rev["changed_count"],
            "review_target_count": rev["review_target_count"],
            "noop_count": rev["noop_count"],
            "pending_count": rev["pending_count"],
            "reviewed_count": rev["reviewed_count"],
            "applied_count": rev["applied_count"],
            "approved_pending_apply": rev["approved_pending_apply"],
            "error": st.error,
            "updated_at": st.updated_at.isoformat() if st.updated_at else None,
        }


# ── run 시작/종료 (중복 실행 방지 = state 행 잠금 + today-guard) ────────────────
def start_run(trigger: str = "manual", *, force: bool = False,
              instance: Optional[str] = None) -> Optional[int]:
    """run 시작. state 단일행에 FOR UPDATE 행 잠금을 걸어 동시 실행을 직렬화하고,
    today-guard(같은 KST 날짜 재실행)면 None 반환(skip). 성공 시 run_id 반환."""
    if not pg_enabled():
        return None
    from backend.db.models.manual_update import ManualUpdateRun
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    today = _today_kst()
    with SessionLocal() as session:
        st = _get_or_create_state(session, for_update=True)  # 동시 실행 직렬화
        if not force and st.last_run_date_kst == today:
            session.commit()
            return None
        run = ManualUpdateRun(trigger=trigger, status="running", detected=False,
                              instance=instance, run_at=_now())
        session.add(run)
        session.flush()
        st.status = "running"
        st.last_run_at = _now()
        st.last_run_date_kst = today
        st.error = None
        session.commit()
        return run.id


def finish_no_change(run_id: int, checked_version: Optional[str] = None) -> None:
    if not pg_enabled():
        return
    from sqlalchemy import select
    from backend.db.models.manual_update import ManualUpdateRun
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        run = session.get(ManualUpdateRun, run_id)
        if run:
            run.status = "no_change"
            run.finished_at = _now()
        st = _get_or_create_state(session)
        st.status = "no_change"
        st.last_success_at = _now()
        st.last_checked_version = checked_version
        # 변경 없음이면 검토 필요는 아니오여야 한다(과거 staged run 의 stale 값 잔존 방지).
        st.needs_review = False
        session.commit()


def finish_error(run_id: int, error: str) -> None:
    if not pg_enabled():
        return
    from backend.db.models.manual_update import ManualUpdateRun
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        run = session.get(ManualUpdateRun, run_id)
        if run:
            run.status = "error"
            run.error = error[:2000]
            run.finished_at = _now()
        st = _get_or_create_state(session)
        st.status = "error"
        st.error = error[:2000]
        session.commit()


def finish_staged(run_id: int, version: str, changed_count: int,
                  candidate_count: int) -> None:
    if not pg_enabled():
        return
    from backend.db.models.manual_update import ManualUpdateRun
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        run = session.get(ManualUpdateRun, run_id)
        if run:
            run.status = "staged"
            run.detected = True
            run.detected_version = version
            run.finished_at = _now()
        st = _get_or_create_state(session)
        st.status = "staged"
        st.last_success_at = _now()
        st.last_detected_version = version
        st.last_staging_version = version
        st.last_checked_version = version
        st.needs_review = candidate_count > 0 or changed_count > 0
        session.commit()


def mark_staging_version(version: str, *, changed_count: int = 0,
                         candidate_count: int = 0) -> None:
    """run 없이 staging 버전을 state 에 반영(관리자 PDF 업로드 → 변경감지 경로용).

    `_review_status`/운영반영 게이트는 `last_staging_version` 기준으로 미검토를 집계하므로,
    변경감지로 새 버전을 save_version 한 뒤 이 함수로 last_staging_version 을 맞춰야
    '뷰 버전 ≠ 게이트 버전' 불일치(검토완료해도 미검토 잔존)가 발생하지 않는다.
    finish_staged 와 달리 run_id 가 없다(업로드 경로는 run 을 만들지 않음)."""
    if not pg_enabled():
        return
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        st = _get_or_create_state(session)
        st.status = "staged"
        st.last_staging_version = version
        st.last_detected_version = version
        st.last_checked_version = version
        st.needs_review = candidate_count > 0 or changed_count > 0
        st.updated_at = _now()
        session.commit()


# ── version + changed_pages + candidates 저장 (transaction) ───────────────────
def save_version(version: str, label_timestamps: dict, changed_pages: list[dict],
                 candidates: list[dict], run_id: Optional[int]) -> dict:
    """버전 1행 + 변경 페이지 + 후보를 한 트랜잭션으로 저장. 같은 version 재실행 시
    기존 version 행과 그 자식(CASCADE)을 교체한다. 반환: {version_id, changed, candidate}."""
    if not pg_enabled():
        return {"version_id": None, "changed": 0, "candidate": 0}
    from sqlalchemy import select, delete
    from backend.db.models.manual_update import (
        ManualUpdateVersion, ManualUpdateChangedPage, ManualUpdateCandidate,
    )
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        existing = session.scalars(
            select(ManualUpdateVersion).where(ManualUpdateVersion.version == version)
        ).first()
        if existing:
            # 자식은 FK CASCADE 로 함께 삭제됨
            session.delete(existing)
            session.flush()
        ver = ManualUpdateVersion(
            version=version, label_timestamps=label_timestamps,
            changed_page_count=len(changed_pages), candidate_count=len(candidates),
            status="staged", run_id=run_id, detected_at=_now(),
        )
        session.add(ver)
        session.flush()
        for cp in changed_pages:
            session.add(ManualUpdateChangedPage(
                update_version_id=ver.id,
                manual_label=cp.get("manual_label"),
                change_type=cp.get("change_type"),
                baseline_page=cp.get("baseline_page"),
                new_page=cp.get("new_page"),
                similarity=cp.get("similarity"),
                new_snippet=(cp.get("new_snippet") or "")[:240],
                baseline_snippet=(cp.get("baseline_snippet") or "")[:240],
                keywords=cp.get("keywords"),
            ))
        for c in candidates:
            session.add(ManualUpdateCandidate(
                update_version_id=ver.id,
                row_id=c.get("row_id"),
                item_index=c.get("item_index"),
                manual_label=c.get("manual_label"),
                old_page_from=c.get("old_page_from"),
                old_page_to=c.get("old_page_to"),
                candidate_page_from=c.get("candidate_page_from"),
                candidate_page_to=c.get("candidate_page_to"),
                reason=c.get("reason"),
                change_type=c.get("change_type"),
                confidence=c.get("confidence"),
                action=c.get("action"),
                match_text=c.get("match_text"),
                new_snippet=(c.get("new_snippet") or "")[:240],
                detailed_code=c.get("detailed_code"),
                business_name=c.get("business_name"),
            ))
        session.commit()
        return {"version_id": ver.id, "changed": len(changed_pages),
                "candidate": len(candidates)}


# ── decision 병합/orphaned/archive (직전 version 까지만 보존) ──────────────────
def _snapshot(d) -> dict:
    return {
        "decision": d.decision, "decision_note": d.decision_note,
        "reviewed": d.reviewed, "reviewed_candidate_page": d.reviewed_candidate_page,
        "manual_page_from": d.manual_page_from, "manual_page_to": d.manual_page_to,
        "applied": d.applied, "source_version": d.source_version,
    }


def merge_decisions_for_version(version: str, candidates: list[dict]) -> dict:
    """active decisions(=직전 세대)를 이번 version 의 candidates 와 병합.

    규칙:
    1. 새 candidates 에 row_id 존재 → 사람 결정 보존, source_version=version,
       previous_version=직전, previous_decision_snapshot=직전값 1개, orphaned 해제,
       후보 page 변동 시 candidate_changed/needs_recheck=True.
    2. 직전엔 있고 이번엔 없는 row_id:
       - 직전 orphaned=False → orphaned=True, orphaned_at=version (active 1회 표시)
       - 직전 orphaned=True  → archive 이동 후 active 에서 제거 (2세대)
    archive 전체를 다시 병합 대상으로 끌어오지 않는다(load 는 active 만).
    반환: {merged, orphaned_marked, archived}.
    """
    if not pg_enabled():
        return {"merged": 0, "orphaned_marked": 0, "archived": 0}
    from sqlalchemy import select
    from backend.db.models.manual_update import (
        ManualReviewDecision, ManualReviewDecisionArchive,
    )
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    cand_by_row = {c.get("row_id"): c for c in candidates if c.get("row_id")}
    merged = orphaned_marked = archived = 0
    with SessionLocal() as session:
        active = session.scalars(select(ManualReviewDecision)).all()
        active_by_row = {d.row_id: d for d in active}

        # 1) 이번에 다시 등장한 row_id → 병합 (orphaned 였어도 복귀)
        for row_id, c in cand_by_row.items():
            d = active_by_row.get(row_id)
            if d is None:
                continue
            prev = d.reviewed_candidate_page
            newp = c.get("candidate_page_from")
            changed = (prev is not None and newp is not None and int(prev) != int(newp))
            d.previous_decision_snapshot = _snapshot(d)
            d.previous_version = d.source_version
            d.source_version = version
            d.orphaned = False
            d.orphaned_at = None
            d.candidate_changed = bool(changed)
            d.needs_recheck = bool(changed)
            d.updated_at = _now()
            merged += 1

        # 2) 직전엔 있고 이번 candidates 에 없는 row_id
        for d in active:
            if d.row_id in cand_by_row:
                continue
            if not d.orphaned:
                d.orphaned = True
                d.orphaned_at = version
                d.needs_recheck = True
                d.previous_version = d.source_version
                d.updated_at = _now()
                orphaned_marked += 1
            else:
                # 2세대 orphaned → archive 이동 후 active 제거
                session.add(ManualReviewDecisionArchive(
                    archived_reason="orphaned 2nd generation (absent again)",
                    archived_at=_now(),
                    **{f: getattr(d, f) for f in _DECISION_FIELDS},
                ))
                session.delete(d)
                archived += 1
        session.commit()
    return {"merged": merged, "orphaned_marked": orphaned_marked, "archived": archived}


def upsert_decision(row_id: str, *, decision: str = "", decision_note: str = "",
                    reviewed: bool = True, reviewed_candidate_page: Optional[int] = None,
                    manual_page_from: Optional[int] = None,
                    manual_page_to: Optional[int] = None, applied: bool = False,
                    source_version: Optional[str] = None) -> dict:
    """사람 검토 결정 저장(향후 review-save/apply 엔드포인트가 사용). row_id 당 1행 upsert.
    이 함수는 운영 manual_ref(JSON)를 수정하지 않는다 — decision 저장만."""
    if not pg_enabled():
        return {"ok": False, "reason": "pg_disabled"}
    from sqlalchemy import select
    from backend.db.models.manual_update import ManualReviewDecision
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        d = session.scalars(
            select(ManualReviewDecision).where(ManualReviewDecision.row_id == row_id)
        ).first()
        if d is None:
            d = ManualReviewDecision(row_id=row_id)
            session.add(d)
        d.decision = decision
        d.decision_note = decision_note
        d.reviewed = reviewed
        d.reviewed_candidate_page = reviewed_candidate_page
        d.manual_page_from = manual_page_from
        d.manual_page_to = manual_page_to
        d.applied = applied
        if source_version is not None:
            d.source_version = source_version
        d.orphaned = False
        d.orphaned_at = None
        d.updated_at = _now()
        session.commit()
        return {"ok": True, "row_id": row_id}


def get_decision(row_id: str) -> Optional[dict]:
    """단일 decision 조회(없으면 None). 운영 반영 가드에서 사용."""
    if not pg_enabled():
        return None
    from sqlalchemy import select
    from backend.db.models.manual_update import ManualReviewDecision
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        d = session.scalars(
            select(ManualReviewDecision).where(ManualReviewDecision.row_id == row_id)
        ).first()
        if not d:
            return None
        return {"row_id": d.row_id, "decision": d.decision, "applied": bool(d.applied),
                "manual_page_from": d.manual_page_from, "manual_page_to": d.manual_page_to,
                "reviewed_candidate_page": d.reviewed_candidate_page}


def mark_decision_applied(row_id: str, page_from: int, page_to: int) -> dict:
    """운영 manual_ref 반영이 끝난 뒤 decision 행을 applied=APPLIED 로 기록.
    JSON(immigration DB) 자체는 라우터에서 수정한다(이 함수는 PG 상태만 갱신)."""
    if not pg_enabled():
        return {"ok": False, "reason": "pg_disabled"}
    from sqlalchemy import select
    from backend.db.models.manual_update import ManualReviewDecision
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        d = session.scalars(
            select(ManualReviewDecision).where(ManualReviewDecision.row_id == row_id)
        ).first()
        if d is None:
            d = ManualReviewDecision(row_id=row_id)
            session.add(d)
        d.decision = "APPLIED"
        d.applied = True
        d.reviewed = True
        d.manual_page_from = page_from
        d.manual_page_to = page_to
        d.needs_recheck = False
        d.updated_at = _now()
        session.commit()
        return {"ok": True, "row_id": row_id}


# ── 관리자 수동 페이지 지정(override) + 재추출/재비교 ─────────────────────────

def save_reviewer_override(row_id: str, *, baseline_from=None, baseline_to=None,
                           candidate_from=None, candidate_to=None,
                           reason: str = "", by: str = "") -> dict:
    """관리자 수동 페이지 지정 저장(자동 추천값은 candidate 테이블에 그대로 보존).
    운영 manual_ref(JSON)는 건드리지 않는다."""
    if not pg_enabled():
        return {"ok": False, "reason": "pg_disabled"}
    from sqlalchemy import select
    from backend.db.models.manual_update import ManualReviewDecision
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        d = session.scalars(
            select(ManualReviewDecision).where(ManualReviewDecision.row_id == row_id)
        ).first()
        if d is None:
            d = ManualReviewDecision(row_id=row_id)
            session.add(d)
        d.reviewer_baseline_from = baseline_from
        d.reviewer_baseline_to = baseline_to or baseline_from
        d.reviewer_candidate_from = candidate_from
        d.reviewer_candidate_to = candidate_to or candidate_from
        d.reviewer_override_reason = reason or None
        d.reviewer_override_by = by or None
        d.reviewer_override_at = _now()
        d.updated_at = _now()
        session.commit()
        return {"ok": True, "row_id": row_id,
                "reviewer_baseline_from": baseline_from, "reviewer_baseline_to": baseline_to or baseline_from,
                "reviewer_candidate_from": candidate_from, "reviewer_candidate_to": candidate_to or candidate_from}


def clear_reviewer_override(row_id: str) -> dict:
    """관리자 수동 지정 초기화(자동 추천값으로 복귀)."""
    if not pg_enabled():
        return {"ok": False, "reason": "pg_disabled"}
    from sqlalchemy import select
    from backend.db.models.manual_update import ManualReviewDecision
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        d = session.scalars(
            select(ManualReviewDecision).where(ManualReviewDecision.row_id == row_id)
        ).first()
        if d:
            d.reviewer_baseline_from = d.reviewer_baseline_to = None
            d.reviewer_candidate_from = d.reviewer_candidate_to = None
            d.reviewer_override_reason = None
            d.reviewer_override_by = None
            d.reviewer_override_at = None
            d.updated_at = _now()
            session.commit()
    return {"ok": True, "row_id": row_id}


def _baseline_text_for(label: str, pf: int, pt: int) -> str:
    pages = {p["rhwp_page_index"]: p for p in load_baseline_pages(label)} if label else {}
    return "\n".join((pages.get(p, {}).get("text") or "") for p in range(pf, (pt or pf) + 1)).strip()


def _candidate_text_for(version: str, label: str, pf: int, pt: int) -> tuple[str, bool]:
    """후보(신규) 페이지 텍스트 — PG에는 변경 페이지 스니펫(240자)만 있다.
    new_page 가 범위에 드는 변경 페이지의 new_snippet 을 모은다. (전체 본문 미보유)
    반환: (text, partial) — partial=True 면 스니펫 기반(전체 아님)."""
    snips = []
    for cp in get_changed_pages(version):
        if cp.get("manual_label") != label:
            continue
        np = cp.get("new_page")
        if np is not None and pf <= np <= (pt or pf):
            snips.append(f"[p.{np}] " + (cp.get("new_snippet") or ""))
    return ("\n".join(snips).strip(), True)


def _diff_segments(a: str, b: str) -> list[dict]:
    import difflib
    sm = difflib.SequenceMatcher(None, a or "", b or "")
    segs = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            segs.append({"op": "equal", "text": a[i1:i2]})
        elif op == "delete":
            segs.append({"op": "delete", "text": a[i1:i2]})
        elif op == "insert":
            segs.append({"op": "insert", "text": b[j1:j2]})
        else:
            segs.append({"op": "delete", "text": a[i1:i2]})
            segs.append({"op": "insert", "text": b[j1:j2]})
    return segs


def recompare(version: str, label: str, baseline_from: int, baseline_to: int,
              candidate_from: int, candidate_to: int) -> dict:
    """수동 지정 페이지 기준으로 기존/후보 텍스트를 재추출하고 diff 를 다시 계산.
    후보(신규) 텍스트는 변경 페이지 스니펫 기반(전체 본문 미보유 → partial)."""
    existing = _baseline_text_for(label, baseline_from, baseline_to)
    cand, partial = _candidate_text_for(version, label, candidate_from, candidate_to)
    return {
        "existing_text": existing,
        "candidate_text": cand,
        "candidate_partial": partial,
        "diff_segments": _diff_segments(existing[:1500], cand[:1500]),
        "has_text_change": existing.strip() != cand.strip(),
    }


# ── 후보 계산 (manual_base_refs 기준) ─────────────────────────────────────────
def compute_candidates(changed: list[dict], new_pages_by_label: dict[str, list[dict]],
                       refs: list[dict]) -> list[dict]:
    """변경 페이지에 연결된 manual_ref 만 후보로 산출. 파일 기반 make_ref_candidates 와
    동일한 로직(overlap 또는 충분히 구체적인 match_text 의 text-hit)이되 refs 는 PG 에서."""
    from backend.scripts.manual_update_local import normalize  # 순수 함수 재사용
    affected: dict[str, set[int]] = {}
    for c in changed:
        if c.get("change_type") == "same":
            continue
        lbl = c.get("manual_label")
        if not lbl:
            continue
        affected.setdefault(lbl, set())
        if c.get("baseline_page"):
            affected[lbl].add(c["baseline_page"])
        if c.get("new_page"):
            affected[lbl].add(c["new_page"])

    new_lookup = {
        lbl: {p["rhwp_page_index"]: p for p in rows}
        for lbl, rows in new_pages_by_label.items()
    }
    cands: list[dict] = []
    for ref in refs:
        lbl = ref.get("manual_label")
        if lbl not in affected:
            continue
        pf = int(ref.get("page_from") or 0)
        pt = int(ref.get("page_to") or 0)
        mt = (ref.get("match_text") or "").strip()
        overlap = any(p in affected[lbl] for p in range(pf, pt + 1))
        text_hit: list[int] = []
        if not overlap:
            norm = normalize(mt) if mt else ""
            if len(norm) >= 8:
                for pn in affected[lbl]:
                    pg = new_lookup.get(lbl, {}).get(pn)
                    if pg and norm in normalize(pg.get("text", "")):
                        text_hit.append(pn)
            if not text_hit:
                continue
        cand_pf, cand_pt = pf, pt
        new_snip = ""
        np = new_lookup.get(lbl, {}).get(pf or 1)
        if np:
            new_snip = np.get("text", "")[:140].replace("\n", " ")
        ctypes = sorted({
            c["change_type"] for c in changed
            if c.get("manual_label") == lbl
            and (c.get("baseline_page") in range(pf, pt + 1)
                 or c.get("new_page") in range(pf, pt + 1))
        })
        conf = "high" if ctypes == ["modified"] else "review"
        action = "review" if conf == "review" else "remap_candidate"
        if text_hit and not overlap:
            action = "review"
            cand_pf = cand_pt = text_hit[0]
            conf = "medium"
        cands.append({
            "row_id": ref.get("row_id"),
            "item_index": ref.get("item_index"),
            "manual_label": lbl,
            "old_page_from": pf, "old_page_to": pt,
            "candidate_page_from": cand_pf, "candidate_page_to": cand_pt,
            "reason": f"baseline pages {pf}-{pt} overlap changed "
                      f"{sorted(affected[lbl] & set(range(pf, pt + 1))) or text_hit}",
            "change_type": "+".join(ctypes) or "unknown",
            "confidence": conf,
            "action": action,
            "match_text": mt,
            "new_snippet": new_snip,
            "detailed_code": ref.get("detailed_code"),
            "business_name": ref.get("business_name"),
        })
    return cands


# ── baseline 적재 (CLI 사용) ──────────────────────────────────────────────────
def upsert_base_version(label: str, version: str, source_sha256: Optional[str],
                        page_count: int, pages: list[dict], *, note: str = "") -> int:
    """기준 버전 + 페이지 적재. 같은 라벨의 기존 active 는 is_active=False 로 강등,
    같은 (label,version) 행은 교체(페이지 CASCADE). 반환: base_version_id."""
    if not pg_enabled():
        raise RuntimeError("PG not enabled (DATABASE_URL + FEATURE_PG_MANUAL_UPDATE)")
    from sqlalchemy import select, update
    from backend.db.models.manual_update import (
        ManualBaseVersion, ManualBasePage,
    )
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # 같은 (label, version) 있으면 교체
        dup = session.scalars(
            select(ManualBaseVersion).where(
                ManualBaseVersion.manual_label == label,
                ManualBaseVersion.version == version,
            )
        ).first()
        if dup:
            session.delete(dup)
            session.flush()
        # 같은 라벨 기존 active 강등
        session.execute(
            update(ManualBaseVersion)
            .where(ManualBaseVersion.manual_label == label,
                   ManualBaseVersion.is_active.is_(True))
            .values(is_active=False)
        )
        bv = ManualBaseVersion(
            manual_label=label, version=version, source_sha256=source_sha256,
            page_count=page_count, is_active=True, note=note, created_at=_now(),
        )
        session.add(bv)
        session.flush()
        for p in pages:
            session.add(ManualBasePage(
                base_version_id=bv.id,
                manual_label=label,
                page_index=p.get("rhwp_page_index"),
                printed_page_no=p.get("printed_page_no"),
                title_guess=p.get("title_guess"),
                text=p.get("text"),
                text_hash=p.get("text_hash"),
                normalized_text_hash=p.get("normalized_text_hash"),
                keywords=p.get("keywords"),
            ))
        session.commit()
        return bv.id


def replace_base_refs(refs: list[dict], snapshot_tag: str = "") -> int:
    """manual_base_refs 전체를 교체(전량 삭제 후 재적재). immigration DB 미수정.
    반환: 적재 행 수."""
    if not pg_enabled():
        raise RuntimeError("PG not enabled")
    from sqlalchemy import delete
    from backend.db.models.manual_update import ManualBaseRef
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        session.execute(delete(ManualBaseRef))
        for r in refs:
            session.add(ManualBaseRef(
                row_id=r.get("row_id"),
                item_index=r.get("item_index"),
                manual_label=r.get("manual_label"),
                manual_kr=r.get("manual_kr"),
                page_from=r.get("page_from"),
                page_to=r.get("page_to"),
                match_text=r.get("match_text"),
                match_type=r.get("match_type"),
                detailed_code=r.get("detailed_code"),
                business_name=r.get("business_name"),
                major_action_std=r.get("major_action_std"),
                snapshot_tag=snapshot_tag,
                created_at=_now(),
            ))
        n = len(refs)
        session.commit()
        return n


def load_baseline_pages(label: str) -> list[dict]:
    """활성 baseline 의 페이지를 diff_pages 입력 형태로 반환."""
    if not pg_enabled():
        return []
    from sqlalchemy import select
    from backend.db.models.manual_update import ManualBaseVersion, ManualBasePage
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        bv = session.scalars(
            select(ManualBaseVersion).where(
                ManualBaseVersion.manual_label == label,
                ManualBaseVersion.is_active.is_(True),
            )
        ).first()
        if not bv:
            return []
        rows = session.scalars(
            select(ManualBasePage)
            .where(ManualBasePage.base_version_id == bv.id)
            .order_by(ManualBasePage.page_index)
        ).all()
        return [{
            "manual_label": r.manual_label,
            "rhwp_page_index": r.page_index,
            "printed_page_no": r.printed_page_no,
            "title_guess": r.title_guess,
            "text": r.text or "",
            "text_hash": r.text_hash,
            "normalized_text_hash": r.normalized_text_hash,
            "keywords": r.keywords or [],
        } for r in rows]


def load_base_refs() -> list[dict]:
    if not pg_enabled():
        return []
    from sqlalchemy import select
    from backend.db.models.manual_update import ManualBaseRef
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(select(ManualBaseRef)).all()
        return [{
            "row_id": r.row_id, "item_index": r.item_index,
            "manual_label": r.manual_label, "manual_kr": r.manual_kr,
            "page_from": r.page_from, "page_to": r.page_to,
            "match_text": r.match_text, "match_type": r.match_type,
            "detailed_code": r.detailed_code, "business_name": r.business_name,
            "major_action_std": r.major_action_std,
        } for r in rows]


# ── admin 읽기 ────────────────────────────────────────────────────────────────
def list_versions() -> list[dict]:
    if not pg_enabled():
        return []
    from sqlalchemy import select
    from backend.db.models.manual_update import ManualUpdateVersion
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(
            select(ManualUpdateVersion).order_by(ManualUpdateVersion.detected_at.desc())
        ).all()
        return [{
            "version": r.version,
            "detected_at": r.detected_at.isoformat() if r.detected_at else None,
            "changed_page_count": r.changed_page_count,
            "candidate_count": r.candidate_count,
            "status": r.status,
            "label_timestamps": r.label_timestamps or {},
        } for r in rows]


def get_changed_pages(version: str) -> list[dict]:
    if not pg_enabled():
        return []
    from sqlalchemy import select
    from backend.db.models.manual_update import (
        ManualUpdateVersion, ManualUpdateChangedPage,
    )
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        ver = session.scalars(
            select(ManualUpdateVersion).where(ManualUpdateVersion.version == version)
        ).first()
        if not ver:
            return []
        rows = session.scalars(
            select(ManualUpdateChangedPage)
            .where(ManualUpdateChangedPage.update_version_id == ver.id)
            .order_by(ManualUpdateChangedPage.id)
        ).all()
        return [{
            "manual_label": r.manual_label, "change_type": r.change_type,
            "baseline_page": r.baseline_page, "new_page": r.new_page,
            "similarity": r.similarity, "new_snippet": r.new_snippet,
            "baseline_snippet": r.baseline_snippet, "keywords": r.keywords or [],
        } for r in rows]


def get_candidates(version: str) -> list[dict]:
    if not pg_enabled():
        return []
    from sqlalchemy import select
    from backend.db.models.manual_update import (
        ManualUpdateVersion, ManualUpdateCandidate,
    )
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        ver = session.scalars(
            select(ManualUpdateVersion).where(ManualUpdateVersion.version == version)
        ).first()
        if not ver:
            return []
        rows = session.scalars(
            select(ManualUpdateCandidate)
            .where(ManualUpdateCandidate.update_version_id == ver.id)
            .order_by(ManualUpdateCandidate.id)
        ).all()
        return [{
            "row_id": r.row_id, "item_index": r.item_index,
            "manual_label": r.manual_label,
            "old_page_from": r.old_page_from, "old_page_to": r.old_page_to,
            "candidate_page_from": r.candidate_page_from,
            "candidate_page_to": r.candidate_page_to,
            "reason": r.reason, "change_type": r.change_type,
            "confidence": r.confidence, "action": r.action,
            "match_text": r.match_text, "new_snippet": r.new_snippet,
            "detailed_code": r.detailed_code, "business_name": r.business_name,
        } for r in rows]


# 같은 페이지 + modified 인데 유사도가 이 값 이상이면 '실질 변경 없음(no-op)'으로 본다.
NOOP_SIMILARITY = 0.95


def _classify_candidate(c: dict, changed_idx: dict) -> dict:
    """후보 1건을 분류. changed_idx: (label, baseline_page) → changed_page dict.

    change_kind:
      new(신규) | page_moved(페이지 변경) | text_changed(본문 변경) |
      uncertain(매칭 불확실) | noop(실질 변경 없음)
    needs_review = (noop 이 아님). 같은 페이지 + modified + 고유사도 → noop.
    """
    lbl = c.get("manual_label")
    opf = int(c.get("old_page_from") or 0)
    opt = int(c.get("old_page_to") or opf or 0)
    cpf = int(c.get("candidate_page_from") or 0)
    conf = c.get("confidence") or ""
    act = c.get("action") or ""
    ct = c.get("change_type") or ""
    overlap = [changed_idx[(lbl, p)] for p in range(opf, (opt or opf) + 1)
               if (lbl, p) in changed_idx]
    sims = [o.get("similarity") for o in overlap if o.get("similarity") is not None]
    sim_min = min(sims) if sims else None
    ctypes = {o.get("change_type") for o in overlap}
    page_changed = bool(cpf) and (opf != cpf)

    if "added" in ctypes or "added" in ct:
        kind = "new"
    elif page_changed or "moved" in ctypes:
        kind = "page_moved"
    elif conf != "high" or act == "review":
        kind = "uncertain"
    elif (ctypes <= {"modified"} or ct == "modified") and sim_min is not None and sim_min >= NOOP_SIMILARITY:
        kind = "noop"
    elif "modified" in ctypes or "modified" in ct:
        kind = "text_changed"
    else:
        kind = "noop"
    return {
        "change_kind": kind,
        "needs_review": kind != "noop",
        "similarity": sim_min,
        "page_changed": page_changed,
        "text_changed": kind == "text_changed",
        "changed_detail": overlap,
    }


def get_candidates_enriched(version: str) -> list[dict]:
    """후보 + 분류(change_kind/needs_review/similarity) + 겹치는 변경 페이지 스니펫."""
    if not pg_enabled():
        return []
    cands = get_candidates(version)
    changed = get_changed_pages(version)
    changed_idx = {}
    for cp in changed:
        if cp.get("manual_label") and cp.get("baseline_page") is not None:
            changed_idx[(cp["manual_label"], cp["baseline_page"])] = cp
    out = []
    for c in cands:
        out.append({**c, **_classify_candidate(c, changed_idx)})
    return out


def candidate_detail(version: str, row_id: str) -> Optional[dict]:
    """후보 1건의 상세(3단 비교용): 기존 baseline 전체 텍스트 + 후보 스니펫 + 분류.

    기존 본문 = manual_base_pages 의 old_page_from..old_page_to 전체 텍스트.
    후보 본문 = 겹치는 변경 페이지의 new_snippet(없으면 candidate.new_snippet).
    """
    if not pg_enabled():
        return None
    enriched = {c["row_id"]: c for c in get_candidates_enriched(version)}
    c = enriched.get(row_id)
    if not c:
        return None
    lbl = c.get("manual_label")
    opf = int(c.get("old_page_from") or 0)
    opt = int(c.get("old_page_to") or opf or 0)
    base_pages = {p["rhwp_page_index"]: p for p in load_baseline_pages(lbl)} if lbl else {}
    base_text = "\n".join(
        (base_pages.get(p, {}).get("text") or "") for p in range(opf, (opt or opf) + 1)
    ).strip()
    base_titles = [base_pages.get(p, {}).get("title_guess") for p in range(opf, (opt or opf) + 1)]
    base_title = next((t for t in base_titles if t), "") or ""
    cand_text = "\n".join(
        (o.get("new_snippet") or "") for o in c.get("changed_detail", [])
    ).strip() or (c.get("new_snippet") or "")
    return {
        "row_id": row_id,
        "manual_label": lbl,
        "change_kind": c.get("change_kind"),
        "needs_review": c.get("needs_review"),
        "similarity": c.get("similarity"),
        "existing": {
            "title": base_title, "code": c.get("detailed_code"),
            "page_from": c.get("old_page_from"), "page_to": c.get("old_page_to"),
            "manual_ref": f"{c.get('old_page_from')}-{c.get('old_page_to')}",
            "match_text": c.get("match_text") or "",
            "text": base_text,
        },
        "candidate": {
            "code": c.get("detailed_code"),
            "page_from": c.get("candidate_page_from"), "page_to": c.get("candidate_page_to"),
            "staging": f"{c.get('candidate_page_from')}-{c.get('candidate_page_to')}",
            "text": cand_text,
        },
        "changed_pages": c.get("changed_detail", []),
    }


def get_active_decisions() -> list[dict]:
    """admin 기본 화면용 — 현재 유효 decision + 이번 version 에서 막 orphaned 된 1회분.
    archive 및 과거 orphaned 는 제외(쿼리에서 자동 제외)."""
    if not pg_enabled():
        return []
    from sqlalchemy import select, or_, and_
    from backend.db.models.manual_update import (
        ManualReviewDecision, ManualUpdateState,
    )
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        st = session.scalars(
            select(ManualUpdateState).order_by(ManualUpdateState.id).limit(1)
        ).first()
        latest = st.last_staging_version if st else None
        stmt = select(ManualReviewDecision).where(
            or_(
                ManualReviewDecision.orphaned.is_(False),
                and_(
                    ManualReviewDecision.orphaned.is_(True),
                    ManualReviewDecision.orphaned_at == latest,
                ),
            )
        ).order_by(ManualReviewDecision.row_id)
        rows = session.scalars(stmt).all()
        return [{
            "row_id": r.row_id, "decision": r.decision,
            "decision_note": r.decision_note, "reviewed": bool(r.reviewed),
            "reviewed_candidate_page": r.reviewed_candidate_page,
            "manual_page_from": r.manual_page_from, "manual_page_to": r.manual_page_to,
            "applied": bool(r.applied), "source_version": r.source_version,
            "previous_version": r.previous_version,
            "orphaned": bool(r.orphaned), "orphaned_at": r.orphaned_at,
            "needs_recheck": bool(r.needs_recheck),
            "candidate_changed": bool(r.candidate_changed),
            "reviewer_baseline_from": r.reviewer_baseline_from, "reviewer_baseline_to": r.reviewer_baseline_to,
            "reviewer_candidate_from": r.reviewer_candidate_from, "reviewer_candidate_to": r.reviewer_candidate_to,
            "reviewer_override_reason": r.reviewer_override_reason, "reviewer_override_by": r.reviewer_override_by,
            "reviewer_override_at": r.reviewer_override_at.isoformat() if r.reviewer_override_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        } for r in rows]


# ── PDF artifact 레지스트리 (Step 3) ─────────────────────────────────────────
def _artifact_to_dict(a, *, with_blob: bool = False) -> dict:
    d = {
        "id": a.id, "run_id": a.run_id, "manual": a.manual, "version": a.version,
        "artifact_type": a.artifact_type, "source": a.source,
        "page_from": a.page_from, "page_to": a.page_to, "page_numbers": a.page_numbers,
        "pdf_path": a.pdf_path, "page_count": a.page_count, "file_size": a.file_size,
        "content_hash": a.content_hash, "status": a.status, "note": a.note,
        # ⚠ pdf_blob 컬럼을 절대 만지지 않는다(메타 조회 시 거대한 bytea 적재 → SSL EOF/OOM).
        #   blob 존재 여부는 file_size 프록시로 판정(save 시 blob 있으면 file_size 설정됨).
        "has_blob": bool(a.file_size),
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }
    if with_blob:
        d["pdf_blob"] = a.pdf_blob
    return d


def save_pdf_artifact(*, manual: str, artifact_type: str, version: str | None = None,
                      run_id: int | None = None, source: str = "staging",
                      page_from: int | None = None, page_to: int | None = None,
                      page_numbers: list | None = None, pdf_blob: bytes | None = None,
                      pdf_path: str | None = None, page_count: int | None = None,
                      status: str = "generated", note: str = "") -> dict:
    """PDF artifact 1건 기록. content_hash/file_size 는 blob 으로부터 자동 산출."""
    if not pg_enabled():
        return {"ok": False, "reason": "pg_disabled"}
    import hashlib
    from backend.db.models.manual_update import ManualPdfArtifact
    from backend.db.session import get_sessionmaker
    fsize = len(pdf_blob) if pdf_blob is not None else None
    chash = hashlib.sha256(pdf_blob).hexdigest() if pdf_blob is not None else None
    with get_sessionmaker()() as session:
        a = ManualPdfArtifact(
            manual=manual, artifact_type=artifact_type, version=version, run_id=run_id,
            source=source, page_from=page_from, page_to=page_to, page_numbers=page_numbers,
            pdf_blob=pdf_blob, pdf_path=pdf_path, page_count=page_count,
            file_size=fsize, content_hash=chash, status=status, note=note or None,
        )
        session.add(a)
        session.commit()
        session.refresh(a)
        return _artifact_to_dict(a)


def get_pdf_artifacts(manual: str | None = None, version: str | None = None) -> list[dict]:
    """artifact 목록(메타데이터만 — pdf_blob 미적재). manual/version 으로 선택 필터.

    ⚠ pdf_blob(bytea)은 절대 함께 SELECT 하지 않는다(여러 PDF blob 동시 적재 → SSL EOF/OOM)."""
    if not pg_enabled():
        return []
    from sqlalchemy import select
    from sqlalchemy.orm import defer
    from backend.db.models.manual_update import ManualPdfArtifact
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        stmt = select(ManualPdfArtifact).options(defer(ManualPdfArtifact.pdf_blob))
        if manual:
            stmt = stmt.where(ManualPdfArtifact.manual == manual)
        if version:
            stmt = stmt.where(ManualPdfArtifact.version == version)
        stmt = stmt.order_by(ManualPdfArtifact.created_at.desc())
        return [_artifact_to_dict(a) for a in session.scalars(stmt).all()]


def get_pdf_artifact(artifact_id: int, *, with_blob: bool = False) -> dict | None:
    """단건 artifact 메타(기본 blob 미적재). with_blob=True 일 때만 그 1건 blob 을 별도로 붙인다."""
    if not pg_enabled():
        return None
    from sqlalchemy import select
    from sqlalchemy.orm import defer
    from backend.db.models.manual_update import ManualPdfArtifact
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        a = session.scalars(
            select(ManualPdfArtifact)
            .options(defer(ManualPdfArtifact.pdf_blob))
            .where(ManualPdfArtifact.id == artifact_id)
        ).first()
        if not a:
            return None
        d = _artifact_to_dict(a)
        if with_blob:
            # 선택된 1건의 blob 만 별도 단일 컬럼 조회(목록 조회와 분리).
            d["pdf_blob"] = session.scalar(
                select(ManualPdfArtifact.pdf_blob).where(ManualPdfArtifact.id == artifact_id))
            d["has_blob"] = d["pdf_blob"] is not None
        return d


def get_pdf_artifact_blob(artifact_id: int) -> bytes | None:
    """선택된 id 1건의 pdf_blob 만 단일 컬럼으로 조회(목록/메타 조회와 절대 섞지 않음)."""
    if not pg_enabled():
        return None
    from sqlalchemy import select
    from backend.db.models.manual_update import ManualPdfArtifact
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        return session.scalar(
            select(ManualPdfArtifact.pdf_blob).where(ManualPdfArtifact.id == artifact_id))


def get_latest_pdf_artifact(manual: str, page_no: int | None = None) -> dict | None:
    """viewer resolver 용 — manual 의 최신 사용가능 artifact.
    우선순위: promoted(production) > generated(staging). page_no 주면 해당 페이지 포함분 우선."""
    if not pg_enabled():
        return None
    from sqlalchemy import select
    from sqlalchemy.orm import defer
    from backend.db.models.manual_update import ManualPdfArtifact
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        rows = session.scalars(
            select(ManualPdfArtifact)
            .options(defer(ManualPdfArtifact.pdf_blob))   # blob 미적재(목록 조회)
            .where(ManualPdfArtifact.manual == manual,
                   ManualPdfArtifact.status.in_(("generated", "promoted")))
            .order_by(ManualPdfArtifact.created_at.desc())
        ).all()
    def _covers(a) -> bool:
        if page_no is None:
            return True
        if a.page_numbers and page_no in a.page_numbers:
            return True
        if a.page_from and a.page_to and a.page_from <= page_no <= a.page_to:
            return True
        return False
    promoted = [a for a in rows if a.status == "promoted" and _covers(a)]
    generated = [a for a in rows if a.status == "generated" and _covers(a)]
    pick = (promoted or generated)
    return _artifact_to_dict(pick[0]) if pick else None


def delete_pdf_artifact(artifact_id: int) -> bool:
    """artifact 삭제 — blob 을 메모리에 적재하지 않고 id 로 직접 DELETE."""
    if not pg_enabled():
        return False
    from sqlalchemy import delete as _delete
    from backend.db.models.manual_update import ManualPdfArtifact
    from backend.db.session import get_sessionmaker
    with get_sessionmaker()() as session:
        res = session.execute(_delete(ManualPdfArtifact).where(ManualPdfArtifact.id == artifact_id))
        session.commit()
        return (res.rowcount or 0) > 0


def pdf_artifact_summary(manual: str | None = None) -> dict:
    """pdf-status/UI 용 — manual 별 artifact 개수 + 최신 staging/production 유무."""
    if not pg_enabled():
        return {"total": 0, "by_manual": {}}
    from sqlalchemy import select, func as safunc
    from backend.db.models.manual_update import ManualPdfArtifact
    from backend.db.session import get_sessionmaker
    out: dict = {"by_manual": {}}
    with get_sessionmaker()() as session:
        stmt = select(ManualPdfArtifact.manual, ManualPdfArtifact.status,
                      safunc.count()).group_by(ManualPdfArtifact.manual, ManualPdfArtifact.status)
        if manual:
            stmt = stmt.where(ManualPdfArtifact.manual == manual)
        total = 0
        for m, st, cnt in session.execute(stmt).all():
            bm = out["by_manual"].setdefault(m, {"total": 0, "generated": 0, "promoted": 0, "failed": 0})
            bm[st] = bm.get(st, 0) + int(cnt)
            bm["total"] += int(cnt)
            total += int(cnt)
        out["total"] = total
    return out


# ── full PDF 합성(PyMuPDF 스플라이스, 검토용) ────────────────────────────────
# 검토용 "완전한 PDF": 배포본 전체 매뉴얼 PDF 에 이미 렌더된 변경 페이지 artifact 를
# 해당 위치에 끼워넣어 '변경 반영된 완전한 PDF(검토용·운영 미반영)' 를 만든다.
# node/playwright 불필요(변경 페이지는 worker 가 이미 렌더). 결과는 full_pdf artifact
# 로 캐시하되, worker/node 가 재렌더한 '진짜' full_pdf 및 staging full PDF 와 반드시
# 구분한다. 구분 마커(note):  "purpose=review_splice;generator=pymupdf_splice;source_hash=…"
# cleanup 은 이 마커가 있는 review_splice artifact 만 삭제 → worker full_pdf 는 절대 보존.
_SPLICE_PURPOSE = "review_splice"
_SPLICE_GENERATOR = "pymupdf_splice"


def is_review_splice_note(note: str | None) -> bool:
    """note 가 PyMuPDF 검토용 스플라이스 artifact 마커를 가지면 True."""
    n = note or ""
    return (f"generator={_SPLICE_GENERATOR}" in n) or (f"purpose={_SPLICE_PURPOSE}" in n)


def _splice_note(source_hash: str) -> str:
    return f"purpose={_SPLICE_PURPOSE};generator={_SPLICE_GENERATOR};source_hash={source_hash}"


def get_worker_full_pdf(manual: str, version: str | None = None) -> dict | None:
    """worker/node 가 재렌더한 '진짜' full_pdf artifact(검토용 splice 가 아닌 것). 없으면 None.
    version 지정 시 해당 버전 우선, 없으면 최신(created_at desc)."""
    if not pg_enabled():
        return None
    rows = [a for a in get_pdf_artifacts(manual, version)
            if a.get("artifact_type") == "full_pdf" and not is_review_splice_note(a.get("note"))]
    if not rows and version:
        rows = [a for a in get_pdf_artifacts(manual, None)
                if a.get("artifact_type") == "full_pdf" and not is_review_splice_note(a.get("note"))]
    return rows[0] if rows else None


def _changed_components(manual: str, version: str) -> list[dict]:
    """(manual, version) 의 변경 페이지 artifact(blob 포함)를 page_from 순으로 반환."""
    out: list[dict] = []
    for a in get_pdf_artifacts(manual, version):
        if a.get("artifact_type") not in ("changed_page", "changed_page_bundle"):
            continue
        pf = a.get("page_from")
        if not pf:
            nums = a.get("page_numbers") or []
            if not nums:
                continue
            pf, pt = min(nums), max(nums)
        else:
            pt = a.get("page_to") or pf
        blob = get_pdf_artifact_blob(a["id"])
        if not blob:
            continue
        out.append({"page_from": int(pf), "page_to": int(pt),
                    "content_hash": a.get("content_hash") or str(a["id"]), "blob": blob})
    out.sort(key=lambda c: c["page_from"])
    return out


def splice_changed_pages_into_full(base_pdf_bytes: bytes, components: list[dict]) -> bytes:
    """배포본 전체 PDF(base)의 변경 구간을 components(렌더된 변경 페이지 PDF)로 교체.

    page_from 내림차순으로 처리해 앞 페이지 인덱스가 흔들리지 않게 한다.
    modified(동일 페이지 수)는 1:1 정확 교체, 페이지 증감 케이스는 근사
    (시작 인덱스에 변경 페이지를 삽입). 1-based 페이지 번호 기준."""
    import fitz
    base = fitz.open(stream=base_pdf_bytes, filetype="pdf")
    try:
        for c in sorted(components, key=lambda x: x["page_from"], reverse=True):
            pf = int(c["page_from"]); pt = int(c["page_to"] or pf)
            i0 = max(0, pf - 1)
            if i0 >= base.page_count:
                continue
            i1 = min(base.page_count - 1, pt - 1)
            repl = fitz.open(stream=c["blob"], filetype="pdf")
            try:
                if i0 <= i1:
                    base.delete_pages(from_page=i0, to_page=i1)
                base.insert_pdf(repl, start_at=i0)
            finally:
                repl.close()
        return base.tobytes(deflate=True, garbage=3)
    finally:
        base.close()


def compose_full_pdf_blob(manual: str, version: str, base_pdf_bytes: bytes,
                          base_hash: str) -> dict | None:
    """변경 페이지 artifact 가 있으면 base 에 스플라이스해 '검토용' full_pdf blob 을 만들고
    review_splice full_pdf artifact 로 캐시한다(입력 동일하면 재사용). 없으면 None.

    캐시/정리 모두 review_splice 마커가 있는 artifact 만 대상으로 한다 → worker/node 가
    만든 진짜 full_pdf 와 staging full PDF 는 절대 건드리지 않는다.
    반환: {"blob", "artifact_id", "cached", "page_count", "components", "review_only": True}."""
    if not pg_enabled():
        return None
    components = _changed_components(manual, version)
    if not components:
        return None
    import hashlib
    src = base_hash + "|" + "|".join(
        f"{c['page_from']}-{c['page_to']}:{c['content_hash']}" for c in components)
    src_hash = hashlib.sha256(src.encode("utf-8")).hexdigest()
    note_tag = _splice_note(src_hash)
    # 동일 입력 캐시 재사용 (review_splice + 동일 source_hash)
    for a in get_pdf_artifacts(manual, version):
        if (a.get("artifact_type") == "full_pdf" and is_review_splice_note(a.get("note"))
                and (a.get("note") or "") == note_tag):
            blob = get_pdf_artifact_blob(a["id"])
            if blob:
                return {"blob": blob, "artifact_id": a["id"], "cached": True,
                        "page_count": a.get("page_count"), "components": len(components),
                        "review_only": True}
    composed = splice_changed_pages_into_full(base_pdf_bytes, components)
    pc = None
    try:
        import fitz
        with fitz.open(stream=composed, filetype="pdf") as _d:
            pc = _d.page_count
    except Exception:
        pass
    # 옛 review_splice 캐시만 정리(같은 manual/version). worker full_pdf/staging 은 보존.
    for a in get_pdf_artifacts(manual, version):
        if a.get("artifact_type") == "full_pdf" and is_review_splice_note(a.get("note")):
            try:
                delete_pdf_artifact(a["id"])
            except Exception:
                pass
    saved = save_pdf_artifact(manual=manual, artifact_type="full_pdf", version=version,
                              source="review_splice", pdf_blob=composed, page_count=pc,
                              status="generated", note=note_tag)
    return {"blob": composed, "artifact_id": saved.get("id"), "cached": False,
            "page_count": pc, "components": len(components), "review_only": True}
