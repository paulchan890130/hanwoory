"use client";
import { useState, useEffect } from "react";
import { oneClickApi, type QuickPoaRequest, type OneClickOutput } from "@/lib/api";
import { Download, Loader2 } from "lucide-react";

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "7px 10px",
  borderRadius: 6,
  border: "1px solid #E2E8F0",
  fontSize: 13,
  background: "#fff",
  color: "#2D3748",
  outline: "none",
  boxSizing: "border-box",
};

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  color: "#718096",
  fontWeight: 600,
  marginBottom: 3,
  display: "block",
};

interface OutputTypeSpec {
  id: OneClickOutput;
  label: string;
  implemented: boolean;
}

const OUTPUT_TYPES: OutputTypeSpec[] = [
  { id: "위임장",             label: "위임장",             implemented: true  },
  { id: "건강보험(세대합가)", label: "건강보험 (세대합가)", implemented: false },
  { id: "건강보험(피부양자)", label: "건강보험 (피부양자)", implemented: false },
  { id: "하이코리아",         label: "하이코리아",          implemented: true  },
  { id: "소시넷(등록증)",     label: "소시넷(등록증)",      implemented: true  },
  { id: "소시넷(여권)",       label: "소시넷(여권)",        implemented: true  },
];

export interface QuickPoaPanelProps {
  initialCustomer?: {
    customer_id?: string;
    kor_name?: string;
    surname?: string;
    given?: string;
    stay_status?: string;
    reg6?: string;
    no7?: string;
    addr?: string;
    phone1?: string;
    phone2?: string;
    phone3?: string;
    passport?: string;
  };
  embedded?: boolean;
  onClose?: () => void;
}

function SealSignRow({
  label,
  hasSeal,
  hasSign,
  sealChecked,
  signChecked,
  onSealChange,
  onSignChange,
}: {
  label: string;
  hasSeal: boolean;
  hasSign: boolean | null;   // null = 확인 중
  sealChecked: boolean;
  signChecked: boolean;
  onSealChange: (v: boolean) => void;
  onSignChange: (v: boolean) => void;
}) {
  const row: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 10, fontSize: 12, color: "#4A5568",
  };
  const chip = (active: boolean, disabled: boolean): React.CSSProperties => ({
    display: "flex", alignItems: "center", gap: 4,
    padding: "3px 8px", borderRadius: 5, fontSize: 11, fontWeight: 600,
    border: `1px solid ${active ? "#D4A843" : disabled ? "#E2E8F0" : "#CBD5E0"}`,
    background: active ? "#FFF9E6" : "#F7FAFC",
    color: active ? "#7A5C10" : disabled ? "#CBD5E0" : "#718096",
    cursor: disabled ? "not-allowed" : "pointer",
    userSelect: "none" as const,
  });
  return (
    <div style={row}>
      <span style={{ width: 40, fontWeight: 600, flexShrink: 0 }}>{label}</span>
      <label style={chip(sealChecked, !hasSeal)}>
        <input
          type="checkbox"
          style={{ display: "none" }}
          disabled={!hasSeal}
          checked={sealChecked}
          onChange={(e) => onSealChange(e.target.checked)}
        />
        도장
      </label>
      <label style={chip(signChecked, hasSign !== true)} title={hasSign === null ? "확인 중..." : hasSign ? undefined : "서명 없음 — 먼저 서명 등록 필요"}>
        <input
          type="checkbox"
          style={{ display: "none" }}
          disabled={hasSign !== true}
          checked={signChecked}
          onChange={(e) => onSignChange(e.target.checked)}
        />
        {hasSign === null ? "서명 확인중" : hasSign ? "서명" : "서명 없음"}
      </label>
    </div>
  );
}

export default function QuickPoaPanel({ initialCustomer }: QuickPoaPanelProps) {
  const customerId = initialCustomer?.customer_id ?? null;

  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [downloadName, setDownloadName] = useState("위임장");

  // 서명 존재 여부 (null = 확인 중)
  const [hasAgentSign, setHasAgentSign]   = useState<boolean | null>(null);
  const [hasCustSign,  setHasCustSign]    = useState<boolean | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("access_token") || "";
    const hdrs = { Authorization: `Bearer ${token}` };
    // 행정사 서명: 오류 시 null 유지 (false 설정 금지 — 도장 강제 전환 방지)
    fetch("/api/signature/agent/exists", { headers: hdrs })
      .then(r => { if (!r.ok) return; return r.json(); })
      .then(j => { if (j) setHasAgentSign(j.exists ?? false); })
      .catch(() => { /* 네트워크 오류 — null 유지, false 설정 금지 */ });
    // 고객 서명: 오류 시 null 유지 (false 설정 금지 — 서명 있는 고객이 도장으로 전환되는 버그 방지)
    if (customerId) {
      fetch(`/api/signature/customer/${encodeURIComponent(customerId)}/exists`, { headers: hdrs })
        .then(r => { if (!r.ok) return; return r.json(); })
        .then(j => { if (j) setHasCustSign(j.exists ?? false); })
        .catch(() => { /* 네트워크 오류 — null 유지, false 설정 금지 */ });
    } else {
      setHasCustSign(false);  // customer_id 자체가 없으면 서명 불가 → false 정상
    }
  }, [customerId]);

  // 서명 존재 확인 후 기본값 자동 설정
  // null = 조회 중 또는 조회 실패 → 기존 선택 유지 (도장으로 강제 전환 금지)
  useEffect(() => {
    if (hasCustSign === null) return;  // 조회 실패/대기 → 현재 선택 유지
    setForm(prev => hasCustSign
      ? { ...prev, apply_applicant_sign: true,  apply_applicant_seal: false }
      : { ...prev, apply_applicant_sign: false, apply_applicant_seal: true  }
    );
  }, [hasCustSign]);

  useEffect(() => {
    if (hasAgentSign === null) return;  // 조회 실패/대기 → 현재 선택 유지
    setForm(prev => hasAgentSign
      ? { ...prev, apply_agent_sign: true,  apply_agent_seal: false }
      : { ...prev, apply_agent_sign: false, apply_agent_seal: true  }
    );
  }, [hasAgentSign]);

  const [selectedOutputs, setSelectedOutputs] = useState<Set<OneClickOutput>>(
    new Set<OneClickOutput>(["위임장"])
  );

  const toggleOutput = (id: OneClickOutput, implemented: boolean) => {
    if (!implemented) return;
    setSelectedOutputs((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const [form, setForm] = useState<QuickPoaRequest>({
    kor_name:    initialCustomer?.kor_name    ?? "",
    surname:     initialCustomer?.surname     ?? "",
    given:       initialCustomer?.given       ?? "",
    stay_status: initialCustomer?.stay_status ?? "",
    reg6:        initialCustomer?.reg6        ?? "",
    no7:         initialCustomer?.no7         ?? "",
    addr:        initialCustomer?.addr        ?? "",
    phone1:      initialCustomer?.phone1      || "010",
    phone2:      initialCustomer?.phone2      ?? "",
    phone3:      initialCustomer?.phone3      ?? "",
    passport:    initialCustomer?.passport    ?? "",
    customer_id:  customerId ?? undefined,
    site_id:      "",
    old_passport: "",
    apply_applicant_seal: true,
    apply_agent_seal:     true,
    apply_applicant_sign: false,
    apply_agent_sign:     false,
    dpi:                  200,
    ck_extension:    false,
    ck_registration: false,
    ck_card:         false,
    ck_adrc:         false,
    ck_change:       false,
    ck_granting:     false,
    ck_ant:          false,
  });

  const set = (key: keyof QuickPoaRequest, value: unknown) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const handleGenerate = async () => {
    if (!form.kor_name.trim()) { setError("신청인 한글명은 필수입니다."); return; }
    if (selectedOutputs.size === 0) { setError("출력할 항목을 하나 이상 선택하세요."); return; }
    setLoading(true);
    setError(null);
    if (downloadUrl) { URL.revokeObjectURL(downloadUrl); setDownloadUrl(null); }
    try {
      const res = await oneClickApi.generate({ ...form, selected_outputs: Array.from(selectedOutputs) });
      const blob = res.data as Blob;
      const cd = res.headers["content-disposition"] || "";
      const rfc5987 = cd.match(/filename\*=UTF-8''([^\s;]+)/i);
      const legacy  = cd.match(/filename="([^"]+)"/);
      const fname   = rfc5987 ? decodeURIComponent(rfc5987[1]) : legacy ? legacy[1] : "위임장.jpg";
      setDownloadName(fname);
      setDownloadUrl(URL.createObjectURL(blob));
    } catch (e: unknown) {
      let detail: string | undefined;
      const errData = (e as { response?: { data?: unknown } })?.response?.data;
      if (errData instanceof Blob) {
        try { const text = await errData.text(); detail = JSON.parse(text)?.detail; } catch { /* ignore */ }
      } else {
        detail = (errData as { detail?: string } | undefined)?.detail;
      }
      setError(detail || "생성 중 오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      {/* 출력 항목 선택 */}
      <div style={{
        background: "#fff", borderRadius: 10, border: "1px solid #E2E8F0",
        padding: "10px 14px", marginBottom: 12,
        display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12,
      }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: "#2D3748", whiteSpace: "nowrap" }}>출력 항목</span>
        {OUTPUT_TYPES.map(({ id, label, implemented }) => (
          <label key={id} style={{
            display: "flex", alignItems: "center", gap: 5, fontSize: 13,
            color: implemented ? "#2D3748" : "#A0AEC0",
            cursor: implemented ? "pointer" : "not-allowed",
            userSelect: "none",
          }} title={implemented ? undefined : "준비 중"}>
            <input type="checkbox" disabled={!implemented} checked={selectedOutputs.has(id)}
              onChange={() => toggleOutput(id, implemented)} />
            {label}
            {!implemented && (
              <span style={{
                fontSize: 10, color: "#A0AEC0", background: "#F7FAFC",
                border: "1px solid #E2E8F0", borderRadius: 4, padding: "1px 5px", lineHeight: 1.4,
              }}>준비 중</span>
            )}
          </label>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        {/* 신청인 정보 */}
        <div style={{
          background: "#fff", borderRadius: 10, border: "1px solid #E2E8F0",
          padding: "14px 16px", display: "flex", flexDirection: "column", gap: 9, minWidth: 0,
        }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 2 }}>신청인 정보</div>
          {([
            { key: "kor_name"    as const, label: "한글명 (도장명) *", placeholder: "홍길동",    always: true  },
            { key: "surname"     as const, label: "영문 성 (Surname)", placeholder: "HONG",       always: true  },
            { key: "given"       as const, label: "영문 이름 (Given)", placeholder: "GILDONG",    always: true  },
            { key: "stay_status" as const, label: "체류자격",           placeholder: "F-6",        always: false },
            { key: "reg6"        as const, label: "등록증 앞 6자리",   placeholder: "YYMMDD",     always: true  },
            { key: "no7"         as const, label: "등록증 뒤 7자리",   placeholder: "1234567",    always: true  },
            { key: "addr"        as const, label: "한국 내 주소",       placeholder: "서울시...",  always: true  },
            { key: "passport"    as const, label: "여권번호",           placeholder: "AB1234567", always: false },
          ] as { key: keyof QuickPoaRequest; label: string; placeholder: string; always: boolean }[])
            .filter(({ always, key }) =>
              always ||
              selectedOutputs.has("위임장") ||
              ((key as string) === "passport" && selectedOutputs.has("소시넷(여권)"))
            )
            .map(({ key, label, placeholder }) => (
              <div key={key as string}>
                <label style={labelStyle}>{label}</label>
                <input style={inputStyle} value={(form[key] as string) ?? ""}
                  onChange={(e) => set(key, e.target.value)} placeholder={placeholder} />
              </div>
            ))}
          {selectedOutputs.has("위임장") && (
            <div style={{ display: "flex", gap: 6 }}>
              {(["phone1", "phone2", "phone3"] as const).map((k, i) => (
                <div key={k} style={{ flex: 1 }}>
                  <label style={labelStyle}>{["연", "락", "처"][i]}</label>
                  <input style={inputStyle} value={(form[k] as string) ?? ""}
                    onChange={(e) => set(k, e.target.value)} placeholder={["010", "", ""][i]} />
                </div>
              ))}
            </div>
          )}
          {/* ID — 하이코리아/소시넷 공통 */}
          <div>
            <label style={labelStyle}>ID (하이코리아 · 소시넷 로그인 ID)</label>
            <input style={inputStyle} value={form.site_id ?? ""}
              onChange={(e) => set("site_id", e.target.value)} placeholder="사이트 ID" />
          </div>
          {/* 구여권 — 소시넷(여권) 선택 시만 표시 */}
          {selectedOutputs.has("소시넷(여권)") && (
            <div>
              <label style={labelStyle}>구여권 번호</label>
              <input style={inputStyle} value={form.old_passport ?? ""}
                onChange={(e) => set("old_passport", e.target.value)} placeholder="이전 여권번호" />
            </div>
          )}
        </div>

        {/* 옵션 + 위임업무 */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
          {/* 도장 / 서명 옵션 */}
          <div style={{
            background: "#fff", borderRadius: 10, border: "1px solid #E2E8F0",
            padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10,
          }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 2 }}>도장 / 서명</div>
            <SealSignRow
              label="신청인"
              hasSeal={true}
              hasSign={hasCustSign}
              sealChecked={form.apply_applicant_seal ?? true}
              signChecked={form.apply_applicant_sign ?? false}
              onSealChange={(v) => setForm(prev => ({
                ...prev, apply_applicant_seal: v, apply_applicant_sign: v ? false : prev.apply_applicant_sign,
              }))}
              onSignChange={(v) => setForm(prev => ({
                ...prev, apply_applicant_sign: v, apply_applicant_seal: v ? false : prev.apply_applicant_seal,
              }))}
            />
            <SealSignRow
              label="행정사"
              hasSeal={true}
              hasSign={hasAgentSign}
              sealChecked={form.apply_agent_seal ?? true}
              signChecked={form.apply_agent_sign ?? false}
              onSealChange={(v) => setForm(prev => ({
                ...prev, apply_agent_seal: v, apply_agent_sign: v ? false : prev.apply_agent_sign,
              }))}
              onSignChange={(v) => setForm(prev => ({
                ...prev, apply_agent_sign: v, apply_agent_seal: v ? false : prev.apply_agent_seal,
              }))}
            />
            <div style={{ marginTop: 4 }}>
              <label style={labelStyle}>JPG 해상도 (DPI)</label>
              <select style={{ ...inputStyle, width: "auto" }} value={form.dpi}
                onChange={(e) => set("dpi", Number(e.target.value))}>
                {[150, 200, 250, 300].map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
            </div>
          </div>

          {/* 위임업무 */}
          {selectedOutputs.has("위임장") && (
            <div style={{
              background: "#fff", borderRadius: 10, border: "1px solid #E2E8F0",
              padding: "14px 16px", display: "flex", flexDirection: "column", gap: 8,
            }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 2 }}>
                위임업무 (해당 항목 선택)
              </div>
              {([
                { key: "ck_extension"    as const, label: "체류기간연장" },
                { key: "ck_registration" as const, label: "외국인등록(등록증발급)" },
                { key: "ck_card"         as const, label: "등록증재발급" },
                { key: "ck_adrc"         as const, label: "체류지변경" },
                { key: "ck_change"       as const, label: "체류자격 변경허가" },
                { key: "ck_granting"     as const, label: "자격부여" },
                { key: "ck_ant"          as const, label: "등록사항변경" },
              ] as { key: keyof QuickPoaRequest; label: string }[]).map(({ key, label }) => (
                <label key={key as string} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#4A5568", cursor: "pointer" }}>
                  <input type="checkbox" checked={form[key] as boolean}
                    onChange={(e) => set(key, e.target.checked)} />
                  {label}
                </label>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 오류 메시지 */}
      {error && (
        <div style={{
          marginTop: 12, padding: "10px 14px", borderRadius: 8,
          background: "#FFF5F5", border: "1px solid #FED7D7", color: "#C53030", fontSize: 13,
        }}>
          {error}
        </div>
      )}

      {/* 생성 버튼 */}
      <button onClick={handleGenerate} disabled={loading || selectedOutputs.size === 0}
        style={{
          marginTop: 16, width: "100%", padding: "11px 0",
          borderRadius: 9, border: "none", fontSize: 14, fontWeight: 700,
          background: (loading || selectedOutputs.size === 0) ? "#CBD5E0" : "#4A6FA5",
          color: "#fff", cursor: (loading || selectedOutputs.size === 0) ? "not-allowed" : "pointer",
          display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
        }}
      >
        {loading
          ? <><Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> 생성 중...</>
          : "⚡ 원클릭 생성"}
      </button>

      {/* 다운로드 버튼 */}
      {downloadUrl && (
        <a href={downloadUrl} download={downloadName} style={{
          marginTop: 10, display: "flex", alignItems: "center", justifyContent: "center",
          gap: 8, padding: "10px 0", borderRadius: 9, border: "2px solid #38A169",
          fontSize: 14, fontWeight: 700, color: "#276749", background: "#F0FFF4",
          textDecoration: "none", cursor: "pointer",
        }}>
          <Download size={15} /> {downloadName} 다운로드
        </a>
      )}
    </div>
  );
}
