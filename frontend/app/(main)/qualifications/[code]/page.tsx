"use client";
// v3 자격 중심 실무지침 — 화면 2(자격 대시보드) + 화면 3(블록·경로 상세 패널)
// 관리자 read-only 베타 (FEATURE_GUIDELINES_V3)
// 좌측 = 체류 업무 격자(위) + 사증 경로 섹션(아래) 동시 표시, 우측 = 상세 패널.
import { CSSProperties, useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, ChevronRight, FileText, Loader2, ShieldAlert, X } from "lucide-react";
import {
  guidelinesV3Api, GuidelineRow, V3Block, V3DeleteImpact, V3DocRequirement,
  V3EntityType, V3QualificationDetail, V3Route,
} from "@/lib/api";
import { getUser, canManageContent } from "@/lib/auth";
import {
  ApplicabilityBadge, ProgramChip, ROUTE_TYPE_LABEL, routeTone,
  compareQualCode, stripInternalIds,
} from "@/components/qualifications/common";
import {
  DrEditor, EditIconButton, EntityEditModal, FieldSpec, ImpactDialog,
  blockFields, qualFields, routeFields, runDelete,
} from "@/components/qualifications/editV3";
import { isDocBlockedV2Row, sanitizeNaReasonDisplay, sanitizeV2RowForDisplay } from "@/components/qualifications/v2docSanitize";
import { GuidelineCard, buildQuickDocUrl } from "@/components/guidelines/shared";

// route 선택 시 child = 하위 세부약호 유래 경로(상위 화면에 집계 표시) — 상세는 하위 자격 detail에서 로드.
type Selection =
  | { kind: "block"; item: V3Block }
  | { kind: "route"; item: V3Route; child?: { code: string; name_ko: string } }
  | null;

// 상위 화면 사증 영역 집계용: 상위 직접 route + 하위 세부약호 route (route_id 기준 중복 제거).
// common=true 는 세부약호 페이지에서 상위 자격의 공통 판정 route 를 상속 표시하는 경우.
type RouteEntry = { route: V3Route; child?: { code: string; name_ko: string }; common?: boolean };
// route 유형 분리(2026-07-14 정합성 복구): 섹션 건수는 실제 신청 가능한 경로만 집계.
// 상태 행(국내 부여·변경 / 대상 아님 / 신청 중단)과 대체 신청 경로는 비클릭 안내로 별도 표시.
const REAL_RECOG_TYPES = ["recognition"];
const REAL_VISA_TYPES = ["consulate", "evisa"];
const ALT_TYPES = ["alternative_route"];
const STATUS_TYPES = ["not_applicable", "excluded", "domestic_only", "discontinued"];

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
        const sanitized = sanitizeV2RowForDisplay(row);
        // 서류 목록 신뢰 불가로 차단된 v2 행 — 서류는 위 v3 준비서류 구분이 정본이므로 목록만 비표시
        const displayRow = isDocBlockedV2Row(row.row_id)
          ? { ...sanitized, form_docs: "", supporting_docs: "" }
          : sanitized;
        const url = buildQuickDocUrl(row);
        return (
          <div key={row.row_id}>
            <GuidelineCard row={displayRow} isSelected={selectedId === row.row_id} defaultExpanded
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

function DetailPanelV3({ sel, v2Rows, drs, subCodes, subNames, onClose, onQuickDoc, editMode, onEdited }: {
  sel: NonNullable<Selection>; v2Rows: GuidelineRow[]; drs: V3DocRequirement[];
  subCodes: string[]; subNames: Record<string, string>; onClose: () => void; onQuickDoc: (url: string) => void;
  editMode?: boolean; onEdited?: () => void;
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
          {isBlock && effB!.fee && (
            <div style={{ marginBottom:12, fontSize:12, color:"#4A5568", lineHeight:1.7 }}>
              <div>수수료: <strong>{effB!.fee}</strong></div>
              <div style={{ fontSize:11, color:"#A0AEC0" }}>면제·감면 대상 여부는 관할 출입국·외국인관서 기준에 따릅니다.</div>
            </div>
          )}
          {!isBlock && (
            <div style={{ marginBottom:12, fontSize:12, color:"#4A5568", lineHeight:1.7 }}>
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

          {/* 준비서류 편집기 — 편집 모드에서만(각 구분 추가·수정·삭제) */}
          {editMode && onEdited && (
            <DrEditor
              targetId={isBlock ? (effB!.block_id) : (r!.route_id)}
              drs={effDrs}
              onChanged={onEdited} />
          )}

          {/* ⑤ 준비서류/필요서류 — A) v3 DR B) 인라인 목록 C) v2 참고 D) 특수경로 안내.
              신청 대상이 아닌 블록(불가)에는 서류 영역을 표시하지 않는다. */}
          {(!isBlock || effB!.applicability === "applicable" || effB!.applicability === "conditional") && (
            effDrs.length > 0 ? (
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
            ) : null
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

  // ── 편집(CRUD) 상태 — detail.editable(FEATURE_GUIDELINES_V3_EDIT)일 때만 노출 ──
  const [editMode, setEditMode] = useState(false);
  const [modal, setModal] = useState<{
    etype: V3EntityType; mode: "create" | "edit"; title: string;
    fields: FieldSpec[]; initial: Record<string, unknown>; id?: string;
  } | null>(null);
  const [impactState, setImpactState] = useState<{
    etype: V3EntityType; id: string; label: string;
    impact: V3DeleteImpact; cascadeAllowed: boolean;
  } | null>(null);
  const [reloadTick, setReloadTick] = useState(0);

  const loadDetail = useCallback(() => {
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

  useEffect(() => { loadDetail(); }, [loadDetail]);

  // 편집 저장 후 전체 재조회 — 상세 fetch 캐시까지 비워 목록·상세·집계를 일치시킨다
  const reloadAll = useCallback(() => {
    _subDetailCache.clear();
    setReloadTick(t => t + 1);
    loadDetail();
  }, [loadDetail]);

  const saveModal = useCallback(async (payload: Record<string, unknown>) => {
    if (!modal) return;
    if (modal.mode === "edit" && modal.id) {
      await guidelinesV3Api.editUpdate(modal.etype, modal.id, payload);
    } else {
      await guidelinesV3Api.editCreate(modal.etype, payload);
    }
    reloadAll();
  }, [modal, reloadAll]);

  // 세부약호 페이지: 상위 자격의 공통 판정 route(예: F-5 '사증발급인정서 대상 아님',
  // E-9 고용허가 인정서, D-2 유학 공통 경로) 상속 표시용 — 캐시 fetch(원본 데이터 무수정)
  const parentCode = detail?.parent?.code ?? null;
  const [parentDetail, setParentDetail] = useState<V3QualificationDetail | null>(null);
  useEffect(() => {
    if (!parentCode) { setParentDetail(null); return; }
    let alive = true;
    setParentDetail(null);
    fetchQualDetail(parentCode)
      .then(d => { if (alive) setParentDetail(d); })
      .catch(() => { /* 상위 상세 로드 실패 시 자체 route만 표시 */ });
    return () => { alive = false; };
  }, [parentCode, reloadTick]);

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
    // 세부약호 페이지: 상위의 '직접' route만 공통 판정으로 상속(형제 세부약호 전용 route는 제외)
    if (parentDetail) {
      for (const r of parentDetail.routes ?? []) {
        if (!seen.has(r.route_id)) {
          seen.add(r.route_id);
          out.push({ route: r, child: { code: parentDetail.master.code, name_ko: parentDetail.master.name_ko }, common: true });
        }
      }
    }
    return out;
  }, [detail, parentDetail]);
  const recogEntries = useMemo(
    () => allRouteEntries.filter(e => REAL_RECOG_TYPES.includes(e.route.route_type)),
    [allRouteEntries]);
  const visaEntries = useMemo(
    () => allRouteEntries.filter(e => REAL_VISA_TYPES.includes(e.route.route_type)),
    [allRouteEntries]);
  const altEntries = useMemo(
    () => allRouteEntries.filter(e => ALT_TYPES.includes(e.route.route_type)),
    [allRouteEntries]);
  const statusEntries = useMemo(
    () => allRouteEntries.filter(e => STATUS_TYPES.includes(e.route.route_type)),
    [allRouteEntries]);
  const naStatusEntries = useMemo(
    () => statusEntries.filter(e => e.route.route_type === "not_applicable" || e.route.route_type === "excluded"),
    [statusEntries]);
  const discontinuedEntries = useMemo(
    () => statusEntries.filter(e => e.route.route_type === "discontinued"),
    [statusEntries]);
  const domesticEntries = useMemo(
    () => statusEntries.filter(e => e.route.route_type === "domestic_only"),
    [statusEntries]);

  if (!isAdmin) {
    return (
      <div style={{ padding:"60px 24px", textAlign:"center", color:"#718096" }}>
        <ShieldAlert size={32} style={{ margin:"0 auto 12px", color:"#CBD5E0" }} />
        <div style={{ fontSize:14, fontWeight:600 }}>관리자 전용 화면입니다.</div>
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
  const isEditable = !!detail.editable;
  const qid = m.qualification_id;

  const openRouteModal = (mode: "create" | "edit", r?: V3Route, presetType?: string) => {
    setModal({
      etype: "visa_route", mode, id: r?.route_id,
      title: mode === "edit" ? `사증 경로 수정 — ${r?.route_label}` : "사증 경로 추가",
      fields: routeFields(),
      initial: (r as unknown as Record<string, unknown>)
        ?? { qualification_id: qid, route_type: presetType ?? "recognition", is_active: true },
    });
  };
  const deleteRoute = (r: V3Route) =>
    runDelete("visa_route", r.route_id, r.route_label || r.route_id,
      (impact, cascadeAllowed) => setImpactState({ etype: "visa_route", id: r.route_id,
        label: r.route_label || r.route_id, impact, cascadeAllowed }),
      reloadAll);
  const openBlockModal = (mode: "create" | "edit", b?: V3Block) => {
    setModal({
      etype: "stay_block", mode, id: b?.block_id,
      title: mode === "edit" ? `체류업무 수정 — ${b?.block_label}` : "체류업무 추가",
      fields: blockFields(mode === "create"),
      initial: (b as unknown as Record<string, unknown>)
        ?? { qualification_id: qid, applicability: "applicable", is_active: true },
    });
  };
  const deleteBlock = (b: V3Block) =>
    runDelete("stay_block", b.block_id, b.block_label,
      (impact, cascadeAllowed) => setImpactState({ etype: "stay_block", id: b.block_id,
        label: b.block_label, impact, cascadeAllowed }),
      reloadAll);

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
              {e.common && (
                <span style={{ marginLeft:5, fontSize:9, fontWeight:700, padding:"1px 6px", borderRadius:99,
                  color:"#4A5568", background:"#EDF2F7", border:"1px solid #E2E8F0", verticalAlign:"middle" }}>공통</span>
              )}
            </div>
          )}
          <div style={{ display:"flex", alignItems:"center", gap:6, flexWrap:"wrap" }}>
            <span style={{ fontSize:12.5, fontWeight:600, color:"#2D3748" }}>
              {r.route_label || ROUTE_TYPE_LABEL[r.route_type] || r.route_type}
            </span>
            <span style={{ fontSize:9.5, fontWeight:700, padding:"1px 8px", borderRadius:99,
              color:tone.color, background:tone.bg, border:`1px solid ${tone.border}` }}>{tone.badge}</span>
            {editMode && <EditIconButton kind="edit" title="경로 수정" onClick={() => openRouteModal("edit", r)} />}
            {editMode && <EditIconButton kind="delete" title="경로 삭제" onClick={() => deleteRoute(r)} />}
          </div>
        </div>
        <ChevronRight size={13} style={{ color:"#CBD5E0", flexShrink:0 }} />
      </div>
    );
  };

  // 상태 행(대상 아님/신청 중단) — 신청 항목이 아니므로 비클릭 안내로만 표시(건수 미집계)
  const renderStatusRow = (e: RouteEntry, i: number) => {
    const r = e.route;
    const tone = routeTone(r);
    return (
      <div key={r.route_id} style={{ padding:"10px 12px", background:"#FAFAFA",
        borderTop: i > 0 ? "1px solid #F1F5F9" : "none" }}>
        {e.child && (
          <div style={{ fontSize:11, fontWeight:700, color:"#718096", marginBottom:2, lineHeight:1.45 }}>
            {e.child.code} <span style={{ fontWeight:400 }}>{e.child.name_ko}</span>
            {e.common && (
              <span style={{ marginLeft:5, fontSize:9, fontWeight:700, padding:"1px 6px", borderRadius:99,
                color:"#4A5568", background:"#EDF2F7", border:"1px solid #E2E8F0", verticalAlign:"middle" }}>공통</span>
            )}
          </div>
        )}
        <div style={{ display:"flex", alignItems:"center", gap:6, flexWrap:"wrap" }}>
          <span style={{ fontSize:12, fontWeight:600, color:"#4A5568" }}>
            {r.route_label || ROUTE_TYPE_LABEL[r.route_type] || r.route_type}
          </span>
          <span style={{ fontSize:9.5, fontWeight:700, padding:"1px 8px", borderRadius:99,
            color:tone.color, background:tone.bg, border:`1px solid ${tone.border}` }}>{tone.badge}</span>
          {editMode && <EditIconButton kind="edit" title="상태 항목 수정" onClick={() => openRouteModal("edit", r)} />}
          {editMode && <EditIconButton kind="delete" title="상태 항목 삭제" onClick={() => deleteRoute(r)} />}
        </div>
        {(r.exceptions ?? []).map((x, j) => (
          <div key={j} style={{ marginTop:3, fontSize:11, color:"#718096", lineHeight:1.55 }}>{stripInternalIds(x)}</div>
        ))}
      </div>
    );
  };

  // 대체 신청 경로 — 다른 자격의 사증으로 신청하는 경우(건수 별도, 인정서·사증 건수 미포함)
  const renderAltRow = (e: RouteEntry, i: number) => {
    const r = e.route;
    return (
      <div key={r.route_id} style={{ padding:"12px 14px", borderTop: i > 0 ? "1px solid #F1F5F9" : "none" }}>
        {e.child && (
          <div style={{ fontSize:11, fontWeight:700, color:"var(--hw-gold-text)", marginBottom:2, lineHeight:1.45 }}>
            {e.child.code} <span style={{ fontWeight:400, color:"#718096" }}>{e.child.name_ko}</span>
          </div>
        )}
        <div style={{ display:"flex", alignItems:"center", gap:6, flexWrap:"wrap", marginBottom:4 }}>
          <span style={{ fontSize:12.5, fontWeight:600, color:"#2D3748" }}>{r.route_label}</span>
          <span style={{ fontSize:9.5, fontWeight:700, padding:"1px 8px", borderRadius:99,
            color:"#553C9A", background:"#FAF5FF", border:"1px solid #D6BCFA" }}>대체 경로</span>
          {editMode && <EditIconButton kind="edit" title="대체 경로 수정" onClick={() => openRouteModal("edit", r)} />}
          {editMode && <EditIconButton kind="delete" title="대체 경로 삭제" onClick={() => deleteRoute(r)} />}
        </div>
        <div style={{ fontSize:11.5, color:"#4A5568", lineHeight:1.65 }}>
          {r.alt_apply_as && <div>신청 경로: <strong>{r.alt_apply_as}</strong></div>}
          {r.alt_relation && <div>관계: {r.alt_relation}</div>}
          {r.alt_follow_up && <div>이후 절차: {r.alt_follow_up}</div>}
          {r.alt_caution && <div style={{ color:"#975A16" }}>주의: {r.alt_caution}</div>}
        </div>
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
          {isEditable && (
            <button onClick={() => setEditMode(v => !v)}
              style={{ fontSize:11, fontWeight:700, padding:"3px 12px", borderRadius:99, cursor:"pointer",
                border:`1.5px solid ${editMode ? "#C53030" : "#CBD5E0"}`,
                background: editMode ? "#FFF5F5" : "#fff", color: editMode ? "#C53030" : "#718096" }}>
              {editMode ? "편집 종료" : "편집"}
            </button>
          )}
          {isEditable && editMode && (
            <>
              <EditIconButton kind="edit" title="자격 정보 수정"
                onClick={() => setModal({ etype:"qualification", mode:"edit", id: qid,
                  title:`자격 수정 — ${m.code} ${m.name_ko}`,
                  fields: qualFields([{ value: m.group, label: m.group }], !!detail.parent)
                    .map(f => f.key === "code" ? { ...f, readOnly: true } : f),
                  initial: m as unknown as Record<string, unknown> })} />
              <EditIconButton kind="delete" title="자격 삭제"
                onClick={() => runDelete("qualification", qid, `${m.code} ${m.name_ko}`,
                  (impact, cascadeAllowed) => setImpactState({ etype:"qualification", id: qid,
                    label:`${m.code} ${m.name_ko}`, impact, cascadeAllowed }),
                  () => router.push(detail.parent
                    ? `/qualifications/${encodeURIComponent(detail.parent.code)}` : "/qualifications"))} />
              {!detail.parent && (
                <button onClick={() => setModal({ etype:"qualification", mode:"create",
                  title:`세부약호 추가 — ${m.code}`,
                  fields: qualFields([], true),
                  initial: { parent_qualification_id: qid, is_active: true } })}
                  style={{ fontSize:11, fontWeight:700, padding:"3px 12px", borderRadius:99, cursor:"pointer",
                    border:"1.5px solid rgba(212,168,67,0.55)", background:"rgba(212,168,67,0.08)",
                    color:"var(--hw-gold-text)" }}>
                  + 세부약호
                </button>
              )}
            </>
          )}
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
          {m.stay_limit && <div>1회 체류기간 상한: {m.stay_limit}</div>}
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
            <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:8 }}>
              <span style={{ fontSize:12.5, fontWeight:700, color:"#4A5568" }}>
                체류 민원 <span style={{ color:"#A0AEC0", fontWeight:600 }}>({baseBlocks.length})</span>
              </span>
              {editMode && <EditIconButton kind="add" title="체류업무 추가" onClick={() => openBlockModal("create")} />}
            </div>
            <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", overflow:"hidden" }}>
              {baseBlocks.map((b, i) => {
                const summary = b.applicability === "not_applicable"
                  ? sanitizeNaReasonDisplay(stripInternalIds(`${b.na_reason ?? ""}${b.redirect_to ? ` → 대안: ${b.redirect_to}` : ""}`))
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
                        {editMode && <EditIconButton kind="edit" title="업무 수정" onClick={() => openBlockModal("edit", b)} />}
                        {editMode && <EditIconButton kind="delete" title="업무 삭제" onClick={() => deleteBlock(b)} />}
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

          {/* ② 사증발급인정서 — 실제 신청 가능한 경로만 집계, '대상 아님'은 비클릭 상태 안내 */}
          <div>
            <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:8 }}>
              <span style={{ fontSize:12.5, fontWeight:700, color:"#4A5568" }}>
                사증발급인정서 <span style={{ color:"#A0AEC0", fontWeight:600 }}>({recogEntries.length})</span>
              </span>
              {editMode && <EditIconButton kind="add" title="인정서 경로 추가"
                onClick={() => openRouteModal("create", undefined, "recognition")} />}
            </div>
            <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", overflow:"hidden" }}>
              {recogEntries.map(renderRouteRow)}
              {naStatusEntries.map((e, i) => renderStatusRow(e, recogEntries.length + i))}
              {recogEntries.length === 0 && naStatusEntries.length === 0 && (
                <div style={{ padding:"12px 14px", fontSize:11.5, color:"#718096" }}>
                  사증발급인정서 신청 경로가 없는 자격입니다.
                </div>
              )}
            </div>
          </div>

          {/* ③ 사증 (재외공관·전자사증) — 실제 신청 가능한 경로만 집계, 신청 중단은 상태 안내 */}
          <div>
            <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:8 }}>
              <span style={{ fontSize:12.5, fontWeight:700, color:"#4A5568" }}>
                사증 <span style={{ fontWeight:600, color:"#A0AEC0" }}>(재외공관·전자) ({visaEntries.length})</span>
              </span>
              {editMode && <EditIconButton kind="add" title="사증 경로 추가"
                onClick={() => openRouteModal("create", undefined, "consulate")} />}
            </div>
            <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", overflow:"hidden" }}>
              {visaEntries.map(renderRouteRow)}
              {discontinuedEntries.map((e, i) => renderStatusRow(e, visaEntries.length + i))}
              {visaEntries.length === 0 && discontinuedEntries.length === 0 && (
                <div style={{ padding:"12px 14px", fontSize:11.5, color:"#718096" }}>
                  {recogEntries.length > 0
                    ? "재외공관 직접 신청 경로가 없는 자격입니다 — 사증발급인정서 경로로 진행합니다."
                    : "재외공관·전자사증 신청 경로가 없는 자격입니다."}
                </div>
              )}
            </div>
          </div>

          {/* ④ 대체 신청 경로 — 다른 자격의 사증으로 신청(인정서·사증 건수와 중복 집계 안 함) */}
          {altEntries.length > 0 && (
            <div>
              <div style={{ fontSize:12.5, fontWeight:700, color:"#4A5568", marginBottom:8 }}>
                대체 신청 경로 <span style={{ color:"#A0AEC0", fontWeight:600 }}>({altEntries.length})</span>
              </div>
              <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", overflow:"hidden" }}>
                {altEntries.map(renderAltRow)}
              </div>
            </div>
          )}

          {/* ⑤ 국내 신청 안내 — 사증이 아닌 국내 체류자격 부여·변경으로 취득하는 유형 */}
          {domesticEntries.length > 0 && (
            <div>
              <div style={{ fontSize:12.5, fontWeight:700, color:"#4A5568", marginBottom:8 }}>
                국내 신청 안내 <span style={{ color:"#A0AEC0", fontWeight:600 }}>({domesticEntries.length})</span>
              </div>
              <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", overflow:"hidden" }}>
                {domesticEntries.map(renderStatusRow)}
              </div>
            </div>
          )}
        </div>

        {/* 우측: 상세 패널 (넓게 — 세부서류 가독성 우선) */}
        <div style={{ flex:"2 1 480px", minWidth:0 }}>
          {sel ? (
            <DetailPanelV3 sel={sel} v2Rows={detail.v2_rows}
              drs={detail.doc_requirements?.[sel.kind === "block" ? (sel.item as V3Block).block_id : (sel.item as V3Route).route_id] ?? []}
              subCodes={m.sub_codes ?? []} subNames={subNames}
              onClose={() => setSel(null)} onQuickDoc={goQuickDoc}
              editMode={editMode} onEdited={reloadAll} />
          ) : (
            <div style={{ background:"#fff", borderRadius:12, border:"1px dashed #CBD5E0",
              padding:"56px 24px", textAlign:"center", color:"#A0AEC0", fontSize:13, lineHeight:1.8 }}>
              좌측에서 체류 민원 또는 사증 경로를 선택하세요.<br />
              수수료·신청인 준비서류·행정사 사무소 준비서류·해당 시 추가서류가 여기에 표시됩니다.
            </div>
          )}
        </div>
      </div>

      {/* 편집 모달 + 삭제 영향 확인 */}
      {modal && (
        <EntityEditModal title={modal.title} fields={modal.fields} initial={modal.initial}
          onSave={saveModal} onClose={() => setModal(null)} />
      )}
      {impactState && (
        <ImpactDialog entityLabel={impactState.label} impact={impactState.impact}
          onCascade={impactState.cascadeAllowed
            ? async () => {
                await guidelinesV3Api.editDelete(impactState.etype, impactState.id, true);
                if (impactState.etype === "qualification" && impactState.id === qid) {
                  router.push(detail.parent
                    ? `/qualifications/${encodeURIComponent(detail.parent.code)}` : "/qualifications");
                } else {
                  reloadAll();
                }
              }
            : null}
          onClose={() => setImpactState(null)} />
      )}
    </div>
  );
}
