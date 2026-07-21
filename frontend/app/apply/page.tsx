"use client";
import { useState } from "react";
import Link from "next/link";
import { officeApplicationApi } from "@/lib/api";

// 공개 사무소 이용신청 — 계정을 만들지 않는다. 신청서만 접수하고 접수번호를 안내한다.
// 승인/로그인 링크 없음. 개인정보는 POST body 로만 전송(URL query 노출 금지).

type Field = { key: string; label: string; required?: boolean; placeholder?: string };

const OFFICE_FIELDS: Field[] = [
  { key: "office_name", label: "사무소명", required: true },
  { key: "representative_name", label: "대표자명", required: true },
  { key: "business_registration_number", label: "사업자등록번호", required: true, placeholder: "숫자만" },
  { key: "office_address", label: "사무소 주소" },
  { key: "office_phone", label: "대표 전화" },
];
const APPLICANT_FIELDS: Field[] = [
  { key: "applicant_name", label: "신청 담당자명", required: true },
  { key: "applicant_email", label: "담당자 이메일", required: true, placeholder: "name@example.com" },
  { key: "applicant_phone", label: "담당자 전화" },
];
const USER_FIELDS: Field[] = [
  { key: "requested_user_1_name", label: "계정 사용자 1 이름", required: true },
  { key: "requested_user_1_email", label: "계정 사용자 1 이메일", required: true },
  { key: "requested_user_2_name", label: "계정 사용자 2 이름", required: true },
  { key: "requested_user_2_email", label: "계정 사용자 2 이메일", required: true },
];

export default function ApplyPage() {
  const [form, setForm] = useState<Record<string, string>>({});
  const [agreePrivacy, setAgreePrivacy] = useState(false);
  const [agreeTerms, setAgreeTerms] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<string | null>(null);

  const set = (k: string, v: string) => setForm((p) => ({ ...p, [k]: v }));

  const missing = [...OFFICE_FIELDS, ...APPLICANT_FIELDS, ...USER_FIELDS]
    .filter((f) => f.required && !(form[f.key] || "").trim())
    .map((f) => f.label);

  const submit = async () => {
    setError("");
    if (missing.length) { setError(`필수 항목을 입력해 주세요: ${missing.join(", ")}`); return; }
    if (!agreePrivacy || !agreeTerms) { setError("개인정보 및 이용약관에 동의해 주세요."); return; }
    setSubmitting(true);
    try {
      const res = await officeApplicationApi.submit({
        ...form, agree_privacy: agreePrivacy, agree_terms: agreeTerms,
      });
      setReceipt((res.data as { application_id: string }).application_id);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "신청 접수에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      setSubmitting(false);
    }
  };

  if (receipt) {
    return (
      <div style={{ maxWidth: 560, margin: "48px auto", padding: "0 16px" }}>
        <div className="hw-card" style={{ textAlign: "center" }}>
          <div style={{ fontSize: 40, marginBottom: 8 }}>✅</div>
          <h1 className="hw-page-title" style={{ marginBottom: 12 }}>신청이 접수되었습니다</h1>
          <p style={{ fontSize: 14, color: "var(--hw-text-sub)", lineHeight: 1.7 }}>
            접수번호 <strong style={{ color: "var(--hw-text)" }}>{receipt}</strong>
          </p>
          <p style={{ fontSize: 13, color: "var(--hw-text-sub)", marginTop: 8, lineHeight: 1.7 }}>
            관리자 심사 후 별도로 안내드립니다. 승인 전에는 로그인할 수 없습니다.
          </p>
          <Link href="/login" className="btn-secondary" style={{ marginTop: 20, textDecoration: "none" }}>
            로그인 화면으로
          </Link>
        </div>
      </div>
    );
  }

  const renderGroup = (title: string, fields: Field[]) => (
    <div className="hw-card" style={{ marginBottom: 16 }}>
      <div className="hw-card-title">{title}</div>
      {fields.map((f) => (
        <div className="hw-field" key={f.key}>
          <label className="hw-label">{f.label}{f.required && <span style={{ color: "#C53030" }}> *</span>}</label>
          <input
            className="hw-input"
            value={form[f.key] || ""}
            placeholder={f.placeholder}
            onChange={(e) => set(f.key, e.target.value)}
          />
        </div>
      ))}
    </div>
  );

  return (
    <div style={{ maxWidth: 560, margin: "40px auto", padding: "0 16px" }}>
      <h1 className="hw-page-title" style={{ marginBottom: 6 }}>사무소 이용 신청</h1>
      <p style={{ fontSize: 13, color: "var(--hw-text-sub)", marginBottom: 20, lineHeight: 1.7 }}>
        신청서를 제출하면 관리자 심사 후 사무소 워크스페이스와 <strong>실명 계정 2개</strong>가 발급됩니다.
        본 신청으로 계정이 즉시 생성되지는 않습니다.
      </p>

      {renderGroup("사무소 정보", OFFICE_FIELDS)}
      {renderGroup("신청 담당자", APPLICANT_FIELDS)}
      <div className="hw-card" style={{ marginBottom: 16 }}>
        <div className="hw-card-title">이용 목적</div>
        <textarea
          className="hw-input"
          style={{ height: 72, resize: "vertical", padding: "8px 12px", lineHeight: 1.6 }}
          value={form["intended_use"] || ""}
          onChange={(e) => set("intended_use", e.target.value)}
          placeholder="예: 출입국 체류/사증 업무 관리"
        />
      </div>
      {renderGroup("발급 계정 2명 (실명)", USER_FIELDS)}

      <div className="hw-card" style={{ marginBottom: 16 }}>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, marginBottom: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={agreePrivacy} onChange={(e) => setAgreePrivacy(e.target.checked)} />
          <span>개인정보 수집·이용에 동의합니다. (신청 심사 목적)</span>
        </label>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, cursor: "pointer" }}>
          <input type="checkbox" checked={agreeTerms} onChange={(e) => setAgreeTerms(e.target.checked)} />
          <span>서비스 이용약관에 동의합니다.</span>
        </label>
      </div>

      {error && (
        <div style={{ background: "#FFF5F5", border: "1px solid #FEB2B2", color: "#C53030",
          borderRadius: 8, padding: "10px 14px", fontSize: 13, marginBottom: 12 }}>
          {error}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button className="btn-primary" onClick={submit} disabled={submitting}>
          {submitting ? "접수 중..." : "이용 신청 제출"}
        </button>
        <Link href="/login" className="btn-secondary" style={{ textDecoration: "none" }}>취소</Link>
      </div>
    </div>
  );
}
