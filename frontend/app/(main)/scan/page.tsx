"use client";

import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ScanLine, Upload } from "lucide-react";
import { api } from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────────

interface PassportOcr {
  성?: string; 명?: string; 국적?: string; 국가?: string; 성별?: string;
  여권?: string; 발급?: string; 만기?: string; 생년월일?: string; error?: string;
}

const ARC_FIELDS = ["한글", "등록증", "번호", "발급일", "만기일", "주소"] as const;
type ArcFieldKey = (typeof ARC_FIELDS)[number];

const ARC_FIELD_LABELS: Record<ArcFieldKey, string> = {
  한글:  "한글 이름",
  등록증: "등록증 앞 (YYMMDD)",
  번호:  "등록증 뒤 7자리",
  발급일: "등록증 발급일 (YYYY-MM-DD)",
  만기일: "등록증 만기일 (YYYY-MM-DD)",
  주소:  "주소",
};

// ── Styles ────────────────────────────────────────────────────────────────────

const labelStyle: React.CSSProperties = {
  display: "block", fontSize: 11, fontWeight: 500, color: "#718096", marginBottom: 3,
};
const inputStyle: React.CSSProperties = {
  width: "100%", padding: "6px 8px", fontSize: 13,
  border: "1px solid #CBD5E0", borderRadius: 6, background: "#fff",
  outline: "none", boxSizing: "border-box",
};
const cardStyle: React.CSSProperties = {
  background: "#fff", border: "1px solid #E2E8F0", borderRadius: 10, padding: 12,
};
const sectionTitleStyle: React.CSSProperties = {
  fontSize: 13, fontWeight: 700, color: "#4A5568", marginBottom: 8,
};
const smallBtnStyle: React.CSSProperties = {
  height: 32, padding: "0 10px", borderRadius: 6,
  border: "1px solid #D69E2E", background: "#fffaf0", color: "#975A16",
  fontSize: 12, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap",
};
const disabledBtnStyle: React.CSSProperties = {
  ...smallBtnStyle, opacity: 0.5, cursor: "not-allowed",
};
const smallToolBtnStyle: React.CSSProperties = {
  height: 28, padding: "0 9px", borderRadius: 5,
  border: "1px solid #CBD5E0", background: "#EDF2F7", color: "#4A5568",
  fontSize: 12, fontWeight: 500, cursor: "pointer",
};
const selBtnStyle: React.CSSProperties = {
  height: 32, padding: "0 8px", borderRadius: 6,
  border: "1px solid #3182ce", background: "#ebf8ff", color: "#2b6cb0",
  fontSize: 12, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap",
};
const selActiveBtnStyle: React.CSSProperties = {
  ...selBtnStyle, background: "#3182ce", color: "#fff",
};

// ── Workspace transform types ─────────────────────────────────────────────────

interface WsTf   { scale: number; tx: number; ty: number; rot: number }
interface WsSize { w: number; h: number }
interface WsState { tf: WsTf; container: WsSize; natural: WsSize }
type ContainerRect = { x: number; y: number; w: number; h: number };

const DEFAULT_TF: WsTf = { scale: 1, tx: 0, ty: 0, rot: 0 };

// ── ROI computation ───────────────────────────────────────────────────────────

function computeRoi(
  guide: { x: number; y: number; w: number; h: number },
  container: WsSize,
  natural: WsSize,
  tf: WsTf,
): ContainerRect {
  const { scale, tx, ty } = tf;
  const rot = ((tf.rot % 360) + 360) % 360;
  const { w: cW, h: cH } = container;

  const dispW = (rot === 90 || rot === 270) ? natural.h * scale : natural.w * scale;
  const dispH = (rot === 90 || rot === 270) ? natural.w * scale : natural.h * scale;

  const imgLeft = cW / 2 + tx - dispW / 2;
  const imgTop  = cH / 2 + ty - dispH / 2;

  const relL = guide.x * cW - imgLeft;
  const relT = guide.y * cH - imgTop;
  const relW = guide.w * cW;
  const relH = guide.h * cH;

  const cl = (v: number) => Math.max(0, Math.min(1, v));
  const cs = (v: number) => Math.max(0.01, Math.min(1, v));

  if (rot === 0) {
    return { x: cl(relL / dispW), y: cl(relT / dispH), w: cs(relW / dispW), h: cs(relH / dispH) };
  }
  if (rot === 90) {
    return {
      x: cl(relT / dispH),
      y: cl((dispW - relL - relW) / dispW),
      w: cs(relH / dispH),
      h: cs(relW / dispW),
    };
  }
  if (rot === 180) {
    return {
      x: cl((dispW - relL - relW) / dispW),
      y: cl((dispH - relT - relH) / dispH),
      w: cs(relW / dispW),
      h: cs(relH / dispH),
    };
  }
  return {
    x: cl((dispH - relT - relH) / dispH),
    y: cl(relL / dispW),
    w: cs(relH / dispH),
    h: cs(relW / dispW),
  };
}

// ── ROI → container-space inverse ────────────────────────────────────────────

function roiToContainerBox(
  roi: ContainerRect,
  container: WsSize,
  natural: WsSize,
  tf: WsTf,
): { left: number; top: number; width: number; height: number } {
  const { scale, tx, ty } = tf;
  const rot = ((tf.rot % 360) + 360) % 360;
  const { w: cW, h: cH } = container;

  const dispW = (rot === 90 || rot === 270) ? natural.h * scale : natural.w * scale;
  const dispH = (rot === 90 || rot === 270) ? natural.w * scale : natural.h * scale;

  const imgLeft = cW / 2 + tx - dispW / 2;
  const imgTop  = cH / 2 + ty - dispH / 2;

  let relL: number, relT: number, relW: number, relH: number;

  if (rot === 0) {
    relL = roi.x * dispW;  relT = roi.y * dispH;
    relW = roi.w * dispW;  relH = roi.h * dispH;
  } else if (rot === 90) {
    relL = dispW * (1 - roi.y - roi.h);  relT = roi.x * dispH;
    relW = roi.h * dispW;                relH = roi.w * dispH;
  } else if (rot === 180) {
    relL = dispW * (1 - roi.x - roi.w);  relT = dispH * (1 - roi.y - roi.h);
    relW = roi.w * dispW;                relH = roi.h * dispH;
  } else {
    relL = roi.y * dispW;                relT = dispH * (1 - roi.x - roi.w);
    relW = roi.h * dispW;                relH = roi.w * dispH;
  }

  return { left: imgLeft + relL, top: imgTop + relT, width: relW, height: relH };
}

// ── Guide definitions ─────────────────────────────────────────────────────────

const PASSPORT_MRZ_GUIDE = {
  key: "mrz", label: "MRZ",
  x: 0.160, y: 0.635, w: 0.630, h: 0.085,
  color: "#D69E2E",
  labelPos: "inside" as const,
};

// labelPos controls where the label appears relative to the box:
//   "inside" = top-left inside box (default)
//   "above"  = above the box
//   "below"  = below the box
//   "right"  = to the right of the box
const ARC_GUIDE_BOXES: Array<{
  key: ArcFieldKey; label: string;
  x: number; y: number; w: number; h: number;
  color: string;
  labelPos: "inside" | "above" | "below" | "right";
}> = [
  // A. 등록증 앞 — label above box
  { key: "등록증", label: "등록증 앞",  x: 0.368, y: 0.174, w: 0.075, h: 0.024, color: "#dd6b20", labelPos: "above" },
  // B. 등록증 뒤 — label above, width 1.2× 등록증 앞
  { key: "번호",   label: "등록증 뒤",  x: 0.451, y: 0.174, w: 0.090, h: 0.024, color: "#d69e2e", labelPos: "above" },
  // C. 한글 이름 — label below, shifted down 2 box-units (2×0.018=0.036)
  { key: "한글",   label: "한글 이름",  x: 0.374, y: 0.241, w: 0.058, h: 0.018, color: "#e53e3e", labelPos: "below" },
  // D. 발급일 — label above, shifted down 2.8 box-units (×0.028=0.078) and left 0.8 box-units (×0.110=0.088)
  { key: "발급일", label: "발급일",    x: 0.477, y: 0.339, w: 0.110, h: 0.028, color: "#38a169", labelPos: "above" },
  // E. 만기일 — label right, horizontal rectangle
  { key: "만기일", label: "만기일",    x: 0.290, y: 0.665, w: 0.180, h: 0.030, color: "#3182ce", labelPos: "right" },
  // F. 주소 — label right, taller box to capture 2-3 address lines
  { key: "주소",   label: "주소",     x: 0.265, y: 0.700, w: 0.250, h: 0.085, color: "#805ad5", labelPos: "right" },
];

// ── SampleBox ─────────────────────────────────────────────────────────────────

function SampleBox({ text, sampleSrc }: { text: string; sampleSrc: string }) {
  return (
    <div style={{
      minHeight: 220, padding: "0 12px",
      display: "flex", alignItems: "center", justifyContent: "space-between",
      gap: 12, background: "#F7FAFC", borderRadius: 8,
    }}>
      <span style={{ fontSize: 13, color: "#A0AEC0", flexShrink: 0 }}>{text}</span>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={sampleSrc} alt="sample" style={{
        height: 160, width: "auto", objectFit: "contain",
        borderRadius: 6, opacity: 0.55, flexShrink: 1, maxWidth: "60%",
      }} />
    </div>
  );
}

// ── WorkspaceCanvas ───────────────────────────────────────────────────────────

const WORKSPACE_H = 660;

interface GuideBox {
  key: string; label: string;
  x: number; y: number; w: number; h: number;
  color: string;
  labelPos?: "inside" | "above" | "below" | "right";
}

interface DebugOverlay {
  key: string;
  roi: ContainerRect;
}

function WorkspaceCanvas({
  preview, file, guides, sampleText, sampleSrc, stateRef, debugOverlay,
  wsMode, selectingFor, onSelectDone, customRois,
}: {
  preview: string | null;
  file: File | null;
  guides: GuideBox[];
  sampleText: string;
  sampleSrc: string;
  stateRef: React.MutableRefObject<WsState>;
  debugOverlay?: DebugOverlay | null;
  wsMode: "이동식" | "선택식";
  selectingFor: string | null;
  onSelectDone: (field: string, rect: ContainerRect) => void;
  customRois: Record<string, ContainerRect>;
}) {
  const [tf, setTf]             = useState<WsTf>(DEFAULT_TF);
  const [dragging, setDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ mx: 0, my: 0, tx: 0, ty: 0 });
  // Selection drawing state (선택식 mode)
  const [drawing, setDrawing] = useState<{ sx: number; sy: number; ex: number; ey: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef       = useRef<HTMLImageElement>(null);

  // Reset on new file
  const prevPreviewRef = useRef<string | null>(null);
  if (preview !== prevPreviewRef.current) {
    prevPreviewRef.current = preview;
    if (tf !== DEFAULT_TF) setTf(DEFAULT_TF);
  }

  const cont = containerRef.current;
  const img  = imgRef.current;
  stateRef.current = {
    tf,
    container: { w: cont?.clientWidth  ?? 1, h: cont?.clientHeight ?? 1 },
    natural:   { w: img?.naturalWidth  ?? 1, h: img?.naturalHeight ?? 1 },
  };

  const onImgLoad = () => {
    const c = containerRef.current;
    const i = imgRef.current;
    if (!c || !i || !i.naturalWidth) return;
    const scale = Math.min(c.clientWidth / i.naturalWidth, WORKSPACE_H / i.naturalHeight);
    setTf({ scale, tx: 0, ty: 0, rot: 0 });
  };

  const zoomIn   = () => setTf(p => ({ ...p, scale: Math.min(20,   p.scale * 1.25) }));
  const zoomOut  = () => setTf(p => ({ ...p, scale: Math.max(0.05, p.scale / 1.25) }));
  // Rotation reversed: CCW (−90°)
  const rotate90 = () => setTf(p => ({ ...p, rot: p.rot - 90 }));
  const reset    = () => {
    const c = containerRef.current;
    const i = imgRef.current;
    if (c && i && i.naturalWidth) {
      const scale = Math.min(c.clientWidth / i.naturalWidth, WORKSPACE_H / i.naturalHeight);
      setTf({ scale, tx: 0, ty: 0, rot: 0 });
    } else {
      setTf(DEFAULT_TF);
    }
  };

  const getContainerNorm = (clientX: number, clientY: number) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return { nx: 0, ny: 0 };
    return {
      nx: (clientX - rect.left) / rect.width,
      ny: (clientY - rect.top)  / rect.height,
    };
  };

  const onMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    if (selectingFor !== null) {
      const { nx, ny } = getContainerNorm(e.clientX, e.clientY);
      setDrawing({ sx: nx, sy: ny, ex: nx, ey: ny });
    } else {
      setDragging(true);
      setDragStart({ mx: e.clientX, my: e.clientY, tx: tf.tx, ty: tf.ty });
    }
  };

  const onMouseMove = (e: React.MouseEvent) => {
    if (drawing !== null) {
      const { nx, ny } = getContainerNorm(e.clientX, e.clientY);
      setDrawing(d => d ? { ...d, ex: nx, ey: ny } : null);
    } else if (dragging) {
      setTf(p => ({
        ...p,
        tx: dragStart.tx + (e.clientX - dragStart.mx),
        ty: dragStart.ty + (e.clientY - dragStart.my),
      }));
    }
  };

  const onMouseUp = (e: React.MouseEvent) => {
    if (drawing !== null && selectingFor !== null) {
      const { nx, ny } = getContainerNorm(e.clientX, e.clientY);
      const x = Math.min(drawing.sx, nx);
      const y = Math.min(drawing.sy, ny);
      const w = Math.max(0.01, Math.abs(nx - drawing.sx));
      const h = Math.max(0.01, Math.abs(ny - drawing.sy));
      onSelectDone(selectingFor, { x, y, w, h });
      setDrawing(null);
    }
    setDragging(false);
  };

  const stopAll = () => { setDragging(false); setDrawing(null); };

  if (!preview || !file) return <SampleBox text={sampleText} sampleSrc={sampleSrc} />;

  const rot = ((tf.rot % 360) + 360) % 360;
  const isSelecting = selectingFor !== null;
  const cursor = isSelecting ? "crosshair" : (dragging ? "grabbing" : "grab");

  // Label rendering by position
  const renderLabel = (box: GuideBox) => {
    const pos = box.labelPos ?? "inside";
    const base: React.CSSProperties = {
      position: "absolute",
      fontSize: 10, fontWeight: 700, color: box.color,
      background: "rgba(0,0,0,0.75)",
      padding: "1px 5px", borderRadius: 3, lineHeight: 1.5,
      whiteSpace: "nowrap", pointerEvents: "none",
    };
    if (pos === "above")  return <span style={{ ...base, bottom: "calc(100% + 2px)", left: 0 }}>{box.label}</span>;
    if (pos === "below")  return <span style={{ ...base, top: "calc(100% + 2px)", left: 0 }}>{box.label}</span>;
    if (pos === "right")  return <span style={{ ...base, left: "calc(100% + 4px)", top: "50%", transform: "translateY(-50%)" }}>{box.label}</span>;
    return <span style={{ ...base, top: 2, left: 4 }}>{box.label}</span>;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {/* Toolbar */}
      <div style={{ display: "flex", gap: 6, justifyContent: "space-between", alignItems: "center" }}>
        <div>
          {isSelecting && (
            <span style={{
              fontSize: 11, color: "#3182ce", fontWeight: 600,
              background: "#ebf8ff", padding: "2px 8px", borderRadius: 4,
            }}>
              ✏️ {guides.find(g => g.key === selectingFor)?.label ?? selectingFor} 영역 드래그 선택 중
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button type="button" onClick={zoomIn}   style={smallToolBtnStyle}>확대 +</button>
          <button type="button" onClick={zoomOut}  style={smallToolBtnStyle}>축소 −</button>
          <button type="button" onClick={rotate90} style={smallToolBtnStyle}>90° 회전</button>
          <button type="button" onClick={reset}    style={smallToolBtnStyle}>원위치</button>
        </div>
      </div>

      {/* Viewport */}
      <div
        ref={containerRef}
        style={{
          position: "relative", width: "100%", height: WORKSPACE_H,
          overflow: "hidden", background: "#1a202c", borderRadius: 8,
          border: `1px solid ${isSelecting ? "#3182ce" : "#4A5568"}`,
          cursor, userSelect: "none", touchAction: "none",
        }}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={stopAll}
      >
        {/* Image layer */}
        <div style={{
          position: "absolute", top: "50%", left: "50%",
          transform: `translate(-50%, -50%) translate(${tf.tx}px, ${tf.ty}px) rotate(${rot}deg) scale(${tf.scale})`,
          transformOrigin: "center center", pointerEvents: "none",
        }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img ref={imgRef} src={preview} alt="preview" draggable={false} onLoad={onImgLoad} style={{ display: "block", maxWidth: "none" }} />
        </div>

        {/* Fixed overlay layer */}
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, pointerEvents: "none" }}>
          {/* Guide boxes — hidden in 선택식 mode (user draws their own areas) */}
          {wsMode !== "선택식" && guides.map((box) => (
            <div
              key={box.key}
              style={{
                position: "absolute",
                left: `${box.x * 100}%`, top: `${box.y * 100}%`,
                width: `${box.w * 100}%`, height: `${box.h * 100}%`,
                border: `2px dashed ${box.color}`,
                boxSizing: "border-box",
                background: `${box.color}20`,
              }}
            >
              {renderLabel(box)}
            </div>
          ))}

          {/* Completed selection ROIs — shown until the user re-selects that field.
               Re-clicking "영역선택" deletes customRois[key] before drawing starts,
               so the old box naturally disappears at that moment. */}
          {wsMode === "선택식" && Object.entries(customRois).map(([key, roi]) => {
            const label = guides.find(g => g.key === key)?.label ?? key;
            return (
              <div key={`sel-${key}`} style={{
                position: "absolute",
                left: `${roi.x * 100}%`, top: `${roi.y * 100}%`,
                width: `${roi.w * 100}%`, height: `${roi.h * 100}%`,
                border: "2px solid #FFD700",
                boxSizing: "border-box",
                background: "rgba(255, 215, 0, 0.18)",
              }}>
                {/* Label above the box — never covers OCR content */}
                <span style={{
                  position: "absolute",
                  bottom: "calc(100% + 2px)", left: 0,
                  fontSize: 10, fontWeight: 700, color: "#B7791F",
                  background: "rgba(0,0,0,0.75)",
                  padding: "1px 5px", borderRadius: 3, lineHeight: 1.5,
                  whiteSpace: "nowrap", pointerEvents: "none",
                }}>
                  {label} ✓
                </span>
              </div>
            );
          })}

          {/* Active drawing rect */}
          {drawing && (
            <div style={{
              position: "absolute",
              left: `${Math.min(drawing.sx, drawing.ex) * 100}%`,
              top:  `${Math.min(drawing.sy, drawing.ey) * 100}%`,
              width: `${Math.abs(drawing.ex - drawing.sx) * 100}%`,
              height: `${Math.abs(drawing.ey - drawing.sy) * 100}%`,
              border: "2px solid #FFD700",
              boxSizing: "border-box",
              background: "rgba(255, 215, 0, 0.25)",
            }} />
          )}

          {/* Debug ROI overlay — only in 이동식 mode */}
          {debugOverlay && wsMode !== "선택식" && (() => {
            const b = roiToContainerBox(debugOverlay.roi, stateRef.current.container, stateRef.current.natural, tf);
            return (
              <div style={{
                position: "absolute", left: b.left, top: b.top,
                width: b.width, height: b.height,
                border: "2px solid #00e5ff", boxSizing: "border-box",
                background: "rgba(0, 229, 255, 0.18)", pointerEvents: "none",
              }}>
                <span style={{
                  position: "absolute", bottom: 2, left: 4,
                  fontSize: 10, fontWeight: 700, color: "#00e5ff",
                  background: "rgba(0,0,0,0.80)", padding: "1px 5px", borderRadius: 3,
                  lineHeight: 1.5, whiteSpace: "nowrap",
                }}>실제 OCR 영역</span>
              </div>
            );
          })()}
        </div>
      </div>

      <div style={{ fontSize: 11, color: "#718096", textAlign: "center" }}>
        {wsMode === "이동식"
          ? "드래그로 이동 · 버튼으로 확대/축소/회전 · 이미지를 가이드 박스에 맞춰주세요"
          : "추출영역 선택 후 드래그로 영역 지정 · 이동식 버튼으로 전환하면 이미지 이동 가능"}
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function birthToRegFront(birth: string): string {
  const d = birth.replace(/[-./]/g, "");
  if (d.length === 8) return d.slice(2, 8);
  return "";
}

// ── Full debug chain types ────────────────────────────────────────────────────

interface CalcChain {
  guide: { key: string; label: string; x: number; y: number; w: number; h: number };
  container: WsSize;
  natural: WsSize;
  tf: WsTf;
  rot: number;
  dispW: number; dispH: number;
  imgLeft: number; imgTop: number;
  relL: number; relT: number; relW: number; relH: number;
  sentRoi: ContainerRect;
}

interface BackendDebug {
  crop_preview_base64?: string;
  prep_preview_base64?: string;
  raw_ocr_text?: string;
  ocr_attempts?: Array<{ lang: string; psm: string; text: string }>;
  mrz_candidates?: { L1: string; L2: string; score: number; found: boolean };
  parse_result?: Record<string, string> | null;
  normalized_text?: string;
  failure_reason?: string;
}

interface FullDebug {
  calc: CalcChain;
  backend: BackendDebug;
  fieldKey?: string;
}

function buildCalcChain(
  guide: { key: string; label: string; x: number; y: number; w: number; h: number },
  container: WsSize,
  natural: WsSize,
  tf: WsTf,
  sentRoi: ContainerRect,
): CalcChain {
  const { scale, tx, ty } = tf;
  const rot = ((tf.rot % 360) + 360) % 360;
  const { w: cW, h: cH } = container;
  const dispW = (rot === 90 || rot === 270) ? natural.h * scale : natural.w * scale;
  const dispH = (rot === 90 || rot === 270) ? natural.w * scale : natural.h * scale;
  const imgLeft = cW / 2 + tx - dispW / 2;
  const imgTop  = cH / 2 + ty - dispH / 2;
  const relL = guide.x * cW - imgLeft;
  const relT = guide.y * cH - imgTop;
  const relW = guide.w * cW;
  const relH = guide.h * cH;
  return {
    guide: { key: guide.key, label: guide.label, x: guide.x, y: guide.y, w: guide.w, h: guide.h },
    container, natural, tf, rot, dispW, dispH, imgLeft, imgTop, relL, relT, relW, relH, sentRoi,
  };
}

function DebugPanel({ debug, title }: { debug: FullDebug; title: string }) {
  const { calc, backend } = debug;
  const f4 = (n: number) => n.toFixed(4);
  const f1 = (n: number) => n.toFixed(1);
  const lc = "#8b949e", vc = "#e6edf3", cc = "#79c0ff", gc = "#3fb950", rc = "#f85149", yc = "#e3b341";
  const sec: React.CSSProperties = { borderBottom: "1px solid #21262d", paddingBottom: 8, marginBottom: 8 };

  return (
    <div style={{ marginTop: 8, padding: "10px 12px", background: "#0d1117", borderRadius: 8, border: "1px solid #30363d", fontSize: 11, fontFamily: "monospace" }}>
      <div style={{ color: cc, fontWeight: 700, marginBottom: 8 }}>🔍 Debug: {title}</div>

      <div style={sec}>
        <div style={{ color: lc, marginBottom: 4 }}>ROI 계산 과정</div>
        <div style={{ color: vc, lineHeight: 1.9 }}>
          <span style={{ color: lc }}>guide&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span>
          {calc.guide.key} x={f4(calc.guide.x)} y={f4(calc.guide.y)} w={f4(calc.guide.w)} h={f4(calc.guide.h)}<br />
          <span style={{ color: lc }}>container&nbsp;</span>{f1(calc.container.w)} × {f1(calc.container.h)} px<br />
          <span style={{ color: lc }}>natural&nbsp;&nbsp;&nbsp;</span>{calc.natural.w} × {calc.natural.h} px<br />
          <span style={{ color: lc }}>transform&nbsp;</span>scale={f4(calc.tf.scale)} tx={f1(calc.tf.tx)} ty={f1(calc.tf.ty)} rot={calc.rot}°<br />
          <span style={{ color: lc }}>dispW×H&nbsp;&nbsp;&nbsp;</span>{f1(calc.dispW)} × {f1(calc.dispH)} px<br />
          <span style={{ color: lc }}>imgTopLeft </span>({f1(calc.imgLeft)}, {f1(calc.imgTop)}) px<br />
          <span style={{ color: lc }}>relBox&nbsp;&nbsp;&nbsp;&nbsp;</span>L={f1(calc.relL)} T={f1(calc.relT)} W={f1(calc.relW)} H={f1(calc.relH)} px<br />
          <span style={{ color: yc }}>→ sent ROI </span>
          x={f4(calc.sentRoi.x)} y={f4(calc.sentRoi.y)} w={f4(calc.sentRoi.w)} h={f4(calc.sentRoi.h)}
        </div>
      </div>

      <div style={{ ...sec, display: "flex", gap: 10, alignItems: "flex-start" }}>
        <div style={{ flexShrink: 0 }}>
          <div style={{ color: lc, marginBottom: 4 }}>크롭 원본</div>
          {backend.crop_preview_base64 ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={backend.crop_preview_base64} alt="crop" style={{ maxWidth: 180, maxHeight: 110, display: "block", border: "1px solid #30363d", borderRadius: 4, marginBottom: 4 }} />
          ) : <span style={{ color: rc }}>없음</span>}
          {backend.prep_preview_base64 && (
            <>
              <div style={{ color: lc, marginBottom: 4 }}>OCR 입력 (전처리후)</div>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={backend.prep_preview_base64} alt="prep" style={{ maxWidth: 180, maxHeight: 110, display: "block", border: "1px solid #555", borderRadius: 4 }} />
            </>
          )}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: lc, marginBottom: 4 }}>Raw OCR Text</div>
          <textarea readOnly value={backend.raw_ocr_text || "(비어있음)"} style={{ width: "100%", boxSizing: "border-box", height: 100, padding: "4px 6px", background: "#161b22", color: yc, border: "1px solid #30363d", borderRadius: 4, fontSize: 10, fontFamily: "monospace", resize: "none" }} />
        </div>
      </div>

      {backend.ocr_attempts && backend.ocr_attempts.length > 0 && (
        <div style={sec}>
          <div style={{ color: lc, marginBottom: 4 }}>OCR 시도 ({backend.ocr_attempts.length}회)</div>
          {backend.ocr_attempts.map((a, i) => (
            <div key={i} style={{ marginBottom: 3 }}>
              <span style={{ color: cc }}>[{a.lang}/{a.psm}]</span>{" "}
              <span style={{ color: a.text ? vc : rc }}>{a.text || "(없음)"}</span>
            </div>
          ))}
        </div>
      )}

      {backend.mrz_candidates && (
        <div style={sec}>
          <div style={{ color: lc, marginBottom: 4 }}>MRZ 후보</div>
          {backend.mrz_candidates.found ? (
            <div style={{ color: vc, lineHeight: 1.8 }}>
              <span style={{ color: gc }}>✓ 발견</span>{" score="}{backend.mrz_candidates.score}<br />
              <span style={{ color: lc }}>L1: </span>{backend.mrz_candidates.L1 || "(없음)"}<br />
              <span style={{ color: lc }}>L2: </span>{backend.mrz_candidates.L2 || "(없음)"}
            </div>
          ) : <span style={{ color: rc }}>✗ 유효한 MRZ 쌍 없음</span>}
        </div>
      )}

      {backend.parse_result && (
        <div style={sec}>
          <div style={{ color: lc, marginBottom: 4 }}>파싱 결과</div>
          <div style={{ color: vc, lineHeight: 1.8 }}>
            {Object.entries(backend.parse_result).map(([k, v]) => (
              <span key={k}><span style={{ color: lc }}>{k}: </span>{v || "(없음)"}{"　"}</span>
            ))}
          </div>
        </div>
      )}

      {backend.normalized_text !== undefined && (
        <div style={sec}>
          <div style={{ color: lc, marginBottom: 4 }}>정규화 결과</div>
          <span style={{ color: backend.normalized_text ? gc : rc }}>{backend.normalized_text || "(없음)"}</span>
        </div>
      )}

      {backend.failure_reason && (
        <div><span style={{ color: rc }}>✗ 실패 원인: </span><span style={{ color: vc }}>{backend.failure_reason}</span></div>
      )}
    </div>
  );
}

// ── ScanPage ──────────────────────────────────────────────────────────────────

export default function ScanPage() {
  const qc = useQueryClient();

  const passportInputRef = useRef<HTMLInputElement>(null);
  const arcInputRef      = useRef<HTMLInputElement>(null);

  const [passportFile, setPassportFile]       = useState<File | null>(null);
  const [passportPreview, setPassportPreview] = useState<string | null>(null);
  const [arcFile, setArcFile]                 = useState<File | null>(null);
  const [arcPreview, setArcPreview]           = useState<string | null>(null);

  const [passportLoading, setPassportLoading]   = useState(false);
  const [arcLoadingField, setArcLoadingField]   = useState<ArcFieldKey | null>(null);

  // Debug state
  const [debugMode, setDebugMode]         = useState(false);
  const [passportDebug, setPassportDebug] = useState<FullDebug | null>(null);
  const [arcDebug, setArcDebug]           = useState<FullDebug | null>(null);

  // Mode and selection state
  const [wsMode, setWsMode]               = useState<"이동식" | "선택식">("이동식");
  const [activeSelection, setActiveSelection] = useState<{ ws: "passport" | "arc"; field: string } | null>(null);
  const [passportCustomRois, setPassportCustomRois] = useState<Record<string, ContainerRect>>({});
  const [arcCustomRois, setArcCustomRois]           = useState<Record<string, ContainerRect>>({});

  // Workspace state refs
  const passportWsRef = useRef<WsState>({ tf: DEFAULT_TF, container: { w: 1, h: 1 }, natural: { w: 1, h: 1 } });
  const arcWsRef      = useRef<WsState>({ tf: DEFAULT_TF, container: { w: 1, h: 1 }, natural: { w: 1, h: 1 } });

  // Field values
  const [성, set성]       = useState("");
  const [명, set명]       = useState("");
  const [국적, set국적]   = useState("");
  const [성별, set성별]   = useState("");
  const [여권, set여권]   = useState("");
  const [여권발급, set여권발급] = useState("");
  const [여권만기, set여권만기] = useState("");

  const [한글, set한글]   = useState("");
  const [등록증, set등록증] = useState("");
  const [번호, set번호]   = useState("");
  const [발급일, set발급일] = useState("");
  const [만기일, set만기일] = useState("");
  const [주소, set주소]   = useState("");

  const [연, set연] = useState("010");
  const [락, set락] = useState("");
  const [처, set처] = useState("");
  const [V, setV]   = useState("");

  const setArcFieldValue = (field: ArcFieldKey, value: string) => {
    switch (field) {
      case "한글":   set한글(value);   break;
      case "등록증": set등록증(value); break;
      case "번호":   set번호(value);   break;
      case "발급일": set발급일(value); break;
      case "만기일": set만기일(value); break;
      case "주소":   set주소(value);   break;
    }
  };

  const convertPdfToImage = async (f: File): Promise<File> => {
    const formData = new FormData();
    formData.append("file", f);
    formData.append("page", "0");
    formData.append("dpi", "200");
    const res = await api.post("/api/scan-workspace/render-pdf", formData, {
      responseType: "blob",
      headers: { "Content-Type": "multipart/form-data" },
    });
    const blob = res.data as Blob;
    return new File([blob], f.name.replace(/\.pdf$/i, ".png"), { type: "image/png" });
  };

  const handlePassportFile = async (f: File) => {
    if (f.type === "application/pdf") {
      toast.loading("PDF 변환 중...", { id: "pdf-convert" });
      try {
        const img = await convertPdfToImage(f);
        toast.dismiss("pdf-convert");
        setPassportFile(img);
        setPassportPreview(URL.createObjectURL(img));
      } catch {
        toast.dismiss("pdf-convert");
        toast.error("PDF 변환 실패");
      }
      return;
    }
    setPassportFile(f);
    setPassportPreview(URL.createObjectURL(f));
  };
  const handleArcFile = async (f: File) => {
    if (f.type === "application/pdf") {
      toast.loading("PDF 변환 중...", { id: "pdf-convert" });
      try {
        const img = await convertPdfToImage(f);
        toast.dismiss("pdf-convert");
        setArcFile(img);
        setArcPreview(URL.createObjectURL(img));
      } catch {
        toast.dismiss("pdf-convert");
        toast.error("PDF 변환 실패");
      }
      return;
    }
    setArcFile(f);
    setArcPreview(URL.createObjectURL(f));
  };

  // Selection complete callbacks
  const onPassportSelectDone = (field: string, rect: ContainerRect) => {
    setPassportCustomRois(p => ({ ...p, [field]: rect }));
    setActiveSelection(null);
  };
  const onArcSelectDone = (field: string, rect: ContainerRect) => {
    setArcCustomRois(p => ({ ...p, [field]: rect }));
    setActiveSelection(null);
  };

  // ── OCR handlers ──────────────────────────────────────────────────────────

  const runPassportWorkspaceOcr = async () => {
    if (!passportFile) { toast.error("여권 파일을 먼저 올려주세요."); return; }
    setPassportLoading(true);
    try {
      const { tf, container, natural } = passportWsRef.current;
      // Use custom roi if drawn in 선택식 mode, else guide box
      const effectiveGuide = passportCustomRois["mrz"]
        ? { key: "mrz", label: "MRZ", ...passportCustomRois["mrz"] }
        : PASSPORT_MRZ_GUIDE;
      const roi = computeRoi(effectiveGuide, container, natural, tf);
      const calcChain = buildCalcChain(effectiveGuide, container, natural, tf, roi);

      const rot = ((tf.rot % 360) + 360) % 360;
      const formData = new FormData();
      formData.append("file", passportFile);
      formData.append("roi_json", JSON.stringify(roi));
      formData.append("rotation_deg", String(rot));

      const res = await api.post("/api/scan-workspace/passport", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const backendDebug: BackendDebug = (res.data as any)?.debug ?? {};
      setPassportDebug({ calc: calcChain, backend: backendDebug });
      const d: PassportOcr = (res.data as any)?.result ?? {};
      if (d.error) { toast.error(d.error); return; }

      set성(d.성 ?? "");
      set명(d.명 ?? "");
      set국적(d.국적 || d.국가 || "");
      set성별(d.성별 ?? "");
      set여권(d.여권 ?? "");
      set여권발급(d.발급 ?? "");
      set여권만기(d.만기 ?? "");

      if (d.생년월일) {
        const reg = birthToRegFront(d.생년월일);
        if (reg) set등록증(prev => prev || reg);
      }
      toast.success("MRZ 추출 완료");
    } catch (err: unknown) {
      toast.error(
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "여권 OCR 오류",
      );
    } finally {
      setPassportLoading(false);
    }
  };

  const runArcFieldOcr = async (field: ArcFieldKey) => {
    if (!arcFile) { toast.error("등록증 파일을 먼저 올려주세요."); return; }
    setArcLoadingField(field);
    try {
      const { tf, container, natural } = arcWsRef.current;
      // Use custom roi if drawn, else guide box
      const customRect = arcCustomRois[field];
      const guide = ARC_GUIDE_BOXES.find(b => b.key === field);
      const effectiveGuide = customRect
        ? { key: field, label: ARC_FIELD_LABELS[field], ...customRect }
        : (guide ?? { key: field, label: field, x: 0, y: 0, w: 1, h: 1, color: "" });
      const roi = computeRoi(effectiveGuide, container, natural, tf);
      const calcChain = buildCalcChain(effectiveGuide, container, natural, tf, roi);

      const rot = ((tf.rot % 360) + 360) % 360;
      const formData = new FormData();
      formData.append("file", arcFile);
      formData.append("field", field);
      formData.append("roi_json", JSON.stringify(roi));
      formData.append("rotation_deg", String(rot));

      const res = await api.post("/api/scan-workspace/arc", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const backendDebug: BackendDebug = (res.data as any)?.debug ?? {};
      setArcDebug({ calc: calcChain, backend: backendDebug, fieldKey: field });

      const resultField = ((res.data as any)?.field || field) as ArcFieldKey;
      const value = String((res.data as any)?.value ?? "");
      if (!value) {
        // Clear field to make failure obvious — do not leave stale old value
        setArcFieldValue(field, "");
        toast.error(`${ARC_FIELD_LABELS[field]} 추출 결과가 없습니다.`);
        return;
      }
      setArcFieldValue(resultField, value);
      toast.success(`${ARC_FIELD_LABELS[resultField]} 추출 완료`);
    } catch (err: unknown) {
      toast.error(
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "등록증 OCR 오류",
      );
    } finally {
      setArcLoadingField(null);
    }
  };

  // ── Reset ─────────────────────────────────────────────────────────────────

  const resetAll = () => {
    setPassportFile(null); setPassportPreview(null);
    setArcFile(null); setArcPreview(null);
    set성(""); set명(""); set국적(""); set성별("");
    set여권(""); set여권발급(""); set여권만기("");
    set한글(""); set등록증(""); set번호("");
    set발급일(""); set만기일(""); set주소("");
    set연("010"); set락(""); set처(""); setV("");
    setPassportDebug(null); setArcDebug(null);
    setPassportCustomRois({}); setArcCustomRois({});
    setActiveSelection(null);
    if (passportInputRef.current) passportInputRef.current.value = "";
    if (arcInputRef.current) arcInputRef.current.value = "";
  };

  // ── Register mutation ─────────────────────────────────────────────────────

  const registerMut = useMutation({
    mutationFn: (data: Record<string, string>) => api.post("/api/scan/register", data),
    onSuccess: (res) => {
      const { status, message } = res.data as { status: string; message: string };
      toast.success(status === "updated" ? `✅ ${message}` : `🆕 ${message}`);
      qc.invalidateQueries({ queryKey: ["customers"] });
      resetAll();
    },
    onError: () => toast.error("고객 등록/업데이트 실패"),
  });

  const handleSubmit = () => {
    const data: Record<string, string> = {
      성: 성.trim(), 명: 명.trim(), 국적: 국적.trim(), 성별: 성별.trim(),
      여권: 여권.trim(), 발급: 여권발급.trim(), 만기: 여권만기.trim(),
      한글: 한글.trim(), 등록증: 등록증.trim(), 번호: 번호.trim(),
      발급일: 발급일.trim(), 만기일: 만기일.trim(), 주소: 주소.trim(),
      연: 연.trim(), 락: 락.trim(), 처: 처.trim(), V: V.trim(),
    };
    registerMut.mutate(data);
  };

  // ── Render helpers ────────────────────────────────────────────────────────

  const dropZoneStyle = (hasFile: boolean): React.CSSProperties => ({
    border: `2px dashed ${hasFile ? "var(--hw-gold)" : "#CBD5E0"}`,
    borderRadius: 8, padding: "10px 14px", cursor: "pointer",
    background: "#fff", minHeight: 52,
    display: "flex", alignItems: "center", justifyContent: "flex-start",
  });

  const arcFieldRows: { key: ArcFieldKey; value: string; onChange: (v: string) => void }[] = [
    { key: "한글",   value: 한글,  onChange: set한글 },
    { key: "등록증", value: 등록증, onChange: set등록증 },
    { key: "번호",   value: 번호,  onChange: set번호 },
    { key: "발급일", value: 발급일, onChange: set발급일 },
    { key: "만기일", value: 만기일, onChange: set만기일 },
    { key: "주소",   value: 주소,  onChange: set주소 },
  ];

  const passportSelectingFor = activeSelection?.ws === "passport" ? activeSelection.field : null;
  const arcSelectingFor      = activeSelection?.ws === "arc"      ? activeSelection.field : null;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <ScanLine size={18} style={{ color: "var(--hw-gold)" }} />
          <h1 className="hw-page-title">반자동 OCR 작업판</h1>
        </div>

        {/* Mode tabs */}
        <div style={{ display: "flex", gap: 0, borderRadius: 7, overflow: "hidden", border: "1px solid #CBD5E0" }}>
          {(["이동식", "선택식"] as const).map(mode => (
            <button
              key={mode}
              type="button"
              onClick={() => { setWsMode(mode); setActiveSelection(null); }}
              style={{
                height: 30, padding: "0 14px", fontSize: 12, fontWeight: 600,
                cursor: "pointer", border: "none",
                background: wsMode === mode ? "#4A5568" : "#F7FAFC",
                color:      wsMode === mode ? "#fff"    : "#718096",
              }}
            >
              {mode}
            </button>
          ))}
        </div>

        {/* Debug checkbox */}
        <label style={{
          display: "flex", alignItems: "center", gap: 6,
          fontSize: 12, color: debugMode ? "#00b4c8" : "#718096",
          fontWeight: debugMode ? 600 : 400, cursor: "pointer", whiteSpace: "nowrap",
        }}>
          <input type="checkbox" checked={debugMode} onChange={(e) => setDebugMode(e.target.checked)} />
          실제 추출 영역 보기
        </label>
      </div>

      <p style={{ fontSize: 13, color: "#718096", margin: 0 }}>
        {wsMode === "이동식"
          ? "이미지를 드래그·확대해 가이드 박스에 맞춘 뒤, 원하는 필드의 추출 버튼을 누르세요."
          : "추출영역 선택 버튼을 누른 뒤 이미지 위에서 드래그로 추출 영역을 지정하세요."}
      </p>

      {/* ── Row 1: 여권 작업판 + 여권 결과 (vertically centered) ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1.25fr 0.95fr", gap: 16, alignItems: "center" }}>

        {/* 여권 작업판 */}
        <div style={cardStyle}>
          <div style={sectionTitleStyle}>여권 작업판</div>
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: "#4A5568" }}>여권 이미지 업로드</div>
            <div
              style={dropZoneStyle(!!passportFile)}
              onClick={() => passportInputRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) handlePassportFile(f); }}
            >
              <input ref={passportInputRef} type="file" accept="image/*,.pdf" style={{ display: "none" }}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) handlePassportFile(f); }} />
              {passportFile
                ? <span style={{ fontSize: 12, color: "var(--hw-gold)", fontWeight: 600 }}>✅ {passportFile.name}</span>
                : <span style={{ fontSize: 12, color: "#718096", display: "flex", alignItems: "center", gap: 4 }}><Upload size={13} style={{ flexShrink: 0 }} />여권 이미지를 업로드 하세요.</span>}
            </div>
          </div>

          <WorkspaceCanvas
            preview={passportPreview} file={passportFile}
            guides={[PASSPORT_MRZ_GUIDE]}
            sampleText="여권 이미지 예시 (업로드 필수)" sampleSrc="/passport-sample.jpg"
            stateRef={passportWsRef}
            debugOverlay={debugMode && passportDebug?.calc ? { key: "mrz", roi: passportDebug.calc.sentRoi } : null}
            wsMode={wsMode}
            selectingFor={passportSelectingFor}
            onSelectDone={onPassportSelectDone}
            customRois={passportCustomRois}
          />
          {debugMode && passportDebug && <DebugPanel debug={passportDebug} title="여권 MRZ" />}

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 12 }}>
            {wsMode === "선택식" && (
              <button
                type="button"
                onClick={() => {
                  if (passportSelectingFor === "mrz") setActiveSelection(null);
                  else {
                    setPassportCustomRois({});
                    setActiveSelection({ ws: "passport", field: "mrz" });
                  }
                }}
                style={passportSelectingFor === "mrz" ? selActiveBtnStyle : selBtnStyle}
              >
                {passportSelectingFor === "mrz" ? "선택 취소" : "추출영역 선택"}
              </button>
            )}
            {passportCustomRois["mrz"] && wsMode === "선택식" && (
              <button type="button" onClick={() => setPassportCustomRois(p => { const n = { ...p }; delete n["mrz"]; return n; })} style={{ ...smallToolBtnStyle, fontSize: 11 }}>
                선택 초기화
              </button>
            )}
            <button
              onClick={runPassportWorkspaceOcr}
              disabled={!passportFile || passportLoading}
              style={!passportFile || passportLoading ? disabledBtnStyle : smallBtnStyle}
            >
              {passportLoading ? "추출 중..." : "MRZ 추출"}
            </button>
          </div>
        </div>

        {/* 여권 결과 */}
        <div style={{ ...cardStyle, borderLeft: "3px solid #D69E2E" }}>
          <div style={sectionTitleStyle}>여권 결과</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div>
              <label style={labelStyle}>성(영문)</label>
              <input style={inputStyle} value={성} onChange={(e) => set성(e.target.value)} />
            </div>
            <div>
              <label style={labelStyle}>명(영문)</label>
              <input style={inputStyle} value={명} onChange={(e) => set명(e.target.value)} />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <div>
                <label style={labelStyle}>국적(3자리)</label>
                <input style={inputStyle} value={국적} onChange={(e) => set국적(e.target.value)} />
              </div>
              <div>
                <label style={labelStyle}>성별</label>
                <select style={inputStyle} value={성별} onChange={(e) => set성별(e.target.value)}>
                  <option value="">-</option>
                  <option value="남">남</option>
                  <option value="여">여</option>
                </select>
              </div>
            </div>
            <div>
              <label style={labelStyle}>여권번호</label>
              <input style={inputStyle} value={여권} onChange={(e) => set여권(e.target.value)} />
            </div>
            <div>
              <label style={labelStyle}>여권 발급일 (YYYY-MM-DD)</label>
              <input style={inputStyle} value={여권발급} onChange={(e) => set여권발급(e.target.value)} />
              <span style={{ fontSize: 10, color: "#A0AEC0", display: "block", marginTop: 2 }}>
                국가별 정책이 다를 수 있으니 원본과 다르면 직접 수정하세요
              </span>
            </div>
            <div>
              <label style={labelStyle}>여권 만기일 (YYYY-MM-DD)</label>
              <input style={inputStyle} value={여권만기} onChange={(e) => set여권만기(e.target.value)} />
            </div>
          </div>
        </div>
      </div>

      {/* ── Row 2: 등록증 작업판 + (등록증 결과 + 연락처/비고 + 버튼) ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1.25fr 0.95fr", gap: 16, alignItems: "center" }}>

        {/* 등록증 작업판 */}
        <div style={cardStyle}>
          <div style={sectionTitleStyle}>등록증 작업판</div>
          <div style={{ marginBottom: 10 }}>
            <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: "#4A5568" }}>등록증/스티커 이미지 업로드</div>
            <div
              style={dropZoneStyle(!!arcFile)}
              onClick={() => arcInputRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) handleArcFile(f); }}
            >
              <input ref={arcInputRef} type="file" accept="image/*,.pdf" style={{ display: "none" }}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) handleArcFile(f); }} />
              {arcFile
                ? <span style={{ fontSize: 12, color: "var(--hw-gold)", fontWeight: 600 }}>✅ {arcFile.name}</span>
                : <span style={{ fontSize: 12, color: "#718096", display: "flex", alignItems: "center", gap: 4 }}><Upload size={13} style={{ flexShrink: 0 }} />등록증 이미지를 업로드 하세요.</span>}
            </div>
          </div>

          <WorkspaceCanvas
            preview={arcPreview} file={arcFile}
            guides={ARC_GUIDE_BOXES}
            sampleText="등록증 이미지 예시 (업로드 선택)" sampleSrc="/arc-sample.jpg"
            stateRef={arcWsRef}
            debugOverlay={debugMode && arcDebug?.calc ? { key: arcDebug.fieldKey ?? "", roi: arcDebug.calc.sentRoi } : null}
            wsMode={wsMode}
            selectingFor={arcSelectingFor}
            onSelectDone={onArcSelectDone}
            customRois={arcCustomRois}
          />
          {debugMode && arcDebug && <DebugPanel debug={arcDebug} title={`등록증 ${arcDebug.fieldKey ?? ""}`} />}

          <div style={{ fontSize: 12, color: "#718096", marginTop: 10 }}>
            앞면: 등록증 앞·뒤·한글 가이드에 맞춰주세요.
            뒷면(스티커): 90° 회전 후 발급일·만기일·주소 가이드에 맞춰주세요.
          </div>
        </div>

        {/* 등록증 결과 + 연락처/비고 + 버튼 — stacked directly below each other */}
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

          <div style={{ ...cardStyle, borderLeft: "3px solid #3182ce" }}>
            <div style={sectionTitleStyle}>등록증 결과</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {arcFieldRows.map(({ key, value, onChange }) => {
                const loading = arcLoadingField === key;
                const isActiveSelect = arcSelectingFor === key;
                return (
                  <div key={key}>
                    <label style={labelStyle}>{ARC_FIELD_LABELS[key]}</label>
                    <div style={{
                      display: "grid",
                      gridTemplateColumns: wsMode === "선택식" ? "1fr auto auto" : "1fr auto",
                      gap: 6, alignItems: "center",
                    }}>
                      <input
                        style={{
                          ...inputStyle,
                          border: `1px solid ${value === "" && arcDebug?.fieldKey === key ? "#FC8181" : "#CBD5E0"}`,
                        }}
                        value={value}
                        onChange={(e) => onChange(e.target.value)}
                      />
                      {wsMode === "선택식" && (
                        <button
                          type="button"
                          onClick={() => {
                            if (isActiveSelect) setActiveSelection(null);
                            else {
                              setArcCustomRois({});
                              setActiveSelection({ ws: "arc", field: key });
                            }
                          }}
                          style={isActiveSelect ? selActiveBtnStyle : selBtnStyle}
                        >
                          {isActiveSelect ? "취소" : "영역선택"}
                        </button>
                      )}
                      <button
                        onClick={() => runArcFieldOcr(key)}
                        disabled={!arcFile || arcLoadingField !== null}
                        style={!arcFile || arcLoadingField !== null ? disabledBtnStyle : smallBtnStyle}
                      >
                        {loading ? "추출 중..." : "추출"}
                      </button>
                    </div>
                    {wsMode === "선택식" && arcCustomRois[key] && (
                      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3 }}>
                        <span style={{ fontSize: 10, color: "#B7791F", background: "#FEFCBF", padding: "1px 6px", borderRadius: 4 }}>
                          ✓ 선택된 영역 있음
                        </span>
                        <button
                          type="button"
                          onClick={() => setArcCustomRois(p => { const n = { ...p }; delete n[key]; return n; })}
                          style={{ fontSize: 10, color: "#718096", background: "none", border: "none", cursor: "pointer", padding: 0 }}
                        >
                          초기화
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          <div style={cardStyle}>
            <div style={sectionTitleStyle}>연락처 / 비고</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 0.8fr", gap: 6 }}>
              <div>
                <label style={labelStyle}>연(앞)</label>
                <input style={inputStyle} value={연} onChange={(e) => set연(e.target.value)} />
              </div>
              <div>
                <label style={labelStyle}>락(중간)</label>
                <input style={inputStyle} value={락} onChange={(e) => set락(e.target.value)} />
              </div>
              <div>
                <label style={labelStyle}>처(끝)</label>
                <input style={inputStyle} value={처} onChange={(e) => set처(e.target.value)} />
              </div>
              <div>
                <label style={labelStyle}>V</label>
                <input style={inputStyle} value={V} onChange={(e) => setV(e.target.value)} />
              </div>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <button
              onClick={resetAll}
              style={{ height: 42, borderRadius: 8, border: "1px solid #CBD5E0", background: "#fff", color: "#4A5568", fontSize: 14, fontWeight: 600, cursor: "pointer" }}
            >
              초기화
            </button>
            <button
              onClick={handleSubmit}
              disabled={registerMut.isPending}
              className="btn-primary"
              style={{ height: 42, borderRadius: 8, fontSize: 14, fontWeight: 700, opacity: registerMut.isPending ? 0.5 : 1 }}
            >
              {registerMut.isPending ? "저장 중..." : "고객관리 반영"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
