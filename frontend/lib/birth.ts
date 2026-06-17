// 외국인등록번호 → 생년월일(세기 정확) 공통 helper.
// 기존 보조창들이 각자 "19" + 앞6자리로 하드코딩해 2000년대 출생자를 1900년대로
// 잘못 변환하던 버그를 한 곳에서 정정한다. 고객상세/복사/하이코리아·소시넷 ID찾기/
// 체류만료조회 보조창이 모두 이 helper 를 쓴다.
//
// 세기 판단 = 등록번호 "뒷자리 첫 숫자"(gender/century code) 기준:
//   1,2,5,6 → 1900년대   /   3,4,7,8 → 2000년대   /   9,0 → 예외(보수적 YY 휴리스틱)
// 단순 YY>현재년도 방식은 사용하지 않는다(9,0 예외에서만 보조적으로 사용).

function _digits(s: string | null | undefined): string {
  return (s ?? "").replace(/\D/g, "");
}

/** 등록번호 뒷자리(또는 그 첫 숫자) → 세기 prefix("19"|"20"). 미상이면 yy 휴리스틱. */
export function centuryFromArcBack(backFirstDigit: string | null | undefined, yy?: string): "19" | "20" {
  const d = _digits(backFirstDigit);
  const code = d.length ? d[0] : "";
  if (code === "1" || code === "2" || code === "5" || code === "6") return "19";
  if (code === "3" || code === "4" || code === "7" || code === "8") return "20";
  // 9,0 또는 미상: 보수적 예외 — yy 가 현재 두자리 이하면 2000년대, 아니면 1900년대.
  const yn = parseInt(_digits(yy).slice(0, 2) || "-1", 10);
  if (yn >= 0) {
    const cur2 = new Date().getFullYear() % 100;
    return yn <= cur2 ? "20" : "19";
  }
  return "19";
}

/**
 * 등록번호 앞 6자리(YYMMDD) + 뒷자리(첫 숫자로 세기 판단) → "YYYYMMDD".
 * 앞자리가 6자리 숫자가 아니면 빈 문자열 반환. (원문 로그 출력 금지 — 호출측도 동일)
 */
export function deriveBirthDateFromArc(
  front6: string | null | undefined,
  arcBack: string | null | undefined,
): string {
  const f = _digits(front6);
  if (f.length !== 6) return "";
  const century = centuryFromArcBack(arcBack, f.slice(0, 2));
  return century + f; // YYYYMMDD
}

/** "YYYYMMDD" → "YYYY-MM-DD". 8자리 아니면 입력 그대로. */
export function formatBirth8(yyyymmdd: string): string {
  const d = _digits(yyyymmdd);
  return d.length === 8 ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` : yyyymmdd;
}
