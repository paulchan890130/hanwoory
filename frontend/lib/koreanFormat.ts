// 한국 전화번호 / 사업자등록번호 형식·정규화 — 화면 표시(하이픈) vs 저장(digits-only) 공통 helper.
// 백엔드 backend/services/korean_identifier_format.py 와 동일 규칙. DB/API 저장은 digits-only.

export function normalizePhoneInput(v: string): string {
  return (v || "").replace(/[^0-9]/g, "");
}

export function formatPhoneKR(v: string): string {
  const d = normalizePhoneInput(v);
  if (d.startsWith("02")) {
    if (d.length === 9) return `${d.slice(0, 2)}-${d.slice(2, 5)}-${d.slice(5)}`;
    if (d.length === 10) return `${d.slice(0, 2)}-${d.slice(2, 6)}-${d.slice(6)}`;
  } else {
    if (d.length === 10) return `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6)}`;
    if (d.length === 11) return `${d.slice(0, 3)}-${d.slice(3, 7)}-${d.slice(7)}`;
  }
  return d;
}

export function normalizeBizInput(v: string): string {
  return (v || "").replace(/[^0-9]/g, "");
}

export function formatBizKR(v: string): string {
  const d = normalizeBizInput(v);
  return d.length === 10 ? `${d.slice(0, 3)}-${d.slice(3, 5)}-${d.slice(5)}` : d;
}
