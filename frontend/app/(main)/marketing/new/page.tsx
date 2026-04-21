"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { getUser } from "@/lib/auth";
import { marketingApi } from "@/lib/api";

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

export default function MarketingNewPage() {
  const router = useRouter();
  const user = getUser();
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    title: "", slug: "", category: "공지사항", summary: "", content: "",
    thumbnail_url: "", is_featured: false,
  });

  useEffect(() => {
    if (!user?.is_admin) router.replace("/dashboard");
  }, []);

  const set = (k: string, v: string | boolean) =>
    setForm((prev) => ({ ...prev, [k]: v }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title.trim()) { toast.error("제목을 입력하세요."); return; }
    setLoading(true);
    try {
      await marketingApi.create({
        ...form,
        is_featured: form.is_featured ? "TRUE" : "FALSE",
      });
      toast.success("게시물이 저장되었습니다. (미게시 상태)");
      router.push("/marketing");
    } catch {
      toast.error("저장에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  };

  if (!user?.is_admin) return null;

  return (
    <div style={{ padding: "32px 24px", maxWidth: 760, margin: "0 auto" }}>
      <div style={{ marginBottom: 24 }}>
        <button
          onClick={() => router.push("/marketing")}
          style={{ fontSize: 13, color: "#718096", background: "none", border: "none", cursor: "pointer", marginBottom: 8 }}
        >
          ← 목록으로
        </button>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: "#1A202C" }}>새 게시물 작성</h1>
        <p style={{ fontSize: 13, color: "#718096", marginTop: 4 }}>
          작성 후 목록에서 "게시" 버튼을 눌러야 홈페이지에 공개됩니다.
        </p>
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
          <label style={labelStyle}>요약 (목록에서 보이는 한 줄 설명)</label>
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
          <label style={labelStyle}>슬러그 (URL용, 비워두면 제목으로 자동 설정)</label>
          <input value={form.slug} onChange={(e) => set("slug", e.target.value)}
            style={inputStyle} placeholder="예: 2026-notice-01" />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <input
            type="checkbox"
            id="is_featured"
            checked={form.is_featured}
            onChange={(e) => set("is_featured", e.target.checked)}
            style={{ width: 16, height: 16, cursor: "pointer" }}
          />
          <label htmlFor="is_featured" style={{ ...labelStyle, marginBottom: 0, cursor: "pointer" }}>
            주요 게시물로 표시
          </label>
        </div>
        <div style={{ display: "flex", gap: 12, paddingTop: 8 }}>
          <button
            type="submit"
            disabled={loading}
            style={{
              padding: "12px 28px", borderRadius: 8, background: loading ? "#ccc" : "#D4A843",
              color: "#fff", fontWeight: 700, fontSize: 15, border: "none",
              cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "저장 중..." : "저장"}
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
