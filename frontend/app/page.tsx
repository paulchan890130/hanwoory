import HomeClient, { type Post } from "./HomeClient";

// 홈 메인 Notice/업무안내 preview 게시글 — /board 와 동일하게 서버에서 published 글을 가져온다(SSR).
// (이전: 클라이언트 fetch → preview 가 비는 문제. 이제 /board 의 getPosts 와 동일 소스/동작.)
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

export default async function HomePage() {
  const posts = await getPosts();
  return <HomeClient initialPosts={posts} />;
}
