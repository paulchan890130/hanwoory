# Manual Update v1 — Build Report

작성일: 2026-06-03 · 브랜치: `feat/postgres-foundation`

---

## 1. Executive conclusion

**Manual Update v1 은 빌드 완료되었고 로컬에서 동작 검증되었다.**

- 기본 파이프라인은 **가볍다**: rhwp 로 텍스트/해시 추출 → baseline diff → 영향 받은
  `manual_ref` 후보 생성. **기본 모드에서 전체 PDF 를 만들지 않는다.**
- 변경 페이지가 있을 때만 **변경 페이지 ± 이웃**에 한해 검토용 PDF 를 만든다.
- 전체 staging PDF 는 `--full-pdf` 명시할 때만 생성.
- 365개 `manual_ref` 를 전수 재검사하지 않는다 — 변경 페이지에 연결된 항목만 후보로 낸다.
- 기존 운영 PDF 뷰어(`/api/guidelines/manual-pdf/{manual}`) 와 운영 PDF/DB 는 **무변경**.
- 24시간 스케줄러 / 하이코리아 폴링 / manual_ref 자동 반영 / 운영 PDF 교체는 **구현하지 않음** (의도적).

검증된 결과:
- same-baseline 전체 3종(1,449p): **변경 0 · 후보 0 · pdf_mode=none**.
- synthetic 1페이지 변경: 영향 후보 **2건만**(M1-0088, M1-0093), 변경 페이지 PDF 는 p740/741/742 **3장만**.
- 엔드포인트 4종 + 음성 케이스(400/401/403/404) 정상.
- 운영 뷰어 200 · 운영 PDF sha256 = baseline 과 동일.

---

## 2. Final architecture

```
[기존 운영 뷰어]  /api/guidelines/manual-pdf/{체류민원|사증민원}
      └─ unlocked_*.pdf 그대로 서빙 — 동작/파일 무변경 (이 작업에서 손대지 않음)

[Manual Update v1 — staging 전용, admin only]
  incoming/*.hwp
      │  rhwp extract.mjs  (텍스트 + sha1 해시, PDF 아님)
      ▼
  rhwp_text/{label}_pages.jsonl
      │  diff_pages()  baseline(260414) 대비 same/modified/moved/added/deleted
      ▼
  diff/changed_pages.json  (+ per-label, changed_pages.md)
      │  make_ref_candidates()  변경 페이지에 연결된 manual_ref 만
      ▼
  candidates/manual_ref_update_candidates.{json,xlsx,md}
      │  변경 있을 때만: generate_pdf.mjs --pages "..." --flat  (변경 ± 이웃)
      ▼
  review_pdf_pages/{label}/p####.pdf   (검토 전용)
      │  --full-pdf 일 때만: rhwp_pdf/ (per-page + merged)
      ▼
  manifest.json (pdf_mode: none | changed-pages-only | full)

[Admin UI]  /admin → "매뉴얼 업데이트 v1 (staging)" 탭
      └─ 버전 선택 · manifest 요약 · 변경 페이지 표 · 후보 표 · 변경 페이지 검토 PDF 뷰어
         (운영 뷰어와 분리된 staging 전용 iframe)
```

핵심 설계 결정:
- **기존 PDF 뷰어 유지** — rhwp SVG/HTML 뷰어로 교체하지 않음.
- **rhwp 는 1차로 텍스트/diff 엔진** — PDF 는 부차적·선택적.
- **변경 페이지만 PDF** 가 기본, 전체 PDF 는 옵션.
- 후보 생성은 **affected-only** (page-overlap 또는 ≥8자 match_text 텍스트 적중).

---

## 3. Files changed

| 파일 | 변경 |
|---|---|
| `backend/scripts/manual_update_local.py` | **전면 개편** — light 기본 동작, `--changed-pages-pdf` / `--no-changed-pages-pdf` / `--full-pdf` / `--neighbor` / `--max-pages` / `--force` 추가, `pdf_mode`/`changed_page_count`/`review_pdf_pages` manifest 필드, `changed_pages.json`(combined), `diff_pages` 에 similarity·moved 감지, `collect_affected_pages()`·`generate_changed_page_pdfs()` 신규 |
| `backend/scripts/manual_update_synthetic_test.py` | 변경 페이지 ± 이웃 검토 PDF 생성 추가(`--neighbor`/`--no-pdf`), manifest 에 `pdf_mode`/`review_pdf_pages`, combined `changed_pages.json` non-same 통일 |
| `tools/rhwp_manual_pipeline/generate_pdf.mjs` | `--pages a,b,c`(비연속 페이지 1회 로드) · `--flat`(중첩 없이 `out-dir/{label}/p####.pdf`) 옵션 추가 — 기존 동작 100% 호환 |
| `tools/rhwp_manual_pipeline/extract.mjs` | `--max-pages N` 옵션(테스트용 추출 제한) + meta 에 `full_page_count` |
| `backend/routers/guidelines.py` | `manual-staging` 검토 엔드포인트 5종 추가(아래 §5) |
| `frontend/app/(main)/admin/page.tsx` | `매뉴얼 업데이트 v1 (staging)` 탭 + `ManualUpdateV1Tab` 컴포넌트 신규 |

> 참고: `backend/data/immigration_guidelines_db_v2.json` 의 `M` 표시는 **이번 작업 이전부터** 있던 변경이며, 본 작업의 스크립트는 이 파일을 **읽기 전용**으로만 사용한다(쓰기 없음).

---

## 4. Files created

| 파일 | 내용 |
|---|---|
| `backend/data/manuals/staging/{version}/manifest.json` | 버전 메타 + `pdf_mode` |
| `backend/data/manuals/staging/{version}/diff/changed_pages.json` | 변경 페이지(non-same) 통합 목록 |
| `.../diff/{label}_changed_pages.json`, `diff/changed_pages.md` | per-label + 요약 |
| `.../candidates/manual_ref_update_candidates.{json,xlsx,md}` | 영향 후보 |
| `.../review_pdf_pages/{label}/p####.pdf` | 변경 페이지 ± 이웃 검토 PDF |
| `.../reports/staging_report.md`, `.../logs/*.log` | 보고서·node 로그 |
| `.../rhwp_pdf/...` | **`--full-pdf` 일 때만** |
| `analysis/manual_update_local_implementation/MANUAL_UPDATE_V1_BUILD_REPORT.md` | 본 보고서 |
| `analysis/manual_update_local_implementation/MANUAL_UPDATE_V1_TEST_COMMANDS.md` | 테스트 명령 모음 |

---

## 5. Backend endpoints (모두 admin only, `Cache-Control: no-store`)

신규 (`backend/routers/guidelines.py`):

| 메서드 · 경로 | 설명 |
|---|---|
| `GET /api/guidelines/manual-staging/versions` | manifest 보유 staging 버전 목록 |
| `GET /api/guidelines/manual-staging/{version}/manifest` | manifest.json |
| `GET /api/guidelines/manual-staging/{version}/changed-pages` | 변경 페이지(non-same) |
| `GET /api/guidelines/manual-staging/{version}/candidates` | 영향 받은 manual_ref 후보 |
| `GET /api/guidelines/manual-staging/{version}/{label}/review-page/{page_no}/pdf` | 변경 페이지 검토 PDF 1장 (query token 또는 헤더, **admin 필수**) |

보안:
- 버전 검증 `_safe_version()` (alnum + `_` + `-` 만) — path traversal 차단.
- `os.path.commonpath` 이중 방어로 staging 디렉터리 밖 접근 거부.
- label 화이트리스트(residence/visa/revision_history) — 위반 시 400.
- 파일 없음 404, 잘못된 label/version 400, 비-admin 403, 미인증 401.

기존 (변경 없음, 유지):
- `GET /api/guidelines/manual-pdf/{manual}` — **운영 뷰어**.
- `GET /api/guidelines/manual-pdf-staging/{version}/{label}/download` — full PDF 다운로드.
- `GET /api/guidelines/manual-pdf-staging/{version}/manifest`.

---

## 6. Admin UI changes

`/admin` 에 탭 추가: **"매뉴얼 업데이트 v1 (staging)"** (`ManualUpdateV1Tab`). 전면 재설계 없음.

- 상단 고정 안내 문구:
  - "기존 실무지침 PDF 조회는 변경되지 않았습니다."
  - "아래 자료는 최신 매뉴얼 후보 검토용 staging 자료입니다."
  - "승인 전에는 운영 실무지침에 반영되지 않습니다."
- staging 버전 셀렉터(`/versions`).
- manifest 요약: version · baseline · status · pdf_mode · 매뉴얼 수 · 변경 페이지 수 · 후보 수 + 매뉴얼별 페이지 수 칩.
- 변경 페이지 표: manual_label · baseline p. · new p. · change_type(+moved_from) · similarity · keywords · "변경 페이지 보기".
- 후보 표: row_id · 자격코드 · manual · 기존/후보 페이지 · 신뢰도 · 액션 · 사유 · 결정(placeholder "미정") · 보기.
- 변경 페이지 검토 PDF 뷰어: staging 전용 iframe (운영 뷰어 미사용). 검토 PDF 가 생성된 페이지에만 버튼 활성.
- 전체 staging PDF 는 명시적 CLI(`--full-pdf`) 안내만 표시 — 무거운 작업의 동기 실행 회피.

---

## 7. Default script behavior

```
python backend/scripts/manual_update_local.py --version <V>
```
1. incoming HWP/HWPX → staging/input 복사
2. rhwp **텍스트/해시 추출** (PDF 아님)
3. baseline 대비 **diff** (same/modified/moved/added/deleted, similarity)
4. **영향 manual_ref 후보** 생성 (affected-only)
5. 변경 페이지가 있으면 **변경 페이지 ± 1 검토 PDF** 만 생성 → `pdf_mode=changed-pages-only`
   - 변경이 없으면 `pdf_mode=none` (아무 PDF도 생성 안 함)
6. `manifest.json` 항상 생성

`--full-pdf` → `pdf_mode=full` (per-page + merged, 무거움).
`--no-changed-pages-pdf` → 변경 페이지 PDF 도 억제(diff/후보만).

---

## 8. Test results

| 테스트 | 명령 | 결과 |
|---|---|---|
| same-baseline (전체 3종) | `--version 260414_test_v1 --dry-run --force` | rev 5/visa 558/res 886 **전부 same**, 변경 0, 후보 0, **pdf_mode=none**, manifest 생성 ✅ |
| same-baseline (단일) | `--label-only revision_history` | 5 same, 변경 0, 후보 0, pdf_mode=none ✅ |
| synthetic 1p 변경 | `manual_update_synthetic_test.py` | residence p741 modified 1건, **후보 2건만**(M1-0088, M1-0093), 검토 PDF p740/741/742 **3장만**, `rhwp_pdf/` 미생성 ✅ |
| 엔드포인트 happy | manifest/changed-pages/candidates/review-pdf | 모두 200, `no-store` ✅ |
| 엔드포인트 음성 | invalid label / page / version / missing / non-admin / no-auth | 400 / 404 / 400 / 404 / 403 / 401 ✅ |
| 기존 뷰어 회귀 | `manual-pdf/체류민원`·`사증민원` | 200, bytes 12,097,749 / 11,693,461, sha256 = baseline 동일 ✅ |
| 컴파일/타입 | `py_compile` · `tsc --noEmit` | 통과 ✅ |

---

## 9. Production files changed or not

**변경 없음.**
- `unlocked_체류민원.pdf` sha256 `adbac759…` = baseline manifest 값과 동일.
- `unlocked_사증민원.pdf` sha256 `442f93b0…` = baseline manifest 값과 동일.
- `immigration_guidelines_db_v2.json` — 스크립트는 **읽기 전용**, 미수정.
- 모든 산출물은 `backend/data/manuals/staging/{version}/` 안에만 생성.

---

## 10. Remaining risks

- rhwp 파이프라인은 PoC node_modules(`analysis/rhwp_pdf_poc_260414/node_modules`)에 의존 — 해당 폴더 삭제 시 추출/PDF 동작 불가.
- 변경 페이지 검토 PDF 는 Chromium(System Chrome) 필요 — 로컬 전용 가정.
- `diff_pages` 는 인덱스 정렬 기반 — 대량의 페이지 삽입/삭제가 섞이면 정렬이 어긋나
  modified 가 과다 집계될 수 있음(moved 감지로 일부 완화). 실제 신규 버전 적용 시
  후보를 사람이 검토하는 전제이므로 v1 범위에서는 허용 가능.
- `--max-pages` 사용 시 baseline 전체와 부분 비교가 되어 added/deleted 가 과다 — 테스트 전용.
- full PDF 생성은 수백 MB·수 분 소요 — UI 동기 실행 미제공(CLI 안내만).

---

## 11. What is deliberately NOT implemented

- ❌ 24시간 자동 감지 스케줄러
- ❌ 하이코리아 폴링
- ❌ manual_ref 자동 반영(승인/적용은 후속 별도 승인 명령에서)
- ❌ 운영 공식 PDF 교체
- ❌ rhwp SVG/HTML 뷰어로 운영 뷰어 교체
- ❌ Google Sheets/Drive 연동 · Render 배포 · git commit/push

---

## 12. Next recommended phase

1. **승인→적용 명령**: 후보의 `user_decision` 을 모아 `immigration_guidelines_db_v2.json`
   의 `manual_ref` 페이지를 백업 후 ID 기반 upsert 로 반영(별도 승인 스크립트, dry-run→apply 2단계).
2. **UI 결정 저장**: 후보 표의 결정(채택/보류/직접입력)을 staging 측 파일에 저장하는 PATCH 엔드포인트.
3. **diff 정합성 강화**: 페이지 정렬이 크게 흔들릴 때를 위한 블록 정렬(LCS) 기반 매칭.
4. 그 이후에야 24h 스케줄러 / 하이코리아 폴링 검토.
