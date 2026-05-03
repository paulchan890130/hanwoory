"use client";
import { useEffect, useState } from "react";

type C = Record<string, string>;

const STORAGE_KEY = "pinned_customer";

function getDaysUntil(dateStr: string): number | null {
  if (!dateStr) return null;
  const clean = dateStr.replace(/\./g, "-").slice(0, 10);
  const d = new Date(clean);
  if (isNaN(d.getTime())) return null;
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return Math.floor((d.getTime() - now.getTime()) / 86_400_000);
}

function dTag(days: number | null): string | null {
  if (days === null || days > 120) return null;
  if (days < 0) return `만료 ${Math.abs(days)}일`;
  return `D-${days}`;
}

function dColor(days: number | null): string {
  if (days === null) return "#2D3748";
  if (days <= 30) return "#C53030";
  if (days <= 120) return "#9C4221";
  return "#2D3748";
}

function Row({ label, value, mono = false, color }: { label: string; value: string; mono?: boolean; color?: string }) {
  if (!value) return null;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 13, color: color ?? "#2D3748", fontFamily: mono ? "monospace" : undefined }}>
        {value}
      </div>
    </div>
  );
}

function ExpiryRow({ label, value, days }: { label: string; value: string; days: number | null }) {
  if (!value) return null;
  const tag = dTag(days);
  const color = dColor(days);
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 13, color, fontWeight: tag ? 600 : 400 }}>
        {value}
        {tag && (
          <span style={{ marginLeft: 6, fontSize: 11, padding: "1px 6px", borderRadius: 10, background: days! <= 30 ? "#FED7D7" : "#FEEBC8", color }}>
            {tag}
          </span>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: "#D4A843", marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {title}
      </div>
      {children}
    </div>
  );
}

export default function CustomerPopupPage() {
  const [customer, setCustomer] = useState<C | null>(null);

  useEffect(() => {
    const load = () => {
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) setCustomer(JSON.parse(raw));
      } catch { /* ignore */ }
    };
    load();
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) load();
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    if (customer) {
      const name = customer["한글"] || `${customer["성"] || ""} ${customer["명"] || ""}`.trim() || "고객";
      document.title = `${name} — 고객카드`;
    }
  }, [customer]);

  if (!customer) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", color: "#A0AEC0", fontSize: 13, fontFamily: "sans-serif" }}>
        고객 정보 없음
      </div>
    );
  }

  const name = customer["한글"] || `${customer["성"] || ""} ${customer["명"] || ""}`.trim() || "고객";
  const tel = [customer["연"], customer["락"], customer["처"]].filter(Boolean).join("-");
  const regNo = [customer["등록증"], customer["번호"]].filter(Boolean).join(" - ");
  const cardDays = getDaysUntil(customer["만기일"]);
  const passDays = getDaysUntil(customer["만기"]);

  return (
    <div style={{ fontFamily: "sans-serif", background: "#fff", minHeight: "100vh", fontSize: 13 }}>
      {/* 헤더 */}
      <div style={{ padding: "12px 16px", borderBottom: "3px solid #D4A843", background: "#FFF9E6", position: "sticky", top: 0 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: "#2D3748" }}>{name}</div>
        {customer["V"] && (
          <div style={{ fontSize: 11, color: "#9C4221", marginTop: 2 }}>{customer["V"]}</div>
        )}
      </div>

      <div style={{ padding: "14px 16px" }}>
        {/* 기본정보 */}
        <Section title="기본정보">
          <Row label="한글이름" value={customer["한글"]} />
          <Row label="국적" value={customer["국적"]} />
          {(customer["성"] || customer["명"]) && (
            <Row label="영문이름" value={`${customer["성"] || ""} ${customer["명"] || ""}`.trim()} />
          )}
          <Row label="체류자격" value={customer["V"]} color="#2D3748" />
        </Section>

        <div style={{ borderTop: "1px solid #EDF2F7", margin: "10px 0" }} />

        {/* 연락처 */}
        <Section title="연락처">
          <Row label="전화번호" value={tel} />
          <Row label="주소" value={customer["주소"]} />
        </Section>

        <div style={{ borderTop: "1px solid #EDF2F7", margin: "10px 0" }} />

        {/* 등록증 */}
        <Section title="등록증">
          <Row label="등록번호" value={regNo} mono />
          <Row label="발급일" value={customer["발급일"]} />
          <ExpiryRow label="만기일" value={customer["만기일"]} days={cardDays} />
        </Section>

        <div style={{ borderTop: "1px solid #EDF2F7", margin: "10px 0" }} />

        {/* 여권 */}
        <Section title="여권">
          <Row label="여권번호" value={customer["여권"]} mono />
          <Row label="발급일" value={customer["발급"]} />
          <ExpiryRow label="만기일" value={customer["만기"]} days={passDays} />
        </Section>

        {/* 업무정보 */}
        {(customer["위임내역"] || customer["비고"]) && (
          <>
            <div style={{ borderTop: "1px solid #EDF2F7", margin: "10px 0" }} />
            <Section title="업무정보">
              <Row label="위임내역" value={customer["위임내역"]} />
              <Row label="비고" value={customer["비고"]} />
            </Section>
          </>
        )}
      </div>
    </div>
  );
}
