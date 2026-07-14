"use client";
// v3 자격 중심 실무지침 — 화면 2(자격 대시보드) + 화면 3(블록·경로 상세 패널)
// 관리자 read-only 베타 (FEATURE_GUIDELINES_V3)
// 좌측 = 체류 업무 격자(위) + 사증 경로 섹션(아래) 동시 표시, 우측 = 상세 패널.
import { CSSProperties, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, ChevronRight, FileText, Loader2, ShieldAlert, X } from "lucide-react";
import { guidelinesV3Api, GuidelineRow, V3Block, V3DocRequirement, V3QualificationDetail, V3Route } from "@/lib/api";
import { getUser, canManageContent } from "@/lib/auth";
import {
  ApplicabilityBadge, ProgramChip, ROUTE_TYPE_LABEL, routeTone,
  compareQualCode, stripInternalIds,
} from "@/components/qualifications/common";
import { DOC_PENDING_NOTE, isDocBlockedV2Row, sanitizeConflictText, sanitizeNaReasonDisplay, sanitizeV2RowForDisplay } from "@/components/qualifications/v2docSanitize";
import { GuidelineCard, buildQuickDocUrl } from "@/components/guidelines/shared";

// route 선택 시 child = 하위 세부약호 유래 경로(상위 화면에 집계 표시) — 상세는 하위 자격 detail에서 로드.
type Selection =
  | { kind: "block"; item: V3Block }
  | { kind: "route"; item: V3Route; child?: { code: string; name_ko: string } }
  | null;

// 상위 화면 사증 영역 집계용: 상위 직접 route + 하위 세부약호 route (route_id 기준 중복 제거)
type RouteEntry = { route: V3Route; child?: { code: string; name_ko: string } };
const RECOG_TYPES = ["recognition", "not_applicable", "excluded"];

// 사증 경로 '없음'(행 자체 부재)과 '미정리'(행은 있으나 실질 내용 공백)를 구분한다.
function isRouteUnfilled(r: V3Route): boolean {
  if (r.route_type === "not_applicable" || r.route_type === "excluded") return false;
  return !(r.application_place || "").trim() && !(r.application_form || "").trim()
    && !String(r.fee ?? "").trim() && !(r.notes || "").trim();
}

// unknown 칸 안내 문구(최종) — 블록 부재형과 추가 확인형을 구분(2026-07-08 확정 문구)
function unknownSummary(b: V3Block): string {
  const n = b.notes || "";
  if (n.includes("부재") || n.includes("규정 없음") || n.includes("언급 자체 없음")) {
    return "매뉴얼에 해당 업무 블록 부재 — 관서 확인 후 안내";
  }
  return "확인이 더 필요한 항목 — 관서 확인 후 안내";
}

// ── 세부약호 상세 fetch 캐시 (페이지 이동 없이 패널 내 전환용) ────────────────
const _subDetailCache = new Map<string, Promise<V3QualificationDetail>>();
function fetchQualDetail(code: string): Promise<V3QualificationDetail> {
  let p = _subDetailCache.get(code);
  if (!p) {
    p = guidelinesV3Api.getQualification(code).then(res => res.data);
    p.catch(() => { _subDetailCache.delete(code); });
    _subDetailCache.set(code, p);
  }
  return p;
}

// ── v3 document_requirements 직접 렌더링 ─────────────────────────────────────
function DrBadge({ text, color, bg, border }: { text: string; color: string; bg: string; border: string }) {
  return (
    <span style={{ fontSize:9.5, fontWeight:700, padding:"2px 6px", borderRadius:6,
      color, background:bg, border:`1px solid ${border}`, whiteSpace:"normal",
      overflowWrap:"anywhere", maxWidth:"100%", lineHeight:1.4 }}>
      {text}
    </span>
  );
}

// 기본 화면 배지 정책: 별지 서식 / 해당 시 / S1·S2 전용 / 폐지된 제도만.
// confidence 등 내부 검토 정보는 하단 접힘 영역 전용.
function DrRow({ d }: { d: V3DocRequirement }) {
  return (
    <div style={{ padding:"5px 0", borderBottom:"1px solid #F7FAFC" }}>
      <div style={{ display:"flex", alignItems:"center", gap:5, flexWrap:"wrap" }}>
        <span style={{ fontSize:12, color:"#2D3748", fontWeight: d.is_required ? 600 : 400,
          maxWidth:"100%", overflowWrap:"anywhere" }}>{d.doc_name}</span>
        {d.form_ref && <DrBadge text={d.form_ref} color="#4A5568" bg="#F7FAFC" border="#E2E8F0" />}
        {d.doc_role === "conditional" && <DrBadge text="해당 시" color="#975A16" bg="#FFFFF0" border="#F6E05E" />}
        {d.s_scope === "s1_only" && <DrBadge text="S1 전용" color="#2C7A7B" bg="#E6FFFA" border="#81E6D9" />}
        {d.s_scope === "s2_only" && <DrBadge text="S2 전용" color="#2C7A7B" bg="#E6FFFA" border="#81E6D9" />}
        {d.display_hint === "abolished_reference" && <DrBadge text="폐지된 제도" color="#822727" bg="#FFF5F5" border="#FEB2B2" />}
      </div>
      {d.doc_role === "conditional" && (
        <div style={{ marginTop:2, fontSize:11, color:"#718096", lineHeight:1.5 }}>
          — {d.display_condition || "해당하는 경우에만 준비합니다."}
        </div>
      )}
    </div>
  );
}

// 그룹 순서·명칭: 신청인 준비서류 → 행정사 사무소 준비서류 → 해당 시 추가서류 (기본 펼침)
// 시각 구분 강화: 그룹별 색 박스(좌측 색 테두리 + 옅은 배경) + 건수 배지 + 성격 설명 한 줄.
function DrGroups({ drs }: { drs: V3DocRequirement[] }) {
  const groups: { key: string; title: string; color: string; caption: string }[] = [
    { key: "client", title: "신청인 준비서류", color: "#48BB78", caption: "손님(신청인)이 지참해야 하는 서류입니다." },
    { key: "office", title: "행정사 사무소 준비서류", color: "#4299E1", caption: "위임장·대행업무수행확인서 등 사무소에서 준비하는 서류입니다." },
    { key: "conditional", title: "해당 시 추가서류", color: "#975A16", caption: "조건에 해당하는 경우에만 준비하는 서류입니다." },
  ];
  return (
    <div style={{ marginBottom:12, display:"flex", flexDirection:"column", gap:10 }}>
      {groups.map(g => {
        const items = drs.filter(d => d.doc_role === g.key);
        if (items.length === 0) return null;
        return (
          <div key={g.key} style={{ borderLeft:`3px solid ${g.color}`, background:`${g.color}0A`,
            border:`1px solid ${g.color}30`, borderLeftWidth:3, borderLeftColor:g.color,
            borderRadius:10, padding:"10px 14px" }}>
            <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:2 }}>
              <span style={{ fontSize:12, fontWeight:700, color:g.color }}>{g.title}</span>
              <span style={{ fontSize:10, fontWeight:700, color:g.color, background:"#fff",
                border:`1px solid ${g.color}50`, borderRadius:99, padding:"1px 8px" }}>{items.length}</span>
            </div>
            <div style={{ fontSize:10.5, color:"#A0AEC0", marginBottom:6 }}>{g.caption}</div>
            {items.map(d => <DrRow key={d.requirement_id} d={d} />)}
          </div>
        );
      })}
    </div>
  );
}

// 핵심 안내문 — applicability 기반 표준 문장
function keyGuidance(applicability: string): string | null {
  if (applicability === "applicable") {
    return "이 업무는 일반적으로 신청 가능한 업무입니다. 다만 신청인의 체류상태, 가족관계 입증 여부, "
      + "체류기간, 관할 출입국 판단에 따라 추가서류가 달라질 수 있습니다.";
  }
  if (applicability === "not_applicable") {
    return "이 업무는 일반적인 신청 대상이 아닙니다. 다만 예외 사유나 관할 출입국 판단에 따라 별도 확인이 필요할 수 있습니다.";
  }
  if (applicability === "conditional") {
    return "이 업무는 일정 요건을 충족하는 경우에만 진행할 수 있습니다. 신청 전 대상 여부와 추가서류를 확인해야 합니다.";
  }
  return null; // unknown 은 기존 관서 확인 박스가 담당
}

// 내부 검토 정보 접힘 영역 — 품질관리 정보 전용(기본 닫힘, 유일한 접힘 영역)
function InternalReview({ sel, drs }: { sel: NonNullable<Selection>; drs: V3DocRequirement[] }) {
  const [open, setOpen] = useState(false);
  const flagged = drs.filter(d => d.needs_human_review || (d.confidence && d.confidence !== "high"));
  const item = sel.item as V3Block & V3Route;
  const count = flagged.length;
  return (
    <div style={{ borderTop:"1px solid #EDF2F7", paddingTop:10, marginTop:12 }}>
      <button onClick={() => setOpen(!open)}
        style={{ fontSize:11, color:"#A0AEC0", background:"none", border:"none", cursor:"pointer", padding:0 }}>
        {open ? "▾" : "▸"} 내부 검토 정보 보기{count > 0 ? ` · ${count}건` : ""}
      </button>
      {open && (
        <div style={{ marginTop:8, padding:"10px 12px", borderRadius:10, background:"#F7FAFC",
          border:"1px solid #E2E8F0", fontSize:11, color:"#718096", lineHeight:1.7 }}>
          <div><strong>항목 신뢰도:</strong> {item.confidence || "-"}
            {("needs_human_review" in item) && (item as V3Block).needs_human_review ? " · 확인 필요" : ""}</div>
          {item.notes && <div><strong>검수 노트:</strong> {item.notes}</div>}
          {"review_note" in item && (item as V3Route).review_note && (
            <div><strong>정정 이력:</strong> {(item as V3Route).review_note}</div>
          )}
          {flagged.length > 0 && (
            <div style={{ marginTop:8 }}>
              <strong>서류별 검토 플래그:</strong>
              {flagged.map(d => (
                <div key={d.requirement_id} style={{ marginTop:4, paddingLeft:8, borderLeft:"2px solid #E2E8F0" }}>
                  <div style={{ color:"#4A5568" }}>{d.doc_name}
                    {d.confidence && d.confidence !== "high" ? " · 추가 확인 필요" : ""}
                    {d.needs_human_review ? " · 확인 필요" : ""}
                    {d.source_v2_row_id ? ` · v2 유래(${d.source_v2_row_id})` : ""}</div>
                  {d.condition && <div>적용 조건: {d.condition}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function DocGroup({ title, color, docs }: { title: string; color: string; docs: string[] }) {
  if (!docs || docs.length === 0) return null;
  return (
    <div style={{ marginBottom:10 }}>
      <div style={{ fontSize:10, fontWeight:700, color, marginBottom:6 }}>{title} ({docs.length})</div>
      <div style={{ display:"flex", flexWrap:"wrap", gap:4 }}>
        {docs.map((d, i) => (
          <span key={i} style={{ fontSize:11, padding:"3px 9px", borderRadius:8,
            background:`${color}14`, color, border:`1px solid ${color}40`,
            whiteSpace:"normal", overflowWrap:"anywhere", maxWidth:"100%", lineHeight:1.5 }}>{d}</span>
        ))}
      </div>
    </div>
  );
}

function LinkedV2Section({ rows, onQuickDoc }: { rows: GuidelineRow[]; onQuickDoc: (url: string) => void }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  if (rows.length === 0) {
    return <div style={{ fontSize:12, color:"#A0AEC0" }}>연결된 기존(v2) 지침 없음 — v3 신규 항목입니다.</div>;
  }
  return (
    <div style={{ display:"flex", flexDirection:"column", gap:8 }}>
      {rows.map(row => {
        // OCR 오염 표시 정제 — 복사본에만 적용(원본 row 불변, /guidelines 무영향)
        const displayRow = sanitizeV2RowForDisplay(row);
        const url = buildQuickDocUrl(row);
        return (
          <div key={row.row_id}>
            <GuidelineCard row={displayRow} isSelected={selectedId === row.row_id} defaultExpanded
              docsPendingNote={isDocBlockedV2Row(row.row_id) ? DOC_PENDING_NOTE : undefined}
              onClick={() => setSelectedId(selectedId === row.row_id ? null : row.row_id)} />
            {url && (
              <button onClick={() => onQuickDoc(url)}
                style={{ marginTop:4, display:"inline-flex", alignItems:"center", gap:5, fontSize:11,
                  padding:"4px 12px", borderRadius:20, border:"1px solid rgba(212,168,67,0.45)",
                  background:"rgba(212,168,67,0.08)", color:"var(--hw-gold-text)", cursor:"pointer", fontWeight:600 }}>
                <FileText size={12} /> 문서자동작성으로
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

function DetailPanelV3({ sel, v2Rows, drs, subCodes, subNames, onClose, onQuickDoc }: {
  sel: NonNullable<Selection>; v2Rows: GuidelineRow[]; drs: V3DocRequirement[];
  subCodes: string[]; subNames: Record<string, string>; onClose: () => void; onQuickDoc: (url: string) => void;
}) {
  const isBlock = sel.kind === "block";
  const b = isBlock ? (sel.item as V3Block) : null;
  const r = !isBlock ? (sel.item as V3Route) : null;
  // 하위 세부약호 유래 route — 서류/v2는 하위 자격 detail(캐시 fetch)에서 로드
  const routeChild = !isBlock && "child" in sel ? sel.child : undefined;
  const [childDetail, setChildDetail] = useState<V3QualificationDetail | null>(null);

  // ③ 세부약호 선택 — 페이지 이동 없이 같은 block_type 블록으로 패널 내용 전환
  const [subCode, setSubCode] = useState<string | null>(null);
  const [subLoading, setSubLoading] = useState(false);
  const [subError, setSubError] = useState("");
  const [subDetail, setSubDetail] = useState<V3QualificationDetail | null>(null);

  const selKey = isBlock ? b!.block_id : r!.route_id;
  useEffect(() => {
    // 다른 업무(블록/경로) 클릭 시 세부약호 선택 초기화
    setSubCode(null); setSubDetail(null); setSubError(""); setSubLoading(false);
  }, [selKey]);

  // 하위 유래 route 선택 시 해당 하위 자격 detail 로드(DR·v2 연결용 — fetch 캐시 재사용)
  const routeChildCode = routeChild?.code ?? null;
  useEffect(() => {
    if (!routeChildCode) { setChildDetail(null); return; }
    let alive = true;
    setChildDetail(null);
    fetchQualDetail(routeChildCode)
      .then(d => { if (alive) setChildDetail(d); })
      .catch(() => { /* 하위 상세 로드 실패 시 임베디드/안내 fallback */ });
    return () => { alive = false; };
  }, [selKey, routeChildCode]);

  useEffect(() => {
    if (!subCode) { setSubDetail(null); setSubError(""); setSubLoading(false); return; }
    let alive = true;
    setSubLoading(true); setSubError(""); setSubDetail(null);
    fetchQualDetail(subCode)
      .then(d => { if (alive) setSubDetail(d); })
      .catch(() => { if (alive) setSubError("세부약호 정보를 불러오지 못했습니다."); })
      .finally(() => { if (alive) setSubLoading(false); });
    return () => { alive = false; };
  }, [subCode]);

  const showSubChips = isBlock && subCodes.length > 0;
  const subBlock = (isBlock && subCode && subDetail)
    ? (subDetail.blocks.find(x => x.block_type === b!.block_type && x.variant === null) ?? null)
    : null;
  const subMissing = isBlock && !!subCode && !!subDetail && !subBlock;

  // 표시 대상(세부약호 선택 시 해당 자격의 블록으로 대체 / 하위 유래 route는 하위 detail 사용)
  const effB = subBlock ?? b;
  const effItem = isBlock ? (effB as V3Block) : (r as V3Route);
  const effDrs = subBlock && subDetail
    ? (subDetail.doc_requirements?.[subBlock.block_id] ?? [])
    : (!isBlock && routeChild)
      ? (childDetail?.doc_requirements?.[r!.route_id] ?? [])
      : drs;
  const effV2Pool = subBlock && subDetail
    ? subDetail.v2_rows
    : (!isBlock && routeChild)
      ? (childDetail?.v2_rows ?? [])
      : v2Rows;
  const linkedIds = isBlock ? (effB!.v2_row_ids ?? []) : (r!.v2_row_id ? [r!.v2_row_id] : []);
  const linked = effV2Pool.filter(row => linkedIds.includes(row.row_id));
  const legacyDocCount = effItem
    ? effItem.office_docs.length + effItem.client_docs.length + effItem.conditional_docs.length
    : 0;
  const effSel: NonNullable<Selection> = subBlock ? { kind: "block", item: subBlock } : sel;

  const subChipStyle = (active: boolean): CSSProperties => ({
    fontSize:11, fontWeight:600, padding:"3px 10px", borderRadius:8, cursor:"pointer",
    color: active ? "var(--hw-gold-text)" : "#4A5568",
    background: active ? "rgba(212,168,67,0.10)" : "#F7FAFC",
    border: active ? "1px solid rgba(212,168,67,0.55)" : "1px solid #E2E8F0",
    textAlign:"left", maxWidth:"100%", whiteSpace:"normal", lineHeight:1.45,
  });

  return (
    <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", padding:"16px 18px" }}>
      {/* ① 업무명 + ② 상태 배지 */}
      <div style={{ display:"flex", alignItems:"flex-start", gap:8, marginBottom:12 }}>
        <div style={{ flex:1 }}>
          <div style={{ fontSize:14, fontWeight:700, color:"#2D3748", marginBottom:6 }}>
            {isBlock ? b!.block_label : (r!.route_label || ROUTE_TYPE_LABEL[r!.route_type] || r!.route_type)}
          </div>
          {isBlock && subCode && (
            <div style={{ fontSize:12, fontWeight:600, color:"var(--hw-gold-text)", marginBottom:6, lineHeight:1.5 }}>
              {subCode}{subNames[subCode] ? ` ${subNames[subCode]}` : ""}
            </div>
          )}
          {routeChild && (
            <div style={{ fontSize:12, fontWeight:600, color:"var(--hw-gold-text)", marginBottom:6, lineHeight:1.5 }}>
              {routeChild.code} {routeChild.name_ko}
            </div>
          )}
          <div style={{ display:"flex", alignItems:"center", gap:6, flexWrap:"wrap" }}>
            {isBlock
              ? <ApplicabilityBadge value={effB!.applicability} />
              : (() => { const tone = routeTone(r!); return (
                  <span style={{ fontSize:11, fontWeight:700, padding:"3px 10px", borderRadius:99,
                    color:tone.color, background:tone.bg, border:`1px solid ${tone.border}` }}>{tone.badge}</span>
                ); })()}
          </div>
        </div>
        <button onClick={onClose} style={{ padding:4, color:"#A0AEC0", background:"none", border:"none", cursor:"pointer" }}>
          <X size={16} />
        </button>
      </div>

      {/* ③ 세부약호 선택 — 상위 자격 페이지에서만 표시 */}
      {showSubChips && (
        <div style={{ marginBottom:12 }}>
          <div style={{ fontSize:10, fontWeight:700, color:"#A0AEC0", marginBottom:6 }}>세부약호 선택</div>
          <div style={{ display:"flex", flexWrap:"wrap", gap:5 }}>
            <button style={subChipStyle(subCode === null)} onClick={() => setSubCode(null)}>공통(기초)</button>
            {[...subCodes].sort(compareQualCode).map(c => (
              <button key={c} style={subChipStyle(subCode === c)} onClick={() => setSubCode(c)}>
                <span style={{ whiteSpace:"nowrap" }}>{c}</span>
                {subNames[c] && <span style={{ fontWeight:400, marginLeft:5, color: subCode === c ? "var(--hw-gold-text)" : "#718096" }}>{subNames[c]}</span>}
              </button>
            ))}
          </div>
        </div>
      )}

      {subError && (
        <div style={{ marginBottom:12, padding:"10px 12px", borderRadius:10, background:"#FFF5F5",
          border:"1px solid #FEB2B2", fontSize:12, color:"#C53030" }}>{subError}</div>
      )}
      {subLoading ? (
        <div style={{ display:"flex", justifyContent:"center", padding:"24px 0" }}>
          <Loader2 size={18} className="animate-spin" style={{ color:"var(--hw-gold)" }} />
        </div>
      ) : subMissing ? (
        <div style={{ padding:"12px 14px", borderRadius:10, background:"#F7FAFC",
          border:"1px solid #E2E8F0", fontSize:12, color:"#718096", lineHeight:1.6 }}>
          이 세부약호에는 해당 업무 정보가 없습니다.
        </div>
      ) : (
        <>
          {/* ④ 업무 안내문 */}
          {isBlock && keyGuidance(effB!.applicability) && (
            <div style={{ marginBottom:12, padding:"10px 12px", borderRadius:10, background:"#F0FFF4",
              border:"1px solid #C6F6D5", fontSize:12, color:"#276749", lineHeight:1.7 }}>
              {keyGuidance(effB!.applicability)}
            </div>
          )}

          {isBlock && effB!.applicability === "not_applicable" && (
            <div style={{ marginBottom:12, padding:"10px 12px", borderRadius:10, background:"#EDF2F7",
              border:"1px solid #CBD5E0", fontSize:12, color:"#4A5568", lineHeight:1.6 }}>
              <div><strong>사유:</strong> {sanitizeNaReasonDisplay(stripInternalIds(effB!.na_reason))}</div>
              {effB!.redirect_to && <div style={{ marginTop:4 }}><strong>대안:</strong> {stripInternalIds(effB!.redirect_to)}</div>}
            </div>
          )}
          {isBlock && effB!.conflict && (
            <div style={{ marginBottom:12, padding:"10px 12px", borderRadius:10, background:"#FFFAF0",
              border:"1px solid #F6AD55", fontSize:12, color:"#975A16", lineHeight:1.6 }}>
              ⚠ {sanitizeConflictText(stripInternalIds(effB!.conflict))}
            </div>
          )}
          {isBlock && effB!.fee && (
            <div style={{ marginBottom:12, fontSize:12, color:"#4A5568", lineHeight:1.7 }}>
              <div>수수료: <strong>{effB!.fee}</strong></div>
              <div style={{ fontSize:11, color:"#A0AEC0" }}>면제·감면 대상 여부는 관할 출입국·외국인관서 기준에 따릅니다.</div>
            </div>
          )}
          {isBlock && effB!.applicability === "unknown" && (
            <div style={{ marginBottom:12, padding:"10px 12px", borderRadius:10, background:"#FFF5F5",
              border:"1px solid #FEB2B2", fontSize:12, color:"#C53030", lineHeight:1.6 }}>
              {unknownSummary(effB!)} — 손님에게 확답하지 말고 관서 확인 후 안내하세요.
            </div>
          )}
          {!isBlock && (
            <div style={{ marginBottom:12, fontSize:12, color:"#4A5568", lineHeight:1.7 }}>
              {isRouteUnfilled(r!) && (
                <div style={{ color:"#975A16", fontWeight:600 }}>사증 경로 미정리 — 검수 필요</div>
              )}
              {r!.application_place && <div>신청처: <strong>{r!.application_place}</strong></div>}
              {r!.application_form && <div>신청 서식: {r!.application_form}</div>}
              {r!.fee !== null && r!.fee !== "" && <div>수수료: {r!.fee}</div>}
              {r!.requires_recognition_before_consulate && (
                <div style={{ color:"#718096" }}>※ 인정서 발급 후 재외공관에서 사증을 발급받는 흐름입니다.</div>
              )}
              {r!.minister_approval_required && <div style={{ color:"#975A16" }}>※ 법무부장관 승인 대상</div>}
              {r!.status === "abolished" && (
                <div style={{ marginTop:6, padding:"8px 10px", borderRadius:8, background:"#FFF5F5",
                  border:"1px solid #FEB2B2", color:"#822727" }}>제도 폐지 — 신규 신청 불가. 대안 안내는 아래 노트 참조.</div>
              )}
            </div>
          )}

          {/* ⑤ 준비서류/필요서류 — 규칙: A) v3 DR 있으면 v3만 B) 없으면 v2 참고 안내 C) 둘 다 없으면 미정리 안내 */}
          {effDrs.length > 0 ? (
            <DrGroups drs={effDrs} />
          ) : legacyDocCount > 0 ? (
            <>
              <DocGroup title="사무소 준비 (office)" color="#4299E1" docs={effItem.office_docs} />
              <DocGroup title="손님 지참 (client)" color="#48BB78" docs={effItem.client_docs} />
              <DocGroup title="조건부 (conditional)" color="#975A16" docs={effItem.conditional_docs} />
            </>
          ) : linked.length > 0 ? (
            <div style={{ fontSize:11, color:"#718096", marginBottom:10 }}>
              연결된 기존 지침의 서류를 참고하세요.
            </div>
          ) : !isBlock && r!.docs_notice ? (
            <div style={{ marginBottom:10, padding:"10px 12px", borderRadius:10, background:"#F7FAFC",
              border:"1px solid #E2E8F0", fontSize:12, color:"#4A5568", lineHeight:1.6 }}>
              {r!.docs_notice}
            </div>
          ) : (
            <div style={{ fontSize:11, color:"#A0AEC0", marginBottom:10 }}>
              제출서류 미정리 항목입니다. 검수 후 반영이 필요합니다.
            </div>
          )}

          {effItem.exceptions.length > 0 && (
            <div style={{ marginBottom:10 }}>
              <div style={{ fontSize:10, fontWeight:700, color:"#975A16", marginBottom:4 }}>예외·주의</div>
              {effItem.exceptions.map((e, i) => (
                <div key={i} style={{ fontSize:12, color:"#4A5568", lineHeight:1.6 }}>· {stripInternalIds(e)}</div>
              ))}
            </div>
          )}
          {isBlock && effB!.visa_docs_reference && (
            <div style={{ marginBottom:10, fontSize:12, color:"#4A5568" }}>
              서류 준용: <span style={{ fontWeight:600 }}>{effB!.visa_docs_reference}</span> (사증 인정신청 기준)
            </div>
          )}

          {/* ⑥ 연결된 기존 지침 (v2) — 서류 기본 펼침 */}
          <div style={{ borderTop:"1px solid #EDF2F7", paddingTop:12 }}>
            <div style={{ fontSize:11, fontWeight:700, color:"#4A5568", marginBottom:8 }}>연결된 기존 지침 (v2)</div>
            <LinkedV2Section rows={linked} onQuickDoc={onQuickDoc} />
          </div>

          {/* ⑦ 내부 검토 정보 — 품질관리 전용(기본 닫힘) */}
          <InternalReview sel={effSel} drs={effDrs} />
        </>
      )}
    </div>
  );
}

export default function QualificationDetailPage() {
  const router = useRouter();
  const params = useParams<{ code: string }>();
  const code = decodeURIComponent(params.code ?? "");
  const user = useMemo(() => getUser(), []);
  const isAdmin = canManageContent(user);

  const [detail, setDetail] = useState<V3QualificationDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sel, setSel] = useState<Selection>(null);

  useEffect(() => {
    if (!isAdmin || !code) { setLoading(false); return; }
    setLoading(true); setSel(null);
    guidelinesV3Api.getQualification(code)
      .then(res => setDetail(res.data))
      .catch(e => {
        setError(e?.response?.status === 404
          ? "자격을 찾을 수 없거나 v3가 비활성 상태입니다 (FEATURE_GUIDELINES_V3)."
          : "v3 데이터를 불러오지 못했습니다.");
      })
      .finally(() => setLoading(false));
  }, [code, isAdmin]);

  const baseBlocks = useMemo(
    () => (detail?.blocks ?? []).filter(b => b.variant === null),
    [detail]);
  const variantBlocks = useMemo(
    () => (detail?.blocks ?? []).filter(b => b.variant !== null),
    [detail]);
  // 세부약호 코드 → 한글명 (children에 name_ko 포함 — 추가 fetch 불필요)
  const subNames = useMemo<Record<string, string>>(
    () => Object.fromEntries((detail?.children ?? []).map(c => [c.code, c.name_ko])),
    [detail]);
  // 상위 직접 route + 하위 세부약호 route 통합 집계(route_id dedup) 후 2분류:
  // 사증발급인정서(recognition/대상아님/제외 — '대상 아님'도 검수 결과 행) vs 사증(공관·전자·확인필요)
  const allRouteEntries = useMemo<RouteEntry[]>(() => {
    const seen = new Set<string>();
    const out: RouteEntry[] = [];
    for (const r of detail?.routes ?? []) {
      if (!seen.has(r.route_id)) { seen.add(r.route_id); out.push({ route: r }); }
    }
    for (const c of detail?.children ?? []) {
      for (const r of c.routes) {
        if (!seen.has(r.route_id)) { seen.add(r.route_id); out.push({ route: r, child: { code: c.code, name_ko: c.name_ko } }); }
      }
    }
    return out;
  }, [detail]);
  const recogEntries = useMemo(
    () => allRouteEntries.filter(e => RECOG_TYPES.includes(e.route.route_type)),
    [allRouteEntries]);
  const visaEntries = useMemo(
    () => allRouteEntries.filter(e => !RECOG_TYPES.includes(e.route.route_type)),
    [allRouteEntries]);

  if (!isAdmin) {
    return (
      <div style={{ padding:"60px 24px", textAlign:"center", color:"#718096" }}>
        <ShieldAlert size={32} style={{ margin:"0 auto 12px", color:"#CBD5E0" }} />
        <div style={{ fontSize:14, fontWeight:600 }}>관리자 전용 베타 화면입니다.</div>
      </div>
    );
  }
  if (loading) {
    return <div style={{ display:"flex", justifyContent:"center", padding:"80px 0" }}>
      <Loader2 size={24} className="animate-spin" style={{ color:"var(--hw-gold)" }} /></div>;
  }
  if (error || !detail) {
    return <div style={{ padding:24 }}>
      <div style={{ padding:"14px 16px", borderRadius:10, background:"#FFF5F5", border:"1px solid #FEB2B2",
        color:"#C53030", fontSize:13, fontWeight:600 }}>{error || "데이터 없음"}</div></div>;
  }

  const m = detail.master;
  const goQuickDoc = (url: string) => router.push(url);

  // 사증 영역 공통 행 렌더 — 하위 유래 route는 "코드 한글명" 줄을 함께 표시
  const renderRouteRow = (e: RouteEntry, i: number) => {
    const r = e.route;
    const tone = routeTone(r);
    return (
      <div key={r.route_id} onClick={() => setSel({ kind:"route", item:r, child:e.child })}
        style={{ display:"flex", alignItems:"center", gap:8, padding:"10px 12px", cursor:"pointer",
          borderTop: i > 0 ? "1px solid #F7FAFC" : "none",
          background: sel?.kind === "route" && sel.item.route_id === r.route_id ? "#FFFDF5" : "#fff" }}>
        <div style={{ flex:1, minWidth:0 }}>
          {e.child && (
            <div style={{ fontSize:11, fontWeight:700, color:"var(--hw-gold-text)", marginBottom:2, lineHeight:1.45 }}>
              {e.child.code}{" "}
              <span style={{ fontWeight:400, color:"#718096" }}>{e.child.name_ko}</span>
            </div>
          )}
          <div style={{ display:"flex", alignItems:"center", gap:6, flexWrap:"wrap" }}>
            <span style={{ fontSize:12.5, fontWeight:600, color:"#2D3748" }}>
              {r.route_label || ROUTE_TYPE_LABEL[r.route_type] || r.route_type}
            </span>
            <span style={{ fontSize:9.5, fontWeight:700, padding:"1px 8px", borderRadius:99,
              color:tone.color, background:tone.bg, border:`1px solid ${tone.border}` }}>{tone.badge}</span>
          </div>
          {isRouteUnfilled(r) && (
            <div style={{ marginTop:2, fontSize:10.5, color:"#975A16" }}>사증 경로 미정리 — 검수 필요</div>
          )}
        </div>
        <ChevronRight size={13} style={{ color:"#CBD5E0", flexShrink:0 }} />
      </div>
    );
  };

  return (
    <div style={{ padding:24, maxWidth:1280, margin:"0 auto" }}>
      {/* 브레드크럼 + 헤더 */}
      <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:14, flexWrap:"wrap" }}>
        <button onClick={() => router.push("/qualifications")}
          style={{ display:"flex", alignItems:"center", gap:4, fontSize:12, color:"#718096",
            background:"#F7FAFC", border:"1px solid #E2E8F0", borderRadius:20, padding:"4px 12px", cursor:"pointer" }}>
          <ArrowLeft size={12} /> 자격 목록
        </button>
        {detail.parent && (
          <>
            <ChevronRight size={13} style={{ color:"#CBD5E0" }} />
            <button onClick={() => router.push(`/qualifications/${encodeURIComponent(detail.parent!.code)}`)}
              style={{ fontSize:12, color:"#718096", background:"#F7FAFC", border:"1px solid #E2E8F0",
                borderRadius:20, padding:"4px 12px", cursor:"pointer" }}>
              {detail.parent.code} {detail.parent.name_ko}
            </button>
          </>
        )}
        <ChevronRight size={13} style={{ color:"#CBD5E0" }} />
        <span style={{ fontSize:12, fontWeight:700, color:"var(--hw-gold-text)", padding:"4px 12px",
          borderRadius:20, background:"rgba(212,168,67,0.08)", border:"1px solid rgba(212,168,67,0.35)" }}>
          {m.code} {m.name_ko}
        </span>
      </div>

      <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", padding:"16px 18px", marginBottom:16 }}>
        <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:8, flexWrap:"wrap" }}>
          <span style={{ fontSize:18, fontWeight:700, color:"#2D3748" }}>{m.code} {m.name_ko}</span>
          {detail.programs.map(p => <ProgramChip key={p.program_id} program={p} />)}
          {m.delegated_to && (
            <span style={{ fontSize:11, fontWeight:600, padding:"3px 10px", borderRadius:99,
              background:"#FFFFF0", color:"#975A16", border:"1px solid #F6E05E" }}>
              본편 챕터 없음 — 동포매뉴얼 기준
            </span>
          )}
        </div>
        <div style={{ fontSize:12.5, color:"#4A5568", lineHeight:1.7 }}>
          {m.activity_scope && <div>활동범위: {m.activity_scope}</div>}
          {m.eligible_persons && <div>해당자: {m.eligible_persons}</div>}
          {m.stay_limit
            ? <div>1회 체류기간 상한: {m.stay_limit}</div>
            : <div style={{ color:"#C53030" }}>1회 체류기간 상한: 확인 필요</div>}
        </div>
        {m.sub_codes.length > 0 && (
          <div style={{ marginTop:10, display:"flex", alignItems:"center", gap:6, flexWrap:"wrap" }}>
            <span style={{ fontSize:11, color:"#A0AEC0" }}>세부약호:</span>
            {[...m.sub_codes].sort(compareQualCode).map(c => (
              <button key={c} onClick={() => router.push(`/qualifications/${encodeURIComponent(c)}`)}
                style={{ fontSize:11, fontWeight:600, color:"#4A5568", background:"#F7FAFC",
                  border:"1px solid #E2E8F0", borderRadius:8, padding:"2px 8px", cursor:"pointer",
                  textAlign:"left", maxWidth:"100%", whiteSpace:"normal", lineHeight:1.45 }}>
                <span style={{ whiteSpace:"nowrap" }}>{c}</span>
                {subNames[c] && <span style={{ fontWeight:400, marginLeft:5, color:"#718096" }}>{subNames[c]}</span>}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 레이아웃: 좌측 좁은 선택 패널(체류 민원 → 사증발급인정서 → 사증, 세로 3섹션)
          + 우측 넓은 상세 패널(세부서류 가독성 우선). 좁은 화면에서는 자연 스택. */}
      <div style={{ display:"flex", gap:16, alignItems:"flex-start", flexWrap:"wrap" }}>
        <div style={{ flex:"1 1 300px", maxWidth:400, minWidth:280, display:"flex", flexDirection:"column", gap:14 }}>
          {/* ① 체류 민원 */}
          <div>
            <div style={{ fontSize:12.5, fontWeight:700, color:"#4A5568", marginBottom:8 }}>
              체류 민원 <span style={{ color:"#A0AEC0", fontWeight:600 }}>({baseBlocks.length})</span>
            </div>
            <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", overflow:"hidden" }}>
              {baseBlocks.map((b, i) => {
                const summary = b.applicability === "not_applicable"
                  ? sanitizeNaReasonDisplay(stripInternalIds(`${b.na_reason ?? ""}${b.redirect_to ? ` → 대안: ${b.redirect_to}` : ""}`))
                  : b.applicability === "unknown" ? unknownSummary(b)
                  : b.applicability === "conditional" ? "일정 요건을 충족하는 경우에만 진행합니다 — 상세 참조"
                  : b.v2_row_ids.length > 0 ? `기존 지침 ${b.v2_row_ids.length}건 연결` : "";
                return (
                  <div key={b.block_id}
                    onClick={() => setSel({ kind:"block", item:b })}
                    style={{ display:"flex", alignItems:"center", gap:8, padding:"10px 12px", cursor:"pointer",
                      borderTop: i > 0 ? "1px solid #F7FAFC" : "none",
                      background: sel?.kind === "block" && sel.item.block_id === b.block_id ? "#FFFDF5" : "#fff" }}>
                    <div style={{ flex:1, minWidth:0 }}>
                      <div style={{ display:"flex", alignItems:"center", gap:6, flexWrap:"wrap" }}>
                        <span style={{ fontSize:10.5, color:"#A0AEC0", flexShrink:0 }}>{b.block_order}</span>
                        <span style={{ fontSize:12.5, fontWeight:600, color:"#2D3748" }}>{b.block_label}</span>
                        <ApplicabilityBadge value={b.applicability} />
                        {b.conflict && (
                          <span style={{ fontSize:9.5, fontWeight:700, padding:"1px 7px", borderRadius:99,
                            background:"#FFFAF0", color:"#975A16", border:"1px solid #F6AD55" }}>⚠ 기준 충돌</span>
                        )}
                      </div>
                      {summary && (
                        <div style={{ marginTop:2, fontSize:10.5, color:"#A0AEC0", overflow:"hidden",
                          textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{summary}</div>
                      )}
                    </div>
                    <ChevronRight size={13} style={{ color:"#CBD5E0", flexShrink:0 }} />
                  </div>
                );
              })}
              {variantBlocks.length > 0 && (
                <div style={{ borderTop:"1px solid #EDF2F7", padding:"8px 12px" }}>
                  <div style={{ fontSize:10, fontWeight:700, color:"#A0AEC0", marginBottom:6 }}>변형 블록</div>
                  {variantBlocks.map(b => (
                    <div key={b.block_id} onClick={() => setSel({ kind:"block", item:b })}
                      style={{ display:"flex", alignItems:"center", gap:8, padding:"5px 0", cursor:"pointer", flexWrap:"wrap" }}>
                      <span style={{ fontSize:12, fontWeight:600, color:"#4A5568" }}>
                        {b.block_label}{b.variant === "residence_report" ? " (거소신고)" : b.variant === "activity_scope_add" ? " (활동범위 추가)" : ` (${b.variant})`}
                      </span>
                      <ApplicabilityBadge value={b.applicability} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* ② 사증발급인정서 — 상위 직접 + 하위 세부약호 route 통합('대상 아님'도 결과 행) */}
          <div>
            <div style={{ fontSize:12.5, fontWeight:700, color:"#4A5568", marginBottom:8 }}>
              사증발급인정서 <span style={{ color:"#A0AEC0", fontWeight:600 }}>({recogEntries.length})</span>
            </div>
            <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", overflow:"hidden" }}>
              {recogEntries.length === 0 ? (
                <div style={{ padding:"12px 14px", fontSize:11.5, color:"#975A16" }}>사증 경로 미정리 — 검수 필요</div>
              ) : recogEntries.map(renderRouteRow)}
            </div>
          </div>

          {/* ③ 사증 (재외공관·전자사증) — 상위 직접 + 하위 세부약호 route 통합 */}
          <div>
            <div style={{ fontSize:12.5, fontWeight:700, color:"#4A5568", marginBottom:8 }}>
              사증 <span style={{ fontWeight:600, color:"#A0AEC0" }}>(재외공관·전자) ({visaEntries.length})</span>
            </div>
            <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", overflow:"hidden" }}>
              {visaEntries.length === 0 ? (
                <div style={{ padding:"12px 14px", fontSize:11.5, color:"#975A16" }}>사증 경로 미정리 — 검수 필요</div>
              ) : visaEntries.map(renderRouteRow)}
            </div>
          </div>
        </div>

        {/* 우측: 상세 패널 (넓게 — 세부서류 가독성 우선) */}
        <div style={{ flex:"2 1 480px", minWidth:0 }}>
          {sel ? (
            <DetailPanelV3 sel={sel} v2Rows={detail.v2_rows}
              drs={detail.doc_requirements?.[sel.kind === "block" ? (sel.item as V3Block).block_id : (sel.item as V3Route).route_id] ?? []}
              subCodes={m.sub_codes ?? []} subNames={subNames}
              onClose={() => setSel(null)} onQuickDoc={goQuickDoc} />
          ) : (
            <div style={{ background:"#fff", borderRadius:12, border:"1px dashed #CBD5E0",
              padding:"56px 24px", textAlign:"center", color:"#A0AEC0", fontSize:13, lineHeight:1.8 }}>
              좌측에서 체류 민원 또는 사증 경로를 선택하세요.<br />
              수수료·신청인 준비서류·행정사 사무소 준비서류·해당 시 추가서류가 여기에 표시됩니다.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
