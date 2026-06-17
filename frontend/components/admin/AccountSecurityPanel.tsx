"use client";
// 관리자 보안/로그인 이력 패널.
// 전체 로딩 금지: 각 목록을 서버 페이지네이션(최신순 20건/페이지, 이전·다음)으로 조회한다.
// 차단계정은 목록에서 바로 해제. login_id 검색은 특정 계정 상세 조회용(검색+페이지 동시 동작).
import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import {
  accountSecurityApi,
  type LoginEventRow, type SecurityNotificationRow, type SecurityStatus, type BlockedAccountRow,
} from "@/lib/api";

const BORDER = "#E2E8F0";
const EVENT_LABEL: Record<string, string> = {
  LOGIN_SUCCESS: "로그인 성공", LOGIN_FAILED: "로그인 실패", LOGIN_LOCKED: "로그인 잠금",
  LOGOUT: "로그아웃", SESSION_REVOKED_BY_NEW_LOGIN: "새 로그인으로 세션 종료",
  SUSPICIOUS_LOGIN_DETECTED: "⚠️ 의심 로그인 감지", ACCOUNT_SECURITY_BLOCKED: "🚫 보안 차단",
  ACCOUNT_SECURITY_UNBLOCKED: "보안 차단 해제",
};
function fmt(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString("ko-KR", { hour12: false });
}
const isRisky = (e: LoginEventRow) =>
  e.risk_level === "suspicious" || e.risk_level === "blocked" || e.event_type === "SUSPICIOUS_LOGIN_DETECTED";

// 이전/다음 페이저(서버 has_next 기반). loading 중엔 비활성.
function Pager({ page, hasNext, loading, onPrev, onNext }: {
  page: number; hasNext: boolean; loading: boolean; onPrev: () => void; onNext: () => void;
}) {
  const btn: React.CSSProperties = {
    fontSize: 12, padding: "4px 12px", borderRadius: 6, border: `1px solid ${BORDER}`,
    background: "#fff", color: "#4A5568", cursor: "pointer",
  };
  const disabledBtn: React.CSSProperties = { ...btn, color: "#CBD5E0", cursor: "not-allowed", background: "#F7FAFC" };
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, justifyContent: "flex-end" }}>
      <button style={page <= 1 || loading ? disabledBtn : btn} disabled={page <= 1 || loading} onClick={onPrev}>이전</button>
      <span style={{ fontSize: 12, color: "#718096" }}>페이지 {page}</span>
      <button style={!hasNext || loading ? disabledBtn : btn} disabled={!hasNext || loading} onClick={onNext}>다음</button>
    </div>
  );
}

export default function AccountSecurityPanel() {
  // 최근 로그인/보안 이벤트
  const [recent, setRecent] = useState<LoginEventRow[]>([]);
  const [recentPage, setRecentPage] = useState(1);
  const [recentHasNext, setRecentHasNext] = useState(false);
  const [loadingRecent, setLoadingRecent] = useState(true);
  const [onlySuspicious, setOnlySuspicious] = useState(false);

  // 차단 계정
  const [blocked, setBlocked] = useState<BlockedAccountRow[]>([]);
  const [blockedPage, setBlockedPage] = useState(1);
  const [blockedHasNext, setBlockedHasNext] = useState(false);
  const [loadingBlocked, setLoadingBlocked] = useState(true);

  // 보안 알림
  const [notifs, setNotifs] = useState<SecurityNotificationRow[]>([]);
  const [notifPage, setNotifPage] = useState(1);
  const [notifHasNext, setNotifHasNext] = useState(false);

  // 특정 계정 상세 조회
  const [loginId, setLoginId] = useState("");
  const [events, setEvents] = useState<LoginEventRow[] | null>(null);
  const [eventsPage, setEventsPage] = useState(1);
  const [eventsHasNext, setEventsHasNext] = useState(false);
  const [status, setStatus] = useState<SecurityStatus | null>(null);
  const [searching, setSearching] = useState(false);

  const loadRecent = useCallback((page: number) => {
    setLoadingRecent(true);
    accountSecurityApi.adminRecentEvents(onlySuspicious, page)
      .then((r) => { setRecent(r.data.events); setRecentPage(r.data.page); setRecentHasNext(r.data.has_next); })
      .catch(() => { /* graceful */ })
      .finally(() => setLoadingRecent(false));
  }, [onlySuspicious]);

  const loadBlocked = useCallback((page: number) => {
    setLoadingBlocked(true);
    accountSecurityApi.adminBlockedAccounts(page)
      .then((r) => { setBlocked(r.data.blocked); setBlockedPage(r.data.page); setBlockedHasNext(r.data.has_next); })
      .catch(() => { /* graceful */ })
      .finally(() => setLoadingBlocked(false));
  }, []);

  const loadNotifs = useCallback((page: number) => {
    accountSecurityApi.adminNotifications(false, page)
      .then((r) => { setNotifs(r.data.notifications); setNotifPage(r.data.page); setNotifHasNext(r.data.has_next); })
      .catch(() => { /* graceful */ });
  }, []);

  // 최초 + 필터(의심만) 변경 시 1페이지부터 재조회.
  useEffect(() => { loadRecent(1); }, [loadRecent]);
  useEffect(() => { loadBlocked(1); loadNotifs(1); }, [loadBlocked, loadNotifs]);

  const search = useCallback((page: number) => {
    const id = loginId.trim();
    if (!id) { toast.error("login_id를 입력하세요."); return; }
    setSearching(true);
    accountSecurityApi.adminLoginEvents(id, page)
      .then((r) => { setEvents(r.data.events); setStatus(r.data.status); setEventsPage(r.data.page); setEventsHasNext(r.data.has_next); })
      .catch(() => toast.error("조회 실패"))
      .finally(() => setSearching(false));
  }, [loginId]);

  const unblock = (id: string) => {
    if (!confirm(`'${id}' 계정의 보안 차단을 해제하고 의심 카운트를 초기화합니다.`)) return;
    accountSecurityApi.adminUnblock(id)
      .then(() => {
        toast.success(`${id} 보안 차단 해제됨`);
        loadBlocked(1);                                  // 차단 목록 새로고침(1페이지)
        if (loginId.trim() === id) search(eventsPage);   // 상세 조회 중이면 상태 갱신
      })
      .catch(() => toast.error("해제 실패"));
  };

  const cell: React.CSSProperties = { padding: "6px 8px", fontSize: 12, borderBottom: `1px solid ${BORDER}` };
  const th: React.CSSProperties = { ...cell, textAlign: "left", fontWeight: 700 };
  const sectionTitle: React.CSSProperties = { fontSize: 13, fontWeight: 800, color: "#2D3748", margin: "4px 0 6px" };

  const renderEventsTable = (rows: LoginEventRow[], showAccount: boolean, emptyMsg: string) => (
    <div style={{ overflowX: "auto", border: `1px solid ${BORDER}`, borderRadius: 8 }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ background: "#F7FAFC" }}>
            {showAccount && <th style={th}>계정</th>}
            <th style={th}>이벤트</th><th style={th}>IP</th><th style={th}>브라우저</th>
            <th style={th}>사유</th><th style={th}>시각</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td style={cell} colSpan={showAccount ? 6 : 5}>{emptyMsg}</td></tr>
          ) : rows.map((e, i) => (
            <tr key={i} style={isRisky(e) ? { background: "#FFFAF0" } : undefined}>
              {showAccount && <td style={{ ...cell, fontWeight: 600 }}>{e.login_id}{e.tenant_id ? ` · ${e.tenant_id}` : ""}</td>}
              <td style={{ ...cell, color: isRisky(e) ? "#C53030" : "#2D3748" }}>{EVENT_LABEL[e.event_type] ?? e.event_type}</td>
              <td style={cell}>{e.ip_prefix_masked || "-"}</td>
              <td style={cell}>{e.user_agent_summary || "-"}</td>
              <td style={cell}>{e.reason || "-"}</td>
              <td style={cell}>{fmt(e.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <div style={{ fontSize: 15, fontWeight: 800, color: "#1A202C" }}>🔐 로그인 보안 / 계정공유 의심</div>

      {/* 차단 계정 목록 — 페이지 단위 + 행별 해제 */}
      <div>
        <div style={sectionTitle}>차단 계정</div>
        {blocked.length === 0 ? (
          <div style={{ fontSize: 12, color: "#A0AEC0", padding: "8px 10px", border: `1px dashed ${BORDER}`, borderRadius: 8 }}>
            {loadingBlocked ? "불러오는 중…" : (blockedPage > 1 ? "더 이상 차단 계정이 없습니다." : "현재 차단 계정 없음")}
          </div>
        ) : (
          <div style={{ overflowX: "auto", border: "1px solid #FEB2B2", borderRadius: 8 }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ background: "#FFF5F5" }}>
                <th style={th}>계정</th><th style={th}>의심횟수</th><th style={th}>차단시각</th><th style={th}>사유</th><th style={th}>해제</th>
              </tr></thead>
              <tbody>
                {blocked.map((b) => (
                  <tr key={b.login_id}>
                    <td style={{ ...cell, fontWeight: 700 }}>{b.login_id}{b.tenant_id ? ` · ${b.tenant_id}` : ""}</td>
                    <td style={cell}>{b.suspicion_count}</td>
                    <td style={cell}>{b.blocked_at ? fmt(b.blocked_at) : "-"}</td>
                    <td style={cell}>{b.blocked_reason || "-"}</td>
                    <td style={cell}>
                      <button onClick={() => unblock(b.login_id)} style={{
                        fontSize: 12, fontWeight: 700, padding: "4px 10px", borderRadius: 6,
                        border: "1px solid #C53030", background: "#fff", color: "#C53030", cursor: "pointer",
                      }}>차단 해제</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {(blockedPage > 1 || blockedHasNext) && (
          <Pager page={blockedPage} hasNext={blockedHasNext} loading={loadingBlocked}
            onPrev={() => loadBlocked(blockedPage - 1)} onNext={() => loadBlocked(blockedPage + 1)} />
        )}
      </div>

      {/* 보안 알림 */}
      {(notifs.length > 0 || notifPage > 1) && (
        <div>
          <div style={sectionTitle}>보안 알림</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {notifs.length === 0 ? (
              <div style={{ fontSize: 12, color: "#A0AEC0" }}>이 페이지에는 알림이 없습니다.</div>
            ) : notifs.map((n) => (
              <div key={n.id} style={{
                padding: "6px 10px", borderRadius: 6, fontSize: 12,
                border: `1px solid ${n.type === "blocked" ? "#FEB2B2" : BORDER}`,
                background: n.type === "blocked" ? "#FFF5F5" : "#fff",
                display: "flex", justifyContent: "space-between", gap: 8,
              }}>
                <span><strong>{n.title}</strong> — {n.body}</span>
                <span style={{ flexShrink: 0, color: "#A0AEC0", fontSize: 11 }}>{fmt(n.created_at)}</span>
              </div>
            ))}
          </div>
          {(notifPage > 1 || notifHasNext) && (
            <Pager page={notifPage} hasNext={notifHasNext} loading={false}
              onPrev={() => loadNotifs(notifPage - 1)} onNext={() => loadNotifs(notifPage + 1)} />
          )}
        </div>
      )}

      {/* 최근 로그인/보안 이벤트 — 페이지 단위 */}
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <span style={sectionTitle}>최근 로그인/보안 이벤트</span>
          <label style={{ fontSize: 12, color: "#718096", display: "flex", alignItems: "center", gap: 4 }}>
            <input type="checkbox" checked={onlySuspicious} onChange={(e) => setOnlySuspicious(e.target.checked)} /> 의심만
          </label>
          <button onClick={() => loadRecent(1)} style={{ fontSize: 11, padding: "3px 8px", border: `1px solid ${BORDER}`, borderRadius: 6, background: "#F7FAFC", cursor: "pointer", color: "#4A5568" }}>새로고침</button>
        </div>
        {renderEventsTable(recent, true, loadingRecent ? "불러오는 중…" : "최근 이벤트가 없습니다.")}
        <Pager page={recentPage} hasNext={recentHasNext} loading={loadingRecent}
          onPrev={() => loadRecent(recentPage - 1)} onNext={() => loadRecent(recentPage + 1)} />
      </div>

      {/* 특정 계정 상세 검색 */}
      <div>
        <div style={sectionTitle}>특정 계정 상세 조회</div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
          <input value={loginId} onChange={(e) => setLoginId(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") search(1); }} placeholder="login_id"
            style={{ height: 32, padding: "0 10px", border: `1px solid ${BORDER}`, borderRadius: 6, fontSize: 13, width: 200 }} />
          <button onClick={() => search(1)} disabled={searching} style={{ height: 32, padding: "0 12px", borderRadius: 6, border: "1px solid #4A5568", background: "#4A5568", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer" }}>조회</button>
          {status && (
            <span style={{
              fontSize: 12, fontWeight: 700, padding: "3px 10px", borderRadius: 12,
              background: status.security_blocked ? "#FED7D7" : "#C6F6D5",
              color: status.security_blocked ? "#C53030" : "#276749",
            }}>{status.security_blocked ? `보안차단 (의심 ${status.suspicion_count})` : `정상 (의심 ${status.suspicion_count})`}</span>
          )}
          {status?.security_blocked && (
            <button onClick={() => unblock(loginId.trim())} style={{ height: 32, padding: "0 12px", borderRadius: 6, border: "1px solid #C53030", background: "#fff", color: "#C53030", fontSize: 12, fontWeight: 700, cursor: "pointer" }}>차단 해제</button>
          )}
        </div>
        {events !== null && (
          <>
            {renderEventsTable(events, false, searching ? "불러오는 중…" : "해당 계정 이벤트 없음")}
            <Pager page={eventsPage} hasNext={eventsHasNext} loading={searching}
              onPrev={() => search(eventsPage - 1)} onNext={() => search(eventsPage + 1)} />
          </>
        )}
      </div>
    </div>
  );
}
