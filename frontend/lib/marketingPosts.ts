// 서버 전용: 공개 마케팅 게시글 단일 조회 함수 (홈/board/documents 공유).
// 임시 진단 로그 포함 — 원인 확인 후 로그는 제거 예정.
//
// 반환 타입은 세 화면(home/board/documents)의 지역 Post 인터페이스를 모두 포괄하는
// superset 이라 각 호출부에 그대로 할당 가능(필드는 문자열로 정규화).

export interface MarketingPost {
  id: string;
  title: string;
  slug: string;
  category: string;
  summary: string;
  content: string;
  tags: string;
  thumbnail_url: string;
  created_at: string;
  updated_at: string;
  is_published: string;
}

import { headers } from "next/headers";

const _s = (v: unknown): string => (v == null ? "" : String(v));

// 서버 SSR fetch base URL 해석 (운영에서 localhost(::1) 로 실패하던 문제 수정).
//  1) API_URL / SERVER_API_URL 이 있으면 사용 — 단 localhost 는 127.0.0.1(IPv4)로 정규화
//     (uvicorn 은 127.0.0.1 바인딩이라 localhost→IPv6 ::1 은 connect 실패).
//  2) 없으면 요청 헤더로 현재 origin 을 만들어 같은 사이트(/api/...)를 호출(Next rewrite→FastAPI).
//  3) 그래도 없으면 development 한정 IPv4 fallback.
function _resolveApiBase(): string {
  const env = (process.env.API_URL || process.env.SERVER_API_URL || "").trim();
  if (env) {
    return env.replace(/\/+$/, "").replace(/\/\/localhost(?=[:/]|$)/, "//127.0.0.1");
  }
  try {
    const h = headers();
    const host = h.get("x-forwarded-host") || h.get("host");
    if (host) {
      const proto = h.get("x-forwarded-proto") || "https";
      return `${proto}://${host}`;
    }
  } catch {
    // headers() 는 요청 스코프(동적 렌더) 밖에서 throw → 무시하고 dev fallback.
  }
  return "http://127.0.0.1:8000";
}

export async function getPublishedMarketingPosts(route: string): Promise<MarketingPost[]> {
  const base = _resolveApiBase();
  const url = `${base}/api/marketing/posts`;
  try {
    const res = await fetch(url, { next: { revalidate: 60 } });
    if (!res.ok) {
      console.error(`[marketing-posts] route=${route} url=${url} status=${res.status} ok=false -> []`);
      return [];
    }
    const data = await res.json();
    const arr = Array.isArray(data) ? data : [];
    console.log(`[marketing-posts] route=${route} url=${url} status=${res.status} length=${arr.length}`);
    return arr.map((p: Record<string, unknown>) => ({
      id: _s(p.id), title: _s(p.title), slug: _s(p.slug), category: _s(p.category),
      summary: _s(p.summary), content: _s(p.content), tags: _s(p.tags),
      thumbnail_url: _s(p.thumbnail_url), created_at: _s(p.created_at),
      updated_at: _s(p.updated_at), is_published: _s(p.is_published),
    }));
  } catch (e) {
    console.error(`[marketing-posts] route=${route} url=${url} error=${(e as Error)?.message ?? e}`);
    return [];
  }
}
