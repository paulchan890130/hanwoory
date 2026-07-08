"use client";
// v3 자격 중심 실무지침 — 화면 2(자격 대시보드) + 화면 3(블록·경로 상세 패널)
// 관리자 read-only 베타 (FEATURE_GUIDELINES_V3)
import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft, ChevronRight, FileText, Loader2, ShieldAlert, X } from "lucide-react";
import { guidelinesV3Api, GuidelineRow, V3Block, V3QualificationDetail, V3Route } from "@/lib/api";
import { getUser, canManageContent } from "@/lib/auth";
import {
  ApplicabilityBadge, ConfidenceChip, ProgramChip, ROUTE_TYPE_LABEL, SourceNote, routeTone,
  compareQualCode, stripInternalIds,
} from "@/components/qualifications/common";
import { GuidelineCard, buildQuickDocUrl } from "@/components/guidelines/shared";

type Selection = { kind: "block"; item: V3Block } | { kind: "route"; item: V3Route } | null;

function DocGroup({ title, color, docs }: { title: string; color: string; docs: string[] }) {
  if (!docs || docs.length === 0) return null;
  return (
    <div style={{ marginBottom:10 }}>
      <div style={{ fontSize:10, fontWeight:700, color, marginBottom:6 }}>{title} ({docs.length})</div>
      <div style={{ display:"flex", flexWrap:"wrap", gap:4 }}>
        {docs.map((d, i) => (
          <span key={i} style={{ fontSize:11, padding:"3px 9px", borderRadius:99,
            background:`${color}14`, color, border:`1px solid ${color}40` }}>{d}</span>
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
        const url = buildQuickDocUrl(row);
        return (
          <div key={row.row_id}>
            <GuidelineCard row={row} isSelected={selectedId === row.row_id}
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

function DetailPanelV3({ sel, v2Rows, onClose, onQuickDoc }: {
  sel: NonNullable<Selection>; v2Rows: GuidelineRow[]; onClose: () => void; onQuickDoc: (url: string) => void;
}) {
  const isBlock = sel.kind === "block";
  const b = isBlock ? (sel.item as V3Block) : null;
  const r = !isBlock ? (sel.item as V3Route) : null;
  const linkedIds = isBlock ? (b!.v2_row_ids ?? []) : (r!.v2_row_id ? [r!.v2_row_id] : []);
  const linked = v2Rows.filter(row => linkedIds.includes(row.row_id));

  return (
    <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", padding:"16px 18px" }}>
      <div style={{ display:"flex", alignItems:"flex-start", gap:8, marginBottom:12 }}>
        <div style={{ flex:1 }}>
          <div style={{ fontSize:14, fontWeight:700, color:"#2D3748", marginBottom:6 }}>
            {isBlock ? b!.block_label : (r!.route_label || ROUTE_TYPE_LABEL[r!.route_type] || r!.route_type)}
          </div>
          <div style={{ display:"flex", alignItems:"center", gap:6, flexWrap:"wrap" }}>
            {isBlock
              ? <ApplicabilityBadge value={b!.applicability} />
              : (() => { const tone = routeTone(r!); return (
                  <span style={{ fontSize:11, fontWeight:700, padding:"3px 10px", borderRadius:99,
                    color:tone.color, background:tone.bg, border:`1px solid ${tone.border}` }}>{tone.badge}</span>
                ); })()}
            <ConfidenceChip value={sel.item.confidence} />
          </div>
        </div>
        <button onClick={onClose} style={{ padding:4, color:"#A0AEC0", background:"none", border:"none", cursor:"pointer" }}>
          <X size={16} />
        </button>
      </div>

      {isBlock && b!.applicability === "not_applicable" && (
        <div style={{ marginBottom:12, padding:"10px 12px", borderRadius:10, background:"#EDF2F7",
          border:"1px solid #CBD5E0", fontSize:12, color:"#4A5568", lineHeight:1.6 }}>
          <div><strong>사유:</strong> {stripInternalIds(b!.na_reason)}</div>
          {b!.redirect_to && <div style={{ marginTop:4 }}><strong>대안:</strong> {stripInternalIds(b!.redirect_to)}</div>}
        </div>
      )}
      {isBlock && b!.applicability === "unknown" && (
        <div style={{ marginBottom:12, padding:"10px 12px", borderRadius:10, background:"#FFF5F5",
          border:"1px solid #FEB2B2", fontSize:12, color:"#C53030", lineHeight:1.6 }}>
          원문 확인 전 — 손님에게는 "관서 확인 후 안내"로 응대하세요. {stripInternalIds(b!.notes)}
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

      <DocGroup title="사무소 준비 (office)" color="#4299E1" docs={sel.item.office_docs} />
      <DocGroup title="손님 지참 (client)" color="#48BB78" docs={sel.item.client_docs} />
      <DocGroup title="조건부 (conditional)" color="#975A16" docs={sel.item.conditional_docs} />
      {(sel.item.office_docs.length + sel.item.client_docs.length + sel.item.conditional_docs.length) === 0 && (
        <div style={{ fontSize:11, color:"#A0AEC0", marginBottom:10 }}>
          서류 상세는 후속 입력 단계 — 아래 연결된 기존(v2) 지침의 서류를 참조하세요.
        </div>
      )}

      {sel.item.exceptions.length > 0 && (
        <div style={{ marginBottom:10 }}>
          <div style={{ fontSize:10, fontWeight:700, color:"#975A16", marginBottom:4 }}>예외·주의</div>
          {sel.item.exceptions.map((e, i) => (
            <div key={i} style={{ fontSize:12, color:"#4A5568", lineHeight:1.6 }}>· {stripInternalIds(e)}</div>
          ))}
        </div>
      )}
      {isBlock && b!.visa_docs_reference && (
        <div style={{ marginBottom:10, fontSize:12, color:"#4A5568" }}>
          서류 준용: <span style={{ fontWeight:600 }}>{b!.visa_docs_reference}</span> (사증 인정신청 기준)
        </div>
      )}
      {sel.item.notes && (
        <div style={{ marginBottom:12, fontSize:11, color:"#718096", lineHeight:1.6 }}>{stripInternalIds(sel.item.notes)}</div>
      )}
      <div style={{ marginBottom:14 }}>
        <SourceNote manual={sel.item.source_manual} pages={sel.item.source_pages} />
      </div>

      <div style={{ borderTop:"1px solid #EDF2F7", paddingTop:12 }}>
        <div style={{ fontSize:11, fontWeight:700, color:"#4A5568", marginBottom:8 }}>연결된 기존 지침 (v2)</div>
        <LinkedV2Section rows={linked} onQuickDoc={onQuickDoc} />
      </div>
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
  const [tab, setTab] = useState<"stay" | "visa">("stay");
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
          <ConfidenceChip value={m.confidence} />
        </div>
        <div style={{ fontSize:12.5, color:"#4A5568", lineHeight:1.7 }}>
          {m.activity_scope && <div>활동범위: {m.activity_scope}</div>}
          {m.eligible_persons && <div>해당자: {m.eligible_persons}</div>}
          {m.stay_limit
            ? <div>1회 체류기간 상한: {m.stay_limit}</div>
            : <div style={{ color:"#C53030" }}>1회 체류기간 상한: 미입력 — 확인필요</div>}
        </div>
        <div style={{ marginTop:8 }}><SourceNote manual={m.source_manual} pages={m.source_pages} /></div>
        {m.sub_codes.length > 0 && (
          <div style={{ marginTop:10, display:"flex", alignItems:"center", gap:6, flexWrap:"wrap" }}>
            <span style={{ fontSize:11, color:"#A0AEC0" }}>세부약호:</span>
            {[...m.sub_codes].sort(compareQualCode).map(c => (
              <button key={c} onClick={() => router.push(`/qualifications/${encodeURIComponent(c)}`)}
                style={{ fontSize:11, fontWeight:600, color:"#4A5568", background:"#F7FAFC",
                  border:"1px solid #E2E8F0", borderRadius:8, padding:"2px 8px", cursor:"pointer" }}>
                {c}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 탭 */}
      <div className="hw-tabs" style={{ marginBottom:14 }}>
        <button className={`hw-tab ${tab === "stay" ? "active" : ""}`} onClick={() => { setTab("stay"); setSel(null); }}>
          체류 업무 격자
        </button>
        <button className={`hw-tab ${tab === "visa" ? "active" : ""}`} onClick={() => { setTab("visa"); setSel(null); }}>
          사증 경로 ({detail.routes.length + detail.children.reduce((n, c) => n + c.routes.length, 0)})
        </button>
      </div>

      <div style={{ display:"flex", gap:16, alignItems:"flex-start" }}>
        <div style={{ flex:1, minWidth:0 }}>
          {tab === "stay" && (
            <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", overflow:"hidden" }}>
              {baseBlocks.map((b, i) => (
                <div key={b.block_id}
                  onClick={() => setSel({ kind:"block", item:b })}
                  style={{ display:"flex", alignItems:"center", gap:12, padding:"12px 16px", cursor:"pointer",
                    borderTop: i > 0 ? "1px solid #F7FAFC" : "none",
                    background: sel?.kind === "block" && sel.item.block_id === b.block_id ? "#FFFDF5" : "#fff" }}>
                  <span style={{ fontSize:11, color:"#A0AEC0", width:18, flexShrink:0 }}>{b.block_order}</span>
                  <span style={{ fontSize:13, fontWeight:600, color:"#2D3748", width:170, flexShrink:0 }}>{b.block_label}</span>
                  <ApplicabilityBadge value={b.applicability} />
                  <span style={{ fontSize:11.5, color:"#718096", overflow:"hidden", textOverflow:"ellipsis",
                    whiteSpace:"nowrap", flex:1 }}>
                    {b.applicability === "not_applicable"
                      ? stripInternalIds(`${b.na_reason ?? ""}${b.redirect_to ? ` → 대안: ${b.redirect_to}` : ""}`)
                      : b.applicability === "unknown" ? "원문 확인 전 — 관서 확인 후 안내"
                      : b.applicability === "conditional" ? stripInternalIds(b.notes || "케이스에 따라 갈림")
                      : b.v2_row_ids.length > 0 ? `기존 지침 ${b.v2_row_ids.length}건 연결` : ""}
                  </span>
                  <ChevronRight size={14} style={{ color:"#CBD5E0", flexShrink:0 }} />
                </div>
              ))}
              {variantBlocks.length > 0 && (
                <div style={{ borderTop:"1px solid #EDF2F7", padding:"10px 16px" }}>
                  <div style={{ fontSize:10, fontWeight:700, color:"#A0AEC0", marginBottom:8 }}>변형 블록</div>
                  {variantBlocks.map(b => (
                    <div key={b.block_id} onClick={() => setSel({ kind:"block", item:b })}
                      style={{ display:"flex", alignItems:"center", gap:10, padding:"6px 0", cursor:"pointer" }}>
                      <span style={{ fontSize:12.5, fontWeight:600, color:"#4A5568" }}>
                        {b.block_label}{b.variant === "residence_report" ? " (거소신고)" : b.variant === "activity_scope_add" ? " (활동범위 추가)" : ` (${b.variant})`}
                      </span>
                      <ApplicabilityBadge value={b.applicability} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {tab === "visa" && (
            <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
              {detail.routes.length === 0 && detail.children.every(c => c.routes.length === 0) && (
                <div style={{ padding:"20px 16px", borderRadius:12, background:"#fff", border:"1px solid #E2E8F0",
                  fontSize:12.5, color:"#718096" }}>
                  이 자격에 입력된 사증 경로가 없습니다 (원문 확인 전이거나 국내 취득 자격).
                </div>
              )}
              {detail.routes.length > 0 && (
                <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(280px, 1fr))", gap:10 }}>
                  {detail.routes.map(r => {
                    const tone = routeTone(r);
                    return (
                      <div key={r.route_id} onClick={() => setSel({ kind:"route", item:r })}
                        style={{ background:"#fff", borderRadius:12, border:`1px solid ${
                          sel?.kind === "route" && sel.item.route_id === r.route_id ? "var(--hw-gold)" : "#E2E8F0"}`,
                          padding:"14px 16px", cursor:"pointer" }}>
                        <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:6, flexWrap:"wrap" }}>
                          <span style={{ fontSize:13, fontWeight:700, color:"#2D3748" }}>
                            {r.route_label || ROUTE_TYPE_LABEL[r.route_type] || r.route_type}
                          </span>
                          <span style={{ fontSize:10, fontWeight:700, padding:"2px 8px", borderRadius:99,
                            color:tone.color, background:tone.bg, border:`1px solid ${tone.border}` }}>{tone.badge}</span>
                        </div>
                        <div style={{ fontSize:11.5, color:"#718096", lineHeight:1.6 }}>
                          {r.application_place && <div>{r.application_place}</div>}
                          {r.application_form && <div>{r.application_form}{r.fee ? ` · 수수료 ${r.fee}` : ""}</div>}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
              {detail.children.filter(c => c.routes.length > 0).length > 0 && (
                <div style={{ background:"#fff", borderRadius:12, border:"1px solid #E2E8F0", padding:"14px 16px" }}>
                  <div style={{ fontSize:11, fontWeight:700, color:"#4A5568", marginBottom:10 }}>세부약호별 사증 경로</div>
                  {detail.children.filter(c => c.routes.length > 0).map(c => (
                    <div key={c.code} style={{ display:"flex", alignItems:"center", gap:10, padding:"7px 0",
                      borderTop:"1px solid #F7FAFC", flexWrap:"wrap" }}>
                      <button onClick={() => router.push(`/qualifications/${encodeURIComponent(c.code)}`)}
                        style={{ fontSize:12, fontWeight:700, color:"#2D3748", background:"#F7FAFC",
                          border:"1px solid #E2E8F0", borderRadius:8, padding:"3px 9px", cursor:"pointer", flexShrink:0 }}>
                        {c.code}
                      </button>
                      <span style={{ fontSize:12, color:"#4A5568", flexShrink:0 }}>{c.name_ko}</span>
                      {c.routes.map(r => {
                        const tone = routeTone(r);
                        return (
                          <span key={r.route_id} style={{ fontSize:10.5, fontWeight:600, padding:"2px 8px",
                            borderRadius:99, color:tone.color, background:tone.bg, border:`1px solid ${tone.border}` }}>
                            {ROUTE_TYPE_LABEL[r.route_type] ?? r.route_type} · {tone.badge}
                          </span>
                        );
                      })}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* 화면 3: 상세 패널 */}
        {sel && (
          <div style={{ width:400, flexShrink:0, position:"sticky", top:16 }}>
            <DetailPanelV3 sel={sel} v2Rows={detail.v2_rows} onClose={() => setSel(null)} onQuickDoc={goQuickDoc} />
          </div>
        )}
      </div>
    </div>
  );
}
