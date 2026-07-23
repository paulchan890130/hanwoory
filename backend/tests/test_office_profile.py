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


# ── 문서별 필수정보 게이트 (quick_doc._require_office_profile_for_docs) ──────────
def test_office_field_missing_per_field():
    from backend.routers.quick_doc import _office_field_missing
    ok = {"contact_tel": "01012345678", "biz_reg_no": "2131237464", "agent_rrn": "9001011234567",
          "agent_rrn_registered": True, "agent_rrn_decrypt_failed": False}
    assert _office_field_missing(ok, "agent_tel") is False
    assert _office_field_missing(ok, "agent_biz_no") is False
    assert _office_field_missing(ok, "agent_rrn") is False
    assert _office_field_missing({"contact_tel": ""}, "agent_tel") is True
    assert _office_field_missing({"biz_reg_no": "123"}, "agent_biz_no") is True
    assert _office_field_missing({"agent_rrn": ""}, "agent_rrn") is True
    # 복호화 실패는 조용히 통과시키지 않는다(빈 문자열이어도 missing=True)
    assert _office_field_missing({"agent_rrn": "", "agent_rrn_decrypt_failed": True}, "agent_rrn") is True


def test_docgen_gate_blocks_only_used_fields(monkeypatch):
    # 문서가 실제 쓰는 필드만 검사 — agent_rrn 만 쓰는 문서에서 RRN 누락 → 409.
    import backend.routers.quick_doc as qd
    from fastapi import HTTPException
    monkeypatch.setattr(qd, "_template_agent_fields", lambda tpl: {"agent_rrn"} if tpl == "doc-rrn" else set())
    monkeypatch.setattr(qd, "_resolve_template_path", lambda name: name)
    acc = {"office_name": "한우리", "contact_tel": "01012345678", "biz_reg_no": "2131237464",
           "agent_rrn": "", "agent_rrn_registered": False, "agent_rrn_decrypt_failed": False}
    with pytest.raises(HTTPException) as ei:
        qd._require_office_profile_for_docs(acc, ["doc-rrn"])
    assert ei.value.status_code == 409
    assert ei.value.detail.get("code") == "OFFICE_PROFILE_INCOMPLETE"
    assert ei.value.detail.get("missing") == ["agent_rrn"]


def test_docgen_gate_customer_only_doc_passes(monkeypatch):
    # 고객정보만 쓰는 문서(행정사 필드 미사용) → RRN 없어도 통과(일괄 차단 금지).
    import backend.routers.quick_doc as qd
    monkeypatch.setattr(qd, "_template_agent_fields", lambda tpl: set())
    monkeypatch.setattr(qd, "_resolve_template_path", lambda name: name)
    acc = {"office_name": "", "contact_tel": "", "agent_rrn": ""}
    qd._require_office_profile_for_docs(acc, ["customer-only"])  # 예외 없음
    qd._require_office_profile_for_docs(None, ["customer-only"])  # 계정 없음도 통과


def test_docgen_gate_decrypt_failure_blocks(monkeypatch):
    import backend.routers.quick_doc as qd
    from fastapi import HTTPException
    monkeypatch.setattr(qd, "_template_agent_fields", lambda tpl: {"agent_rrn"})
    monkeypatch.setattr(qd, "_resolve_template_path", lambda name: name)
    acc = {"office_name": "한우리", "contact_tel": "01012345678", "biz_reg_no": "2131237464",
           "agent_rrn": "", "agent_rrn_registered": True, "agent_rrn_decrypt_failed": True}
    with pytest.raises(HTTPException) as ei:
        qd._require_office_profile_for_docs(acc, ["d"])
    assert ei.value.status_code == 409 and ei.value.detail.get("missing") == ["agent_rrn"]


# ── PART A: canonical office_role (DB role 과 분리) ─────────────────────────────
def test_office_role_computation():
    from backend.routers.auth import _office_role_for
    assert _office_role_for(True, "app-1", {}) == "office_admin"
    assert _office_role_for(False, "app-1", {}) == "office_staff"
    assert _office_role_for(True, "", {}) is None          # 비-SaaS(source 없음)
    assert _office_role_for(False, None, {}) is None
    assert _office_role_for(True, "app-1", {"is_master": True}) is None
    assert _office_role_for(True, "app-1", {"is_system_admin": True}) is None


# ── PART C: 온보딩 완료 API 검증(action/version) ─────────────────────────────────
def test_onboarding_complete_rejects_bad_action():
    from backend.routers.auth import complete_my_onboarding, OnboardingCompleteRequest, ONBOARDING_VERSION
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        complete_my_onboarding(OnboardingCompleteRequest(version=ONBOARDING_VERSION, action="bogus"),
                               current_user={"login_id": "x"})
    assert ei.value.status_code == 400 and ei.value.detail["code"] == "INVALID_ONBOARDING_ACTION"


def test_onboarding_complete_rejects_bad_version():
    from backend.routers.auth import complete_my_onboarding, OnboardingCompleteRequest, ONBOARDING_VERSION
    from fastapi import HTTPException
    for bad in (0, -1, ONBOARDING_VERSION + 1):
        with pytest.raises(HTTPException) as ei:
            complete_my_onboarding(OnboardingCompleteRequest(version=bad, action="completed"),
                                   current_user={"login_id": "x"})
        assert ei.value.status_code == 400 and ei.value.detail["code"] == "INVALID_ONBOARDING_VERSION"


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
