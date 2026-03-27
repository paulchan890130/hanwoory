/**
 * 클라이언트 사이드 인증 헬퍼
 */
import type { UserInfo } from "./api";

export function getUser(): UserInfo | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("user_info");
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setUser(user: UserInfo): void {
  if (typeof window === "undefined") return;
  localStorage.setItem("user_info", JSON.stringify(user));
  localStorage.setItem("access_token", user.access_token);
  // Presence cookie for middleware route guard (not httpOnly — set from JS)
  document.cookie = "kid_auth=1; path=/; SameSite=Lax";
}

export function clearUser(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem("user_info");
  localStorage.removeItem("access_token");
  document.cookie = "kid_auth=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax";
}

export function isLoggedIn(): boolean {
  return !!getUser();
}
