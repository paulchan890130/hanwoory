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
 *  Accepts: YYYYMMDD, YYYY.MM.DD, YYYY/MM/DD, YYYY-MM-DD.
 *  Returns the input unchanged if it doesn't match any known pattern.
 */
export function normalizeDate(v: string): string {
  if (!v) return v;
  const s = v.trim();
  // YYYYMMDD → YYYY-MM-DD
  if (/^\d{8}$/.test(s)) {
    return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
  }
  // YYYY.MM.DD or YYYY/MM/DD → YYYY-MM-DD
  if (/^\d{4}[./]\d{2}[./]\d{2}$/.test(s)) {
    return s.replace(/[./]/g, "-");
  }
  return s;
}
