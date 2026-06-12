"use client";
/**
 * 문서자동작성 설정 (관리자 전용) — 편집형 선택 트리 + 필요서류. Phase I-1J-6O.
 *
 * 구분 → 민원 → 종류 → 세부 4단계를 Miller 컬럼으로 탐색하고, 선택한(가장 깊은)
 * 노드에 연결된 필요서류(민원서류/행정사서류)를 추가·수정·삭제·자동매핑한다.
 * 코드 파일을 고치지 않고 DB 설정만 변경하며, 결과는 일반 문서자동작성 화면(/tree)에 반영된다.
 * 삭제는 soft delete(숨김). 비활성 항목은 흐리게 표시.
 */
import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  docConfigApi, AdminDocNode, AdminDocTree, AdminReqDoc, DocNodeLevel, TemplateFile,
} from "@/lib/api";
import { Plus, Trash2, RotateCcw, Eye, EyeOff, Pencil, FileWarning, FileCheck, Link2 } from "lucide-react";

const GOLD = "var(--hw-gold, #B8860B)";
const LEVEL_LABEL: Record<DocNodeLevel, string> = {
  category: "구분", petition: "민원", type: "종류", subtype: "세부",
};
const CHILD_LEVEL: Partial<Record<DocNodeLevel, DocNodeLevel>> = {
  category: "petition", petition: "type", type: "subtype",
};

function errMsg(e: unknown, fb: string): string {
  return (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fb;
}

export default function DocConfigTab() {
  const qc = useQueryClient();
  const [sel, setSel] = useState<Record<DocNodeLevel, number | null>>({
    category: null, petition: null, type: null, subtype: null,
  });

  const { data: tree, isLoading, error } = useQuery({
    queryKey: ["doc-config-tree"],
    queryFn: () => docConfigApi.getTree().then((r) => r.data as AdminDocTree),
  });
  const { data: templates } = useQuery({
    queryKey: ["doc-config-templates"],
    queryFn: () => docConfigApi.getTemplates().then((r) => r.data.templates as TemplateFile[]),
  });

  const refresh = () => qc.invalidateQueries({ queryKey: ["doc-config-tree"] });

  // ── 컬럼별 항목 계산 ──
  const categories = tree?.categories ?? [];
  const catNode = categories.find((c) => c.id === sel.category) || null;
  const petitions = catNode?.petitions ?? [];
  const petNode = petitions.find((p) => p.id === sel.petition) || null;
  const types = petNode?.types ?? [];
  const typeNode = types.find((t) => t.id === sel.type) || null;
  const subtypes = typeNode?.subtypes ?? [];
  const subNode = subtypes.find((s) => s.id === sel.subtype) || null;

  // 가장 깊은 선택 노드 = 필요서류 편집 대상
  const activeNode: AdminDocNode | null = subNode || typeNode || petNode || catNode;

  const select = (level: DocNodeLevel, id: number) => {
    setSel((prev) => {
      const next = { ...prev, [level]: prev[level] === id ? null : id };
      // 하위 선택 초기화
      if (level === "category") { next.petition = next.type = next.subtype = null; }
      if (level === "petition") { next.type = next.subtype = null; }
      if (level === "type") { next.subtype = null; }
      return next;
    });
  };

  if (isLoading) return <div className="hw-card text-sm">불러오는 중…</div>;
  if (error) {
    return (
      <div className="hw-card text-sm" style={{ background: "#FFF5F5", borderColor: "#FEB2B2", color: "#C53030" }}>
        문서자동작성 설정을 불러오지 못했습니다. PostgreSQL 미구성(503)이거나 권한이 없습니다. ({errMsg(error, "오류")})
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="hw-card text-xs leading-relaxed" style={{ background: "#FFFBEB", borderColor: "#FDE68A" }}>
        <div style={{ fontWeight: 700, color: "#92400E" }}>문서자동작성 선택 구조 / 필요서류 관리</div>
        <div style={{ color: "#4A5568", marginTop: 4 }}>
          구분 → 민원 → 종류 → 세부 순으로 클릭해 하위 항목을 추가·수정·삭제(숨김)합니다.
          변경 내용은 일반 문서자동작성 화면에 즉시 반영됩니다(<code>FEATURE_PG_QUICK_DOC_CONFIG</code> ON 기준).
          서류명은 <code>templates/</code> 폴더의 동일 이름 PDF에 자동 매핑됩니다.
        </div>
      </div>

      {/* Miller 컬럼: 구분 / 민원 / 종류 / 세부 */}
      <div className="grid grid-cols-4 gap-2">
        <NodeColumn level="category" parentId={null} items={categories} selectedId={sel.category}
          onSelect={(id) => select("category", id)} onChanged={refresh} />
        <NodeColumn level="petition" parentId={catNode?.id ?? null} items={petitions} selectedId={sel.petition}
          onSelect={(id) => select("petition", id)} onChanged={refresh}
          disabledHint={!catNode ? "구분을 선택하세요" : undefined} />
        <NodeColumn level="type" parentId={petNode?.id ?? null} items={types} selectedId={sel.type}
          onSelect={(id) => select("type", id)} onChanged={refresh}
          disabledHint={!petNode ? "민원을 선택하세요" : undefined} />
        <NodeColumn level="subtype" parentId={typeNode?.id ?? null} items={subtypes} selectedId={sel.subtype}
          onSelect={(id) => select("subtype", id)} onChanged={refresh}
          disabledHint={!typeNode ? "종류를 선택하세요" : undefined} />
      </div>

      {/* 필요서류 편집 */}
      {activeNode ? (
        <DocsEditor node={activeNode} pathLabel={[catNode, petNode, typeNode, subNode].filter(Boolean).map((n) => n!.name).join(" > ")}
          templates={templates ?? []} onChanged={refresh} />
      ) : (
        <div className="hw-card text-sm text-gray-500">위에서 항목을 선택하면 해당 단계의 필요서류를 관리할 수 있습니다.</div>
      )}
    </div>
  );
}

// ── 트리 컬럼 (노드 목록 + 추가/수정/삭제) ───────────────────────────────────
function NodeColumn({
  level, parentId, items, selectedId, onSelect, onChanged, disabledHint,
}: {
  level: DocNodeLevel; parentId: number | null; items: AdminDocNode[];
  selectedId: number | null; onSelect: (id: number) => void; onChanged: () => void;
  disabledHint?: string;
}) {
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [editId, setEditId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const canAdd = level === "category" || parentId != null;

  const createMut = useMutation({
    mutationFn: () => docConfigApi.createNode({ parent_id: level === "category" ? null : parentId, level, name: newName.trim() }),
    onSuccess: () => { toast.success(`${LEVEL_LABEL[level]} 추가됨`); setNewName(""); setAdding(false); onChanged(); },
    onError: (e) => toast.error(errMsg(e, "추가 실패")),
  });
  const renameMut = useMutation({
    mutationFn: ({ id, name }: { id: number; name: string }) => docConfigApi.updateNode(id, { name }),
    onSuccess: () => { toast.success("이름 수정됨"); setEditId(null); onChanged(); },
    onError: (e) => toast.error(errMsg(e, "수정 실패")),
  });
  const toggleMut = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) => docConfigApi.updateNode(id, { is_active }),
    onSuccess: () => onChanged(),
    onError: (e) => toast.error(errMsg(e, "변경 실패")),
  });
  const delMut = useMutation({
    mutationFn: (id: number) => docConfigApi.deleteNode(id),
    onSuccess: () => { toast.success("숨김 처리됨"); onChanged(); },
    onError: (e) => toast.error(errMsg(e, "삭제 실패")),
  });

  return (
    <div className="hw-card p-2" style={{ minHeight: 200 }}>
      <div className="flex items-center justify-between mb-2 px-1">
        <span style={{ fontSize: 12, fontWeight: 700, color: "#2D3748" }}>{LEVEL_LABEL[level]}</span>
        {canAdd && !adding && (
          <button onClick={() => setAdding(true)} title={`${LEVEL_LABEL[level]} 추가`}
            style={{ color: GOLD, background: "none", border: "none", cursor: "pointer" }}>
            <Plus size={15} />
          </button>
        )}
      </div>

      {disabledHint && <div className="text-xs text-gray-400 px-1 py-3">{disabledHint}</div>}

      {!disabledHint && (
        <div className="space-y-1">
          {items.map((n) => (
            <div key={n.id}
              className="flex items-center gap-1 rounded px-1.5 py-1"
              style={{
                background: selectedId === n.id ? "#FEF3C7" : "transparent",
                opacity: n.is_active ? 1 : 0.45,
              }}>
              {editId === n.id ? (
                <input autoFocus value={editName} onChange={(e) => setEditName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && editName.trim()) renameMut.mutate({ id: n.id, name: editName.trim() }); if (e.key === "Escape") setEditId(null); }}
                  style={{ flex: 1, fontSize: 12, border: "1px solid #CBD5E0", borderRadius: 4, padding: "2px 4px" }} />
              ) : (
                <button onClick={() => onSelect(n.id)} title="선택"
                  style={{ flex: 1, textAlign: "left", fontSize: 12, background: "none", border: "none", cursor: "pointer", color: "#2D3748", fontWeight: selectedId === n.id ? 700 : 400 }}>
                  {n.name}{!n.is_active && " (숨김)"}
                </button>
              )}
              {editId === n.id ? (
                <button onClick={() => renameMut.mutate({ id: n.id, name: editName.trim() })} disabled={!editName.trim()}
                  style={{ fontSize: 11, color: GOLD, background: "none", border: "none", cursor: "pointer" }}>저장</button>
              ) : (
                <>
                  <button onClick={() => { setEditId(n.id); setEditName(n.name); }} title="이름 수정"
                    style={{ color: "#718096", background: "none", border: "none", cursor: "pointer" }}><Pencil size={12} /></button>
                  <button onClick={() => toggleMut.mutate({ id: n.id, is_active: !n.is_active })} title={n.is_active ? "숨기기" : "다시 표시"}
                    style={{ color: "#718096", background: "none", border: "none", cursor: "pointer" }}>
                    {n.is_active ? <Eye size={12} /> : <EyeOff size={12} />}
                  </button>
                  {n.is_active && (
                    <button onClick={() => { if (confirm(`'${n.name}' 항목을 숨김 처리할까요? (하위 항목/서류는 보존)`)) delMut.mutate(n.id); }} title="삭제(숨김)"
                      style={{ color: "#E53E3E", background: "none", border: "none", cursor: "pointer" }}><Trash2 size={12} /></button>
                  )}
                </>
              )}
            </div>
          ))}
          {items.length === 0 && <div className="text-xs text-gray-400 px-1 py-2">항목 없음</div>}
        </div>
      )}

      {adding && (
        <div className="flex items-center gap-1 mt-2">
          <input autoFocus value={newName} onChange={(e) => setNewName(e.target.value)}
            placeholder={`새 ${LEVEL_LABEL[level]}`}
            onKeyDown={(e) => { if (e.key === "Enter" && newName.trim()) createMut.mutate(); if (e.key === "Escape") { setAdding(false); setNewName(""); } }}
            style={{ flex: 1, fontSize: 12, border: "1px solid #CBD5E0", borderRadius: 4, padding: "3px 5px" }} />
          <button onClick={() => createMut.mutate()} disabled={!newName.trim() || createMut.isPending}
            style={{ fontSize: 11, color: "#fff", background: GOLD, border: "none", borderRadius: 4, padding: "3px 7px", cursor: "pointer" }}>추가</button>
          <button onClick={() => { setAdding(false); setNewName(""); }}
            style={{ fontSize: 11, color: "#718096", background: "none", border: "none", cursor: "pointer" }}>취소</button>
        </div>
      )}
    </div>
  );
}

// ── 필요서류 편집기 ──────────────────────────────────────────────────────────
function DocsEditor({
  node, pathLabel, templates, onChanged,
}: {
  node: AdminDocNode; pathLabel: string; templates: TemplateFile[]; onChanged: () => void;
}) {
  const docs = node.docs ?? [];
  const main = useMemo(() => docs.filter((d) => d.doc_group === "main"), [docs]);
  const agent = useMemo(() => docs.filter((d) => d.doc_group === "agent"), [docs]);

  return (
    <div className="hw-card p-3 space-y-3">
      <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748" }}>
        필요서류 — <span style={{ color: GOLD }}>{pathLabel || node.name}</span>
        <span className="text-xs text-gray-400 font-normal ml-2">({LEVEL_LABEL[node.level]} 노드에 연결)</span>
      </div>
      <DocGroup title="민원 서류" group="main" nodeId={node.id} items={main} templates={templates} onChanged={onChanged} />
      <DocGroup title="행정사 서류" group="agent" nodeId={node.id} items={agent} templates={templates} onChanged={onChanged} />
    </div>
  );
}

function DocGroup({
  title, group, nodeId, items, templates, onChanged,
}: {
  title: string; group: "main" | "agent"; nodeId: number; items: AdminReqDoc[];
  templates: TemplateFile[]; onChanged: () => void;
}) {
  const [newName, setNewName] = useState("");
  const createMut = useMutation({
    mutationFn: () => docConfigApi.createDoc({ node_id: nodeId, name: newName.trim(), doc_group: group }),
    onSuccess: (r) => {
      const d = r.data as AdminReqDoc;
      toast.success(d.template_status === "mapped" ? `추가됨 (템플릿: ${d.template_filename})` : "추가됨 (템플릿 없음 ⚠)");
      setNewName(""); onChanged();
    },
    onError: (e) => toast.error(errMsg(e, "추가 실패")),
  });

  return (
    <div>
      <div style={{ fontSize: 12, fontWeight: 600, color: "#4A5568", marginBottom: 4 }}>{title}</div>
      <div className="space-y-1">
        {items.map((d) => <DocRow key={d.id} doc={d} templates={templates} onChanged={onChanged} />)}
        {items.length === 0 && <div className="text-xs text-gray-400 px-1">없음</div>}
      </div>
      <div className="flex items-center gap-1 mt-2">
        <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder={`새 ${title} 추가`}
          onKeyDown={(e) => { if (e.key === "Enter" && newName.trim()) createMut.mutate(); }}
          style={{ flex: 1, fontSize: 12, border: "1px solid #CBD5E0", borderRadius: 4, padding: "3px 6px", maxWidth: 320 }} />
        <button onClick={() => createMut.mutate()} disabled={!newName.trim() || createMut.isPending}
          style={{ fontSize: 11, color: "#fff", background: GOLD, border: "none", borderRadius: 4, padding: "3px 9px", cursor: "pointer" }}>추가</button>
      </div>
    </div>
  );
}

function DocRow({ doc, templates, onChanged }: { doc: AdminReqDoc; templates: TemplateFile[]; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(doc.name);
  const [pickTemplate, setPickTemplate] = useState(false);

  const updateMut = useMutation({
    mutationFn: (data: Parameters<typeof docConfigApi.updateDoc>[1]) => docConfigApi.updateDoc(doc.id, data),
    onSuccess: () => { toast.success("저장됨"); setEditing(false); setPickTemplate(false); onChanged(); },
    onError: (e) => toast.error(errMsg(e, "저장 실패")),
  });
  const remapMut = useMutation({
    mutationFn: () => docConfigApi.remapDoc(doc.id),
    onSuccess: (r) => { const d = r.data as AdminReqDoc; toast.success(d.template_status === "mapped" ? `매핑됨: ${d.template_filename}` : "매칭되는 템플릿 없음 ⚠"); onChanged(); },
    onError: (e) => toast.error(errMsg(e, "자동매핑 실패")),
  });
  const delMut = useMutation({
    mutationFn: () => docConfigApi.deleteDoc(doc.id),
    onSuccess: () => { toast.success("숨김 처리됨"); onChanged(); },
    onError: (e) => toast.error(errMsg(e, "삭제 실패")),
  });

  const mapped = doc.template_status === "mapped" && !!doc.template_filename;

  return (
    <div className="flex items-center gap-1.5 rounded px-1.5 py-1" style={{ background: "#F7FAFC", opacity: doc.is_active ? 1 : 0.45 }}>
      {editing ? (
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) updateMut.mutate({ name: name.trim() }); if (e.key === "Escape") setEditing(false); }}
          style={{ flex: 1, fontSize: 12, border: "1px solid #CBD5E0", borderRadius: 4, padding: "2px 4px" }} />
      ) : (
        <span style={{ flex: 1, fontSize: 12, color: "#2D3748" }}>{doc.name}{!doc.is_active && " (숨김)"}</span>
      )}

      {/* 템플릿 상태 */}
      {mapped ? (
        <span title={doc.template_filename} style={{ fontSize: 10, color: "#2F855A", display: "inline-flex", alignItems: "center", gap: 2 }}>
          <FileCheck size={11} /> {doc.template_filename}
        </span>
      ) : (
        <span title="templates 폴더에 일치하는 PDF 없음" style={{ fontSize: 10, color: "#C05621", display: "inline-flex", alignItems: "center", gap: 2 }}>
          <FileWarning size={11} /> 템플릿 없음
        </span>
      )}

      {editing ? (
        <button onClick={() => updateMut.mutate({ name: name.trim() })} disabled={!name.trim()}
          style={{ fontSize: 11, color: GOLD, background: "none", border: "none", cursor: "pointer" }}>저장</button>
      ) : (
        <>
          <button onClick={() => { setName(doc.name); setEditing(true); }} title="이름 수정"
            style={{ color: "#718096", background: "none", border: "none", cursor: "pointer" }}><Pencil size={12} /></button>
          <button onClick={() => remapMut.mutate()} title="템플릿 자동매핑 재계산"
            style={{ color: "#718096", background: "none", border: "none", cursor: "pointer" }}><RotateCcw size={12} /></button>
          <button onClick={() => setPickTemplate((v) => !v)} title="템플릿 직접 선택"
            style={{ color: "#718096", background: "none", border: "none", cursor: "pointer" }}><Link2 size={12} /></button>
          {doc.is_active && (
            <button onClick={() => { if (confirm(`'${doc.name}' 서류를 숨김 처리할까요?`)) delMut.mutate(); }} title="삭제(숨김)"
              style={{ color: "#E53E3E", background: "none", border: "none", cursor: "pointer" }}><Trash2 size={12} /></button>
          )}
          {!doc.is_active && (
            <button onClick={() => updateMut.mutate({ is_active: true })} title="다시 표시"
              style={{ color: "#3182CE", background: "none", border: "none", cursor: "pointer" }}><Eye size={12} /></button>
          )}
        </>
      )}

      {pickTemplate && (
        <select defaultValue={doc.template_filename}
          onChange={(e) => updateMut.mutate({ template_filename: e.target.value })}
          style={{ fontSize: 11, border: "1px solid #CBD5E0", borderRadius: 4, padding: "2px" }}>
          <option value="">(연결 해제)</option>
          {templates.map((t) => <option key={t.filename} value={t.filename}>{t.filename}</option>)}
        </select>
      )}
    </div>
  );
}
