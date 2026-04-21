"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { boardApi, type BoardPost } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { Plus, Trash2, MessageSquare, ChevronLeft, Pin, RefreshCw, Pencil } from "lucide-react";

export default function BoardPage() {
  const qc = useQueryClient();
  const user = getUser();
  const isAdmin = user?.is_admin === true;

  const [view, setView] = useState<"list" | "write" | "edit" | "detail">("list");
  const [selectedPost, setSelectedPost] = useState<BoardPost | null>(null);
  const [form, setForm] = useState({ title: "", content: "", category: "", is_notice: false, popup_yn: false });
  const [editForm, setEditForm] = useState({ title: "", content: "", category: "", is_notice: false, popup_yn: false });
  const [comment, setComment] = useState("");

  const { data: posts = [] } = useQuery({
    queryKey: ["board"],
    queryFn: () => boardApi.list().then((r) => r.data),
  });

  const { data: comments = [] } = useQuery({
    queryKey: ["board", selectedPost?.id, "comments"],
    queryFn: () => boardApi.getComments(selectedPost!.id).then((r) => r.data),
    enabled: !!selectedPost,
  });

  const createMut = useMutation({
    mutationFn: () =>
      boardApi.create({
        title: form.title,
        content: form.content,
        category: form.category.trim() || "자유",
        is_notice: isAdmin && form.is_notice ? "Y" : "",
        popup_yn: isAdmin && form.popup_yn ? "Y" : "",
      }),
    onSuccess: () => {
      toast.success("작성됨");
      qc.invalidateQueries({ queryKey: ["board"] });
      setView("list");
      setForm({ title: "", content: "", category: "", is_notice: false, popup_yn: false });
    },
    onError: () => toast.error("작성 실패"),
  });

  const updateMut = useMutation({
    mutationFn: () =>
      boardApi.update(selectedPost!.id, {
        title: editForm.title,
        content: editForm.content,
        category: editForm.category.trim() || "자유",
        is_notice: isAdmin && editForm.is_notice ? "Y" : "",
        popup_yn: isAdmin && editForm.popup_yn ? "Y" : "",
      }),
    onSuccess: (res) => {
      toast.success("수정됨");
      setSelectedPost(res.data as BoardPost);
      qc.invalidateQueries({ queryKey: ["board"] });
      setView("detail");
    },
    onError: () => toast.error("수정 실패"),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => boardApi.delete(id),
    onSuccess: () => {
      toast.success("삭제됨");
      qc.invalidateQueries({ queryKey: ["board"] });
      setView("list");
      setSelectedPost(null);
    },
    onError: () => toast.error("삭제 실패"),
  });

  const addCommentMut = useMutation({
    mutationFn: () => boardApi.addComment(selectedPost!.id, comment),
    onSuccess: () => {
      toast.success("댓글 등록됨");
      setComment("");
      qc.invalidateQueries({ queryKey: ["board", selectedPost?.id, "comments"] });
    },
    onError: () => toast.error("댓글 등록 실패"),
  });

  const deleteCommentMut = useMutation({
    mutationFn: ({ postId, commentId }: { postId: string; commentId: string }) =>
      boardApi.deleteComment(postId, commentId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["board", selectedPost?.id, "comments"] });
    },
  });

  const checkManualMut = useMutation({
    mutationFn: () => boardApi.checkManual(),
    onSuccess: (res) => {
      if (res.data.updated) {
        toast.success(`메뉴얼 업데이트 감지: ${res.data.date}`);
        qc.invalidateQueries({ queryKey: ["board"] });
      } else {
        toast.success(`메뉴얼 최신 상태 (${res.data.date})`);
      }
    },
    onError: () => toast.error("하이코리아 확인 실패"),
  });

  // 공지 / 일반 분리 (백엔드에서 이미 정렬되어 오지만 프론트에서도 구분)
  const notices = (posts as BoardPost[]).filter(
    (p) => String(p.is_notice ?? "").trim().toUpperCase() === "Y"
  );
  const normals = (posts as BoardPost[]).filter(
    (p) => String(p.is_notice ?? "").trim().toUpperCase() !== "Y"
  );

  // 본인 또는 관리자 여부
  const canEdit = (post: BoardPost) =>
    isAdmin || post.author_login === user?.login_id || post.author === user?.login_id;
  const canDelete = (post: BoardPost) =>
    isAdmin || post.author_login === user?.login_id || post.author === user?.login_id;
  const canDeleteComment = (c: Record<string, string>) =>
    isAdmin || c.author_login === user?.login_id || c.author === user?.login_id;

  // 게시글 표시용 이름: office_name 우선, 없으면 author_login
  const displayAuthor = (post: BoardPost) =>
    post.office_name || post.author_login || post.author || "";

  const PostRow = ({ post, isNotice }: { post: BoardPost; isNotice?: boolean }) => (
    <tr key={post.id}>
      <td style={{ cursor: "pointer" }} onClick={() => { setSelectedPost(post); setView("detail"); }}>
        {isNotice && (
          <span style={{ marginRight: 6, fontSize: 11, color: "#D4A017", fontWeight: 700 }}>
            [공지]
          </span>
        )}
        <span style={{ color: isNotice ? "#1A202C" : "#2D3748", fontWeight: isNotice ? 700 : 500 }}>
          {post.title}
        </span>
        {post.category ? (
          <span style={{ marginLeft: 6, fontSize: 10, color: "#A0AEC0", background: "#EDF2F7", borderRadius: 4, padding: "1px 5px" }}>
            {post.category}
          </span>
        ) : null}
        {post.comment_count != null && post.comment_count > 0 && (
          <span style={{ marginLeft: 6, fontSize: 10, color: "#4299E1", fontWeight: 600 }}>
            [{post.comment_count}]
          </span>
        )}
      </td>
      <td style={{ color: "#718096", fontSize: 12 }}>{displayAuthor(post)}</td>
      <td style={{ color: "#A0AEC0", fontSize: 11 }}>{(post.updated_at ?? post.created_at)?.slice(0, 10)}</td>
      <td style={{ textAlign: "center" }}>
        {canDelete(post) && (
          <button
            onClick={(e) => { e.stopPropagation(); deleteMut.mutate(post.id); }}
            style={{ color: "#FC8181", background: "none", border: "none", cursor: "pointer", padding: 2 }}
          >
            <Trash2 size={12} />
          </button>
        )}
      </td>
    </tr>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* 헤더 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        {view !== "list" && (
          <button
            onClick={() => {
              if (view === "edit") { setView("detail"); }
              else { setView("list"); setSelectedPost(null); }
            }}
            style={{ padding: 4, background: "none", border: "none", cursor: "pointer", color: "#718096", borderRadius: 6 }}
          >
            <ChevronLeft size={18} />
          </button>
        )}
        <h1 className="hw-page-title">📢 게시판</h1>
        {view === "list" && (
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
            {isAdmin && (
              <button
                onClick={() => checkManualMut.mutate()}
                disabled={checkManualMut.isPending}
                style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, padding: "5px 10px", background: "#EBF8FF", color: "#2B6CB0", border: "1px solid #BEE3F8", borderRadius: 6, cursor: "pointer", opacity: checkManualMut.isPending ? 0.6 : 1 }}
              >
                <RefreshCw size={12} /> 메뉴얼 업데이트 확인
              </button>
            )}
            <button
              onClick={() => setView("write")}
              className="btn-primary"
              style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, padding: "5px 12px" }}
            >
              <Plus size={12} /> 글쓰기
            </button>
          </div>
        )}
      </div>

      {/* ── 목록 ── */}
      {view === "list" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {/* 공지사항 섹션 */}
          {notices.length > 0 && (
            <div className="hw-card" style={{ padding: 0, overflow: "hidden", border: "1px solid #F6D97A" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "10px 16px", background: "#FFFBEB", borderBottom: "1px solid #F6D97A" }}>
                <Pin size={13} style={{ color: "#D4A017" }} />
                <span style={{ fontSize: 13, fontWeight: 700, color: "#92700A" }}>공지사항</span>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table className="hw-table" style={{ width: "100%" }}>
                  <tbody>
                    {notices.map((p) => <PostRow key={p.id} post={p} isNotice />)}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 일반 게시글 */}
          <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
            {normals.length === 0 && notices.length === 0 ? (
              <div style={{ padding: "32px 0", textAlign: "center", color: "#A0AEC0", fontSize: 14 }}>
                게시글이 없습니다.
              </div>
            ) : normals.length === 0 ? (
              <div style={{ padding: "16px", textAlign: "center", color: "#A0AEC0", fontSize: 13 }}>
                일반 게시글이 없습니다.
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="hw-table" style={{ width: "100%" }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: "left" }}>제목</th>
                      <th style={{ textAlign: "left", width: 96 }}>작성자</th>
                      <th style={{ textAlign: "left", width: 100 }}>날짜</th>
                      <th style={{ width: 32 }} />
                    </tr>
                  </thead>
                  <tbody>
                    {normals.map((p) => <PostRow key={p.id} post={p} />)}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── 글쓰기 ── */}
      {view === "write" && (
        <div className="hw-card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: "#2D3748" }}>새 글 작성</div>

          {/* 관리자만 공지 / 팝업 체크박스 표시 */}
          {isAdmin && (
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="checkbox"
                  id="is_notice"
                  checked={form.is_notice}
                  onChange={(e) => setForm(p => ({ ...p, is_notice: e.target.checked }))}
                  style={{ width: 14, height: 14, cursor: "pointer", accentColor: "#D4A017" }}
                />
                <label htmlFor="is_notice" style={{ fontSize: 13, color: "#92700A", fontWeight: 600, cursor: "pointer" }}>
                  📌 공지사항으로 등록
                </label>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="checkbox"
                  id="popup_yn"
                  checked={form.popup_yn}
                  onChange={(e) => setForm(p => ({ ...p, popup_yn: e.target.checked }))}
                  style={{ width: 14, height: 14, cursor: "pointer", accentColor: "#3182CE" }}
                />
                <label htmlFor="popup_yn" style={{ fontSize: 13, color: "#2B6CB0", fontWeight: 600, cursor: "pointer" }}>
                  🔔 팝업 표시
                </label>
              </div>
            </div>
          )}

          <div style={{ display: "flex", gap: 10 }}>
            <div style={{ flex: 1 }}>
              <label style={{ display: "block", fontSize: 11, color: "#718096", marginBottom: 4 }}>제목</label>
              <input
                className="hw-input"
                style={{ width: "100%", fontSize: 14, padding: "8px 10px" }}
                value={form.title}
                onChange={(e) => setForm(p => ({ ...p, title: e.target.value }))}
                placeholder="제목을 입력하세요"
              />
            </div>
            <div style={{ width: 120 }}>
              <label style={{ display: "block", fontSize: 11, color: "#718096", marginBottom: 4 }}>분류</label>
              <input
                className="hw-input"
                style={{ width: "100%", fontSize: 14, padding: "8px 10px" }}
                value={form.category}
                onChange={(e) => setForm(p => ({ ...p, category: e.target.value }))}
                placeholder="자유"
              />
            </div>
          </div>
          <div>
            <label style={{ display: "block", fontSize: 11, color: "#718096", marginBottom: 4 }}>내용</label>
            <textarea
              style={{
                width: "100%", height: 320, resize: "vertical",
                border: "1px solid #CBD5E0", borderRadius: 6, padding: "10px 12px",
                fontSize: 14, outline: "none", fontFamily: "inherit", lineHeight: 1.7,
                boxSizing: "border-box",
              }}
              value={form.content}
              onChange={(e) => setForm(p => ({ ...p, content: e.target.value }))}
              placeholder="내용을 입력하세요"
            />
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button
              onClick={() => { setView("list"); setForm({ title: "", content: "", category: "", is_notice: false, popup_yn: false }); }}
              className="btn-secondary"
              style={{ fontSize: 13, padding: "7px 16px" }}
            >
              취소
            </button>
            <button
              onClick={() => createMut.mutate()}
              disabled={!form.title || createMut.isPending}
              className="btn-primary"
              style={{ fontSize: 13, padding: "7px 16px", opacity: (!form.title || createMut.isPending) ? 0.5 : 1 }}
            >
              {createMut.isPending ? "등록 중..." : "등록"}
            </button>
          </div>
        </div>
      )}

      {/* ── 수정 ── */}
      {view === "edit" && selectedPost && (
        <div className="hw-card" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ fontSize: 15, fontWeight: 600, color: "#2D3748" }}>글 수정</div>

          {isAdmin && (
            <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="checkbox"
                  id="edit_is_notice"
                  checked={editForm.is_notice}
                  onChange={(e) => setEditForm(p => ({ ...p, is_notice: e.target.checked }))}
                  style={{ width: 14, height: 14, cursor: "pointer", accentColor: "#D4A017" }}
                />
                <label htmlFor="edit_is_notice" style={{ fontSize: 13, color: "#92700A", fontWeight: 600, cursor: "pointer" }}>
                  📌 공지사항으로 등록
                </label>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="checkbox"
                  id="edit_popup_yn"
                  checked={editForm.popup_yn}
                  onChange={(e) => setEditForm(p => ({ ...p, popup_yn: e.target.checked }))}
                  style={{ width: 14, height: 14, cursor: "pointer", accentColor: "#3182CE" }}
                />
                <label htmlFor="edit_popup_yn" style={{ fontSize: 13, color: "#2B6CB0", fontWeight: 600, cursor: "pointer" }}>
                  🔔 팝업 표시
                </label>
              </div>
            </div>
          )}

          <div style={{ display: "flex", gap: 10 }}>
            <div style={{ flex: 1 }}>
              <label style={{ display: "block", fontSize: 11, color: "#718096", marginBottom: 4 }}>제목</label>
              <input
                className="hw-input"
                style={{ width: "100%", fontSize: 14, padding: "8px 10px" }}
                value={editForm.title}
                onChange={(e) => setEditForm(p => ({ ...p, title: e.target.value }))}
              />
            </div>
            <div style={{ width: 120 }}>
              <label style={{ display: "block", fontSize: 11, color: "#718096", marginBottom: 4 }}>분류</label>
              <input
                className="hw-input"
                style={{ width: "100%", fontSize: 14, padding: "8px 10px" }}
                value={editForm.category}
                onChange={(e) => setEditForm(p => ({ ...p, category: e.target.value }))}
              />
            </div>
          </div>
          <div>
            <label style={{ display: "block", fontSize: 11, color: "#718096", marginBottom: 4 }}>내용</label>
            <textarea
              style={{
                width: "100%", height: 320, resize: "vertical",
                border: "1px solid #CBD5E0", borderRadius: 6, padding: "10px 12px",
                fontSize: 14, outline: "none", fontFamily: "inherit", lineHeight: 1.7,
                boxSizing: "border-box",
              }}
              value={editForm.content}
              onChange={(e) => setEditForm(p => ({ ...p, content: e.target.value }))}
            />
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button
              onClick={() => setView("detail")}
              className="btn-secondary"
              style={{ fontSize: 13, padding: "7px 16px" }}
            >
              취소
            </button>
            <button
              onClick={() => updateMut.mutate()}
              disabled={!editForm.title || updateMut.isPending}
              className="btn-primary"
              style={{ fontSize: 13, padding: "7px 16px", opacity: (!editForm.title || updateMut.isPending) ? 0.5 : 1 }}
            >
              {updateMut.isPending ? "저장 중..." : "저장"}
            </button>
          </div>
        </div>
      )}

      {/* ── 상세 ── */}
      {view === "detail" && selectedPost && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* 본문 */}
          <div className="hw-card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
              <div>
                {String(selectedPost.is_notice ?? "").trim().toUpperCase() === "Y" && (
                  <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 4 }}>
                    <Pin size={12} style={{ color: "#D4A017" }} />
                    <span style={{ fontSize: 11, color: "#D4A017", fontWeight: 700 }}>공지사항</span>
                  </div>
                )}
                <div style={{ fontSize: 17, fontWeight: 700, color: "#1A202C" }}>{selectedPost.title}</div>
                <div style={{ fontSize: 12, color: "#A0AEC0", marginTop: 4 }}>
                  {displayAuthor(selectedPost)} · {(selectedPost.updated_at ?? selectedPost.created_at)?.slice(0, 10)}
                </div>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                {canEdit(selectedPost) && (
                  <button
                    onClick={() => {
                      setEditForm({
                        title: selectedPost.title ?? "",
                        content: selectedPost.content ?? "",
                        category: selectedPost.category ?? "",
                        is_notice: String(selectedPost.is_notice ?? "").trim().toUpperCase() === "Y",
                        popup_yn: String(selectedPost.popup_yn ?? "").trim().toUpperCase() === "Y",
                      });
                      setView("edit");
                    }}
                    style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "#3182CE", background: "none", border: "none", cursor: "pointer" }}
                  >
                    <Pencil size={12} /> 수정
                  </button>
                )}
                {canDelete(selectedPost) && (
                  <button
                    onClick={() => deleteMut.mutate(selectedPost.id)}
                    style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "#FC8181", background: "none", border: "none", cursor: "pointer" }}
                  >
                    <Trash2 size={12} /> 삭제
                  </button>
                )}
              </div>
            </div>
            <div style={{ borderTop: "1px solid #E2E8F0", paddingTop: 16, fontSize: 14, color: "#4A5568", whiteSpace: "pre-wrap", lineHeight: 1.8 }}>
              {selectedPost.content}
            </div>
            {selectedPost.link_url && (
              <div style={{ marginTop: 16 }}>
                <a
                  href={selectedPost.link_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 13, color: "#3182CE", fontWeight: 600, textDecoration: "none" }}
                >
                  🔗 바로 가기
                </a>
              </div>
            )}
          </div>

          {/* 댓글 */}
          <div className="hw-card" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, fontWeight: 600, color: "#4A5568" }}>
              <MessageSquare size={14} /> 댓글 {comments.length}
            </div>
            {(comments as Record<string, string>[]).map((c) => (
              <div key={c.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", paddingBottom: 10, borderBottom: "1px solid #EDF2F7" }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "#2D3748" }}>
                      {c.office_name || c.author_login || c.author}
                    </span>
                    <span style={{ fontSize: 11, color: "#A0AEC0" }}>{c.created_at?.slice(0, 16)}</span>
                  </div>
                  <div style={{ fontSize: 13, color: "#4A5568", marginTop: 3 }}>{c.content}</div>
                </div>
                {canDeleteComment(c) && (
                  <button
                    onClick={() => deleteCommentMut.mutate({ postId: selectedPost.id, commentId: c.id })}
                    style={{ color: "#FC8181", background: "none", border: "none", cursor: "pointer", padding: 2, flexShrink: 0 }}
                  >
                    <Trash2 size={11} />
                  </button>
                )}
              </div>
            ))}
            {/* 댓글 입력 */}
            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
              <input
                className="hw-input"
                style={{ flex: 1, fontSize: 13 }}
                placeholder="댓글 입력..."
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && comment.trim()) {
                    e.preventDefault();
                    addCommentMut.mutate();
                  }
                }}
              />
              <button
                onClick={() => addCommentMut.mutate()}
                disabled={!comment.trim() || addCommentMut.isPending}
                className="btn-primary"
                style={{ fontSize: 12, padding: "6px 14px", opacity: (!comment.trim() || addCommentMut.isPending) ? 0.5 : 1 }}
              >
                등록
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
