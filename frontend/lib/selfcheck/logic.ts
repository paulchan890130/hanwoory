// 공통기준 자가점검 — 순수 로직(부작용 없음, 메모리 전용).
// 그래프 무결성 검증 + 답변요약/경로/전체로직 생성. 네트워크·스토리지 접근 없음.
import type { SelfCheckConfig, SelfCheckQuestion, SelfCheckResult, SelfCheckAnswer, SelfCheckItem, SelfCheckBundle } from "./types";

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

// ── 다중 항목 번들 helpers ────────────────────────────────────────────────────
// 저장 content 가 (a) v2 번들 {schema_version:2, items:[...]} 이거나 (b) 레거시 단일
// SelfCheckConfig 일 수 있다. 어느 쪽이든 안전하게 번들로 정규화한다(파괴적 변경 없음).
export function normalizeBundle(raw: unknown, legacyPublished = false): SelfCheckBundle {
  if (raw && typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    if (Array.isArray(obj.items)) {
      const items = (obj.items as unknown[])
        .filter((it): it is SelfCheckItem => !!it && typeof it === "object" && !!(it as SelfCheckItem).config)
        .map((it, i) => ({
          ...it,
          sort_order: typeof it.sort_order === "number" ? it.sort_order : i,
          placement: Array.isArray(it.placement) ? it.placement : [],
          is_published: !!it.is_published,
          popup_enabled: it.popup_enabled !== false,
        }));
      return { schema_version: 2, items };
    }
    // 레거시 단일 config → item 1개로 감싼다(관리자에게 그대로 표시, DB 자동 변경 없음).
    if (Array.isArray(obj.questions) && Array.isArray(obj.results)) {
      const cfg = raw as SelfCheckConfig;
      return {
        schema_version: 2,
        items: [{
          item_id: "legacy", title: cfg.item_name || "기존 설정", description: null,
          sort_order: 0, is_published: legacyPublished, popup_enabled: true,
          placement: [], config: cfg,
        }],
      };
    }
  }
  return { schema_version: 2, items: [] };
}

export interface BundleValidationReport {
  errors: string[];
  warnings: string[];
  itemErrors: Record<string, string[]>; // item_id → errors
}

// 번들 무결성: item_id 중복/누락, 각 item.config 그래프 검증.
export function validateBundle(bundle: SelfCheckBundle | null | undefined): BundleValidationReport {
  const errors: string[] = [];
  const warnings: string[] = [];
  const itemErrors: Record<string, string[]> = {};
  if (!bundle || !Array.isArray(bundle.items)) return { errors: ["번들이 비어 있습니다."], warnings, itemErrors };
  const ids = bundle.items.map((it) => it.item_id);
  const dup = ids.filter((v, i) => ids.indexOf(v) !== i);
  if (dup.length) errors.push(`중복 item_id: ${Array.from(new Set(dup)).join(", ")}`);
  for (const it of bundle.items) {
    if (!it.item_id || !it.item_id.trim()) { errors.push("item_id 가 비어 있는 항목이 있습니다."); continue; }
    const rep = validateConfig(it.config);
    if (rep.errors.length) itemErrors[it.item_id] = rep.errors;
  }
  return { errors, warnings, itemErrors };
}

// 공개(런처/공개 API)에 노출할 항목: 게시 + 팝업 + 그래프 유효 + sort_order 정렬.
export function publishedItems(bundle: SelfCheckBundle | null | undefined): SelfCheckItem[] {
  if (!bundle || !Array.isArray(bundle.items)) return [];
  return bundle.items
    .filter((it) => it.is_published && it.popup_enabled && validateConfig(it.config).errors.length === 0)
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
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
