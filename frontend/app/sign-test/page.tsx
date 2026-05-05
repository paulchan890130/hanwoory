"use client";
import { useEffect, useRef, useState } from "react";

const pageStyle: React.CSSProperties = {
  width: "100vw",
  height: "100dvh",
  display: "flex",
  flexDirection: "column",
  background: "#fff",
  overflow: "hidden",
};

export default function SignTestPage() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const signWrapperRef = useRef<HTMLDivElement>(null);
  const padRef = useRef<import("signature_pad").default | null>(null);
  const [ready, setReady] = useState(false);
  const [msg, setMsg] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

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
      setReady(true);

      const ro = new ResizeObserver(() => resizeCanvas());
      ro.observe(wrapper);
      return () => ro.disconnect();
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleClear = () => {
    padRef.current?.clear();
    setMsg("");
    setPreview(null);
    setSaved(false);
  };

  const handleSave = () => {
    const pad = padRef.current;
    if (!pad) return;
    if (pad.isEmpty()) { setMsg("서명을 먼저 그려주세요."); return; }
    setMsg("");
    const dataUrl = pad.toDataURL("image/png");
    console.log("[sign-test] dataUrl length:", dataUrl.length, "| starts with:", dataUrl.slice(0, 30));
    setPreview(dataUrl);
    setSaved(true);
  };

  return (
    <div style={pageStyle}>

      {/* 헤더 */}
      <div style={{
        height: 48, flexShrink: 0,
        display: "flex", justifyContent: "space-between", alignItems: "center",
        padding: "0 16px",
        borderBottom: "0.5px solid #E2E8F0",
      }}>
        <span style={{ fontSize: 14, fontWeight: 600, color: "#1A202C" }}>한우리소프트</span>
        <span style={{ fontSize: 12, color: "#718096" }}>아래에 서명해 주세요</span>
      </div>

      {/* 중앙 영역 */}
      <div style={{
        flex: 1,
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center",
        padding: 16, overflow: "hidden", gap: 12,
      }}>
        {/* 서명칸 */}
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
          {!ready && (
            <div style={{
              position: "absolute", inset: 0,
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "#A0AEC0", fontSize: 13, pointerEvents: "none",
            }}>
              로딩 중...
            </div>
          )}
        </div>

        {/* 저장 완료 + 프리뷰 */}
        {saved && preview && (
          <div style={{ textAlign: "center", width: "100%", maxWidth: 720 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: "#276749", marginBottom: 6 }}>
              ✓ 테스트 저장 완료 — 투명 PNG 확인
            </div>
            <div style={{
              display: "inline-block",
              background: "repeating-conic-gradient(#e0e0e0 0% 25%, #fff 0% 50%) 0 0 / 12px 12px",
              borderRadius: 6,
              padding: 4,
              border: "1px solid #E2E8F0",
            }}>
              <img
                src={preview}
                alt="서명 미리보기"
                style={{ display: "block", maxWidth: "100%", maxHeight: 80 }}
              />
            </div>
          </div>
        )}
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
          disabled={!ready}
          style={{
            flex: 1, height: 48,
            border: "1px solid #CBD5E0", borderRadius: 12,
            background: "#fff", fontSize: 14, color: "#4A5568",
            cursor: !ready ? "default" : "pointer",
            opacity: !ready ? 0.45 : 1,
          }}
        >
          다시 서명하기
        </button>
        <button
          onClick={handleSave}
          disabled={!ready}
          style={{
            flex: 1, height: 48,
            background: !ready ? "#E2E8F0" : "#F5A623",
            border: "none", borderRadius: 12,
            color: "#fff", fontSize: 14, fontWeight: 600,
            cursor: !ready ? "default" : "pointer",
          }}
        >
          저장하기
        </button>
      </div>

    </div>
  );
}
