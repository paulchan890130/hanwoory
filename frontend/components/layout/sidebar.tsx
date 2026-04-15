"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { getUser } from "@/lib/auth";
import {
  Home, Users, ClipboardList, DollarSign,
  FileText, ScanLine, BookOpen, Search, FileEdit,
  MessageSquare, Settings, ChevronLeft, ChevronRight, BarChart2,
  ExternalLink, X, Library,
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/dashboard",  label: "홈 대시보드",   icon: Home },
  { href: "/customers",  label: "고객관리",       icon: Users },
  { href: "/tasks",      label: "업무관리",       icon: ClipboardList },
  { href: "/daily",      label: "일일결산",       icon: DollarSign },
  { href: "/monthly",    label: "월간결산",       icon: BarChart2 },
  { href: "/quick-doc",  label: "문서자동작성",   icon: FileEdit },
  { href: "/scan",       label: "OCR 스캔",       icon: ScanLine },
  { href: "/reference",   label: "업무참고",       icon: BookOpen },
  { href: "/guidelines",  label: "실무지침",       icon: Library },
  { href: "/search",     label: "통합검색",       icon: Search },
  { href: "/memos",      label: "메모",           icon: FileText },
  { href: "/board",      label: "게시판",         icon: MessageSquare },
  // { href: "/manual", label: "메뉴얼 검색", icon: HelpCircle },
];

const HIKOREA_MANUAL_URL =
  "https://www.hikorea.go.kr/board/BoardNtcDetailR.pt?BBS_SEQ=1&BBS_GB_CD=BS10&NTCCTT_SEQ=1062&page=1";

const ADMIN_ITEM = { href: "/admin", label: "관리자", icon: Settings };

export const SIDEBAR_EXPANDED_WIDTH = 220;
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

  const isActive = (href: string) => pathname.startsWith(href) && href !== "/";

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
        {/* 로고 + 브랜드 */}
        <div
          className="flex items-center gap-3 px-4 py-4 border-b shrink-0"
          style={{ borderColor: "rgba(255,255,255,0.08)", minHeight: 56 }}
        >
          <img
            src="/hanwoori-logo.jpeg"
            alt="한우리 로고"
            style={{ width: 32, height: 32, borderRadius: 8, objectFit: "cover", flexShrink: 0 }}
          />
          {showExpanded && (
            <div className="overflow-hidden flex-1">
              <div className="font-bold text-white text-sm leading-tight">한우리</div>
              <div className="text-[11px] text-[#A0AEC0] leading-tight truncate">출입국업무관리</div>
            </div>
          )}
          {/* 모바일: 닫기 버튼 */}
          {isMobile && (
            <button
              onClick={onMobileClose}
              style={{ color: "#718096", background: "none", border: "none", cursor: "pointer", padding: 4, flexShrink: 0 }}
            >
              <X size={18} />
            </button>
          )}
        </div>

        {/* 사무소명 */}
        {showExpanded && user?.office_name && (
          <div
            className="px-4 py-2.5 text-[11px] border-b"
            style={{ color: "#718096", borderColor: "rgba(255,255,255,0.06)" }}
          >
            <span className="block font-medium text-[#A0AEC0] truncate">{user.office_name}</span>
          </div>
        )}

        {/* 네비게이션 */}
        <nav className="flex-1 py-2 overflow-y-auto overflow-x-hidden">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              title={!showExpanded ? label : undefined}
              className={`hw-sidebar-item ${isActive(href) ? "active" : ""}`}
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

          {user?.is_admin && (
            <Link
              href={ADMIN_ITEM.href}
              title={!showExpanded ? ADMIN_ITEM.label : undefined}
              className={`hw-sidebar-item ${isActive(ADMIN_ITEM.href) ? "active" : ""}`}
              onClick={isMobile ? onMobileClose : undefined}
            >
              <ADMIN_ITEM.icon size={16} className="shrink-0" />
              {showExpanded && <span className="truncate">{ADMIN_ITEM.label}</span>}
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
