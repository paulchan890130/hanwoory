// deriveBirthDateFromArc 단위 케이스(프레임워크 비의존).
// 프로젝트에 JS 테스트 러너가 없어 tsc 타입체크만 받는다. 향후 vitest/jest 도입 시
// import 하여 runBirthTests() 를 호출하거나, `npx tsx lib/birth.test.ts` 로 직접 실행.
import { deriveBirthDateFromArc } from "./birth";

const CASES: Array<[string, string, string]> = [
  ["020911", "7", "20020911"], // 2000년대(7)
  ["020911", "8", "20020911"], // 2000년대(8)
  ["900101", "5", "19900101"], // 1900년대(5)
  ["900101", "6", "19900101"], // 1900년대(6)
  ["900101", "1", "19900101"], // 1900년대(1)
  ["010101", "3", "20010101"], // 2000년대(3)
  ["010101", "4", "20010101"], // 2000년대(4)
];

export function runBirthTests(): void {
  for (const [front6, back, expected] of CASES) {
    const got = deriveBirthDateFromArc(front6, back);
    if (got !== expected) {
      throw new Error(`birth case ${front6}+${back} => ${got} (expected ${expected})`);
    }
  }
  // 비정상 입력은 빈 문자열
  if (deriveBirthDateFromArc("12345", "7") !== "") throw new Error("short front6 must be empty");
  if (deriveBirthDateFromArc("", "7") !== "") throw new Error("empty front6 must be empty");
}
