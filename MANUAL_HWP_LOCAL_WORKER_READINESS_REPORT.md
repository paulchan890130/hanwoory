# MANUAL_HWP_LOCAL_WORKER_READINESS_REPORT.md

이전에 성공했던 HWP/HWPX 매뉴얼 변환 파이프라인이 현재 로컬 Windows 머신에서 그대로 동작 가능한지 점검한 **읽기 전용 진단** 보고서.

본 진단은 어떤 변환도 실행하지 않음. HWP 잠금해제·다운로드·PDF 저장·Google API 호출·git 변경 모두 0건.

---

## 1. 실행 결론 (Executive Conclusion)

| 영역 | 상태 |
|---|---|
| 검증된 코드 자산 (`hwp_unlock.py`, `hwp_to_pdf.py`, `manual_watcher.py`) | ✅ 그대로 존재, 핵심 패턴 모두 보존 |
| .NET 도구 (`OpenHwpExe.exe`, `HwpSharp.dll`, `OpenMcdf.dll`) | ✅ 분석 폴더에 존재 |
| 이전 변환 결과 PDF 2종 (체류민원/사증민원) | ✅ 약 11.6MB / 12.1MB 로 디스크에 보존 |
| Hancom Office (HWPFrame.HwpObject) | ✅ **2024 v13.0.0.1352** 설치 + COM 객체 즉시 생성/해제 성공 (파일 무열림) |
| Python 의존성 (`pythonnet/clr`, `win32com`(pywin32), `olefile`) | ❌ **현재 venv 에 미설치** — Phase A/B 실제 호출 불가능 |
| Python 의존성 (`fitz` / PyMuPDF) | ✅ 1.27.2.2 설치 — Phase B 의 2-up 분할만 단독 동작 가능 |

**총평:**

- 시스템 측 자산(.NET 도구, Hancom Office)은 **즉시 동작 가능 상태**.
- 코드 자산도 손상 없이 그대로 보존.
- 단지 `.venv` 의 Python 패키지 3 종 (`pythonnet`, `pywin32`, `olefile`) 만 재설치하면 이전 파이프라인이 **그대로 부활** 가능. 추가 코드 작업 불필요.

---

## 2. 파일 존재 확인 (체크리스트)

8개 모두 **확인됨**. 절대경로 + 바이트 크기:

| # | 파일 | 크기 | 상태 |
|---|---|---|---|
| 1 | `backend/services/hwp_unlock.py` | 9,774 | ✅ |
| 2 | `backend/services/hwp_to_pdf.py` | 8,009 | ✅ |
| 3 | `backend/services/manual_watcher.py` | 14,788 | ✅ |
| 4 | `analysis/클로드/배포용 한글문서 변환기/OpenHwpExe.exe` | 19,968 | ✅ |
| 5 | `analysis/클로드/배포용 한글문서 변환기/HwpSharp.dll` | 29,184 | ✅ |
| 6 | `analysis/클로드/배포용 한글문서 변환기/OpenMcdf.dll` | 62,464 | ✅ |
| 6a | `analysis/클로드/배포용 한글문서 변환기/OpenHwpExe.exe.config` | 189 | ✅ (참고) |
| 7 | `backend/data/manuals/unlocked_체류민원.pdf` | 12,097,749 | ✅ |
| 8 | `backend/data/manuals/unlocked_사증민원.pdf` | 11,693,461 | ✅ |

---

## 3. Python 의존성 체크리스트

`.venv/Scripts/python.exe` (= `C:\Users\윤찬\K.ID soft\.venv\Lib\site-packages`) 기준:

| 패키지 | import 결과 | 비고 |
|---|---|---|
| `pythonnet` (`import pythonnet`) | ❌ `ModuleNotFoundError` | Phase A 잠금해제 필수 |
| `clr` (`import clr`) | ❌ `ModuleNotFoundError` | `pythonnet` 설치 시 함께 제공 |
| `win32com.client` (pywin32) | ❌ `ModuleNotFoundError` | Phase B HWP→PDF 필수 |
| `olefile` | ❌ `ModuleNotFoundError` | `inspect_hwp` 가 OLE 헤더 파싱에 사용 |
| `fitz` (PyMuPDF) | ✅ **1.27.2.2** | `split_2up_landscape` 등 PDF 가공용 |

### 부가 진단 — venv 이중 경로 주의
- `.venv\Scripts\python.exe` → `C:\Users\윤찬\K.ID soft\.venv\Lib\site-packages` (실제 Korean 경로)
- `.venv\Scripts\pip.exe` → `C:\Users\66885\Documents\K.ID 이민…\.venv\Lib\site-packages` (DBCS shortname 우회 경로)

⇒ 직접 `pip.exe install ...` 은 다른 site-packages 에 떨어지므로, **반드시 `python -m pip install ...` 형식** 으로 설치해야 의존성이 동일 venv 에 적용된다 (이전 라운드에서 동일 이슈 확인됨).

### 권장 재설치 명령 (실행 안 함, 가이드만)
```powershell
.venv\Scripts\python.exe -m pip install pythonnet pywin32 olefile
```

PyMuPDF 는 이미 설치되어 있으므로 제외.

---

## 4. Hancom COM 사용 가능성 결과

**검증 방식:** PowerShell `New-Object -ComObject HWPFrame.HwpObject` 로 객체 생성 후 **즉시** `Quit()` + `ReleaseComObject` → 파일 무열림, PDF 무생성. (`win32com` 미설치이므로 Python 경로 우회.)

| 항목 | 값 |
|---|---|
| ProgID `HWPFrame.HwpObject` CLSID | `{2291CF00-64A1-4877-A9B4-68CFE89612D6}` (HKLM\SOFTWARE\Classes 에 등록) |
| WOW6432Node CLSID 등록 | 없음 (64-bit 단독) |
| Uninstall 항목 검색 | **한컴오피스 2024 · v13.0.0.1352** · `C:\Program Files (x86)\HNC\Office 2024\` |
| COM 인스턴스 생성 시도 | ✅ **OK** — 객체 생성 성공 즉시 Quit + Release |
| 파일 열림 / PDF 저장 | ❌ **수행 안 함** (진단 범위 제한) |

**의미:** 한컴 자동화 보안 환경설정은 이전 시점에 1회 완료된 것으로 보임 (없으면 보안 대화상자가 떴을 것). 다만 사용자 세션에서만 안정적이고, Windows Service / 비대화형 세션에서 동일 동작은 보장되지 않는다 (§6 위험 참고).

---

## 5. 기존 코드 경로 확인 (소스 grep)

세 파일의 핵심 패턴을 모두 한 번에 검증. **모두 보존됨**.

| 패턴 | 위치 (file:line) |
|---|---|
| `OpenHwpExe.exe` 절대경로 상수 | `hwp_unlock.py:24` (`_OPEN_HWP_EXE = _TOOL_DIR / "OpenHwpExe.exe"`) |
| `Main.ConvertFile` 인용 | `hwp_unlock.py:11`, `hwp_unlock.py:115` (`method = main_t.GetMethod("ConvertFile", bf)`) |
| Subprocess worker (`_WORKER_CODE`) | `hwp_unlock.py:94–132` |
| `Application.DoEvents()` 폴링 | `hwp_unlock.py:121` |
| `Assembly.LoadFrom(OpenHwpExe.exe)` | `hwp_unlock.py:100–102` |
| `asm.GetType("OpenHwpExe.Main")` | `hwp_unlock.py:105` |
| `win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")` | `hwp_to_pdf.py:37` |
| `RegisterModule("FilePathCheckDLL", "AutomationModule")` | `hwp_to_pdf.py:10` (docstring), `hwp_to_pdf.py:40` (실호출) |
| `HAction.GetDefault("FileSaveAsPdf", ...)` | `hwp_to_pdf.py:62` |
| `HAction.Execute("FileSaveAsPdf", ...)` | `hwp_to_pdf.py:66` |
| `SaveAs(dst, "PDF", "")` fallback | `hwp_to_pdf.py` (워커 코드 내) |
| `def split_2up_landscape(...)` | `hwp_to_pdf.py:89` |
| `split_2up_landscape(...)` 호출 | `hwp_to_pdf.py:207` |
| `.watcher_state.json` 경로 상수 | `manual_watcher.py:49` (`STATE = MANUALS / ".watcher_state.json"`) |
| `.watcher_state.json` 도큐먼트 | `manual_watcher.py:16` |

⇒ 직전 라운드 조사 보고서 (`MANUAL_HWP_PDF_CONVERSION_HISTORY_INVESTIGATION_REPORT.md` §3) 의 흐름 그대로 **재구현 없이 부활 가능**.

---

## 6. 위험 (Risks)

본 진단에서 발견된 잠재 위험:

1. **venv 이중 경로** — `pip.exe` 와 `python.exe` 가 서로 다른 `.venv` 를 가리킨다 (`C:\Users\66885\Documents\…` vs `C:\Users\윤찬\…`). `pip install` 단독으로는 의존성이 잘못된 venv 에 떨어진다. **`python -m pip` 강제** 필요.
2. **Hancom COM 의 비대화형 환경 한계** — 한컴 자동화는 메시지 펌프가 필요해 winlogon 콘솔 세션에서만 안정적이다. Windows Service / Task Scheduler "사용자 로그온 여부와 무관" 옵션으로 돌리면 freeze / dialog 차단으로 실패할 수 있다.
3. **한컴 보안 환경설정 의존** — 이전에 "도구 > 환경설정 > 보안" 또는 `AutomationModule` 등록을 1회 수행한 상태로 보임. 한컴 업데이트나 사용자 프로필 재생성 시 재등록 필요.
4. **OpenHwpExe.exe 출처/라이선스** — `analysis/클로드/배포용 한글문서 변환기/` 에 그대로 보존되어 있으나, README / 출처 문서가 없어 서드파티 도구 사용의 적법성은 사용자 책임이다.
5. **HWPX 미지원** — 모든 코드가 HWP 5.x OLE 전용. 향후 하이코리아가 HWPX 신형식으로 전환하면 별도 PoC 필요.
6. **DRM / 일반 암호 보호 문서** — `hwp_unlock.py` 가 `password` / `drm` 비트 ON 이면 즉시 거부. 우회 시도 흔적 없음 (정책상 합당).
7. **`OpenHwpExe.exe` 실행 권한 / 보안 솔루션** — 일부 EDR/AV 제품이 .NET WinForms 도구를 차단할 수 있다. 사용자 PC 의 보안 정책 확인 필요.

---

## 7. 다음 권장 단계 (Next Recommended Step)

진단만 수행. 실제 작업은 다음 라운드에서 진행 권장. 우선순위:

1. **(필수) Python 의존성 3개 재설치** — 코드 / 시스템은 이미 준비됨. 다음 한 줄이면 Phase A/B 가 동작 가능:
   ```powershell
   .venv\Scripts\python.exe -m pip install pythonnet pywin32 olefile
   ```
   (`PyMuPDF` 는 이미 1.27.2.2 설치됨.)

2. **(권장) 비파괴 smoke 검증** — 실제 잠금해제/변환은 하지 않고, import 만 성공 시 다음 3 단계만 확인:
   - `from backend.services.hwp_unlock import inspect_hwp` 로 기존 PDF 가 아닌 raw HWP 1건만 `inspect` (수정 안 함, OLE 헤더만 읽음)
   - `win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")` Python 측에서 객체 생성 + `Quit()` (파일 무열림)
   - `pythonnet` 으로 `OpenHwpExe.exe` Assembly.LoadFrom 만 성공 확인 (`Main.ConvertFile` 호출 안 함)

3. **(보류) 실제 변환 재실행** — 사용자 명시 지시 전까지 보류. 실행 시 사용자 PC 에서 한컴 GUI 가 백그라운드 실행되어야 하므로, 사용자 작업 시간대 회피.

4. **(다음 라운드) 매뉴얼 자동 업데이트 시스템 설계** — 직전 조사 보고서 §6 의 Phase 1~5 안 (소스 감지 → 로컬 Windows 워커 → PDF diff → 패치 후보 → admin 승인) 으로 진행.

---

**정지.** 본 보고서는 진단만 기록. 변환·다운로드·코드 수정·외부 API 호출·git 작업 0건. 사용자 검토 대기.
