"use client";
import { useEffect, useState, useCallback } from "react";
import { toast } from "sonner";
import { officeApplicationApi, type OfficeApplication } from "@/lib/api";

// 승인형 SaaS 관리자 화면 — 사무소 이용신청 목록/상세/심사/승인/반려.
// 기존 hw-card / hw-table / btn-primary 디자인 시스템 재사용. 전면 재설계 없음.
// FEATURE_APPROVED_SAAS off 이거나 0031 미적용이면 API 가 404/503 → 안내만 표시.

const STATUS_KO: Record<string, string> = {
  pending: "접수", reviewing: "심사중", approved: "승인", rejected: "반려", cancelled: "취소",
};
const STATUS_COLOR: Record<string, string> = {
  pending: "#B7791F", reviewing: "#2B6CB0", approved: "#276749", rejected: "#C53030", cancelled: "#718096",
};

function fmtFlags(flags?: Record<string, unknown>): string[] {
  if (!flags) return [];
  const LABEL: Record<string, string> = {
    existing_tenant_biz_reg_no: "기존 사무소와 동일 사업자번호",
    duplicate_biz_reg_no_applications: "동일 사업자번호 신청 다수",
    duplicate_office_phone: "동일 대표전화 신청",
    duplicate_applicant_email: "동일 신청 이메일",
    duplicate_office_address: "동일 주소 신청",
    duplicate_representative_name: "동일 대표자명 신청",
    matches_rejected_office: "과거 반려 사무소와 일치",
    matches_suspended_tenant: "정지/종료 사무소와 일치",
    repeated_ip_1h: "동일 IP 반복 신청(1시간)",
    missing_fields: "필수정보 누락",
  };
  return Object.entries(flags).map(([k, v]) =>
    `${LABEL[k] || k}${Array.isArray(v) ? `: ${v.join(", ")}` : (v === true ? "" : `: ${v}`)}`);
}

export default function OfficeApplicationsTab() {
  const [apps, setApps] = useState<OfficeApplication[]>([]);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState<string>("");
  const [sel, setSel] = useState<OfficeApplication | null>(null);
  const [note, setNote] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [approveResult, setApproveResult] = useState<{ tenant_id: string; users: { login_id: string; name: string; role: string; activation_token: string }[] } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    officeApplicationApi.list()
      .then((r) => { setApps((r.data as { applications: OfficeApplication[] }).applications); setUnavailable(""); })
      .catch((e) => {
        const st = e?.response?.status;
        setUnavailable(st === 404
          ? "승인형 SaaS 기능이 비활성 상태입니다 (FEATURE_APPROVED_SAAS off / migration 0031 미적용)."
          : "신청 목록을 불러오지 못했습니다.");
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const openDetail = (a: OfficeApplication) => {
    setSel(a); setNote(a.review_note_internal || ""); setRejectReason(""); setApproveResult(null);
  };

  const doReview = async (action: string) => {
    if (!sel) return;
    setBusy(true);
    try {
      await officeApplicationApi.review(sel.application_id, { action, review_note_internal: note });
      toast.success(action === "start_review" ? "심사를 시작했습니다." : "메모를 저장했습니다.");
      load();
      const r = await officeApplicationApi.get(sel.application_id);
      setSel(r.data as OfficeApplication);
    } catch (e) { toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "실패"); }
    finally { setBusy(false); }
  };

  const doApprove = async () => {
    if (!sel) return;
    if (!confirm("이 신청을 승인하고 사무소 테넌트 + 계정 2개를 생성하시겠습니까?")) return;
    setBusy(true);
    try {
      const r = await officeApplicationApi.approve(sel.application_id, { seat_limit: 2 });
      const data = r.data as { already_approved: boolean; tenant_id: string; users: { login_id: string; name: string; role: string; activation_token: string }[] };
      if (data.already_approved) toast.info("이미 승인된 신청입니다.");
      else { toast.success("승인 완료 — 계정 2개가 생성되었습니다."); setApproveResult(data); }
      load();
      const g = await officeApplicationApi.get(sel.application_id);
      setSel(g.data as OfficeApplication);
    } catch (e) { toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "승인 실패"); }
    finally { setBusy(false); }
  };

  const doReject = async () => {
    if (!sel) return;
    if (!rejectReason.trim()) { toast.error("반려 사유(공개)를 입력하세요."); return; }
    if (!confirm("이 신청을 반려하시겠습니까?")) return;
    setBusy(true);
    try {
      await officeApplicationApi.reject(sel.application_id, { rejection_reason_public: rejectReason, review_note_internal: note });
      toast.success("반려 처리되었습니다.");
      load();
      const g = await officeApplicationApi.get(sel.application_id);
      setSel(g.data as OfficeApplication);
    } catch (e) { toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "반려 실패"); }
    finally { setBusy(false); }
  };

  if (unavailable) {
    return <div className="hw-card" style={{ fontSize: 13, color: "var(--hw-text-sub)", lineHeight: 1.7 }}>{unavailable}</div>;
  }

  return (
    <div style={{ display: "grid", gridTemplateColumns: sel ? "1fr 1fr" : "1fr", gap: 16, alignItems: "start" }}>
      {/* 목록 */}
      <div className="hw-card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <div className="hw-card-title" style={{ marginBottom: 0 }}>가입 신청 목록</div>
          <button className="btn-secondary" style={{ fontSize: 12 }} onClick={load}>새로고침</button>
        </div>
        {loading ? <p style={{ fontSize: 13, color: "var(--hw-text-sub)" }}>불러오는 중...</p> :
          apps.length === 0 ? <p style={{ fontSize: 13, color: "var(--hw-text-sub)" }}>신청이 없습니다.</p> : (
            <div style={{ overflowX: "auto" }}>
              <table className="hw-table">
                <thead><tr><th>상태</th><th>사무소</th><th>대표</th><th>신청자</th><th>경고</th><th>신청일</th></tr></thead>
                <tbody>
                  {apps.map((a) => (
                    <tr key={a.application_id} style={{ cursor: "pointer" }} onClick={() => openDetail(a)}>
                      <td><span style={{ fontWeight: 700, color: STATUS_COLOR[a.status] || "#4A5568" }}>{STATUS_KO[a.status] || a.status}</span></td>
                      <td style={{ fontWeight: 600 }}>{a.office_name}</td>
                      <td>{a.representative_name || "—"}</td>
                      <td>{a.applicant_name || "—"}</td>
                      <td>{Object.keys(a.duplicate_flags || {}).length > 0 ? <span style={{ color: "#C53030" }}>⚠️ {Object.keys(a.duplicate_flags || {}).length}</span> : "—"}</td>
                      <td style={{ whiteSpace: "nowrap" }}>{(a.created_at || "").slice(0, 10)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </div>

      {/* 상세 */}
      {sel && (
        <div className="hw-card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <div className="hw-card-title" style={{ marginBottom: 0 }}>
              {sel.office_name} <span style={{ fontSize: 12, color: STATUS_COLOR[sel.status] }}>· {STATUS_KO[sel.status] || sel.status}</span>
            </div>
            <button className="btn-secondary" style={{ fontSize: 12 }} onClick={() => setSel(null)}>닫기</button>
          </div>

          <div style={{ fontSize: 13, lineHeight: 1.8, color: "var(--hw-text)" }}>
            <div>접수번호: <strong>{sel.application_id}</strong></div>
            <div>대표자: {sel.representative_name || "—"} / 사업자: {sel.business_registration_number || "—"}</div>
            <div>주소: {sel.office_address || "—"}</div>
            <div>대표전화: {sel.office_phone || "—"}</div>
            <div>신청자: {sel.applicant_name || "—"} ({sel.applicant_email || "—"}, {sel.applicant_phone || "—"})</div>
            <div>이용목적: {sel.intended_use || "—"}</div>
            {sel.approved_tenant_id && <div>발급 테넌트: <strong>{sel.approved_tenant_id}</strong></div>}
          </div>

          <div className="hw-section-divider" style={{ marginTop: 12 }}>계정 발급 대상 2명</div>
          <div style={{ fontSize: 13, lineHeight: 1.8 }}>
            <div>① {sel.requested_user_1_name || "—"} — {sel.requested_user_1_email || "—"} (office_admin 제안)</div>
            <div>② {sel.requested_user_2_name || "—"} — {sel.requested_user_2_email || "—"} (office_staff 제안)</div>
          </div>

          {fmtFlags(sel.duplicate_flags).length > 0 && (
            <>
              <div className="hw-section-divider" style={{ marginTop: 12 }}>중복·위험 경고 (자동 반려 아님 — 판단 보조)</div>
              <ul style={{ fontSize: 12.5, color: "#9C4221", paddingLeft: 18, lineHeight: 1.7 }}>
                {fmtFlags(sel.duplicate_flags).map((f, i) => <li key={i}>{f}</li>)}
              </ul>
            </>
          )}

          <div className="hw-section-divider" style={{ marginTop: 12 }}>내부 메모 (신청자 비노출)</div>
          <textarea className="hw-input" style={{ height: 60, resize: "vertical", padding: "8px 12px", lineHeight: 1.6 }}
            value={note} onChange={(e) => setNote(e.target.value)} placeholder="심사 내부 메모" />

          {(sel.status === "pending" || sel.status === "reviewing") && (
            <>
              <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                {sel.status === "pending" && (
                  <button className="btn-secondary" style={{ fontSize: 13 }} disabled={busy} onClick={() => doReview("start_review")}>심사 시작</button>
                )}
                <button className="btn-secondary" style={{ fontSize: 13 }} disabled={busy} onClick={() => doReview("note")}>메모 저장</button>
                <button className="btn-primary" style={{ fontSize: 13 }} disabled={busy} onClick={doApprove}>승인 (계정 2개 생성)</button>
              </div>
              <div className="hw-section-divider" style={{ marginTop: 12 }}>반려</div>
              <input className="hw-input" value={rejectReason} onChange={(e) => setRejectReason(e.target.value)}
                placeholder="반려 사유(공개 — 신청자에게 안내)" />
              <button className="btn-danger" style={{ fontSize: 13, marginTop: 8 }} disabled={busy} onClick={doReject}>반려</button>
            </>
          )}

          {sel.status === "rejected" && sel.rejection_reason_public && (
            <div style={{ marginTop: 12, fontSize: 13, color: "#C53030" }}>반려 사유: {sel.rejection_reason_public}</div>
          )}

          {approveResult && (
            <div style={{ marginTop: 14, background: "var(--hw-gold-50)", border: "1px solid var(--hw-gold-200)", borderRadius: 8, padding: "12px 14px" }}>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>✅ 계정 2개 생성됨 — 활성화 링크 전달 필요</div>
              <div style={{ fontSize: 12, color: "var(--hw-text-sub)", marginBottom: 8 }}>
                아래 활성화 링크를 각 사용자에게 전달하세요. 링크는 1회성이며 만료됩니다. (자동 이메일 발송 없음)
              </div>
              {approveResult.users.map((u) => (
                <div key={u.login_id} style={{ fontSize: 12, marginBottom: 8, wordBreak: "break-all" }}>
                  <div><strong>{u.name}</strong> ({u.login_id}) — {u.role}</div>
                  <code style={{ fontSize: 11 }}>{`${typeof window !== "undefined" ? window.location.origin : ""}/activate/${u.activation_token}`}</code>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
