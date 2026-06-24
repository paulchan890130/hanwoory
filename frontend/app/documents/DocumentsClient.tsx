"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { getDocGroup, getDocOrder } from "@/lib/docGroupTags";

interface Post {
  id: string;
  title: string;
  slug: string;
  tags?: string;
}

interface DbGroup {
  id: string;
  group_key: string;
  title: string;
  description: string;
  sort_order: number;
  is_published: string;
}

interface GroupDef {
  id: string;
  group: string;
  slugOrder: string[];
}

// Group scaffold: defines section labels, anchor IDs, and the display order for
// already-imported posts. New posts appear at the end of their group via
// the "doc_group:<id>" tag convention (see migrate_doc_groups.py).
const GROUP_DEFS: GroupDef[] = [
  {
    id: "f1",
    group: "F-1",
    slugOrder: [
      "f1-childcare-support-invitation-documents",
      "f15-invitation-documents",
    ],
  },
  {
    id: "f2",
    group: "F-2",
    slugOrder: [
      "f2-invitation-change-documents",
      "f2-change-minor-documents",
      "f2-registration-extension-spouse-documents",
      "f2-registration-extension-minor-documents",
    ],
  },
  {
    id: "f3",
    group: "F-3",
    slugOrder: [
      "f3-invitation-documents",
      "f3-change-spouse-documents",
      "f3-change-child-documents",
      "f3-registration-extension-spouse-documents",
      "f3-registration-extension-minor-documents",
      "f3r-change-documents",
    ],
  },
  {
    id: "f4",
    group: "F-4",
    slugOrder: [
      "f4-registration-documents",
      "f4-extension-documents",
      "h2-to-f4-change-documents",
      "other-status-to-f4-change-documents",
      "f4-change-age-60-or-test-documents",
      "f4-change-school-student-documents",
      "f4-change-local-manufacturing-documents",
      "f4r-change-documents",
    ],
  },
  {
    id: "f5",
    group: "F-5 / 영주권",
    slugOrder: [
      "f4-two-year-pr-four-insurance-documents",
      "f4-two-year-pr-daily-worker-documents",
      "f4-two-year-pr-property-tax-documents",
      "f4-two-year-pr-assets-documents",
      "f4-two-year-pr-business-owner-documents",
      "h2-four-year-permanent-residence-documents",
      "c38-permanent-residence-parent-nationality-documents",
      "f4-pr-income-70-percent-condition",
    ],
  },
  {
    id: "f6",
    group: "F-6",
    slugOrder: [
      "f6-invitation-documents",
      "f6-change-documents",
      "f6-extension-documents",
    ],
  },
  {
    id: "h2",
    group: "H-2",
    slugOrder: [
      "h2-registration-documents",
      "h2-extension-documents",
      "c38-to-h2-change-documents",
    ],
  },
  {
    id: "nationality",
    group: "국적 / 귀화",
    slugOrder: [
      "naturalization-general-documents",
      "naturalization-simple-marriage-two-years-documents",
      "naturalization-simple-marriage-breakdown-documents",
      "naturalization-marriage-minor-child-documents",
      "naturalization-special-parent-nationality-documents",
      "naturalization-simple-three-years-deceased-parent-documents",
    ],
  },
  {
    id: "china-notarization",
    group: "중국 공증·아포스티유",
    slugOrder: [
      "family-notarization-documents",
      "marriage-notarization-documents",
      "single-remarriage-notarization-documents",
      "criminal-record-notarization-documents",
    ],
  },
];

// GROUP_DEFS 의 group key(id) → slugOrder. DB 그룹 렌더 시에도 알려진 글 정렬·매칭에 재사용.
const SLUG_ORDER_BY_KEY: Record<string, string[]> = Object.fromEntries(
  GROUP_DEFS.map((g) => [g.id, g.slugOrder])
);

export function DocumentsClient({
  posts,
  groups: dbGroups = [],
}: {
  posts: Post[];
  groups?: DbGroup[];
}) {
  const [query, setQuery] = useState("");

  const postBySlug = useMemo(() => {
    const map: Record<string, Post> = {};
    for (const p of posts) {
      if (p.slug) map[p.slug] = p;
    }
    return map;
  }, [posts]);

  // doc_group 태그 기준으로 글을 그룹 key 별로 모은다(신규 추가 글 포함).
  const taggedByGroup = useMemo(() => {
    const map: Record<string, Post[]> = {};
    for (const p of posts) {
      const gid = getDocGroup(p.tags);
      if (!gid) continue;
      if (!map[gid]) map[gid] = [];
      map[gid].push(p);
    }
    return map;
  }, [posts]);

  // 한 그룹(key)의 표시 글 목록: 태그 매칭 + slugOrder fallback, doc_order/slugOrder 순.
  const buildItems = (key: string) => {
    const slugOrder = SLUG_ORDER_BY_KEY[key] || [];
    const slugIndex = new Map(slugOrder.map((s, i) => [s, i]));
    const seen = new Set<string>();
    const collected: Post[] = [];
    // 1) doc_group 태그가 붙은 글
    for (const p of taggedByGroup[key] || []) {
      if (p.slug && seen.has(p.slug)) continue;
      if (p.slug) seen.add(p.slug);
      collected.push(p);
    }
    // 2) 태그가 아직 없어도 slugOrder 에 알려진 글(backfill 전 호환)
    for (const slug of slugOrder) {
      if (seen.has(slug)) continue;
      const p = postBySlug[slug];
      if (p) { seen.add(slug); collected.push(p); }
    }
    collected.sort((a, b) => {
      const oa = getDocOrder(a.tags), ob = getDocOrder(b.tags);
      if (oa != null && ob != null) return oa - ob;
      if (oa != null) return -1;
      if (ob != null) return 1;
      const ia = a.slug ? slugIndex.get(a.slug) : undefined;
      const ib = b.slug ? slugIndex.get(b.slug) : undefined;
      if (ia != null && ib != null) return ia - ib;
      if (ia != null) return -1;
      if (ib != null) return 1;
      return (a.title || "").localeCompare(b.title || "");
    });
    return collected.map((p) => ({ label: p.title, href: `/board/${p.slug}` }));
  };

  const groups = useMemo(() => {
    // DB 중분류가 있으면 그것을 기준(sort_order)으로 렌더. 없으면 하드코딩 GROUP_DEFS fallback.
    if (dbGroups.length > 0) {
      return [...dbGroups]
        .filter((g) => String(g.is_published).toUpperCase() === "TRUE")
        .sort((a, b) => a.sort_order - b.sort_order)
        .map((g) => ({ id: g.group_key, group: g.title || g.group_key, items: buildItems(g.group_key) }))
        .filter((g) => g.items.length > 0);
    }
    return GROUP_DEFS.map((g) => ({ id: g.id, group: g.group, items: buildItems(g.id) }))
      .filter((g) => g.items.length > 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [postBySlug, taggedByGroup, dbGroups]);

  const filteredGroups = useMemo(() => {
    if (!query.trim()) return groups;
    const q = query.trim().toLowerCase();
    return groups
      .map((g) => ({
        ...g,
        items: g.items.filter((item) => item.label.toLowerCase().includes(q)),
      }))
      .filter((g) => g.items.length > 0);
  }, [groups, query]);

  return (
    <>
      {/* ── 검색 ───────────────────────────────────────────────────────── */}
      <div style={{ marginBottom: 32 }}>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="체류자격 또는 업무명으로 검색 (예: F-4, 연장, 귀화...)"
          style={{
            width: "100%",
            padding: "11px 18px",
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

      {/* ── 그룹 그리드 ─────────────────────────────────────────────────── */}
      {filteredGroups.length === 0 ? (
        <p style={{ color: "#999", textAlign: "center", padding: "60px 0", fontSize: 15 }}>
          &apos;{query}&apos; 검색 결과가 없습니다.
        </p>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 20,
          }}
        >
          {filteredGroups.map((group) => (
            <section
              key={group.group}
              id={group.id}
              style={{
                background: "#FAF8F4",
                border: "1px solid #EAE4D8",
                borderRadius: 10,
                padding: "18px 20px 16px",
                scrollMarginTop: 80,
              }}
            >
              <h2
                style={{
                  fontSize: 14,
                  fontWeight: 700,
                  color: "#7A5C10",
                  margin: "0 0 12px",
                  paddingBottom: 10,
                  borderBottom: "1px solid #E4DAC8",
                }}
              >
                {group.group}
              </h2>
              <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
                {group.items.map((item) => (
                  <li key={item.href} style={{ marginBottom: 7 }}>
                    <Link
                      href={item.href}
                      style={{
                        fontSize: 13,
                        color: "#333",
                        textDecoration: "none",
                        display: "flex",
                        alignItems: "baseline",
                        gap: 6,
                        lineHeight: 1.55,
                      }}
                    >
                      <span style={{ color: "#C8A84B", flexShrink: 0, fontSize: 11 }}>›</span>
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </>
  );
}
