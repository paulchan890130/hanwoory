/**
 * 출입국 실무지침 DB — 로컬 서버 전용 클라이언트
 *
 * [기존 구글 드라이브 방식에서 로컬 서버 방식으로 전환]
 *
 * 교체 방법:
 *   기존: const db = require('./구글드라이브_연동모듈');
 *   변경: const db = require('./immigration_client_local');
 *
 * 서버 주소 설정 (.env 파일 또는 환경변수):
 *   IMMIGRATION_API_URL=http://192.168.x.x:8000   ← 서버 컴퓨터 내부 IP
 *   (같은 와이파이 환경에서는 이것만 설정하면 됩니다)
 */

// ── 서버 주소 설정 ────────────────────────────────────────────
// 우선순위: 환경변수 → 기본값(로컬호스트)
const 서버주소 = process.env.IMMIGRATION_API_URL || 'http://localhost:8000';

// ── 내부 요청 함수 ────────────────────────────────────────────
async function 조회(경로, 파라미터 = {}) {
  const url = new URL(서버주소 + 경로);
  Object.entries(파라미터).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') {
      url.searchParams.set(k, v);
    }
  });

  let res;
  try {
    res = await fetch(url.toString());
  } catch (err) {
    throw new Error(
      `[실무지침 서버 연결 실패] 서버가 실행 중인지 확인하세요.\n주소: ${url}\n원인: ${err.message}`
    );
  }

  if (!res.ok) {
    const 오류 = await res.json().catch(() => ({}));
    throw new Error(`[실무지침 서버 오류] ${res.status} — ${오류.detail || res.statusText}`);
  }

  return res.json();
}

// ══════════════════════════════════════════════════════════════
// 핵심 조회 함수
// ══════════════════════════════════════════════════════════════

/**
 * 체류자격 코드로 관련 업무 전체 조회
 * @param {string} 코드 - 예: 'F-4', 'E-7', 'D-2'
 * @returns {{ count, action_types, data: 업무[] }}
 */
async function 코드로조회(코드) {
  return 조회(`/api/v2/guidelines/code/${encodeURIComponent(코드)}`);
}

/**
 * 업무유형 + 체류자격 코드로 서류 패키지 조회
 * 가장 자주 사용하는 함수
 *
 * @param {string} 코드        - 예: 'F-4'
 * @param {string} 업무유형    - 'CHANGE'|'EXTEND'|'EXTRA_WORK'|'REGISTRATION'|'REENTRY'|'GRANT'|'VISA_CONFIRM'
 * @returns {{ 작성서류: string[], 첨부서류: string[], 인지세: string, 예외사항: string }}
 */
async function 서류패키지(코드, 업무유형) {
  const 결과 = await 코드로조회(코드);
  const 업무 = 결과.data.find(r => r.action_type === 업무유형);
  if (!업무) return null;

  const 분리 = str => str ? str.split('|').map(x => x.trim()).filter(Boolean) : [];

  return {
    체류자격코드: 업무.detailed_code,
    업무명: 업무.business_name,
    업무유형: 업무.action_type,
    개요: 업무.overview_short,
    작성서류: 분리(업무.form_docs),       // 업체 준비
    첨부서류: 분리(업무.supporting_docs), // 고객 준비
    인지세: 업무.fee_rule,
    예외사항: 업무.exceptions_summary,
    근거: 업무.basis_section,
  };
}

/**
 * 키워드 검색
 * @param {string} 검색어
 * @param {{ 업무유형?: string, 페이지?: number, 개수?: number }} 옵션
 */
async function 검색(검색어, 옵션 = {}) {
  return 조회('/api/v2/guidelines/search/query', {
    q: 검색어,
    action_type: 옵션.업무유형,
    page: 옵션.페이지 || 1,
    limit: 옵션.개수 || 20,
  });
}

/**
 * 업무유형별 전체 목록
 * @param {string} 업무유형 - 'CHANGE'|'EXTEND'|'EXTRA_WORK' 등
 */
async function 업무유형별목록(업무유형, 옵션 = {}) {
  return 조회('/api/v2/guidelines', {
    action_type: 업무유형,
    status: 'active',
    page: 옵션.페이지 || 1,
    limit: 옵션.개수 || 50,
  });
}

/**
 * 예외 조건 조회
 * @param {string} 코드  - 체류자격 코드
 * @param {string} 업무  - 업무대분류명
 */
async function 예외조건(코드, 업무) {
  return 조회('/api/v2/exceptions', {
    applies_to_code: 코드,
    applies_to_major: 업무,
  });
}

/**
 * 서류명 표준화 조회
 * @param {string} 서류명 - 부분 일치 검색
 */
async function 서류명조회(서류명) {
  return 조회('/api/v2/docs/lookup', { name: 서류명 });
}

/** 서버 상태 및 통계 확인 */
async function 서버상태() {
  return 조회('/api/v2/stats');
}

/** 서버 연결 테스트 (시스템 시작 시 호출 권장) */
async function 연결확인() {
  try {
    const 결과 = await 조회('/');
    console.log(`[실무지침 서버 연결 성공] 업무항목 ${결과.master_rows}건 로드됨`);
    return true;
  } catch (err) {
    console.error(err.message);
    return false;
  }
}

// ══════════════════════════════════════════════════════════════
// 사용 예시 (node immigration_client_local.js 로 직접 실행 시)
// ══════════════════════════════════════════════════════════════
if (require.main === module) {
  (async () => {
    console.log('=== 서버 연결 확인 ===');
    await 연결확인();

    console.log('\n=== F-4 체류자격 변경 서류패키지 ===');
    const pkg = await 서류패키지('F-4', 'CHANGE');
    if (pkg) {
      console.log('작성서류 (업체 준비):');
      pkg.작성서류.forEach(s => console.log('  -', s));
      console.log('첨부서류 (고객 준비):');
      pkg.첨부서류.forEach(s => console.log('  -', s));
      console.log('인지세:', pkg.인지세);
    }

    console.log('\n=== E-7 관련 업무 목록 ===');
    const e7 = await 코드로조회('E-7');
    console.log(`총 ${e7.count}건:`, e7.action_types);
  })().catch(console.error);
}

module.exports = {
  코드로조회,
  서류패키지,
  검색,
  업무유형별목록,
  예외조건,
  서류명조회,
  서버상태,
  연결확인,
};
