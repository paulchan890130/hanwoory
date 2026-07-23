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
    monkeypatch.setattr(qd, "_required_agent_fields_for_docs", lambda docs, output: {"agent_rrn"})
    acc = {"office_name": "한우리", "contact_tel": "01012345678", "biz_reg_no": "2131237464",
           "agent_rrn": "", "agent_rrn_registered": False, "agent_rrn_decrypt_failed": False}
    with pytest.raises(HTTPException) as ei:
        qd._require_office_profile_for_docs(acc, ["doc-rrn"], output="pdf")
    assert ei.value.status_code == 409
    assert ei.value.detail.get("code") == "OFFICE_PROFILE_INCOMPLETE"
    assert ei.value.detail.get("missing") == ["agent_rrn"]


def test_docgen_gate_customer_only_doc_passes(monkeypatch):
    # 고객정보만 쓰는 문서(행정사 필드 미사용) → RRN 없어도 통과(일괄 차단 금지, 계정 없음도 허용).
    import backend.routers.quick_doc as qd
    monkeypatch.setattr(qd, "_required_agent_fields_for_docs", lambda docs, output: set())
    qd._require_office_profile_for_docs({"office_name": ""}, ["customer-only"])  # 예외 없음
    qd._require_office_profile_for_docs(None, ["customer-only"])                 # 계정 없음도 통과


def test_docgen_gate_account_none_but_fields_needed_409(monkeypatch):
    # 행정사 필드가 필요한데 account 없음(조회 실패 아님) → 409(조용한 통과 금지).
    import backend.routers.quick_doc as qd
    from fastapi import HTTPException
    monkeypatch.setattr(qd, "_required_agent_fields_for_docs", lambda docs, output: {"agent_tel"})
    with pytest.raises(HTTPException) as ei:
        qd._require_office_profile_for_docs(None, ["d"], output="pdf")
    assert ei.value.status_code == 409 and ei.value.detail.get("missing") == ["agent_tel"]


def test_docgen_gate_contract_unavailable_422(monkeypatch):
    # 계약(PDF/HWPX 필드) 확인 실패 → 422(조용한 빈집합 금지).
    import backend.routers.quick_doc as qd
    from fastapi import HTTPException
    def _boom(docs, output):
        raise qd.OfficeProfileContractUnavailable("hwpx:x")
    monkeypatch.setattr(qd, "_required_agent_fields_for_docs", _boom)
    with pytest.raises(HTTPException) as ei:
        qd._require_office_profile_for_docs({"x": 1}, ["d"], output="hwpx")
    assert ei.value.status_code == 422
    assert ei.value.detail.get("code") == "OFFICE_PROFILE_CONTRACT_UNAVAILABLE"


def test_docgen_gate_decrypt_failure_blocks(monkeypatch):
    import backend.routers.quick_doc as qd
    from fastapi import HTTPException
    monkeypatch.setattr(qd, "_required_agent_fields_for_docs", lambda docs, output: {"agent_rrn"})
    acc = {"office_name": "한우리", "contact_tel": "01012345678", "biz_reg_no": "2131237464",
           "agent_rrn": "", "agent_rrn_registered": True, "agent_rrn_decrypt_failed": True}
    with pytest.raises(HTTPException) as ei:
        qd._require_office_profile_for_docs(acc, ["d"], output="pdf")
    assert ei.value.status_code == 409 and ei.value.detail.get("missing") == ["agent_rrn"]


def test_load_account_db_error_raises_unavailable(monkeypatch):
    # DB 오류 → OfficeProfileUnavailable (계정 없음으로 위장 금지) → _load_account_or_503 는 503.
    import backend.routers.quick_doc as qd
    from fastapi import HTTPException
    def _boom(_tid):
        raise RuntimeError("db down")
    monkeypatch.setattr("backend.services.auth_pg_service.find_account_by_tenant_pg", _boom)
    with pytest.raises(qd.OfficeProfileUnavailable):
        qd._load_account("t1")
    with pytest.raises(HTTPException) as ei:
        qd._load_account_or_503("t1")
    assert ei.value.status_code == 503 and ei.value.detail.get("code") == "OFFICE_PROFILE_UNAVAILABLE"


def test_load_account_missing_returns_none(monkeypatch):
    import backend.routers.quick_doc as qd
    monkeypatch.setattr("backend.services.auth_pg_service.find_account_by_tenant_pg", lambda _tid: None)
    assert qd._load_account("t-missing") is None


# ── PART A: 템플릿 절대경로 resolver (실제 저장소 템플릿) ─────────────────────────
def test_resolve_template_abs_path_rules():
    import os
    import backend.routers.quick_doc as qd
    base, tdir = qd._BASE, qd._TEMPLATES_DIR
    # templates/foo.pdf → _BASE/templates/foo.pdf (templates/templates 중복 없음)
    r = qd._resolve_template_abs_path("templates/위임장.pdf")
    assert r == os.path.normpath(os.path.join(base, "templates/위임장.pdf"))
    assert "templates" + os.sep + "templates" not in r
    # 파일명만 → _TEMPLATES_DIR/foo.pdf
    assert qd._resolve_template_abs_path("위임장.pdf") == os.path.normpath(os.path.join(tdir, "위임장.pdf"))
    # templates/hwpx/foo.hwpx → _BASE/templates/hwpx/...
    assert qd._resolve_template_abs_path("templates/hwpx/거주숙소제공확인서.hwpx") == \
        os.path.normpath(os.path.join(base, "templates/hwpx/거주숙소제공확인서.hwpx"))
    # ../ traversal 차단
    assert qd._resolve_template_abs_path("templates/../../etc/passwd") is None
    assert qd._resolve_template_abs_path("../secret.pdf") is None
    # templates 외부 절대경로 차단
    assert qd._resolve_template_abs_path(os.path.join(base, "fonts", "x.ttf")) is None


def test_doc_templates_resolve_and_open_real_pdfs():
    """실제 저장소 DOC_TEMPLATES PDF 들이 올바른 절대경로로 resolve + fitz open 되는지(우회 없음)."""
    import os
    pytest.importorskip("fitz", reason="PyMuPDF 미설치 — 실제 PDF 계약 테스트 skip")
    import backend.routers.quick_doc as qd
    opened = 0
    agent_docs = {}
    for name, rel in qd.DOC_TEMPLATES.items():
        if not rel or not str(rel).lower().endswith(".pdf"):
            continue
        abs_path = qd._resolve_template_abs_path(rel)
        assert abs_path is not None, f"{name}: resolve None"
        assert "templates" + os.sep + "templates" not in abs_path, f"{name}: 중복 templates"
        if not os.path.exists(abs_path):
            continue
        fields = qd._agent_fields_of_template(abs_path)   # 실제 fitz open
        opened += 1
        if fields:
            agent_docs[name] = sorted(fields)
    assert opened >= 1, "실제 PDF 템플릿을 하나도 열지 못함"
    print("PDF agent-field docs:", agent_docs)


def test_hwpx_templates_agent_field_scan():
    """실제 HWPX 템플릿에서 extract_hwpx_fields 로 행정사 필드 계약을 검사(제외하지 않음)."""
    import os, glob
    import backend.routers.quick_doc as qd
    hwpx_dir = os.path.join(qd._BASE, "templates", "hwpx")
    if not os.path.isdir(hwpx_dir):
        pytest.skip("hwpx 디렉터리 없음")
    scanned = 0
    agent_docs = {}
    for f in sorted(glob.glob(os.path.join(hwpx_dir, "*.hwpx"))):
        try:
            fields = qd._agent_fields_of_template(f)
        except qd.OfficeProfileContractUnavailable:
            continue
        scanned += 1
        if fields:
            agent_docs[os.path.basename(f)] = sorted(fields)
    assert scanned >= 1, "실제 HWPX 템플릿을 하나도 스캔하지 못함"
    print("HWPX agent-field docs:", agent_docs)


# ── 자가점검 게시글 placement (backend) ───────────────────────────────────────


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


# ── PART B: HWPX 분할 필드 canonical (_canonical_agent_contract_field) ──────────
def test_canonical_agent_contract_field_exact():
    from backend.routers.quick_doc import _canonical_agent_contract_field as C
    assert C("agent_rrn") == "agent_rrn"
    assert C("agent_biz_no") == "agent_biz_no"
    assert C("agent_tel") == "agent_tel"


def test_canonical_agent_contract_field_split():
    from backend.routers.quick_doc import _canonical_agent_contract_field as C
    assert C("agent_rrn1") == "agent_rrn"
    assert C("agent_rrn13") == "agent_rrn"
    assert C("agent_tel1") == "agent_tel"
    assert C("agent_tel3") == "agent_tel"
    assert C("agent_biz_no1") == "agent_biz_no"
    assert C("agent_biz_no10") == "agent_biz_no"


def test_canonical_agent_contract_field_false_positives():
    from backend.routers.quick_doc import _canonical_agent_contract_field as C
    for bad in ("agent_rrn_note", "my_agent_tel", "agent_tel_extra", "agent1_rrn", "agentrrn", "", "  "):
        assert C(bad) is None, bad


def test_canonical_agent_contract_field_with_annotations():
    from backend.routers.quick_doc import _canonical_agent_contract_field as C
    # normalize_field_name 이 #suffix 와 ' [annotation]' 를 제거한 뒤 canonical 적용.
    assert C("agent_rrn#0") == "agent_rrn"
    assert C("agent_tel1 [0]") == "agent_tel"
    assert C("agent_biz_no10#3") == "agent_biz_no"


def test_hwpx_split_fields_canonicalized(monkeypatch):
    """분할 필드만 있는 HWPX → canonical 3필드로 합산."""
    import os, glob
    import backend.routers.quick_doc as qd
    hwpx_dir = os.path.join(qd._BASE, "templates", "hwpx")
    files = glob.glob(os.path.join(hwpx_dir, "*.hwpx"))
    if not files:
        pytest.skip("hwpx 템플릿 없음")
    real = files[0]                      # getmtime 이 통하도록 실재 파일 경로 사용
    qd._TEMPLATE_AGENT_FIELDS_CACHE.pop(real, None)
    monkeypatch.setattr("utils.hwpx_document.extract_hwpx_fields",
                        lambda p: {"unique_fields": ["agent_rrn1", "agent_rrn2", "agent_tel1", "agent_biz_no10", "Surname"]})
    assert qd._agent_fields_of_template(real) == {"agent_rrn", "agent_tel", "agent_biz_no"}


def test_split_field_hwpx_missing_rrn_blocks(monkeypatch):
    """분할 필드 HWPX 선택 + RRN 누락 → 409 OFFICE_PROFILE_INCOMPLETE."""
    import backend.routers.quick_doc as qd
    from fastapi import HTTPException
    monkeypatch.setattr(qd, "_required_agent_fields_for_docs", lambda docs, output: {"agent_rrn"})
    acc = {"office_name": "한우리", "contact_tel": "01012345678", "biz_reg_no": "2131237464",
           "agent_rrn": "", "agent_rrn_registered": False, "agent_rrn_decrypt_failed": False}
    with pytest.raises(HTTPException) as ei:
        qd._require_office_profile_for_docs(acc, ["hwpx-doc"], output="hwpx")
    assert ei.value.status_code == 409 and ei.value.detail.get("missing") == ["agent_rrn"]


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
