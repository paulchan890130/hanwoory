import { test, expect } from "@playwright/test";

import { CRIMINAL_RECORD_CONFIG, TUBERCULOSIS_CONFIG, FINGERPRINT_CONFIG } from "../lib/selfcheck/defaultConfig";
import { nextStep, validateConfig } from "../lib/selfcheck/logic";
import {
  TUBERCULOSIS_HIGH_RISK_COUNTRIES, TB_CANONICAL_COUNT, verifyTuberculosis, normalizeCountry, isTuberculosisItem,
} from "../lib/selfcheck/tuberculosis";
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

test.describe("결핵 고위험 국가 공식 35개국 + 게시 검증", () => {
  const MISSING_18 = [
    "말레이시아", "스리랑카", "우즈베키스탄", "카자흐스탄", "우크라이나", "아제르바이잔",
    "벨라루스", "몰도바공화국", "나이지리아", "남아프리카공화국", "에티오피아",
    "콩고민주공화국", "케냐", "모잠비크", "짐바브웨", "앙골라", "페루", "파푸아뉴기니",
  ];

  test("공식 목록 정확히 35개 · 중복 0 · 빈 문자열 없음", () => {
    expect(TUBERCULOSIS_HIGH_RISK_COUNTRIES.length).toBe(35);
    expect(TB_CANONICAL_COUNT).toBe(35);
    expect(new Set(TUBERCULOSIS_HIGH_RISK_COUNTRIES).size).toBe(35);
    expect(TUBERCULOSIS_HIGH_RISK_COUNTRIES.every((c) => c.trim().length > 0)).toBeTruthy();
  });

  test("기존 누락 18개국 모두 포함", () => {
    for (const c of MISSING_18) expect(TUBERCULOSIS_HIGH_RISK_COUNTRIES).toContain(c);
  });

  test("기본 TB config 는 게시 검증 통과(35/35·출처 완료)", () => {
    const v = verifyTuberculosis(TUBERCULOSIS_CONFIG);
    expect(v.ok).toBeTruthy();
    expect(v.count).toBe(35);
    expect(v.dup).toBe(0);
    expect(v.matchesCanonical).toBeTruthy();
    expect(v.hasSource).toBeTruthy();
    expect(v.banned).toBeFalsy();
  });

  test("17개 목록 → 게시 검증 실패", () => {
    const v = verifyTuberculosis({ ...TUBERCULOSIS_CONFIG, country_list: TUBERCULOSIS_HIGH_RISK_COUNTRIES.slice(0, 17) });
    expect(v.ok).toBeFalsy();
    expect(v.count).toBe(17);
  });

  test("잘못된 국가 치환 → 공식 set 불일치", () => {
    const bad = [...TUBERCULOSIS_HIGH_RISK_COUNTRIES]; bad[0] = "대한민국";
    const v = verifyTuberculosis({ ...TUBERCULOSIS_CONFIG, country_list: bad });
    expect(v.matchesCanonical).toBeFalsy();
    expect(v.ok).toBeFalsy();
  });

  test("source metadata 누락 → 게시 검증 실패", () => {
    const v = verifyTuberculosis({
      ...TUBERCULOSIS_CONFIG,
      country_list_source_title: "", country_list_source_date: "", country_list_verified_at: "",
    });
    expect(v.hasSource).toBeFalsy();
    expect(v.ok).toBeFalsy();
  });

  test("키르기스 alias 는 canonical 과 동일", () => {
    expect(normalizeCountry("키르기스")).toBe("키르기스스탄");
    const aliased = TUBERCULOSIS_HIGH_RISK_COUNTRIES.map((c) => (c === "키르기스스탄" ? "키르기스" : c));
    expect(verifyTuberculosis({ ...TUBERCULOSIS_CONFIG, country_list: aliased }).ok).toBeTruthy();
  });

  test("isTuberculosisItem: item_id 또는 TB-1.0 로 식별", () => {
    expect(isTuberculosisItem({ item_id: "tuberculosis", config: CRIMINAL_RECORD_CONFIG })).toBeTruthy();
    expect(isTuberculosisItem({ item_id: "x", config: TUBERCULOSIS_CONFIG })).toBeTruthy();
    expect(isTuberculosisItem({ item_id: "x", config: FINGERPRINT_CONFIG })).toBeFalsy();
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
