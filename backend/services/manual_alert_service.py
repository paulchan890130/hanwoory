"""매뉴얼 업데이트 알림 서비스 (PG 전용).

설계:
  * 감지(무거움)는 1일 1회 cron 또는 관리자 수동 버튼에서만 → 첨부파일 제목 변동을 본다.
    제목 변동 = 첨부 파일명(ori) + 하이코리아 timestamp 조합의 hash 변화.
  * 변동 시 manual_update_alert_events 에 1건 생성(manual+new_title_hash 멱등).
  * 로그인 시에는 active 이벤트 중 '해당 login_id 가 dismiss 하지 않은' 것만 조회(가벼움).
  * '이번 업데이트 다시 알리지 않음' = 현재 event 만 숨김(전역 영구차단 아님).
"""
from __future__ import annotations

import hashlib
from typing import Optional

# 추적 라벨(한글) → manual 코드
_LABEL_TO_MANUAL = {"사증민원": "visa", "체류민원": "stay", "수정이력": "revision_history"}
_MANUAL_KR = {"visa": "사증민원", "stay": "체류민원", "revision_history": "수정이력"}


def _pg_ready() -> bool:
    try:
        from backend.db.session import is_configured
        return is_configured()
    except Exception:
        return False


def _title_hash(title: str, version: str = "") -> str:
    return hashlib.sha256(f"{(title or '').strip()}|{(version or '').strip()}".encode("utf-8")).hexdigest()


def manual_kr(manual: str) -> str:
    return _MANUAL_KR.get(manual, manual)


def record_title_if_changed(manual: str, new_title: str, *, version_label: str = "",
                            source_url: str = "") -> dict:
    """manual 의 첨부 제목이 직전 이벤트 대비 바뀌었으면 alert event 1건 생성.

    멱등: (manual, new_title_hash) 유니크 → 같은 제목/버전은 재생성하지 않는다."""
    if not _pg_ready():
        return {"created": False, "reason": "pg_not_configured"}
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from backend.db.session import get_sessionmaker
    from backend.db.models.manual_update import ManualUpdateAlertEvent

    new_hash = _title_hash(new_title, version_label)
    with get_sessionmaker()() as s:
        latest = s.scalars(
            select(ManualUpdateAlertEvent)
            .where(ManualUpdateAlertEvent.manual == manual)
            .order_by(ManualUpdateAlertEvent.detected_at.desc())
            .limit(1)
        ).first()
        if latest is not None and latest.new_title_hash == new_hash:
            return {"created": False, "reason": "unchanged", "manual": manual}
        ev = ManualUpdateAlertEvent(
            manual=manual,
            old_title=(latest.new_title if latest else None),
            old_title_hash=(latest.new_title_hash if latest else None),
            new_title=new_title,
            new_title_hash=new_hash,
            source_url=source_url or None,
            version_label=version_label or None,
            is_active=True,
        )
        s.add(ev)
        try:
            s.commit()
        except IntegrityError:
            # 동일 (manual, new_title_hash) 이미 존재 → 멱등(중복 생성 방지)
            s.rollback()
            return {"created": False, "reason": "duplicate", "manual": manual}
        return {"created": True, "manual": manual, "event_id": ev.id,
                "version_label": version_label}


def run_title_detection() -> dict:
    """첨부파일 제목을 1회 조회해 변동분만 alert event 로 기록(무거움 — cron/admin 전용).

    네트워크/파싱 실패는 graceful — 빈 결과 반환. PG 미구성 시 skip."""
    if not _pg_ready():
        return {"status": "skip", "reason": "pg_not_configured", "events": []}
    try:
        from backend.services.manual_auto_update import _fetch_detail_html, _parse_attachments
        from backend.services.manual_watcher import classify_attachment
    except Exception as e:  # pragma: no cover
        return {"status": "error", "reason": f"import: {e}", "events": []}

    try:
        html = _fetch_detail_html()
    except Exception as e:
        return {"status": "error", "reason": f"fetch: {e}", "events": []}

    atts = _parse_attachments(html or "")
    created: list[dict] = []
    checked = 0
    for att in atts:
        ori = (att.get("ori") or "").strip()
        label = classify_attachment(ori)
        manual = _LABEL_TO_MANUAL.get(label or "")
        if not manual:
            continue
        checked += 1
        ts = (att.get("timestamp") or "").strip()
        res = record_title_if_changed(manual, ori, version_label=ts)
        if res.get("created"):
            created.append({"manual": manual, "title": ori, "version_label": ts,
                            "event_id": res.get("event_id")})
    return {"status": "ok", "checked": checked, "created": len(created), "events": created}


def list_active_alerts_for_user(login_id: str) -> list[dict]:
    """active 이고 해당 login_id 가 dismiss 하지 않은 알림만(가벼운 로그인 조회용)."""
    if not _pg_ready() or not (login_id or "").strip():
        return []
    from sqlalchemy import select
    from backend.db.session import get_sessionmaker
    from backend.db.models.manual_update import (
        ManualUpdateAlertEvent, ManualUpdateAlertDismissal,
    )
    out: list[dict] = []
    try:
      with get_sessionmaker()() as s:
        dismissed = set(s.scalars(
            select(ManualUpdateAlertDismissal.alert_event_id)
            .where(ManualUpdateAlertDismissal.login_id == login_id)
        ).all())
        rows = s.scalars(
            select(ManualUpdateAlertEvent)
            .where(ManualUpdateAlertEvent.is_active.is_(True))
            .order_by(ManualUpdateAlertEvent.detected_at.desc())
        ).all()
        for r in rows:
            if r.id in dismissed:
                continue
            out.append({
                "id": r.id,
                "manual": r.manual,
                "manual_kr": manual_kr(r.manual),
                "new_title": r.new_title or "",
                "version_label": r.version_label or "",
                "detected_at": r.detected_at.isoformat() if r.detected_at else None,
            })
    except Exception:
        # 알림 테이블 미존재(0017 미적용)·일시 오류 → 알림 없음으로 graceful. 로그인/앱 진입 정상.
        return []
    return out


def dismiss_alert(event_id: int, login_id: str, dismiss_type: str = "this_update") -> dict:
    """현재 event 만 해당 사용자에게 숨김(멱등). 미래 업데이트는 영향 없음."""
    if not _pg_ready():
        return {"ok": False, "reason": "pg_not_configured"}
    if not (login_id or "").strip():
        return {"ok": False, "reason": "no_login_id"}
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from backend.db.session import get_sessionmaker
    from backend.db.models.manual_update import (
        ManualUpdateAlertEvent, ManualUpdateAlertDismissal,
    )
    with get_sessionmaker()() as s:
        ev = s.get(ManualUpdateAlertEvent, event_id)
        if ev is None:
            return {"ok": False, "reason": "event_not_found"}
        exists = s.scalars(
            select(ManualUpdateAlertDismissal)
            .where(ManualUpdateAlertDismissal.alert_event_id == event_id,
                   ManualUpdateAlertDismissal.login_id == login_id)
        ).first()
        if exists is not None:
            return {"ok": True, "already": True}
        s.add(ManualUpdateAlertDismissal(
            alert_event_id=event_id, login_id=login_id, dismiss_type=dismiss_type))
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            return {"ok": True, "already": True}
        return {"ok": True}
