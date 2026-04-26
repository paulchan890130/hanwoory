import type { Metadata } from "next";
import Link from "next/link";
import { PublicMobileNav } from "@/components/PublicMobileNav";

export const metadata: Metadata = {
  title: "정왕 행정사 | 외국인 체류·비자 업무 안내",
  description:
    "정왕·정왕동 인근 외국인등록, 체류기간 연장, 체류자격 변경, 영주권, 귀화, 중국 공증·아포스티유 업무를 안내합니다.",
  openGraph: {
    title: "정왕 행정사 | 외국인 체류·비자 업무 안내",
    description:
      "정왕·정왕동 인근 외국인등록, 체류기간 연장, 체류자격 변경, 영주권, 귀화, 중국 공증·아포스티유 업무를 안내합니다.",
    type: "website",
  },
  alternates: { canonical: "https://www.hanwory.com/jeongwang-immigration-agent" },
};

const BASE_URL = "https://www.hanwory.com";

const breadcrumbJsonLd = {
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  itemListElement: [
    { "@type": "ListItem", position: 1, name: "홈", item: `${BASE_URL}/` },
    { "@type": "ListItem", position: 2, name: "정왕 행정사", item: `${BASE_URL}/jeongwang-immigration-agent` },
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
    streetAddress: "군로서마을로 12, 1층",
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

export default function JeongwangImmigrationAgentPage() {
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
          <span style={{ color: "#555", fontSize: 14 }}>정왕 행정사</span>
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
            정왕 · 정왕동 출입국 행정사
          </p>
          <h1 style={{ fontSize: 28, fontWeight: 700, color: "#1A1A1A", margin: "0 0 14px", lineHeight: 1.4 }}>
            정왕 행정사 외국인 체류·비자 업무 안내
          </h1>
          <p style={{ fontSize: 15, color: "#555", margin: 0, lineHeight: 1.8 }}>
            한우리행정사사무소는 경기도 시흥시 군로서마을로 12, 1층에 위치한 정왕동 행정사입니다.
            정왕 출입국 행정사로서 정왕·정왕동 인근 외국인 의뢰인의 외국인등록, 체류기간 연장,
            체류자격 변경, 영주권, 귀화, 중국 공증·아포스티유 업무를 처리합니다.
          </p>
        </header>

        {/* 섹션 1: 정왕·정왕동 출입국 업무 */}
        <section style={{ marginBottom: 40 }} aria-labelledby="jeongwang-intro">
          <h2 id="jeongwang-intro" style={{ fontSize: 18, fontWeight: 700, color: "#1A1A1A", margin: "0 0 14px", paddingBottom: 10, borderBottom: `1px solid ${BORDER}` }}>
            정왕·정왕동 인근 출입국 업무 안내
          </h2>
          <p style={{ fontSize: 14, color: "#444", lineHeight: 1.9, margin: "0 0 12px" }}>
            정왕·정왕동 지역은 외국인 거주 인구가 많은 시흥시 핵심 지역 중 하나입니다.
            한우리행정사사무소는 이 지역을 주요 서비스 권역으로 하는 정왕 행정사로서,
            정왕동 인근 외국인 의뢰인의 체류 관련 업무를 전문적으로 지원합니다.
          </p>
          <p style={{ fontSize: 14, color: "#444", lineHeight: 1.9, margin: 0 }}>
            정왕동 행정사, 정왕 출입국 행정사로서 체류기간 연장, 체류자격 변경, 외국인등록,
            영주권(F-5) 신청, 귀화, 중국 공증·아포스티유 등 다양한 출입국 민원 업무를 처리합니다.
            중국어 의사소통이 가능하여 중국 국적 의뢰인도 편하게 상담받으실 수 있습니다.
          </p>
        </section>

        {/* 섹션 2: 주요 업무 */}
        <section style={{ marginBottom: 40 }} aria-labelledby="jeongwang-services">
          <h2 id="jeongwang-services" style={{ fontSize: 18, fontWeight: 700, color: "#1A1A1A", margin: "0 0 16px", paddingBottom: 10, borderBottom: `1px solid ${BORDER}` }}>
            주요 업무
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 12 }}>
            {[
              { title: "체류기간 연장", desc: "F-4, H-2, F-6 등 체류자격별 연장 신청. 서류 준비부터 접수까지 일괄 처리합니다." },
              { title: "체류자격 변경", desc: "H-2→F-4, F-4→F-5 등 체류자격 변경. 요건 확인 및 필요 서류를 안내합니다." },
              { title: "외국인등록", desc: "최초 외국인등록, 체류지 변경 신고, 등록증 재발급 등 외국인등록 업무." },
              { title: "영주권(F-5) 신청", desc: "F-4 2년 이상, H-2 4년 이상 체류자 대상 영주권 신청. 소득 증빙 서류 검토 지원." },
              { title: "귀화", desc: "일반귀화, 간이귀화, 혼인귀화, 특별귀화 등 국적 취득 절차 안내 및 서류 준비." },
              { title: "중국 공증·아포스티유", desc: "친속공증, 결혼공증, 무범죄공증, 아포스티유 등 중국 관련 공증 업무 처리." },
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

        {/* 섹션 3: 상담 준비 */}
        <section style={{ marginBottom: 40 }} aria-labelledby="jeongwang-prep">
          <h2 id="jeongwang-prep" style={{ fontSize: 18, fontWeight: 700, color: "#1A1A1A", margin: "0 0 14px", paddingBottom: 10, borderBottom: `1px solid ${BORDER}` }}>
            상담 전 준비하면 좋은 사항
          </h2>
          <p style={{ fontSize: 14, color: "#444", lineHeight: 1.9, margin: "0 0 12px" }}>
            방문 상담 전 아래 서류를 준비해 두시면 보다 정확한 안내를 받으실 수 있습니다.
          </p>
          <ul style={{ margin: 0, padding: "0 0 0 18px", fontSize: 14, color: "#444", lineHeight: 2 }}>
            <li>여권 (유효기간 및 최근 입국 날짜 확인)</li>
            <li>외국인등록증 (보유 시)</li>
            <li>현재 체류 상황 관련 서류 (재직증명서, 임대차계약서, 사업자등록증 등)</li>
            <li>가족관계 서류 (결혼, 자녀, 귀화 관련 업무의 경우)</li>
            <li>소득·재산 관련 서류 (영주권, 특정 귀화 요건 확인에 필요)</li>
          </ul>
          <p style={{ fontSize: 13, color: "#777", margin: "12px 0 0", lineHeight: 1.7 }}>
            ※ 개인의 체류이력, 가족관계, 소득자료에 따라 추가 서류가 필요할 수 있습니다.
            전화 상담 시 상황에 맞는 구체적인 안내를 드립니다.
          </p>
        </section>

        {/* 섹션 4: 준비서류 바로가기 */}
        <section style={{ marginBottom: 40 }} aria-labelledby="jeongwang-docs">
          <h2 id="jeongwang-docs" style={{ fontSize: 18, fontWeight: 700, color: "#1A1A1A", margin: "0 0 14px", paddingBottom: 10, borderBottom: `1px solid ${BORDER}` }}>
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
          aria-labelledby="jeongwang-contact"
          style={{
            background: "#FAF8F4",
            border: `1px solid ${BORDER}`,
            borderRadius: 10,
            padding: "24px 28px",
            marginBottom: 40,
          }}
        >
          <h2 id="jeongwang-contact" style={{ fontSize: 18, fontWeight: 700, color: "#1A1A1A", margin: "0 0 16px" }}>
            사무소 위치 및 문의
          </h2>
          <dl style={{ margin: 0, display: "grid", gap: "10px 0" }}>
            {[
              { dt: "사무소명", dd: "한우리행정사사무소" },
              { dt: "소재지", dd: "경기도 시흥시 군로서마을로 12, 1층" },
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
          <Link href="/siheung-immigration-agent" style={{ color: GOLD, fontSize: 14, textDecoration: "none", fontWeight: 500 }}>시흥 지역 안내 →</Link>
          <Link href="/documents" style={{ color: GOLD, fontSize: 14, textDecoration: "none", fontWeight: 500 }}>업무별 준비서류 →</Link>
        </footer>
      </main>
    </>
  );
}
