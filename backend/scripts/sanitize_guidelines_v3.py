# -*- coding: utf-8 -*-
"""실무지침 v3 운영 JSON sanitize — 출처성 키/문구 제거(정본 구현, tracked).

운영 산출물(backend/data/guidelines_v3/*.json)에는 매뉴얼 출처 표기·내부 검토 이력이
남지 않아야 한다. 이 모듈이 규칙의 단일 정본이며, v3 생성기는 산출 직전에 반드시
`sanitize_dataset()`/`sanitize_meta()`를 호출한다(생성기 재실행 시 복원 방지).

단독 실행(이미 생성된 JSON을 제자리 정리):
    python -m backend.scripts.sanitize_guidelines_v3            # 검사만(변경 필요 여부 리포트)
    python -m backend.scripts.sanitize_guidelines_v3 --write    # 제자리 정리 실행

멱등: 동일 입력 → 동일 출력(고정 정규식·치환표만 사용).
"""
from __future__ import annotations

import json
import os
import re
import sys

# 운영 산출물에서 통째로 제거하는 키(내부 출처/인용 필드)
STRIP_KEYS = ("source_pages", "source_manual", "source_quote", "source_summary")

# 운영 노출 금지 표현(값 검사용). '법무부장관 승인' 등 법령 실체 문구는 ALLOW로 예외.
FORBIDDEN = ["source_pages", "source_manual", "근거", "페이지", "정독", "원문", "발췌",
             "OCR", "오염", "복제", "편람", "체류관리편람", "2026-07", "사용자 승인",
             "내부 참고", "최신 재확인", "base-build", "원문 재확인", "원문재확인",
             "reuse", "복사"]
PAGEREF = re.compile(r"\(?p\.?\s*\d+", re.I)
ALLOW = ["법무부장관 승인", "법무부장관의 승인", "승인 대상", "승인을 받아"]

# 일반 규칙으로 문장이 어색해지는 소수 항목의 확정 문안(결론 보존형)
OVERRIDES = {
    ("stay_blocks", "SB:E-10_CHANGE", "conflict"):
        "기존 지침과 매뉴얼 기준 충돌 — 확인 필요. 매뉴얼 기준은 '체류자격 변경허가 해당사항 없음'으로 명시하나 기존 지침(E-10 변경)이 있습니다. 관서 확인 전까지는 기존 지침 기준으로 안내하세요.",
    ("visa_routes", "VR:F-1-23_CONSULATE", "review_note"):
        "초기 가정은 '가사보조인 묶음(22·23·24) 인정 경로 준용'이었으나 재검토로 공관장재량 경로(인정서 절 미열거)로 정정 확정.",
}

_PHRASES = [
    ("원문 재확인", "확인 필요"),
    ("재정독", "재검토"),
    ("정독 완료", "검토 완료"),
    ("원문 정독", "매뉴얼 기준 검토"),
    ("발췌 원문", "매뉴얼 기준"),
    ("원문상", "매뉴얼 기준상"),
    ("원문에", "매뉴얼 기준에"),
    ("원문은", "매뉴얼 기준은"),
    ("원문이", "매뉴얼 기준이"),
    ("원문과", "매뉴얼 기준과"),
    ("원문", "매뉴얼 기준"),
    ("정독", "검토"),
    ("발췌", "확인"),
    ("근거 노트", "참고 노트"),
    ("근거로", "기준으로"),
    ("근거가", "기준이"),
    ("근거", "기준"),
    ("내부 참고", "참고"),
    ("최신 재확인", "재확인"),
    ("사용자 승인으로", ""),
    ("사용자 승인", ""),
]

_SEG_SEP = " | "

TEXT_FIELDS = {
    "stay_blocks": ["notes", "na_reason", "conflict", "redirect_to", "exceptions"],
    "visa_routes": ["notes", "review_note", "exceptions", "docs_notice", "route_label",
                    "application_place", "application_form"],
    "document_requirements": ["notes", "condition", "display_condition"],
    "qualification_master": ["notes", "activity_scope", "eligible_persons", "stay_limit", "name_ko"],
    "v2_mapping": [],
    "aux_civil": ["notes", "description", "name"],
    "program_tags": ["description", "notes", "program_name"],
}
ID_KEYS = {
    "stay_blocks": "block_id", "visa_routes": "route_id",
    "document_requirements": "requirement_id", "qualification_master": "qualification_id",
    "v2_mapping": "v2_row_id", "aux_civil": "aux_id", "program_tags": "program_id",
}
FILE_NAMES = {
    "stay_blocks": "stay_blocks.json", "visa_routes": "visa_routes.json",
    "document_requirements": "document_requirements.json",
    "qualification_master": "qualification_master.json", "v2_mapping": "v2_mapping.json",
    "aux_civil": "aux_civil.json", "program_tags": "program_tags.json",
}


def _scrub_segment(s: str) -> str:
    t = s
    t = re.sub(r"정독\([^)]*\)\s*(확정)?\s*[:：]?\s*", "", t)
    t = re.sub(r"\(\s*20\d{2}-\d{2}-\d{2}[^)]*\)", "", t)
    t = re.sub(r"20\d{2}-\d{2}-\d{2}\s*(확정|기준)?\s*[:：]?\s*", "", t)
    t = re.sub(r"\(\d차[^)]*\)", "", t)
    t = re.sub(r"\([^)]*?p\.?\s*\d+[^)]*?\)", "", t)
    t = re.sub(r"p\.?\s*\d+(\s*[–~\-]\s*\d+)?", "", t)
    for a, b in _PHRASES:
        t = t.replace(a, b)
    t = re.sub(r"\s{2,}", " ", t)
    t = re.sub(r"\s+([,.·)\]』»])", r"\1", t)
    t = re.sub(r"([(\[『«])\s+", r"\1", t)
    t = re.sub(r"(^|\s)[—·:：,]+\s*(?=$|\s)", " ", t)
    t = t.strip(" —·|,:：")
    t = re.sub(r"\(\s*\)", "", t).strip()
    return t.strip()


def _is_forbidden(s: str) -> bool:
    m = s
    for a in ALLOW:
        m = m.replace(a, "")
    return any(w in m for w in FORBIDDEN) or bool(PAGEREF.search(m))


def scrub_text(s: str):
    """반환: (정제문, 변경여부, 잔여금지어여부). 정제 불능 세그먼트는 폐기."""
    if not s or not _is_forbidden(s):
        return s, False, False
    segs = s.split(_SEG_SEP) if _SEG_SEP in s else [s]
    keep = []
    for seg in segs:
        c = _scrub_segment(seg)
        if not c or _is_forbidden(c):
            continue
        keep.append(c)
    cleaned = _SEG_SEP.join(keep).strip()
    if len(cleaned) < 4:
        cleaned = ""
    return cleaned, True, _is_forbidden(cleaned) if cleaned else False


def sanitize_dataset(name: str, rows: list):
    """단일 데이터셋 sanitize(제자리 수정). 반환: (counts, provenance, human_review)."""
    counts = {"keys_removed": 0, "reason_removed": 0, "text_cleaned": 0,
              "text_emptied": 0, "condition_replaced": 0, "target_ids_fixed": 0}
    prov, human = [], []
    idk = ID_KEYS[name]
    for row in rows:
        rid = row.get(idk) or "?"
        for k in STRIP_KEYS:
            if k in row:
                prov.append({"file": name, "id": rid, "field": k, "removed_value": row.pop(k)})
                counts["keys_removed"] += 1
        # 미사용 스키마 키(키명이 금지어) — 값이 없을 때만 제거
        if name == "document_requirements" and "reuse_of" in row and not row.get("reuse_of"):
            row.pop("reuse_of")
            counts["keys_removed"] += 1
        if name == "v2_mapping":
            if "reason" in row:
                prov.append({"file": name, "id": rid, "field": "reason", "removed_value": row.pop("reason")})
                counts["reason_removed"] += 1
            tids = row.get("v3_target_ids") or []
            fixed = [re.sub(r"\([^)]*\)", "", t).strip() for t in tids]
            if fixed != tids:
                prov.append({"file": name, "id": rid, "field": "v3_target_ids", "removed_value": tids})
                row["v3_target_ids"] = fixed
                counts["target_ids_fixed"] += 1
            continue
        if name == "document_requirements":
            cond = row.get("condition")
            disp = (row.get("display_condition") or "").strip()
            if cond and _is_forbidden(cond) and disp and not _is_forbidden(disp):
                prov.append({"file": name, "id": rid, "field": "condition", "removed_value": cond})
                row["condition"] = disp
                counts["condition_replaced"] += 1
        for f in TEXT_FIELDS[name]:
            v = row.get(f)
            if v is None:
                continue
            if (name, rid, f) in OVERRIDES:
                nv = OVERRIDES[(name, rid, f)]
                if v != nv:
                    prov.append({"file": name, "id": rid, "field": f, "removed_value": v})
                    row[f] = nv
                    counts["text_cleaned"] += 1
                continue
            if isinstance(v, list):
                newlist, changed = [], False
                for item in v:
                    c, ch, _still = scrub_text(item)
                    if ch:
                        changed = True
                    if c:
                        newlist.append(c)
                    elif ch:
                        human.append({"file": name, "id": rid, "field": f, "original": item})
                if changed:
                    prov.append({"file": name, "id": rid, "field": f, "removed_value": v})
                    row[f] = newlist
                    counts["text_cleaned"] += 1
                continue
            if not isinstance(v, str):
                continue
            c, ch, still = scrub_text(v)
            if not ch:
                continue
            prov.append({"file": name, "id": rid, "field": f, "removed_value": v})
            if not c:
                human.append({"file": name, "id": rid, "field": f, "original": v})
                counts["text_emptied"] += 1
                row[f] = ""
            else:
                counts["text_cleaned"] += 1
                row[f] = c
            if still:
                human.append({"file": name, "id": rid, "field": f, "original": v,
                              "note": "정제 후 잔여 — 확인 필요", "cleaned": c})
    return counts, prov, human


def sanitize_meta(meta: dict):
    """_meta.json — 출처성 메타 키 제거(status/counts 등 검증 필수 키는 유지)."""
    prov = []
    for k in ("source_manuals", "generated"):
        if k in meta:
            prov.append({"file": "_meta", "id": "_meta", "field": k, "removed_value": meta.pop(k)})
    return prov


def sanitize_dir(data_dir: str, write: bool = False):
    """이미 생성된 v3 JSON 디렉터리를 검사(기본)하거나 제자리 정리(--write)."""
    total_changed = 0
    for name, fn in FILE_NAMES.items():
        path = os.path.join(data_dir, fn)
        rows = json.load(open(path, encoding="utf-8"))
        counts, _prov, _human = sanitize_dataset(name, rows)
        changed = sum(counts.values())
        total_changed += changed
        if changed and write:
            json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{fn}: {'변경 ' + str(changed) + '건' if changed else '정리 상태 유지'}"
              f"{' (기록됨)' if changed and write else ''}")
    meta_path = os.path.join(data_dir, "_meta.json")
    meta = json.load(open(meta_path, encoding="utf-8"))
    mp = sanitize_meta(meta)
    if mp and write:
        json.dump(meta, open(meta_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    total_changed += len(mp)
    print(f"_meta.json: {'변경 ' + str(len(mp)) + '건' if mp else '정리 상태 유지'}")
    return total_changed


if __name__ == "__main__":
    try:  # Windows cp949 콘솔 대비
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    d = os.path.join(root, "backend", "data", "guidelines_v3")
    do_write = "--write" in sys.argv
    n = sanitize_dir(d, write=do_write)
    if n and not do_write:
        print(f"총 {n}건 정리 필요 — '--write'로 실행하면 제자리 정리합니다.")
        sys.exit(1)
    print("OK — 운영 JSON 정리 상태" + (" (반영 완료)" if do_write and n else ""))
