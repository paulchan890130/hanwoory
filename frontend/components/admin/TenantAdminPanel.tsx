"use client";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { officeApplicationApi } from "@/lib/api";
import TenantPurgeModal from "@/components/admin/TenantPurgeModal";

// 시스템 관리자 — 사업장 관리: 모든 사업장 조회(상태 필터·검색), 사업장 정지·복구,
// 기존 사업장에 새 관리자 발급, 계정 연결 변경(relink — 데이터 이동 없음), 사업장 전체 폐기.
// 폐기의 안전 조건(정지+비활성·외부저장소·마스터/actor·미분류 테이블)은 완화하지 않는다.

interface TenantRow {
  tenant_id: string; office_name: string; service_status: string; is_active: boolean;
  seat_limit: number; total_users: number; active_users: number; loginable_users: number;
  active_admins: number; invited_admins: number; customers: number; tasks: number;
  needs_cleanup: boolean;
  external_storage_refs: Record<string, string>; local_storage_refs: Record<string, string>;
  can_purge: boolean; blocking_reasons: string[];
}

interface RelinkTenantBlock {
  tenant_id: string; office_name: string; service_status: string; is_active: boolean;
  user_count: number; data_counts: Record<string, number>;
  residual_data_counts?: Record<string, number>;
  seat_limit?: number; active_count?: number; invited_count?: number;
}
interface RelinkPreview {
  account: { login_id: string; account_status: string | null; is_active: boolean | null; current_role: string | null } | null;
  source_tenant: RelinkTenantBlock | null;
  target_tenant: RelinkTenantBlock | null;
  role_after: string; confirmation_phrase: string;
  warnings: string[]; blocking_reasons: string[]; can_relink: boolean;
  source_tenant_id?: string | null;
}

const origin = typeof window !== "undefined" ? window.location.origin : "";
const STATUS_KO: Record<string, string> = {
  active: "활성", pending_activation: "활성화 대기", suspended: "정지", terminated: "종료",
};
const FILTERS: { key: string; label: string }[] = [
  { key: "all", label: "전체" }, { key: "active", label: "활성" },
  { key: "pending_activation", label: "활성화 대기" }, { key: "suspended", label: "정지" },
  { key: "needs_cleanup", label: "정리 대상" }, { key: "terminated", label: "종료" },
];
const canIssueAdmin = (t: TenantRow) =>
  (t.service_status === "active" || t.service_status === "pending_activation")
  && t.active_admins === 0 && t.invited_admins === 0;
const sumCounts = (c?: Record<string, number>) => Object.values(c || {}).reduce((a, b) => a + (b || 0), 0);

export default function TenantAdminPanel() {
  const [rows, setRows] = useState<TenantRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState("");
  const [busy, setBusy] = useState(false);
  const [statusFilter, setStatusFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [issueFor, setIssueFor] = useState<TenantRow | null>(null);
  const [issueName, setIssueName] = useState("");
  const [issueEmail, setIssueEmail] = useState("");
  const [issued, setIssued] = useState<{ login: string; token: string } | null>(null);
  const [purgeFor, setPurgeFor] = useState<TenantRow | null>(null);
  // relink
  const [relinkLogin, setRelinkLogin] = useState("");
  const [relinkTarget, setRelinkTarget] = useState("");
  const [relinkPrev, setRelinkPrev] = useState<RelinkPreview | null>(null);
  const [cLogin, setCLogin] = useState(""); const [cSource, setCSource] = useState("");
  const [cTarget, setCTarget] = useState(""); const [cPhrase, setCPhrase] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    officeApplicationApi.listTenants({ status: statusFilter, q: query.trim() || undefined })
      .then((r) => { setRows((r.data as { tenants: TenantRow[] }).tenants); setUnavailable(""); })
      .catch((e) => setUnavailable(e?.response?.status === 404
        ? "승인형 SaaS 기능이 비활성 상태입니다." : "목록을 불러오지 못했습니다."))
      .finally(() => setLoading(false));
  }, [statusFilter, query]);
  useEffect(() => { load(); }, [load]);

  const errMsg = (e: unknown) => (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "실패";
  const withBusy = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try { await fn(); toast.success(ok); load(); } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  const doSuspend = (t: TenantRow) => {
    if (!confirm("사업장을 정지하면 이 사업장의 모든 사용자 로그인이 차단됩니다. 계속하시겠습니까?")) return;
    return withBusy(() => officeApplicationApi.suspendTenant(t.tenant_id), "사업장이 정지되었습니다.");
  };
  const doRestore = (t: TenantRow) =>
    withBusy(() => officeApplicationApi.restoreTenant(t.tenant_id), "사업장이 복구되었습니다.");

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

  const resetRelink = () => { setRelinkPrev(null); setCLogin(""); setCSource(""); setCTarget(""); setCPhrase(""); };
  const doRelinkPreview = async () => {
    if (!relinkLogin.trim() || !relinkTarget.trim()) { toast.error("로그인 ID와 대상 사업장 ID를 입력하세요."); return; }
    try {
      const r = await officeApplicationApi.relinkPreview({ login_id: relinkLogin.trim(), target_tenant_id: relinkTarget.trim() });
      setRelinkPrev(r.data as RelinkPreview); setCLogin(""); setCSource(""); setCTarget(""); setCPhrase("");
    } catch (e) { toast.error(errMsg(e)); }
  };
  const srcId = relinkPrev?.source_tenant?.tenant_id || relinkPrev?.source_tenant_id || "";
  const relinkConfirmed = !!relinkPrev?.can_relink
    && cLogin.trim() === relinkLogin.trim() && cSource.trim() === srcId
    && cTarget.trim() === relinkTarget.trim()
    && cPhrase.trim() === (relinkPrev?.confirmation_phrase || "계정 사업장 연결 변경");
  const doRelink = async () => {
    if (!relinkConfirmed) return;
    if (!confirm("계정의 소속 사업장을 변경하시겠습니까? (고객·업무·분류 데이터는 이동하지 않습니다)")) return;
    setBusy(true);
    try {
      await officeApplicationApi.relink({
        login_id: relinkLogin.trim(), target_tenant_id: relinkTarget.trim(),
        confirm_login_id: cLogin.trim(), confirm_target_tenant_id: cTarget.trim(),
        confirmation_phrase: cPhrase.trim(), source_tenant_id: cSource.trim(),
      });
      toast.success("연결이 변경되었습니다. 대상 계정은 초대 상태가 되며 활성화가 필요합니다.");
      resetRelink(); setRelinkLogin(""); setRelinkTarget(""); load();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  if (unavailable) return <div className="hw-card" style={{ fontSize: 13, color: "var(--hw-text-sub)" }}>{unavailable}</div>;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      <div className="hw-card">
        <div className="hw-card-title">사업장 관리</div>
        <div style={{ fontSize: 12, color: "var(--hw-text-sub)", marginBottom: 10, lineHeight: 1.6 }}>
          모든 사업장의 상태·계정·데이터 현황을 조회하고, 사업장 정지·복구·새 관리자 발급·전체 폐기를 관리합니다.
          사업장 데이터의 소속은 변경되지 않습니다.
        </div>

        {/* 상태 필터 + 검색 */}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
          {FILTERS.map((f) => (
            <button key={f.key} className={`hw-filter-btn ${statusFilter === f.key ? "active" : ""}`}
              style={statusFilter === f.key ? { background: "var(--hw-gold-600, #B7791F)", color: "#fff" } : undefined}
              onClick={() => setStatusFilter(f.key)}>{f.label}</button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
          <input className="hw-input" style={{ maxWidth: 320 }} placeholder="사무소명 또는 사업장 ID 검색"
            value={query} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") load(); }} />
          <button className="btn-secondary" style={{ fontSize: 12 }} onClick={load}>검색/새로고침</button>
        </div>

        {loading ? <p style={{ fontSize: 13, color: "var(--hw-text-sub)" }}>불러오는 중...</p> :
          rows.length === 0 ? <p style={{ fontSize: 13, color: "var(--hw-text-sub)" }}>해당 조건의 사업장이 없습니다.</p> : (
            <div style={{ overflowX: "auto" }}>
              <table className="hw-table">
                <thead><tr>
                  <th>사무소</th><th>사업장 ID</th><th>상태</th><th>계정(로그인)</th><th>관리자(활/초)</th>
                  <th>고객</th><th>업무</th><th>저장소</th><th>관리</th>
                </tr></thead>
                <tbody>
                  {rows.map((t) => {
                    const active = t.service_status === "active";
                    const pending = t.service_status === "pending_activation";
                    const suspended = t.service_status === "suspended";
                    const terminated = t.service_status === "terminated";
                    const hasExternal = Object.keys(t.external_storage_refs || {}).length > 0;
                    const hasLocal = Object.keys(t.local_storage_refs || {}).length > 0;
                    return (
                      <tr key={t.tenant_id}>
                        <td style={{ fontWeight: 600 }}>{t.office_name}{t.needs_cleanup && <span style={{ marginLeft: 6, fontSize: 11, color: "#B7791F" }}>정리대상</span>}</td>
                        <td style={{ fontFamily: "monospace", fontSize: 11 }}>{t.tenant_id}</td>
                        <td>{STATUS_KO[t.service_status] || t.service_status}</td>
                        <td>{t.total_users} ({t.loginable_users})</td>
                        <td>{t.active_admins}/{t.invited_admins}</td>
                        <td>{t.customers}</td>
                        <td>{t.tasks}</td>
                        <td style={{ fontSize: 11 }}>
                          {hasExternal ? <span style={{ color: "#C53030" }}>외부</span> : hasLocal ? <span style={{ color: "#718096" }}>로컬</span> : "—"}
                        </td>
                        <td>
                          <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                            {(active || pending) && (
                              <button className="hw-filter-btn" disabled={busy} onClick={() => doSuspend(t)}>사업장 정지</button>
                            )}
                            {suspended && (
                              <button className="hw-filter-btn" disabled={busy} onClick={() => doRestore(t)}>사업장 복구</button>
                            )}
                            {canIssueAdmin(t) && (
                              <button className="hw-filter-btn" disabled={busy}
                                onClick={() => { setIssueFor(t); setIssued(null); }}>새 관리자 발급</button>
                            )}
                            {!terminated && (
                              <button className="hw-filter-btn" style={{ color: "#C53030", borderColor: "#FEB2B2" }}
                                disabled={busy || !t.can_purge}
                                title={t.can_purge ? "사업장 전체 폐기" : (t.blocking_reasons[0] || "폐기 불가")}
                                onClick={() => setPurgeFor(t)}>폐기</button>
                            )}
                            {terminated && <span style={{ fontSize: 11, color: "#A0AEC0" }}>종료됨</span>}
                          </div>
                          {/* 폐기 불가 사유 화면 표시(title 만으로 대체하지 않음) */}
                          {!terminated && !t.can_purge && t.blocking_reasons.length > 0 && (
                            <ul style={{ margin: "4px 0 0", paddingLeft: 15, fontSize: 10.5, color: "#9C4221", lineHeight: 1.5 }}>
                              {t.blocking_reasons.map((r, i) => <li key={i}>{r}</li>)}
                            </ul>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

        {issueFor && (
          <div style={{ marginTop: 12, background: "var(--hw-gold-50)", border: "1px solid var(--hw-gold-200)", borderRadius: 8, padding: "12px 14px" }}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>새 관리자 발급 — {issueFor.office_name}</div>
            <div style={{ fontSize: 12, color: "var(--hw-text-sub)", marginBottom: 8 }}>
              상태 {STATUS_KO[issueFor.service_status]} · 좌석 {issueFor.active_users}/{issueFor.seat_limit} ·
              현재 관리자 활성 {issueFor.active_admins} · 초대 {issueFor.invited_admins}
            </div>
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

      {/* 계정 연결 변경(relink) — 고급 */}
      <div className="hw-card">
        <div className="hw-card-title">계정 연결 변경 (고급)</div>
        <div style={{ fontSize: 12, color: "var(--hw-text-sub)", marginBottom: 8, lineHeight: 1.6 }}>
          계정이 접근하는 사업장만 변경하며, 데이터 자체는 이동하지 않습니다. 연결 후 역할은 항상 직원(office_staff)이며,
          관리자 연결이 필요하면 “새 관리자 발급”을 사용하세요.
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          <input className="hw-input" placeholder="대상 계정 로그인 ID(이메일)" value={relinkLogin} onChange={(e) => { setRelinkLogin(e.target.value); resetRelink(); }} />
          <input className="hw-input" placeholder="이동할 사업장 ID(of-...)" value={relinkTarget} onChange={(e) => { setRelinkTarget(e.target.value); resetRelink(); }} />
          <div><button className="btn-secondary" style={{ fontSize: 13 }} onClick={doRelinkPreview}>연결 가능 여부 확인</button></div>

          {relinkPrev && (
            <div style={{ border: "1px solid var(--hw-border)", borderRadius: 8, padding: "10px 12px", fontSize: 12.5, lineHeight: 1.7 }}>
              <div style={{ fontWeight: 700, marginBottom: 4 }}>연결 변경 미리보기</div>
              {relinkPrev.account && <div>계정: <code>{relinkPrev.account.login_id}</code> · 상태 {relinkPrev.account.account_status} · 현재 역할 <strong>{relinkPrev.account.current_role}</strong> → 변경 후 <strong>{relinkPrev.role_after}</strong></div>}
              {relinkPrev.source_tenant && <div>원본: <strong>{relinkPrev.source_tenant.office_name}</strong> (<code>{relinkPrev.source_tenant.tenant_id}</code>) · 사용자 {relinkPrev.source_tenant.user_count}명 · 잔여 데이터 {sumCounts(relinkPrev.source_tenant.residual_data_counts)}건</div>}
              {relinkPrev.target_tenant && <div>대상: <strong>{relinkPrev.target_tenant.office_name}</strong> (<code>{relinkPrev.target_tenant.tenant_id}</code>) · 좌석 {relinkPrev.target_tenant.active_count}/{relinkPrev.target_tenant.seat_limit} · 초대 {relinkPrev.target_tenant.invited_count}</div>}
              {relinkPrev.warnings?.length > 0 && <ul style={{ paddingLeft: 16, margin: "6px 0 0", color: "var(--hw-text-sub)" }}>{relinkPrev.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
              {!relinkPrev.can_relink && <ul style={{ paddingLeft: 16, margin: "6px 0 0", color: "#C53030" }}>{relinkPrev.blocking_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
            </div>
          )}
          {relinkPrev?.can_relink && (
            <div style={{ background: "#FFF5F5", border: "1px solid #FEB2B2", borderRadius: 8, padding: "10px 12px", display: "grid", gap: 8 }}>
              <div style={{ fontSize: 12, color: "#C53030", fontWeight: 700 }}>실행하려면 아래 4가지를 정확히 입력하세요.</div>
              <input className="hw-input" placeholder={`로그인 ID: ${relinkLogin.trim()}`} value={cLogin} onChange={(e) => setCLogin(e.target.value)} />
              <input className="hw-input" placeholder={`원본 사업장 ID: ${srcId}`} value={cSource} onChange={(e) => setCSource(e.target.value)} />
              <input className="hw-input" placeholder={`대상 사업장 ID: ${relinkTarget.trim()}`} value={cTarget} onChange={(e) => setCTarget(e.target.value)} />
              <input className="hw-input" placeholder={`확인 문구: ${relinkPrev.confirmation_phrase}`} value={cPhrase} onChange={(e) => setCPhrase(e.target.value)} />
              <div style={{ display: "flex", gap: 8 }}>
                <button className="btn-danger" style={{ fontSize: 13 }} disabled={!relinkConfirmed || busy} onClick={doRelink}>연결 변경 실행</button>
                <button className="btn-secondary" style={{ fontSize: 13 }} onClick={resetRelink}>취소</button>
              </div>
            </div>
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
