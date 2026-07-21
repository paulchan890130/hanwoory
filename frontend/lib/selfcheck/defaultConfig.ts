import type { SelfCheckConfig } from "./types";

// 기본 자가점검 설정(CR-1.0) — 관리자가 아직 게시하지 않았을 때의 fallback 겸 시드.
// 결핵 검진 대상 예시: 첫 질문에서 고위험 국가 목록을 펼쳐 확인, 이후 분기.
// 이 상수는 관리 설정일 뿐 사용자 답변과 무관하다.
export const DEFAULT_SELF_CHECK_CONFIG: SelfCheckConfig = {
  item_name: "결핵 검진 대상 자가점검",
  logic_version: "CR-1.0",
  start_question_id: "q1",
  notice_text: "본 결과는 참고용이며 최종 판단은 관할 출입국·외국인관서 기준을 따릅니다.",
  country_list_title: "결핵 고위험 국가",
  country_list: [
    "네팔", "동티모르", "라오스", "러시아", "몽골", "미얀마", "방글라데시",
    "베트남", "인도", "인도네시아", "중국", "캄보디아", "키르기스스탄",
    "타지키스탄", "태국", "파키스탄", "필리핀",
  ],
  questions: [
    {
      id: "q1", display_number: "①", text: "결핵 고위험 국가 국적입니까?",
      summary: "고위험국가 국적", country_list_ref: true,
      yes: "q2", no: "r_none", sort_order: 1,
    },
    {
      id: "q2", display_number: "②", text: "90일을 초과하는 장기체류입니까?",
      summary: "90일 초과 장기체류",
      yes: "q3", no: "r_none", sort_order: 2,
    },
    {
      id: "q3", display_number: "③", text: "최근 6개월 이내 결핵검진 확인서 제출 이력이 있습니까?",
      summary: "6개월내 검진 제출이력",
      yes: "r_none", no: "r_target", sort_order: 3,
    },
  ],
  results: [
    {
      id: "r_target", item_name: "결핵 검진", headline: "결핵 검진 대상입니다",
      label: "검진 대상",
      notice_text: "지정 의료기관에서 결핵 검진 후 확인서를 제출하세요.",
    },
    {
      id: "r_none", item_name: "결핵 검진", headline: "검진 대상이 아닙니다",
      label: "비대상", notice_text: null,
    },
  ],
};
