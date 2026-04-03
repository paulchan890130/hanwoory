"use client";
import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Search, Bell, LogOut, X, Clock, User, ClipboardList, Calendar, FileText, BookOpen, BookMarked, Menu } from "lucide-react";
import { getUser, clearUser } from "@/lib/auth";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { customersApi } from "@/lib/api";

interface TopbarProps {
  leftOffset: number;
  isMobile?: boolean;
  onMobileMenuToggle?: () => void;
}

const RECENT_SEARCH_KEY = "hw_recent_searches";

function getRecentSearches(): string[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(RECENT_SEARCH_KEY) || "[]"); }
  catch { return []; }
}

function addRecentSearch(q: string) {
  if (!q.trim()) return;
  const prev = getRecentSearches().filter((s) => s !== q);
  localStorage.setItem(RECENT_SEARCH_KEY, JSON.stringify([q, ...prev].slice(0, 8)));
}

export default function Topbar({ leftOffset, isMobile, onMobileMenuToggle }: TopbarProps) {
  const router = useRouter();
  const qc = useQueryClient();
  const user = getUser();
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // 만기 알림 건수 (배지용)
  const { data: expiryData } = useQuery({
    queryKey: ["expiry-alerts"],
    queryFn: () => customersApi.expiryAlerts().then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });
  const alertCount =
    (expiryData?.card_alerts?.length ?? 0) +
    (expiryData?.passport_alerts?.length ?? 0);

  // 검색 열기 단축키: / 또는 Ctrl+K
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen(true);
      }
      if (e.key === "Escape") setSearchOpen(false);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // 검색창 열릴 때 포커스
  useEffect(() => {
    if (searchOpen) {
      setTimeout(() => inputRef.current?.focus(), 50);
    } else {
      setQuery("");
    }
  }, [searchOpen]);

  const handleSearch = (q?: string) => {
    const term = (q ?? query).trim();
    if (!term) return;
    addRecentSearch(term);
    setSearchOpen(false);
    router.push(`/search?q=${encodeURIComponent(term)}`);
  };

  const handleLogout = () => {
    qc.clear();   // wipe ALL cached queries before switching accounts
    clearUser();
    router.replace("/login");
  };

  const recentSearches = getRecentSearches();

  const QUICK_LINKS = [
    { label: "신규 고객",   href: "/customers?action=new",   icon: User },
    { label: "진행업무 추가", href: "/tasks?tab=active&action=new", icon: ClipboardList },
    { label: "OCR 스캔",   href: "/scan",                    icon: Search },
    { label: "일정 추가",   href: "/dashboard?action=event", icon: Calendar },
  ];

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
        {/* 데스크톱: 여백 스페이서 */}
        {!isMobile && <div style={{ flexShrink: 0, minWidth: 0 }} />}

        {/* 글로벌 검색창 - 반응형: 최소 160px, 최대 300px, 공간 부족 시 수축 */}
        <div className="hw-search-bar" style={{ flex: "1 1 auto", minWidth: 160, maxWidth: 300, overflow: "hidden" }}>
          <Search size={14} className="search-icon" />
          <input
            type="text"
            placeholder="통합 검색... (Ctrl+K)"
            readOnly
            onClick={() => setSearchOpen(true)}
            style={{ cursor: "pointer" }}
          />
        </div>

        {/* 알림 벨 */}
        <div style={{ position: "relative", flexShrink: 0, display: "inline-flex" }}>
          <button
            className="p-2 rounded-lg transition-colors"
            style={{ color: "#718096", display: "flex", alignItems: "center", justifyContent: "center" }}
            onClick={() => router.push("/dashboard")}
            title={alertCount > 0 ? `만기 알림 ${alertCount}건` : "알림 없음"}
          >
            <Bell size={18} />
          </button>
          {alertCount > 0 && (
            <span
              className="text-[10px] font-bold text-white flex items-center justify-center rounded-full"
              style={{
                background: "#E53E3E",
                minWidth: 16, height: 16, padding: "0 3px",
                position: "absolute", top: 2, right: 2,
                pointerEvents: "none",
                lineHeight: 1,
              }}
            >
              {alertCount > 99 ? "99+" : alertCount}
            </span>
          )}
        </div>

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

      {/* 검색 허브 오버레이 */}
      {searchOpen && (
        <div className="hw-search-overlay" onClick={() => setSearchOpen(false)}>
          <div
            className="hw-search-modal"
            onClick={(e) => e.stopPropagation()}
          >
            {/* 검색 입력 */}
            <div className="hw-search-modal-input">
              <Search size={18} style={{ color: "#A0AEC0", flexShrink: 0 }} />
              <input
                ref={inputRef}
                type="text"
                placeholder="고객·업무·게시글·일정·메모·업무참고 검색..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleSearch();
                  if (e.key === "Escape") setSearchOpen(false);
                }}
              />
              {query && (
                <button onClick={() => setQuery("")} style={{ color: "#A0AEC0" }}>
                  <X size={16} />
                </button>
              )}
            </div>

            <div style={{ maxHeight: 440, overflowY: "auto" }}>
              {/* 최근 검색어 */}
              {!query && recentSearches.length > 0 && (
                <div className="hw-search-result-group">
                  <div className="hw-search-result-header">최근 검색어</div>
                  {recentSearches.map((s) => (
                    <div
                      key={s}
                      className="hw-search-result-item"
                      onClick={() => handleSearch(s)}
                    >
                      <Clock size={13} style={{ color: "#A0AEC0", flexShrink: 0 }} />
                      <span>{s}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* 빠른 이동 (검색어 없을 때) */}
              {!query && (
                <div className="hw-search-result-group">
                  <div className="hw-search-result-header">빠른 이동</div>
                  {QUICK_LINKS.map(({ label, href, icon: Icon }) => (
                    <div
                      key={href}
                      className="hw-search-result-item"
                      onClick={() => { setSearchOpen(false); router.push(href); }}
                    >
                      <Icon size={13} style={{ color: "#F5A623", flexShrink: 0 }} />
                      <span>{label}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* 검색어 입력 시: 검색 실행 안내 */}
              {query && (
                <div className="hw-search-result-group">
                  <div
                    className="hw-search-result-item"
                    onClick={() => handleSearch()}
                    style={{ padding: "14px 20px" }}
                  >
                    <Search size={14} style={{ color: "#F5A623", flexShrink: 0 }} />
                    <span>
                      <strong>&quot;{query}&quot;</strong> 전체 검색
                    </span>
                    <span style={{ marginLeft: "auto", fontSize: 11, color: "#A0AEC0" }}>Enter</span>
                  </div>

                  {/* 카테고리별 빠른 검색 */}
                  {[
                    { label: "고객에서 검색", type: "customer", icon: User },
                    { label: "업무에서 검색", type: "task", icon: ClipboardList },
                    { label: "게시판에서 검색", type: "board", icon: BookOpen },
                    { label: "업무참고에서 검색", type: "reference", icon: BookMarked },
                    { label: "메모에서 검색", type: "memo", icon: FileText },
                  ].map(({ label, type, icon: Icon }) => (
                    <div
                      key={type}
                      className="hw-search-result-item"
                      onClick={() => {
                        addRecentSearch(query);
                        setSearchOpen(false);
                        router.push(`/search?q=${encodeURIComponent(query)}&type=${type}`);
                      }}
                    >
                      <Icon size={13} style={{ color: "#A0AEC0", flexShrink: 0 }} />
                      <span style={{ color: "#718096" }}>{label}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* 하단 단축키 안내 */}
            <div
              style={{
                padding: "10px 20px",
                borderTop: "1px solid #E2E8F0",
                fontSize: 11,
                color: "#A0AEC0",
                display: "flex",
                gap: 16,
              }}
            >
              <span><kbd style={{ background: "#F7FAFC", padding: "1px 5px", borderRadius: 4, border: "1px solid #E2E8F0" }}>↵</kbd> 검색</span>
              <span><kbd style={{ background: "#F7FAFC", padding: "1px 5px", borderRadius: 4, border: "1px solid #E2E8F0" }}>Esc</kbd> 닫기</span>
              <span><kbd style={{ background: "#F7FAFC", padding: "1px 5px", borderRadius: 4, border: "1px solid #E2E8F0" }}>Ctrl+K</kbd> 검색 열기</span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
