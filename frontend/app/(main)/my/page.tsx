"use client";
import { useState, useEffect, useRef } from "react";
import { toast } from "sonner";
import { api, businessCardApi, type BusinessCard } from "@/lib/api";
import { Save, KeyRound, User, Plus, X as XIcon, Copy, ExternalLink, Upload, Trash2, ChevronDown } from "lucide-react";
import SignatureModal from "@/components/SignatureModal";
import { useSubmit } from "@/lib/useSubmit";
import { SubmitButton } from "@/components/SubmitButton";
import MySecuritySection from "@/components/my/MySecuritySection";

const PUBLIC_BASE = "https://www.hanwory.com";

const GOLD = "#D4A843";
const BORDER = "#E2E8F0";

// 로고 업로드 정책(프론트 1차 검증 — 서버도 동일 정책으로 재검증)
const LOGO_MAX_BYTES = 200 * 1024;
const LOGO_ALLOWED_MIME = ["image/jpeg", "image/png", "image/webp"];
const LOGO_ACCEPT = LOGO_ALLOWED_MIME.join(",");

const lblStyle: React.CSSProperties = { display: "block", fontSize: 11, color: "#718096", marginBottom: 4, fontWeight: 600 };
const inpStyle: React.CSSProperties = { width: "100%", boxSizing: "border-box" };

interface MyInfo {
  login_id: string;
  role?: string;
  office_role?: string | null;
  is_admin?: boolean;
  is_master?: boolean;
  office_name: string;
  office_adr: string;
  contact_name: string;
  contact_tel: string;
  contact_tel_source?: string;
  biz_reg_no: string;
  agent_rrn_registered?: boolean;
  agent_rrn_last4?: string;
  profile_complete?: boolean;
  missing_profile_fields?: string[];
}

// 화면 표시용 하이픈 형식(백엔드 korean_identifier_format 와 동일 규칙 — 저장은 서버가 숫자 정규화).
function fmtPhoneKR(v: string): string {
  const d = (v || "").replace(/[^0-9]/g, "");
  if (d.startsWith("02")) {
    if (d.length === 9) return `${d.slice(0, 2)}-${d.slice(2, 5)}-${d.slice(5)}`;
    if (d.length === 10) return `${d.slice(0, 2)}-${d.slice(2, 6)}-${d.slice(6)}`;
  } else {
    if (d.length === 10) return `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6)}`;
    if (d.length === 11) return `${d.slice(0, 3)}-${d.slice(3, 7)}-${d.slice(7)}`;
  }
  return d;
}
function fmtBizKR(v: string): string {
  const d = (v || "").replace(/[^0-9]/g, "");
  return d.length === 10 ? `${d.slice(0, 3)}-${d.slice(3, 5)}-${d.slice(5)}` : d;
}
const PROFILE_FIELD_LABELS: Record<string, string> = {
  office_name: "사무소명", office_adr: "사무소 주소", contact_name: "담당자명",
  contact_tel: "대표 전화번호", biz_reg_no: "사업자등록번호", agent_rrn: "행정사 주민등록번호",
};

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
  const [saving, setSaving] = useState(false);

  // ── 로고 상태(즉시 업로드하지 않고 최종 '저장' 때 텍스트와 함께 반영) ──
  const [hasLogo, setHasLogo] = useState(false);
  const [savedPreview, setSavedPreview] = useState<string | null>(null);   // 저장된 로고 blob URL
  const [pendingFile, setPendingFile] = useState<File | null>(null);       // 선택했으나 미반영(저장 시 업로드)
  const [pendingPreview, setPendingPreview] = useState<string | null>(null);
  const [markedForDelete, setMarkedForDelete] = useState(false);           // 저장 시 로고 삭제
  const [showAdvanced, setShowAdvanced] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const load = (c: BusinessCard) => {
    setCard(c);
    // 편집칸은 '원본 저장값'(raw)으로 채운다. 비워두면 공개 명함에서 사무소 연락처/주소로
    // fallback 되므로, effective 값을 미리 채워 fallback을 굳혀버리지 않도록 한다.
    setPhone(c.raw?.card_phone ?? "");
    setAddress(c.raw?.card_address ?? "");
    setBio(c.bio || "");
    setLogoUrl(c.raw?.card_logo_url ?? "");
    setHasLogo(!!c.has_logo);
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

  // 저장된 로고가 있으면(그리고 선택 대기 중인 파일이 없으면) blob 미리보기를 받아온다.
  useEffect(() => {
    let revoked: string | null = null;
    if (hasLogo && !pendingFile) {
      businessCardApi.getMyLogoBlob()
        .then((r) => {
          const url = URL.createObjectURL(r.data);
          revoked = url;
          setSavedPreview((prev) => { if (prev) URL.revokeObjectURL(prev); return url; });
        })
        .catch(() => setSavedPreview(null));
    } else if (!hasLogo) {
      setSavedPreview((prev) => { if (prev) URL.revokeObjectURL(prev); return null; });
    }
    return () => { if (revoked) { /* keep until replaced */ } };
  }, [hasLogo, pendingFile, card?.logo_updated_at]);

  const publicUrl = slug ? `${PUBLIC_BASE}/card/${slug}` : "";
  // 로고 미리보기: 새로 고른 파일 > (삭제 예정이면 없음) > 저장된 로고
  const logoToShow = pendingPreview || (markedForDelete ? null : savedPreview);
  const logoPendingChange = !!pendingFile || markedForDelete;

  // slug 검증 — backend(_SLUG_RE)와 동일 기준(영문 소문자·숫자·하이픈, 3~50자).
  const slugTrim = slug.trim();
  const slugBadFormat = !!slugTrim && !/^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$/.test(slugTrim);
  const slugRequiredButEmpty = isPublic && !slugTrim;

  const onPickFile = (f: File | null) => {
    if (!f) return;
    if (!LOGO_ALLOWED_MIME.includes(f.type)) {
      toast.error("JPG / PNG / WEBP 형식만 업로드할 수 있습니다.");
      return;
    }
    if (f.size > LOGO_MAX_BYTES) {
      toast.error("로고 파일은 200KB 이하만 업로드할 수 있습니다.");
      return;
    }
    setMarkedForDelete(false);
    setPendingFile(f);
    setPendingPreview((prev) => { if (prev) URL.revokeObjectURL(prev); return URL.createObjectURL(f); });
  };

  const cancelPending = () => {
    setPendingPreview((prev) => { if (prev) URL.revokeObjectURL(prev); return null; });
    setPendingFile(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  // 최종 저장 — 텍스트 + 로고(업로드/삭제)를 한 번에 반영하고, 끝나면 재조회로 state 갱신.
  // 실패 시 입력 state 는 그대로 유지(절대 초기화하지 않음)하고 어느 단계에서 실패했는지 알린다.
  const handleSave = async () => {
    if (slugBadFormat) { toast.error("공개주소는 영문 소문자·숫자·하이픈(-)만, 3자 이상 입력해 주세요."); return; }
    if (slugRequiredButEmpty) { toast.error("공개하려면 공개 주소(slug)를 입력하세요."); return; }
    if (saving) return;
    setSaving(true);
    let step = "명함 내용";
    try {
      await businessCardApi.updateMine({
        phone, address, bio, logo_url: logoUrl,
        work_fields: fields.map((f) => f.trim()).filter(Boolean),
        public_slug: slugTrim,
        is_public: isPublic,
      });
      if (pendingFile) {
        step = "로고 업로드";
        await businessCardApi.uploadLogo(pendingFile);
      } else if (markedForDelete) {
        step = "로고 삭제";
        await businessCardApi.deleteLogo();
      }
      step = "재조회";
      const r = await businessCardApi.getMine();
      load(r.data);              // 재조회 결과(raw 포함)로만 state 갱신 → 입력값 보존
      cancelPending();
      setMarkedForDelete(false);
      toast.success("전자명함이 저장되었습니다.");
    } catch (e: any) {
      const detail = e?.response?.data?.detail;
      const note = step === "명함 내용" ? "" : " (명함 내용은 저장되었을 수 있습니다)";
      toast.error(`저장 실패 — ${step} 단계${detail ? `: ${detail}` : ""}.${note} 입력값은 그대로 유지됩니다.`);
      // load() 호출하지 않음 → 사용자가 입력한 텍스트/로고 선택 유지
    } finally {
      setSaving(false);
    }
  };

  const copyLink = async () => {
    if (!publicUrl) return;
    try { await navigator.clipboard.writeText(publicUrl); toast.success("공개 링크가 복사되었습니다."); }
    catch { toast.error("복사 실패 — 링크를 직접 선택해 복사하세요."); }
  };

  return (
    <Section title="전자명함">
      <div style={{ fontSize: 11, color: "#A0AEC0", marginBottom: 6, lineHeight: 1.6 }}>
        공개로 설정하면 <b>로그인 없이</b> 열람 가능한 명함 링크가 생성됩니다. 내부 계정·권한 정보는 공개되지 않습니다.
      </div>
      {/* 저장-반영 안내(내부 마이페이지에만 표시 — 공개 명함에는 표시하지 않음) */}
      <div style={{ fontSize: 11, color: "#8A6D1F", background: "#FBF8F0", border: `1px solid #EAD9A8`,
        borderRadius: 8, padding: "8px 11px", marginBottom: 14, lineHeight: 1.6 }}>
        저장한 내용과 로고는 <b>공개 전자명함 링크에 즉시 반영</b>됩니다. 별도 배포나 관리자 작업이 필요하지 않습니다.
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

      {/* ── 로고 (파일 업로드) ── */}
      <div style={{ marginBottom: 14 }}>
        <label style={{ display: "block", fontSize: 11, color: "#718096", marginBottom: 6, fontWeight: 600 }}>로고</label>
        <input ref={fileRef} type="file" accept={LOGO_ACCEPT} style={{ display: "none" }}
          onChange={(e) => onPickFile(e.target.files?.[0] ?? null)} />

        <div style={{ display: "flex", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
          {/* 미리보기 / 없음 */}
          <div style={{
            width: 72, height: 72, flexShrink: 0, borderRadius: 12,
            border: `1px solid ${BORDER}`, background: "#FAFAFA",
            display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden",
          }}>
            {logoToShow
              ? <img src={logoToShow} alt="로고 미리보기" style={{ width: "100%", height: "100%", objectFit: "contain" }} />
              : <span style={{ fontSize: 10, color: "#A0AEC0", textAlign: "center", lineHeight: 1.4 }}>로고<br/>없음</span>}
          </div>

          <div style={{ flex: 1, minWidth: 160 }}>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button type="button" onClick={() => fileRef.current?.click()} disabled={saving}
                style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "7px 12px", borderRadius: 8,
                  border: `1px solid ${BORDER}`, background: "#fff", color: "#4A5568", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                <Upload size={13} /> {hasLogo && !markedForDelete ? "로고 변경" : "로고 선택"}
              </button>
              {pendingFile && (
                <button type="button" onClick={cancelPending} disabled={saving}
                  style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "7px 12px", borderRadius: 8,
                    border: `1px solid ${BORDER}`, background: "#fff", color: "#4A5568", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                  선택 취소
                </button>
              )}
              {hasLogo && !pendingFile && !markedForDelete && (
                <button type="button" onClick={() => setMarkedForDelete(true)} disabled={saving}
                  style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "7px 12px", borderRadius: 8,
                    border: `1px solid #FBD5D5`, background: "#fff", color: "#C53030", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                  <Trash2 size={13} /> 로고 삭제
                </button>
              )}
              {markedForDelete && (
                <button type="button" onClick={() => setMarkedForDelete(false)} disabled={saving}
                  style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "7px 12px", borderRadius: 8,
                    border: `1px solid ${BORDER}`, background: "#fff", color: "#4A5568", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
                  삭제 취소
                </button>
              )}
            </div>
            <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: 8, lineHeight: 1.6 }}>
              권장: 512px × 512px, JPG/PNG/WEBP, 200KB 이하 (정사각형 권장)<br/>
              로고를 등록하지 않으면 전자명함에는 로고가 표시되지 않습니다.
            </div>
            {logoPendingChange && (
              <div style={{ fontSize: 11, color: "#8A6D1F", background: "#FBF8F0", border: `1px solid #EAD9A8`,
                borderRadius: 8, padding: "7px 10px", marginTop: 8, lineHeight: 1.6 }}>
                {pendingFile ? "선택한 로고" : "로고 삭제"}는 아래 <b>저장</b> 버튼을 누르면 명함 내용과 <b>함께 반영</b>됩니다.
              </div>
            )}
          </div>
        </div>

        {/* 고급 설정 — 외부 로고 URL(보조, 하위호환). 업로드 로고가 우선 표시됨 */}
        <button type="button" onClick={() => setShowAdvanced((v) => !v)}
          style={{ marginTop: 10, display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11, color: "#A0AEC0", background: "none", border: "none", cursor: "pointer" }}>
          <ChevronDown size={13} style={{ transform: showAdvanced ? "rotate(180deg)" : "none", transition: "transform .15s" }} />
          고급 설정 (외부 로고 URL)
        </button>
        {showAdvanced && (
          <div style={{ marginTop: 8 }}>
            <Field label="로고 URL (선택, 보조)" value={logoUrl} onChange={setLogoUrl} placeholder="https://example.com/logo.png" />
            <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: -8, lineHeight: 1.6 }}>
              업로드한 로고가 있으면 그 로고가 우선 표시됩니다. 외부 URL은 업로드 로고가 없을 때만 사용됩니다.
            </div>
          </div>
        )}
      </div>

      {/* 공개 설정 */}
      <div style={{ borderTop: `1px solid ${BORDER}`, marginTop: 6, paddingTop: 14 }}>
        <Field label="공개 주소(slug)" value={slug} onChange={(v) => setSlug(v.toLowerCase())} placeholder="예: my-office" />
        <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: -8, marginBottom: 8, lineHeight: 1.6 }}>
          공개주소는 영문 소문자·숫자·하이픈(-)만 사용할 수 있으며 <b>3자 이상</b> 입력해야 합니다.
        </div>
        {slugBadFormat && (
          <div style={{ fontSize: 11, color: "#C53030", marginBottom: 6 }}>공개주소는 영문 소문자·숫자·하이픈(-)만, 3자 이상 입력해 주세요.</div>
        )}
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#2D3748", cursor: "pointer", marginBottom: 4 }}>
          <input type="checkbox" checked={isPublic} onChange={(e) => setIsPublic(e.target.checked)} style={{ width: 15, height: 15, accentColor: GOLD }} />
          전자명함 공개 (링크로 누구나 열람 가능)
        </label>
        {slugRequiredButEmpty && (
          <div style={{ fontSize: 11, color: "#C53030", marginBottom: 6 }}>공개하려면 공개 주소(slug)를 입력하세요.</div>
        )}
      </div>

      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 8 }}>
        <SubmitButton isSubmitting={saving} disabled={slugBadFormat || slugRequiredButEmpty}
          onClick={handleSave} loadingText="저장 중..." className="text-xs" style={{ padding: "6px 12px", fontSize: 12 }}>
          <><Save size={12} /> 전자명함 저장</>
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
    contact_name: "", contact_tel: "", biz_reg_no: "",
  });
  const { submit: submitInfo, isSubmitting: infoSaving } = useSubmit();

  // ── 행정사 주민등록번호(등록/변경) ──
  const [rrnEditing, setRrnEditing] = useState(false);
  const [rrnForm, setRrnForm] = useState({ value: "", confirm: "" });
  const { submit: submitRrn, isSubmitting: rrnSaving } = useSubmit();

  // ── 비밀번호 ──
  const [pwForm, setPwForm] = useState({ current: "", next: "", confirm: "" });
  const { submit: submitPw, isSubmitting: pwSaving } = useSubmit();

  // ── 서명 ──
  const [signData, setSignData] = useState<string | null>(null);
  const [showSignModal, setShowSignModal] = useState(false);

  const reloadMe = () => api.get<MyInfo>("/api/auth/me").then((r) => setInfo(r.data)).catch(() => {});

  useEffect(() => {
    reloadMe();
    api.get<{ data: string | null }>("/api/signature/agent")
      .then((r) => setSignData(r.data.data ?? null))
      .catch(() => {});
  }, []);

  // 대표자(사무소 관리자) 또는 전체 관리자만 tenant 공통정보(사무소명·주소·사업자번호·주민번호) 편집.
  // canonical office_role 기준(DB role=admin/user 와 분리).
  const canEditTenant = info.office_role === "office_admin" || !!info.is_admin || !!info.is_master;
  const isStaff = info.office_role === "office_staff";

  const handleInfoSave = () => {
    const intendedTel = (info.contact_tel || "").replace(/[^0-9]/g, "");
    submitInfo(
      async () => {
        const payload: Record<string, string> = {
          contact_name: info.contact_name,
          contact_tel:  info.contact_tel,
        };
        if (canEditTenant) {
          payload.office_name = info.office_name;
          payload.office_adr = info.office_adr;
          payload.biz_reg_no = info.biz_reg_no;
        }
        await api.patch("/api/auth/me", payload);
        // 저장 후 서버 재조회로 확정 — 재조회 값이 저장 의도와 다르면 성공으로 처리하지 않는다.
        const fresh = (await api.get<MyInfo>("/api/auth/me")).data;
        setInfo(fresh);
        const savedTel = (fresh.contact_tel || "").replace(/[^0-9]/g, "");
        if (savedTel !== intendedTel) {
          throw new Error("저장한 연락처가 재조회 값과 일치하지 않습니다. 다시 시도해 주세요.");
        }
      },
      { successMessage: "문서 자동작성 필수정보가 저장되었습니다.", errorMessage: "저장 실패" }
    );
  };

  const handleRrnSave = () => {
    const v = rrnForm.value.trim();
    const c = rrnForm.confirm.trim();
    if (!v) { toast.error("행정사 주민등록번호를 입력하세요."); return; }
    if (v !== c) { toast.error("행정사 주민등록번호 확인이 일치하지 않습니다."); return; }
    submitRrn(
      async () => {
        const { authApi } = await import("@/lib/api");
        await authApi.updateAgentRrn(v);   // 원문은 서버에서 암호화, 응답에 원문 없음
        setRrnForm({ value: "", confirm: "" });  // 저장 후 원문 input 즉시 제거
        setRrnEditing(false);
        await reloadMe();
      },
      { successMessage: "행정사 주민등록번호가 저장되었습니다.", errorMessage: "저장 실패(형식 또는 보안 설정 확인)" }
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

      {/* 문서 자동작성 필수정보 */}
      <Section title="문서 자동작성 필수정보">
        <div data-tour-id="profile-required-info">
        {info.profile_complete === false && (
          <div style={{ background: "#FFF5F5", border: "1px solid #FEB2B2", color: "#C53030",
            borderRadius: 8, padding: "8px 12px", fontSize: 12, marginBottom: 14, lineHeight: 1.6 }}>
            문서 자동작성 필수정보가 아직 완료되지 않았습니다.
            {info.missing_profile_fields?.length ? (
              <> 누락: {info.missing_profile_fields.map((k) => PROFILE_FIELD_LABELS[k] || k).join(", ")}.</>
            ) : null}
            {" "}이 정보가 없으면 문서 자동작성 결과에 필수정보가 누락될 수 있습니다.
          </div>
        )}
        {/* auto-fit → 320px 등 좁은 화면에서 자동 1열 */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "0 16px" }}>
          <div style={{ gridColumn: "1 / -1" }}>
            <label style={lblStyle}>사무소명</label>
            <input className="hw-input" style={{ ...inpStyle, background: canEditTenant ? "#fff" : "#F7FAFC" }}
              value={info.office_name} readOnly={!canEditTenant}
              onChange={(e) => setInfo((p) => ({ ...p, office_name: e.target.value }))} />
          </div>
          <div style={{ gridColumn: "1 / -1" }}>
            <label style={lblStyle}>사무소 주소</label>
            <input className="hw-input" style={{ ...inpStyle, background: canEditTenant ? "#fff" : "#F7FAFC" }}
              value={info.office_adr} placeholder="사무소 주소" readOnly={!canEditTenant}
              onChange={(e) => setInfo((p) => ({ ...p, office_adr: e.target.value }))} />
          </div>
          <Field label="담당자명" value={info.contact_name}
            onChange={(v) => setInfo((p) => ({ ...p, contact_name: v }))} />
          <div style={{ marginBottom: 14 }}>
            <label style={lblStyle}>{isStaff ? "내 연락처" : "대표 전화번호"}</label>
            <input className="hw-input" style={inpStyle}
              value={fmtPhoneKR(info.contact_tel)}
              placeholder="010-0000-0000"
              onChange={(e) => setInfo((p) => ({ ...p, contact_tel: e.target.value.replace(/[^0-9]/g, "") }))} />
            {info.contact_tel_source === "application_fallback" && (
              <div style={{ fontSize: 10.5, color: "#B7791F", marginTop: 3 }}>가입신청서의 대표전화입니다. 저장하면 정식 반영됩니다.</div>
            )}
          </div>
          <div>
            <label style={lblStyle}>사업자등록번호</label>
            <input className="hw-input" style={{ ...inpStyle, background: canEditTenant ? "#fff" : "#F7FAFC" }}
              value={fmtBizKR(info.biz_reg_no)} placeholder="000-00-00000" readOnly={!canEditTenant}
              onChange={(e) => setInfo((p) => ({ ...p, biz_reg_no: e.target.value.replace(/[^0-9]/g, "") }))} />
            {!canEditTenant && <div style={{ fontSize: 10.5, color: "#A0AEC0", marginTop: 3 }}>대표자(사무소 관리자)만 수정할 수 있습니다.</div>}
          </div>
        </div>

        {/* 행정사 주민등록번호 — office_admin 만 입력·변경, 원문 미표시 */}
        <div style={{ marginTop: 6, paddingTop: 12, borderTop: `1px solid ${BORDER}` }}>
          <label style={{ display: "block", fontSize: 11, color: "#718096", marginBottom: 6, fontWeight: 600 }}>행정사 주민등록번호</label>
          {!canEditTenant ? (
            <div style={{ fontSize: 12, color: "#A0AEC0" }}>대표자(사무소 관리자)만 확인·변경할 수 있습니다.</div>
          ) : !rrnEditing ? (
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, color: info.agent_rrn_registered ? "#276749" : "#C53030" }}>
                {info.agent_rrn_registered ? `등록됨 · 끝 4자리 ${info.agent_rrn_last4 || "****"}` : "미등록"}
              </span>
              <button type="button" className="btn-secondary" style={{ fontSize: 12, padding: "5px 10px" }}
                onClick={() => { setRrnForm({ value: "", confirm: "" }); setRrnEditing(true); }}>
                {info.agent_rrn_registered ? "변경" : "입력"}
              </button>
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 16px" }}>
              <Field label="행정사 주민등록번호" value={rrnForm.value}
                onChange={(v) => setRrnForm((p) => ({ ...p, value: v }))} placeholder="000000-0000000" />
              <Field label="행정사 주민등록번호 확인" value={rrnForm.confirm}
                onChange={(v) => setRrnForm((p) => ({ ...p, confirm: v }))} placeholder="000000-0000000" />
              <div style={{ gridColumn: "1 / -1", display: "flex", gap: 8, justifyContent: "flex-end" }}>
                <button type="button" className="btn-secondary" style={{ fontSize: 12, padding: "5px 10px" }}
                  onClick={() => { setRrnForm({ value: "", confirm: "" }); setRrnEditing(false); }}>취소</button>
                <SubmitButton isSubmitting={rrnSaving} onClick={handleRrnSave} loadingText="저장 중..."
                  className="text-xs" style={{ padding: "6px 12px", fontSize: 12 }}>
                  <><Save size={12} /> 주민번호 저장</>
                </SubmitButton>
              </div>
            </div>
          )}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 10 }} data-tour-id="profile-save">
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

      <Section title="보안 / 로그인 이력">
        <MySecuritySection />
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
