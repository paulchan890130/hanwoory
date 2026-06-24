"use client";
import { useState, useRef } from "react";
import { toast } from "sonner";
import { Loader2, X, Download, Upload } from "lucide-react";
import { customersApi, type BulkValidateResult, type BulkCommitResult } from "@/lib/api";

const STATUS_STYLE: Record<string, { bg: string; color: string; label: string }> = {
  new: { bg: "#C6F6D5", color: "#276749", label: "신규" },
  duplicate: { bg: "#FEEBC8", color: "#9C4221", label: "중복 의심" },
  error: { bg: "#FED7D7", color: "#9B2C2C", label: "오류" },
};

export function BulkAddModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [validating, setValidating] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [result, setResult] = useState<BulkValidateResult | null>(null);
  const [includeDup, setIncludeDup] = useState(false);

  const downloadTemplate = async () => {
    try {
      const res = await customersApi.bulkTemplate();
      const url = window.URL.createObjectURL(res.data as Blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "고객_일괄등록_양식.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch {
      toast.error("양식 다운로드에 실패했습니다.");
    }
  };

  const onPick = (f: File | undefined) => {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".xlsx")) {
      toast.error("xlsx 파일만 업로드할 수 있습니다.");
      return;
    }
    setFile(f);
    setResult(null);
  };

  const runValidate = async () => {
    if (!file) { toast.error("파일을 선택하세요."); return; }
    setValidating(true);
    try {
      const res = await customersApi.bulkValidate(file);
      setResult(res.data);
      if (res.data.total === 0) toast.error("입력된 데이터 행이 없습니다.");
    } catch {
      toast.error("엑셀 검증에 실패했습니다. 양식을 확인해 주세요.");
    } finally {
      setValidating(false);
    }
  };

  const runCommit = async () => {
    if (!file || !result) return;
    const willRegister = result.counts.new + (includeDup ? result.counts.duplicate : 0);
    if (willRegister === 0) { toast.error("등록할 행이 없습니다."); return; }
    if (!confirm(`${willRegister}명을 등록합니다. 진행할까요?`)) return;
    setCommitting(true);
    try {
      const res = await customersApi.bulkCommit(file, includeDup);
      const r: BulkCommitResult = res.data;
      toast.success(`등록 ${r.registered}명 완료 (중복 제외 ${r.skipped_duplicate}, 오류 제외 ${r.skipped_error}${r.failed ? `, 실패 ${r.failed}` : ""})`);
      onDone();
      onClose();
    } catch {
      toast.error("등록 중 오류가 발생했습니다.");
    } finally {
      setCommitting(false);
    }
  };

  const c = result?.counts;
  const willRegister = c ? c.new + (includeDup ? c.duplicate : 0) : 0;

  return (
    <div
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", padding: 20 }}
      onClick={onClose}
    >
      <div
        style={{ background: "#fff", borderRadius: 12, width: "min(760px, 96vw)", maxHeight: "90vh", overflow: "auto", padding: 24 }}
        onClick={(e) => e.stopPropagation()}
      >
        <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: "#1A202C" }}>엑셀 일괄 고객등록</h2>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "#718096" }}><X size={20} /></button>
        </div>

        {/* 안내 */}
        <div style={{ background: "#F7FAFC", border: "1px solid #E2E8F0", borderRadius: 8, padding: "12px 14px", fontSize: 13, color: "#4A5568", lineHeight: 1.7, marginBottom: 16 }}>
          1) 기준 양식을 내려받아 2행 헤더 아래부터 입력하세요. 고객ID는 입력하지 않습니다(자동 생성).<br />
          2) 날짜는 <strong>yyyy-mm-dd</strong> 형식, <strong>고객명</strong>은 필수입니다.<br />
          3) 외국인등록번호 뒷자리는 암호화 저장되며 화면에는 마스킹됩니다.<br />
          4) 업로드 후 미리보기에서 신규/중복의심/오류를 확인한 뒤 등록하세요.
        </div>

        <div style={{ display: "flex", gap: 10, marginBottom: 16, flexWrap: "wrap" }}>
          <button onClick={downloadTemplate} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "9px 16px", borderRadius: 8, border: "1.5px solid #D4A843", background: "#fff", color: "#B7791F", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
            <Download size={15} /> 기준 양식 다운로드
          </button>
          <button onClick={() => fileRef.current?.click()} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "9px 16px", borderRadius: 8, border: "1px solid #E2E8F0", background: "#fff", color: "#4A5568", fontWeight: 600, fontSize: 13, cursor: "pointer" }}>
            <Upload size={15} /> {file ? "파일 변경" : "엑셀 파일 선택"}
          </button>
          <input ref={fileRef} type="file" accept=".xlsx" style={{ display: "none" }} onChange={(e) => { onPick(e.target.files?.[0]); e.target.value = ""; }} />
          {file && <span style={{ fontSize: 13, color: "#718096", alignSelf: "center" }}>{file.name}</span>}
        </div>

        {file && !result && (
          <button onClick={runValidate} disabled={validating} style={{ padding: "10px 20px", borderRadius: 8, background: validating ? "#ccc" : "#D4A843", color: "#fff", fontWeight: 700, fontSize: 14, border: "none", cursor: validating ? "not-allowed" : "pointer", display: "inline-flex", alignItems: "center", gap: 6 }}>
            {validating && <Loader2 size={14} style={{ animation: "spin 0.8s linear infinite" }} />}
            업로드 · 검증
          </button>
        )}

        {result && (
          <>
            <div style={{ display: "flex", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, color: "#4A5568" }}>전체 <strong>{result.total}</strong>행</span>
              <span style={{ fontSize: 13, color: "#276749" }}>신규 <strong>{c!.new}</strong></span>
              <span style={{ fontSize: 13, color: "#9C4221" }}>중복 의심 <strong>{c!.duplicate}</strong></span>
              <span style={{ fontSize: 13, color: "#9B2C2C" }}>오류 <strong>{c!.error}</strong></span>
            </div>

            <div style={{ maxHeight: 300, overflow: "auto", border: "1px solid #EDF2F7", borderRadius: 8, marginBottom: 14 }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr style={{ background: "#F7FAFC", position: "sticky", top: 0 }}>
                    {["행", "상태", "고객명", "국적", "체류자격", "여권", "메시지"].map((h) => (
                      <th key={h} style={{ padding: "7px 8px", textAlign: "left", fontSize: 11, fontWeight: 600, color: "#718096", whiteSpace: "nowrap" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.map((row) => {
                    const s = STATUS_STYLE[row.status];
                    return (
                      <tr key={row.row_no} style={{ borderBottom: "1px solid #F0F0F0" }}>
                        <td style={{ padding: "6px 8px", color: "#A0AEC0" }}>{row.row_no}</td>
                        <td style={{ padding: "6px 8px" }}>
                          <span style={{ background: s.bg, color: s.color, padding: "1px 8px", borderRadius: 10, fontSize: 11, fontWeight: 600, whiteSpace: "nowrap" }}>{s.label}</span>
                        </td>
                        <td style={{ padding: "6px 8px", color: "#1A202C" }}>{row.name || "-"}</td>
                        <td style={{ padding: "6px 8px", color: "#718096" }}>{row.nationality || "-"}</td>
                        <td style={{ padding: "6px 8px", color: "#718096" }}>{row.visa || "-"}</td>
                        <td style={{ padding: "6px 8px", color: "#718096" }}>{row.passport_masked || "-"}</td>
                        <td style={{ padding: "6px 8px", color: row.status === "error" ? "#9B2C2C" : "#A0AEC0" }}>
                          {row.status === "error" && row.messages.length > 0 && (
                            <div style={{ color: "#9B2C2C" }}>{row.messages.join(" / ")}</div>
                          )}
                          {row.dup_customer_id && (
                            <div style={{ color: "#9C4221" }}>기존 고객ID {row.dup_customer_id}</div>
                          )}
                          {row.transforms?.length > 0 && (
                            <div style={{ color: "#2B6CB0" }}>{row.transforms.join(" · ")}</div>
                          )}
                          {row.warnings?.length > 0 && (
                            <div style={{ color: "#B7791F" }}>⚠ {row.warnings.join(" / ")}</div>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {c!.duplicate > 0 && (
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#4A5568", marginBottom: 14, cursor: "pointer" }}>
                <input type="checkbox" checked={includeDup} onChange={(e) => setIncludeDup(e.target.checked)} style={{ width: 15, height: 15 }} />
                중복 의심 {c!.duplicate}건도 신규로 등록 (기본: 제외)
              </label>
            )}

            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button onClick={() => { setResult(null); }} style={{ padding: "10px 18px", borderRadius: 8, background: "#fff", color: "#4A5568", fontWeight: 600, fontSize: 14, border: "1px solid #E2E8F0", cursor: "pointer" }}>
                다시 선택
              </button>
              <button onClick={runCommit} disabled={committing || willRegister === 0} style={{ padding: "10px 22px", borderRadius: 8, background: committing || willRegister === 0 ? "#ccc" : "#38A169", color: "#fff", fontWeight: 700, fontSize: 14, border: "none", cursor: committing || willRegister === 0 ? "not-allowed" : "pointer", display: "inline-flex", alignItems: "center", gap: 6 }}>
                {committing && <Loader2 size={14} style={{ animation: "spin 0.8s linear infinite" }} />}
                {willRegister}명 등록
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
