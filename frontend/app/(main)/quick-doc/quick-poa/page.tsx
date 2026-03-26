"use client";
import { useState } from "react";
import { quickPoaApi, type QuickPoaRequest } from "@/lib/api";
import { useRouter } from "next/navigation";
import { ChevronLeft, Download, Loader2 } from "lucide-react";

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "7px 10px",
  borderRadius: 6,
  border: "1px solid #E2E8F0",
  fontSize: 13,
  background: "#fff",
  color: "#2D3748",
  outline: "none",
};

const labelStyle: React.CSSProperties = {
  fontSize: 11,
  color: "#718096",
  fontWeight: 600,
  marginBottom: 3,
  display: "block",
};

const checkboxRowStyle: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  fontSize: 13,
  color: "#2D3748",
  cursor: "pointer",
};

export default function QuickPoaPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [downloadName, setDownloadName] = useState("위임장");

  const [form, setForm] = useState<QuickPoaRequest>({
    kor_name: "",
    surname: "",
    given: "",
    stay_status: "",
    reg6: "",
    no7: "",
    addr: "",
    phone1: "010",
    phone2: "",
    phone3: "",
    passport: "",
    apply_applicant_seal: true,
    apply_agent_seal: true,
    dpi: 200,
    ck_extension: false,
    ck_registration: false,
    ck_card: false,
    ck_adrc: false,
    ck_change: false,
    ck_granting: false,
    ck_ant: false,
  });

  const set = (key: keyof QuickPoaRequest, value: unknown) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const handleGenerate = async () => {
    if (!form.kor_name.trim()) {
      setError("신청인 한글명은 필수입니다.");
      return;
    }
    setLoading(true);
    setError(null);
    if (downloadUrl) {
      URL.revokeObjectURL(downloadUrl);
      setDownloadUrl(null);
    }
    try {
      const res = await quickPoaApi.generate(form);
      const blob = res.data as Blob;
      const cd = res.headers["content-disposition"] || "";
      const match = cd.match(/filename="([^"]+)"/);
      const fname = match ? match[1] : "위임장.jpg";
      setDownloadName(fname);
      setDownloadUrl(URL.createObjectURL(blob));
    } catch (e: unknown) {
      const detail =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "생성 중 오류가 발생했습니다.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ maxWidth: 760, margin: "0 auto" }}>
      {/* 헤더 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 20 }}>
        <button
          onClick={() => router.back()}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "5px 10px", borderRadius: 7, border: "1px solid #E2E8F0",
            background: "#fff", fontSize: 12, cursor: "pointer", color: "#718096",
          }}
        >
          <ChevronLeft size={13} /> 돌아가기
        </button>
        <h1 style={{ fontSize: 18, fontWeight: 800, margin: 0 }}>
          ⚡ 위임장 빠른작성
        </h1>
        <span style={{ fontSize: 12, color: "#A0AEC0" }}>
          임시 입력 → 도장 포함 → JPG 다운로드
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* 왼쪽: 신청인 정보 */}
        <div
          style={{
            background: "#fff", borderRadius: 10, border: "1px solid #E2E8F0",
            padding: "16px 18px", display: "flex", flexDirection: "column", gap: 10,
          }}
        >
          <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 4 }}>
            신청인 입력
          </div>
          {[
            { key: "kor_name" as const, label: "한글명 (도장명) *", placeholder: "홍길동" },
            { key: "surname"  as const, label: "영문 성 (Surname)", placeholder: "HONG" },
            { key: "given"    as const, label: "영문 이름 (Given)", placeholder: "GILDONG" },
            { key: "stay_status" as const, label: "체류자격", placeholder: "F-6" },
            { key: "reg6"     as const, label: "등록증 앞 6자리", placeholder: "YYMMDD" },
            { key: "no7"      as const, label: "등록증 뒤 7자리", placeholder: "1234567" },
            { key: "addr"     as const, label: "한국 내 주소", placeholder: "서울시..." },
            { key: "passport" as const, label: "여권번호", placeholder: "AB1234567" },
          ].map(({ key, label, placeholder }) => (
            <div key={key}>
              <label style={labelStyle}>{label}</label>
              <input
                style={inputStyle}
                value={(form[key] as string) ?? ""}
                onChange={(e) => set(key, e.target.value)}
                placeholder={placeholder}
              />
            </div>
          ))}
          <div style={{ display: "flex", gap: 8 }}>
            {(["phone1", "phone2", "phone3"] as const).map((k, i) => (
              <div key={k} style={{ flex: 1 }}>
                <label style={labelStyle}>{["연", "락", "처"][i]}</label>
                <input
                  style={inputStyle}
                  value={(form[k] as string) ?? ""}
                  onChange={(e) => set(k, e.target.value)}
                  placeholder={["010", "", ""][i]}
                />
              </div>
            ))}
          </div>
        </div>

        {/* 오른쪽: 옵션 + 위임업무 */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          {/* 옵션 */}
          <div
            style={{
              background: "#fff", borderRadius: 10, border: "1px solid #E2E8F0",
              padding: "14px 18px", display: "flex", flexDirection: "column", gap: 10,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748" }}>옵션</div>
            <label style={checkboxRowStyle}>
              <input
                type="checkbox"
                checked={form.apply_applicant_seal}
                onChange={(e) => set("apply_applicant_seal", e.target.checked)}
              />
              신청인 도장(yin)
            </label>
            <label style={checkboxRowStyle}>
              <input
                type="checkbox"
                checked={form.apply_agent_seal}
                onChange={(e) => set("apply_agent_seal", e.target.checked)}
              />
              행정사 도장(ayin)
            </label>
            <div>
              <label style={labelStyle}>JPG 해상도 (DPI)</label>
              <select
                style={{ ...inputStyle, width: "auto" }}
                value={form.dpi}
                onChange={(e) => set("dpi", Number(e.target.value))}
              >
                {[150, 200, 250, 300].map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </div>
          </div>

          {/* 위임업무 체크 */}
          <div
            style={{
              background: "#fff", borderRadius: 10, border: "1px solid #E2E8F0",
              padding: "14px 18px", display: "flex", flexDirection: "column", gap: 8,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 2 }}>
              위임업무 (해당 항목 선택)
            </div>
            {[
              { key: "ck_extension"   as const, label: "체류기간연장" },
              { key: "ck_registration"as const, label: "외국인등록(등록증발급)" },
              { key: "ck_card"        as const, label: "등록증재발급" },
              { key: "ck_adrc"        as const, label: "체류지변경" },
              { key: "ck_change"      as const, label: "체류자격 변경허가" },
              { key: "ck_granting"    as const, label: "자격부여" },
              { key: "ck_ant"         as const, label: "등록사항변경" },
            ].map(({ key, label }) => (
              <label key={key} style={checkboxRowStyle}>
                <input
                  type="checkbox"
                  checked={form[key] as boolean}
                  onChange={(e) => set(key, e.target.checked)}
                />
                {label}
              </label>
            ))}
          </div>
        </div>
      </div>

      {/* 오류 메시지 */}
      {error && (
        <div
          style={{
            marginTop: 14, padding: "10px 14px", borderRadius: 8,
            background: "#FFF5F5", border: "1px solid #FED7D7", color: "#C53030", fontSize: 13,
          }}
        >
          {error}
        </div>
      )}

      {/* 생성 버튼 */}
      <button
        onClick={handleGenerate}
        disabled={loading}
        style={{
          marginTop: 18, width: "100%", padding: "11px 0",
          borderRadius: 9, border: "none", fontSize: 14, fontWeight: 700,
          background: loading ? "#CBD5E0" : "#F5A623",
          color: "#fff", cursor: loading ? "not-allowed" : "pointer",
          display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
        }}
      >
        {loading ? <><Loader2 size={15} style={{ animation: "spin 1s linear infinite" }} /> 생성 중...</> : "🖨 위임장 생성"}
      </button>

      {/* 다운로드 버튼 */}
      {downloadUrl && (
        <a
          href={downloadUrl}
          download={downloadName}
          style={{
            marginTop: 10, display: "flex", alignItems: "center", justifyContent: "center",
            gap: 8, padding: "10px 0", borderRadius: 9, border: "2px solid #38A169",
            fontSize: 14, fontWeight: 700, color: "#276749", background: "#F0FFF4",
            textDecoration: "none", cursor: "pointer",
          }}
        >
          <Download size={15} /> {downloadName} 다운로드
        </a>
      )}
    </div>
  );
}
