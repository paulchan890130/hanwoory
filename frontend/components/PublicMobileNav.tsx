"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import "./public-mobile.css";

const PAGE_MAP: Record<string, { label: string; href: string }> = {
  "/board": { label: "업무 안내", href: "/board" },
  "/documents": { label: "업무별 준비서류", href: "/documents" },
  "/siheung-immigration-agent": { label: "시흥 출입국 업무 안내", href: "/siheung-immigration-agent" },
  "/jeongwang-immigration-agent": { label: "정왕 출입국 업무 안내", href: "/jeongwang-immigration-agent" },
};

function getPageInfo(pathname: string): { label: string; href: string } | null {
  if (PAGE_MAP[pathname]) return PAGE_MAP[pathname];
  if (pathname.startsWith("/board/")) return { label: "업무 안내", href: "/board" };
  return null;
}

export function PublicMobileNav() {
  const pathname = usePathname();
  const isHome = pathname === "/";
  const pageInfo = getPageInfo(pathname);

  return (
    <>
      {/* Fixed top breadcrumb header — mobile only, not shown on homepage (homepage has its own nav) */}
      {!isHome && (
        <header className="pmn-header" aria-label="모바일 내비게이션">
          <Link href="/" className="pmn-logo-link">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/hanwoori-logo-new.png"
              alt="한우리행정사사무소 로고"
              className="pmn-logo-img"
            />
            <span className="pmn-logo-text">한우리행정사사무소</span>
          </Link>
          {pageInfo && (
            <>
              <span className="pmn-sep" aria-hidden="true">›</span>
              <Link href={pageInfo.href} className="pmn-page-label">
                {pageInfo.label}
              </Link>
            </>
          )}
        </header>
      )}

      {/* Height spacer — pushes page content below the fixed header on mobile */}
      {!isHome && <div className="pmn-top-spacer" aria-hidden="true" />}

      {/* Fixed bottom contact bar — mobile only, all public pages */}
      <div className="pmn-contact-bar" role="complementary" aria-label="문의 연락처">
        <span className="pmn-contact-text">
          문의전화 :{" "}
          <a href="tel:01047028886">010-4702-8886</a>
        </span>
        <div className="pmn-contact-icons">
          <a href="tel:01047028886" className="pmn-icon-btn" aria-label="전화하기">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07A19.5 19.5 0 015 12.91a19.79 19.79 0 01-3.07-8.67A2 2 0 013.92 2h3a2 2 0 012 1.72c.127.96.361 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0122 16.92z" />
            </svg>
          </a>
          <a href="sms:01047028886" className="pmn-icon-btn" aria-label="문자 보내기">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
            </svg>
          </a>
        </div>
      </div>
    </>
  );
}
