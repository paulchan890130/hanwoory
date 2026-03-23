"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { isLoggedIn } from "@/lib/auth";
import Sidebar, {
  SIDEBAR_EXPANDED_WIDTH,
  SIDEBAR_COLLAPSED_WIDTH,
} from "@/components/layout/sidebar";
import Topbar from "@/components/layout/topbar";

const SIDEBAR_COLLAPSED_KEY = "hw_sidebar_collapsed";

export default function MainLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [collapsed, setCollapsed] = useState(false);
  const [mounted, setMounted] = useState(false);

  // 인증 체크
  useEffect(() => {
    if (!isLoggedIn()) {
      router.replace("/login");
    }
  }, [router]);

  // 사이드바 상태 localStorage 복원
  useEffect(() => {
    const saved = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (saved === "true") setCollapsed(true);
    setMounted(true);
  }, []);

  const handleToggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      return next;
    });
  };

  const leftOffset = collapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_EXPANDED_WIDTH;

  // 마운트 전 레이아웃 깜빡임 방지
  if (!mounted) {
    return (
      <div className="min-h-screen" style={{ background: "var(--hw-page-bg)" }} />
    );
  }

  return (
    <div className="flex min-h-screen" style={{ background: "var(--hw-page-bg)" }}>
      {/* 사이드바 */}
      <Sidebar collapsed={collapsed} onToggle={handleToggle} />

      {/* 우측 전체 영역 */}
      <div
        className="flex flex-col flex-1 min-w-0"
        style={{
          marginLeft: leftOffset,
          transition: "margin-left 0.2s",
        }}
      >
        {/* 상단바 */}
        <Topbar leftOffset={leftOffset} />

        {/* 메인 컨텐츠 — 상단바 56px 높이 확보 */}
        <main
          className="flex-1"
          style={{
            marginTop: 56,
            padding: "24px 28px",
            minHeight: "calc(100vh - 56px)",
          }}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
