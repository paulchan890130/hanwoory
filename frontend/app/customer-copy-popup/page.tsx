"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { deriveBirthDateFromArc } from "@/lib/birth";

// ── Types ────────────────────────────────────────────────────────────────────

type C = Record<string, string>;
type Mode = "expiry" | "hikorea-id" | "socinet-id";

const MODE_TITLE: Record<Mode, string> = {
  "expiry":     "체류만료조회 보조",
  "hikorea-id": "하이코리아 ID찾기 보조",
  "socinet-id": "소시넷 ID찾기 보조",
};

// Fields to highlight per mode (matched against row label strings below)
const HIGHLIGHT: Record<Mode, string[]> = {
  "expiry":     ["여권번호", "국적", "생년월일", "체류자격", "체류만료일"],
  "hikorea-id": ["영문이름", "생년월일", "외국인등록번호", "여권번호"],
  "socinet-id": ["영문이름", "등록번호 앞 6자리", "등록번호 뒤 7자리", "여권번호", "전화번호"],
};

// ── Copy row component ────────────────────────────────────────────────────────

function CopyBtn({ text, label, onCopy }: {
  text: string;
  label?: string;
  onCopy: (text: string, label: string) => void;
}) {
  if (!text) return null;
  return (
    <button
      onClick={() => onCopy(text, label ?? text)}
      style={{
        fontSize: 10, padding: "2px 7px", borderRadius: 4,
        border: "1px solid #E2E8F0", background: "#F7FAFC",
        color: "#4A5568", cursor: "pointer", flexShrink: 0, lineHeight: 1.4,
      }}
    >
      {label ? label : "복사"}
    </button>
  );
}

function CopyRow({ label, value, highlight, extra }: {
  label: string;
  value: string;
  highlight: boolean;
  extra?: React.ReactNode;
}) {
  const [flash, setFlash] = useState(false);

  const copy = (text: string, btnLabel?: string) => {
    if (!text) return;
    navigator.clipboard.writeText(text).catch(() => {});
    setFlash(true);
    setTimeout(() => setFlash(false), 900);
  };

  if (!value) return null;

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6, marginBottom: 5,
      padding: "4px 8px", borderRadius: 4,
      borderLeft: highlight ? "3px solid #D4A843" : "3px solid transparent",
      background: flash ? "#FFF9E6" : highlight ? "#FFFDF0" : "transparent",
      transition: "background 0.2s",
    }}>
      <span style={{ fontSize: 10, color: "#718096", width: 84, flexShrink: 0 }}>
        {label}
      </span>
      <span style={{ fontSize: 12, color: "#1A202C", flex: 1, fontFamily: "monospace", wordBreak: "break-all" }}>
        {value}
      </span>
      <CopyBtn text={value} onCopy={copy} />
      {extra}
    </div>
  );
}

// ── Inner component (needs useSearchParams) ──────────────────────────────────

function Inner() {
  const params     = useSearchParams();
  const customerId = params.get("customerId") ?? "";
  const mode       = (params.get("mode") ?? "expiry") as Mode;
  const nonce      = params.get("nonce") ?? "";

  const [c,       setC]       = useState<C | null>(null);
  const [loadErr, setLoadErr] = useState(false);
  const [fl,      setFl]      = useState<string>("");
  // Strict Mode guard: prevents the second effect invocation from treating
  // the already-removed storage key as a missing-data error.
  const loadedRef = useRef(false);

  useEffect(() => {
    if (loadedRef.current) return;   // already loaded on the first invocation
    if (!customerId || !nonce) { setLoadErr(true); return; }
    const storageKey = `customer_copy_popup_data_${customerId}_${mode}_${nonce}`;
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) { setLoadErr(true); return; }

      const payload = JSON.parse(raw) as {
        customerId: string; mode: string; savedAt: number; data: C;
      };

      // customerId 불일치 → 잘못된 데이터
      if (payload.customerId !== customerId) { setLoadErr(true); return; }
      // mode 불일치
      if (payload.mode !== mode)             { setLoadErr(true); return; }
      // 2분 초과 → 만료
      if (Date.now() - payload.savedAt > 2 * 60 * 1000) { setLoadErr(true); return; }

      // 유효 → guard 설정 후 React 상태에 로드, 스토리지 즉시 삭제
      loadedRef.current = true;
      setC(payload.data);
      localStorage.removeItem(storageKey);
    } catch {
      setLoadErr(true);
    }
  }, [customerId, mode, nonce]);

  useEffect(() => {
    if (c) {
      const name = c["한글"] || `${c["성"] || ""} ${c["명"] || ""}`.trim() || "고객";
      document.title = `${name} — ${MODE_TITLE[mode]}`;
    }
  }, [c, mode]);

  const copy = (text: string, label: string) => {
    navigator.clipboard.writeText(text).catch(() => {});
    setFl(label);
    setTimeout(() => setFl(""), 1000);
  };

  if (loadErr) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", color: "#718096", fontSize: 13, fontFamily: "sans-serif", padding: 24, textAlign: "center" }}>
        고객정보를 불러오지 못했습니다.<br />
        원래 고객관리 화면에서 다시 열어 주세요.
      </div>
    );
  }

  if (!c) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", color: "#A0AEC0", fontSize: 13, fontFamily: "sans-serif" }}>
        고객 정보를 불러오는 중...
      </div>
    );
  }

  // ── Derived values ─────────────────────────────────────────────────────────
  const 성 = c["성"] || "";
  const 명 = c["명"] || "";
  const engName  = [성.trim().toUpperCase(), 명.trim().toUpperCase()].filter(Boolean).join(" ");
  const reg6     = (c["등록증"] || "").trim();
  const reg7     = (c["번호"]   || "").trim();
  const regFull  = reg6 + reg7;
  // 세기(19xx/20xx)는 등록번호 뒷자리 첫 숫자로 판단(공통 helper). 2000년대 출생자 정정.
  const birthdate = deriveBirthDateFromArc(reg6, reg7);
  const tel       = [c["연"], c["락"], c["처"]].filter(Boolean).join("-");
  const telDigits = [c["연"] || "", c["락"] || "", c["처"] || ""].map(s => s.replace(/\D/g, "")).join("");
  const name      = c["한글"] || `${성} ${명}`.trim() || "고객";
  const hl        = (label: string) => (HIGHLIGHT[mode] ?? []).includes(label);

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div style={{ fontFamily: "sans-serif", background: "#fff", minHeight: "100vh", fontSize: 13 }}>
      {/* 헤더 */}
      <div style={{ padding: "10px 14px", borderBottom: "3px solid #D4A843", background: "#FFF9E6", position: "sticky", top: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: "#2D3748" }}>{name}</span>
          <span style={{
            fontSize: 10, fontWeight: 700, padding: "1px 7px", borderRadius: 8,
            background: "#D4A843", color: "#fff",
          }}>
            {MODE_TITLE[mode]}
          </span>
        </div>
        {fl && (
          <div style={{ fontSize: 11, color: "#276749", marginTop: 3 }}>✓ {fl} 복사됨</div>
        )}
      </div>

      {/* 항목 */}
      <div style={{ padding: "12px 10px" }}>

        {/* 이름 */}
        <CopyRow label="한글이름"   value={c["한글"]}  highlight={false} />
        <CopyRow label="영문이름"   value={engName}    highlight={hl("영문이름")} />
        <CopyRow label="국적"       value={c["국적"]}  highlight={hl("국적")} />
        <CopyRow label="체류자격"   value={c["V"]}     highlight={hl("체류자격")} />

        {/* 생년월일 */}
        {birthdate && (
          <CopyRow label="생년월일" value={birthdate} highlight={hl("생년월일")} />
        )}

        {/* 등록번호 */}
        {reg6 && (
          <div style={{
            display: "flex", alignItems: "center", gap: 6, marginBottom: 5,
            padding: "4px 8px", borderRadius: 4,
            borderLeft: hl("외국인등록번호") ? "3px solid #D4A843" : hl("등록번호 앞 6자리") ? "3px solid #D4A843" : "3px solid transparent",
            background: hl("외국인등록번호") || hl("등록번호 앞 6자리") ? "#FFFDF0" : "transparent",
          }}>
            <span style={{ fontSize: 10, color: "#718096", width: 84, flexShrink: 0 }}>등록번호</span>
            <span style={{ fontSize: 12, color: "#1A202C", flex: 1, fontFamily: "monospace" }}>
              {reg6}{reg7 ? `-${reg7}` : ""}
            </span>
            <CopyBtn text={reg6}   label="앞 6자리" onCopy={copy} />
            {reg7 && <CopyBtn text={reg7}   label="뒤 7자리" onCopy={copy} />}
            {reg7 && <CopyBtn text={regFull} label="전체"     onCopy={copy} />}
          </div>
        )}

        {/* 여권 */}
        <CopyRow label="여권번호"   value={c["여권"]}  highlight={hl("여권번호")} />
        <CopyRow label="여권만기일" value={c["만기"]}  highlight={false} />

        {/* 체류만료일 */}
        <CopyRow label="체류만료일" value={c["만기일"]} highlight={hl("체류만료일")} />

        {/* 전화번호 */}
        {tel && (
          <div style={{
            display: "flex", alignItems: "center", gap: 6, marginBottom: 5,
            padding: "4px 8px", borderRadius: 4,
            borderLeft: hl("전화번호") ? "3px solid #D4A843" : "3px solid transparent",
            background: hl("전화번호") ? "#FFFDF0" : "transparent",
          }}>
            <span style={{ fontSize: 10, color: "#718096", width: 84, flexShrink: 0 }}>전화번호</span>
            <span style={{ fontSize: 12, color: "#1A202C", flex: 1, fontFamily: "monospace" }}>{tel}</span>
            <CopyBtn text={tel}       label="복사"          onCopy={copy} />
            <CopyBtn text={telDigits} label="숫자만"        onCopy={copy} />
          </div>
        )}

        {/* 주소 */}
        <CopyRow label="주소" value={c["주소"]} highlight={false} />
      </div>
    </div>
  );
}

// ── Public export (Suspense boundary for useSearchParams) ────────────────────

export default function CustomerCopyPopupPage() {
  return (
    <Suspense fallback={
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", color: "#A0AEC0", fontSize: 13, fontFamily: "sans-serif" }}>
        불러오는 중...
      </div>
    }>
      <Inner />
    </Suspense>
  );
}
