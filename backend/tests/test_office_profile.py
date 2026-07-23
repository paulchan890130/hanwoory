"""문서 자동작성 필수정보 — 역할별 완성도 계산 + 문서생성 게이트 + 형식."""
import pytest


# ── 역할별 profile completeness (auth._compute_profile) ────────────────────────
def test_profile_office_admin_complete():
    from backend.routers.auth import _compute_profile
    complete, missing = _compute_profile(
        "office_admin", office_name="한우리", office_adr="서울",
        contact_name="홍길동", contact_tel_effective="010-1234-5678",
        biz_reg_no="2131237464", agent_rrn_registered=True,
    )
    assert complete is True and missing == []


def test_profile_office_admin_missing_rrn_and_tel():
    from backend.routers.auth import _compute_profile
    complete, missing = _compute_profile(
        "office_admin", office_name="한우리", office_adr="서울",
        contact_name="홍길동", contact_tel_effective="",
        biz_reg_no="2131237464", agent_rrn_registered=False,
    )
    assert complete is False
    assert "contact_tel" in missing and "agent_rrn" in missing


def test_profile_office_staff_ignores_tenant_common():
    # staff 는 사무소명/사업자번호/주민번호를 요구하지 않는다(본인 연락처만).
    from backend.routers.auth import _compute_profile
    complete, missing = _compute_profile(
        "office_staff", office_name="", office_adr="",
        contact_name="김실무", contact_tel_effective="010-9999-8888",
        biz_reg_no="", agent_rrn_registered=False,
    )
    assert complete is True and missing == []


def test_profile_staff_missing_own_contact():
    from backend.routers.auth import _compute_profile
    complete, missing = _compute_profile(
        "office_staff", office_name="", office_adr="",
        contact_name="", contact_tel_effective="",
        biz_reg_no="", agent_rrn_registered=False,
    )
    assert complete is False and set(missing) == {"contact_name", "contact_tel"}


def test_profile_non_office_role_not_nagged():
    from backend.routers.auth import _compute_profile
    complete, missing = _compute_profile(
        "user", office_name="", office_adr="", contact_name="", contact_tel_effective="",
        biz_reg_no="", agent_rrn_registered=False,
    )
    assert complete is True and missing == []


# ── 문서생성 게이트 (quick_doc._office_profile_missing / _require_office_profile) ──
def test_docgen_gate_all_empty_blocks_409():
    from backend.routers.quick_doc import _require_office_profile
    from fastapi import HTTPException
    acc = {"office_name": "", "contact_tel": "", "agent_rrn": ""}
    with pytest.raises(HTTPException) as ei:
        _require_office_profile(acc)
    assert ei.value.status_code == 409
    assert ei.value.detail.get("code") == "OFFICE_PROFILE_INCOMPLETE"


def test_docgen_gate_partial_profile_passes():
    # 일부라도 있으면 통과(불필요 문서까지 일괄 차단하지 않음).
    from backend.routers.quick_doc import _require_office_profile
    _require_office_profile({"office_name": "한우리", "contact_tel": "", "agent_rrn": ""})  # 예외 없음
    _require_office_profile({"office_name": "", "contact_tel": "01012345678", "agent_rrn": ""})
    _require_office_profile(None)  # 계정 없음 → 통과(사무소정보 없이 생성 허용)


def test_docgen_missing_list():
    from backend.routers.quick_doc import _office_profile_missing
    assert set(_office_profile_missing({"office_name": "", "contact_tel": "", "agent_rrn": ""})) == {
        "office_name", "contact_tel", "agent_rrn"}
    assert _office_profile_missing({"office_name": "x", "contact_tel": "01012345678", "agent_rrn": "9001011234567"}) == []


# ── 자가점검 게시글 placement (backend) ───────────────────────────────────────
def test_self_check_supports_post_placement():
    from backend.routers.self_check import SUPPORTED_PLACEMENTS
    assert "post" in SUPPORTED_PLACEMENTS and "home" in SUPPORTED_PLACEMENTS


def test_public_config_post_placement_filters(monkeypatch):
    import json
    from fastapi import Response
    import backend.routers.self_check as sc

    def _item(iid, placement):
        return {"item_id": iid, "title": iid, "sort_order": 0, "is_published": True,
                "popup_enabled": True, "placement": placement,
                "config": {"item_name": "공통", "logic_version": "CR-1.0", "start_question_id": "q1",
                           "questions": [{"id": "q1", "display_number": "①", "text": "?", "summary": "s", "yes": "r", "no": "r"}],
                           "results": [{"id": "r", "headline": "h", "label": "l"}]}}
    bundle = {"schema_version": 2, "items": [_item("a", ["post"]), _item("b", ["home"])]}
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "TRUE", "content": json.dumps(bundle, ensure_ascii=False)})
    out = sc.public_get_config(Response(), placement="post")
    assert [x["item_id"] for x in out["items"]] == ["a"]
    out2 = sc.public_get_config(Response(), placement="home")
    assert [x["item_id"] for x in out2["items"]] == ["b"]
