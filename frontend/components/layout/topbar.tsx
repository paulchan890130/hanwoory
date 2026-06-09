"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Bell, LogOut, Menu, PenLine } from "lucide-react";
import { getUser, clearUser } from "@/lib/auth";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { customersApi, api, authApi } from "@/lib/api";
import TempSlotModal from "@/components/TempSlotModal";
import SignPadUrlModal from "@/components/SignPadUrlModal";

interface TopbarProps {
  leftOffset: number;
  isMobile?: boolean;
  onMobileMenuToggle?: () => void;
}

interface SlotInfo { slot: number; has_data: boolean; 비고: string; }

const SHORTCUTS = [
  { label: "하이코리아", url: "https://www.hikorea.go.kr/Main.pt" },
  { label: "비자포털",   url: "https://www.visa.go.kr/openPage.do?MENU_ID=10301" },
  { label: "사회통합",   url: "https://www.socinet.go.kr/soci/main/main.jsp?MENU_TYPE=S_TOP_SY" },
  { label: "이민재단",   url: "https://www.kiiptest.org/index.html" },
];

export default function Topbar({ leftOffset, isMobile, onMobileMenuToggle }: TopbarProps) {
  const router = useRouter();
  const qc = useQueryClient();
  const user = getUser();

  // 임시저장 슬롯 상태
  const [slots, setSlots] = useState<SlotInfo[]>([
    { slot: 1, has_data: false, 비고: "" },
    { slot: 2, has_data: false, 비고: "" },
    { slot: 3, has_data: false, 비고: "" },
  ]);
  const [activeSlot, setActiveSlot] = useState<SlotInfo | null>(null);
  const [showPadModal, setShowPadModal] = useState(false);

  const fetchSlots = () => {
    api.get<SlotInfo[]>("/api/signature/temp-slots")
      .then((r) => setSlots(r.data))
      .catch(() => {});
  };

  useEffect(() => {
    fetchSlots();
    const id = setInterval(fetchSlots, 30_000);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 만기 알림 건수 (배지용)
  const { data: expiryData } = useQuery({
    queryKey: ["expiry-alerts"],
    queryFn: () => customersApi.expiryAlerts().then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });
  const alertCount =
    (expiryData?.card_alerts?.length ?? 0) +
    (expiryData?.passport_alerts?.length ?? 0);

  const handleLogout = () => {
    // 단일 세션 모드: 현재 세션 revoke (best-effort). off면 서버 no-op.
    authApi.logout().catch(() => { /* 무시 — 로컬 정리는 계속 */ });
    qc.clear();
    clearUser();
    router.replace("/login");
  };

  return (
    <>
      {/* 상단바 */}
      <header
        className="hw-topbar"
        style={{ left: leftOffset }}
      >
        {/* 모바일: 햄버거 메뉴 */}
        {isMobile && (
          <button
            onClick={onMobileMenuToggle}
            style={{ color: "#4A5568", background: "none", border: "none", cursor: "pointer", padding: "4px 6px", display: "flex", alignItems: "center", flexShrink: 0 }}
          >
            <Menu size={20} />
          </button>
        )}

        {/* ── 왼쪽 그룹: 알람 + 임시서명 + 바로가기 ── */}
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>

          {/* 알람 벨 */}
          <div style={{ position: "relative", flexShrink: 0, display: "inline-flex" }}>
            <button
              style={{
                display: "flex", alignItems: "center", justifyContent: "center",
                padding: 6, borderRadius: 8,
                background: "none", border: "none", cursor: "pointer",
                color: alertCount > 0 ? "#E53E3E" : "#718096",
                transition: "background 0.15s",
              }}
              onClick={() => router.push("/dashboard")}
              title={alertCount > 0 ? `만기 알림 ${alertCount}건` : "알림 없음"}
              onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#FFF5F5"; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "none"; }}
            >
              <Bell size={18} />
            </button>
            {alertCount > 0 && (
              <span
                style={{
                  background: "#E53E3E", color: "#fff",
                  fontSize: 10, fontWeight: 700,
                  minWidth: 16, height: 16, padding: "0 3px",
                  borderRadius: "50%",
                  position: "absolute", top: 2, right: 2,
                  pointerEvents: "none",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  lineHeight: 1,
                }}
              >
                {alertCount > 99 ? "99+" : alertCount}
              </span>
            )}
          </div>

          {/* 서명 임시저장 슬롯 아이콘 */}
          {slots.map((s) => (
            <div
              key={s.slot}
              onClick={() => setActiveSlot(s)}
              style={{ position: "relative", cursor: "pointer", flexShrink: 0, display: "inline-flex", alignItems: "center", justifyContent: "center", padding: 4 }}
              title={`서명 슬롯 ${s.slot}번${s.has_data ? ` — ${s.비고 || "저장됨"}` : " — 비어있음"}`}
            >
              <PenLine size={18} style={{ color: "#718096" }} />
              <span style={{
                position: "absolute", top: 0, right: 0,
                width: 8, height: 8, borderRadius: "50%",
                background: s.has_data ? "#F5A623" : "#48BB78",
                border: "1.5px solid #fff",
              }} />
            </div>
          ))}

          {/* 서명패드 URL/QR 발급 — 로그인 직원 전용 */}
          <button
            onClick={() => setShowPadModal(true)}
            title="서명패드 URL/QR 발급 (태블릿 상시 서명용)"
            style={{
              flexShrink: 0, padding: "3px 8px", borderRadius: 5,
              border: "1px solid #E2E8F0", background: "#F7FAFC", color: "#4A5568",
              fontSize: 11, fontWeight: 500, cursor: "pointer", lineHeight: 1.4, whiteSpace: "nowrap",
            }}
          >
            서명패드
          </button>

          {/* 바로가기 버튼 — 원클릭 직접 열기 */}
          {SHORTCUTS.map(({ label, url }) => (
            <button
              key={label}
              onClick={() => window.open(url, "_blank")}
              title={label}
              style={{
                flexShrink: 0,
                padding: "3px 8px",
                borderRadius: 5,
                border: "1px solid #E2E8F0",
                background: "#F7FAFC",
                color: "#4A5568",
                fontSize: 11,
                fontWeight: 500,
                cursor: "pointer",
                lineHeight: 1.4,
                transition: "all 0.15s",
                whiteSpace: "nowrap",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = "#EBF8FF";
                (e.currentTarget as HTMLButtonElement).style.borderColor = "#90CDF4";
                (e.currentTarget as HTMLButtonElement).style.color = "#2B6CB0";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.background = "#F7FAFC";
                (e.currentTarget as HTMLButtonElement).style.borderColor = "#E2E8F0";
                (e.currentTarget as HTMLButtonElement).style.color = "#4A5568";
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {/* 가운데 스페이서 */}
        <div style={{ flex: "1 1 auto" }} />

        {/* ── 오른쪽 그룹: 사무소명 + 로그아웃 ── */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          {/* 사무소명 */}
          <span
            className="hidden sm:block text-[13px] truncate max-w-[140px]"
            style={{ color: "#4A5568" }}
          >
            {user?.office_name || user?.login_id}
          </span>

          {/* 로그아웃 */}
          <button
            onClick={handleLogout}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] transition-colors"
            style={{ color: "#718096" }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = "#FFF5F5";
              (e.currentTarget as HTMLButtonElement).style.color = "#C53030";
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.background = "transparent";
              (e.currentTarget as HTMLButtonElement).style.color = "#718096";
            }}
          >
            <LogOut size={14} />
            <span className="hidden sm:inline">로그아웃</span>
          </button>
        </div>
      </header>

      {/* 임시저장 슬롯 모달 */}
      {activeSlot && (
        <TempSlotModal
          slot={activeSlot.slot as 1 | 2 | 3}
          hasData={activeSlot.has_data}
          memo={activeSlot.비고}
          onClose={() => setActiveSlot(null)}
          onUpdate={() => { fetchSlots(); setActiveSlot(null); }}
        />
      )}

      {/* 서명패드 URL/QR 발급 모달 */}
      {showPadModal && <SignPadUrlModal onClose={() => setShowPadModal(false)} />}
    </>
  );
}
