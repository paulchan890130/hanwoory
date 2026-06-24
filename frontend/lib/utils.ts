import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function safeInt(v: unknown): number {
  try {
    const s = String(v ?? "0").replace(/,/g, "").trim();
    if (!s || s === "none" || s.toLowerCase() === "nan") return 0;
    return parseInt(String(parseFloat(s)), 10) || 0;
  } catch {
    return 0;
  }
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat("ko-KR").format(n);
}

/**
 * 원 단위 금액을 "만원" 단위 문자열로 변환 (소수 1자리까지).
 * 예: 1,250,000 → "125만원", 35,000 → "3.5만원", 0 → "0만원".
 * 음수도 안전 처리. 상세 원 단위는 tooltip/상세표에서만 사용.
 */
export function formatManwon(n: number): string {
  const man = (n || 0) / 10000;
  // 소수 1자리, 단 정수면 소수점 제거 (125.0 → 125)
  const rounded = Math.round(man * 10) / 10;
  const s = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return `${new Intl.NumberFormat("ko-KR").format(Number(s))}만원`;
}

export function formatDate(d: Date | string): string {
  const date = typeof d === "string" ? new Date(d) : d;
  return date.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

export function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** Normalize user-entered date strings to YYYY-MM-DD.
 *  Accepts: YYYYMMDD, YYYY.MM.DD, YYYY/MM/DD, YYYY-MM-DD,
 *           and timestamp forms ("YYYY-MM-DD hh:mm:ss", "YYYY-MM-DDThh:mm:ss…")
 *           — the time part is dropped, only the date is kept.
 *  Returns the input unchanged if it doesn't match any known pattern.
 */
export function normalizeDate(v: string): string {
  if (!v) return v;
  // Strip trailing dots/slashes before matching (handles "0000.00.00.")
  const s = v.trim().replace(/[./]+$/, "");
  // YYYY-MM-DD (optionally followed by space/T + time) → date part only
  const ymd = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T].*)?$/);
  if (ymd) {
    return `${ymd[1]}-${ymd[2]}-${ymd[3]}`;
  }
  // YYYYMMDD → YYYY-MM-DD
  if (/^\d{8}$/.test(s)) {
    return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
  }
  // YYYY.MM.DD or YYYY/MM/DD (optionally with trailing time) → YYYY-MM-DD
  const dotted = s.match(/^(\d{4})[./](\d{2})[./](\d{2})(?:[ T].*)?$/);
  if (dotted) {
    return `${dotted[1]}-${dotted[2]}-${dotted[3]}`;
  }
  return s;
}
