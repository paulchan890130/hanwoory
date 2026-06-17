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
  const [status, setStatus] = useState<SecurityStatus | null>(null);
  const [notifs, setNotifs] = useState<SecurityNotificationRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    Promise.all([accountSecurityApi.myLoginEvents(30), accountSecurityApi.myNotifications(false)])
      .then(([ev, nt]) => { setEvents(ev.data.events); setStatus(ev.data.status); setNotifs(nt.data.notifications); })
      .catch(() => { /* graceful: 0021 미적용 등 → 빈 상태 유지 */ })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

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
      </div>
    </div>
  );
}
