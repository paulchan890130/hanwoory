// 공통기준 자가점검 — 관리용 설정 타입.
// 여기에는 "관리자 설정"만 담긴다. 사용자 답변/결과/경로는 이 타입에 존재하지 않으며
// 오직 컴포넌트의 React 메모리 state 로만 다룬다(서버/스토리지 저장 금지).

export type SelfCheckTarget = string; // question_id | result_id

export interface SelfCheckQuestion {
  id: string;
  display_number: string;   // "①" 등 표시용 번호
  text: string;             // 질문 문구
  summary: string;          // 답변 요약/문자에 쓰는 짧은 라벨
  help?: string | null;     // 선택 도움말
  country_list_ref?: boolean; // 결핵 고위험 국가 목록을 이 질문에서 펼침(첫 질문 전용 권장)
  yes: SelfCheckTarget;     // 예 → question_id | result_id
  no: SelfCheckTarget;      // 아니오 → question_id | result_id
  sort_order?: number;
}

export interface SelfCheckResult {
  id: string;
  item_name?: string | null; // 미지정 시 config.item_name 사용
  headline: string;          // 최종 판정(가장 크게)
  label?: string | null;     // 짧은 상태 라벨(문자용)
  notice_text?: string | null; // 결과별 주의문구(미지정 시 config.notice_text)
}

export interface SelfCheckConfig {
  item_name: string;
  logic_version: string;     // 예: "CR-1.0"
  start_question_id: string;
  notice_text?: string | null;
  country_list?: string[];   // 결핵 고위험 국가 목록(첫 질문에서만 표시)
  country_list_title?: string | null;
  questions: SelfCheckQuestion[];
  results: SelfCheckResult[];
}

// 관리 설정 + 공개여부(마케팅 저장 계층에서 관리).
export interface SelfCheckConfigEnvelope {
  published: boolean;
  config: SelfCheckConfig | null;
}

// 사용자 진행 중 메모리 state (저장 금지 — 참고용 타입).
export interface SelfCheckAnswer {
  question_id: string;
  display_number: string;
  summary: string;
  answer: "yes" | "no";
}
