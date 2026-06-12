"""ROI 프리셋 — PostgreSQL 전용(Phase I). ``roi_preset_sheet.py``(Google Sheets) 대체.

테넌트당 슬롯 1/2/3. 슬롯1=시스템 기본값(삭제 불가, 리셋만). is_default 는 테넌트 내 1개만.
``scan_roi_preset`` 라우터가 동일 함수명(get_all_presets/upsert_preset/delete_preset/
rename_preset)으로 드롭인 사용. PG 미구성 시 get_sessionmaker() 가 RuntimeError(Sheets fallback 없음).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select


# 기존 하드코딩 좌표(roi_preset_sheet.DEFAULT_PRESET_DATA 와 동일) — Sheets 모듈 의존 제거 위해 복제.
DEFAULT_PRESET_DATA: dict = {
    "passport": {
        "mrz": {"x": 0.129, "y": 0.635, "w": 0.693, "h": 0.085},
        "rotation": 0, "zoom": 1.0, "pan": {"x": 0, "y": 0},
    },
    "arc": {
        "한글":   {"x": 0.368, "y": 0.232, "w": 0.058, "h": 0.018},
        "등록증": {"x": 0.368, "y": 0.174, "w": 0.090, "h": 0.024},
        "번호":   {"x": 0.478, "y": 0.174, "w": 0.117, "h": 0.024},
        "발급일": {"x": 0.675, "y": 0.336, "w": 0.088, "h": 0.028},
        "만기일": {"x": 0.290, "y": 0.665, "w": 0.108, "h": 0.030},
        "주소":   {"x": 0.265, "y": 0.828, "w": 0.200, "h": 0.043},
        "rotation": 0, "zoom": 1.0, "pan": {"x": 0, "y": 0},
    },
}


def _SL():
    from backend.db.session import get_sessionmaker
    return get_sessionmaker()()


def _to_dict(row) -> dict:
    return {
        "slot": row.slot,
        "name": row.name or "",
        "data": row.data or {},
        "is_default": bool(row.is_default),
    }


def get_all_presets(tenant_id: str) -> list:
    """슬롯 1/2/3 순서 반환(빈 슬롯=None). 슬롯1 없으면 DEFAULT 자동 시드."""
    from backend.db.models.roi_preset import RoiPreset
    with _SL() as session:
        rows = session.scalars(
            select(RoiPreset).where(RoiPreset.tenant_id == tenant_id)
        ).all()
        slot_map = {r.slot: _to_dict(r) for r in rows if r.slot in (1, 2, 3)}
    if 1 not in slot_map:
        slot_map[1] = upsert_preset(tenant_id, slot=1, name="기본값",
                                    data=DEFAULT_PRESET_DATA, is_default=True)
    return [slot_map.get(i) for i in (1, 2, 3)]


def upsert_preset(tenant_id: str, slot: int, name: str, data: dict, is_default: bool) -> dict:
    """slot 행 upsert. is_default=True 면 동일 테넌트 다른 슬롯 is_default 를 False 로."""
    from backend.db.models.roi_preset import RoiPreset
    with _SL() as session:
        if is_default:
            for r in session.scalars(
                select(RoiPreset).where(RoiPreset.tenant_id == tenant_id, RoiPreset.slot != slot)
            ).all():
                if r.is_default:
                    r.is_default = False
        row = session.scalar(
            select(RoiPreset).where(RoiPreset.tenant_id == tenant_id, RoiPreset.slot == slot)
        )
        if row is None:
            row = RoiPreset(tenant_id=tenant_id, slot=slot, name=name,
                            data=data, is_default=bool(is_default))
            session.add(row)
        else:
            row.name = name
            row.data = data
            row.is_default = bool(is_default)
        session.commit()
        session.refresh(row)
        return _to_dict(row)


def delete_preset(tenant_id: str, slot: int):
    """slot1=삭제불가→DEFAULT 리셋({deleted:False,reset_to_default:True,preset}). 없으면 False, 성공 True."""
    from backend.db.models.roi_preset import RoiPreset
    if slot == 1:
        preset = upsert_preset(tenant_id, slot=1, name="기본값",
                               data=DEFAULT_PRESET_DATA, is_default=True)
        return {"deleted": False, "reset_to_default": True, "preset": preset}
    with _SL() as session:
        row = session.scalar(
            select(RoiPreset).where(RoiPreset.tenant_id == tenant_id, RoiPreset.slot == slot)
        )
        if row is None:
            return False
        session.delete(row)
        session.commit()
    return True


def rename_preset(tenant_id: str, slot: int, new_name: str) -> dict:
    """name 만 변경. 슬롯 없으면 ValueError."""
    from backend.db.models.roi_preset import RoiPreset
    with _SL() as session:
        row = session.scalar(
            select(RoiPreset).where(RoiPreset.tenant_id == tenant_id, RoiPreset.slot == slot)
        )
        if row is None:
            raise ValueError(f"슬롯 {slot}을 찾을 수 없습니다.")
        row.name = new_name
        session.commit()
        session.refresh(row)
        return _to_dict(row)
