"use client";
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

interface Props {
  type: "agent" | "customer";
  customerId?: string;
  customerSheetKey?: string;
  onSave: (base64: string) => void;
  onClose: () => void;
}

type ModalStatus = "requesting" | "waiting" | "done" | "expired" | "error";

export default function SignatureModal({
  type, customerId, customerSheetKey, onSave, onClose,
}: Props) {
  const [status, setStatus]       = useState<ModalStatus>("requesting");
  const [token, setToken]         = useState<string | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [url, setUrl]             = useState<string>("");
  const [qrSrc, setQrSrc]         = useState<string>("");
  const [signData, setSignData]   = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const pollRef   = useRef<ReturnType<typeof setInterval> | null>(null);
  const doneTokenRef = useRef<string | null>(null);

  const stopPoll = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  const requestToken = async () => {
    setStatus("requesting");
    setSignData(null);
    setSaveError(null);
    setToken(null);
    setRequestId(null);
    setQrSrc("");
    try {
      const res = await api.post<{ token: string; url: string; request_id?: string }>("/api/signature/request", {
        type,
        customer_id: customerId ?? null,
        customer_sheet_key: customerSheetKey ?? null,
      });
      const { token: tok, url: signUrl, request_id: rid } = res.data;
      setToken(tok);
      setUrl(signUrl);
      setRequestId(rid ?? null);
      const QRCode = await import("qrcode");
      const qr = await QRCode.toDataURL(signUrl, { width: 220, margin: 1 });
      setQrSrc(qr);
      setStatus("waiting");
    } catch {
      setStatus("error");
    }
  };

  // 마운트 시 토큰 요청 (한 번만)
  useEffect(() => {
    requestToken();
    return () => stopPoll();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // waiting 상태면 2초마다 폴링
  useEffect(() => {
    if (status !== "waiting" || !token) { stopPoll(); return; }
    pollRef.current = setInterval(async () => {
      try {
        const pollRes = await api.get<{ status: string; data?: string; request_id?: string }>(`/api/signature/poll/${token}`);
        const json = pollRes.data;
        if (json.status === "expired") { stopPoll(); setStatus("expired"); return; }
        if (json.status === "saved") {
          // Guard: if server returned a request_id and it doesn't match ours, ignore — stale response.
          if (requestId && json.request_id && json.request_id !== requestId) return;
          stopPoll();
          doneTokenRef.current = token;
          try {
            const saveRes = await api.post<{ status: string; data: string | null }>(`/api/signature/save/${token}`);
            const saved = saveRes.data.data ?? "";
            setSignData(saved || null);
            setStatus("done");
            onSave(saved);
          } catch {
            setStatus("done");
            onSave("");
          }
          setTimeout(() => onClose(), 2000);
          return;
        }
        if (json.status === "done") {
          if (requestId && json.request_id && json.request_id !== requestId) return;
          stopPoll();
          doneTokenRef.current = token;
          try {
            const saveRes = await api.post<{ status: string; data: string }>(`/api/signature/save/${token}`);
            const saved = saveRes.data.data;
            setSignData(saved);
            setStatus("done");
            onSave(saved);
            setTimeout(() => onClose(), 2000);
          } catch {
            setSaveError("서명 저장에 실패했습니다. 저장 재시도를 누르거나 사무소에 문의해주세요.");
            setStatus("error");
          }
          return;
        }
      } catch { /* 폴링 통신 오류는 무시 (일시적 네트워크 끊김) */ }
    }, 2000);
    return () => stopPoll();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, token, requestId]);

  // 저장 재시도 (agent 타입 — Sheets 저장 실패 시)
  const retrySave = async () => {
    const tok = doneTokenRef.current;
    if (!tok) { handleRegenerate(); return; }
    setSaveError(null);
    setStatus("requesting");
    try {
      const saveRes = await api.post<{ status: string; data: string }>(`/api/signature/save/${tok}`);
      const saved = saveRes.data.data;
      setSignData(saved);
      setStatus("done");
      onSave(saved);
      setTimeout(() => onClose(), 2000);
    } catch {
      setSaveError("저장 재시도 실패. 새 링크를 생성하거나 사무소에 문의해주세요.");
      setStatus("error");
    }
  };

  // 새 링크 재생성 — 확인 필요
  const handleRegenerate = () => {
    const ok = window.confirm(
      "기존에 복사한 링크는 더 이상 사용하지 않는 것으로 처리됩니다.\n새 링크를 생성할까요?"
    );
    if (ok) {
      stopPoll();
      requestToken();
      toast.info("새 서명 링크가 생성되었습니다.");
    }
  };

  const handleCopy = () => {
    navigator.clipboard.writeText(url).then(() => {
      toast.success("서명 링크가 복사되었습니다.");
    });
  };

  return (
    <>
      <div
        style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 200 }}
        onClick={onClose}
      />
      <div style={{
        position: "fixed", top: "50%", left: "50%",
        transform: "translate(-50%, -50%)",
        zIndex: 201, width: "min(360px, 94vw)",
        background: "#fff", borderRadius: 16,
        boxShadow: "0 8px 40px rgba(0,0,0,0.18)",
        padding: "24px 22px",
      }}>
        {/* 헤더 */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: "#1A202C" }}>서명 등록</span>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "#718096" }}>
            <X size={18} />
          </button>
        </div>

        {/* 완료 */}
        {status === "done" && (
          <div style={{ textAlign: "center", padding: "16px 0" }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>✅</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "#276749", marginBottom: 12 }}>서명 등록 완료</div>
            {signData && (
              <img src={signData} alt="서명" style={{ maxWidth: "100%", border: "1px solid #E2E8F0", borderRadius: 8 }} />
            )}
          </div>
        )}

        {/* 만료 */}
        {status === "expired" && (
          <div style={{ textAlign: "center", padding: "16px 0" }}>
            <div style={{ fontSize: 30, marginBottom: 8 }}>⏰</div>
            <div style={{ fontSize: 14, color: "#C53030", marginBottom: 4 }}>링크가 만료되었습니다.</div>
            <div style={{ fontSize: 12, color: "#718096", marginBottom: 16 }}>
              복사한 링크가 있다면 새 링크를 생성하세요.
            </div>
            <button onClick={handleRegenerate} style={{
              padding: "10px 24px", borderRadius: 8, background: "#F5A623",
              color: "#fff", border: "none", fontWeight: 700, cursor: "pointer", fontSize: 14,
            }}>새 링크 생성</button>
          </div>
        )}

        {/* 에러 */}
        {status === "error" && (
          <div style={{ textAlign: "center", padding: "16px 0" }}>
            <div style={{ fontSize: 13, color: "#C53030", marginBottom: 16, lineHeight: 1.6 }}>
              {saveError || "요청에 실패했습니다."}
            </div>
            <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
              {doneTokenRef.current && (
                <button onClick={retrySave} style={{
                  padding: "10px 18px", borderRadius: 8, background: "#F5A623",
                  color: "#fff", border: "none", fontWeight: 700, cursor: "pointer", fontSize: 13,
                }}>저장 재시도</button>
              )}
              <button onClick={handleRegenerate} style={{
                padding: "10px 18px", borderRadius: 8, background: "#fff",
                color: "#4A5568", border: "1px solid #CBD5E0", fontWeight: 600, cursor: "pointer", fontSize: 13,
              }}>새 링크 생성</button>
            </div>
          </div>
        )}

        {/* 요청 중 */}
        {status === "requesting" && (
          <div style={{ textAlign: "center", padding: "24px 0", color: "#A0AEC0", fontSize: 13 }}>QR 생성 중...</div>
        )}

        {/* 대기 중 */}
        {status === "waiting" && (
          <>
            <div style={{ fontSize: 13, color: "#4A5568", marginBottom: 14, textAlign: "center", lineHeight: 1.6 }}>
              휴대폰으로 QR코드를 스캔하거나<br />링크를 직접 여세요
            </div>

            {qrSrc ? (
              <div style={{ textAlign: "center", marginBottom: 14 }}>
                <img src={qrSrc} alt="QR" style={{ width: 220, height: 220, borderRadius: 8 }} />
              </div>
            ) : (
              <div style={{ height: 220, display: "flex", alignItems: "center", justifyContent: "center", color: "#A0AEC0" }}>
                생성 중...
              </div>
            )}

            {/* URL + 복사 */}
            <div style={{
              display: "flex", alignItems: "center", gap: 6,
              background: "#F7FAFC", borderRadius: 8, padding: "8px 10px",
              marginBottom: 8,
            }}>
              <span style={{ flex: 1, fontSize: 11, color: "#4A5568", wordBreak: "break-all" }}>{url}</span>
              <button onClick={handleCopy} style={{
                flexShrink: 0, fontSize: 11, padding: "4px 10px",
                border: "1px solid #E2E8F0", borderRadius: 6,
                background: "#fff", color: "#4A5568",
                cursor: "pointer", fontWeight: 600,
              }}>
                복사
              </button>
            </div>

            {/* 고정 안내 */}
            <div style={{ fontSize: 11, color: "#718096", textAlign: "center", marginBottom: 10 }}>
              🔒 이 링크는 서명이 저장될 때까지 고정됩니다.
            </div>

            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ fontSize: 12, color: "#A0AEC0" }}>
                ⏳ 서명 대기 중...
              </div>
              <button
                onClick={handleRegenerate}
                style={{
                  fontSize: 11, color: "#A0AEC0", background: "none", border: "none",
                  cursor: "pointer", padding: "2px 6px", textDecoration: "underline",
                }}
              >
                새 링크 생성
              </button>
            </div>
          </>
        )}
      </div>
    </>
  );
}
