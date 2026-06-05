import type { MetadataRoute } from "next";

const BASE_URL = "https://www.hanwory.com";
// /board, /documents 페이지와 동일한 백엔드 접근 방식 사용.
// (이전 fallback "localhost"는 운영에서 IPv6(::1) 우선 해석으로 FastAPI(IPv4) 연결 실패 가능 → 127.0.0.1 로 통일)
const API_URL = process.env.API_URL || "http://127.0.0.1:8000";

// 빌드 시점(백엔드 미기동)의 빈 결과가 정적 캐시되어 오래된 sitemap이 노출되는 것을 방지.
// 요청 시점에 렌더링하여 운영에서 항상 최신 게시물을 포함시킨다.
export const dynamic = "force-dynamic";

interface MarketingPost {
  id: string;
  slug?: string;
  updated_at?: string;
}

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
    // /api/marketing/posts 는 is_published=TRUE 게시물만 반환하므로 추가 필터 불필요
    // (비공개/초안 게시물 및 /login·/dashboard·/admin·/marketing·/posts 는 애초에 포함되지 않음)
    const res = await fetch(`${API_URL}/api/marketing/posts`, {
      next: { revalidate: 3600 },
    });
    if (!res.ok) {
      // 조용히 정적 5개만 반환하지 않도록 원인 파악용 경고를 남긴다.
      console.warn(
        `[sitemap] GET ${API_URL}/api/marketing/posts 실패: ${res.status} ${res.statusText} — 게시물 상세 URL 없이 정적 항목만 포함됩니다.`
      );
    } else {
      const posts: MarketingPost[] = await res.json();
      dynamicEntries = posts.map((post) => ({
        url: `${BASE_URL}/board/${post.slug || post.id}`,
        lastModified: post.updated_at ? new Date(post.updated_at) : now,
        changeFrequency: "weekly" as const,
        priority: 0.6,
      }));
    }
  } catch (err) {
    // fetch 자체 예외(네트워크/주소 해석 실패 등) — 원인 파악용 경고
    console.warn(
      `[sitemap] GET ${API_URL}/api/marketing/posts 예외: ${
        err instanceof Error ? err.message : String(err)
      } — 게시물 상세 URL 없이 정적 항목만 포함됩니다.`
    );
  }

  return [...staticEntries, ...dynamicEntries];
}
