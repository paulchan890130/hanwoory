# MANUAL_HWP_PDF_CONVERSION_HISTORY_INVESTIGATION_REPORT.md

신규 매뉴얼 자동 업데이트 시스템을 설계하기 전, 본 프로젝트에서 이미 한 번 성공한 HWP/HWPX → PDF 변환 작업의 흔적을 전수 조사한 보고서.

**조사 원칙:** 코드 미수정 · 변환 미실행 · 외부 호출 0. 마크다운 문서 + 기존 코드 파일 + 분석 자산만 읽음.

---

## 1. 조사한 파일 목록

### 1-A. 전체 프로젝트 마크다운 (node_modules 등 제외) — 53개
검색에 사용된 키워드 hit 분포:

| 키워드 | 마크다운 파일 hit |
|---|---|
| `hwp\|HWP\|hwpx\|HWPX\|배포용\|잠금\|libreoffice\|soffice\|한컴\|hancom` | **10 files** |
| `OpenHwpExe\|HWPFrame\|hwp_unlock\|hwp_to_pdf\|manual_watcher\|ViewText\|BodyText\|LEA-128` | **3 files** (핵심) |
| `google.{0,20}drive.{0,30}convert\|drive\.files\.export` | **0 files** ← Google Drive 변환 시도 흔적 없음 |

### 1-B. 결정적 증거가 있는 파일 (모두 절대경로)

| 파일 경로 | 역할 |
|---|---|
| `C:\Users\윤찬\K.ID soft\docs\session-log.md` | 2026-04-30 세션 로그 — Phase A/B 요약 (인용 §75–§89) |
| `C:\Users\윤찬\K.ID soft\docs\CLAUDE_OLD_BACKUP.md` | 매뉴얼 자동화 파이프라인 절 §810–§889 |
| `C:\Users\윤찬\K.ID soft\docs\CLAUDE_OLD_BACKUP_20260504_105823.md` | 위 문서의 타임스탬프 백업 (동일 내용) |
| `C:\Users\윤찬\K.ID soft\CLAUDE_MANUAL_REF.md` | manual_ref 후속 작업 현황 |
| `C:\Users\윤찬\K.ID soft\backend\services\hwp_unlock.py` | 잠금해제 구현 |
| `C:\Users\윤찬\K.ID soft\backend\services\hwp_to_pdf.py` | HWP→PDF 구현 |
| `C:\Users\윤찬\K.ID soft\backend\services\manual_watcher.py` | 워치독 (폴링 + 다운로드) |
| `C:\Users\윤찬\K.ID soft\backend\scripts\test_hwp_unlock_poc.py` | PoC 스크립트 |
| `C:\Users\윤찬\K.ID soft\backend\scripts\scrape_hikorea_test.py` | 하이코리아 스크래핑 테스트 |
| `C:\Users\윤찬\K.ID soft\analysis\클로드\배포용 한글문서 변환기\OpenHwpExe.exe` | .NET 변환기 본체 (+ `HwpSharp.dll`, `OpenMcdf.dll`, `OpenHwpExe.exe.config`) |
| `C:\Users\윤찬\K.ID soft\backend\data\manuals\unlocked_체류민원.pdf` | 실제 변환 결과 PDF 1 |
| `C:\Users\윤찬\K.ID soft\backend\data\manuals\unlocked_사증민원.pdf` | 실제 변환 결과 PDF 2 |

---

## 2. 관련 증거 (파일별 핵심 내용)

### 2-A. `docs/session-log.md` §75–§89 — 2026-04-30 세션

**섹션 헤더:** `## 2026-04-30 세션 (오후) — 매뉴얼 자동화 파이프라인 구축`

**Phase A — HWP 잠금해제 (`backend/services/hwp_unlock.py`):**
- 배포용 HWP의 진짜 보호: `BodyText` 빈 stub + `ViewText`가 LEA-128 암호화 + 256바이트 키 record
- 단순 비트 토글 / 단순 ViewText 복사 모두 손상 발생 (검증 완료)
- **정답: `OpenHwpExe.exe`(분석 폴더, .NET) 의 `Main.ConvertFile()` 메서드를 subprocess + DoEvents 폴링으로 호출**
- WinForms async Task는 `Application.DoEvents()` 메시지 펌프 필요
- subprocess 분리 필수 — Form 인스턴스 재사용 시 deadlock

**Phase B — 매뉴얼 워치독 + PDF 변환 (`manual_watcher.py`, `hwp_to_pdf.py`):**
- 하이코리아 NTCCTT_SEQ=1062 페이지 폴링 → 첨부파일 timestamp 변경 감지
- 다운로드 endpoint: `POST /fileNewExistsChkAjax.pt`
- **HWP→PDF는 한컴 COM(`HWPFrame.HwpObject`) 사용.** `RegisterModule("FilePathCheckDLL", "AutomationModule")` 으로 보안 대화상자 우회
- **2-up 자동 분할** (`split_2up_landscape`): 가로 A4(841×595pt)에 두 페이지 모아찍기된 경우 PyMuPDF로 좌/우 분할
- 캐시: `.watcher_state.json` — 변경 감지 시에만 처리

### 2-B. `docs/CLAUDE_OLD_BACKUP.md` §810–§889 — 동일 내용 영구 문서화

**섹션 헤더:** `## 매뉴얼 자동화 파이프라인 (2026-04-30 구축)`

핵심 인용:
- "배포용(distribution) HWP의 진짜 보호 메커니즘:
  - `FileHeader` bit 2 = 1
  - `BodyText/Section*` = 빈 stub (314바이트)
  - `ViewText/Section*` = LEA-128 암호화된 본문 + `HWPTAG_DISTRIBUTE_DOC_DATA(0x1C)` 256바이트 키 record
  - **단순 비트 토글로는 한컴이 손상으로 인식**"
- "해결: `OpenHwpExe.exe`(분석 폴더, .NET) 의 `Main.ConvertFile()` 메서드를 **subprocess + DoEvents 폴링**으로 호출."
- "의존성: `pythonnet`, `olefile`, `OpenHwpExe.exe + HwpSharp.dll + OpenMcdf.dll` (`analysis/클로드/배포용 한글문서 변환기/`)"
- "HWP→PDF는 한컴 COM(`HWPFrame.HwpObject`) 사용. 자동화 보안 우회: `RegisterModule("FilePathCheckDLL", "AutomationModule")`"

### 2-C. `backend/services/hwp_unlock.py` — 잠금해제 실제 구현

핵심 인용:
- 파일 헤더: `"HWP 5.x 배포용 문서 잠금 해제 서비스 (v4 — subprocess wrapper)"`
- "정식 잠금해제는 LEA 복호화가 필요하므로, 이미 검증된 .NET 도구 OpenHwpExe.exe 의 Main.ConvertFile() 을 호출."
- 변환 흐름:
  - `inspect_hwp()`: olefile 로 OLE 구조 + FileHeader flags 점검
  - `password` 또는 `drm` 비트 ON 이면 즉시 거부 (`해제 불가`)
  - `distribution` 비트 OFF 이면 단순 복사
  - `distribution` 비트 ON 이면 `OpenHwpExe.exe` 호출
- 호출 방식: `subprocess.run([sys.executable, "-c", _WORKER_CODE, src, prefix, timeout])`
- 워커 (별도 Python process):
  - `clr.AddReference("System.Windows.Forms")` → `Application.EnableVisualStyles()`
  - `Assembly.LoadFrom(OpenHwpExe.exe)` → `OpenHwpExe.Main` 타입 인스턴스화
  - `radSavePathPrefix.Checked = True`, `txtSavePathPrefix.Text = "unlocked_"`
  - `Main.ConvertFile(src, basename)` (BindingFlags NonPublic|Instance)
  - `while not task.IsCompleted: Application.DoEvents(); sleep(0.02)`
- 검증: 변환 후 다시 `inspect_hwp()` 로 distribution 비트 OFF 확인 → 실패 시 RuntimeError

### 2-D. `backend/services/hwp_to_pdf.py` — HWP → PDF 실제 구현

핵심 인용:
- "한컴오피스 COM 자동화(HWPFrame.HwpObject) 사용. 배포용 잠금이 풀린 HWP 파일을 PDF로 변환."
- 워커:
  - `win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")`
  - `hwp.RegisterModule("FilePathCheckDLL", "AutomationModule")` — 보안 대화상자 우회
  - `hwp.Open(src, "HWP", "forceopen:true;suspendpassword:true")`
  - `FilePrintSetup.PagesPerSheet = 0` (1-up 강제)
  - `FileSaveAsPdf` 액션 → 실패 시 `SaveAs(dst, "PDF", "")` 폴백
- 2-up 자동 분할: `split_2up_landscape()` — A4 가로(841×595) + 비율 1.3~1.5 페이지를 PyMuPDF 로 좌/우 분할

### 2-E. `backend/services/manual_watcher.py` — 워치독 파이프라인

핵심 인용:
- 추적 매뉴얼 (3종): `체류민원`, `사증민원`, `수정이력`
- 대상 페이지: `https://www.hikorea.go.kr/board/BoardNtcDetailR.pt?BBS_SEQ=1&BBS_GB_CD=BS10&NTCCTT_SEQ=1062&page=1`
- 다운로드: `POST https://www.hikorea.go.kr/fileNewExistsChkAjax.pt` (form 9개 필드)
- 변경 감지: 첨부파일명 끝 17자리 `[20260414182305670].hwp` 패턴에서 timestamp 추출 → `.watcher_state.json` 캐시와 비교
- 변경 시 흐름:
  1. raw_HWP 저장 (`manuals/raw_<oriFileNm>`)
  2. `unlock_hwp()` 호출 → `manuals/unlocked_<label>.hwp`
  3. `hwp_to_pdf()` 호출 → `manuals/unlocked_<label>.pdf`
  4. 캐시 갱신
  5. (옵션) 게시판 자동공지 1회

### 2-F. 변환 결과 PDF — 실제 존재 확인

```
backend/data/manuals/unlocked_체류민원.pdf
backend/data/manuals/unlocked_사증민원.pdf
```

`docs/CLAUDE_OLD_BACKUP.md` §828 의 "pdf_size: 11645052" 같은 수치도 기록되어 있어 변환 성공 사실 확정.

### 2-G. Google Drive 변환 시도 흔적 — **없음**

`google.{0,20}drive.{0,30}convert` / `drive\.files\.export` / `application/pdf` (in conversion context) / `gdocs` / `구글.{0,5}드라이브.{0,20}변환` — 마크다운 0건 hit.

`docs/CLAUDE_OLD_BACKUP.md:500` 의 "application/pdf" 매칭은 여권/등록증 스캔 PDF 처리 (`handlePassportFile`) 로, 매뉴얼 변환과 무관.

사용자가 기억하는 "Google Drive 변환 자동화 실패" 는 **실제 코드/문서로 흔적이 남지 않음**. 결론: 본 프로젝트는 처음부터 한컴 COM + .NET OpenHwpExe 경로로 성공했으며, Google Drive 변환은 채택되지 않았다.

---

## 3. 재구성된 이전 방법 (Step-by-step)

| 단계 | 입력 | 도구 / 명령 | 출력 |
|---|---|---|---|
| 1 | 매뉴얼 페이지 (NTCCTT_SEQ=1062) | `requests.get` + `_FN_PATTERN` 정규식 | 첨부 메타데이터 dict (timestamp 포함) |
| 2 | 첨부 메타 | `POST /fileNewExistsChkAjax.pt` | 원본 HWP 바이너리 (`raw_<oriFileNm>`) |
| 3 | 배포용 HWP | `olefile.OleFileIO` + FileHeader flags 점검 | distribution / password / drm 판정 |
| 4 | distribution=true HWP | **subprocess + pythonnet + `OpenHwpExe.exe` (.NET WinForms)** → `Main.ConvertFile(src, "unlocked_")` (NonPublic Instance, DoEvents 폴링) | `unlocked_<label>.hwp` (LEA-128 복호화된 본문 + distribution 비트 OFF) |
| 5 | 잠금해제 HWP | **`win32com.client.gencache.EnsureDispatch("HWPFrame.HwpObject")`** → `RegisterModule("FilePathCheckDLL","AutomationModule")` → `Open(forceopen:true;suspendpassword:true)` → `FileSaveAsPdf` 액션 | `unlocked_<label>.pdf` |
| 6 | (옵션) 가로 A4 2-up PDF | PyMuPDF (`fitz`) `split_2up_landscape()` 좌/우 분할 | 1-up portrait PDF |
| 7 | 결과 | `.watcher_state.json` 캐시 갱신 + (옵션) 게시판 자동공지 | — |

**입력 파일 타입:** 한글 5.x OLE 구조 HWP (배포용 = `FileHeader` bit 2 = 1).

**보호 메커니즘:** LEA-128 암호화된 ViewText + `HWPTAG_DISTRIBUTE_DOC_DATA(0x1C)` 256바이트 키 record.

**제거된 것:** distribution flag + ViewText 의 LEA 암호화 (정확하게는 OpenHwpExe 가 복호화 후 일반 BodyText 로 재구성).

**제거 방법:** **단순 비트 토글로는 손상 발생.** OpenHwpExe.exe (.NET) 의 `Main.ConvertFile()` 가 정상 복호화 + 일반 HWP 재기록.

**사용된 변환 프로그램:**
1. `OpenHwpExe.exe` (.NET WinForms, `analysis/클로드/배포용 한글문서 변환기/` 폴더 내 4 파일)
2. 한컴오피스 (HWPFrame.HwpObject COM — 시스템에 설치되어 있어야 함)

**한계:**
- `password` 비트 ON 인 일반 암호 문서는 해제 불가
- `drm` 비트 ON 인 DRM 문서도 해제 불가
- HWPX (XML 기반 신형식) 미검증 — 본 구현은 HWP 5.x 전용

---

## 4. 위험도 평가

| 항목 | 평가 |
|---|---|
| 자동화 안전성 | ⚠️ subprocess + DoEvents 폴링 + Form 인스턴스 deadlock 회피 등 미세 조정 필요. 한 번 동작하면 안정적이나, 동시 실행 / 재진입 시 freeze 가능 |
| Windows 의존성 | ✅ Windows 전용 (.NET / WinForms / DoEvents / win32com 모두 Windows-only) |
| 한컴오피스 설치 필요 | ✅ HWP→PDF 단계가 한컴 COM 사용 — 라이선스가 있는 한컴오피스 설치 + 1회 보안 환경설정 (도구 > 환경설정 > 보안 > 낮음 또는 AutomationModule 등록) 필수 |
| GUI 상호작용 | ⚠️ headless 가능하지만 WinForms 메시지 펌프 (`Application.DoEvents`) 가 필요해 winlogon 세션이 있어야 안정적. **Windows 서비스로 돌리면 흔히 실패** — 콘솔 세션에서 돌려야 함 |
| Render Linux 실행 가능 여부 | ❌ **불가**. .NET 의존 + 한컴 COM 의존 → Linux 컨테이너에서 동작 불가 |
| 로컬 Windows 워커 vs 서버 | **로컬 Windows 워커 강제** — Render 측 처리 시도 자체가 무의미 |
| 라이선스 / 법적 위험 | 한컴 자동화 API 사용은 라이선스 허용 범위 (개인/사업체 보유 정품). OpenHwpExe.exe 는 분석 폴더에 이미 포함된 .NET 도구 — 출처 / 라이선스는 사용자 책임 |

---

## 5. 권장 아키텍처

조사된 증거만으로 도출:

```
┌──────────────────────────────────────────────────────────────┐
│  FastAPI + PostgreSQL (Render or 로컬)                        │
│  ─────────────────────────────────────                        │
│  - 매뉴얼 메타데이터 테이블 (manual_versions)                  │
│  - 페이지 매핑 / 매뉴얼 인덱스 (manual_pages, manual_overrides)│
│  - 패치 후보 / 승인 큐 (manual_patch_candidates)               │
│  - 감사 로그 (audit_logs)                                     │
│  - 변환 결과 PDF 메타데이터 (path / sha256 / pages / size)    │
└────────────────┬─────────────────────────────────────────────┘
                 │ REST + outbox/notification
                 │
                 ▼
┌──────────────────────────────────────────────────────────────┐
│  로컬 Windows Worker (사용자 PC 또는 사내 Windows 머신)       │
│  ─────────────────────────────────────                        │
│  - 폴링: 하이코리아 NTCCTT_SEQ=1062 timestamp 감시            │
│  - 다운로드: POST /fileNewExistsChkAjax.pt                    │
│  - 잠금해제: OpenHwpExe.exe + pythonnet (이미 검증)           │
│  - 변환: 한컴 COM HWPFrame.HwpObject (이미 검증)              │
│  - 2-up 분할: PyMuPDF                                         │
│  - 결과 업로드: PDF + sha256 + manifest → 서버 API             │
└──────────────────────────────────────────────────────────────┘

❌ Google Drive 변환 자동화는 채택하지 않음
   (이전 코드/문서에 시도 흔적 자체가 없으며, 안정 경로가 이미 검증됨)
```

**PDF 저장 경로 (단계적):**
- Phase 단기: 로컬 워커가 만든 PDF 를 서버 `/manuals/` 로 업로드 → FastAPI 가 파일시스템 저장
- Phase 중기: PG `manual_versions.pdf_blob` (BYTEA) 또는 S3-호환 객체 저장소 (Render Disk / B2 / R2 등)

**실무지침 업데이트 흐름:**
1. 워커가 새 PDF 업로드 → 서버가 페이지 diff 계산 + 영향받는 manual_ref 후보 추출
2. **admin 승인 큐** (`manual_patch_candidates`) — 자동 반영 금지
3. admin 이 row-by-row 검토 후 "적용" 클릭 → manual_ref 일괄 PATCH
4. 모든 변경은 audit_logs 에 기록

---

## 6. 구체적 다음 구현 계획 (Phase 1 ~ 5)

본 라운드에서는 **구현하지 않음**. 차후 라운드용 제안.

### Phase 1 — 소스 감지 + 다운로드 메타데이터
- 기존 `manual_watcher.fetch_attachment_list` 재사용
- 새 `manual_versions` 테이블: `(id, manual_label, hikorea_timestamp, ori_filename, apnd_seq, downloaded_at, raw_path, sha256, status)`
- 변환 단계 분리 — 다운로드만 먼저 끝내고 상태 `RAW_DOWNLOADED`
- 검증: timestamp 변경 → row 1개 추가, 다른 매뉴얼 row 무변동 (row-level INSERT)

### Phase 2 — 로컬 Windows 변환 워커 (검증된 메서드)
- 별도 패키지 `manual_worker/` (서버 코드와 의존성 분리)
- 사용자 PC 에서 `python -m manual_worker run` 실행
- 워커 흐름:
  1. 서버 API 호출 → 변환 대기 row 목록 조회
  2. 각 row 의 raw HWP 다운로드 (또는 서버 path 공유)
  3. `unlock_hwp` → `hwp_to_pdf` → `split_2up_landscape`
  4. PDF + sha256 + page_count 를 서버에 PUT
  5. 상태 `PDF_READY` 로 갱신
- 한컴오피스 설치 + AutomationModule 등록 1회 가이드 문서화

### Phase 3 — PDF 페이지 추출 + diff
- 서버에서 PDF 도착 시 PyMuPDF 로 페이지별 텍스트 추출 → `manual_pages` (manual_label, version_id, page_no, text)
- 직전 버전의 동일 페이지와 diff
- 변동 페이지 + manual_ref 영향 범위 계산 → `manual_patch_candidates`

### Phase 4 — 실무지침 patch 후보 생성
- 기존 `manual_indexer_v6` + `MANUAL_PAGE_OVERRIDE` 누적 테이블 패턴 재사용
- 각 후보 row: `(manual_ref_id, old_page_from, old_page_to, suggested_page_from, suggested_page_to, confidence, evidence_text)`
- LLM 검증 옵션 (`backend/scripts/llm_judge_*` 기존 인프라 재사용)

### Phase 5 — admin 승인 + 적용
- `/admin/manual-review` 화면에 patch_candidates 표시
- 일괄 / 개별 승인 → manual_ref 일괄 PATCH
- 모든 변경은 audit_logs 기록 + 게시판 자동 공지 (선택)

---

## 7. 알려지지 않은 사항 (Unknowns)

이번 조사로 **확인된** 것은 위 §3 의 완전한 흐름 + 의존성. 다만 다음은 본 조사 범위에서 확인 못 함:

| 항목 | 상태 |
|---|---|
| `OpenHwpExe.exe` 원본 출처 / 라이선스 | 파일은 `analysis/클로드/배포용 한글문서 변환기/` 에 존재. README 등 없음. 분석/추출 경로 불명 |
| HWPX (XML 신형식) 지원 여부 | 현재 구현은 HWP 5.x OLE 전용. HWPX 처리 코드 없음 |
| 한컴오피스 버전 호환성 정확한 범위 | 코드에 명시된 버전 없음. HWPFrame.HwpObject 는 한컴오피스 2007+ 지원이지만 검증 환경 미기록 |
| `password` / `drm` 비트 ON 문서 해제 가능성 | 코드에서 즉시 거부. 우회 시도 흔적 없음 |
| Render Linux 에서의 시도 흔적 | 없음 — 처음부터 로컬 Windows 전제 |
| 사용자가 "이전에 성공" 이라 표현한 Google Drive 변환 | 흔적 없음. 사용자의 기억일 가능성. **현재 검증된 경로 = 한컴 COM + OpenHwpExe** |
| 변환 시 한컴 보안 환경설정 1회 단계의 자동화 | 코드 주석에 "최초 1회만 사용자가 한컴에서 도구>환경설정>보안>낮음 설정" 명시. 자동화 도구 없음 |

---

## 8. 최종 권고

### 지금 자동화 가능한가?
**예 — 단, 로컬 Windows 워커 형태로만.**

이미 검증된 코드가 있고, 실제 결과 PDF 가 디스크에 존재한다. 동일 경로를 워커 패키지로 다듬어 운영화하는 것이 가장 안전하다.

### 가장 안전한 방법
1. 본 라운드는 **구현하지 않고 본 보고서 + 기존 코드 보전**.
2. 다음 라운드에서 §6 Phase 1 부터 단계적 구현.
3. Render Linux 측에서 변환 시도하지 말 것. 한컴 COM / OpenHwpExe / pythonnet 모두 Linux 미지원.
4. Google Drive 변환 자동화는 **명시적으로 채택하지 않음.** 이전 시도 흔적도 없고, 검증된 안전 경로가 있다.

### 만약 자동화가 어려운 경우의 대체안
- 한컴오피스 미설치 환경 / 로컬 Windows 워커 운영 어려운 경우:
  - 매뉴얼 변경 알림만 자동화 + PDF 변환은 수동 (사용자가 한컴에서 직접 "다른 이름으로 저장 → PDF") 후 업로드 폼 제공
  - 또는 HWPX 변환에 별도 오픈소스 도구 (예: hwp5proc 같은 reverse-engineered 라이브러리) 평가 — 별도 PoC 필요

### 빠진 증거 / 추가 확인 필요
- `OpenHwpExe.exe` 의 정확한 라이선스 / 안전성 검토 (서드파티 분석 도구 사용 적법성)
- HWPX 신형식 매뉴얼이 하이코리아에 올라오는 경우의 대응 (현재 코드는 HWP 5.x 만)
- 한컴오피스 라이선스 — 자동화 호출에 대한 한컴 측 약관 확인

---

**정지.** 본 보고서는 **조사만** 수행. 변환/구현/배포 미수행. 사용자 검토 대기.
