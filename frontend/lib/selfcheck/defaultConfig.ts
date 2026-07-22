import type { SelfCheckConfig, SelfCheckItem, SelfCheckBundle } from "./types";
import { TUBERCULOSIS_HIGH_RISK_COUNTRIES, TB_SOURCE_META } from "./tuberculosis";

// 공통기준 자가점검 — PDF 기준 3개 항목의 기본 설정(관리자 "PDF 기준 기본 항목 불러오기" 시드).
// 이 상수는 관리 설정일 뿐 사용자 답변과 무관하다. 게시(공개)는 관리자가 저장할 때만 반영된다.
//
// 적용 범위 안내(모든 항목 공통): 본 점검은 관리자 설정에 기재된 해당 사증·체류 업무
// 범위를 기준으로 하며, 구체적 제출 여부는 관할 출입국·외국인관서 또는 재외공관 기준을
// 확인해야 한다. 서로 다른 사증·체류 상황의 규칙을 하나로 무리하게 일반화하지 않는다.

const SCOPE_NOTICE =
  "본 점검은 관리자 설정에 기재된 해당 사증·체류 업무 범위를 기준으로 하며, " +
  "구체적 제출 여부는 관할 출입국·외국인관서 또는 재외공관 기준을 확인해야 합니다.";

// ── 1) 해외범죄경력증명 필요 확인 (CR-1.0) ──────────────────────────────────────
export const CRIMINAL_RECORD_CONFIG: SelfCheckConfig = {
  item_name: "해외범죄경력증명 필요 확인",
  logic_version: "CR-1.0",
  start_question_id: "q1",
  notice_text: SCOPE_NOTICE,
  questions: [
    { id: "q1", display_number: "①", text: "만 14세 이상입니까?", summary: "만 14세 이상", yes: "q2", no: "r_none", sort_order: 1 },
    { id: "q2", display_number: "②", text: "F-4 변경 또는 연장입니까?", summary: "F-4 변경·연장", yes: "q3", no: "q4", sort_order: 2 },
    { id: "q3", display_number: "③", text: "만 60세 이상입니까?", summary: "만 60세 이상", yes: "r_none", no: "q4", sort_order: 3 },
    { id: "q4", display_number: "④", text: "출입국·외국인관서에 해외범죄경력증명서를 제출한 적이 있습니까?", summary: "관서 제출 이력", help: "재외공관 제출은 제외합니다.", yes: "q5", no: "r_target", sort_order: 4 },
    { id: "q5", display_number: "⑤", text: "제출 이후 해외에서 계속하여 6개월 이상 체류했습니까?", summary: "제출 후 해외 6개월 이상", yes: "r_target", no: "r_none", sort_order: 5 },
  ],
  results: [
    { id: "r_target", item_name: "해외범죄경력증명", headline: "해외범죄경력증명 제출 대상입니다", label: "제출 대상", notice_text: null },
    { id: "r_none", item_name: "해외범죄경력증명", headline: "해외범죄경력증명 제출 대상이 아닙니다", label: "비대상", notice_text: null },
  ],
};

// ── 2) 결핵검진 필요 확인 (TB-1.0) ─────────────────────────────────────────────
// 국가 목록 = 법무부 결핵검사 의무화 대상국가(2020.4.1. 확대, 35개국) 공식 목록.
// source of truth 는 lib/selfcheck/tuberculosis.ts(TUBERCULOSIS_HIGH_RISK_COUNTRIES).
// 게시(공개)는 서버가 공식 35개국·출처 정보를 검증한 뒤에만 허용한다.
export const TUBERCULOSIS_CONFIG: SelfCheckConfig = {
  item_name: "결핵검진 필요 확인",
  logic_version: "TB-1.0",
  start_question_id: "q1",
  notice_text: SCOPE_NOTICE,
  country_list_title: "결핵 고위험 국가",
  country_list: [...TUBERCULOSIS_HIGH_RISK_COUNTRIES],
  country_list_source_title: TB_SOURCE_META.country_list_source_title,
  country_list_source_date: TB_SOURCE_META.country_list_source_date,
  country_list_verified_at: TB_SOURCE_META.country_list_verified_at,
  country_list_source_note: TB_SOURCE_META.country_list_source_note,
  questions: [
    { id: "q1", display_number: "①", text: "결핵 고위험 국가 국적입니까?", summary: "고위험국가 국적", country_list_ref: true, yes: "q2", no: "r_none", sort_order: 1 },
    { id: "q2", display_number: "②", text: "만 6세 이상입니까?", summary: "만 6세 이상", yes: "q3", no: "r_none", sort_order: 2 },
    { id: "q3", display_number: "③", text: "과거 결핵검진서를 제출한 적이 있습니까?", summary: "과거 검진서 제출 이력", yes: "q4", no: "r_target", sort_order: 3 },
    { id: "q4", display_number: "④", text: "결핵검진서 제출 또는 비자발급 이후 결핵 고위험 국가에서 계속하여 6개월 이상 체류했습니까?", summary: "제출·발급 후 고위험국 6개월 이상", yes: "r_target", no: "r_none", sort_order: 4 },
  ],
  results: [
    { id: "r_target", item_name: "결핵검진", headline: "결핵검진서 제출 대상입니다", label: "제출 대상", notice_text: null },
    { id: "r_none", item_name: "결핵검진", headline: "결핵검진서 제출 대상이 아닙니다", label: "비대상", notice_text: null },
  ],
};

// ── 3) 지문등록 필요 확인 (FP-1.0) ─────────────────────────────────────────────
export const FINGERPRINT_CONFIG: SelfCheckConfig = {
  item_name: "지문등록 필요 확인",
  logic_version: "FP-1.0",
  start_question_id: "q1",
  notice_text: SCOPE_NOTICE,
  questions: [
    { id: "q1", display_number: "①", text: "만 17세 이상입니까?", summary: "만 17세 이상", yes: "q2", no: "r_none", sort_order: 1 },
    { id: "q2", display_number: "②", text: "과거 외국인등록을 한 적이 있습니까?", summary: "과거 외국인등록 이력", yes: "r_principle_none", no: "r_target", sort_order: 2 },
  ],
  results: [
    { id: "r_target", item_name: "지문등록", headline: "지문등록 대상입니다", label: "등록 대상", notice_text: null },
    { id: "r_none", item_name: "지문등록", headline: "지문등록 대상이 아닙니다", label: "비대상", notice_text: null },
    { id: "r_principle_none", item_name: "지문등록", headline: "원칙적으로 지문등록 대상이 아닙니다", label: "원칙적 비대상", notice_text: "다만 경우에 따라 다시 요구될 수 있습니다." },
  ],
};

// PDF 기준 기본 항목(관리자 "불러오기" 시드). 안전을 위해 모두 비공개(draft)로 불러온다.
// 공개는 관리자가 내용을 검토하고 저장할 때만 반영된다(운영 반영은 별도 승인 단계).
export const PDF_DEFAULT_ITEMS: SelfCheckItem[] = [
  { item_id: "criminal-record", title: "해외범죄경력증명 필요 확인", description: SCOPE_NOTICE, sort_order: 1, is_published: false, popup_enabled: true, placement: ["home"], config: CRIMINAL_RECORD_CONFIG },
  { item_id: "tuberculosis", title: "결핵검진 필요 확인", description: "결핵 고위험 국가 공식 35개국 목록과 출처 확인이 완료된 항목입니다. 내용을 검토한 뒤 공개하세요.", sort_order: 2, is_published: false, popup_enabled: true, placement: ["home"], config: TUBERCULOSIS_CONFIG },
  { item_id: "fingerprint", title: "지문등록 필요 확인", description: SCOPE_NOTICE, sort_order: 3, is_published: false, popup_enabled: true, placement: ["home"], config: FINGERPRINT_CONFIG },
];

export const DEFAULT_SELF_CHECK_BUNDLE: SelfCheckBundle = {
  schema_version: 2,
  items: PDF_DEFAULT_ITEMS,
};

// 하위호환: 기존 코드가 단일 config 를 import 하던 경로. 편집기 초기값 등에서 사용.
export const DEFAULT_SELF_CHECK_CONFIG: SelfCheckConfig = CRIMINAL_RECORD_CONFIG;
