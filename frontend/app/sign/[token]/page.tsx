"use client";
import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";

type Status = "loading" | "ready" | "submitting" | "submitted" | "expired" | "error";

export default function SignPage() {
  const { token } = useParams<{ token: string }>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const canvasWrapperRef = useRef<HTMLDivElement>(null);
  const padRef = useRef<import("signature_pad").default | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [msg, setMsg] = useState("");
  const [officeName, setOfficeName] = useState("");

  // 토큰 유효성 + 사무소 이름 조회
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
    canvas.width = canvas.offsetWidth * ratio;
    canvas.height = canvas.offsetHeight * ratio;
    const ctx = canvas.getContext("2d");
    ctx?.scale(ratio, ratio);
  };

  // SignaturePad 초기화 + ResizeObserver
  useEffect(() => {
    import("signature_pad").then((mod) => {
      const SignaturePad = mod.default;
      const canvas = canvasRef.current;
      if (!canvas) return;
      resizeCanvas();
      padRef.current = new SignaturePad(canvas, {
        backgroundColor: "rgba(0,0,0,0)",
        penColor: "#000000",
        minWidth: 1.5,
        maxWidth: 3,
      });
      if (status !== "expired") setStatus("ready");
    });

    const wrapper = canvasWrapperRef.current;
    if (!wrapper) return;
    const ro = new ResizeObserver(() => resizeCanvas());
    ro.observe(wrapper);
    return () => ro.disconnect();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleClear = () => padRef.current?.clear();

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
    } catch (e: unknown) {
      setStatus("error");
      setMsg(e instanceof Error ? e.message : "저장 실패. 다시 시도해 주세요.");
    }
  };

  const wrapper: React.CSSProperties = {
    width: "100vw",
    height: "100dvh",
    display: "flex",
    flexDirection: "column",
    background: "#fff",
    overflow: "hidden",
  };

  const header: React.CSSProperties = {
    height: 40,
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0 16px",
    borderBottom: "0.5px solid #E2E8F0",
  };

  const footer: React.CSSProperties = {
    height: 72,
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "0 16px",
    borderTop: "0.5px solid #E2E8F0",
  };

  if (status === "submitted") {
    return (
      <div style={wrapper}>
        <div style={header}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#1A202C" }}>{officeName || "서명 등록"}</span>
        </div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10 }}>
          <span style={{ fontSize: 40, color: "#48BB78" }}>✓</span>
          <span style={{ fontSize: 18, fontWeight: 600, color: "#1A202C" }}>서명이 저장되었습니다</span>
          <span style={{ fontSize: 14, color: "#718096" }}>창을 닫아도 됩니다</span>
        </div>
      </div>
    );
  }

  if (status === "expired") {
    return (
      <div style={wrapper}>
        <div style={header}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#1A202C" }}>{officeName || "서명 등록"}</span>
        </div>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10 }}>
          <span style={{ fontSize: 18, fontWeight: 600, color: "#C53030" }}>링크가 만료되었습니다</span>
          <span style={{ fontSize: 14, color: "#718096" }}>새로 요청해 주세요</span>
        </div>
      </div>
    );
  }

  return (
    <div style={wrapper}>
      {/* 헤더 */}
      <div style={header}>
        <span style={{ fontSize: 13, fontWeight: 600, color: "#1A202C" }}>
          {officeName || "서명 등록"}
        </span>
        <span style={{ fontSize: 11, color: "#718096" }}>아래에 서명해 주세요</span>
      </div>

      {/* 캔버스 영역 */}
      <div ref={canvasWrapperRef} style={{ flex: 1, position: "relative" }}>
        {/* 점선 테두리 */}
        <div style={{
          position: "absolute", inset: 10,
          border: "1.5px dashed #CBD5E0",
          borderRadius: 4,
          pointerEvents: "none",
        }} />
        {/* 중앙 가이드라인 */}
        <div style={{
          position: "absolute",
          top: "50%", left: 10, right: 10,
          height: 1,
          background: "#E2E8F0",
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
            color: "#A0AEC0", fontSize: 13,
          }}>
            로딩 중...
          </div>
        )}
        {msg && (
          <div style={{
            position: "absolute", bottom: 14, left: 0, right: 0,
            textAlign: "center", fontSize: 12, color: "#C53030",
          }}>
            {msg}
          </div>
        )}
      </div>

      {/* 푸터 */}
      <div style={footer}>
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
          다시 그리기
        </button>
        <button
          onClick={handleSave}
          disabled={status !== "ready"}
          style={{
            flex: 2, height: 48,
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
