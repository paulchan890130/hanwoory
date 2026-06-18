import HomeClient from "./HomeClient";
import { getPublishedMarketingPosts } from "@/lib/marketingPosts";

// 요청 시점 서버 렌더(빌드 시 백엔드 미가동 → 빈 배열이 정적으로 구워지는 문제 방지).
// /board 가 searchParams 로 자동 dynamic 인 것과 동일 효과 — sitemap.ts 와 같은 패턴.
export const dynamic = "force-dynamic";

export default async function HomePage() {
  // /board 와 **동일한 공유 함수**로 published 글을 서버에서 가져온다.
  const posts = await getPublishedMarketingPosts();
  return <HomeClient initialPosts={posts} />;
}
