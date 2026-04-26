import type { Metadata } from "next";
import Link from "next/link";
import { PublicMobileNav } from "@/components/PublicMobileNav";

export const metadata: Metadata = {
  title: "시흥 행정사 | 출입국·체류 업무 상담 안내",
  description:
    "시흥 지역 외국인등록, 체류기간 연장, 체류자격 변경, 영주권, 귀화, 가족초청, 중국 공증·아포스티유 업무를 안내합니다.",
  openGraph: {
    title: "시흥 행정사 | 출입국·체류 업무 상담 안내",
    description:
      "시흥 지역 외국인등록, 체류기간 연장, 체류자격 변경, 영주권, 귀화, 가족초청, 중국 공증·아포스티유 업무를 안내합니다.",
    type: "website",
  },
  alternates: { canonical: "https://www.hanwory.com/siheung-immigration-agent" },
};

const BASE_URL = "https://www.hanwory.com";

const breadcrumbJsonLd = {
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  itemListElement: [
    { "@type": "ListItem", position: 1, name: "홈", item: `${BASE_URL}/` },
    { "@type": "ListItem", position: 2, name: "시흥 행정사", item: `${BASE_URL}/siheung-immigration-agent` },
  ],
};

const localBusinessJsonLd = {
  "@context": "https://schema.org",
  "@type": "LocalBusiness",
  name: "한우리행정사사무소",
  url: `${BASE_URL}/`,
  logo: `${BASE_URL}/hanwoori-logo-new.png`,
  telephone: "010-4702-8886",
  address: {
    "@type": "PostalAddress",
    streetAddress: "군서마을로 12, 101호",
    addressLocality: "시흥시",
    addressRegion: "경기도",
    addressCountry: "KR",
  },
  areaServed: ["시흥", "정왕", "정왕동", "안산", "인천", "경기도"],
  knowsAbout: ["행정사", "출입국 업무", "외국인등록", "체류기간 연장", "체류자격 변경", "영주권", "귀화", "가족초청", "중국 공증", "아포스티유"],
};

const FONT = "'Noto Sans KR', 'Pretendard', sans-serif";
const GOLD = "#8B6914";
const GOLD_LIGHT = "#C8A84B";
const BORDER = "#E8E0D4";

export default function SiheungImmigrationAgentPage() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbJsonLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(localBusinessJsonLd) }} />
      <PublicMobileNav />

      {/* 브레드크럼 */}
      <nav
        aria-label="breadcrumb"
        style={{ background: "#fff", borderBottom: `1px solid ${BORDER}`, padding: "0 24px", fontFamily: FONT }}
      >
        <div style={{ maxWidth: 820, margin: "0 auto", height: 56, display: "flex", alignItems: "center", gap: 10 }}>
          <Link href="/" style={{ color: GOLD, fontWeight: 700, fontSize: 15, textDecoration: "none" }}>
            한우리행정사사무소
          </Link>
          <span style={{ color: "#CCC", fontSize: 14 }}>›</span>
          <span style={{ color: "#555", fontSize: 14 }}>시흥 행정사</span>
        </div>
      </nav>

      <main
        style={{
          maxWidth: 820,
          margin: "0 auto",
          padding: "48px 24px 96px",
          fontFamily: FONT,
        }}
      >
        {/* 페이지 헤더 */}
        <header style={{ marginBottom: 40, borderBottom: `2px solid ${GOLD_LIGHT}`, paddingBottom: 28 }}>
          <p style={{ fontSize: 11, fontWeight: 700, color: GOLD, letterSpacing: "0.12em", textTransform: "uppercase", margin: "0 0 10px" }}>
            시흥 · 정왕 출입국 행정사
          </p>
          <h1 style={{ fontSize: 28, fontWeight: 700, color: "#1A1A1A", margin: "0 0 14px", lineHeight: 1.4 }}>
            시흥 행정사 출입국·체류 업무 안내
          </h1>
          <p style={{ fontSize: 15, color: "#555", margin: 0, lineHeight: 1.8 }}>
            한우리행정사사무소는 경기도 시흥시 군서마을로 12, 101호에 위치한 시흥 행정사입니다.
            시흥 출입국 행정사로서 외국인등록, 체류기간 연장, 체류자격 변경, 영주권, 귀화, 가족초청,
            중국 공증·아포스티유 업무를 법적 절차에 따라 처리합니다.
          </p>
        </header>

        {/* 섹션 1: 시흥 지역 출입국 업무 */}
        <section style={{ marginBottom: 40 }} aria-labelledby="siheung-intro">
          <h2 id="siheung-intro" style={{ fontSize: 18, fontWeight: 700, color: "#1A1A1A", margin: "0 0 14px", paddingBottom: 10, borderBottom: `1px solid ${BORDER}` }}>
            시흥 지역 출입국·체류 업무 안내
          </h2>
          <p style={{ fontSize: 14, color: "#444", lineHeight: 1.9, margin: "0 0 12px" }}>
            시흥·정왕 지역에는 중국 동포(조선족) 및 다양한 국적의 외국인이 거주하고 있습니다.
            한우리행정사사무소는 이 지역 외국인 의뢰인의 체류 업무를 전문적으로 지원하는
            시흥 행정사입니다. 출입국관리법에 따른 정확한 서류 검토와 실무 절차 안내를 제공합니다.
          </p>
          <p style={{ fontSize: 14, color: "#444", lineHeight: 1.9, margin: 0 }}>
            시흥 출입국 행정사로서 체류기간 만료 전 연장 신청, 체류자격 변경, 최초 외국인등록,
            영주권(F-5) 신청, 귀화, 가족초청, 중국 공증·아포스티유 등 출입국 관련 업무 전반을 처리합니다.
          </p>
        </section>

        {/* 섹션 2: 주요 업무 */}
        <section style={{ marginBottom: 40 }} aria-labelledby="siheung-services">
          <h2 id="siheung-services" style={{ fontSize: 18, fontWeight: 700, color: "#1A1A1A", margin: "0 0 16px", paddingBottom: 10, borderBottom: `1px solid ${BORDER}` }}>
            주요 업무
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12 }}>
            {[
              { title: "체류기간 연장", desc: "F-4, H-2, F-6 등 체류기간 만료 전 연장 신청 대행. 필요 서류 검토부터 접수까지." },
              { title: "체류자격 변경", desc: "H-2→F-4, F-4→F-5 등 체류자격 변경 신청. 요건 확인 및 서류 준비를 지원합니다." },
              { title: "외국인등록", desc: "최초 외국인등록, 변경신고, 체류지 변경 신고 등 외국인등록 관련 업무." },
              { title: "영주권(F-5) 신청", desc: "F-4 2년, H-2 4년 등 영주권 신청 요건 확인, 소득 증빙 서류 준비 지원." },
              { title: "귀화", desc: "일반귀화, 간이귀화(결혼·혼인단절), 특별귀화 절차 안내 및 서류 준비." },
              { title: "가족초청", desc: "배우자, 자녀, 부모 등 가족 초청(F-1, F-2, F-3, F-6) 신청 대행." },
              { title: "중국 공증·아포스티유", desc: "친속공증, 결혼공증, 무범죄공증, 아포스티유 등 중국 관련 공증 업무." },
            ].map((svc) => (
              <div
                key={svc.title}
                style={{
                  background: "#FAF8F4",
                  border: `1px solid ${BORDER}`,
                  borderRadius: 8,
                  padding: "16px 18px",
                }}
              >
                <p style={{ fontSize: 13, fontWeight: 700, color: GOLD, margin: "0 0 6px" }}>{svc.title}</p>
                <p style={{ fontSize: 13, color: "#555", margin: 0, lineHeight: 1.7 }}>{svc.desc}</p>
              </div>
            ))}
          </div>
        </section>

        {/* 섹션 3: 상담 전 준비 */}
        <section style={{ marginBottom: 40 }} aria-labelledby="siheung-prep">
          <h2 id="siheung-prep" style={{ fontSize: 18, fontWeight: 700, color: "#1A1A1A", margin: "0 0 14px", paddingBottom: 10, borderBottom: `1px solid ${BORDER}` }}>
            상담 전 준비하면 좋은 사항
          </h2>
          <p style={{ fontSize: 14, color: "#444", lineHeight: 1.9, margin: "0 0 12px" }}>
            방문 상담 전 아래 서류를 준비해 두시면 더 정확한 안내를 받으실 수 있습니다.
          </p>
          <ul style={{ margin: 0, padding: "0 0 0 18px", fontSize: 14, color: "#444", lineHeight: 2 }}>
            <li>여권 (유효기간 및 입국 날짜 확인)</li>
            <li>외국인등록증 (보유 시)</li>
            <li>현재 체류 상황 관련 서류 (재직증명서, 임대차계약서, 사업자등록증 등)</li>
            <li>가족관계 관련 서류 (가족초청·귀화·결혼 관련 업무의 경우)</li>
            <li>소득 또는 재산 관련 서류 (영주권 신청의 경우)</li>
          </ul>
          <p style={{ fontSize: 13, color: "#777", margin: "12px 0 0", lineHeight: 1.7 }}>
            ※ 개인의 체류이력, 가족관계, 소득자료, 거주지 상황에 따라 추가 서류가 요구될 수 있습니다.
            전화 또는 방문 상담 시 구체적인 안내를 드립니다.
          </p>
        </section>

        {/* 섹션 4: 준비서류 바로가기 */}
        <section style={{ marginBottom: 40 }} aria-labelledby="siheung-docs">
          <h2 id="siheung-docs" style={{ fontSize: 18, fontWeight: 700, color: "#1A1A1A", margin: "0 0 14px", paddingBottom: 10, borderBottom: `1px solid ${BORDER}` }}>
            업무별 준비서류 바로가기
          </h2>
          <p style={{ fontSize: 14, color: "#444", lineHeight: 1.9, margin: "0 0 16px" }}>
            자주 문의하시는 업무의 준비서류를 아래에서 바로 확인하실 수 있습니다.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[
              { label: "F-4 체류기간 연장 준비서류", href: "/board/f4-extension-documents" },
              { label: "H-2 체류기간 연장 준비서류", href: "/board/h2-extension-documents" },
              { label: "일반귀화 준비서류", href: "/board/naturalization-general-documents" },
              { label: "친속공증 준비서류", href: "/board/family-notarization-documents" },
            ].map((item) => (
              <Link
                key={item.href}
                href={item.href}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "12px 16px",
                  background: "#FAF8F4",
                  border: `1px solid ${BORDER}`,
                  borderRadius: 6,
                  textDecoration: "none",
                  color: "#333",
                  fontSize: 14,
                }}
              >
                <span style={{ color: GOLD_LIGHT, flexShrink: 0 }}>›</span>
                {item.label}
              </Link>
            ))}
            <Link
              href="/documents"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "12px 16px",
                background: "#FAF8F4",
                border: `1px solid ${BORDER}`,
                borderRadius: 6,
                textDecoration: "none",
                color: GOLD,
                fontSize: 14,
                fontWeight: 600,
              }}
            >
              <span style={{ color: GOLD_LIGHT, flexShrink: 0 }}>›</span>
              전체 업무별 준비서류 목록 보기
            </Link>
          </div>
        </section>

        {/* 섹션 5: 사무소 위치 및 문의 */}
        <section
          aria-labelledby="siheung-contact"
          style={{
            background: "#FAF8F4",
            border: `1px solid ${BORDER}`,
            borderRadius: 10,
            padding: "24px 28px",
            marginBottom: 40,
          }}
        >
          <h2 id="siheung-contact" style={{ fontSize: 18, fontWeight: 700, color: "#1A1A1A", margin: "0 0 16px" }}>
            사무소 위치 및 문의
          </h2>
          <dl style={{ margin: 0, display: "grid", gap: "10px 0" }}>
            {[
              { dt: "사무소명", dd: "한우리행정사사무소" },
              { dt: "소재지", dd: "경기도 시흥시 군서마을로 12, 101호" },
              { dt: "문의전화", dd: "010-4702-8886" },
              { dt: "상담 시간", dd: "평일 09:00 ~ 18:00" },
            ].map(({ dt, dd }) => (
              <div key={dt} style={{ display: "flex", gap: 16, fontSize: 14, lineHeight: 1.7 }}>
                <dt style={{ color: "#888", flexShrink: 0, width: 70 }}>{dt}</dt>
                <dd style={{ color: "#333", margin: 0, fontWeight: dt === "문의전화" ? 600 : 400 }}>
                  {dt === "문의전화" ? (
                    <a href="tel:01047028886" style={{ color: GOLD, textDecoration: "none" }}>{dd}</a>
                  ) : dd}
                </dd>
              </div>
            ))}
          </dl>
          <div style={{ marginTop: 18, display: "flex", gap: 12, flexWrap: "wrap" }}>
            <a
              href="tel:01047028886"
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "10px 20px",
                background: GOLD_LIGHT,
                color: "#fff",
                fontWeight: 600,
                fontSize: 14,
                borderRadius: 6,
                textDecoration: "none",
              }}
            >
              전화 상담하기
            </a>
            <Link
              href="/board"
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "10px 20px",
                background: "#fff",
                color: GOLD,
                fontWeight: 600,
                fontSize: 14,
                borderRadius: 6,
                textDecoration: "none",
                border: `1px solid ${BORDER}`,
              }}
            >
              업무 안내 보기
            </Link>
          </div>
        </section>

        {/* 하단 내비 */}
        <footer style={{ paddingTop: 24, borderTop: `1px solid ${BORDER}`, display: "flex", gap: 20, flexWrap: "wrap" }}>
          <Link href="/" style={{ color: GOLD, fontSize: 14, textDecoration: "none", fontWeight: 500 }}>← 홈으로</Link>
          <Link href="/jeongwang-immigration-agent" style={{ color: GOLD, fontSize: 14, textDecoration: "none", fontWeight: 500 }}>정왕 지역 안내 →</Link>
          <Link href="/documents" style={{ color: GOLD, fontSize: 14, textDecoration: "none", fontWeight: 500 }}>업무별 준비서류 →</Link>
        </footer>
      </main>
    </>
  );
}
