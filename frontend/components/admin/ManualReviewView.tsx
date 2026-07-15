"use client";
// 관리자 "매뉴얼 검토" 뷰 — admin/page.tsx 에서 분리(표시 개선용).
// 데이터 형태/엔드포인트/운영 반영(apply)·분류 로직은 변경하지 않는다.
import { useState, useEffect, useCallback, useMemo, useRef, Fragment } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { api, manualApi, manualUpdateApi, type ManualUploadResult } from "@/lib/api";
import { Loader2, RotateCcw, ExternalLink, GitMerge } from "lucide-react";
import {
  recommendGroup, summarizeGroup, judgmentPoints, affectedTargets,
  REC_KR, REC_CONF_KR, type RecResult, type RecKind,
} from "./manualReviewRecommend";
import { ApplyToV3Modal } from "@/components/qualifications/editV3";

// 자동 추천(규칙 기반) 배지 색상 (검토완료=green / 보류=yellow / 무시=red)
const REC_STYLE: Record<RecKind, { bg: string; color: string; bd: string }> = {
  approve: { bg: "#C6F6D5", color: "#22543D", bd: "#9AE6B4" },
  hold: { bg: "#FEFCBF", color: "#975A16", bd: "#FAF089" },
  reject: { bg: "#FED7D7", color: "#822727", bd: "#FEB2B2" },
};

export type PgStateResp = {
  source: "pg" | "file";
  state?: {
    status?: string;
    last_run_at?: string | null;
    last_success_at?: string | null;
    last_run_date_kst?: string | null;
    last_checked_version?: string | null;
    last_detected_version?: string | null;
    last_staging_version?: string | null;
    needs_review?: boolean;
    needs_review_stored?: boolean;
    review_reason?: string;
    candidate_count?: number;
    changed_count?: number;
    review_target_count?: number;
    noop_count?: number;
    pending_count?: number;
    reviewed_count?: number;
    applied_count?: number;
    approved_pending_apply?: number;
    error?: string | null;
    updated_at?: string | null;
  };
  baseline?: {
    loaded?: boolean;
    versions?: { manual_label: string; version: string; page_count: number }[];
    refs_count?: number;
    total_pages?: number;
  };
};
type PgVersion = {
  version: string;
  detected_at?: string | null;
  changed_page_count?: number;
  candidate_count?: number;
  status?: string | null;
  label_timestamps?: Record<string, string>;
};
type PgChangedPage = {
  manual_label?: string; change_type?: string;
  baseline_page?: number | null; new_page?: number | null;
  similarity?: number | null; new_snippet?: string; baseline_snippet?: string;
};
type PgCandidate = {
  row_id: string; item_index?: number | null; manual_label?: string;
  old_page_from?: number | null; old_page_to?: number | null;
  candidate_page_from?: number | null; candidate_page_to?: number | null;
  reason?: string; change_type?: string; confidence?: string; action?: string;
  match_text?: string; new_snippet?: string; detailed_code?: string; business_name?: string;
  change_kind?: "new" | "page_moved" | "text_changed" | "uncertain" | "noop";
  needs_review?: boolean; similarity?: number | null; page_changed?: boolean; text_changed?: boolean;
  changed_detail?: { baseline_page?: number; new_page?: number; change_type?: string; similarity?: number | null; baseline_snippet?: string; new_snippet?: string }[];
};
type DiffSeg = { op: "equal" | "insert" | "delete"; text: string };
type PgCandidateDetail = {
  row_id: string; manual_label?: string; change_kind?: string; similarity?: number | null;
  existing: { title?: string; code?: string; page_from?: number | null; page_to?: number | null; manual_ref?: string; match_text?: string; text?: string };
  candidate: { code?: string; page_from?: number | null; page_to?: number | null; staging?: string; text?: string };
  changed_pages: { baseline_page?: number; new_page?: number; change_type?: string; similarity?: number | null; baseline_snippet?: string; new_snippet?: string; diff_segments?: DiffSeg[]; has_text_change?: boolean }[];
};
const CHANGE_KIND: Record<string, { label: string; color: string; bg: string }> = {
  new: { label: "신규", color: "#22543D", bg: "#C6F6D5" },
  page_moved: { label: "페이지 변경", color: "#744210", bg: "#FEEBC8" },
  text_changed: { label: "본문 변경", color: "#822727", bg: "#FED7D7" },
  uncertain: { label: "매칭 불확실", color: "#553C9A", bg: "#E9D8FD" },
  noop: { label: "실질 변경 없음", color: "#4A5568", bg: "#EDF2F7" },
};
// 검토 우선순위: 매칭불확실 > 본문변경 > 페이지변경 > 신규 > noop
const KIND_ORDER: Record<string, number> = { uncertain: 0, text_changed: 1, page_moved: 2, new: 3, noop: 9 };

// 체류자격 자동 그룹(프론트 추정) — detailed_code / 업무명 / 라벨에서 'F-4' 같은 코드를 추출.
// 추정이 불확실하면 "미분류". (분류/운영 로직과 무관한 표시용 그룹)
function stayGroupOf(c: { detailed_code?: string; business_name?: string; manual_label?: string }): string {
  const hay = `${c.detailed_code ?? ""} ${c.business_name ?? ""} ${c.manual_label ?? ""}`.toUpperCase();
  const m = hay.match(/\b([A-Z])-?(\d{1,2})\b/);
  return m ? `${m[1]}-${m[2]}` : "미분류";
}

// 매뉴얼 라벨 → 한글. 알 수 없으면 원문.
const MANUAL_KR: Record<string, string> = { visa: "사증", stay: "체류", revision_history: "개정이력" };
function manualKr(label?: string): string { return MANUAL_KR[label || ""] || (label || "-"); }

// "중요 변경 가능성" FE 추정(운영 판단 아님, 표시용). 신규/불확실/페이지이동/저유사도/체류자격코드.
function isImportantCand(c: { change_kind?: string; page_changed?: boolean; similarity?: number | null; detailed_code?: string; new_snippet?: string; match_text?: string }): boolean {
  const k = c.change_kind;
  if (k === "new" || k === "uncertain") return true;
  if (c.page_changed) return true;
  if (typeof c.similarity === "number" && c.similarity < 0.8) return true;
  return /\b[A-Z]-?\d{1,2}\b/.test(`${c.detailed_code || ""} ${c.new_snippet || c.match_text || ""}`);
}
type PgDecision = {
  row_id: string; decision?: string; decision_note?: string; reviewed?: boolean;
  reviewed_candidate_page?: number | null;
  manual_page_from?: number | null; manual_page_to?: number | null;
  applied?: boolean; source_version?: string | null; previous_version?: string | null;
  orphaned?: boolean; orphaned_at?: string | null;
  needs_recheck?: boolean; candidate_changed?: boolean; updated_at?: string | null;
  reviewer_baseline_from?: number | null; reviewer_baseline_to?: number | null;
  reviewer_candidate_from?: number | null; reviewer_candidate_to?: number | null;
  reviewer_override_reason?: string | null; reviewer_override_by?: string | null;
};
type RecompareResp = { existing_text?: string; candidate_text?: string; candidate_partial?: boolean; diff_segments?: DiffSeg[]; has_text_change?: boolean };
type PdfStatus = {
  manual: string; kr_label?: string; viewer_source: string; viewer_file: string; staging_pdf_exists: boolean;
  deployed: { filename: string; exists: boolean; mtime?: string | null; page_count?: number | null };
  generator_present: boolean; source_hwp_present: boolean; replace_pipeline_wired: boolean;
  can_refresh_now: boolean; reason: string;
  artifacts?: { total?: number; generated?: number; promoted?: number; failed?: number };
  artifacts_total?: number; full_pdf_artifact?: { id: number } | null;
};

const PG_STATUS_KR: Record<string, string> = {
  never_run: "실행 이력 없음",
  no_change: "변경 없음",
  staged: "검토 대기 (staged)",
  running: "실행 중",
  error: "오류",
  pg_disabled: "PG 비활성",
};

// UI 결정 키 → 한글 라벨 (백엔드가 vocabulary 로 매핑)
const DEC_UI_KR: Record<string, string> = {
  approve: "승인", keep_existing: "기존 유지", hold: "보류", reject: "제외", manual_page: "직접입력",
};
// 저장된 decision(vocabulary) → 배지 표시
const DEC_BADGE: Record<string, { label: string; color: string; bg: string }> = {
  "": { label: "미검토", color: "#975A16", bg: "#FEFCBF" },
  NEW_CANDIDATE: { label: "미검토", color: "#975A16", bg: "#FEFCBF" },
  UNRESOLVED: { label: "보류", color: "#744210", bg: "#FAF089" },
  REVIEWED_APPROVE_CANDIDATE: { label: "승인", color: "#22543D", bg: "#C6F6D5" },
  REVIEWED_KEEP_EXISTING: { label: "기존 유지", color: "#2A4365", bg: "#BEE3F8" },
  REJECTED_BAD_CANDIDATE: { label: "제외", color: "#822727", bg: "#FED7D7" },
  NEEDS_MANUAL_PAGE: { label: "직접입력", color: "#22543D", bg: "#C6F6D5" },
  APPLIED: { label: "운영반영됨", color: "#FFFFFF", bg: "#38A169" },
};
const DEC_APPLYABLE = new Set(["REVIEWED_APPROVE_CANDIDATE", "NEEDS_MANUAL_PAGE"]);

// 후보 상세 — 3단 비교(기존 / 차이 / 후보) + 본문 diff + 수동 페이지 지정 + PDF
function CandidateDetailView({ d, version, cand, decision, onOpenPdf, onOpenCandidatePdf, onOverrideChanged }: {
  d: PgCandidateDetail; version: string; cand: PgCandidate; decision?: PgDecision;
  onOpenPdf: (manual: string, page: number) => void;
  onOpenCandidatePdf: (rowId: string, manual: string, fallbackPage: number) => void;
  onOverrideChanged: () => void;
}) {
  const [showFull, setShowFull] = useState(false);
  const [bf, setBf] = useState(String(decision?.reviewer_baseline_from ?? cand.old_page_from ?? ""));
  const [bt, setBt] = useState(String(decision?.reviewer_baseline_to ?? cand.old_page_to ?? ""));
  const [cf, setCf] = useState(String(decision?.reviewer_candidate_from ?? cand.candidate_page_from ?? ""));
  const [ct, setCt] = useState(String(decision?.reviewer_candidate_to ?? cand.candidate_page_to ?? ""));
  const [reason, setReason] = useState(decision?.reviewer_override_reason ?? "");
  const [recmp, setRecmp] = useState<RecompareResp | null>(null);
  const [busy, setBusy] = useState(false);
  const [pageCount, setPageCount] = useState<number | null>(null);
  const [pageCountKnown, setPageCountKnown] = useState(false);
  const hasOverride = decision?.reviewer_baseline_from != null || decision?.reviewer_candidate_from != null;
  const manual = cand.manual_label || d.manual_label || "visa";
  // 매뉴얼 전체 page_count 조회 → 임의 페이지 입력 검증 상한. null 이면 '전체 페이지 수 확인 불가'.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await api.get(`/api/guidelines/manual-update/pdf-source`, { params: { manual, version } });
        if (!alive) return;
        const pc = r.data?.page_count;
        setPageCount(typeof pc === "number" ? pc : null);
        setPageCountKnown(typeof pc === "number");
      } catch { if (alive) { setPageCount(null); setPageCountKnown(false); } }
    })();
    return () => { alive = false; };
  }, [manual, version]);
  const LIMIT = 800;
  const clip = (t?: string) => { const s = t || ""; return (showFull || s.length <= LIMIT) ? s : s.slice(0, LIMIT) + " …"; };
  const err = (e: unknown, fb: string) => (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fb;

  // 표시 텍스트/diff: 재비교 결과가 있으면 그 값을, 없으면 원본 detail 값.
  const existingText = recmp ? (recmp.existing_text ?? "") : (d.existing.text ?? "");
  const candidateText = recmp ? (recmp.candidate_text ?? "") : (d.candidate.text ?? "");
  const col: React.CSSProperties = { flex: 1, minWidth: 220, background: "#fff", border: "1px solid #E2E8F0", borderRadius: 6, padding: 8 };
  const head: React.CSSProperties = { fontSize: 11, fontWeight: 700, marginBottom: 4 };
  const body: React.CSSProperties = { fontSize: 11, color: "#4A5568", whiteSpace: "pre-wrap", wordBreak: "break-word", lineHeight: 1.5, maxHeight: 320, overflow: "auto" };

  const doRecompare = async () => {
    setBusy(true);
    try {
      const r = await api.get(`/api/guidelines/manual-update/recompare`, { params: {
        version, label: manual, baseline_from: Number(bf) || 0, baseline_to: Number(bt) || Number(bf) || 0,
        candidate_from: Number(cf) || 0, candidate_to: Number(ct) || Number(cf) || 0 } });
      setRecmp(r.data as RecompareResp);
      toast.success("재추출·재비교 완료");
    } catch (e) { toast.error(err(e, "재비교 실패")); }
    finally { setBusy(false); }
  };
  // 임의 페이지 입력 검증: 1 이상 정수, from ≤ to, (page_count 알면) page_count 이하.
  // page_count 미확인 시 상한 검증은 생략(서버가 fallback 상한으로 최종 차단).
  const pageErr = (() => {
    const pairs: [string, string, string][] = [[bf, bt, "기준"], [cf, ct, "후보"]];
    for (const [f, t, name] of pairs) {
      const fv = f.trim() === "" ? null : Number(f);
      const tv = t.trim() === "" ? null : Number(t);
      for (const v of [fv, tv]) {
        if (v !== null && (!Number.isInteger(v) || v < 1)) return `${name} 페이지는 1 이상의 정수여야 합니다.`;
        if (v !== null && pageCountKnown && pageCount != null && v > pageCount)
          return `${name} 페이지는 1~${pageCount}(전체 ${pageCount}페이지) 범위를 벗어났습니다.`;
      }
      if (fv !== null && tv !== null && fv > tv) return `${name} 시작 페이지가 끝 페이지보다 큽니다.`;
    }
    return "";
  })();
  const saveOverride = async () => {
    if (pageErr) { toast.error(pageErr); return; }
    if (!reason.trim()) { toast.error("수동 페이지 지정 사유를 입력하세요 (필수)."); return; }
    setBusy(true);
    try {
      await api.post(`/api/guidelines/manual-update/decisions/${encodeURIComponent(cand.row_id)}/override`, {
        baseline_from: Number(bf) || null, baseline_to: Number(bt) || null,
        candidate_from: Number(cf) || null, candidate_to: Number(ct) || null, reason,
        manual, version });   // manual/version → 서버가 page_count 로 상한 검증
      toast.success("관리자 지정 페이지 저장됨");
      onOverrideChanged();
    } catch (e) { toast.error(err(e, "저장 실패")); }
    finally { setBusy(false); }
  };
  const clearOverride = async () => {
    setBusy(true);
    try {
      await api.delete(`/api/guidelines/manual-update/decisions/${encodeURIComponent(cand.row_id)}/override`);
      setBf(String(cand.old_page_from ?? "")); setBt(String(cand.old_page_to ?? ""));
      setCf(String(cand.candidate_page_from ?? "")); setCt(String(cand.candidate_page_to ?? "")); setReason(""); setRecmp(null);
      toast.success("override 초기화됨");
      onOverrideChanged();
    } catch (e) { toast.error(err(e, "초기화 실패")); }
    finally { setBusy(false); }
  };

  const diffSegs = recmp ? (recmp.diff_segments ?? []) : null;

  return (
    <div>
      {/* PDF + 자동/관리자 페이지 요약 바 */}
      <div className="flex items-center gap-2 flex-wrap mb-2 text-[11px]">
        <span style={{ color: "#718096" }}>자동: 기준 {cand.old_page_from}-{cand.old_page_to} / 후보 {cand.candidate_page_from}-{cand.candidate_page_to}</span>
        {hasOverride && <span style={{ color: "#C05621", fontWeight: 700 }}>· 관리자 지정: 기준 {decision?.reviewer_baseline_from}-{decision?.reviewer_baseline_to} / 후보 {decision?.reviewer_candidate_from}-{decision?.reviewer_candidate_to}</span>}
        <span style={{ color: "#CBD5E0" }}>|</span>
        <button onClick={() => onOpenCandidatePdf(cand.row_id, manual, Number(cf) || cand.candidate_page_from || 1)}
          title="변경 반영된 완전한 PDF(전체 문서)를 후보 페이지로 자동 이동해 엽니다 — 앞뒤 스크롤 가능" className="px-2 py-0.5 rounded font-bold" style={{ background: "#C6F6D5", color: "#22543D", border: "1px solid #9AE6B4" }}>변경 반영 완전 PDF (후보 p.{Number(cf) || cand.candidate_page_from || 1})</button>
        <button onClick={() => onOpenPdf(manual, Number(cf) || cand.candidate_page_from || 1)} className="px-2 py-0.5 rounded" style={{ background: "#EBF8FF", color: "#2B6CB0", border: "1px solid #BEE3F8" }}>전체 PDF(후보 페이지)</button>
        <button onClick={() => onOpenPdf(manual, cand.candidate_page_from || 1)} className="px-2 py-0.5 rounded border" style={{ borderColor: "#CBD5E0", color: "#4A5568" }}>후보 페이지 열기</button>
        <button onClick={() => onOpenPdf(manual, cand.old_page_from || 1)} className="px-2 py-0.5 rounded border" style={{ borderColor: "#CBD5E0", color: "#4A5568" }}>기존 페이지 열기</button>
      </div>

      {/* 수동 페이지 지정 — 기존/추천이 모두 틀릴 때 실제 페이지 직접 입력 */}
      <div className="mb-2 p-2 rounded" style={{ background: "#FFFBEB", border: "1px solid #FDE68A" }}>
        <div className="text-[11px] font-bold mb-1" style={{ color: "#92400E" }}>
          ✏️ 수동 페이지 지정
          {hasOverride && <span className="ml-1" style={{ fontSize: 10, padding: "1px 6px", borderRadius: 8, background: "#FBD38D", color: "#7B341E", fontWeight: 700 }}>수동 지정됨</span>}
          {pageCountKnown && pageCount != null
            ? <span style={{ fontWeight: 400, color: "#718096" }}> (전체 {pageCount}페이지 — 1~{pageCount} 입력 가능)</span>
            : <span style={{ fontWeight: 400, color: "#C05621" }}> (전체 페이지 수 확인 불가)</span>}
        </div>
        <div className="text-[11px] mb-2" style={{ color: "#92400E", lineHeight: 1.5 }}>
          자동 매칭된 기존 페이지와 후보 페이지가 틀렸을 때만 수정하세요. 실제 변경이 있는 매뉴얼 페이지 범위를 입력하면 해당 페이지 기준으로 다시 비교합니다. <b>사유는 필수</b>입니다.
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px]" style={{ color: "#718096" }}>기준</span>
          <input type="number" min={1} value={bf} onChange={(e) => setBf(e.target.value)} className="hw-input" style={{ width: 56 }} />
          <span>-</span>
          <input type="number" min={1} value={bt} onChange={(e) => setBt(e.target.value)} className="hw-input" style={{ width: 56 }} />
          <span className="text-[11px]" style={{ color: "#718096" }}>후보</span>
          <input type="number" min={1} value={cf} onChange={(e) => setCf(e.target.value)} className="hw-input" style={{ width: 56 }} />
          <span>-</span>
          <input type="number" min={1} value={ct} onChange={(e) => setCt(e.target.value)} className="hw-input" style={{ width: 56 }} />
          <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="사유 필수 (예: 자동 매칭이 D-8-1로 잡혔으나 실제 변경은 D-7 주재 p.108-109)" className="hw-input" style={{ flex: 1, minWidth: 160 }} />
          <button disabled={busy} onClick={() => void doRecompare()} className="text-[11px] px-2 py-1 rounded" style={{ background: "#2B6CB0", color: "#fff", border: "none" }}>다시 비교</button>
          <button disabled={busy || !!pageErr || !reason.trim()} onClick={() => void saveOverride()} title={pageErr || (!reason.trim() ? "사유를 입력하세요 (필수)" : "관리자 지정 페이지 저장")} className="text-[11px] px-2 py-1 rounded disabled:opacity-50" style={{ background: "#DD6B20", color: "#fff", border: "none" }}>페이지 저장</button>
          <button disabled={busy} onClick={() => void clearOverride()} className="text-[11px] px-2 py-1 rounded border" style={{ borderColor: "#CBD5E0", color: "#718096", background: "#fff" }}>초기화</button>
        </div>
        {pageErr && <div className="text-[10px] mt-1" style={{ color: "#C53030" }}>⚠ {pageErr}</div>}
      </div>
      {recmp?.candidate_partial && <div className="text-[10px] mb-2" style={{ color: "#C05621" }}>※ 후보(신규) 본문은 변경 페이지 스니펫 기반입니다(전체 본문 미보유) — 정확한 페이지는 PDF로 확인하세요.</div>}

      <div className="flex gap-2 flex-wrap" style={{ alignItems: "stretch" }}>
        {/* 왼쪽: 기존 */}
        <div style={col}>
          <div style={{ ...head, color: "#2A4365" }}>기존 기준 항목{recmp ? " (재추출)" : ""}</div>
          <div style={{ fontSize: 11, color: "#718096" }}>제목: {d.existing.title || "-"}</div>
          <div style={{ fontSize: 11, color: "#718096" }}>코드: {d.existing.code || "-"} · manual_ref {d.existing.manual_ref}</div>
          {d.existing.match_text && <div style={{ fontSize: 10, color: "#A0AEC0", marginTop: 2 }}>match_text: {d.existing.match_text}</div>}
          <div style={{ ...body, marginTop: 6 }}>{clip(existingText) || <span style={{ color: "#CBD5E0" }}>(추출 텍스트 없음)</span>}</div>
        </div>
        {/* 가운데: 차이 */}
        <div style={{ ...col, maxWidth: 360 }}>
          <div style={{ ...head, color: "#822727" }}>차이{recmp ? " (재계산)" : ""}</div>
          <div style={body}>
            {diffSegs ? (
              diffSegs.length === 0 ? <span style={{ color: "#276749" }}>실질 변경 없음</span> :
              diffSegs.map((seg, j) => (
                <span key={j} style={{ background: seg.op === "insert" ? "#C6F6D5" : seg.op === "delete" ? "#FED7D7" : "transparent", color: seg.op === "delete" ? "#822727" : seg.op === "insert" ? "#22543D" : "#4A5568", textDecoration: seg.op === "delete" ? "line-through" : "none" }}>{seg.text}</span>
              ))
            ) : (
              <>
                {(d.changed_pages || []).map((cp, i) => (
                  <div key={i} style={{ marginBottom: 6 }}>
                    <div style={{ color: "#A0AEC0", fontSize: 10 }}>p.{cp.baseline_page}→{cp.new_page} ({cp.change_type}{cp.similarity != null ? `, ${Math.round(cp.similarity * 100)}%` : ""})</div>
                    <div>{(cp.diff_segments || []).map((seg, j) => (
                      <span key={j} style={{ background: seg.op === "insert" ? "#C6F6D5" : seg.op === "delete" ? "#FED7D7" : "transparent", color: seg.op === "delete" ? "#822727" : seg.op === "insert" ? "#22543D" : "#4A5568", textDecoration: seg.op === "delete" ? "line-through" : "none" }}>{seg.text}</span>
                    ))}</div>
                  </div>
                ))}
                {(d.changed_pages || []).length === 0 && <span style={{ color: "#CBD5E0" }}>(변경 페이지 정보 없음)</span>}
              </>
            )}
          </div>
        </div>
        {/* 오른쪽: 후보 */}
        <div style={col}>
          <div style={{ ...head, color: "#22543D" }}>후보 항목 (staging){recmp ? " (재추출)" : ""}</div>
          <div style={{ fontSize: 11, color: "#718096" }}>코드: {d.candidate.code || "-"} · staging {d.candidate.staging}</div>
          <div style={{ ...body, marginTop: 6 }}>{clip(candidateText) || <span style={{ color: "#CBD5E0" }}>(추출 텍스트 없음 — PDF로 확인)</span>}</div>
        </div>
      </div>
      {((existingText || "").length > LIMIT || (candidateText || "").length > LIMIT) && (
        <button onClick={() => setShowFull((v) => !v)} className="text-[11px] mt-2 px-2 py-0.5 rounded border" style={{ borderColor: "#CBD5E0", color: "#2B6CB0", background: "#fff" }}>
          {showFull ? "접기" : "전체 보기"}
        </button>
      )}
    </div>
  );
}

// ── 상태 요약 카드 (색상 의미: blue 진행/검토 · green 완료 · yellow 대기/주의 · red 실패 · gray 정보) ──
const _TONE: Record<string, { bg: string; bd: string; fg: string }> = {
  blue: { bg: "#EBF8FF", bd: "#BEE3F8", fg: "#2B6CB0" },
  green: { bg: "#F0FFF4", bd: "#C6F6D5", fg: "#276749" },
  yellow: { bg: "#FFFAF0", bd: "#FEEBC8", fg: "#C05621" },
  red: { bg: "#FFF5F5", bd: "#FED7D7", fg: "#C53030" },
  gray: { bg: "#F7FAFC", bd: "#E2E8F0", fg: "#718096" },
};

function StatusSummaryCards({ cards }: { cards: { label: string; value: string; tone: string }[] }) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {cards.map((c) => {
        const t = _TONE[c.tone] ?? _TONE.gray;
        return (
          <div key={c.label} className="rounded-lg p-3" style={{ background: t.bg, border: `1px solid ${t.bd}` }}>
            <div className="text-[11px]" style={{ color: "#718096" }}>{c.label}</div>
            <div className="text-sm font-bold mt-1" style={{ color: t.fg }}>{c.value}</div>
          </div>
        );
      })}
    </div>
  );
}

// ── 매뉴얼 업데이트 알림(첨부 제목 변동) 보조 카드 — 화면 하단/사이드 ──────────
function ManualAlertAdminCard() {
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<string>("");
  const run = async () => {
    setBusy(true);
    try {
      const r = await manualApi.runAlertDetect();
      const created = r.data.created ?? 0;
      setLast(created > 0 ? `제목 변경 ${created}건 감지 — 전 사용자에게 로그인 알림 표시` : "변경 없음(이미 최신)");
      toast.success(created > 0 ? `제목 변경 ${created}건 감지됨` : "제목 변경 없음");
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setLast(`실패 — ${detail || "감지 오류"}`);
      toast.error(detail || "제목 감지 실패");
    } finally { setBusy(false); }
  };
  return (
    <details className="hw-card" style={{ background: "#FBFCFE" }}>
      <summary className="text-xs font-semibold cursor-pointer" style={{ color: "#718096" }}>🔔 매뉴얼 업데이트 알림 (보조)</summary>
      <div className="mt-2 text-[11px]" style={{ color: "#718096", lineHeight: 1.7 }}>
        하이코리아 첨부파일 <b>제목 변동</b>을 감지하면 전 사용자가 다음 로그인 시 알림을 봅니다(1일 1회 자동 감시).
        Cron 미설정 시 아래 버튼으로 수동 감지할 수 있습니다.
        <div className="mt-2 flex items-center gap-2 flex-wrap">
          <button type="button" onClick={() => void run()} disabled={busy}
            className="px-2.5 py-1 rounded font-bold" style={{ background: "#2B6CB0", color: "#fff", border: "none", opacity: busy ? 0.6 : 1 }}>
            {busy ? "감지 중..." : "제목 변경 감지 실행"}
          </button>
          {last && <span style={{ color: "#4A5568" }}>{last}</span>}
        </div>
      </div>
    </details>
  );
}

// ── 관리자 최신 PDF 업로드 카드 (web 합성/렌더 없이 저장+텍스트추출+비교) ──────────
const _UPLOAD_MANUALS = [
  { k: "visa", kr: "사증민원" },
  { k: "stay", kr: "체류민원" },
  { k: "revision_history", kr: "revision_history" },
];

function ManualPdfUploadCard({ token, onReload }: { token: string; onReload?: () => void }) {
  const [manual, setManual] = useState("stay");
  const [version, setVersion] = useState("");
  const [memo, setMemo] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ManualUploadResult | null>(null);
  const [detect, setDetect] = useState<{ status: string; changed?: number; candidates?: number; message?: string } | null>(null);
  const [detectErr, setDetectErr] = useState<string>("");
  const [viewer, setViewer] = useState<{ manual: string; version: string; kr: string } | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const doUpload = async () => {
    if (!file) { toast.error("PDF 파일을 선택하세요."); return; }
    if (!version.trim()) { toast.error("버전을 입력하세요 (예: 260616)."); return; }
    setBusy(true); setResult(null); setDetect(null); setDetectErr("");
    try {
      const r = await manualUpdateApi.uploadPdf(manual, version.trim(), file, memo);
      setResult(r.data);
      toast.success("PDF 업로드됨 (저장 완료) · 변경감지는 별도 실행");
      onReload?.();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "업로드 실패");
    } finally { setBusy(false); }
  };

  const runDetect = async () => {
    if (!result) return;
    setBusy(true); setDetectErr("");
    try {
      const r = await manualUpdateApi.detectChanges(result.manual, result.version);
      setDetect(r.data);
      toast.success(r.data.status === "ok"
        ? `변경감지 완료 · 변경 ${r.data.changed} · 후보 ${r.data.candidates}건`
        : (r.data.message || "변경감지 완료"));
      onReload?.();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setDetectErr(detail || "변경감지 실패");
      toast.error(detail || "변경감지 실패 — 업로드 PDF는 유지됩니다.");
    } finally { setBusy(false); }
  };

  const promote = async () => {
    if (!result) return;
    if (!window.confirm(`${result.manual_kr} ${result.version} 을(를) 운영 PDF로 반영(승격)할까요?\n기존 운영 PDF는 previous로 보존됩니다.`)) return;
    setBusy(true);
    try {
      await manualUpdateApi.promotePdf(result.manual, result.version);
      toast.success("운영 반영(승격) 완료 — 다음 업로드부터 이 PDF가 비교 기준이 됩니다.");
      onReload?.();
    } catch (e) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "승격 실패");
    } finally { setBusy(false); }
  };

  return (
    <div className="hw-card">
      <div className="text-xs font-semibold mb-2" style={{ color: "#2D3748" }}>📤 최신 PDF 업로드 (저장 우선 → 변경감지 별도 실행)</div>
      <div className="text-[11px] mb-2" style={{ color: "#718096", lineHeight: 1.6 }}>
        업로드 시 서버는 <b>저장만</b> 합니다(전체 PDF 합성/스플라이스/렌더 없음 → 메모리 안전). 텍스트 추출·변경 감지는 <b>“변경감지 실행”</b> 버튼으로 분리되어 있습니다.
        업로드본은 <b>운영 미반영(검토용)</b>이며, 검토 후 <b>운영 반영(승격)</b> 시 적용됩니다.
      </div>

      {/* 빠른 선택 버튼 */}
      <div className="flex items-center gap-2 flex-wrap mb-2">
        {_UPLOAD_MANUALS.map((m) => (
          <button key={m.k} type="button" onClick={() => { setManual(m.k); fileRef.current?.click(); }}
            className="text-[11px] px-2.5 py-1 rounded" style={{ border: "1px solid #CBD5E0", background: manual === m.k ? "#FFF9E6" : "#fff", color: "#4A5568" }}>
            {m.kr} 최신 PDF 업로드
          </button>
        ))}
      </div>

      {/* 폼 */}
      <div className="flex items-center gap-2 flex-wrap mb-2">
        <select className="hw-input text-xs" value={manual} onChange={(e) => setManual(e.target.value)} style={{ minWidth: 130 }}>
          {_UPLOAD_MANUALS.map((m) => <option key={m.k} value={m.k}>{m.kr}</option>)}
        </select>
        <input className="hw-input text-xs" placeholder="버전 예: 260616" value={version}
          onChange={(e) => setVersion(e.target.value)} style={{ width: 120 }} />
        <input ref={fileRef} type="file" accept="application/pdf,.pdf" className="text-xs"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <input className="hw-input text-xs" placeholder="메모(선택)" value={memo}
          onChange={(e) => setMemo(e.target.value)} style={{ width: 160 }} />
        <button type="button" onClick={() => void doUpload()} disabled={busy}
          className="text-xs px-3 py-1.5 rounded font-bold" style={{ background: "#2F855A", color: "#fff", border: "none", opacity: busy ? 0.6 : 1 }}>
          {busy ? "처리 중..." : "업로드"}
        </button>
      </div>
      {file && <div className="text-[11px] mb-1" style={{ color: "#718096" }}>선택됨: {file.name} ({Math.round(file.size / 1024)}KB)</div>}

      {/* 업로드 결과/상태 */}
      {result && (
        <div className="text-[11px] mt-2 p-2 rounded" style={{ background: "#F0FFF4", border: "1px solid #C6F6D5", color: "#22543D", lineHeight: 1.9 }}>
          <div><b>✔ 검토용 업로드 PDF</b> · <span style={{ color: "#C05621" }}>운영 미반영</span> · {result.manual_kr} {result.version}</div>
          <div>페이지 수: {result.page_count} · 파일 {Math.round(result.file_size / 1024)}KB{result.prior_uploads_removed ? ` · 이전 업로드본 ${result.prior_uploads_removed}건 정리됨` : ""}</div>
          <div>
            {detectErr
              ? <span style={{ color: "#C53030" }}>⚠ 변경감지 실패 — {detectErr} (업로드 PDF는 유지됨, viewer 사용 가능)</span>
              : detect
                ? (detect.status === "ok"
                    ? <span style={{ color: "#22543D" }}>✔ 변경감지 완료 · 변경 페이지 {detect.changed} · 후보 {detect.candidates}건</span>
                    : <span style={{ color: "#718096" }}>{detect.message || "변경감지 완료"}</span>)
              : <span style={{ color: "#C05621" }}>PDF 업로드됨 · 변경감지 대기 (아래 “변경감지 실행”)</span>}
          </div>
          <div className="text-[10px]" style={{ color: "#A0AEC0" }}>
            ℹ PDF 기준 변경 감지 — 후보 매칭은 기준 DB(manual_base_refs) 품질에 따라 제한될 수 있습니다.
          </div>
          <div className="flex items-center gap-2 flex-wrap mt-1">
            {result.supports_change_detection && (
              <button type="button" onClick={() => void runDetect()} disabled={busy}
                className="px-2 py-0.5 rounded font-bold" style={{ background: "#2B6CB0", color: "#fff", border: "none", opacity: busy ? 0.6 : 1 }}>
                {busy ? "변경감지 중..." : "변경감지 실행"}
              </button>
            )}
            <button type="button" onClick={() => setViewer({ manual: result.manual, version: result.version, kr: result.manual_kr })}
              className="px-2 py-0.5 rounded" style={{ border: "1px solid #CBD5E0", background: "#fff", color: "#2B6CB0" }}>
              검토 PDF 열기(전체)
            </button>
            <button type="button" onClick={() => void promote()} disabled={busy}
              className="px-2 py-0.5 rounded font-bold" style={{ background: "#DD6B20", color: "#fff", border: "none" }}>
              운영 반영(승격)
            </button>
          </div>
        </div>
      )}

      {/* 검토용 PDF 뷰어 (운영 미반영 배너) */}
      {viewer && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1100, display: "flex", flexDirection: "column", padding: 20 }}>
          <div className="hw-card" style={{ flex: 1, display: "flex", flexDirection: "column", background: "#fff", overflow: "hidden" }}>
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
              <div className="text-sm font-bold" style={{ color: "#C05621" }}>
                검토용 PDF / 운영 미반영 — {viewer.kr} · {viewer.version}
              </div>
              <button type="button" onClick={() => setViewer(null)} className="text-xs px-2 py-1 rounded" style={{ border: "1px solid #E2E8F0", background: "#fff" }}>닫기</button>
            </div>
            <iframe title="staging-pdf" style={{ flex: 1, border: "1px solid #E2E8F0", borderRadius: 6 }}
              src={`/api/guidelines/manual-update/uploaded-pdf?manual=${encodeURIComponent(viewer.manual)}&version=${encodeURIComponent(viewer.version)}&token=${encodeURIComponent(token)}#toolbar=1&view=Fit`} />
          </div>
        </div>
      )}
    </div>
  );
}

export function ManualUpdatePgView({ state }: { state: PgStateResp | null }) {
  const router = useRouter();
  const [applyV3Cand, setApplyV3Cand] = useState<{
    code?: string | null; title: string; rowId?: string;
    existingText?: string; candidateText?: string; reason?: string;
  } | null>(null);
  const [versions, setVersions] = useState<PgVersion[]>([]);
  const [version, setVersion] = useState<string>("");
  const [changed, setChanged] = useState<PgChangedPage[]>([]);
  const [candidates, setCandidates] = useState<PgCandidate[]>([]);
  const [decisions, setDecisions] = useState<PgDecision[]>([]);
  const [loading, setLoading] = useState(false);
  // 상태 카드는 결정/반영 후 다시 갱신해야 하므로 prop(state)을 로컬로 복제해 둔다.
  const [liveState, setLiveState] = useState<PgStateResp | null>(state);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);              // 진행 중 row_id 또는 "bulk"
  const [applyModal, setApplyModal] = useState<{ rowId: string; pf: string; pt: string } | null>(null);
  const [filter, setFilter] = useState<string>("review");             // 기본: 미검토 + 실질 변경 있음
  const [stayFilter, setStayFilter] = useState<string>("");           // 체류자격 그룹 필터(빈값=전체)
  const [expanded, setExpanded] = useState<string | null>(null);      // 펼친 후보 row_id
  const [detailCache, setDetailCache] = useState<Record<string, PgCandidateDetail>>({});
  const [detailLoading, setDetailLoading] = useState<string | null>(null);
  const [bulkApply, setBulkApply] = useState(false);                  // 운영 반영 요약 모달
  const [helpOpen, setHelpOpen] = useState(false);                    // "검토완료/보류/무시 차이 보기" 도움말
  const [bulkConfirm, setBulkConfirm] = useState<{ ui: "approve" | "hold" | "reject"; rowIds: string[]; hasImportant: boolean } | null>(null);  // 일괄 처리 확인 모달
  const [showAdvCols, setShowAdvCols] = useState(false);              // 후보 표 고급 컬럼(신뢰도/매칭사유/row_id) 표시
  const [mainTab, setMainTab] = useState<"unreviewed" | "important" | "done" | "advanced">("unreviewed");
  const [visibleCount, setVisibleCount] = useState(20);               // 페이지 그룹 표시 제한(더 보기)
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());  // 펼친 페이지 그룹 key
  useEffect(() => { setVisibleCount(20); setSelected(new Set()); }, [mainTab, stayFilter]);   // 탭/필터 변경 시 표시수·선택 초기화
  const [pdfView, setPdfView] = useState<{ manual?: string; page: number; isStaging?: boolean; artifactId?: number; label?: string; reviewOnly?: boolean; source?: string } | null>(null);
  const [pdfStatus, setPdfStatus] = useState<Record<string, PdfStatus>>({});
  const [runCap, setRunCap] = useState<{ can_diagnose?: boolean; can_record_update?: boolean; can_generate_pdf?: boolean; node_available?: boolean; extract_mjs_exists?: boolean; rhwp_available?: boolean; chromium_pkg_present?: boolean; chromium_available?: boolean; chromium_path?: string; is_worker?: boolean; runtime?: string; reason?: string; pdf_reason?: string } | null>(null);
  const [runBusy, setRunBusy] = useState<"diagnose" | "record" | "generate_pdf_artifacts" | null>(null);
  const [runResult, setRunResult] = useState<{ mode?: string; result?: { status?: string; version?: string; source_deleted?: boolean; wrote_to_pg?: boolean; stages?: Record<string, unknown>; error?: string; error_stage?: string } } | null>(null);
  // row_id → artifact id (해당 후보에 생성된 변경 페이지 PDF artifact). note "candidate <row_id>" 로 매칭.
  const [artifactByRow, setArtifactByRow] = useState<Record<string, number>>({});

  const token = (typeof window !== "undefined" ? localStorage.getItem("access_token") || "" : "");
  // PDF 열기: staging 있으면 staging, 없으면 배포본 (백엔드가 자동 선택). 배너용으로 source 조회.
  const openPdf = useCallback(async (manual: string, page: number) => {
    let isStaging = false; let reviewOnly = false; let src = "deployed";
    try {
      const r = await api.get(`/api/guidelines/manual-update/pdf-source`, { params: { manual, version } });
      isStaging = !!r.data?.is_staging;
      reviewOnly = !!r.data?.review_only;
      src = String(r.data?.source || "deployed");
    } catch { /* 기본 deployed */ }
    setPdfView({ manual, page: page || 1, isStaging, reviewOnly, source: src });
  }, [version]);

  // 후보 상세: '변경 반영된 완전한 PDF'(전체 문서)를 후보 페이지로 자동 이동해 연다.
  // (변경 페이지만 있는 bundle 이 아니라 전체 문서 → 앞뒤 스크롤 가능. 백엔드가 변경 페이지를
  //  배포본에 스플라이스해 합성한다.)
  const openCandidatePdf = useCallback(async (rowId: string, manual: string, fallbackPage: number) => {
    try {
      const r = await api.get(`/api/guidelines/manual-update/versions/${encodeURIComponent(version)}/candidates/${encodeURIComponent(rowId)}/pdf-artifact`);
      const page = Number(r.data?.page) || fallbackPage || 1;
      const m = (r.data?.manual as string) || manual;
      void openPdf(m, page);
      return;
    } catch { toast.message("후보 PDF 조회 실패 — 배포본 PDF로 엽니다."); }
    void openPdf(manual, fallbackPage);
  }, [version, openPdf]);

  const loadCapability = useCallback(async () => {
    try {
      const r = await api.get(`/api/guidelines/manual-update/capabilities`);
      setRunCap(r.data);
    } catch { /* skip */ }
  }, []);
  useEffect(() => { void loadCapability(); }, [loadCapability]);

  // 관리자 수동 실행: diagnose(진단, PG 미기록) | record(실제 기록, capability 통과 시).
  const runNow = useCallback(async (mode: "diagnose" | "record" | "generate_pdf_artifacts") => {
    if (mode === "record" && !window.confirm("실제 업데이트를 실행합니다(PG staging 기록). 계속할까요?")) return;
    if (mode === "generate_pdf_artifacts" && !window.confirm("변경 페이지 PDF artifact를 생성합니다(node+chromium 필요). 계속할까요?")) return;
    setRunBusy(mode); setRunResult(null);
    try {
      const r = await api.post(`/api/guidelines/manual-update/run-now`, { mode });
      setRunResult(r.data);
      toast.success(`${mode === "diagnose" ? "진단" : "실제"} 실행 완료: ${r.data?.result?.status}`);
      void loadCapability();
    } catch (e) {
      const det = (e as { response?: { status?: number } })?.response;
      if (det?.status === 409) toast.error("실행 차단(409): 이미 실행 중이거나 실행 불가 환경입니다.");
      else toast.error("실행 실패");
    } finally { setRunBusy(null); }
  }, [loadCapability]);

  const reloadState = useCallback(async () => {
    try {
      const r = await api.get("/api/guidelines/manual-update/state");
      setLiveState(r.data as PgStateResp);
    } catch { /* 상태 갱신 실패는 치명적이지 않음 */ }
  }, []);

  const loadTop = useCallback(async () => {
    try {
      const [vr, dr] = await Promise.all([
        api.get("/api/guidelines/manual-update/versions"),
        api.get("/api/guidelines/manual-update/decisions/active"),
      ]);
      const vs = (vr.data?.versions ?? []) as PgVersion[];
      setVersions(vs);
      setDecisions((dr.data?.rows ?? []) as PgDecision[]);
      if (vs.length) setVersion((cur) => cur || vs[0].version);
      void reloadState();
    } catch { toast.error("PG manual update 자료를 불러오지 못했습니다."); }
  }, [reloadState]);

  useEffect(() => { void loadTop(); }, [loadTop]);

  // 결정만 다시 불러오기(후보/버전 재조회 없이 빠르게).
  const reloadDecisions = useCallback(async () => {
    try {
      const dr = await api.get("/api/guidelines/manual-update/decisions/active");
      setDecisions((dr.data?.rows ?? []) as PgDecision[]);
    } catch { /* ignore */ }
    void reloadState();
  }, [reloadState]);

  const errText = (e: unknown, fb: string) =>
    (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fb;

  // 단일 결정 저장(승인/기존유지/보류/제외). 승인 시 후보 페이지는 백엔드가 자동 채움.
  const setDecision = useCallback(async (c: PgCandidate, ui: string) => {
    setBusy(c.row_id);
    try {
      await api.post(`/api/guidelines/manual-update/decisions/${encodeURIComponent(c.row_id)}`, {
        decision: ui,
        candidate_page_from: c.candidate_page_from ?? undefined,
        candidate_page_to: c.candidate_page_to ?? undefined,
      });
      toast.success(`결정 저장: ${DEC_UI_KR[ui] ?? ui}`);
      await reloadDecisions();
    } catch (e) { toast.error(errText(e, "결정 저장 실패")); }
    finally { setBusy(null); }
  }, [reloadDecisions]);

  // 일괄 결정(선택 또는 전체).
  const bulkDecision = useCallback(async (ui: string, rowIds: string[]) => {
    if (rowIds.length === 0) { toast.message("선택된 후보가 없습니다."); return; }
    setBusy("bulk");
    try {
      const r = await api.post("/api/guidelines/manual-update/decisions/bulk", { row_ids: rowIds, decision: ui });
      const requested = rowIds.length;
      const processed = Number(r.data?.count ?? requested);
      const label = DEC_UI_KR[ui] ?? ui;
      if (processed < requested) {
        toast.error(`${requested}개 중 ${processed}개만 ${label} 처리되었습니다. (실패 ${requested - processed}개)`);
      } else {
        toast.success(`${requested}개 항목을 ${label} 처리했습니다.`);
      }
      setSelected(new Set());
      await reloadDecisions();   // 서버 재조회 우선 — 미검토/반영가능 판단은 최신 서버 상태 기준
    } catch (e) { toast.error(errText(e, "일괄 처리 실패")); }
    finally { setBusy(null); }
  }, [reloadDecisions]);

  // 운영 반영(확인 모달에서 호출).
  const doApply = useCallback(async () => {
    if (!applyModal) return;
    const pf = parseInt(applyModal.pf, 10);
    const pt = parseInt(applyModal.pt, 10) || pf;
    if (!(pf >= 1)) { toast.error("page_from은 1 이상이어야 합니다."); return; }
    setBusy(applyModal.rowId);
    try {
      const r = await api.post(`/api/guidelines/manual-update/decisions/${encodeURIComponent(applyModal.rowId)}/apply`, { page_from: pf, page_to: pt });
      toast.success(`운영 반영 완료 (백업: ${r.data?.backup ?? "-"})`);
      setApplyModal(null);
      await reloadDecisions();
    } catch (e) { toast.error(errText(e, "운영 반영 실패")); }
    finally { setBusy(null); }
  }, [applyModal, reloadDecisions]);

  // 행 펼침 → 상세(3단 비교) 로드(캐시).
  const toggleExpand = useCallback(async (c: PgCandidate) => {
    if (expanded === c.row_id) { setExpanded(null); return; }
    setExpanded(c.row_id);
    if (detailCache[c.row_id] || !version) return;
    setDetailLoading(c.row_id);
    try {
      const r = await api.get(`/api/guidelines/manual-update/versions/${encodeURIComponent(version)}/candidates/${encodeURIComponent(c.row_id)}/detail`);
      setDetailCache((prev) => ({ ...prev, [c.row_id]: r.data as PgCandidateDetail }));
    } catch (e) { toast.error(errText(e, "상세를 불러오지 못했습니다.")); }
    finally { setDetailLoading(null); }
  }, [expanded, detailCache, version]);

  // 그룹 상세 — 펼칠 때만 각 후보 상세를 lazy 로딩(접힌 그룹은 상세 DOM 미생성).
  const ensureDetail = useCallback(async (c: PgCandidate) => {
    if (detailCache[c.row_id] || !version) return;
    setDetailLoading(c.row_id);
    try {
      const r = await api.get(`/api/guidelines/manual-update/versions/${encodeURIComponent(version)}/candidates/${encodeURIComponent(c.row_id)}/detail`);
      setDetailCache((prev) => ({ ...prev, [c.row_id]: r.data as PgCandidateDetail }));
    } catch (e) { toast.error(errText(e, "상세를 불러오지 못했습니다.")); }
    finally { setDetailLoading(null); }
  }, [detailCache, version]);
  const toggleGroup = useCallback((key: string, cands: PgCandidate[]) => {
    setExpandedGroups((prev) => {
      const n = new Set(prev);
      if (n.has(key)) n.delete(key);
      else { n.add(key); cands.forEach((c) => void ensureDetail(c)); }
      return n;
    });
  }, [ensureDetail]);

  // 운영 반영 일괄: 승인(approve/manual_page)했으나 아직 미반영인 후보 전부 반영.
  const doBulkApply = useCallback(async () => {
    const dmap: Record<string, PgDecision> = {};
    for (const d of decisions) dmap[d.row_id] = d;
    const targets = candidates.filter((c) => {
      const d = dmap[c.row_id];
      return d && !d.applied && DEC_APPLYABLE.has(d.decision ?? "");
    });
    if (targets.length === 0) { toast.message("운영 반영할 승인 항목이 없습니다."); setBulkApply(false); return; }
    setBusy("bulk");
    let ok = 0;
    for (const c of targets) {
      const dd = dmap[c.row_id];
      // 관리자 지정(override)이 있으면 그 페이지로 반영, 없으면 자동 후보 페이지.
      const pf = dd?.reviewer_candidate_from ?? c.candidate_page_from ?? 1;
      const pt = dd?.reviewer_candidate_to ?? c.candidate_page_to ?? pf;
      try {
        await api.post(`/api/guidelines/manual-update/decisions/${encodeURIComponent(c.row_id)}/apply`, {
          page_from: pf, page_to: pt,
        });
        ok += 1;
      } catch { /* 개별 실패는 계속 */ }
    }
    toast.success(`운영 반영 ${ok}/${targets.length}건 완료`);
    setBulkApply(false); setBusy(null);
    await reloadDecisions();
  }, [candidates, decisions, reloadDecisions]);

  const loadVersion = useCallback(async (v: string) => {
    if (!v) return;
    setLoading(true); setChanged([]); setCandidates([]); setExpanded(null); setDetailCache({});
    try {
      const [ch, ca] = await Promise.all([
        api.get(`/api/guidelines/manual-update/versions/${encodeURIComponent(v)}/changed-pages`),
        api.get(`/api/guidelines/manual-update/versions/${encodeURIComponent(v)}/candidates`),
      ]);
      setChanged((ch.data?.rows ?? []) as PgChangedPage[]);
      setCandidates((ca.data?.rows ?? []) as PgCandidate[]);
    } catch { toast.error("버전 자료를 불러오지 못했습니다."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (version) void loadVersion(version); }, [version, loadVersion]);

  // 후보별 PDF artifact 매핑(version 단위) — note "candidate <row_id>" 파싱.
  useEffect(() => {
    if (!version) { setArtifactByRow({}); return; }
    (async () => {
      try {
        const r = await api.get(`/api/guidelines/manual-update/pdf-artifacts`, { params: { version } });
        const map: Record<string, number> = {};
        for (const a of (r.data?.rows ?? []) as { id: number; note?: string }[]) {
          const m = /candidate\s+(\S+)/.exec(a.note || "");
          if (m) map[m[1]] = a.id;
        }
        setArtifactByRow(map);
      } catch { setArtifactByRow({}); }
    })();
  }, [version, runResult]);

  // PDF 최신화 진단(visa/stay) — 뷰어가 여는 파일/소스/파이프라인 연결 상태.
  useEffect(() => {
    (async () => {
      const out: Record<string, PdfStatus> = {};
      for (const m of ["visa", "stay"]) {
        try {
          const r = await api.get(`/api/guidelines/manual-update/pdf-status`, { params: { manual: m, version } });
          out[m] = r.data as PdfStatus;
        } catch { /* skip */ }
      }
      setPdfStatus(out);
    })();
  }, [version]);

  const s = liveState?.state ?? {};
  const bl = liveState?.baseline ?? {};
  const blVersions = bl.versions ?? [];
  // row_id → 저장된 decision (후보 행에 현재 결정/배지/반영버튼 표시)
  const decByRow: Record<string, PgDecision> = {};
  for (const d of decisions) decByRow[d.row_id] = d;

  // 필터 + 정렬 + 코드 그룹핑
  const matchFilter = (c: PgCandidate): boolean => {
    const dec = decByRow[c.row_id]?.decision ?? "";
    const kind = c.change_kind ?? "text_changed";
    const decided = dec && dec !== "NEW_CANDIDATE";
    switch (filter) {
      case "all": return true;
      case "review": return c.needs_review !== false && !decided;   // 미검토 + 실질 변경 있음 (기본)
      case "unreviewed": return !decided;
      case "page_moved": return kind === "page_moved";
      case "text_changed": return kind === "text_changed";
      case "uncertain": return kind === "uncertain";
      case "new": return kind === "new";
      case "noop": return c.needs_review === false;
      case "has_pdf": return !!artifactByRow[c.row_id];
      case "approve": return dec === "REVIEWED_APPROVE_CANDIDATE";
      case "keep_existing": return dec === "REVIEWED_KEEP_EXISTING";
      case "hold": return dec === "UNRESOLVED";
      case "reject": return dec === "REJECTED_BAD_CANDIDATE";
      default: return true;
    }
  };
  const filteredCands = candidates
    .filter(matchFilter)
    .filter((c) => !stayFilter || stayGroupOf(c) === stayFilter)
    .sort((a, b) => {
      const ka = KIND_ORDER[a.change_kind ?? "text_changed"] ?? 5;
      const kb = KIND_ORDER[b.change_kind ?? "text_changed"] ?? 5;
      if (ka !== kb) return ka - kb;
      const ga = (a.detailed_code || a.row_id), gb = (b.detailed_code || b.row_id);
      return ga.localeCompare(gb);   // 같은 코드/업무명 묶음
    });
  // 체류자격 그룹별 카운트(미검토 기준) — 체류자격별 탭 칩에 표시.
  const stayGroups = (() => {
    const map = new Map<string, number>();
    for (const c of candidates) {
      const dec = decByRow[c.row_id]?.decision ?? "";
      const decided = dec && dec !== "NEW_CANDIDATE";
      if (c.needs_review === false || decided) continue;   // 미검토+실질변경만 집계
      const g = stayGroupOf(c);
      map.set(g, (map.get(g) ?? 0) + 1);
    }
    return Array.from(map.entries()).sort((a, b) => {
      if (a[0] === "미분류") return 1;
      if (b[0] === "미분류") return -1;
      return a[0].localeCompare(b[0]);
    });
  })();
  // 페이지 단위 그룹핑(manual_label + 기존페이지 + 신규페이지 + change_kind). no-op 은 기본 제외(고급에서만).
  type PageGroup = {
    key: string; manual_label?: string; old_from?: number | null; old_to?: number | null;
    new_from?: number | null; new_to?: number | null; change_kind: string;
    cands: PgCandidate[]; rowIds: string[]; important: boolean; summary: string; pending: boolean;
  };
  const pageGroups: PageGroup[] = useMemo(() => {
    const map = new Map<string, PageGroup>();
    for (const c of candidates) {
      if (c.needs_review === false) continue;                      // no-op → 고급 탭에서만
      if (stayFilter && stayGroupOf(c) !== stayFilter) continue;
      const key = `${c.manual_label}|${c.old_page_from}|${c.candidate_page_from}|${c.change_kind}`;
      let g = map.get(key);
      if (!g) {
        g = { key, manual_label: c.manual_label, old_from: c.old_page_from, old_to: c.old_page_to,
              new_from: c.candidate_page_from, new_to: c.candidate_page_to, change_kind: c.change_kind || "text_changed",
              cands: [], rowIds: [], important: false, summary: "", pending: false };
        map.set(key, g);
      }
      g.cands.push(c); g.rowIds.push(c.row_id);
      if (isImportantCand(c)) g.important = true;
      if (!g.summary) g.summary = (c.new_snippet || c.match_text || c.reason || "").trim();
    }
    const arr = Array.from(map.values());
    for (const g of arr) {
      g.pending = g.cands.some((c) => { const dk = decByRow[c.row_id]?.decision ?? ""; return !(dk && dk !== "NEW_CANDIDATE"); });
    }
    arr.sort((a, b) => (a.important === b.important ? 0 : a.important ? -1 : 1)
      || `${a.manual_label}${String(a.old_from).padStart(6, "0")}`.localeCompare(`${b.manual_label}${String(b.old_from).padStart(6, "0")}`));
    return arr;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidates, decisions, stayFilter]);
  // 그룹(카드)별 규칙 기반 추천(검토완료/보류/무시) — 표시·일괄선택 보조용(운영 로직 무관).
  const recByKey = useMemo(() => {
    const m: Record<string, RecResult> = {};
    for (const g of pageGroups) m[g.key] = recommendGroup(g.cands);
    return m;
  }, [pageGroups]);
  const tabCounts = {
    unreviewed: pageGroups.filter((g) => g.pending).length,
    important: pageGroups.filter((g) => g.important && g.pending).length,
    done: pageGroups.filter((g) => !g.pending).length,
  };
  const tabGroups = mainTab === "unreviewed" ? pageGroups.filter((g) => g.pending)
    : mainTab === "important" ? pageGroups.filter((g) => g.important && g.pending)
    : mainTab === "done" ? pageGroups.filter((g) => !g.pending)
    : pageGroups;
  const visibleGroups = tabGroups.slice(0, visibleCount);
  const stayOptions = stayGroups.map(([g]) => g);

  const FILTERS: [string, string][] = [
    ["review", "검토 대상"], ["unreviewed", "미검토"], ["text_changed", "본문 변경"],
    ["page_moved", "페이지 변경"], ["uncertain", "매칭 불확실"], ["new", "신규"],
    ["noop", "실질 변경 없음"], ["has_pdf", "PDF 있음"], ["approve", "승인"], ["keep_existing", "기존유지"],
    ["hold", "보류"], ["reject", "제외"], ["all", "전체"],
  ];
  const filterCount = (f: string) => candidates.filter((c) => {
    const saved = filter; let r: boolean;
    // 임시로 평가(간단히 재사용): 동일 로직
    const dec = decByRow[c.row_id]?.decision ?? "";
    const kind = c.change_kind ?? "text_changed";
    const decided = dec && dec !== "NEW_CANDIDATE";
    switch (f) {
      case "all": r = true; break;
      case "review": r = c.needs_review !== false && !decided; break;
      case "unreviewed": r = !decided; break;
      case "page_moved": r = kind === "page_moved"; break;
      case "text_changed": r = kind === "text_changed"; break;
      case "uncertain": r = kind === "uncertain"; break;
      case "new": r = kind === "new"; break;
      case "noop": r = c.needs_review === false; break;
      case "has_pdf": r = !!artifactByRow[c.row_id]; break;
      case "approve": r = dec === "REVIEWED_APPROVE_CANDIDATE"; break;
      case "keep_existing": r = dec === "REVIEWED_KEEP_EXISTING"; break;
      case "hold": r = dec === "UNRESOLVED"; break;
      case "reject": r = dec === "REJECTED_BAD_CANDIDATE"; break;
      default: r = true;
    }
    void saved; return r;
  }).length;
  // 운영 반영 요약(모달용)
  const applySummary = (() => {
    let approve = 0, keep = 0, hold = 0, reject = 0, applyable = 0, noop = 0, applied = 0;
    for (const c of candidates) {
      if (c.needs_review === false) noop++;
      const d = decByRow[c.row_id];
      const dk = d?.decision ?? "";
      if (d?.applied) { applied++; }
      if (dk === "REVIEWED_APPROVE_CANDIDATE" || dk === "NEEDS_MANUAL_PAGE") { approve++; if (!d?.applied) applyable++; }
      else if (dk === "REVIEWED_KEEP_EXISTING") keep++;
      else if (dk === "UNRESOLVED") hold++;
      else if (dk === "REJECTED_BAD_CANDIDATE") reject++;
    }
    return { approve, keep, hold, reject, applyable, noop, applied };
  })();

  // 현재 단계(시각 스테퍼 강조용): 버전 없음→업로드/감지, 미검토 있음→검토, 그 외→운영 반영.
  const pendingCnt = s.pending_count ?? 0;
  const curStep = versions.length === 0 ? 1 : (pendingCnt > 0 ? 3 : 4);

  // ── 회차(run) 정보 + 검토 카운트 (상단 헤더용) ─────────────────────────────
  const curVer = versions.find((v) => v.version === version);
  const verIdx = versions.findIndex((v) => v.version === version);
  const runOrdinal = verIdx >= 0 ? versions.length - verIdx : null;   // 최신 = 가장 큰 번호
  const labelsInRun = Array.from(new Set(candidates.map((c) => c.manual_label).filter(Boolean))) as string[];
  const targetKr = labelsInRun.length === 0 ? "-"
    : labelsInRun.length >= 2 ? "공통(사증·체류)" : labelsInRun.map(manualKr).join(" · ");
  const fmtDt = (iso?: string | null) => (iso ? iso.replace("T", " ").slice(0, 16) : "-");
  // 검토 진행 카운트(no-op 제외, decByRow 기준 재계산).
  const reviewCounts = (() => {
    let done = 0, keep = 0, hold = 0, reject = 0, pending = 0, important = 0, detected = 0;
    for (const c of candidates) {
      if (c.needs_review === false) continue;   // no-op 제외
      detected++;
      if (isImportantCand(c)) important++;
      const dk = decByRow[c.row_id]?.decision ?? "";
      if (dk === "REVIEWED_APPROVE_CANDIDATE" || dk === "NEEDS_MANUAL_PAGE") done++;
      else if (dk === "REVIEWED_KEEP_EXISTING") keep++;
      else if (dk === "UNRESOLVED") hold++;
      else if (dk === "REJECTED_BAD_CANDIDATE") reject++;
      else pending++;
    }
    return { done, keep, hold, reject, pending, important, detected };
  })();
  const blByLabel: Record<string, { version: string; page_count: number }> = {};
  for (const v of blVersions) blByLabel[v.manual_label] = { version: v.version, page_count: v.page_count };

  return (
    <div className="space-y-4">
      {/* 워크플로 — 4단계 시각 스테퍼 (현재 단계 강조 · 완료 초록 · 대기 회색) */}
      <div className="hw-card" style={{ background: "#EBF8FF", borderColor: "#BEE3F8" }}>
        <div className="flex items-center gap-1 flex-wrap">
          {[["1", "PDF 업로드"], ["2", "변경감지"], ["3", "변경 검토"], ["4", "운영 반영"]].map(([num, label], i) => {
            const stepNo = i + 1;
            const done = stepNo < curStep;
            const active = stepNo === curStep;
            const bg = active ? "#2B6CB0" : done ? "#C6F6D5" : "#EDF2F7";
            const fg = active ? "#fff" : done ? "#22543D" : "#A0AEC0";
            return (
              <Fragment key={num}>
                <span className="text-xs px-3 py-1 rounded-full" style={{ background: bg, color: fg, fontWeight: active ? 700 : 500 }}>
                  {done ? "✓" : num}) {label}
                </span>
                {i < 3 && <span style={{ color: "#CBD5E0" }}>→</span>}
              </Fragment>
            );
          })}
        </div>
        <div className="text-xs mt-2" style={{ color: "#4A5568" }}>
          운영 매뉴얼은 아직 바뀌지 않았습니다. 아래 <b>검토 대상</b>만 확인한 뒤 <b>운영 반영</b>을 누르세요. (‘운영 반영’ 전까지 자동 반영 없음)
        </div>
      </div>

      {/* 상단 안내 — 무엇을 검토하고 어떤 결정을 하는지 (검토완료/보류/무시 정의) */}
      <div className="hw-card" style={{ background: "#FFFDF7", borderColor: "#FEEBC8" }}>
        <div className="flex items-start justify-between gap-2 flex-wrap">
          <div className="text-xs" style={{ color: "#4A5568", lineHeight: 1.8, maxWidth: 760 }}>
            이 화면은 <b>새 실무지침과 기존 실무지침을 비교</b>하여, 운영 데이터에 반영할 변경사항을 검토하는 단계입니다. 각 항목에서 다음 중 하나를 선택하세요.
            <div className="mt-2 grid gap-1.5">
              <div><span style={{ background: "#C6F6D5", color: "#22543D", fontWeight: 700, padding: "1px 8px", borderRadius: 10 }}>검토 완료</span> 실제 지침 변경으로 인정 → <b>이번 운영 반영 대상에 포함</b>합니다.</div>
              <div><span style={{ background: "#FEFCBF", color: "#975A16", fontWeight: 700, padding: "1px 8px", borderRadius: 10 }}>보류</span> 지금 판단하기 어려움 → 이번 반영에서는 <b>제외</b>하고 보류함에 남겨 나중에 다시 검토합니다.</div>
              <div><span style={{ background: "#FED7D7", color: "#822727", fontWeight: 700, padding: "1px 8px", borderRadius: 10 }}>무시</span> 자동 감지 오류이거나 우리 업무와 무관 → <b>이번 변경에서 제외(종결)</b>합니다.</div>
            </div>
            <div className="mt-2" style={{ color: "#C05621" }}>
              모든 항목이 <b>검토 완료·보류·무시</b> 중 하나로 처리되어야 운영 반영을 진행할 수 있습니다.
            </div>
          </div>
          <button type="button" onClick={() => setHelpOpen(true)}
            className="text-[11px] px-2.5 py-1 rounded font-bold flex-shrink-0"
            style={{ background: "#EBF8FF", color: "#2B6CB0", border: "1px solid #BEE3F8" }}>
            검토 완료 / 보류 / 무시 차이 보기
          </button>
        </div>
      </div>

      {/* 회차(run) 정보 헤더 — 몇 번째 업데이트인지 + 기준/후보 + 검토 진행 카운트 */}
      {version && (
        <div className="hw-card" style={{ background: "#F7FAFF", borderColor: "#BEE3F8" }}>
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="text-sm font-bold" style={{ color: "#2B6CB0" }}>
              매뉴얼 업데이트{runOrdinal != null ? ` #${runOrdinal}` : ""} · {version}
            </span>
            <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: "#E9D8FD", color: "#553C9A", fontWeight: 700 }}>대상: {targetKr}</span>
            <span className="text-[11px]" style={{ color: "#718096" }}>감지일시 {fmtDt(curVer?.detected_at)}</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-1 text-[11px]" style={{ color: "#4A5568" }}>
            {labelsInRun.map((lbl) => (
              <div key={lbl}>
                <span style={{ color: "#A0AEC0" }}>{manualKr(lbl)} </span>
                기준 v{blByLabel[lbl]?.version ?? "-"} ({blByLabel[lbl]?.page_count ?? "-"}p)
                {curVer?.label_timestamps?.[lbl] ? ` → 후보 ${fmtDt(curVer.label_timestamps[lbl])}` : ""}
              </div>
            ))}
          </div>
          <div className="flex items-center gap-1.5 flex-wrap mt-2 text-[11px]">
            {[
              ["감지", reviewCounts.detected, "#EDF2F7", "#4A5568"],
              ["중요", reviewCounts.important, "#FEEBC8", "#9C4221"],
              ["검토완료", reviewCounts.done, "#C6F6D5", "#22543D"],
              ["기존유지", reviewCounts.keep, "#BEE3F8", "#2A4365"],
              ["보류", reviewCounts.hold, "#FAF089", "#744210"],
              ["무시", reviewCounts.reject, "#FED7D7", "#822727"],
              ["미검토", reviewCounts.pending, "#FEFCBF", "#975A16"],
            ].map(([label, val, bg, color]) => (
              <span key={label as string} style={{ background: bg as string, color: color as string, fontWeight: 700, padding: "2px 8px", borderRadius: 10 }}>
                {label} {val}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 상태 요약 — 한눈에 */}
      {(() => {
        const pdfSrc = pdfStatus.stay?.viewer_source || pdfStatus.visa?.viewer_source || "";
        const pdfLabel = pdfSrc === "upload_staging" ? "검토용 업로드됨"
          : pdfSrc === "upload_deployed" ? "운영본(업로드)"
          : "현재 운영 PDF";
        const pdfTone = pdfSrc === "upload_staging" ? "yellow" : pdfSrc === "upload_deployed" ? "green" : "gray";
        const cand = s.candidate_count ?? 0;
        const detectLabel = versions.length === 0 ? "대기 중" : cand > 0 ? `완료 · 변경 ${cand}건` : "완료 · 변경 없음";
        const detectTone = versions.length === 0 ? "yellow" : "green";
        const pending = s.pending_count ?? 0;
        const reviewLabel = (s.review_target_count ?? 0) > 0 ? `${s.review_target_count}건 (미검토 ${pending})` : "없음";
        const reviewTone = pending > 0 ? "yellow" : "green";
        const applyLabel = applySummary.applyable > 0 ? `반영 대기 ${applySummary.applyable}건`
          : applySummary.applied > 0 ? `${applySummary.applied}건 반영 완료` : "미반영";
        const applyTone = applySummary.applyable > 0 ? "blue" : applySummary.applied > 0 ? "green" : "gray";
        return <StatusSummaryCards cards={[
          { label: "PDF 상태", value: pdfLabel, tone: pdfTone },
          { label: "변경감지", value: detectLabel, tone: detectTone },
          { label: "검토 대상", value: reviewLabel, tone: reviewTone },
          { label: "운영 반영", value: applyLabel, tone: applyTone },
        ]} />;
      })()}
      {(s.review_reason || s.needs_review) && (
        <div className="text-xs px-2 py-1.5 rounded"
          style={{ background: s.needs_review ? "#FFFAF0" : "#F0FFF4", color: s.needs_review ? "#C05621" : "#276749", border: `1px solid ${s.needs_review ? "#FEEBC8" : "#C6F6D5"}` }}>
          {s.needs_review ? "⚠ " : "✓ "}{s.review_reason || (s.needs_review ? "검토가 필요합니다" : "검토 완료")}
        </div>
      )}

      {/* 고급 · 진단 정보 (단계 진행 상태 · 기준 DB) — 기본 접힘 */}
      <details className="hw-card" style={{ background: "#FBFCFE" }}>
        <summary className="text-xs font-semibold cursor-pointer" style={{ color: "#718096" }}>🔧 고급 · 진단 정보 (단계 진행 상태 · 기준 DB)</summary>
        <div className="space-y-3 mt-3">
      {/* 단계별 진행 상태 — "어디까지 작동했고 어디부터 미구현인지" 분리 표시(작동 안 함 오해 방지) */}
      <div className="hw-card">
        <div className="text-xs font-semibold mb-2" style={{ color: "#2D3748" }}>단계별 진행 상태</div>
        {(() => {
          const changed = s.changed_count ?? 0;
          const cand = s.candidate_count ?? 0;
          const review = s.review_target_count ?? 0;
          const artTot = (pdfStatus.visa?.artifacts_total ?? 0) + (pdfStatus.stay?.artifacts_total ?? 0);
          const anyFull = !!(pdfStatus.visa?.full_pdf_artifact || pdfStatus.stay?.full_pdf_artifact);
          const stages: { label: string; state: "ok" | "info" | "todo"; text: string }[] = [
            { label: "텍스트 변경 감지", state: "ok",
              text: changed > 0 ? `정상 · 변경 ${changed}p 감지` : "정상 · 최신(변경 없음)" },
            { label: "manual_ref 후보", state: cand > 0 ? "ok" : "info",
              text: cand > 0 ? `후보 있음 ${cand}건 (검토대상 ${review})`
                    : changed > 0 ? "후보 없음 · 영향 manual_ref 없음 / revision_history만 변경(정상)"
                    : "후보 없음" },
            { label: "변경 페이지 PDF", state: artTot > 0 ? "ok" : "info",
              text: artTot > 0 ? `생성됨 (${artTot}건)` : "없음 (Cron/Worker에서 생성)" },
            { label: "전체 PDF 뷰어 최신화", state: anyFull ? "ok" : "todo",
              text: anyFull ? "full_pdf artifact 적용" : "미구현 · full_pdf artifact 없음 → 배포본 PDF 표시" },
            { label: "실행 주체", state: "info",
              text: runCap?.is_worker ? "워커 런타임" : "웹서비스(감지·조회 전용) · 기록/PDF 생성은 Cron/Worker 담당" },
          ];
          const col = (st: string) => st === "ok" ? "#276749" : st === "todo" ? "#C53030" : "#B7791F";
          const ic = (st: string) => st === "ok" ? "✅" : st === "todo" ? "⛔" : "ℹ️";
          return (
            <div className="flex flex-col gap-1.5">
              {stages.map((st) => (
                <div key={st.label} className="text-xs flex gap-2" style={{ alignItems: "baseline" }}>
                  <span style={{ width: 132, color: "#A0AEC0", flexShrink: 0 }}>{st.label}</span>
                  <span style={{ color: col(st.state), fontWeight: 600 }}>{ic(st.state)} {st.text}</span>
                </div>
              ))}
            </div>
          );
        })()}
        <div className="text-xs mt-2" style={{ color: "#718096" }}>
          ※ 텍스트 변경 감지·후보 검토·페이지 override·변경 페이지 PDF는 작동하며, <b>전체 PDF 뷰어 최신화만</b> 미구현입니다.
        </div>
      </div>

      {/* baseline 요약 */}
      <div className="hw-card">
        <div className="text-xs font-semibold mb-2" style={{ color: "#2D3748" }}>
          기준 DB (baseline) {bl.loaded ? "✅ 적재됨" : "⚠ 미적재"}
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          {blVersions.map((v) => (
            <div key={v.manual_label}>
              <div style={{ color: "#A0AEC0" }}>{v.manual_label} (v{v.version})</div>
              <div style={{ color: "#2D3748", fontWeight: 600 }}>{v.page_count} pages</div>
            </div>
          ))}
          <div>
            <div style={{ color: "#A0AEC0" }}>manual_base_refs</div>
            <div style={{ color: "#2D3748", fontWeight: 600 }}>{bl.refs_count ?? 0} rows</div>
          </div>
        </div>
      </div>

        </div>
      </details>

      {/* 1단계 · 최신 PDF 업로드 */}
      <div className="text-sm font-bold px-1 pt-1" style={{ color: "#2B6CB0" }}>1단계 · 최신 PDF 업로드</div>
      <ManualPdfUploadCard token={token} onReload={() => { void reloadState(); void reloadDecisions(); }} />

      {/* 2단계 · 변경감지 안내 (실제 실행은 위 업로드 카드의 "변경감지 실행" 버튼) */}
      <div className="text-sm font-bold px-1 pt-1" style={{ color: "#2B6CB0" }}>2단계 · 변경감지 실행</div>
      <div className="text-[11px] px-1" style={{ color: "#718096" }}>
        업로드한 PDF와 기준 PDF를 비교해 변경된 페이지를 찾습니다 — 위 업로드 카드의 <b>“변경감지 실행”</b> 버튼을 누르세요. (자동 실행/진단 등 상세는 아래 고급 정보)
      </div>

      {/* 고급 · 진단 정보 (자동 실행 · PDF 상태) — 기본 접힘 */}
      <details className="hw-card" style={{ background: "#FBFCFE" }}>
        <summary className="text-xs font-semibold cursor-pointer" style={{ color: "#718096" }}>🔧 고급 · 진단 정보 (자동 실행 · 워커 · PDF 표시 상태)</summary>
        <div className="space-y-3 mt-3">
      {/* 매뉴얼 최신화 수동 실행 (진단 / 실제) */}
      <div className="hw-card">
        <div className="text-xs font-semibold mb-2" style={{ color: "#2D3748" }}>매뉴얼 최신화 실행 (자동/워커)</div>
        <div className="flex items-center gap-2 flex-wrap mb-2">
          <button disabled={runBusy !== null} onClick={() => void runNow("diagnose")}
            className="text-xs px-3 py-1.5 rounded" style={{ background: "#2B6CB0", color: "#fff", border: "none" }}>
            {runBusy === "diagnose" ? "진단 중..." : "최신 매뉴얼 진단 실행"}
          </button>
          {/* 실제 업데이트(PG 기록) / 변경 페이지 PDF 생성은 무거운 작업 → 웹서비스에서 직접
              동기 실행하지 않는다. chromium 포함 Render Cron/Worker(Dockerfile.worker)가 담당.
              웹 UI 에서는 워커 런타임(is_worker)일 때만 활성화한다(실질적으로 항상 비활성, 안내용). */}
          <button disabled={runBusy !== null || !runCap?.is_worker || !runCap?.can_record_update}
            title={runCap?.is_worker ? "실제 업데이트(PG 기록) 실행" : "실제 업데이트는 Render Cron/Worker가 담당합니다(웹서비스에서 직접 실행하지 않음)"}
            onClick={() => void runNow("record")}
            className="text-xs px-3 py-1.5 rounded"
            style={{ background: (runCap?.is_worker && runCap?.can_record_update) ? "#DD6B20" : "#E2E8F0", color: (runCap?.is_worker && runCap?.can_record_update) ? "#fff" : "#A0AEC0", border: "none", cursor: (runCap?.is_worker && runCap?.can_record_update) ? "pointer" : "not-allowed" }}>
            {runBusy === "record" ? "실행 중..." : "실제 업데이트 실행 (Cron/Worker 담당)"}
          </button>
          <button disabled={runBusy !== null || !runCap?.is_worker || !runCap?.can_generate_pdf}
            title={runCap?.is_worker ? "변경 페이지 PDF artifact 생성(node+chromium)" : "PDF 생성은 chromium 포함 Render Cron/Worker가 담당합니다"}
            onClick={() => void runNow("generate_pdf_artifacts")}
            className="text-xs px-3 py-1.5 rounded"
            style={{ background: (runCap?.is_worker && runCap?.can_generate_pdf) ? "#38A169" : "#E2E8F0", color: (runCap?.is_worker && runCap?.can_generate_pdf) ? "#fff" : "#A0AEC0", border: "none", cursor: (runCap?.is_worker && runCap?.can_generate_pdf) ? "pointer" : "not-allowed" }}>
            {runBusy === "generate_pdf_artifacts" ? "생성 중..." : "변경 페이지 PDF 생성 (Cron/Worker 담당)"}
          </button>
          {runCap && (
            <span className="text-[11px]" style={{ color: "#718096" }}>
              런타임 {runCap.runtime} · node {runCap.node_available ? "✅" : "❌"} · rhwp {runCap.rhwp_available ? "✅" : "❌"} · chromium {runCap.chromium_available ? "✅" : "❌"} · 워커 {runCap.is_worker ? "✅" : "❌"} · 실제기록 {runCap.can_record_update ? "✅" : "❌"} · PDF생성 {runCap.can_generate_pdf ? "✅" : "❌"}
            </span>
          )}
        </div>
        {runCap && !runCap.is_worker && (
          <div className="text-xs px-2 py-1.5 rounded" style={{ background: "#FFFAF0", color: "#C05621", border: "1px solid #FEEBC8" }}>
            ⚠ <b>실제 업데이트(PG 기록)·변경 페이지 PDF 생성</b>은 매일 15:00 KST 또는 수동 트리거 시 <b>Render Cron/Worker(Dockerfile.worker, chromium 포함)</b>가 담당합니다. 웹서비스에서는 무거운 작업을 직접 실행하지 않으며, 이 화면은 <b>감지(진단)·상태 조회</b> 용도입니다. {runCap.can_record_update ? "(현재 웹 런타임도 node/rhwp 는 가능하나, 부하 분리를 위해 워커로 일원화)" : null}
          </div>
        )}
        {/* Render Cron Job 설정 안내 — 미설정 시 자동 업데이트가 동작하지 않음을 명확히 표시 */}
        <details className="text-[11px] mt-2 p-2 rounded" style={{ background: "#F0F5FF", color: "#2A4365", border: "1px solid #BEE3F8" }}>
          <summary style={{ cursor: "pointer", fontWeight: 700 }}>ⓘ 자동 업데이트는 Render Cron Job 설정 시 동작 — 미설정 시 비동작 (설정값 보기)</summary>
          <div style={{ lineHeight: 1.9, marginTop: 6 }}>
            <div><b>Render Dashboard → New + → Cron Job</b> (Web Service 아님). repo=동일, branch=main.</div>
            <div>Dockerfile: <code className="font-mono">Dockerfile.worker</code></div>
            <div>Command: <code className="font-mono">python -m backend.scripts.manual_worker_run --pg --with-pdf</code></div>
            <div>Schedule(UTC): <code className="font-mono">0 6 * * *</code> (= 15:00 KST)</div>
            <div>필수 env: <code className="font-mono">DATABASE_URL</code>(Web과 동일 PG) · <code className="font-mono">FEATURE_PG_MANUAL_UPDATE=1</code> · <code className="font-mono">FEATURE_MANUAL_AUTO_UPDATE=1</code></div>
            <div>선택 env(이미지에 baked): <code className="font-mono">CHROME_PATH=/usr/bin/chromium</code> · <code className="font-mono">MANUAL_UPDATE_WORKER=1</code></div>
            <div>불필요: KID_PII_ENCRYPTION_KEY · JWT/웹 전용 env · 업로드 관련 env</div>
            <div style={{ color: "#C05621" }}>결과는 PG(manual_pdf_artifacts blob 등)에 저장되어 이 화면에서 조회됩니다. Cron Job 미설정 시 자동 staging/PDF가 생성되지 않습니다.</div>
          </div>
        </details>
        {runResult && (() => {
          const r = runResult.result || {}; const s = (r.stages || {}) as Record<string, unknown>;
          const dl = Array.isArray(s.downloaded) ? (s.downloaded as { name: string; bytes: number }[]) : [];
          const ep = (s.extracted_pages || {}) as Record<string, number>;
          const ch = Array.isArray(s.changed) ? s.changed.length : undefined;
          return (
            <div className="text-[11px] mt-2 p-2 rounded" style={{ background: "#F7FAFC", color: "#2D3748", lineHeight: 1.8 }}>
              <div><b>{runResult.mode === "diagnose" ? "진단" : "실제"} 실행 결과</b> — status=<b>{r.status}</b>{r.version && <> · version {r.version}</>}</div>
              <div>하이코리아 접속: {s.detail_fetch_bytes ? `성공(${String(s.detail_fetch_bytes)} bytes)` : "-"} · 첨부 탐지: {s.attachments_found != null ? String(s.attachments_found) : "-"}건{ch != null && <> · 변경 감지 {ch}건</>}</div>
              {dl.length > 0 && <div>다운로드: {dl.map((f) => `${f.name} (${Math.round(f.bytes / 1024)}KB)`).join(", ")}</div>}
              {s.tmp_dir != null && <div>/tmp 저장: {String(s.tmp_dir)}</div>}
              {Object.keys(ep).length > 0 && <div>rhwp 추출: {Object.entries(ep).map(([k, v]) => `${k} ${v}p`).join(", ")}</div>}
              {s.changed_pages != null && <div>baseline diff 변경 페이지: {String(s.changed_pages)} · 후보: {String(s.candidates ?? "-")}</div>}
              <div>PG staging 기록: <b style={{ color: r.wrote_to_pg ? "#C05621" : "#276749" }}>{r.wrote_to_pg ? "기록함(record)" : "미기록(diagnose)"}</b>{r.source_deleted != null && <> · 원본 삭제: {r.source_deleted ? "✅" : "❌"}</>}</div>
              {s.note != null && <div style={{ color: "#C05621" }}>{String(s.note)}</div>}
              {r.error != null && <div style={{ color: "#C53030" }}>오류[{r.error_stage}]: {r.error}</div>}
            </div>
          );
        })()}
      </div>

      {/* PDF 최신화 상태 (왜 배포본 PDF 가 보이는지 투명하게 — 미구현 숨김 금지) */}
      <div className="hw-card">
        <div className="text-xs font-semibold mb-2" style={{ color: "#2D3748" }}>PDF 최신화 상태</div>
        <div className="text-xs mb-2 px-2 py-1.5 rounded" style={{ background: "#FFFAF0", color: "#C05621", border: "1px solid #FEEBC8" }}>
          ℹ️ <b>전체 PDF 뷰어 최신화만</b> 미구현입니다(full_pdf artifact 없음). 텍스트 변경 감지·후보 검토·페이지 override·변경 페이지 PDF 생성은 <b>정상 동작</b>합니다.
          “전체 PDF 보기”는 full_pdf artifact가 없어 <b>배포본(현행 운영) PDF</b>로 표시되며, 이 부분(변경 페이지→전체 PDF 교체)은 다음 단계 구현 예정입니다.
        </div>
        <div className="overflow-x-auto">
          <table className="hw-table w-full text-xs" style={{ minWidth: 720 }}>
            <thead><tr>{["매뉴얼", "뷰어 소스", "여는 파일", "배포본 날짜", "배포본 페이지", "최신 staging PDF", "PDF artifact", "생성기", "교체 파이프라인"].map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>
              {["visa", "stay"].map((m) => {
                const ps = pdfStatus[m];
                if (!ps) return <tr key={m}><td>{m}</td><td colSpan={8} style={{ color: "#A0AEC0" }}>조회 중…</td></tr>;
                const af = ps.artifacts || {};
                const vs = ps.viewer_source === "upload_staging" ? "업로드(검토용·미반영)"
                  : ps.viewer_source === "upload_deployed" ? "업로드(운영본)"
                  : ps.viewer_source === "artifact" ? "artifact"
                  : ps.viewer_source === "staging" ? "staging" : "배포본 fallback";
                return (
                  <tr key={m}>
                    <td>{m} ({ps.kr_label ?? ps.manual})</td>
                    <td><span style={{ fontWeight: 700, color: ps.viewer_source === "deployed" ? "#C05621" : "#22543D" }}>{vs}</span></td>
                    <td style={{ fontSize: 10 }}>{ps.viewer_file}</td>
                    <td>{ps.deployed?.mtime ?? "-"}</td>
                    <td>{ps.deployed?.page_count ?? "-"}p</td>
                    <td>{ps.staging_pdf_exists ? "있음 ✅" : "없음 ⚠"}</td>
                    <td>총 {af.total ?? 0} {ps.full_pdf_artifact ? "(full ✅)" : af.total ? "(changed)" : ""}</td>
                    <td>{ps.generator_present ? "설치됨" : "없음"}</td>
                    <td><span style={{ color: ps.replace_pipeline_wired ? "#22543D" : "#C53030", fontWeight: 700 }}>{ps.replace_pipeline_wired ? "연결됨" : "미구현"}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {(() => {
          const tot = (pdfStatus.visa?.artifacts_total ?? 0) + (pdfStatus.stay?.artifacts_total ?? 0);
          const anyFull = !!(pdfStatus.visa?.full_pdf_artifact || pdfStatus.stay?.full_pdf_artifact);
          if (tot === 0) return (
            <div className="text-xs mt-2 px-2 py-1.5 rounded" style={{ background: "#F7FAFC", color: "#718096" }}>
              현재 생성된 PDF artifact가 없습니다. viewer는 배포본 PDF fallback을 사용 중입니다.
            </div>
          );
          return (
            <div className="text-xs mt-2 px-2 py-1.5 rounded" style={{ background: "#F0FFF4", color: "#276749", border: "1px solid #C6F6D5" }}>
              PDF artifact {tot}건 저장됨{anyFull ? " — full_pdf artifact 있음(viewer 우선 사용)" : " (changed_page 검토용; viewer는 full_pdf artifact가 있어야 우선 사용)"}.
            </div>
          );
        })()}
      </div>

        </div>
      </details>

      {/* 3단계 · 변경사항 검토 */}
      <div className="text-sm font-bold px-1 pt-1" style={{ color: "#2B6CB0" }}>3단계 · 변경사항 검토</div>

      {/* 버전 선택 */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-xs font-medium" style={{ color: "#718096" }}>업데이트 버전</span>
        <select className="hw-input text-xs" style={{ minWidth: 200 }} value={version}
          onChange={(e) => setVersion(e.target.value)}>
          {versions.length === 0 && <option value="">(버전 없음)</option>}
          {versions.map((v) => (
            <option key={v.version} value={v.version}>
              {v.version} · 변경 {v.changed_page_count ?? 0} · 후보 {v.candidate_count ?? 0}
            </option>
          ))}
        </select>
        <button onClick={() => void loadTop()}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg border"
          style={{ borderColor: "#4299E1", color: "#2B6CB0", background: "#EBF8FF" }}>
          <RotateCcw size={12} /> 새로고침
        </button>
        {loading && <Loader2 size={14} className="animate-spin" style={{ color: "#A0AEC0" }} />}
      </div>

      {/* 버전 0건 안내 (정상) */}
      {versions.length === 0 && (
        <div className="hw-card text-sm" style={{ color: "#4A5568", lineHeight: 1.7 }}>
          <div style={{ fontWeight: 700, color: "#2D3748", marginBottom: 6 }}>
            기준 DB는 적재되었습니다. 아직 매뉴얼 변경 감지 실행 이력이 없습니다.
          </div>
          <div>매일 자동 감지(또는 수동 실행)가 변경을 발견하면 이 목록에 버전이 나타납니다.</div>
          <div style={{ color: "#276749" }}>기존 실무지침 PDF 조회는 정상 유지됩니다.</div>
        </div>
      )}

      {/* 변경 페이지 (원본 표) — 고급 탭에서만 */}
      {version && mainTab === "advanced" && (
        <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="text-xs font-semibold px-3 py-2" style={{ color: "#2D3748", borderBottom: "1px solid #EDF2F7" }}>
            변경 페이지 ({changed.length})
          </div>
          <div className="overflow-x-auto">
            <table className="hw-table w-full text-xs" style={{ minWidth: 700 }}>
              <thead><tr>
                {["매뉴얼", "변경", "baseline p.", "new p.", "유사도", "new 스니펫"].map((h) => <th key={h}>{h}</th>)}
              </tr></thead>
              <tbody>
                {changed.length === 0 && <tr><td colSpan={6} style={{ color: "#A0AEC0", textAlign: "center", padding: 16 }}>변경 페이지 없음</td></tr>}
                {changed.map((c, i) => (
                  <tr key={i}>
                    <td>{c.manual_label}</td><td>{c.change_type}</td>
                    <td>{c.baseline_page ?? "-"}</td><td>{c.new_page ?? "-"}</td>
                    <td>{c.similarity ?? "-"}</td>
                    <td style={{ maxWidth: 320, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.new_snippet}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* manual_ref 후보 — 검토/승인/운영반영 */}
      {version && (
        <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="px-3 py-2" style={{ borderBottom: "1px solid #EDF2F7" }}>
            <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
              <span className="text-xs font-semibold" style={{ color: "#2D3748" }}>
                변경사항 검토 — {mainTab === "advanced" ? `전체 후보 ${candidates.length}건` : `${tabGroups.length} 페이지 (표시 ${visibleGroups.length})`}
              </span>
              <button disabled={busy === "bulk" || applySummary.applyable === 0 || reviewCounts.pending > 0} onClick={() => setBulkApply(true)}
                title={reviewCounts.pending > 0 ? `미검토 ${reviewCounts.pending}건이 남아 운영 반영할 수 없습니다` : "승인 항목을 운영 실무지침에 반영 (4단계)"}
                className="text-[11px] px-2 py-1 rounded font-bold"
                style={{ background: (applySummary.applyable && reviewCounts.pending === 0) ? "#DD6B20" : "#E2E8F0", color: (applySummary.applyable && reviewCounts.pending === 0) ? "#fff" : "#A0AEC0", border: "none", cursor: (applySummary.applyable && reviewCounts.pending === 0) ? "pointer" : "not-allowed" }}>
                4단계 · 운영 반영 ({applySummary.applyable})
              </button>
            </div>
            {reviewCounts.pending > 0 && (
              <div className="text-[11px] mb-2 px-2 py-1.5 rounded" style={{ background: "#FFF5F5", color: "#C53030", border: "1px solid #FED7D7" }}>
                ⚠ 미검토 페이지가 남아 있습니다. 모든 페이지를 검토 완료·보류·무시 처리한 뒤 운영 반영할 수 있습니다.
              </div>
            )}
            {/* 탭: 미검토 / 중요 변경 / 검토 완료 / 고급 (기본 미검토) */}
            <div className="flex items-center gap-1 flex-wrap">
              {([["unreviewed", `미검토 ${tabCounts.unreviewed}`], ["important", `중요 변경 ${tabCounts.important}`], ["done", `검토 완료 ${tabCounts.done}`], ["advanced", "고급"]] as [typeof mainTab, string][]).map(([t, label]) => (
                <button key={t} onClick={() => setMainTab(t)} className="text-xs px-3 py-1 rounded-full"
                  style={{ border: `1px solid ${mainTab === t ? "#2B6CB0" : "#E2E8F0"}`, background: mainTab === t ? "#2B6CB0" : "#fff", color: mainTab === t ? "#fff" : "#718096", fontWeight: mainTab === t ? 700 : 500 }}>
                  {label}
                </button>
              ))}
              {stayOptions.length > 0 && mainTab !== "advanced" && (
                <select value={stayFilter} onChange={(e) => setStayFilter(e.target.value)} className="text-xs ml-1"
                  style={{ border: "1px solid #E2E8F0", borderRadius: 8, padding: "3px 8px", color: "#4A5568", background: "#fff" }}>
                  <option value="">체류자격 전체</option>
                  {stayOptions.map((g) => <option key={g} value={g}>{g}</option>)}
                </select>
              )}
            </div>
            {/* 고급 탭 전용: 선택 일괄 + 고급 컬럼 + 세부 필터 */}
            {mainTab === "advanced" && (
              <div className="flex items-center gap-1 flex-wrap mt-2">
                <span className="text-[11px]" style={{ color: "#A0AEC0" }}>선택 {selected.size}</span>
                <button disabled={busy === "bulk" || selected.size === 0} onClick={() => bulkDecision("approve", Array.from(selected))} className="text-[11px] px-2 py-1 rounded" style={{ background: "#EBF8FF", color: "#2B6CB0", border: "1px solid #BEE3F8" }}>선택 승인</button>
                <button disabled={busy === "bulk" || selected.size === 0} onClick={() => bulkDecision("keep_existing", Array.from(selected))} className="text-[11px] px-2 py-1 rounded" style={{ background: "#EBF8FF", color: "#2B6CB0", border: "1px solid #BEE3F8" }}>선택 기존유지</button>
                <button disabled={busy === "bulk" || selected.size === 0} onClick={() => bulkDecision("hold", Array.from(selected))} className="text-[11px] px-2 py-1 rounded" style={{ background: "#FFFFF0", color: "#975A16", border: "1px solid #FAF089" }}>선택 보류</button>
                <button disabled={busy === "bulk" || selected.size === 0} onClick={() => bulkDecision("reject", Array.from(selected))} className="text-[11px] px-2 py-1 rounded" style={{ background: "#FFF5F5", color: "#C53030", border: "1px solid #FED7D7" }}>선택 제외</button>
                <button type="button" onClick={() => setShowAdvCols((v) => !v)} className="text-[11px] px-2 py-1 rounded" style={{ border: "1px solid #E2E8F0", background: "#fff", color: "#718096" }}>
                  {showAdvCols ? "고급 컬럼 숨기기" : "고급 컬럼"}
                </button>
                <span style={{ color: "#CBD5E0" }}>|</span>
                {FILTERS.map(([f, label]) => (
                  <button key={f} onClick={() => setFilter(f)} className="text-[11px] px-2 py-0.5 rounded-full"
                    style={{ border: `1px solid ${filter === f ? "#2B6CB0" : "#E2E8F0"}`, background: filter === f ? "#2B6CB0" : "#fff", color: filter === f ? "#fff" : "#718096", fontWeight: filter === f ? 700 : 400 }}>
                    {label} {filterCount(f)}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 검토 카드 목록 — 페이지 단위 그룹 · 현재 탭 20개만 렌더(더 보기) · 상세는 펼칠 때만 lazy */}
          {mainTab !== "advanced" && (
          <div className="p-3 flex flex-col gap-2">
            {/* 일괄 선택 / 일괄 처리 도구 */}
            {tabGroups.length > 0 && (
              <div className="rounded-lg p-2 flex items-center gap-1.5 flex-wrap" style={{ background: "#F7FAFC", border: "1px solid #E2E8F0" }}>
                <span className="text-[11px] font-bold" style={{ color: "#4A5568" }}>{selected.size}개 선택됨 / 카드 {tabGroups.length}</span>
                <span style={{ color: "#CBD5E0" }}>|</span>
                <span className="text-[11px]" style={{ color: "#A0AEC0" }}>빠른 선택</span>
                <button onClick={() => setSelected(new Set(tabGroups.flatMap((g) => g.rowIds)))} className="text-[11px] px-2 py-0.5 rounded border" style={{ borderColor: "#CBD5E0", color: "#4A5568", background: "#fff" }}>현재 목록 전체</button>
                <button onClick={() => setSelected(new Set(tabGroups.filter((g) => g.important).flatMap((g) => g.rowIds)))} className="text-[11px] px-2 py-0.5 rounded border" style={{ borderColor: "#FBD38D", color: "#9C4221", background: "#fff" }}>중요 변경만</button>
                <button onClick={() => setSelected(new Set(tabGroups.filter((g) => (recByKey[g.key]?.rec) === "approve").flatMap((g) => g.rowIds)))} className="text-[11px] px-2 py-0.5 rounded border" style={{ borderColor: "#9AE6B4", color: "#22543D", background: "#fff" }}>자동추천 검토완료만</button>
                <button onClick={() => setSelected(new Set(tabGroups.filter((g) => (recByKey[g.key]?.rec) === "hold").flatMap((g) => g.rowIds)))} className="text-[11px] px-2 py-0.5 rounded border" style={{ borderColor: "#FAF089", color: "#744210", background: "#fff" }}>자동추천 보류만</button>
                <button onClick={() => setSelected(new Set(tabGroups.filter((g) => (recByKey[g.key]?.rec) === "reject").flatMap((g) => g.rowIds)))} className="text-[11px] px-2 py-0.5 rounded border" style={{ borderColor: "#FEB2B2", color: "#822727", background: "#fff" }}>자동추천 무시만</button>
                {selected.size > 0 && <button onClick={() => setSelected(new Set())} className="text-[11px] px-2 py-0.5 rounded border" style={{ borderColor: "#E2E8F0", color: "#A0AEC0", background: "#fff" }}>선택 해제</button>}
                <span style={{ color: "#CBD5E0" }}>|</span>
                <span className="text-[11px]" style={{ color: "#A0AEC0" }}>선택 일괄</span>
                {([["approve", "검토 완료", "#C6F6D5", "#22543D"], ["hold", "보류", "#FEFCBF", "#975A16"], ["reject", "무시", "#FED7D7", "#822727"]] as [("approve" | "hold" | "reject"), string, string, string][]).map(([ui, label, bg, color]) => (
                  <button key={ui} disabled={busy === "bulk" || selected.size === 0}
                    onClick={() => {
                      const rowIds = Array.from(selected);
                      const hasImportant = tabGroups.some((g) => g.important && g.rowIds.some((id) => selected.has(id)));
                      setBulkConfirm({ ui, rowIds, hasImportant });
                    }}
                    className="text-[11px] px-2 py-0.5 rounded font-bold disabled:opacity-40"
                    style={{ background: bg, color, border: "none" }}>
                    일괄 {label}
                  </button>
                ))}
              </div>
            )}
            {tabGroups.length > 0 && (
              <div className="text-[11px] px-1" style={{ color: "#A0AEC0" }}>
                ‘자동 추천’은 규칙 기반 <b>참고용</b>입니다 — 최종 판단(검토 완료 / 보류 / 무시)은 관리자가 합니다.
              </div>
            )}
            {visibleGroups.length === 0 && (
              <div style={{ color: "#A0AEC0", textAlign: "center", padding: 16, fontSize: 12 }}>이 탭에 표시할 페이지가 없습니다.</div>
            )}
            {visibleGroups.map((g) => {
              const kind = CHANGE_KIND[g.change_kind] ?? CHANGE_KIND.text_changed;
              const open = expandedGroups.has(g.key);
              const groupBusy = g.rowIds.some((id) => busy === id);
              const rec = recByKey[g.key] ?? recommendGroup(g.cands);
              const recS = REC_STYLE[rec.rec];
              const { codes, areas } = affectedTargets(g.cands);
              // 그룹 현재 결정 배지: 행별 결정이 일치하면 그 값, 섞이면 '혼합', 미결이면 미검토.
              const decKeys = g.rowIds.map((id) => decByRow[id]?.decision ?? "");
              const allSame = decKeys.every((k) => k === decKeys[0]);
              const grpBadge = !g.pending
                ? (allSame ? (DEC_BADGE[decKeys[0]] ?? DEC_BADGE[""]) : { label: "혼합", color: "#4A5568", bg: "#E2E8F0" })
                : DEC_BADGE[""];
              const allSelected = g.rowIds.length > 0 && g.rowIds.every((id) => selected.has(id));
              const toggleCard = () => setSelected((prev) => {
                const n = new Set(prev);
                if (allSelected) g.rowIds.forEach((id) => n.delete(id));
                else g.rowIds.forEach((id) => n.add(id));
                return n;
              });
              const points = judgmentPoints(g, rec);
              return (
                <div key={g.key} className="rounded-lg border" style={{ borderColor: allSelected ? "#2B6CB0" : g.important && g.pending ? "#F6AD55" : "#E2E8F0", background: allSelected ? "#F7FBFF" : "#fff", padding: 12 }}>
                  <div className="flex items-center gap-2 flex-wrap" style={{ marginBottom: 6 }}>
                    <input type="checkbox" checked={allSelected} onChange={toggleCard} title="이 항목 선택 (일괄 처리용)" />
                    <span style={{ fontSize: 10, padding: "1px 6px", borderRadius: 8, background: g.manual_label === "visa" ? "#E9D8FD" : "#BEE3F8", color: "#4A5568" }}>{manualKr(g.manual_label)}</span>
                    <span style={{ fontWeight: 700, color: "#2D3748", fontSize: 13 }}>
                      p.{g.old_from}{g.old_to && g.old_to !== g.old_from ? `-${g.old_to}` : ""} → <span style={{ color: g.old_from !== g.new_from ? "#DD6B20" : "#2B6CB0" }}>p.{g.new_from}{g.new_to && g.new_to !== g.new_from ? `-${g.new_to}` : ""}</span>
                    </span>
                    <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 10, background: kind.bg, color: kind.color, fontWeight: 700 }}>{kind.label}</span>
                    {g.important && <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 10, background: "#FEEBC8", color: "#9C4221", fontWeight: 700 }}>중요 변경 가능성</span>}
                    {g.cands.length > 1 && <span style={{ fontSize: 10, color: "#718096" }}>후보 {g.cands.length}건</span>}
                    <span className="ml-auto" style={{ fontSize: 10, padding: "2px 8px", borderRadius: 10, background: grpBadge.bg, color: grpBadge.color, fontWeight: 700 }}>{grpBadge.label}</span>
                  </div>

                  {/* 변경 요약 (실무자용 1~2줄) */}
                  <div style={{ fontSize: 12, color: "#2D3748", lineHeight: 1.55, marginBottom: 6 }}>{summarizeGroup(g)}</div>

                  {/* 영향 대상 */}
                  <div className="flex flex-wrap gap-x-3 gap-y-1" style={{ marginBottom: 6, fontSize: 11 }}>
                    <span style={{ color: "#718096" }}>영향 체류자격: <b style={{ color: "#4A5568" }}>{codes.length ? codes.join(", ") : "미분류"}</b></span>
                    {areas.length > 0 && <span style={{ color: "#718096" }}>업무영역: <b style={{ color: "#4A5568" }}>{areas.slice(0, 4).join(" / ")}{areas.length > 4 ? " 외" : ""}</b></span>}
                  </div>

                  {/* 자동 추천(규칙 기반) 처리 + 근거 + 신뢰도 — 참고용, 최종 판단은 관리자 */}
                  <div className="rounded p-2 mb-2" style={{ background: "#FBFCFE", border: `1px solid ${recS.bd}` }}>
                    <div className="flex items-center gap-2 flex-wrap" style={{ marginBottom: 2 }}>
                      <span style={{ fontSize: 10, color: "#A0AEC0", fontWeight: 700 }} title="후보의 페이지·유사도·신뢰도·체류자격 혼재 등 신호를 규칙으로 분석한 참고용 추천입니다. 최종 판단은 관리자가 합니다.">자동 추천</span>
                      <span style={{ fontSize: 11, padding: "1px 8px", borderRadius: 10, background: recS.bg, color: recS.color, fontWeight: 700 }}>{REC_KR[rec.rec]}</span>
                      <span style={{ fontSize: 10, color: "#718096" }}>추천 신뢰도 {REC_CONF_KR[rec.confidence]}</span>
                      <span style={{ fontSize: 9, color: "#A0AEC0" }}>· 참고용</span>
                    </div>
                    <div style={{ fontSize: 11, color: "#4A5568", lineHeight: 1.5 }}>{rec.reason}</div>
                    {points.length > 0 && (
                      <div style={{ fontSize: 11, color: "#718096", marginTop: 4 }}>
                        <b>확인할 점</b> — {points.join(" · ")}
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-1 flex-wrap">
                    <button onClick={() => toggleGroup(g.key, g.cands)} className="text-[11px] px-2 py-1 rounded border" style={{ borderColor: "#E2E8F0", color: "#2B6CB0", background: "#fff" }}>{open ? "자세히 닫기" : "자세히 보기"}</button>
                    <button disabled={groupBusy} title="이 페이지 변경을 검토 완료(승인)로 표시 → 운영 반영 대상" onClick={() => bulkDecision("approve", g.rowIds)} className="text-[11px] px-2 py-1 rounded border" style={{ borderColor: "#9AE6B4", color: "#22543D", background: "#fff" }}>검토 완료</button>
                    <button disabled={groupBusy} title="이번 반영에서 제외하고 나중에 다시 검토" onClick={() => bulkDecision("hold", g.rowIds)} className="text-[11px] px-2 py-1 rounded border" style={{ borderColor: "#FAF089", color: "#744210", background: "#fff" }}>보류</button>
                    <button disabled={groupBusy} title="오탐/무관으로 이번 변경에서 종결(무시)" onClick={() => bulkDecision("reject", g.rowIds)} className="text-[11px] px-2 py-1 rounded border" style={{ borderColor: "#FED7D7", color: "#822727", background: "#fff" }}>무시</button>
                    <button onClick={() => setApplyV3Cand({
                      code: codes[0], title: `${codes.length ? codes.join(", ") : g.key} — p.${g.new_from}${g.new_to && g.new_to !== g.new_from ? `-${g.new_to}` : ""}`,
                      rowId: g.cands[0]?.row_id,
                      existingText: g.cands[0]?.match_text, candidateText: g.cands[0]?.new_snippet, reason: g.cands[0]?.reason,
                    })}
                      title="v3에 적용 — 자격/체류업무/사증경로/준비서류 오버레이 편집"
                      className="text-[11px] px-2 py-1 rounded border flex items-center gap-1" style={{ borderColor: "#D6BCFA", color: "#6B46C1", background: "#fff" }}>
                      <GitMerge size={11} /> v3에 적용
                    </button>
                    {groupBusy && <Loader2 size={12} className="animate-spin" style={{ color: "#A0AEC0" }} />}
                  </div>
                  {open && (
                    <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
                      {g.cands.map((c) => {
                        const dec = decByRow[c.row_id];
                        const detail = detailCache[c.row_id];
                        return (
                          <div key={c.row_id} style={{ background: "#F7FAFC", borderRadius: 6, padding: 10 }}>
                            {g.cands.length > 1 && <div style={{ fontSize: 11, fontWeight: 600, color: "#4A5568", marginBottom: 6 }}>{c.detailed_code || "(코드없음)"}{c.business_name ? ` · ${c.business_name}` : ""}</div>}
                            {detailLoading === c.row_id ? <div style={{ color: "#A0AEC0" }}>상세 불러오는 중…</div>
                              : detail ? (
                                <CandidateDetailView d={detail} version={version} cand={c} decision={dec}
                                  onOpenPdf={openPdf} onOpenCandidatePdf={openCandidatePdf}
                                  onOverrideChanged={() => void reloadDecisions()} />
                              ) : <div style={{ color: "#A0AEC0" }}>상세 없음</div>}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
            {tabGroups.length > visibleGroups.length && (
              <button onClick={() => setVisibleCount((n) => n + 20)} className="text-xs px-3 py-2 rounded border" style={{ borderColor: "#BEE3F8", color: "#2B6CB0", background: "#EBF8FF", alignSelf: "center" }}>
                더 보기 ({visibleGroups.length} / {tabGroups.length} 페이지)
              </button>
            )}
          </div>
          )}

          {/* 고급 탭 · 전체 원본 표 (선택 일괄·기존유지·페이지 지정·행별 운영반영·no-op 포함) */}
          {mainTab === "advanced" && (
          <div className="overflow-x-auto">
            <div className="text-[11px] px-3 pt-2" style={{ color: "#A0AEC0" }}>전체 후보(no-op 포함) 원본 표 · 세부 필터/고급 컬럼은 위 도구 사용</div>
            <table className="hw-table w-full text-xs" style={{ minWidth: 1040 }}>
              <thead><tr>
                <th style={{ width: 24 }}>
                  <input type="checkbox" aria-label="전체 선택"
                    checked={filteredCands.length > 0 && filteredCands.every((c) => selected.has(c.row_id))}
                    onChange={(e) => setSelected(e.target.checked ? new Set(filteredCands.map((c) => c.row_id)) : new Set())} />
                </th>
                <th style={{ width: 24 }}></th>
                <th>업무명</th><th>매뉴얼</th><th>기존 p.</th><th>추천 p.</th>
                {showAdvCols && <th>신뢰도</th>}
                <th>변경 유형</th>
                {showAdvCols && <th>매칭 사유</th>}
                <th>현재 결정</th><th>결정</th><th>운영 반영</th>
              </tr></thead>
              <tbody>
                {filteredCands.length === 0 && <tr><td colSpan={showAdvCols ? 12 : 10} style={{ color: "#A0AEC0", textAlign: "center", padding: 16 }}>해당 필터에 후보 없음</td></tr>}
                {filteredCands.map((c) => {
                  const dec = decByRow[c.row_id];
                  const decKey = dec?.decision ?? "";
                  const badge = DEC_BADGE[decKey] ?? DEC_BADGE[""];
                  const kind = CHANGE_KIND[c.change_kind ?? "text_changed"] ?? CHANGE_KIND.text_changed;
                  const applied = !!dec?.applied;
                  const canApply = !applied && DEC_APPLYABLE.has(decKey);
                  const rowBusy = busy === c.row_id;
                  const isOpen = expanded === c.row_id;
                  const detail = detailCache[c.row_id];
                  return (
                    <Fragment key={c.row_id}>
                      <tr style={{ background: selected.has(c.row_id) ? "#F7FAFC" : c.needs_review === false ? "#FAFAFA" : undefined }}>
                        <td>
                          <input type="checkbox" checked={selected.has(c.row_id)}
                            onChange={(e) => setSelected((prev) => { const n = new Set(prev); if (e.target.checked) n.add(c.row_id); else n.delete(c.row_id); return n; })} />
                        </td>
                        <td>
                          <button onClick={() => void toggleExpand(c)} title="상세 비교"
                            style={{ background: "none", border: "none", cursor: "pointer", color: "#718096" }}>
                            {isOpen ? "▼" : "▶"}
                          </button>
                        </td>
                        <td>
                          <div style={{ fontWeight: 600 }}>
                            {c.detailed_code || "(코드없음)"}
                            {!!c.detailed_code && (
                              <>
                                <button onClick={() => router.push(`/qualifications/${encodeURIComponent(c.detailed_code!)}`)}
                                  title="해당 업무 화면 열기" className="ml-1"
                                  style={{ background: "none", border: "none", cursor: "pointer", color: "#3182CE", verticalAlign: "middle" }}>
                                  <ExternalLink size={11} />
                                </button>
                                <button onClick={() => setApplyV3Cand({
                                  code: c.detailed_code, title: `${c.detailed_code || c.row_id} — ${c.business_name || ""}`,
                                  rowId: c.row_id,
                                  existingText: c.match_text, candidateText: c.new_snippet, reason: c.reason,
                                })}
                                  title="v3에 적용 — 자격/체류업무/사증경로/준비서류 오버레이 편집" className="ml-1"
                                  style={{ background: "none", border: "none", cursor: "pointer", color: "#6B46C1", verticalAlign: "middle" }}>
                                  <GitMerge size={11} />
                                </button>
                              </>
                            )}
                            {artifactByRow[c.row_id] && (
                              <button onClick={() => setPdfView({ artifactId: artifactByRow[c.row_id], page: 1, label: `변경 페이지 PDF — ${c.detailed_code || c.row_id} (#${artifactByRow[c.row_id]})` })}
                                title="이 후보의 변경 페이지 PDF artifact 보기" className="ml-1" style={{ fontSize: 10, padding: "0 5px", borderRadius: 8, background: "#C6F6D5", color: "#22543D", border: "1px solid #9AE6B4", cursor: "pointer", fontWeight: 700 }}>
                                📄 PDF
                              </button>
                            )}
                          </div>
                          <div style={{ color: "#A0AEC0", fontSize: 10 }}>{showAdvCols ? c.row_id : ""}{c.business_name ? `${showAdvCols ? " · " : ""}${c.business_name}` : ""}</div>
                        </td>
                        <td><span style={{ fontSize: 10, padding: "1px 5px", borderRadius: 8, background: c.manual_label === "visa" ? "#E9D8FD" : "#BEE3F8", color: "#4A5568" }}>{c.manual_label}</span></td>
                        <td>{c.old_page_from}-{c.old_page_to}</td>
                        <td style={{ fontWeight: 600, color: c.page_changed ? "#DD6B20" : "#2B6CB0" }}>
                          {c.candidate_page_from}-{c.candidate_page_to}
                          {dec?.reviewer_candidate_from != null && (
                            <div style={{ fontSize: 10, color: "#C05621", fontWeight: 700 }} title="관리자 지정 (현재 검토 기준)">
                              ★지정 {dec.reviewer_candidate_from}-{dec.reviewer_candidate_to}
                            </div>
                          )}
                        </td>
                        {showAdvCols && <td>{c.confidence}{c.similarity != null && <span style={{ color: "#A0AEC0" }}> ({Math.round(c.similarity * 100)}%)</span>}</td>}
                        <td><span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 10, background: kind.bg, color: kind.color, fontWeight: 700 }}>{kind.label}</span></td>
                        {showAdvCols && <td style={{ maxWidth: 200, fontSize: 10, color: "#718096", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }} title={c.reason}>{c.reason}</td>}
                        <td><span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 10, background: badge.bg, color: badge.color, fontWeight: 700 }}>{badge.label}</span></td>
                        <td>
                          <div className="flex items-center gap-1">
                            <button disabled={rowBusy} title="후보 내용을 운영 반영 대상으로 선택" onClick={() => setDecision(c, "approve")} className="text-[11px] px-1.5 py-0.5 rounded border" style={{ borderColor: "#9AE6B4", color: "#22543D", background: "#fff" }}>승인</button>
                            <button disabled={rowBusy} title="기존 manual_ref를 유지" onClick={() => setDecision(c, "keep_existing")} className="text-[11px] px-1.5 py-0.5 rounded border" style={{ borderColor: "#BEE3F8", color: "#2A4365", background: "#fff" }}>기존유지</button>
                            <button disabled={rowBusy} title="나중에 다시 검토" onClick={() => setDecision(c, "hold")} className="text-[11px] px-1.5 py-0.5 rounded border" style={{ borderColor: "#FAF089", color: "#744210", background: "#fff" }}>보류</button>
                            <button disabled={rowBusy} title="이번 후보에서 제외" onClick={() => setDecision(c, "reject")} className="text-[11px] px-1.5 py-0.5 rounded border" style={{ borderColor: "#FED7D7", color: "#822727", background: "#fff" }}>제외</button>
                          </div>
                        </td>
                        <td>
                          {applied ? <span style={{ color: "#38A169", fontWeight: 700 }}>반영됨</span>
                            : canApply ? (
                              <button disabled={rowBusy} onClick={() => setApplyModal({ rowId: c.row_id, pf: String(dec?.reviewer_candidate_from ?? c.candidate_page_from ?? ""), pt: String(dec?.reviewer_candidate_to ?? c.candidate_page_to ?? dec?.reviewer_candidate_from ?? c.candidate_page_from ?? "") })}
                                className="text-[11px] px-2 py-0.5 rounded" style={{ background: "#DD6B20", color: "#fff", border: "none" }}>운영 반영</button>
                            ) : <span style={{ color: "#CBD5E0" }}>—</span>}
                        </td>
                      </tr>
                      {isOpen && (
                        <tr>
                          <td colSpan={12} style={{ background: "#F7FAFC", padding: 10 }}>
                            {detailLoading === c.row_id ? <div style={{ color: "#A0AEC0" }}>상세 불러오는 중…</div>
                              : detail ? (
                                <CandidateDetailView d={detail} version={version} cand={c} decision={dec}
                                  onOpenPdf={openPdf} onOpenCandidatePdf={openCandidatePdf}
                                  onOverrideChanged={() => void reloadDecisions()} />
                              ) : <div style={{ color: "#A0AEC0" }}>상세 없음</div>}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          )}
        </div>
      )}

      {/* active decisions (현재 + 이번 orphaned 1회만; archive 제외) — 고급 탭에서만 */}
      {mainTab === "advanced" && (
      <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
        <div className="text-xs font-semibold px-3 py-2" style={{ color: "#2D3748", borderBottom: "1px solid #EDF2F7" }}>
          검토 결정 (active · {decisions.length})
        </div>
        <div className="overflow-x-auto">
          <table className="hw-table w-full text-xs" style={{ minWidth: 800 }}>
            <thead><tr>
              {["row_id", "결정", "검토", "후보p.", "재검토", "후보변경", "orphaned", "source ver"].map((h) => <th key={h}>{h}</th>)}
            </tr></thead>
            <tbody>
              {decisions.length === 0 && <tr><td colSpan={8} style={{ color: "#A0AEC0", textAlign: "center", padding: 16 }}>검토 결정 없음 (PG 신규 시작)</td></tr>}
              {decisions.map((d, i) => (
                <tr key={i}>
                  <td>{d.row_id}</td><td>{d.decision || "-"}</td>
                  <td>{d.reviewed ? "✓" : ""}</td>
                  <td>{d.reviewed_candidate_page ?? "-"}</td>
                  <td>{d.needs_recheck ? "⚠" : ""}</td>
                  <td>{d.candidate_changed ? "✓" : ""}</td>
                  <td>{d.orphaned ? `예(${d.orphaned_at ?? ""})` : ""}</td>
                  <td>{d.source_version ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      )}

      {/* 운영 반영 확인 모달 */}
      {applyModal && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
          onClick={() => busy !== applyModal.rowId && setApplyModal(null)}>
          <div className="hw-card" style={{ width: 420, maxWidth: "90vw", background: "#fff" }} onClick={(e) => e.stopPropagation()}>
            <div className="text-sm font-bold mb-1" style={{ color: "#C05621" }}>⚠ 운영 반영 확인</div>
            {(() => {
              const c = candidates.find((x) => x.row_id === applyModal.rowId);
              const dd = decByRow[applyModal.rowId];
              return (
                <div className="text-xs mb-2 p-2 rounded" style={{ background: "#F7FAFC", lineHeight: 1.8 }}>
                  <div style={{ color: "#718096" }}>자동 기준 p.: {c?.old_page_from}-{c?.old_page_to} · 자동 후보 p.: {c?.candidate_page_from}-{c?.candidate_page_to}</div>
                  <div style={{ color: "#C05621" }}>관리자 지정 기준 p.: {dd?.reviewer_baseline_from ?? "-"}-{dd?.reviewer_baseline_to ?? "-"} · 관리자 지정 후보 p.: {dd?.reviewer_candidate_from ?? "-"}-{dd?.reviewer_candidate_to ?? "-"}</div>
                  <div style={{ color: "#822727", fontWeight: 700 }}>실제 반영될 페이지: {applyModal.pf}-{applyModal.pt}</div>
                </div>
              );
            })()}
            <div className="text-xs mb-3" style={{ color: "#4A5568", lineHeight: 1.6 }}>
              <b>{applyModal.rowId}</b> 의 manual_ref 페이지를 운영 실무지침(immigration DB)에 <b>실제로 반영</b>합니다.
              반영 전 자동 백업되며, 승인/직접입력 상태에서만 가능합니다. 되돌리려면 백업본으로 복원해야 합니다.
            </div>
            <div className="flex items-center gap-2 mb-3 text-xs">
              <label style={{ color: "#718096" }}>page_from</label>
              <input className="hw-input" style={{ width: 70 }} value={applyModal.pf}
                onChange={(e) => setApplyModal((m) => m && { ...m, pf: e.target.value })} />
              <label style={{ color: "#718096" }}>page_to</label>
              <input className="hw-input" style={{ width: 70 }} value={applyModal.pt}
                onChange={(e) => setApplyModal((m) => m && { ...m, pt: e.target.value })} />
            </div>
            <div className="flex justify-end gap-2">
              <button onClick={() => setApplyModal(null)} disabled={busy === applyModal.rowId}
                className="text-xs px-3 py-1.5 rounded border" style={{ borderColor: "#CBD5E0", color: "#718096", background: "#fff" }}>취소</button>
              <button onClick={() => void doApply()} disabled={busy === applyModal.rowId}
                className="text-xs px-3 py-1.5 rounded" style={{ background: "#DD6B20", color: "#fff", border: "none" }}>
                {busy === applyModal.rowId ? "반영 중..." : "운영 반영 실행"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 운영 반영 일괄 요약 모달 (req 9) */}
      {bulkApply && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
          onClick={() => busy !== "bulk" && setBulkApply(false)}>
          <div className="hw-card" style={{ width: 420, maxWidth: "90vw", background: "#fff" }} onClick={(e) => e.stopPropagation()}>
            <div className="text-sm font-bold mb-2" style={{ color: "#C05621" }}>⚠ 운영 반영 — 최종 요약 확인</div>
            <div className="text-xs mb-2 p-2 rounded" style={{ background: "#F0FFF4", border: "1px solid #C6F6D5", lineHeight: 1.9 }}>
              <div style={{ color: "#22543D", fontWeight: 700 }}>반영 예정 — 검토 완료(승인) {applySummary.applyable}건{applySummary.applied > 0 ? ` (이미 반영 ${applySummary.applied}건 별도)` : ""}</div>
            </div>
            <div className="text-xs mb-2" style={{ color: "#4A5568", lineHeight: 1.9 }}>
              <div>이번 반영 제외 — 보류: <b>{applySummary.hold}</b>건 · 무시: <b>{applySummary.reject}</b>건 · 기존유지: <b>{applySummary.keep}</b>건</div>
              <div>미검토: <b style={{ color: reviewCounts.pending > 0 ? "#C53030" : "#718096" }}>{reviewCounts.pending}</b>건 · 실질 변경 없음(no-op): {applySummary.noop}건</div>
            </div>
            {reviewCounts.pending > 0 ? (
              <div className="text-xs mb-3 p-2 rounded" style={{ background: "#FFF5F5", color: "#C53030", border: "1px solid #FED7D7" }}>
                ⛔ 미검토 {reviewCounts.pending}건이 남아 운영 반영을 진행할 수 없습니다. 모든 항목을 검토 완료·보류·무시로 처리하세요.
              </div>
            ) : (
              <div className="text-xs mb-3" style={{ color: "#718096", lineHeight: 1.6 }}>
                보류 항목은 이번 운영 반영에서 제외되며, 보류함에서 나중에 다시 검토할 수 있습니다. 무시 항목은 이번 업데이트 run에서 반영되지 않습니다.
                <div style={{ color: "#822727", marginTop: 4 }}>승인 항목의 후보 페이지를 운영 실무지침(immigration DB)에 반영합니다. 각 건 반영 전 자동 백업됩니다.</div>
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={() => setBulkApply(false)} disabled={busy === "bulk"}
                className="text-xs px-3 py-1.5 rounded border" style={{ borderColor: "#CBD5E0", color: "#718096", background: "#fff" }}>돌아가서 검토</button>
              <button onClick={() => void doBulkApply()} disabled={busy === "bulk" || applySummary.applyable === 0 || reviewCounts.pending > 0}
                className="text-xs px-3 py-1.5 rounded disabled:opacity-40" style={{ background: "#DD6B20", color: "#fff", border: "none" }}>
                {busy === "bulk" ? "반영 중..." : `운영 반영 진행 (${applySummary.applyable}건)`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 도움말 모달 — 검토완료/보류/무시 차이 */}
      {helpOpen && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
          onClick={() => setHelpOpen(false)}>
          <div className="hw-card" style={{ width: 460, maxWidth: "92vw", background: "#fff" }} onClick={(e) => e.stopPropagation()}>
            <div className="text-sm font-bold mb-3" style={{ color: "#2D3748" }}>검토 완료 / 보류 / 무시 차이</div>
            <div className="flex flex-col gap-2 text-xs" style={{ color: "#4A5568", lineHeight: 1.6 }}>
              <div className="p-2 rounded" style={{ background: "#F0FFF4", border: "1px solid #C6F6D5" }}>
                <b style={{ color: "#22543D" }}>검토 완료 = 반영 대상</b><br />실제 지침 변경으로 인정하고 이번 운영 반영에 포함합니다.
              </div>
              <div className="p-2 rounded" style={{ background: "#FFFFF0", border: "1px solid #FAF089" }}>
                <b style={{ color: "#975A16" }}>보류 = 이번 반영 제외, 보류함에 남김</b><br />지금 판단하기 어려우므로 이번 반영에서는 제외하고 나중에 다시 검토합니다.
              </div>
              <div className="p-2 rounded" style={{ background: "#FFF5F5", border: "1px solid #FED7D7" }}>
                <b style={{ color: "#822727" }}>무시 = 이번 run에서 오탐/무관으로 종결</b><br />자동 감지 오류이거나 우리 업무 데이터와 무관하여 이번 변경에서 제외합니다.
              </div>
              <div style={{ color: "#718096" }}><b>자동 추천은 규칙 기반 참고용이며, 최종 판단은 관리자가 합니다.</b> (후보의 페이지·유사도·신뢰도·체류자격 혼재 등 신호를 규칙으로 분석한 것으로, 외부 AI가 반영 여부를 결정하지 않습니다.)</div>
            </div>
            <div className="flex justify-end mt-3">
              <button onClick={() => setHelpOpen(false)} className="text-xs px-3 py-1.5 rounded" style={{ background: "#2B6CB0", color: "#fff", border: "none" }}>닫기</button>
            </div>
          </div>
        </div>
      )}

      {/* 일괄 처리 확인 모달 (검토완료/보류/무시) */}
      {bulkConfirm && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center" }}
          onClick={() => busy !== "bulk" && setBulkConfirm(null)}>
          <div className="hw-card" style={{ width: 420, maxWidth: "90vw", background: "#fff" }} onClick={(e) => e.stopPropagation()}>
            <div className="text-sm font-bold mb-2" style={{ color: bulkConfirm.ui === "reject" ? "#C53030" : bulkConfirm.ui === "hold" ? "#975A16" : "#22543D" }}>
              일괄 {bulkConfirm.ui === "approve" ? "검토 완료" : bulkConfirm.ui === "hold" ? "보류" : "무시"} 확인
            </div>
            <div className="text-xs mb-2" style={{ color: "#4A5568", lineHeight: 1.7 }}>
              {bulkConfirm.ui === "approve" && <>선택한 <b>{bulkConfirm.rowIds.length}개 항목</b>을 검토 완료 처리합니다. 이 항목들은 <b>운영 반영 대상에 포함</b>됩니다. 진행할까요?</>}
              {bulkConfirm.ui === "hold" && <>선택한 <b>{bulkConfirm.rowIds.length}개 항목</b>을 보류 처리합니다. 이번 운영 반영에서는 <b>제외</b>되며 보류함에 남아 나중에 다시 검토할 수 있습니다.</>}
              {bulkConfirm.ui === "reject" && <>선택한 <b>{bulkConfirm.rowIds.length}개 항목</b>을 무시 처리합니다. 이번 업데이트 run에서 <b>반영되지 않습니다</b>.</>}
            </div>
            {bulkConfirm.ui === "reject" && bulkConfirm.hasImportant && (
              <div className="text-xs mb-2 p-2 rounded" style={{ background: "#FFF5F5", color: "#9B2C2C", border: "1px solid #FEB2B2" }}>
                ⚠ <b>중요 변경 가능성</b>이 있는 항목이 포함되어 있습니다. 무시하면 이번 업데이트에서 반영되지 않습니다. 정말 무시하시겠습니까?
              </div>
            )}
            <div className="flex justify-end gap-2">
              <button onClick={() => setBulkConfirm(null)} disabled={busy === "bulk"}
                className="text-xs px-3 py-1.5 rounded border" style={{ borderColor: "#CBD5E0", color: "#718096", background: "#fff" }}>취소</button>
              <button onClick={async () => { const b = bulkConfirm; setBulkConfirm(null); await bulkDecision(b.ui, b.rowIds); }}
                disabled={busy === "bulk"}
                className="text-xs px-3 py-1.5 rounded font-bold" style={{ background: bulkConfirm.ui === "reject" ? "#C53030" : bulkConfirm.ui === "hold" ? "#DD6B20" : "#2F855A", color: "#fff", border: "none" }}>
                {busy === "bulk" ? "처리 중..." : `${bulkConfirm.rowIds.length}건 진행`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 매뉴얼 업데이트 알림 (보조 카드 — 화면 하단) */}
      <ManualAlertAdminCard />

      {/* 전체 PDF 보기 모달 (staging 우선, 없으면 배포본) */}
      {pdfView && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 1100, display: "flex", flexDirection: "column", padding: 20 }}
          onClick={() => setPdfView(null)}>
          <div className="hw-card" style={{ flex: 1, display: "flex", flexDirection: "column", background: "#fff", overflow: "hidden" }} onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
              <div className="text-sm font-bold" style={{ color: "#2D3748" }}>
                {pdfView.artifactId ? (pdfView.label || `변경 페이지 artifact #${pdfView.artifactId}`)
                  : `${pdfView.isStaging ? "최신 staging PDF" : "배포본 PDF"} — ${pdfView.manual} · p.${pdfView.page}`}
              </div>
              <div className="flex items-center gap-2 text-xs">
                {!pdfView.artifactId && <>
                  <span style={{ color: "#718096" }}>페이지</span>
                  <input defaultValue={String(pdfView.page)} className="hw-input" style={{ width: 60 }}
                    onKeyDown={(e) => { if (e.key === "Enter") { const n = parseInt((e.target as HTMLInputElement).value, 10); if (n >= 1) setPdfView((p) => p && { ...p, page: n }); } }} />
                </>}
                <button onClick={() => setPdfView(null)} className="px-2 py-1 rounded border" style={{ borderColor: "#CBD5E0", color: "#718096" }}>닫기</button>
              </div>
            </div>
            {pdfView.artifactId ? (
              <div className="text-xs mb-2 px-2 py-1 rounded" style={{ background: "#F0FFF4", color: "#276749", border: "1px solid #C6F6D5" }}>
                ✅ 최신 변경 페이지 PDF artifact 표시 중 (staging 생성본)
              </div>
            ) : pdfView.source === "upload_staging" ? (
              <div className="text-xs mb-2 px-2 py-1 rounded" style={{ background: "#FFF5F5", color: "#9B2C2C", border: "1px solid #FEB2B2" }}>
                🔎 검토용 업로드 PDF — 운영 미반영 (관리자가 업로드한 최신 전체 문서 · 후보 페이지로 이동 · 앞뒤 스크롤 가능). 운영 반영(승격) 전입니다.
              </div>
            ) : pdfView.source === "upload_deployed" ? (
              <div className="text-xs mb-2 px-2 py-1 rounded" style={{ background: "#F0FFF4", color: "#276749", border: "1px solid #C6F6D5" }}>
                ✅ 현재 운영 PDF (관리자 업로드 승격본 · 전체 문서 · 앞뒤 스크롤 가능)
              </div>
            ) : pdfView.reviewOnly ? (
              <div className="text-xs mb-2 px-2 py-1 rounded" style={{ background: "#FFF5F5", color: "#9B2C2C", border: "1px solid #FEB2B2" }}>
                🔎 검토용 PDF (운영 미반영) — 변경 페이지를 배포본에 합성한 미리보기입니다. 전체 문서이며 앞뒤 스크롤이 가능합니다. 운영 배포 PDF는 아직 교체되지 않았습니다.
              </div>
            ) : pdfView.source === "staging" || pdfView.source === "worker_artifact" || pdfView.isStaging ? (
              <div className="text-xs mb-2 px-2 py-1 rounded" style={{ background: "#F0FFF4", color: "#276749", border: "1px solid #C6F6D5" }}>
                ✅ 최신 전체 PDF 표시 중 (전체 문서 · 앞뒤 스크롤 가능)
              </div>
            ) : (
              <div className="text-xs mb-2 px-2 py-1 rounded" style={{ background: "#FFFAF0", color: "#C05621", border: "1px solid #FEEBC8" }}>
                ℹ 업로드 PDF 없음 — 기존 배포본 fallback (전체 문서 · 앞뒤 스크롤 가능). 최신 PDF를 업로드하면 검토 화면이 그 PDF를 엽니다.
              </div>
            )}
            <iframe key={pdfView.artifactId ? `art-${pdfView.artifactId}` : `${pdfView.manual}-${pdfView.page}`} style={{ flex: 1, border: "1px solid #E2E8F0", borderRadius: 6 }}
              src={pdfView.artifactId
                ? `/api/guidelines/manual-update/pdf-artifacts/${pdfView.artifactId}/content?token=${encodeURIComponent(token)}#toolbar=1&view=Fit`
                : `/api/guidelines/manual-update/pdf?manual=${encodeURIComponent(pdfView.manual || "")}&version=${encodeURIComponent(version)}&token=${encodeURIComponent(token)}#page=${pdfView.page}&toolbar=1&view=Fit`} />
          </div>
        </div>
      )}
      {applyV3Cand && (
        <ApplyToV3Modal
          hintCode={applyV3Cand.code ?? undefined}
          hintTitle={applyV3Cand.title}
          candidateRowId={applyV3Cand.rowId}
          candidateContext={{
            existingText: applyV3Cand.existingText,
            candidateText: applyV3Cand.candidateText,
            reason: applyV3Cand.reason,
          }}
          onClose={() => setApplyV3Cand(null)}
          onApplied={() => toast.success("v3 오버레이에 반영되었습니다.")}
        />
      )}
    </div>
  );
}
