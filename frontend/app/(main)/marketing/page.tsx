"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { getUser } from "@/lib/auth";
import { marketingApi, type MarketingPost } from "@/lib/api";

export default function MarketingPage() {
  const router = useRouter();
  const user = getUser();
  const [posts, setPosts] = useState<MarketingPost[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user?.is_admin) {
      router.replace("/dashboard");
      return;
    }
    load();
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const res = await marketingApi.adminList();
      setPosts(res.data);
    } catch {
      toast.error("게시물 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  const handleToggle = async (id: string) => {
    try {
      const res = await marketingApi.togglePublish(id);
      setPosts((prev) =>
        prev.map((p) => (p.id === id ? res.data : p))
      );
      const published = res.data.is_published?.toUpperCase() === "TRUE";
      toast.success(published ? "게시 완료" : "게시 취소");
    } catch {
      toast.error("상태 변경에 실패했습니다.");
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("이 게시물을 삭제하시겠습니까?")) return;
    try {
      await marketingApi.delete(id);
      setPosts((prev) => prev.filter((p) => p.id !== id));
      toast.success("삭제되었습니다.");
    } catch {
      toast.error("삭제에 실패했습니다.");
    }
  };

  const fmtDate = (iso: string) => {
    if (!iso) return "-";
    return new Date(iso).toLocaleDateString("ko-KR");
  };

  if (!user?.is_admin) return null;

  return (
    <div style={{ padding: "32px 24px", maxWidth: 900, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "#1A202C" }}>마케팅 · 홈페이지 게시물</h1>
          <p style={{ fontSize: 13, color: "#718096", marginTop: 4 }}>
            공개 홈페이지(/)에 표시되는 게시물을 관리합니다. 게시 상태인 글만 홈페이지에 표시됩니다.
          </p>
        </div>
        <button
          onClick={() => router.push("/marketing/new")}
          style={{
            padding: "10px 20px", borderRadius: 8, background: "#D4A843",
            color: "#fff", fontWeight: 700, fontSize: 14, border: "none", cursor: "pointer",
          }}
        >
          + 새 게시물
        </button>
      </div>

      {loading ? (
        <p style={{ color: "#718096", textAlign: "center", padding: 40 }}>불러오는 중...</p>
      ) : posts.length === 0 ? (
        <div style={{
          textAlign: "center", padding: 60,
          border: "1px dashed #E2E8F0", borderRadius: 12, color: "#A0AEC0"
        }}>
          <p style={{ fontSize: 16, marginBottom: 8 }}>등록된 게시물이 없습니다.</p>
          <p style={{ fontSize: 13 }}>새 게시물 버튼을 눌러 홈페이지에 표시할 내용을 작성하세요.</p>
        </div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #E2E8F0" }}>
              {["제목", "카테고리", "게시 상태", "작성일", "관리"].map((h) => (
                <th
                  key={h}
                  style={{
                    padding: "10px 12px", textAlign: "left",
                    fontSize: 12, fontWeight: 600, color: "#4A5568",
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {posts.map((post) => {
              const published = post.is_published?.toUpperCase() === "TRUE";
              return (
                <tr
                  key={post.id}
                  style={{ borderBottom: "1px solid #F0F0F0" }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = "#FAFAFA")}
                  onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                >
                  <td style={{ padding: "12px", fontSize: 14, color: "#1A202C", maxWidth: 300 }}>
                    <div style={{ fontWeight: 500 }}>{post.title}</div>
                    {post.summary && (
                      <div style={{ fontSize: 12, color: "#718096", marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {post.summary}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: "12px", fontSize: 13, color: "#718096" }}>
                    {post.category || "-"}
                  </td>
                  <td style={{ padding: "12px" }}>
                    <button
                      onClick={() => handleToggle(post.id)}
                      style={{
                        padding: "4px 12px", borderRadius: 20,
                        fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer",
                        background: published ? "#C6F6D5" : "#FED7D7",
                        color: published ? "#276749" : "#9B2C2C",
                      }}
                    >
                      {published ? "게시 중" : "미게시"}
                    </button>
                  </td>
                  <td style={{ padding: "12px", fontSize: 12, color: "#718096", whiteSpace: "nowrap" }}>
                    {fmtDate(post.created_at)}
                  </td>
                  <td style={{ padding: "12px" }}>
                    <div style={{ display: "flex", gap: 8 }}>
                      <button
                        onClick={() => router.push(`/marketing/${post.id}/edit`)}
                        style={{
                          padding: "4px 10px", borderRadius: 6, fontSize: 12,
                          border: "1px solid #E2E8F0", background: "#fff",
                          cursor: "pointer", color: "#4A5568",
                        }}
                      >
                        수정
                      </button>
                      <button
                        onClick={() => handleDelete(post.id)}
                        style={{
                          padding: "4px 10px", borderRadius: 6, fontSize: 12,
                          border: "1px solid #FED7D7", background: "#fff",
                          cursor: "pointer", color: "#E53E3E",
                        }}
                      >
                        삭제
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
