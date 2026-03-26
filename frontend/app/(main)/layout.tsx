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
  // ready = true only after mount AND auth confirmed — children never render until then
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // 사이드바 상태 localStorage 복원
    const saved = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (saved === "true") setCollapsed(true);

    // 인증 체크: 미로그인이면 리디렉트하고 ready를 올리지 않음
    if (!isLoggedIn()) {
      router.replace("/login");
      return; // ready stays false → blank page shown until redirect completes
    }
    setReady(true);
  }, [router]);

  const handleToggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      return next;
    });
  };

  const leftOffset = collapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_EXPANDED_WIDTH;

  // 인증 확인 전 (미마운트 포함) — 아무것도 렌더하지 않음
  if (!ready) {
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
