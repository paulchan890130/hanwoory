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
