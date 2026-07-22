"""공통기준 자가점검 — 관리 설정 검증 + 개인정보 보호(사용자 답변 endpoint 부재) 테스트.

사용자 답변/결과는 서버가 받지 않으므로 그에 대한 테스트 대상 자체가 없다.
여기서는 (1) 그래프 무결성 검증 로직, (2) 라우터에 답변/결과 제출 endpoint 가 없음을 확인한다.
"""
import pytest
from backend.routers.self_check import _validate_config, _validate_config_report, router


def _valid_cfg():
    return {
        "item_name": "결핵 검진",
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
    content = _bundle_json([_item("criminal-record", published=True), _item("hidden", published=False)])
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
