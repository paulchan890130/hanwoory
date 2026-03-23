"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearUser, getUser } from "@/lib/auth";
import { cn } from "@/lib/utils";
import {
  Home, Users, DollarSign, ClipboardList, FileText,
  ScanLine, MessageSquare, Settings, LogOut, Zap, BookOpen,
} from "lucide-react";

const NAV_ITEMS = [
  { href: "/dashboard",  label: "홈",       icon: Home },
  { href: "/tasks",      label: "업무",     icon: ClipboardList },
  { href: "/customers",  label: "고객관리", icon: Users },
  { href: "/daily",      label: "결산",     icon: DollarSign },
  { href: "/memos",      label: "메모",     icon: FileText },
  { href: "/board",      label: "게시판",   icon: MessageSquare },
  { href: "/reference",  label: "업무참고", icon: BookOpen },
  { href: "/scan",       label: "OCR 스캔", icon: ScanLine },
  { href: "/quick-doc",  label: "위임장",   icon: Zap },
];

export default function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const user = getUser();

  const handleLogout = () => {
    clearUser();
    router.replace("/login");
  };

  return (
    <header className="sticky top-0 z-50 bg-white border-b shadow-sm">
      <div className="max-w-screen-2xl mx-auto px-4 flex items-center gap-2 h-12">
        {/* 로고 */}
        <Link href="/dashboard" className="font-bold text-blue-700 text-lg mr-3 shrink-0">
          📋 K.ID
        </Link>

        {/* 네비게이션 */}
        <nav className="flex items-center gap-0.5 overflow-x-auto flex-1 min-w-0">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors",
                pathname.startsWith(href) && href !== "/" && pathname !== "/"
                  ? "bg-blue-50 text-blue-700"
                  : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
              )}
            >
              <Icon size={13} />
              {label}
            </Link>
          ))}
          {user?.is_admin && (
            <Link
              href="/admin"
              className={cn(
                "flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors",
                pathname.startsWith("/admin")
                  ? "bg-orange-50 text-orange-700"
                  : "text-gray-600 hover:bg-gray-100"
              )}
            >
              <Settings size={13} />
              계정관리
            </Link>
          )}
        </nav>

        {/* 우측: 사용자 정보 + 로그아웃 */}
        <div className="flex items-center gap-2 shrink-0 ml-2">
          <span className="text-xs text-gray-500 hidden sm:block">
            {user?.office_name || user?.login_id}
          </span>
          <button
            onClick={handleLogout}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs text-gray-500 hover:bg-red-50 hover:text-red-600 transition-colors"
          >
            <LogOut size={13} />
            로그아웃
          </button>
        </div>
      </div>
    </header>
  );
}
