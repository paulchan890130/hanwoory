"use client";
import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";

type Status = "loading" | "ready" | "submitting" | "submitted" | "expired" | "error";

const pageStyle: React.CSSProperties = {
  width: "100vw",
  height: "100dvh",
  display: "flex",
  flexDirection: "column",
  background: "#fff",
  overflow: "hidden",
};

export default function SignPage() {
  const { token } = useParams<{ token: string }>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const signWrapperRef = useRef<HTMLDivElement>(null);
  const padRef = useRef<import("signature_pad").default | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [msg, setMsg] = useState("");
  const [officeName, setOfficeName] = useState("");

  // 토큰 유효성 + 사무소 이름 조회 — 기존 로직 유지
  useEffect(() => {
    fetch(`/api/signature/info/${token}`)
      .then((r) => r.json())
      .then((j) => {
        if (j.status === "expired") setStatus("expired");
        if (j.office_name) setOfficeName(j.office_name);
      })
      .catch(() => {});
  }, [token]);

  const resizeCanvas = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ratio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.round(rect.width * ratio);
    canvas.height = Math.round(rect.height * ratio);
    const ctx = canvas.getContext("2d");
    ctx?.setTransform(ratio, 0, 0, ratio, 0, 0);
    padRef.current?.clear();
  };

  // SignaturePad 초기화 — ResizeObserver는 서명칸 wrapper 기준
  useEffect(() => {
    import("signature_pad").then((mod) => {
      const SignaturePad = mod.default;
      const canvas = canvasRef.current;
      const wrapper = signWrapperRef.current;
      if (!canvas || !wrapper) return;

      resizeCanvas();
      padRef.current = new SignaturePad(canvas, {
        backgroundColor: "rgba(0,0,0,0)",
        penColor: "#000000",
        minWidth: 1.5,
        maxWidth: 3,
      });
      if (status !== "expired") setStatus("ready");

      const ro = new ResizeObserver(() => resizeCanvas());
      ro.observe(wrapper);
      return () => ro.disconnect();
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleClear = () => {
    padRef.current?.clear();
    setMsg("");
  };

  // 기존 submit 로직 완전 유지
  const handleSave = async () => {
    const pad = padRef.current;
    if (!pad) return;
    if (pad.isEmpty()) { setMsg("서명을 먼저 그려주세요."); return; }
    setStatus("submitting");
    setMsg("");
    try {
      const dataUrl = pad.toDataURL("image/png");
      const res = await fetch(`/api/signature/submit/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: dataUrl }),
      });
      if (res.status === 404) { setStatus("expired"); return; }
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        throw new Error(j.detail || "저장 실패");
      }
      setStatus("submitted");
    } catch {
      // Reset to ready so customer can retry; show clear contact message
      setStatus("ready");
      setMsg("서명 저장에 실패했습니다. 창을 닫지 말고 사무소에 연락해주세요.");
    }
  };

  if (status === "submitted") {
    return (
      <div style={{ ...pageStyle, alignItems: "center", justifyContent: "center", gap: 12 }}>
        <span style={{ fontSize: 40, color: "#48BB78" }}>✓</span>
        <span style={{ fontSize: 18, fontWeight: 700, color: "#1A202C" }}>서명이 저장되었습니다</span>
        <span style={{ fontSize: 13, color: "#718096" }}>창을 닫아도 됩니다</span>
      </div>
    );
  }

  if (status === "expired") {
    return (
      <div style={{ ...pageStyle, alignItems: "center", justifyContent: "center", gap: 12 }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: "#E53E3E" }}>링크가 만료되었습니다</span>
        <span style={{ fontSize: 13, color: "#718096" }}>새로 요청해 주세요</span>
      </div>
    );
  }

  return (
    <div style={pageStyle}>

      {/* 헤더 */}
      <div style={{
        height: 48, flexShrink: 0,
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "0 16px",
        borderBottom: "0.5px solid #E2E8F0",
      }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: "#1A202C" }}>
          {officeName || "서명 등록"}
        </span>
        <span style={{ fontSize: 12, color: "#718096" }}>아래에 서명해 주세요</span>
      </div>

      {/* 중앙 영역 — 서명칸을 가운데 배치 */}
      <div style={{
        flex: 1,
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 16, overflow: "hidden",
      }}>
        {/* 서명칸 wrapper — aspectRatio만, flex:1 금지 */}
        <div
          ref={signWrapperRef}
          style={{
            position: "relative",
            width: "100%",
            maxWidth: 720,
            aspectRatio: "10 / 7",
            flex: "0 0 auto",
            background: "transparent",
          }}
        >
          {/* 점선 가이드 */}
          <div style={{
            position: "absolute", inset: 0,
            border: "1.5px dashed #CBD5E0",
            borderRadius: 8,
            pointerEvents: "none",
          }} />

          <canvas
            ref={canvasRef}
            style={{
              position: "absolute", inset: 0,
              width: "100%", height: "100%",
              touchAction: "none",
              background: "transparent",
            }}
          />

          {status === "loading" && (
            <div style={{
              position: "absolute", inset: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "#A0AEC0", fontSize: 13, pointerEvents: "none",
            }}>
              로딩 중...
            </div>
          )}
        </div>
      </div>

      {/* 푸터 */}
      <div style={{
        height: 64, flexShrink: 0,
        display: "flex", justifyContent: "space-between", alignItems: "center",
        gap: 12, padding: "8px 16px",
        borderTop: "0.5px solid #E2E8F0",
      }}>
        {msg && (
          <span style={{
            position: "absolute",
            bottom: 72, left: 0, right: 0,
            textAlign: "center", fontSize: 12, color: "#C53030",
            pointerEvents: "none",
          }}>
            {msg}
          </span>
        )}
        <button
          onClick={handleClear}
          disabled={status !== "ready"}
          style={{
            flex: 1, height: 48,
            border: "1px solid #CBD5E0", borderRadius: 12,
            background: "#fff", fontSize: 14, color: "#4A5568",
            cursor: status !== "ready" ? "default" : "pointer",
            opacity: status !== "ready" ? 0.45 : 1,
          }}
        >
          다시 서명하기
        </button>
        <button
          onClick={handleSave}
          disabled={status !== "ready"}
          style={{
            flex: 1, height: 48,
            background: status !== "ready" ? "#E2E8F0" : "#F5A623",
            border: "none", borderRadius: 12,
            color: "#fff", fontSize: 14, fontWeight: 600,
            cursor: status !== "ready" ? "default" : "pointer",
            opacity: status === "submitting" ? 0.65 : 1,
          }}
        >
          {status === "submitting" ? "저장 중..." : "저장하기"}
        </button>
      </div>

    </div>
  );
}
