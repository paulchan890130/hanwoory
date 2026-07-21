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

// ── 권한 헬퍼 ────────────────────────────────────────────────────────────────
// 백엔드가 권한의 source of truth(메뉴 숨김은 UX일 뿐). 아래는 표시용 게이트.

/** full admin 또는 마스터 — 계정관리/보안설정 등 전체 관리자 기능. */
export function isFullAdmin(u: UserInfo | null): boolean {
  return !!(u && (u.is_admin || u.is_master));
}

/** 준 관리자(sub_admin) — full admin 이 아니면서 sub_admin 권한. */
export function isSubAdmin(u: UserInfo | null): boolean {
  return !!(u && !u.is_admin && !u.is_master && (u.role === "sub_admin" || u.is_sub_admin));
}

/** 실무지침 수정 / 게시판·마케팅 관리 — admin/master/sub_admin 허용. */
export function canManageContent(u: UserInfo | null): boolean {
  return isFullAdmin(u) || isSubAdmin(u);
}

/** 시스템 운영 관리자(전역 설정 · 승인형 SaaS 시스템 API).
 *  서버가 내려주는 `is_system_admin`(마스터 + SYSTEM_ADMIN_LOGIN_IDS 허용목록)을 최종 판단으로
 *  사용한다. env 허용목록 계정도 정확히 반영된다. 구버전 토큰(필드 없음) 호환을 위해 master 폴백. */
export function isSystemAdmin(u: UserInfo | null): boolean {
  if (u && typeof u.is_system_admin === "boolean") return u.is_system_admin;
  return !!(u && u.is_master);
}
