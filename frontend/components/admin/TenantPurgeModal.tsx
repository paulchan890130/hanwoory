"use client";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { officeApplicationApi } from "@/lib/api";

// 사업장 전체 폐기 — 고위험. 시스템 관리자 tenant 상세에서만 진입.
// 미리보기(건수 + blocking) → tenant ID·사무소명·확인문구 직접 입력 → 최종 실행.

const PHRASE = "사업장 전체 폐기";

interface PurgePreview {
  tenant_id: string; office_name: string; service_status: string; is_active: boolean;
  users: number; customers: number; active_tasks: number; completed_tasks: number;
  work_references: number; board_posts: number; sessions: number; activation_tokens: number;
  applications: number; audit_logs: number; counts: Record<string, number>;
  external_storage: string[];
  external_storage_refs: Record<string, string>; local_storage_refs: Record<string, string>;
  blocking_reasons: string[]; can_purge: boolean;
}

const LABELS: Record<string, string> = {
  users: "계정", customers: "고객", active_tasks: "진행업무", planned_tasks: "예정업무",
  completed_tasks: "완료업무", cert_groups: "공증 분류", work_reference_rows: "업무참고",
  board_posts: "게시글", user_sessions: "세션", activation_tokens: "활성화 토큰",
  office_applications: "신청서", audit_logs: "감사 로그(삭제 후 요약만 보존)",
};

export default function TenantPurgeModal({ tenantId, officeName, onClose, onDone }: {
  tenantId: string; officeName: string; onClose: () => void; onDone: () => void;
}) {
  const [preview, setPreview] = useState<PurgePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [cTid, setCTid] = useState("");
  const [cName, setCName] = useState("");
  const [cPhrase, setCPhrase] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    officeApplicationApi.purgePreview(tenantId)
      .then((r) => { if (alive) setPreview(r.data as PurgePreview); })
      .catch((e) => { if (alive) toast.error(e?.response?.data?.detail || "미리보기 실패"); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [tenantId]);

  const confirmed = cTid.trim() === tenantId && cName.trim() === (officeName || "").trim() && cPhrase.trim() === PHRASE;
  const canExecute = !!preview?.can_purge && confirmed && !busy;

  const doPurge = async () => {
    if (!canExecute) return;
    if (!confirm("정말로 이 사업장과 모든 데이터를 영구 삭제하시겠습니까? 되돌릴 수 없습니다.")) return;
    setBusy(true);
    try {
      await officeApplicationApi.purge(tenantId, {
        confirm_tenant_id: cTid.trim(), confirm_office_name: cName.trim(), confirmation_phrase: cPhrase.trim(),
      });
      toast.success("사업장과 관련 데이터가 영구 삭제되었습니다.");
      onDone();
    } catch (e) {
      toast.error((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "폐기 실패");
    } finally { setBusy(false); }
  };

  const rows = preview ? Object.entries(preview.counts).filter(([, n]) => n > 0) : [];

  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.5)", zIndex: 9999, display: "flex", alignItems: "center", justifyContent: "center" }} onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="hw-card" style={{ width: 540, maxWidth: "94vw", maxHeight: "88vh", overflowY: "auto", background: "#fff" }}>
        <div style={{ fontWeight: 800, fontSize: 15, color: "#C53030", marginBottom: 4 }}>사업장 전체 폐기 — 복구 불가</div>
        <div style={{ fontSize: 12.5, color: "var(--hw-text-sub)", lineHeight: 1.7, marginBottom: 10 }}>
          이 사업장의 모든 계정과 고객·업무·분류·설정 데이터를 영구적으로 삭제합니다.
        </div>
        <div style={{ fontSize: 13, marginBottom: 8 }}>
          사업장: <strong>{officeName}</strong> (<code style={{ fontFamily: "monospace" }}>{tenantId}</code>)
        </div>

        {loading ? <p style={{ fontSize: 13, color: "var(--hw-text-sub)" }}>영향 미리보기 확인 중…</p> : preview && (
          <>
            <div style={{ fontSize: 12, color: "var(--hw-text-sub)", marginBottom: 6 }}>
              상태 {preview.service_status} · 활성 {String(preview.is_active)}
            </div>
            <div style={{ fontSize: 11.5, color: "var(--hw-text-sub)", marginBottom: 6, lineHeight: 1.6 }}>
              감사 로그는 삭제되고, 폐기 후 개인정보 없는 요약 감사 1건(사업장 ID 해시 + 삭제 건수)만 남습니다.
            </div>
            {Object.keys(preview.local_storage_refs || {}).length > 0 && (
              <div style={{ fontSize: 11.5, color: "#718096", marginBottom: 6, lineHeight: 1.6 }}>
                로컬 모의 저장소(폐기 차단 아님):{" "}
                {Object.entries(preview.local_storage_refs).map(([k, v]) => `${k}=${v}`).join(", ")}
              </div>
            )}
            {Object.keys(preview.external_storage_refs || {}).length > 0 && (
              <div style={{ fontSize: 11.5, color: "#C53030", marginBottom: 6, lineHeight: 1.6 }}>
                실제 외부 저장소(폐기 차단):{" "}
                {Object.entries(preview.external_storage_refs).map(([k, v]) => `${k}=${v}`).join(", ")}
              </div>
            )}
            <table className="hw-table" style={{ marginBottom: 10 }}>
              <thead><tr><th>데이터</th><th style={{ textAlign: "right" }}>삭제 건수</th></tr></thead>
              <tbody>
                {rows.length === 0 ? <tr><td colSpan={2} style={{ color: "#718096" }}>삭제할 데이터가 없습니다.</td></tr> :
                  rows.map(([t, n]) => (
                    <tr key={t}><td>{LABELS[t] || t}</td><td style={{ textAlign: "right", fontWeight: 600 }}>{n}</td></tr>
                  ))}
              </tbody>
            </table>

            {preview.blocking_reasons.length > 0 && (
              <div style={{ background: "#FFF5F5", border: "1px solid #FEB2B2", color: "#C53030", borderRadius: 8, padding: "10px 12px", fontSize: 12.5, marginBottom: 10, lineHeight: 1.7 }}>
                <div style={{ fontWeight: 700, marginBottom: 4 }}>폐기할 수 없습니다:</div>
                <ul style={{ paddingLeft: 16, margin: 0 }}>
                  {preview.blocking_reasons.map((r, i) => <li key={i}>{r}</li>)}
                </ul>
              </div>
            )}

            {preview.can_purge && (
              <div style={{ display: "grid", gap: 8, marginBottom: 12 }}>
                <div style={{ fontSize: 12, color: "var(--hw-text-sub)" }}>아래 3가지를 정확히 입력해야 실행됩니다.</div>
                <input className="hw-input" placeholder={`사업장 ID: ${tenantId}`} value={cTid} onChange={(e) => setCTid(e.target.value)} />
                <input className="hw-input" placeholder={`사무소명: ${officeName}`} value={cName} onChange={(e) => setCName(e.target.value)} />
                <input className="hw-input" placeholder={`확인 문구: ${PHRASE}`} value={cPhrase} onChange={(e) => setCPhrase(e.target.value)} />
              </div>
            )}
          </>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="btn-secondary" onClick={onClose} disabled={busy}>취소</button>
          <button className="btn-danger" onClick={doPurge} disabled={!canExecute}>영구 삭제</button>
        </div>
      </div>
    </div>
  );
}
