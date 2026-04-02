"use client";

import { useRef, useState, useEffect } from "react";
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
  fontSize: 12, fontWeight: 600, cursor: "pointer",
};
const disabledBtnStyle: React.CSSProperties = {
  ...smallBtnStyle, opacity: 0.5, cursor: "not-allowed",
};
const smallToolBtnStyle: React.CSSProperties = {
  height: 28, padding: "0 9px", borderRadius: 5,
  border: "1px solid #CBD5E0", background: "#EDF2F7", color: "#4A5568",
  fontSize: 12, fontWeight: 500, cursor: "pointer",
};

// ── Workspace transform types ─────────────────────────────────────────────────

interface WsTf   { scale: number; tx: number; ty: number; rot: number }
interface WsSize { w: number; h: number }
interface WsState { tf: WsTf; container: WsSize; natural: WsSize }

const DEFAULT_TF: WsTf = { scale: 1, tx: 0, ty: 0, rot: 0 };

// ── ROI computation ───────────────────────────────────────────────────────────
// Converts a guide box (in container-space 0–1) to image-space ROI (0–1),
// accounting for the current image transform (scale, pan, rotation).

function computeRoi(
  guide: { x: number; y: number; w: number; h: number },
  container: WsSize,
  natural: WsSize,
  tf: WsTf,
): { x: number; y: number; w: number; h: number } {
  const { scale, tx, ty } = tf;
  const rot = ((tf.rot % 360) + 360) % 360;
  const { w: cW, h: cH } = container;

  // Displayed image dimensions after rotation (axes swap at 90/270)
  const dispW = (rot === 90 || rot === 270) ? natural.h * scale : natural.w * scale;
  const dispH = (rot === 90 || rot === 270) ? natural.w * scale : natural.h * scale;

  // Image top-left in container pixels (image centered + user translation)
  const imgLeft = cW / 2 + tx - dispW / 2;
  const imgTop  = cH / 2 + ty - dispH / 2;

  // Guide box in container pixels, relative to image top-left
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
    // 90° CW: display-x maps to orig-(iH - y), display-y maps to orig-x
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
  // 270° CW (= 90° CCW)
  return {
    x: cl((dispH - relT - relH) / dispH),
    y: cl(relL / dispW),
    w: cs(relH / dispH),
    h: cs(relW / dispW),
  };
}

// ── Guide definitions ─────────────────────────────────────────────────────────
// Positions in container-space (0–1). Initial image scale fits to container,
// so these approximately correspond to image-normalized field positions.

// Passport: MRZ guide — calibrated to the two MRZ lines on a standard passport scan.
// x/y/w/h are container-space (0–1). User aligns passport so the MRZ lines sit inside this box.
const PASSPORT_MRZ_GUIDE = {
  key: "mrz", label: "MRZ",
  x: 0.160, y: 0.635, w: 0.630, h: 0.085,
  color: "#D69E2E",
};

// ARC: 6 field guides. Coordinates are container-space (0–1).
// Front card (top half of portrait scan): 등록증앞/뒤, 한글이름, 발급일.
// Back sticker (bottom half, rotated 90° in scan): 만기일 and 주소 are intentionally
// narrow+tall to match the rotated layout before the user rotates the image.
const ARC_GUIDE_BOXES: Array<{
  key: ArcFieldKey; label: string;
  x: number; y: number; w: number; h: number;
  color: string;
}> = [
  { key: "등록증", label: "등록증 앞",  x: 0.368, y: 0.174, w: 0.075, h: 0.024, color: "#dd6b20" },
  { key: "번호",   label: "등록증 뒤",  x: 0.451, y: 0.174, w: 0.075, h: 0.024, color: "#d69e2e" },
  { key: "한글",   label: "한글 이름",  x: 0.374, y: 0.205, w: 0.058, h: 0.018, color: "#e53e3e" },
  { key: "발급일", label: "발급일",    x: 0.565, y: 0.261, w: 0.110, h: 0.028, color: "#38a169" },
  { key: "만기일", label: "만기일",    x: 0.425, y: 0.650, w: 0.032, h: 0.110, color: "#3182ce" },
  { key: "주소",   label: "주소",     x: 0.500, y: 0.695, w: 0.072, h: 0.118, color: "#805ad5" },
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
// Fixed-height viewport. Image is movable (drag/zoom/rotate) beneath fixed guide overlays.
// No wheel zoom. Buttons only.

const WORKSPACE_H = 660;

interface GuideBox {
  key: string; label: string;
  x: number; y: number; w: number; h: number;
  color: string;
}

function WorkspaceCanvas({
  preview, file, guides, sampleText, sampleSrc, stateRef,
}: {
  preview: string | null;
  file: File | null;
  guides: GuideBox[];
  sampleText: string;
  sampleSrc: string;
  stateRef: React.MutableRefObject<WsState>;
}) {
  const [tf, setTf]           = useState<WsTf>(DEFAULT_TF);
  const [dragging, setDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ mx: 0, my: 0, tx: 0, ty: 0 });
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef       = useRef<HTMLImageElement>(null);

  // Reset transform when a new file is loaded
  useEffect(() => { setTf(DEFAULT_TF); }, [preview]);

  // Keep stateRef current on every render so OCR handlers always see latest values
  // (stateRef is a mutable ref — writing here does not trigger re-renders)
  const cont = containerRef.current;
  const img  = imgRef.current;
  stateRef.current = {
    tf,
    container: { w: cont?.clientWidth  ?? 1, h: cont?.clientHeight ?? 1 },
    natural:   { w: img?.naturalWidth  ?? 1, h: img?.naturalHeight ?? 1 },
  };

  // Fit image to container on load (no upscaling cap — allows small images to fill workspace)
  const onImgLoad = () => {
    const c = containerRef.current;
    const i = imgRef.current;
    if (!c || !i || !i.naturalWidth) return;
    const scale = Math.min(c.clientWidth / i.naturalWidth, WORKSPACE_H / i.naturalHeight);
    setTf({ scale, tx: 0, ty: 0, rot: 0 });
  };

  const zoomIn   = () => setTf(p => ({ ...p, scale: Math.min(20,   p.scale * 1.25) }));
  const zoomOut  = () => setTf(p => ({ ...p, scale: Math.max(0.05, p.scale / 1.25) }));
  const rotate90 = () => setTf(p => ({ ...p, rot: p.rot + 90 }));
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

  const onMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    setDragging(true);
    setDragStart({ mx: e.clientX, my: e.clientY, tx: tf.tx, ty: tf.ty });
  };
  const onMouseMove = (e: React.MouseEvent) => {
    if (!dragging) return;
    setTf(p => ({
      ...p,
      tx: dragStart.tx + (e.clientX - dragStart.mx),
      ty: dragStart.ty + (e.clientY - dragStart.my),
    }));
  };
  const stopDrag = () => setDragging(false);

  if (!preview || !file) return <SampleBox text={sampleText} sampleSrc={sampleSrc} />;

  if (file.type === "application/pdf") {
    return (
      <div>
        <iframe
          src={preview}
          style={{ width: "100%", minHeight: 420, border: "none", borderRadius: 8 }}
          title="PDF 미리보기"
        />
        <div style={{ fontSize: 12, color: "#A0AEC0", marginTop: 6 }}>
          PDF는 ROI 숫자값만 조정합니다.
        </div>
      </div>
    );
  }

  const rot = ((tf.rot % 360) + 360) % 360;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {/* Toolbar — top-right of workspace */}
      <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
        <button type="button" onClick={zoomIn}   style={smallToolBtnStyle}>확대 +</button>
        <button type="button" onClick={zoomOut}  style={smallToolBtnStyle}>축소 −</button>
        <button type="button" onClick={rotate90} style={smallToolBtnStyle}>90° 회전</button>
        <button type="button" onClick={reset}    style={smallToolBtnStyle}>원위치</button>
      </div>

      {/* Viewport — fixed height, image can be panned to reveal any part */}
      <div
        ref={containerRef}
        style={{
          position: "relative",
          width: "100%",
          height: WORKSPACE_H,
          overflow: "hidden",
          background: "#1a202c",
          borderRadius: 8,
          border: "1px solid #4A5568",
          cursor: dragging ? "grabbing" : "grab",
          userSelect: "none",
          touchAction: "none",
        }}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={stopDrag}
        onMouseLeave={stopDrag}
      >
        {/* ── Image layer (moves with drag/zoom/rotate) ── */}
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            // Centered first, then user translation, then rotation+scale
            transform: `translate(-50%, -50%) translate(${tf.tx}px, ${tf.ty}px) rotate(${rot}deg) scale(${tf.scale})`,
            transformOrigin: "center center",
            pointerEvents: "none",
          }}
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            ref={imgRef}
            src={preview}
            alt="preview"
            draggable={false}
            onLoad={onImgLoad}
            style={{ display: "block", maxWidth: "none" }}
          />
        </div>

        {/* ── Guide overlay (stays fixed while image moves beneath) ── */}
        <div style={{
          position: "absolute",
          top: 0, left: 0, right: 0, bottom: 0,
          pointerEvents: "none",
        }}>
          {guides.map((box) => (
            <div
              key={box.key}
              style={{
                position: "absolute",
                left:   `${box.x * 100}%`,
                top:    `${box.y * 100}%`,
                width:  `${box.w * 100}%`,
                height: `${box.h * 100}%`,
                border: `2px dashed ${box.color}`,
                boxSizing: "border-box",
                background: `${box.color}20`,
              }}
            >
              <span style={{
                position: "absolute", top: 2, left: 4,
                fontSize: 10, fontWeight: 700,
                color: box.color,
                background: "rgba(0,0,0,0.70)",
                padding: "1px 5px", borderRadius: 3, lineHeight: 1.5,
                whiteSpace: "nowrap",
              }}>
                {box.label}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ fontSize: 11, color: "#718096", textAlign: "center" }}>
        드래그로 이동 · 버튼으로 확대/축소/회전 · 이미지를 가이드 박스에 맞춰주세요
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

// ── ScanPage ──────────────────────────────────────────────────────────────────

export default function ScanPage() {
  const qc = useQueryClient();

  const passportInputRef = useRef<HTMLInputElement>(null);
  const arcInputRef      = useRef<HTMLInputElement>(null);

  const [passportFile, setPassportFile]     = useState<File | null>(null);
  const [passportPreview, setPassportPreview] = useState<string | null>(null);
  const [arcFile, setArcFile]               = useState<File | null>(null);
  const [arcPreview, setArcPreview]         = useState<string | null>(null);

  const [passportLoading, setPassportLoading]   = useState(false);
  const [arcLoadingField, setArcLoadingField]   = useState<ArcFieldKey | null>(null);

  // Workspace state refs — WorkspaceCanvas keeps these current on every render.
  // Read at OCR button click time to compute the correct image-space ROI.
  const passportWsRef = useRef<WsState>({
    tf: DEFAULT_TF, container: { w: 1, h: 1 }, natural: { w: 1, h: 1 },
  });
  const arcWsRef = useRef<WsState>({
    tf: DEFAULT_TF, container: { w: 1, h: 1 }, natural: { w: 1, h: 1 },
  });

  // 여권 정보
  const [성, set성]       = useState("");
  const [명, set명]       = useState("");
  const [국적, set국적]   = useState("");
  const [성별, set성별]   = useState("");
  const [여권, set여권]   = useState("");
  const [여권발급, set여권발급] = useState("");
  const [여권만기, set여권만기] = useState("");

  // 등록증 정보
  const [한글, set한글]   = useState("");
  const [등록증, set등록증] = useState("");
  const [번호, set번호]   = useState("");
  const [발급일, set발급일] = useState("");
  const [만기일, set만기일] = useState("");
  const [주소, set주소]   = useState("");

  // 연락처
  const [연, set연] = useState("010");
  const [락, set락] = useState("");
  const [처, set처] = useState("");
  const [V, setV]   = useState("");

  // 등록증 필드 잠금 (OCR 덮어쓰기 방지; 수동 입력은 항상 허용)
  const [arcLocks, setArcLocks] = useState<Record<ArcFieldKey, boolean>>({
    한글: false, 등록증: false, 번호: false, 발급일: false, 만기일: false, 주소: false,
  });

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

  const toggleArcLock = (field: ArcFieldKey) =>
    setArcLocks(p => ({ ...p, [field]: !p[field] }));

  const handlePassportFile = (f: File) => {
    setPassportFile(f);
    setPassportPreview(URL.createObjectURL(f));
  };
  const handleArcFile = (f: File) => {
    setArcFile(f);
    setArcPreview(URL.createObjectURL(f));
  };

  // ── OCR handlers ──────────────────────────────────────────────────────────

  const runPassportWorkspaceOcr = async () => {
    if (!passportFile) { toast.error("여권 파일을 먼저 올려주세요."); return; }
    setPassportLoading(true);
    try {
      const { tf, container, natural } = passportWsRef.current;
      const roi = computeRoi(PASSPORT_MRZ_GUIDE, container, natural, tf);

      const formData = new FormData();
      formData.append("file", passportFile);
      formData.append("roi_json", JSON.stringify(roi));

      const res = await api.post("/api/scan-workspace/passport", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
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
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          "여권 OCR 오류",
      );
    } finally {
      setPassportLoading(false);
    }
  };

  const runArcFieldOcr = async (field: ArcFieldKey) => {
    if (!arcFile) { toast.error("등록증 파일을 먼저 올려주세요."); return; }
    if (arcLocks[field]) { toast.error(`${ARC_FIELD_LABELS[field]} 필드는 잠금 상태입니다.`); return; }
    setArcLoadingField(field);
    try {
      const { tf, container, natural } = arcWsRef.current;
      const guide = ARC_GUIDE_BOXES.find(b => b.key === field);
      const roi = guide
        ? computeRoi(guide, container, natural, tf)
        : { x: 0, y: 0, w: 1, h: 1 };

      const formData = new FormData();
      formData.append("file", arcFile);
      formData.append("field", field);
      formData.append("roi_json", JSON.stringify(roi));

      const res = await api.post("/api/scan-workspace/arc", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      const resultField = ((res.data as any)?.field || field) as ArcFieldKey;
      const value = String((res.data as any)?.value ?? "");
      if (!value) { toast.error(`${ARC_FIELD_LABELS[field]} 추출 결과가 없습니다.`); return; }
      setArcFieldValue(resultField, value);
      toast.success(`${ARC_FIELD_LABELS[resultField]} 추출 완료`);
    } catch (err: unknown) {
      toast.error(
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
          "등록증 OCR 오류",
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
    setArcLocks({ 한글: false, 등록증: false, 번호: false, 발급일: false, 만기일: false, 주소: false });
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

  // ── Render ────────────────────────────────────────────────────────────────

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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <ScanLine size={18} style={{ color: "var(--hw-gold)" }} />
        <h1 className="hw-page-title">반자동 OCR 작업판</h1>
      </div>

      <p style={{ fontSize: 13, color: "#718096", margin: 0 }}>
        이미지를 드래그·확대해 가이드 박스에 맞춘 뒤, 원하는 필드의 <b>추출</b> 버튼을 누르세요.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1.25fr 0.95fr", gap: 16 }}>

        {/* ── 좌측 작업판 ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {/* 여권 작업판 */}
          <div style={cardStyle}>
            <div style={sectionTitleStyle}>여권 작업판</div>

            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: "#4A5568" }}>
                여권 이미지 업로드
              </div>
              <div
                style={dropZoneStyle(!!passportFile)}
                onClick={() => passportInputRef.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  const f = e.dataTransfer.files?.[0];
                  if (f) handlePassportFile(f);
                }}
              >
                <input
                  ref={passportInputRef}
                  type="file"
                  accept="image/*,.pdf"
                  style={{ display: "none" }}
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) handlePassportFile(f); }}
                />
                {passportFile ? (
                  <span style={{ fontSize: 12, color: "var(--hw-gold)", fontWeight: 600 }}>
                    ✅ {passportFile.name}
                  </span>
                ) : (
                  <span style={{ fontSize: 12, color: "#718096", display: "flex", alignItems: "center", gap: 4 }}>
                    <Upload size={13} style={{ flexShrink: 0 }} />
                    여권 이미지를 업로드 하세요.
                  </span>
                )}
              </div>
            </div>

            <WorkspaceCanvas
              preview={passportPreview}
              file={passportFile}
              guides={[PASSPORT_MRZ_GUIDE]}
              sampleText="여권 이미지 예시 (업로드 필수)"
              sampleSrc="/passport-sample.jpg"
              stateRef={passportWsRef}
            />

            <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 12 }}>
              <button
                onClick={runPassportWorkspaceOcr}
                disabled={!passportFile || passportLoading}
                style={!passportFile || passportLoading ? disabledBtnStyle : smallBtnStyle}
              >
                {passportLoading ? "추출 중..." : "MRZ 추출"}
              </button>
            </div>
          </div>

          {/* 등록증 작업판 */}
          <div style={cardStyle}>
            <div style={sectionTitleStyle}>등록증 작업판</div>

            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6, color: "#4A5568" }}>
                등록증/스티커 이미지 업로드
              </div>
              <div
                style={dropZoneStyle(!!arcFile)}
                onClick={() => arcInputRef.current?.click()}
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  const f = e.dataTransfer.files?.[0];
                  if (f) handleArcFile(f);
                }}
              >
                <input
                  ref={arcInputRef}
                  type="file"
                  accept="image/*,.pdf"
                  style={{ display: "none" }}
                  onChange={(e) => { const f = e.target.files?.[0]; if (f) handleArcFile(f); }}
                />
                {arcFile ? (
                  <span style={{ fontSize: 12, color: "var(--hw-gold)", fontWeight: 600 }}>
                    ✅ {arcFile.name}
                  </span>
                ) : (
                  <span style={{ fontSize: 12, color: "#718096", display: "flex", alignItems: "center", gap: 4 }}>
                    <Upload size={13} style={{ flexShrink: 0 }} />
                    등록증 이미지를 업로드 하세요.
                  </span>
                )}
              </div>
            </div>

            <WorkspaceCanvas
              preview={arcPreview}
              file={arcFile}
              guides={ARC_GUIDE_BOXES}
              sampleText="등록증 이미지 예시 (업로드 선택)"
              sampleSrc="/arc-sample.jpg"
              stateRef={arcWsRef}
            />

            <div style={{ fontSize: 12, color: "#718096", marginTop: 10 }}>
              앞면: 등록증 앞·뒤·한글 가이드에 맞춰주세요.
              뒷면(스티커): 90° 회전 후 발급일·만기일·주소 가이드에 맞춰주세요.
            </div>
          </div>
        </div>

        {/* ── 우측 결과판 (sticky) ── */}
        <div style={{
          display: "flex", flexDirection: "column", gap: 16,
          position: "sticky", top: 16,
          alignSelf: "flex-start",
          overflowY: "auto",
          maxHeight: "calc(100vh - 48px)",
        }}>

          {/* 여권 결과 */}
          <div style={cardStyle}>
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
              </div>
              <div>
                <label style={labelStyle}>여권 만기일 (YYYY-MM-DD)</label>
                <input style={inputStyle} value={여권만기} onChange={(e) => set여권만기(e.target.value)} />
              </div>
            </div>
          </div>

          {/* 등록증 결과 */}
          <div style={cardStyle}>
            <div style={sectionTitleStyle}>등록증 결과</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {arcFieldRows.map(({ key, value, onChange }) => {
                const loading = arcLoadingField === key;
                const locked  = arcLocks[key];
                return (
                  <div key={key}>
                    <label style={labelStyle}>{ARC_FIELD_LABELS[key]}</label>
                    <div style={{
                      display: "grid",
                      gridTemplateColumns: "1fr auto auto",
                      gap: 6, alignItems: "center",
                    }}>
                      <input
                        style={inputStyle}
                        value={value}
                        onChange={(e) => onChange(e.target.value)}
                      />
                      <label style={{
                        display: "flex", alignItems: "center", gap: 4,
                        fontSize: 12, color: locked ? "#C05621" : "#718096",
                        whiteSpace: "nowrap",
                      }}>
                        <input type="checkbox" checked={locked} onChange={() => toggleArcLock(key)} />
                        잠금
                      </label>
                      <button
                        onClick={() => runArcFieldOcr(key)}
                        disabled={!arcFile || locked || arcLoadingField !== null}
                        style={!arcFile || locked || arcLoadingField !== null ? disabledBtnStyle : smallBtnStyle}
                      >
                        {loading ? "추출 중..." : "추출"}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 연락처 / 비고 */}
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
              style={{
                height: 42, borderRadius: 8,
                border: "1px solid #CBD5E0",
                background: "#fff", color: "#4A5568",
                fontSize: 14, fontWeight: 600, cursor: "pointer",
              }}
            >
              초기화
            </button>
            <button
              onClick={handleSubmit}
              disabled={registerMut.isPending}
              className="btn-primary"
              style={{
                height: 42, borderRadius: 8,
                fontSize: 14, fontWeight: 700,
                opacity: registerMut.isPending ? 0.5 : 1,
              }}
            >
              {registerMut.isPending ? "저장 중..." : "고객관리 반영"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
