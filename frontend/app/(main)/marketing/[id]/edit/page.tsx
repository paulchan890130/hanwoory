"use client";
import { useState, useRef, useEffect } from "react";
import { useRouter, useParams } from "next/navigation";
import { toast } from "sonner";
import { getUser } from "@/lib/auth";
import { marketingApi, type MarketingPost } from "@/lib/api";
import { RichEditor } from "@/components/RichEditor";

const CATEGORIES = [
  "공지사항",
  "업무 안내",
  "준비서류 안내",
  "출입국 업무안내",
  "중국 공증·아포스티유",
  "영주권·귀화",
  "제도 변경",
  "기타",
];

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
  const thumbFileRef = useRef<HTMLInputElement>(null);
  const imgFileRef   = useRef<HTMLInputElement>(null);

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [thumbUploading, setThumbUploading] = useState(false);
  const [imgUploading,   setImgUploading]   = useState(false);
  const [form, setForm] = useState({
    title: "", slug: "", category: "공지사항", summary: "",
    content: "", thumbnail_url: "", is_featured: false, is_published: false,
    image_file_id: "", image_url: "", image_alt: "",
    meta_description: "", tags: "",
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
        image_file_id:    post.image_file_id    || "",
        image_url:        post.image_url        || "",
        image_alt:        post.image_alt        || "",
        meta_description: post.meta_description || "",
        tags:             post.tags             || "",
      });
    } catch {
      toast.error("게시물을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  const set = (k: string, v: string | boolean) =>
    setForm((prev) => ({ ...prev, [k]: v }));

  const uploadImage = async (file: File): Promise<string> => {
    const res = await marketingApi.uploadImage(file);
    return res.data.url;
  };

  const handleThumbUpload = async (file: File) => {
    setThumbUploading(true);
    try {
      const url = await uploadImage(file);
      set("thumbnail_url", url);
      toast.success("썸네일 업로드 완료");
    } catch {
      toast.error("썸네일 업로드에 실패했습니다.");
    } finally {
      setThumbUploading(false);
    }
  };

  const handleImgUpload = async (file: File) => {
    setImgUploading(true);
    try {
      const res = await marketingApi.uploadImage(file);
      set("image_url",     res.data.url);
      set("image_file_id", res.data.file_id);
      toast.success("이미지 업로드 완료");
    } catch {
      toast.error("이미지 업로드 실패");
    } finally {
      setImgUploading(false);
    }
  };

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
  if (loading) return (
    <div style={{ padding: 40, textAlign: "center", color: "#718096" }}>불러오는 중...</div>
  );

  return (
    <div style={{ padding: "32px 24px", maxWidth: 820, margin: "0 auto" }}>
      <div style={{ marginBottom: 24 }}>
        <button
          onClick={() => router.push("/marketing")}
          style={{ fontSize: 13, color: "#718096", background: "none", border: "none", cursor: "pointer", marginBottom: 8 }}
        >
          ← 목록으로
        </button>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: "#1A202C" }}>게시물 수정</h1>
      </div>

      <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 22 }}>
        {/* 제목 */}
        <div>
          <label style={labelStyle}>제목 *</label>
          <input
            value={form.title}
            onChange={(e) => set("title", e.target.value)}
            style={inputStyle}
            placeholder="게시물 제목"
          />
        </div>

        {/* 카테고리 */}
        <div>
          <label style={labelStyle}>카테고리</label>
          <select
            value={form.category}
            onChange={(e) => set("category", e.target.value)}
            style={inputStyle}
          >
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>

        {/* 요약 */}
        <div>
          <label style={labelStyle}>요약 <span style={{ fontWeight: 400, color: "#A0AEC0" }}>(목록에서 보이는 한 줄 설명)</span></label>
          <input
            value={form.summary}
            onChange={(e) => set("summary", e.target.value)}
            style={inputStyle}
            placeholder="독자에게 보여줄 짧은 요약 (1~2문장)"
          />
        </div>

        {/* SEO 설명 */}
        <div>
          <label style={labelStyle}>SEO 설명 <span style={{ fontWeight: 400, color: "#A0AEC0" }}>(비워두면 요약 자동 사용, 160자 이내 권장)</span></label>
          <input
            value={form.meta_description}
            onChange={(e) => set("meta_description", e.target.value)}
            style={inputStyle}
            placeholder="검색엔진에 표시될 설명"
          />
        </div>

        {/* 태그 */}
        <div>
          <label style={labelStyle}>태그 <span style={{ fontWeight: 400, color: "#A0AEC0" }}>(쉼표로 구분)</span></label>
          <input
            value={form.tags}
            onChange={(e) => set("tags", e.target.value)}
            style={inputStyle}
            placeholder="예: F-4, 연장, 서류안내"
          />
        </div>

        {/* 대표 이미지 썸네일 */}
        <div>
          <label style={labelStyle}>대표 이미지 (썸네일)</label>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={form.thumbnail_url}
              onChange={(e) => set("thumbnail_url", e.target.value)}
              style={{ ...inputStyle, flex: 1 }}
              placeholder="이미지 URL 직접 입력 또는 파일 업로드"
            />
            <button
              type="button"
              onClick={() => thumbFileRef.current?.click()}
              disabled={thumbUploading}
              style={{
                padding: "10px 14px", borderRadius: 8, border: "1.5px solid #D4A843",
                background: "#fff", color: "#D4A843", fontWeight: 600, fontSize: 13,
                cursor: thumbUploading ? "not-allowed" : "pointer", whiteSpace: "nowrap",
              }}
            >
              {thumbUploading ? "업로드 중..." : "파일 업로드"}
            </button>
            <input
              ref={thumbFileRef}
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp"
              style={{ display: "none" }}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleThumbUpload(f);
                e.target.value = "";
              }}
            />
          </div>
          {form.thumbnail_url && (
            <div style={{ marginTop: 8 }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={form.thumbnail_url}
                alt="thumbnail preview"
                style={{ maxHeight: 140, maxWidth: "100%", borderRadius: 6, border: "1px solid #E2E8F0", objectFit: "cover" }}
              />
            </div>
          )}
        </div>

        {/* 게시물 이미지 (상세 페이지 표시용) */}
        <div>
          <label style={labelStyle}>게시물 이미지</label>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              value={form.image_url}
              onChange={(e) => set("image_url", e.target.value)}
              style={{ ...inputStyle, flex: 1 }}
              placeholder="이미지 URL 직접 입력 또는 파일 업로드"
            />
            <button
              type="button"
              onClick={() => imgFileRef.current?.click()}
              disabled={imgUploading}
              style={{
                padding: "10px 14px", borderRadius: 8, border: "1.5px solid #D4A843",
                background: "#fff", color: "#D4A843", fontWeight: 600, fontSize: 13,
                cursor: imgUploading ? "not-allowed" : "pointer", whiteSpace: "nowrap",
              }}
            >
              {imgUploading ? "업로드 중..." : "파일 업로드"}
            </button>
            <input
              ref={imgFileRef}
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp"
              style={{ display: "none" }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleImgUpload(f); e.target.value = ""; }}
            />
          </div>
          {form.image_url && (
            <div style={{ marginTop: 8 }}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={form.image_url} alt="preview" style={{ maxHeight: 140, maxWidth: "100%", borderRadius: 6, border: "1px solid #E2E8F0", objectFit: "cover" }} />
            </div>
          )}
        </div>

        {/* 이미지 설명 (alt) */}
        <div>
          <label style={labelStyle}>이미지 설명 <span style={{ fontWeight: 400, color: "#A0AEC0" }}>(접근성·SEO용 대체 텍스트)</span></label>
          <input
            value={form.image_alt}
            onChange={(e) => set("image_alt", e.target.value)}
            style={inputStyle}
            placeholder="이미지를 설명하는 짧은 문구"
          />
        </div>

        {/* 본문 — RichEditor */}
        <div>
          <label style={labelStyle}>본문</label>
          <RichEditor
            value={form.content}
            onChange={(v) => set("content", v)}
            onImageUpload={uploadImage}
          />
        </div>

        {/* 슬러그 */}
        <div>
          <label style={labelStyle}>슬러그 (URL용)</label>
          <input
            value={form.slug}
            onChange={(e) => set("slug", e.target.value)}
            style={inputStyle}
            placeholder="예: 2026-visa-notice-01"
          />
        </div>

        {/* 체크박스 */}
        <div style={{ display: "flex", gap: 28, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <input
              type="checkbox"
              id="is_featured"
              checked={form.is_featured}
              onChange={(e) => set("is_featured", e.target.checked)}
              style={{ width: 16, height: 16, cursor: "pointer" }}
            />
            <label htmlFor="is_featured" style={{ ...labelStyle, marginBottom: 0, cursor: "pointer" }}>
              주요 게시물
            </label>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <input
              type="checkbox"
              id="is_published"
              checked={form.is_published}
              onChange={(e) => set("is_published", e.target.checked)}
              style={{ width: 16, height: 16, cursor: "pointer" }}
            />
            <label htmlFor="is_published" style={{ ...labelStyle, marginBottom: 0, cursor: "pointer" }}>
              홈페이지에 게시
            </label>
          </div>
        </div>

        {/* 버튼 */}
        <div style={{ display: "flex", gap: 12, paddingTop: 8 }}>
          <button
            type="submit"
            disabled={saving}
            style={{
              padding: "12px 28px", borderRadius: 8,
              background: saving ? "#ccc" : "#D4A843",
              color: "#fff", fontWeight: 700, fontSize: 15,
              border: "none", cursor: saving ? "not-allowed" : "pointer",
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
