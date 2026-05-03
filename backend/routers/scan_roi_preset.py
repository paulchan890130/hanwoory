"""
backend/routers/scan_roi_preset.py

ROI 프리셋 CRUD 엔드포인트.
prefix: /api/scan  (기존 scan 라우터와 동일 prefix, 경로 충돌 없음)

엔드포인트:
  GET    /api/scan/roi-presets
  PUT    /api/scan/roi-presets/{slot}
  DELETE /api/scan/roi-presets/{slot}
  PATCH  /api/scan/roi-presets/{slot}/rename
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import get_current_user
from backend.services.roi_preset_sheet import (
    get_all_presets,
    upsert_preset,
    delete_preset,
    rename_preset,
)

router = APIRouter()

_VALID_SLOTS = {1, 2, 3}


def _validate_slot(slot: int) -> None:
    if slot not in _VALID_SLOTS:
        raise HTTPException(status_code=400, detail="슬롯은 1, 2, 3 중 하나여야 합니다.")


# ── Pydantic 모델 ─────────────────────────────────────────────────────────────

class SavePresetBody(BaseModel):
    name: str = Field(..., max_length=50)
    data: dict
    is_default: bool = False


class RenamePresetBody(BaseModel):
    name: str = Field(..., max_length=50)


# ── 엔드포인트 ────────────────────────────────────────────────────────────────

@router.get("/roi-presets")
def list_roi_presets(user: dict = Depends(get_current_user)):
    """
    슬롯 1~3 프리셋 목록 반환.
    빈 슬롯은 null.
    슬롯 1이 없으면 자동 시드.
    응답: { "presets": [preset|null, preset|null, preset|null] }
    """
    tenant_id = user.get("tenant_id", "")
    try:
        presets = get_all_presets(tenant_id)
        return {"presets": presets}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/roi-presets/{slot}")
def save_roi_preset(
    slot: int,
    body: SavePresetBody,
    user: dict = Depends(get_current_user),
):
    """
    슬롯에 프리셋 저장 (upsert).
    is_default=True 이면 다른 슬롯들의 기본값 해제.
    응답: { "preset": {...} }
    """
    _validate_slot(slot)
    tenant_id = user.get("tenant_id", "")
    try:
        preset = upsert_preset(
            tenant_id,
            slot=slot,
            name=body.name,
            data=body.data,
            is_default=body.is_default,
        )
        return {"preset": preset}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/roi-presets/{slot}")
def remove_roi_preset(
    slot: int,
    user: dict = Depends(get_current_user),
):
    """
    슬롯 삭제.
    - slot=1: 삭제 불가 → DEFAULT_PRESET_DATA로 리셋,
               { "deleted": false, "reset_to_default": true, "preset": {...} }
    - 슬롯 없음: { "deleted": false, "reset_to_default": false }
    - 성공: { "deleted": true, "reset_to_default": false }
    """
    _validate_slot(slot)
    tenant_id = user.get("tenant_id", "")
    try:
        result = delete_preset(tenant_id, slot)
        if result is False:
            return {"deleted": False, "reset_to_default": False}
        if isinstance(result, dict):
            # slot=1 리셋 케이스
            return {
                "deleted": False,
                "reset_to_default": True,
                "preset": result.get("preset"),
            }
        return {"deleted": True, "reset_to_default": False}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/roi-presets/{slot}/rename")
def rename_roi_preset(
    slot: int,
    body: RenamePresetBody,
    user: dict = Depends(get_current_user),
):
    """
    슬롯 이름만 변경.
    응답: { "preset": {...} }
    """
    _validate_slot(slot)
    tenant_id = user.get("tenant_id", "")
    try:
        preset = rename_preset(tenant_id, slot, body.name)
        return {"preset": preset}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
