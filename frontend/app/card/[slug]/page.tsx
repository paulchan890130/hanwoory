import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Phone, MapPin, FileText } from "lucide-react";

const BASE_URL = "https://www.hanwory.com";

interface PublicCard {
  office_name: string;
  contact_name: string;
  phone: string;
  address: string;
  bio: string;
  work_fields: string[];
  logo_url: string;
  public_slug: string;
}

async function getCard(slug: string): Promise<PublicCard | null> {
  try {
    const base = process.env.API_URL || "http://127.0.0.1:8000";
    const res = await fetch(
      `${base}/api/public/business-card/${encodeURIComponent(slug)}`,
      { next: { revalidate: 60 } }
    );
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

// 테넌트가 입력한 로고 URL 이 있을 때만 절대 URL 로 변환(없으면 null — 특정 사무소 기본 로고 fallback 없음)
function absLogo(u: string): string | null {
  const v = (u || "").trim();
  if (!v) return null;
  return v.startsWith("http") ? v : `${BASE_URL}${v.startsWith("/") ? "" : "/"}${v}`;
}

// "행정사 {이름}" 표기. 이름 없으면 빈 문자열(단독 "행정사" 금지). 이미 "행정사" 포함 시 중복 방지.
function agentLabel(contactName: string): string {
  const n = (contactName || "").trim();
  if (!n) return "";
  return n.includes("행정사") ? n : `행정사 ${n}`;
}

export async function generateMetadata({
  params,
}: {
  params: { slug: string };
}): Promise<Metadata> {
  const card = await getCard(params.slug);
  if (!card) return { title: { absolute: "전자명함" } };
  const name = card.office_name || card.contact_name || "전자명함";
  const descParts = [
    agentLabel(card.contact_name),
    card.phone,
    card.work_fields?.length ? card.work_fields.slice(0, 3).join(", ") : "",
  ].filter(Boolean);
  const desc = descParts.join(" · ") || "전자명함";
  const url = `${BASE_URL}/card/${card.public_slug || params.slug}`;
  const logo = absLogo(card.logo_url);
  return {
    title: { absolute: `${name} 전자명함` },
    description: desc,
    openGraph: {
      title: `${name} 전자명함`,
      description: desc,
      type: "profile",
      siteName: "전자명함",
      url,
      locale: "ko_KR",
      ...(logo ? { images: [{ url: logo }] } : {}),
    },
    twitter: logo
      ? { card: "summary_large_image", title: `${name} 전자명함`, description: desc, images: [logo] }
      : { card: "summary", title: `${name} 전자명함`, description: desc },
    alternates: { canonical: url },
  };
}

// ── 색 토큰 (웜 그레이 + 절제된 골드 포인트) ──
const INK = "#2B2A27";
const SUB = "#6B675E";
const MUTE = "#9A958A";
const LINE = "#EBE6DC";
const GOLD = "#C2A35A";
const GOLD_SOFT = "#F6EFDD";

function InfoRow({ icon, label, children, strong }: {
  icon: React.ReactNode; label: string; children: React.ReactNode; strong?: boolean;
}) {
  return (
    <div style={{ display: "flex", gap: 12, padding: "13px 0", alignItems: "flex-start" }}>
      <div style={{
        width: 34, height: 34, borderRadius: 9, flexShrink: 0,
        background: GOLD_SOFT, color: GOLD,
        display: "flex", alignItems: "center", justifyContent: "center",
      }}>{icon}</div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ fontSize: 11, color: MUTE, fontWeight: 600, marginBottom: 2 }}>{label}</div>
        <div style={{
          fontSize: strong ? 16 : 14, fontWeight: strong ? 700 : 500, color: INK,
          lineHeight: 1.6, wordBreak: "break-word", whiteSpace: "pre-wrap",
        }}>{children}</div>
      </div>
    </div>
  );
}

export default async function PublicCardPage({
  params,
}: {
  params: { slug: string };
}) {
  const card = await getCard(params.slug);
  if (!card) notFound();

  const logo = (card.logo_url || "").trim();
  const telHref = card.phone ? `tel:${card.phone.replace(/[^0-9+]/g, "")}` : "";
  const initial = (card.office_name || card.contact_name || "·").trim().charAt(0);

  return (
    <main style={{
      minHeight: "100vh",
      background: "linear-gradient(180deg, #F4F1EA 0%, #ECE8DF 100%)",
      padding: "32px 14px 48px",
      display: "flex", justifyContent: "center", alignItems: "flex-start",
    }}>
      <div style={{
        width: "100%", maxWidth: 440, background: "#fff",
        border: `1px solid ${LINE}`, borderRadius: 20,
        boxShadow: "0 10px 30px rgba(60,52,30,0.10), 0 2px 6px rgba(0,0,0,0.04)",
        overflow: "hidden",
      }}>
        {/* 상단 포인트 영역 */}
        <div style={{
          background: "linear-gradient(135deg, #F7F1E2 0%, #FBF8F0 100%)",
          borderBottom: `1px solid ${LINE}`,
          padding: "26px 24px 22px", textAlign: "center",
        }}>
          {/* 로고: 입력 URL 있을 때만, 없으면 사무소명 이니셜 원형 */}
          {logo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={logo}
              alt={`${card.office_name || "사무소"} 로고`}
              style={{
                width: 84, height: 84, objectFit: "contain", borderRadius: 16,
                background: "#fff", border: `1px solid ${LINE}`, padding: 8, margin: "0 auto 14px",
                display: "block",
              }}
            />
          ) : (
            <div style={{
              width: 64, height: 64, borderRadius: "50%", margin: "0 auto 14px",
              background: "#fff", border: `1px solid ${GOLD}`, color: GOLD,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 26, fontWeight: 800,
            }}>{initial}</div>
          )}

          {card.office_name && (
            <h1 style={{ fontSize: 23, fontWeight: 800, color: INK, margin: 0, letterSpacing: "-0.01em" }}>
              {card.office_name}
            </h1>
          )}
          {card.contact_name && (
            <div style={{ fontSize: 14, fontWeight: 600, color: SUB, marginTop: 5 }}>
              {agentLabel(card.contact_name)}
            </div>
          )}

          {/* 주력 업무 chips — 입력값 있을 때만 */}
          {card.work_fields?.length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 7, justifyContent: "center", marginTop: 16 }}>
              {card.work_fields.map((w, i) => (
                <span key={i} style={{
                  fontSize: 12.5, fontWeight: 700, color: "#8A6B22",
                  background: "#fff", border: `1px solid ${GOLD}`,
                  borderRadius: 999, padding: "5px 12px",
                }}>{w}</span>
              ))}
            </div>
          )}
        </div>

        {/* 정보 섹션 */}
        {(card.phone || card.address || card.bio) && (
          <div style={{ padding: "8px 24px 4px" }}>
            {card.phone && (
              <InfoRow icon={<Phone size={17} />} label="전화" strong>
                <a href={telHref} style={{ color: INK, textDecoration: "none" }}>{card.phone}</a>
              </InfoRow>
            )}
            {card.phone && (card.address || card.bio) && <div style={{ height: 1, background: LINE }} />}
            {card.address && (
              <InfoRow icon={<MapPin size={17} />} label="주소">{card.address}</InfoRow>
            )}
            {card.address && card.bio && <div style={{ height: 1, background: LINE }} />}
            {card.bio && (
              <InfoRow icon={<FileText size={17} />} label="소개">{card.bio}</InfoRow>
            )}
          </div>
        )}

        {/* CTA — 전화하기(전화번호 있을 때만) */}
        {card.phone && (
          <div style={{ padding: "16px 24px 26px" }}>
            <a href={telHref} style={{
              display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
              width: "100%", boxSizing: "border-box",
              padding: "15px 16px", borderRadius: 12,
              background: GOLD, color: "#fff", fontSize: 16, fontWeight: 800,
              textDecoration: "none", boxShadow: "0 6px 16px rgba(194,163,90,0.35)",
            }}>
              <Phone size={18} /> 전화하기
            </a>
          </div>
        )}
      </div>
    </main>
  );
}
