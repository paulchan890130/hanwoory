// 매뉴얼 검토 — 규칙 기반 "자동 추천" 엔진 (표시/검토 보조 전용, 참고용).
// 화면 문구는 "자동 추천"으로 표기한다(외부 LLM 호출 아님 — 최종 판단은 관리자).
//
// ⚠ 이 모듈은 운영 manual_ref 반영(apply)·백엔드 분류(change_kind/needs_review)에
//    전혀 영향을 주지 않는다. 후보가 이미 가진 신호(change_kind / confidence /
//    similarity / page_changed / 페이지 / detailed_code / new_snippet / match_text)
//    만으로 "검토 완료 / 보류 / 무시" 중 하나를 추천하고 근거·신뢰도를 만든다.
//    외부 LLM 호출 없음 → 추가 env·네트워크·migration 불필요(현 상황에서 즉시 동작).

export type RecKind = "approve" | "hold" | "reject";
export type RecConfidence = "high" | "medium" | "low";

export interface RecResult {
  rec: RecKind;
  confidence: RecConfidence;
  reason: string;
}

// 추천 산출에 필요한 후보 필드(ManualReviewView 의 PgCandidate 와 호환되는 부분집합).
export interface RecCand {
  change_kind?: string;
  confidence?: string; // high | medium | review
  similarity?: number | null;
  page_changed?: boolean;
  old_page_from?: number | null;
  candidate_page_from?: number | null;
  detailed_code?: string;
  business_name?: string;
  new_snippet?: string;
  match_text?: string;
  reason?: string;
  manual_label?: string;
}

const MANUAL_KR: Record<string, string> = { visa: "사증", stay: "체류", revision_history: "개정이력" };
export function recManualKr(label?: string): string { return MANUAL_KR[label || ""] || (label || "-"); }

const KIND_KR: Record<string, string> = {
  new: "신규 추가", page_moved: "페이지 이동", text_changed: "본문 변경",
  uncertain: "매칭 불확실", noop: "실질 변경 없음",
};
export function recKindKr(kind?: string): string { return KIND_KR[kind || ""] || "본문 변경"; }

export const REC_KR: Record<RecKind, string> = { approve: "검토 완료", hold: "보류", reject: "무시" };
export const REC_CONF_KR: Record<RecConfidence, string> = { high: "높음", medium: "보통", low: "낮음" };

// 한국 체류자격 코드(A~H 계열) 추출. "p.108" / "2026" 같은 숫자는 앞 글자 매칭이 없어 제외된다.
const VISA_LETTERS = "ABCDEFGH";
export function extractStayCodes(text: string): string[] {
  const out = new Set<string>();
  // 세부코드(D-8-1)까지 포착. 'p.108' / '2026' 등 앞 글자 없는 숫자는 제외.
  const re = /\b([A-Z])-?(\d{1,2})(?:-(\d{1,2}))?\b/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) != null) {
    if (!VISA_LETTERS.includes(m[1])) continue;
    out.add(m[3] ? `${m[1]}-${m[2]}-${m[3]}` : `${m[1]}-${m[2]}`);
  }
  // 세부코드(D-8-1)가 있으면 같은 패밀리의 단독 코드(D-8)는 중복이므로 제거.
  const all = Array.from(out);
  const filtered = all.filter((c) => {
    const parts = c.split("-");
    if (parts.length !== 2) return true;           // 이미 세부코드면 유지
    return !all.some((o) => o !== c && o.startsWith(c + "-"));
  });
  return filtered.sort();
}

function groupText(cands: RecCand[]): string {
  return cands
    .map((c) => `${c.detailed_code ?? ""} ${c.business_name ?? ""} ${c.new_snippet ?? ""} ${c.match_text ?? ""} ${c.reason ?? ""}`)
    .join(" ");
}

// 그룹(=카드, 같은 페이지에 묶인 후보들)의 영향 대상.
export function affectedTargets(cands: RecCand[]): { codes: string[]; areas: string[] } {
  const codes = extractStayCodes(groupText(cands));
  const areas = Array.from(new Set(cands.map((c) => (c.business_name || "").trim()).filter(Boolean)));
  return { codes, areas };
}

function pct(sim: number | null | undefined): string | null {
  return typeof sim === "number" ? `${Math.round(sim * 100)}%` : null;
}

// 핵심: 그룹 1개(카드)에 대한 추천 산출. 첫 매칭 규칙이 이긴다(보수적 우선).
export function recommendGroup(cands: RecCand[]): RecResult {
  if (!cands.length) return { rec: "hold", confidence: "low", reason: "후보 정보가 없어 판단을 보류합니다." };
  const codes = extractStayCodes(groupText(cands));
  const candCount = cands.length;
  const kinds = new Set(cands.map((c) => c.change_kind || "text_changed"));
  const sims = cands.map((c) => c.similarity).filter((n): n is number => typeof n === "number");
  const minSim = sims.length ? Math.min(...sims) : null;
  const anyLowConf = cands.some((c) => (c.confidence || "") !== "high");
  const pageMovedOnly = Array.from(kinds).every((k) => k === "page_moved");
  const simP = pct(minSim);

  // C. 무시 추천 — 본문은 거의 동일하고 페이지 위치만 이동(목차/페이지번호 이동 가능성).
  if (pageMovedOnly && minSim != null && minSim >= 0.95) {
    return {
      rec: "reject", confidence: "high",
      reason: `본문이 거의 동일(유사도 ${simP})하고 페이지 위치만 이동했습니다. 목차·페이지 번호 이동일 가능성이 높아 이번 변경에서 제외(무시)를 추천합니다.`,
    };
  }
  // B. 보류 추천 — 서로 다른 체류자격이 한 페이지에 섞여 있음(예: D-7 / D-8-1).
  if (codes.length >= 2) {
    return {
      rec: "hold", confidence: "low",
      reason: `서로 다른 체류자격(${codes.join(", ")})이 한 페이지에 섞여 있어 어느 항목의 변경인지 자동 매칭만으로 단정하기 어렵습니다. 수동 페이지·항목 검증 후 결정을 추천합니다.`,
    };
  }
  // B. 보류 — 후보가 2건 이상(어느 항목의 변경인지 모호).
  if (candCount >= 2) {
    return {
      rec: "hold", confidence: "low",
      reason: `이 페이지에 ${candCount}개 항목이 함께 매칭되어 어떤 항목의 변경인지 모호합니다. 개별 항목을 펼쳐 확인 후 결정을 추천합니다.`,
    };
  }
  // B. 보류 — 자동 매칭 불확실.
  if (kinds.has("uncertain")) {
    return {
      rec: "hold", confidence: "low",
      reason: `자동 매칭이 '불확실'로 분류되었습니다. 후보 페이지가 실제 변경 위치와 일치하는지 확인이 필요합니다.`,
    };
  }
  // B. 보류 — 본문 유사도가 낮아 매칭이 어긋났거나 추출이 깨졌을 수 있음.
  if (minSim != null && minSim < 0.6) {
    return {
      rec: "hold", confidence: "medium",
      reason: `기존↔후보 본문 유사도가 낮아(${simP}) 매칭이 어긋났거나 본문 추출이 깨졌을 수 있습니다. 본문·PDF 확인 후 결정을 추천합니다.`,
    };
  }
  // B. 보류 — 신규 추가 페이지(기존 항목과의 연결 확인 필요).
  if (kinds.has("new")) {
    return {
      rec: "hold", confidence: "medium",
      reason: `신규 추가된 페이지로 보입니다. 기존 항목과의 연결(페이지 범위)이 정확한지 확인 후 결정을 추천합니다.`,
    };
  }
  // B. 보류 — 페이지 매칭 신뢰도가 '높음'이 아님.
  if (anyLowConf) {
    return {
      rec: "hold", confidence: "medium",
      reason: `페이지 매칭 신뢰도가 '높음'이 아닙니다. 후보 페이지를 확인 후 결정을 추천합니다.`,
    };
  }
  // A. 검토 완료 추천 — 단일 항목·높은 신뢰도·동일 체류자격의 명확한 본문 변경.
  return {
    rec: "approve", confidence: "high",
    reason: `단일 항목·높은 신뢰도·동일 체류자격의 명확한 본문 변경입니다${simP ? ` (유사도 ${simP})` : ""}. 운영 반영 대상으로 검토 완료를 추천합니다.`,
  };
}

// 그룹(카드) 변경 요약 — 1~2줄, 사람이 읽는 문장. (개발자 diff 가 아닌 실무자용)
export function summarizeGroup(g: {
  manual_label?: string; old_from?: number | null; old_to?: number | null;
  new_from?: number | null; new_to?: number | null; change_kind: string;
  cands: RecCand[]; summary?: string;
}): string {
  const { codes } = affectedTargets(g.cands);
  const moved = g.old_from !== g.new_from;
  const pageStr = `p.${g.old_from}${g.old_to && g.old_to !== g.old_from ? `-${g.old_to}` : ""}` +
    (moved ? ` → p.${g.new_from}${g.new_to && g.new_to !== g.new_from ? `-${g.new_to}` : ""}` : "");
  const snippet = (g.summary || "").trim().replace(/\s+/g, " ").slice(0, 90);
  const parts = [`${recManualKr(g.manual_label)} ${pageStr} 구간에서 ${recKindKr(g.change_kind)}이 감지되었습니다.`];
  if (codes.length) parts.push(`영향 체류자격: ${codes.join(", ")}.`);
  if (snippet) parts.push(`주요 내용: “${snippet}…”`);
  return parts.join(" ");
}

// 판단 포인트 — 추천 근거에 따라 "확인할 점" 체크리스트를 만든다.
export function judgmentPoints(g: {
  old_from?: number | null; new_from?: number | null; change_kind: string; cands: RecCand[];
}, rec: RecResult): string[] {
  const { codes } = affectedTargets(g.cands);
  const pts: string[] = [];
  if (codes.length >= 2) pts.push(`서로 다른 체류자격(${codes.join(", ")})이 잘못 매칭된 것은 아닌지`);
  if (g.cands.length >= 2) pts.push(`${g.cands.length}개 후보 중 실제로 바뀐 항목이 무엇인지`);
  if (g.old_from !== g.new_from || g.change_kind === "page_moved") pts.push("자동 페이지 매칭이 정확한지");
  if (g.change_kind === "new") pts.push("이 신규 내용이 기존 항목에 추가된 것인지, 별개 항목인지");
  pts.push("첨부서류·자격요건 등 실제 본문 내용이 바뀌었는지");
  if (rec.rec === "reject") pts.push("정말 목차/페이지 이동뿐이고 본문 변경이 없는지");
  return pts;
}
