# Codebase Audit — 공통기준 자가점검 (privacy-first)

작업 branch: `feat/common-criteria-self-check` · 기준 SHA `ba317641`.

## 실측 결과
- 기존 "공통기준 자가점검" 유사 기능 **없음**(신규 기능).
- 마케팅 관리 구조: `MarketingPost`(id/title/slug/category/**content**(Text)/is_published…) + `marketing_pg_service.upsert_post`(고정 id 허용) + 마케팅 라우터 admin CRUD. → **설정 저장에 재사용 적합**.
- 공개 노출: `/`(HomeClient, force-dynamic) + `/board` 등. 모달 CSS(`hw-modal`), toast(sonner), 아이콘(lucide-react), 클립보드 helper 부재(신규), 저장소(localStorage 등) 자가점검 관련 사용 없음.

## 재사용 구조
- **저장**: `marketing_pg_service.upsert_post`/`get_post`(마케팅 테이블, 고정 id `common-criteria-self-check`) → **신규 테이블/migration 없음**(alembic head 불변 `a1b2c3d40031`).
- **권한**: `require_admin`(관리 저장). 공개 조회는 무인증 GET.
- UI: sonner toast, lucide-react 아이콘, 골드 디자인 토큰, `hw-card`/버튼 스타일.

## 제거 대상(사용자 결과 저장 경로)
- 없음 — 신규 기능이며 애초에 사용자 답변/결과 저장 endpoint 를 **만들지 않았다**. 서버에는 `GET /api/self-check/config`(공개, 게시설정만) + `GET/PUT /api/self-check/admin/config`(관리)만 존재. 답변/결과/경로 제출 API 부재(테스트로 강제).

## 신규 구현
- 프론트: `lib/selfcheck/{types,defaultConfig,logic,sms}.ts`, `components/selfcheck/{CommonCriteriaSelfCheck,SelfCheckLauncher,SelfCheckAdminEditor}.tsx`, `app/(main)/marketing/self-check/page.tsx`, HomeClient 진입 버튼.
- 백엔드: `routers/self_check.py`(설정 저장/조회 + 그래프 검증), main.py 등록.
- 테스트: `backend/tests/test_self_check.py`(검증/무-답변-endpoint), `frontend/e2e/self-check.spec.ts`(Playwright).

## 개인정보 전송 가능 지점 / 차단
- 진행 중 유일한 네트워크는 **설정 GET 1회**. 답변/결과/경로는 React state 로만 존재.
- 저장소 미사용(localStorage/sessionStorage/cookie/IndexedDB). bfcache/pathname/unmount/닫기/다시 시 reset.
- 문자 본문은 프론트 메모리 생성, 자동전송 없음(`sms:` + clipboard). 서버·로그·analytics 미전송. E2E 로 검증.

## 마이그레이션 필요 여부
- **불필요**. 마케팅 저장 계층 재사용, 파괴적 변경 없음.

## 모바일 한 화면 위험 / 대응
- 결과 패널 100dvh grid + clamp() 사이즈 + 배경 스크롤 잠금. 관리자 길이 카운터/경고로 overflow 예방. 360×740~412×915 Playwright 무스크롤 검증.
