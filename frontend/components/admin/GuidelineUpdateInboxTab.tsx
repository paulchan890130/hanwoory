"use client";
/**
 * 매뉴얼 업데이트 — 패키지 검토 섹션 (구 "실무지침 업데이트 검토함").
 *
 * "메뉴얼 업데이트" 관리자 탭 안에 원문 PDF 관리 + 이번 batch 반영 상태 + 패키지
 * 단위 검토(원문 대조·페이지 입력·메모·승인/보류/무시)를 한 화면에서 제공한다.
 * 더 이상 별도 탭이 아니며, bundle JSON 은 서버가 자동 제공한다(관리자가 파일
 * 경로를 알거나 직접 업로드할 필요 없음 — `GET .../manual-update/review-bundle`).
 *
 * 중요: 이 컴포넌트가 다루는 batch(`manual_update_260617_260623_v1`)는 이미
 * 실무지침 JSON(v2.1)에 **일괄 반영 완료**된 상태다. 여기서 누르는 승인/보류/
 * 무시·검토페이지·메모는 DB를 다시 바꾸지 않는 **사후 검토 기록**이며, 다음
 * batch 부터 이 기록을 근거로 승인 항목만 반영하는 방식으로 전환한다.
 *
 * 기록은 localStorage(review_id 단위)에 저장 + JSON 내보내기 — 저장 위치는
 * v3 스키마와 동일하므로 기존에 쌓인 결정은 그대로 이어서 보인다.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { manualSourcePdfApi, manualUpdateApi, type ManualSourcePdfMeta } from "@/lib/api";
import {
  Upload, Download, CheckCircle, PauseCircle, XCircle, RotateCcw,
  ChevronDown, ChevronUp, AlertTriangle, ExternalLink, BookOpen, Save, FileUp, CheckCircle2,
} from "lucide-react";

// ── 타입 ──────────────────────────────────────────────────────────────────────
interface BundleItem {
  id: string;
  delta_id: string;
  status_or_task: string;
  status_code: string;
  manual_type: string;
  change_type: string;
  old_content: string;
  new_content: string;
  practical_impact: string;
  requirements?: string[];
  documents?: Record<string, string[]>;
  risk_points?: string[];
  source_file: string;
  source_pages: number[];
  manual?: "visa" | "stay";
  section: string;
  confidence: string;
}

interface BundlePackage {
  id: string;
  title: string;
  impact: "high" | "medium" | "low";
  recommended_action: "quick_apply" | "confirm_then_apply" | "needs_confirmation" | "hold";
  decision_required: boolean;
  summary_3_lines: string[];
  why_user_should_care: string;
  item_count: number;
  affected_rows_count: number;
  affected_rows_sample: string[];
  items: BundleItem[];
}

interface ManualMeta {
  file: string;
  page_count: number | null;
}

interface ReviewBundle {
  review_id: string;
  bundle_format?: number;
  generated: string;
  summary: {
    package_count: number;
    quick_apply_count: number;
    confirm_then_apply_count: number;
    needs_confirmation_count: number;
    hold_count: number;
    total_items: number;
    affected_guideline_rows: number;
  };
  manual_meta?: Record<string, ManualMeta>;
  packages: BundlePackage[];
  /** 서버 자동 제공 bundle 에만 존재 — 이 batch 가 실무지침 JSON에 이미 반영됐는지 */
  applied?: boolean;
  batch_status?: BatchStatus;
}

interface BatchStatus {
  batch_id: string;
  status: "applied" | "not_applied";
  guideline_version: string;
  guideline_updated_at: string;
  row_count_total: number;
  row_count_before: number;
  rows_touched: number;
  rows_inserted: number;
  manual_updates_count: number;
  source_pages_missing: number;
}

type Decision = "approved" | "held" | "ignored";

/** 항목별 검토 상태 — 결정 + 사용자가 확인한 검토 페이지 + 메모 (AI 추출 페이지와 별도) */
interface ItemState {
  decision?: Decision;
  reviewed_page_input?: string;
  reviewed_pages?: number[];
  note?: string;
  updated_at?: string;
}

interface DecisionState {
  packages: Record<string, Decision>;
  items: Record<string, ItemState>;
}

const DECISION_LABEL: Record<Decision, string> = { approved: "승인", held: "보류", ignored: "무시" };

const ACTION_META: Record<BundlePackage["recommended_action"], { label: string; bg: string; fg: string }> = {
  quick_apply: { label: "즉시 반영 후보", bg: "#F0FFF4", fg: "#276749" },
  confirm_then_apply: { label: "확인 후 반영", bg: "#EBF8FF", fg: "#2B6CB0" },
  needs_confirmation: { label: "반드시 확인", bg: "#FFF5F5", fg: "#C53030" },
  hold: { label: "보류 가능", bg: "#EDF2F7", fg: "#4A5568" },
};

const IMPACT_META: Record<string, { label: string; bg: string; fg: string }> = {
  high: { label: "영향 높음", bg: "#FED7D7", fg: "#822727" },
  medium: { label: "영향 보통", bg: "#FEEBC8", fg: "#7B341E" },
  low: { label: "영향 낮음", bg: "#E2E8F0", fg: "#4A5568" },
};

// ── localStorage (v3: 항목 상태 객체) ────────────────────────────────────────
function storageKey(reviewId: string) {
  return `guideline_update_review_v3_${reviewId}`;
}

function loadDecisions(reviewId: string): DecisionState {
  try {
    const raw = localStorage.getItem(storageKey(reviewId));
    if (raw) {
      const p = JSON.parse(raw) as DecisionState;
      return { packages: p.packages ?? {}, items: p.items ?? {} };
    }
    // v2(항목 값이 문자열 decision) → v3 마이그레이션
    const old = localStorage.getItem(`guideline_update_review_v2_${reviewId}`);
    if (old) {
      const p = JSON.parse(old) as { packages?: Record<string, Decision>; items?: Record<string, Decision> };
      const items: Record<string, ItemState> = {};
      Object.entries(p.items ?? {}).forEach(([k, v]) => { items[k] = { decision: v }; });
      return { packages: p.packages ?? {}, items };
    }
  } catch { /* noop */ }
  return { packages: {}, items: {} };
}

function saveDecisions(reviewId: string, st: DecisionState) {
  try { localStorage.setItem(storageKey(reviewId), JSON.stringify(st)); } catch { /* noop */ }
}

// ── 원문 PDF 열기 — 서버 저장본(PG) 우선, 로컬 analysis fallback ─────────────
// Authorization 헤더로 blob 을 받아 Blob URL 로 새 탭에 연다(query token 미노출).
// 우선순위: 1) manual_source_pdfs(업로드본) 2) deprecated 로컬 fallback 3) 안내.
async function openSourcePdf(manual: "visa" | "stay" | undefined,
                             which: "current" | "previous", page?: number) {
  if (!manual) { toast.error("원문 매뉴얼 정보가 없습니다"); return;
  }
  let blob: Blob | null = null;
  try {
    blob = (await manualSourcePdfApi.contentBlob(manual, which)).data;
  } catch {
    try {
      blob = (await manualSourcePdfApi.legacyBlob(manual, which)).data;
    } catch {
      toast.error("원문 PDF가 업로드되지 않았습니다 — [원문 PDF 관리]에서 업로드하세요");
      return;
    }
  }
  const url = URL.createObjectURL(new Blob([blob], { type: "application/pdf" }));
  const frag = page && page > 0 ? `#page=${page}` : "";
  window.open(url + frag, "_blank", "noopener");
  // Blob URL 은 탭이 로드된 뒤 해제 (즉시 revoke 하면 새 탭이 못 읽음)
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// ── 페이지 입력 파싱/검증: "566" | "566-577" | "566, 568, 570-572" ───────────
function parsePageInput(input: string, maxPage: number | null): { pages: number[] } | { error: string } {
  const s = (input || "").trim();
  if (!s) return { error: "페이지를 입력하세요" };
  if (!/^[\d\s,\-~]+$/.test(s)) return { error: "숫자, 쉼표, 범위(-)만 입력 가능합니다" };
  const pages = new Set<number>();
  for (const part of s.split(",")) {
    const p = part.trim().replace("~", "-");
    if (!p) continue;
    const m = p.match(/^(\d+)\s*-\s*(\d+)$/);
    if (m) {
      const a = parseInt(m[1], 10), b = parseInt(m[2], 10);
      if (a <= 0 || b <= 0) return { error: "페이지는 1 이상이어야 합니다" };
      if (a > b) return { error: `역순 범위입니다: ${a}-${b}` };
      if (b - a > 2000) return { error: "범위가 너무 큽니다" };
      for (let i = a; i <= b; i++) pages.add(i);
    } else if (/^\d+$/.test(p)) {
      const n = parseInt(p, 10);
      if (n <= 0) return { error: "페이지는 1 이상이어야 합니다" };
      pages.add(n);
    } else {
      return { error: `해석할 수 없는 입력: "${p}"` };
    }
  }
  if (pages.size === 0) return { error: "페이지를 입력하세요" };
  const arr = Array.from(pages).sort((x, y) => x - y);
  if (maxPage && arr[arr.length - 1] > maxPage) {
    return { error: `이 매뉴얼은 ${maxPage}페이지까지입니다 (입력: ${arr[arr.length - 1]})` };
  }
  return { pages: arr };
}

// ── 결정 버튼 ────────────────────────────────────────────────────────────────
function DecisionButtons({ decision, onDecide, small }: {
  decision: Decision | undefined;
  onDecide: (d: Decision | null) => void;
  small?: boolean;
}) {
  const fs = small ? 10 : 11;
  const pad = small ? "2px 8px" : "4px 10px";
  return (
    <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
      <button onClick={() => onDecide("approved")}
        style={{ fontSize: fs, fontWeight: 600, padding: pad, borderRadius: 5, border: "1px solid #9AE6B4", background: decision === "approved" ? "#38A169" : "#F0FFF4", color: decision === "approved" ? "#fff" : "#276749", cursor: "pointer" }}>
        <CheckCircle size={fs} className="inline mr-0.5" />승인
      </button>
      <button onClick={() => onDecide("held")}
        style={{ fontSize: fs, fontWeight: 600, padding: pad, borderRadius: 5, border: "1px solid #FBD38D", background: decision === "held" ? "#DD6B20" : "#FFFAF0", color: decision === "held" ? "#fff" : "#C05621", cursor: "pointer" }}>
        <PauseCircle size={fs} className="inline mr-0.5" />보류
      </button>
      <button onClick={() => onDecide("ignored")}
        style={{ fontSize: fs, fontWeight: 600, padding: pad, borderRadius: 5, border: "1px solid #CBD5E0", background: decision === "ignored" ? "#718096" : "#F7FAFC", color: decision === "ignored" ? "#fff" : "#4A5568", cursor: "pointer" }}>
        <XCircle size={fs} className="inline mr-0.5" />무시
      </button>
      {decision && (
        <button onClick={() => onDecide(null)} title="결정 취소"
          style={{ fontSize: fs, padding: pad, borderRadius: 5, border: "1px solid #E2E8F0", background: "#fff", color: "#A0AEC0", cursor: "pointer" }}>
          <RotateCcw size={fs} />
        </button>
      )}
    </span>
  );
}

// ── 항목 행 (상세 안 — 접힌 기본, 펼치면 원문검토→메모→결정 순) ──────────────
function ItemRow({ item, state, manualMeta, onUpdate }: {
  item: BundleItem;
  state: ItemState | undefined;
  manualMeta: Record<string, ManualMeta>;
  onUpdate: (patch: Partial<ItemState>) => void;
}) {
  const [open, setOpen] = useState(false);
  const [pageInput, setPageInput] = useState(state?.reviewed_page_input ?? "");
  const [note, setNote] = useState(state?.note ?? "");

  const meta = item.manual ? manualMeta[item.manual] : undefined;
  const maxPage = meta?.page_count ?? null;
  const aiFirstPage = (item.source_pages || [])[0];
  const aiPagesLabel = (item.source_pages || []).join(", ");

  const docs = item.documents ?? {};
  const docEntries = Object.entries(docs).filter(([, v]) => v && v.length > 0);
  const DOC_LABEL: Record<string, string> = {
    applicant: "신청인", employer: "고용주/기관", family: "가족/신분",
    financial: "소득/재정", career_or_education: "경력/학력", other: "기타",
  };

  const savePages = () => {
    const r = parsePageInput(pageInput, maxPage);
    if ("error" in r) { toast.error(r.error); return; }
    onUpdate({ reviewed_page_input: pageInput.trim(), reviewed_pages: r.pages });
    toast.success(`검토 페이지 저장됨: p.${r.pages[0]}${r.pages.length > 1 ? `~${r.pages[r.pages.length - 1]} (${r.pages.length}쪽)` : ""}`);
  };

  const openInputPage = () => {
    const r = parsePageInput(pageInput, maxPage);
    if ("error" in r) { toast.error(r.error); return; }
    void openSourcePdf(item.manual, "current", r.pages[0]);
  };

  const saveNote = () => {
    onUpdate({ note: note.trim() });
    toast.success("검토 메모 저장됨");
  };

  const decision = state?.decision;

  return (
    <div style={{ borderTop: "1px solid #EDF2F7", padding: "6px 0" }}>
      {/* 접힌 한 줄 */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }} onClick={() => setOpen(!open)}>
        <span style={{ fontSize: 10, color: "#A0AEC0", width: 46, flexShrink: 0 }}>{item.delta_id}</span>
        <span style={{ fontSize: 10, fontWeight: 700, color: "#4A5568", width: 56, flexShrink: 0 }}>{item.change_type}</span>
        <span style={{ fontSize: 11, color: "#2D3748", flex: 1 }}>{item.status_or_task}</span>
        {state?.reviewed_pages && state.reviewed_pages.length > 0 && (
          <span title={`사용자 검토 페이지: ${state.reviewed_page_input}`} style={{ fontSize: 9, fontWeight: 700, color: "#2B6CB0" }}>
            검토 p.{state.reviewed_pages[0]}{state.reviewed_pages.length > 1 ? "~" : ""}
          </span>
        )}
        {state?.note && <span title={state.note} style={{ fontSize: 9, color: "#805AD5" }}>메모</span>}
        {decision && (
          <span style={{ fontSize: 10, fontWeight: 700, color: decision === "approved" ? "#38A169" : decision === "held" ? "#DD6B20" : "#718096" }}>
            {DECISION_LABEL[decision]}
          </span>
        )}
        {open ? <ChevronUp size={12} color="#A0AEC0" /> : <ChevronDown size={12} color="#A0AEC0" />}
      </div>

      {open && (
        <div style={{ marginTop: 6, marginLeft: 8, fontSize: 11 }}>
          {/* 1. 핵심 요약 */}
          <div style={{ fontWeight: 700, color: "#2D3748", marginBottom: 4 }}>
            {item.status_or_task} <span style={{ color: "#718096", fontWeight: 400 }}>({item.manual_type} · {item.change_type} · 확신도 {item.confidence || "-"})</span>
          </div>

          {/* 2·3. 기존/최신 */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            <div style={{ background: "#F7FAFC", borderRadius: 6, padding: "6px 8px" }}>
              <div style={{ fontWeight: 700, color: "#718096", marginBottom: 2 }}>기존 분석 내용</div>
              <div style={{ color: "#4A5568", whiteSpace: "pre-wrap" }}>{item.old_content || "—"}</div>
            </div>
            <div style={{ background: "#F0FFF4", borderRadius: 6, padding: "6px 8px" }}>
              <div style={{ fontWeight: 700, color: "#276749", marginBottom: 2 }}>최신 매뉴얼 내용</div>
              <div style={{ color: "#2D3748", whiteSpace: "pre-wrap" }}>{item.new_content || "—"}</div>
            </div>
          </div>

          {/* 4. 실무 영향 */}
          {item.practical_impact && (
            <div style={{ color: "#553C9A", marginTop: 4 }}><b>실무 영향:</b> {item.practical_impact}</div>
          )}

          {/* 5. 제출서류 변경 */}
          {docEntries.length > 0 && (
            <div style={{ marginTop: 4, color: "#4A5568" }}>
              <b>제출서류 변경:</b>
              {docEntries.map(([k, v]) => (
                <div key={k} style={{ marginLeft: 8 }}>· {DOC_LABEL[k] ?? k}: {v.join(", ")}</div>
              ))}
            </div>
          )}

          {/* 6. 원문 검토 */}
          <div style={{ marginTop: 8, background: "#FFFBEB", border: "1px solid #FDE68A", borderRadius: 6, padding: "8px 10px" }}>
            <div style={{ fontWeight: 700, color: "#92400E", marginBottom: 4, display: "flex", alignItems: "center", gap: 4 }}>
              <BookOpen size={12} /> 원문 검토
            </div>
            <div style={{ color: "#4A5568", lineHeight: 1.7 }}>
              출처 파일: {meta?.file || item.source_file}<br />
              AI 추출 페이지: {aiPagesLabel ? `p.${aiPagesLabel}` : "없음"} — {item.section || "섹션 정보 없음"}
              {state?.reviewed_pages && state.reviewed_pages.length > 0 && (
                <><br /><b style={{ color: "#2B6CB0" }}>사용자 검토 페이지: {state.reviewed_page_input}</b> (저장됨)</>
              )}
            </div>
            <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap", alignItems: "center" }}>
              <button onClick={() => void openSourcePdf(item.manual, "current")}
                style={{ fontSize: 10, fontWeight: 600, padding: "3px 10px", borderRadius: 5, border: "1px solid #B7791F", background: "#fff", color: "#975A16", cursor: "pointer" }}>
                <ExternalLink size={10} className="inline mr-1" />최신 원문 열기
              </button>
              <button onClick={() => void openSourcePdf(item.manual, "previous")}
                title="직전 버전 매뉴얼 (업로드되어 있을 때)"
                style={{ fontSize: 10, fontWeight: 600, padding: "3px 10px", borderRadius: 5, border: "1px solid #E2E8F0", background: "#fff", color: "#718096", cursor: "pointer" }}>
                <ExternalLink size={10} className="inline mr-1" />직전 원문 열기
              </button>
              <button onClick={() => void openSourcePdf(item.manual, "current", aiFirstPage)} disabled={!aiFirstPage}
                style={{ fontSize: 10, fontWeight: 600, padding: "3px 10px", borderRadius: 5, border: "1px solid #90CDF4", background: "#fff", color: "#2B6CB0", cursor: aiFirstPage ? "pointer" : "default", opacity: aiFirstPage ? 1 : 0.5 }}>
                <ExternalLink size={10} className="inline mr-1" />AI 추출 페이지 열기{aiFirstPage ? ` (p.${aiFirstPage})` : ""}
              </button>
              <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                <input
                  value={pageInput}
                  onChange={(e) => setPageInput(e.target.value)}
                  placeholder={`직접 입력 (예: 566-577)${maxPage ? ` · 1~${maxPage}` : ""}`}
                  style={{ width: 170, height: 24, fontSize: 10, border: "1px solid #CBD5E0", borderRadius: 5, padding: "0 6px" }}
                  onClick={(e) => e.stopPropagation()}
                />
                <button onClick={openInputPage}
                  style={{ fontSize: 10, fontWeight: 600, padding: "3px 10px", borderRadius: 5, border: "1px solid #CBD5E0", background: "#fff", color: "#4A5568", cursor: "pointer" }}>
                  해당 페이지 열기
                </button>
                <button onClick={savePages}
                  style={{ fontSize: 10, fontWeight: 700, padding: "3px 10px", borderRadius: 5, border: "1px solid #9AE6B4", background: "#F0FFF4", color: "#276749", cursor: "pointer" }}>
                  <Save size={10} className="inline mr-1" />검토 페이지로 저장
                </button>
              </span>
            </div>
            <div style={{ fontSize: 9, color: "#A0AEC0", marginTop: 4 }}>
              저장된 검토 페이지는 AI 추출 페이지를 덮어쓰지 않고 별도(reviewed_pages)로 보존되어 최종 반영 근거로 내보내집니다.
            </div>
          </div>

          {/* 7. 검토 메모 */}
          <div style={{ marginTop: 6, display: "flex", gap: 6, alignItems: "flex-start" }}>
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="검토 메모 (예: 고시번호 2026-35/65 표기 불일치 — 고시 원문 대조 후 반영)"
              rows={2}
              style={{ flex: 1, fontSize: 10, border: "1px solid #E2E8F0", borderRadius: 5, padding: "4px 6px", resize: "vertical" }}
            />
            <button onClick={saveNote}
              style={{ fontSize: 10, fontWeight: 600, padding: "4px 10px", borderRadius: 5, border: "1px solid #D6BCFA", background: "#FAF5FF", color: "#553C9A", cursor: "pointer", flexShrink: 0 }}>
              <Save size={10} className="inline mr-1" />메모 저장
            </button>
          </div>

          {/* 8. 결정 */}
          <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 10, color: "#A0AEC0" }}>개별 예외(사후 검토 기록):</span>
            <DecisionButtons decision={decision} onDecide={(d) => onUpdate({ decision: d ?? undefined })} small />
          </div>

          <div style={{ fontSize: 10, color: "#A0AEC0", marginTop: 4 }}>
            근거: {item.source_file} p.{aiPagesLabel} — {item.section}
          </div>
        </div>
      )}
    </div>
  );
}

// ── 패키지 카드 ──────────────────────────────────────────────────────────────
function PackageCard({ pkg, decisions, manualMeta, onPackageDecide, onItemUpdate }: {
  pkg: BundlePackage;
  decisions: DecisionState;
  manualMeta: Record<string, ManualMeta>;
  onPackageDecide: (pid: string, d: Decision | null) => void;
  onItemUpdate: (itemId: string, patch: Partial<ItemState>) => void;
}) {
  const [open, setOpen] = useState(false);
  const am = ACTION_META[pkg.recommended_action];
  const im = IMPACT_META[pkg.impact] ?? IMPACT_META.medium;
  const decision = decisions.packages[pkg.id];
  const itemTouched = pkg.items.filter((it) => {
    const s = decisions.items[it.id];
    return s && (s.decision || s.reviewed_pages?.length || s.note);
  }).length;

  return (
    <div
      className="hw-card"
      style={{
        padding: "12px 14px", marginBottom: 10,
        borderLeft: decision === "approved" ? "4px solid #38A169"
          : decision === "held" ? "4px solid #DD6B20"
          : decision === "ignored" ? "4px solid #A0AEC0"
          : pkg.recommended_action === "needs_confirmation" ? "4px solid #E53E3E"
          : "4px solid #CBD5E0",
        opacity: decision === "ignored" ? 0.55 : 1,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 14, fontWeight: 800, color: "#2D3748" }}>{pkg.title}</span>
        <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 10, background: am.bg, color: am.fg }}>{am.label}</span>
        <span style={{ fontSize: 10, fontWeight: 700, padding: "2px 8px", borderRadius: 10, background: im.bg, color: im.fg }}>{im.label}</span>
        {pkg.decision_required && (
          <span style={{ fontSize: 10, color: "#C53030", fontWeight: 700, display: "inline-flex", alignItems: "center", gap: 2 }}>
            <AlertTriangle size={11} /> 판단 필요
          </span>
        )}
        {decision && (
          <span style={{ marginLeft: "auto", fontSize: 11, fontWeight: 800, color: decision === "approved" ? "#38A169" : decision === "held" ? "#DD6B20" : "#718096" }}>
            패키지 {DECISION_LABEL[decision]}됨{itemTouched > 0 && ` (개별 검토 ${itemTouched})`}
          </span>
        )}
      </div>

      <ol style={{ margin: "8px 0 0 18px", fontSize: 12, color: "#4A5568", listStyle: "decimal", lineHeight: 1.7 }}>
        {pkg.summary_3_lines.map((l, i) => <li key={i}>{l}</li>)}
      </ol>

      <div style={{ fontSize: 11, color: "#718096", marginTop: 6 }}>
        항목 {pkg.item_count}건 · 영향 DB 행 {pkg.affected_rows_count}개
        <span style={{ color: "#805AD5", marginLeft: 8 }}>{pkg.why_user_should_care}</span>
      </div>

      <div style={{ display: "flex", gap: 6, marginTop: 8, alignItems: "center", flexWrap: "wrap" }}>
        <span style={{ fontSize: 10, color: "#A0AEC0" }}>사후 검토 기록:</span>
        <DecisionButtons decision={decision} onDecide={(d) => onPackageDecide(pkg.id, d)} />
        <button onClick={() => setOpen(!open)}
          style={{ marginLeft: "auto", fontSize: 11, fontWeight: 600, padding: "4px 12px", borderRadius: 5, border: "1px solid #CBD5E0", background: "#fff", color: "#2B6CB0", cursor: "pointer" }}>
          {open ? <><ChevronUp size={11} className="inline mr-1" />접기</> : <><ChevronDown size={11} className="inline mr-1" />상세 보기 ({pkg.item_count})</>}
        </button>
      </div>

      {open && (
        <div style={{ marginTop: 8 }}>
          {pkg.affected_rows_sample.length > 0 && (
            <div style={{ fontSize: 10, color: "#A0AEC0", marginBottom: 4 }}>
              영향 행 예: {pkg.affected_rows_sample.join(", ")}{pkg.affected_rows_count > pkg.affected_rows_sample.length && " …"}
            </div>
          )}
          {pkg.items.map((it) => (
            <ItemRow key={it.id} item={it} state={decisions.items[it.id]} manualMeta={manualMeta}
              onUpdate={(patch) => onItemUpdate(it.id, patch)} />
          ))}
        </div>
      )}
    </div>
  );
}

// ── 원문 PDF 관리 (manual_type별 최신/직전 2개 보관, 3번째 자동 삭제) ─────────
const MANUAL_TYPE_LABEL: Record<"visa" | "stay", string> = {
  visa: "사증민원 매뉴얼", stay: "체류민원 매뉴얼",
};

function fmtSize(n: number): string {
  return n >= 1024 * 1024 ? `${(n / (1024 * 1024)).toFixed(1)}MB` : `${Math.round(n / 1024)}KB`;
}

function SourcePdfManager() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const fileRefs = { visa: useRef<HTMLInputElement>(null), stay: useRef<HTMLInputElement>(null) };

  const { data: list, isError } = useQuery({
    queryKey: ["manual-source-pdfs"],
    queryFn: () => manualSourcePdfApi.list().then((r) => r.data),
    staleTime: 30_000,
    retry: false,   // 0029 미적용/PG 미구성 → 조용히 안내만
  });

  const uploadMut = useMutation({
    mutationFn: ({ type, file }: { type: "visa" | "stay"; file: File }) => {
      const fd = new FormData();
      fd.append("manual_type", type);
      // 파일명 앞 6자리 숫자(예: 260617)를 version_label 로 추정 — 실패 시 빈 값
      const m = file.name.match(/^(\d{6})/);
      fd.append("version_label", m ? m[1] : "");
      fd.append("file", file);
      return manualSourcePdfApi.upload(fd);
    },
    onSuccess: (r) => {
      toast.success(`업로드됨: ${r.data.uploaded.original_filename} (${r.data.uploaded.page_count}p) — 최신/직전 2개만 유지`);
      qc.invalidateQueries({ queryKey: ["manual-source-pdfs"] });
    },
    onError: (e) => {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "업로드 실패");
    },
  });

  const row = (type: "visa" | "stay") => {
    const items: ManualSourcePdfMeta[] = list?.[type] ?? [];
    const cur = items[0];
    const prev = items[1];
    return (
      <div key={type} style={{ marginTop: 8 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#2D3748" }}>{MANUAL_TYPE_LABEL[type]}</div>
        <div style={{ fontSize: 11, color: "#4A5568", marginTop: 2, lineHeight: 1.7 }}>
          최신: {cur ? `${cur.original_filename} / ${cur.page_count ?? "?"}p / ${fmtSize(cur.file_size)} / ${cur.uploaded_at.slice(0, 10)}` : "업로드 없음"}<br />
          직전: {prev ? `${prev.original_filename} / ${prev.page_count ?? "?"}p / ${fmtSize(prev.file_size)} / ${prev.uploaded_at.slice(0, 10)}` : "없음"}
        </div>
        <div style={{ display: "flex", gap: 6, marginTop: 4, flexWrap: "wrap" }}>
          <button onClick={() => void openSourcePdf(type, "current")} disabled={!cur}
            style={{ fontSize: 10, fontWeight: 600, padding: "3px 10px", borderRadius: 5, border: "1px solid #B7791F", background: "#fff", color: "#975A16", cursor: cur ? "pointer" : "default", opacity: cur ? 1 : 0.5 }}>
            최신 열기
          </button>
          <button onClick={() => void openSourcePdf(type, "previous")} disabled={!prev}
            style={{ fontSize: 10, fontWeight: 600, padding: "3px 10px", borderRadius: 5, border: "1px solid #E2E8F0", background: "#fff", color: "#718096", cursor: prev ? "pointer" : "default", opacity: prev ? 1 : 0.5 }}>
            직전 열기
          </button>
          <input ref={fileRefs[type]} type="file" accept=".pdf,application/pdf" style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) uploadMut.mutate({ type, file: f });
              e.target.value = "";
            }} />
          <button onClick={() => fileRefs[type].current?.click()} disabled={uploadMut.isPending}
            style={{ fontSize: 10, fontWeight: 600, padding: "3px 10px", borderRadius: 5, border: "1px solid #9AE6B4", background: "#F0FFF4", color: "#276749", cursor: "pointer" }}>
            <FileUp size={10} className="inline mr-1" />{uploadMut.isPending ? "업로드 중…" : "새 PDF 업로드"}
          </button>
        </div>
      </div>
    );
  };

  return (
    <div className="hw-card" style={{ padding: "10px 14px", marginBottom: 10 }}>
      <button onClick={() => setOpen(!open)}
        style={{ fontSize: 12, fontWeight: 700, color: "#2D3748", background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex", alignItems: "center", gap: 6 }}>
        <BookOpen size={13} /> 원문 PDF 관리 {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        <span style={{ fontSize: 10, fontWeight: 400, color: "#A0AEC0" }}>
          — 매뉴얼별 최신/직전 2개만 서버(PG)에 보관, 새 업로드 시 3번째는 자동 삭제
        </span>
      </button>
      {open && (
        isError ? (
          <div style={{ fontSize: 11, color: "#C05621", marginTop: 6 }}>
            원문 PDF 저장소를 사용할 수 없습니다 (PG 미구성 또는 migration 0029 미적용).
            로컬 환경에서는 analysis 폴더 fallback 으로 열람은 가능합니다.
          </div>
        ) : (
          <>
            {row("visa")}
            {row("stay")}
          </>
        )
      )}
    </div>
  );
}

// ── 메인 탭 ───────────────────────────────────────────────────────────────────
type Filter = "all" | "quick" | "confirm" | "hold" | "pending";

// ── 반영 상태 카드 ────────────────────────────────────────────────────────────
function BatchStatusCard({ status }: { status: BatchStatus }) {
  const applied = status.status === "applied";
  return (
    <div className="hw-card" style={{ padding: "12px 14px", marginBottom: 10,
      background: applied ? "#F0FFF4" : "#FFFAF0", borderColor: applied ? "#9AE6B4" : "#FDE68A" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <CheckCircle2 size={14} color={applied ? "#276749" : "#C05621"} />
        <span style={{ fontSize: 13, fontWeight: 800, color: applied ? "#276749" : "#92400E" }}>
          현재 batch: {status.batch_id}
        </span>
        <span style={{ fontSize: 11, fontWeight: 700, padding: "2px 8px", borderRadius: 10,
          background: applied ? "#38A169" : "#DD6B20", color: "#fff", marginLeft: 4 }}>
          {applied ? "일괄 반영 완료" : "미반영"}
        </span>
      </div>
      <div style={{ fontSize: 11, color: "#4A5568", marginTop: 6, lineHeight: 1.7 }}>
        이번 260617/260623 매뉴얼 업데이트는 실무지침 데이터 v{status.guideline_version}에 이미
        일괄 반영되었습니다. 아래 패키지는 <b>이번 반영 내역 확인용</b>이며, 다음 업데이트부터는
        이 화면에서 승인된 항목만 반영하는 방식으로 전환합니다.
      </div>
      <div style={{ display: "flex", gap: 16, marginTop: 8, flexWrap: "wrap", fontSize: 11, color: "#718096" }}>
        <span>실무지침 버전 <b style={{ color: "#2D3748" }}>v{status.guideline_version}</b></span>
        <span>행 수 <b style={{ color: "#2D3748" }}>{status.row_count_before} → {status.row_count_total}</b></span>
        <span>manual_updates <b style={{ color: "#2D3748" }}>{status.manual_updates_count}건</b></span>
        <span>신규 행 <b style={{ color: "#2D3748" }}>{status.rows_inserted}건</b></span>
        <span>source_pages 누락 <b style={{ color: status.source_pages_missing > 0 ? "#C53030" : "#2D3748" }}>
          {status.source_pages_missing}건</b></span>
      </div>
    </div>
  );
}

export default function GuidelineUpdateInboxTab() {
  const [bundle, setBundle] = useState<ReviewBundle | null>(null);
  const [decisions, setDecisions] = useState<DecisionState>({ packages: {}, items: {} });
  const [filter, setFilter] = useState<Filter>("all");
  const [showManualUpload, setShowManualUpload] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // 서버가 현재 batch 의 bundle 을 자동 제공 — 관리자가 파일을 올릴 필요 없음.
  const { data: serverBundle, isLoading: bundleLoading, error: bundleError } = useQuery({
    queryKey: ["manual-update", "review-bundle"],
    queryFn: () => manualUpdateApi.getReviewBundle().then((r) => r.data as unknown as ReviewBundle),
    retry: false,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (serverBundle && serverBundle.review_id && Array.isArray(serverBundle.packages)) {
      setBundle(serverBundle);
      setDecisions(loadDecisions(serverBundle.review_id));
    }
  }, [serverBundle]);

  const onFile = (f: File | undefined) => {
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result)) as ReviewBundle;
        if (!parsed.review_id || !Array.isArray(parsed.packages)) {
          toast.error(parsed && (parsed as unknown as { items?: unknown }).items
            ? "구버전 bundle(v1)입니다 — build_review_bundle.py 를 다시 실행해 패키지형(v2)으로 재생성하세요"
            : "review bundle 형식이 아닙니다 (review_id/packages 필요)");
          return;
        }
        setBundle(parsed);
        setDecisions(loadDecisions(parsed.review_id));
        toast.success(`패키지 ${parsed.packages.length}개 로드됨 (${parsed.review_id})`);
      } catch {
        toast.error("JSON 파싱 실패");
      }
    };
    reader.readAsText(f, "utf-8");
  };

  const decidePackage = (pid: string, d: Decision | null) => {
    if (!bundle) return;
    setDecisions((prev) => {
      const next = { ...prev, packages: { ...prev.packages } };
      if (d === null) delete next.packages[pid];
      else next.packages[pid] = d;
      saveDecisions(bundle.review_id, next);
      return next;
    });
  };

  const updateItem = (itemId: string, patch: Partial<ItemState>) => {
    if (!bundle) return;
    setDecisions((prev) => {
      const cur = prev.items[itemId] ?? {};
      const merged: ItemState = { ...cur, ...patch, updated_at: new Date().toISOString() };
      // decision 을 undefined 로 패치하면 결정 취소
      if (patch.decision === undefined && "decision" in patch) delete merged.decision;
      const next = { ...prev, items: { ...prev.items, [itemId]: merged } };
      // 전부 빈 상태면 키 제거
      if (!merged.decision && !(merged.reviewed_pages?.length) && !merged.note) {
        delete next.items[itemId];
      }
      saveDecisions(bundle.review_id, next);
      return next;
    });
  };

  const exportDecisions = () => {
    if (!bundle) return;
    const itemDecisions: object[] = [];
    for (const p of bundle.packages) {
      for (const it of p.items) {
        const s = decisions.items[it.id];
        if (!s || (!s.decision && !(s.reviewed_pages?.length) && !s.note)) continue;
        itemDecisions.push({
          package_id: p.id,
          item_id: it.id,
          delta_id: it.delta_id,
          status_or_task: it.status_or_task,
          decision: s.decision ?? "pending",
          ai_source_pages: it.source_pages,
          reviewed_page_input: s.reviewed_page_input ?? "",
          reviewed_pages: s.reviewed_pages ?? [],
          reviewed_by_user: !!(s.reviewed_pages && s.reviewed_pages.length),
          note: s.note ?? "",
          updated_at: s.updated_at ?? "",
        });
      }
    }
    const out = {
      review_id: bundle.review_id,
      exported_at: new Date().toISOString(),
      package_decisions: bundle.packages.map((p) => ({
        package_id: p.id,
        title: p.title,
        recommended_action: p.recommended_action,
        decision: decisions.packages[p.id] ?? "pending",
      })),
      decisions: itemDecisions,
    };
    const blob = new Blob([JSON.stringify(out, null, 1)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${bundle.review_id}_decisions.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("결정 내역 다운로드됨 (검토 페이지·메모 포함)");
  };

  const shown = useMemo(() => {
    if (!bundle) return [];
    return bundle.packages.filter((p) => {
      if (filter === "quick") return p.recommended_action === "quick_apply";
      if (filter === "confirm") return p.recommended_action === "needs_confirmation" || p.decision_required;
      if (filter === "hold") return p.recommended_action === "hold";
      if (filter === "pending") return !decisions.packages[p.id];
      return true;
    });
  }, [bundle, filter, decisions]);

  const done = bundle ? Object.keys(decisions.packages).length : 0;
  const manualMeta = bundle?.manual_meta ?? {};

  return (
    <div>
      {/* 원문 PDF 관리 — 매뉴얼별 최신/직전 보관·업로드 */}
      <SourcePdfManager />

      {/* 이번 batch 반영 상태 */}
      {bundle?.batch_status && <BatchStatusCard status={bundle.batch_status} />}

      <div className="hw-card" style={{ padding: "12px 14px", marginBottom: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, fontWeight: 800, color: "#2D3748" }}>패키지 검토</span>
          {bundleLoading && <span style={{ fontSize: 11, color: "#A0AEC0" }}>불러오는 중…</span>}
          {bundle && (
            <>
              <button onClick={exportDecisions}
                style={{ fontSize: 11, fontWeight: 600, padding: "4px 12px", borderRadius: 6, border: "1px solid #9AE6B4", background: "#F0FFF4", color: "#276749", cursor: "pointer" }}>
                <Download size={11} className="inline mr-1" />결정 내보내기
              </button>
              <span style={{ marginLeft: "auto", fontSize: 11, color: "#718096" }}>
                패키지 검토 {done}/{bundle.packages.length} · 기준 {bundle.generated}
              </span>
            </>
          )}
        </div>
        {bundle && (
          <div style={{ fontSize: 11, color: "#718096", marginTop: 6, lineHeight: 1.6 }}>
            이번 batch는 실무지침 v{bundle.batch_status?.guideline_version ?? "2.1"}에 이미 일괄
            반영되었습니다. 아래에서 누르는 승인/보류/무시, 검토 페이지, 메모는 <b>사후 검토 및
            다음 업데이트 기준 정리용</b>으로 이 브라우저에 저장되며, 다음 batch부터는 이 검토
            결과를 기준으로 승인 항목만 반영하는 방식으로 전환합니다.
          </div>
        )}
        {bundleError && !bundle && (
          <div style={{ fontSize: 11, color: "#C05621", marginTop: 6 }}>
            서버에서 현재 batch 검토 bundle을 불러오지 못했습니다. 아래 개발자용 옵션으로 로컬
            bundle 파일을 직접 열 수 있습니다.
          </div>
        )}

        {/* 개발자용 수동 업로드 — 서버 bundle이 없을 때만 쓰는 fallback, 기본 접힘 */}
        <details style={{ marginTop: 8 }} open={!bundle && !!bundleError}
          onToggle={(e) => setShowManualUpload((e.target as HTMLDetailsElement).open)}>
          <summary style={{ fontSize: 10, color: "#A0AEC0", cursor: "pointer" }}>
            개발자용: bundle 파일 직접 열기
          </summary>
          {showManualUpload && (
            <div style={{ marginTop: 6 }}>
              <input ref={fileRef} type="file" accept=".json,application/json" style={{ display: "none" }}
                onChange={(e) => onFile(e.target.files?.[0])} />
              <button onClick={() => fileRef.current?.click()}
                style={{ fontSize: 11, fontWeight: 600, padding: "4px 12px", borderRadius: 6, border: "1px solid #CBD5E0", background: "#fff", color: "#718096", cursor: "pointer" }}>
                <Upload size={11} className="inline mr-1" />bundle JSON 열기
              </button>
            </div>
          )}
        </details>
      </div>

      {bundle && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 8, marginBottom: 10 }}>
            {[
              { label: "처리 패키지", value: bundle.summary.package_count, color: "#2D3748" },
              { label: "즉시 반영 후보", value: bundle.summary.quick_apply_count, color: "#276749" },
              { label: "확인 후 반영", value: bundle.summary.confirm_then_apply_count, color: "#2B6CB0" },
              { label: "반드시 확인", value: bundle.summary.needs_confirmation_count, color: "#C53030" },
              { label: "보류 가능", value: bundle.summary.hold_count, color: "#718096" },
              { label: "영향 DB 행", value: bundle.summary.affected_guideline_rows, color: "#805AD5" },
            ].map((c) => (
              <div key={c.label} className="hw-card" style={{ padding: "8px 12px", textAlign: "center" }}>
                <div style={{ fontSize: 20, fontWeight: 800, color: c.color }}>{c.value}</div>
                <div style={{ fontSize: 10, color: "#A0AEC0" }}>{c.label}</div>
              </div>
            ))}
          </div>

          <div style={{ display: "flex", gap: 6, marginBottom: 10, flexWrap: "wrap" }}>
            {([
              ["all", "전체 패키지"],
              ["quick", "즉시 반영 후보만"],
              ["confirm", "확인 필요만"],
              ["hold", "보류만"],
              ["pending", "미처리만"],
            ] as [Filter, string][]).map(([k, label]) => (
              <button key={k} onClick={() => setFilter(k)}
                style={{
                  fontSize: 11, fontWeight: 600, padding: "5px 12px", borderRadius: 14,
                  border: filter === k ? "1px solid #B7791F" : "1px solid #E2E8F0",
                  background: filter === k ? "#FFFFF0" : "#fff",
                  color: filter === k ? "#975A16" : "#4A5568", cursor: "pointer",
                }}>
                {label}
              </button>
            ))}
          </div>

          {shown.length === 0 ? (
            <div className="hw-card text-center text-sm py-8" style={{ color: "#A0AEC0" }}>
              조건에 맞는 패키지가 없습니다.
            </div>
          ) : (
            shown.map((p) => (
              <PackageCard key={p.id} pkg={p} decisions={decisions} manualMeta={manualMeta}
                onPackageDecide={decidePackage} onItemUpdate={updateItem} />
            ))
          )}
        </>
      )}
    </div>
  );
}
