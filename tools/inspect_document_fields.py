"""문서 자동작성 필드명 진단 CLI (PDF AcroForm ↔ HWPX 누름틀 ↔ build_field_values 키 비교).

기존 PDF/HWPX 템플릿·코드를 **읽기 전용**으로만 분석한다. 어떤 파일도 수정하지 않는다.

추출/비교 대상
  A. PDF 템플릿의 AcroForm/widget 필드명           (PyMuPDF)
  B. HWPX 템플릿의 누름틀(CLICK_HERE) 필드명         (utils.hwpx_document)
  C. build_field_values() 가 생성하는 field_values 키 (샘플 데이터로 1회 호출)
  D. ROLE_WIDGETS / ROLE_SIGN_WIDGETS (도장/서명 역할 필드명)
  E. HWPX BinData 이미지 + borderFill↔셀 매핑(도장 셀 진단)
  F. HWPX marker text([[yin]] 등)

사용:
  python tools/inspect_document_fields.py
  python tools/inspect_document_fields.py --pdf templates/통합신청서.pdf \
      --hwpx templates/hwpx/통합신청서.hwpx --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def extract_pdf_fields(pdf_path: str) -> dict:
    """PDF AcroForm widget 필드명(중복 제거, 등장 순) + 타입."""
    import fitz
    names: list = []
    types: dict = {}
    with fitz.open(pdf_path) as d:
        for pg in d:
            for w in (pg.widgets() or []):
                n = w.field_name
                if n not in types:
                    names.append(n)
                    types[n] = w.field_type_string
    return {"fields": names, "types": types}


def sample_field_values() -> dict:
    """build_field_values() 를 대표 샘플 데이터로 1회 호출해 키 집합을 얻는다.

    값 자체는 의미 없다(키 비교용). 체류-변경-F-5 시나리오로 changew/aggregator 분기까지 커버.
    """
    from backend.routers.quick_doc import build_field_values
    applicant = {
        "성": "KIM", "명": "CHULSOO", "한글": "김철수", "등록증": "900101", "번호": "1234567",
        "여권": "M12345678", "발급": "2020-01-01", "만기": "2030-01-01", "국적": "베트남",
        "주소": "서울시 ...", "연": "010", "락": "1234", "처": "5678", "희망자격": "F-5",
        "환불계좌": "1002-...", "신청이유": "테스트", "배우자": "", "부모": "",
    }
    guarantor = dict(applicant, 한글="보증인", 등록증="850202", 번호="2000000", 주소="부산시 ...")
    guardian = dict(applicant, 한글="대리인")
    aggregator = dict(applicant, 한글="합산자")
    accommodation = dict(applicant, 한글="숙소제공자")
    account = {"office_name": "한우리행정사", "contact_name": "담당자", "agent_rrn": "",
               "biz_reg_no": "000-00-00000", "contact_tel": "02-000-0000", "office_adr": "서울"}
    fv = build_field_values(
        row=applicant, prov=accommodation, accommodation_provider=None,
        guardian=guardian, guarantor=guarantor, aggregator=aggregator,
        is_minor=False, account=account,
        category="체류", minwon="변경", kind="F", detail="5",
    )
    # generate_full 이 요청 시점에 추가하는 날짜/관계 키도 키 비교 대상에 포함(실제 출력 키와 일치시킴)
    fv.setdefault("작성년", "")
    fv.setdefault("월", "")
    fv.setdefault("일", "")
    fv.setdefault("rela", "")
    return fv


def diagnose_pdf_field_fill(pdf_path: str, field_values: dict, field_name: str,
                            render_modes=("field_ap", "acroform")) -> dict:
    """주어진 PDF 누름틀이 **실제 출력 PDF에서 값이 채워지는지** 경험적으로 확인한다.

    기존 PDF 생성 함수(``fill_and_append_pdf``)를 그대로 호출해 결과 PDF를 만든 뒤, 해당
    위젯의 ``field_value`` 를 다시 읽어 비어 있지 않으면 "채워짐"으로 본다. 추정이 아니라 실측이다.
    """
    import fitz
    from backend.routers.quick_doc import fill_and_append_pdf
    empty = {"applicant": None, "accommodation": None, "guarantor": None,
             "guardian": None, "aggregator": None, "agent": None}
    out: dict = {}
    for mode in render_modes:
        value_seen = None
        try:
            merged = fitz.open()
            fill_and_append_pdf(pdf_path, field_values, empty, merged, empty, render_mode=mode)
            for pg in merged:
                for w in (pg.widgets() or []):
                    if w.field_name == field_name:
                        value_seen = w.field_value or ""
                        break
                if value_seen is not None:
                    break
            merged.close()
        except Exception as e:  # noqa: BLE001
            out[mode] = {"error": str(e)}
            continue
        out[mode] = {"filled": bool((value_seen or "").strip()), "value": value_seen}
    return out


def build_alias_diagnosis(pdf_path: str, fv: dict) -> dict:
    """``희망`` ↔ ``hope`` 핵심 불일치를 한눈에 보이도록 정리(숨김 변환 금지)."""
    from utils.hwpx_document import extract_hwpx_fields, HWPX_FIELD_ALIASES
    pdf = extract_pdf_fields(pdf_path) if os.path.exists(pdf_path) else {"fields": []}
    hwpx_fields = set(extract_hwpx_fields(
        os.path.join(_ROOT, "templates", "hwpx", "통합신청서.hwpx")
    )["unique_fields"]) if os.path.exists(os.path.join(_ROOT, "templates", "hwpx", "통합신청서.hwpx")) else set()
    pdf_fill = {}
    if os.path.exists(pdf_path):
        pdf_fill = diagnose_pdf_field_fill(pdf_path, fv, "희망")
    return {
        "pdf_field_name_present": "희망" in set(pdf["fields"]),
        "hwpx_field_name_present": "희망" in hwpx_fields,
        "field_values_has_희망": "희망" in fv,
        "field_values_has_hope": "hope" in fv,
        "hope_value_in_sample": fv.get("hope", "(없음)"),
        "pdf_희망_filled_actual": pdf_fill,   # 실측: 실제 PDF 출력에서 희망 위젯이 채워지는가
        "current_hwpx_alias": HWPX_FIELD_ALIASES,
    }


def build_missing_field_table(pdf_path: str, hwpx_path: str, fv: dict) -> list:
    """PDF 에는 있고 HWPX 에는 없는 본문 필드(why/bankaccount/card 등)를 표로 정리.

    "통합신청서 필요 여부" 는 개발자가 단정하지 않고 항상 '사용자 확인 필요' 로 둔다(임의 추가 금지).
    """
    from utils.hwpx_document import extract_hwpx_fields
    from backend.routers.quick_doc import ROLE_WIDGETS, ROLE_SIGN_WIDGETS
    pdf = extract_pdf_fields(pdf_path) if os.path.exists(pdf_path) else {"fields": [], "types": {}}
    pdf_set, pdf_types = set(pdf["fields"]), pdf.get("types", {})
    hwpx_set = set(extract_hwpx_fields(hwpx_path)["unique_fields"])
    fv_set = set(fv.keys())
    role_widget_names = set(ROLE_WIDGETS.values()) | set(ROLE_SIGN_WIDGETS.values())
    candidates = sorted((pdf_set - hwpx_set) - role_widget_names)
    rows = []
    for name in candidates:
        rows.append({
            "field": name,
            "pdf_type": pdf_types.get(name, "?"),
            "in_pdf": True,
            "in_hwpx": False,
            "in_field_values": name in fv_set,
            "needed_in_통합신청서": "사용자 확인 필요",   # 개발자 단정 금지
            "조치안": "임의로 HWPX 템플릿에 누름틀 추가 금지 — 사용자 확인 후 결정",
        })
    return rows


def build_report(pdf_path: str, hwpx_path: str) -> dict:
    from utils.hwpx_document import (extract_hwpx_fields, HWPX_FIELD_ALIASES, SEAL_MARKER_TO_ROLE,
                                     SIGN_MARKER_TO_ROLE, diagnose_seal_cells, diagnose_marker_cells)
    from backend.routers.quick_doc import ROLE_WIDGETS, ROLE_SIGN_WIDGETS

    pdf = extract_pdf_fields(pdf_path) if os.path.exists(pdf_path) else {"fields": [], "types": {}}
    hwpx = extract_hwpx_fields(hwpx_path)
    fv = sample_field_values()

    pdf_set = set(pdf["fields"])
    hwpx_set = set(hwpx["unique_fields"])
    fv_set = set(fv.keys())
    # alias 적용 후의 HWPX→field_values 해석 키
    hwpx_resolved = {HWPX_FIELD_ALIASES.get(n, n) for n in hwpx_set}

    # 역할 위젯(도장/서명)은 텍스트 필드 비교에서 제외하고 따로 본다.
    role_widget_names = set(ROLE_WIDGETS.values()) | set(ROLE_SIGN_WIDGETS.values())

    return {
        "pdf_fields": pdf["fields"],
        "pdf_field_types": pdf["types"],
        "hwpx_fields": hwpx["unique_fields"],
        "hwpx_field_counts": hwpx["field_counts"],
        "field_value_keys": sorted(fv_set),
        # 비교(역할 위젯 제외)
        "pdf_missing_in_hwpx": sorted((pdf_set - hwpx_set) - role_widget_names),
        "hwpx_missing_in_pdf": sorted(hwpx_set - pdf_set),
        "hwpx_missing_in_field_values": sorted(hwpx_resolved - fv_set),
        "field_values_unused_in_hwpx": sorted((fv_set - hwpx_resolved) - role_widget_names),
        "duplicate_hwpx_fields": hwpx["duplicate_fields"],
        # 도장/서명
        "role_widgets": ROLE_WIDGETS,
        "role_sign_widgets": ROLE_SIGN_WIDGETS,
        "seal_markers_in_template": hwpx["seal_markers"],
        "sign_markers_in_template": hwpx.get("sign_markers", {}),
        "seal_marker_map": SEAL_MARKER_TO_ROLE,
        "sign_marker_map": SIGN_MARKER_TO_ROLE,
        "pdf_role_widgets_present": sorted(pdf_set & role_widget_names),
        # HWPX 이미지/도장 셀 진단
        "hwpx_bin_images": hwpx["bin_images"],
        "hwpx_image_borderfills": hwpx["image_borderfills"],
        # alias
        "hwpx_field_aliases": HWPX_FIELD_ALIASES,
        # 희망↔hope 핵심 불일치 진단(실측 포함)
        "alias_diagnosis_희망_hope": build_alias_diagnosis(pdf_path, fv),
        # 도장 셀 진단: borderFill → section/셀 → marker 존재 여부(역할 추정 금지)
        "seal_cell_diagnosis": diagnose_seal_cells(hwpx_path),
        # marker 셀 진단(방식 B 준비): marker → 셀 borderFill → BinData 이미지 바인딩 여부
        "marker_cell_diagnosis": diagnose_marker_cells(hwpx_path),
        # PDF 에만 있고 HWPX 에 없는 본문 필드 표(통합신청서 필요 여부 = 사용자 확인 필요)
        "pdf_only_field_table": build_missing_field_table(pdf_path, hwpx_path, fv),
    }


def _print_human(r: dict) -> None:
    def section(title):
        print("\n" + "=" * 70 + "\n" + title + "\n" + "-" * 70)

    section("A. PDF 누름틀(AcroForm) 필드  (%d개)" % len(r["pdf_fields"]))
    print(", ".join(r["pdf_fields"]) or "(없음)")
    section("B. HWPX 누름틀(CLICK_HERE) 필드  (%d개)" % len(r["hwpx_fields"]))
    print(", ".join(r["hwpx_fields"]) or "(없음)")
    section("C. build_field_values 키  (%d개)" % len(r["field_value_keys"]))
    print(", ".join(r["field_value_keys"]))
    section("D. 역할 도장/서명 위젯")
    print("ROLE_WIDGETS      :", r["role_widgets"])
    print("ROLE_SIGN_WIDGETS :", r["role_sign_widgets"])
    print("PDF 에 존재하는 역할 위젯 :", r["pdf_role_widgets_present"])
    section("불일치 비교 (역할 위젯 제외)")
    print("PDF 에 있는데 HWPX 에 없음        :", r["pdf_missing_in_hwpx"])
    print("HWPX 에 있는데 PDF 에 없음        :", r["hwpx_missing_in_pdf"])
    print("HWPX 에 있는데 field_values 없음  :", r["hwpx_missing_in_field_values"], "(alias 적용 후)")
    print("field_values 에 있는데 HWPX 없음  :", r["field_values_unused_in_hwpx"])
    print("HWPX 중복 필드                    :", r["duplicate_hwpx_fields"])
    print("HWPX alias                        :", r["hwpx_field_aliases"])
    section("E. HWPX BinData 이미지 / 도장 셀(borderFill) 매핑")
    print("BinData 이미지 :", r["hwpx_bin_images"])
    for e in r["hwpx_image_borderfills"]:
        print("  image=%s  borderFill_id=%s  셀사용=%d" % (e["image"], e["border_fill_id"], e["cell_uses"]))
    section("F. 도장/서명 marker")
    print("템플릿 내 도장(seal) marker :", r["seal_markers_in_template"] or "(없음)")
    print("템플릿 내 서명(sign) marker :", r.get("sign_markers_in_template") or "(없음)")
    print("seal marker→역할 :", r["seal_marker_map"])
    print("sign marker→역할 :", r.get("sign_marker_map"))

    section("G. 핵심 불일치 진단 — 희망 ↔ hope (실측 포함)")
    d = r["alias_diagnosis_희망_hope"]
    print("PDF 필드명 '희망' 존재         :", d["pdf_field_name_present"])
    print("HWPX 필드명 '희망' 존재        :", d["hwpx_field_name_present"])
    print("field_values 키 '희망' 존재    :", d["field_values_has_희망"])
    print("field_values 키 'hope' 존재    :", d["field_values_has_hope"], " (샘플값=%r)" % d["hope_value_in_sample"])
    print("→ 실제 PDF 출력에서 '희망' 필드가 채워지는가 (실측):")
    for mode, info in d["pdf_희망_filled_actual"].items():
        if "error" in info:
            print("    [%s] 오류: %s" % (mode, info["error"]))
        else:
            print("    [%s] filled=%s  value=%r" % (mode, info["filled"], info["value"]))
    _alias = d["current_hwpx_alias"]
    print("HWPX alias 맵                  :", _alias,
          " (← 비어 있음)" if not _alias
          else " (← ★ 임시처리(미확정), inspect 에 노출됨 — 숨김 변환 아님)")
    print("권장안(승인 필요): build_field_values 의 hope 키 유지 +"
          " field_values[\"희망\"]=field_values.get(\"hope\",\"\") 추가 → PDF/HWPX 동일 적용")

    section("H. marker 셀 진단 (방식 B: 셀 배경 이미지 교체 준비)")
    mc = r["marker_cell_diagnosis"]
    print("%-11s %-5s %-12s %-10s %s" % ("marker", "종류", "역할", "borderFill", "배경이미지"))
    for c in mc["cells"]:
        print("%-11s %-5s %-12s %-10s %s"
              % (c["marker"], c["kind"], c["role"], c["border_fill_id"],
                 ("있음(%s)" % c["image_id"]) if c["has_bg_image"] else "없음 ✗"))
    if mc["shared_borderfills"]:
        print("\n⚠⚠ borderFill 공유 감지 — 같은 borderFill 을 여러 marker 가 공유하면 방식 B 로는")
        print("   역할별 다른 이미지 교체가 불가능합니다(전부 같은 이미지가 됨):")
        for bf, mks in mc["shared_borderfills"].items():
            print("     borderFill %s ← %s" % (bf, ", ".join(mks)))
    no_bg = [c for c in mc["cells"] if not c["has_bg_image"]]
    if no_bg:
        print("\n⚠ 방식 B 미충족: %d개 marker 셀에 placeholder 배경이미지가 없습니다." % len(no_bg))
        print("  → 한컴오피스에서 각 도장/서명 셀에 '서로 다른' placeholder 배경이미지를 넣어야")
        print("     셀마다 고유 borderFill+BinData 가 생겨 역할별 교체가 가능해집니다.")

    section("I. PDF 에만 있고 HWPX 에 없는 본문 필드 (임의 추가 금지)")
    print("%-12s %-9s %-7s %-8s %-13s %s" %
          ("필드명", "PDF존재", "HWPX존재", "fv존재", "통합신청서필요", "조치안"))
    for row in r["pdf_only_field_table"]:
        print("%-12s %-9s %-7s %-8s %-13s %s" %
              (row["field"], "O", "X", "O" if row["in_field_values"] else "X",
               row["needed_in_통합신청서"], row["조치안"]))


def main() -> None:
    ap = argparse.ArgumentParser(description="문서 자동작성 필드 진단(PDF/HWPX/field_values)")
    ap.add_argument("--pdf", default=os.path.join("templates", "통합신청서.pdf"))
    ap.add_argument("--hwpx", default=os.path.join("templates", "hwpx", "통합신청서.hwpx"))
    ap.add_argument("--json", default="", help="결과 JSON 저장 경로(선택)")
    args = ap.parse_args()

    pdf_path = args.pdf if os.path.isabs(args.pdf) else os.path.join(_ROOT, args.pdf)
    hwpx_path = args.hwpx if os.path.isabs(args.hwpx) else os.path.join(_ROOT, args.hwpx)

    if not os.path.exists(hwpx_path):
        print("[ERROR] HWPX 템플릿 없음:", hwpx_path)
        sys.exit(1)

    report = build_report(pdf_path, hwpx_path)
    _print_human(report)
    if args.json:
        out = args.json if os.path.isabs(args.json) else os.path.join(_ROOT, args.json)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print("\n[저장] JSON →", out)


if __name__ == "__main__":
    main()
