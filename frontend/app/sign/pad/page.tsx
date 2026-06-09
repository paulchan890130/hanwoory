"use client";
import { useEffect, useRef, useState } from "react";

// 상시 서명패드 — 사무실 태블릿/휴대폰에 항상 띄워두는 페이지.
// 고객정보 표시 없음. 저장 시 비어 있는 임시서명(1→2→3) 중 가장 앞 슬롯에 자동 저장.
type Status = "loading" | "ready" | "saving" | "invalid";

const pageStyle: React.CSSProperties = {
  width: "100vw", height: "100dvh", display: "flex", flexDirection: "column",
  background: "#fff", overflow: "hidden",
};

export default function SignPadPage() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const signWrapperRef = useRef<HTMLDivElement>(null);
  const padRef = useRef<import("signature_pad").default | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [officeName, setOfficeName] = useState("");
  const [banner, setBanner] = useState<{ kind: "ok" | "full" | "error"; text: string } | null>(null);

  // 토큰은 URL ?token= 에서 읽는다(Suspense 회피 위해 window 사용).
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("token");
    if (!t) { setStatus("invalid"); return; }
    setToken(t);
    fetch(`/api/signature/pad/info?token=${encodeURIComponent(t)}`)
      .then((r) => r.json())
      .then((j) => {
        if (!j.valid) { setStatus("invalid"); return; }
        if (j.office_name) setOfficeName(j.office_name);
      })
      .catch(() => { /* 네트워크 일시 오류는 무시 — 저장 시 재검증됨 */ });
  }, []);

  const resizeCanvas = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ratio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.round(rect.width * ratio);
    canvas.height = Math.round(rect.height * ratio);
    canvas.getContext("2d")?.setTransform(ratio, 0, 0, ratio, 0, 0);
    padRef.current?.clear();
  };

  useEffect(() => {
    import("signature_pad").then((mod) => {
      const SignaturePad = mod.default;
      const canvas = canvasRef.current;
      const wrapper = signWrapperRef.current;
      if (!canvas || !wrapper) return;
      resizeCanvas();
      padRef.current = new SignaturePad(canvas, {
        backgroundColor: "rgba(0,0,0,0)",   // 투명 배경 — 흰색 fill 금지
        penColor: "#000000", minWidth: 1.5, maxWidth: 3,
      });
      setStatus((s) => (s === "invalid" ? s : "ready"));
      const ro = new ResizeObserver(() => resizeCanvas());
      ro.observe(wrapper);
      return () => ro.disconnect();
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleClear = () => { padRef.current?.clear(); setBanner(null); };

  const handleSave = async () => {
    const pad = padRef.current;
    if (!pad || !token) return;
    if (pad.isEmpty()) { setBanner({ kind: "error", text: "서명을 먼저 해주세요." }); return; }
    setStatus("saving");
    setBanner(null);
    try {
      const dataUrl = pad.toDataURL("image/png");  // 투명 PNG (alpha 유지)
      const res = await fetch(`/api/signature/pad/save?token=${encodeURIComponent(token)}`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: dataUrl }),
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok && j.status === "ok") {
        setBanner({ kind: "ok", text: `${j.slot}번 임시서명에 저장되었습니다.` });
        pad.clear();
        // 1.5초 후 배너 비우고 다음 서명 대기(상시 모드)
        window.setTimeout(() => setBanner(null), 1500);
      } else if (res.ok && j.status === "full") {
        setBanner({ kind: "full", text: "임시서명란이 모두 찼습니다. 직원에게 말씀해 주세요." });
      } else {
        setBanner({ kind: "error", text: "저장에 실패했습니다. 직원에게 말씀해 주세요." });
      }
    } catch {
      setBanner({ kind: "error", text: "저장에 실패했습니다. 직원에게 말씀해 주세요." });
    } finally {
      setStatus((s) => (s === "invalid" ? s : "ready"));
    }
  };

  if (status === "invalid") {
    return (
      <div style={{ ...pageStyle, alignItems: "center", justifyContent: "center", gap: 12 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: "#E53E3E" }}>유효하지 않은 서명패드 주소입니다</span>
        <span style={{ fontSize: 13, color: "#718096" }}>직원에게 말씀해 주세요</span>
      </div>
    );
  }

  const bannerColor = banner?.kind === "ok" ? "#276749" : banner?.kind === "full" ? "#9C4221" : "#C53030";

  return (
    <div style={pageStyle}>
      <div style={{ height: 48, flexShrink: 0, display: "flex", justifyContent: "space-between", alignItems: "center", padding: "0 16px", borderBottom: "0.5px solid #E2E8F0" }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: "#1A202C" }}>{officeName || "서명"}</span>
        <span style={{ fontSize: 13, color: "#718096" }}>서명해 주세요</span>
      </div>

      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 16, overflow: "hidden" }}>
        <div ref={signWrapperRef} style={{ position: "relative", width: "100%", maxWidth: 720, aspectRatio: "10 / 7", flex: "0 0 auto", background: "transparent" }}>
          <div style={{ position: "absolute", inset: 0, border: "1.5px dashed #CBD5E0", borderRadius: 8, pointerEvents: "none" }} />
          <canvas ref={canvasRef} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", touchAction: "none", background: "transparent" }} />
        </div>
      </div>

      <div style={{ height: 64, flexShrink: 0, position: "relative", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, padding: "8px 16px", borderTop: "0.5px solid #E2E8F0" }}>
        {banner && (
          <span style={{ position: "absolute", bottom: 72, left: 0, right: 0, textAlign: "center", fontSize: 15, fontWeight: 700, color: bannerColor, pointerEvents: "none" }}>
            {banner.text}
          </span>
        )}
        <button onClick={handleClear} disabled={status === "saving"}
          style={{ flex: 1, height: 48, border: "1px solid #CBD5E0", borderRadius: 12, background: "#fff", fontSize: 15, color: "#4A5568", cursor: status === "saving" ? "default" : "pointer", opacity: status === "saving" ? 0.5 : 1 }}>
          다시 쓰기
        </button>
        <button onClick={handleSave} disabled={status === "saving" || banner?.kind === "full"}
          style={{ flex: 1, height: 48, background: status === "saving" ? "#E2E8F0" : "#F5A623", border: "none", borderRadius: 12, color: "#fff", fontSize: 15, fontWeight: 700, cursor: status === "saving" ? "default" : "pointer", opacity: status === "saving" ? 0.7 : 1 }}>
          {status === "saving" ? "저장 중..." : "저장"}
        </button>
      </div>
    </div>
  );
}
