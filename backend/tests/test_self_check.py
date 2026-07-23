"""공통기준 자가점검 — 관리 설정 검증 + 개인정보 보호(사용자 답변 endpoint 부재) 테스트.

사용자 답변/결과는 서버가 받지 않으므로 그에 대한 테스트 대상 자체가 없다.
여기서는 (1) 그래프 무결성 검증 로직, (2) 라우터에 답변/결과 제출 endpoint 가 없음을 확인한다.
"""
import pytest
from backend.routers.self_check import _validate_config, _validate_config_report, router


def _valid_cfg():
    # item_name 에 '결핵' 을 넣지 않는다 — CR-1.0 + '결핵' 조합은 obsolete legacy 로 판정되므로
    # 그래프 검증 공용 fixture 는 중립 이름을 쓴다(결핵 전용 케이스는 별도 fixture 사용).
    return {
        "item_name": "공통 점검",
        "logic_version": "CR-1.0",
        "start_question_id": "q1",
        "questions": [
            {"id": "q1", "display_number": "①", "text": "고위험국가?", "summary": "고위험", "yes": "q2", "no": "r_no"},
            {"id": "q2", "display_number": "②", "text": "장기체류?", "summary": "장기", "yes": "r_yes", "no": "r_no"},
        ],
        "results": [
            {"id": "r_yes", "headline": "검진 대상입니다", "label": "대상"},
            {"id": "r_no", "headline": "대상 아님", "label": "비대상"},
        ],
    }


def test_valid_config_passes():
    assert _validate_config(_valid_cfg(), for_publish=True) == []


def test_dangling_target_detected():
    c = _valid_cfg()
    c["questions"][0]["yes"] = "does_not_exist"
    errs = _validate_config(c, for_publish=True)
    assert any("존재하지 않" in e for e in errs)


def test_cycle_detected():
    c = _valid_cfg()
    c["questions"][1]["yes"] = "q1"  # q1->q2->q1 순환
    errs = _validate_config(c, for_publish=True)
    assert any("순환" in e for e in errs)


def test_duplicate_question_id():
    c = _valid_cfg()
    c["questions"][1]["id"] = "q1"
    errs = _validate_config(c, for_publish=True)
    assert any("중복 question_id" in e for e in errs)


def test_missing_logic_version():
    c = _valid_cfg()
    c["logic_version"] = ""
    errs = _validate_config(c, for_publish=True)
    assert any("로직 버전" in e for e in errs)


def test_invalid_start_question():
    c = _valid_cfg()
    c["start_question_id"] = "nope"
    errs = _validate_config(c, for_publish=True)
    assert any("시작 질문" in e for e in errs)


def test_no_result_unreachable():
    # 결과로 이어지지 않는 구성(모든 분기가 질문으로만) → 순환/미도달 오류
    c = {
        "item_name": "x", "logic_version": "v1", "start_question_id": "q1",
        "questions": [
            {"id": "q1", "display_number": "1", "text": "a", "summary": "a", "yes": "q2", "no": "q2"},
            {"id": "q2", "display_number": "2", "text": "b", "summary": "b", "yes": "q1", "no": "q1"},
        ],
        "results": [{"id": "r1", "headline": "r", "label": "r"}],
    }
    errs = _validate_config(c, for_publish=True)
    assert errs  # 순환 또는 미도달

# ── errors/warnings 분리 + 도달성 ────────────────────────────────────────────
def test_report_shape_errors_and_warnings():
    rep = _validate_config_report(_valid_cfg())
    assert rep["errors"] == [] and rep["warnings"] == []


def test_unreachable_question_warned():
    c = _valid_cfg()
    # 어디서도 가리키지 않는 질문 추가 → 도달 불가 경고(오류 아님)
    c["questions"].append({"id": "q_orphan", "display_number": "9", "text": "x", "summary": "x", "yes": "r_yes", "no": "r_no"})
    rep = _validate_config_report(c)
    assert rep["errors"] == []
    assert any("도달 불가능한 질문: q_orphan" in w for w in rep["warnings"])


def test_unreachable_result_warned():
    c = _valid_cfg()
    c["results"].append({"id": "r_unused", "headline": "안 쓰임", "label": "x"})
    rep = _validate_config_report(c)
    assert rep["errors"] == []
    assert any("도달 불가능한 결과: r_unused" in w for w in rep["warnings"])


def test_branch_loop_blocks_publish():
    # 한 분기는 결과, 다른 분기는 loop → 게시 차단(순환 오류)
    c = _valid_cfg()
    c["questions"][1]["no"] = "q1"  # q1→q2→(no)q1 순환
    rep = _validate_config_report(c)
    assert any("순환" in e for e in rep["errors"])


def test_branch_missing_target_blocks_publish():
    c = _valid_cfg()
    c["questions"][1]["no"] = "ghost"
    rep = _validate_config_report(c)
    assert any("존재하지 않" in e for e in rep["errors"])


def test_all_branches_reach_result_ok():
    rep = _validate_config_report(_valid_cfg())
    assert rep["errors"] == []


def test_multi_results_all_reachable_ok():
    c = _valid_cfg()
    # q2.no 를 새 결과로 → 결과 2개 모두 도달 가능
    c["results"].append({"id": "r_mid", "headline": "중간", "label": "중간"})
    c["questions"][1]["no"] = "r_mid"
    rep = _validate_config_report(c)
    assert rep["errors"] == [] and not any("도달 불가능한 결과" in w for w in rep["warnings"])


def test_admin_endpoints_require_system_admin():
    """자가점검 관리 API 는 require_system_admin 으로 게이트(office_admin 차단)."""
    from backend.auth import require_system_admin
    from fastapi.routing import APIRoute
    for rt in router.routes:
        if isinstance(rt, APIRoute) and rt.path.startswith("/admin/"):
            deps = [d.call for d in rt.dependant.dependencies]
            assert require_system_admin in deps, f"{rt.path} not gated by require_system_admin"


# ── 다중 항목 번들(schema v2) ────────────────────────────────────────────────
from backend.routers.self_check import _normalize_bundle, _public_items  # noqa: E402


def _item(item_id, published=True, popup=True, cfg=None):
    return {
        "item_id": item_id, "title": item_id, "sort_order": 0,
        "is_published": published, "popup_enabled": popup,
        "placement": [], "config": cfg or _valid_cfg(),
    }


def test_normalize_legacy_single_config_wraps_one_item():
    # 레거시 단일 config → item 1개 번들(파괴적 변경 없음).
    b = _normalize_bundle(_valid_cfg(), legacy_published=True)
    assert b["schema_version"] == 2
    assert len(b["items"]) == 1
    assert b["items"][0]["item_id"] == "legacy"
    assert b["items"][0]["is_published"] is True
    assert b["items"][0]["config"]["logic_version"] == "CR-1.0"


def test_normalize_v2_bundle_passthrough():
    raw = {"schema_version": 2, "items": [_item("a"), _item("b")]}
    b = _normalize_bundle(raw)
    assert [it["item_id"] for it in b["items"]] == ["a", "b"]


def test_normalize_corrupt_returns_empty():
    assert _normalize_bundle("not-json-object")["items"] == []
    assert _normalize_bundle({"foo": "bar"})["items"] == []


def test_public_items_only_published_valid_popup_sorted():
    bad = _valid_cfg()
    bad["questions"][0]["yes"] = "ghost"  # 그래프 오류 → 공개 제외
    items = [
        {**_item("z", published=True), "sort_order": 2},
        {**_item("a", published=True), "sort_order": 1},
        _item("hidden", published=False),
        _item("nopopup", published=True, popup=False),
        {**_item("broken", published=True), "config": bad},
    ]
    out = _public_items({"schema_version": 2, "items": items})
    ids = [it["item_id"] for it in out]
    assert ids == ["a", "z"]  # 정렬 + 게시/팝업/유효만


def test_save_rejects_duplicate_item_id(monkeypatch):
    from backend.routers import self_check as sc
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    monkeypatch.setattr("backend.services.marketing_pg_service.upsert_post", lambda rec: rec)
    body = sc.ConfigSave(bundle={"schema_version": 2, "items": [_item("dup"), _item("dup")]})
    with pytest.raises(Exception) as ei:
        sc.admin_save_config(body, user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 400


def test_save_blocks_publishing_item_with_graph_error(monkeypatch):
    from backend.routers import self_check as sc
    import backend.db.session as dbs
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    monkeypatch.setattr("backend.services.marketing_pg_service.upsert_post", lambda rec: rec)
    bad = _valid_cfg(); bad["questions"][0]["yes"] = "ghost"
    body = sc.ConfigSave(bundle={"schema_version": 2, "items": [_item("x", published=True, cfg=bad)]})
    with pytest.raises(Exception) as ei:
        sc.admin_save_config(body, user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 400


def test_save_allows_unpublished_draft_with_error(monkeypatch):
    # 비공개(draft) 항목은 그래프 오류가 있어도 저장 허용(공개만 차단).
    from backend.routers import self_check as sc
    import backend.db.session as dbs
    saved = {}
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    monkeypatch.setattr("backend.services.marketing_pg_service.upsert_post", lambda rec: saved.update(rec) or rec)
    bad = _valid_cfg(); bad["questions"][0]["yes"] = "ghost"
    body = sc.ConfigSave(bundle={"schema_version": 2, "items": [_item("x", published=False, cfg=bad)]})
    res = sc.admin_save_config(body, user={"login_id": "sys"})
    assert res["ok"] is True and saved["is_published"] == "FALSE"


def test_no_answer_submission_endpoint():
    # 사용자 답변/결과 제출 endpoint 가 존재하지 않는다(개인정보 무저장).
    from fastapi.routing import APIRoute
    paths = [(rt.path, tuple(rt.methods or ())) for rt in router.routes if isinstance(rt, APIRoute)]
    for path, methods in paths:
        low = path.lower()
        assert not any(k in low for k in ("answer", "result", "submit", "response")), f"의심 endpoint: {path}"
        # POST 로 사용자 데이터를 받는 config 저장 외 endpoint 가 없어야 함
    assert not any("POST" in m and "/admin/config" not in p for p, m in paths)


def test_public_config_has_no_auth_dependency():
    from backend.auth import require_system_admin
    from fastapi.routing import APIRoute
    for rt in router.routes:
        if isinstance(rt, APIRoute) and rt.path == "/config":
            deps = [d.call for d in rt.dependant.dependencies]
            assert require_system_admin not in deps


# ── 공개 GET (번들 shape) ─────────────────────────────────────────────────────
def _valid_cfg_json():
    import json
    return json.dumps(_valid_cfg(), ensure_ascii=False)


def _bundle_json(items):
    import json
    return json.dumps({"schema_version": 2, "items": items}, ensure_ascii=False)


def test_public_get_config_empty_when_no_row(monkeypatch):
    from fastapi import Response
    import backend.routers.self_check as sc
    monkeypatch.setattr(sc, "_load_row", lambda: None)
    out = sc.public_get_config(Response())
    assert out == {"schema_version": 2, "items": []}


def test_public_get_config_hides_unpublished_legacy(monkeypatch):
    # 레거시 단일 config + 행 미게시 → item is_published=False → 공개 항목 0.
    from fastapi import Response
    import backend.routers.self_check as sc
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "FALSE", "content": _valid_cfg_json()})
    assert sc.public_get_config(Response())["items"] == []


def test_public_get_config_hides_corrupt(monkeypatch):
    from fastapi import Response
    import backend.routers.self_check as sc
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "TRUE", "content": "{bad"})
    assert sc.public_get_config(Response())["items"] == []


def test_public_get_config_returns_published_bundle(monkeypatch):
    from fastapi import Response
    import backend.routers.self_check as sc
    # PART D: 공개 GET 은 placement 미지정 시 home 으로 해석하므로 노출 항목은 placement=home 필요.
    cr = _item("criminal-record", published=True); cr["placement"] = ["home"]
    content = _bundle_json([cr, _item("hidden", published=False)])
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "TRUE", "content": content})
    r = Response()
    out = sc.public_get_config(r)
    assert out["schema_version"] == 2
    assert [it["item_id"] for it in out["items"]] == ["criminal-record"]  # 게시만
    assert r.headers.get("Cache-Control") == "no-store"


def test_public_get_config_legacy_published_wrapped(monkeypatch):
    # 레거시 단일 config + 행 게시 → item 1개로 감싸 공개.
    from fastapi import Response
    import backend.routers.self_check as sc
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "TRUE", "content": _valid_cfg_json()})
    out = sc.public_get_config(Response())
    assert len(out["items"]) == 1 and out["items"][0]["item_id"] == "legacy"


def test_router_has_no_answer_or_result_submission_endpoint():
    """개인정보: 답변/결과/경로를 받는 endpoint 가 존재하지 않아야 한다."""
    paths = {r.path for r in router.routes}
    # 허용된 관리/공개 설정 경로만 존재
    assert paths == {"/config", "/admin/config"}
    # 답변/제출/결과 저장 흔적 없음
    joined = " ".join(paths).lower()
    for banned in ("answer", "submit", "result", "response", "track", "log"):
        assert banned not in joined


# ── PART A: row-level fail-closed ─────────────────────────────────────────────
def test_public_fail_closed_when_row_unpublished(monkeypatch):
    # 최상위 marketing row 가 비공개면 내부 item is_published=TRUE 여도 공개 0.
    from fastapi import Response
    import backend.routers.self_check as sc
    content = _bundle_json([_item("criminal-record", published=True)])
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "FALSE", "content": content})
    assert sc.public_get_config(Response())["items"] == []


def test_public_shows_when_row_published(monkeypatch):
    from fastapi import Response
    import backend.routers.self_check as sc
    it = _item("criminal-record", published=True)
    it["placement"] = ["home"]
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "TRUE", "content": _bundle_json([it])})
    out = sc.public_get_config(Response())
    assert [x["item_id"] for x in out["items"]] == ["criminal-record"]


# ── PART A/C: placement 필터 ──────────────────────────────────────────────────
def test_public_items_placement_filter():
    from backend.routers.self_check import _public_items
    a = _item("a", published=True); a["placement"] = ["home"]
    b = _item("b", published=True); b["placement"] = ["other"]
    c = _item("c", published=True); c["placement"] = []
    bundle = {"schema_version": 2, "items": [a, b, c]}
    assert [x["item_id"] for x in _public_items(bundle, placement="home")] == ["a"]
    assert [x["item_id"] for x in _public_items(bundle, placement="other")] == ["b"]
    assert {x["item_id"] for x in _public_items(bundle, placement=None)} == {"a", "b", "c"}


def test_legacy_public_home_placement(monkeypatch):
    # 레거시 단일 config + 행 게시 → placement=home 으로 해석되어 home 런처에 노출.
    from fastapi import Response
    import backend.routers.self_check as sc
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "TRUE", "content": _valid_cfg_json()})
    out = sc.public_get_config(Response(), placement="home")
    assert len(out["items"]) == 1 and out["items"][0]["item_id"] == "legacy"
    # 다른 위치에는 미노출
    assert sc.public_get_config(Response(), placement="other")["items"] == []


# ── PART B: 쓰기 엄격 검증(손상 item 저장 차단, 조용한 제거 금지) ─────────────
def _save_capture(monkeypatch):
    from backend.routers import self_check as sc
    import backend.db.session as dbs
    calls = {"n": 0}
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    monkeypatch.setattr("backend.services.marketing_pg_service.upsert_post",
                        lambda rec: calls.__setitem__("n", calls["n"] + 1) or rec)
    return sc, calls


@pytest.mark.parametrize("mutate", [
    lambda it: it.update({"config": None}),                 # config 누락
    lambda it: it.__setitem__("config", {"questions": "x", "results": []}),  # questions 문자열
    lambda it: it.__setitem__("placement", "home"),          # placement 문자열
    lambda it: it.__setitem__("sort_order", float("nan")),   # NaN
    lambda it: it.__setitem__("title", ""),                  # 빈 title
    lambda it: it.__setitem__("is_published", "yes"),        # boolean 아님
])
def test_save_malformed_item_blocks_and_no_upsert(monkeypatch, mutate):
    sc, calls = _save_capture(monkeypatch)
    good1, good2 = _item("a", published=False), _item("b", published=False)
    bad = _item("c", published=False)
    mutate(bad)
    body = sc.ConfigSave(bundle={"schema_version": 2, "items": [good1, bad, good2]})
    with pytest.raises(Exception) as ei:
        sc.admin_save_config(body, user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 400
    assert calls["n"] == 0  # upsert 미호출 → 정상 2개만 저장되는 부분 저장 없음


def test_save_null_item_blocks(monkeypatch):
    sc, calls = _save_capture(monkeypatch)
    body = sc.ConfigSave(bundle={"schema_version": 2, "items": [_item("a"), None]})
    with pytest.raises(Exception) as ei:
        sc.admin_save_config(body, user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 400
    assert calls["n"] == 0


def test_save_wrong_schema_version_blocks(monkeypatch):
    sc, calls = _save_capture(monkeypatch)
    body = sc.ConfigSave(bundle={"schema_version": 1, "items": [_item("a")]})
    with pytest.raises(Exception) as ei:
        sc.admin_save_config(body, user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 400
    assert calls["n"] == 0


def test_save_valid_bundle_preserves_all_items(monkeypatch):
    sc, calls = _save_capture(monkeypatch)
    saved = {}
    monkeypatch.setattr("backend.services.marketing_pg_service.upsert_post",
                        lambda rec: saved.update(rec) or rec)
    items = [_item("a", published=False), _item("b", published=False), _item("c", published=False)]
    body = sc.ConfigSave(bundle={"schema_version": 2, "items": items})
    res = sc.admin_save_config(body, user={"login_id": "sys"})
    import json as _json
    stored = _json.loads(saved["content"])
    assert [it["item_id"] for it in stored["items"]] == ["a", "b", "c"]  # 손실 없음
    assert res["ok"] is True


# ── PART A: 결핵(TB) 공식 국가 목록 35개국 ────────────────────────────────────
from backend.routers.self_check import (  # noqa: E402
    TB_HIGH_RISK_COUNTRIES, TB_CANONICAL_COUNT, _tb_verification,
    _is_obsolete_legacy_selfcheck, _normalize_country,
)

TB_MISSING_18 = [
    "말레이시아", "스리랑카", "우즈베키스탄", "카자흐스탄", "우크라이나", "아제르바이잔",
    "벨라루스", "몰도바공화국", "나이지리아", "남아프리카공화국", "에티오피아",
    "콩고민주공화국", "케냐", "모잠비크", "짐바브웨", "앙골라", "페루", "파푸아뉴기니",
]


def _tb_cfg(countries=None, with_source=True, **over):
    cfg = {
        "item_name": "결핵검진 필요 확인", "logic_version": "TB-1.0", "start_question_id": "q1",
        "country_list_title": "결핵 고위험 국가",
        "country_list": list(TB_HIGH_RISK_COUNTRIES if countries is None else countries),
        "questions": [
            {"id": "q1", "display_number": "①", "text": "결핵 고위험 국가 국적입니까?", "summary": "고위험국가 국적", "country_list_ref": True, "yes": "q2", "no": "r_none"},
            {"id": "q2", "display_number": "②", "text": "만 6세 이상입니까?", "summary": "만 6세 이상", "yes": "q3", "no": "r_none"},
            {"id": "q3", "display_number": "③", "text": "과거 결핵검진서를 제출한 적이 있습니까?", "summary": "과거 제출 이력", "yes": "q4", "no": "r_target"},
            {"id": "q4", "display_number": "④", "text": "결핵검진서 제출 또는 비자발급 이후 결핵 고위험 국가에서 계속하여 6개월 이상 체류했습니까?", "summary": "제출·발급 후 6개월 이상", "yes": "r_target", "no": "r_none"},
        ],
        "results": [
            {"id": "r_target", "headline": "결핵검진서 제출 대상입니다", "label": "제출 대상"},
            {"id": "r_none", "headline": "결핵검진서 제출 대상이 아닙니다", "label": "비대상"},
        ],
    }
    if with_source:
        cfg.update({
            "country_list_source_title": "법무부 결핵검사 의무화 대상국가 및 재외공관 공식 안내",
            "country_list_source_date": "2020-04-01 기준 35개국",
            "country_list_verified_at": "2026-07-23",
            "country_list_source_note": "법무부 및 2025~2026년 재외공관 공식 안내와 대조",
        })
    cfg.update(over)
    return cfg


def _tb_item(cfg, published=True):
    return {"item_id": "tuberculosis", "title": "결핵검진 필요 확인", "sort_order": 0,
            "is_published": published, "popup_enabled": True, "placement": ["home"], "config": cfg}


def test_tb_official_list_exactly_35_no_dup_no_empty():
    assert len(TB_HIGH_RISK_COUNTRIES) == 35
    assert TB_CANONICAL_COUNT == 35
    assert len(set(TB_HIGH_RISK_COUNTRIES)) == 35   # 중복 없음
    assert all(str(c).strip() for c in TB_HIGH_RISK_COUNTRIES)  # 빈 문자열 없음


def test_tb_official_list_includes_missing_18():
    for c in TB_MISSING_18:
        assert c in TB_HIGH_RISK_COUNTRIES, f"누락된 국가: {c}"


def test_tb_verification_canonical_match():
    v = _tb_verification(_tb_cfg())
    assert v["ok"] is True and v["matches"] is True and v["count"] == 35 and v["dup"] == 0 and v["has_source"] is True


def test_tb_alias_kyrgyz_equivalent():
    assert _normalize_country("키르기스") == "키르기스스탄"
    lst = ["키르기스" if c == "키르기스스탄" else c for c in TB_HIGH_RISK_COUNTRIES]
    v = _tb_verification(_tb_cfg(countries=lst))
    assert v["ok"] is True and v["matches"] is True


# ── PART B: TB 게시 검증 ──────────────────────────────────────────────────────
def _tb_save(monkeypatch):
    from backend.routers import self_check as sc
    import backend.db.session as dbs
    calls = {"n": 0}
    monkeypatch.setattr(dbs, "is_configured", lambda: True)
    monkeypatch.setattr("backend.services.marketing_pg_service.upsert_post",
                        lambda rec: calls.__setitem__("n", calls["n"] + 1) or rec)
    return sc, calls


def test_tb_publish_blocked_17_countries(monkeypatch):
    sc, calls = _tb_save(monkeypatch)
    body = sc.ConfigSave(bundle={"schema_version": 2, "items": [_tb_item(_tb_cfg(countries=TB_HIGH_RISK_COUNTRIES[:17]))]})
    with pytest.raises(Exception) as ei:
        sc.admin_save_config(body, user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 400
    assert ei.value.detail.get("code") == "TB_COUNTRY_LIST_NOT_VERIFIED"
    assert calls["n"] == 0


def test_tb_publish_blocked_34_countries(monkeypatch):
    sc, calls = _tb_save(monkeypatch)
    body = sc.ConfigSave(bundle={"schema_version": 2, "items": [_tb_item(_tb_cfg(countries=TB_HIGH_RISK_COUNTRIES[:34]))]})
    with pytest.raises(Exception) as ei:
        sc.admin_save_config(body, user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 400
    assert calls["n"] == 0


def test_tb_publish_blocked_wrong_country_substitution(monkeypatch):
    sc, calls = _tb_save(monkeypatch)
    lst = list(TB_HIGH_RISK_COUNTRIES); lst[0] = "대한민국"  # 공식 목록에 없는 국가로 치환(수 35 유지)
    body = sc.ConfigSave(bundle={"schema_version": 2, "items": [_tb_item(_tb_cfg(countries=lst))]})
    with pytest.raises(Exception) as ei:
        sc.admin_save_config(body, user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 400
    assert calls["n"] == 0


def test_tb_publish_blocked_missing_source(monkeypatch):
    sc, calls = _tb_save(monkeypatch)
    body = sc.ConfigSave(bundle={"schema_version": 2, "items": [_tb_item(_tb_cfg(with_source=False))]})
    with pytest.raises(Exception) as ei:
        sc.admin_save_config(body, user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 400
    assert calls["n"] == 0


def test_tb_publish_blocked_banned_phrase(monkeypatch):
    sc, calls = _tb_save(monkeypatch)
    cfg = _tb_cfg()
    cfg["questions"][3]["text"] = "최근 6개월 이내 결핵검진 확인서 제출 이력이 있습니까?"  # 폐기 문구
    body = sc.ConfigSave(bundle={"schema_version": 2, "items": [_tb_item(cfg)]})
    with pytest.raises(Exception) as ei:
        sc.admin_save_config(body, user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 400
    assert calls["n"] == 0


def test_tb_publish_allowed_valid_35(monkeypatch):
    sc, calls = _tb_save(monkeypatch)
    body = sc.ConfigSave(bundle={"schema_version": 2, "items": [_tb_item(_tb_cfg())]})
    res = sc.admin_save_config(body, user={"login_id": "sys"})
    assert res["ok"] is True and calls["n"] == 1


def test_tb_draft_saved_with_warning(monkeypatch):
    # 비공개 draft 인 TB 항목은 검증 미통과여도 저장 허용 + 경고 반환.
    sc, calls = _tb_save(monkeypatch)
    body = sc.ConfigSave(bundle={"schema_version": 2, "items": [_tb_item(_tb_cfg(countries=TB_HIGH_RISK_COUNTRIES[:17]), published=False)]})
    res = sc.admin_save_config(body, user={"login_id": "sys"})
    assert res["ok"] is True and calls["n"] == 1
    assert "tuberculosis" in res["tb_warnings"] and res["tb_warnings"]["tuberculosis"]


# ── PART C: obsolete legacy 판정 + 공개 차단 + 관리자 표시 ───────────────────────
def _obsolete_tb_legacy():
    return {
        "item_name": "결핵검진 확인", "logic_version": "CR-1.0", "start_question_id": "q1",
        "questions": [
            {"id": "q1", "display_number": "①", "text": "90일을 초과하는 장기체류입니까?", "summary": "장기체류", "yes": "q2", "no": "r_none"},
            {"id": "q2", "display_number": "②", "text": "최근 6개월 이내 결핵검진 확인서 제출 이력이 있습니까?", "summary": "6개월내 제출", "yes": "r_none", "no": "r_target"},
        ],
        "results": [
            {"id": "r_target", "headline": "제출 대상", "label": "대상"},
            {"id": "r_none", "headline": "비대상", "label": "비대상"},
        ],
    }


def _normal_legacy():
    c = _valid_cfg()
    c["item_name"] = "기존 단일 설정"  # 결핵 무관 + 정상 그래프
    return c


def test_obsolete_legacy_detected():
    assert _is_obsolete_legacy_selfcheck(_obsolete_tb_legacy()) is True


def test_obsolete_legacy_missing_six_year_question():
    cfg = _tb_cfg()
    cfg["questions"] = [q for q in cfg["questions"] if "6세" not in q["text"]]  # 만 6세 질문 제거
    assert _is_obsolete_legacy_selfcheck(cfg) is True


def test_normal_legacy_not_obsolete():
    assert _is_obsolete_legacy_selfcheck(_normal_legacy()) is False


def test_v2_bundle_never_obsolete():
    assert _is_obsolete_legacy_selfcheck({"schema_version": 2, "items": [_item("a")]}) is False
    assert _is_obsolete_legacy_selfcheck("not-a-dict") is False


def test_public_hides_obsolete_legacy_even_when_row_published(monkeypatch):
    import json
    from fastapi import Response
    import backend.routers.self_check as sc
    content = json.dumps(_obsolete_tb_legacy(), ensure_ascii=False)
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "TRUE", "content": content})
    assert sc.public_get_config(Response())["items"] == []               # home 기본
    assert sc.public_get_config(Response(), placement="home")["items"] == []


def test_public_shows_normal_legacy_when_row_published(monkeypatch):
    import json
    from fastapi import Response
    import backend.routers.self_check as sc
    content = json.dumps(_normal_legacy(), ensure_ascii=False)
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "TRUE", "content": content})
    out = sc.public_get_config(Response())
    assert len(out["items"]) == 1 and out["items"][0]["item_id"] == "legacy"


def test_admin_flags_obsolete_legacy(monkeypatch):
    import json
    import backend.routers.self_check as sc
    content = json.dumps(_obsolete_tb_legacy(), ensure_ascii=False)
    monkeypatch.setattr(sc, "_load_row", lambda *a, **k: {"is_published": "TRUE", "content": content})
    out = sc.admin_get_config(user={"login_id": "sys"})
    assert out["obsolete_legacy"] is True
    assert out["config_state"] == "legacy"
    assert len(out["items"]) == 1  # 원본은 편집·확인을 위해 그대로 반환(자동 변경 없음)


def test_admin_normal_legacy_not_flagged(monkeypatch):
    import json
    import backend.routers.self_check as sc
    content = json.dumps(_normal_legacy(), ensure_ascii=False)
    monkeypatch.setattr(sc, "_load_row", lambda *a, **k: {"is_published": "TRUE", "content": content})
    out = sc.admin_get_config(user={"login_id": "sys"})
    assert out["obsolete_legacy"] is False
    assert out["config_state"] == "legacy"


# ── PART D: placement 공개 API fail-closed ────────────────────────────────────
def test_public_placement_fail_closed(monkeypatch):
    from fastapi import Response
    import backend.routers.self_check as sc
    a = _item("a", published=True); a["placement"] = ["home"]
    b = _item("b", published=True); b["placement"] = ["other"]
    c = _item("c", published=True); c["placement"] = []
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "TRUE", "content": _bundle_json([a, b, c])})
    # query 없음 → home 으로 동작
    assert [x["item_id"] for x in sc.public_get_config(Response())["items"]] == ["a"]
    # placement=home → home 항목만
    assert [x["item_id"] for x in sc.public_get_config(Response(), placement="home")["items"]] == ["a"]
    # 지원하지 않는 위치 → 공개 0(우회 차단)
    assert sc.public_get_config(Response(), placement="other")["items"] == []
    # 빈 문자열 → home 으로 해석
    assert [x["item_id"] for x in sc.public_get_config(Response(), placement="")["items"]] == ["a"]


def test_public_placement_empty_array_item_never_shown(monkeypatch):
    from fastapi import Response
    import backend.routers.self_check as sc
    c = _item("c", published=True); c["placement"] = []  # 신규 v2 item, 위치 미지정
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "TRUE", "content": _bundle_json([c])})
    assert sc.public_get_config(Response())["items"] == []
    assert sc.public_get_config(Response(), placement="home")["items"] == []


def test_public_unverified_tb_v2_item_hidden(monkeypatch):
    # 게시된 TB v2 항목이 공식 35개국 검증 미통과면 공개에서 제외(서버 fail-closed).
    from fastapi import Response
    import backend.routers.self_check as sc
    it = _tb_item(_tb_cfg(countries=TB_HIGH_RISK_COUNTRIES[:17]), published=True)
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "TRUE", "content": _bundle_json([it])})
    assert sc.public_get_config(Response())["items"] == []


def test_public_verified_tb_v2_item_shown(monkeypatch):
    from fastapi import Response
    import backend.routers.self_check as sc
    it = _tb_item(_tb_cfg(), published=True)
    monkeypatch.setattr(sc, "_load_row", lambda: {"is_published": "TRUE", "content": _bundle_json([it])})
    out = sc.public_get_config(Response())
    assert [x["item_id"] for x in out["items"]] == ["tuberculosis"]


# ── PART A/B/C: 관리자 조회 경계(실패/없음/정상/손상) + 무손실 ──────────────────
def _raise_get_post(monkeypatch, exc=RuntimeError("db down")):
    def boom(_cid):
        raise exc
    monkeypatch.setattr("backend.services.marketing_pg_service.get_post", boom)


def _set_get_post(monkeypatch, row):
    monkeypatch.setattr("backend.services.marketing_pg_service.get_post", lambda _cid: row)


def test_public_get_config_db_error_failclosed(monkeypatch):
    # 공개 GET: 저장 계층 오류 → items=[] (fail-closed, 500 없음).
    from fastapi import Response
    import backend.routers.self_check as sc
    _raise_get_post(monkeypatch)
    out = sc.public_get_config(Response())
    assert out == {"schema_version": 2, "items": []}


def test_admin_get_config_db_error_503(monkeypatch):
    # 관리자 GET: 저장 계층 오류 → 503, 빈/기본 bundle 반환 금지.
    import backend.routers.self_check as sc
    _raise_get_post(monkeypatch)
    with pytest.raises(Exception) as ei:
        sc.admin_get_config(user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 503
    assert ei.value.detail.get("code") == "SELF_CHECK_CONFIG_UNAVAILABLE"


def test_admin_get_config_absent_when_no_row(monkeypatch):
    import backend.routers.self_check as sc
    _set_get_post(monkeypatch, None)
    out = sc.admin_get_config(user={"login_id": "sys"})
    assert out["config_state"] == "absent" and out["items"] == [] and out["obsolete_legacy"] is False


def test_admin_get_config_absent_when_empty_content(monkeypatch):
    import backend.routers.self_check as sc
    _set_get_post(monkeypatch, {"is_published": "FALSE", "content": ""})
    out = sc.admin_get_config(user={"login_id": "sys"})
    assert out["config_state"] == "absent" and out["items"] == []


def test_admin_get_config_valid_v2_preserves_items(monkeypatch):
    import backend.routers.self_check as sc
    content = _bundle_json([_item("a", published=False), _item("b", published=True), _item("c", published=False)])
    _set_get_post(monkeypatch, {"is_published": "TRUE", "content": content})
    out = sc.admin_get_config(user={"login_id": "sys"})
    assert out["config_state"] == "valid"
    assert [it["item_id"] for it in out["items"]] == ["a", "b", "c"]  # 전 item 보존


def test_admin_get_config_corrupt_json_409(monkeypatch):
    import backend.routers.self_check as sc
    _set_get_post(monkeypatch, {"is_published": "TRUE", "content": "{bad json"})
    with pytest.raises(Exception) as ei:
        sc.admin_get_config(user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 409
    assert ei.value.detail.get("code") == "SELF_CHECK_CONFIG_CORRUPT"


def test_admin_get_config_malformed_v2_item_409_no_partial(monkeypatch):
    # v2 번들: 정상 CR + config=null 손상 TB + 정상 FP → 409, 정상 2개 부분 반환 없음, DB 변경 없음.
    import json
    import backend.routers.self_check as sc
    bad = _tb_item(_tb_cfg(), published=False); bad["config"] = None
    raw = {"schema_version": 2, "items": [_item("criminal-record"), bad, _item("fingerprint")]}
    _set_get_post(monkeypatch, {"is_published": "TRUE", "content": json.dumps(raw, ensure_ascii=False)})
    with pytest.raises(Exception) as ei:
        sc.admin_get_config(user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 409
    assert ei.value.detail.get("code") == "SELF_CHECK_CONFIG_CORRUPT"


def test_admin_get_config_unknown_structure_409(monkeypatch):
    import json
    import backend.routers.self_check as sc
    _set_get_post(monkeypatch, {"is_published": "TRUE", "content": json.dumps({"foo": "bar"})})
    with pytest.raises(Exception) as ei:
        sc.admin_get_config(user={"login_id": "sys"})
    assert getattr(ei.value, "status_code", None) == 409


def test_public_get_config_malformed_v2_failclosed(monkeypatch):
    # 공개 GET: v2 번들 구조 손상 → 전체 items=[] (부분 공개 없음, 500 없음).
    import json
    from fastapi import Response
    import backend.routers.self_check as sc
    bad = _item("x", published=True); bad["config"] = None  # config 손상
    raw = {"schema_version": 2, "items": [_item("ok", published=True), bad]}
    _set_get_post(monkeypatch, {"is_published": "TRUE", "content": json.dumps(raw, ensure_ascii=False)})
    assert sc.public_get_config(Response())["items"] == []


def test_load_row_suppress_vs_raise(monkeypatch):
    # _load_row(suppress_errors=True) → None(공개), suppress_errors=False → 예외(관리자).
    import backend.routers.self_check as sc
    _raise_get_post(monkeypatch)
    assert sc._load_row(suppress_errors=True) is None
    with pytest.raises(sc.SelfCheckConfigUnavailable):
        sc._load_row(suppress_errors=False)
