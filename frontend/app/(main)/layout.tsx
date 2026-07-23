"use client";
import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { isLoggedIn, getUser } from "@/lib/auth";
import { authApi, manualApi, type ManualAlert } from "@/lib/api";
import Sidebar, {
  SIDEBAR_EXPANDED_WIDTH,
  SIDEBAR_COLLAPSED_WIDTH,
} from "@/components/layout/sidebar";
import Topbar from "@/components/layout/topbar";
import OnboardingController from "@/components/onboarding/OnboardingController";
import ProfileIncompleteBanner from "@/components/onboarding/ProfileIncompleteBanner";
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
      background: "#fff", borderLeft: "2px solid #D4A843",
      boxShadow: "-3px 0 14px rgba(0,0,0,0.09)",
      zIndex: 150, display: "flex", flexDirection: "column",
      overflowY: "auto",
    }}>
      {/* 헤더 */}
      <div style={{
        padding: "11px 14px", borderBottom: "1px solid #E2E8F0",
        display: "flex", alignItems: "flex-start", justifyContent: "space-between",
        flexShrink: 0, background: "#FFF9E6",
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

// ── 매뉴얼 업데이트 알림 모달 — 로그인 후 최초 1회(세션당), 미확인 active 알림이 있으면 표시 ──
function ManualUpdateAlertModal() {
  const router = useRouter();
  const [alerts, setAlerts] = useState<ManualAlert[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const u = getUser();
    const key = `manual_alert_shown_${u?.login_id ?? ""}`;
    if (sessionStorage.getItem(key) === "1") return;   // 이번 세션엔 이미 확인 → 나브마다 재팝업 방지
    manualApi.activeAlerts()
      .then((r) => {
        if (r.data?.alerts?.length) {
          setAlerts(r.data.alerts);
          setIsAdmin(!!r.data.is_admin);
          setShow(true);
        }
        sessionStorage.setItem(key, "1");
      })
      .catch(() => {/* 무시 — 알림 실패가 앱을 막지 않게 */});
  }, []);

  if (!show || alerts.length === 0) return null;
  const a = alerts[0];

  const dismissAll = async () => {
    setBusy(true);
    try { await Promise.all(alerts.map((x) => manualApi.dismissAlert(x.id))); } catch { /* 무시 */ }
    setBusy(false);
    setShow(false);
  };
  const confirm = () => { setShow(false); if (isAdmin) router.push("/admin"); };

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 2000,
      display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <div style={{ width: 460, maxWidth: "94vw", background: "#fff", borderRadius: 14,
        border: "1px solid #EAD9A8", boxShadow: "0 12px 36px rgba(0,0,0,0.18)", overflow: "hidden" }}>
        <div style={{ background: "#FBF8F0", borderBottom: "1px solid #EAD9A8", padding: "14px 18px" }}>
          <div style={{ fontSize: 14, fontWeight: 800, color: "#8A6D1F" }}>📢 새 매뉴얼 업데이트가 감지되었습니다</div>
        </div>
        <div style={{ padding: "16px 18px", fontSize: 13, color: "#2D3748", lineHeight: 1.7 }}>
          <div style={{ marginBottom: 8 }}>
            <b>{a.manual_kr}</b> 매뉴얼 첨부파일 제목이 변경되었습니다
            {a.version_label ? <span style={{ color: "#A0AEC0" }}> (버전 {a.version_label})</span> : null}.
            {alerts.length > 1 && <span style={{ color: "#A0AEC0" }}> 외 {alerts.length - 1}건</span>}
          </div>
          <div style={{ fontSize: 12, color: "#4A5568" }}>
            {isAdmin
              ? "관리자 화면에서 최신 PDF를 업로드하고 변경사항을 검토해 주세요."
              : "업무 기준이 변경되었을 수 있으므로 관리자 확인 전까지 주의해 주세요."}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", padding: "0 18px 16px", flexWrap: "wrap" }}>
          <button type="button" onClick={dismissAll} disabled={busy}
            style={{ padding: "8px 12px", borderRadius: 8, border: "1px solid #E2E8F0", background: "#fff",
              color: "#718096", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
            이번 업데이트 다시 알리지 않음
          </button>
          <button type="button" onClick={confirm} disabled={busy}
            style={{ padding: "8px 14px", borderRadius: 8, border: "1px solid var(--hw-gold-soft-border)", background: "var(--hw-gold-soft-bg)",
              color: "var(--hw-gold-soft-text)", fontSize: 12, fontWeight: 700, cursor: "pointer" }}>
            {isAdmin ? "매뉴얼 업데이트 확인" : "확인"}
          </button>
        </div>
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

  // 비활성/삭제 계정 자동 로그아웃 — 진입 시 + 탭 focus/visibility + 45초 주기로 상태 재확인.
  // 비활성화된 계정이면 API를 직접 누르지 않아도 401(ACCOUNT_DISABLED) → api.ts 인터셉터가
  // 토큰을 정리하고 /login 으로 보낸다(여기선 호출만 트리거).
  useEffect(() => {
    if (!ready) return;
    let stopped = false;
    const check = () => { if (!stopped && isLoggedIn()) authApi.me().catch(() => {}); };
    check();
    const onVisible = () => { if (document.visibilityState === "visible") check(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", check);
    const intervalId = window.setInterval(check, 45_000);
    return () => {
      stopped = true;
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", check);
      window.clearInterval(intervalId);
    };
  }, [ready]);

  // 고객카드 고정 이벤트 수신
  useEffect(() => {
    const handler = (e: Event) => setPinnedCustomer((e as CustomEvent<PinnedCustomer>).detail);
    window.addEventListener("pin-customer", handler);
    return () => window.removeEventListener("pin-customer", handler);
  }, []);

  // 온보딩 투어가 모바일 사이드바 대상을 강조할 때 드로어를 연다.
  useEffect(() => {
    const open = () => { if (window.innerWidth < 768) setMobileDrawerOpen(true); };
    window.addEventListener("onboarding-open-sidebar", open);
    return () => window.removeEventListener("onboarding-open-sidebar", open);
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
        style={{
          marginLeft: mainMarginLeft,
          transition: "margin-left 0.2s",
          // overlay가 사이드바 오른쪽부터 시작하도록 CSS 변수 제공
          ...({ "--hw-main-left": `${mainMarginLeft}px` } as React.CSSProperties),
        }}
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
          <ProfileIncompleteBanner />
          {children}
        </main>
      </div>

      {/* 매뉴얼 업데이트 알림 — 로그인 후 최초 1회(세션당) */}
      <ManualUpdateAlertModal />

      {/* 최초 로그인 온보딩(사용법 안내) 투어 */}
      <OnboardingController />

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
