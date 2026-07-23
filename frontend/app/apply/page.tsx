"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { officeApplicationApi } from "@/lib/api";

// 무자격 업장·택배대행 회원 가입 방지 — 서류 이메일 제출 안내(운영 정책 문구).
const DOCS_NOTICE =
  "무자격 업장 및 택배대행 회원의 가입을 방지하기 위해, 이용신청 후 사업자등록증과 사업장 사진 3장을 " +
  "chan@hanwory.com으로 보내주시기 바랍니다. 제출 자료를 확인한 후 승인하며, 자료가 제출되지 않거나 " +
  "실제 사업장 확인이 어려운 경우 승인되지 않습니다.";
const DOCS_CONFIRM_LABEL =
  "사업자등록증과 사업장 사진 3장을 이메일로 제출해야 승인된다는 내용을 확인했습니다.";

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
  const [agreeDocs, setAgreeDocs] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState<string | null>(null);
  const [availability, setAvailability] = useState<Availability>("loading");
  // 동기식 inflight guard — React 재렌더 이전에도 두 번째 제출을 즉시 차단(더블클릭·Enter+클릭 중복 방지).
  const inflightRef = useRef(false);

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
    // 동기식 중복 제출 차단 — state 재렌더보다 먼저 실행되므로 빠른 더블클릭·Enter 겹침을 잡는다.
    if (inflightRef.current) return;
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
    if (!agreeDocs) { setError("서류 제출 확인에 동의해 주세요."); return; }
    if (!agreePrivacy || !agreeTerms) { setError("개인정보 및 이용약관에 동의해 주세요."); return; }
    inflightRef.current = true;
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
        agree_supporting_docs: agreeDocs,
      });
      setReceipt((res.data as { application_id: string }).application_id);
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "신청 접수에 실패했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      inflightRef.current = false;
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
          <div style={{ textAlign: "left", fontSize: 12.5, color: "var(--hw-text-sub)", lineHeight: 1.75,
            background: "var(--hw-gold-50)", border: "1px solid var(--hw-gold-200)", borderRadius: 8,
            padding: "12px 16px", marginTop: 16 }}>
            <div style={{ fontWeight: 700, color: "var(--hw-text)", marginBottom: 6 }}>다음 절차로 진행됩니다</div>
            <ol style={{ paddingLeft: 18, margin: 0 }}>
              <li>신청서 접수</li>
              <li><strong>사업자등록증과 사업장 사진 3장</strong>을 <strong>chan@hanwory.com</strong>으로 이메일 제출</li>
              <li>관리자 자료 확인과 사무소 승인</li>
              <li>관리자가 <strong>가입신청 때 입력한 이메일 주소</strong>로 대표자·실무자 활성화 링크 전달 (대표자·실무자 링크는 서로 다름)</li>
              <li>각 사용자가 링크에서 최초 비밀번호 설정</li>
              <li>이메일(로그인 ID)과 설정한 비밀번호로 로그인</li>
              <li>최초 로그인 후 <strong>마이페이지에서 문서 자동작성 필수정보 입력</strong></li>
              <li>필수정보 저장 후 고객관리·업무관리·문서 자동작성 사용</li>
            </ol>
            <div style={{ marginTop: 8 }}>{DOCS_NOTICE}</div>
            <div style={{ marginTop: 8, background: "#fff", border: "1px dashed var(--hw-gold-300, #E3C77A)", borderRadius: 6, padding: "8px 12px", color: "var(--hw-text)" }}>
              승인 후 최초 로그인하면 마이페이지에서 <strong>대표 전화번호, 사업자등록번호, 사무소 주소, 행정사 주민등록번호</strong>를 반드시 확인·입력하세요.
              이 정보가 없으면 문서 자동작성 결과에 필수정보가 누락될 수 있습니다.
            </div>
          </div>

          {/* 로그인 방법 — 이메일이 로그인 ID, 신청 단계 비밀번호 없음 */}
          <div style={{ textAlign: "left", fontSize: 12.5, color: "#234E52", lineHeight: 1.8,
            background: "#E6FFFA", border: "1px solid #81E6D9", borderRadius: 8, padding: "12px 16px", marginTop: 14 }}>
            <div style={{ fontWeight: 800, color: "#1A202C", marginBottom: 6 }}>로그인 방법</div>
            <ul style={{ paddingLeft: 18, margin: 0 }}>
              <li><strong>로그인 ID는 가입신청 때 입력한 이메일 주소</strong>입니다.</li>
              <li>가입신청 단계에서는 <strong>비밀번호를 입력하지 않습니다.</strong></li>
              <li>관리자가 승인하면 대표자와 실무자에게 <strong>각각 다른 활성화 링크</strong>를 전달합니다.</li>
              <li>각 사용자는 자신의 활성화 링크에서 <strong>최초 비밀번호를 설정</strong>해야 합니다.</li>
              <li>설정 후 로그인 화면에서 <strong>이메일 + 설정한 비밀번호</strong>로 로그인합니다.</li>
              <li>활성화 링크는 자동 이메일로 발송되지 않으며, 관리자가 별도로 전달합니다.</li>
            </ul>
            <div style={{ marginTop: 8, background: "#fff", border: "1px dashed #81E6D9", borderRadius: 6, padding: "8px 12px" }}>
              <div>대표자 로그인 ID = <strong>{(form["representative_email"] || "대표자 이메일").trim()}</strong></div>
              <div>실무자 로그인 ID = <strong>{(form["staff_email"] || "실무자 이메일").trim()}</strong></div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 20, alignItems: "center", flexWrap: "wrap" }}>
            <button className="btn-secondary" onClick={() => { navigator.clipboard?.writeText(receipt); }}>
              접수번호 복사
            </button>
            <Link href="/login" className="btn-secondary" style={{ textDecoration: "none" }}>
              로그인 화면으로
            </Link>
            <span style={{ fontSize: 11.5, color: "var(--hw-text-sub)" }}>승인 및 활성화 링크 전달 전에는 로그인할 수 없습니다.</span>
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
      <ol style={{ fontSize: 12.5, color: "var(--hw-text-sub)", lineHeight: 1.7, background: "var(--hw-gold-50)", border: "1px solid var(--hw-gold-200)", borderRadius: 8, padding: "12px 16px 12px 30px", marginBottom: 16 }}>
        <li>신청서 접수</li>
        <li>사업자등록증·사업장 사진 3장 이메일 제출</li>
        <li>관리자 심사·사무소 승인</li>
        <li>대표자 관리자 계정·실무자 계정 발급</li>
        <li>활성화 링크로 각자 비밀번호 설정 (자동 이메일 없음 — 관리자가 직접 안내)</li>
      </ol>

      {/* 서류 제출 안내(폼 상단) */}
      <div style={{ fontSize: 12.5, color: "#7B341E", lineHeight: 1.75, background: "#FFFAF0",
        border: "1px solid #F6AD55", borderRadius: 8, padding: "12px 16px", marginBottom: 20 }}>
        <div style={{ fontWeight: 700, marginBottom: 4 }}>제출 서류 안내</div>
        {DOCS_NOTICE}
      </div>

      {renderGroup("사무소 정보", OFFICE_FIELDS)}
      {renderGroup("실무자용 계정 발급 정보", STAFF_FIELDS)}

      <div className="hw-card" style={{ marginBottom: 16 }}>
        <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 13, marginBottom: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={agreeDocs} onChange={(e) => setAgreeDocs(e.target.checked)} style={{ marginTop: 3 }} />
          <span>{DOCS_CONFIRM_LABEL}</span>
        </label>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, marginBottom: 8, cursor: "pointer" }}>
          <input type="checkbox" checked={agreePrivacy} onChange={(e) => setAgreePrivacy(e.target.checked)} />
          <span>개인정보 수집·이용에 동의합니다. (신청 심사 목적)</span>
        </label>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 13, cursor: "pointer" }}>
          <input type="checkbox" checked={agreeTerms} onChange={(e) => setAgreeTerms(e.target.checked)} />
          <span>서비스 이용약관에 동의합니다.</span>
        </label>
      </div>

      {/* 제출 버튼 바로 위 서류 제출 재안내 */}
      <div style={{ fontSize: 12, color: "var(--hw-text-sub)", lineHeight: 1.7, marginBottom: 8 }}>
        신청 제출 후 <strong>사업자등록증과 사업장 사진 3장</strong>을 <strong>chan@hanwory.com</strong>으로 보내주세요.
        자료 확인 후 승인됩니다.
      </div>

      {error && (
        <div style={{ background: "#FFF5F5", border: "1px solid #FEB2B2", color: "#C53030",
          borderRadius: 8, padding: "10px 14px", fontSize: 13, marginBottom: 12 }}>
          {error}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button className="btn-primary" onClick={submit}
          disabled={submitting || !agreeDocs || !agreePrivacy || !agreeTerms}>
          {submitting ? "접수 중..." : "이용 신청 제출"}
        </button>
        <Link href="/login" className="btn-secondary" style={{ textDecoration: "none" }}>취소</Link>
      </div>
    </div>
  );
}
