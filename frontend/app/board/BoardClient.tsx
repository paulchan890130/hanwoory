"use client";

import { useState, useMemo, type CSSProperties } from "react";
import Link from "next/link";

const CATEGORIES = [
  "준비서류 안내",
  "출입국 업무안내",
  "중국 공증·아포스티유",
  "영주권·귀화",
  "공지사항",
  "업무 안내",
  "제도 변경",
  "기타",
];

const QUICK_LINKS = [
  {
    group: "체류기간 연장",
    items: [
      { label: "F-4 연장 준비서류", href: "/board/f4-extension-documents" },
      { label: "H-2 연장 준비서류", href: "/board/h2-extension-documents" },
      { label: "F-6 연장 준비서류", href: "/board/f6-extension-documents" },
    ],
  },
  {
    group: "외국인등록",
    items: [
      { label: "F-4 등록 준비서류", href: "/board/f4-registration-documents" },
      { label: "H-2 등록 준비서류", href: "/board/h2-registration-documents" },
      { label: "F-2 미성년자 등록·연장", href: "/board/f2-registration-extension-minor-documents" },
      { label: "F-3 미성년자 등록·연장", href: "/board/f3-registration-extension-minor-documents" },
    ],
  },
  {
    group: "체류자격 변경",
    items: [
      { label: "C-3-8 → H-2", href: "/board/c38-to-h2-change-documents" },
      { label: "H-2 → F-4", href: "/board/h2-to-f4-change-documents" },
      { label: "기타 → F-4", href: "/board/other-status-to-f4-change-documents" },
      { label: "F-3 배우자 변경", href: "/board/f3-change-spouse-documents" },
      { label: "F-3 자녀 변경", href: "/board/f3-change-child-documents" },
    ],
  },
  {
    group: "영주권·귀화",
    items: [
      { label: "F-4 2년 영주권", href: "/board/f4-two-year-pr-four-insurance-documents" },
      { label: "H-2 4년 영주권", href: "/board/h2-four-year-permanent-residence-documents" },
      { label: "일반귀화 준비서류", href: "/board/naturalization-general-documents" },
      { label: "간이귀화 준비서류", href: "/board/naturalization-simple-marriage-two-years-documents" },
      { label: "특별귀화 준비서류", href: "/board/naturalization-special-parent-nationality-documents" },
    ],
  },
  {
    group: "가족초청",
    items: [
      { label: "친족 단기초청", href: "/board/family-short-term-invitation-documents" },
      { label: "F-3 초청 준비서류", href: "/board/f3-invitation-documents" },
      { label: "F-6 초청 준비서류", href: "/board/f6-invitation-documents" },
      { label: "F-1 양육지원 초청", href: "/board/f1-childcare-support-invitation-documents" },
      { label: "F-1-5 초청 준비서류", href: "/board/f15-invitation-documents" },
    ],
  },
  {
    group: "중국 공증·아포스티유",
    items: [
      { label: "친속공증", href: "/board/family-notarization-documents" },
      { label: "결혼공증", href: "/board/marriage-notarization-documents" },
      { label: "무범죄공증", href: "/board/criminal-record-notarization-documents" },
      { label: "미혼·재혼공증", href: "/board/single-remarriage-notarization-documents" },
    ],
  },
];

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

  const filtered = useMemo(() => {
    let result = posts;
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
  }, [posts, activeCategory, query]);

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
      {/* ── 자주 찾는 준비서류 ─────────────────────────────────────────── */}
      <section
        aria-label="자주 찾는 준비서류"
        style={{
          background: "#FAF8F4",
          border: "1px solid #EAE4D8",
          borderRadius: 10,
          padding: "22px 24px 18px",
          marginBottom: 36,
        }}
      >
        <h2
          style={{
            fontSize: 13,
            fontWeight: 700,
            color: "#7A5C10",
            margin: "0 0 18px",
            letterSpacing: "0.04em",
          }}
        >
          자주 찾는 준비서류
        </h2>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
            gap: "20px 28px",
          }}
        >
          {QUICK_LINKS.map((group) => (
            <div key={group.group}>
              <p
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  color: "#8B6914",
                  margin: "0 0 8px",
                  paddingBottom: 6,
                  borderBottom: "1px solid #E4DAC8",
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                }}
              >
                {group.group}
              </p>
              <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
                {group.items.map((item) => (
                  <li key={item.href} style={{ marginBottom: 5 }}>
                    <Link
                      href={item.href}
                      style={{
                        fontSize: 13,
                        color: "#444",
                        textDecoration: "none",
                        display: "flex",
                        alignItems: "baseline",
                        gap: 5,
                        lineHeight: 1.5,
                      }}
                    >
                      <span style={{ color: "#C8A84B", flexShrink: 0, fontSize: 10 }}>›</span>
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

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
                    style={{
                      display: "flex",
                      gap: 10,
                      alignItems: "center",
                      marginBottom: 10,
                    }}
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
                      style={{
                        fontSize: 14,
                        color: "#555",
                        margin: "0 0 12px",
                        lineHeight: 1.7,
                      }}
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
