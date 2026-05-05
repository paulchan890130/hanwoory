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
        penColor: "#000",
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

  const fullScreen: React.CSSProperties = {
    width: "100vw", height: "100dvh",
    display: "flex", flexDirection: "column",
    background: "#fff", overflow: "hidden",
  };

  if (status === "submitted") {
    return (
      <div style={{ ...fullScreen, alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 44, marginBottom: 12 }}>✅</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#276749", marginBottom: 6 }}>
            서명이 저장되었습니다.
          </div>
          <div style={{ fontSize: 13, color: "#718096" }}>창을 닫아도 됩니다.</div>
        </div>
      </div>
    );
  }

  if (status === "expired") {
    return (
      <div style={{ ...fullScreen, alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center" }}>
          <div style={{ fontSize: 44, marginBottom: 12 }}>⏰</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#C53030", marginBottom: 6 }}>
            링크가 만료되었습니다.
          </div>
          <div style={{ fontSize: 13, color: "#718096" }}>담당자에게 새 링크를 요청해 주세요.</div>
        </div>
      </div>
    );
  }

  return (
    <div style={fullScreen}>
      {/* 헤더 */}
      <div style={{
        flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "12px 16px",
        borderBottom: "1px solid #E2E8F0",
      }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: "#1A202C" }}>
          {officeName || "서명 등록"}
        </span>
        <span style={{ fontSize: 12, color: "#A0AEC0" }}>아래에 서명해 주세요</span>
      </div>

      {/* 캔버스 영역 */}
      <div
        ref={canvasWrapperRef}
        style={{
          flex: 1, position: "relative", overflow: "hidden",
          border: "1.5px dashed #CBD5E0",
          margin: "8px 12px", borderRadius: 8,
        }}
      >
        {/* 중앙 안내선 */}
        <div style={{
          position: "absolute", left: "5%", right: "5%",
          top: "50%", height: 1,
          background: "#E2E8F0", pointerEvents: "none",
        }} />
        <canvas
          ref={canvasRef}
          style={{
            position: "absolute", top: 0, left: 0,
            width: "100%", height: "100%",
            touchAction: "none", background: "transparent",
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
            position: "absolute", bottom: 8, left: 0, right: 0,
            textAlign: "center", fontSize: 12, color: "#C53030",
          }}>
            {msg}
          </div>
        )}
      </div>

      {/* 푸터 */}
      <div style={{
        flexShrink: 0,
        display: "flex", gap: 12,
        padding: "10px 16px", height: 60, boxSizing: "border-box",
      }}>
        <button
          onClick={handleClear}
          disabled={status !== "ready"}
          style={{
            flex: 1, borderRadius: 10, fontSize: 14, fontWeight: 600,
            cursor: status !== "ready" ? "default" : "pointer",
            background: "#fff", color: "#4A5568",
            border: "1.5px solid #CBD5E0",
            opacity: status !== "ready" ? 0.5 : 1,
          }}
        >
          다시 그리기
        </button>
        <button
          onClick={handleSave}
          disabled={status !== "ready"}
          style={{
            flex: 2, borderRadius: 10, fontSize: 15, fontWeight: 700,
            cursor: status !== "ready" ? "default" : "pointer",
            background: status !== "ready" ? "#E2E8F0" : "#F5A623",
            color: "#fff", border: "none",
            opacity: status === "submitting" ? 0.7 : 1,
          }}
        >
          {status === "submitting" ? "저장 중..." : "저장하기"}
        </button>
      </div>
    </div>
  );
}
