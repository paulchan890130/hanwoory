import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { MarkdownContent } from "@/components/MarkdownContent";

interface Post {
  id: string;
  title: string;
  slug: string;
  category: string;
  summary: string;
  content: string;
  thumbnail_url?: string;
  created_at: string;
  updated_at: string;
}

async function getPost(id: string): Promise<Post | null> {
  try {
    const base = process.env.API_URL || "http://127.0.0.1:8000";
    const res = await fetch(
      `${base}/api/marketing/posts/${encodeURIComponent(id)}`,
      { next: { revalidate: 60 } }
    );
    if (res.status === 404) return null;
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: {
  params: { id: string };
}): Promise<Metadata> {
  const post = await getPost(params.id);
  if (!post) return { title: "게시물 없음 | 한우리행정사사무소" };
  const desc = post.summary || post.content?.replace(/[#*>`[\]!()-]/g, "").slice(0, 120) || "";
  return {
    title: `${post.title} | 한우리행정사사무소`,
    description: desc,
    openGraph: {
      title: post.title,
      description: desc,
      type: "article",
      publishedTime: post.created_at,
      modifiedTime: post.updated_at,
      ...(post.thumbnail_url ? { images: [{ url: post.thumbnail_url }] } : {}),
    },
    alternates: { canonical: `/board/${post.slug || post.id}` },
  };
}

function fmtDate(iso: string) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일`;
}

export default async function BoardDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const post = await getPost(params.id);
  if (!post) notFound();

  return (
    <>
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
          <Link href="/" style={{ color: "#8B6914", fontWeight: 700, fontSize: 15, textDecoration: "none" }}>
            한우리행정사사무소
          </Link>
          <span style={{ color: "#CCC", fontSize: 14 }}>›</span>
          <Link href="/board" style={{ color: "#8B6914", fontSize: 14, textDecoration: "none" }}>
            업무 안내
          </Link>
          <span style={{ color: "#CCC", fontSize: 14 }}>›</span>
          <span
            style={{
              color: "#555", fontSize: 14,
              overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 220,
            }}
          >
            {post.title}
          </span>
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
        <article>
          {/* 게시글 헤더 */}
          <header style={{ marginBottom: 36, borderBottom: "1px solid #EAE4D8", paddingBottom: 24 }}>
            {post.category && (
              <p
                style={{
                  fontSize: 11, fontWeight: 700, color: "#7A5C10",
                  background: "#FBF2DC", display: "inline-block",
                  padding: "4px 12px", borderRadius: 4, margin: "0 0 14px",
                }}
              >
                {post.category}
              </p>
            )}
            <h1
              style={{
                fontSize: 26, fontWeight: 700, color: "#1A1A1A",
                margin: "0 0 14px", lineHeight: 1.4,
              }}
            >
              {post.title}
            </h1>
            <div style={{ display: "flex", gap: 20, fontSize: 13, color: "#888", flexWrap: "wrap" }}>
              <time dateTime={post.created_at}>작성일: {fmtDate(post.created_at)}</time>
              {post.updated_at && post.updated_at !== post.created_at && (
                <time dateTime={post.updated_at}>수정일: {fmtDate(post.updated_at)}</time>
              )}
            </div>
          </header>

          {/* 대표 이미지 (썸네일이 있을 경우) */}
          {post.thumbnail_url && (
            <figure style={{ margin: "0 0 32px", textAlign: "center" }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={post.thumbnail_url}
                alt={`${post.title} 대표 이미지`}
                style={{
                  maxWidth: "100%",
                  maxHeight: 400,
                  borderRadius: 10,
                  objectFit: "cover",
                  display: "inline-block",
                }}
                loading="lazy"
              />
            </figure>
          )}

          {/* 요약 */}
          {post.summary && (
            <p
              style={{
                fontSize: 15, color: "#555", lineHeight: 1.8,
                background: "#F5F0E8", borderLeft: "3px solid #C8A84B",
                padding: "14px 18px", borderRadius: "0 6px 6px 0",
                margin: "0 0 32px",
              }}
            >
              {post.summary}
            </p>
          )}

          {/* 본문 — 마크다운 렌더링 (시맨틱 HTML, AI·크롤러 친화) */}
          <section
            aria-label="본문"
            style={{ fontSize: 15, lineHeight: 1.9, color: "#333" }}
          >
            <MarkdownContent content={post.content} />
          </section>
        </article>

        <footer
          style={{
            marginTop: 48, paddingTop: 24,
            borderTop: "1px solid #EAE4D8",
            display: "flex", gap: 24,
          }}
        >
          <Link href="/board" style={{ color: "#8B6914", fontSize: 14, textDecoration: "none", fontWeight: 500 }}>
            ← 목록으로
          </Link>
          <Link href="/" style={{ color: "#8B6914", fontSize: 14, textDecoration: "none", fontWeight: 500 }}>
            홈으로
          </Link>
        </footer>
      </main>
    </>
  );
}
