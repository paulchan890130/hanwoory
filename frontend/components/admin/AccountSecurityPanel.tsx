"use client";
// 관리자 보안/로그인 이력 패널 — 계정별 이력·상태 조회 + 보안차단 해제 + 관리자 알림.
import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { accountSecurityApi, type LoginEventRow, type SecurityNotificationRow, type SecurityStatus } from "@/lib/api";

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

export default function AccountSecurityPanel() {
  const [loginId, setLoginId] = useState("");
  const [events, setEvents] = useState<LoginEventRow[]>([]);
  const [status, setStatus] = useState<SecurityStatus | null>(null);
  const [notifs, setNotifs] = useState<SecurityNotificationRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [onlySuspicious, setOnlySuspicious] = useState(false);

  const loadNotifs = useCallback(() => {
    accountSecurityApi.adminNotifications(false)
      .then((r) => setNotifs(r.data.notifications)).catch(() => {});
  }, []);
  useEffect(() => { loadNotifs(); }, [loadNotifs]);

  const search = () => {
    const id = loginId.trim();
    if (!id) { toast.error("login_id를 입력하세요."); return; }
    setLoading(true);
    accountSecurityApi.adminLoginEvents(id, 80)
      .then((r) => { setEvents(r.data.events); setStatus(r.data.status); })
      .catch(() => toast.error("조회 실패"))
      .finally(() => setLoading(false));
  };

  const unblock = () => {
    const id = loginId.trim();
    if (!id) return;
    if (!confirm(`'${id}' 계정의 보안 차단을 해제하고 의심 카운트를 초기화합니다.`)) return;
    accountSecurityApi.adminUnblock(id)
      .then((r) => { setStatus(r.data.status); toast.success("보안 차단 해제됨"); loadNotifs(); })
      .catch(() => toast.error("해제 실패"));
  };

  const cell: React.CSSProperties = { padding: "6px 8px", fontSize: 12, borderBottom: `1px solid ${BORDER}` };
  const shownEvents = onlySuspicious
    ? events.filter((e) => e.risk_level === "suspicious" || e.risk_level === "blocked" || e.event_type === "SUSPICIOUS_LOGIN_DETECTED")
    : events;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <div style={{ fontSize: 15, fontWeight: 800, color: "#1A202C" }}>🔐 로그인 보안 / 계정공유 의심</div>

      {/* 관리자 알림 */}
      {notifs.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#4A5568" }}>보안 알림 ({notifs.filter(n => !n.is_read).length} 안읽음)</div>
          {notifs.slice(0, 8).map((n) => (
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
      )}

      {/* 검색 */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <input value={loginId} onChange={(e) => setLoginId(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") search(); }}
          placeholder="login_id"
          style={{ height: 32, padding: "0 10px", border: `1px solid ${BORDER}`, borderRadius: 6, fontSize: 13, width: 200 }} />
        <button onClick={search} style={{ height: 32, padding: "0 12px", borderRadius: 6, border: "1px solid #4A5568", background: "#4A5568", color: "#fff", fontSize: 12, fontWeight: 700, cursor: "pointer" }}>이력 조회</button>
        <label style={{ fontSize: 12, color: "#718096", display: "flex", alignItems: "center", gap: 4 }}>
          <input type="checkbox" checked={onlySuspicious} onChange={(e) => setOnlySuspicious(e.target.checked)} /> 의심만
        </label>
        {status && (
          <span style={{
            fontSize: 12, fontWeight: 700, padding: "3px 10px", borderRadius: 12,
            background: status.security_blocked ? "#FED7D7" : "#C6F6D5",
            color: status.security_blocked ? "#C53030" : "#276749",
          }}>
            {status.security_blocked ? `보안차단 (의심 ${status.suspicion_count})` : `정상 (의심 ${status.suspicion_count})`}
          </span>
        )}
        {status?.security_blocked && (
          <button onClick={unblock} style={{ height: 32, padding: "0 12px", borderRadius: 6, border: "1px solid #C53030", background: "#fff", color: "#C53030", fontSize: 12, fontWeight: 700, cursor: "pointer" }}>차단 해제</button>
        )}
      </div>

      {/* 이력 테이블 */}
      <div style={{ overflowX: "auto", border: `1px solid ${BORDER}`, borderRadius: 8 }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ background: "#F7FAFC" }}>
              {["이벤트", "IP", "브라우저", "사유", "시각"].map((h) => (
                <th key={h} style={{ ...cell, textAlign: "left", fontWeight: 700 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shownEvents.length === 0 ? (
              <tr><td style={cell} colSpan={5}>{loading ? "불러오는 중…" : "조회 결과 없음 (login_id 입력 후 조회)"}</td></tr>
            ) : shownEvents.map((e, i) => (
              <tr key={i}>
                <td style={{ ...cell, color: e.risk_level === "suspicious" || e.risk_level === "blocked" ? "#C53030" : "#2D3748" }}>
                  {EVENT_LABEL[e.event_type] ?? e.event_type}
                </td>
                <td style={cell}>{e.ip_prefix_masked || "-"}</td>
                <td style={cell}>{e.user_agent_summary || "-"}</td>
                <td style={cell}>{e.reason || "-"}</td>
                <td style={cell}>{fmt(e.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
