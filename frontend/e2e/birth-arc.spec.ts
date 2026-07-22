import { test, expect } from "@playwright/test";

import {
  canonicalArcFront,
  centuryFromArcBack,
  deriveBirthDateFromArc,
  formatBirth8,
} from "../lib/birth";

// 외국인등록번호 앞자리(YYMMDD) 선행 0 손실 방어 — 프론트 순수 로직 단위 검증.
// 브라우저/서버 불필요(page 미사용). 합성 값만 사용(실 고객 원문 금지).

test.describe("birth.ts — reg_front 선행 0 방어", () => {
  test("canonicalArcFront: 1~5자리는 좌측 0 채움 후 YYMMDD 검증", () => {
    expect(canonicalArcFront("1010")).toBe("001010");   // 선행 0 손실 복구
    expect(canonicalArcFront("001010")).toBe("001010");  // 이미 정상
    expect(canonicalArcFront("900101")).toBe("900101");  // 정상 6자리
    expect(canonicalArcFront("")).toBe("");
    expect(canonicalArcFront(null)).toBe("");
  });

  test("canonicalArcFront: 무효(범위 위반/7자리+)는 '' 반환(추측 금지)", () => {
    expect(canonicalArcFront("1234567")).toBe(""); // 7자리
    expect(canonicalArcFront("99999")).toBe("");   // →099999 mm=99 무효
    expect(canonicalArcFront("001300")).toBe("");  // mm=13 무효
  });

  test("deriveBirthDateFromArc: 손실된 앞자리도 복구 후 세기(뒷자리) 판정", () => {
    // 앞자리 '1010'(=001010) + 뒷자리 첫숫자로 세기 확정.
    expect(deriveBirthDateFromArc("1010", "3020304")).toBe("20001010");
    expect(deriveBirthDateFromArc("1010", "1020304")).toBe("19001010");
    expect(deriveBirthDateFromArc("001010", "3")).toBe("20001010");
    expect(deriveBirthDateFromArc("bad", "1")).toBe(""); // 복구 불가
  });

  test("deriveBirthDateFromArc: 세기 결합 실제 그레고리력 검증(백엔드와 동일 벡터)", () => {
    expect(deriveBirthDateFromArc("001010", "7020304")).toBe("20001010"); // 정상
    expect(deriveBirthDateFromArc("001010", "1020304")).toBe("19001010"); // 정상
    expect(deriveBirthDateFromArc("000229", "3020304")).toBe("20000229"); // 2000 윤년
    expect(deriveBirthDateFromArc("000229", "1020304")).toBe("");         // 1900 평년 → 없음
    expect(deriveBirthDateFromArc("990229", "1020304")).toBe("");         // 1999 평년 → 없음
    expect(deriveBirthDateFromArc("040229", "3020304")).toBe("20040229"); // 2004 윤년
  });

  test("centuryFromArcBack: 뒷자리 첫 숫자 규칙", () => {
    expect(centuryFromArcBack("1")).toBe("19");
    expect(centuryFromArcBack("3")).toBe("20");
    expect(centuryFromArcBack("6")).toBe("19");
    expect(centuryFromArcBack("8")).toBe("20");
  });

  test("formatBirth8: 8자리 → YYYY-MM-DD", () => {
    expect(formatBirth8("20001010")).toBe("2000-10-10");
    expect(formatBirth8("19001010")).toBe("1900-10-10");
  });
});
