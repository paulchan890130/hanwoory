// 체류자격(비자) 코드 공통 정의 — 문서자동작성 / 고객관리 / OCR 스캔에서 공유.
//
// 저장값은 code 중심("F-4", "H-2", "E-7", "D-2" …)을 권장하되, 알 수 없는 기존
// 입력값은 절대 버리지 않는다(직접입력으로 보존). normalize 는 읽기 전용이며
// 기존 고객 데이터를 일괄 변환하지 않는다.

export interface VisaOption {
  code: string;   // 저장/매핑 기준 코드 (canonical)
  label: string;  // 화면 표시용 (코드 + 한글 병기)
}

// 실무에서 자주 쓰는 체류자격 — 필요 시 추가만 하면 됨(삭제는 호환성 주의).
export const VISA_STATUS_OPTIONS: VisaOption[] = [
  { code: "D-2",  label: "D-2 (유학)" },
  { code: "D-4",  label: "D-4 (일반연수)" },
  { code: "D-8",  label: "D-8 (기업투자)" },
  { code: "D-10", label: "D-10 (구직)" },
  { code: "E-7",  label: "E-7 (특정활동)" },
  { code: "E-9",  label: "E-9 (비전문취업)" },
  { code: "F-1",  label: "F-1 (방문동거)" },
  { code: "F-2",  label: "F-2 (거주)" },
  { code: "F-3",  label: "F-3 (동반)" },
  { code: "F-4",  label: "F-4 (재외동포)" },
  { code: "F-5",  label: "F-5 (영주)" },
  { code: "F-6",  label: "F-6 (결혼이민)" },
  { code: "H-2",  label: "H-2 (방문취업)" },
  { code: "G-1",  label: "G-1 (기타)" },
];

const VISA_CODE_SET = new Set(VISA_STATUS_OPTIONS.map((o) => o.code));

// 한글 명칭 → 코드 (대표 명칭만; 부분 일치 흡수)
const NAME_ALIASES: { kw: string; code: string }[] = [
  { kw: "재외동포", code: "F-4" },
  { kw: "방문취업", code: "H-2" },
  { kw: "영주",     code: "F-5" },
  { kw: "결혼이민", code: "F-6" },
  { kw: "거주",     code: "F-2" },
  { kw: "유학",     code: "D-2" },
  { kw: "구직",     code: "D-10" },
  { kw: "비전문취업", code: "E-9" },
  { kw: "특정활동", code: "E-7" },
];

/**
 * 입력 문자열을 표준 비자 코드로 정규화한다.
 * - "F4" / "f-4" / "F - 4" → "F-4"
 * - "F-4 재외동포" → "F-4" (코드가 앞에 있으면 코드 우선)
 * - "재외동포" → "F-4"
 * - 공백/빈값 → ""
 * - 인식 불가 → 입력값 trim 그대로 보존(삭제 금지)
 */
export function normalizeVisaCode(raw: string | null | undefined): string {
  if (raw == null) return "";
  const s = String(raw).trim();
  if (!s) return "";

  // 1) 코드 패턴(영문 1글자 + 숫자) 먼저 추출 — "F-4 재외동포" 같은 병기 흡수
  const m = s.toUpperCase().match(/\b([A-Z])\s*-?\s*(\d{1,2})\b/);
  if (m) {
    const code = `${m[1]}-${m[2]}`;
    return code;
  }

  // 2) 한글 명칭 별칭
  for (const a of NAME_ALIASES) {
    if (s.includes(a.kw)) return a.code;
  }

  // 3) 인식 불가 → 원문 보존
  return s;
}

/** 정규화 후 표준 옵션 목록에 존재하는 코드인지 */
export function isKnownVisaCode(raw: string | null | undefined): boolean {
  const c = normalizeVisaCode(raw);
  return !!c && VISA_CODE_SET.has(c);
}

export interface ExtensionWorktype {
  category: string;  // 항상 "체류"
  minwon: string;    // 항상 "연장"
  kind: string;      // 문서자동작성 종류 vocab: "F" | "H2" | "E7" | "D" | (그외)
  detail: string;    // 세부: F/D 는 숫자, 그외 ""
  matched: boolean;  // 비자 코드를 파싱했는지(최종 유효성은 트리로 재검증)
}

/**
 * 고객 체류자격 → 문서자동작성 "체류기간 연장" 선택값 매핑.
 * kind/detail 는 문서자동작성의 어휘로 변환하되, 실제 유효성(연장 트리에 존재하는지)은
 * QuickDocPanel 이 서버 tree 로 재검증한다. 매칭 불가 시 category/민원만 세팅하고 안내.
 */
export function visaToExtensionWorktype(raw: string | null | undefined): ExtensionWorktype {
  const base = { category: "체류", minwon: "연장" };
  const code = normalizeVisaCode(raw);
  const m = code.match(/^([A-Z])-(\d{1,2})$/);
  if (!m) return { ...base, kind: "", detail: "", matched: false };

  const letter = m[1];
  const num = m[2];
  let kind: string;
  if (letter === "F") kind = "F";
  else if (letter === "H" && num === "2") kind = "H2";
  else if (letter === "E" && num === "7") kind = "E7";
  else if (letter === "D") kind = "D";
  else kind = `${letter}${num}`; // 연장 트리에 없을 가능성 — 재검증에서 안내 처리

  const detail = kind === "F" || kind === "D" ? num : "";
  return { ...base, kind, detail, matched: true };
}
