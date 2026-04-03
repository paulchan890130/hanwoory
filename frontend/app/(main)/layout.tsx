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
  const [ready, setReady] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (saved === "true") setCollapsed(true);
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [router]);

  useEffect(() => {
    const check = () => {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      if (!mobile) setMobileDrawerOpen(false);
    };
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  const handleToggle = () => {
    setCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(next));
      return next;
    });
  };

  const leftOffset = collapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_EXPANDED_WIDTH;
  const mainMarginLeft = isMobile ? 0 : leftOffset;

  if (!ready) {
    return <div className="min-h-screen" style={{ background: "var(--hw-page-bg)" }} />;
  }

  return (
    <div className="flex min-h-screen" style={{ background: "var(--hw-page-bg)" }}>
      <Sidebar
        collapsed={collapsed}
        onToggle={handleToggle}
        isMobile={isMobile}
        mobileOpen={mobileDrawerOpen}
        onMobileClose={() => setMobileDrawerOpen(false)}
      />

      <div
        className="flex flex-col flex-1 min-w-0"
        style={{ marginLeft: mainMarginLeft, transition: "margin-left 0.2s" }}
      >
        <Topbar
          leftOffset={mainMarginLeft}
          isMobile={isMobile}
          onMobileMenuToggle={() => setMobileDrawerOpen((v) => !v)}
        />

        <main
          className="flex-1"
          style={{
            marginTop: 56,
            padding: isMobile ? "14px 12px" : "24px 28px",
            minHeight: "calc(100vh - 56px)",
          }}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
