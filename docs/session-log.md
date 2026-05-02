# Session Log — K.ID SaaS

과거 세션별 수정 완료 항목 기록. 현재 코드 상태를 반영하는 참고 이력.

---

## 2026-04-30 세션 (저녁) — manual_ref 정밀화 v3 파이프라인 + 1차 apply

**전체 흐름**: 매뉴얼 매핑 정확도 감사 → 라우팅 정정 → 6 카테고리 분류 → 사람 spot-check → blocklist 누적 → DB 적용 → 사후 검증/이상치 감사. **DB는 항상 read-only로 시작, 사람이 명시적 `--apply` 실행 시에만 변경.**

**감사 v1 (`backend/scripts/audit_manual_mapping.py`):**
- 369 row × PDF/structure/CSV 후보 전수 비교
- 7가지 매칭 방법(manual_override/exact_bracket_heading/code_alias_exact/structure_heading/exact_action_heading/section_only/prefix_fallback) + 5단계 신뢰도(`exact/high/medium/low/none`)
- 결과: exact+high 238, medium 111, low+none 20 / conflict 66 / E-9 conflict 20

**감사 v2 (`backend/scripts/audit_manual_mapping_v2.py`):**
- **action_type 우선 라우팅** — VISA_CONFIRM→사증, 그 외→체류
- 두 매뉴얼에서 독립적 후보 생성 후 preferred 매뉴얼 선택, 비선호 매뉴얼만 후보가 있으면 신뢰도 강제 하향
- 효과: E-9 conflict 20→0, F-1 17→6 (라우팅 false positive 해소)

**Triage v3 (`backend/scripts/triage_manual_mapping_v3.py`):**
- 6 카테고리 분류:
  - `AUTO_SAFE` (170, apply_candidate=true): preferred 매뉴얼 + exact/high + status∈{same,changed} + no warning
  - `ROUTING_SAFE_REVIEW` (21): current_in_wrong_manual conflict
  - `MANUAL_REVIEW` (43): both_manuals_plausible conflict, missing_current with high
  - `LOW_CONFIDENCE` (126): medium/low 또는 prefix_fallback
  - `NO_CANDIDATE` (2): 후보 없음
  - `APPLICATION_CLAIM_REVIEW` (7): APPLICATION_CLAIM/빈 코드

**Apply 스크립트 (`backend/scripts/apply_manual_mapping_triage_v3.py`):**
- DEFAULT dry-run, `--apply` 명시 시에만 DB 갱신
- 8중 candidate 검증: triage_category=AUTO_SAFE / apply_candidate=true / status=changed / confidence∈{exact,high} / no routing_warning / no both_plausible / action≠APPLICATION_CLAIM / valid manual+pages
- blocklist 자동 로드 (`manual_mapping_apply_blocklist_v3.json`), malformed면 abort
- 백업: `backend/data/backups/immigration_guidelines_db_v2.manual_ref_backup_<TS>.json`
- 사전·사후 JSON 검증 + master_rows 개수 보존 + readback 검증, 실패 시 abort + 복구 명령 출력
- candidates에 blocked_id 섞이면 즉시 abort (이중 안전망)

**Spot-check 도구 (`backend/scripts/build_spotcheck_v3.py`):**
- AUTO_SAFE changed 151 → 89 표본 추출 (high-jump ≥20p / D-2 EXTRA_WORK / first30 / by-action / by-manual)
- PNG 렌더링 (DPI 120): `backend/data/manuals/spotcheck_pages_v3/<row_id>_<manual>_p<N>.png`
- 페이지 텍스트 미리보기 (PDF raw, 1500자 한도, AI 요약 금지)

**EXTRA_WORK 엄격 검증 (`backend/scripts/review_extra_work_v3.py`):**
- 페이지 heading 영역(첫 600자) + 본문 1500자 분석
- BLOCK 자동 분류 규칙: 자격 설명 마커("자격해당자"/"1회에부여할수"/"체류기간상한"/"별도허가없이") + EXTRA_WORK 섹션 헤더 부재 → BLOCK
- 56건 검증 결과: KEEP 45 / BLOCK 10 / NEEDS_REVIEW 1
- D-2-1~D-2-8 + D-4-1/D-4-7 모두 p.35로 매핑되었으나 p.35는 D-2 자격 설명 페이지 → BLOCK 자동 검출 ✅

**비-EXTRA_WORK 최종 spot-check (`backend/scripts/final_spotcheck_v3.py`):**
- CHANGE/EXTEND/REGISTRATION/REENTRY/GRANT 16 표본 (top 15 by page_delta + action_type별 최소 표본)
- 자동 분류: PASS 14 / BLOCK 1 / NEEDS_REVIEW 1
- 자동 분류된 BLOCK/NEEDS_REVIEW 2건 모두 사람 검증 결과 false negative — 한컴 매뉴얼 테이블 셀이 한글 자모를 세로 배치(`체류자격\n부\n여`)하기 때문에 단순 키워드 매칭 실패. 페이지는 실제로 정답에 가까움.

**Blocklist 누적 결정 (12 row):**
- D-2-1~D-2-8 EXTRA_WORK (8): p.35 자격 설명 페이지 false positive
- D-4-1, D-4-7 EXTRA_WORK (2): D-2와 동일한 p.35 false positive 패턴
- M1-0005 D-2 EXTRA_WORK (p.36): 페이지 중간부터 EXTRA_WORK 시작하나 row title이 "유학 시간제취업"이라 정확 페이지 재확인 필요
- M1-0085 F-3-2R EXTRA_WORK (p.625): 페이지 90%가 CHANGE/EXTEND, EXTRA_WORK는 마지막 4줄 — 본체는 p.626 이어짐

**Apply 실행 + 검증 (2026-04-30 23:19):**
- 139 row의 `manual_ref` 갱신 (DB 1,038,187 → 1,011,468 bytes)
- 백업: `immigration_guidelines_db_v2.manual_ref_backup_20260430_231933.json`
- `verify_apply_v3.py` 12개 검증 항목 모두 PASS:
  - master_rows 369 보존 / updated=139 / match_proposed=139/139 / blocked_unchanged=12/12 / protected_unchanged=199/199 / non_manual_ref_field_diffs=0 / actual_mismatch=0 / errors=0

**사후 이상치 감사 (`backend/scripts/audit_post_apply_manual_ref_anomalies_v3.py`):**
- 5개 패턴 검출: SAME_PAGE_CLUSTER / DUAL_MANUAL_SUSPICIOUS / WRONG_PRIMARY_MANUAL / BROAD_FAMILY_PAGE / USER_SPECIFIED_HIGH
- 192 anomaly 검출 (115 HIGH priority)
- 사용자 명시 4건 (F-1-15 EXTEND / F-1-21 VISA_CONFIRM / F-1-22 EXTEND / F-1-24 EXTEND): 정답 = 체류 p.543 + 사증 p.404 → CREATE_MANUAL_OVERRIDE 권장
- 적용된 139 row 중 23 row가 anomaly 패턴에 걸렸으나 `RESTORE_FROM_BACKUP` 권장은 0 — apply는 일관되게 좁고 정밀한 페이지로 이동
- 잔여 169 anomaly는 적용 안 된 legacy 부정확 매핑 — 별도 후속 단계

---

## 2026-04-30 세션 (오후) — 매뉴얼 자동화 파이프라인 구축

**Phase A — HWP 잠금해제 (`backend/services/hwp_unlock.py`):**
- 배포용 HWP의 진짜 보호: `BodyText` 빈 stub + `ViewText`가 LEA-128 암호화 + 256바이트 키 record
- 단순 비트 토글 / 단순 ViewText 복사 모두 손상 발생 (검증 완료)
- 정답: `OpenHwpExe.exe`(분석 폴더, .NET) 의 `Main.ConvertFile()` 메서드를 subprocess + DoEvents 폴링으로 호출
- WinForms async Task는 `Application.DoEvents()` 메시지 펌프 필요
- subprocess 분리 필수 — Form 인스턴스 재사용 시 deadlock

**Phase B — 매뉴얼 워치독 + PDF 변환 (`manual_watcher.py`, `hwp_to_pdf.py`):**
- 하이코리아 NTCCTT_SEQ=1062 페이지 폴링 → 첨부파일 timestamp 변경 감지
- 다운로드 endpoint: `POST /fileNewExistsChkAjax.pt`
- HWP→PDF는 한컴 COM(`HWPFrame.HwpObject`) 사용. `RegisterModule("FilePathCheckDLL", "AutomationModule")` 으로 보안 대화상자 우회
- **2-up 자동 분할** (`split_2up_landscape`): 가로 A4(841×595pt)에 두 페이지 모아찍기된 경우 PyMuPDF로 좌/우 분할
- 캐시: `.watcher_state.json` — 변경 감지 시에만 처리

**Phase C — 매뉴얼 페이지 인덱서 v6 (`manual_indexer_v6.py`):**
- 〔F-X-Y〕 정식 표기 = sub-category 시작 (강한 시그널)
- (F-X-Y) 일반괄호 = 본문 인용 (약한 시그널, 노이즈)
- sub-category 영역 = 자기 시작 ~ 다음 〔??〕 시작 직전
- 모든 sub-category에 CHANGE 자동 강제 등록
- 일반 자격은 본문 연속 3+ 페이지 보호로 F-4-R 같은 케이스 처리

**중요한 발견 — DB와 매뉴얼 코드 체계 불일치:**
- DB: 일반/시행령 표기 (`F-5-2 미성년 자녀`)
- 매뉴얼: 시행령 별표 1의3 호수 (`〔F-5-4〕`)
- `DB_TO_MANUAL_ALIAS` + `MANUAL_PAGE_OVERRIDE` 누적 테이블로 해결

**Phase D — DetailPanel PDF 임베드:**
- `ManualPdfViewer` 컴포넌트 — 왼쪽 floating 패널, 매뉴얼별 탭, 페이지 자동 이동
- 백엔드 PDF 서빙: `GET /api/guidelines/manual-pdf/{manual}` (JWT 쿼리토큰 또는 헤더 인증)
- `Content-Disposition` 한글 파일명 RFC 5987 형식 필수 (latin-1 인코딩 한계)
- iframe URL fragment `#navpanes=0&pagemode=none` 으로 좌측 썸네일 패널 숨김

**LLM 자동화 인프라 (`backend/scripts/`):**
- `analyze_manual_structure.py` — 매뉴얼 통째 LLM 분석 (1M context, streaming, max_tokens=64000, prompt caching)
- `build_llm_chunks_v2.py` — v6 인덱스 활용 자격별 통합 청크
- `llm_remap_all.py` — 자격별 일괄 LLM 처리
- `apply_llm_results.py` — DB 적용 + 자동 백업
- `rollback_manual_ref_keep_tips.py` — 매핑만 롤백, 팁/수정 유지
- `MANUAL_PAGE_OVERRIDE`에 사용자 정답 누적 (F-5-1, F-5-2, F-5-6, F-5-11, F-5-14, F-4 EXTRA_WORK, F-4-R EXTEND)

**LLM 매핑 한계 (실증):**
- 청크 분할(25k chars) 시 자격 섹션 일부만 LLM에 전달 → 잘못된 페이지 답변
- 매뉴얼 코드 체계가 시행령과 달라 LLM도 혼동
- 사용자 누적 override 방식이 더 정확
- 매뉴얼 통째 1M context LLM 분석 (Phase 1) 또는 사용자 누적 override가 정답

---

## 2026-04-30 세션 수정 완료 항목

**관리자 계정 소프트 삭제 (`backend/routers/admin.py`, `frontend/app/(main)/admin/page.tsx`, `frontend/lib/api.ts`):**
- `DELETE /api/admin/accounts/{login_id}` 엔드포인트 추가 — `is_active=FALSE`로 소프트 삭제
- 이미 비활성이면 idempotent 200 반환 (두 번 삭제 시 500 방지)
- `DeleteConfirmModal` 컴포넌트: 계정명·경고문·[취소]/[삭제 확인] 버튼
- 비활성 계정 행에서 삭제 버튼 → "삭제됨" 배지로 교체 (재클릭 방지)
- `adminApi.deleteAccount(loginId)` 추가

**고객카드 팝업 창 (`frontend/app/customer-popup/page.tsx`):**
- 새 파일 생성: 인증 필요, 레이아웃 없음, 드로어와 동일한 필드 그룹(기본정보·연락처·등록증·여권·업무정보)
- 고정 버튼 → **팝업창** 버튼(`<ExternalLink>`)으로 변경
- `localStorage["pinned_customer"]` 저장 후 `window.open()` 새 창 (창 이름 `customer_card_popup`으로 재사용)
- `storage` 이벤트로 다른 고객 선택 시 팝업 실시간 갱신
- 팝업 차단 시 fallback: CustomEvent → 오른쪽 고정 패널

**실무지침 DB 동포 브랜치 Phase 1 전체 패치:**
- 패치 스크립트: `backend/scripts/patch_donpo_v1.py` (H-2·F-4 핵심 6개), `patch_donpo_v2_full.py` (나머지 17개 전체)
- H-2(4개): 등록·연장·변경·재입국 모두 `practical_notes`·`step_after`·`apply_channel` 추가
- F-4(7개): 거소신고·단순노무특례·재입국·F-4-19·인구감소지역·지역특화형(변경·연장) 전면 재작성
- F-5 동포 경로(8개): 국민배우자·미성년자녀·결혼이민자·재외동포동포영주(5개 sub_types)·점수제우수인재·H-2제조업4년·영주등록·영주재입국
- `GuidelineSubType` 타입 추가 (`frontend/lib/api.ts`)

**실무지침 UI 업그레이드 (`frontend/app/(main)/guidelines/page.tsx`):**
- L4 조건 분기: `row.sub_types` 있으면 "어떤 경우인가요?" 분기 버튼 표시 → 서류 자동 교체
- `parseChannelDocs()`: `【전자민원】`/`【창구민원】` 마커 파싱, 채널별 탭 표시
- DetailPanel 신규 섹션: 실무 주의사항(`practical_notes`, 파란 배경), 허가 후 다음 단계(`step_after`, 초록 배경), 신청경로 뱃지(`apply_channel`)
- DetailPanel 폭: 440px → 460px

---

## 2026-04-26 세션 수정 완료 항목

**실무지침 `/guidelines` 클릭 버그 수정 (`frontend/app/(main)/guidelines/page.tsx`):**
- **버그**: 카드에 9건 표시되어 있어도 클릭 시 0건 + "해당 항목이 없습니다." 표시
- **원인**: `entryRowCounts`가 `ep.count`(서버 API)를 사용하고, 클릭 결과는 `getMatchingRows(allRows, entry)` (클라이언트 필터)를 사용 — 데이터 소스 분리. `list` API silent fail 시 `allRows = []`가 되면서 두 값이 불일치.
- **수정**:
  1. `entryRowCounts` → `allRows.length > 0`이면 `getMatchingRows(allRows, ep).length`로 계산 (카드 count = 클릭 결과 항상 동일)
  2. `handleEntryClick` → `allRows.length === 0`이면 `list` API 재요청 후 `loadEntryRows` 실행 (fallback)
  3. `setAllRows` → `Array.isArray(rows) ? rows : []` 안전 가드 추가
  4. `loadEntryRows` → `console.debug` 로그 추가 (inputRows/matched/sample 확인용)

**모바일 공개 헤더/연락처 바:**
- `frontend/components/PublicMobileNav.tsx` + `public-mobile.css` 신규 생성
- 모바일(`≤768px`) 전용: 고정 상단 헤더 `[로고] 한우리행정사사무소 > 현재 페이지명`, 고정 하단 연락처 바 `문의전화 : 010-4702-8886 [전화 아이콘] [SMS 아이콘]`
- 홈페이지(`/`)는 기존 `.nav`가 상단 담당 → 하단 바만 추가. 비홈페이지 공개 페이지는 상단+하단 모두 표시.
- `homepage.css` 모바일 미디어쿼리에 `footer { padding-bottom: 72px }` 추가 (하단 바 가림 방지)

**로컬 SEO 페이지 신규 생성:**
- `app/siheung-immigration-agent/page.tsx` — 시흥 행정사 랜딩 (서버 컴포넌트, `LocalBusiness` + `BreadcrumbList` JSON-LD)
- `app/jeongwang-immigration-agent/page.tsx` — 정왕 행정사 랜딩 (서버 컴포넌트, `LocalBusiness` + `BreadcrumbList` JSON-LD)
- 두 페이지 모두: 주요 업무 카드 그리드, 상담 준비 체크리스트, 준비서류 바로가기(`/board/f4-extension-documents` 등), 사무소 연락처 카드 포함

**메타데이터 / JSON-LD 업데이트:**
- `layout.tsx` default title: "한우리행정사사무소 | **시흥·정왕 출입국 행정사**"
- `app/page.tsx` JSON-LD: `LegalService` → `LocalBusiness` (telephone `010-4702-8886`, streetAddress `군로서마을로 12, 1층`, `areaServed` 배열, `knowsAbout` 배열)
- `board/[id]/page.tsx` Article JSON-LD에 `mainEntityOfPage` 추가
- CTA 섹션 전화번호 `031-488-8862` → `010-4702-8886`

**미들웨어 / 사이트맵:**
- `middleware.ts`: `/siheung-immigration-agent`, `/jeongwang-immigration-agent` 공개 경로 추가
- `sitemap.ts`: 두 페이지 정적 항목 추가 (priority 0.8, changeFrequency: monthly)

**홈페이지 로컬 SEO 텍스트:**
- About 섹션 소개 문구: "경기도 시흥시 정왕동 인근 … 시흥 행정사" 포함
- `about-visual` 박스: 소재지 → "경기도 시흥시 정왕동", 연락처 → "010-4702-8886", 지역 안내 링크 2개 추가
- 푸터 컬럼 → "지역 안내" 헤딩 + 시흥/정왕 링크
- 푸터 하단 라인 → "경기도 시흥시 정왕동 · 시흥 행정사" 포함

---

## 2026-04-25 세션 수정 완료 항목

**준비서류 안내 게시물 일괄 import:**
- `hanwoori_required_documents_original_txt/` — 원본 TXT 파일 46개 (`.txt` 형식). 각 파일에 `제목:`, `슬러그 제안:`, `카테고리:`, `요약:`, `메타설명:`, `태그:`, `공개여부:`, `본문:` 필드 포함.
- `hanwoori_required_documents_posts_txt/` — 번호 매겨진 pre-processed TXT 파일 46개 (참고용).
- `import_board_posts.py` — 루트에 위치. TXT 파일 파싱 → slug 기준 upsert (시트 전체 덮어쓰기 없음). `--dry-run` 옵션 지원. 실행: `python import_board_posts.py [--dry-run]`
- `diagnose_marketing_posts.py` — 루트에 위치. Google Sheets `홈페이지게시물` 탭 현황 진단 (데이터 삭제 없음). 실행: `python diagnose_marketing_posts.py`

**TXT 파일 파싱 규칙** (`import_board_posts.py` 기준):
- `00_` 로 시작하는 파일 자동 제외
- `본문:` 라인 이후 전체가 content (이 라인 포함 전까지가 frontmatter)
- `공개여부: 공개` → `is_published=TRUE`; 나머지 → `FALSE`
- Upsert 키: `slug` (영문 슬러그). 기존 게시물의 slug와 충돌하지 않으면 신규 생성

**`/board` UI 개선 (현재 최종 상태):**
- `board/page.tsx` → server component (data fetch), `BoardClient.tsx` → client component
- `BoardClient.tsx` — `BOARD_ONLY` 세트로 준비서류 카테고리 제외, 일반 카테고리(공지사항/업무 안내/제도 변경/기타) 필터, 검색, `/documents` 바로가기 callout, 게시물 목록
- 게시물 목록 링크: `post.slug || post.id` (slug 우선), maxWidth 820

**`/documents` 신규 생성 (현재 최종 상태):**
- `documents/page.tsx` — server component; metadata(title: "업무별 준비서류 | 한우리행정사사무소"), BreadcrumbList JSON-LD
- `documents/DocumentsClient.tsx` — 9그룹 44링크; 검색; 각 `<section id="f4">` 등 stable anchor; `scrollMarginTop: 80`
- 미들웨어에 `/documents` 공개 경로 추가; sitemap에 priority 0.9로 추가

**홈페이지 `업무별 준비서류` 섹션:**
- `app/page.tsx` — BOARD 섹션과 FAQ 사이에 `<section id="documents-section">` 추가
- `DOCUMENT_GROUPS` 상수: 9개 카드, 각 `/documents#${anchor}` 링크
- 홈페이지 "전체" 탭 필터에 `HOMEPAGE_BOARD_ONLY` 세트 적용 → 46개 준비서류 게시물 홈페이지에서 제외

**메타데이터 업데이트:**
- `layout.tsx` default title: ~~"한우리행정사사무소 | 출입국·체류·사증 업무 안내"~~ → 2026-04-26 세션에서 변경됨
- `board/page.tsx` title: "업무 안내", canonical: `https://www.hanwory.com/board`
- `documents/page.tsx` canonical: `https://www.hanwory.com/documents`

**SEO / 구조화 데이터:**
- `app/page.tsx` — ~~`LegalService` JSON-LD (031-488-8862)~~ → 2026-04-26 세션에서 `LocalBusiness`로 교체됨
- `board/[id]/page.tsx` — `Article` + `BreadcrumbList` JSON-LD
- `documents/page.tsx` — `BreadcrumbList` JSON-LD (홈 › 업무별 준비서류)
- `robots.txt` — 단순화: `Allow: /`, `Disallow: /login|/dashboard|/admin|/marketing|/private`
- MARKETING_HEADER: 12 → 17 columns (`image_file_id`, `image_url`, `image_alt`, `meta_description`, `tags` 추가)

---

## 2026-04-22 세션 수정 완료 항목

- sitemap.xml → `/login` 리디렉션 버그 수정: 미들웨어 matcher에 `xml|txt` 추가 + pathname 공개 예외 목록에 `/sitemap.xml`, `/robots.txt` 추가
- `frontend/app/sitemap.ts` 신규 생성 (동적 sitemap, 마케팅 게시물 포함)
- `frontend/public/robots.txt` 신규 생성
- 마케팅 게시물 편집기 리치 에디터로 업그레이드:
  - `frontend/components/MarkdownContent.tsx` — 공개 페이지 마크다운 렌더러 (의존성 0)
  - `frontend/components/RichEditor.tsx` — 관리자용 마크다운 툴바 에디터
  - `backend/routers/marketing.py` — `POST /admin/upload-image` 엔드포인트 추가 (Google Drive)
  - `frontend/lib/api.ts` — `marketingApi.uploadImage()` 추가
  - `marketing/new/page.tsx`, `marketing/[id]/edit/page.tsx` — RichEditor + 썸네일 업로드 UI 적용
  - `board/[id]/page.tsx` — MarkdownContent 렌더링 + 썸네일 커버 이미지 + OG image 메타
  - `board/page.tsx` — 목록에 썸네일 이미지 표시

---

## 2026-04-21 세션 수정 완료 항목

- 공개 홈페이지 구현: `app/page.tsx` (homepage.txt 기반 React 변환) + `app/homepage.css`
- 미들웨어 `/` 경로 인증 게이트 제외
- 마케팅 게시물 시스템 신규 추가: `backend/routers/marketing.py` + `(main)/marketing/` 3개 페이지
- 사이드바에 관리자 전용 "마케팅" 메뉴 항목 추가
- CSS 격리: `homepage.css`의 `--radius` → `--hp-radius` (globals.css 충돌 방지)

---

## 2026-04-19 세션 수정 완료 항목

- `status: "정상"` → `"active"` 7개 행 수정 (list API 필터 통과 문제)
- F-4 EXTEND fee_rule `수수료 없음` → `인지세 6만원`
- F-5 영주 6개 항목 신규 추가 (F-5-1, F-5-2, F-5-6, F-5-10 동포영주, F-5-11, F-5-14)
- F-5-10 동포영주 체류기간 오류 수정: "5년" → "2년" (F-4 자격 기준)
- fee_rule 전수 정규화 (~110건): EXTEND 62건 → "기본 6만원", CHANGE 39건 → "기본 10만원", 등록증/재입국 형식 통일
- 실무지침 트리 탐색 아키텍처 변경: per-click lazy API → 마운트 시 전체 preload + 클라이언트 필터 (`allRows` 캐시)
