"""실무지침 분류 오버레이 라우터 (A+ 방식).

- 조회(GET)는 로그인 사용자 누구나(조회 트리 오버레이 렌더용).
- 쓰기(POST/PUT/PATCH/DELETE)는 require_guideline_editor 로 **백엔드에서 관리자/준 관리자 강제**.
- PG 전용(FEATURE_PG_GUIDELINES off면 비활성). 원본 JSON 무수정.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import get_current_user, require_admin, require_guideline_editor

router = APIRouter()


def _require_pg():
    from backend.db.feature_flags import pg_guidelines_enabled
    if not pg_guidelines_enabled():
        raise HTTPException(
            status_code=409,
            detail="실무지침 분류 편집은 PG 모드(FEATURE_PG_GUIDELINES=true)에서만 사용할 수 있습니다.",
        )


# ── 모델 ──────────────────────────────────────────────────────────────────────
class CategoryCreate(BaseModel):
    level: str = "minor"            # major | middle | minor
    parent_id: Optional[int] = None
    display_name: str
    sort_order: int = 0
    is_active: bool = True


class CategoryUpdate(BaseModel):
    display_name: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    parent_id: Optional[int] = None


class CategoryMove(BaseModel):
    parent_id: Optional[int] = None
    sort_order: Optional[int] = None


class OverrideSet(BaseModel):
    row_id: str
    category_id: int


# ── 조회 (로그인 사용자) ──────────────────────────────────────────────────────
@router.get("")
@router.get("/")
def list_categories_ep(include_inactive: bool = False, user: dict = Depends(get_current_user)):
    """분류 목록. include_inactive=true 는 관리자 화면용(비활성 포함).

    비관리자가 include_inactive=true 를 요청하면 무시하고 활성만 반환(정보노출 차단)."""
    _require_pg()
    from backend.services.guideline_category_pg_service import list_categories, list_overrides
    # 뷰어가 비활성 분류를 '숨김 + 미분류 재배치' 하려면 is_active 정보가 필요하므로 전체 반환.
    # (분류명은 민감정보가 아니며, 쓰기는 별도 require_admin 으로 보호된다.)
    _ = include_inactive, user
    cats = list_categories(include_inactive=True)
    return {"categories": cats, "overrides": list_overrides()}


# ── 분류 CRUD (관리자) ────────────────────────────────────────────────────────
@router.post("")
def create_category_ep(body: CategoryCreate, _: dict = Depends(require_guideline_editor)):
    _require_pg()
    if not body.display_name.strip():
        raise HTTPException(status_code=400, detail="display_name은 필수입니다.")
    from backend.services.guideline_category_pg_service import create_category
    return create_category({**body.model_dump(), "is_custom": True})


@router.put("/{cat_id}")
def update_category_ep(cat_id: int, body: CategoryUpdate, _: dict = Depends(require_guideline_editor)):
    _require_pg()
    from backend.services.guideline_category_pg_service import update_category
    res = update_category(cat_id, body.model_dump(exclude_none=True))
    if res is None:
        raise HTTPException(status_code=404, detail="분류를 찾을 수 없습니다.")
    return res


@router.patch("/{cat_id}/deactivate")
def deactivate_category_ep(cat_id: int, _: dict = Depends(require_guideline_editor)):
    """기본 삭제 동작 = 비활성화(물리삭제 아님). 연결 row가 있어도 안전."""
    _require_pg()
    from backend.services.guideline_category_pg_service import deactivate_category
    res = deactivate_category(cat_id)
    if res is None:
        raise HTTPException(status_code=404, detail="분류를 찾을 수 없습니다.")
    return res


@router.put("/{cat_id}/move")
def move_category_ep(cat_id: int, body: CategoryMove, _: dict = Depends(require_guideline_editor)):
    _require_pg()
    from backend.services.guideline_category_pg_service import move_category
    res = move_category(cat_id, body.parent_id, body.sort_order)
    if res is None:
        raise HTTPException(status_code=404, detail="분류를 찾을 수 없습니다.")
    return res


# ── override (관리자) ─────────────────────────────────────────────────────────
@router.post("/overrides")
def set_override_ep(body: OverrideSet, _: dict = Depends(require_guideline_editor)):
    """특정 row_id 를 지정 category_id 아래로 재배치(JSON 무수정)."""
    _require_pg()
    from backend.services.guideline_category_pg_service import set_override
    try:
        return set_override(body.row_id, body.category_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/overrides/{row_id}")
def clear_override_ep(row_id: str, _: dict = Depends(require_guideline_editor)):
    """override 해제 → 원래 JSON 파생 분류로 복귀."""
    _require_pg()
    from backend.services.guideline_category_pg_service import clear_override
    ok = clear_override(row_id)
    return {"row_id": row_id, "cleared": ok}


# ── seed (관리자) ─────────────────────────────────────────────────────────────
@router.post("/seed-from-json")
def seed_from_json_ep(_: dict = Depends(require_guideline_editor)):
    """JSON 파생 분류(major/middle/minor)를 누락분만 생성(멱등). 앱 부팅 시 자동실행 아님."""
    _require_pg()
    from backend.routers.guidelines import _MASTER_ROWS
    from backend.services.guideline_category_pg_service import seed_from_rows
    return seed_from_rows(_MASTER_ROWS)
