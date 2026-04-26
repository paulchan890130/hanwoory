import type { Metadata } from "next";
import Link from "next/link";
import { BoardClient } from "./BoardClient";
import { PublicMobileNav } from "@/components/PublicMobileNav";

export const metadata: Metadata = {
  title: "업무 안내",
  description: "출입국·체류자격·사증 관련 업무 안내 및 최신 제도 변경 사항을 확인하세요.",
  openGraph: {
    title: "업무 안내 | 한우리행정사사무소",
    description: "출입국·체류자격·사증 관련 업무 안내 및 최신 제도 변경 사항을 확인하세요.",
    type: "website",
  },
  alternates: { canonical: "https://www.hanwory.com/board" },
};

interface Post {
  id: string;
  title: string;
  slug: string;
  category: string;
  summary: string;
  thumbnail_url?: string;
  tags?: string;
  created_at: string;
  updated_at: string;
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

export default async function BoardListPage({
  searchParams,
}: {
  searchParams?: { category?: string };
}) {
  const posts = await getPosts();
  const initialCategory = searchParams?.category ?? "";

  return (
    <>
      <PublicMobileNav />
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
            maxWidth: 820,
            margin: "0 auto",
            height: 56,
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          <Link
            href="/"
            style={{
              color: "#8B6914",
              fontWeight: 700,
              fontSize: 15,
              textDecoration: "none",
            }}
          >
            한우리행정사사무소
          </Link>
          <span style={{ color: "#CCC", fontSize: 14 }}>›</span>
          <span style={{ color: "#555", fontSize: 14 }}>업무 안내</span>
        </div>
      </nav>

      <main
        style={{
          maxWidth: 820,
          margin: "0 auto",
          padding: "48px 24px 80px",
          fontFamily: "'Noto Sans KR', 'Pretendard', sans-serif",
        }}
      >
        <header
          style={{
            marginBottom: 32,
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
            Notice
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
            업무 안내
          </h1>
          <p style={{ fontSize: 14, color: "#666", margin: 0, lineHeight: 1.7 }}>
            출입국·체류자격·사증 관련 업무 안내 및 최신 제도 변경 사항을 확인하세요.
          </p>
        </header>

        <BoardClient posts={posts} initialCategory={initialCategory} />

        <footer
          style={{ marginTop: 48, paddingTop: 24, borderTop: "1px solid #EAE4D8" }}
        >
          <Link
            href="/"
            style={{
              color: "#8B6914",
              fontSize: 14,
              textDecoration: "none",
              fontWeight: 500,
            }}
          >
            ← 홈으로
          </Link>
        </footer>
      </main>
    </>
  );
}
