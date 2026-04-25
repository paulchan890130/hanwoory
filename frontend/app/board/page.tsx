import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "업무 안내 | 한우리행정사사무소",
  description:
    "출입국·체류자격·사증 관련 업무 안내 및 공지사항. 한우리행정사사무소의 최신 안내 정보를 확인하세요.",
  openGraph: {
    title: "업무 안내 | 한우리행정사사무소",
    description: "출입국·체류자격·사증 관련 업무 안내 및 공지사항.",
    type: "website",
  },
};

const BOARD_CATEGORIES = [
  "공지사항",
  "업무 안내",
  "준비서류 안내",
  "출입국 업무안내",
  "중국 공증·아포스티유",
  "영주권·귀화",
  "제도 변경",
  "기타",
];

interface Post {
  id: string;
  title: string;
  slug: string;
  category: string;
  summary: string;
  thumbnail_url?: string;
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

function fmtDate(iso: string) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

export default async function BoardListPage({
  searchParams,
}: {
  searchParams?: { category?: string };
}) {
  const posts = await getPosts();
  const activeCategory = searchParams?.category ?? "";
  const filtered = activeCategory
    ? posts.filter((p) => p.category === activeCategory)
    : posts;

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
          <Link
            href="/"
            style={{ color: "#8B6914", fontWeight: 700, fontSize: 15, textDecoration: "none" }}
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
        <header style={{ marginBottom: 32, borderBottom: "2px solid #C8A84B", paddingBottom: 24 }}>
          <p
            style={{
              fontSize: 12, fontWeight: 700, color: "#8B6914",
              letterSpacing: "0.12em", textTransform: "uppercase",
              margin: "0 0 10px",
            }}
          >
            Notice
          </p>
          <h1 style={{ fontSize: 30, fontWeight: 700, color: "#1A1A1A", margin: "0 0 12px", lineHeight: 1.3 }}>
            업무 안내
          </h1>
          <p style={{ fontSize: 14, color: "#666", margin: 0, lineHeight: 1.7 }}>
            출입국·체류자격·사증 관련 업무 안내 및 최신 제도 변경 사항을 확인하세요.
          </p>
        </header>

        {/* 카테고리 필터 */}
        <nav aria-label="카테고리 필터" style={{ marginBottom: 32, display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Link
            href="/board"
            style={{
              fontSize: 13, fontWeight: activeCategory === "" ? 700 : 500,
              color: activeCategory === "" ? "#7A5C10" : "#888",
              background: activeCategory === "" ? "#FBF2DC" : "#F5F5F5",
              border: `1px solid ${activeCategory === "" ? "#C8A84B" : "#E0E0E0"}`,
              padding: "5px 14px", borderRadius: 99, textDecoration: "none",
              whiteSpace: "nowrap",
            }}
          >
            전체
          </Link>
          {BOARD_CATEGORIES.map((cat) => (
            <Link
              key={cat}
              href={`/board?category=${encodeURIComponent(cat)}`}
              style={{
                fontSize: 13, fontWeight: activeCategory === cat ? 700 : 500,
                color: activeCategory === cat ? "#7A5C10" : "#888",
                background: activeCategory === cat ? "#FBF2DC" : "#F5F5F5",
                border: `1px solid ${activeCategory === cat ? "#C8A84B" : "#E0E0E0"}`,
                padding: "5px 14px", borderRadius: 99, textDecoration: "none",
                whiteSpace: "nowrap",
              }}
            >
              {cat}
            </Link>
          ))}
        </nav>

        {filtered.length === 0 ? (
          <p style={{ color: "#999", textAlign: "center", padding: "60px 0", fontSize: 15 }}>
            {activeCategory ? `'${activeCategory}' 카테고리의 게시물이 없습니다.` : "등록된 게시물이 없습니다."}
          </p>
        ) : (
          <section aria-label="게시물 목록">
            {filtered.map((post) => (
              <article key={post.id} style={{ borderBottom: "1px solid #EAE4D8", padding: "28px 0" }}>
                <Link
                  href={`/board/${post.id}`}
                  style={{ textDecoration: "none", color: "inherit", display: "flex", gap: 20, alignItems: "flex-start" }}
                >
                  {/* 썸네일 (있을 때만) */}
                  {post.thumbnail_url && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={post.thumbnail_url}
                      alt={post.title}
                      style={{
                        width: 96, height: 72, objectFit: "cover",
                        borderRadius: 6, flexShrink: 0,
                        border: "1px solid #EAE4D8",
                      }}
                      loading="lazy"
                    />
                  )}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
                      {post.category && (
                        <span
                          style={{
                            fontSize: 11, fontWeight: 700, color: "#7A5C10",
                            background: "#FBF2DC", padding: "3px 10px", borderRadius: 4,
                          }}
                        >
                          {post.category}
                        </span>
                      )}
                      <time dateTime={post.created_at} style={{ fontSize: 12, color: "#999" }}>
                        {fmtDate(post.updated_at || post.created_at)}
                      </time>
                    </div>
                    <h2
                      style={{
                        fontSize: 18, fontWeight: 600, color: "#1A1A1A",
                        margin: "0 0 8px", lineHeight: 1.45,
                      }}
                    >
                      {post.title}
                    </h2>
                    {post.summary && (
                      <p style={{ fontSize: 14, color: "#555", margin: "0 0 12px", lineHeight: 1.7 }}>
                        {post.summary}
                      </p>
                    )}
                    <span style={{ fontSize: 13, color: "#8B6914", fontWeight: 500 }}>
                      자세히 보기 →
                    </span>
                  </div>
                </Link>
              </article>
            ))}
          </section>
        )}

        <footer style={{ marginTop: 48, paddingTop: 24, borderTop: "1px solid #EAE4D8" }}>
          <Link href="/" style={{ color: "#8B6914", fontSize: 14, textDecoration: "none", fontWeight: 500 }}>
            ← 홈으로
          </Link>
        </footer>
      </main>
    </>
  );
}
