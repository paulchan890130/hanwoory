# 이민행정시스템.zip 추출 보고서

## 1) 아카이브 개요
- 총 파일 수: 177
- 최상위 실행 파일: `iLink.Window.UI.exe`
- 실행 환경: `.NET Framework 4.6.2`
- 주요 UI 라이브러리: `DevExpress 17.2`
- 문서 처리: `HWPCONTROLLib`, `iTextSharp`, `GemBox.Spreadsheet`
- 브라우저 자동화 드라이버 포함: `chromedriver.exe`, `msedgedriver.exe`, `MicrosoftWebDriver.exe`

## 2) 바로 확인되는 핵심 기능
### A. 원격 DB/파일 연동
- DB/WCF 엔드포인트
- http://soa.eos21.co.kr/soaDbconn2.svc
- http://soa.eos21.co.kr/TransferService.svc

- EXE 문자열에서 확인되는 DB/파일 메서드
- <FileName>k__BackingField
- <UserUploaded>k__BackingField
- Action*http://tempuri.org/ITransferService/isFile
- Action+http://tempuri.org/ITransferService/getFile
- Action,http://tempuri.org/ITransferService/getFiles
- Action.http://tempuri.org/ITransferService/UploadFile
- Action.http://tempuri.org/ITransferService/deleteFile
- Action/http://tempuri.org/ITransferService/UploadFile2
- Action/http://tempuri.org/ITransferService/getFileInfoy
- Action/http://tempuri.org/ITransferService/getFileSize
- Action0http://tempuri.org/ITransferService/DownloadFile
- Action0http://tempuri.org/ITransferService/getDirectory}
- Action2http://tempuri.org/ITransferService/directoryExist
- Action4http://tempuri.org/ITransferService/getDirectoryInfo
- Action7http://dnetsoa.bebob.net/IsoaDbconn2/IsoaDbconn2/logout
- Action9http://dnetsoa.bebob.net/IsoaDbconn2/IsoaDbconn2/saveFile
- Action:http://dnetsoa.bebob.net/IsoaDbconn2/IsoaDbconn2/AddRegist{
- Action;http://dnetsoa.bebob.net/IsoaDbconn2/IsoaDbconn2/ExecuteSQL
- Action;http://dnetsoa.bebob.net/IsoaDbconn2/IsoaDbconn2/loginCheck
- Action<http://dnetsoa.bebob.net/IsoaDbconn2/IsoaDbconn2/ExecuteSQL2
- ActionAhttp://dnetsoa.bebob.net/IsoaDbconn2/IsoaDbconn2/getDataSetString
- ActionBhttp://dnetsoa.bebob.net/IsoaDbconn2/IsoaDbconn2/getDataSetString2
- ActionChttp://dnetsoa.bebob.net/IsoaDbconn2/IsoaDbconn2/loginCheckforilink
- AddRegist
- AddRegistAsync
- AssemblyAssociatedContentFileAttribute
- AssemblyFileVersionAttribute
- AttachFile
- AttachFileInfo
- Bebob.FileUpload.ForiLink
- CompanyRegistInfo
- CompanyRegistInfo 
- ConfigurationName$FileTransferService.ITransferServiceV
- DataSet
- Directory
- DirectoryInfo
- DownloadData
- DownloadFile
- DownloadFile2
- DownloadFileAsync

### B. 문서/폼 처리
- HWP 관련 폼/클래스
- AxHWPCONTROLLib
- AxHwpCtrl
- AxInterop.HWPCONTROLLib
- DHwpAction
- DHwpParameterSet
- HWPCONTROLLib
- HwpFileInfo
- Interop.HWPCONTROLLib
- cHwpFile
- frmHwpEditor
- frmHwpViewer
- get_HwpFileInfo
- hwpConvert
- hwpFileInfo
- hwpUploadURL
- set_HwpFileInfo
- ucHWPLine

- PDF/Excel 관련
- ExcelCell
- ExcelFile
- ExcelRow
- ExcelRowCollection
- ExcelRowColumnCellCollectionBase
- ExcelRowColumnCollectionBase`1
- ExcelWorksheet
- ExcelWorksheetCollection
- PdfContentByte
- PdfReader
- PdfStamper
- PdfViewer
- iTextSharp.text.pdf

### C. UI 모듈(폼/사용자컨트롤)
- 폼: frmAbout, frmBoard, frmHwpViewer, frmHwpEditor, frmIDPASS, frmIDPWList, frmLogin, frmMain, frmMainList, frmMemo, frmSignPad
- 사용자컨트롤: ucFile, ucHWPLine, ucPhotoArray, ucPhotoBox, ucSetDate, ucSignPad, ucMEMO

### D. 보조 기능
- SMS/Kakao 발송 DLL 존재: `sms.dll`
- 업데이트 모듈: `UpdateChecker.exe`
- 폴더 권한 설정 모듈: `SetFolderPermission.exe`
- 사진/서명 관련: `ucPhotoArray`, `ucPhotoBox`, `ucSignPad`, `AutoCrop`, `frmSignPad`

## 3) 첨부 템플릿/대장 파일
- `excel/외국인등록증교부대장.xlsx`: 대행업무 수행확인서(외국인등록증 등 수령)
- `excel/출입국민원접수대장.xlsx`: 출입국민원 접수대장
- `sample.xlsx`: 고객 엑셀 업로드/등록용 샘플

## 4) 서명 좌표 설정 파일(conf/signpoints)
- 총 항목 수: 128
- 특정 민원서류에서 서명/날인 위치를 자동화하기 위한 좌표 테이블로 보임.
- 포함 서식 예:
- 통합신청서
- 위임장
- PCR동의서
- 거소신고서
- 건강확인서
- 국내단순노무업종 비취업 서약서
- 국적보유신고서
- 국적상실신고서
- 국적선택신고서
- 국적이탈신고서
- 국적취득신고서
- 국적판정신청서
- 국적회복신청서
- 국적회복진술서(일반국가)
- 국적회복진술서(중국동포)
- 귀화신청서
- 비취업서약서(F-1-5)
- 비취업서약서(F-1-28)
- 사실증명 발급열람신청서
- 사증발급인정신청서
- 영주자격자의 배우자 결혼배경진술서(F-2-3)
- 외국국적불행사서약서
- 외국인 배우자의 결혼배경 진술서
- 외국인 재학여부 신고서
- 외국인 재학여부 신고서(해당자)
- 외국인 직업 및 연간 소득금액 신고서
- 외국인 직업 신고서
- 외국인 직업 신고서(해당자)
- 자기건강확인서
- 장기체류를 위한 거주 체류자격(F-2)변경·연장신청사유서
- 재입국사유서
- 취업 외 목적 방문취업(H-2) 체류자격 소지자 안내 및 유의사항
- 한글병기 신청서
- 확인서
- 사업자(고용주)및 신청인 서약서
- 소득금액증명 서식
- 비취업서약서(F-1)
- 영주(F-5) 자격 신청자 기본 정보
- 국내거소신고사실발급신청서(위임장)
- 재입국 시 유의사항 안내 및 확인 동의서

## 5) 난독화 상태 판단
- `iLink.Window.UI.exe`는 완전히 패킹되어 있지 않음.
- 주요 폼명, 컨트롤명, 서비스명, 메서드명, 엔드포인트가 그대로 노출됨.
- 다만 `c8cba187bd...` 같은 난수형 식별자도 다수 존재하여 일부 난독화는 적용된 것으로 보임.
- 이번 추출에서는 난수형 식별자를 제거하고, 의미 있는 심볼(폼/메서드/서비스/템플릿/좌표/엔드포인트) 위주로 재구성함.
- 현재 환경에는 전용 .NET 디컴파일러가 없어 전체 소스 수준 복원까지는 하지 않았음.

## 6) 실무 참고용 핵심 결론
1. 이 시스템은 로컬 WinForms + 원격 WCF 서비스(DB/파일) 구조다.
2. 문서(HWP/PDF/Excel) 처리, 사진/서명 배치, 민원대장 관리, 파일 업로드/다운로드, 로그인/업체등록, SMS/Kakao 발송, 업데이트 모듈까지 포함한다.
3. `conf/signpoints`는 서류별 서명 위치 자동화 참고자료로 바로 쓸 수 있다.
4. `sample.xlsx`와 각종 대장 엑셀은 고객 엑셀 업로드/등록 구조 설계 참고자료 가치가 높다.
5. 재현 우선순위는 고객 엑셀 등록 구조 → 문서 업로드/다운로드 → 서명 좌표 자동화 → HWP/PDF 미리보기 → SMS/알림 순이 합리적이다.
