"use client";
// 실무지침 공용 표시 컴포넌트 — guidelines/page.tsx 에서 추출(동작 불변).
// 사유: v3 자격 중심 화면(/qualifications)이 GuidelineCard·quickdoc 딥링크를
// 재사용해야 하는데, Next.js 페이지 모듈은 값 export 를 허용하지 않음.
import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { GuidelineRow } from "@/lib/api";

export const ACTION_TYPE_LABELS: Record<string, string> = {
  CHANGE:                    "체류자격 변경",
  EXTEND:                    "체류기간 연장",
  EXTRA_WORK:                "체류자격 외 활동",
  WORKPLACE:                 "근무처 변경·추가",
  REGISTRATION:              "외국인등록",
  REENTRY:                   "재입국허가",
  GRANT:                     "체류자격 부여",
  VISA_CONFIRM:              "사증",
  APPLICATION_CLAIM:         "직접신청",
  DOMESTIC_RESIDENCE_REPORT: "국내 거소신고",
  ACTIVITY_EXTRA:            "활동범위 확대",
};

export const ACTION_TYPE_COLORS: Record<string, string> = {
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

// ── quickdoc 딥링크 URL 생성 ───────────────────────────────────────────────────
export function buildQuickDocUrl(row: GuidelineRow): string | null {
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
export function DocChip({ text, color }: { text: string; color: string }) {
  return (
    <span style={{ display:"inline-block", fontSize:11, padding:"3px 9px", borderRadius:99, background:`${color}18`, color, border:`1px solid ${color}40`, whiteSpace:"normal", wordBreak:"break-word", overflowWrap:"anywhere", maxWidth:"100%", fontWeight:500 }}>
      {text}
    </span>
  );
}

// ── 업무유형 뱃지 ──────────────────────────────────────────────────────────────
export function ActionBadge({ type }: { type: string }) {
  const color = ACTION_TYPE_COLORS[type] || "#A0AEC0";
  const label = ACTION_TYPE_LABELS[type] || type;
  return (
    <span style={{ display:"inline-block", fontSize:10, fontWeight:700, padding:"2px 7px", borderRadius:6, background:`${color}18`, color }}>
      {label}
    </span>
  );
}

// ── 실무지침 행 카드 ───────────────────────────────────────────────────────────
export function GuidelineCard({ row, isSelected, onClick, defaultExpanded, docsPendingNote }: { row: GuidelineRow; isSelected: boolean; onClick: () => void; defaultExpanded?: boolean; docsPendingNote?: string }) {
  const [expanded, setExpanded] = useState(defaultExpanded ?? false);
  const color = ACTION_TYPE_COLORS[row.action_type] || "#A0AEC0";
  const officeDocs   = (row.form_docs ?? "").split("|").map(s => s.trim()).filter(Boolean);
  const requiredDocs = (row.supporting_docs ?? "").split("|").map(s => s.trim()).filter(Boolean);
  return (
    <div style={{ background:"#fff", borderRadius:12, border:`1px solid ${isSelected ? color : "#E2E8F0"}`, boxShadow:isSelected?`0 0 0 2px ${color}30`:"none", transition:"border-color 0.15s" }}>
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
          {docsPendingNote && (
            <div style={{ marginTop:12, padding:"8px 10px", borderRadius:8, background:"#FFFAF0",
              border:"1px solid #F6AD55", fontSize:12, color:"#975A16", lineHeight:1.5 }}>
              {docsPendingNote}
            </div>
          )}
          <div style={{ paddingTop:12, display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(160px, 1fr))", gap:12 }}>
            {officeDocs.length > 0 && (
              <div>
                <div style={{ fontSize:10, fontWeight:700, color:"#4299E1", marginBottom:6 }}>사무소 준비서류 ({officeDocs.length})</div>
                <div style={{ display:"flex", flexWrap:"wrap", gap:4 }}>{officeDocs.map((d,i) => <DocChip key={i} text={d} color="#4299E1"/>)}</div>
              </div>
            )}
            {requiredDocs.length > 0 && (
              <div>
                <div style={{ fontSize:10, fontWeight:700, color:"#48BB78", marginBottom:6 }}>필요서류 ({requiredDocs.length})</div>
                <div style={{ display:"flex", flexWrap:"wrap", gap:4 }}>{requiredDocs.map((d,i) => <DocChip key={i} text={d} color="#48BB78"/>)}</div>
              </div>
            )}
          </div>
          {row.fee_rule && (
            <div style={{ marginTop:8, fontSize:11, color:"#718096", wordBreak:"break-word", overflowWrap:"break-word" }}>
              인지세: <span style={{color:"#6B5314",fontWeight:600}}>{row.fee_rule}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
