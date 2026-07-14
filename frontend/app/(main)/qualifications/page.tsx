"use client";
// v3 자격 중심 실무지침 — 화면 1: 자격 선택 (전 로그인 사용자 조회, FEATURE_GUIDELINES_V3)
// 편집 UI 는 서버 editable(관리자+FEATURE_GUIDELINES_V3_EDIT)일 때만 노출.
// 대분류(그룹)는 서버 제공(오버레이 편집 가능) — 미제공 시 GROUP_LABEL fallback.
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, Loader2, Search } from "lucide-react";
import { guidelinesV3Api, V3Aux, V3DeleteImpact, V3Group, V3Program, V3Qualification } from "@/lib/api";
import { ProgramChip } from "@/components/qualifications/common";
import { GuidelineCard, buildQuickDocUrl } from "@/components/guidelines/shared";
import {
  EditIconButton, EntityEditModal, FieldSpec, GROUP_FIELDS, ImpactDialog,
  qualFields, runDelete,
} from "@/components/qualifications/editV3";

const GROUP_LABEL: Record<string, string> = {
  A: "A 계열 (외교·공무·협정)",
  B: "B 계열 (사증면제·관광통과)",
  C: "C 계열 (단기)",
  D: "D 계열 (유학·투자·주재 등)",
  E: "E 계열 (취업)",
  F: "F 계열 (동거·거주·동포·영주·결혼)",
  G: "G 계열 (기타)",
  H: "H 계열 (관광취업·방문취업)",
};

type EditModalState = {
  etype: "group" | "qualification";
  mode: "create" | "edit";
  title: string;
  fields: FieldSpec[];
  initial: Record<string, unknown>;
  id?: string;
} | null;

function QualCard({ q, onClick, editMode, onEdit, onDelete }: {
  q: V3Qualification; onClick: () => void; editMode?: boolean;
  onEdit?: () => void; onDelete?: () => void;
}) {
  const s = q.summary;
  const confirmed = (s?.applicable ?? 0) + (s?.not_applicable ?? 0) + (s?.conditional ?? 0);
  const total = confirmed + (s?.unknown ?? 0);
  return (
    <div onClick={onClick}
      style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", padding:"14px 16px",
        cursor:"pointer", transition:"border-color 0.15s" }}
      onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.borderColor = "var(--hw-gold)"; }}
      onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.borderColor = "#E2E8F0"; }}>
      <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:6, flexWrap:"wrap" }}>
        <span style={{ fontSize:15, fontWeight:700, color:"#2D3748" }}>{q.code}</span>
        <span style={{ fontSize:13, color:"#4A5568", flex:1 }}>{q.name_ko}</span>
        {editMode && onEdit && <EditIconButton kind="edit" title="자격 수정" onClick={onEdit} />}
        {editMode && onDelete && <EditIconButton kind="delete" title="자격 삭제" onClick={onDelete} />}
      </div>
      <div style={{ display:"flex", alignItems:"center", gap:6, flexWrap:"wrap", fontSize:11, color:"#718096" }}>
        <span>체류업무 {confirmed}/{total} 확정</span>
        {(s?.not_applicable ?? 0) > 0 && <span style={{ color:"#4A5568" }}>· 불가 {s!.not_applicable}</span>}
        {(s?.conditional ?? 0) > 0 && <span style={{ color:"#975A16" }}>· 조건부 {s!.conditional}</span>}
        {(s?.recognition_count ?? 0) > 0 && <span>· 인정서 경로 {s!.recognition_count}</span>}
        {(s?.visa_count ?? 0) > 0 && <span>· 사증 경로 {s!.visa_count}</span>}
        {(q.child_count ?? 0) > 0 && <span>· 세부약호 {q.child_count}</span>}
      </div>
      {q.delegated_to && (
        <div style={{ marginTop:6, fontSize:11, color:"var(--hw-gold-text)" }}>※ 동포매뉴얼 기준(본편 위임)</div>
      )}
    </div>
  );
}

// 보조 민원(격자 밖 기타 신청·신고) 카드 — 자격 선택 없이 진행되는 민원. 격자와 시각 분리(회색 톤).
function AuxCard({ a, expanded, onToggle, onQuickDoc }: {
  a: V3Aux; expanded: boolean; onToggle: () => void; onQuickDoc: (url: string) => void;
}) {
  const url = a.v2_row ? buildQuickDocUrl(a.v2_row) : null;
  return (
    <div style={{ background:"#FAFAFA", borderRadius:12, border:"1px solid #E2E8F0" }}>
      <div onClick={onToggle} style={{ padding:"12px 16px", cursor:"pointer" }}>
        <div style={{ fontSize:13.5, fontWeight:600, color:"#4A5568", marginBottom:3 }}>{a.name}</div>
        {a.description && (
          <div style={{ fontSize:11.5, color:"#A0AEC0", lineHeight:1.5 }}>
            {a.description.length > 70 ? a.description.slice(0, 70) + "…" : a.description}
          </div>
        )}
      </div>
      {expanded && (
        <div style={{ padding:"0 16px 14px" }}>
          {(a.requirements?.length ?? 0) > 0 && (
            <div style={{ marginBottom:8 }}>
              <div style={{ fontSize:10, fontWeight:700, color:"#4A5568", marginBottom:4 }}>
                서류 (v3 기준 · {a.requirements!.length}건)
              </div>
              {a.requirements!.map(d => (
                <div key={d.requirement_id} style={{ fontSize:11.5, color:"#4A5568", padding:"2px 0" }}>
                  · {d.doc_name}{d.doc_role === "conditional" && d.condition ? ` (조건: ${d.condition})` : ""}
                </div>
              ))}
            </div>
          )}
          {a.v2_row ? (
            <>
              <GuidelineCard row={a.v2_row} isSelected={false} onClick={() => {}} />
              {url && (
                <button onClick={() => onQuickDoc(url)}
                  style={{ marginTop:6, display:"inline-flex", alignItems:"center", gap:5, fontSize:11,
                    padding:"4px 12px", borderRadius:20, border:"1px solid rgba(212,168,67,0.45)",
                    background:"rgba(212,168,67,0.08)", color:"var(--hw-gold-text)", cursor:"pointer", fontWeight:600 }}>
                  <FileText size={12} /> 문서자동작성으로
                </button>
              )}
            </>
          ) : (
            <div style={{ fontSize:12, color:"#A0AEC0" }}>연결된 기존 지침 없음</div>
          )}
        </div>
      )}
    </div>
  );
}

function ProgramCard({ p, onCodeClick }: { p: V3Program; onCodeClick: (code: string) => void }) {
  return (
    <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", padding:"14px 16px" }}>
      <div style={{ marginBottom:8 }}><ProgramChip program={p} /></div>
      {p.ladder.length > 0 ? (
        <div style={{ display:"flex", alignItems:"center", gap:4, flexWrap:"wrap", fontSize:12 }}>
          {p.ladder.map((st, i) => (
            <span key={st.code} style={{ display:"inline-flex", alignItems:"center", gap:4 }}>
              {i > 0 && <span style={{ color:"#CBD5E0" }}>→</span>}
              <button onClick={() => onCodeClick(st.code)}
                style={{ fontSize:12, fontWeight:600, color:"#2D3748", background:"#F7FAFC",
                  border:"1px solid #E2E8F0", borderRadius:8, padding:"3px 8px", cursor:"pointer" }}>
                {st.code} <span style={{ fontWeight:400, color:"#718096" }}>{st.label}</span>
              </button>
            </span>
          ))}
        </div>
      ) : (
        <div style={{ fontSize:12, color:"#718096" }}>{p.applies_to.join(" · ")}</div>
      )}
      {/* 표시 정제: 데이터 무수정 원칙 — description의 내부용 어휘만 화면에서 치환 */}
      {p.description && <div style={{ marginTop:8, fontSize:11, color:"#A0AEC0", lineHeight:1.5 }}>{p.description.replace(/원문/g, "전문")}</div>}
    </div>
  );
}

export default function QualificationsPage() {
  const router = useRouter();

  const [items, setItems] = useState<V3Qualification[]>([]);
  const [programs, setPrograms] = useState<V3Program[]>([]);
  const [srvGroups, setSrvGroups] = useState<V3Group[]>([]);
  const [editable, setEditable] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [modal, setModal] = useState<EditModalState>(null);
  const [impactState, setImpactState] = useState<{
    etype: "group" | "qualification"; id: string; label: string;
    impact: V3DeleteImpact; cascadeAllowed: boolean;
  } | null>(null);
  const [auxItems, setAuxItems] = useState<V3Aux[]>([]);
  const [expandedAux, setExpandedAux] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");

  // 조회는 전 로그인 사용자 — 편집 노출 여부는 서버 editable(관리자+플래그)로만 판단
  const reload = useCallback(() => {
    guidelinesV3Api.listQualifications()
      .then(res => {
        setItems(res.data.data);
        setPrograms(res.data.programs ?? []);
        setSrvGroups(res.data.groups ?? []);
        setEditable(res.data.editable ?? false);
      })
      .catch(e => {
        setError(e?.response?.status === 404
          ? "v3 자격 중심 화면이 비활성 상태입니다 (FEATURE_GUIDELINES_V3 off 또는 데이터 없음)."
          : "v3 데이터를 불러오지 못했습니다.");
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    reload();
    // 보조 민원(별도 축) — 실패해도 자격 화면은 정상 동작
    guidelinesV3Api.listAux()
      .then(res => setAuxItems(res.data.data))
      .catch(() => setAuxItems([]));
  }, [reload]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(m =>
      m.code.toLowerCase().includes(q) || m.name_ko.includes(query.trim())
      || (m.sub_codes ?? []).some(c => c.toLowerCase().includes(q)));
  }, [items, query]);

  // 대분류 정의: 서버 groups 우선(편집 가능), 없으면 GROUP_LABEL fallback
  const groupDefs = useMemo<V3Group[]>(() => {
    if (srvGroups.length > 0) return srvGroups;
    return Object.entries(GROUP_LABEL).map(([k, label], i) =>
      ({ group_key: k, label, sort_order: (i + 1) * 10 }));
  }, [srvGroups]);

  const groups = useMemo(() => {
    const byKey = new Map<string, V3Qualification[]>(groupDefs.map(g => [g.group_key, []]));
    const extra = new Map<string, V3Qualification[]>();
    filtered.forEach(m => {
      if (byKey.has(m.group)) byKey.get(m.group)!.push(m);
      else {
        if (!extra.has(m.group)) extra.set(m.group, []);
        extra.get(m.group)!.push(m);
      }
    });
    const ordered: { def: V3Group; quals: V3Qualification[] }[] =
      groupDefs.map(g => ({ def: g, quals: byKey.get(g.group_key)! }));
    Array.from(extra.entries()).sort(([a], [b]) => a.localeCompare(b))
      .forEach(([k, quals]) => ordered.push({ def: { group_key: k, label: `${k} 계열` }, quals }));
    // 빈 대분류는 편집 모드에서만 표시(추가 직후 관리 가능하도록)
    return ordered.filter(x => x.quals.length > 0 || (editMode && !query.trim()));
  }, [groupDefs, filtered, editMode, query]);

  const groupOptions = useMemo(
    () => groupDefs.map(g => ({ value: g.group_key, label: g.label })), [groupDefs]);

  const saveModal = useCallback(async (payload: Record<string, unknown>) => {
    if (!modal) return;
    if (modal.mode === "edit" && modal.id) {
      await guidelinesV3Api.editUpdate(modal.etype, modal.id, payload);
    } else {
      await guidelinesV3Api.editCreate(modal.etype, payload);
    }
    reload();
  }, [modal, reload]);

  return (
    <div style={{ padding:24, maxWidth:1200, margin:"0 auto" }}>
      <div style={{ display:"flex", alignItems:"center", gap:12, marginBottom:6, flexWrap:"wrap" }}>
        <h1 style={{ fontSize:20, fontWeight:700, color:"#2D3748", margin:0 }}>실무지침</h1>
        <span style={{ fontSize:11, fontWeight:700, padding:"3px 10px", borderRadius:99,
          background:"rgba(212,168,67,0.10)", color:"var(--hw-gold-text)", border:"1px solid rgba(212,168,67,0.35)" }}>
          v3 기준
        </span>
      </div>
      <div style={{ fontSize:12, color:"#718096", marginBottom:12 }}>
        손님의 체류자격을 선택하면 가능한 업무·사증 경로를 안내합니다.
        기존 실무지침 화면·데이터는 그대로 유지됩니다.
      </div>

      {/* 검색 방식 탭 — 자격별 찾기가 기본, 기존 방식은 보조 탭으로 유지 */}
      <div style={{ display:"flex", gap:8, marginBottom:14, flexWrap:"wrap", alignItems:"center" }}>
        <button
          style={{ display:"flex", alignItems:"center", gap:5, fontSize:12, padding:"6px 14px", borderRadius:20,
            border:"1.5px solid var(--hw-gold)", background:"rgba(212,168,67,0.08)",
            color:"var(--hw-gold-text)", fontWeight:700, cursor:"default" }}>
          자격별 찾기
        </button>
        <button onClick={() => router.push("/guidelines?view=class")}
          style={{ display:"flex", alignItems:"center", gap:5, fontSize:12, padding:"6px 14px", borderRadius:20,
            border:"1.5px solid #CBD5E0", background:"#fff", color:"#718096", fontWeight:400, cursor:"pointer" }}>
          분류별 찾기
        </button>
        <button onClick={() => router.push("/guidelines?view=work")}
          style={{ display:"flex", alignItems:"center", gap:5, fontSize:12, padding:"6px 14px", borderRadius:20,
            border:"1.5px solid #CBD5E0", background:"#fff", color:"#718096", fontWeight:400, cursor:"pointer" }}>
          업무별 찾기
        </button>
        {editable && (
          <button onClick={() => setEditMode(m => !m)}
            style={{ display:"flex", alignItems:"center", gap:5, fontSize:12, padding:"6px 14px", borderRadius:20,
              marginLeft:"auto",
              border:`1.5px solid ${editMode ? "#C53030" : "#CBD5E0"}`,
              background: editMode ? "#FFF5F5" : "#fff",
              color: editMode ? "#C53030" : "#718096", fontWeight: editMode ? 700 : 400, cursor:"pointer" }}>
            {editMode ? "편집 종료" : "편집"}
          </button>
        )}
        {editable && editMode && (
          <button onClick={() => setModal({ etype:"group", mode:"create", title:"대분류 추가",
            fields: GROUP_FIELDS, initial: { is_active: true, sort_order: 900 } })}
            style={{ display:"flex", alignItems:"center", gap:5, fontSize:12, padding:"6px 14px", borderRadius:20,
              border:"1.5px solid rgba(212,168,67,0.55)", background:"rgba(212,168,67,0.08)",
              color:"var(--hw-gold-text)", fontWeight:700, cursor:"pointer" }}>
            + 대분류
          </button>
        )}
      </div>

      <div style={{ position:"relative", maxWidth:380, marginBottom:20 }}>
        <Search size={14} style={{ position:"absolute", left:12, top:11, color:"#A0AEC0" }} />
        <input value={query} onChange={e => setQuery(e.target.value)}
          placeholder="자격명/코드 검색 (예: F-2, 계절근로)"
          style={{ width:"100%", height:36, padding:"0 12px 0 34px", fontSize:13,
            border:"1px solid #E2E8F0", borderRadius:20, outline:"none" }} />
      </div>

      {loading ? (
        <div style={{ display:"flex", justifyContent:"center", padding:"60px 0" }}>
          <Loader2 size={24} className="animate-spin" style={{ color:"var(--hw-gold)" }} />
        </div>
      ) : error ? (
        <div style={{ padding:"14px 16px", borderRadius:10, background:"#FFF5F5",
          border:"1px solid #FEB2B2", color:"#C53030", fontSize:13, fontWeight:600 }}>
          {error}
        </div>
      ) : (
        <>
          {groups.map(({ def, quals }) => (
            <div key={def.group_key} style={{ marginBottom:22 }}>
              <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:10 }}>
                <span style={{ fontSize:13, fontWeight:700, color:"#4A5568" }}>
                  {def.label} <span style={{ fontWeight:400, color:"#A0AEC0" }}>({quals.length})</span>
                </span>
                {editMode && (
                  <>
                    <EditIconButton kind="edit" title="대분류 수정"
                      onClick={() => setModal({ etype:"group", mode:"edit", id:def.group_key,
                        title:`대분류 수정 — ${def.label}`,
                        fields: GROUP_FIELDS.map(f => f.key === "group_key" ? { ...f, readOnly:true } : f),
                        initial: def as unknown as Record<string, unknown> })} />
                    <EditIconButton kind="delete" title="대분류 삭제"
                      onClick={() => runDelete("group", def.group_key, def.label,
                        (impact, cascadeAllowed) => setImpactState({ etype:"group", id:def.group_key,
                          label:def.label, impact, cascadeAllowed }),
                        reload)} />
                    <EditIconButton kind="add" title="자격 추가"
                      onClick={() => setModal({ etype:"qualification", mode:"create",
                        title:`자격 추가 — ${def.label}`,
                        fields: qualFields(groupOptions, false),
                        initial: { group: def.group_key, is_active: true } })} />
                  </>
                )}
              </div>
              <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(230px, 1fr))", gap:10 }}>
                {quals.map(q => (
                  <QualCard key={q.qualification_id} q={q} editMode={editMode}
                    onClick={() => router.push(`/qualifications/${encodeURIComponent(q.code)}`)}
                    onEdit={() => setModal({ etype:"qualification", mode:"edit", id:q.qualification_id,
                      title:`자격 수정 — ${q.code} ${q.name_ko}`,
                      fields: qualFields(groupOptions, false).map(f => f.key === "code" ? { ...f, readOnly:true } : f),
                      initial: q as unknown as Record<string, unknown> })}
                    onDelete={() => runDelete("qualification", q.qualification_id, `${q.code} ${q.name_ko}`,
                      (impact, cascadeAllowed) => setImpactState({ etype:"qualification",
                        id:q.qualification_id, label:`${q.code} ${q.name_ko}`, impact, cascadeAllowed }),
                      reload)} />
                ))}
              </div>
            </div>
          ))}
          {programs.length > 0 && (
            <div style={{ marginTop:28 }}>
              <div style={{ fontSize:13, fontWeight:700, color:"#4A5568", marginBottom:10 }}>
                특별제도 · 프로그램 <span style={{ fontWeight:400, color:"#A0AEC0" }}>({programs.length})</span>
              </div>
              <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(320px, 1fr))", gap:10 }}>
                {programs.map(p => (
                  <ProgramCard key={p.program_id} p={p}
                    onCodeClick={code => router.push(`/qualifications/${encodeURIComponent(code)}`)} />
                ))}
              </div>
            </div>
          )}
          {auxItems.length > 0 && (
            <div style={{ marginTop:28 }}>
              <div style={{ fontSize:13, fontWeight:700, color:"#718096", marginBottom:4 }}>
                기타 신청·신고 (보조 민원) <span style={{ fontWeight:400, color:"#A0AEC0" }}>({auxItems.length})</span>
              </div>
              <div style={{ fontSize:11.5, color:"#A0AEC0", marginBottom:10 }}>
                매뉴얼의 자격×업무 체계 밖의 민원(사실증명 등) — 자격 선택 없이 진행합니다.
              </div>
              <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(320px, 1fr))", gap:10 }}>
                {auxItems.map(a => (
                  <AuxCard key={a.aux_id} a={a}
                    expanded={expandedAux === a.aux_id}
                    onToggle={() => setExpandedAux(expandedAux === a.aux_id ? null : a.aux_id)}
                    onQuickDoc={url => router.push(url)} />
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* 편집 모달 + 삭제 영향 확인 */}
      {modal && (
        <EntityEditModal title={modal.title} fields={modal.fields} initial={modal.initial}
          onSave={saveModal} onClose={() => setModal(null)} />
      )}
      {impactState && (
        <ImpactDialog entityLabel={impactState.label} impact={impactState.impact}
          onCascade={impactState.cascadeAllowed
            ? async () => { await guidelinesV3Api.editDelete(impactState.etype, impactState.id, true); reload(); }
            : null}
          onClose={() => setImpactState(null)} />
      )}
    </div>
  );
}
