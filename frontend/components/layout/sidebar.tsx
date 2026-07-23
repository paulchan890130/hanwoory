"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { getUser, isFullAdmin, isSystemAdmin, canManageContent } from "@/lib/auth";
import { officeApplicationApi } from "@/lib/api";
import {
  Home, Users, ClipboardList, DollarSign,
  FileText, ScanLine, Search, FileEdit,
  MessageSquare, Settings, ChevronLeft, ChevronRight, BarChart2,
  ExternalLink, X, Library, Globe, User, Award,
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/dashboard",  label: "홈 대시보드",   icon: Home },
  { href: "/customers",  label: "고객관리",       icon: Users },
  { href: "/tasks",      label: "업무관리",       icon: ClipboardList },
  { href: "/daily",      label: "일일결산",       icon: DollarSign },
  { href: "/monthly",    label: "월간결산",       icon: BarChart2 },
  { href: "/quick-doc",  label: "문서자동작성",   icon: FileEdit },
  { href: "/scan",       label: "문서 인식",      icon: ScanLine },
  // 업무참고는 기타업무참고(각종공인증)로 대체되어 메뉴에서 숨김. 라우트/데이터는 유지.
  // { href: "/reference",            label: "업무참고",    icon: BookOpen },
  { href: "/certification-services",  label: "기타업무참고", icon: Award },
  { href: "/guidelines",              label: "실무지침",    icon: Library },
  { href: "/search",     label: "통합검색",       icon: Search },
  { href: "/memos",      label: "메모",           icon: FileText },
  { href: "/noticeboard", label: "게시판",         icon: MessageSquare },
  // { href: "/manual", label: "메뉴얼 검색", icon: HelpCircle },
];

// 온보딩 투어 강조 대상(안정적 앵커). 나머지 메뉴는 undefined → 속성 미부여.
const NAV_TOUR_ID: Record<string, string | undefined> = {
  "/customers": "sidebar-customers",
  "/tasks": "sidebar-work",
  "/quick-doc": "sidebar-quick-doc",
};

const HIKOREA_MANUAL_URL =
  "https://www.hikorea.go.kr/board/BoardNtcDetailR.pt?BBS_SEQ=1&BBS_GB_CD=BS10&NTCCTT_SEQ=1062&page=1";

const MY_ITEM = { href: "/my", label: "마이페이지", icon: User };
const ADMIN_ITEM = { href: "/admin", label: "관리자", icon: Settings };
const MARKETING_ITEM = { href: "/marketing", label: "마케팅", icon: Globe };
const OFFICE_ACCOUNTS_ITEM = { href: "/account-management", label: "우리 사무소 계정", icon: Users };

export const SIDEBAR_EXPANDED_WIDTH = 164;
export const SIDEBAR_COLLAPSED_WIDTH = 64;

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  isMobile?: boolean;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

export default function Sidebar({ collapsed, onToggle, isMobile, mobileOpen, onMobileClose }: SidebarProps) {
  const pathname = usePathname();
  const user = getUser();

  // 승인형 SaaS 활성 여부(공개 availability). OFF 회귀 방지를 위해 메뉴 노출 기준에 사용:
  //  - 관리자(시스템 전체): 시스템 관리자 || (SaaS OFF 인 레거시에서 full admin)
  //  - 우리 사무소 계정: SaaS ON + full admin (office 서브계정 관리 — SaaS 전용 화면)
  const [saasEnabled, setSaasEnabled] = useState(false);
  useEffect(() => {
    let alive = true;
    officeApplicationApi.availability()
      .then((r) => { if (alive) setSaasEnabled(!!r.data?.enabled); })
      .catch(() => { if (alive) setSaasEnabled(false); });
    return () => { alive = false; };
  }, []);
  const showAdminMenu = isSystemAdmin(user) || (!saasEnabled && isFullAdmin(user));
  const showOfficeAccountsMenu = saasEnabled && isFullAdmin(user);

  // 시스템 관리자 전용: 신규 사무소 신청 미처리(pending) 건수 배지 + 증가 시 1회 toast.
  // 로그인/포커스 복귀/30초 주기로 갱신. sessionStorage 로 마지막 건수를 관리해 같은 건수 반복 toast 방지.
  const [pendingApps, setPendingApps] = useState(0);
  const firstStatPoll = useRef(true);
  const sysAdmin = isSystemAdmin(user);
  useEffect(() => {
    if (!sysAdmin || !saasEnabled) return;
    let alive = true;
    const KEY = "office_app_last_pending";
    const poll = () => {
      officeApplicationApi.stats().then((r) => {
        if (!alive) return;
        const n = r.data?.pending ?? 0;
        setPendingApps(n);
        try {
          const prev = Number(sessionStorage.getItem(KEY) || "0");
          // 최초 폴링은 기준선만 저장(기존 pending 을 신규로 오인해 toast 하지 않음).
          if (!firstStatPoll.current && n > prev) {
            toast.info("새로운 사무소 이용 신청이 접수되었습니다.");
          }
          sessionStorage.setItem(KEY, String(n));
          firstStatPoll.current = false;
        } catch { /* sessionStorage 불가 환경 무시 */ }
      }).catch(() => { /* OFF/오류는 배지 미표시 */ });
    };
    poll();
    const id = setInterval(poll, 30000);
    const onWake = () => poll();
    window.addEventListener("focus", onWake);
    document.addEventListener("visibilitychange", onWake);
    return () => {
      alive = false; clearInterval(id);
      window.removeEventListener("focus", onWake);
      document.removeEventListener("visibilitychange", onWake);
    };
  }, [sysAdmin, saasEnabled]);

  const isActive = (href: string) => pathname.startsWith(href) && href !== "/";

  // 실무지침 기본 화면 = 자격별 찾기(/qualifications) — 전 로그인 사용자 공통.
  // (편집 기능만 관리자 차등 — 서버 editable) 활성 표시는 두 경로 모두 실무지침 메뉴로 취급.
  const navHref = (href: string) =>
    href === "/guidelines" ? "/qualifications" : href;
  const navActive = (href: string) =>
    href === "/guidelines"
      ? (isActive("/guidelines") || isActive("/qualifications"))
      : isActive(href);

  // 모바일: 항상 expanded 형태로, transform으로 슬라이드
  const showExpanded = isMobile ? true : !collapsed;

  const sidebarStyle: React.CSSProperties = isMobile
    ? {
        width: SIDEBAR_EXPANDED_WIDTH,
        transform: mobileOpen ? "translateX(0)" : "translateX(-100%)",
        transition: "transform 0.25s ease",
        zIndex: 200,
      }
    : { width: collapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_EXPANDED_WIDTH };

  return (
    <>
      {/* 모바일 백드롭 */}
      {isMobile && mobileOpen && (
        <div
          onClick={onMobileClose}
          style={{
            position: "fixed", inset: 0,
            background: "rgba(0,0,0,0.5)",
            zIndex: 199,
          }}
        />
      )}

      <aside
        className={`hw-sidebar ${showExpanded ? "expanded" : "collapsed"}`}
        style={sidebarStyle}
      >
        {/* 브랜드 헤더 */}
        <div
          style={{
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            gap: 9,
            padding: showExpanded ? "12px 12px" : "12px 0",
            justifyContent: showExpanded ? "flex-start" : "center",
            borderBottom: "1px solid rgba(255,255,255,0.08)",
            minHeight: 60,
          }}
        >
          <div style={{
            width: showExpanded ? 34 : 34,
            height: showExpanded ? 34 : 34,
            borderRadius: 8,
            background: "#FFFFFF",
            padding: 3,
            flexShrink: 0,
            overflow: "hidden",
          }}>
            <img
              src="/logo.jpg"
              alt="한우리 로고"
              style={{
                width: "100%",
                height: "100%",
                borderRadius: 6,
                objectFit: "cover",
                display: "block",
              }}
            />
          </div>
          {showExpanded && (
            <div style={{ overflow: "hidden", flex: 1, minWidth: 0 }}>
              <div style={{
                fontSize: 13, fontWeight: 800, color: "#FFFFFF",
                lineHeight: 1.2, letterSpacing: "-0.01em",
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                한우리 소프트
              </div>
              <div style={{ fontSize: 10, color: "#718096", lineHeight: 1.3, marginTop: 2 }}>
                출입국 업무관리
              </div>
            </div>
          )}
          {isMobile && (
            <button
              onClick={onMobileClose}
              style={{ marginLeft: "auto", color: "#718096", background: "none", border: "none", cursor: "pointer", padding: 4, flexShrink: 0 }}
            >
              <X size={18} />
            </button>
          )}
        </div>

        {/* 네비게이션 */}
        <nav className="flex-1 py-2 overflow-y-auto overflow-x-hidden">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={navHref(href)}
              title={!showExpanded ? label : undefined}
              data-tour-id={NAV_TOUR_ID[href]}
              className={`hw-sidebar-item ${navActive(href) ? "active" : ""}`}
              aria-current={navActive(href) ? "page" : undefined}
              onClick={isMobile ? onMobileClose : undefined}
            >
              <Icon size={16} className="shrink-0" />
              {showExpanded && <span className="truncate">{label}</span>}
            </Link>
          ))}

          {/* 메뉴얼 — 외부 링크 */}
          <a
            href={HIKOREA_MANUAL_URL}
            target="_blank"
            rel="noopener noreferrer"
            title={!showExpanded ? "메뉴얼" : undefined}
            className="hw-sidebar-item"
          >
            <ExternalLink size={16} className="shrink-0" />
            {showExpanded && <span className="truncate">메뉴얼</span>}
          </a>

          {/* 구분선 */}
          <div className="my-2 mx-4" style={{ borderTop: "1px solid rgba(255,255,255,0.08)" }} />

          {/* 마이페이지 — 모든 로그인 사용자 */}
          <Link
            href={MY_ITEM.href}
            title={!showExpanded ? MY_ITEM.label : undefined}
            data-tour-id="sidebar-my"
            className={`hw-sidebar-item ${isActive(MY_ITEM.href) ? "active" : ""}`}
            aria-current={isActive(MY_ITEM.href) ? "page" : undefined}
            onClick={isMobile ? onMobileClose : undefined}
          >
            <MY_ITEM.icon size={16} className="shrink-0" />
            {showExpanded && <span className="truncate">{MY_ITEM.label}</span>}
          </Link>

          {/* 우리 사무소 계정 — 승인형 SaaS 의 사무소 주계정(office_admin/master) 전용.
              office_staff 는 미표시(서버도 차단). SaaS OFF 에서는 이 화면이 동작하지 않아 숨긴다. */}
          {showOfficeAccountsMenu && (
            <Link
              href={OFFICE_ACCOUNTS_ITEM.href}
              title={!showExpanded ? OFFICE_ACCOUNTS_ITEM.label : undefined}
              data-tour-id="sidebar-account"
              className={`hw-sidebar-item ${isActive(OFFICE_ACCOUNTS_ITEM.href) ? "active" : ""}`}
              aria-current={isActive(OFFICE_ACCOUNTS_ITEM.href) ? "page" : undefined}
              onClick={isMobile ? onMobileClose : undefined}
            >
              <OFFICE_ACCOUNTS_ITEM.icon size={16} className="shrink-0" />
              {showExpanded && <span className="truncate">{OFFICE_ACCOUNTS_ITEM.label}</span>}
            </Link>
          )}

          {canManageContent(user) && (
            <Link
              href={MARKETING_ITEM.href}
              title={!showExpanded ? MARKETING_ITEM.label : undefined}
              className={`hw-sidebar-item ${isActive(MARKETING_ITEM.href) ? "active" : ""}`}
              aria-current={isActive(MARKETING_ITEM.href) ? "page" : undefined}
              onClick={isMobile ? onMobileClose : undefined}
            >
              <MARKETING_ITEM.icon size={16} className="shrink-0" />
              {showExpanded && <span className="truncate">{MARKETING_ITEM.label}</span>}
            </Link>
          )}
          {/* 관리자(시스템 전체 관리) — 시스템 운영 관리자 전용(SaaS ON). SaaS OFF 레거시에서는
              기존처럼 full admin 에게 노출(회귀 방지). office_admin 은 SaaS ON 에서 미표시(서버도 차단). */}
          {showAdminMenu && (
            <Link
              href={pendingApps > 0 ? `${ADMIN_ITEM.href}?tab=office-applications` : ADMIN_ITEM.href}
              title={!showExpanded ? `${ADMIN_ITEM.label}${pendingApps > 0 ? ` · 신규 신청 ${pendingApps}` : ""}` : undefined}
              className={`hw-sidebar-item ${isActive(ADMIN_ITEM.href) ? "active" : ""}`}
              aria-current={isActive(ADMIN_ITEM.href) ? "page" : undefined}
              onClick={isMobile ? onMobileClose : undefined}
              style={{ position: "relative" }}
            >
              <ADMIN_ITEM.icon size={16} className="shrink-0" />
              {showExpanded && <span className="truncate">{ADMIN_ITEM.label}</span>}
              {pendingApps > 0 && (
                showExpanded ? (
                  <span style={{ marginLeft: "auto", background: "#C53030", color: "#fff",
                    fontSize: 10, fontWeight: 800, borderRadius: 10, padding: "1px 7px", lineHeight: 1.5 }}>
                    {pendingApps}
                  </span>
                ) : (
                  <span style={{ position: "absolute", top: 6, right: 10, width: 8, height: 8,
                    background: "#C53030", borderRadius: "50%" }} />
                )
              )}
            </Link>
          )}
        </nav>

        {/* 접기/펼치기 버튼 — 데스크톱만 */}
        {!isMobile && (
          <div className="p-3 border-t shrink-0" style={{ borderColor: "rgba(255,255,255,0.08)" }}>
            <button
              onClick={onToggle}
              className="w-full flex items-center justify-center gap-2 px-2 py-2 rounded-lg transition-colors"
              style={{ color: "#718096" }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = "rgba(255,255,255,0.08)";
                (e.currentTarget as HTMLButtonElement).style.color = "#CBD5E0";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = "transparent";
                (e.currentTarget as HTMLButtonElement).style.color = "#718096";
              }}
              title={collapsed ? "사이드바 펼치기" : "사이드바 접기"}
            >
              {collapsed ? <ChevronRight size={15} /> : (
                <>
                  <ChevronLeft size={15} />
                  <span className="text-xs">접기</span>
                </>
              )}
            </button>
          </div>
        )}
      </aside>
    </>
  );
}
