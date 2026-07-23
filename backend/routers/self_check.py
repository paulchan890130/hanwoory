"""공통기준 자가점검 — **관리 설정만** 저장/조회하는 라우터.

개인정보 원칙:
- 사용자 답변/결과/경로를 받는 endpoint 는 **존재하지 않는다**(제출·결과저장 API 없음).
- 저장되는 것은 관리자 설정(질문 그래프/결과/주의문구/버전/국가목록/공개여부)뿐이다.
- 저장은 **기존 마케팅 저장 계층**(marketing_pg_service, marketing_posts 테이블)을 재사용한다
  — 신규 테이블/migration 없음. 고정 id 싱글턴 행 1개.
공개 GET 은 게시된 설정만 반환하고, 평가(판정)는 전적으로 프론트에서 수행한다.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from backend.auth import require_system_admin

logger = logging.getLogger(__name__)

router = APIRouter()


class SelfCheckConfigUnavailable(Exception):
    """저장 계층 조회 실패 — '설정 없음'과 반드시 구별(관리자에게 503)."""

CONFIG_ID = "common-criteria-self-check"
CONFIG_CATEGORY = "self_check_config"

# 공개 런처가 실제 배치된(지원되는) 노출 위치. 프론트 SUPPORTED_PLACEMENTS 와 동일.
# home = 홈페이지 hero(현재 제거됨, 하위호환 유지), post = 마케팅 게시글 본문 shortcode.
SUPPORTED_PLACEMENTS: frozenset[str] = frozenset({"home", "post"})

# ── 결핵검진(TB-1.0) 공식 기준 (source of truth) ──────────────────────────────
# 법무부 결핵검사 의무화 대상국가(2020.4.1. 확대, 35개국) 및 2025~2026년 재외공관 공식
# 안내와 대조한 목록. 프론트 lib/selfcheck/tuberculosis.ts 와 동일해야 한다(서버가 최종 권위).
TB_HIGH_RISK_COUNTRIES: list[str] = [
    "네팔", "동티모르", "러시아", "말레이시아", "몽골", "미얀마", "방글라데시",
    "베트남", "스리랑카", "우즈베키스탄", "인도", "인도네시아", "중국", "캄보디아",
    "키르기스스탄", "태국", "파키스탄", "필리핀", "라오스", "카자흐스탄", "타지키스탄",
    "우크라이나", "아제르바이잔", "벨라루스", "몰도바공화국", "나이지리아",
    "남아프리카공화국", "에티오피아", "콩고민주공화국", "케냐", "모잠비크", "짐바브웨",
    "앙골라", "페루", "파푸아뉴기니",
]
# 표기 alias — 검색·비교 시 동일 국가로 취급(화면 표기는 canonical).
TB_COUNTRY_ALIASES: dict[str, str] = {
    "키르기스": "키르기스스탄", "키르기즈": "키르기스스탄", "키르기스공화국": "키르기스스탄",
    "몰도바": "몰도바공화국", "남아공": "남아프리카공화국", "콩고": "콩고민주공화국",
}


def _normalize_country(name: Any) -> str:
    s = "".join(str(name or "").split())  # 모든 공백 제거
    return TB_COUNTRY_ALIASES.get(s, s)


TB_CANONICAL_SET: frozenset[str] = frozenset(_normalize_country(c) for c in TB_HIGH_RISK_COUNTRIES)
TB_CANONICAL_COUNT = len(TB_CANONICAL_SET)  # 35

# 폐기된 과거(잘못된) 결핵 판정 문구 — 하나라도 있으면 게시/공개 차단.
TB_BANNED_PHRASES: tuple[str, ...] = (
    "90일을 초과하는 장기체류",
    "최근 6개월 이내 결핵검진",
    "최근 6개월 이내 결핵검진 확인서 제출 이력",
    "6개월내 검진 제출이력",
)


def _config_text_blob(cfg: dict) -> str:
    parts = [str(cfg.get("item_name") or "")]
    for q in cfg.get("questions") or []:
        if isinstance(q, dict):
            parts += [str(q.get("text") or ""), str(q.get("summary") or ""), str(q.get("help") or "")]
    for r in cfg.get("results") or []:
        if isinstance(r, dict):
            parts += [str(r.get("headline") or ""), str(r.get("label") or ""), str(r.get("notice_text") or "")]
    return "\n".join(parts)


def _is_tb_config(cfg: dict) -> bool:
    """TB(결핵) 성격의 config 인가 — item_name 에 결핵 포함 또는 logic_version 이 TB 계열."""
    if not isinstance(cfg, dict):
        return False
    name = str(cfg.get("item_name") or "")
    lv = str(cfg.get("logic_version") or "").upper()
    return "결핵" in name or lv.startswith("TB")


def _tb_verification(cfg: dict) -> dict:
    """TB 항목 게시 가능성 검사. reasons 가 비어야 게시 가능(서버가 최종 권위)."""
    reasons: list[str] = []
    if not isinstance(cfg, dict):
        return {"ok": False, "reasons": ["설정 형식 오류"], "count": 0, "dup": 0,
                "matches": False, "has_source": False, "banned": False, "version_ok": False}
    version_ok = str(cfg.get("logic_version") or "") == "TB-1.0"
    if not version_ok:
        reasons.append("로직 버전이 TB-1.0 이 아닙니다.")

    raw = [str(c).strip() for c in (cfg.get("country_list") or []) if str(c).strip()]
    norm = [_normalize_country(c) for c in raw]
    count = len(norm)
    uniq = set(norm)
    dup = len(norm) - len(uniq)
    matches = uniq == set(TB_CANONICAL_SET)
    if count != TB_CANONICAL_COUNT:
        reasons.append(f"국가 목록이 정확히 {TB_CANONICAL_COUNT}개가 아닙니다(현재 {count}개).")
    if dup:
        reasons.append("국가 목록에 중복이 있습니다.")
    if not matches:
        reasons.append("공식 35개국 목록과 일치하지 않습니다.")

    has_source = all(str(cfg.get(k) or "").strip() for k in
                     ("country_list_source_title", "country_list_source_date", "country_list_verified_at"))
    if not has_source:
        reasons.append("출처 정보(source metadata)가 없습니다.")

    blob = _config_text_blob(cfg)
    banned = any(b in blob for b in TB_BANNED_PHRASES)
    if banned:
        reasons.append("폐기된 과거 문구가 포함되어 있습니다.")

    return {"ok": not reasons, "reasons": reasons, "count": count, "dup": dup,
            "matches": matches, "has_source": has_source, "banned": banned, "version_ok": version_ok}


def _is_obsolete_legacy_selfcheck(raw: Any) -> bool:
    """운영 DB 의 기존 '단일 설정'이 폐기 대상 구형 결핵 로직인지 판정(자동 삭제·수정 없음).

    v2 번들(items 배열)은 항목별 게시 검증이 담당하므로 여기서 판정하지 않는다.
    레거시 단일 config(questions/results 최상위)만 대상으로 한다."""
    if not isinstance(raw, dict):
        return False
    if isinstance(raw.get("items"), list):
        return False  # v2 번들 — 대상 아님
    if not (isinstance(raw.get("questions"), list) and isinstance(raw.get("results"), list)):
        return False
    cfg = raw
    name = str(cfg.get("item_name") or "")
    lv = str(cfg.get("logic_version") or "").upper()
    blob = _config_text_blob(cfg)
    # ① item_name 에 결핵 + logic_version == CR-1.0 (해외범죄경력 로직을 결핵에 잘못 쓴 흔적)
    if "결핵" in name and lv == "CR-1.0":
        return True
    # ②~④ 폐기 문구
    if any(b in blob for b in TB_BANNED_PHRASES):
        return True
    # ⑤~⑥ 결핵 항목인데 필수 질문 누락
    if _is_tb_config(cfg):
        qtexts = [str(q.get("text") or "") for q in (cfg.get("questions") or []) if isinstance(q, dict)]
        if not any("6세" in t for t in qtexts):
            return True  # 만 6세 질문 없음
        has_stay = any(("6개월" in t and ("이상" in t or "계속" in t) and "최근 6개월 이내" not in t) for t in qtexts)
        if not has_stay:
            return True  # 제출/발급 이후 별도 6개월 체류 질문 없음
    return False


class ConfigSave(BaseModel):
    # 다중 항목 번들(schema v2). 레거시 단일 config 저장도 계속 허용(하위호환).
    bundle: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    is_published: bool = False


# ── 그래프 무결성 검증 (frontend lib/selfcheck/logic.ts validateConfig 와 동일 개념) ──
# 반환: {"errors": [...], "warnings": [...]}. errors 는 게시 차단, warnings 는 안내.
# 프론트/백엔드 결과가 동일하도록 검사 항목·판정 기준을 맞춘다.
def _validate_config_report(cfg: dict) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(cfg, dict):
        return {"errors": ["설정 형식이 올바르지 않습니다."], "warnings": []}
    questions = cfg.get("questions") or []
    results = cfg.get("results") or []
    qids = [q.get("id") for q in questions]
    rids = [r.get("id") for r in results]
    if len(qids) != len(set(qids)):
        errors.append("중복 question_id")
    if len(rids) != len(set(rids)):
        errors.append("중복 result_id")
    idset = set(qids) | set(rids)
    if set(qids) & set(rids):
        errors.append("question/result id 충돌")
    if not (cfg.get("logic_version") or "").strip():
        errors.append("로직 버전 누락")
    if not results:
        errors.append("결과가 없습니다.")
    qmap = {q.get("id"): q for q in questions}
    for q in questions:
        for br, ko in (("yes", "예"), ("no", "아니오")):
            tgt = q.get(br)
            if not tgt or tgt not in idset:
                errors.append(f"질문 {q.get('id')}의 '{ko}' 대상({tgt or '없음'})이 존재하지 않습니다.")
    start = cfg.get("start_question_id")
    if not start or start not in qmap:
        errors.append("시작 질문이 없거나 유효하지 않습니다.")
        return {"errors": errors, "warnings": warnings}  # 시작 없으면 도달성/순환 분석 불가

    # 순환 감지 + 도달성(DFS 컬러링). 도달한 질문/결과 집계.
    color: dict[str, int] = {}
    reachable_q: set = set()
    reachable_r: set = set()
    cycle = {"v": False}

    def dfs(node: str) -> None:
        if node in rids:
            reachable_r.add(node)
            return
        q = qmap.get(node)
        if not q:
            return
        if color.get(node) == 1:
            cycle["v"] = True
            return
        if color.get(node) == 2:
            return
        color[node] = 1
        reachable_q.add(node)
        for br in ("yes", "no"):
            tgt = q.get(br)
            if tgt in idset:
                dfs(tgt)
        color[node] = 2

    dfs(start)
    if cycle["v"]:
        errors.append("질문 순환(loop)이 감지되었습니다. 모든 경로가 결과로 끝나야 합니다.")
    # 도달 불가 경고
    for q in questions:
        if q.get("id") not in reachable_q:
            warnings.append(f"도달 불가능한 질문: {q.get('id')}")
    for r in results:
        if r.get("id") not in reachable_r:
            warnings.append(f"도달 불가능한 결과: {r.get('id')}")
    if not cycle["v"] and len(reachable_r) == 0:
        errors.append("어떤 경로에서도 결과에 도달하지 못합니다.")
    return {"errors": errors, "warnings": warnings}


# 하위호환 + 간결 호출용 — errors 리스트만 반환.
def _validate_config(cfg: dict, for_publish: bool = False) -> list[str]:
    return _validate_config_report(cfg)["errors"]


def _load_row(suppress_errors: bool = True) -> dict | None:
    """저장 row 조회. 반환 None = 실제 '설정 없음'.

    - suppress_errors=True (공개 경로): 저장 계층 오류를 잡아 None 반환(fail-closed, 빈 items).
      개인정보 없이 오류 '종류'만 로그.
    - suppress_errors=False (관리자 경로): 오류를 삼키지 않고 SelfCheckConfigUnavailable 로 전파
      → '설정 없음'과 '조회 실패'를 구별(관리자에게 503)."""
    from backend.services import marketing_pg_service as mk
    try:
        return mk.get_post(CONFIG_ID)
    except Exception as e:  # noqa: BLE001
        if not suppress_errors:
            raise SelfCheckConfigUnavailable(type(e).__name__) from e
        try:
            logger.warning("self-check public config load failed: %s", type(e).__name__)
        except Exception:  # noqa: BLE001
            pass
        return None


def _parse_content(row: dict | None) -> tuple[Any, bool]:
    """(parsed_json | None, row_published)."""
    if not row:
        return None, False
    published = str(row.get("is_published", "")).upper() in ("TRUE", "Y", "1")
    raw = row.get("content") or ""
    try:
        return (json.loads(raw) if raw else None), published
    except Exception:
        return None, published


def _normalize_bundle(raw: Any, legacy_published: bool = False) -> dict:
    """저장 content(신규 번들 | 레거시 단일 config) → {schema_version:2, items:[...]}.

    프론트 lib/selfcheck/logic.ts normalizeBundle 과 동일 개념. 파괴적 변경 없음."""
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        items = []
        for i, it in enumerate(raw["items"]):
            if not isinstance(it, dict) or not isinstance(it.get("config"), dict):
                continue
            items.append({
                "item_id": str(it.get("item_id") or "").strip(),
                "title": it.get("title") or "",
                "description": it.get("description"),
                "sort_order": it.get("sort_order") if isinstance(it.get("sort_order"), (int, float)) else i,
                "is_published": bool(it.get("is_published")),
                "popup_enabled": it.get("popup_enabled") is not False,
                "placement": it.get("placement") if isinstance(it.get("placement"), list) else [],
                "config": it["config"],
            })
        return {"schema_version": 2, "items": items}
    if isinstance(raw, dict) and isinstance(raw.get("questions"), list) and isinstance(raw.get("results"), list):
        # 레거시 단일 config → 기존 공개 상태 보존을 위해 placement 를 ["home"] 으로 해석.
        return {"schema_version": 2, "items": [{
            "item_id": "legacy", "title": raw.get("item_name") or "기존 설정", "description": None,
            "sort_order": 0, "is_published": bool(legacy_published), "popup_enabled": True,
            "placement": ["home"], "config": raw,
        }]}
    return {"schema_version": 2, "items": []}


def _public_items(bundle: dict, placement: str | None = None) -> list[dict]:
    """게시 + 팝업 + 그래프 유효 + (placement 지정 시) 노출 위치 포함 항목만, sort_order 정렬.

    추가 fail-closed: 게시된 TB(결핵) 항목이 공식 35개국·출처 검증을 통과하지 못하면 공개에서 제외
    (검증 안 된 구형 결핵 설정이 공개로 흘러가는 것을 막는다 — 서버가 최종 권위)."""
    out = []
    for it in bundle.get("items", []):
        if not it.get("is_published") or it.get("popup_enabled") is False:
            continue
        cfg = it.get("config") or {}
        if _validate_config_report(cfg)["errors"]:
            continue
        if (it.get("item_id") == "tuberculosis" or _is_tb_config(cfg)) and not _tb_verification(cfg)["ok"]:
            continue
        if placement is not None:
            places = it.get("placement") if isinstance(it.get("placement"), list) else []
            if placement not in places:
                continue
        out.append(it)
    out.sort(key=lambda x: x.get("sort_order", 0))
    return out


# ── 공개: 게시된 유효 항목만 반환(사용자 답변 미수집) ─────────────────────────
# no-store 로 응답 → 관리자가 비공개 전환 시 프록시/브라우저 캐시로 늦게 반영되지 않음.
# fail-closed: (1) marketing row 자체가 비공개면 내부 항목이 게시여도 공개하지 않는다.
# (2) 손상/미게시/그래프오류/위치불일치 항목 제외. 잘못된 설정을 공개로 흘리지 않는다.
@router.get("/config")
def public_get_config(response: Response, placement: str | None = None):
    response.headers["Cache-Control"] = "no-store"
    raw, row_published = _parse_content(_load_row())
    if not row_published:
        return {"schema_version": 2, "items": []}  # 최상위 row 비공개 → 전면 차단
    # PART C: 폐기 대상 구형 결핵 legacy 는 게시 상태여도 공개에서 즉시 숨긴다(DB 자동 변경 없음).
    if _is_obsolete_legacy_selfcheck(raw):
        return {"schema_version": 2, "items": []}
    # PART C: v2 번들 구조가 손상이면 부분 공개하지 않고 전체 fail-closed(정상 item 만 골라 흘리지 않음).
    if isinstance(raw, dict) and isinstance(raw.get("items"), list) and _structural_bundle_errors(raw):
        return {"schema_version": 2, "items": []}
    bundle = _normalize_bundle(raw, legacy_published=True)
    # PART D: placement fail-closed — query 없으면 home 으로 해석(위치 필터를 해제하지 않는다).
    # 지원하지 않는 위치 값은 전면 미노출(우회로 전체 반환되는 것을 막는다).
    place = placement if (placement is not None and placement != "") else "home"
    if place not in SUPPORTED_PLACEMENTS:
        return {"schema_version": 2, "items": []}
    return {"schema_version": 2, "items": _public_items(bundle, placement=place)}


# ── 관리자: 편집용 조회 — 조회실패/설정없음/정상/손상을 명확히 구별 ─────────────
# 원칙: 조회 실패를 '설정 없음'으로 위장하지 않는다. 손상 설정은 편집기·저장을 차단한다.
# 어떤 경우에도 기본(PDF) 설정을 자동 반환하지 않고, 운영 DB 를 자동 수정·삭제하지 않는다.
def _corrupt(errors: list[str]):
    return HTTPException(status_code=409, detail={
        "code": "SELF_CHECK_CONFIG_CORRUPT",
        "message": "저장된 자가점검 설정이 손상되어 안전하게 편집할 수 없습니다.",
        "errors": errors})


@router.get("/admin/config")
def admin_get_config(user: dict = Depends(require_system_admin)):
    try:
        row = _load_row(suppress_errors=False)   # 조회 실패를 삼키지 않음
    except SelfCheckConfigUnavailable:
        raise HTTPException(status_code=503, detail={
            "code": "SELF_CHECK_CONFIG_UNAVAILABLE",
            "message": "자가점검 설정을 불러오지 못했습니다. 잠시 후 다시 시도하세요."})
    # 설정 없음(빈 content 포함) → absent (기본안 자동 반환 금지)
    if not row or not (row.get("content") or "").strip():
        return {"schema_version": 2, "items": [], "config_state": "absent", "obsolete_legacy": False}
    published = str(row.get("is_published", "")).upper() in ("TRUE", "Y", "1")
    try:
        raw = json.loads(row["content"])
    except Exception:
        raise _corrupt(["JSON 파싱 실패"])   # 손상 JSON → 409(부분/기본 반환 없음)
    # v2 번들: 저장 raw 전체를 strict 검사(malformed item 조용한 제거 금지)
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        errs = _structural_bundle_errors(raw)
        if errs:
            raise _corrupt(errs)
        bundle = _normalize_bundle(raw, legacy_published=published)
        return {**bundle, "config_state": "valid", "obsolete_legacy": False}
    # 레거시 단일 config
    if isinstance(raw, dict) and isinstance(raw.get("questions"), list) and isinstance(raw.get("results"), list):
        bundle = _normalize_bundle(raw, legacy_published=published)
        return {**bundle, "config_state": "legacy", "obsolete_legacy": _is_obsolete_legacy_selfcheck(raw)}
    # 인식 불가 구조 → 손상 취급(기본안 자동 반환 금지)
    raise _corrupt(["알 수 없는 설정 구조"])


# ── 쓰기 엄격 검증: 잘못된 item 을 조용히 버리지 않는다(하나라도 손상 시 전체 400) ──
def _structural_bundle_errors(raw: Any) -> list[str]:
    """저장 요청 bundle 의 구조 무결성 검사(그래프 무결성과 별개). 오류 목록 반환."""
    errs: list[str] = []
    if not isinstance(raw, dict):
        return ["bundle 이 객체가 아닙니다."]
    if raw.get("schema_version") != 2:
        errs.append("schema_version 은 2 여야 합니다.")
    items = raw.get("items")
    if not isinstance(items, list):
        return errs + ["items 가 배열이 아닙니다."]
    seen: set[str] = set()
    for idx, it in enumerate(items):
        tag = f"항목[{idx}]"
        if not isinstance(it, dict):
            errs.append(f"{tag} 이(가) 객체가 아닙니다.")
            continue
        iid = it.get("item_id")
        if not isinstance(iid, str) or not iid.strip():
            errs.append(f"{tag} item_id 가 비어 있습니다.")
        else:
            if iid in seen:
                errs.append(f"중복 item_id: {iid}")
            seen.add(iid)
        if not isinstance(it.get("title"), str) or not it.get("title").strip():
            errs.append(f"{tag} title 이 비어 있습니다.")
        so = it.get("sort_order")
        if not isinstance(so, (int, float)) or isinstance(so, bool) or so != so or so in (float("inf"), float("-inf")):
            errs.append(f"{tag} sort_order 가 유효한 숫자가 아닙니다.")
        if not isinstance(it.get("is_published"), bool):
            errs.append(f"{tag} is_published 가 boolean 이 아닙니다.")
        if not isinstance(it.get("popup_enabled"), bool):
            errs.append(f"{tag} popup_enabled 가 boolean 이 아닙니다.")
        pl = it.get("placement")
        if not isinstance(pl, list) or not all(isinstance(p, str) for p in pl):
            errs.append(f"{tag} placement 가 문자열 배열이 아닙니다.")
        cfg = it.get("config")
        if not isinstance(cfg, dict):
            errs.append(f"{tag} config 가 객체가 아닙니다.")
        else:
            if not isinstance(cfg.get("questions"), list):
                errs.append(f"{tag} config.questions 가 배열이 아닙니다.")
            if not isinstance(cfg.get("results"), list):
                errs.append(f"{tag} config.results 가 배열이 아닙니다.")
    return errs


# ── 관리자: 저장 + 게시(검증 통과 시에만) ─────────────────────────────────────
@router.put("/admin/config")
def admin_save_config(body: ConfigSave, user: dict = Depends(require_system_admin)):
    # 번들 우선. 레거시 {config,is_published} 는 item 1개 번들로 감싼다(하위호환).
    if body.bundle is not None:
        # 쓰기 엄격 검증: 구조 손상 item 이 하나라도 있으면 400(조용한 제거 금지).
        struct_errs = _structural_bundle_errors(body.bundle)
        if struct_errs:
            raise HTTPException(status_code=400, detail={"message": "저장할 수 없는 손상된 설정입니다.", "errors": struct_errs})
        # 구조 검증을 통과한 원본을 그대로 저장(item 손실 없음). 타입은 이미 검증됨.
        bundle = {"schema_version": 2, "items": [dict(it) for it in body.bundle["items"]]}
    elif body.config is not None:
        bundle = {"schema_version": 2, "items": [{
            "item_id": "legacy", "title": body.config.get("item_name") or "기존 설정",
            "description": None, "sort_order": 0, "is_published": bool(body.is_published),
            "popup_enabled": True, "placement": ["home"], "config": body.config,
        }]}
    else:
        raise HTTPException(status_code=400, detail={"message": "bundle 또는 config 가 필요합니다.", "errors": ["빈 요청"]})

    # item_id 중복/빈값(레거시 경로 방어 — 번들 경로는 위에서 이미 검증).
    ids = [it["item_id"] for it in bundle["items"]]
    if len(ids) != len(set(ids)):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        raise HTTPException(status_code=400, detail={"message": "item_id 가 중복되었습니다.", "errors": [f"중복 item_id: {', '.join(dup)}"]})
    if any(not i for i in ids):
        raise HTTPException(status_code=400, detail={"message": "item_id 가 비어 있는 항목이 있습니다.", "errors": ["빈 item_id"]})

    # 게시하려는 항목은 그래프 오류가 없어야 한다(비공개 draft 는 그래프 오류 허용).
    item_errors: dict[str, list[str]] = {}
    for it in bundle["items"]:
        rep = _validate_config_report(it.get("config") or {})
        if rep["errors"]:
            item_errors[it["item_id"]] = rep["errors"]
    publish_blocked = {iid: errs for iid, errs in item_errors.items()
                       if next((it for it in bundle["items"] if it["item_id"] == iid), {}).get("is_published")}
    if publish_blocked:
        raise HTTPException(status_code=400, detail={
            "message": "게시하려는 항목의 오류를 먼저 수정하세요.", "item_errors": publish_blocked})

    # ── PART B: TB(결핵) 항목 게시 검증 — 공식 35개국·출처·폐기문구 부재를 강제 ──
    # 게시하려는 TB 항목은 검증 통과 필수(400). 비공개 draft 는 저장 허용하되 경고를 반환한다.
    tb_publish_blocked: dict[str, list[str]] = {}
    tb_warnings: dict[str, list[str]] = {}
    for it in bundle["items"]:
        cfg = it.get("config") or {}
        if not (it.get("item_id") == "tuberculosis" or _is_tb_config(cfg)):
            continue
        rep = _tb_verification(cfg)
        if rep["ok"]:
            continue
        if it.get("is_published"):
            tb_publish_blocked[it["item_id"]] = rep["reasons"]
        else:
            tb_warnings[it["item_id"]] = rep["reasons"]
    if tb_publish_blocked:
        raise HTTPException(status_code=400, detail={
            "code": "TB_COUNTRY_LIST_NOT_VERIFIED",
            "message": "결핵 고위험 국가 공식 35개국 목록과 확인 정보를 먼저 확정하세요.",
            "item_errors": tb_publish_blocked})

    from backend.services import marketing_pg_service as mk
    from backend.db.session import is_configured
    if not is_configured():
        raise HTTPException(status_code=503, detail="데이터베이스가 구성되지 않았습니다.")
    any_published = any(it.get("is_published") for it in bundle["items"])
    rec = {
        "id": CONFIG_ID,
        "title": "공통기준 자가점검",
        "slug": CONFIG_ID,
        "category": CONFIG_CATEGORY,
        "content": json.dumps(bundle, ensure_ascii=False),
        "is_published": "TRUE" if any_published else "FALSE",
        "created_by": user.get("login_id", ""),
    }
    try:
        mk.upsert_post(rec)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"저장 실패: {e}")
    return {"ok": True, "published_items": [it["item_id"] for it in bundle["items"] if it.get("is_published")],
            "item_errors": item_errors, "tb_warnings": tb_warnings}
