"use client";

import { useState, useMemo, type CSSProperties } from "react";
import Link from "next/link";

// 일반 게시판 카테고리 (준비서류 계열 제외)
const CATEGORIES = ["공지사항", "업무 안내", "제도 변경", "기타"];

// 이 카테고리 또는 빈 카테고리만 /board에 표시 — 나머지는 /documents로 분리됨
const BOARD_ONLY = new Set(["공지사항", "업무 안내", "제도 변경", "기타"]);

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

interface Props {
  posts: Post[];
  initialCategory?: string;
}

function fmtDate(iso: string) {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, "0")}.${String(d.getDate()).padStart(2, "0")}`;
}

export function BoardClient({ posts, initialCategory = "" }: Props) {
  const [activeCategory, setActiveCategory] = useState(initialCategory);
  const [query, setQuery] = useState("");

  // 일반 게시판 게시물만 (준비서류 안내 등 제외)
  const boardPosts = useMemo(
    () => posts.filter((p) => !p.category || BOARD_ONLY.has(p.category)),
    [posts]
  );

  const filtered = useMemo(() => {
    let result = boardPosts;
    if (activeCategory) {
      result = result.filter((p) => p.category === activeCategory);
    }
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      result = result.filter(
        (p) =>
          p.title.toLowerCase().includes(q) ||
          (p.summary || "").toLowerCase().includes(q) ||
          (p.category || "").toLowerCase().includes(q) ||
          (p.tags || "").toLowerCase().includes(q)
      );
    }
    return result;
  }, [boardPosts, activeCategory, query]);

  const catBtn = (cat: string): CSSProperties => ({
    fontSize: 13,
    fontWeight: activeCategory === cat ? 700 : 500,
    color: activeCategory === cat ? "#7A5C10" : "#888",
    background: activeCategory === cat ? "#FBF2DC" : "#F5F5F5",
    border: `1px solid ${activeCategory === cat ? "#C8A84B" : "#E0E0E0"}`,
    padding: "5px 14px",
    borderRadius: 99,
    cursor: "pointer",
    whiteSpace: "nowrap",
    fontFamily: "'Noto Sans KR', 'Pretendard', sans-serif",
  });

  return (
    <>
      {/* ── 준비서류 안내 링크 ──────────────────────────────────────────── */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          background: "#FAF8F4",
          border: "1px solid #EAE4D8",
          borderRadius: 8,
          padding: "10px 18px",
          marginBottom: 28,
        }}
      >
        <span style={{ fontSize: 13, color: "#666" }}>
          체류자격별 준비서류를 찾고 계신가요?
        </span>
        <Link
          href="/documents"
          style={{
            fontSize: 13,
            color: "#8B6914",
            fontWeight: 600,
            textDecoration: "none",
            whiteSpace: "nowrap",
          }}
        >
          업무별 준비서류 →
        </Link>
      </div>

      {/* ── 검색 ───────────────────────────────────────────────────────── */}
      <div style={{ marginBottom: 14 }}>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="제목, 카테고리, 태그로 검색..."
          style={{
            width: "100%",
            padding: "10px 16px",
            fontSize: 14,
            border: "1px solid #DDD",
            borderRadius: 8,
            outline: "none",
            fontFamily: "'Noto Sans KR', 'Pretendard', sans-serif",
            boxSizing: "border-box",
            color: "#333",
            background: "#fff",
          }}
        />
      </div>

      {/* ── 카테고리 필터 ───────────────────────────────────────────────── */}
      <nav
        aria-label="카테고리 필터"
        style={{ marginBottom: 32, display: "flex", gap: 8, flexWrap: "wrap" }}
      >
        <button style={catBtn("")} onClick={() => setActiveCategory("")}>
          전체
        </button>
        {CATEGORIES.map((cat) => (
          <button key={cat} style={catBtn(cat)} onClick={() => setActiveCategory(cat)}>
            {cat}
          </button>
        ))}
      </nav>

      {/* ── 게시물 목록 ─────────────────────────────────────────────────── */}
      {filtered.length === 0 ? (
        <p style={{ color: "#999", textAlign: "center", padding: "60px 0", fontSize: 15 }}>
          {query
            ? `'${query}' 검색 결과가 없습니다.`
            : activeCategory
            ? `'${activeCategory}' 카테고리의 게시물이 없습니다.`
            : "등록된 게시물이 없습니다."}
        </p>
      ) : (
        <section aria-label="게시물 목록">
          {filtered.map((post) => (
            <article key={post.id} style={{ borderBottom: "1px solid #EAE4D8", padding: "28px 0" }}>
              <Link
                href={`/board/${post.slug || post.id}`}
                style={{
                  textDecoration: "none",
                  color: "inherit",
                  display: "flex",
                  gap: 20,
                  alignItems: "flex-start",
                }}
              >
                {post.thumbnail_url && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={post.thumbnail_url}
                    alt={post.title}
                    style={{
                      width: 96,
                      height: 72,
                      objectFit: "cover",
                      borderRadius: 6,
                      flexShrink: 0,
                      border: "1px solid #EAE4D8",
                    }}
                    loading="lazy"
                  />
                )}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}
                  >
                    {post.category && (
                      <span
                        style={{
                          fontSize: 11,
                          fontWeight: 700,
                          color: "#7A5C10",
                          background: "#FBF2DC",
                          padding: "3px 10px",
                          borderRadius: 4,
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
                      fontSize: 18,
                      fontWeight: 600,
                      color: "#1A1A1A",
                      margin: "0 0 8px",
                      lineHeight: 1.45,
                    }}
                  >
                    {post.title}
                  </h2>
                  {post.summary && (
                    <p
                      style={{ fontSize: 14, color: "#555", margin: "0 0 12px", lineHeight: 1.7 }}
                    >
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
    </>
  );
}
