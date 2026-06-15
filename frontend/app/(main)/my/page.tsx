"use client";
import { useState, useEffect } from "react";
import { toast } from "sonner";
import { api, businessCardApi, type BusinessCard } from "@/lib/api";
import { Save, KeyRound, User, Plus, X as XIcon, Copy, ExternalLink } from "lucide-react";
import SignatureModal from "@/components/SignatureModal";
import { useSubmit } from "@/lib/useSubmit";
import { SubmitButton } from "@/components/SubmitButton";

const PUBLIC_BASE = "https://www.hanwory.com";

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

// ── 전자명함 섹션 ──────────────────────────────────────────────────────────
function BusinessCardSection() {
  const [card, setCard] = useState<BusinessCard | null>(null);
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [bio, setBio] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [slug, setSlug] = useState("");
  const [isPublic, setIsPublic] = useState(false);
  const [fields, setFields] = useState<string[]>(["", "", ""]);
  const { submit: save, isSubmitting: saving } = useSubmit();

  const load = (c: BusinessCard) => {
    setCard(c);
    // 편집칸은 '원본 저장값'(raw)으로 채운다. 비워두면 공개 명함에서 사무소 연락처/주소로
    // fallback 되므로, effective 값을 미리 채워 fallback을 굳혀버리지 않도록 한다.
    setPhone(c.raw?.card_phone ?? "");
    setAddress(c.raw?.card_address ?? "");
    setBio(c.bio || "");
    setLogoUrl(c.raw?.card_logo_url ?? "");
    setSlug(c.public_slug || "");
    setIsPublic(!!c.is_public);
    // 저장된 업무분야만 채우고, 없으면 빈 3칸(placeholder 예시만). 기본값을 실제로 넣지 않는다.
    const raw = c.raw?.card_work_fields;
    const wf = (raw && raw.length ? raw.slice() : ["", "", ""]);
    while (wf.length < 3) wf.push("");
    setFields(wf);
  };

  useEffect(() => {
    businessCardApi.getMine().then((r) => load(r.data)).catch(() => {});
  }, []);

  const publicUrl = slug ? `${PUBLIC_BASE}/card/${slug}` : "";

  const handleSave = () => {
    save(
      async () => {
        const r = await businessCardApi.updateMine({
          phone, address, bio, logo_url: logoUrl,
          work_fields: fields.map((f) => f.trim()).filter(Boolean),
          public_slug: slug.trim(),
          is_public: isPublic,
        });
        load(r.data);
      },
      { successMessage: "전자명함이 저장되었습니다.", errorMessage: "저장 실패" }
    );
  };

  const copyLink = async () => {
    if (!publicUrl) return;
    try { await navigator.clipboard.writeText(publicUrl); toast.success("공개 링크가 복사되었습니다."); }
    catch { toast.error("복사 실패 — 링크를 직접 선택해 복사하세요."); }
  };

  return (
    <Section title="전자명함">
      <div style={{ fontSize: 11, color: "#A0AEC0", marginBottom: 14, lineHeight: 1.6 }}>
        공개로 설정하면 <b>로그인 없이</b> 열람 가능한 명함 링크가 생성됩니다. 내부 계정·권한 정보는 공개되지 않습니다.
      </div>

      <Field label="전화번호" value={phone} onChange={setPhone} placeholder="비워두면 사무소 연락처 사용" />
      <Field label="주소" value={address} onChange={setAddress} placeholder="비워두면 사무소 주소 사용" />

      <div style={{ marginBottom: 14 }}>
        <label style={{ display: "block", fontSize: 11, color: "#718096", marginBottom: 4, fontWeight: 600 }}>약력</label>
        <textarea value={bio} onChange={(e) => setBio(e.target.value)} placeholder="간단한 소개 / 약력"
          className="hw-input" style={{ width: "100%", boxSizing: "border-box", height: 72, resize: "vertical", fontSize: 13 }} />
      </div>

      {/* 업무분야 — 빈 칸 + 회색 placeholder 예시(저장값 아님). 입력한 값만 공개 명함에 표시됨 */}
      <div style={{ marginBottom: 14 }}>
        <label style={{ display: "block", fontSize: 11, color: "#718096", marginBottom: 4, fontWeight: 600 }}>주력 업무</label>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {fields.map((f, i) => {
            const phs = ["예: 외국인 체류기간 연장", "예: 중국 공증·아포스티유", "예: 영주권·귀화 신청"];
            const ph = phs[i] || "예: 주력 업무를 입력하세요";
            return (
              <div key={i} style={{ display: "flex", gap: 6, alignItems: "center" }}>
                <input value={f} onChange={(e) => setFields((p) => p.map((v, j) => j === i ? e.target.value : v))}
                  placeholder={ph} className="hw-input" style={{ flex: 1, boxSizing: "border-box" }} />
                <button type="button" onClick={() => setFields((p) => p.filter((_, j) => j !== i))}
                  style={{ background: "none", border: "none", cursor: "pointer", color: "#CBD5E0", padding: 4 }} aria-label="삭제">
                  <XIcon size={14} />
                </button>
              </div>
            );
          })}
        </div>
        <button type="button" onClick={() => setFields((p) => [...p, ""])}
          style={{ marginTop: 8, display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, color: GOLD, background: "none", border: "none", cursor: "pointer", fontWeight: 600 }}>
          <Plus size={13} /> 업무분야 추가
        </button>
        <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: 6 }}>
          위 회색 예시는 안내일 뿐 저장되지 않습니다. 직접 입력한 업무만 공개 명함에 표시됩니다.
        </div>
      </div>

      <Field label="로고 URL (선택)" value={logoUrl} onChange={setLogoUrl} placeholder="https://example.com/logo.png" />
      <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: -8, marginBottom: 14, lineHeight: 1.6 }}>
        로고 이미지는 인터넷에서 접근 가능한 이미지 주소(URL)를 입력해야 표시됩니다. 입력하지 않으면 전자명함에 로고가 표시되지 않습니다.
      </div>

      {/* 공개 설정 */}
      <div style={{ borderTop: `1px solid ${BORDER}`, marginTop: 6, paddingTop: 14 }}>
        <Field label="공개 주소(slug)" value={slug} onChange={(v) => setSlug(v.toLowerCase())} placeholder="예: hanwoori (영문 소문자·숫자·하이픈)" />
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#2D3748", cursor: "pointer", marginBottom: 4 }}>
          <input type="checkbox" checked={isPublic} onChange={(e) => setIsPublic(e.target.checked)} style={{ width: 15, height: 15, accentColor: GOLD }} />
          전자명함 공개 (링크로 누구나 열람 가능)
        </label>
        {isPublic && !slug.trim() && (
          <div style={{ fontSize: 11, color: "#C53030", marginBottom: 6 }}>공개하려면 공개 주소(slug)를 입력하세요.</div>
        )}
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
        <SubmitButton isSubmitting={saving} onClick={handleSave} loadingText="저장 중..." className="text-xs" style={{ padding: "6px 12px", fontSize: 12 }}>
          <><Save size={12} /> 저장</>
        </SubmitButton>
      </div>

      {/* 공개 링크 + 미리보기 */}
      {card?.is_public && card.public_slug && (
        <div style={{ marginTop: 14, padding: "12px 14px", background: "#FBF8F0", border: `1px solid #EAD9A8`, borderRadius: 10 }}>
          <div style={{ fontSize: 11, color: "#8A6D1F", fontWeight: 700, marginBottom: 6 }}>공개 링크</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <a href={`${PUBLIC_BASE}/card/${card.public_slug}`} target="_blank" rel="noopener noreferrer"
              style={{ fontSize: 13, color: "#2B6CB0", textDecoration: "none", wordBreak: "break-all", flex: 1, minWidth: 0 }}>
              {PUBLIC_BASE}/card/{card.public_slug}
            </a>
            <button type="button" onClick={copyLink} className="text-xs"
              style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "5px 10px", borderRadius: 7, border: `1px solid ${BORDER}`, background: "#fff", cursor: "pointer", color: "#4A5568" }}>
              <Copy size={12} /> 복사
            </button>
            <a href={`/card/${card.public_slug}`} target="_blank" rel="noopener noreferrer" className="text-xs"
              style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "5px 10px", borderRadius: 7, border: `1px solid ${BORDER}`, background: "#fff", textDecoration: "none", color: "#4A5568" }}>
              <ExternalLink size={12} /> 미리보기
            </a>
          </div>
        </div>
      )}
    </Section>
  );
}

export default function MyPage() {
  // ── 사무소 정보 ──
  const [info, setInfo] = useState<MyInfo>({
    login_id: "", office_name: "", office_adr: "",
    contact_name: "", contact_tel: "", biz_reg_no: "", agent_rrn: "",
  });
  const { submit: submitInfo, isSubmitting: infoSaving } = useSubmit();

  // ── 비밀번호 ──
  const [pwForm, setPwForm] = useState({ current: "", next: "", confirm: "" });
  const { submit: submitPw, isSubmitting: pwSaving } = useSubmit();

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

  const handleInfoSave = () => {
    submitInfo(
      async () => {
        await api.patch("/api/auth/me", {
          office_name:  info.office_name,
          office_adr:   info.office_adr,
          contact_name: info.contact_name,
          contact_tel:  info.contact_tel,
        });
      },
      { successMessage: "사무소 정보가 저장되었습니다.", errorMessage: "저장 실패" }
    );
  };

  const handlePasswordChange = () => {
    if (!pwForm.current) { toast.error("현재 비밀번호를 입력하세요."); return; }
    if (pwForm.next.length < 6) { toast.error("새 비밀번호는 6자 이상이어야 합니다."); return; }
    if (pwForm.next !== pwForm.confirm) { toast.error("새 비밀번호가 일치하지 않습니다."); return; }
    submitPw(
      async () => {
        await api.patch("/api/auth/me/password", {
          current_password: pwForm.current,
          new_password:     pwForm.next,
        });
      },
      {
        successMessage: "비밀번호가 변경되었습니다.",
        errorMessage: "비밀번호 변경 실패",
        onSuccess: () => setPwForm({ current: "", next: "", confirm: "" }),
      }
    );
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
          <SubmitButton
            isSubmitting={infoSaving}
            onClick={handleInfoSave}
            loadingText="저장 중..."
            className="text-xs"
            style={{ padding: "6px 12px", fontSize: 12 }}
          >
            <><Save size={12} /> 저장</>
          </SubmitButton>
        </div>
      </Section>

      {/* 전자명함 */}
      <BusinessCardSection />

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
          <SubmitButton
            isSubmitting={pwSaving}
            onClick={handlePasswordChange}
            loadingText="변경 중..."
            className="text-xs"
            style={{ padding: "6px 12px", fontSize: 12 }}
          >
            <><KeyRound size={12} /> 변경</>
          </SubmitButton>
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
