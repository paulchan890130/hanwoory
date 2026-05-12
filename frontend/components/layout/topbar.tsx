"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Bell, LogOut, Globe, Menu, PenLine } from "lucide-react";
import { getUser, clearUser } from "@/lib/auth";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { customersApi, api } from "@/lib/api";
import TempSlotModal from "@/components/TempSlotModal";

interface TopbarProps {
  leftOffset: number;
  isMobile?: boolean;
  onMobileMenuToggle?: () => void;
}

interface SlotInfo { slot: number; has_data: boolean; 비고: string; }

const SHORTCUTS = [
  { label: "하이코리아",     url: "https://www.hikorea.go.kr/Main.pt" },
  { label: "비자포털",       url: "https://www.visa.go.kr/openPage.do?MENU_ID=10301" },
  { label: "사회통합정보망", url: "https://www.socinet.go.kr/soci/main/main.jsp?MENU_TYPE=S_TOP_SY" },
  { label: "이민재단",       url: "https://www.kiiptest.org/index.html" },
];

export default function Topbar({ leftOffset, isMobile, onMobileMenuToggle }: TopbarProps) {
  const router = useRouter();
  const qc = useQueryClient();
  const user = getUser();

  const [shortcutOpen, setShortcutOpen] = useState(false);

  // 임시저장 슬롯 상태
  const [slots, setSlots] = useState<SlotInfo[]>([
    { slot: 1, has_data: false, 비고: "" },
    { slot: 2, has_data: false, 비고: "" },
    { slot: 3, has_data: false, 비고: "" },
  ]);
  const [activeSlot, setActiveSlot] = useState<SlotInfo | null>(null);

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

        {/* 여백 스페이서 */}
        <div style={{ flex: "1 1 auto" }} />

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

        {/* 바로가기 */}
        <button
          onClick={() => setShortcutOpen(true)}
          title="바로가기"
          style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: 6, borderRadius: 8,
            background: "none", border: "none", cursor: "pointer",
            color: "#718096", flexShrink: 0,
            transition: "background 0.15s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = "#EBF8FF";
            (e.currentTarget as HTMLButtonElement).style.color = "#2B6CB0";
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = "none";
            (e.currentTarget as HTMLButtonElement).style.color = "#718096";
          }}
        >
          <Globe size={18} />
        </button>

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
      </header>

      {/* 바로가기 팝업 */}
      {shortcutOpen && (
        <div
          style={{
            position: "fixed", inset: 0, zIndex: 300,
            background: "rgba(0,0,0,0.5)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}
          onClick={() => setShortcutOpen(false)}
        >
          <div
            style={{
              background: "#fff", borderRadius: 16,
              padding: "32px 28px",
              width: "min(480px, 92vw)",
              boxShadow: "0 8px 40px rgba(0,0,0,0.22)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ fontSize: 16, fontWeight: 700, color: "#1A202C", marginBottom: 20, textAlign: "center" }}>
              바로가기
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
              {SHORTCUTS.map(({ label, url }) => (
                <button
                  key={label}
                  onClick={() => { window.open(url, "_blank"); setShortcutOpen(false); }}
                  style={{
                    padding: "20px 16px", borderRadius: 12,
                    border: "1.5px solid #E2E8F0", background: "#F7FAFC",
                    cursor: "pointer", fontSize: 14, fontWeight: 600, color: "#2D3748",
                    transition: "all 0.15s", textAlign: "center",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background = "#EBF8FF";
                    (e.currentTarget as HTMLButtonElement).style.borderColor = "#90CDF4";
                    (e.currentTarget as HTMLButtonElement).style.color = "#2B6CB0";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background = "#F7FAFC";
                    (e.currentTarget as HTMLButtonElement).style.borderColor = "#E2E8F0";
                    (e.currentTarget as HTMLButtonElement).style.color = "#2D3748";
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
            <button
              onClick={() => setShortcutOpen(false)}
              style={{
                marginTop: 20, width: "100%", padding: "10px",
                borderRadius: 8, border: "1px solid #E2E8F0",
                background: "#fff", color: "#718096",
                fontSize: 13, cursor: "pointer", fontWeight: 600,
              }}
            >
              닫기
            </button>
          </div>
        </div>
      )}

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
    </>
  );
}
