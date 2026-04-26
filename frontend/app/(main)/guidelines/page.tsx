"use client";
import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  Search, BookOpen, ChevronDown, ChevronUp, X, Loader2,
  FileText, Paperclip, AlertCircle, BookMarked,
  ArrowRight, GitBranch, ShieldAlert, ChevronRight,
} from "lucide-react";
import { guidelinesApi, GuidelineRow, GuidelineEntryPoint } from "@/lib/api";

// ── 업무유형 한글 라벨 ────────────────────────────────────────────────────────
const ACTION_TYPE_LABELS: Record<string, string> = {
  CHANGE:                    "체류자격 변경",
  EXTEND:                    "체류기간 연장",
  EXTRA_WORK:                "체류자격 외 활동",
  WORKPLACE:                 "근무처 변경·추가",
  REGISTRATION:              "외국인등록",
  REENTRY:                   "재입국허가",
  GRANT:                     "체류자격 부여",
  VISA_CONFIRM:              "사증발급인정서",
  APPLICATION_CLAIM:         "직접신청",
  DOMESTIC_RESIDENCE_REPORT: "국내 거소신고",
  ACTIVITY_EXTRA:            "활동범위 확대",
};

const ACTION_TYPE_COLORS: Record<string, string> = {
  CHANGE:                    "#4299E1",
  EXTEND:                    "#48BB78",
  EXTRA_WORK:                "#ED8936",
  WORKPLACE:                 "#9F7AEA",
  REGISTRATION:              "#38B2AC",
  REENTRY:                   "#F6AD55",
  GRANT:                     "#FC8181",
  VISA_CONFIRM:              "#667EEA",
  APPLICATION_CLAIM:         "#A0AEC0",
  DOMESTIC_RESIDENCE_REPORT: "#68D391",
  ACTIVITY_EXTRA:            "#F6AD55",
};

const ACTION_TYPE_ORDER = [
  "CHANGE","EXTEND","REGISTRATION","EXTRA_WORK","WORKPLACE",
  "GRANT","REENTRY","VISA_CONFIRM","APPLICATION_CLAIM",
  "DOMESTIC_RESIDENCE_REPORT","ACTIVITY_EXTRA",
];

const ACTION_TYPE_TABS = [
  { key: "",                          label: "전체" },
  { key: "CHANGE",                    label: "변경" },
  { key: "EXTEND",                    label: "연장" },
  { key: "EXTRA_WORK",                label: "자격외활동" },
  { key: "WORKPLACE",                 label: "근무처" },
  { key: "REGISTRATION",              label: "등록" },
  { key: "REENTRY",                   label: "재입국" },
  { key: "GRANT",                     label: "자격부여" },
  { key: "VISA_CONFIRM",              label: "사증발급인정" },
  { key: "APPLICATION_CLAIM",         label: "직접신청" },
  { key: "DOMESTIC_RESIDENCE_REPORT", label: "거소신고" },
  { key: "ACTIVITY_EXTRA",            label: "활동범위" },
];

// ── TB 적용 대상 action_type ───────────────────────────────────────────────────
const TB_APPLICABLE_TYPES = new Set(["REGISTRATION", "CHANGE", "EXTEND", "GRANT"]);
const TB_STAGE_LABEL: Record<string, string> = {
  REGISTRATION: "외국인등록 신청 시",
  CHANGE:       "체류자격 변경 허가 신청 시",
  EXTEND:       "체류기간 연장 허가 신청 시",
  GRANT:        "체류자격 부여 신청 시",
};

// ── 진입점 fallback ────────────────────────────────────────────────────────────
const ENTRY_POINTS: GuidelineEntryPoint[] = [
  { id:"F5",   label:"영주 (F-5)",        subtitle:"체류자격 변경·등록",    codes:"F-5",       color:"#48BB78", search_query:"F-5",        action_types:["CHANGE","REGISTRATION"] },
  { id:"F4",   label:"재외동포 (F-4)",    subtitle:"변경·연장·등록",        codes:"F-4",       color:"#4299E1", search_query:"F-4",        action_types:["CHANGE","EXTEND","REGISTRATION"] },
  { id:"E7",   label:"특정활동 (E-7)",    subtitle:"변경·연장·부여",        codes:"E-7",       color:"#9F7AEA", search_query:"E-7",        action_types:["CHANGE","EXTEND","GRANT"] },
  { id:"D2",   label:"유학 (D-2)",        subtitle:"등록·변경·연장·자격외활동", codes:"D-2",  color:"#667EEA", search_query:"D-2",        action_types:["CHANGE","EXTEND","REGISTRATION","EXTRA_WORK"] },
  { id:"H2",   label:"방문취업 (H-2)",    subtitle:"등록·연장·변경",        codes:"H-2",       color:"#ED8936", search_query:"H-2",        action_types:["CHANGE","EXTEND","REGISTRATION"] },
  { id:"F6",   label:"결혼이민 (F-6)",    subtitle:"변경·연장·부여",        codes:"F-6",       color:"#FC8181", search_query:"F-6",        action_types:["CHANGE","EXTEND","GRANT"] },
  { id:"F2",   label:"거주 (F-2)",        subtitle:"변경·연장·부여",        codes:"F-2",       color:"#F6AD55", search_query:"F-2",        action_types:["CHANGE","EXTEND","GRANT"] },
  { id:"REG",  label:"외국인 등록",        subtitle:"최초 등록 절차",        codes:"등록",       color:"#38B2AC", search_query:"외국인등록",  action_types:["REGISTRATION"] },
  { id:"REEN", label:"재입국 허가",        subtitle:"단수·복수 재입국",      codes:"재입국",     color:"#F6AD55", search_query:"재입국허가",  action_types:["REENTRY"] },
  { id:"EX",   label:"체류자격 외 활동",  subtitle:"시간제취업·기타",       codes:"자격외활동", color:"#ED8936", search_query:"시간제취업",  action_types:["EXTRA_WORK"] },
  { id:"WP",   label:"근무처 변경·추가",  subtitle:"취업자격 근무처",       codes:"근무처",     color:"#9F7AEA", search_query:"근무처변경",  action_types:["WORKPLACE"] },
  { id:"GR",   label:"체류자격 부여",     subtitle:"출생·귀화 후 부여",     codes:"부여",       color:"#FC8181", search_query:"체류자격부여",action_types:["GRANT"] },
  { id:"VC",   label:"사증발급인정서",    subtitle:"국내 초청 사증",         codes:"사증",       color:"#667EEA", search_query:"사증발급인정",action_types:["VISA_CONFIRM"] },
  { id:"DR",   label:"거소신고",          subtitle:"재외동포 거소",          codes:"거소",       color:"#68D391", search_query:"거소신고",    action_types:["DOMESTIC_RESIDENCE_REPORT"] },
];

// ── 트리 헬퍼 ──────────────────────────────────────────────────────────────────
function isCodeEntry(entry: GuidelineEntryPoint): boolean {
  return /^[A-Z]-[0-9A-Z]/i.test(entry.search_query);
}

function getMatchingRows(rows: GuidelineRow[], entry: GuidelineEntryPoint): GuidelineRow[] {
  const q = entry.search_query.toLowerCase();
  // 코드 기반 진입점: search_query가 비자 코드 패턴 (예: F-5, D-2, E-7, H-2)
  if (isCodeEntry(entry)) {
    return rows.filter(r =>
      (r.detailed_code || "").toLowerCase().startsWith(q)
    );
  }
  // 업무 기반 진입점: action_type으로 필터
  const atFilter = new Set(entry.action_types || []);
  return rows.filter(r => atFilter.size === 0 || atFilter.has(r.action_type));
}

async function fetchRowsForEntry(entry: GuidelineEntryPoint): Promise<GuidelineRow[]> {
  if (isCodeEntry(entry)) {
    const res = await guidelinesApi.getTreeResults({
      search_query: entry.search_query,
      limit: 100,
    });
    return Array.isArray(res.data.data) ? res.data.data : [];
  }

  const actionTypes = entry.action_types || [];
  if (actionTypes.length === 1) {
    const res = await guidelinesApi.getTreeResults({
      action_type: actionTypes[0],
      limit: 100,
    });
    return Array.isArray(res.data.data) ? res.data.data : [];
  }

  const res = await guidelinesApi.list({ limit: 500, status: "all" });
  return getMatchingRows(Array.isArray(res.data.data) ? res.data.data : [], entry);
}

// ── quickdoc 딥링크 URL 생성 ───────────────────────────────────────────────────
function buildQuickDocUrl(row: GuidelineRow): string | null {
  if (row.quickdoc_category) {
    const params = new URLSearchParams();
    params.set("category", row.quickdoc_category);
    if (row.quickdoc_minwon)  params.set("minwon",  row.quickdoc_minwon);
    if (row.quickdoc_kind)    params.set("kind",    row.quickdoc_kind);
    if (row.quickdoc_detail)  params.set("detail",  row.quickdoc_detail);
    params.set("from_label", row.business_name);
    return `/quick-doc?${params.toString()}`;
  }
  const code = row.detailed_code ?? "";
  const at   = row.action_type ?? "";
  const params = new URLSearchParams();
  if (at === "VISA_CONFIRM") {
    params.set("category", "사증");
    params.set("from_label", row.business_name);
    return `/quick-doc?${params.toString()}`;
  }
  params.set("category", "체류");
  const minwonMap: Record<string, string> = {
    CHANGE: "변경", EXTEND: "연장", REGISTRATION: "등록",
    GRANT: "부여", EXTRA_WORK: "기타", WORKPLACE: "기타",
    REENTRY: "기타", DOMESTIC_RESIDENCE_REPORT: "기타",
    ACTIVITY_EXTRA: "기타", APPLICATION_CLAIM: "기타",
  };
  const minwon = minwonMap[at];
  if (!minwon) return null;
  params.set("minwon", minwon);
  if (code.startsWith("F-4"))      { params.set("kind", "F"); params.set("detail", "4"); }
  else if (code.startsWith("F-6")) { params.set("kind", "F"); params.set("detail", "6"); }
  else if (code.startsWith("F-2")) { params.set("kind", "F"); params.set("detail", "2"); }
  else if (code.startsWith("F-5")) { params.set("kind", "F"); params.set("detail", "5"); }
  else if (code.startsWith("H-2")) { params.set("kind", "H2"); }
  else if (code.startsWith("E-7")) { params.set("kind", "E7"); }
  else if (code.startsWith("D-"))  { params.set("kind", "D"); }
  params.set("from_label", row.business_name);
  return `/quick-doc?${params.toString()}`;
}

// ── 서류 칩 ──────────────────────────────────────────────────────────────────
function DocChip({ text, color }: { text: string; color: string }) {
  return (
    <span style={{ display:"inline-block", fontSize:11, padding:"3px 9px", borderRadius:99, background:`${color}18`, color, border:`1px solid ${color}40`, whiteSpace:"normal", wordBreak:"break-word", fontWeight:500 }}>
      {text}
    </span>
  );
}

// ── 업무유형 뱃지 ──────────────────────────────────────────────────────────────
function ActionBadge({ type }: { type: string }) {
  const color = ACTION_TYPE_COLORS[type] || "#A0AEC0";
  const label = ACTION_TYPE_LABELS[type] || type;
  return (
    <span style={{ display:"inline-block", fontSize:10, fontWeight:700, padding:"2px 7px", borderRadius:6, background:`${color}18`, color }}>
      {label}
    </span>
  );
}

// ── 서류 섹션 (DetailPanel 전용) ───────────────────────────────────────────────
function DocSection({ title, icon, color, docs }: { title: string; icon: React.ReactNode; color: string; docs: string[] }) {
  if (docs.length === 0) return null;
  return (
    <div>
      <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:8 }}>
        {icon}
        <span style={{ fontSize:12, fontWeight:700, color }}>{title}</span>
        <span style={{ fontSize:11, color:"#A0AEC0" }}>({docs.length})</span>
      </div>
      <div style={{ display:"flex", flexWrap:"wrap", gap:6 }}>
        {docs.map((doc, i) => <DocChip key={i} text={doc} color={color} />)}
      </div>
    </div>
  );
}

// ── 상세 패널 ──────────────────────────────────────────────────────────────────
function DetailPanel({ row, onClose }: { row: GuidelineRow; onClose: () => void }) {
  const router = useRouter();
  const [relatedExceptions, setRelatedExceptions] = useState<{ exc_id: string; trigger_condition?: string; add_supporting_docs?: string; add_form_docs?: string }[]>([]);

  useEffect(() => {
    setRelatedExceptions([]);
    guidelinesApi.getDetail(row.row_id)
      .then(res => {
        const data = res.data as GuidelineRow & { related_exceptions?: { exc_id: string; trigger_condition?: string; add_supporting_docs?: string; add_form_docs?: string }[] };
        if (data.related_exceptions?.length) setRelatedExceptions(data.related_exceptions);
      })
      .catch(() => {});
  }, [row.row_id]);

  const officeDocs   = (row.form_docs ?? "").split("|").map(s => s.trim()).filter(Boolean);
  const requiredDocs = (row.supporting_docs ?? "").split("|").map(s => s.trim()).filter(Boolean);
  const exceptions   = (row.exceptions_summary ?? "").split("|").map(s => s.trim()).filter(Boolean);
  const deepLinkUrl  = buildQuickDocUrl(row);

  return (
    <div style={{ position:"fixed", top:0, right:0, bottom:0, width:440, background:"#fff", boxShadow:"-4px 0 32px rgba(0,0,0,0.13)", zIndex:300, overflowY:"auto", display:"flex", flexDirection:"column" }}>
      {/* 헤더 */}
      <div style={{ padding:"18px 20px 14px", borderBottom:"1px solid #E2E8F0", flexShrink:0 }}>
        <div style={{ display:"flex", alignItems:"flex-start", gap:12 }}>
          <div style={{ flex:1, minWidth:0 }}>
            <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:4, flexWrap:"wrap" }}>
              <ActionBadge type={row.action_type} />
              <span style={{ fontSize:12, color:"#A0AEC0" }}>{row.detailed_code}</span>
            </div>
            <div style={{ fontSize:16, fontWeight:700, color:"#1A202C", lineHeight:1.4, marginBottom:4 }}>{row.business_name}</div>
            {row.overview_short && <div style={{ fontSize:12, color:"#718096", lineHeight:1.6 }}>{row.overview_short}</div>}
          </div>
          <button onClick={onClose} style={{ padding:6, borderRadius:8, background:"none", border:"none", cursor:"pointer", color:"#A0AEC0", flexShrink:0 }}
            onMouseEnter={e=>(e.currentTarget as HTMLButtonElement).style.background="#F7FAFC"}
            onMouseLeave={e=>(e.currentTarget as HTMLButtonElement).style.background="none"}>
            <X size={16} />
          </button>
        </div>
        {deepLinkUrl && (
          <button onClick={() => router.push(deepLinkUrl)}
            style={{ marginTop:12, width:"100%", display:"flex", alignItems:"center", justifyContent:"center", gap:6, padding:"8px 14px", borderRadius:8, background:"rgba(245,166,35,0.10)", border:"1px solid #F5A623", color:"#92631A", fontSize:12, fontWeight:700, cursor:"pointer", transition:"all 0.15s" }}
            onMouseEnter={e=>(e.currentTarget as HTMLButtonElement).style.background="rgba(245,166,35,0.20)"}
            onMouseLeave={e=>(e.currentTarget as HTMLButtonElement).style.background="rgba(245,166,35,0.10)"}>
            <FileText size={13} /> 문서 자동작성으로 이동 <ArrowRight size={13} />
          </button>
        )}
      </div>

      {/* 본문 */}
      <div style={{ flex:1, padding:"18px 20px", display:"flex", flexDirection:"column", gap:18 }}>
        <DocSection title="사무소 준비서류" icon={<FileText size={13} style={{color:"#4299E1"}}/>} color="#4299E1" docs={officeDocs} />
        <DocSection title="필요서류 (고객 준비)" icon={<Paperclip size={13} style={{color:"#48BB78"}}/>} color="#48BB78" docs={requiredDocs} />

        {row.fee_rule && (
          <div>
            <div style={{ fontSize:12, fontWeight:700, color:"#718096", marginBottom:6 }}>인지세</div>
            <div style={{ fontSize:13, padding:"10px 14px", borderRadius:8, background:"#FFFBF0", color:"#744210", border:"1px solid #F6E05E", lineHeight:1.5, wordBreak:"break-word", overflowWrap:"break-word" }}>
              {row.fee_rule}
            </div>
          </div>
        )}

        {exceptions.length > 0 && (
          <div>
            <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:8 }}>
              <AlertCircle size={13} style={{color:"#ED8936"}}/>
              <span style={{ fontSize:12, fontWeight:700, color:"#ED8936" }}>예외사항</span>
            </div>
            <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
              {exceptions.map((exc, i) => (
                <div key={i} style={{ fontSize:12, padding:"8px 12px", borderRadius:8, background:"#FFFAF0", color:"#7B341E", border:"1px solid #FBD38D", lineHeight:1.6 }}>{exc}</div>
              ))}
            </div>
          </div>
        )}

        {relatedExceptions.filter(e => e.trigger_condition).length > 0 && (
          <div>
            <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:8 }}>
              <GitBranch size={13} style={{color:"#9F7AEA"}}/>
              <span style={{ fontSize:12, fontWeight:700, color:"#9F7AEA" }}>공통 조건부 예외</span>
            </div>
            <div style={{ display:"flex", flexDirection:"column", gap:5 }}>
              {relatedExceptions.filter(e=>e.trigger_condition).map(e => (
                <div key={e.exc_id} style={{ fontSize:11, padding:"7px 11px", borderRadius:7, background:"#F5F3FF", color:"#553C9A", border:"1px solid #D6BCFA", lineHeight:1.6 }}>
                  <span style={{fontWeight:700}}>조건: </span>{e.trigger_condition}
                  {e.add_supporting_docs && <span style={{display:"block",marginTop:2,color:"#44337A"}}>→ 추가 서류: <strong>{e.add_supporting_docs}</strong></span>}
                  {e.add_form_docs && <span style={{display:"block",marginTop:2,color:"#44337A"}}>→ 추가 작성: <strong>{e.add_form_docs}</strong></span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {row.basis_section && (
          <div>
            <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:6 }}>
              <BookMarked size={13} style={{color:"#9F7AEA"}}/>
              <span style={{ fontSize:12, fontWeight:700, color:"#9F7AEA" }}>근거</span>
            </div>
            <div style={{ fontSize:12, color:"#718096", lineHeight:1.7, wordBreak:"break-word", overflowWrap:"break-word" }}>{row.basis_section}</div>
          </div>
        )}

        {TB_APPLICABLE_TYPES.has(row.action_type) && (
          <div style={{ padding:"10px 14px", borderRadius:8, background:"#FFF5F5", border:"1px solid #FEB2B2", display:"flex", gap:10, alignItems:"flex-start" }}>
            <ShieldAlert size={14} style={{color:"#E53E3E",flexShrink:0,marginTop:1}}/>
            <div>
              <div style={{ fontSize:12, fontWeight:700, color:"#C53030", marginBottom:3 }}>결핵 고위험국 국적자 주의</div>
              <div style={{ fontSize:11, color:"#742A2A", lineHeight:1.6 }}>
                {TB_STAGE_LABEL[row.action_type]} 결핵 고위험국 국적자는 보건소 결핵 검사 결과서를 함께 제출해야 합니다.<br/>
                <span style={{color:"#9B2C2C",fontWeight:600}}>해당 여부: 베트남·중국·인도·필리핀·인도네시아 등 약 70개국</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── 결과 카드 ─────────────────────────────────────────────────────────────────
function GuidelineCard({ row, isSelected, onClick }: { row: GuidelineRow; isSelected: boolean; onClick: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const color = ACTION_TYPE_COLORS[row.action_type] || "#A0AEC0";
  const officeDocs   = (row.form_docs ?? "").split("|").map(s => s.trim()).filter(Boolean);
  const requiredDocs = (row.supporting_docs ?? "").split("|").map(s => s.trim()).filter(Boolean);

  return (
    <div style={{ background:"#fff", borderRadius:12, border:`1px solid ${isSelected ? color : "#E2E8F0"}`, boxShadow: isSelected ? `0 0 0 2px ${color}30` : "none", transition:"border-color 0.15s" }}>
      <div style={{ padding:"14px 16px", cursor:"pointer" }} onClick={onClick}
        onMouseEnter={e=>{if(!isSelected)(e.currentTarget as HTMLDivElement).style.background="#F7FAFC";}}
        onMouseLeave={e=>{(e.currentTarget as HTMLDivElement).style.background="transparent";}}>
        <div style={{ display:"flex", alignItems:"flex-start", gap:12 }}>
          <div style={{ width:3, height:42, borderRadius:99, background:color, flexShrink:0, marginTop:2 }}/>
          <div style={{ flex:1, minWidth:0 }}>
            <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:4, flexWrap:"wrap" }}>
              <ActionBadge type={row.action_type} />
              <span style={{ fontSize:11, color:"#A0AEC0" }}>{row.detailed_code}</span>
              <span style={{ fontSize:11, color:"#CBD5E0" }}>{row.major_action_std}</span>
            </div>
            <div style={{ fontSize:14, fontWeight:600, color:"#2D3748", marginBottom:3 }}>{row.business_name}</div>
            {row.overview_short && (
              <div style={{ fontSize:12, color:"#A0AEC0", lineHeight:1.5 }}>
                {row.overview_short.length > 90 ? row.overview_short.slice(0,90)+"…" : row.overview_short}
              </div>
            )}
          </div>
          <button style={{ padding:4, color:"#CBD5E0", background:"none", border:"none", cursor:"pointer", flexShrink:0 }}
            onClick={e=>{e.stopPropagation(); setExpanded(!expanded);}}>
            {expanded ? <ChevronUp size={14}/> : <ChevronDown size={14}/>}
          </button>
        </div>
      </div>
      {expanded && (
        <div style={{ padding:"0 16px 14px", borderTop:"1px solid #F7FAFC" }}>
          <div style={{ paddingTop:12, display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(160px, 1fr))", gap:12 }}>
            {officeDocs.length > 0 && (
              <div>
                <div style={{ fontSize:10, fontWeight:700, color:"#4299E1", marginBottom:6 }}>사무소 준비서류 ({officeDocs.length})</div>
                <div style={{ display:"flex", flexWrap:"wrap", gap:4 }}>
                  {officeDocs.map((d,i) => <DocChip key={i} text={d} color="#4299E1"/>)}
                </div>
              </div>
            )}
            {requiredDocs.length > 0 && (
              <div>
                <div style={{ fontSize:10, fontWeight:700, color:"#48BB78", marginBottom:6 }}>필요서류 ({requiredDocs.length})</div>
                <div style={{ display:"flex", flexWrap:"wrap", gap:4 }}>
                  {requiredDocs.map((d,i) => <DocChip key={i} text={d} color="#48BB78"/>)}
                </div>
              </div>
            )}
          </div>
          {row.fee_rule && (
            <div style={{ marginTop:8, fontSize:11, color:"#718096", wordBreak:"break-word", overflowWrap:"break-word" }}>
              인지세: <span style={{color:"#744210",fontWeight:600}}>{row.fee_rule}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 진입점 카드 ───────────────────────────────────────────────────────────────
function EntryPointCard({ entry, rowCount, onClick }: { entry: GuidelineEntryPoint; rowCount: number; onClick: () => void }) {
  const [hovered, setHovered] = useState(false);
  return (
    <button onClick={onClick} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      style={{ display:"flex", alignItems:"flex-start", gap:10, padding:"14px 16px", borderRadius:12, border:`1.5px solid ${hovered ? entry.color : "#E2E8F0"}`, background: hovered ? `${entry.color}0C` : "#fff", cursor:"pointer", textAlign:"left", transition:"all 0.15s", width:"100%" }}>
      <div style={{ width:36, height:36, borderRadius:10, flexShrink:0, background:`${entry.color}18`, display:"flex", alignItems:"center", justifyContent:"center", fontSize:12, fontWeight:800, color:entry.color }}>
        {entry.codes.slice(0,2)}
      </div>
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ fontSize:13, fontWeight:700, color:"#2D3748", marginBottom:2 }}>{entry.label}</div>
        <div style={{ fontSize:11, color:"#A0AEC0" }}>{entry.subtitle}</div>
        {rowCount > 0 && <div style={{ fontSize:10, color:entry.color, fontWeight:600, marginTop:3 }}>{rowCount}건</div>}
      </div>
      <ChevronRight size={14} style={{ color: hovered ? entry.color : "#CBD5E0", flexShrink:0, marginTop:2, transition:"color 0.15s" }}/>
    </button>
  );
}

// ── L2 업무유형 카드 ──────────────────────────────────────────────────────────
function ActionTypeCard({ actionType, label, count, color, onClick }: { actionType: string; label: string; count: number; color: string; onClick: () => void }) {
  const [hovered, setHovered] = useState(false);
  return (
    <button onClick={onClick} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      style={{ display:"flex", alignItems:"center", justifyContent:"space-between", padding:"16px 18px", borderRadius:12, border:`1.5px solid ${hovered ? color : "#E2E8F0"}`, background: hovered ? `${color}0C` : "#fff", cursor:"pointer", textAlign:"left", transition:"all 0.15s", width:"100%" }}>
      <div>
        <div style={{ fontSize:14, fontWeight:700, color:"#2D3748", marginBottom:4 }}>{label}</div>
        <div style={{ fontSize:12, color, fontWeight:600 }}>{count}건</div>
      </div>
      <div style={{ width:32, height:32, borderRadius:8, background:`${color}18`, display:"flex", alignItems:"center", justifyContent:"center" }}>
        <ArrowRight size={14} style={{color}}/>
      </div>
    </button>
  );
}

// ── 메인 페이지 ───────────────────────────────────────────────────────────────
export default function GuidelinesPage() {
  const [entryPoints, setEntryPoints]       = useState<GuidelineEntryPoint[]>(ENTRY_POINTS);
  const [allRows, setAllRows]               = useState<GuidelineRow[]>([]);
  const [loadingAll, setLoadingAll]         = useState(true);
  const [loadError, setLoadError]           = useState("");

  // 트리 상태
  const [selectedEntry, setSelectedEntry]           = useState<GuidelineEntryPoint | null>(null);
  const [selectedActionType, setSelectedActionType] = useState<string | null>(null);
  const [selectedRow, setSelectedRow]               = useState<GuidelineRow | null>(null);
  const [currentEntryRows, setCurrentEntryRows]     = useState<GuidelineRow[]>([]);
  const [treeLoading, setTreeLoading]               = useState(false);
  const [treeError, setTreeError]                   = useState("");

  // 검색 상태
  const [searchQuery, setSearchQuery]     = useState("");
  const [searchActiveType, setSearchActiveType] = useState("");
  const [searchResults, setSearchResults] = useState<GuidelineRow[]>([]);
  const [searchTotal, setSearchTotal]     = useState(0);
  const [isSearching, setIsSearching]     = useState(false);
  const [hasSearched, setHasSearched]     = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);

  // 마운트 시 전체 rows + 진입점 동시 로딩
  useEffect(() => {
    setLoadError("");
    Promise.all([
      guidelinesApi.getEntryPoints().then(res => res.data.data).catch(() => [] as GuidelineEntryPoint[]),
      guidelinesApi.list({ limit: 500, status: "all" }).then(res => res.data.data).catch(() => {
        setLoadError("실무지침 목록을 불러오지 못했습니다. 로그인 상태 또는 서버 연결을 확인해 주세요.");
        return [] as GuidelineRow[];
      }),
    ]).then(([eps, rows]) => {
      if (eps.length > 0) setEntryPoints(eps);
      setAllRows(Array.isArray(rows) ? rows : []);
    }).finally(() => setLoadingAll(false));
  }, []);

  // L1: 진입점별 row 수 — allRows가 로드된 경우 getMatchingRows로 계산 (클릭 결과와 동일한 소스/로직 사용)
  // allRows가 비어있는 동안(로딩 중)에만 API count 임시 표시
  const entryRowCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const ep of entryPoints) {
      counts[ep.id ?? ep.label] = allRows.length > 0
        ? getMatchingRows(allRows, ep).length
        : (ep.count ?? 0);
    }
    return counts;
  }, [entryPoints, allRows]);

  // L2: 선택된 진입점의 업무유형 그룹 (currentEntryRows 기반)
  const treeL2Items = useMemo(() => {
    if (!selectedEntry) return [];
    const grouped: Record<string, number> = {};
    currentEntryRows.forEach(r => { grouped[r.action_type] = (grouped[r.action_type] || 0) + 1; });
    return Object.entries(grouped)
      .map(([at, count]) => ({ key: at, label: ACTION_TYPE_LABELS[at] || at, count, color: ACTION_TYPE_COLORS[at] || "#A0AEC0" }))
      .sort((a, b) => {
        const ai = ACTION_TYPE_ORDER.indexOf(a.key);
        const bi = ACTION_TYPE_ORDER.indexOf(b.key);
        return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
      });
  }, [currentEntryRows, selectedEntry]);

  const skipL2 = treeL2Items.length <= 1;

  // L3: 최종 row 목록 (currentEntryRows 기반)
  const treeL3Rows = useMemo(() => {
    if (!selectedEntry) return [];
    if (skipL2) return currentEntryRows;
    if (selectedActionType) return currentEntryRows.filter(r => r.action_type === selectedActionType);
    return [];
  }, [currentEntryRows, selectedEntry, selectedActionType, skipL2]);

  // 뷰 모드
  const viewMode: "search" | "l1" | "l2" | "l3" =
    hasSearched ? "search"
    : !selectedEntry ? "l1"
    : (skipL2 || selectedActionType !== null) ? "l3"
    : "l2";

  // ── 진입점 rows — 전체 캐시 우선, 실패/미로딩 시 read-only tree endpoint 폴백 ──
  const loadEntryRows = useCallback(async (entry: GuidelineEntryPoint) => {
    setTreeLoading(true);
    setTreeError("");
    setCurrentEntryRows([]);

    try {
      let matched = allRows.length > 0 ? getMatchingRows(allRows, entry) : [];
      if (matched.length === 0) {
        matched = await fetchRowsForEntry(entry);
      }

      if (process.env.NODE_ENV !== "production") {
        console.debug("[guidelines:tree]", {
          id: entry.id,
          label: entry.label,
          search_query: entry.search_query,
          action_types: entry.action_types,
          cachedRows: allRows.length,
          matched: matched.length,
        });
      }

      setCurrentEntryRows(matched);
      if (matched.length === 0) {
        setTreeError("이 분류에 연결된 실무지침이 없습니다.");
      }
    } catch {
      setCurrentEntryRows([]);
      setTreeError("이 분류에 연결된 실무지침이 없습니다.");
    } finally {
      setTreeLoading(false);
    }
  }, [allRows]);

  // ── 핸들러 ──
  const doSearch = useCallback(async (q: string, type: string) => {
    if (!q.trim() && !type) return;
    setIsSearching(true);
    setHasSearched(true);
    setSelectedRow(null);
    try {
      const res = q.trim()
        ? await guidelinesApi.search(q.trim(), type || undefined, 1, 80)
        : await guidelinesApi.list({ action_type: type || undefined, limit: 80 });
      setSearchResults(res.data.data);
      setSearchTotal(res.data.total);
    } catch {
      setSearchResults([]); setSearchTotal(0);
    } finally {
      setIsSearching(false);
    }
  }, []);

  const handleSearch = () => {
    if (searchQuery.trim()) {
      setSelectedEntry(null); setSelectedActionType(null);
      doSearch(searchQuery, searchActiveType);
    }
  };

  const handleClearSearch = () => {
    setSearchQuery(""); setHasSearched(false);
    setSearchResults([]); setSearchTotal(0); setSearchActiveType("");
    inputRef.current?.focus();
  };

  const handleEntryClick = (entry: GuidelineEntryPoint) => {
    setSelectedEntry(entry); setSelectedActionType(null);
    setSelectedRow(null); setHasSearched(false);
    void loadEntryRows(entry);
  };

  const handleActionTypeClick = (at: string) => {
    setSelectedActionType(at); setSelectedRow(null);
  };

  const handleBackToL1 = () => {
    setSelectedEntry(null); setSelectedActionType(null);
    setSelectedRow(null); setCurrentEntryRows([]);
  };

  const handleBackToL2 = () => {
    setSelectedActionType(null); setSelectedRow(null);
  };

  return (
    <div style={{ paddingRight: selectedRow ? 460 : 0, transition: "padding-right 0.2s", overflowX:"hidden" }}>

      {/* ── 헤더 ── */}
      <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:14 }}>
        <BookOpen size={20} style={{color:"var(--hw-gold)"}}/>
        <h1 className="hw-page-title" style={{margin:0}}>실무지침</h1>
        {loadingAll && <Loader2 size={13} className="animate-spin" style={{color:"#A0AEC0"}}/>}
        {hasSearched && !isSearching && <span style={{fontSize:13,color:"#A0AEC0"}}>{searchTotal}건</span>}
        {(hasSearched) && (
          <button onClick={handleClearSearch}
            style={{ marginLeft:"auto", display:"flex", alignItems:"center", gap:4, fontSize:12, color:"#A0AEC0", background:"none", border:"none", cursor:"pointer", padding:"4px 8px" }}>
            <X size={12}/> 검색 초기화
          </button>
        )}
      </div>

      {/* ── 검색창 (보조) ── */}
      <div className="hw-card" style={{ marginBottom:14 }}>
        <div style={{ display:"flex", gap:10, alignItems:"center" }}>
          <div style={{ flex:1, position:"relative", minWidth:0 }}>
            <Search size={14} style={{ position:"absolute", left:12, top:"50%", transform:"translateY(-50%)", color:"#A0AEC0", pointerEvents:"none" }}/>
            <input ref={inputRef} type="text"
              placeholder="직접 검색: 코드·업무명·서류명 (예: F-4, 재직증명서, 시간제취업)"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") handleSearch(); }}
              style={{ width:"100%", height:38, border:"1px solid #CBD5E0", borderRadius:20, padding:"0 36px 0 38px", fontSize:13, outline:"none", background:"#F8F9FA", boxSizing:"border-box" }}
              onFocus={e=>{ e.currentTarget.style.borderColor="var(--hw-gold)"; e.currentTarget.style.background="#fff"; }}
              onBlur={e=>{ e.currentTarget.style.borderColor="#CBD5E0"; e.currentTarget.style.background="#F8F9FA"; }}
            />
            {searchQuery && (
              <button onClick={handleClearSearch} style={{ position:"absolute", right:10, top:"50%", transform:"translateY(-50%)", color:"#CBD5E0", background:"none", border:"none", cursor:"pointer", padding:2 }}>
                <X size={13}/>
              </button>
            )}
          </div>
          <button onClick={handleSearch} className="btn-primary"
            style={{ display:"flex", alignItems:"center", gap:6, fontSize:13, padding:"0 18px", height:38, flexShrink:0, borderRadius:20 }}>
            <Search size={13}/> 검색
          </button>
        </div>
      </div>

      {loadError && (
        <div
          style={{
            marginBottom: 14,
            padding: "12px 14px",
            borderRadius: 10,
            background: "#FFF5F5",
            border: "1px solid #FEB2B2",
            color: "#C53030",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {loadError}
        </div>
      )}

      {/* ── 검색 결과 뷰 ── */}
      {viewMode === "search" && (
        <>
          <div className="hw-tabs" style={{ flexWrap:"wrap", gap:4, marginBottom:14 }}>
            {ACTION_TYPE_TABS.map(({ key, label }) => (
              <button key={key} className={`hw-tab ${searchActiveType === key ? "active" : ""}`}
                onClick={() => { setSearchActiveType(key); doSearch(searchQuery, key); }}>{label}</button>
            ))}
          </div>
          {isSearching ? (
            <div style={{ display:"flex", justifyContent:"center", padding:"60px 0" }}>
              <Loader2 size={24} className="animate-spin" style={{color:"var(--hw-gold)"}}/>
            </div>
          ) : searchResults.length === 0 ? (
            <div style={{ textAlign:"center", padding:"60px 0", borderRadius:12, background:"#fff", border:"1px solid #E2E8F0" }}>
              <Search size={36} style={{color:"#E2E8F0",margin:"0 auto 12px"}}/>
              <div style={{fontSize:14,fontWeight:600,color:"#4A5568",marginBottom:4}}>검색 결과 없음</div>
              <div style={{fontSize:12,color:"#A0AEC0"}}>다른 검색어나 업무유형 탭을 선택해 보세요.</div>
            </div>
          ) : (
            <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
              {searchResults.map(row => (
                <GuidelineCard key={row.row_id} row={row}
                  isSelected={selectedRow?.row_id === row.row_id}
                  onClick={() => setSelectedRow(selectedRow?.row_id === row.row_id ? null : row)}/>
              ))}
            </div>
          )}
        </>
      )}

      {/* ── L1: 진입점 그리드 ── */}
      {viewMode === "l1" && (
        <div>
          <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:12 }}>
            <GitBranch size={14} style={{color:"#A0AEC0"}}/>
            <span style={{fontSize:12,color:"#A0AEC0"}}>업무 분류를 선택해 타고 들어가거나, 위에서 직접 검색하세요</span>
          </div>
          <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(210px, 1fr))", gap:10 }}>
            {entryPoints.map(entry => (
              <EntryPointCard
                key={entry.id ?? entry.label}
                entry={entry}
                rowCount={entryRowCounts[entry.id ?? entry.label] ?? 0}
                onClick={() => handleEntryClick(entry)}
              />
            ))}
          </div>
          {/* 자주 찾는 서류 */}
          <div style={{ marginTop:24, textAlign:"center" }}>
            <div style={{fontSize:11,color:"#CBD5E0",marginBottom:10}}>자주 찾는 서류</div>
            <div style={{display:"flex",flexWrap:"wrap",gap:6,justifyContent:"center"}}>
              {["통합신청서","사업자등록증","재직증명서","가족관계증명서","위임장"].map(hint => (
                <button key={hint}
                  onClick={() => { setSearchQuery(hint); doSearch(hint, ""); }}
                  style={{ fontSize:11, padding:"4px 12px", borderRadius:99, background:"rgba(245,166,35,0.08)", color:"var(--hw-gold-text)", border:"1px solid rgba(245,166,35,0.35)", cursor:"pointer" }}>
                  {hint}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── 브레드크럼 (L2·L3 공통) ── */}
      {(viewMode === "l2" || viewMode === "l3") && selectedEntry && (
        <div style={{ display:"flex", alignItems:"center", gap:4, marginBottom:16, flexWrap:"wrap" }}>
          <button onClick={handleBackToL1}
            style={{ display:"flex", alignItems:"center", gap:3, fontSize:12, color:"#718096", background:"#F7FAFC", border:"1px solid #E2E8F0", borderRadius:20, padding:"4px 12px", cursor:"pointer", fontWeight:500 }}>
            ← 전체 목록
          </button>
          <ChevronRight size={13} style={{color:"#CBD5E0"}}/>
          {viewMode === "l3" && selectedActionType ? (
            <>
              <button onClick={handleBackToL2}
                style={{ fontSize:12, color:"#718096", background:"#F7FAFC", border:"1px solid #E2E8F0", borderRadius:20, padding:"4px 12px", cursor:"pointer", fontWeight:500 }}>
                {selectedEntry.label}
              </button>
              <ChevronRight size={13} style={{color:"#CBD5E0"}}/>
              <span style={{ fontSize:12, fontWeight:700, padding:"4px 12px", background:`${ACTION_TYPE_COLORS[selectedActionType]}18`, borderRadius:20, border:`1px solid ${ACTION_TYPE_COLORS[selectedActionType]}40`, color:ACTION_TYPE_COLORS[selectedActionType] }}>
                {ACTION_TYPE_LABELS[selectedActionType]}
              </span>
            </>
          ) : (
            <span style={{ fontSize:12, fontWeight:700, padding:"4px 12px", background:`${selectedEntry.color}18`, borderRadius:20, border:`1px solid ${selectedEntry.color}40`, color:selectedEntry.color }}>
              {selectedEntry.label}
            </span>
          )}
          <span style={{ marginLeft:"auto", fontSize:12, color:"#A0AEC0" }}>
            {viewMode === "l3" ? `${treeL3Rows.length}건` : ""}
          </span>
        </div>
      )}

      {/* ── L2: 업무유형 선택 ── */}
      {viewMode === "l2" && selectedEntry && (
        <div>
          <div style={{fontSize:12,color:"#718096",marginBottom:14}}>
            <strong style={{color:"#2D3748"}}>{selectedEntry.label}</strong> — 업무 유형을 선택하세요
          </div>
          <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(200px, 1fr))", gap:10 }}>
            {treeL2Items.map(item => (
              <ActionTypeCard
                key={item.key}
                actionType={item.key}
                label={item.label}
                count={item.count}
                color={item.color}
                onClick={() => handleActionTypeClick(item.key)}
              />
            ))}
          </div>
        </div>
      )}

      {/* ── L3: 항목 목록 ── */}
      {viewMode === "l3" && (
        treeLoading ? (
          <div style={{ display:"flex", justifyContent:"center", padding:"60px 0" }}>
            <Loader2 size={24} className="animate-spin" style={{color:"var(--hw-gold)"}}/>
          </div>
        ) : treeL3Rows.length === 0 ? (
          <div style={{textAlign:"center",padding:"40px 0",color:"#A0AEC0",fontSize:13}}>
            {treeError || "이 분류에 연결된 실무지침이 없습니다."}
          </div>
        ) : (
          <div style={{display:"flex",flexDirection:"column",gap:10}}>
            {treeL3Rows.map(row => (
              <GuidelineCard key={row.row_id} row={row}
                isSelected={selectedRow?.row_id === row.row_id}
                onClick={() => setSelectedRow(selectedRow?.row_id === row.row_id ? null : row)}/>
            ))}
          </div>
        )
      )}

      {/* 상세 패널 */}
      {selectedRow && <DetailPanel row={selectedRow} onClose={() => setSelectedRow(null)}/>}
    </div>
  );
}
