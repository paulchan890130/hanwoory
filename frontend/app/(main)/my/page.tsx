"use client";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Save, KeyRound, User } from "lucide-react";
import SignatureModal from "@/components/SignatureModal";

const GOLD = "#D4A843";
const BORDER = "#E2E8F0";

interface MyInfo {
  login_id: string;
  office_name: string;
  office_adr: string;
  contact_name: string;
  contact_tel: string;
  biz_reg_no: string;
  agent_rrn: string;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{
      background: "#fff", border: `1px solid ${BORDER}`,
      borderRadius: 12, padding: "20px 24px",
      boxShadow: "0 1px 4px rgba(0,0,0,0.05)",
    }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 18, display: "flex", alignItems: "center", gap: 6 }}>
        {title}
      </div>
      {children}
    </div>
  );
}

function Field({ label, value, onChange, type = "text", placeholder = "" }: {
  label: string; value: string; onChange: (v: string) => void;
  type?: string; placeholder?: string;
}) {
  return (
    <div style={{ marginBottom: 14 }}>
      <label style={{ display: "block", fontSize: 11, color: "#718096", marginBottom: 4, fontWeight: 600 }}>{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="hw-input"
        style={{ width: "100%", boxSizing: "border-box" }}
      />
    </div>
  );
}

export default function MyPage() {
  // ── 사무소 정보 ──
  const [info, setInfo] = useState<MyInfo>({
    login_id: "", office_name: "", office_adr: "",
    contact_name: "", contact_tel: "", biz_reg_no: "", agent_rrn: "",
  });
  const [infoSaving, setInfoSaving] = useState(false);

  // ── 비밀번호 ──
  const [pwForm, setPwForm] = useState({ current: "", next: "", confirm: "" });
  const [pwSaving, setPwSaving] = useState(false);

  // ── 서명 ──
  const [signData, setSignData] = useState<string | null>(null);
  const [showSignModal, setShowSignModal] = useState(false);

  useEffect(() => {
    api.get<MyInfo>("/api/auth/me")
      .then((r) => setInfo(r.data))
      .catch(() => {});
    api.get<{ data: string | null }>("/api/signature/agent")
      .then((r) => setSignData(r.data.data ?? null))
      .catch(() => {});
  }, []);

  const handleInfoSave = async () => {
    setInfoSaving(true);
    try {
      await api.patch("/api/auth/me", {
        office_name:  info.office_name,
        office_adr:   info.office_adr,
        contact_name: info.contact_name,
        contact_tel:  info.contact_tel,
      });
      toast.success("사무소 정보가 저장되었습니다.");
    } catch {
      toast.error("저장 실패");
    } finally {
      setInfoSaving(false);
    }
  };

  const handlePasswordChange = async () => {
    if (!pwForm.current) { toast.error("현재 비밀번호를 입력하세요."); return; }
    if (pwForm.next.length < 6) { toast.error("새 비밀번호는 6자 이상이어야 합니다."); return; }
    if (pwForm.next !== pwForm.confirm) { toast.error("새 비밀번호가 일치하지 않습니다."); return; }
    setPwSaving(true);
    try {
      await api.patch("/api/auth/me/password", {
        current_password: pwForm.current,
        new_password:     pwForm.next,
      });
      toast.success("비밀번호가 변경되었습니다.");
      setPwForm({ current: "", next: "", confirm: "" });
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(msg || "비밀번호 변경 실패");
    } finally {
      setPwSaving(false);
    }
  };

  return (
    <div style={{ maxWidth: 560, display: "flex", flexDirection: "column", gap: 20 }}>
      {/* 헤더 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <User size={18} style={{ color: GOLD }} />
        <h1 className="hw-page-title">마이페이지</h1>
        {info.login_id && (
          <span style={{ fontSize: 12, color: "#A0AEC0", marginLeft: 4 }}>({info.login_id})</span>
        )}
      </div>

      {/* 사무소 정보 */}
      <Section title="사무소 정보">
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 16px" }}>
          <div style={{ gridColumn: "1 / -1" }}>
            <Field label="사무소명" value={info.office_name}
              onChange={(v) => setInfo((p) => ({ ...p, office_name: v }))} />
          </div>
          <div style={{ gridColumn: "1 / -1" }}>
            <Field label="주소" value={info.office_adr}
              onChange={(v) => setInfo((p) => ({ ...p, office_adr: v }))}
              placeholder="사무소 주소" />
          </div>
          <Field label="담당자" value={info.contact_name}
            onChange={(v) => setInfo((p) => ({ ...p, contact_name: v }))} />
          <Field label="연락처" value={info.contact_tel}
            onChange={(v) => setInfo((p) => ({ ...p, contact_tel: v }))}
            placeholder="010-0000-0000" />
        </div>
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 4 }}>
          <button
            onClick={handleInfoSave}
            disabled={infoSaving}
            className="btn-primary flex items-center gap-1.5 text-xs disabled:opacity-50"
          >
            <Save size={12} /> {infoSaving ? "저장 중..." : "저장"}
          </button>
        </div>
      </Section>

      {/* 비밀번호 변경 */}
      <Section title="비밀번호 변경">
        <Field label="현재 비밀번호" value={pwForm.current} type="password"
          onChange={(v) => setPwForm((p) => ({ ...p, current: v }))} />
        <Field label="새 비밀번호" value={pwForm.next} type="password"
          placeholder="6자 이상"
          onChange={(v) => setPwForm((p) => ({ ...p, next: v }))} />
        <Field label="새 비밀번호 확인" value={pwForm.confirm} type="password"
          onChange={(v) => setPwForm((p) => ({ ...p, confirm: v }))} />
        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 4 }}>
          <button
            onClick={handlePasswordChange}
            disabled={pwSaving}
            className="btn-primary flex items-center gap-1.5 text-xs disabled:opacity-50"
          >
            <KeyRound size={12} /> {pwSaving ? "변경 중..." : "변경"}
          </button>
        </div>
      </Section>

      {/* 내 서명 */}
      <Section title="내 서명">
        <div style={{
          width: "100%", minHeight: 80, border: `1px solid ${BORDER}`,
          borderRadius: 8, background: "#FAFAFA", marginBottom: 14,
          display: "flex", alignItems: "center", justifyContent: "center",
          overflow: "hidden",
        }}>
          {signData
            ? <img src={signData} alt="행정사 서명" style={{ maxWidth: "100%", maxHeight: 120 }} />
            : <span style={{ fontSize: 12, color: "#A0AEC0" }}>등록된 서명 없음</span>
          }
        </div>
        <button
          onClick={() => setShowSignModal(true)}
          className="btn-primary text-xs"
          style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
        >
          {signData ? "서명 재등록" : "서명 등록"}
        </button>
      </Section>

      {/* 서명 모달 */}
      {showSignModal && (
        <SignatureModal
          type="agent"
          onSave={(data) => {
            setSignData(data);
            toast.success("서명이 등록되었습니다.");
          }}
          onClose={() => setShowSignModal(false)}
        />
      )}
    </div>
  );
}
