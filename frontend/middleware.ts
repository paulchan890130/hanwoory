import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Route guard: redirect to /login if the kid_auth presence cookie is absent.
 * The cookie is set by setUser() in lib/auth.ts on successful login and
 * cleared by clearUser() on logout / 401.
 *
 * Matcher excludes: /login, /_next/*, /api/*, and common static asset extensions.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  // 공개 경로 — 인증 없이 접근 가능
  if (pathname === "/" || pathname.startsWith("/board")) {
    return NextResponse.next();
  }
  const authed = request.cookies.has("kid_auth");
  if (!authed) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!login|_next|api|favicon\\.ico|.*\\.(?:jpg|jpeg|png|gif|svg|ico|webp|woff2?|ttf|otf|css|js)).*)",
  ],
};
