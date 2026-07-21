"use client";
import { useState, useEffect, useMemo, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { getUser, canManageContent } from "@/lib/auth";
import { marketingApi, docGroupApi, type MarketingPost, type DocGroup } from "@/lib/api";
import { getDocGroup, getDocOrder, setDocGroup, setDocOrder } from "@/lib/docGroupTags";

export default function MarketingDocGroupDetailPage() {
  const router = useRouter();
  const params = useParams();
  const groupKey = String(params?.groupKey || "").toLowerCase();
  const user = getUser();

  const [allPosts, setAllPosts] = useState<MarketingPost[]>([]);
  const [groups, setGroups] = useState<DocGroup[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());

  const fromQuery = `?from=${encodeURIComponent(`/marketing/documents/${groupKey}`)}`;

  useEffect(() => {
    if (!canManageContent(user)) { router.replace("/dashboard"); return; }
    load();
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const [postsRes, groupsRes] = await Promise.all([
        marketingApi.adminList(),
        docGroupApi.adminList(),
      ]);
      setAllPosts(postsRes.data);
      setGroups(groupsRes.data);
    } catch {
      toast.error("불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  const group = useMemo(() => groups.find((g) => g.group_key === groupKey), [groups, groupKey]);

  // 이 중분류 글 — doc_order 우선, 없으면 뒤로(생성일 순).
  const posts = useMemo(() => {
    const mine = allPosts.filter((p) => getDocGroup(p.tags) === groupKey);
    return mine.sort((a, b) => {
      const oa = getDocOrder(a.tags), ob = getDocOrder(b.tags);
      if (oa != null && ob != null) return oa - ob;
      if (oa != null) return -1;
      if (ob != null) return 1;
      return (a.created_at || "").localeCompare(b.created_at || "");
    });
  }, [allPosts, groupKey]);

  const markBusy = (id: string, on: boolean) =>
    setBusyIds((prev) => { const n = new Set(prev); on ? n.add(id) : n.delete(id); return n; });

  const handleToggle = async (post: MarketingPost) => {
    markBusy(post.id, true);
    try {
      const res = await marketingApi.togglePublish(post.id);
      setAllPosts((prev) => prev.map((p) => (p.id === post.id ? res.data : p)));
      toast.success(res.data.is_published?.toUpperCase() === "TRUE" ? "게시 완료" : "게시 취소");
    } catch {
      toast.error("상태 변경 실패");
    } finally {
      markBusy(post.id, false);
    }
  };

  // 순서 변경: 인접 두 글을 바꾼 뒤, 그룹 전체에 doc_order 를 0..n 으로 재기록(slug/제목 불변).
  const reorder = useCallback(async (index: number, dir: -1 | 1) => {
    const target = index + dir;
    if (target < 0 || target >= posts.length) return;
    const ordered = [...posts];
    [ordered[index], ordered[target]] = [ordered[target], ordered[index]];
    setBusyIds(new Set(ordered.map((p) => p.id)));
    try {
      await Promise.all(
        ordered.map((p, i) => {
          const newTags = setDocOrder(p.tags, i);
          if (newTags === (p.tags || "")) return Promise.resolve(null);
          return marketingApi.update(p.id, { tags: newTags });
        })
      );
      await load();
    } catch {
      toast.error("순서 변경에 실패했습니다.");
    } finally {
      setBusyIds(new Set());
    }
  }, [posts]);

  // 다른 중분류로 이동: doc_group 만 교체(doc_order 제거 → 대상 그룹 끝). slug/URL 불변.
  const moveToGroup = async (post: MarketingPost, newKey: string) => {
    if (!newKey || newKey === groupKey) return;
    markBusy(post.id, true);
    try {
      const moved = setDocOrder(setDocGroup(post.tags, newKey), null);
      await marketingApi.update(post.id, { tags: moved });
      toast.success("이동되었습니다.");
      setAllPosts((prev) => prev.map((p) => (p.id === post.id ? { ...p, tags: moved } : p)));
    } catch {
      toast.error("이동에 실패했습니다.");
    } finally {
      markBusy(post.id, false);
    }
  };

  const fmtDate = (iso: string) => (iso ? new Date(iso).toLocaleDateString("ko-KR") : "-");

  if (!canManageContent(user)) return null;

  return (
    <div style={{ padding: "32px 24px", maxWidth: 1000, margin: "0 auto" }}>
      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>

      {/* breadcrumb */}
      <div style={{ fontSize: 13, color: "#A0AEC0", marginBottom: 10 }}>
        <button onClick={() => router.push("/marketing")} style={{ background: "none", border: "none", cursor: "pointer", color: "#718096", padding: 0 }}>마케팅</button>
        {" › "}
        <button onClick={() => router.push("/marketing/documents")} style={{ background: "none", border: "none", cursor: "pointer", color: "#718096", padding: 0 }}>업무별 준비서류</button>
        {" › "}
        <span style={{ color: "#4A5568", fontWeight: 600 }}>{group?.title || groupKey}</span>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "#1A202C" }}>
            {group?.title || groupKey}
            {group && group.is_published?.toUpperCase() !== "TRUE" && (
              <span style={{ marginLeft: 10, fontSize: 12, fontWeight: 600, color: "#9B2C2C", background: "#FED7D7", padding: "2px 10px", borderRadius: 20 }}>비공개</span>
            )}
          </h1>
          <p style={{ fontSize: 13, color: "#718096", marginTop: 4 }}>
            이 중분류의 준비서류 글을 관리합니다. {!group && "(아직 등록되지 않은 중분류 키입니다)"}
          </p>
        </div>
        <button
          onClick={() => router.push(`/marketing/new?doc_group=${encodeURIComponent(groupKey)}&from=${encodeURIComponent(`/marketing/documents/${groupKey}`)}`)}
          style={{ padding: "10px 18px", borderRadius: 8, background: "var(--hw-gold-soft-bg)", color: "var(--hw-gold-soft-text)", fontWeight: 700, fontSize: 14, border: "1px solid var(--hw-gold-soft-border)", cursor: "pointer", whiteSpace: "nowrap" }}
        >
          + 새 준비서류 글
        </button>
      </div>

      {loading ? (
        <p style={{ color: "#718096", textAlign: "center", padding: 40 }}>불러오는 중...</p>
      ) : posts.length === 0 ? (
        <div style={{ textAlign: "center", padding: 60, border: "1px dashed #E2E8F0", borderRadius: 12, color: "#A0AEC0" }}>
          <p style={{ fontSize: 15 }}>이 중분류에 연결된 글이 없습니다.</p>
        </div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #E2E8F0" }}>
              {["순서", "제목 / 공개 URL", "게시 상태", "수정일", "이동", "관리"].map((h) => (
                <th key={h} style={{ padding: "10px 12px", textAlign: "left", fontSize: 12, fontWeight: 600, color: "#4A5568" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {posts.map((post, i) => {
              const published = post.is_published?.toUpperCase() === "TRUE";
              const busy = busyIds.has(post.id);
              return (
                <tr key={post.id} style={{ borderBottom: "1px solid #F0F0F0", opacity: published ? 1 : 0.7 }}>
                  <td style={{ padding: "12px", width: 70 }}>
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      <button onClick={() => reorder(i, -1)} disabled={busy || i === 0} style={{ cursor: i === 0 ? "default" : "pointer", border: "1px solid #E2E8F0", background: "#fff", borderRadius: 4, fontSize: 11, padding: "1px 6px", opacity: i === 0 ? 0.4 : 1 }}>▲</button>
                      <button onClick={() => reorder(i, 1)} disabled={busy || i === posts.length - 1} style={{ cursor: i === posts.length - 1 ? "default" : "pointer", border: "1px solid #E2E8F0", background: "#fff", borderRadius: 4, fontSize: 11, padding: "1px 6px", opacity: i === posts.length - 1 ? 0.4 : 1 }}>▼</button>
                    </div>
                  </td>
                  <td style={{ padding: "12px", fontSize: 14, color: "#1A202C", maxWidth: 360 }}>
                    <div style={{ fontWeight: 500 }}>{post.title}</div>
                    <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: 2 }}>/board/{post.slug || post.id}</div>
                  </td>
                  <td style={{ padding: "12px" }}>
                    <button
                      onClick={() => handleToggle(post)}
                      disabled={busy}
                      style={{
                        padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: 600, border: "none",
                        cursor: busy ? "not-allowed" : "pointer", opacity: busy ? 0.6 : 1,
                        background: published ? "#C6F6D5" : "#FED7D7", color: published ? "#276749" : "#9B2C2C",
                        display: "inline-flex", alignItems: "center", gap: 4,
                      }}
                    >
                      {busy && <Loader2 size={11} style={{ animation: "spin 0.8s linear infinite" }} />}
                      {published ? "게시 중" : "미게시"}
                    </button>
                  </td>
                  <td style={{ padding: "12px", fontSize: 12, color: "#718096", whiteSpace: "nowrap" }}>{fmtDate(post.updated_at || post.created_at)}</td>
                  <td style={{ padding: "12px" }}>
                    <select
                      value={groupKey}
                      onChange={(e) => moveToGroup(post, e.target.value)}
                      disabled={busy}
                      style={{ fontSize: 12, padding: "4px 8px", border: "1px solid #E2E8F0", borderRadius: 6, background: "#fff", color: "#4A5568", cursor: "pointer", maxWidth: 140 }}
                    >
                      {groups.map((g) => (
                        <option key={g.id} value={g.group_key}>{g.title || g.group_key}</option>
                      ))}
                    </select>
                  </td>
                  <td style={{ padding: "12px" }}>
                    <button
                      onClick={() => router.push(`/marketing/${post.id}/edit${fromQuery}`)}
                      style={{ padding: "4px 10px", borderRadius: 6, fontSize: 12, border: "1px solid #E2E8F0", background: "#fff", cursor: "pointer", color: "#4A5568" }}
                    >
                      수정
                    </button>
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
