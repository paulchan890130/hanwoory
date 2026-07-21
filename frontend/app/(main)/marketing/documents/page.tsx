"use client";
import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { getUser, canManageContent } from "@/lib/auth";
import { docGroupApi, marketingApi, type DocGroup, type MarketingPost } from "@/lib/api";
import { isUnclassifiedPrep } from "@/lib/docGroupTags";

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "9px 11px", fontSize: 13,
  border: "1.5px solid #E2E8F0", borderRadius: 8,
  background: "#F9FAFB", color: "#1A202C", outline: "none", boxSizing: "border-box",
};

export default function MarketingDocGroupsPage() {
  const router = useRouter();
  const user = getUser();
  const [groups, setGroups] = useState<DocGroup[]>([]);
  const [unclassified, setUnclassified] = useState<MarketingPost[]>([]);  // 미분류 준비서류
  const [loading, setLoading] = useState(true);
  const [busyIds, setBusyIds] = useState<Set<string>>(new Set());

  // 새 중분류 입력
  const [showAdd, setShowAdd] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [creating, setCreating] = useState(false);

  // 인라인 편집
  const [editId, setEditId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editOrder, setEditOrder] = useState("0");

  useEffect(() => {
    if (!canManageContent(user)) { router.replace("/dashboard"); return; }
    load();
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const [gr, pr] = await Promise.all([docGroupApi.adminList(), marketingApi.adminList()]);
      setGroups(gr.data);
      // 미분류 준비서류: 준비서류 계열 카테고리 + doc_group 미지정. 공개 /documents 에는 노출 안 함.
      setUnclassified(pr.data.filter((p) => isUnclassifiedPrep(p)));
    } catch {
      toast.error("중분류 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  const markBusy = (id: string, on: boolean) =>
    setBusyIds((prev) => { const n = new Set(prev); on ? n.add(id) : n.delete(id); return n; });

  const handleCreate = async () => {
    const key = newKey.trim().toLowerCase();
    if (!/^[a-z0-9][a-z0-9-]*$/.test(key)) {
      toast.error("키는 소문자/숫자/하이픈만 사용할 수 있습니다 (예: f4, china-notarization).");
      return;
    }
    if (!newTitle.trim()) { toast.error("중분류명을 입력하세요."); return; }
    setCreating(true);
    try {
      await docGroupApi.create({ group_key: key, title: newTitle.trim(), description: newDesc.trim(), is_published: true });
      toast.success("중분류가 추가되었습니다.");
      setNewKey(""); setNewTitle(""); setNewDesc(""); setShowAdd(false);
      load();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "추가에 실패했습니다.");
    } finally {
      setCreating(false);
    }
  };

  const startEdit = (g: DocGroup) => {
    setEditId(g.id); setEditTitle(g.title); setEditDesc(g.description); setEditOrder(String(g.sort_order));
  };

  const saveEdit = async (id: string) => {
    markBusy(id, true);
    try {
      await docGroupApi.update(id, {
        title: editTitle.trim(),
        description: editDesc.trim(),
        sort_order: parseInt(editOrder, 10) || 0,
      });
      toast.success("저장되었습니다.");
      setEditId(null);
      load();
    } catch {
      toast.error("저장에 실패했습니다.");
    } finally {
      markBusy(id, false);
    }
  };

  const handleToggle = async (g: DocGroup) => {
    markBusy(g.id, true);
    try {
      const res = await docGroupApi.togglePublish(g.id);
      setGroups((prev) => prev.map((x) => (x.id === g.id ? { ...x, ...res.data } : x)));
      toast.success(res.data.is_published?.toUpperCase() === "TRUE" ? "공개로 전환" : "비공개로 전환");
    } catch {
      toast.error("상태 변경에 실패했습니다.");
    } finally {
      markBusy(g.id, false);
    }
  };

  if (!canManageContent(user)) return null;

  return (
    <div style={{ padding: "32px 24px", maxWidth: 980, margin: "0 auto" }}>
      <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>

      <button
        onClick={() => router.push("/marketing")}
        style={{ fontSize: 13, color: "#718096", background: "none", border: "none", cursor: "pointer", marginBottom: 10 }}
      >
        ← 마케팅 홈
      </button>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
        <div>
          <div style={{ fontSize: 13, color: "#A0AEC0", marginBottom: 4 }}>마케팅 › 업무별 준비서류</div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "#1A202C" }}>업무별 준비서류 — 중분류 관리</h1>
          <p style={{ fontSize: 13, color: "#718096", marginTop: 4 }}>
            공개 홈페이지 /documents 의 중분류입니다. 중분류를 클릭하면 하위 준비서류 글을 관리합니다.
          </p>
        </div>
        <button
          onClick={() => setShowAdd((v) => !v)}
          style={{ padding: "10px 18px", borderRadius: 8, background: "var(--hw-gold-soft-bg)", color: "var(--hw-gold-soft-text)", fontWeight: 700, fontSize: 14, border: "1px solid var(--hw-gold-soft-border)", cursor: "pointer", whiteSpace: "nowrap" }}
        >
          + 중분류 추가
        </button>
      </div>

      {/* v1 안내 */}
      <div style={{ background: "#FFF8E6", border: "1px solid #F0E0B0", borderRadius: 8, padding: "10px 14px", fontSize: 12.5, color: "#7A5C10", marginBottom: 20 }}>
        v1에서는 중분류 <strong>삭제</strong>를 지원하지 않습니다. 노출을 끄려면 <strong>비공개</strong>로 전환하세요(하위 글·URL은 보존되며 다시 공개하면 그대로 복구됩니다).
      </div>

      {showAdd && (
        <div style={{ border: "1px solid #E2E8F0", borderRadius: 10, padding: 18, marginBottom: 22, background: "#fff", display: "flex", flexDirection: "column", gap: 12 }}>
          <h3 style={{ fontSize: 15, fontWeight: 700, color: "#1A202C", margin: 0 }}>새 중분류</h3>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 180px" }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: "#4A5568" }}>키 (group_key, 변경 불가)</label>
              <input value={newKey} onChange={(e) => setNewKey(e.target.value)} style={inputStyle} placeholder="예: f4, china-notarization" />
            </div>
            <div style={{ flex: "1 1 180px" }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: "#4A5568" }}>중분류명</label>
              <input value={newTitle} onChange={(e) => setNewTitle(e.target.value)} style={inputStyle} placeholder="예: F-4" />
            </div>
          </div>
          <div>
            <label style={{ fontSize: 12, fontWeight: 600, color: "#4A5568" }}>설명 (선택)</label>
            <input value={newDesc} onChange={(e) => setNewDesc(e.target.value)} style={inputStyle} placeholder="보조 문구" />
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={handleCreate} disabled={creating} style={{ padding: "9px 20px", borderRadius: 8, background: creating ? "#ccc" : "var(--hw-gold-soft-bg)", color: creating ? "#fff" : "var(--hw-gold-soft-text)", fontWeight: 700, fontSize: 13, border: creating ? "none" : "1px solid var(--hw-gold-soft-border)", cursor: creating ? "not-allowed" : "pointer" }}>
              {creating ? "추가 중..." : "추가"}
            </button>
            <button onClick={() => setShowAdd(false)} style={{ padding: "9px 20px", borderRadius: 8, background: "#fff", color: "#4A5568", fontWeight: 600, fontSize: 13, border: "1px solid #E2E8F0", cursor: "pointer" }}>취소</button>
          </div>
        </div>
      )}

      {loading ? (
        <p style={{ color: "#718096", textAlign: "center", padding: 40 }}>불러오는 중...</p>
      ) : groups.length === 0 ? (
        <div style={{ textAlign: "center", padding: 60, border: "1px dashed #E2E8F0", borderRadius: 12, color: "#A0AEC0" }}>
          <p style={{ fontSize: 15 }}>등록된 중분류가 없습니다. &quot;중분류 추가&quot;로 시작하세요.</p>
        </div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #E2E8F0" }}>
              {["순서", "중분류명 / 키", "설명", "하위 글", "공개", "관리"].map((h) => (
                <th key={h} style={{ padding: "10px 12px", textAlign: "left", fontSize: 12, fontWeight: 600, color: "#4A5568" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.map((g) => {
              const published = g.is_published?.toUpperCase() === "TRUE";
              const busy = busyIds.has(g.id);
              const editing = editId === g.id;
              return (
                <tr key={g.id} style={{ borderBottom: "1px solid #F0F0F0", opacity: published ? 1 : 0.7 }}>
                  <td style={{ padding: "12px", fontSize: 13, color: "#718096", width: 60 }}>
                    {editing ? (
                      <input value={editOrder} onChange={(e) => setEditOrder(e.target.value)} style={{ ...inputStyle, width: 56 }} />
                    ) : g.sort_order}
                  </td>
                  <td style={{ padding: "12px", fontSize: 14, color: "#1A202C" }}>
                    {editing ? (
                      <input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} style={inputStyle} />
                    ) : (
                      <button
                        onClick={() => router.push(`/marketing/documents/${g.group_key}`)}
                        style={{ background: "none", border: "none", cursor: "pointer", padding: 0, textAlign: "left", color: "#1A202C", fontWeight: 600, fontSize: 14 }}
                      >
                        {g.title || g.group_key} ›
                      </button>
                    )}
                    <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: 2 }}>{g.group_key}</div>
                  </td>
                  <td style={{ padding: "12px", fontSize: 13, color: "#718096", maxWidth: 240 }}>
                    {editing ? (
                      <input value={editDesc} onChange={(e) => setEditDesc(e.target.value)} style={inputStyle} />
                    ) : (g.description || "-")}
                  </td>
                  <td style={{ padding: "12px", fontSize: 13, color: "#718096", whiteSpace: "nowrap" }}>
                    {g.post_count ?? 0}건 <span style={{ color: "#A0AEC0" }}>(게시 {g.published_post_count ?? 0})</span>
                  </td>
                  <td style={{ padding: "12px" }}>
                    <button
                      onClick={() => handleToggle(g)}
                      disabled={busy}
                      style={{
                        padding: "4px 12px", borderRadius: 20, fontSize: 12, fontWeight: 600, border: "none",
                        cursor: busy ? "not-allowed" : "pointer", opacity: busy ? 0.6 : 1,
                        background: published ? "#C6F6D5" : "#FED7D7", color: published ? "#276749" : "#9B2C2C",
                        display: "inline-flex", alignItems: "center", gap: 4,
                      }}
                    >
                      {busy && <Loader2 size={11} style={{ animation: "spin 0.8s linear infinite" }} />}
                      {published ? "공개" : "비공개"}
                    </button>
                  </td>
                  <td style={{ padding: "12px" }}>
                    <div style={{ display: "flex", gap: 8 }}>
                      {editing ? (
                        <>
                          <button onClick={() => saveEdit(g.id)} disabled={busy} style={{ padding: "4px 10px", borderRadius: 6, fontSize: 12, border: "1px solid var(--hw-gold-soft-border)", background: "var(--hw-gold-soft-bg)", color: "var(--hw-gold-soft-text)", fontWeight: 600, cursor: "pointer" }}>저장</button>
                          <button onClick={() => setEditId(null)} style={{ padding: "4px 10px", borderRadius: 6, fontSize: 12, border: "1px solid #E2E8F0", background: "#fff", cursor: "pointer", color: "#4A5568" }}>취소</button>
                        </>
                      ) : (
                        <>
                          <button onClick={() => startEdit(g)} style={{ padding: "4px 10px", borderRadius: 6, fontSize: 12, border: "1px solid #E2E8F0", background: "#fff", cursor: "pointer", color: "#4A5568" }}>수정</button>
                          <button
                            onClick={() => router.push(`/marketing/documents/${g.group_key}`)}
                            style={{ padding: "4px 10px", borderRadius: 6, fontSize: 12, border: "1px solid #E2E8F0", background: "#fff", cursor: "pointer", color: "#4A5568" }}
                          >
                            글 관리
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {/* 미분류 준비서류 — 준비서류 계열 카테고리지만 중분류(doc_group) 미지정. 관리자 전용(공개 /documents 미노출). */}
      <div style={{ marginTop: 32 }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: "#1A202C", marginBottom: 4 }}>
          미분류 준비서류 <span style={{ fontSize: 13, fontWeight: 500, color: "#A0AEC0" }}>({unclassified.length})</span>
        </h2>
        <p style={{ fontSize: 12.5, color: "#718096", marginBottom: 12 }}>
          준비서류 계열 글이지만 중분류가 지정되지 않아 공개 /documents에 표시되지 않습니다. 글을 열어 <strong>중분류를 지정</strong>하거나 <strong>비공개</strong>로 처리하세요. (삭제하지 않음)
        </p>
        {loading ? (
          <p style={{ color: "#718096", fontSize: 13 }}>불러오는 중...</p>
        ) : unclassified.length === 0 ? (
          <div style={{ border: "1px dashed #E2E8F0", borderRadius: 10, padding: 20, color: "#A0AEC0", fontSize: 13, textAlign: "center" }}>
            미분류 준비서류가 없습니다.
          </div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #E2E8F0" }}>
                {["제목", "카테고리", "게시 상태", "관리"].map((h) => (
                  <th key={h} style={{ padding: "10px 12px", textAlign: "left", fontSize: 12, fontWeight: 600, color: "#4A5568" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {unclassified.map((p) => {
                const published = p.is_published?.toUpperCase() === "TRUE";
                return (
                  <tr key={p.id} style={{ borderBottom: "1px solid #F0F0F0" }}>
                    <td style={{ padding: "12px", fontSize: 14, color: "#1A202C" }}>
                      <div style={{ fontWeight: 500 }}>{p.title}</div>
                      <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: 2 }}>/board/{p.slug || p.id}</div>
                    </td>
                    <td style={{ padding: "12px", fontSize: 13, color: "#718096" }}>{p.category || "-"}</td>
                    <td style={{ padding: "12px" }}>
                      <span style={{ fontSize: 12, fontWeight: 600, padding: "2px 10px", borderRadius: 20, background: published ? "#C6F6D5" : "#FED7D7", color: published ? "#276749" : "#9B2C2C" }}>
                        {published ? "게시 중" : "미게시"}
                      </span>
                    </td>
                    <td style={{ padding: "12px" }}>
                      <button
                        onClick={() => router.push(`/marketing/${p.id}/edit?from=/marketing/documents`)}
                        style={{ padding: "4px 10px", borderRadius: 6, fontSize: 12, border: "1px solid #E2E8F0", background: "#fff", cursor: "pointer", color: "#4A5568" }}
                      >
                        수정 (중분류 지정/비공개)
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
