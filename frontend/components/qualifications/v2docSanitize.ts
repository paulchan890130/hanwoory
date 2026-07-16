// v2 실무지침 원본 JSON의 OCR 오염 표시 정제 유틸.
// 원본 데이터(JSON·API 응답 객체)는 절대 수정하지 않는다 — 표시 직전 복사본/표시값에만 적용.
// 서류·개요 정제(sanitizeV2RowForDisplay)는 qualifications [code] 페이지 전용(/guidelines 무영향).
// 단 sanitizeFeeRuleDisplay 는 /guidelines·/qualifications 양쪽 인지세 표시에 공용 — 두 화면의
// 수수료 표시값이 항상 동일해야 한다(오안내 방지).
import { GuidelineRow, V3DocRequirement } from "@/lib/api";

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

/** fee_rule 표시 직전 정제(원본 무수정).
 *  ① F-6 체류기간 연장: 표시값 "기본 6만원" → "3만원" (공식 기준 정정 — detailed_code가 F-6 계열이고
 *     업무가 체류기간 연장인 행에만 적용. 다른 자격의 연장 6만원, F-6의 변경 10만원·부여 4만원은 불변.)
 *  ② D-2·D-4 시간제취업(자격외활동 행): 표시값 → "2만원" (현행 공식 기준 — 면제/없음·"12만원(2만원
 *     가능)" 표기는 과거값. 비 D-2/D-4·다른 업무 미적용, v3 블록 수수료 2만원과 표시 통일.)
 *  ③ 페이지 참조 표기 제거("매뉴얼 p.39 마항" 류 — 수수료 안내 문구 자체는 유지). */
export function sanitizeFeeRuleDisplay(row: GuidelineRow): string {
  let fee = row.fee_rule ?? "";
  if (!fee.trim()) return fee;
  const code = row.detailed_code ?? "";
  const isD2D4PartTime =
    (code.startsWith("D-2") || code.startsWith("D-4")) &&
    (row.action_type === "EXTRA_WORK" || (row.major_action_std ?? "").includes("체류자격외"));
  if (isD2D4PartTime) {
    return "2만원";
  }
  const isF6Extend =
    code.startsWith("F-6") &&
    ((row.major_action_std ?? "").includes("연장") || row.action_type === "EXTEND");
  if (isF6Extend && fee.includes("기본 6만원")) {
    fee = fee.split("기본 6만원").join("3만원");
  }
  fee = fee
    .replace(/[,，]?\s*(?:매뉴얼\s*)?(?:p\.\s*\d+|페이지\s*\d+|\d+\s*페이지)(?:\s*[가-힣]항)?/g, "")
    .replace(/\(\s*\)/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  return fee;
}

// "|" 구분 서류 문자열: 쓰레기 pill 제거 + 오탈자 정제.
// "수수료" 단독 pill은 서류가 아니라 납부 항목 — qualifications 화면은 블록 수수료·인지세로
// 금액을 표시하므로 이중 표시 방지 차원에서 서류 목록에서는 숨긴다(원본 무수정).
function sanitizeDocList(s: string): string {
  return (s ?? "")
    .split("|")
    .map(t => t.trim())
    .filter(Boolean)
    .filter(t => t !== "수수료")
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
    fee_rule: sanitizeFeeRuleDisplay(row),
  };
}

// ── V2 → V3 준비서류 변환(지연 복제/표시용) ─────────────────────────────────────
// V3 document_requirements 가 아직 없는 업무에서, 연결된 V2 지침의 서류를 V3 준비서류
// UI(신청인/사무소/해당 시) 형식으로 "표시 직전" 변환한다. 저장(복제)은 관리자가 처음
// 편집할 때만 별도로 일어난다(page.tsx). 원문 문구는 그대로 보존한다.
//
// 분류 규칙:
//   - form_docs(사무소 준비서류)  → office
//   - supporting_docs(필요서류/신청인) → client
//   - 단, 항목 문구에 조건 표현("해당 시/해당자/필요한 경우/…인 경우/조건")이 있으면
//     출처와 무관하게 conditional("해당 시 추가서류")로 분류(안전한 기본값).

// 조건부 판정 마커. "경우"는 "…인 경우/…한 경우/…할 경우" 처럼 조건 문맥에서만 잡히도록
// 별도 정규식으로 처리하고, 그 밖엔 명시적 조건 문구만 매칭한다.
const _CONDITIONAL_MARKERS = ["해당 시", "해당시", "해당자", "해당하는", "해당되는", "필요한 경우", "필요시", "조건부"];
const _CASE_RE = /(?:인|한|할|된|되는|하는|일)\s*경우|경우에|경우 /;

export function isConditionalDocName(name: string): boolean {
  const s = name ?? "";
  if (_CONDITIONAL_MARKERS.some(m => s.includes(m))) return true;
  return _CASE_RE.test(s);
}

// 표시용 합성 V3DocRequirement 를 만든다(requirement_id 접두 "V2FB:" = 실제 V3 아님).
function _mkFallbackDoc(rowId: string, idx: number, name: string, role: "client" | "office" | "conditional"): V3DocRequirement {
  const conditional = role === "conditional";
  return {
    requirement_id: `V2FB:${rowId}:${idx}`,
    target_type: "",
    target_id: "",
    doc_name: name,
    doc_kind: "evidence",
    doc_role: role,
    condition: conditional ? name : null,
    is_required: !conditional,
    reuse_of: null,
    form_ref: null,
    confidence: "",
    notes: "",
    // 조건부는 원문을 그대로 조건 안내로도 노출(문구 손실 방지). 화면 DrRow 가 display_condition 사용.
    display_condition: conditional ? "해당하는 경우에만 준비합니다." : undefined,
  };
}

/**
 * 연결된 V2 행들(이미 sanitizeV2RowForDisplay 적용된 것을 넣을 것)을 V3 준비서류 형식으로 변환.
 * (doc_name, doc_role) 기준 중복 제거. V3 DR 이 하나도 없을 때만 fallback 으로 사용한다.
 */
export function v2RowsToFallbackDocs(rows: GuidelineRow[]): V3DocRequirement[] {
  const out: V3DocRequirement[] = [];
  const seen = new Set<string>();
  const push = (rowId: string, raw: string, srcRole: "office" | "client") => {
    for (const item of (raw ?? "").split("|").map(t => t.trim()).filter(Boolean)) {
      const role = isConditionalDocName(item) ? "conditional" : srcRole;
      const key = `${role}||${item}`;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(_mkFallbackDoc(rowId, out.length, item, role));
    }
  };
  for (const row of rows) {
    push(row.row_id, row.form_docs, "office");        // 사무소 준비서류
    push(row.row_id, row.supporting_docs, "client");  // 필요서류/신청인
  }
  return out;
}

/** 합성(V2 fallback) 준비서류인지 판정 — requirement_id 접두로 구분. */
export function isV2FallbackDoc(d: V3DocRequirement): boolean {
  return (d.requirement_id ?? "").startsWith("V2FB:");
}
