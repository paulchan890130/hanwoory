import type { MetadataRoute } from "next";

const BASE_URL = "https://www.hanwory.com";
const API_URL = process.env.API_URL ?? "http://localhost:8000";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const now = new Date();

  const staticEntries: MetadataRoute.Sitemap = [
    {
      url: `${BASE_URL}/`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 1.0,
    },
    {
      url: `${BASE_URL}/board`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 0.7,
    },
    {
      url: `${BASE_URL}/documents`,
      lastModified: now,
      changeFrequency: "weekly",
      priority: 0.9,
    },
    {
      url: `${BASE_URL}/siheung-immigration-agent`,
      lastModified: now,
      changeFrequency: "monthly",
      priority: 0.8,
    },
    {
      url: `${BASE_URL}/jeongwang-immigration-agent`,
      lastModified: now,
      changeFrequency: "monthly",
      priority: 0.8,
    },
  ];

  let dynamicEntries: MetadataRoute.Sitemap = [];

  try {
    const res = await fetch(`${API_URL}/api/marketing/posts`, {
      next: { revalidate: 3600 },
    });
    if (res.ok) {
      const posts: Array<{ id: string; slug?: string; updated_at?: string }> = await res.json();
      // /api/marketing/posts 는 is_published=TRUE 인 게시물만 반환하므로 추가 필터 불필요
      dynamicEntries = posts.map((post) => ({
        url: `${BASE_URL}/board/${post.slug || post.id}`,
        lastModified: post.updated_at ? new Date(post.updated_at) : now,
        changeFrequency: "weekly" as const,
        priority: 0.6,
      }));
    }
  } catch {
    // API 접근 불가 시 정적 항목만 반환
  }

  return [...staticEntries, ...dynamicEntries];
}
