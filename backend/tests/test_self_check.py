"""공통기준 자가점검 — 관리 설정 검증 + 개인정보 보호(사용자 답변 endpoint 부재) 테스트.

사용자 답변/결과는 서버가 받지 않으므로 그에 대한 테스트 대상 자체가 없다.
여기서는 (1) 그래프 무결성 검증 로직, (2) 라우터에 답변/결과 제출 endpoint 가 없음을 확인한다.
"""
import pytest
from backend.routers.self_check import _validate_config, router


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
    assert any("유효하지 않" in e for e in errs)


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

def test_router_has_no_answer_or_result_submission_endpoint():
    """개인정보: 답변/결과/경로를 받는 endpoint 가 존재하지 않아야 한다."""
    paths = {r.path for r in router.routes}
    # 허용된 관리/공개 설정 경로만 존재
    assert paths == {"/config", "/admin/config"}
    # 답변/제출/결과 저장 흔적 없음
    joined = " ".join(paths).lower()
    for banned in ("answer", "submit", "result", "response", "track", "log"):
        assert banned not in joined
