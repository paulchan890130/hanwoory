"""PDF overlay 렌더 스타일 + 텍스트 드로어 (Phase I-1J-5, bold 옵션 I-1J-6D).

render_mode="overlay" 전용. **Text 필드만** 대상이며 CheckBox/도장/서명은 호출측(quick_doc)에서
별도 처리한다. 전역 기본값(GLOBAL_STYLE) + 필드별 override(STYLE_OVERRIDE) 구조이고,
폰트는 PyMuPDF **내장** 'korea'/'china-s' 를 글자단위 폴백으로 사용한다(외부 폰트 파일/커밋 없음).
정식 배포 전 Noto Sans CJK KR 등 서버 설치 폰트 경로로 교체 검토(구조만 열어둠).

bold(I-1J-6D): overlay 자동입력 글자를 굵게 출력하는 옵션. **AcroForm 기본 방식엔 영향 없음.**
  · 글리프 커버리지(한글+한자)는 항상 내장 'korea'/'china-s' 가 보장한다(font_regular 개념).
  · bold=True 이고 시스템에 실제 bold 폰트(font_bold = bold_font_path/auto-discover)가 있고
    해당 글자 글리프를 가지면 **실제 bold 폰트**로 그린다.
  · 실제 bold 폰트가 없거나 글리프 미보유 → **faux-bold**(미세 x-offset 1회 재획, 0.25~0.35pt)로 폴백.
  · 운영(Render)엔 Windows 폰트가 없을 수 있으므로 경로 하드코딩 강제 없음 + repo 폰트 미커밋.
"""
from __future__ import annotations
import os

# 전역 기본 스타일.
GLOBAL_STYLE = {
    "font_size": 10.0,     # I-1J-6F: 9 → 10 (+1pt). 자동축소는 유지(박스 초과 시 줄어듦)
    "align": 1,            # I-1J-6F: 기본 가운데 맞춤(0=좌,1=중,2=우). PDF /Q(좌/우)보다 우선
    "pad": 1.5,
    "max_lines": 1,
    "min_font": 5.0,
    "keep_field": False,   # True 면 flatten 제외(AcroForm 위젯 유지) — 예외 편집 필드용(구조만 개방)
    # ── bold (overlay 자동입력 전용) ──
    "bold": True,          # 기본 굵게. field별 STYLE_OVERRIDE 로 끌 수 있음
    "bold_strength": 0.25, # faux-bold x-offset(pt). I-1J-6G: 0.3 → 0.25 (영문/숫자 겹침 여지 축소)
    "bold_font_path": None,  # None=시스템 자동 탐색(_BOLD_FONT_CANDIDATES) / 문자열=해당 경로 우선
    # I-1J-6I: 글자 사이 간격(pt). 0=기존. 한 줄(max_lines==1) 필드에만 적용(wrap 필드는 무시).
    # 영문/숫자처럼 좁은 칸에서 글자가 붙어 보이는 문제를 실제 자간으로 완화한다.
    "letter_spacing": 0.0,
}

# 주소 계열: I-1J-6F 부터 굵게(bold=True) + 가운데(글로벌 align 상속) + 줄바꿈(max_lines=2) 유지.
# font_size 는 전체 +1pt 기조에 맞춰 8 → 9. 긴 주소가 박스를 넘으면 자동축소가 우선이라 뭉개지지 않는다.
# bold_strength 는 글로벌(0.3) 그대로 사용해 주소가 과하게 두꺼워지지 않게 한다.
_ADDRESS_STYLE = {"font_size": 9.0, "max_lines": 2, "bold": True}

# 필드별 override. align 은 지정하지 않으면 글로벌(center)을 그대로 상속한다.
STYLE_OVERRIDE = {
    "adress":      dict(_ADDRESS_STYLE),   # 신청인 주소
    "address":     dict(_ADDRESS_STYLE),
    "hadress":     dict(_ADDRESS_STYLE),   # 숙소제공자 주소
    "badress":     dict(_ADDRESS_STYLE),   # 신원보증인 주소
    "gadress":     dict(_ADDRESS_STYLE),   # 법정대리인 주소
    "padress":     dict(_ADDRESS_STYLE),   # 합산자 주소
    "office_adr":  dict(_ADDRESS_STYLE),   # 사무소 주소
    # 성명(한글): 선명하게(bold 유지, 크기만 키움). 10 → 11 (+1pt)
    "koreanname":  {"font_size": 11.0, "bold": True},
}

# I-1J-6H: 영문/숫자 계열은 +1pt·center·bold 는 유지하되 faux-bold 강도를 크게 낮춰
# 글자끼리 붙어 보이는 문제를 완화한다(한글 이름·주소 bold 는 그대로 유지).
# I-1J-6J: 고정 letter_spacing 은 글자 폭 차이(I 좁고 M 넓음)를 보정 못해 간격이 들쭉날쭉했다.
# → 단일행 필드 전체 폭을 글자 수로 균등분할(distribute)해 각 글자를 cell 중앙에 배치한다.
# distribute=True 면 letter_spacing 은 무시된다(동시 적용 금지).
_LATIN_NAME_STYLE = {"bold": True, "bold_strength": 0.06, "max_lines": 1, "distribute": True}  # 영문 이름
_PASSPORT_STYLE   = {"bold": True, "bold_strength": 0.04, "max_lines": 1, "distribute": True}  # 여권번호
_NUMID_STYLE      = {"bold": True, "bold_strength": 0.12, "max_lines": 1, "distribute": True}  # 등록/주민번호

STYLE_OVERRIDE.update({
    # 영문 이름 계열(신청인/숙소/보증인/대리인/합산자)
    "Surname":       dict(_LATIN_NAME_STYLE),
    "Given names":   dict(_LATIN_NAME_STYLE),
    "hsurname":      dict(_LATIN_NAME_STYLE),
    "hgiven names":  dict(_LATIN_NAME_STYLE),
    "bsurname":      dict(_LATIN_NAME_STYLE),
    "bgiven names":  dict(_LATIN_NAME_STYLE),
    "gsurname":      dict(_LATIN_NAME_STYLE),
    "ggiven names":  dict(_LATIN_NAME_STYLE),
    "psurname":      dict(_LATIN_NAME_STYLE),
    "pgiven names":  dict(_LATIN_NAME_STYLE),
    # 여권번호 계열 (좁은 칸)
    "passport":      dict(_PASSPORT_STYLE),
    "opassport":     dict(_PASSPORT_STYLE),
    "hpassport":     dict(_PASSPORT_STYLE),
    "bpassport":     dict(_PASSPORT_STYLE),
    "gpassport":     dict(_PASSPORT_STYLE),
    "ppassport":     dict(_PASSPORT_STYLE),
    # 등록번호/외국인등록번호 계열(숫자) — agent_rrn 은 정상이라 미포함(글로벌 유지)
    "rnumber":       dict(_NUMID_STYLE),
    "fnumber":       dict(_NUMID_STYLE),
    "hrnumber":      dict(_NUMID_STYLE),
    "hfnumber":      dict(_NUMID_STYLE),
    "brnumber":      dict(_NUMID_STYLE),
    "bfnumber":      dict(_NUMID_STYLE),
})


def style_for(field_name: str, widget_align: int) -> dict:
    st = dict(GLOBAL_STYLE)
    st.update(STYLE_OVERRIDE.get(field_name, {}))
    if st.get("align") is None:
        st["align"] = widget_align
    return st


# ── 내장 CJK 폰트(글자단위 폴백, font_regular) ────────────────────────────────
_FONTS: dict = {}


def _font(name: str):
    import fitz
    if name not in _FONTS:
        _FONTS[name] = fitz.Font(name)
    return _FONTS[name]


def _pick(ch: str):
    # CJK 한자(㐀–鿿) → china-s, 그 외(한글/ASCII/기호) → korea
    return "china-s" if "㐀" <= ch <= "鿿" else "korea"


# ── 실제 bold 폰트(font_bold) — 시스템 설치 폰트만 탐색, repo 미커밋/하드코딩 강제 없음 ──
# env OVERLAY_BOLD_FONT 로 우선 지정 가능. 운영(Render)엔 없을 수 있음 → faux-bold 폴백.
_BOLD_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgunbd.ttf",                        # Malgun Gothic Bold (Windows 로컬)
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",   # Linux 설치 시
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]
_BOLD_FONT_NAME = "overlaybold"
_bold_cache: dict = {}   # path-or-None → (fitz.Font | None, path | None)


def _resolve_bold_font(explicit_path):
    """bold 폰트 1회 탐색(경로별 캐시). 사용 가능하면 (fitz.Font, path), 없으면 (None, None)."""
    key = explicit_path or "__auto__"
    if key not in _bold_cache:
        import fitz
        candidates = []
        if explicit_path:
            candidates.append(explicit_path)
        else:
            env = (os.environ.get("OVERLAY_BOLD_FONT") or "").strip()
            if env:
                candidates.append(env)
            candidates.extend(_BOLD_FONT_CANDIDATES)
        found = (None, None)
        for p in candidates:
            if p and os.path.exists(p):
                try:
                    found = (fitz.Font(fontfile=p), p)
                    break
                except Exception:
                    continue
        _bold_cache[key] = found
    return _bold_cache[key]


def _draw_font(ch: str, bold: bool, bf, bp):
    """그릴 폰트 결정 → (fitz.Font, fontname, fontfile|None, faux: bool).
    bold 이고 실제 bold 폰트가 해당 글자 글리프 보유 → 실제 bold(faux=False).
    그 외 → 내장 폰트(bold면 faux=True 로 미세 재획)."""
    if bold and bf is not None:
        try:
            if bf.has_glyph(ord(ch)):
                return bf, _BOLD_FONT_NAME, bp, False
        except Exception:
            pass
    name = _pick(ch)
    return _font(name), name, None, bold


def _w(text: str, size: float, bold: bool, bf, bp, spacing: float = 0.0) -> float:
    # 실제 그릴 폰트 기준으로 폭 측정 + 자간(글자수-1) → wrap/자동축소와 출력이 일치.
    base = sum(_draw_font(c, bold, bf, bp)[0].text_length(c, size) for c in text)
    if spacing and len(text) > 1:
        base += spacing * (len(text) - 1)
    return base


def _wrap(text: str, width: float, size: float, bold: bool, bf, bp, spacing: float = 0.0) -> list:
    lines, cur = [], ""
    for ch in text:
        if _w(cur + ch, size, bold, bf, bp, spacing) > width and cur:
            lines.append(cur); cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def _glyph_w(ch: str, size: float, bold: bool, bf, bp) -> float:
    return _draw_font(ch, bold, bf, bp)[0].text_length(ch, size)


def _draw_one(page, x: float, y: float, ch: str, size: float, bold: bool, bf, bp, strength: float) -> None:
    """글자 1개를 (x,y)에 그린다(실제 bold 폰트 우선, 아니면 내장+faux-bold)."""
    import fitz  # noqa: F401  (color 튜플만 사용)
    f, fname, ffile, faux = _draw_font(ch, bold, bf, bp)
    if ffile:
        page.insert_text((x, y), ch, fontname=fname, fontfile=ffile, fontsize=size, color=(0, 0, 0))
    else:
        page.insert_text((x, y), ch, fontname=fname, fontsize=size, color=(0, 0, 0))
        if faux and strength > 0:
            # faux-bold: 미세 x offset 1회만 재획(과한 다중 stroke 금지 → 번짐 최소화)
            page.insert_text((x + strength, y), ch, fontname=fname, fontsize=size, color=(0, 0, 0))


# 표준 글자 칸 폭(통합신청서 yyyy 칸 ≈ 53.7pt/4 ≈ 13.4pt 기준). 폰트 크기에 비례시켜 둔다.
# 필드가 넓어도 이 폭 이상으로는 벌리지 않고(과확산 방지), 글자 묶음은 가운데 배치한다.
# 필드가 좁으면(표준칸*글자수 > 가용폭) width/n 로 줄여 칸에 맞춘다.
_STD_CELL_EM = 1.35


def _try_distributed(page, rect, text, st, bold, strength, bf, bp, min_font) -> bool:
    """단일행 균등배치. **표준 칸 폭(yyyy 칸 기준)**으로 글자 간격을 통일하고 묶음을 가운데 둔다.
    - cell = min(표준칸, 가용폭/글자수) → 넓은 필드는 표준칸(과확산 방지), 좁은 필드는 자동 축소.
    - 각 글자는 자기 cell 중앙. 공백은 cell 1개 차지하되 그리지 않음. 글자수 1이면 미적용.
    성공 시 True, (좁아서 표준칸도 글자가 안 들어가면) 폰트축소→padding축소 후에도 안되면 False."""
    import fitz
    n = len(text)
    if n < 2:
        return False
    base_pad = st["pad"]
    glyphs = [c for c in text if not c.isspace()]
    for cur_pad in (base_pad, base_pad * 0.5, 0.0):
        r = fitz.Rect(rect.x0 + cur_pad, rect.y0 + cur_pad, rect.x1 - cur_pad, rect.y1 - cur_pad)
        size = float(st["font_size"])
        fit = False
        cw = 0.0
        while size >= min_font:
            cw = min(size * _STD_CELL_EM, r.width / n)   # 표준칸 우선, 좁으면 가용폭/n
            maxg = max((_glyph_w(c, size, bold, bf, bp) for c in glyphs), default=0.0)
            if maxg <= cw and size * 1.2 <= r.height + 0.5:
                fit = True
                break
            size -= 0.5
        if fit:
            block_w = cw * n
            start_x = r.x0 + (r.width - block_w) / 2     # 글자 묶음을 필드 가운데로
            y = r.y0 + (r.height - size * 1.2) / 2 + size * 0.85
            for i, ch in enumerate(text):
                if ch.isspace():
                    continue  # cell 은 차지하되 그리지 않음
                gw = _glyph_w(ch, size, bold, bf, bp)
                x = start_x + i * cw + (cw - gw) / 2      # 각 글자를 자기 cell 중앙에
                _draw_one(page, x, y, ch, size, bold, bf, bp, strength)
            return True
    return False  # 좁아서 표준칸도 안 들어감 → 호출측 center fallback


def draw_overlay_text(page, rect, text: str, st: dict) -> None:
    """rect 안에 text 를 그린다(글자단위 폰트 폴백 + 정렬 + 폭/줄수 자동 축소 + 선택적 bold).

    distribute=True(단일행) → 필드 전체 폭 균등분배(cell layout) 우선. letter_spacing 은 무시.
    실패(폭 부족) 시 기존 center+자동축소 경로로 fallback."""
    import fitz
    if not text:
        return
    bold = bool(st.get("bold", False))
    strength = float(st.get("bold_strength", 0.0) or 0.0)
    bf, bp = _resolve_bold_font(st.get("bold_font_path")) if bold else (None, None)
    pad = st["pad"]
    r = fitz.Rect(rect.x0 + pad, rect.y0 + pad, rect.x1 - pad, rect.y1 - pad)
    max_lines = max(1, int(st["max_lines"]))
    size = float(st["font_size"])
    min_font = float(st["min_font"])
    # 균등분배: 단일행 필드에서만. 성공하면 종료. (letter_spacing 보다 우선, 동시 적용 금지)
    if bool(st.get("distribute", False)) and max_lines == 1:
        if _try_distributed(page, rect, text, st, bold, strength, bf, bp, min_font):
            return
    # 자간(letter_spacing): 한 줄 필드에만 적용. wrap/multiline·distribute 는 0 으로 강제.
    spacing = float(st.get("letter_spacing", 0.0) or 0.0)
    if max_lines > 1 or st.get("distribute", False):
        spacing = 0.0
    # 1) 폭·줄수·높이에 맞게 폰트 자동 축소 (실제 그릴 폰트 폭 + 자간 기준)
    while size >= min_font:
        lines = _wrap(text, r.width, size, bold, bf, bp, spacing)
        if len(lines) <= max_lines and len(lines) * size * 1.2 <= r.height + 0.5:
            break
        size -= 0.5
    else:
        size = min_font
        lines = _wrap(text, r.width, size, bold, bf, bp, spacing)[:max_lines]
    # 2) 한 줄인데도 자간 때문에 폭 초과면 자간을 단계적으로 축소(최소 0). 칸 밖 튐 방지.
    if spacing > 0 and len(lines) == 1:
        while spacing > 0 and _w(lines[0], size, bold, bf, bp, spacing) > r.width:
            spacing = round(spacing - 0.1, 2)
            if spacing < 0:
                spacing = 0.0
    align = st["align"] or 0
    block_h = len(lines) * size * 1.2
    y = r.y0 + (r.height - block_h) / 2 + size * 0.85
    for ln in lines:
        lw = _w(ln, size, bold, bf, bp, spacing)
        if align == 2:
            x = r.x1 - lw
        elif align == 1:
            x = r.x0 + (r.width - lw) / 2
        else:
            x = r.x0
        for ch in ln:
            _draw_one(page, x, y, ch, size, bold, bf, bp, strength)
            x += _glyph_w(ch, size, bold, bf, bp) + spacing  # 자간 반영(마지막 글자 뒤 여백은 정렬 무영향)
        y += size * 1.2
