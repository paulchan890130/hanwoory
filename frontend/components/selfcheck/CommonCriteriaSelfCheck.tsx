"use client";
// 공통기준 자가점검 팝업 — 개인정보 무전송/무저장(프론트 메모리 전용).
// 게시 항목이 2개 이상이면 먼저 항목 선택 화면을 보여주고, 선택 후 질문 1개씩 진행 →
// 최종 결과를 동일 팝업(스마트폰 한 화면) 안에서 표시한다. 항목이 1개면 선택 화면 없이 바로 진행.
// 답변/결과/경로/선택 항목은 React state 로만 존재하며 서버·스토리지·로그에 절대 보내지 않는다.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { toast } from "sonner";
import { X, MessageSquare, RotateCcw, ChevronLeft } from "lucide-react";
import type { SelfCheckConfig, SelfCheckAnswer, SelfCheckItem } from "@/lib/selfcheck/types";
import { getQuestion, getResult, nextStep, buildFullLogic, buildAnswerLines, buildPathLine } from "@/lib/selfcheck/logic";
import { sendOrCopy, SMS_RECIPIENT_DISPLAY } from "@/lib/selfcheck/sms";

interface Props {
  /** 공개: 게시된 항목들(정렬 완료 가정). 2개 이상이면 선택 화면 표시. */
  items?: SelfCheckItem[];
  /** 관리자 미리보기 등 단일 config 직접 렌더(선택 화면 없음). */
  config?: SelfCheckConfig;
  open: boolean;
  onClose: () => void;
  /** 관리자 미리보기: fixed 오버레이 대신 360×740 등 지정 프레임 안에 렌더 */
  frame?: { width: number; height: number } | null;
}

export default function CommonCriteriaSelfCheck({ items, config, open, onClose, frame = null }: Props) {
  const pathname = usePathname();

  // 활성 항목 목록: items 우선, 없으면 단일 config 를 pseudo-item 1개로 감싼다.
  const activeItems = useMemo<SelfCheckItem[]>(() => {
    if (items && items.length) return items;
    if (config) return [{ item_id: "single", title: config.item_name, sort_order: 0, is_published: true, popup_enabled: true, placement: [], config }];
    return [];
  }, [items, config]);

  const autoSingle = activeItems.length === 1;
  const multi = activeItems.length > 1;

  const [selectedIdx, setSelectedIdx] = useState<number | null>(autoSingle ? 0 : null);
  const [currentQuestionId, setCurrentQuestionId] = useState<string>("");
  const [answers, setAnswers] = useState<SelfCheckAnswer[]>([]);
  const [finalResultId, setFinalResultId] = useState<string | null>(null);
  const [showCountries, setShowCountries] = useState(false);
  const [busy, setBusy] = useState(false);
  const headingRef = useRef<HTMLHeadingElement | null>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  const cfg: SelfCheckConfig | null = selectedIdx != null ? activeItems[selectedIdx]?.config ?? null : null;

  // 진행 상태만 초기화(선택 유지). 서버·스토리지 흔적 없음 → 순수 state reset.
  const resetProgress = useCallback((c: SelfCheckConfig | null) => {
    setCurrentQuestionId(c?.start_question_id ?? "");
    setAnswers([]);
    setFinalResultId(null);
    setShowCountries(false);
  }, []);

  // 전체 초기화(선택 화면으로). 항목 1개면 그 항목으로 자동 재선택.
  const resetAll = useCallback(() => {
    const idx = autoSingle ? 0 : null;
    setSelectedIdx(idx);
    resetProgress(idx != null ? activeItems[idx]?.config ?? null : null);
  }, [autoSingle, activeItems, resetProgress]);

  // 팝업 열릴 때 항상 처음부터. 열던 요소 기억(닫을 때 focus 복원).
  useEffect(() => {
    if (open) {
      openerRef.current = (typeof document !== "undefined" ? (document.activeElement as HTMLElement) : null);
      resetAll();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // 페이지 이동 시 초기화(다른 페이지로 나가면 흔적 없음).
  useEffect(() => { resetAll(); }, [pathname, resetAll]);

  // 언마운트 + bfcache(뒤로가기 복원) 시 초기화.
  useEffect(() => {
    const onPageShow = (e: PageTransitionEvent) => { if (e.persisted) resetAll(); };
    const onPageHide = () => resetAll();
    window.addEventListener("pageshow", onPageShow);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      window.removeEventListener("pageshow", onPageShow);
      window.removeEventListener("pagehide", onPageHide);
      resetAll();
    };
  }, [resetAll]);

  // ESC 닫기 + 열릴 때 heading 으로 focus.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") handleClose(); };
    window.addEventListener("keydown", onKey);
    const t = window.setTimeout(() => headingRef.current?.focus(), 30);
    return () => { window.removeEventListener("keydown", onKey); window.clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, selectedIdx, currentQuestionId, finalResultId]);

  // 팝업 열린 동안 배경 스크롤 잠금 — 실제 모달 모드에서만(미리보기 프레임 제외).
  useEffect(() => {
    if (!open || frame) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [open, frame]);

  const handleClose = () => {
    resetAll();
    onClose();
    window.setTimeout(() => { try { openerRef.current?.focus(); } catch { /* noop */ } }, 0);
  };

  const selectItem = (idx: number) => {
    setSelectedIdx(idx);
    resetProgress(activeItems[idx]?.config ?? null);
  };

  const backToSelection = () => {
    setSelectedIdx(null);
    resetProgress(null);
  };

  const answer = (ans: "yes" | "no") => {
    if (!cfg) return;
    const q = getQuestion(cfg, currentQuestionId);
    if (!q) return;
    const rec: SelfCheckAnswer = { question_id: q.id, display_number: q.display_number, summary: q.summary, answer: ans };
    const step = nextStep(cfg, q.id, ans);
    setAnswers((prev) => [...prev, rec]);
    setShowCountries(false);
    if (step.kind === "result") setFinalResultId(step.id);
    else if (step.kind === "question") setCurrentQuestionId(step.id);
  };

  const doSms = async () => {
    if (busy || !cfg) return;
    setBusy(true);
    try {
      const res = await sendOrCopy(cfg, answers, finalResultId);
      toast(res.toast, { duration: 6000 });
    } catch {
      toast(`수신번호: ${SMS_RECIPIENT_DISPLAY} · 내용을 직접 복사해 전송해 주세요.`);
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  const q = cfg ? getQuestion(cfg, currentQuestionId) : undefined;
  const result = cfg && finalResultId ? getResult(cfg, finalResultId) : null;
  const showSelection = selectedIdx == null && multi;
  const showResult = !!result;

  const overlayStyle: React.CSSProperties = frame
    ? { width: frame.width, height: frame.height, position: "relative", background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", borderRadius: 8 }
    : { position: "fixed", inset: 0, zIndex: 9000, background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", padding: "8px" };

  const panelStyle: React.CSSProperties = {
    width: frame ? "100%" : "min(420px, 96vw)",
    height: frame ? "100%" : "auto",
    maxHeight: frame ? "100%" : "96dvh",
    background: "#fff",
    borderRadius: frame ? 0 : 12,
    boxShadow: "0 12px 40px rgba(0,0,0,0.22)",
    display: "grid",
    gridTemplateRows: "auto 1fr auto",
    minHeight: 0,
    overflow: "hidden",
    boxSizing: "border-box",
    paddingBottom: "env(safe-area-inset-bottom, 0px)",
  };

  return (
    <div style={overlayStyle} onClick={frame ? undefined : handleClose}>
      <div role="dialog" aria-modal="true" aria-label="공통기준 자가점검" style={panelStyle} onClick={(e) => e.stopPropagation()}>
        {/* 헤더 */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid var(--hw-border)", minWidth: 0 }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0 }}>
            {multi && selectedIdx != null && !showResult && (
              <button onClick={backToSelection} aria-label="항목 선택으로"
                style={{ background: "none", border: "none", cursor: "pointer", color: "#718096", padding: 2, display: "inline-flex" }}>
                <ChevronLeft size={16} />
              </button>
            )}
            <span style={{ fontSize: 13, fontWeight: 700, color: "var(--hw-gold-700)", whiteSpace: "nowrap" }}>공통기준 자가점검</span>
          </span>
          <button onClick={handleClose} aria-label="자가점검 닫기"
            style={{ background: "none", border: "none", cursor: "pointer", color: "#718096", padding: 4, display: "inline-flex" }}>
            <X size={18} />
          </button>
        </div>

        {showSelection && (
          <SelectionView items={activeItems} headingRef={headingRef} onSelect={selectItem} />
        )}

        {!showSelection && !showResult && cfg && q && (
          <QuestionView q={q} config={cfg} showCountries={showCountries} setShowCountries={setShowCountries}
            headingRef={headingRef} onAnswer={answer} />
        )}

        {!showSelection && showResult && cfg && result && (
          <ResultView config={cfg} result={result} answers={answers} finalResultId={finalResultId}
            headingRef={headingRef} onSms={doSms} onRestart={() => resetProgress(cfg)} onClose={handleClose}
            onChangeItem={multi ? backToSelection : undefined} busy={busy} />
        )}

        {/* 선택/질문/결과 어디에도 안 걸리는 방어(빈 항목) */}
        {!showSelection && !cfg && (
          <div style={{ padding: 24, fontSize: 13, color: "var(--hw-text-sub)" }}>표시할 점검 항목이 없습니다.</div>
        )}
      </div>
    </div>
  );
}

// ── 항목 선택 화면 (게시 항목 2개 이상) ──────────────────────────────────────
function SelectionView({ items, headingRef, onSelect }: {
  items: SelfCheckItem[];
  headingRef: React.RefObject<HTMLHeadingElement>;
  onSelect: (idx: number) => void;
}) {
  return (
    <div style={{ padding: "16px 16px 12px", overflowY: "auto", minHeight: 0 }}>
      <h2 ref={headingRef} tabIndex={-1} style={{ fontSize: 17, fontWeight: 800, color: "#111827", outline: "none", marginBottom: 4 }}>
        점검할 항목을 선택하세요
      </h2>
      <p style={{ fontSize: 12, color: "var(--hw-text-sub)", marginBottom: 12, lineHeight: 1.5 }}>
        각 항목은 예/아니오 질문으로 진행됩니다. 답변은 저장되지 않습니다.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {items.map((it, idx) => (
          <button key={it.item_id} onClick={() => onSelect(idx)}
            style={{ textAlign: "left", width: "100%", boxSizing: "border-box", borderRadius: 8, cursor: "pointer",
              background: "var(--hw-gold-50)", border: "1px solid var(--hw-gold-200)", padding: "12px 14px",
              display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: "#111827" }}>{it.title || it.config.item_name}</span>
            {it.config.logic_version && (
              <span style={{ fontSize: 11, color: "#A0AEC0" }}>{it.config.logic_version}</span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── 질문 화면 (항상 1개만) ────────────────────────────────────────────────────
function QuestionView({ q, config, showCountries, setShowCountries, headingRef, onAnswer }: {
  q: NonNullable<ReturnType<typeof getQuestion>>;
  config: SelfCheckConfig;
  showCountries: boolean;
  setShowCountries: (v: boolean) => void;
  headingRef: React.RefObject<HTMLHeadingElement>;
  onAnswer: (a: "yes" | "no") => void;
}) {
  const hasCountries = !!q.country_list_ref && (config.country_list?.length ?? 0) > 0;
  const btn: React.CSSProperties = {
    minHeight: 48, width: "100%", boxSizing: "border-box", borderRadius: 8, fontSize: 16, fontWeight: 700, cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
  };
  return (
    <div style={{ padding: "16px 16px 6px", overflowY: "auto", minHeight: 0 }} aria-live="polite">
      <div style={{ fontSize: 12, color: "var(--hw-text-sub)", marginBottom: 4 }}>{config.item_name}</div>
      <h2 ref={headingRef} tabIndex={-1} style={{ fontSize: 18, fontWeight: 800, color: "#111827", lineHeight: 1.4, outline: "none", overflowWrap: "anywhere" }}>
        <span style={{ color: "var(--hw-gold-700)", marginRight: 6 }}>{q.display_number}</span>{q.text}
      </h2>
      {q.help && <p style={{ fontSize: 12.5, color: "var(--hw-text-sub)", marginTop: 8, lineHeight: 1.5 }}>{q.help}</p>}

      {hasCountries && (
        <div style={{ marginTop: 12 }}>
          <button onClick={() => setShowCountries(!showCountries)} aria-expanded={showCountries}
            style={{ fontSize: 12, fontWeight: 600, color: "var(--hw-gold-700)", background: "var(--hw-gold-50)",
              border: "1px solid var(--hw-gold-200)", borderRadius: 6, padding: "6px 10px", cursor: "pointer", width: "100%", boxSizing: "border-box", textAlign: "left" }}>
            {showCountries ? "▲ " : "▼ "}{config.country_list_title || "고위험 국가"} 목록 보기 ({config.country_list!.length}개국)
          </button>
          {showCountries && (
            <div style={{ marginTop: 6, maxHeight: 160, overflowY: "auto", border: "1px solid var(--hw-border)", borderRadius: 6, padding: "8px 10px",
              display: "flex", flexWrap: "wrap", gap: "4px 8px", fontSize: 12, color: "#4A5568" }}>
              {config.country_list!.map((c) => <span key={c}>{c}</span>)}
            </div>
          )}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 18 }}>
        <button onClick={() => onAnswer("yes")} style={{ ...btn, background: "var(--hw-gold-200)", color: "#111827", border: "1px solid var(--hw-gold-500)" }}>예</button>
        <button onClick={() => onAnswer("no")} style={{ ...btn, background: "#fff", color: "#1A202C", border: "1px solid var(--hw-border)" }}>아니오</button>
      </div>
    </div>
  );
}

// ── 결과 화면 (한 화면 완결) ──────────────────────────────────────────────────
function ResultView({ config, result, answers, finalResultId, headingRef, onSms, onRestart, onClose, onChangeItem, busy }: {
  config: SelfCheckConfig;
  result: NonNullable<ReturnType<typeof getResult>>;
  answers: SelfCheckAnswer[];
  finalResultId: string | null;
  headingRef: React.RefObject<HTMLHeadingElement>;
  onSms: () => void; onRestart: () => void; onClose: () => void; onChangeItem?: () => void; busy: boolean;
}) {
  const itemName = result.item_name || config.item_name;
  const notice = result.notice_text || config.notice_text || "";
  const answerLines = buildAnswerLines(answers);
  const pathLine = buildPathLine(config, answers, finalResultId);
  const fullLogic = buildFullLogic(config);
  const actBtn: React.CSSProperties = { minHeight: 44, borderRadius: 8, fontSize: 13, fontWeight: 700, cursor: "pointer", boxSizing: "border-box",
    display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6 };
  return (
    <>
      <div style={{ padding: "10px 16px 4px", overflow: "hidden", minHeight: 0,
        display: "grid", gridTemplateRows: "auto auto auto auto auto", gap: 8, alignContent: "start" }}>
        <div>
          <div style={{ fontSize: "clamp(15px, 4vw, 17px)", color: "var(--hw-text-sub)", fontWeight: 600 }}>{itemName}</div>
          <h2 ref={headingRef} tabIndex={-1} aria-live="polite"
            style={{ fontSize: "clamp(22px, 6.2vw, 27px)", fontWeight: 800, color: "#111827", lineHeight: 1.15, margin: "2px 0 0", outline: "none", overflowWrap: "anywhere" }}>
            {result.headline}
          </h2>
        </div>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--hw-gold-700)", marginBottom: 2 }}>내 답변</div>
          <div style={{ fontSize: "clamp(11.5px, 3.2vw, 13px)", color: "#2D3748", lineHeight: 1.5 }}>
            {answerLines.map((l, i) => <div key={i}>{l}</div>)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: "var(--hw-gold-700)", marginBottom: 2 }}>판정 경로</div>
          <div style={{ fontSize: "clamp(11.5px, 3.2vw, 13px)", color: "#2D3748", lineHeight: 1.4, overflowWrap: "anywhere" }}>{pathLine}</div>
        </div>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#718096", marginBottom: 2 }}>전체 판정 로직</div>
          <div style={{ fontSize: "clamp(9.5px, 2.7vw, 10.5px)", color: "#718096", lineHeight: 1.3 }}>
            {fullLogic.map((l, i) => <div key={i}>{l}</div>)}
          </div>
        </div>
        <div>
          {notice && <div style={{ fontSize: "clamp(10px, 2.8vw, 11px)", color: "#9C4221", lineHeight: 1.35 }}>{notice}</div>}
          <div style={{ fontSize: 10.5, color: "#A0AEC0", marginTop: 2 }}>적용 로직: {config.logic_version}</div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: onChangeItem ? "1.3fr 1fr 1fr 1fr" : "1.4fr 1fr 1fr", gap: 6, padding: "8px 12px 12px", borderTop: "1px solid var(--hw-border)" }}>
        <button onClick={onSms} disabled={busy} aria-label="문자로 보내기"
          style={{ ...actBtn, background: "var(--hw-gold-200)", color: "#111827", border: "1px solid var(--hw-gold-500)" }}>
          <MessageSquare size={15} /> 문자
        </button>
        <button onClick={onRestart} aria-label="다시 점검"
          style={{ ...actBtn, background: "#fff", color: "#4A5568", border: "1px solid var(--hw-border)" }}>
          <RotateCcw size={14} /> 다시
        </button>
        {onChangeItem && (
          <button onClick={onChangeItem} aria-label="항목 변경"
            style={{ ...actBtn, background: "#fff", color: "#4A5568", border: "1px solid var(--hw-border)" }}>
            <ChevronLeft size={14} /> 항목
          </button>
        )}
        <button onClick={onClose} aria-label="닫기"
          style={{ ...actBtn, background: "#fff", color: "#4A5568", border: "1px solid var(--hw-border)" }}>
          <X size={14} /> 닫기
        </button>
      </div>
    </>
  );
}
