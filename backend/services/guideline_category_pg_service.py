"""실무지침 분류 오버레이 PG 서비스 (A+ 방식). PostgreSQL-only.

원본 JSON 무수정. source_key 로 JSON 파생 분류와 연결하고, override 로 row 재배치.

source_key 규칙(프론트 buildTree 와 동일하게 재계산 가능):
  major  = "M|{action_type}"
  middle = "m|{action_type}|{family}"
  minor  = "s|{action_type}|{family}|{mid}"
  family = detailed_code[0].upper() (없으면 "_BLANK")
  mid    = detailed_code 의 앞 두 '-' 구획 ("X-Y"), 아니면 code, 없으면 "_BLANK"
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, select


# ── source_key 계산 (frontend getFamily/getMidCode 와 동일) ──────────────────
def _family(code: str) -> str:
    code = str(code or "")
    return code[0].upper() if code else "_BLANK"


def _mid(code: str) -> str:
    code = str(code or "")
    if not code:
        return "_BLANK"
    parts = code.split("-")
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}"
    return code


# 대분류(action_type) → 한글 표시명. source_key 는 영문 유지, display_name 만 한글.
ACTION_KO: dict = {
    "CHANGE": "체류자격 변경",
    "EXTEND": "체류기간 연장",
    "REGISTRATION": "외국인등록",
    "EXTRA_WORK": "체류자격외활동",
    "WORKPLACE": "근무처 변경·추가",
    "GRANT": "체류자격 부여",
    "REENTRY": "재입국허가",
    "VISA_CONFIRM": "사증발급인정",
    "APPLICATION_CLAIM": "각종 신청·신고",
    "DOMESTIC_RESIDENCE_REPORT": "국내거소신고",
    "ACTIVITY_EXTRA": "활동범위 추가",
}


def source_key_major(action_type: str) -> str:
    return f"M|{action_type or '_OTHER'}"


def source_key_middle(action_type: str, code: str) -> str:
    return f"m|{action_type or '_OTHER'}|{_family(code)}"


def source_key_minor(action_type: str, code: str) -> str:
    return f"s|{action_type or '_OTHER'}|{_family(code)}|{_mid(code)}"


def row_source_keys(row: dict) -> dict:
    """한 row 의 (major/middle/minor) source_key 묶음."""
    at = row.get("action_type", "") or "_OTHER"
    code = row.get("detailed_code", "") or ""
    return {
        "major": source_key_major(at),
        "middle": source_key_middle(at, code),
        "minor": source_key_minor(at, code),
    }


# ── dict 변환 ────────────────────────────────────────────────────────────────
def _to_dict(row) -> dict:
    return {
        "id": row.id,
        "parent_id": row.parent_id,
        "level": row.level or "",
        "source_key": row.source_key or "",
        "display_name": row.display_name or "",
        "sort_order": int(row.sort_order or 0),
        "is_active": bool(row.is_active),
        "is_custom": bool(row.is_custom),
    }


# ── 조회 ──────────────────────────────────────────────────────────────────────
def list_categories(include_inactive: bool = False) -> list[dict]:
    from backend.db.models.guideline_category import GuidelineCategory
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        q = select(GuidelineCategory)
        if not include_inactive:
            q = q.where(GuidelineCategory.is_active.is_(True))
        rows = session.scalars(q.order_by(GuidelineCategory.level, GuidelineCategory.sort_order, GuidelineCategory.id)).all()
    return [_to_dict(r) for r in rows]


def list_overrides() -> dict:
    """{row_id: category_id} 맵."""
    from backend.db.models.guideline_category import GuidelineCategoryOverride
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        rows = session.scalars(select(GuidelineCategoryOverride)).all()
    return {r.row_id: r.category_id for r in rows}


# ── 분류 CRUD ─────────────────────────────────────────────────────────────────
def create_category(data: dict) -> dict:
    """커스텀 분류 생성(기본 is_custom=True, source_key 없음)."""
    from backend.db.models.guideline_category import GuidelineCategory
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = GuidelineCategory(
            parent_id=data.get("parent_id"),
            level=str(data.get("level", "")).strip() or "minor",
            source_key=(str(data.get("source_key", "")).strip() or None),
            display_name=str(data.get("display_name", "")).strip(),
            sort_order=int(data.get("sort_order", 0) or 0),
            is_active=bool(data.get("is_active", True)),
            is_custom=bool(data.get("is_custom", True)),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _to_dict(row)


def update_category(cat_id: int, data: dict) -> Optional[dict]:
    """표시명/순서/활성/상위만 수정. source_key 는 변경하지 않는다(연결 유지)."""
    from backend.db.models.guideline_category import GuidelineCategory
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        row = session.get(GuidelineCategory, cat_id)
        if row is None:
            return None
        if "display_name" in data:
            row.display_name = str(data.get("display_name", "")).strip()
        if "sort_order" in data:
            row.sort_order = int(data.get("sort_order", 0) or 0)
        if "is_active" in data:
            row.is_active = bool(data.get("is_active"))
        if "parent_id" in data:
            row.parent_id = data.get("parent_id")
        session.commit()
        session.refresh(row)
        return _to_dict(row)


def deactivate_category(cat_id: int) -> Optional[dict]:
    return update_category(cat_id, {"is_active": False})


def move_category(cat_id: int, parent_id: Optional[int], sort_order: Optional[int]) -> Optional[dict]:
    data: dict = {"parent_id": parent_id}
    if sort_order is not None:
        data["sort_order"] = sort_order
    return update_category(cat_id, data)


# ── override ──────────────────────────────────────────────────────────────────
def set_override(row_id: str, category_id: int) -> dict:
    from backend.db.models.guideline_category import GuidelineCategory, GuidelineCategoryOverride
    from backend.db.session import get_sessionmaker

    row_id = str(row_id).strip()
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        # override 대상은 active minor 분류만 허용 (D.3)
        target = session.get(GuidelineCategory, int(category_id))
        if target is None or target.level != "minor" or not target.is_active:
            raise ValueError("override 대상은 활성 소분류(minor)만 가능합니다.")
        row = session.scalar(select(GuidelineCategoryOverride).where(GuidelineCategoryOverride.row_id == row_id))
        if row is None:
            row = GuidelineCategoryOverride(row_id=row_id, category_id=int(category_id))
            session.add(row)
        else:
            row.category_id = int(category_id)
        session.commit()
        return {"row_id": row_id, "category_id": int(category_id)}


def clear_override(row_id: str) -> bool:
    from backend.db.models.guideline_category import GuidelineCategoryOverride
    from backend.db.session import get_sessionmaker

    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        result = session.execute(
            delete(GuidelineCategoryOverride).where(GuidelineCategoryOverride.row_id == str(row_id).strip())
        )
        session.commit()
        return (result.rowcount or 0) > 0


# ── seed (JSON 파생 분류 기본값 생성, 멱등) ───────────────────────────────────
def seed_from_rows(master_rows: list) -> dict:
    """JSON master_rows 에서 major/middle/minor source_key 를 추출해 누락분만 생성.
    이미 존재하는 source_key 는 건너뛴다(중복/덮어쓰기 없음). 멱등."""
    from backend.db.models.guideline_category import GuidelineCategory
    from backend.db.session import get_sessionmaker

    # 고유 분류 수집: source_key → (level, display_name, parent_source_key, sort_order)
    majors: dict = {}
    middles: dict = {}
    minors: dict = {}
    for r in master_rows or []:
        at = r.get("action_type", "") or "_OTHER"
        code = r.get("detailed_code", "") or ""
        mk = source_key_major(at)
        midk = source_key_middle(at, code)
        mnk = source_key_minor(at, code)
        majors.setdefault(mk, at)
        middles.setdefault(midk, (mk, _family(code)))
        minors.setdefault(mnk, (midk, _mid(code)))

    SessionLocal = get_sessionmaker()
    created = 0
    with SessionLocal() as session:
        existing = {r.source_key: r for r in session.scalars(select(GuidelineCategory)).all() if r.source_key}

        def ensure(level, source_key, display_name, parent_source_key, order):
            nonlocal created
            if source_key in existing:
                return existing[source_key]
            parent = existing.get(parent_source_key) if parent_source_key else None
            row = GuidelineCategory(
                parent_id=parent.id if parent else None,
                level=level, source_key=source_key, display_name=display_name,
                sort_order=order, is_active=True, is_custom=False,
            )
            session.add(row)
            session.flush()  # id 확보(자식 parent 연결용)
            existing[source_key] = row
            created += 1
            return row

        for i, (mk, at) in enumerate(sorted(majors.items())):
            ko = ACTION_KO.get(at, at)
            row = ensure("major", mk, ko, None, i)
            # backfill: 기존 major display_name 이 영문코드(==action_type) 이거나 비어있으면 한글로 보정.
            #           사용자가 직접 바꾼 값(그 외)은 절대 덮어쓰지 않는다.
            if (row.display_name or "").strip() in ("", at) and row.display_name != ko:
                row.display_name = ko
        for i, (midk, (mk, fam)) in enumerate(sorted(middles.items())):
            ensure("middle", midk, fam, mk, i)
        for i, (mnk, (midk, mid)) in enumerate(sorted(minors.items())):
            ensure("minor", mnk, mid, midk, i)
        session.commit()

    return {"created": created, "total_source_keys": len(majors) + len(middles) + len(minors)}
