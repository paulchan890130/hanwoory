/**
 * 출입국 실무지침 DB - Node.js 클라이언트 유틸
 * FastAPI 서버(immigration_api.py)와 연동
 *
 * 사용법:
 *   const db = require('./immigration_client');
 *   const results = await db.searchByCode('F-4');
 *   const detail  = await db.getGuideline('M1-0001');
 */

const BASE_URL = process.env.IMMIGRATION_API_URL || 'http://localhost:8000';

/** GET 요청 공통 */
async function apiGet(path, params = {}) {
  const url = new URL(BASE_URL + path);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null) url.searchParams.set(k, v);
  });
  const res = await fetch(url.toString());
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(`[ImmigrationDB] ${res.status} ${path}: ${err.detail || res.statusText}`);
  }
  return res.json();
}

// ── 핵심 API ──────────────────────────────────────────────────

/**
 * 체류자격 코드로 관련 업무 전체 조회
 * @param {string} code - 예: 'F-4', 'E-7', 'D-2-1'
 */
async function searchByCode(code) {
  return apiGet(`/api/v2/guidelines/code/${encodeURIComponent(code)}`);
}

/**
 * row_id로 단건 상세 조회 (관련 rules, exceptions 포함)
 * @param {string} rowId - 예: 'M1-0001'
 */
async function getGuideline(rowId) {
  return apiGet(`/api/v2/guidelines/${encodeURIComponent(rowId)}`);
}

/**
 * 키워드 검색
 * @param {string} query - 검색어 (코드/업무명/서류명)
 * @param {object} opts  - { action_type, domain, page, limit }
 */
async function search(query, opts = {}) {
  return apiGet('/api/v2/guidelines/search/query', { q: query, ...opts });
}

/**
 * 업무유형(action_type)별 목록
 * @param {string} actionType - CHANGE|EXTEND|EXTRA_WORK|WORKPLACE|REGISTRATION|REENTRY|GRANT|VISA_CONFIRM
 * @param {object} opts       - { domain, page, limit }
 */
async function listByActionType(actionType, opts = {}) {
  return apiGet('/api/v2/guidelines', { action_type: actionType, status: 'active', ...opts });
}

/**
 * 서류 신청 패키지 조회
 * code + actionType 으로 form_docs / supporting_docs 추출
 * @returns {{ form_docs: string[], supporting_docs: string[], row_id: string, fee_rule: string }}
 */
async function getDocPackage(code, actionType) {
  const res = await searchByCode(code);
  const row = res.data.find(r => r.action_type === actionType);
  if (!row) return null;
  const split = s => s ? s.split('|').map(x => x.trim()).filter(Boolean) : [];
  return {
    row_id: row.row_id,
    code: row.detailed_code,
    action_type: row.action_type,
    overview: row.overview_short,
    form_docs: split(row.form_docs),       // 작성서류
    supporting_docs: split(row.supporting_docs), // 첨부서류
    fee_rule: row.fee_rule,
    exceptions_summary: row.exceptions_summary,
  };
}

/**
 * 공통 규칙 조회
 * @param {string} ruleType - DocPolicy|ActionTemplate|FeeTemplate|FeeOverride|StatusTemplate
 */
async function getRules(ruleType) {
  return apiGet('/api/v2/rules', { rule_type: ruleType });
}

/**
 * 예외 분기 조회
 * @param {string} code  - 체류자격 코드 (부분일치)
 * @param {string} major - 업무대분류
 */
async function getExceptions(code, major) {
  return apiGet('/api/v2/exceptions', {
    applies_to_code: code,
    applies_to_major: major,
  });
}

/**
 * 서류명 표준화 조회
 * @param {string} name - 서류명 (부분일치)
 */
async function lookupDoc(name) {
  return apiGet('/api/v2/docs/lookup', { name });
}

/** DB 통계 */
async function getStats() {
  return apiGet('/api/v2/stats');
}

// ── 사용 예시 (직접 실행 시) ──────────────────────────────────
if (require.main === module) {
  (async () => {
    console.log('\n=== F-4 체류자격변경 서류패키지 ===');
    const pkg = await getDocPackage('F-4', 'CHANGE');
    if (pkg) {
      console.log('작성서류:', pkg.form_docs);
      console.log('첨부서류:', pkg.supporting_docs);
      console.log('수수료:', pkg.fee_rule);
    }

    console.log('\n=== "통합신청서" 검색 ===');
    const res = await search('통합신청서', { limit: 5 });
    console.log(`총 ${res.total}건 중 ${res.data.length}건 표시`);
    res.data.forEach(r => console.log(` - ${r.row_id} | ${r.detailed_code} | ${r.action_type}`));

    console.log('\n=== DB 통계 ===');
    const st = await getStats();
    console.log(st);
  })().catch(console.error);
}

module.exports = {
  searchByCode,
  getGuideline,
  search,
  listByActionType,
  getDocPackage,
  getRules,
  getExceptions,
  lookupDoc,
  getStats,
};
