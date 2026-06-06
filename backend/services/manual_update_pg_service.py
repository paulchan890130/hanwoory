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


def get_state_dict() -> dict:
    """admin 상태 조회용 dict. PG off 면 {'status':'pg_disabled'}."""
    if not pg_enabled():
        return {"status": "pg_disabled", "needs_review": False}
    from backend.db.session import get_sessionmaker
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        st = _get_or_create_state(session)
        session.commit()
        return {
            "status": st.status,
            "last_run_at": st.last_run_at.isoformat() if st.last_run_at else None,
            "last_success_at": st.last_success_at.isoformat() if st.last_success_at else None,
            "last_run_date_kst": st.last_run_date_kst,
            "last_checked_version": st.last_checked_version,
            "last_detected_version": st.last_detected_version,
            "last_staging_version": st.last_staging_version,
            "needs_review": bool(st.needs_review),
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
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        } for r in rows]
