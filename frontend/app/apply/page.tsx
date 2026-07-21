"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { officeApplicationApi } from "@/lib/api";

// 가용성 4-state: 확인 중 / 신청 가능 / 신청 마감(비활성) / 확인 실패.
// disabled·error 상태에서는 신청 폼을 렌더링하지 않고 POST 도 하지 않는다(fail-closed).
type Availability = "loading" | "enabled" | "disabled" | "error";

// 공개 사무소 이용신청 — 계정을 만들지 않는다. 신청서만 접수하고 접수번호를 안내한다.
// 대표자(승인 시 사무소 관리자) + 실무자(서브계정) 정보만 받는다.

// ── 사업자등록번호 / 전화번호 정규화·형식화 (백엔드와 동일 규칙) ──────────────
const bizDigits = (v: string) => (v || "").replace(/[^0-9]/g, "").slice(0, 10);
const fmtBiz = (v: string) => {
  const d = bizDigits(v);
  if (d.length <= 3) return d;
  if (d.length <= 5) return `${d.slice(0, 3)}-${d.slice(3)}`;
  return `${d.slice(0, 3)}-${d.slice(3, 5)}-${d.slice(5)}`;
};
const phoneDigits = (v: string) => (v || "").replace(/[^0-9]/g, "").slice(0, 11);
const fmtPhone = (v: string) => {
  const d = phoneDigits(v);
  if (d.startsWith("02")) {
    if (d.length <= 2) return d;
    if (d.length <= 5) return `${d.slice(0, 2)}-${d.slice(2)}`;
    if (d.length <= 9) return `${d.slice(0, 2)}-${d.slice(2, 5)}-${d.slice(5)}`;
    return `${d.slice(0, 2)}-${d.slice(2, 6)}-${d.slice(6)}`;
  }
  if (d.length <= 3) return d;
  if (d.length <= 7) return `${d.slice(0, 3)}-${d.slice(3)}`;
  return `${d.slice(0, 3)}-${d.slice(3, 7)}-${d.slice(7)}`;
};

type Field = {
  key: string; label: string; required?: boolean; placeholder?: string;
  desc?: string; kind?: "text" | "email" | "biz" | "phone";
};

const OFFICE_FIELDS: Field[] = [
  { key: "office_name", label: "사무소명", required: true },
  { key: "representative_name", label: "대표자명", required: true },
  {
    key: "representative_email", label: "대표자 이메일", required: true, kind: "email",
    placeholder: "name@example.com", desc: "승인 후 사무소 관리자 계정으로 발급됩니다.",
  },
  {
    key: "business_registration_number", label: "사업자등록번호", required: true, kind: "biz",
    placeholder: "213-12-37464", desc: "숫자만 입력하면 자동으로 형식이 적용됩니다.",
  },
  { key: "office_address", label: "사무소 주소" },
  {
    key: "office_phone", label: "대표 전화", kind: "phone",
    placeholder: "010-0000-0000", desc: "숫자만 입력하면 자동으로 형식이 적용됩니다.",
  },
];
const STAFF_FIELDS: Field[] = [
  { key: "staff_name", label: "실무자 이름", required: true },
  {
    key: "staff_email", label: "실무자 이메일", required: true, kind: "email",
    placeholder: "name@example.com", desc: "승인 후 직원용 서브계정으로 발급됩니다.",
  },
];

export default function ApplyPage() {
  // form 에는 사업자번호·전화번호를 **digits-only** 로 보관하고, 화면에만 형식을 적용한다.
  const [form, setForm] = useState<Record<string, string>>({});
  const [agreePrivacy, setAgreePrivacy] = useState(false);
  const [agreeTerms, setAgreeTerms] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<string | null>(null);
  const [availability, setAvailability] = useState<Availability>("loading");

  useEffect(() => {
    let alive = true;
    officeApplicationApi.availability()
      .then((r) => { if (alive) setAvailability(r.data?.enabled ? "enabled" : "disabled"); })
      .catch(() => { if (alive) setAvailability("error"); });
    return () => { alive = false; };
  }, []);

  const set = (k: string, v: string) => setForm((p) => ({ ...p, [k]: v }));
  const onChangeField = (f: Field, raw: string) => {
    if (f.kind === "biz") set(f.key, bizDigits(raw));
    else if (f.kind === "phone") set(f.key, phoneDigits(raw));
    else set(f.key, raw);
  };
  const displayValue = (f: Field): string => {
    const v = form[f.key] || "";
    if (f.kind === "biz") return fmtBiz(v);
    if (f.kind === "phone") return fmtPhone(v);
    return v;
  };

  const missing = [...OFFICE_FIELDS, ...STAFF_FIELDS]
    .filter((f) => f.required && !(form[f.key] || "").trim())
    .map((f) => f.label);

  const submit = async () => {
    setError("");
    if (availability !== "enabled") { setError("현재 신청을 받을 수 없습니다."); return; }
    if (missing.length) { setError(`필수 항목을 입력해 주세요: ${missing.join(", ")}`); return; }
    const biz = bizDigits(form["business_registration_number"] || "");
    if (biz.length !== 10) { setError("사업자등록번호 10자리를 입력해 주세요."); return; }
    const repEmail = (form["representative_email"] || "").trim().toLowerCase();
    const staffEmail = (form["staff_email"] || "").trim().toLowerCase();
    if (repEmail && staffEmail && repEmail === staffEmail) {
      setError("대표자와 실무자의 이메일은 서로 달라야 합니다."); return;
    }
    if (!agreePrivacy || !agreeTerms) { setError("개인정보 및 이용약관에 동의해 주세요."); return; }
    setSubmitting(true);
    try {
      const res = await officeApplicationApi.submit({
        office_name: form["office_name"],
        representative_name: form["representative_name"],
        representative_email: repEmail,
        business_registration_number: biz,
        office_address: form["office_address"] || "",
        office_phone: phoneDigits(form["office_phone"] || ""),
        staff_name: form["staff_name"],
        staff_email: staffEmail,
        agree_privacy: agreePrivacy, agree_terms: agreeTerms,
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
            <br />자동 이메일 발송은 없으며, 승인 시 관리자가 활성화 링크를 직접 안내합니다.
          </p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 20 }}>
            <button className="btn-secondary" onClick={() => { navigator.clipboard?.writeText(receipt); }}>
              접수번호 복사
            </button>
            <Link href="/login" className="btn-secondary" style={{ textDecoration: "none" }}>
              로그인 화면으로
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // 확인 중 / 마감 / 확인 실패 — 폼을 렌더링하지 않는다(fail-closed).
  if (availability !== "enabled") {
    const panel =
      availability === "loading"
        ? { icon: "⏳", title: "신청 가능 여부 확인 중…", body: "잠시만 기다려 주세요." }
        : availability === "disabled"
        ? { icon: "🚫", title: "현재 신규 신청을 받지 않습니다",
            body: "사무소 이용 신청이 일시적으로 마감되었습니다. 자세한 사항은 한우리 행정사에 문의해 주세요." }
        : { icon: "⚠️", title: "신청 가능 여부를 확인할 수 없습니다",
            body: "네트워크 상태를 확인한 뒤 잠시 후 다시 시도해 주세요." };
    return (
      <div style={{ maxWidth: 560, margin: "48px auto", padding: "0 16px" }}>
        <div className="hw-card" style={{ textAlign: "center" }}>
          <div style={{ fontSize: 40, marginBottom: 8 }}>{panel.icon}</div>
          <h1 className="hw-page-title" style={{ marginBottom: 12 }}>{panel.title}</h1>
          <p style={{ fontSize: 14, color: "var(--hw-text-sub)", lineHeight: 1.7 }}>{panel.body}</p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 20 }}>
            {availability === "error" && (
              <button className="btn-secondary" onClick={() => window.location.reload()}>다시 시도</button>
            )}
            <Link href="/" className="btn-secondary" style={{ textDecoration: "none" }}>홈으로</Link>
            <Link href="/login" className="btn-secondary" style={{ textDecoration: "none" }}>로그인</Link>
          </div>
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
            value={displayValue(f)}
            placeholder={f.placeholder}
            inputMode={f.kind === "biz" ? "numeric" : f.kind === "phone" ? "tel" : undefined}
            type={f.kind === "email" ? "email" : "text"}
            onChange={(e) => onChangeField(f, e.target.value)}
          />
          {f.desc && (
            <div style={{ fontSize: 12, color: "var(--hw-text-sub)", marginTop: 4 }}>{f.desc}</div>
          )}
        </div>
      ))}
    </div>
  );

  return (
    <div style={{ maxWidth: 560, margin: "40px auto", padding: "0 16px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <Link href="/" aria-label="한우리 홈페이지로 이동"
          style={{ display: "inline-flex", alignItems: "center", gap: 8, textDecoration: "none", color: "var(--hw-text)", fontWeight: 800, fontSize: 18 }}>
          <img src="/hanwoori-logo-new.jpeg" alt="한우리 로고" style={{ width: 36, height: 36, objectFit: "contain" }} /> K.ID
        </Link>
        <Link href="/login" style={{ fontSize: 13, color: "var(--hw-gold-700)", textDecoration: "none" }}>로그인 →</Link>
      </div>
      <h1 className="hw-page-title" style={{ marginBottom: 6 }}>사무소 이용 신청</h1>
      <p style={{ fontSize: 13, color: "var(--hw-text-sub)", marginBottom: 12, lineHeight: 1.7 }}>
        신청서를 제출하면 관리자 심사 후 사무소 업무공간과 <strong>대표자 관리자 계정 1개, 실무자 계정 1개</strong>가
        발급됩니다. 신청 즉시 계정이 생성되지는 않습니다.
      </p>
      <ol style={{ fontSize: 12.5, color: "var(--hw-text-sub)", lineHeight: 1.7, background: "var(--hw-gold-50)", border: "1px solid var(--hw-gold-200)", borderRadius: 8, padding: "12px 16px 12px 30px", marginBottom: 20 }}>
        <li>신청서 접수</li>
        <li>관리자 심사</li>
        <li>사무소 승인</li>
        <li>대표자 관리자 계정·실무자 계정 발급</li>
        <li>활성화 링크로 각자 비밀번호 설정 (자동 이메일 없음 — 관리자가 직접 안내)</li>
      </ol>

      {renderGroup("사무소 정보", OFFICE_FIELDS)}
      {renderGroup("실무자용 계정 발급 정보", STAFF_FIELDS)}

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
