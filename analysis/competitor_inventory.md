# competitor_inventory.md
# 경쟁사 프로그램 파일 인벤토리
# 검사 경로: C:\Users\윤찬\이민행정시스템\
# 검사 방법: 읽기 전용, 정상적인 파일 탐색 및 텍스트 추출만 수행
# 작성일: 2026-04-06

---

## 1. 루트 디렉토리 구조

```
C:\Users\윤찬\이민행정시스템\
│
├── iLink.Window.UI.exe           [1,077,248 B] 메인 실행 파일 (2024-03-11)
├── iLink.Window.UI.exe.config    [19,828 B]    앱 설정 파일 (XML, 평문)
├── sms.dll                       [14,336 B]    SMS 발송 라이브러리 (2024-03-11)
├── UpdateChecker.exe             [187,392 B]   자동 업데이트 체커 (2024-03-11)
├── UpdateChecker.InstallState    [2,597 B]     설치 상태 (XML)
├── SetFolderPermission.exe       [18,432 B]    폴더 권한 설정 유틸리티
├── _version.txt                  [49 B]        버전 정보 JSON
├── _LoginInfo                    [52 B]        로그인 정보 캐시 JSON
├── _permChecked                  [0 B]         권한 확인 완료 플래그 파일
├── remakeicon.ico                [122,384 B]   앱 아이콘
├── sample.xlsx                   [11,693 B]    고객 데이터 입력 샘플 (Excel)
│
├── conf/                         설정 데이터 폴더
│   ├── facepoints                [0 B]         빈 파일 (얼굴인식 좌표용 예약)
│   ├── signpoints                [5,752 B]     서명 위치 좌표 - 주요 서식 목록 (~110개)
│   ├── signpoints2               [405 B]       서명 위치 좌표 - 추가 서식 (~9개)
│   ├── signpoints3               [30 B]        서명 위치 좌표 - 숙소제공확인서
│   └── signpoints4               [433 B]       서명 위치 좌표 - 추가 서식 (~10개)
│
├── excel/                        Excel 서식 파일 폴더
│   ├── 출입국민원접수대장.xlsx   [11,736 B]   민원 접수 대장 (2022-02-16)
│   ├── 출입국민원접수대장_imsi.xlsx [11,736 B] 임시용 동일본
│   └── 외국인등록증교부대장.xlsx  [12,142 B]  외국인등록증 교부 대장 (2022-04-06)
│
└── drivers/                      웹 자동화 드라이버 폴더
    ├── chromedriver.exe           [12,762,624 B] Chrome 웹드라이버 (2023-02-01)
    ├── MicrosoftWebDriver.exe     [17,310,120 B] Edge 레거시 웹드라이버 (2023-02-16)
    └── edgedriver_win64/
        └── msedgedriver.exe       [17,310,120 B] Edge 웹드라이버 (2023-02-16)
```

---

## 2. 제3자 라이브러리 (DLL) 목록

| 라이브러리 | 버전 | 용도 |
|---|---|---|
| DevExpress.XtraBars.v17.2.dll | 17.2 | 리본/메뉴 UI |
| DevExpress.XtraGrid.v17.2.dll | 17.2 | 데이터 그리드 |
| DevExpress.XtraEditors.v17.2.dll | 17.2 | 입력 에디터 |
| DevExpress.XtraLayout.v17.2.dll | 17.2 | 폼 레이아웃 |
| DevExpress.XtraPdfViewer.v17.2.dll | 17.2 | PDF 뷰어 내장 |
| DevExpress.XtraRichEdit.v17.2.dll | 17.2 | 리치텍스트 편집 |
| DevExpress.XtraNavBar.v17.2.dll | 17.2 | 탐색 사이드바 |
| DevExpress.XtraTreeList.v17.2.dll | 17.2 | 트리 목록 |
| DevExpress.XtraCharts.v17.2.dll | 17.2 | 차트/그래프 |
| DevExpress.Pdf.v17.2.Core.dll | 17.2 | PDF 처리 |
| DevExpress.RichEdit.v17.2.Core.dll | 17.2 | 리치텍스트 코어 |
| iTextSharp.dll | - | PDF 생성/편집 |
| GemBox.Spreadsheet.dll | 37.3 | Excel 처리 |
| Newtonsoft.Json.dll | - | JSON 처리 |
| HwpCtrl.ocx | - | 한글(HWP) 문서 제어 |
| AxInterop.HWPCONTROLLib.dll | - | HWP COM 인터롭 |
| Interop.HWPCONTROLLib.dll | - | HWP COM 인터롭 |
| MstHtmlEditor.dll | - | HTML 편집기 |
| NHunspell.dll | - | 맞춤법 검사 |
| sms.dll | - | SMS/알림톡 발송 (자체 제작) |

---

## 3. 핵심 파일 분석

### _version.txt (평문 JSON)
```json
{"version":"1.7.8","filePath":"http://"}
```
- 프로그램 버전: **1.7.8**
- filePath: 업데이트 서버 주소 (현재 비어 있음)

### _LoginInfo (평문 JSON)
```json
{"ClientID":"VhH24nNZ","usrID":"jpup","Passwd":null}
```
- 마지막 로그인 정보 캐시
- Passwd는 null (메모리에만 유지하거나 별도 보안 저장소 사용)

### iLink.Window.UI.exe.config (WCF 서비스 설정)
- **런타임**: .NET Framework 4.6.2
- **백엔드 서비스 URL**: `http://soa.eos21.co.kr/soaDbconn2.svc`
  - 바인딩: WSHttpBinding (보안 없음)
  - 계약: `SoaDbconn2.IsoaDbconn2`
- **파일 전송 서비스 URL**: `http://soa.eos21.co.kr/TransferService.svc`
  - 바인딩: BasicHttpBinding
  - 계약: `FileTransferService.ITransferService`
- **벤더 도메인**: `eos21.co.kr`

### sms.dll (SMS 라이브러리 - 공개 API 메서드)
확인된 메서드 시그니처 (리플렉션 메타데이터):
- `SendSMS` — 문자 발송
- `SendMMS` — 멀티미디어 발송
- `SendLMS` — 장문 발송
- `SendAlimtalk` — 카카오 알림톡 발송
- `SendChingutalk` — 카카오 친구톡 발송
- `GetBalance` — 잔액 조회
- `UploadImage` — 이미지 업로드
- `UploadKakaoImage` — 카카오용 이미지 업로드
- `GetSignature` — 인증 서명 생성
- `GetAuth` — 인증 처리

확인된 파라미터명:
`templateId`, `groupId`, `imageId`, `linkPc`, `linkAnd`, `buttonName`, `buttonType`, `message`, `protocol`, `method`

### sample.xlsx (고객 데이터 입력 예시 - 시트명: "엑셀고객등록")
고객 데이터 컬럼 구조:
- 등록이름 / 성 / 이름
- 연도 / 월 / 일 (생년월일 분리)
- 앞자리 / 뒷자리 (외국인등록번호)
- 성별 / 국적
- 외국인등록번호 (통합)
- 생년월일
- 여권번호
- 체류자격구분
- 여권발급일자 / 여권유효기간 / 체류만료일
- 전화번호 / 핸드폰번호
- 우편번호
- 대한민국내주소1 / 대한민국내주소2

---

## 4. 웹 자동화 드라이버 존재 의미

`drivers/` 폴더에 Chrome, Edge 웹드라이버가 존재:
- 하이코리아(HiKorea) 또는 전자정부 시스템 자동화 가능성
- 민원 자동 제출, 상태 조회, 체류자격 확인 등에 사용 추정

---

## 5. 주요 실행 파일 특성

- `iLink.Window.UI.exe`: **난독화 적용됨** (ConfuserEx 또는 유사 도구)
  - 바이너리에서 추출한 한글 문자열이 정상적으로 읽히지 않음
  - UI 문자열, 메뉴 레이블 등은 평문 추출 불가
  - → 실행을 통한 정상적인 관찰만 가능 (별도 실행 환경 필요)
