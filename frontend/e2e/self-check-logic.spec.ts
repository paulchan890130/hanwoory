import { test, expect } from "@playwright/test";

import { CRIMINAL_RECORD_CONFIG, TUBERCULOSIS_CONFIG, FINGERPRINT_CONFIG } from "../lib/selfcheck/defaultConfig";
import { nextStep, validateConfig } from "../lib/selfcheck/logic";
import type { SelfCheckConfig } from "../lib/selfcheck/types";

// PDF 기준 판정 로직 — 순수 그래프 검증(브라우저 불필요). 답변 경로별 종결 결과를 확인한다.

function walk(cfg: SelfCheckConfig, answers: Array<"yes" | "no">): string {
  let id = cfg.start_question_id;
  for (const a of answers) {
    const step = nextStep(cfg, id, a);
    if (step.kind === "result") return step.id;
    if (step.kind === "invalid") return "INVALID";
    id = step.id;
  }
  return "NO_RESULT"; // 답변이 부족해 결과에 도달 못함
}

test.describe("자가점검 판정 로직 — 그래프 무결성", () => {
  test("세 항목 모두 구조 검증 통과 + 올바른 버전", () => {
    expect(validateConfig(CRIMINAL_RECORD_CONFIG).errors).toEqual([]);
    expect(validateConfig(TUBERCULOSIS_CONFIG).errors).toEqual([]);
    expect(validateConfig(FINGERPRINT_CONFIG).errors).toEqual([]);
    expect(CRIMINAL_RECORD_CONFIG.logic_version).toBe("CR-1.0");
    expect(TUBERCULOSIS_CONFIG.logic_version).toBe("TB-1.0");
    expect(FINGERPRINT_CONFIG.logic_version).toBe("FP-1.0");
  });
});

test.describe("해외범죄경력증명 (CR-1.0)", () => {
  const C = CRIMINAL_RECORD_CONFIG;
  test("14세 미만 → 비대상", () => expect(walk(C, ["no"])).toBe("r_none"));
  test("F-4 변경·연장 + 60세 이상 → 비대상", () => expect(walk(C, ["yes", "yes", "yes"])).toBe("r_none"));
  test("미제출 → 대상", () => expect(walk(C, ["yes", "no", "no"])).toBe("r_target"));
  test("기제출 + 해외 6개월 이상 → 대상", () => expect(walk(C, ["yes", "no", "yes", "yes"])).toBe("r_target"));
  test("기제출 + 해외 6개월 미만 → 비대상", () => expect(walk(C, ["yes", "no", "yes", "no"])).toBe("r_none"));
});

test.describe("결핵검진 (TB-1.0)", () => {
  const T = TUBERCULOSIS_CONFIG;
  test("q1 아니오 → 비대상", () => expect(walk(T, ["no"])).toBe("r_none"));
  test("q1 예 → q2 아니오 → 비대상", () => expect(walk(T, ["yes", "no"])).toBe("r_none"));
  test("q1 예 → q2 예 → q3 아니오 → 제출 대상", () => expect(walk(T, ["yes", "yes", "no"])).toBe("r_target"));
  test("q1 예 → q2 예 → q3 예 → q4 예 → 제출 대상", () => expect(walk(T, ["yes", "yes", "yes", "yes"])).toBe("r_target"));
  test("q1 예 → q2 예 → q3 예 → q4 아니오 → 비대상", () => expect(walk(T, ["yes", "yes", "yes", "no"])).toBe("r_none"));

  test("잘못된 과거 로직 문구가 제거됨", () => {
    const s = JSON.stringify(TUBERCULOSIS_CONFIG);
    for (const banned of ["90일을 초과하는 장기체류", "최근 6개월 이내 결핵검진", "6개월내 검진 제출이력"]) {
      expect(s.includes(banned)).toBeFalsy();
    }
    // q4 는 "제출 또는 비자발급 이후 … 계속하여 6개월 이상 체류" 의미여야 한다.
    const q4 = TUBERCULOSIS_CONFIG.questions.find((q) => q.id === "q4");
    expect(q4?.text).toContain("6개월 이상");
    expect(q4?.text).toContain("이후");
  });
});

test.describe("지문등록 (FP-1.0)", () => {
  const F = FINGERPRINT_CONFIG;
  test("17세 미만 → 비대상", () => expect(walk(F, ["no"])).toBe("r_none"));
  test("17세 이상 + 과거 등록 없음 → 대상", () => expect(walk(F, ["yes", "no"])).toBe("r_target"));
  test("17세 이상 + 과거 등록 있음 → 원칙적 비대상", () => {
    expect(walk(F, ["yes", "yes"])).toBe("r_principle_none");
    const r = FINGERPRINT_CONFIG.results.find((x) => x.id === "r_principle_none");
    expect(r?.notice_text || "").toContain("다시 요구");
  });
});
