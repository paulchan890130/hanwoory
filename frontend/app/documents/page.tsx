import type { Metadata } from "next";
import Link from "next/link";
import { DocumentsClient } from "./DocumentsClient";
import { PublicMobileNav } from "@/components/PublicMobileNav";

interface Post {
  id: string;
  title: string;
  slug: string;
  tags?: string;
}

async function getPosts(): Promise<Post[]> {
  try {
    const base = process.env.API_URL || "http://127.0.0.1:8000";
    const res = await fetch(`${base}/api/marketing/posts`, {
      next: { revalidate: 60 },
    });
    if (!res.ok) return [];
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch {
    return [];
  }
}

export const metadata: Metadata = {
  title: "업무별 준비서류",
  description:
    "F-1, F-2, F-3, F-4, F-5 영주권, F-6, H-2, 국적·귀화, 중국 공증·아포스티유 업무별 준비서류를 체류자격별로 확인할 수 있습니다.",
  openGraph: {
    title: "업무별 준비서류 | 한우리행정사사무소",
    description:
      "F-4, H-2, F-5(영주권), F-6, F-3, 귀화, 중국 공증 등 체류자격별·업무별 준비서류 안내.",
    type: "website",
  },
  alternates: { canonical: "https://www.hanwory.com/documents" },
};

const breadcrumbJsonLd = {
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  itemListElement: [
    { "@type": "ListItem", position: 1, name: "홈", item: "https://www.hanwory.com/" },
    {
      "@type": "ListItem",
      position: 2,
      name: "업무별 준비서류",
      item: "https://www.hanwory.com/documents",
    },
  ],
};

export default async function DocumentsPage() {
  const posts = await getPosts();
  return (
    <>
      <PublicMobileNav />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbJsonLd) }}
      />

      <nav
        aria-label="breadcrumb"
        style={{
          background: "#fff",
          borderBottom: "1px solid #E8E0D4",
          padding: "0 24px",
          fontFamily: "'Noto Sans KR', 'Pretendard', sans-serif",
        }}
      >
        <div
          style={{
            maxWidth: 1040,
            margin: "0 auto",
            height: 56,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <Link
            href="/"
            style={{ color: "#8B6914", fontWeight: 700, fontSize: 15, textDecoration: "none" }}
          >
            한우리행정사사무소
          </Link>
          <span style={{ color: "#CCC", fontSize: 14 }}>›</span>
          <span style={{ color: "#555", fontSize: 14 }}>업무별 준비서류</span>
        </div>
      </nav>

      <main
        style={{
          maxWidth: 1040,
          margin: "0 auto",
          padding: "48px 24px 80px",
          fontFamily: "'Noto Sans KR', 'Pretendard', sans-serif",
        }}
      >
        <header
          style={{
            marginBottom: 36,
            borderBottom: "2px solid #C8A84B",
            paddingBottom: 24,
          }}
        >
          <p
            style={{
              fontSize: 12,
              fontWeight: 700,
              color: "#8B6914",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              margin: "0 0 10px",
            }}
          >
            Documents
          </p>
          <h1
            style={{
              fontSize: 30,
              fontWeight: 700,
              color: "#1A1A1A",
              margin: "0 0 12px",
              lineHeight: 1.3,
            }}
          >
            업무별 준비서류
          </h1>
          <p style={{ fontSize: 14, color: "#555", margin: "0 0 8px", lineHeight: 1.7 }}>
            체류자격별·업무별로 필요한 준비서류를 확인할 수 있습니다.
          </p>
          <p style={{ fontSize: 13, color: "#888", margin: 0, lineHeight: 1.7 }}>
            ※ 개인의 체류이력, 가족관계, 소득자료, 거주지 상황에 따라 추가서류가 요구될 수
            있습니다.
          </p>
        </header>

        <DocumentsClient posts={posts} />

        <footer
          style={{
            marginTop: 48,
            paddingTop: 24,
            borderTop: "1px solid #EAE4D8",
            display: "flex",
            gap: 24,
          }}
        >
          <Link
            href="/"
            style={{ color: "#8B6914", fontSize: 14, textDecoration: "none", fontWeight: 500 }}
          >
            ← 홈으로
          </Link>
          <Link
            href="/board"
            style={{ color: "#8B6914", fontSize: 14, textDecoration: "none", fontWeight: 500 }}
          >
            업무 안내 →
          </Link>
        </footer>
      </main>
    </>
  );
}
