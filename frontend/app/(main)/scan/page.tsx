"use client";
import { useState, useRef } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { ScanLine, Upload } from "lucide-react";

interface PassportOcr {
  성?: string;
  명?: string;
  국적?: string;
  국가?: string;
  성별?: string;
  여권?: string;
  발급?: string;
  만기?: string;
  생년월일?: string;
  error?: string;
}

interface ArcOcr {
  한글?: string;
  등록증?: string;
  번호?: string;
  발급일?: string;
  만기일?: string;
  주소?: string;
  error?: string;
}

function birthToRegFront(birth: string): string {
  const d = birth.replace(/[-./]/g, "");
  if (d.length === 8) return d.slice(2, 8);
  return "";
}

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 11,
  fontWeight: 500,
  color: "#718096",
  marginBottom: 3,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "6px 8px",
  fontSize: 13,
  border: "1px solid #CBD5E0",
  borderRadius: 6,
  background: "#fff",
  outline: "none",
  boxSizing: "border-box",
};

export default function ScanPage() {
  const qc = useQueryClient();
  const passportInputRef = useRef<HTMLInputElement>(null);
  const arcInputRef = useRef<HTMLInputElement>(null);

  // 파일 & 미리보기
  const [passportFile, setPassportFile] = useState<File | null>(null);
  const [passportPreview, setPassportPreview] = useState<string | null>(null);
  const [arcFile, setArcFile] = useState<File | null>(null);
  const [arcPreview, setArcPreview] = useState<string | null>(null);

  // 로딩
  const [passportLoading, setPassportLoading] = useState(false);
  const [arcLoading, setArcLoading] = useState(false);

  // 여권 정보 필드
  const [성, set성] = useState("");
  const [명, set명] = useState("");
  const [국적, set국적] = useState("");
  const [성별, set성별] = useState("");
  const [여권, set여권] = useState("");
  const [여권발급, set여권발급] = useState("");
  const [여권만기, set여권만기] = useState("");

  // 등록증 정보 필드
  const [한글, set한글] = useState("");
  const [등록증, set등록증] = useState("");
  const [번호, set번호] = useState("");
  const [발급일, set발급일] = useState("");
  const [만기일, set만기일] = useState("");
  const [주소, set주소] = useState("");

  // 연락처
  const [연, set연] = useState("010");
  const [락, set락] = useState("");
  const [처, set처] = useState("");
  const [V, setV] = useState("");

  // 여권 OCR 자동 실행
  const runPassportOcr = async (file: File) => {
    setPassportLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await api.post<PassportOcr>("/api/scan/passport", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const d = (res.data as any).result ?? res.data;
      if (d.error) {
        toast.error(d.error);
      } else {
        if (d.성) set성(d.성);
        if (d.명) set명(d.명);
        if (d.국적 || d.국가) set국적(d.국적 || d.국가 || "");
        if (d.성별) set성별(d.성별);
        if (d.여권) set여권(d.여권);
        if (d.발급) set여권발급(d.발급);
        if (d.만기) set여권만기(d.만기);
        // 여권 생년월일 → 등록증 앞자리 자동 채우기 (비어 있을 때만)
        if (d.생년월일) {
          const reg = birthToRegFront(d.생년월일);
          if (reg) set등록증((prev) => prev || reg);
        }
        toast.success("여권 OCR 완료");
      }
    } catch (err: unknown) {
      toast.error(
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          "여권 OCR 오류"
      );
    } finally {
      setPassportLoading(false);
    }
  };

  // 등록증 OCR 자동 실행
  const runArcOcr = async (file: File) => {
    setArcLoading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await api.post<ArcOcr>("/api/scan/arc", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const d = (res.data as any).result ?? res.data;
      if (d.error) {
        toast.error(d.error);
      } else {
        // ── [INSTRUMENT] OCR result vs current state ──────────────────────────
        console.log("[SCAN][FE][OCR-ARC] OCR result 만기일 from server:", JSON.stringify(d.만기일));
        // NOTE: set만기일 below runs AFTER this OCR call resolves.
        // If the user edited 만기일 while OCR was loading, this WILL overwrite it.
        // ─────────────────────────────────────────────────────────────────────
        if (d.한글) set한글(d.한글);
        if (d.등록증) set등록증(d.등록증);
        if (d.번호) set번호(d.번호);
        if (d.발급일) set발급일(d.발급일);
        if (d.만기일) {
          console.log("[SCAN][FE][OCR-ARC] set만기일 called with:", d.만기일,
            "— this OVERWRITES any user edit made during OCR loading");
          set만기일(d.만기일);
        }
        if (d.주소) set주소(d.주소);
        toast.success("등록증 OCR 완료");
      }
    } catch (err: unknown) {
      toast.error(
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          "등록증 OCR 오류"
      );
    } finally {
      setArcLoading(false);
    }
  };

  const handlePassportFile = (f: File) => {
    setPassportFile(f);
    setPassportPreview(URL.createObjectURL(f));
    runPassportOcr(f);
  };

  const handleArcFile = (f: File) => {
    setArcFile(f);
    setArcPreview(URL.createObjectURL(f));
    runArcOcr(f);
  };

  // 스캔 폼 전체 초기화 (다음 고객 스캔을 위해)
  const resetAll = () => {
    setPassportFile(null);
    setPassportPreview(null);
    setArcFile(null);
    setArcPreview(null);
    set성(""); set명(""); set국적(""); set성별(""); set여권(""); set여권발급(""); set여권만기("");
    set한글(""); set등록증(""); set번호(""); set발급일(""); set만기일(""); set주소("");
    set연("010"); set락(""); set처(""); setV("");
    if (passportInputRef.current) passportInputRef.current.value = "";
    if (arcInputRef.current) arcInputRef.current.value = "";
  };

  // 저장
  const registerMut = useMutation({
    mutationFn: (data: Record<string, string>) =>
      api.post("/api/scan/register", data),
    onSuccess: (res) => {
      const { status, message } = res.data;
      toast.success(status === "updated" ? `✅ ${message}` : `🆕 ${message}`);
      qc.invalidateQueries({ queryKey: ["customers"] });
      resetAll();
    },
    onError: () => toast.error("고객 등록/업데이트 실패"),
  });

  const handleSubmit = () => {
    const data: Record<string, string> = {
      성: 성.trim(),
      명: 명.trim(),
      국적: 국적.trim(),
      성별: 성별.trim(),
      여권: 여권.trim(),
      발급: 여권발급.trim(),
      만기: 여권만기.trim(),
      한글: 한글.trim(),
      등록증: 등록증.trim(),
      번호: 번호.trim(),
      발급일: 발급일.trim(),
      만기일: 만기일.trim(),
      주소: 주소.trim(),
      연: 연.trim(),
      락: 락.trim(),
      처: 처.trim(),
      V: V.trim(),
    };
    // ── [INSTRUMENT] log state + payload at submit time ───────────────────────
    console.log("[SCAN][FE][SUBMIT] 만기일 React state at submit:", JSON.stringify(만기일));
    console.log("[SCAN][FE][SUBMIT] 여권만기 React state at submit:", JSON.stringify(여권만기));
    console.log("[SCAN][FE][SUBMIT] full payload:", JSON.stringify(data, null, 2));
    // ─────────────────────────────────────────────────────────────────────────
    registerMut.mutate(data);
  };

  const dropZoneStyle = (hasFile: boolean): React.CSSProperties => ({
    border: `2px dashed ${hasFile ? "var(--hw-gold)" : "#CBD5E0"}`,
    borderRadius: 8,
    padding: "10px 14px",
    cursor: "pointer",
    background: "#fff",
    minHeight: 52,
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-start",
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* 헤더 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <ScanLine size={18} style={{ color: "var(--hw-gold)" }} />
        <h1 className="hw-page-title">스캔으로 고객 추가/수정</h1>
      </div>
      <p style={{ fontSize: 13, color: "#718096", margin: 0 }}>
        여권 1장만 또는 여권+등록증 2장을 업로드하세요.
      </p>

      {/* 파일 업로드 2열 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        {/* 여권 업로드 */}
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: "#4A5568" }}>
            여권 이미지 (필수)
          </div>
          <div
            style={dropZoneStyle(!!passportFile)}
            onClick={() => passportInputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const f = e.dataTransfer.files[0];
              if (f) handlePassportFile(f);
            }}
          >
            <input
              ref={passportInputRef}
              type="file"
              accept="image/*,.pdf"
              style={{ display: "none" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handlePassportFile(f);
              }}
            />
            {passportFile ? (
              <span style={{ fontSize: 12, color: "var(--hw-gold)", fontWeight: 500 }}>
                {passportLoading ? "⏳ OCR 인식 중..." : `✅ ${passportFile.name}`}
              </span>
            ) : (
              <span style={{ fontSize: 12, color: "#718096", display: "flex", alignItems: "center", gap: 4 }}>
                <Upload size={13} style={{ flexShrink: 0 }} />
                여권 이미지를 업로드 하세요.(필수)
              </span>
            )}
          </div>
        </div>

        {/* 등록증 업로드 */}
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: "#4A5568" }}>
            등록증/스티커 이미지 (선택)
          </div>
          <div
            style={dropZoneStyle(!!arcFile)}
            onClick={() => arcInputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              const f = e.dataTransfer.files[0];
              if (f) handleArcFile(f);
            }}
          >
            <input
              ref={arcInputRef}
              type="file"
              accept="image/*,.pdf"
              style={{ display: "none" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleArcFile(f);
              }}
            />
            {arcFile ? (
              <span style={{ fontSize: 12, color: "var(--hw-gold)", fontWeight: 500 }}>
                {arcLoading ? "⏳ OCR 인식 중..." : `✅ ${arcFile.name}`}
              </span>
            ) : (
              <span style={{ fontSize: 12, color: "#718096", display: "flex", alignItems: "center", gap: 4 }}>
                <Upload size={13} style={{ flexShrink: 0 }} />
                등록증 이미지를 업로드 하세요.(선택)
              </span>
            )}
          </div>
        </div>
      </div>

      <div style={{ fontWeight: 600, fontSize: 14, color: "#2D3748" }}>🔎 스캔 결과 확인 및 수정</div>

      {/* Row 1: 여권 이미지 (7) + 여권 정보 (3) */}
      <div style={{ display: "grid", gridTemplateColumns: "7fr 3fr", gap: 16, alignItems: "center" }}>
        <div className="hw-card" style={{ padding: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#4A5568" }}>여권 이미지</div>
          {passportPreview ? (
            passportFile?.type === "application/pdf" ? (
              <iframe
                src={passportPreview}
                style={{ width: "100%", minHeight: 320, border: "none", borderRadius: 8 }}
                title="여권 PDF 미리보기"
              />
            ) : (
              <img
                src={passportPreview}
                alt="여권"
                style={{ width: "100%", borderRadius: 8, objectFit: "contain" }}
              />
            )
          ) : (
            <div style={{
              minHeight: 220, padding: "0 12px",
              display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
              background: "#F7FAFC", borderRadius: 8,
            }}>
              <span style={{ fontSize: 13, color: "#A0AEC0", flexShrink: 0 }}>여권 이미지 예시(업로드 필수)</span>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/passport-sample.jpg" alt="여권 예시" style={{ height: 160, width: "auto", objectFit: "contain", borderRadius: 6, opacity: 0.55, flexShrink: 1, maxWidth: "60%" }} />
            </div>
          )}
        </div>

        <div className="hw-card" style={{ padding: 12, display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#4A5568" }}>여권 정보</div>

          <div>
            <label style={labelStyle}>성(영문)</label>
            <input className="hw-input" style={inputStyle} value={성} onChange={(e) => set성(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>명(영문)</label>
            <input className="hw-input" style={inputStyle} value={명} onChange={(e) => set명(e.target.value)} />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <div>
              <label style={labelStyle}>국적(3자리)</label>
              <input className="hw-input" style={inputStyle} value={국적} onChange={(e) => set국적(e.target.value)} />
            </div>
            <div>
              <label style={labelStyle}>성별</label>
              <select
                style={{ ...inputStyle }}
                value={성별}
                onChange={(e) => set성별(e.target.value)}
              >
                <option value="">-</option>
                <option value="남">남</option>
                <option value="여">여</option>
              </select>
            </div>
          </div>

          <div>
            <label style={labelStyle}>여권번호</label>
            <input className="hw-input" style={inputStyle} value={여권} onChange={(e) => set여권(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>여권 발급일 (YYYY-MM-DD)</label>
            <input className="hw-input" style={inputStyle} value={여권발급} onChange={(e) => set여권발급(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>여권 만기일 (YYYY-MM-DD)</label>
            <input className="hw-input" style={inputStyle} value={여권만기} onChange={(e) => set여권만기(e.target.value)} />
          </div>
        </div>
      </div>

      {/* Row 2: 등록증 이미지 (7) + 등록증 정보 (3) */}
      <div style={{ display: "grid", gridTemplateColumns: "7fr 3fr", gap: 16, alignItems: "center" }}>
        <div className="hw-card" style={{ padding: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#4A5568" }}>등록증 이미지</div>
          {arcPreview ? (
            arcFile?.type === "application/pdf" ? (
              <iframe
                src={arcPreview}
                style={{ width: "100%", minHeight: 320, border: "none", borderRadius: 8 }}
                title="등록증 PDF 미리보기"
              />
            ) : (
              <img
                src={arcPreview}
                alt="등록증"
                style={{ width: "100%", borderRadius: 8, objectFit: "contain" }}
              />
            )
          ) : (
            <div style={{
              minHeight: 220, padding: "0 12px",
              display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
              background: "#F7FAFC", borderRadius: 8,
            }}>
              <span style={{ fontSize: 13, color: "#A0AEC0", flexShrink: 0 }}>등록증 이미지 예시(업로드 선택)</span>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/arc-sample.jpg" alt="등록증 예시" style={{ height: 160, width: "auto", objectFit: "contain", borderRadius: 6, opacity: 0.55, flexShrink: 1, maxWidth: "60%" }} />
            </div>
          )}
        </div>

        <div className="hw-card" style={{ padding: 12, display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#4A5568" }}>등록증 / 연락처 정보</div>

          <div>
            <label style={labelStyle}>한글 이름</label>
            <input className="hw-input" style={inputStyle} value={한글} onChange={(e) => set한글(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>등록증 앞 (YYMMDD)</label>
            <input className="hw-input" style={inputStyle} value={등록증} onChange={(e) => set등록증(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>등록증 뒤 7자리</label>
            <input className="hw-input" style={inputStyle} value={번호} onChange={(e) => set번호(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>등록증 발급일 (YYYY-MM-DD)</label>
            <input className="hw-input" style={inputStyle} value={발급일} onChange={(e) => set발급일(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>등록증 만기일 (YYYY-MM-DD)</label>
            <input className="hw-input" style={inputStyle} value={만기일} onChange={(e) => set만기일(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>주소</label>
            <input className="hw-input" style={inputStyle} value={주소} onChange={(e) => set주소(e.target.value)} />
          </div>

          {/* 연락처 4열 */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 0.7fr", gap: 6 }}>
            <div>
              <label style={labelStyle}>연(앞)</label>
              <input className="hw-input" style={inputStyle} value={연} onChange={(e) => set연(e.target.value)} />
            </div>
            <div>
              <label style={labelStyle}>락(중간)</label>
              <input className="hw-input" style={inputStyle} value={락} onChange={(e) => set락(e.target.value)} />
            </div>
            <div>
              <label style={labelStyle}>처(끝)</label>
              <input className="hw-input" style={inputStyle} value={처} onChange={(e) => set처(e.target.value)} />
            </div>
            <div>
              <label style={labelStyle}>V</label>
              <input className="hw-input" style={inputStyle} value={V} onChange={(e) => setV(e.target.value)} />
            </div>
          </div>
        </div>
      </div>

      {/* 저장 버튼 */}
      <button
        onClick={handleSubmit}
        disabled={registerMut.isPending}
        className="btn-primary"
        style={{
          width: "100%",
          padding: "12px",
          fontSize: 15,
          fontWeight: 600,
          opacity: registerMut.isPending ? 0.5 : 1,
        }}
      >
        {registerMut.isPending ? "저장 중..." : "💾 고객관리 반영"}
      </button>
    </div>
  );
}
