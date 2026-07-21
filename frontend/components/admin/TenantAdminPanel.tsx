"use client";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { officeApplicationApi } from "@/lib/api";
import TenantPurgeModal from "@/components/admin/TenantPurgeModal";

// 시스템 관리자 — 사업장 관리: 사용자 없는(정리 대상) 사업장 조회, 기존 사업장에 새 관리자 발급,
// 계정 연결 변경(relink — 데이터는 이동하지 않음), 사업장 전체 폐기.

interface TenantSummaryLite {
  tenant_id: string; office_name: string; service_status: string; is_active: boolean;
  seat_limit: number; total_users: number; active_users: number; loginable_users: number;
  no_login_users: boolean; needs_cleanup: boolean;
  data_counts: Record<string, number>;
}

const origin = typeof window !== "undefined" ? window.location.origin : "";

export default function TenantAdminPanel() {
  const [tenants, setTenants] = useState<TenantSummaryLite[]>([]);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState("");
  const [busy, setBusy] = useState(false);
  const [issueFor, setIssueFor] = useState<TenantSummaryLite | null>(null);
  const [issueName, setIssueName] = useState("");
  const [issueEmail, setIssueEmail] = useState("");
  const [issued, setIssued] = useState<{ login: string; token: string } | null>(null);
  const [purgeFor, setPurgeFor] = useState<TenantSummaryLite | null>(null);
  // relink
  const [relinkLogin, setRelinkLogin] = useState("");
  const [relinkTarget, setRelinkTarget] = useState("");
  const [relinkPrev, setRelinkPrev] = useState<{ can_relink: boolean; blocking_reasons: string[];
    source_office_name?: string | null; target_office_name?: string | null } | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    officeApplicationApi.noUserTenants()
      .then((r) => { setTenants((r.data as { tenants: TenantSummaryLite[] }).tenants); setUnavailable(""); })
      .catch((e) => setUnavailable(e?.response?.status === 404
        ? "승인형 SaaS 기능이 비활성 상태입니다." : "목록을 불러오지 못했습니다."))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  const errMsg = (e: unknown) => (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "실패";

  const doIssue = async () => {
    if (!issueFor || !issueName.trim() || !issueEmail.trim()) { toast.error("이름과 이메일을 입력하세요."); return; }
    setBusy(true);
    try {
      const r = await officeApplicationApi.issueAdmin(issueFor.tenant_id, {
        name: issueName.trim(), email: issueEmail.trim(), confirm_tenant_id: issueFor.tenant_id,
      });
      setIssued({ login: (r.data as { login_id: string }).login_id, token: (r.data as { activation_token: string }).activation_token });
      toast.success("새 관리자 계정이 발급되었습니다.");
      setIssueFor(null); setIssueName(""); setIssueEmail(""); load();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  const doRelinkPreview = async () => {
    if (!relinkLogin.trim() || !relinkTarget.trim()) { toast.error("로그인 ID와 대상 사업장 ID를 입력하세요."); return; }
    try {
      const r = await officeApplicationApi.relinkPreview({ login_id: relinkLogin.trim(), target_tenant_id: relinkTarget.trim() });
      setRelinkPrev(r.data as typeof relinkPrev);
    } catch (e) { toast.error(errMsg(e)); }
  };
  const doRelink = async () => {
    if (!relinkPrev?.can_relink) return;
    if (!confirm("계정의 소속 사업장을 변경하시겠습니까? (고객·업무·분류 데이터는 이동하지 않습니다)")) return;
    setBusy(true);
    try {
      await officeApplicationApi.relink({
        login_id: relinkLogin.trim(), target_tenant_id: relinkTarget.trim(),
        confirm_login_id: relinkLogin.trim(), confirm_target_tenant_id: relinkTarget.trim(),
      });
      toast.success("연결이 변경되었습니다. 대상 계정은 초대 상태가 되며 활성화가 필요합니다.");
      setRelinkPrev(null); setRelinkLogin(""); setRelinkTarget(""); load();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  if (unavailable) return <div className="hw-card" style={{ fontSize: 13, color: "var(--hw-text-sub)" }}>{unavailable}</div>;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="hw-card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <div className="hw-card-title" style={{ marginBottom: 0 }}>
            로그인 사용자 없는 사업장 {tenants.length > 0 ? `${tenants.length}건` : ""}
          </div>
          <button className="btn-secondary" style={{ fontSize: 12 }} onClick={load}>새로고침</button>
        </div>
        <div style={{ fontSize: 12, color: "var(--hw-text-sub)", marginBottom: 8, lineHeight: 1.6 }}>
          연결 계정이 없거나 로그인 가능한 계정이 0명인 사업장입니다. 새 관리자를 발급해 운영을 복구하거나,
          실험용 사업장이면 전체 폐기할 수 있습니다. (사업장 데이터의 소속은 변경되지 않습니다.)
        </div>
        {loading ? <p style={{ fontSize: 13, color: "var(--hw-text-sub)" }}>불러오는 중...</p> :
          tenants.length === 0 ? <p style={{ fontSize: 13, color: "var(--hw-text-sub)" }}>정리 대상 사업장이 없습니다.</p> : (
            <div style={{ overflowX: "auto" }}>
              <table className="hw-table">
                <thead><tr><th>사무소</th><th>사업장 ID</th><th>상태</th><th>계정</th><th>고객</th><th>업무</th><th>관리</th></tr></thead>
                <tbody>
                  {tenants.map((t) => (
                    <tr key={t.tenant_id}>
                      <td style={{ fontWeight: 600 }}>{t.office_name}</td>
                      <td style={{ fontFamily: "monospace", fontSize: 11 }}>{t.tenant_id}</td>
                      <td>{t.service_status}</td>
                      <td>{t.total_users} (로그인 {t.loginable_users})</td>
                      <td>{t.data_counts?.customers ?? 0}</td>
                      <td>{(t.data_counts?.active_tasks ?? 0) + (t.data_counts?.completed_tasks ?? 0)}</td>
                      <td>
                        <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                          <button className="hw-filter-btn" disabled={busy} onClick={() => { setIssueFor(t); setIssued(null); }}>새 관리자 발급</button>
                          <button className="hw-filter-btn" style={{ color: "#C53030", borderColor: "#FEB2B2" }}
                            disabled={busy || t.service_status !== "suspended"}
                            title={t.service_status !== "suspended" ? "먼저 사업장을 정지하세요." : "사업장 전체 폐기"}
                            onClick={() => setPurgeFor(t)}>폐기</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

        {issueFor && (
          <div style={{ marginTop: 12, background: "var(--hw-gold-50)", border: "1px solid var(--hw-gold-200)", borderRadius: 8, padding: "12px 14px" }}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>새 관리자 발급 — {issueFor.office_name}</div>
            <div style={{ display: "grid", gap: 8 }}>
              <input className="hw-input" placeholder="새 관리자 이름" value={issueName} onChange={(e) => setIssueName(e.target.value)} />
              <input className="hw-input" placeholder="새 관리자 이메일(로그인 ID)" value={issueEmail} onChange={(e) => setIssueEmail(e.target.value)} />
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn-primary" style={{ fontSize: 13 }} disabled={busy} onClick={doIssue}>발급</button>
                <button className="btn-secondary" style={{ fontSize: 13 }} onClick={() => setIssueFor(null)}>취소</button>
              </div>
            </div>
          </div>
        )}

        {issued && (
          <div style={{ marginTop: 12, background: "var(--hw-gold-50)", border: "1px solid var(--hw-gold-200)", borderRadius: 8, padding: "10px 12px" }}>
            <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 4 }}>활성화 링크 (1회 표시 — {issued.login})</div>
            <code style={{ fontSize: 11, wordBreak: "break-all" }}>{`${origin}/activate/${issued.token}`}</code>
            <div style={{ marginTop: 6 }}>
              <button className="btn-secondary" style={{ fontSize: 12 }} onClick={() => { navigator.clipboard?.writeText(`${origin}/activate/${issued.token}`); toast.success("복사됨"); }}>링크 복사</button>
            </div>
          </div>
        )}
      </div>

      {/* 계정 연결 변경(relink) — 고급 기능 */}
      <div className="hw-card">
        <div className="hw-card-title">계정 연결 변경 (고급)</div>
        <div style={{ fontSize: 12, color: "var(--hw-text-sub)", marginBottom: 8, lineHeight: 1.6 }}>
          계정 연결 변경은 계정이 접근하는 사업장만 변경하며, 고객·업무·분류 데이터 자체는 이동하지 않습니다.
          기본 권장 동작은 “새 관리자 발급”입니다.
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          <input className="hw-input" placeholder="대상 계정 로그인 ID(이메일)" value={relinkLogin} onChange={(e) => { setRelinkLogin(e.target.value); setRelinkPrev(null); }} />
          <input className="hw-input" placeholder="이동할 사업장 ID(of-...)" value={relinkTarget} onChange={(e) => { setRelinkTarget(e.target.value); setRelinkPrev(null); }} />
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn-secondary" style={{ fontSize: 13 }} onClick={doRelinkPreview}>연결 가능 여부 확인</button>
            <button className="btn-primary" style={{ fontSize: 13 }} disabled={!relinkPrev?.can_relink || busy} onClick={doRelink}>연결 변경</button>
          </div>
          {relinkPrev && (
            relinkPrev.can_relink
              ? <div style={{ fontSize: 12.5, color: "#276749" }}>연결 가능: {relinkPrev.source_office_name} → {relinkPrev.target_office_name}</div>
              : <ul style={{ fontSize: 12.5, color: "#C53030", paddingLeft: 16 }}>{relinkPrev.blocking_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
          )}
        </div>
      </div>

      {purgeFor && (
        <TenantPurgeModal tenantId={purgeFor.tenant_id} officeName={purgeFor.office_name}
          onClose={() => setPurgeFor(null)} onDone={() => { setPurgeFor(null); load(); }} />
      )}
    </div>
  );
}
