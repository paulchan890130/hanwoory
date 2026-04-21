"use client";
import { useState, useEffect } from "react";
import { useRouter, useParams } from "next/navigation";
import { toast } from "sonner";
import { getUser } from "@/lib/auth";
import { marketingApi, type MarketingPost } from "@/lib/api";

const CATEGORIES = ["공지사항", "업무 안내", "제도 변경", "기타"];

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "10px 12px", fontSize: 14,
  border: "1.5px solid #E2E8F0", borderRadius: 8,
  background: "#F9FAFB", color: "#1A202C", outline: "none",
  boxSizing: "border-box",
};
const labelStyle: React.CSSProperties = {
  display: "block", fontSize: 13, fontWeight: 600, color: "#2D3748", marginBottom: 6,
};

export default function MarketingEditPage() {
  const router = useRouter();
  const params = useParams();
  const postId = params?.id as string;
  const user = getUser();

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    title: "", slug: "", category: "공지사항", summary: "", content: "",
    thumbnail_url: "", is_featured: false, is_published: false,
  });

  useEffect(() => {
    if (!user?.is_admin) { router.replace("/dashboard"); return; }
    loadPost();
  }, []);

  const loadPost = async () => {
    setLoading(true);
    try {
      const res = await marketingApi.adminList();
      const post: MarketingPost | undefined = res.data.find((p) => p.id === postId);
      if (!post) { toast.error("게시물을 찾을 수 없습니다."); router.push("/marketing"); return; }
      setForm({
        title: post.title || "",
        slug: post.slug || "",
        category: post.category || "공지사항",
        summary: post.summary || "",
        content: post.content || "",
        thumbnail_url: post.thumbnail_url || "",
        is_featured: post.is_featured?.toUpperCase() === "TRUE",
        is_published: post.is_published?.toUpperCase() === "TRUE",
      });
    } catch {
      toast.error("게시물을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  const set = (k: string, v: string | boolean) =>
    setForm((prev) => ({ ...prev, [k]: v }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title.trim()) { toast.error("제목을 입력하세요."); return; }
    setSaving(true);
    try {
      await marketingApi.update(postId, {
        ...form,
        is_published: (form.is_published ? "TRUE" : "FALSE") as string,
        is_featured: (form.is_featured ? "TRUE" : "FALSE") as string,
      });
      toast.success("저장되었습니다.");
      router.push("/marketing");
    } catch {
      toast.error("저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  };

  if (!user?.is_admin) return null;
  if (loading) return <div style={{ padding: 40, textAlign: "center", color: "#718096" }}>불러오는 중...</div>;

  return (
    <div style={{ padding: "32px 24px", maxWidth: 760, margin: "0 auto" }}>
      <div style={{ marginBottom: 24 }}>
        <button
          onClick={() => router.push("/marketing")}
          style={{ fontSize: 13, color: "#718096", background: "none", border: "none", cursor: "pointer", marginBottom: 8 }}
        >
          ← 목록으로
        </button>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: "#1A202C" }}>게시물 수정</h1>
      </div>
      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <label style={labelStyle}>제목 *</label>
          <input value={form.title} onChange={(e) => set("title", e.target.value)}
            style={inputStyle} placeholder="게시물 제목" />
        </div>
        <div>
          <label style={labelStyle}>카테고리</label>
          <select value={form.category} onChange={(e) => set("category", e.target.value)}
            style={{ ...inputStyle }}>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>요약</label>
          <input value={form.summary} onChange={(e) => set("summary", e.target.value)}
            style={inputStyle} placeholder="짧은 요약" />
        </div>
        <div>
          <label style={labelStyle}>본문</label>
          <textarea
            value={form.content}
            onChange={(e) => set("content", e.target.value)}
            style={{ ...inputStyle, minHeight: 200, resize: "vertical" }}
            placeholder="본문 내용을 입력하세요."
          />
        </div>
        <div>
          <label style={labelStyle}>슬러그</label>
          <input value={form.slug} onChange={(e) => set("slug", e.target.value)}
            style={inputStyle} placeholder="예: 2026-notice-01" />
        </div>
        <div style={{ display: "flex", gap: 24 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <input type="checkbox" id="is_featured" checked={form.is_featured}
              onChange={(e) => set("is_featured", e.target.checked)}
              style={{ width: 16, height: 16, cursor: "pointer" }} />
            <label htmlFor="is_featured" style={{ ...labelStyle, marginBottom: 0, cursor: "pointer" }}>
              주요 게시물
            </label>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <input type="checkbox" id="is_published" checked={form.is_published}
              onChange={(e) => set("is_published", e.target.checked)}
              style={{ width: 16, height: 16, cursor: "pointer" }} />
            <label htmlFor="is_published" style={{ ...labelStyle, marginBottom: 0, cursor: "pointer" }}>
              홈페이지에 게시
            </label>
          </div>
        </div>
        <div style={{ display: "flex", gap: 12, paddingTop: 8 }}>
          <button
            type="submit"
            disabled={saving}
            style={{
              padding: "12px 28px", borderRadius: 8, background: saving ? "#ccc" : "#D4A843",
              color: "#fff", fontWeight: 700, fontSize: 15, border: "none",
              cursor: saving ? "not-allowed" : "pointer",
            }}
          >
            {saving ? "저장 중..." : "저장"}
          </button>
          <button
            type="button"
            onClick={() => router.push("/marketing")}
            style={{
              padding: "12px 28px", borderRadius: 8, background: "#fff",
              color: "#4A5568", fontWeight: 600, fontSize: 15,
              border: "1px solid #E2E8F0", cursor: "pointer",
            }}
          >
            취소
          </button>
        </div>
      </form>
    </div>
  );
}
