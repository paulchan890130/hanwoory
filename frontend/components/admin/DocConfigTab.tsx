"use client";
/**
 * 문서자동작성 설정 (관리자 전용) — 편집형 선택 트리 + 필요서류. Phase I-1J-6O.
 *
 * 구분 → 민원 → 종류 → 세부 4단계를 Miller 컬럼으로 탐색하고, 선택한(가장 깊은)
 * 노드에 연결된 필요서류(민원서류/행정사서류)를 추가·수정·삭제·자동매핑한다.
 * 코드 파일을 고치지 않고 DB 설정만 변경하며, 결과는 일반 문서자동작성 화면(/tree)에 반영된다.
 * 숨김(soft delete)은 그대로 유지 — 완전삭제(물리 삭제, 복원 불가)는 숨김 상태의 말단만
 * 가능하고, 실제 템플릿 파일(HWPX/HWP/PDF)은 절대 건드리지 않는다.
 */
import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  docConfigApi, AdminDocNode, AdminDocTree, AdminReqDoc, DocNodeLevel, TemplateFile,
  HwpxTemplateFile, HwpxFieldsResponse, DocNodeDeleteImpact, DocRequiredDocDeleteImpact,
} from "@/lib/api";
import { Plus, Trash2, RotateCcw, Eye, EyeOff, Pencil, FileWarning, FileCheck, FileSearch, X } from "lucide-react";

type FilterMode = "active" | "hidden" | "all";

// ── 완전삭제 확인창(공용) — 노드/필요서류 둘 다 이 컴포넌트를 쓴다 ────────────────
function HardDeleteConfirmModal({
  title, impactRows, notice, onCancel, onConfirm, confirming, cascadeChoice, blockedReason,
}: {
  title: string;
  impactRows: { label: string; value: string }[];
  notice: string[];
  onCancel: () => void;
  onConfirm: () => void;
  confirming: boolean;
  /** 활성 하위가 없지만 하위 노드가 있는 부모 삭제 시 — 별도 문구로 강조. */
  cascadeChoice?: boolean;
  /** 서버 사전조사 결과 차단 사유(활성 하위 존재 등) — 있으면 완전삭제 버튼 비활성화. */
  blockedReason?: string | null;
}) {
  return (
    <div onClick={onCancel} onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)", zIndex: 9999,
        display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div onClick={(e) => e.stopPropagation()} className="hw-card" style={{ width: 420, maxWidth: "92vw", background: "#fff" }}>
        <div className="flex items-center gap-2 mb-2">
          <Trash2 size={16} style={{ color: "#C53030" }} />
          <span className="font-semibold text-sm" style={{ color: "#C53030" }}>{title}</span>
        </div>
        <div className="text-sm mb-2" style={{ color: "#4A5568" }}>이 항목을 완전히 삭제하시겠습니까?</div>
        <div className="text-xs mb-3 rounded p-2" style={{ background: "#F7FAFC", lineHeight: 1.7 }}>
          {impactRows.map((r) => (
            <div key={r.label} style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "#718096" }}>{r.label}</span>
              <span style={{ color: "#2D3748", fontWeight: 600 }}>{r.value}</span>
            </div>
          ))}
        </div>
        <div className="text-xs mb-3" style={{ color: "#975A16", background: "#FFFBEB", border: "1px solid #FDE68A", borderRadius: 6, padding: "6px 8px", lineHeight: 1.6 }}>
          {notice.map((n) => <div key={n}>· {n}</div>)}
        </div>
        {blockedReason && (
          <div className="text-xs mb-3" style={{ color: "#822727", background: "#FFF5F5", border: "1px solid #FEB2B2", borderRadius: 6, padding: "6px 8px" }}>
            {blockedReason}
          </div>
        )}
        {!blockedReason && cascadeChoice && (
          <div className="text-xs mb-3" style={{ color: "#822727" }}>
            하위 항목이 모두 숨김 상태입니다 — 계속하면 하위 항목까지 전부 함께 완전삭제됩니다(단일 트랜잭션).
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button autoFocus onClick={onCancel} className="text-xs px-3 py-1.5 rounded-lg border" style={{ borderColor: "#E2E8F0", color: "#718096", background: "#fff" }}>
            취소
          </button>
          <button onClick={() => { if (!confirming) onConfirm(); }} disabled={confirming || !!blockedReason}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ color: "#fff", background: "#C53030", border: "1px solid #9B2C2C" }}>
            완전삭제
          </button>
        </div>
      </div>
    </div>
  );
}

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
  const [filterMode, setFilterMode] = useState<FilterMode>("active");

  const { data: tree, isLoading, error } = useQuery({
    queryKey: ["doc-config-tree"],
    queryFn: () => docConfigApi.getTree().then((r) => r.data as AdminDocTree),
  });
  const { data: templates } = useQuery({
    queryKey: ["doc-config-templates"],
    queryFn: () => docConfigApi.getTemplates().then((r) => r.data.templates as TemplateFile[]),
  });
  const { data: hwpxTemplates } = useQuery({
    queryKey: ["doc-config-hwpx-templates"],
    queryFn: () => docConfigApi.getHwpxTemplates().then((r) => r.data.templates as HwpxTemplateFile[]),
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
        <div style={{ fontWeight: 700, color: "#92400E" }}>문서자동작성 선택 구조 / 필요서류 관리 — HWPX 중심</div>
        <div style={{ color: "#4A5568", marginTop: 4 }}>
          구분 → 민원 → 종류 → 세부 순으로 클릭해 하위 항목을 추가·수정·삭제(숨김)합니다.
          각 서류의 <b>주 출력은 HWPX</b>입니다 — Git의 <code>templates/hwpx/</code> 템플릿에서 선택하고(미선택 시
          동일 이름 자동매칭), 행에 표시되는 필드 진단(정상/주의/위험)으로 매핑 상태를 확인하세요.
          PDF는 접힌 fallback으로 유지됩니다. 출력방식(HWPX 우선/PDF만/둘 다/비활성)은 생성 API에서 강제됩니다.
        </div>
      </div>

      {/* 활성/숨김/전체 필터 — 기본값 활성 */}
      <div className="flex items-center gap-1">
        {(["active", "hidden", "all"] as FilterMode[]).map((m) => (
          <button key={m} onClick={() => setFilterMode(m)}
            style={{ fontSize: 11, fontWeight: 700, padding: "3px 12px", borderRadius: 20,
              border: `1px solid ${filterMode === m ? GOLD : "#E2E8F0"}`,
              background: filterMode === m ? "rgba(184,134,11,0.1)" : "#fff",
              color: filterMode === m ? GOLD : "#718096", cursor: "pointer" }}>
            {m === "active" ? "활성" : m === "hidden" ? "숨김" : "전체"}
          </button>
        ))}
      </div>

      {/* Miller 컬럼: 구분 / 민원 / 종류 / 세부 */}
      <div className="grid grid-cols-4 gap-2">
        <NodeColumn level="category" parentId={null} items={categories} selectedId={sel.category}
          onSelect={(id) => select("category", id)} onChanged={refresh} filterMode={filterMode} />
        <NodeColumn level="petition" parentId={catNode?.id ?? null} items={petitions} selectedId={sel.petition}
          onSelect={(id) => select("petition", id)} onChanged={refresh} filterMode={filterMode}
          disabledHint={!catNode ? "구분을 선택하세요" : undefined} />
        <NodeColumn level="type" parentId={petNode?.id ?? null} items={types} selectedId={sel.type}
          onSelect={(id) => select("type", id)} onChanged={refresh} filterMode={filterMode}
          disabledHint={!petNode ? "민원을 선택하세요" : undefined} />
        <NodeColumn level="subtype" parentId={typeNode?.id ?? null} items={subtypes} selectedId={sel.subtype} filterMode={filterMode}
          onSelect={(id) => select("subtype", id)} onChanged={refresh}
          disabledHint={!typeNode ? "종류를 선택하세요" : undefined} />
      </div>

      {/* 필요서류 편집 */}
      {activeNode ? (
        <DocsEditor node={activeNode} pathLabel={[catNode, petNode, typeNode, subNode].filter(Boolean).map((n) => n!.name).join(" > ")}
          templates={templates ?? []} hwpxTemplates={hwpxTemplates ?? []} onChanged={refresh} filterMode={filterMode} />
      ) : (
        <div className="hw-card text-sm text-gray-500">위에서 항목을 선택하면 해당 단계의 필요서류를 관리할 수 있습니다.</div>
      )}
    </div>
  );
}

// ── 트리 컬럼 (노드 목록 + 추가/수정/숨김/완전삭제) ──────────────────────────
function NodeColumn({
  level, parentId, items, selectedId, onSelect, onChanged, disabledHint, filterMode,
}: {
  level: DocNodeLevel; parentId: number | null; items: AdminDocNode[];
  selectedId: number | null; onSelect: (id: number) => void; onChanged: () => void;
  disabledHint?: string; filterMode: FilterMode;
}) {
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [editId, setEditId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [hardDeleteTarget, setHardDeleteTarget] = useState<{ node: AdminDocNode; impact: DocNodeDeleteImpact } | null>(null);
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
    onSuccess: (_r, { is_active }) => { toast.success(is_active ? "복원됨" : "숨김 처리됨"); onChanged(); },
    onError: (e) => toast.error(errMsg(e, "변경 실패")),
  });
  const hardDeleteMut = useMutation({
    mutationFn: ({ id, cascade }: { id: number; cascade: boolean }) => docConfigApi.hardDeleteNode(id, cascade),
    onSuccess: () => { toast.success("완전삭제됨"); setHardDeleteTarget(null); onChanged(); },
    onError: (e) => toast.error(errMsg(e, "완전삭제 실패")),
  });

  const openHardDelete = async (n: AdminDocNode) => {
    try {
      const r = await docConfigApi.nodeDeleteImpact(n.id);
      setHardDeleteTarget({ node: n, impact: r.data });
    } catch (e) {
      toast.error(errMsg(e, "영향 조회 실패"));
    }
  };

  const visibleItems = items.filter((n) => filterMode === "all" || n.is_active === (filterMode === "active"));

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
          {visibleItems.map((n) => (
            <div key={n.id}
              className="flex items-center gap-1 rounded px-1.5 py-1"
              style={{
                background: selectedId === n.id ? "#FEF3C7" : "transparent",
                opacity: n.is_active ? 1 : 0.55,
              }}>
              {editId === n.id ? (
                <input autoFocus value={editName} onChange={(e) => setEditName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && editName.trim()) renameMut.mutate({ id: n.id, name: editName.trim() }); if (e.key === "Escape") setEditId(null); }}
                  style={{ flex: 1, fontSize: 12, border: "1px solid #CBD5E0", borderRadius: 4, padding: "2px 4px" }} />
              ) : (
                <button onClick={() => onSelect(n.id)} title="선택"
                  style={{ flex: 1, textAlign: "left", fontSize: 12, background: "none", border: "none", cursor: "pointer", color: n.is_active ? "#2D3748" : "#A0AEC0", fontWeight: selectedId === n.id ? 700 : 400 }}>
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
                  {n.is_active ? (
                    <button onClick={() => toggleMut.mutate({ id: n.id, is_active: false })} title="숨김 처리 — 실제 삭제되지 않고 숨김 목록으로 이동합니다"
                      style={{ color: "#718096", background: "none", border: "none", cursor: "pointer" }}><EyeOff size={12} /></button>
                  ) : (
                    <>
                      <button onClick={() => toggleMut.mutate({ id: n.id, is_active: true })} title="복원 — 다시 활성 상태로"
                        style={{ color: "#3182CE", background: "none", border: "none", cursor: "pointer" }}><Eye size={12} /></button>
                      <button onClick={() => openHardDelete(n)} title="완전삭제 — 물리 삭제, 복원 불가"
                        style={{ color: "#E53E3E", background: "none", border: "none", cursor: "pointer" }}><Trash2 size={12} /></button>
                    </>
                  )}
                </>
              )}
            </div>
          ))}
          {visibleItems.length === 0 && <div className="text-xs text-gray-400 px-1 py-2">항목 없음</div>}
        </div>
      )}

      {hardDeleteTarget && (
        <HardDeleteConfirmModal
          title={`${LEVEL_LABEL[level]} 완전삭제`}
          impactRows={[
            { label: "항목명", value: hardDeleteTarget.node.name },
            { label: "노드 ID", value: String(hardDeleteTarget.node.id) },
            { label: "하위 항목", value: `${hardDeleteTarget.impact.descendant_count}개` },
            { label: "연결된 필요서류", value: `${hardDeleteTarget.impact.doc_count}개` },
          ]}
          notice={[
            "문서자동작성 설정만 삭제됩니다.",
            "실제 HWPX·HWP·PDF 템플릿 파일은 삭제되지 않습니다.",
            "삭제 후에는 복원할 수 없습니다.",
          ]}
          cascadeChoice={hardDeleteTarget.impact.descendant_count > 0}
          blockedReason={hardDeleteTarget.impact.blocked_reason}
          confirming={hardDeleteMut.isPending}
          onCancel={() => setHardDeleteTarget(null)}
          onConfirm={() => hardDeleteMut.mutate({
            id: hardDeleteTarget.node.id,
            cascade: hardDeleteTarget.impact.descendant_count > 0,
          })}
        />
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
  node, pathLabel, templates, hwpxTemplates, onChanged, filterMode,
}: {
  node: AdminDocNode; pathLabel: string; templates: TemplateFile[];
  hwpxTemplates: HwpxTemplateFile[]; onChanged: () => void; filterMode: FilterMode;
}) {
  const docs = node.docs ?? [];
  const visible = useMemo(
    () => docs.filter((d) => filterMode === "all" || d.is_active === (filterMode === "active")),
    [docs, filterMode],
  );
  const main = useMemo(() => visible.filter((d) => d.doc_group === "main"), [visible]);
  const agent = useMemo(() => visible.filter((d) => d.doc_group === "agent"), [visible]);

  return (
    <div className="hw-card p-3 space-y-3">
      <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748" }}>
        필요서류 — <span style={{ color: GOLD }}>{pathLabel || node.name}</span>
        <span className="text-xs text-gray-400 font-normal ml-2">({LEVEL_LABEL[node.level]} 노드에 연결)</span>
      </div>
      <DocGroup title="민원 서류" group="main" nodeId={node.id} items={main} templates={templates} hwpxTemplates={hwpxTemplates} onChanged={onChanged} />
      <DocGroup title="행정사 서류" group="agent" nodeId={node.id} items={agent} templates={templates} hwpxTemplates={hwpxTemplates} onChanged={onChanged} />
    </div>
  );
}

function DocGroup({
  title, group, nodeId, items, templates, hwpxTemplates, onChanged,
}: {
  title: string; group: "main" | "agent"; nodeId: number; items: AdminReqDoc[];
  templates: TemplateFile[]; hwpxTemplates: HwpxTemplateFile[]; onChanged: () => void;
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
        {items.map((d) => <DocRow key={d.id} doc={d} templates={templates} hwpxTemplates={hwpxTemplates} onChanged={onChanged} />)}
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

// 서류명 ↔ HWPX 파일명 자동매칭(레지스트리)과 동일한 정규화 — 공백 제거 비교.
// 표시용 근사치이며, 실제 생성 시 해석은 서버 레지스트리가 담당한다.
function normalizeDocName(s: string): string {
  return (s || "").replace(/\s+/g, "");
}

function autoHwpxMatch(docName: string, hwpxTemplates: HwpxTemplateFile[]): HwpxTemplateFile | null {
  const key = normalizeDocName(docName);
  if (!key) return null;
  return hwpxTemplates.find((t) => normalizeDocName(t.display_name) === key) ?? null;
}

// 출력방식 표기 — DB 값은 그대로(pdf/hwpx/both/disabled/""), 라벨만 HWPX 중심으로.
const OUTPUT_FORMAT_LABEL: Record<string, string> = {
  "": "자동", hwpx: "HWPX 우선", pdf: "PDF만", both: "둘 다 생성", disabled: "비활성",
};

// ── HWPX 필드 진단 배지 (행 내 상시 표시 — 핵심 기능) ────────────────────────
// 정상: 미매핑 0~2 + 미인식 marker 0 / 주의: 미매핑 3+ 또는 미인식 marker / 위험: 템플릿 없음·추출 실패
function HwpxDiagBadge({ filename, onOpenDetail }: { filename: string; onOpenDetail: () => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["doc-config-hwpx-fields", filename],
    queryFn: () => docConfigApi.getHwpxFields(filename).then((r) => r.data as HwpxFieldsResponse),
    staleTime: 5 * 60_000,   // 템플릿 파일은 자주 안 바뀜 — 같은 파일명 행들이 캐시 공유
  });
  if (isLoading) return <span style={{ fontSize: 10, color: "#A0AEC0" }}>진단 중…</span>;
  if (error || !data) {
    return (
      <span style={{ fontSize: 10, fontWeight: 700, padding: "1px 8px", borderRadius: 9, background: "#FED7D7", color: "#822727" }}>
        위험 · 필드 추출 실패
      </span>
    );
  }
  const s = data.summary;
  const level = s.unmapped >= 3 || s.unknown_markers > 0 ? "주의" : "정상";
  const c = level === "정상" ? { bg: "#C6F6D5", fg: "#22543D" } : { bg: "#FEEBC8", fg: "#7B341E" };
  return (
    <button onClick={onOpenDetail} title="클릭하면 필드 비교 상세를 엽니다"
      style={{ fontSize: 10, border: "none", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 5, background: "none", padding: 0 }}>
      <span style={{ fontWeight: 700, padding: "1px 8px", borderRadius: 9, background: c.bg, color: c.fg }}>{level}</span>
      <span style={{ color: "#4A5568" }}>
        필드 {s.field_count} · 채움 {s.fillable + s.fillable_split} · 미매핑 {s.unmapped} · marker {s.marker_count}
        {s.unknown_markers > 0 && <b style={{ color: "#C53030" }}> · 미인식 {s.unknown_markers}</b>}
      </span>
    </button>
  );
}

function DocRow({ doc, templates, hwpxTemplates, onChanged }: {
  doc: AdminReqDoc; templates: TemplateFile[]; hwpxTemplates: HwpxTemplateFile[]; onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(doc.name);
  const [pdfOpen, setPdfOpen] = useState(false);       // PDF fallback 접힘(기본 닫힘)
  const [fieldsModal, setFieldsModal] = useState<string | null>(null);
  const [hardDeleteImpact, setHardDeleteImpact] = useState<DocRequiredDocDeleteImpact | null>(null);

  const updateMut = useMutation({
    mutationFn: (data: Parameters<typeof docConfigApi.updateDoc>[1]) => docConfigApi.updateDoc(doc.id, data),
    onSuccess: () => { toast.success("저장됨"); setEditing(false); onChanged(); },
    onError: (e) => toast.error(errMsg(e, "저장 실패")),
  });
  const remapMut = useMutation({
    mutationFn: () => docConfigApi.remapDoc(doc.id),
    onSuccess: (r) => { const d = r.data as AdminReqDoc; toast.success(d.template_status === "mapped" ? `PDF 매핑됨: ${d.template_filename}` : "매칭되는 PDF 없음 ⚠"); onChanged(); },
    onError: (e) => toast.error(errMsg(e, "자동매핑 실패")),
  });
  const hardDeleteMut = useMutation({
    mutationFn: () => docConfigApi.hardDeleteDoc(doc.id),
    onSuccess: () => { toast.success("완전삭제됨"); setHardDeleteImpact(null); onChanged(); },
    onError: (e) => toast.error(errMsg(e, "완전삭제 실패")),
  });

  const openHardDelete = async () => {
    try {
      const r = await docConfigApi.docDeleteImpact(doc.id);
      setHardDeleteImpact(r.data);
    } catch (e) {
      toast.error(errMsg(e, "영향 조회 실패"));
    }
  };

  const pdfMapped = doc.template_status === "mapped" && !!doc.template_filename;
  // HWPX 해석(표시용): 명시 매핑 > 파일명 정규화 자동매칭. 실제 생성 해석은 서버가 담당.
  const hwpxExplicit = doc.hwpx_template_filename || "";
  const hwpxAuto = autoHwpxMatch(doc.name, hwpxTemplates);
  const hwpxResolved = hwpxExplicit || hwpxAuto?.filename || "";

  return (
    <div className="rounded px-2 py-1.5" style={{ background: "#F7FAFC", opacity: doc.is_active ? 1 : 0.45 }}>
      {/* 1줄: 서류명 + 출력방식 + 관리 버튼 */}
      <div className="flex items-center gap-1.5">
        {editing ? (
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) updateMut.mutate({ name: name.trim() }); if (e.key === "Escape") setEditing(false); }}
            style={{ flex: 1, fontSize: 12, border: "1px solid #CBD5E0", borderRadius: 4, padding: "2px 4px" }} />
        ) : (
          <span style={{ flex: 1, fontSize: 12, fontWeight: 600, color: "#2D3748" }}>{doc.name}{!doc.is_active && " (숨김)"}</span>
        )}
        <select value={doc.output_format ?? ""}
          onChange={(e) => updateMut.mutate({ output_format: e.target.value })}
          title="출력방식 — 자동: 템플릿 존재 여부에 따름 / HWPX 우선·PDF만·비활성은 생성 API에서 강제됨"
          style={{ fontSize: 10, fontWeight: 600, border: "1px solid #D6BCFA", borderRadius: 4, padding: "1px 3px", color: "#553C9A", background: "#FAF5FF" }}>
          {Object.entries(OUTPUT_FORMAT_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        {editing ? (
          <button onClick={() => updateMut.mutate({ name: name.trim() })} disabled={!name.trim()}
            style={{ fontSize: 11, color: GOLD, background: "none", border: "none", cursor: "pointer" }}>저장</button>
        ) : (
          <>
            <button onClick={() => { setName(doc.name); setEditing(true); }} title="이름 수정"
              style={{ color: "#718096", background: "none", border: "none", cursor: "pointer" }}><Pencil size={12} /></button>
            {doc.is_active ? (
              <button onClick={() => updateMut.mutate({ is_active: false })} title="숨김 처리 — 실제 삭제되지 않고 숨김 목록으로 이동합니다"
                style={{ color: "#718096", background: "none", border: "none", cursor: "pointer" }}><EyeOff size={12} /></button>
            ) : (
              <>
                <button onClick={() => updateMut.mutate({ is_active: true })} title="복원 — 다시 활성 상태로"
                  style={{ color: "#3182CE", background: "none", border: "none", cursor: "pointer" }}><Eye size={12} /></button>
                <button onClick={openHardDelete} title="완전삭제 — 물리 삭제, 복원 불가"
                  style={{ color: "#E53E3E", background: "none", border: "none", cursor: "pointer" }}><Trash2 size={12} /></button>
              </>
            )}
          </>
        )}
      </div>

      {/* 2줄: HWPX 주 출력 — 템플릿 선택 + 상시 필드 진단 */}
      <div className="flex flex-wrap items-center gap-1.5 mt-1">
        <span style={{ fontSize: 10, fontWeight: 700, color: "#2B6CB0", width: 64, flexShrink: 0 }}>주 출력 HWPX</span>
        <select value={hwpxExplicit}
          onChange={(e) => updateMut.mutate({ hwpx_template_filename: e.target.value })}
          title={hwpxExplicit ? `명시 매핑: ${hwpxExplicit}` : hwpxResolved ? `자동매칭: ${hwpxResolved}` : "매칭되는 HWPX 없음"}
          style={{ fontSize: 11, border: "1px solid #90CDF4", borderRadius: 4, padding: "1px 3px", maxWidth: 230, color: "#2C5282", background: "#EBF8FF" }}>
          <option value="">{hwpxResolved && !hwpxExplicit ? `(자동) ${hwpxResolved}` : "(자동매칭)"}</option>
          {hwpxTemplates.map((t) => (
            <option key={t.filename} value={t.filename}>{t.filename}</option>
          ))}
        </select>
        {hwpxResolved ? (
          <HwpxDiagBadge filename={hwpxResolved} onOpenDetail={() => setFieldsModal(hwpxResolved)} />
        ) : (
          <span style={{ fontSize: 10, fontWeight: 700, padding: "1px 8px", borderRadius: 9, background: "#FED7D7", color: "#822727" }}>
            위험 · HWPX 템플릿 없음
          </span>
        )}
        {hwpxResolved && (
          <button onClick={() => setFieldsModal(hwpxResolved)} title="필드 비교 상세"
            style={{ color: "#2B6CB0", background: "none", border: "none", cursor: "pointer" }}><FileSearch size={12} /></button>
        )}
      </div>

      {/* 3줄: PDF fallback — 접힘(기본 닫힘) */}
      <div className="mt-1">
        <button onClick={() => setPdfOpen(!pdfOpen)}
          style={{ fontSize: 10, color: "#718096", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
          {pdfOpen ? "▲" : "▼"} PDF fallback {pdfMapped ? `(${doc.template_filename})` : "(없음)"}
        </button>
        {pdfOpen && (
          <div className="flex flex-wrap items-center gap-1.5 mt-1" style={{ paddingLeft: 8 }}>
            {pdfMapped ? (
              <span title={`PDF: ${doc.template_filename}`} style={{ fontSize: 10, color: "#2F855A", display: "inline-flex", alignItems: "center", gap: 2 }}>
                <FileCheck size={11} /> {doc.template_filename}
              </span>
            ) : (
              <span title="templates 폴더에 일치하는 PDF 없음" style={{ fontSize: 10, color: "#C05621", display: "inline-flex", alignItems: "center", gap: 2 }}>
                <FileWarning size={11} /> PDF 템플릿 없음
              </span>
            )}
            <select value={doc.template_filename}
              onChange={(e) => updateMut.mutate({ template_filename: e.target.value })}
              title="PDF 템플릿 직접 선택"
              style={{ fontSize: 10, border: "1px solid #CBD5E0", borderRadius: 4, padding: "1px 3px", maxWidth: 200 }}>
              <option value="">(연결 해제)</option>
              {templates.map((t) => <option key={t.filename} value={t.filename}>{t.filename}</option>)}
            </select>
            <button onClick={() => remapMut.mutate()} title="PDF 자동매핑 재계산"
              style={{ fontSize: 10, color: "#718096", background: "none", border: "none", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 2 }}>
              <RotateCcw size={11} /> 재계산
            </button>
          </div>
        )}
      </div>

      {fieldsModal && (
        <HwpxFieldsModal filename={fieldsModal} onClose={() => setFieldsModal(null)} />
      )}

      {hardDeleteImpact && (
        <HardDeleteConfirmModal
          title="필요서류 완전삭제"
          impactRows={[
            { label: "항목명", value: hardDeleteImpact.name },
            { label: "구분", value: hardDeleteImpact.doc_group === "main" ? "민원 서류" : "행정사 서류" },
          ]}
          notice={[
            "문서자동작성 설정만 삭제됩니다.",
            "실제 HWPX·HWP·PDF 템플릿 파일은 삭제되지 않습니다.",
            "삭제 후에는 복원할 수 없습니다.",
          ]}
          blockedReason={hardDeleteImpact.blocked_reason}
          confirming={hardDeleteMut.isPending}
          onCancel={() => setHardDeleteImpact(null)}
          onConfirm={() => hardDeleteMut.mutate()}
        />
      )}
    </div>
  );
}

// ── HWPX 필드/marker 보기 모달 ───────────────────────────────────────────────
function HwpxFieldsModal({ filename, onClose }: { filename: string; onClose: () => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["doc-config-hwpx-fields", filename],
    queryFn: () => docConfigApi.getHwpxFields(filename).then((r) => r.data as HwpxFieldsResponse),
  });

  const STATUS_LABEL: Record<string, { label: string; color: string }> = {
    fillable: { label: "채움 가능", color: "#2F855A" },
    fillable_split: { label: "채움 가능(분할)", color: "#2B6CB0" },
    unmapped: { label: "미매핑(공백 처리)", color: "#C05621" },
  };

  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 200, display: "flex", alignItems: "center", justifyContent: "center" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="hw-card"
        style={{ width: "min(640px, 92vw)", maxHeight: "80vh", overflowY: "auto", padding: 16 }}
      >
        <div style={{ display: "flex", alignItems: "center", marginBottom: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748" }}>HWPX 필드 — {filename}</div>
          <button onClick={onClose} style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", color: "#718096" }}>
            <X size={16} />
          </button>
        </div>

        {isLoading && <div className="text-sm text-gray-400">분석 중…</div>}
        {!!error && <div className="text-sm" style={{ color: "#C53030" }}>필드 추출 실패: {errMsg(error, "오류")}</div>}

        {data && (
          <>
            {/* 요약 */}
            <div style={{ display: "flex", gap: 12, flexWrap: "wrap", fontSize: 11, color: "#4A5568", marginBottom: 10 }}>
              <span>필드 <b>{data.summary.field_count}</b></span>
              <span style={{ color: "#2F855A" }}>채움 가능 <b>{data.summary.fillable}</b></span>
              <span style={{ color: "#2B6CB0" }}>분할 채움 <b>{data.summary.fillable_split}</b></span>
              <span style={{ color: "#C05621" }}>미매핑 <b>{data.summary.unmapped}</b></span>
              <span style={{ color: "#805AD5" }}>marker <b>{data.summary.marker_count}</b></span>
              {data.summary.unknown_markers > 0 && (
                <span style={{ color: "#C53030" }}>미인식 marker <b>{data.summary.unknown_markers}</b></span>
              )}
            </div>

            {/* marker */}
            {(data.seal_markers.length > 0 || data.sign_markers.length > 0) && (
              <div style={{ fontSize: 11, marginBottom: 10 }}>
                <div style={{ fontWeight: 700, color: "#4A5568", marginBottom: 3 }}>도장/서명 marker</div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {data.seal_markers.map((m) => (
                    <span key={m.marker} title={m.known ? "도장 marker (역할 매핑 있음)" : "미인식 marker — 역할 매핑 없음"}
                      style={{ padding: "2px 8px", borderRadius: 10, background: m.known ? "#FEEBC8" : "#FED7D7", color: m.known ? "#7B341E" : "#822727" }}>
                      {m.marker} 도장{!m.known && " ⚠"}
                    </span>
                  ))}
                  {data.sign_markers.map((m) => (
                    <span key={m.marker} title={m.known ? "서명 marker (역할 매핑 있음)" : "미인식 marker — 역할 매핑 없음"}
                      style={{ padding: "2px 8px", borderRadius: 10, background: m.known ? "#E9D8FD" : "#FED7D7", color: m.known ? "#553C9A" : "#822727" }}>
                      {m.marker} 서명{!m.known && " ⚠"}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* 필드 표 */}
            <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ color: "#718096", textAlign: "left" }}>
                  <th style={{ padding: "3px 6px", borderBottom: "1px solid #E2E8F0" }}>필드명 (fieldBegin name)</th>
                  <th style={{ padding: "3px 6px", borderBottom: "1px solid #E2E8F0", width: 40 }}>개수</th>
                  <th style={{ padding: "3px 6px", borderBottom: "1px solid #E2E8F0", width: 130 }}>상태</th>
                </tr>
              </thead>
              <tbody>
                {data.fields.map((f) => {
                  const st = STATUS_LABEL[f.status] ?? { label: f.status, color: "#4A5568" };
                  return (
                    <tr key={f.name}>
                      <td style={{ padding: "3px 6px", borderBottom: "1px solid #F7FAFC", fontFamily: "monospace" }}>{f.name}</td>
                      <td style={{ padding: "3px 6px", borderBottom: "1px solid #F7FAFC" }}>{f.count}</td>
                      <td style={{ padding: "3px 6px", borderBottom: "1px solid #F7FAFC", color: st.color, fontWeight: 600 }}>{st.label}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            <div style={{ fontSize: 10, color: "#A0AEC0", marginTop: 8, lineHeight: 1.5 }}>
              · 미매핑 필드는 생성 시 <b>공백(&quot; &quot;)</b>으로 채워져 안내문이 숨겨집니다(기존 원칙).<br />
              · 도장 marker는 도장 이미지(없으면 투명 PNG), 서명 marker는 서명 이미지(없으면 투명 PNG)로만 채워집니다 — 교차 대체 없음.<br />
              · 상태는 시스템 필드 카탈로그(더미 데이터 열거) 기준 근사치이며, 실제 값은 고객 데이터에 따라 달라집니다.
            </div>
          </>
        )}
      </div>
    </div>
  );
}
