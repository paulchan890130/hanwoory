"use client";
// v3 자격 중심 실무지침 — 화면 1: 자격 선택 (관리자 read-only 베타, FEATURE_GUIDELINES_V3)
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, Loader2, Search, ShieldAlert } from "lucide-react";
import { guidelinesV3Api, V3Aux, V3Program, V3Qualification } from "@/lib/api";
import { getUser, canManageContent } from "@/lib/auth";
import { ProgramChip } from "@/components/qualifications/common";
import { GuidelineCard, buildQuickDocUrl } from "@/components/guidelines/shared";

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

function QualCard({ q, onClick }: { q: V3Qualification; onClick: () => void }) {
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
        <span style={{ fontSize:13, color:"#4A5568" }}>{q.name_ko}</span>
      </div>
      <div style={{ display:"flex", alignItems:"center", gap:6, flexWrap:"wrap", fontSize:11, color:"#718096" }}>
        <span>업무 {confirmed}/{total} 확인됨</span>
        {(s?.not_applicable ?? 0) > 0 && <span style={{ color:"#4A5568" }}>· 불가 {s!.not_applicable}</span>}
        {(s?.unknown ?? 0) > 0 && <span style={{ color:"#C53030" }}>· 확인필요 {s!.unknown}</span>}
        {(s?.route_count ?? 0) > 0 && <span>· 사증 경로 {s!.route_count}</span>}
        {(q.child_count ?? 0) > 0 && <span>· 세부 {q.child_count}</span>}
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
      {p.description && <div style={{ marginTop:8, fontSize:11, color:"#A0AEC0", lineHeight:1.5 }}>{p.description}</div>}
    </div>
  );
}

export default function QualificationsPage() {
  const router = useRouter();
  const user = useMemo(() => getUser(), []);
  const isAdmin = canManageContent(user);

  const [items, setItems] = useState<V3Qualification[]>([]);
  const [programs, setPrograms] = useState<V3Program[]>([]);
  const [auxItems, setAuxItems] = useState<V3Aux[]>([]);
  const [expandedAux, setExpandedAux] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!isAdmin) { setLoading(false); return; }
    guidelinesV3Api.listQualifications()
      .then(res => { setItems(res.data.data); setPrograms(res.data.programs ?? []); })
      .catch(e => {
        setError(e?.response?.status === 404
          ? "v3 자격 중심 화면이 비활성 상태입니다 (FEATURE_GUIDELINES_V3 off 또는 데이터 없음)."
          : "v3 데이터를 불러오지 못했습니다.");
      })
      .finally(() => setLoading(false));
    // 보조 민원(별도 축) — 실패해도 자격 화면은 정상 동작
    guidelinesV3Api.listAux()
      .then(res => setAuxItems(res.data.data))
      .catch(() => setAuxItems([]));
  }, [isAdmin]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(m =>
      m.code.toLowerCase().includes(q) || m.name_ko.includes(query.trim())
      || (m.sub_codes ?? []).some(c => c.toLowerCase().includes(q)));
  }, [items, query]);

  const groups = useMemo(() => {
    const g = new Map<string, V3Qualification[]>();
    filtered.forEach(m => {
      if (!g.has(m.group)) g.set(m.group, []);
      g.get(m.group)!.push(m);
    });
    return Array.from(g.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [filtered]);

  if (!isAdmin) {
    return (
      <div style={{ padding:"60px 24px", textAlign:"center", color:"#718096" }}>
        <ShieldAlert size={32} style={{ margin:"0 auto 12px", color:"#CBD5E0" }} />
        <div style={{ fontSize:14, fontWeight:600 }}>관리자 전용 베타 화면입니다.</div>
      </div>
    );
  }

  return (
    <div style={{ padding:24, maxWidth:1200, margin:"0 auto" }}>
      <div style={{ display:"flex", alignItems:"center", gap:12, marginBottom:6, flexWrap:"wrap" }}>
        <h1 style={{ fontSize:20, fontWeight:700, color:"#2D3748", margin:0 }}>자격으로 찾기</h1>
        <span style={{ fontSize:11, fontWeight:700, padding:"3px 10px", borderRadius:99,
          background:"rgba(212,168,67,0.10)", color:"var(--hw-gold-text)", border:"1px solid rgba(212,168,67,0.35)" }}>
          관리자 read-only 베타 · 매뉴얼 원문(v3) 기준
        </span>
      </div>
      <div style={{ fontSize:12, color:"#718096", marginBottom:16 }}>
        손님의 체류자격을 선택하면 가능한 업무·사증 경로를 매뉴얼 원문 구조로 안내합니다.
        기존 실무지침 화면·데이터는 그대로 유지됩니다.
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
          {groups.map(([g, quals]) => (
            <div key={g} style={{ marginBottom:22 }}>
              <div style={{ fontSize:13, fontWeight:700, color:"#4A5568", marginBottom:10 }}>
                {GROUP_LABEL[g] ?? `${g} 계열`} <span style={{ fontWeight:400, color:"#A0AEC0" }}>({quals.length})</span>
              </div>
              <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(230px, 1fr))", gap:10 }}>
                {quals.map(q => (
                  <QualCard key={q.qualification_id} q={q}
                    onClick={() => router.push(`/qualifications/${encodeURIComponent(q.code)}`)} />
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
    </div>
  );
}
