"use client";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { isLoggedIn } from "@/lib/auth";
import Sidebar, {
  SIDEBAR_EXPANDED_WIDTH,
  SIDEBAR_COLLAPSED_WIDTH,
} from "@/components/layout/sidebar";
import Topbar from "@/components/layout/topbar";
import { X } from "lucide-react";

type PinnedCustomer = Record<string, string>;

function getDaysUntil(dateStr: string): number | null {
  if (!dateStr) return null;
  const clean = dateStr.replace(/\./g, "-").slice(0, 10);
  const d = new Date(clean);
  if (isNaN(d.getTime())) return null;
  const now = new Date(); now.setHours(0, 0, 0, 0);
  return Math.floor((d.getTime() - now.getTime()) / 86_400_000);
}

function ExpiryLine({ label, value, days }: { label: string; value: string; days: number | null }) {
  if (!value) return null;
  const urgent = days !== null && days <= 30;
  const warn = days !== null && days > 30 && days <= 120;
  const color = urgent ? "#C53030" : warn ? "#9C4221" : "#2D3748";
  const dTag = days !== null && days <= 120
    ? (days < 0 ? `(만료 ${Math.abs(days)}일)` : `(D-${days})`)
    : null;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 12, color, fontWeight: urgent || warn ? 600 : 400 }}>
        {value} {dTag && <span style={{ fontSize: 10 }}>{dTag}</span>}
      </div>
    </div>
  );
}

function PinnedCustomerCard({ customer, onClose }: { customer: PinnedCustomer; onClose: () => void }) {
  const name = customer["한글"] || `${customer["성"] || ""} ${customer["명"] || ""}`.trim() || "고객";
  const tel = [customer["연"], customer["락"], customer["처"]].filter(Boolean).join("-");
  const cardDays = getDaysUntil(customer["만기일"]);
  const passDays = getDaysUntil(customer["만기"]);

  return (
    <div style={{
      position: "fixed", right: 0, top: 56,
      width: 272, height: "calc(100vh - 56px)",
      background: "#fff", borderLeft: "2px solid #F5A623",
      boxShadow: "-3px 0 14px rgba(0,0,0,0.09)",
      zIndex: 150, display: "flex", flexDirection: "column",
      overflowY: "auto",
    }}>
      {/* 헤더 */}
      <div style={{
        padding: "11px 14px", borderBottom: "1px solid #E2E8F0",
        display: "flex", alignItems: "flex-start", justifyContent: "space-between",
        flexShrink: 0, background: "#FFFBF2",
      }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748" }}>{name}</div>
          <div style={{ fontSize: 10, color: "#C27800", marginTop: 2 }}>📌 참조 고정 중</div>
        </div>
        <button onClick={onClose} style={{ padding: 4, color: "#718096", flexShrink: 0 }}>
          <X size={14} />
        </button>
      </div>

      {/* 내용 */}
      <div style={{ padding: "14px", flex: 1 }}>
        {customer["국적"] && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 2 }}>국적</div>
            <div style={{ fontSize: 12, color: "#2D3748" }}>{customer["국적"]}</div>
          </div>
        )}
        {customer["V"] && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 2 }}>체류자격</div>
            <div style={{ fontSize: 12, color: "#2D3748", fontWeight: 600 }}>{customer["V"]}</div>
          </div>
        )}
        {tel && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 2 }}>연락처</div>
            <div style={{ fontSize: 12, color: "#2D3748" }}>{tel}</div>
          </div>
        )}

        <div style={{ borderTop: "1px solid #EDF2F7", margin: "10px 0" }} />

        {(customer["등록증"] || customer["번호"]) && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 2 }}>등록번호</div>
            <div style={{ fontSize: 12, color: "#2D3748", fontFamily: "monospace" }}>
              {[customer["등록증"], customer["번호"]].filter(Boolean).join(" - ")}
            </div>
          </div>
        )}
        <ExpiryLine label="등록증 만기" value={customer["만기일"]} days={cardDays} />

        <div style={{ borderTop: "1px solid #EDF2F7", margin: "10px 0" }} />

        {customer["여권"] && (
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 2 }}>여권번호</div>
            <div style={{ fontSize: 12, color: "#2D3748", fontFamily: "monospace" }}>{customer["여권"]}</div>
          </div>
        )}
        <ExpiryLine label="여권 만기" value={customer["만기"]} days={passDays} />

        {customer["주소"] && (
          <>
            <div style={{ borderTop: "1px solid #EDF2F7", margin: "10px 0" }} />
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 2 }}>주소</div>
              <div style={{ fontSize: 11, color: "#4A5568", lineHeight: 1.5 }}>{customer["주소"]}</div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

const SIDEBAR_COLLAPSED_KEY = "hw_sidebar_collapsed";

export default function MainLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [ready, setReady] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [pinnedCustomer, setPinnedCustomer] = useState<PinnedCustomer | null>(null);

  useEffect(() => {
    const saved = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (saved === "true") setCollapsed(true);
    if (!isLoggedIn()) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [router]);

  // 페이지 이동 시 스크롤 최상단 이동
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  // 고객카드 고정 이벤트 수신
  useEffect(() => {
    const handler = (e: Event) => setPinnedCustomer((e as CustomEvent<PinnedCustomer>).detail);
    window.addEventListener("pin-customer", handler);
    return () => window.removeEventListener("pin-customer", handler);
  }, []);

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
            marginRight: (!isMobile && pinnedCustomer) ? 272 : 0,
            transition: "margin-right 0.2s",
          }}
        >
          {children}
        </main>
      </div>

      {/* 고객카드 고정 패널 — 모바일에서는 숨김 */}
      {!isMobile && pinnedCustomer && (
        <PinnedCustomerCard
          customer={pinnedCustomer}
          onClose={() => setPinnedCustomer(null)}
        />
      )}
    </div>
  );
}
