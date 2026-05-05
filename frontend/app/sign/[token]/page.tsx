"use client";
import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";

type Status = "loading" | "ready" | "submitting" | "submitted" | "expired" | "error";

export default function SignPage() {
  const { token } = useParams<{ token: string }>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const padRef = useRef<import("signature_pad").default | null>(null);
  const [status, setStatus] = useState<Status>("loading");
  const [msg, setMsg] = useState("");

  // SignaturePad 초기화
  useEffect(() => {
    let SignaturePad: typeof import("signature_pad").default;
    import("signature_pad").then((mod) => {
      SignaturePad = mod.default;
      const canvas = canvasRef.current;
      if (!canvas) return;

      // devicePixelRatio 대응
      const ratio = window.devicePixelRatio || 1;
      canvas.width  = canvas.offsetWidth  * ratio;
      canvas.height = canvas.offsetHeight * ratio;
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.scale(ratio, ratio);

      padRef.current = new SignaturePad(canvas, {
        backgroundColor: "rgba(255,255,255,0)",
        penColor: "#000",
      });
      setStatus("ready");
    });

    const handleResize = () => {
      const canvas = canvasRef.current;
      const pad = padRef.current;
      if (!canvas || !pad) return;
      const data = pad.toData();
      const ratio = window.devicePixelRatio || 1;
      canvas.width  = canvas.offsetWidth  * ratio;
      canvas.height = canvas.offsetHeight * ratio;
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.scale(ratio, ratio);
      pad.fromData(data);
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const handleClear = () => {
    padRef.current?.clear();
  };

  const handleSave = async () => {
    const pad = padRef.current;
    if (!pad) return;
    if (pad.isEmpty()) {
      setMsg("서명을 먼저 그려주세요.");
      return;
    }
    setStatus("submitting");
    setMsg("");
    try {
      const dataUrl = pad.toDataURL("image/png");
      const res = await fetch(`/api/signature/submit/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ data: dataUrl }),
      });
      if (res.status === 404) {
        setStatus("expired");
        return;
      }
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

  // ── 제출 완료 화면 ──
  if (status === "submitted") {
    return (
      <div style={styles.page}>
        <div style={{ ...styles.card, textAlign: "center", padding: "40px 24px" }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>✅</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#276749", marginBottom: 8 }}>
            서명이 저장되었습니다.
          </div>
          <div style={{ fontSize: 14, color: "#718096" }}>창을 닫아도 됩니다.</div>
        </div>
      </div>
    );
  }

  // ── 만료 화면 ──
  if (status === "expired") {
    return (
      <div style={styles.page}>
        <div style={{ ...styles.card, textAlign: "center", padding: "40px 24px" }}>
          <div style={{ fontSize: 48, marginBottom: 12 }}>⏰</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#C53030", marginBottom: 8 }}>
            링크가 만료되었습니다.
          </div>
          <div style={{ fontSize: 14, color: "#718096" }}>담당자에게 새 링크를 요청해 주세요.</div>
        </div>
      </div>
    );
  }

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        {/* 헤더 */}
        <div style={{ textAlign: "center", marginBottom: 20 }}>
          <div style={{ fontSize: 22, marginBottom: 4 }}>🖊</div>
          <div style={{ fontSize: 17, fontWeight: 700, color: "#1A202C" }}>한우리행정사사무소</div>
          <div style={{ fontSize: 13, color: "#718096", marginTop: 4 }}>아래에 서명해 주세요</div>
        </div>

        {/* 캔버스 영역 */}
        <div style={{
          position: "relative",
          border: "2px dashed #CBD5E0",
          borderRadius: 10,
          background: "#FAFAFA",
          marginBottom: 16,
          overflow: "hidden",
        }}>
          {/* 중앙 안내선 */}
          <div style={{
            position: "absolute", left: "5%", right: "5%",
            top: "50%", height: 1,
            background: "#E2E8F0", pointerEvents: "none",
          }} />
          <canvas
            ref={canvasRef}
            style={{ display: "block", width: "100%", height: 200, touchAction: "none" }}
          />
          {status === "loading" && (
            <div style={{
              position: "absolute", inset: 0, display: "flex",
              alignItems: "center", justifyContent: "center",
              color: "#A0AEC0", fontSize: 13,
            }}>
              로딩 중...
            </div>
          )}
        </div>

        {/* 에러 메시지 */}
        {msg && (
          <div style={{ color: "#C53030", fontSize: 13, marginBottom: 10, textAlign: "center" }}>
            {msg}
          </div>
        )}

        {/* 버튼 */}
        <div style={{ display: "flex", gap: 10 }}>
          <button
            onClick={handleClear}
            disabled={status !== "ready"}
            style={{ ...styles.btn, flex: 1, background: "#fff", color: "#4A5568", border: "1.5px solid #CBD5E0" }}
          >
            다시 그리기
          </button>
          <button
            onClick={handleSave}
            disabled={status !== "ready"}
            style={{ ...styles.btn, flex: 2, background: status !== "ready" ? "#E2E8F0" : "#F5A623", color: "#fff", border: "none" }}
          >
            {status === "submitting" ? "저장 중..." : "저장하기"}
          </button>
        </div>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: "100dvh",
    background: "#fff",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "16px",
  },
  card: {
    width: "100%",
    maxWidth: 420,
    background: "#fff",
    borderRadius: 14,
    boxShadow: "0 2px 20px rgba(0,0,0,0.10)",
    padding: "24px 20px",
  },
  btn: {
    height: 52,
    borderRadius: 10,
    fontSize: 15,
    fontWeight: 700,
    cursor: "pointer",
    transition: "opacity 0.15s",
  },
};
