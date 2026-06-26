"""HWPX 문서 자동작성 (PoC) — 통합신청서.hwpx 누름틀(CLICK_HERE) 텍스트 자동입력 + 도장 marker 처리.

기존 PDF 자동작성(``backend/routers/quick_doc.py``)과 **완전 독립**이다. PDF 로직/필드명/템플릿
경로/``build_field_values`` 결과를 절대 건드리지 않으며, PDF 에서 만든 ``field_values`` dict 를
**그대로 재사용**해 동일 데이터로 HWPX 를 채운다.

처리 원칙
---------
- HWPX 는 ZIP 패키지 → ``zipfile`` 로 메모리에서 읽고 ``Contents/section*.xml`` 만 치환 후 재패키징.
- CLICK_HERE 누름틀은 다음 구조다(통합신청서.hwpx 확인):

      <hp:ctrl><hp:fieldBegin ... name="Surname" ...>...</hp:fieldBegin></hp:ctrl>
      <hp:t>Surname</hp:t>                      ← 이 placeholder 텍스트만 실제 값으로 교체
      <hp:ctrl><hp:fieldEnd beginIDRef="..."/></hp:ctrl>

  → ``fieldBegin name`` ~ ``fieldEnd`` 한 영역의 ``<hp:t>`` 내용만 바꾼다. run/charPrIDRef/
    paraPrIDRef/표 셀 속성은 절대 재생성·삭제하지 않는다(글자모양·문단모양·표 보존).
- 같은 ``name`` 이 여러 번 나오면(예: ``koreanname``, ``parents``) **전부 같은 값**으로 교체.
- ``field_values`` 에 없는 누름틀은 placeholder 를 빈칸으로 지우고(garbage 표시 방지) **진단 결과에
  남긴다**(조용히 무시하지 않음).
- XML escape 필수. 값이 ``None`` 이면 빈 문자열.

도장/서명(marker 기반)
----------------------
도장/서명은 누름틀 name 이 아니라 **표 셀 안 marker text**(``[[yin]]`` 등)로 식별한다. 원본 이미지
파일명/BinData 순서에 의존하지 않는다. 현재 ``통합신청서.hwpx`` 에는 marker 가 **없고** 3개의 샘플
도장 이미지가 셀 배경(borderFill)에 박혀 있다 → 마커 기반 자동삽입은 **no-op** 이며 진단에 보고한다
(템플릿 셀에 marker 를 추가하면 활성화). 셀 배경 이미지 교체 인프라(:func:`replace_seal_borderfill_image`)
는 마커가 추가되는 경우를 대비해 함께 제공한다.
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import zipfile
from typing import Optional


# ── HWPX 누름틀 ↔ field_values 별칭(alias) ───────────────────────────────────────
# 원칙: 원본 field_values 는 훼손하지 않고, HWPX 누름틀 name 이 field_values 키와 다를 때만 여기서
# 변환한다(숨김 변환 금지 — inspect 결과에 항상 노출).
#
# ★ 임시처리(미확정): "희망"(PDF·HWPX 누름틀명) ↔ "hope"(field_values 키) 불일치.
#   build_field_values() 는 "hope" 키만 만들고 "희망" 키는 없어, 실측상 기존 PDF 출력에서도 "희망"
#   위젯은 비어 있었다(잠재 버그). 현재는 HWPX 전용으로만 아래 alias 로 "희망"→"hope" 변환한다.
#   ※ 이는 **임시처리이며 확정 아님**. 권장 해결안(사용자 승인 필요):
#     build_field_values 의 hope 키는 유지하고, 출력 호환용으로
#     `field_values["희망"] = field_values.get("hope", "")` 를 추가해 PDF/HWPX 양쪽에 동일 적용.
HWPX_FIELD_ALIASES: dict = {
    "희망": "hope",
}


# ── 도장/서명 marker ↔ 역할 ──────────────────────────────────────────────────────
# 도장(印) = quick_doc.ROLE_WIDGETS 와 동일 체계(yin/hyin/byin/gyin/pyin/ayin).
SEAL_MARKER_TO_ROLE: dict = {
    "[[yin]]":  "applicant",     # 신청인
    "[[hyin]]": "accommodation", # 숙소제공자
    "[[byin]]": "guarantor",     # 신원보증인
    "[[gyin]]": "guardian",      # 법정대리인/부모
    "[[pyin]]": "aggregator",    # 소득합산자 (대리인이 [[pyin]] 을 쓰는 템플릿도 허용)
    "[[ayin]]": "agent",         # 행정사
}
# 서명(署名) = quick_doc.ROLE_SIGN_WIDGETS 와 동일 체계(ysign/hysign/bysign/gysign/pysign/aysign).
SIGN_MARKER_TO_ROLE: dict = {
    "[[ysign]]":  "applicant",
    "[[hysign]]": "accommodation",
    "[[bysign]]": "guarantor",
    "[[gysign]]": "guardian",
    "[[pysign]]": "aggregator",
    "[[aysign]]": "agent",
}
# 인식 대상 전체(도장 ∪ 서명). marker → (kind, role). kind ∈ "seal"/"sign".
ALL_MARKER_TO_ROLE: dict = {
    **{m: ("seal", r) for m, r in SEAL_MARKER_TO_ROLE.items()},
    **{m: ("sign", r) for m, r in SIGN_MARKER_TO_ROLE.items()},
}

_SECTION_RE = re.compile(r"^Contents/section\d+\.xml$")

# fieldBegin(name=...) ~ fieldEnd 한 영역. mid 는 둘 사이(placeholder <hp:t> 포함).
_FIELD_REGION_RE = re.compile(
    r'(?P<begin><hp:fieldBegin\b[^>]*?\bname="(?P<name>[^"]*)"[^>]*?>.*?</hp:fieldBegin>)'
    r'(?P<mid>.*?)'
    r'(?P<end><hp:fieldEnd\b[^>]*?/>)',
    re.S,
)
_HP_T_RE = re.compile(r"<hp:t>.*?</hp:t>", re.S)
_MARKER_RE = re.compile(r"\[\[[a-zA-Z]+\]\]")


# ── XML 유틸 ─────────────────────────────────────────────────────────────────────

def _xml_escape(value) -> str:
    if value is None:
        return ""
    s = str(value)
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _resolve_key(name: str) -> str:
    """HWPX 누름틀 name → field_values 키. alias 우선, 없으면 name 그대로."""
    return HWPX_FIELD_ALIASES.get(name, name)


# ── 필드 추출(진단용) ────────────────────────────────────────────────────────────

def _read_sections(z: zipfile.ZipFile) -> dict:
    """{entry_name: xml_text} — Contents/section*.xml 만."""
    out = {}
    for n in z.namelist():
        if _SECTION_RE.match(n):
            out[n] = z.read(n).decode("utf-8")
    return out


def _image_borderfill_map(z: zipfile.ZipFile) -> list:
    """header.xml 의 borderFill 중 ``<hc:img binaryItemIDRef="imageN">`` 을 쓰는 항목과
    section*.xml 에서 그 borderFill 을 참조하는 셀 수를 매핑(진단용)."""
    try:
        hdr = z.read("Contents/header.xml").decode("utf-8")
    except Exception:
        return []
    sections = "".join(_read_sections(z).values())
    out = []
    for block in re.findall(r"<hh:borderFill\b.*?</hh:borderFill>", hdr, re.S):
        idm = re.search(r'id="(\d+)"', block)
        imgm = re.search(r'binaryItemIDRef="(image\d+)"', block)
        if imgm:
            bid = idm.group(1) if idm else None
            uses = len(re.findall(r'borderFillIDRef="%s"' % re.escape(bid or ""), sections)) if bid else 0
            out.append({"image": imgm.group(1), "border_fill_id": bid, "cell_uses": uses})
    return out


def diagnose_seal_cells(template_path: str) -> list:
    """샘플 도장 이미지(borderFill)가 들어 있는 표 셀을 찾아 위치 + marker 존재 여부를 진단한다.

    개발자가 BinData 순서(image1→yin 등)로 역할을 **추정하지 않도록** 하기 위한 진단이다.
    각 이미지 borderFill 에 대해: 그 borderFill 을 참조하는 표 셀(hp:tc)이 어느 section XML 의
    어느 셀 주소에 있는지, 그 셀 안에 도장 marker([[yin]] 등)가 있는지 보고한다. marker 가 없으면
    역할을 확정할 수 없으므로 ``role_resolvable=False`` (자동 도장 교체 불가).

    반환: [{image, border_fill_id, cells:[{section, cell_addr, markers_in_cell}], role_resolvable}]
    """
    with zipfile.ZipFile(template_path) as z:
        img_bf = _image_borderfill_map(z)
        sections = _read_sections(z)

    out = []
    for entry in img_bf:
        bid = entry.get("border_fill_id")
        cells = []
        if bid:
            ref = 'borderFillIDRef="%s"' % bid
            for sname, xml in sections.items():
                for m in re.finditer(r"<hp:tc\b.*?</hp:tc>", xml, re.S):
                    block = m.group(0)
                    if ref not in block:
                        continue
                    col = re.search(r'colAddr="(\d+)"', block)
                    row = re.search(r'rowAddr="(\d+)"', block)
                    markers = [mk for mk in _MARKER_RE.findall(block) if mk in SEAL_MARKER_TO_ROLE]
                    cells.append({
                        "section": sname,
                        "cell_addr": ({"col": col.group(1), "row": row.group(1)}
                                      if (col and row) else None),
                        "markers_in_cell": markers,
                    })
        out.append({
            "image": entry.get("image"),
            "border_fill_id": bid,
            "cells": cells,
            "role_resolvable": any(c["markers_in_cell"] for c in cells),
        })
    return out


def diagnose_marker_cells(template_path: str) -> dict:
    """도장/서명 marker가 든 표 셀의 ``borderFillIDRef`` + 그 borderFill의 BinData 이미지 바인딩
    여부를 보고한다(방식 B '셀 배경 이미지 교체' 준비 진단). 역할 추정 없음 — marker 기준.

    방식 B 가 역할별로 동작하려면 각 marker 셀이 **서로 다른 borderFill** 을 가지고 그 borderFill 이
    **각자 BinData placeholder 이미지**를 참조해야 한다. 반환에 ``shared_borderfills`` 가 있으면
    여러 marker 가 한 borderFill 을 공유 → 같은 이미지로만 교체 가능(역할 구분 불가)하므로 경고 대상.

    반환: {"cells": [{marker, kind, role, section, border_fill_id, image_id, has_bg_image}],
           "shared_borderfills": {bf_id: [markers...]}}
    """
    with zipfile.ZipFile(template_path) as z:
        sections = _read_sections(z)
        try:
            header = z.read("Contents/header.xml").decode("utf-8")
        except Exception:
            header = ""
        bin_ids = {n.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                   for n in z.namelist() if n.startswith("BinData/")}
    bf_img: dict = {}
    for blk in re.findall(r"<hh:borderFill\b.*?</hh:borderFill>", header, re.S):
        idm = re.search(r'id="(\d+)"', blk)
        im = re.search(r'binaryItemIDRef="([^"]+)"', blk)
        if idm:
            bf_img[idm.group(1)] = im.group(1) if im else None

    cells: list = []
    for sname, xml in sections.items():
        for m in _MARKER_RE.finditer(xml):
            kr = ALL_MARKER_TO_ROLE.get(m.group(0))
            if not kr:
                continue
            tc_s = xml.rfind("<hp:tc", 0, m.start())
            tag = xml[tc_s:xml.find(">", tc_s) + 1] if tc_s >= 0 else ""
            bf = re.search(r'borderFillIDRef="(\d+)"', tag)
            bfid = bf.group(1) if bf else None
            img_id = bf_img.get(bfid)
            cells.append({
                "marker": m.group(0), "kind": kr[0], "role": kr[1], "section": sname,
                "border_fill_id": bfid, "image_id": img_id,
                "has_bg_image": bool(img_id and img_id in bin_ids),
            })
    bf_markers: dict = {}
    for c in cells:
        bf_markers.setdefault(c["border_fill_id"], set()).add(c["marker"])
    shared = {b: sorted(v) for b, v in bf_markers.items() if len(v) > 1}
    return {"cells": cells, "shared_borderfills": shared}


def extract_hwpx_fields(template_path: str) -> dict:
    """HWPX 누름틀 필드명·placeholder·중복·marker·BinData 이미지 추출(진단용).

    반환:
        {
          "fields":            [name, ...],          # 등장 순서, 중복 포함
          "unique_fields":     [name, ...],          # 중복 제거(첫 등장 순)
          "field_counts":      {name: count},
          "duplicate_fields":  {name: count>1},
          "placeholders":      {name: placeholder_text},  # 첫 등장 기준
          "seal_markers":      {marker: count},       # [[yin]] 등
          "bin_images":        [BinData 항목명, ...],
          "image_borderfills": [{image, border_fill_id, cell_uses}, ...],
        }
    """
    with zipfile.ZipFile(template_path) as z:
        sections = _read_sections(z)
        bin_images = [n for n in z.namelist()
                      if n.startswith("BinData/") and n.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif"))]
        image_bf = _image_borderfill_map(z)

    fields: list = []
    placeholders: dict = {}
    seal_counts: dict = {}
    sign_counts: dict = {}
    for xml in sections.values():
        for m in _FIELD_REGION_RE.finditer(xml):
            name = m.group("name")
            fields.append(name)
            if name not in placeholders:
                ts = _HP_T_RE.search(m.group("mid"))
                placeholders[name] = (
                    re.sub(r"<[^>]+>", "", ts.group(0)) if ts else ""
                )
        for mk in _MARKER_RE.findall(xml):
            if mk in SEAL_MARKER_TO_ROLE:
                seal_counts[mk] = seal_counts.get(mk, 0) + 1
            elif mk in SIGN_MARKER_TO_ROLE:
                sign_counts[mk] = sign_counts.get(mk, 0) + 1

    counts: dict = {}
    for n in fields:
        counts[n] = counts.get(n, 0) + 1
    unique = list(dict.fromkeys(fields))
    return {
        "fields": fields,
        "unique_fields": unique,
        "field_counts": counts,
        "duplicate_fields": {n: c for n, c in counts.items() if c > 1},
        "placeholders": placeholders,
        "seal_markers": seal_counts,
        "sign_markers": sign_counts,
        "bin_images": bin_images,
        "image_borderfills": image_bf,
    }


# ── 텍스트 누름틀 값 교체 ─────────────────────────────────────────────────────────

def _set_region_text(mid: str, value: str) -> tuple[str, bool]:
    """누름틀 영역(mid)의 첫 ``<hp:t>`` 내용을 value 로 교체(나머지 hp:t 는 비움).
    반환 (새 mid, 교체했는지). hp:t 가 없으면 (원본, False)."""
    state = {"set": False}

    def repl(_m):
        if not state["set"]:
            state["set"] = True
            return "<hp:t>%s</hp:t>" % _xml_escape(value)
        return "<hp:t></hp:t>"

    new_mid = _HP_T_RE.sub(repl, mid)
    return (new_mid, True) if state["set"] else (mid, False)


def replace_hwpx_click_here_fields(xml: str, field_values: dict,
                                   empty_placeholder: str = "") -> tuple[str, dict]:
    """section XML 의 CLICK_HERE 누름틀을 field_values 로 채운다.

    - ``fieldBegin name`` 기준으로만 찾는다(단순 문자열 치환 금지).
    - alias(:data:`HWPX_FIELD_ALIASES`) 적용.
    - field_values 에 키가 있으면 그 값으로, 없으면 placeholder 를 지우고 ``unfilled`` 에 기록.
    - ``empty_placeholder``: 값이 빈 문자열일 때 ``<hp:t>`` 에 넣을 내용. 기본 "".
      한컴 CLICK_HERE 는 hp:t 가 비면 안내문("이곳을 마우스로…")을 표시하므로, 공란으로 보이게
      하려면 " "(공백) 을 주면 안내문이 사라진다.
    반환 (새 xml, 보고 dict). 보고: {"filled": {name: key}, "unfilled": [name], "no_text_region": [name]}
    """
    report = {"filled": {}, "unfilled": [], "no_text_region": []}

    def repl(m: re.Match) -> str:
        name = m.group("name")
        key = _resolve_key(name)
        if key in field_values:
            value = field_values.get(key)
            value = "" if value is None else str(value)
            report["filled"][name] = key
        else:
            value = ""  # placeholder 제거(garbage 방지)
            if name not in report["unfilled"]:
                report["unfilled"].append(name)
        if value == "":
            value = empty_placeholder
        new_mid, changed = _set_region_text(m.group("mid"), value)
        if not changed and name not in report["no_text_region"]:
            report["no_text_region"].append(name)
        return m.group("begin") + new_mid + m.group("end")

    return _FIELD_REGION_RE.sub(repl, xml), report


# ── 도장/서명 marker 처리 ────────────────────────────────────────────────────────

def replace_hwpx_seal_markers(xml: str, seal_values: Optional[dict],
                              marker_replacement: str = "") -> tuple[str, dict]:
    """표 셀 안 도장/서명 marker text([[yin]]·[[ysign]] 등)를 찾아 **텍스트는 제거**하고,
    어느 종류(seal/sign)/역할과 연결되는지 진단 결과로 보고한다.

    PoC 단계: 실제 도장/서명 이미지 삽입은 **미구현**이다(현재 템플릿엔 셀 배경 이미지가 없어
    교체 대상도 없다). 따라서 인식된 marker 텍스트는 전부 제거하되(문서에 ``[[ysign]]`` 같은
    날 텍스트가 남지 않도록), 이미지 삽입은 별도 단계로 보고한다. seal/sign 두 종류 모두 처리한다.

    반환 (새 xml, 보고). 보고:
        {"markers_found": {marker: count},     # seal+sign 합산(하위호환)
         "seal_markers": {...}, "sign_markers": {...},
         "roles": [role], "removed": count}
    """
    found: dict = {}
    seal_found: dict = {}
    sign_found: dict = {}
    for mk in _MARKER_RE.findall(xml):
        kr = ALL_MARKER_TO_ROLE.get(mk)
        if not kr:
            continue
        found[mk] = found.get(mk, 0) + 1
        (seal_found if kr[0] == "seal" else sign_found)[mk] = \
            (seal_found if kr[0] == "seal" else sign_found).get(mk, 0) + 1

    removed = 0

    def repl(m: re.Match) -> str:
        nonlocal removed
        if m.group(0) in ALL_MARKER_TO_ROLE:
            removed += 1
            return marker_replacement  # marker 텍스트 치환(기본 "" 삭제 / " " 공백 등)
        return m.group(0)

    new_xml = _MARKER_RE.sub(repl, xml)
    roles = sorted({ALL_MARKER_TO_ROLE[mk][1] for mk in found})
    return new_xml, {"markers_found": found, "seal_markers": seal_found,
                     "sign_markers": sign_found, "roles": roles, "removed": removed}


def replace_seal_borderfill_image(zip_entries: dict, header_xml: str,
                                  border_fill_id: str, png_bytes: bytes) -> bool:
    """지정 borderFill 이 참조하는 BinData 이미지를 png_bytes 로 **교체**(in-place, zip_entries 수정).

    위치/크기 계산 없이 기존 셀 배경 이미지 바이트만 바꾼다(권장 방식). 성공 True.
    header.xml 에서 ``border_fill_id`` → ``binaryItemIDRef`` → BinData/<id>.<ext> 를 찾아 교체.
    구조 불일치/대상 없음 → False(호출측이 기존 이미지 유지)."""
    try:
        block_m = re.search(
            r'<hh:borderFill\b[^>]*\bid="%s".*?</hh:borderFill>' % re.escape(border_fill_id),
            header_xml, re.S)
        if not block_m:
            return False
        ref_m = re.search(r'binaryItemIDRef="([^"]+)"', block_m.group(0))
        if not ref_m:
            return False
        img_id = ref_m.group(1)
        for entry_name in list(zip_entries.keys()):
            base = entry_name.rsplit("/", 1)[-1]
            if entry_name.startswith("BinData/") and base.rsplit(".", 1)[0] == img_id:
                zip_entries[entry_name] = png_bytes
                return True
        return False
    except Exception:
        return False


# ── 새 hp:pic 도장/서명 삽입 (권장 방식 — 기존 이미지/hashkey 무변경) ─────────────────
# 기존 BinData 바이트/borderFill 을 건드리지 않고, **새 BinData + 새 hp:pic** 을 추가한다.
# rhwp 가 만든 정상 HWPX 분석 결과: 새로 추가한 이미지의 manifest opf:item 에는 hashkey 가 없어도
# 한컴이 정상 개방한다(무결성 변조 경고 회피). marker 텍스트는 **삭제/치환하지 않고 그대로 유지**하며,
# 같은 run 안 marker 의 <hp:t> 바로 뒤에 hp:pic 을 끼워넣는다(셀/누름틀/스타일 보존).

# 도장 기본 크기(HWPUNIT = 1/7200 inch). 3000 ≈ 10.6mm 정사각(도장에 적당, 셀 넘침 최소).
_PIC_DEFAULT_SIZE = 3000
# marker <hp:t> 매칭(여는 태그 속성 보존). 인식 marker 만 대상.
_MARKER_T_RE = re.compile(r"(<hp:t\b[^>]*>)(\[\[[a-zA-Z]+\]\])(</hp:t>)")


def _seal_pic_xml(ref_id: str, pic_id: int, inst_id: int, w: int, h: int,
                  treat_as_char: bool) -> str:
    """인라인/플로팅 hp:pic XML 생성(rhwp 정상 출력 구조 기반).

    treat_as_char=True  → 글자처럼(인라인). 줄높이가 그림에 맞춰 늘 수 있음.
    treat_as_char=False → 플로팅(텍스트 앞, 겹침 허용) → 레이아웃에 영향 없이 셀 위에 표시.
    """
    tac = "1" if treat_as_char else "0"
    text_wrap = "SQUARE" if treat_as_char else "IN_FRONT_OF_TEXT"
    overlap = "0" if treat_as_char else "1"
    return (
        f'<hp:pic id="{pic_id}" zOrder="{pic_id}" numberingType="PICTURE" textWrap="{text_wrap}" '
        f'textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" '
        f'instid="{inst_id}" reverse="0">'
        f'<hp:offset x="0" y="0"/><hp:orgSz width="0" height="0"/>'
        f'<hp:curSz width="{w}" height="{h}"/>'
        f'<hp:flip horizontal="0" vertical="0"/>'
        f'<hp:rotationInfo angle="0" centerX="0" centerY="0" rotateimage="0"/>'
        f'<hp:renderingInfo>'
        f'<hc:transMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        f'<hc:scaMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        f'<hc:rotMatrix e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"/>'
        f'</hp:renderingInfo>'
        f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{w}" y="0"/>'
        f'<hc:pt2 x="{w}" y="{h}"/><hc:pt3 x="0" y="{h}"/></hp:imgRect>'
        f'<hp:imgClip left="0" right="{w}" top="0" bottom="{h}"/>'
        f'<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
        f'<hp:imgDim dimwidth="{w}" dimheight="{h}"/>'
        f'<hc:img binaryItemIDRef="{ref_id}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
        f'<hp:effects></hp:effects>'
        f'<hp:sz width="{w}" widthRelTo="ABSOLUTE" height="{h}" heightRelTo="ABSOLUTE" protect="0"/>'
        f'<hp:pos treatAsChar="{tac}" affectLSpacing="0" flowWithText="1" allowOverlap="{overlap}" '
        f'holdAnchorAndSO="0" vertRelTo="PARA" horzRelTo="PARA" vertAlign="CENTER" horzAlign="CENTER" '
        f'vertOffset="0" horzOffset="0"/>'
        f'<hp:outMargin left="0" right="0" top="0" bottom="0"/>'
        f'</hp:pic>'
    )


def render_hwpx_with_pic_seals(template_path: str, field_values: dict,
                               marker_pngs: Optional[dict] = None,
                               treat_as_char: bool = True,
                               empty_placeholder: str = " ",
                               pic_size: int = _PIC_DEFAULT_SIZE) -> tuple[bytes, dict]:
    """권장 방식: 텍스트 누름틀 채움 + marker **유지** + marker 셀에 **새 hp:pic 도장/서명 삽입**.

    - 기존 BinData 바이트/hashkey/borderFill 미변경 → 한컴 무결성(변조) 회피.
    - marker(`[[yin]]` 등) 텍스트는 그대로 두고(위치 탐색용), 같은 run 의 <hp:t> 뒤에 hp:pic 추가.
    - ``marker_pngs``: {marker_text: png_bytes}. 같은 내용 png 는 BinData 1개로 합치고 여러 hp:pic 이 참조.
    - 빈 누름틀은 ``empty_placeholder``(기본 공백)로 안내문 억제.
    반환 (hwpx_bytes, report).
    """
    marker_pngs = marker_pngs or {}
    report: dict = {"text": {"filled": {}, "unfilled": []},
                    "pics": {"inserted": 0, "by_marker": {}, "new_bindata": [], "mode":
                             ("inline" if treat_as_char else "float")},
                    "warnings": []}

    entries: dict = {}
    infos: list = []
    section_names: list = []
    img_compress = zipfile.ZIP_STORED
    with zipfile.ZipFile(template_path) as z:
        for info in z.infolist():
            entries[info.filename] = z.read(info.filename)
            infos.append(info)
            if _SECTION_RE.match(info.filename):
                section_names.append(info.filename)
            if info.filename.startswith("BinData/"):
                img_compress = info.compress_type

    hpf_name = "Contents/content.hpf"
    hpf = entries.get(hpf_name, b"").decode("utf-8")

    # 1) 새 BinData + manifest 준비 — 같은 png 내용은 1개로 dedupe
    existing_nums = [int(n) for n in re.findall(r'href="BinData/image(\d+)\.\w+"', hpf)]
    next_n = (max(existing_nums) + 1) if existing_nums else 1
    digest_to_ref: dict = {}
    marker_to_ref: dict = {}
    manifest_items: list = []
    new_files: dict = {}
    for mk, png in marker_pngs.items():
        if mk not in ALL_MARKER_TO_ROLE or not png:
            continue
        dg = hashlib.md5(png).hexdigest()
        if dg not in digest_to_ref:
            ref = f"image{next_n}"; next_n += 1
            fn = f"BinData/{ref}.png"
            digest_to_ref[dg] = ref
            new_files[fn] = png
            # 새 이미지 opf:item — **hashkey 없음**(rhwp 정상 출력과 동일 → 무결성 회피)
            manifest_items.append(
                f'<opf:item id="{ref}" href="{fn}" media-type="image/png" isEmbeded="1"/>')
        marker_to_ref[mk] = digest_to_ref[dg]

    if manifest_items and "</opf:manifest>" in hpf:
        hpf = hpf.replace("</opf:manifest>", "".join(manifest_items) + "</opf:manifest>")
        entries[hpf_name] = hpf.encode("utf-8")

    # 2) 섹션별: 텍스트 누름틀 채움(마커 유지) + 마커 <hp:t> 뒤 hp:pic 삽입
    pic_id = 2100000000
    inst_id = 100001
    for sname in section_names:
        xml = entries[sname].decode("utf-8")
        xml, trep = replace_hwpx_click_here_fields(xml, field_values,
                                                   empty_placeholder=empty_placeholder)
        report["text"]["filled"].update(trep["filled"])
        for n in trep["unfilled"]:
            if n not in report["text"]["unfilled"]:
                report["text"]["unfilled"].append(n)

        def repl(m: re.Match) -> str:
            nonlocal pic_id, inst_id
            marker = m.group(2)
            ref = marker_to_ref.get(marker)
            if not ref:
                return m.group(0)  # png 없는 마커는 그대로(삽입 안 함)
            pic = _seal_pic_xml(ref, pic_id, inst_id, pic_size, pic_size, treat_as_char)
            pic_id += 1; inst_id += 1
            report["pics"]["inserted"] += 1
            report["pics"]["by_marker"][marker] = report["pics"]["by_marker"].get(marker, 0) + 1
            return m.group(0) + pic   # marker <hp:t> 유지 + 같은 run 안에 hp:pic 추가

        xml = _MARKER_T_RE.sub(repl, xml)
        entries[sname] = xml.encode("utf-8")

    # 3) 새 BinData 엔트리 추가(원본 이미지와 동일 압축방식, 끝에 append — OCF 순서 무관)
    for fn, png in new_files.items():
        zi = zipfile.ZipInfo(fn)
        zi.compress_type = img_compress
        infos.append(zi)
        entries[fn] = png
        report["pics"]["new_bindata"].append(fn)

    if marker_pngs and not marker_to_ref:
        report["warnings"].append("marker_pngs 가 인식 가능한 marker 와 매칭되지 않아 도장을 넣지 않았습니다.")

    out_bytes = package_hwpx(infos, entries)
    return out_bytes, report


# ── 방식 C: 기존 borderFill 그림 참조(binaryItemIDRef) 교체 ──────────────────────────
# 한컴이 **이미 화면에 렌더링하는** 그림 객체(현 템플릿은 셀 배경 borderFill imgBrush)를 그대로
# 두고, 그 ``binaryItemIDRef`` 만 **새 BinData(해시키 없음)** 로 바꾼다.
#  - 기존 BinData 바이트/hashkey 무변경(방식 B 의 변조 원인 회피).
#  - 새 hp:pic 생성 안 함(방식 A 는 한컴이 렌더 실패).
#  - marker 삭제/공백치환 안 함(텍스트만 누름틀 채움 + 빈칸 공백).
# diagnose_marker_cells 가 각 marker 셀의 borderFill→현재 image 를 알려주므로, role+kind 별 새 도장을
# 그 borderFill 에 연결한다. borderFill 이 여러 marker 에 공유되면(역할 충돌) 건너뛰고 보고한다.

def _repoint_borderfill_image(header_xml: str, border_fill_id: str, new_ref: str) -> tuple[str, bool]:
    """header.xml 의 특정 borderFill 블록 안 ``binaryItemIDRef`` 만 new_ref 로 교체(블록 한정)."""
    m = re.search(r'<hh:borderFill\b[^>]*\bid="%s".*?</hh:borderFill>' % re.escape(border_fill_id),
                  header_xml, re.S)
    if not m:
        return header_xml, False
    block = m.group(0)
    if "binaryItemIDRef=" not in block:
        return header_xml, False
    newblock = re.sub(r'(binaryItemIDRef=")[^"]*(")', r"\g<1>%s\g<2>" % new_ref, block, count=1)
    return header_xml[:m.start()] + newblock + header_xml[m.end():], True


def render_hwpx_reference_swap(template_path: str, field_values: dict,
                               marker_pngs: Optional[dict] = None,
                               empty_placeholder: str = " ") -> tuple[bytes, dict]:
    """방식 C: 텍스트 누름틀 채움 + marker 유지 + **기존 borderFill 그림 참조를 새 BinData 로 교체**.

    ``marker_pngs``: {marker_text: png_bytes}. 같은 png 내용은 BinData 1개로 합치고 여러 borderFill 이 참조.
    반환 (hwpx_bytes, report). report.swap: 교체/건너뜀 내역, report.conflicts: 공유 borderFill 경고.
    """
    marker_pngs = marker_pngs or {}
    report: dict = {"text": {"filled": {}, "unfilled": []},
                    "swap": {"repointed": [], "new_bindata": [], "skipped": []},
                    "conflicts": [], "warnings": []}

    diag = diagnose_marker_cells(template_path)
    # borderFill → 그 셀의 marker 집합(공유 검출). 같은 bf 에 서로 다른 marker 면 충돌.
    bf_markers: dict = {}
    for c in diag["cells"]:
        bf_markers.setdefault(c["border_fill_id"], set()).add(c["marker"])

    entries: dict = {}
    infos: list = []
    section_names: list = []
    img_compress = zipfile.ZIP_STORED
    with zipfile.ZipFile(template_path) as z:
        for info in z.infolist():
            entries[info.filename] = z.read(info.filename)
            infos.append(info)
            if _SECTION_RE.match(info.filename):
                section_names.append(info.filename)
            if info.filename.startswith("BinData/"):
                img_compress = info.compress_type

    hpf_name = "Contents/content.hpf"
    hdr_name = "Contents/header.xml"
    hpf = entries.get(hpf_name, b"").decode("utf-8")
    header = entries.get(hdr_name, b"").decode("utf-8")

    # 1) 새 BinData + manifest(해시키 없음) — png 내용별 1개
    existing_nums = [int(n) for n in re.findall(r'href="BinData/image(\d+)\.\w+"', hpf)]
    next_n = (max(existing_nums) + 1) if existing_nums else 1
    digest_to_ref: dict = {}
    manifest_items: list = []
    new_files: dict = {}

    def ref_for(png: bytes) -> str:
        nonlocal next_n
        dg = hashlib.md5(png).hexdigest()
        if dg not in digest_to_ref:
            ref = f"image{next_n}"; next_n += 1
            fn = f"BinData/{ref}.png"
            digest_to_ref[dg] = ref
            new_files[fn] = png
            manifest_items.append(
                f'<opf:item id="{ref}" href="{fn}" media-type="image/png" isEmbeded="1"/>')
        return digest_to_ref[dg]

    # 2) borderFill 별 repoint (역할 충돌 검사)
    for c in diag["cells"]:
        bfid = c["border_fill_id"]; marker = c["marker"]
        if len(bf_markers.get(bfid, set())) > 1:
            msg = f"borderFill {bfid} 가 여러 marker({sorted(bf_markers[bfid])})에 공유 → 역할 확정 불가, 건너뜀"
            if msg not in report["conflicts"]:
                report["conflicts"].append(msg)
            continue
        if not c["has_bg_image"]:
            report["swap"]["skipped"].append({"marker": marker, "bf": bfid, "이유": "셀 배경 이미지 없음"})
            continue
        png = marker_pngs.get(marker)
        if not png:
            report["swap"]["skipped"].append({"marker": marker, "bf": bfid, "이유": "png 미제공"})
            continue
        new_ref = ref_for(png)
        header, ok = _repoint_borderfill_image(header, bfid, new_ref)
        if ok:
            report["swap"]["repointed"].append({"marker": marker, "bf": bfid,
                                                "old": c["image_id"], "new": new_ref})
        else:
            report["swap"]["skipped"].append({"marker": marker, "bf": bfid, "이유": "borderFill repoint 실패"})

    if manifest_items and "</opf:manifest>" in hpf:
        hpf = hpf.replace("</opf:manifest>", "".join(manifest_items) + "</opf:manifest>")
        entries[hpf_name] = hpf.encode("utf-8")
    entries[hdr_name] = header.encode("utf-8")

    # 3) 텍스트 누름틀 채움(마커 유지, 빈칸 공백)
    for sname in section_names:
        xml = entries[sname].decode("utf-8")
        xml, trep = replace_hwpx_click_here_fields(xml, field_values,
                                                   empty_placeholder=empty_placeholder)
        entries[sname] = xml.encode("utf-8")
        report["text"]["filled"].update(trep["filled"])
        for n in trep["unfilled"]:
            if n not in report["text"]["unfilled"]:
                report["text"]["unfilled"].append(n)

    # 4) 새 BinData 엔트리 추가
    for fn, png in new_files.items():
        zi = zipfile.ZipInfo(fn); zi.compress_type = img_compress
        infos.append(zi); entries[fn] = png
        report["swap"]["new_bindata"].append(fn)

    out_bytes = package_hwpx(infos, entries)
    return out_bytes, report


# ── 패키징 ───────────────────────────────────────────────────────────────────────

def package_hwpx(infos: list, entries: dict) -> bytes:
    """원본 ZipInfo 객체를 **그대로 재사용**해 HWPX(zip) bytes 를 만든다.

    한컴이 거부하지 않도록 원본의 entry 순서·압축방식·date_time·flag_bits·external_attr 를 모두
    보존한다(mimetype 무압축 선두 유지). CRC/크기만 새 데이터로 재계산된다. ZipInfo 를 새로 만들면
    이런 메타데이터가 유실돼 일부 뷰어가 파일을 거부할 수 있어, 반드시 원본 info 를 재사용한다."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zout:
        for info in infos:
            data = entries.get(info.filename)
            if data is None:
                continue
            zout.writestr(info, data)   # 원본 ZipInfo(압축/메타) 그대로 사용
    return buf.getvalue()


def _update_hpf_hashkey(hpf_xml: str, image_id: str, png_bytes: bytes) -> str:
    """content.hpf 의 해당 이미지 opf:item ``hashkey`` 를 새 바이트 기준 base64(md5) 로 갱신.

    한컴은 임베드 바이너리에 hashkey(무결성/중복판정 키)를 둔다. 바이트만 바꾸고 hashkey 를
    그대로 두면 열기 오류가 날 수 있으므로 동기화한다. 패턴 불일치 시 원본 그대로 반환(무해)."""
    new_key = base64.b64encode(hashlib.md5(png_bytes).digest()).decode()
    pat = re.compile(r'(<opf:item\b[^>]*\bid="%s"[^>]*\bhashkey=")[^"]*(")' % re.escape(image_id))
    return pat.sub(lambda m: m.group(1) + new_key + m.group(2), hpf_xml)


def fill_hwpx_template(template_path: str, field_values: dict,
                       seal_values: Optional[dict] = None,
                       image_overrides: Optional[dict] = None) -> tuple[bytes, dict]:
    """통합신청서.hwpx 등 HWPX 템플릿을 field_values 로 채워 새 HWPX bytes 를 만든다.

    - 텍스트: CLICK_HERE 누름틀 name 기준 교체(:func:`replace_hwpx_click_here_fields`).
    - 도장/서명: marker text 제거 + (가능 시) 셀 배경 이미지 교체. 현재 통합신청서.hwpx 는
      marker 가 없으므로 도장 자동삽입은 미적용(보고서에 명시).
    반환 (hwpx_bytes, report).
    """
    report: dict = {"text": {"filled": {}, "unfilled": [], "no_text_region": []},
                    "seal": {"markers_found": {}, "seal_markers": {}, "sign_markers": {},
                             "roles": [], "removed": 0, "images_replaced": []},
                    "warnings": []}

    entries: dict = {}
    infos: list = []           # 원본 ZipInfo 순서/메타 보존용
    header_xml = ""
    section_names: list = []
    bindata_by_id: dict = {}   # image id(확장자 제외) → zip entry 이름
    hpf_name = "Contents/content.hpf"
    with zipfile.ZipFile(template_path) as z:
        for info in z.infolist():
            data = z.read(info.filename)
            entries[info.filename] = data
            infos.append(info)
            if info.filename == "Contents/header.xml":
                header_xml = data.decode("utf-8")
            if _SECTION_RE.match(info.filename):
                section_names.append(info.filename)
            if info.filename.startswith("BinData/"):
                bindata_by_id[info.filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]] = info.filename

    # 0) 기존 BinData 이미지 바이트 교체(방식 B 핵심 — 구조 변경 없이 셀 배경 이미지 바이트만 swap).
    #    image_overrides: {image_id(확장자 제외): png_bytes}. 존재하는 BinData 만 교체하고,
    #    content.hpf 의 hashkey 도 새 바이트 기준으로 동기화(미동기화 시 한컴 열기 오류 가능).
    if image_overrides:
        hpf_xml = entries.get(hpf_name, b"").decode("utf-8") if hpf_name in entries else ""
        for img_id, png in image_overrides.items():
            entry = bindata_by_id.get(img_id)
            if entry and png:
                entries[entry] = png
                if hpf_xml:
                    hpf_xml = _update_hpf_hashkey(hpf_xml, img_id, png)
                report["seal"]["images_replaced"].append(img_id)
            else:
                report["warnings"].append("image_overrides: BinData '%s' 없음 → 교체 생략" % img_id)
        if hpf_xml and hpf_name in entries:
            entries[hpf_name] = hpf_xml.encode("utf-8")

    # 1) 텍스트 누름틀 + marker 처리 (section*.xml)
    for sname in section_names:
        xml = entries[sname].decode("utf-8")
        xml, trep = replace_hwpx_click_here_fields(xml, field_values)
        xml, srep = replace_hwpx_seal_markers(xml, seal_values)
        entries[sname] = xml.encode("utf-8")
        # 보고 병합
        report["text"]["filled"].update(trep["filled"])
        for n in trep["unfilled"]:
            if n not in report["text"]["unfilled"]:
                report["text"]["unfilled"].append(n)
        for n in trep["no_text_region"]:
            if n not in report["text"]["no_text_region"]:
                report["text"]["no_text_region"].append(n)
        for mk, c in srep["markers_found"].items():
            report["seal"]["markers_found"][mk] = report["seal"]["markers_found"].get(mk, 0) + c
        for mk, c in srep["seal_markers"].items():
            report["seal"]["seal_markers"][mk] = report["seal"]["seal_markers"].get(mk, 0) + c
        for mk, c in srep["sign_markers"].items():
            report["seal"]["sign_markers"][mk] = report["seal"]["sign_markers"].get(mk, 0) + c
        report["seal"]["removed"] += srep["removed"]
        for r in srep["roles"]:
            if r not in report["seal"]["roles"]:
                report["seal"]["roles"].append(r)

    # 2) 도장/서명 이미지 삽입 — **아직 미구현**.
    #    현재 통합신청서.hwpx 는 도장/서명 셀에 배경 이미지가 없고 marker text 만 있다. 따라서
    #    인식된 marker 는 위에서 전부 제거(문서에 [[ysign]] 같은 날 텍스트 잔존 방지)했지만, 실제
    #    도장/서명 PNG 를 셀에 삽입하는 단계는 아직 구현되지 않았다(인라인 이미지 주입 또는
    #    셀 배경 이미지 교체 방식 중 택1 필요 — Hancom 열기 검증 동반). 명확히 보고한다.
    if report["seal"]["markers_found"]:
        kinds = []
        if report["seal"]["seal_markers"]:
            kinds.append("도장 %d개" % sum(report["seal"]["seal_markers"].values()))
        if report["seal"]["sign_markers"]:
            kinds.append("서명 %d개" % sum(report["seal"]["sign_markers"].values()))
        report["warnings"].append(
            "marker(%s)를 인식해 텍스트는 제거했으나, 실제 도장/서명 이미지 삽입은 아직 "
            "미구현입니다(해당 위치는 현재 공란). 이미지 삽입 방식 확정 후 구현 예정."
            % ", ".join(kinds)
        )
        if seal_values:
            report["warnings"].append(
                "seal_values 가 전달되었으나 이미지 삽입 미구현으로 반영하지 않았습니다."
            )

    out_bytes = package_hwpx(infos, entries)
    return out_bytes, report
