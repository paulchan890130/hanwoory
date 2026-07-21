// 공통기준 자가점검 — 순수 로직(부작용 없음, 메모리 전용).
// 그래프 무결성 검증 + 답변요약/경로/전체로직 생성. 네트워크·스토리지 접근 없음.
import type { SelfCheckConfig, SelfCheckQuestion, SelfCheckResult, SelfCheckAnswer } from "./types";

export function getQuestion(cfg: SelfCheckConfig, id: string): SelfCheckQuestion | undefined {
  return cfg.questions.find((q) => q.id === id);
}
export function getResult(cfg: SelfCheckConfig, id: string): SelfCheckResult | undefined {
  return cfg.results.find((r) => r.id === id);
}
export function isResultId(cfg: SelfCheckConfig, id: string): boolean {
  return cfg.results.some((r) => r.id === id);
}
export function isQuestionId(cfg: SelfCheckConfig, id: string): boolean {
  return cfg.questions.some((q) => q.id === id);
}

export interface ValidationReport {
  errors: string[];
  warnings: string[];
}

// 그래프 무결성 검증 — 저장/게시 전 사용(서버·클라이언트 공통 개념).
export function validateConfig(cfg: SelfCheckConfig | null | undefined, forPublish = false): ValidationReport {
  const errors: string[] = [];
  const warnings: string[] = [];
  if (!cfg) return { errors: ["설정이 비어 있습니다."], warnings };

  // 중복 id
  const qids = cfg.questions.map((q) => q.id);
  const rids = cfg.results.map((r) => r.id);
  const dupQ = qids.filter((v, i) => qids.indexOf(v) !== i);
  const dupR = rids.filter((v, i) => rids.indexOf(v) !== i);
  if (dupQ.length) errors.push(`중복 question_id: ${Array.from(new Set(dupQ)).join(", ")}`);
  if (dupR.length) errors.push(`중복 result_id: ${Array.from(new Set(dupR)).join(", ")}`);
  const idSet = new Set<string>([...qids, ...rids]);
  const dupCross = qids.filter((q) => rids.includes(q));
  if (dupCross.length) errors.push(`question/result id 충돌: ${dupCross.join(", ")}`);

  if (!cfg.logic_version || !cfg.logic_version.trim()) errors.push("로직 버전이 없습니다.");
  if (!cfg.results.length) errors.push("결과가 하나도 없습니다.");

  // 존재하지 않는 target
  for (const q of cfg.questions) {
    for (const [br, tgt] of [["예", q.yes], ["아니오", q.no]] as const) {
      if (!tgt || !idSet.has(tgt)) errors.push(`질문 ${q.id}의 '${br}' 대상(${tgt || "없음"})이 존재하지 않습니다.`);
    }
  }

  // 시작 질문
  const start = cfg.start_question_id;
  if (!start || !isQuestionId(cfg, start)) {
    errors.push("시작 질문이 없거나 유효하지 않습니다.");
    return { errors, warnings }; // 시작이 없으면 도달성/순환 분석 불가
  }

  // 순환 감지 + 도달성 (DFS 컬러링). target 이 이미 검증 실패면 스킵.
  const color: Record<string, number> = {}; // 0 white,1 gray,2 black
  const reachableQ = new Set<string>();
  const reachableR = new Set<string>();
  let cycle = false;
  const dfs = (id: string) => {
    if (isResultId(cfg, id)) { reachableR.add(id); return; }
    const q = getQuestion(cfg, id);
    if (!q) return;
    if (color[id] === 1) { cycle = true; return; }
    if (color[id] === 2) return;
    color[id] = 1;
    reachableQ.add(id);
    if (q.yes && idSet.has(q.yes)) dfs(q.yes);
    if (q.no && idSet.has(q.no)) dfs(q.no);
    color[id] = 2;
  };
  dfs(start);
  if (cycle) errors.push("질문 순환(loop)이 감지되었습니다. 모든 경로가 결과로 끝나야 합니다.");

  // 도달 불가 경고
  for (const q of cfg.questions) if (!reachableQ.has(q.id)) warnings.push(`도달 불가능한 질문: ${q.id}`);
  for (const r of cfg.results) if (!reachableR.has(r.id)) warnings.push(`도달 불가능한 결과: ${r.id}`);
  if (!cycle && reachableR.size === 0) errors.push("어떤 경로에서도 결과에 도달하지 못합니다.");

  if (forPublish && errors.length === 0) {
    // 게시 시 추가 무결성(치명): 이미 위에서 대부분 커버.
  }
  return { errors, warnings };
}

// 전체 판정 로직(그래프의 압축 표현) — 사용자 답변과 무관. 저장/캐시 가능.
export function buildFullLogic(cfg: SelfCheckConfig): string[] {
  const label = (tgt: string): string => {
    const r = getResult(cfg, tgt);
    if (r) return r.label || r.headline;
    const q = getQuestion(cfg, tgt);
    return q ? q.display_number : tgt;
  };
  return [...cfg.questions]
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
    .map((q) => `${q.display_number} ${q.summary}: 예→${label(q.yes)} / 아니오→${label(q.no)}`);
}

// 사용자 실제 답변 요약(메모리 answers 로만 생성).
export function buildAnswerLines(answers: SelfCheckAnswer[]): string[] {
  return answers.map((a) => `${a.display_number} ${a.summary}: ${a.answer === "yes" ? "예" : "아니오"}`);
}

// 사용자 실제 경로: "① 예 → ② 아니오 → 검진 대상".
export function buildPathLine(cfg: SelfCheckConfig, answers: SelfCheckAnswer[], resultId: string | null): string {
  const steps = answers.map((a) => `${a.display_number} ${a.answer === "yes" ? "예" : "아니오"}`);
  const r = resultId ? getResult(cfg, resultId) : null;
  if (r) steps.push(r.label || r.headline);
  return steps.join(" → ");
}

// 다음 스텝 계산(순수). 반환 target 이 result 면 {result}, question 이면 {question}.
export function nextStep(cfg: SelfCheckConfig, questionId: string, answer: "yes" | "no"):
  { kind: "question"; id: string } | { kind: "result"; id: string } | { kind: "invalid" } {
  const q = getQuestion(cfg, questionId);
  if (!q) return { kind: "invalid" };
  const tgt = answer === "yes" ? q.yes : q.no;
  if (isResultId(cfg, tgt)) return { kind: "result", id: tgt };
  if (isQuestionId(cfg, tgt)) return { kind: "question", id: tgt };
  return { kind: "invalid" };
}
