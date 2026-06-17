"use client";
// 마이페이지 보안 섹션 — 내 최근 로그인 이력 + 보안 알림(읽음 처리).
import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { accountSecurityApi, type LoginEventRow, type SecurityNotificationRow, type SecurityStatus } from "@/lib/api";

const BORDER = "#E2E8F0";

const EVENT_LABEL: Record<string, string> = {
  LOGIN_SUCCESS: "로그인 성공", LOGIN_FAILED: "로그인 실패", LOGIN_LOCKED: "로그인 잠금",
  LOGOUT: "로그아웃", SESSION_REVOKED_BY_NEW_LOGIN: "다른 기기 로그인으로 세션 종료",
  SUSPICIOUS_LOGIN_DETECTED: "⚠️ 의심 로그인 감지", ACCOUNT_SECURITY_BLOCKED: "🚫 보안 차단",
  ACCOUNT_SECURITY_UNBLOCKED: "보안 차단 해제",
};

function fmt(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString("ko-KR", { hour12: false });
}

export default function MySecuritySection() {
  const [events, setEvents] = useState<LoginEventRow[]>([]);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [status, setStatus] = useState<SecurityStatus | null>(null);
  const [notifs, setNotifs] = useState<SecurityNotificationRow[]>([]);
  const [loading, setLoading] = useState(true);

  // 로그인 이력: 서버 페이지네이션(최신순 20건/페이지, 이전·다음). 본인 것만.
  const loadEvents = useCallback((p: number) => {
    setLoading(true);
    accountSecurityApi.myLoginEvents(p)
      .then((ev) => { setEvents(ev.data.events); setStatus(ev.data.status); setPage(ev.data.page); setHasNext(ev.data.has_next); })
      .catch(() => { /* graceful: 미적용/오류 → 빈 상태 유지 */ })
      .finally(() => setLoading(false));
  }, []);

  const loadNotifs = useCallback(() => {
    accountSecurityApi.myNotifications(false)
      .then((nt) => setNotifs(nt.data.notifications))
      .catch(() => { /* graceful */ });
  }, []);

  useEffect(() => { loadEvents(1); loadNotifs(); }, [loadEvents, loadNotifs]);

  const markRead = (id: number) => {
    accountSecurityApi.myMarkRead(id)
      .then(() => setNotifs((p) => p.map((n) => (n.id === id ? { ...n, is_read: true } : n))))
      .catch(() => toast.error("처리 실패"));
  };

  const cell: React.CSSProperties = { padding: "6px 8px", fontSize: 12, borderBottom: `1px solid ${BORDER}` };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {status?.security_blocked && (
        <div style={{ padding: 10, borderRadius: 8, background: "#FFF5F5", border: "1px solid #FEB2B2", color: "#C53030", fontSize: 13 }}>
          🚫 계정공유 의심 누적으로 보안 차단된 상태입니다. 관리자 확인 후 이용할 수 있습니다.
        </div>
      )}

      {/* 보안 알림 */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#4A5568", marginBottom: 6 }}>내 보안 알림</div>
        {notifs.length === 0 ? (
          <div style={{ fontSize: 12, color: "#A0AEC0" }}>{loading ? "불러오는 중…" : "알림이 없습니다."}</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {notifs.map((n) => (
              <div key={n.id} style={{
                padding: "8px 10px", borderRadius: 8, fontSize: 12,
                border: `1px solid ${n.is_read ? BORDER : "#FBD38D"}`,
                background: n.is_read ? "#fff" : "#FFFAF0",
                display: "flex", justifyContent: "space-between", gap: 8,
              }}>
                <div>
                  <div style={{ fontWeight: 700, color: "#2D3748" }}>{n.title}</div>
                  <div style={{ color: "#718096", marginTop: 2 }}>{n.body}</div>
                  <div style={{ color: "#A0AEC0", marginTop: 2, fontSize: 11 }}>{fmt(n.created_at)}</div>
                </div>
                {!n.is_read && (
                  <button onClick={() => markRead(n.id)} style={{
                    flexShrink: 0, alignSelf: "center", fontSize: 11, padding: "4px 8px",
                    border: `1px solid ${BORDER}`, borderRadius: 6, background: "#F7FAFC", cursor: "pointer", color: "#4A5568",
                  }}>읽음</button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 로그인 이력 */}
      <div>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#4A5568", marginBottom: 6 }}>내 최근 로그인 이력</div>
        <div style={{ overflowX: "auto", border: `1px solid ${BORDER}`, borderRadius: 8 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "#F7FAFC" }}>
                <th style={{ ...cell, textAlign: "left", fontWeight: 700 }}>이벤트</th>
                <th style={{ ...cell, textAlign: "left", fontWeight: 700 }}>IP</th>
                <th style={{ ...cell, textAlign: "left", fontWeight: 700 }}>브라우저</th>
                <th style={{ ...cell, textAlign: "left", fontWeight: 700 }}>시각</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 ? (
                <tr><td style={cell} colSpan={4}>{loading ? "불러오는 중…" : "이력이 없습니다."}</td></tr>
              ) : events.map((e, i) => (
                <tr key={i}>
                  <td style={{ ...cell, color: e.risk_level === "suspicious" || e.risk_level === "blocked" ? "#C53030" : "#2D3748" }}>
                    {EVENT_LABEL[e.event_type] ?? e.event_type}
                  </td>
                  <td style={cell}>{e.ip_prefix_masked || "-"}</td>
                  <td style={cell}>{e.user_agent_summary || "-"}</td>
                  <td style={cell}>{fmt(e.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {(page > 1 || hasNext) && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, justifyContent: "flex-end" }}>
            <button disabled={page <= 1 || loading} onClick={() => loadEvents(page - 1)}
              style={{ fontSize: 12, padding: "4px 12px", borderRadius: 6, border: `1px solid ${BORDER}`,
                background: page <= 1 || loading ? "#F7FAFC" : "#fff", color: page <= 1 || loading ? "#CBD5E0" : "#4A5568",
                cursor: page <= 1 || loading ? "not-allowed" : "pointer" }}>이전</button>
            <span style={{ fontSize: 12, color: "#718096" }}>페이지 {page}</span>
            <button disabled={!hasNext || loading} onClick={() => loadEvents(page + 1)}
              style={{ fontSize: 12, padding: "4px 12px", borderRadius: 6, border: `1px solid ${BORDER}`,
                background: !hasNext || loading ? "#F7FAFC" : "#fff", color: !hasNext || loading ? "#CBD5E0" : "#4A5568",
                cursor: !hasNext || loading ? "not-allowed" : "pointer" }}>다음</button>
          </div>
        )}
      </div>
    </div>
  );
}
