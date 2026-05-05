"use client";
import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { api } from "@/lib/api";

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
  const [status, setStatus]   = useState<ModalStatus>("requesting");
  const [token, setToken]     = useState<string | null>(null);
  const [url, setUrl]         = useState<string>("");
  const [qrSrc, setQrSrc]     = useState<string>("");
  const [signData, setSignData] = useState<string | null>(null);
  const [copied, setCopied]   = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  const requestToken = async () => {
    setStatus("requesting");
    setSignData(null);
    setToken(null);
    setQrSrc("");
    try {
      const res = await api.post<{ token: string; url: string }>("/api/signature/request", {
        type,
        customer_id: customerId ?? null,
        customer_sheet_key: customerSheetKey ?? null,
      });
      const { token: tok, url: signUrl } = res.data;
      setToken(tok);
      setUrl(signUrl);

      // QR 생성
      const QRCode = await import("qrcode");
      const qr = await QRCode.toDataURL(signUrl, { width: 220, margin: 1 });
      setQrSrc(qr);
      setStatus("waiting");
    } catch {
      setStatus("error");
    }
  };

  // 마운트 시 토큰 요청
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
        const pollRes = await api.get<{ status: string; data?: string }>(`/api/signature/poll/${token}`);
        const json = pollRes.data;
        if (json.status === "expired") { stopPoll(); setStatus("expired"); return; }
        if (json.status === "done") {
          stopPoll();
          const saveRes = await api.post<{ status: string; data: string }>(`/api/signature/save/${token}`);
          const saved = saveRes.data.data;
          setSignData(saved);
          setStatus("done");
          onSave(saved);
          setTimeout(() => onClose(), 2000);
        }
      } catch { /* 폴링 일시 실패는 무시 */ }
    }, 2000);
    return () => stopPoll();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, token]);

  const handleCopy = () => {
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
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

        {/* 완료 상태 */}
        {status === "done" && (
          <div style={{ textAlign: "center", padding: "16px 0" }}>
            <div style={{ fontSize: 32, marginBottom: 8 }}>✅</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: "#276749", marginBottom: 12 }}>서명 등록 완료</div>
            {signData && (
              <img src={signData} alt="서명" style={{ maxWidth: "100%", border: "1px solid #E2E8F0", borderRadius: 8 }} />
            )}
          </div>
        )}

        {/* 만료 상태 */}
        {status === "expired" && (
          <div style={{ textAlign: "center", padding: "16px 0" }}>
            <div style={{ fontSize: 30, marginBottom: 8 }}>⏰</div>
            <div style={{ fontSize: 14, color: "#C53030", marginBottom: 16 }}>링크가 만료되었습니다.</div>
            <button onClick={requestToken} style={{
              padding: "10px 24px", borderRadius: 8, background: "#F5A623",
              color: "#fff", border: "none", fontWeight: 700, cursor: "pointer", fontSize: 14,
            }}>다시 시도</button>
          </div>
        )}

        {/* 에러 상태 */}
        {status === "error" && (
          <div style={{ textAlign: "center", padding: "16px 0" }}>
            <div style={{ fontSize: 14, color: "#C53030", marginBottom: 16 }}>요청에 실패했습니다.</div>
            <button onClick={requestToken} style={{
              padding: "10px 24px", borderRadius: 8, background: "#F5A623",
              color: "#fff", border: "none", fontWeight: 700, cursor: "pointer", fontSize: 14,
            }}>다시 시도</button>
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

            {/* QR 코드 */}
            {qrSrc ? (
              <div style={{ textAlign: "center", marginBottom: 14 }}>
                <img src={qrSrc} alt="QR" style={{ width: 220, height: 220, borderRadius: 8 }} />
              </div>
            ) : (
              <div style={{ height: 220, display: "flex", alignItems: "center", justifyContent: "center", color: "#A0AEC0" }}>
                생성 중...
              </div>
            )}

            {/* URL + 복사 버튼 */}
            <div style={{
              display: "flex", alignItems: "center", gap: 6,
              background: "#F7FAFC", borderRadius: 8, padding: "8px 10px",
              marginBottom: 16,
            }}>
              <span style={{ flex: 1, fontSize: 11, color: "#4A5568", wordBreak: "break-all" }}>{url}</span>
              <button onClick={handleCopy} style={{
                flexShrink: 0, fontSize: 11, padding: "4px 10px",
                border: "1px solid #E2E8F0", borderRadius: 6,
                background: copied ? "#C6F6D5" : "#fff",
                color: copied ? "#276749" : "#4A5568",
                cursor: "pointer", fontWeight: 600,
              }}>
                {copied ? "복사됨" : "복사"}
              </button>
            </div>

            <div style={{ textAlign: "center", fontSize: 12, color: "#A0AEC0" }}>
              ⏳ 서명 대기 중... 완료되면 자동 반영됩니다
            </div>
          </>
        )}
      </div>
    </>
  );
}
