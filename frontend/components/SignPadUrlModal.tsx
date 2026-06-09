"use client";
import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { api } from "@/lib/api";

/**
 * 서명패드 URL/QR 발급 모달 — 로그인 직원 전용.
 * /api/signature/pad/token (current_user.tenant_id 기반) 으로 발급된 URL 을 표시·복사·새창·QR.
 * 고객정보는 표시하지 않는다. QR 은 URL 시각화일 뿐 별도 저장 로직 없음.
 */
export default function SignPadUrlModal({ onClose }: { onClose: () => void }) {
  const [url, setUrl] = useState("");
  const [qr, setQr] = useState("");
  const [status, setStatus] = useState<"loading" | "ok" | "error">("loading");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.get<{ url: string; token: string }>("/api/signature/pad/token", {
      headers: { "X-Skip-Auth-Redirect": "1" },
    })
      .then(async (r) => {
        const u = r.data?.url || "";
        setUrl(u);
        try { setQr(await QRCode.toDataURL(u, { width: 240, margin: 1 })); } catch { /* QR 생성 실패 무시 */ }
        setStatus("ok");
      })
      .catch(() => setStatus("error"));
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { /* clipboard 차단 환경 */ }
  };

  return (
    <div onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 400, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ width: "min(420px, 94vw)", background: "#fff", borderRadius: 14, boxShadow: "0 8px 32px rgba(0,0,0,0.18)", padding: 0, overflow: "hidden" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 18px", borderBottom: "1px solid #E2E8F0", background: "#FAFBFC" }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: "#1A202C" }}>📝 서명패드 URL / QR</span>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "#A0AEC0", fontSize: 18 }}>×</button>
        </div>

        <div style={{ padding: 18, display: "flex", flexDirection: "column", gap: 12 }}>
          {status === "loading" && <div style={{ color: "#718096", fontSize: 13, textAlign: "center", padding: 20 }}>발급 중...</div>}

          {status === "error" && (
            <div style={{ color: "#C53030", fontSize: 13, background: "#FFF5F5", border: "1px solid #FEB2B2", borderRadius: 8, padding: "10px 12px" }}>
              서명패드 URL 발급에 실패했습니다.
            </div>
          )}

          {status === "ok" && (
            <>
              <div style={{ color: "#276749", fontSize: 13, fontWeight: 600 }}>서명패드 URL이 발급되었습니다.</div>
              <div style={{ fontSize: 11, color: "#718096", lineHeight: 1.5 }}>
                안 쓰는 태블릿·휴대폰에서 아래 URL을 열거나 QR을 스캔하면 상시 서명 화면이 뜹니다.
                (서명 시 비어 있는 임시서명 1~3번에 자동 저장)
              </div>

              <div style={{ display: "flex", gap: 6 }}>
                <input readOnly value={url}
                  style={{ flex: 1, fontSize: 12, padding: "8px 10px", border: "1px solid #CBD5E0", borderRadius: 8, background: "#F7FAFC", color: "#2D3748" }}
                  onFocus={(e) => e.currentTarget.select()} />
              </div>

              <div style={{ display: "flex", gap: 8 }}>
                <button onClick={copy} className="btn-primary" style={{ flex: 1, fontSize: 13, padding: "8px 0" }}>
                  {copied ? "복사됨 ✓" : "복사"}
                </button>
                <button onClick={() => window.open(url, "_blank")}
                  style={{ flex: 1, fontSize: 13, padding: "8px 0", border: "1px solid #CBD5E0", borderRadius: 8, background: "#fff", color: "#4A5568", cursor: "pointer" }}>
                  새 창에서 열기
                </button>
              </div>

              {qr && (
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6, marginTop: 4 }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={qr} alt="서명패드 QR" width={200} height={200} style={{ borderRadius: 8, border: "1px solid #E2E8F0" }} />
                  <span style={{ fontSize: 11, color: "#A0AEC0" }}>QR을 태블릿/휴대폰으로 스캔</span>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
