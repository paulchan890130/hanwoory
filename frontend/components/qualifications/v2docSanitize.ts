// v2 실무지침 원본 JSON의 OCR 오염 표시 정제 유틸 (qualifications 화면 전용).
// 원본 데이터(JSON·API 응답 객체)는 절대 수정하지 않는다 — 표시 직전 복사본에만 적용.
// /guidelines 화면에는 영향 없음 (qualifications [code] 페이지에서만 사용).
import { GuidelineRow } from "@/lib/api";

// 확정된 오탈자 치환표 — 배열 순서대로 적용한다(순서 의존: "결핵진 단서］" → "결핵진 단서" 등).
// ("즘함기관"은 정답 불명 — 치환하지 않음.)
const TYPO_REPLACEMENTS: [string, string][] = [
  ["사회틈합", "사회통합"],
  ["졸업증명세SNI", "졸업증명서(GNI"],
  ["G이", "GNI"],
  ["교건완화", "요건완화"],
  ["1 인담", "1인당"],
  ["듬기 부듬본", "등기부등본"],
  ["르통지서", "료통지서"],
  ["체류만 르", "체류만료"],
  ["체류만 료", "체류만료"],
  ["결랙", "결핵"],
  ["결핵진 단서］", "결핵진단서("],
  ["결핵진 단서", "결핵진단서"],
  ["결핵진 단 打", "결핵진단서("],
  ["국가메", "국가에"],
  ["연속으르", "연속으로"],
  ["무역전믄", "무역전문"],
  ["미수증", "이수증"],
  ["무역업고유번흐", "무역업고유번호"],
  ["해 담자", "해당자"],
  ["해담자", "해당자"],
  ["신청일기즌", "신청일기준"],
  ["트 픽", "토픽"],
  ["트픽", "토픽"],
  ["프르 그램", "프로그램"],
  ["즘합소득자", "종합소득자"],
  ["일욤근르", "일용근로"],
  ["일묨근로", "일용근로"],
  ["근르소득", "근로소득"],
  ["근르자", "근로자"],
  ["업므확인서", "업무확인서"],
  ["고믕계약서", "고용계약서"],
  ["고묨브험", "고용보험"],
  ["고묨비율", "고용비율"],
  ["지밤세", "지방세"],
  ["부가가치세과세표 즌", "부가가치세과세표준"],
  ["산업틈상자원부", "산업통상자원부"],
  ["즐 업자", "졸업자"],
  ["줌 택 1", "중 택 1"],
  ["1 년이내", "1년 이내"],
];

/** 오탈자 치환 + 전각괄호（）→ () 반각화. */
export function sanitizeV2DocText(s: string): string {
  let out = s ?? "";
  for (const [from, to] of TYPO_REPLACEMENTS) {
    out = out.split(from).join(to);
  }
  return out.split("（").join("(").split("）").join(")");
}

// 정상 중문 서류명 — 포함되어 있으면 쓰레기 판정 제외(户口本의 口 등 한자 오검 방지).
const CJK_DOC_WHITELIST = [
  "身份证", "户口本", "公证", "海牙认证", "无犯罪记录", "租借合同书", "合同人登陆证",
];

/**
 * OCR 쓰레기 pill 판정. true → 화면에서 제외.
 * 휴리스틱: (한글 완성형 글자 수)/(비공백 문자 수) < 0.3 이면서 라틴 낱자(1~2자) 토큰 3개 이상,
 * 또는 [口亠厂丁±] 포함. 단 정상 중문 서류명 whitelist 포함 시 false.
 */
export function isGarbageDocText(s: string): boolean {
  const t = (s ?? "").trim();
  if (!t) return false;
  if (CJK_DOC_WHITELIST.some(w => t.includes(w))) return false;
  if (/[口亠厂丁±]/.test(t)) return true;
  const nonSpace = t.replace(/\s+/g, "");
  if (nonSpace.length === 0) return false;
  const hangulCount = (nonSpace.match(/[가-힣]/g) ?? []).length;
  if (hangulCount / nonSpace.length >= 0.3) return false;
  const latinSingleTokens = t.split(/\s+/).filter(tok => /^[A-Za-z]{1,2}$/.test(tok)).length;
  return latinSingleTokens >= 3;
}

/** conflict 안내문 표시 직전 치환: "원문" → "기존 기준" (상시 노출 금지 문구 대응). */
export function sanitizeConflictText(s: string): string {
  return (s ?? "").split("원문").join("기존 기준");
}

/** na_reason 표시 직전 정제 — 내부 이력 표기 "(2026-07-08 확정)" 류 제거(데이터 무수정, 결론만 노출). */
export function sanitizeNaReasonDisplay(s: string): string {
  return (s ?? "").replace(/\s*\(\s*20\d{2}-\d{2}-\d{2}[^)]*\)\s*/g, "").trim();
}

// "|" 구분 서류 문자열: 쓰레기 pill 제거 + 오탈자 정제.
function sanitizeDocList(s: string): string {
  return (s ?? "")
    .split("|")
    .map(t => t.trim())
    .filter(Boolean)
    .filter(t => !isGarbageDocText(t))
    .map(sanitizeV2DocText)
    .join("|");
}

// 서류 목록 신뢰 불가로 확정된 v2 행 — 검수 완료 전까지 서류 표시를 차단한다(원본 데이터 무수정).
// v3 document_requirements 가 있으면 그쪽이 우선 표시되므로, 이 차단은 v2 fallback 표시에만 작용.
const DOC_BLOCKED_V2_ROWS = new Set([
  "M1-0233", "M1-0238", "M1-0242", "M1-0246", "M1-0250", "M1-0254", "M1-0257", "M1-0281",
  "M1-0123", "M1-0124",
]);

export const DOC_PENDING_NOTE = "제출서류 미정리 항목입니다. 검수 후 반영이 필요합니다.";

export function isDocBlockedV2Row(rowId: string): boolean {
  return DOC_BLOCKED_V2_ROWS.has(rowId);
}

/** v2 행 표시용 복사본 생성 — form_docs·supporting_docs·overview_short만 정제(원본 불변).
 *  서류 차단 행은 서류 목록을 비운다(카드 제목·업무명·설명은 유지). */
export function sanitizeV2RowForDisplay(row: GuidelineRow): GuidelineRow {
  const blocked = isDocBlockedV2Row(row.row_id);
  return {
    ...row,
    form_docs: blocked ? "" : sanitizeDocList(row.form_docs),
    supporting_docs: blocked ? "" : sanitizeDocList(row.supporting_docs),
    overview_short: sanitizeV2DocText(row.overview_short ?? ""),
  };
}
