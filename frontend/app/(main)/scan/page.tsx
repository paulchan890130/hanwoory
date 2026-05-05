"use client";

import { useRef, useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ScanLine, Upload } from "lucide-react";
import { api } from "@/lib/api";
import type { RoiPreset, RoiPresetData, RoiBox, ArcRoiBoxes } from "@/lib/types/roiPreset";
import { wsTfToTransform, transformToWsTf } from "@/lib/types/roiPreset";
import { fetchRoiPresets, saveRoiPreset, renameRoiPreset } from "@/lib/api/roiPreset";
import RoiPresetBar from "@/components/scan/RoiPresetBar";
import SignatureModal from "@/components/SignatureModal";

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
  border: "1px solid #D4A843", background: "#fffaf0", color: "#96751E",
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
const overlayBtnStyle: React.CSSProperties = {
  height: 30, minWidth: 52, padding: "0 8px", borderRadius: 5,
  border: "1px solid rgba(255,255,255,0.25)",
  background: "rgba(0,0,0,0.55)", color: "#e2e8f0",
  fontSize: 11, fontWeight: 600, cursor: "pointer",
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
  x: 0.129, y: 0.635, w: 0.693, h: 0.085,   // 좌우 5%씩 확장
  color: "#D4A843",
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
  // A. 등록증 앞 — 우로 20% 확장
  { key: "등록증", label: "등록증 앞",  x: 0.368, y: 0.174, w: 0.090, h: 0.024, color: "#dd6b20", labelPos: "above" },
  // B. 등록증 뒤 — 우로 30% 이동, 우로 30% 확장
  { key: "번호",   label: "등록증 뒤",  x: 0.478, y: 0.174, w: 0.117, h: 0.024, color: "#D4A843", labelPos: "above" },
  // C. 한글 이름 — 위로 50% 이동, 좌로 10% 이동
  { key: "한글",   label: "한글 이름",  x: 0.368, y: 0.232, w: 0.058, h: 0.018, color: "#e53e3e", labelPos: "below" },
  // D. 발급일 — 위로 10% 이동, 우로 180% 이동, 우측 80%로 축소
  { key: "발급일", label: "발급일",    x: 0.675, y: 0.336, w: 0.088, h: 0.028, color: "#38a169", labelPos: "above" },
  // E. 만기일 — 우측 60%로 축소
  { key: "만기일", label: "만기일",    x: 0.290, y: 0.665, w: 0.108, h: 0.030, color: "#3182ce", labelPos: "right" },
  // F. 주소 — 아래로 150% 이동, 높이 50% 축소, 너비 80% 축소
  { key: "주소",   label: "주소",     x: 0.265, y: 0.828, w: 0.200, h: 0.043, color: "#805ad5", labelPos: "right" },
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

// 가이드 박스 편집 모드: 8방향 리사이즈 핸들
const RESIZE_HANDLES: Array<{ id: string; cursor: string; style: React.CSSProperties }> = [
  { id: "nw", cursor: "nw-resize", style: { top: -4,               left: -4 } },
  { id: "n",  cursor: "n-resize",  style: { top: -4,               left: "calc(50% - 4px)" } },
  { id: "ne", cursor: "ne-resize", style: { top: -4,               right: -4 } },
  { id: "e",  cursor: "e-resize",  style: { top: "calc(50% - 4px)", right: -4 } },
  { id: "se", cursor: "se-resize", style: { bottom: -4,            right: -4 } },
  { id: "s",  cursor: "s-resize",  style: { bottom: -4,            left: "calc(50% - 4px)" } },
  { id: "sw", cursor: "sw-resize", style: { bottom: -4,            left: -4 } },
  { id: "w",  cursor: "w-resize",  style: { top: "calc(50% - 4px)", left: -4 } },
];

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
  externalTf, resetTrigger, onTfChange,
  editMode, onBoxChange,
  initialAlign = "center",
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
  // [프리셋] tf 외부 주입
  externalTf?: WsTf;
  resetTrigger?: number;
  onTfChange?: (tf: WsTf) => void;
  // [프리셋] 가이드 박스 편집 모드
  editMode?: boolean;
  onBoxChange?: (key: string, box: { x: number; y: number; w: number; h: number }) => void;
  // 초기 정렬: center(여권) 또는 top(등록증)
  initialAlign?: "center" | "top";
}) {
  const [tf, setTf]             = useState<WsTf>(DEFAULT_TF);
  const [dragging, setDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ mx: 0, my: 0, tx: 0, ty: 0 });
  // Selection drawing state (선택식 mode)
  const [drawing, setDrawing] = useState<{ sx: number; sy: number; ex: number; ey: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef       = useRef<HTMLImageElement>(null);

  // [프리셋] 가이드 박스 편집 드래그 state
  const [editBoxDrag, setEditBoxDrag] = useState<{
    key: string; type: "move" | "resize"; handle: string;
    startMouseX: number; startMouseY: number;
    startBox: { x: number; y: number; w: number; h: number };
  } | null>(null);
  const [editBoxLive, setEditBoxLive] = useState<{
    key: string; box: { x: number; y: number; w: number; h: number };
  } | null>(null);

  // [프리셋] resetTrigger → tf 리셋
  useEffect(() => {
    if (externalTf !== undefined && resetTrigger !== undefined) {
      setTf(externalTf);
    }
    // resetTrigger 변경 시만 실행
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetTrigger]);

  // [프리셋] tf 변경 → 부모 알림
  useEffect(() => {
    onTfChange?.(tf);
  }, [tf]); // eslint-disable-line react-hooks/exhaustive-deps

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

  const calcInitialTf = (c: HTMLDivElement, i: HTMLImageElement): WsTf => {
    const scale = c.clientWidth / i.naturalWidth;
    const ty = initialAlign === "top"
      ? (i.naturalHeight * scale) / 2 - WORKSPACE_H / 2
      : 0;
    return { scale, tx: 0, ty, rot: 0 };
  };

  const onImgLoad = () => {
    const c = containerRef.current;
    const i = imgRef.current;
    if (!c || !i || !i.naturalWidth) return;
    setTf(calcInitialTf(c, i));
  };

  const zoomIn   = () => setTf(p => ({ ...p, scale: Math.min(20,   p.scale * 1.25) }));
  const zoomOut  = () => setTf(p => ({ ...p, scale: Math.max(0.05, p.scale / 1.25) }));
  // Rotation reversed: CCW (−90°)
  const rotate90 = () => setTf(p => ({ ...p, rot: p.rot - 90 }));
  const reset    = () => {
    const c = containerRef.current;
    const i = imgRef.current;
    if (c && i && i.naturalWidth) {
      setTf(calcInitialTf(c, i));
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
    // [프리셋] 가이드 박스 편집 드래그
    if (editBoxDrag !== null && editMode) {
      const rect = containerRef.current?.getBoundingClientRect();
      if (rect) {
        const dx = (e.clientX - editBoxDrag.startMouseX) / rect.width;
        const dy = (e.clientY - editBoxDrag.startMouseY) / rect.height;
        const { x: sx, y: sy, w: sw, h: sh } = editBoxDrag.startBox;
        const MIN_W = 0.02, MIN_H = 0.01;
        let nx = sx, ny = sy, nw = sw, nh = sh;
        if (editBoxDrag.type === "move") {
          nx = Math.max(0, Math.min(1 - sw, sx + dx));
          ny = Math.max(0, Math.min(1 - sh, sy + dy));
        } else {
          const h = editBoxDrag.handle;
          const isN = h === "n"  || h === "nw" || h === "ne";
          const isS = h === "s"  || h === "sw" || h === "se";
          const isW = h === "w"  || h === "nw" || h === "sw";
          const isE = h === "e"  || h === "ne" || h === "se";
          if (isW) { nx = Math.max(0, Math.min(sx + sw - MIN_W, sx + dx)); nw = sw - (nx - sx); }
          if (isE) { nw = Math.max(MIN_W, Math.min(1 - sx, sw + dx)); }
          if (isN) { ny = Math.max(0, Math.min(sy + sh - MIN_H, sy + dy)); nh = sh - (ny - sy); }
          if (isS) { nh = Math.max(MIN_H, Math.min(1 - sy, sh + dy)); }
          nw = Math.min(1 - nx, nw); nh = Math.min(1 - ny, nh);
        }
        setEditBoxLive({ key: editBoxDrag.key, box: { x: nx, y: ny, w: nw, h: nh } });
      }
      return;
    }
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
    // [프리셋] 편집 박스 드래그 완료 → onBoxChange 콜백
    if (editBoxDrag !== null) {
      if (editBoxLive && onBoxChange) onBoxChange(editBoxLive.key, editBoxLive.box);
      setEditBoxDrag(null); setEditBoxLive(null);
      return;
    }
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

  const stopAll = () => {
    setDragging(false); setDrawing(null);
    // [프리셋] 마우스가 캔버스 밖으로 나가도 편집 결과 적용
    if (editBoxDrag !== null) {
      if (editBoxLive && onBoxChange) onBoxChange(editBoxLive.key, editBoxLive.box);
      setEditBoxDrag(null); setEditBoxLive(null);
    }
  };

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
      {/* 선택식 모드일 때만 상태 표시 */}
      {isSelecting && (
        <div>
          <span style={{
            fontSize: 11, color: "#3182ce", fontWeight: 600,
            background: "#ebf8ff", padding: "2px 8px", borderRadius: 4,
          }}>
            ✏️ {guides.find(g => g.key === selectingFor)?.label ?? selectingFor} 영역 드래그 선택 중
          </span>
        </div>
      )}

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
          {wsMode !== "선택식" && guides.map((box) => {
            // [프리셋] 편집 중인 박스는 live 위치 사용
            const live = (editBoxLive?.key === box.key) ? editBoxLive.box : box;
            const isEditable = !!editMode;
            return (
              <div
                key={box.key}
                style={{
                  position: "absolute",
                  left: `${live.x * 100}%`, top: `${live.y * 100}%`,
                  width: `${live.w * 100}%`, height: `${live.h * 100}%`,
                  border: `${isEditable ? "2.5px solid" : "2px dashed"} ${box.color}`,
                  boxSizing: "border-box",
                  background: `${box.color}${isEditable ? "28" : "20"}`,
                  pointerEvents: isEditable ? "auto" : "none",
                  cursor: isEditable ? "move" : "default",
                }}
                onMouseDown={isEditable ? (e) => {
                  e.stopPropagation(); e.preventDefault();
                  setEditBoxDrag({ key: box.key, type: "move", handle: "move",
                    startMouseX: e.clientX, startMouseY: e.clientY,
                    startBox: { x: live.x, y: live.y, w: live.w, h: live.h } });
                  setEditBoxLive({ key: box.key, box: { x: live.x, y: live.y, w: live.w, h: live.h } });
                } : undefined}
              >
                {renderLabel(box)}
                {/* [프리셋] 편집모드 리사이즈 핸들 */}
                {isEditable && RESIZE_HANDLES.map(rh => (
                  <div
                    key={rh.id}
                    style={{
                      position: "absolute", width: 8, height: 8,
                      background: box.color, borderRadius: 1,
                      ...rh.style, pointerEvents: "auto", cursor: rh.cursor, zIndex: 1,
                    }}
                    onMouseDown={(e) => {
                      e.stopPropagation(); e.preventDefault();
                      setEditBoxDrag({ key: box.key, type: "resize", handle: rh.id,
                        startMouseX: e.clientX, startMouseY: e.clientY,
                        startBox: { x: live.x, y: live.y, w: live.w, h: live.h } });
                      setEditBoxLive({ key: box.key, box: { x: live.x, y: live.y, w: live.w, h: live.h } });
                    }}
                  />
                ))}
              </div>
            );
          })}

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
                  fontSize: 10, fontWeight: 700, color: "#6B5314",
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

        {/* 확대/축소/회전/원위치 — 캔버스 우측 중앙 세로 정렬 */}
        <div style={{
          position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)",
          display: "flex", flexDirection: "column", gap: 4, zIndex: 10,
        }}>
          <button type="button" onClick={zoomIn}   onMouseDown={(e) => e.stopPropagation()} style={overlayBtnStyle}>확대 +</button>
          <button type="button" onClick={zoomOut}  onMouseDown={(e) => e.stopPropagation()} style={overlayBtnStyle}>축소 −</button>
          <button type="button" onClick={rotate90} onMouseDown={(e) => e.stopPropagation()} style={overlayBtnStyle}>90°↻</button>
          <button type="button" onClick={reset}    onMouseDown={(e) => e.stopPropagation()} style={overlayBtnStyle}>원위치</button>
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

  // [프리셋] tf 최신값 ref (onTfChange 콜백으로 업데이트)
  const passportTfRef = useRef<WsTf>(DEFAULT_TF);
  const arcTfRef      = useRef<WsTf>(DEFAULT_TF);

  // [프리셋] 프리셋 state
  const [presets, setPresets]         = useState<(RoiPreset | null)[]>([null, null, null]);
  const [activeSlot, setActiveSlot]   = useState<1 | 2 | 3>(1);
  const [editMode, setEditMode]       = useState(false);
  const [isDirty, setIsDirty]         = useState(false);

  // [프리셋] WorkspaceCanvas tf 외부 주입
  const [passportExternalTf, setPassportExternalTf] = useState<WsTf | undefined>();
  const [passportResetTrigger, setPassportResetTrigger] = useState(0);
  const [arcExternalTf, setArcExternalTf]           = useState<WsTf | undefined>();
  const [arcResetTrigger, setArcResetTrigger]       = useState(0);

  // [프리셋] 가이드 박스 state (기존 하드코딩 상수에서 초기화)
  const [passportMrzBox, setPassportMrzBox] = useState<RoiBox>({
    x: PASSPORT_MRZ_GUIDE.x, y: PASSPORT_MRZ_GUIDE.y,
    w: PASSPORT_MRZ_GUIDE.w, h: PASSPORT_MRZ_GUIDE.h,
  });
  const [arcBoxes, setArcBoxes] = useState<Record<string, RoiBox>>(() =>
    Object.fromEntries(ARC_GUIDE_BOXES.map(b => [b.key, { x: b.x, y: b.y, w: b.w, h: b.h }]))
  );

  // 등록 후 서명 프롬프트
  const [signPrompt, setSignPrompt] = useState<{ name: string; customerId: string } | null>(null);
  const [showSignModal, setShowSignModal] = useState(false);

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

  // ── [프리셋] 마운트 시 프리셋 로드 ───────────────────────────────────────────
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    fetchRoiPresets().then(loaded => {
      setPresets(loaded);
      const defaultPreset = loaded.find(p => p?.is_default) ?? loaded[0];
      if (defaultPreset) {
        applyPreset(defaultPreset);
        setActiveSlot(defaultPreset.slot as 1 | 2 | 3);
      }
    }).catch(console.error);
  }, []);

  // 페이지 이탈 방지 (저장 안 된 변경사항)
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (isDirty) { e.preventDefault(); e.returnValue = ""; }
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  // [프리셋] 프리셋 적용
  function applyPreset(preset: RoiPreset) {
    setPassportMrzBox(preset.data.passport.mrz);
    const ppTf = transformToWsTf(preset.data.passport);
    setPassportExternalTf(ppTf);
    setPassportResetTrigger(v => v + 1);

    const newArcBoxes: Record<string, RoiBox> = {};
    (["한글", "등록증", "번호", "발급일", "만기일", "주소"] as const).forEach(k => {
      if (preset.data.arc[k]) newArcBoxes[k] = preset.data.arc[k];
    });
    setArcBoxes(prev => ({ ...prev, ...newArcBoxes }));
    const arcTf = transformToWsTf(preset.data.arc);
    setArcExternalTf(arcTf);
    setArcResetTrigger(v => v + 1);

    setEditMode(false);
    setIsDirty(false);
  }

  // [프리셋] 현재 화면 상태 수집
  function collectCurrentData(): RoiPresetData {
    const ppTf  = passportTfRef.current;
    const aTf   = arcTfRef.current;
    return {
      passport: { mrz: passportMrzBox, ...wsTfToTransform(ppTf) },
      arc: {
        한글:   arcBoxes["한글"]   ?? { x: 0, y: 0, w: 0.1, h: 0.05 },
        등록증: arcBoxes["등록증"] ?? { x: 0, y: 0, w: 0.1, h: 0.05 },
        번호:   arcBoxes["번호"]   ?? { x: 0, y: 0, w: 0.1, h: 0.05 },
        발급일: arcBoxes["발급일"] ?? { x: 0, y: 0, w: 0.1, h: 0.05 },
        만기일: arcBoxes["만기일"] ?? { x: 0, y: 0, w: 0.1, h: 0.05 },
        주소:   arcBoxes["주소"]   ?? { x: 0, y: 0, w: 0.1, h: 0.05 },
        ...wsTfToTransform(aTf),
      } as ArcRoiBoxes & import("@/lib/types/roiPreset").ImageTransform,
    };
  }

  // [프리셋] 슬롯 변경
  function handleSlotChange(slot: 1 | 2 | 3) {
    if (isDirty) {
      if (!confirm("저장하지 않은 변경사항이 있습니다. 슬롯을 변경하시겠습니까?")) return;
    }
    const preset = presets[slot - 1];
    if (preset) { applyPreset(preset); setActiveSlot(slot); }
  }

  // [프리셋] 저장 — 활성 슬롯에 현재 화면 위치 덮어쓰기
  async function handleSave() {
    try {
      const activePreset = presets[activeSlot - 1];
      const name = activePreset?.name ?? `슬롯 ${activeSlot}`;
      const data = collectCurrentData();
      const saved = await saveRoiPreset(activeSlot, name, data, false);
      setPresets(prev => {
        const next = [...prev] as (RoiPreset | null)[];
        next[activeSlot - 1] = saved;
        return next;
      });
      setIsDirty(false);
      toast.success("프리셋 저장 완료");
    } catch {
      toast.error("프리셋 저장 실패");
    }
  }

  // [프리셋] 빈 슬롯에 현재 화면 위치 저장
  async function handleSaveEmpty(slot: 1 | 2 | 3) {
    try {
      const data = collectCurrentData();
      const saved = await saveRoiPreset(slot, `슬롯 ${slot}`, data, false);
      setPresets(prev => {
        const next = [...prev] as (RoiPreset | null)[];
        next[slot - 1] = saved;
        return next;
      });
      setActiveSlot(slot);
      setIsDirty(false);
      toast.success(`슬롯 ${slot} 저장 완료`);
    } catch {
      toast.error("슬롯 저장 실패");
    }
  }

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
      // [프리셋] 선택식이면 사용자 그린 ROI, 아니면 state 기반 가이드 박스
      const effectiveGuide = passportCustomRois["mrz"]
        ? { key: "mrz", label: "MRZ", ...passportCustomRois["mrz"] }
        : { ...PASSPORT_MRZ_GUIDE, ...passportMrzBox };
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
      const stateBox = arcBoxes[field];
      // [프리셋] 선택식이면 사용자 그린 ROI, 아니면 state 기반 가이드 박스
      const effectiveGuide = customRect
        ? { key: field, label: ARC_FIELD_LABELS[field], ...customRect }
        : (guide && stateBox
            ? { ...guide, ...stateBox }
            : (guide ?? { key: field, label: field, x: 0, y: 0, w: 1, h: 1, color: "" }));
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
      const { status, message, 고객ID: newId } = res.data as { status: string; message: string; 고객ID?: string };
      toast.success(status === "updated" ? `✅ ${message}` : `🆕 ${message}`);
      qc.invalidateQueries({ queryKey: ["customers"] });
      const savedName = 한글.trim() || `${성.trim()} ${명.trim()}`.trim() || "신규 고객";
      resetAll();
      if (status === "created" && newId) {
        setSignPrompt({ name: savedName, customerId: newId });
      }
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
    <>
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* [프리셋] ROI 프리셋 슬롯 바 */}
      <RoiPresetBar
        presets={presets}
        activeSlot={activeSlot}
        editMode={editMode}
        isDirty={isDirty}
        onSlotChange={handleSlotChange}
        onEditModeChange={setEditMode}
        onSave={handleSave}
        onSaveEmpty={handleSaveEmpty}
        onRename={async (slot, name) => {
          try {
            const updated = await renameRoiPreset(slot, name);
            setPresets(prev => {
              const next = [...prev] as (RoiPreset | null)[];
              next[slot - 1] = updated;
              return next;
            });
          } catch { toast.error("이름 변경 실패"); }
        }}
      />

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
            guides={[{ ...PASSPORT_MRZ_GUIDE, ...passportMrzBox }]}
            sampleText="여권 이미지 예시 (업로드 필수)" sampleSrc="/passport-sample.jpg"
            stateRef={passportWsRef}
            debugOverlay={debugMode && passportDebug?.calc ? { key: "mrz", roi: passportDebug.calc.sentRoi } : null}
            wsMode={wsMode}
            selectingFor={passportSelectingFor}
            onSelectDone={onPassportSelectDone}
            customRois={passportCustomRois}
            externalTf={passportExternalTf}
            resetTrigger={passportResetTrigger}
            onTfChange={(tf) => { passportTfRef.current = tf; }}
            editMode={editMode}
            onBoxChange={(key, box) => {
              setPassportMrzBox(box);
              setIsDirty(true);
            }}
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
        <div style={{ ...cardStyle, borderLeft: "3px solid #D4A843" }}>
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
            guides={ARC_GUIDE_BOXES.map(b => ({ ...b, ...(arcBoxes[b.key] ?? {}) }))}
            sampleText="등록증 이미지 예시 (업로드 선택)" sampleSrc="/arc-sample.jpg"
            stateRef={arcWsRef}
            debugOverlay={debugMode && arcDebug?.calc ? { key: arcDebug.fieldKey ?? "", roi: arcDebug.calc.sentRoi } : null}
            wsMode={wsMode}
            selectingFor={arcSelectingFor}
            onSelectDone={onArcSelectDone}
            customRois={arcCustomRois}
            externalTf={arcExternalTf}
            resetTrigger={arcResetTrigger}
            onTfChange={(tf) => { arcTfRef.current = tf; }}
            editMode={editMode}
            onBoxChange={(key, box) => {
              setArcBoxes(prev => ({ ...prev, [key]: box }));
              setIsDirty(true);
            }}
            initialAlign="top"
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
                      gridTemplateColumns: wsMode === "선택식" ? "auto 1fr auto" : "auto 1fr",
                      gap: 6, alignItems: "center",
                    }}>
                      <button
                        onClick={() => runArcFieldOcr(key)}
                        disabled={!arcFile || arcLoadingField !== null}
                        style={!arcFile || arcLoadingField !== null ? disabledBtnStyle : smallBtnStyle}
                      >
                        {loading ? "추출 중..." : "추출"}
                      </button>
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
                    </div>
                    {wsMode === "선택식" && arcCustomRois[key] && (
                      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3 }}>
                        <span style={{ fontSize: 10, color: "#6B5314", background: "#FFF9E6", padding: "1px 6px", borderRadius: 4 }}>
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

    {/* OCR 신규 등록 후 서명 프롬프트 */}
    {signPrompt && !showSignModal && (
      <>
        <div style={{ position:"fixed", inset:0, background:"rgba(0,0,0,0.35)", zIndex:200 }}
          onClick={() => setSignPrompt(null)} />
        <div style={{
          position:"fixed", top:"50%", left:"50%",
          transform:"translate(-50%,-50%)", zIndex:201,
          width:"min(340px,92vw)", background:"#fff",
          borderRadius:14, boxShadow:"0 8px 32px rgba(0,0,0,0.16)",
          padding:"28px 24px",
        }}>
          <div style={{ fontSize:15, fontWeight:700, color:"#1A202C", marginBottom:10 }}>
            신규 고객 서명 등록
          </div>
          <div style={{ fontSize:13, color:"#4A5568", marginBottom:24, lineHeight:1.6 }}>
            <strong>{signPrompt.name}</strong> 고객의 서명을 등록하시겠습니까?
          </div>
          <div style={{ display:"flex", gap:10, justifyContent:"flex-end" }}>
            <button
              onClick={() => setSignPrompt(null)}
              style={{ padding:"9px 18px", borderRadius:8, border:"1px solid #E2E8F0", background:"#fff", color:"#718096", fontSize:13, cursor:"pointer", fontWeight:600 }}>
              나중에
            </button>
            <button
              onClick={() => setShowSignModal(true)}
              style={{ padding:"9px 18px", borderRadius:8, border:"none", background:"#F5A623", color:"#fff", fontSize:13, cursor:"pointer", fontWeight:700 }}>
              서명 등록하기
            </button>
          </div>
        </div>
      </>
    )}

    {/* 서명 모달 */}
    {showSignModal && signPrompt && (
      <SignatureModal
        type="customer"
        customerId={signPrompt.customerId}
        onSave={() => {
          toast.success("서명이 등록되었습니다");
          setShowSignModal(false);
          setSignPrompt(null);
        }}
        onClose={() => {
          setShowSignModal(false);
          setSignPrompt(null);
        }}
      />
    )}
    </>
  );
}
