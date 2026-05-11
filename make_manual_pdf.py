# -*- coding: utf-8 -*-
"""한우리 출입국업무관리 사용자 매뉴얼 — PDF 생성 (ReportLab)"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, PageBreak, Table, TableStyle
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import datetime, os

# ─── 한글 폰트 등록 ───────────────────────────────────────────
def _reg(name, path):
    if os.path.exists(path):
        pdfmetrics.registerFont(TTFont(name, path))
        return True
    return False

FONT = "Malgun"
FONT_B = "MalgunB"
candidates = [
    ("C:/Windows/Fonts/malgun.ttf", "C:/Windows/Fonts/malgunbd.ttf"),
    ("C:/Windows/Fonts/gulim.ttc",  "C:/Windows/Fonts/gulim.ttc"),
]
font_ok = False
for reg, regb in candidates:
    if _reg(FONT, reg) and _reg(FONT_B, regb):
        font_ok = True
        break
if not font_ok:
    FONT = FONT_B = "Helvetica"

# ─── 스타일 ──────────────────────────────────────────────────
W, H = A4
ML = MR = 2.0 * cm
MT = MB = 1.8 * cm

def S(name, parent="Normal", font=FONT, size=10, leading=None, color=colors.black,
      bold=False, spaceBefore=4, spaceAfter=4, leftIndent=0):
    return ParagraphStyle(
        name=name, fontName=FONT_B if bold else font,
        fontSize=size, leading=leading or (size * 1.4),
        textColor=color, spaceBefore=spaceBefore, spaceAfter=spaceAfter,
        leftIndent=leftIndent,
    )

sH1    = S("H1",   size=16, bold=True,  color=colors.HexColor("#21548F"), spaceBefore=18, spaceAfter=8)
sH2    = S("H2",   size=12, bold=True,  color=colors.HexColor("#287028"), spaceBefore=10, spaceAfter=4, leftIndent=10)
sH3    = S("H3",   size=11, bold=True,  color=colors.HexColor("#3C3C64"), spaceBefore=8,  spaceAfter=3, leftIndent=18)
sBody  = S("Body", size=10, leftIndent=12, spaceAfter=3)
sBull  = S("Bull", size=10, leftIndent=24, spaceAfter=2)
sStep  = S("Step", size=10, leftIndent=28, spaceAfter=2)
sTip   = S("Tip",  size=9,  color=colors.HexColor("#6B4700"), leftIndent=20, spaceAfter=3)
sWarn  = S("Warn", size=9,  color=colors.HexColor("#AA3200"), leftIndent=20, spaceAfter=3)
sTitle = S("Title",size=24, bold=True,  color=colors.HexColor("#21548F"), spaceBefore=0, spaceAfter=8)
sSub   = S("Sub",  size=14, color=colors.HexColor("#505050"), spaceBefore=0, spaceAfter=6)
sMeta  = S("Meta", size=10, color=colors.HexColor("#888888"), spaceBefore=0, spaceAfter=4)
sToc   = S("Toc",  size=10, color=colors.HexColor("#333366"), spaceAfter=2)

def div():
    return HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CCCCCC"),
                      spaceBefore=8, spaceAfter=8)

def h1(t):  return Paragraph(t, sH1)
def h2(t):  return Paragraph(t, sH2)
def h3(t):  return Paragraph(t, sH3)
def body(t, indent=12): return Paragraph(t, S("b_"+t[:8], size=10, leftIndent=indent, spaceAfter=3))
def bull(t, indent=24): return Paragraph(f"&bull;&nbsp;&nbsp;{t}", sBull)
def step(n, t):         return Paragraph(f"<b>[{n}]</b>&nbsp;&nbsp;{t}", sStep)
def tip(t):             return Paragraph(f"<i>&nbsp;TIP &nbsp;|&nbsp; {t}</i>", sTip)
def warn(t):            return Paragraph(f"<i>&nbsp;주의 &nbsp;|&nbsp; {t}</i>", sWarn)
def sp(h=6):            return Spacer(1, h)

elems = []

# ─── 표지 ────────────────────────────────────────────────────
elems += [sp(120)]
elems.append(Paragraph("한우리 출입국업무관리 시스템", sTitle))
elems.append(Paragraph("사 &nbsp;용 &nbsp;자 &nbsp;&nbsp;매 &nbsp;뉴 &nbsp;얼", sSub))
elems += [sp(30)]
elems.append(Paragraph(f"작성일: {datetime.date.today().strftime('%Y년 %m월 %d일')}", sMeta))
elems.append(Paragraph("hanwory.com &nbsp;|&nbsp; 내부 사용 전용", sMeta))
elems.append(PageBreak())

# ─── 목차 ────────────────────────────────────────────────────
elems.append(Paragraph("목 &nbsp;&nbsp; 차", sH1))
toc_data = [
    ("1", "로그인 및 기본 화면"),
    ("2", "홈 대시보드"),
    ("3", "고객관리"),
    ("4", "    고객카드 버튼 가이드"),
    ("5", "         문서자동작성 (노란 버튼)"),
    ("6", "         숙소제공자 (Home 아이콘)"),
    ("7", "         원클릭 작성 (번개 아이콘 ⚡)"),
    ("8", "         체류만료조회 (지구본 아이콘 🌐)"),
    ("9", "         하이코리아 ID찾기 (ID 버튼)"),
    ("10", "업무관리"),
    ("11", "일일결산"),
    ("12", "월간결산"),
    ("13", "문서자동작성 (전체 기능)"),
    ("14", "OCR 스캔"),
    ("15", "업무참고 · 실무지침"),
    ("16", "통합검색 · 메모 · 게시판"),
    ("17", "마이페이지 (행정사 서명 등록)"),
    ("18", "공통 사용 팁"),
]
for num, label in toc_data:
    indent = (len(label) - len(label.lstrip())) * 4
    elems.append(Paragraph(f"<b>{num}.</b>&nbsp;&nbsp;{label.strip()}",
                            S("tc"+num, size=10, leftIndent=8+indent, spaceAfter=2,
                              color=colors.HexColor("#333388") if indent==0 else colors.HexColor("#555555"))))
elems.append(PageBreak())

# ─────────────────────────────────────────────────────────────
# 1. 로그인
# ─────────────────────────────────────────────────────────────
elems += [h1("1.  로그인 및 기본 화면"),
          body("접속 주소:  https://www.hanwory.com"),
          h2("로그인"),
          bull("아이디와 비밀번호를 입력합니다."),
          bull("왼쪽 사이드바에서 각 메뉴로 이동합니다."),
          bull("사이드바 하단 [접기] 버튼으로 사이드바를 좁힐 수 있습니다."),
          tip("사이드바가 접힌 상태에서 아이콘에 마우스를 올리면 메뉴명이 표시됩니다."),
          h2("사이드바 메뉴 구성"),
]
menus = [
    ("🏠 홈 대시보드", "Home", "업무 현황·만기 알림 종합"),
    ("👥 고객관리", "Users", "고객 정보 검색·편집"),
    ("📋 업무관리", "Clipboard", "진행·예정·완료 업무"),
    ("💰 일일결산", "DollarSign", "수입·지출 입력"),
    ("📊 월간결산", "BarChart2", "월별 수익 분석"),
    ("✏️ 문서자동작성", "FileEdit", "서류 자동 생성"),
    ("🔍 OCR 스캔", "ScanLine", "여권·등록증 자동 인식"),
    ("📖 업무참고", "BookOpen", "참고 자료 조회·편집"),
    ("📚 실무지침", "Library", "법령·지침 자료"),
    ("🔎 통합검색", "Search", "전체 데이터 검색"),
    ("📝 메모", "FileText", "장기·중기 메모"),
    ("💬 게시판", "MessageSquare", "공지·업무 공유"),
    ("👤 마이페이지", "User", "서명·사무소 정보"),
]
for name, icon, desc in menus:
    elems.append(bull(f"{name}  ({icon} 아이콘)  —  {desc}"))

elems += [div(),

# ─────────────────────────────────────────────────────────────
# 2. 대시보드
# ─────────────────────────────────────────────────────────────
h1("2.  홈 대시보드   (Home 아이콘)"),
body("로그인 후 가장 먼저 보이는 종합 현황 화면입니다."),
h2("주요 위젯"),
bull("진행 업무 요약 — 접수·처리·보관 중인 업무 건수"),
bull("예정 업무 — 오늘·이번 주 예정된 업무 목록"),
bull("등록증·여권 만기 알림 — 30일 이내 만기 고객 자동 표시"),
bull("이번 달 일정 — 달력 형식 일정 확인"),
bull("단기 메모 — 빠른 메모 작성 및 확인"),
tip("만기 알림 항목을 클릭하면 해당 고객의 고객카드로 바로 이동합니다."),
div(),

# ─────────────────────────────────────────────────────────────
# 3. 고객관리
# ─────────────────────────────────────────────────────────────
h1("3.  고객관리   (Users 아이콘)"),
body("모든 고객의 정보를 검색하고 관리하는 핵심 화면입니다."),
h2("고객 목록"),
bull("검색창: 이름·여권번호·국적으로 검색 (2자 이상 입력 시 자동 검색)"),
bull("테이블: 한글이름, 국적, 영문성명, 연락처, 체류자격, 등록번호, 여권번호, 주소"),
bull("만기 30일 이내 → 빨간색 / 120일 이내 → 주황색으로 표시"),
bull("[+ 신규 고객] 버튼으로 새 고객 등록"),
bull("행 클릭 → 오른쪽에 고객카드(Drawer)가 열림"),
h2("고객카드 편집"),
bull("기본정보, 연락처, 등록증, 여권, 업무정보(비고·폴더) 항목 편집"),
bull("하단 [저장] 버튼으로 Google Sheets에 반영"),
bull("[삭제] 버튼으로 고객 삭제 (확인 창 있음)"),
h2("업무 현황 배지"),
bull("출입국 / 전자민원 / 공증 / 여권·초청 / 기타 — 완료업무 건수 배지"),
bull("[완료업무 보기] 버튼 → 상세 팝업창 열기"),
bull("팝업: 접수일, 구분, 업무명, 세부내용, 완료일, 진행 상태"),
h2("서명 섹션"),
bull("고객 서명 있음/없음 표시"),
bull("[서명 등록] 클릭 → QR코드 생성 → 고객 스마트폰으로 서명"),
bull("임시저장 서명을 특정 고객에 연결하는 기능 포함"),
div(),

# ─────────────────────────────────────────────────────────────
# 4. 고객카드 버튼 가이드
# ─────────────────────────────────────────────────────────────
h1("4.  고객카드 — 기본정보 버튼 가이드"),
body("기본정보 섹션 바로 아래에 다음 버튼들이 나타납니다 (기존 고객만 표시)."),
]

# 버튼 요약 테이블
table_data = [
    ["버튼", "모양", "기능 요약"],
    ["문서자동작성", "노란 테두리, FileText 아이콘", "문서자동작성 패널 열기"],
    ["숙소제공자", "회색/파란 테두리, Home 아이콘", "숙소제공자 설정"],
    ["⚡ 원클릭 작성", "파란 배경, 번개(Zap) 아이콘 28px", "원클릭 작성 패널 열기"],
    ["🌐 체류만료조회", "초록 배경, 지구본(Globe) 아이콘 28px", "하이코리아 체류만료조회 보조"],
    ["ID", "보라 배경, 텍스트 'ID' 28px", "하이코리아 ID찾기 보조"],
]
t = Table(table_data, colWidths=[3.5*cm, 7*cm, 6.5*cm])
t.setStyle(TableStyle([
    ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#21548F")),
    ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
    ("FONTNAME",   (0,0), (-1,0), FONT_B),
    ("FONTSIZE",   (0,0), (-1,-1), 9),
    ("FONTNAME",   (0,1), (-1,-1), FONT),
    ("GRID",       (0,0), (-1,-1), 0.5, colors.HexColor("#CCCCCC")),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F7F7FF")]),
    ("VALIGN",     (0,0), (-1,-1), "MIDDLE"),
    ("LEFTPADDING",(0,0), (-1,-1), 6),
    ("TOPPADDING", (0,0), (-1,-1), 4),
    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
]))
elems += [sp(6), t, sp(6), div()]

# ─────────────────────────────────────────────────────────────
# 5. 문서자동작성
# ─────────────────────────────────────────────────────────────
elems += [
h1("5.  문서자동작성   (노란색 테두리 버튼)"),
h2("버튼 모양"),
bull("버튼 색상: 노란/금색 계열 — 배경 #FFF9E6, 테두리 #D4A843"),
bull("아이콘: 편집 문서 (FileText) 아이콘"),
bull("버튼 텍스트: [문서자동작성]"),
h2("사용 순서"),
step("1", "고객카드에서 [문서자동작성] 버튼 클릭"),
step("2", "화면 왼쪽에 문서자동작성 패널이 열림"),
step("3", "체류 / 사증 선택"),
step("4", "민원 유형 선택 (등록·연장·변경·부여·신고·기타)"),
step("5", "비자 종류 선택 (F·H2·E7·국적 등)"),
step("6", "세부 구분 선택 (1, 2, 3... 또는 일반·간이·특별)"),
step("7", "필요 서류 목록이 자동으로 표시됨"),
step("8", "원하는 서류에 체크박스 선택"),
step("9", "관련인 배정: 숙소제공자·보증인·법정대리인 등 (필요 시)"),
step("10","도장·서명 옵션 설정"),
step("11","[PDF 생성] 클릭 → PDF 다운로드"),
tip("고객 데이터(이름·등록번호·주소 등)가 PDF 필드에 자동으로 입력됩니다."),
tip("미성년자는 법정대리인 이름으로 도장이 자동 처리됩니다."),
div(),

# ─────────────────────────────────────────────────────────────
# 6. 숙소제공자
# ─────────────────────────────────────────────────────────────
h1("6.  숙소제공자   (Home 아이콘)"),
h2("버튼 모양"),
bull("버튼 색상: 회색(기본) → 파란색(설정됨)"),
bull("아이콘: 집 모양 (Home) 아이콘"),
bull("설정 전: [숙소제공자] / 설정 후: [숙소: 홍길동] 형태로 표시"),
h2("사용 방법"),
step("1", "고객카드에서 Home 아이콘 버튼 클릭"),
step("2", "숙소제공자 설정 모달 창이 열림"),
step("3", "[고객 DB 검색] 탭: 기존 등록 고객 중에서 선택"),
body("       또는 [직접 입력] 탭: 외부인 정보 직접 입력"),
step("4", "[숙소제공자 고정] 버튼 클릭"),
tip("설정된 숙소제공자 정보는 문서자동작성의 거주숙소 제공 확인서에 자동 반영됩니다."),
div(),

# ─────────────────────────────────────────────────────────────
# 7. 원클릭 작성
# ─────────────────────────────────────────────────────────────
h1("7.  원클릭 작성   (번개 아이콘 ⚡)"),
h2("버튼 모양"),
bull("버튼 색상: 파란색 계열 — 배경 #EBF8FF, 테두리 #BEE3F8"),
bull("아이콘: 번개 모양 (Zap) 아이콘"),
bull("크기: 28×28px 정사각형 아이콘 버튼"),
bull("툴팁: '원클릭 작성'"),
h2("출력 항목"),
bull("위임장 — 대리인 위임 문서"),
bull("하이코리아 — 하이코리아 접속용 정보 문서"),
bull("소시넷(등록증) — 등록증 기반 소시넷 문서"),
bull("소시넷(여권) — 여권 기반 소시넷 문서"),
h2("사용 순서"),
step("1", "번개(⚡) 아이콘 버튼 클릭 → 원클릭 작성 패널이 왼쪽에 열림"),
step("2", "생성할 문서 체크박스 선택 (복수 선택 가능)"),
step("3", "고객정보가 자동 입력됨 — 필요 시 수정"),
step("4", "도장/서명 선택 (신청인·행정사 각각)"),
body("       서명이 등록된 경우 자동으로 서명이 선택됨"),
step("5", "ID 입력: 하이코리아·소시넷 로그인 아이디"),
step("6", "구여권 번호 입력 (소시넷(여권) 선택 시에만 표시)"),
step("7", "위임장 선택 시: 위임업무 체크 (체류기간연장 등)"),
step("8", "[⚡ 원클릭 생성] 버튼 클릭"),
step("9", "JPG(1페이지) 또는 ZIP(여러 페이지) 자동 다운로드"),
tip("도장과 서명은 동시에 선택할 수 없습니다. 서명이 있으면 자동으로 서명이 선택됩니다."),
warn("도장+서명 동시 선택 시 서명만 적용됩니다."),
div(),

# ─────────────────────────────────────────────────────────────
# 8. 체류만료조회
# ─────────────────────────────────────────────────────────────
h1("8.  체류만료조회   (지구본 아이콘 🌐)"),
h2("버튼 모양"),
bull("버튼 색상: 초록색 계열 — 배경 #F0FFF4, 테두리 #C6F6D5"),
bull("아이콘: 지구본 모양 (Globe) 아이콘"),
bull("크기: 28×28px 정사각형 아이콘 버튼"),
bull("툴팁: '체류만료조회(동포)'"),
h2("보조 패널 표시 값"),
bull("여권번호 — 고객의 여권번호"),
bull("국적 — 한국계 중국인 (고정값)"),
bull("생년월일 — 19 + 등록번호 앞자리 6자리  (예: 19750606)"),
h2("사용 순서"),
step("1", "지구본(🌐) 아이콘 클릭 → 보조 패널이 아이콘 바로 아래에 열림"),
step("2", "[하이코리아 열기] 클릭 → 화면 왼쪽에 별도 창으로 열림"),
step("3", "보조 패널에서 [복사] 클릭 → 하이코리아 입력칸에 붙여넣기"),
step("4", "입력확인란(보안숫자): 화면에 보이는 숫자를 직접 입력"),
step("5", "조회 결과(체류만료일)를 '조회 결과 반영' 입력칸에 입력"),
step("6", "[등록만기일에 반영] 클릭 → 고객카드 등록만기일 필드에 반영"),
step("7", "고객카드 하단 [저장] 클릭 → 최종 저장"),
warn("하이코리아는 외부 사이트이므로 값을 자동으로 입력할 수 없습니다."),
warn("입력확인란(보안숫자)은 자동 처리가 불가능합니다. 직접 입력해야 합니다."),
tip("[전체 복사] 버튼을 사용하면 여권번호·국적·생년월일을 한꺼번에 복사할 수 있습니다."),
div(),

# ─────────────────────────────────────────────────────────────
# 9. ID찾기
# ─────────────────────────────────────────────────────────────
h1("9.  하이코리아 ID찾기   (보라색 ID 버튼)"),
h2("버튼 모양"),
bull("버튼 색상: 보라색 계열 — 배경 #FAF5FF, 테두리 #D6BCFA"),
bull("버튼 텍스트: [ID]"),
bull("크기: 28×28px 정사각형 버튼"),
bull("툴팁: '하이코리아 ID찾기'"),
h2("보조 패널 표시 값"),
bull("영문이름 — 영문 성 + 영문 이름 대문자  (예: JIN ZHEFAN)"),
bull("생년월일 — 19 + 등록번호 앞자리 6자리  (예: 19750606)"),
bull("외국인등록번호 — 앞자리+뒷자리 13자리 (하이픈 없음)  (예: 7506065820208)"),
h2("사용 순서"),
step("1", "ID 버튼 클릭 → 보조 패널이 아이콘 바로 아래에 열림"),
step("2", "[ID찾기 열기] 클릭 → 화면 왼쪽에 별도 창으로 열림"),
step("3", "보조 패널에서 [복사] 클릭 → 하이코리아 입력칸에 붙여넣기"),
warn("하이코리아는 외부 사이트이므로 값을 자동으로 입력할 수 없습니다."),
tip("체류만료조회(🌐)와 ID찾기(ID) 패널은 동시에 열리지 않습니다."),
div(),

# ─────────────────────────────────────────────────────────────
# 10. 업무관리
# ─────────────────────────────────────────────────────────────
h1("10.  업무관리   (Clipboard 아이콘)"),
h2("진행업무 탭"),
bull("분류·날짜·이름·업무명·세부내용·금액(이체/현금/카드/인지/미수) 편집"),
bull("진행 상태 체크박스: 접수 ✓ / 처리 ✓ / 보관중 ✓"),
bull("완료 체크박스 선택 → [완료 업무 추가] → 완료업무로 이동"),
tip("일일결산을 저장하면 해당 업무가 진행업무에 자동 생성됩니다."),
h2("예정업무 탭"),
bull("날짜, 기간(당일·이번주 등), 내용, 비고 입력"),
h2("완료업무 탭"),
bull("완료 처리된 업무 이력 조회"),
bull("체크 후 [삭제] 버튼으로 삭제 가능"),
div(),

# ─────────────────────────────────────────────────────────────
# 11. 일일결산
# ─────────────────────────────────────────────────────────────
h1("11.  일일결산   (DollarSign 아이콘)"),
h2("내역 입력"),
bull("구분: 현금출금 / 출입국 / 전자민원 / 공증 / 여권 / 초청 / 영주권 / 기타"),
bull("성명: 고객 이름 자동완성 — 기존 고객 선택 가능"),
bull("수입 / 지출1 / 지출2: 유형(이체·현금·카드·인지·미수) + 금액"),
bull("[추가] 버튼으로 저장"),
h2("자동 연동"),
bull("저장 시 → 진행업무 탭에 업무 자동 생성·업데이트"),
bull("고객 선택 시 → 해당 고객 위임내역에 업무 이력 자동 기록"),
div(),

# ─────────────────────────────────────────────────────────────
# 12. 월간결산
# ─────────────────────────────────────────────────────────────
h1("12.  월간결산   (BarChart2 아이콘)"),
bull("연도·월 선택 → 총 수입·지출·순수익 요약"),
bull("일별 추세 차트, 요일별 분석, 카테고리별 분석, 시간대별 분석"),
bull("전월 대비 비교"),
div(),

# ─────────────────────────────────────────────────────────────
# 13. 문서자동작성 전체
# ─────────────────────────────────────────────────────────────
h1("13.  문서자동작성   (FileEdit 아이콘)"),
body("고객 정보가 자동 입력된 PDF 서류를 생성합니다."),
h2("지원 서류"),
bull("통합신청서 (F계열, H2계열, E7 등 비자별 별도 양식)"),
bull("위임장 · 대행업무수행확인서"),
bull("비취업 서약서 · 단순노무 비취업 서약서 · 비취업 확인서"),
bull("신원보증서 · 거주숙소 제공 확인서"),
bull("직업신고서 · 한글성명 병기 신청서 · 치료예정 서약서"),
bull("법령준수 확인서 · 정보제공동의서"),
h2("관련인 배정"),
bull("숙소제공자 / 보증인 / 법정대리인 / 합산자 설정"),
tip("미성년자는 법정대리인 이름으로 도장이 자동 처리됩니다."),
warn("도장과 서명을 동시에 선택하면 서명만 적용됩니다."),
div(),

# ─────────────────────────────────────────────────────────────
# 14. OCR
# ─────────────────────────────────────────────────────────────
h1("14.  OCR 스캔   (ScanLine 아이콘)"),
body("여권·등록증 사진을 업로드하면 정보를 자동으로 읽어옵니다."),
h2("사용 방법"),
step("1", "이미지 파일 업로드 또는 카메라 촬영"),
step("2", "문서 종류 선택: 여권 / 등록증"),
step("3", "자동 인식 결과 확인"),
step("4", "[고객으로 저장] 또는 [클립보드 복사]"),
warn("OCR 결과는 이미지 품질에 따라 달라집니다. 반드시 결과를 육안으로 확인하세요."),
div(),

# ─────────────────────────────────────────────────────────────
# 15~16 (업무참고·검색·메모·게시판)
# ─────────────────────────────────────────────────────────────
h1("15.  업무참고 · 실무지침"),
h2("업무참고   (BookOpen 아이콘)"),
bull("Google Sheets '업무참고' 탭과 실시간 연동"),
bull("공휴일·수수료·체크리스트 등 참고 자료 조회·편집"),
h2("실무지침   (Library 아이콘)"),
bull("출입국 관련 실무지침·법령 자료"),
bull("카테고리별 필터 및 검색 기능"),
div(),

h1("16.  통합검색 · 메모 · 게시판"),
h2("통합검색   (Search 아이콘)"),
bull("고객·업무·게시판·메모 등 모든 데이터를 한 번에 검색"),
bull("결과 클릭 → 해당 상세 페이지로 이동"),
h2("메모   (FileText 아이콘)"),
bull("장기메모 / 중기메모 작성 및 관리"),
h2("게시판   (MessageSquare 아이콘)"),
bull("공지사항 등록, 팝업 설정, 댓글"),
bull("새 댓글 달리면 목록에 [N] 빨간 배지 표시 — 게시글 읽으면 사라짐"),
div(),

# ─────────────────────────────────────────────────────────────
# 17. 마이페이지
# ─────────────────────────────────────────────────────────────
h1("17.  마이페이지   (User 아이콘)"),
h2("사무소 정보"),
bull("사무소명·주소·대표자·연락처·사업자등록번호·행정사 주민등록번호 입력·저장"),
tip("연락처(contact_tel)를 입력해두면 소시넷·하이코리아 문서에 행정사 전화번호가 자동 삽입됩니다."),
h2("행정사 서명 등록"),
step("1", "[서명 등록] 버튼 클릭 → QR코드 생성"),
step("2", "스마트폰으로 QR코드 스캔 → 서명 → 완료"),
bull("등록된 서명은 PDF 생성 시 행정사 서명란에 자동 삽입됩니다."),
warn("QR 스캔 후 서명 완료까지 5분 이내에 처리해야 합니다. 시간 초과 시 다시 QR 생성."),
div(),

# ─────────────────────────────────────────────────────────────
# 18. 공통 팁
# ─────────────────────────────────────────────────────────────
h1("18.  공통 사용 팁"),
h2("데이터 저장"),
bull("모든 데이터는 Google Sheets에 실시간 저장됩니다."),
bull("수정 후 반드시 [저장] 버튼을 눌러야 반영됩니다. 자동 저장 없음."),
bull("저장 성공 시 화면 상단에 '저장됨' 알림이 표시됩니다."),
h2("팝업창 고객카드"),
bull("고객 드로어에서 [팝업창] 버튼 클릭 → 별도 창에 고객카드 열림"),
bull("메인 화면에서 업무를 처리하면서 고객 정보를 동시에 참조할 수 있습니다."),
h2("브라우저 권장"),
bull("Google Chrome 또는 Microsoft Edge 최신 버전 권장"),
bull("복사 기능은 HTTPS(hanwory.com)에서만 동작합니다."),
bull("팝업 차단 시 hanwory.com을 허용 목록에 추가하세요."),
sp(12),
]

# ─── PDF 빌드 ────────────────────────────────────────────────
os.makedirs("docs", exist_ok=True)
out = "docs/한우리_출입국업무관리_사용자매뉴얼.pdf"
doc2 = SimpleDocTemplate(
    out, pagesize=A4,
    leftMargin=ML, rightMargin=MR, topMargin=MT, bottomMargin=MB,
    title="한우리 출입국업무관리 사용자 매뉴얼",
    author="한우리행정사사무소",
)

def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(FONT, 8)
    canvas.setFillColor(colors.HexColor("#AAAAAA"))
    if doc.page > 1:
        canvas.drawString(ML, MB * 0.5, "한우리 출입국업무관리 시스템 — 사용자 매뉴얼")
        canvas.drawRightString(W - MR, MB * 0.5, f"p. {doc.page}")
    canvas.restoreState()

doc2.build(elems, onFirstPage=header_footer, onLaterPages=header_footer)
print(f"PDF 저장 완료: {out}")
