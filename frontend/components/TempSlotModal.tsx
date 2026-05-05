"use client";
import { useEffect, useRef, useState } from "react";
import { X, Search } from "lucide-react";
import { api, quickDocApi, type CustomerSearchResult } from "@/lib/api";
import { toast } from "sonner";

interface Props {
  slot: 1 | 2 | 3;
  hasData: boolean;
  memo: string;
  onClose: () => void;
  onUpdate: () => void;
}

type Phase = "idle" | "requesting" | "waiting" | "done" | "mapping";

export default function TempSlotModal({ slot, hasData, memo: initMemo, onClose, onUpdate }: Props) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [memoInput, setMemoInput] = useState(initMemo);
  const [token, setToken] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [qrSrc, setQrSrc] = useState("");
  const [preview, setPreview] = useState<string | null>(null);
  const [previewLoaded, setPreviewLoaded] = useState(false);
  const [customerQ, setCustomerQ] = useState("");
  const [customers, setCustomers] = useState<CustomerSearchResult[]>([]);
  const [deleting, setDeleting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };

  // 서명 미리보기 로드 (클릭 시)
  const loadPreview = async () => {
    if (previewLoaded) return;
    try {
      const r = await api.get<{ data: string | null }>(`/api/signature/temp-slots/${slot}/data`);
      setPreview(r.data.data ?? null);
      setPreviewLoaded(true);
    } catch { toast.error("미리보기 로드 실패"); }
  };

  // 서명 받기 클릭
  const handleRequest = async () => {
    setPhase("requesting");
    try {
      const r = await api.post<{ token: string; url: string }>(
        `/api/signature/temp-slots/${slot}/request`,
        { memo: memoInput },
      );
      setToken(r.data.token);
      setUrl(r.data.url);
      const QRCode = await import("qrcode");
      setQrSrc(await QRCode.toDataURL(r.data.url, { width: 200, margin: 1 }));
      setPhase("waiting");
    } catch { toast.error("요청 실패"); setPhase("idle"); }
  };

  // 폴링
  useEffect(() => {
    if (phase !== "waiting" || !token) { stopPoll(); return; }
    pollRef.current = setInterval(async () => {
      try {
        const r = await api.get<{ status: string }>(`/api/signature/poll/${token}`);
        if (r.data.status === "expired") { stopPoll(); setPhase("idle"); toast.error("링크 만료"); }
        if (r.data.status === "done") {
          stopPoll();
          await api.post(`/api/signature/temp-slots/${slot}/save/${token}`);
          setPhase("done");
          onUpdate();
          toast.success(`슬롯 ${slot}번 서명 저장됨`);
          setTimeout(onClose, 1500);
        }
      } catch { /* ignore transient */ }
    }, 2000);
    return () => stopPoll();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase, token]);

  // 삭제
  const handleClear = async () => {
    if (!confirm("슬롯 서명을 삭제하시겠습니까?")) return;
    setDeleting(true);
    try {
      await api.post(`/api/signature/temp-slots/${slot}/clear`);
      toast.success("삭제됨");
      onUpdate();
      onClose();
    } catch { toast.error("삭제 실패"); } finally { setDeleting(false); }
  };

  // 고객 검색
  useEffect(() => {
    if (phase !== "mapping" || customerQ.length < 1) { setCustomers([]); return; }
    quickDocApi.searchCustomers(customerQ).then((r) => setCustomers(r.data)).catch(() => {});
  }, [customerQ, phase]);

  // 고객에 매핑
  const handleMap = async (c: CustomerSearchResult) => {
    try {
      await api.post(`/api/signature/temp-slots/${slot}/map-customer`, { customer_id: c.id });
      toast.success(`${c.name} 고객에 서명 매핑 완료`);
      onUpdate();
      onClose();
    } catch { toast.error("매핑 실패"); }
  };

  const GOLD = "#F5A623";
  const BORDER = "#E2E8F0";

  return (
    <>
      <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 300 }} onClick={onClose} />
      <div style={{
        position: "fixed", top: "50%", left: "50%",
        transform: "translate(-50%,-50%)",
        zIndex: 301, width: "min(360px, 94vw)",
        background: "#fff", borderRadius: 16,
        boxShadow: "0 8px 40px rgba(0,0,0,0.18)",
        padding: "22px",
      }}>
        {/* 헤더 */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 18 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: "#1A202C" }}>서명 임시저장 {slot}번</span>
          <button onClick={onClose} style={{ background: "none", border: "none", cursor: "pointer", color: "#718096" }}><X size={18} /></button>
        </div>

        {/* ── 완료 ── */}
        {phase === "done" && (
          <div style={{ textAlign: "center", padding: "20px 0" }}>
            <div style={{ fontSize: 32 }}>✅</div>
            <div style={{ fontSize: 14, fontWeight: 600, color: "#276749", marginTop: 8 }}>서명 저장 완료</div>
          </div>
        )}

        {/* ── 서명 없음 ── */}
        {!hasData && phase !== "done" && (
          <>
            <div style={{ marginBottom: 14 }}>
              <label style={{ fontSize: 11, color: "#718096", display: "block", marginBottom: 4 }}>비고 (누구 서명인지)</label>
              <input
                value={memoInput}
                onChange={(e) => setMemoInput(e.target.value)}
                placeholder="예: 홍길동 고객"
                style={{ width: "100%", padding: "8px 10px", border: `1px solid ${BORDER}`, borderRadius: 8, fontSize: 13, boxSizing: "border-box" }}
              />
            </div>

            {(phase === "idle") && (
              <button
                onClick={handleRequest}
                style={{ width: "100%", padding: "11px 0", background: GOLD, border: "none", borderRadius: 10, color: "#fff", fontSize: 14, fontWeight: 600, cursor: "pointer" }}
              >
                서명 받기
              </button>
            )}

            {phase === "requesting" && (
              <div style={{ textAlign: "center", color: "#A0AEC0", fontSize: 13, padding: "12px 0" }}>QR 생성 중...</div>
            )}

            {phase === "waiting" && (
              <>
                <div style={{ textAlign: "center", fontSize: 12, color: "#4A5568", marginBottom: 10 }}>
                  휴대폰으로 QR코드를 스캔하거나 링크를 여세요
                </div>
                {qrSrc && <div style={{ textAlign: "center", marginBottom: 10 }}><img src={qrSrc} alt="QR" style={{ width: 200, height: 200, borderRadius: 8 }} /></div>}
                <div style={{
                  display: "flex", alignItems: "center", gap: 6,
                  background: "#F7FAFC", borderRadius: 8, padding: "7px 10px", marginBottom: 10,
                }}>
                  <span style={{ flex: 1, fontSize: 11, color: "#4A5568", wordBreak: "break-all" }}>{url}</span>
                  <button onClick={() => navigator.clipboard.writeText(url)} style={{ flexShrink: 0, fontSize: 11, padding: "3px 8px", border: `1px solid ${BORDER}`, borderRadius: 5, background: "#fff", cursor: "pointer" }}>복사</button>
                </div>
                <div style={{ textAlign: "center", fontSize: 12, color: "#A0AEC0" }}>⏳ 서명 대기 중...</div>
              </>
            )}
          </>
        )}

        {/* ── 서명 있음 ── */}
        {hasData && phase !== "done" && phase !== "mapping" && (
          <>
            <div style={{ fontSize: 13, color: "#276749", fontWeight: 600, marginBottom: 6 }}>● 서명 저장됨</div>
            {initMemo && <div style={{ fontSize: 12, color: "#718096", marginBottom: 12 }}>비고: {initMemo}</div>}

            {/* 미리보기 */}
            <div
              onClick={loadPreview}
              style={{
                width: "100%", minHeight: 80, border: `1px solid ${BORDER}`,
                borderRadius: 8, background: "#FAFAFA", marginBottom: 14,
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: previewLoaded ? "default" : "pointer", overflow: "hidden",
              }}
            >
              {preview
                ? <img src={preview} alt="서명" style={{ maxWidth: "100%", maxHeight: 100 }} />
                : <span style={{ fontSize: 12, color: "#A0AEC0" }}>{previewLoaded ? "서명 없음" : "클릭하여 미리보기"}</span>
              }
            </div>

            <div style={{ display: "flex", gap: 10 }}>
              <button
                onClick={handleClear}
                disabled={deleting}
                style={{ flex: 1, padding: "10px 0", border: `1px solid #FC8181`, borderRadius: 10, background: "#FFF5F5", color: "#C53030", fontSize: 13, fontWeight: 600, cursor: "pointer" }}
              >
                삭제
              </button>
              <button
                onClick={() => setPhase("mapping")}
                style={{ flex: 2, padding: "10px 0", background: GOLD, border: "none", borderRadius: 10, color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer" }}
              >
                고객에 매핑하기
              </button>
            </div>
          </>
        )}

        {/* ── 고객 매핑 ── */}
        {phase === "mapping" && (
          <>
            <div style={{ marginBottom: 10, fontSize: 13, color: "#4A5568" }}>고객을 검색하여 서명을 연결합니다.</div>
            <div style={{ position: "relative", marginBottom: 10 }}>
              <Search size={13} style={{ position: "absolute", left: 9, top: "50%", transform: "translateY(-50%)", color: "#A0AEC0" }} />
              <input
                autoFocus
                value={customerQ}
                onChange={(e) => setCustomerQ(e.target.value)}
                placeholder="고객명 검색"
                style={{ width: "100%", padding: "8px 8px 8px 28px", border: `1px solid ${BORDER}`, borderRadius: 8, fontSize: 13, boxSizing: "border-box" }}
              />
            </div>
            {customers.length > 0 && (
              <div style={{ border: `1px solid ${BORDER}`, borderRadius: 8, maxHeight: 180, overflowY: "auto", marginBottom: 10 }}>
                {customers.map((c) => (
                  <button
                    key={c.id}
                    onClick={() => handleMap(c)}
                    style={{ display: "block", width: "100%", textAlign: "left", padding: "8px 12px", background: "none", border: "none", cursor: "pointer", fontSize: 12, color: "#2D3748", borderBottom: `1px solid ${BORDER}` }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "#FFF9E6")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "none")}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
            )}
            <button onClick={() => setPhase("idle")} style={{ width: "100%", padding: "9px 0", border: `1px solid ${BORDER}`, borderRadius: 10, background: "#fff", color: "#718096", fontSize: 13, cursor: "pointer" }}>
              취소
            </button>
          </>
        )}
      </div>
    </>
  );
}
