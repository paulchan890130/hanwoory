"use client";
// 관리자 편집기 — 다중 항목(번들) 관리. 좌: 항목 목록 + 선택 항목 편집, 우: 미리보기.
// 미리보기는 공개 컴포넌트(CommonCriteriaSelfCheck)를 그대로 재사용(별도 복제 UI 없음).
// 미리보기 답변/결과도 메모리에만 존재하며 저장/전송하지 않는다.
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { selfCheckApi } from "@/lib/api";
import type { SelfCheckConfig, SelfCheckQuestion, SelfCheckResult, SelfCheckItem, SelfCheckBundle } from "@/lib/selfcheck/types";
import { DEFAULT_SELF_CHECK_BUNDLE } from "@/lib/selfcheck/defaultConfig";
import { validateConfig, validateBundle, buildFullLogic } from "@/lib/selfcheck/logic";
import { buildSmsBody } from "@/lib/selfcheck/sms";
import { verifyTuberculosis, isTuberculosisItem, TB_SOURCE_META, TB_CANONICAL_COUNT } from "@/lib/selfcheck/tuberculosis";
import CommonCriteriaSelfCheck from "./CommonCriteriaSelfCheck";

const RECO = { item_name: 22, headline: 18, label: 8, question_text: 44, summary: 16, notice: 90 };

// 저장소가 현재 실제 지원하는 공개 진입 위치(런처가 배치된 곳). 존재하지 않는 위치를 만들지 않는다.
const SUPPORTED_PLACEMENTS: { id: string; label: string }[] = [{ id: "home", label: "홈페이지" }];

// 관리자 미리보기 viewport(모바일 4종).
const PREVIEW_VIEWPORTS = [
  { w: 360, h: 740 }, { w: 375, h: 812 }, { w: 390, h: 844 }, { w: 412, h: 915 },
];

const cell: React.CSSProperties = { border: "1px solid var(--hw-border)", borderRadius: 6, padding: "6px 8px", fontSize: 13, width: "100%", boxSizing: "border-box" };
const lbl: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: "var(--hw-text-sub)", display: "block", marginBottom: 3 };

function Counter({ v, max }: { v: string; max: number }) {
  const over = (v || "").length > max;
  return <span style={{ fontSize: 10, color: over ? "#C53030" : "#A0AEC0" }}>{(v || "").length}/{max}{over ? " 초과" : ""}</span>;
}

function emptyItem(n: number): SelfCheckItem {
  return {
    item_id: `item-${n}`, title: "새 항목", description: null, sort_order: n, is_published: false, popup_enabled: true, placement: [],
    config: { item_name: "새 항목", logic_version: "V-1.0", start_question_id: "q1",
      questions: [{ id: "q1", display_number: "①", text: "", summary: "", yes: "", no: "", sort_order: 1 }],
      results: [{ id: "r_target", headline: "", label: "" }, { id: "r_none", headline: "", label: "" }] },
  };
}

export default function SelfCheckAdminEditor({ initialBundle, obsoleteLegacy = false }: { initialBundle?: SelfCheckBundle | null; obsoleteLegacy?: boolean }) {
  const [bundle, setBundle] = useState<SelfCheckBundle>(
    initialBundle && initialBundle.items?.length ? initialBundle : { schema_version: 2, items: [] },
  );
  const [selIdx, setSelIdx] = useState<number>(0);
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);
  const [previewVpIdx, setPreviewVpIdx] = useState(0); // 기본 360×740
  // 구형(obsolete) 경고는 저장 후 갱신되어야 한다 — 서버 prop 을 초기값으로 내부 state 로 보유.
  const [obsolete, setObsolete] = useState(obsoleteLegacy);
  const [loadedDefaults, setLoadedDefaults] = useState(false); // PDF 기본안 불러오기만 한(미저장) 상태
  useEffect(() => { setObsolete(obsoleteLegacy); setLoadedDefaults(false); }, [obsoleteLegacy]);
  const isLegacy = bundle.items.some((it) => it.item_id === "legacy");

  const sorted = useMemo(() => bundle.items.map((it, i) => ({ it, i })).sort((a, b) => (a.it.sort_order ?? 0) - (b.it.sort_order ?? 0)), [bundle]);
  const bundleReport = useMemo(() => validateBundle(bundle), [bundle]);
  const item: SelfCheckItem | undefined = bundle.items[selIdx];
  const cfg = item?.config;
  const report = useMemo(() => (cfg ? validateConfig(cfg) : { errors: ["항목이 선택되지 않았습니다."], warnings: [] }), [cfg]);
  // 결핵(TB) 항목이면 공식 35개국·출처·폐기문구 검증 상태(공개 조건). 서버가 최종 권위.
  const isTbItem = !!item && isTuberculosisItem(item);
  const tbStatus = useMemo(() => (isTbItem && cfg ? verifyTuberculosis(cfg) : null), [isTbItem, cfg]);

  const targets = useMemo(() => (cfg
    ? [...cfg.questions.map((q) => ({ id: q.id, label: `질문 ${q.display_number} (${q.id})` })),
       ...cfg.results.map((r) => ({ id: r.id, label: `결과 ${r.label || r.headline} (${r.id})` }))]
    : []), [cfg]);

  const lengthWarnings = useMemo(() => {
    if (!cfg) return [];
    const w: string[] = [];
    if ((cfg.item_name || "").length > RECO.item_name) w.push("항목명이 권장 길이를 초과");
    for (const q of cfg.questions) {
      if ((q.text || "").length > RECO.question_text) w.push(`질문 ${q.id} 문구가 김`);
      if ((q.summary || "").length > RECO.summary) w.push(`질문 ${q.id} 요약이 김`);
    }
    for (const r of cfg.results) {
      if ((r.headline || "").length > RECO.headline) w.push(`결과 ${r.id} 판정문이 김(2줄 초과 위험)`);
      if ((r.notice_text || "").length > RECO.notice) w.push(`결과 ${r.id} 주의문구가 김`);
    }
    if (buildFullLogic(cfg).length > 8) w.push("판정 로직 줄 수가 많아 360×740 초과 위험");
    return w;
  }, [cfg]);

  // ── 항목/설정 mutation helpers ──
  const setItem = (i: number, p: Partial<SelfCheckItem>) =>
    setBundle((b) => ({ ...b, items: b.items.map((it, j) => (j === i ? { ...it, ...p } : it)) }));
  // 공개 토글 가드: 결핵(TB) 항목은 공식 35개국·출처 확인이 완료된 경우에만 공개 가능(프론트 편의 검증).
  // 조건 미충족 시 즉시 오류 안내 후 원상복구(상태 미변경 → 컨트롤드 체크박스 자동 복귀).
  const tryTogglePublish = (i: number, checked: boolean) => {
    const it = bundle.items[i];
    if (checked && it && isTuberculosisItem(it) && !verifyTuberculosis(it.config).ok) {
      toast.error("결핵 항목은 공식 35개국 목록과 출처 확인이 완료된 경우에만 공개할 수 있습니다.");
      return;
    }
    setItem(i, { is_published: checked });
  };
  const patchCfg = (p: Partial<SelfCheckConfig>) =>
    setBundle((b) => ({ ...b, items: b.items.map((it, j) => (j === selIdx ? { ...it, config: { ...it.config, ...p } } : it)) }));
  const patchQ = (qi: number, p: Partial<SelfCheckQuestion>) =>
    setBundle((b) => ({ ...b, items: b.items.map((it, j) => (j === selIdx ? { ...it, config: { ...it.config, questions: it.config.questions.map((q, k) => (k === qi ? { ...q, ...p } : q)) } } : it)) }));
  const patchR = (ri: number, p: Partial<SelfCheckResult>) =>
    setBundle((b) => ({ ...b, items: b.items.map((it, j) => (j === selIdx ? { ...it, config: { ...it.config, results: it.config.results.map((r, k) => (k === ri ? { ...r, ...p } : r)) } } : it)) }));
  const addQ = () => cfg && patchCfg({ questions: [...cfg.questions, { id: `q${cfg.questions.length + 1}`, display_number: `${cfg.questions.length + 1}`, text: "", summary: "", yes: "", no: "", sort_order: cfg.questions.length + 1 }] });
  const addR = () => cfg && patchCfg({ results: [...cfg.results, { id: `r${cfg.results.length + 1}`, headline: "", label: "" }] });
  const delQ = (qi: number) => cfg && patchCfg({ questions: cfg.questions.filter((_, k) => k !== qi) });
  const delR = (ri: number) => cfg && patchCfg({ results: cfg.results.filter((_, k) => k !== ri) });

  const addItem = () => setBundle((b) => { const it = emptyItem(b.items.length + 1); return { ...b, items: [...b.items, it] }; });
  const delItem = (i: number) => setBundle((b) => {
    const items = b.items.filter((_, j) => j !== i);
    setSelIdx((s) => Math.max(0, Math.min(s, items.length - 1)));
    return { ...b, items };
  });
  const moveItem = (i: number, dir: -1 | 1) => setBundle((b) => {
    const items = [...b.items];
    const j = i + dir;
    if (j < 0 || j >= items.length) return b;
    [items[i], items[j]] = [items[j], items[i]];
    items.forEach((it, k) => (it.sort_order = k + 1));
    setSelIdx(j);
    return { ...b, items };
  });

  const loadDefaults = () => {
    if (!window.confirm("현재 편집 중인 임시 설정을 PDF 기준 기본안으로 교체합니다.\nDB에는 저장 버튼을 누르기 전까지 반영되지 않습니다.\n계속하시겠습니까?")) return;
    setBundle(JSON.parse(JSON.stringify(DEFAULT_SELF_CHECK_BUNDLE)));
    setSelIdx(0);
    setLoadedDefaults(true);   // 불러오기만 한 미저장 상태 — 운영 DB 는 아직 이전 설정
    toast.success("PDF 기준 3개 기본 항목을 불러왔습니다. (미저장)");
  };

  const save = async () => {
    // 게시(is_published)로 설정된 항목에 그래프 오류가 있으면 서버가 400. 사전 안내.
    const blocked = bundle.items.filter((it) => it.is_published && (bundleReport.itemErrors[it.item_id]?.length));
    if (blocked.length) { toast.error(`게시하려는 항목의 오류를 먼저 수정하세요: ${blocked.map((b) => b.title).join(", ")}`); return; }
    if (bundleReport.errors.length) { toast.error(bundleReport.errors[0]); return; }
    // 결핵(TB) 항목을 공개하려면 공식 35개국·출처 확인 완료 필수(서버도 TB_COUNTRY_LIST_NOT_VERIFIED 로 400).
    const tbBlocked = bundle.items.filter((it) => it.is_published && isTuberculosisItem(it) && !verifyTuberculosis(it.config).ok);
    if (tbBlocked.length) { toast.error("결핵 항목은 공식 35개국 목록과 출처 확인이 완료된 경우에만 공개할 수 있습니다."); return; }
    setSaving(true);
    try {
      await selfCheckApi.adminSave(bundle);
      const pub = bundle.items.filter((it) => it.is_published).length;
      // 저장 성공 → 현재 저장본이 새 bundle 이므로 구형(obsolete) 경고 제거(새로고침 없이 갱신).
      setObsolete(false);
      setLoadedDefaults(false);
      toast.success(pub ? `저장 완료 · 공개 항목 ${pub}개` : "저장 완료 (모두 비공개)");
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail;
      toast.error(typeof d === "object" && d?.message ? d.message : "저장 실패");
    } finally { setSaving(false); }
  };

  const smsPreview = cfg ? buildSmsBody(cfg, cfg.questions.slice(0, 1).map((q) => ({ question_id: q.id, display_number: q.display_number, summary: q.summary, answer: "예" as unknown as "yes" })), cfg.results[0]?.id ?? null) : "";

  const previewItems = item ? [item] : [];

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 20, alignItems: "flex-start" }}>
      {obsolete && (
        <div data-testid="selfcheck-obsolete-banner" style={{ flex: "1 1 100%", background: "#FFF5F5", border: "1px solid #FEB2B2",
          color: "#C53030", borderRadius: 8, padding: "10px 14px", fontSize: 13, lineHeight: 1.6 }}>
          현재 공개 설정은 <b>폐기 대상인 구형 결핵 판정 로직</b>입니다. 공개 홈페이지에서는 안전을 위해 표시되지 않습니다.
          ‘PDF 기준 3개 기본 항목 불러오기’ 후 내용을 검토하고 저장하세요. 자동으로 운영 설정을 변경하지 않습니다.
          {loadedDefaults && (
            <div data-testid="selfcheck-obsolete-unsaved" style={{ marginTop: 6, fontWeight: 600 }}>
              PDF 기준 기본안을 불러왔습니다(미저장). 운영 DB 에는 아직 구형 설정이 남아 있으며 공개 API 에서는 안전 차단 중입니다.
              저장해야 공개 설정이 교체됩니다.
            </div>
          )}
        </div>
      )}
      {isLegacy && !obsolete && (
        <div data-testid="selfcheck-legacy-banner" style={{ flex: "1 1 100%", background: "#FFFAF0", border: "1px solid #FBD38D",
          color: "#9C4221", borderRadius: 8, padding: "10px 14px", fontSize: 13, lineHeight: 1.6 }}>
          현재 저장본은 <b>기존 단일 자가점검 설정</b>입니다. PDF 기준 3개 항목을 적용하려면
          ‘PDF 기준 3개 기본 항목 불러오기’를 누른 뒤 내용을 검토하고 저장해야 합니다.
          자동으로 운영 설정을 변경하지 않습니다.
        </div>
      )}
      {/* 편집 pane */}
      <div className="hw-card" style={{ flex: "1 1 440px", minWidth: 0 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <div className="hw-card-title" style={{ margin: 0 }}>공통기준 자가점검 설정 (항목 {bundle.items.length}개)</div>
          <button className="btn-secondary" style={{ fontSize: 12 }} onClick={loadDefaults}>PDF 기준 3개 기본 항목 불러오기</button>
        </div>

        {/* 항목 목록 */}
        <div style={{ marginTop: 10, border: "1px solid var(--hw-border)", borderRadius: 8, overflow: "hidden" }}>
          {sorted.length === 0 && (
            <div style={{ padding: 12, fontSize: 13, color: "var(--hw-text-sub)" }}>
              항목이 없습니다. “PDF 기준 3개 기본 항목 불러오기” 또는 아래 “+ 항목 추가”로 시작하세요.
            </div>
          )}
          {sorted.map(({ it, i }) => (
            <div key={it.item_id + i} onClick={() => setSelIdx(i)}
              style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", cursor: "pointer",
                borderBottom: "1px solid var(--hw-border)", background: i === selIdx ? "var(--hw-gold-50)" : "#fff", flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: "#111827", flex: "1 1 140px", minWidth: 0 }}>{it.title || it.config.item_name || "(제목 없음)"}</span>
              <span style={{ fontSize: 11, color: "#A0AEC0" }}>{it.config.logic_version}</span>
              <label style={{ fontSize: 11, display: "inline-flex", alignItems: "center", gap: 3 }} onClick={(e) => e.stopPropagation()}>
                <input type="checkbox" data-testid={`publish-${it.item_id}`} checked={it.is_published} onChange={(e) => tryTogglePublish(i, e.target.checked)} /> 공개
              </label>
              <label style={{ fontSize: 11, display: "inline-flex", alignItems: "center", gap: 3 }} onClick={(e) => e.stopPropagation()}>
                <input type="checkbox" checked={it.popup_enabled} onChange={(e) => setItem(i, { popup_enabled: e.target.checked })} /> 팝업
              </label>
              <span onClick={(e) => e.stopPropagation()} style={{ display: "inline-flex", gap: 2 }}>
                <button onClick={() => moveItem(i, -1)} aria-label="위로" style={{ ...cell, width: "auto", padding: "2px 6px", cursor: "pointer" }}>↑</button>
                <button onClick={() => moveItem(i, 1)} aria-label="아래로" style={{ ...cell, width: "auto", padding: "2px 6px", cursor: "pointer" }}>↓</button>
                <button onClick={() => delItem(i)} aria-label="삭제" style={{ ...cell, width: "auto", padding: "2px 6px", color: "#C53030", cursor: "pointer" }}>✕</button>
              </span>
            </div>
          ))}
          <div style={{ padding: 8, textAlign: "right" }}>
            <button className="btn-secondary" style={{ fontSize: 12 }} onClick={addItem}>+ 항목 추가</button>
          </div>
        </div>
        {bundleReport.errors.length > 0 && (
          <div style={{ marginTop: 8, background: "#FFF5F5", border: "1px solid #FEB2B2", color: "#C53030", borderRadius: 6, padding: 8, fontSize: 12 }}>
            {bundleReport.errors.join(" · ")}
          </div>
        )}

        {/* 선택 항목 편집 */}
        {cfg && item && (
          <div style={{ marginTop: 14, borderTop: "2px solid var(--hw-gold-200)", paddingTop: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>선택 항목 편집</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10, marginBottom: 12 }}>
              <div><label style={lbl}>항목 id</label><input style={cell} value={item.item_id} onChange={(e) => setItem(selIdx, { item_id: e.target.value })} /></div>
              <div><label style={lbl}>제목</label><input style={cell} value={item.title} onChange={(e) => setItem(selIdx, { title: e.target.value })} /></div>
              <div><label style={lbl}>점검 항목명 <Counter v={cfg.item_name} max={RECO.item_name} /></label><input style={cell} value={cfg.item_name} onChange={(e) => patchCfg({ item_name: e.target.value })} /></div>
              <div><label style={lbl}>로직 버전</label><input style={cell} value={cfg.logic_version} onChange={(e) => patchCfg({ logic_version: e.target.value })} placeholder="CR-1.0" /></div>
              <div><label style={lbl}>시작 질문</label>
                <select style={cell} value={cfg.start_question_id} onChange={(e) => patchCfg({ start_question_id: e.target.value })}>
                  {cfg.questions.map((q) => <option key={q.id} value={q.id}>{q.display_number} ({q.id})</option>)}
                </select></div>
              <div><label style={lbl}>공통 주의문구 <Counter v={cfg.notice_text || ""} max={RECO.notice} /></label><input style={cell} value={cfg.notice_text || ""} onChange={(e) => patchCfg({ notice_text: e.target.value })} /></div>
            </div>

            {/* 항목 설명 + 노출 위치 */}
            <div style={{ marginBottom: 12 }}>
              <label style={lbl}>항목 설명</label>
              <textarea data-testid="item-description" style={{ ...cell, height: 48, resize: "vertical" }}
                value={item.description || ""} onChange={(e) => setItem(selIdx, { description: e.target.value })} />
            </div>
            <div style={{ marginBottom: 12 }}>
              <label style={lbl}>노출 위치(선택 안 하면 어느 런처에도 표시되지 않음)</label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                {SUPPORTED_PLACEMENTS.map((p) => {
                  const on = (item.placement || []).includes(p.id);
                  return (
                    <label key={p.id} style={{ fontSize: 12, display: "inline-flex", alignItems: "center", gap: 4 }}>
                      <input type="checkbox" data-testid={`placement-${p.id}`} checked={on}
                        onChange={(e) => setItem(selIdx, {
                          placement: e.target.checked
                            ? Array.from(new Set([...(item.placement || []), p.id]))
                            : (item.placement || []).filter((x) => x !== p.id),
                        })} /> {p.label}
                    </label>
                  );
                })}
              </div>
            </div>

            <div style={{ marginBottom: 12 }}>
              <label style={lbl}>고위험 국가 목록(첫 질문에서 펼침, 한 줄에 하나 · 결과 화면에는 미출력)</label>
              <textarea style={{ ...cell, height: 60, resize: "vertical" }}
                value={(cfg.country_list || []).join("\n")}
                onChange={(e) => patchCfg({ country_list: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })} />
            </div>

            {/* 결핵(TB) 항목: 공식 35개국·출처 확인 상태 + 출처 metadata 편집 */}
            {isTbItem && tbStatus && (
              <div data-testid="tb-status" style={{ marginBottom: 12, border: "1px solid var(--hw-gold-200)", borderRadius: 8, padding: 10, background: "var(--hw-gold-50)" }}>
                <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 6 }}>결핵 고위험 국가 공식 확인</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: 6, fontSize: 12, marginBottom: 8 }}>
                  <span data-testid="tb-status-count">목록: <b style={{ color: tbStatus.count === TB_CANONICAL_COUNT ? "#276749" : "#C53030" }}>{tbStatus.count}/{TB_CANONICAL_COUNT}</b></span>
                  <span data-testid="tb-status-dup">중복: <b style={{ color: tbStatus.dup === 0 ? "#276749" : "#C53030" }}>{tbStatus.dup}</b></span>
                  <span data-testid="tb-status-match">공식 set 일치: <b style={{ color: tbStatus.matchesCanonical ? "#276749" : "#C53030" }}>{tbStatus.matchesCanonical ? "예" : "아니오"}</b></span>
                  <span data-testid="tb-status-source">출처 정보: <b style={{ color: tbStatus.hasSource ? "#276749" : "#C53030" }}>{tbStatus.hasSource ? "완료" : "미완료"}</b></span>
                </div>
                {!tbStatus.ok && (
                  <div style={{ fontSize: 12, color: "#C53030", marginBottom: 8, lineHeight: 1.5 }}>
                    공식 35개국 목록과 출처 확인이 완료된 경우에만 공개할 수 있습니다.
                    {tbStatus.banned && <div>· 폐기된 과거 문구가 포함되어 있습니다(공개 불가).</div>}
                  </div>
                )}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8 }}>
                  <div><label style={lbl}>출처 제목</label><input data-testid="tb-source-title" style={cell} value={cfg.country_list_source_title || ""} onChange={(e) => patchCfg({ country_list_source_title: e.target.value })} /></div>
                  <div><label style={lbl}>출처 기준·일자</label><input data-testid="tb-source-date" style={cell} value={cfg.country_list_source_date || ""} onChange={(e) => patchCfg({ country_list_source_date: e.target.value })} /></div>
                  <div><label style={lbl}>최종 대조일</label><input data-testid="tb-verified-at" style={cell} value={cfg.country_list_verified_at || ""} onChange={(e) => patchCfg({ country_list_verified_at: e.target.value })} /></div>
                  <div><label style={lbl}>대조 기준 설명</label><input data-testid="tb-source-note" style={cell} value={cfg.country_list_source_note || ""} onChange={(e) => patchCfg({ country_list_source_note: e.target.value })} /></div>
                </div>
                <div style={{ marginTop: 8, fontSize: 11, color: "var(--hw-text-sub)", lineHeight: 1.5 }}>
                  공식 목록 확인: {TB_CANONICAL_COUNT}개국 · 확인 기준: {TB_SOURCE_META.country_list_source_date} · 최종 대조: {cfg.country_list_verified_at || TB_SOURCE_META.country_list_verified_at}
                </div>
                <button className="btn-secondary" style={{ fontSize: 11, marginTop: 6 }}
                  onClick={() => patchCfg({
                    country_list_source_title: cfg.country_list_source_title || TB_SOURCE_META.country_list_source_title,
                    country_list_source_date: cfg.country_list_source_date || TB_SOURCE_META.country_list_source_date,
                    country_list_verified_at: cfg.country_list_verified_at || TB_SOURCE_META.country_list_verified_at,
                    country_list_source_note: cfg.country_list_source_note || TB_SOURCE_META.country_list_source_note,
                  })}>출처 기본값 채우기</button>
              </div>
            )}

            {/* 질문 */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 6 }}>
              <div style={{ fontSize: 13, fontWeight: 700 }}>질문</div>
              <button className="btn-secondary" style={{ fontSize: 12 }} onClick={addQ}>+ 질문 추가</button>
            </div>
            {cfg.questions.map((q, i) => (
              <div key={i} style={{ border: "1px solid var(--hw-border)", borderRadius: 8, padding: 10, margin: "8px 0", background: "#FAFBFC" }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
                  <div style={{ flex: "0 0 70px" }}><label style={lbl}>id</label><input style={cell} value={q.id} onChange={(e) => patchQ(i, { id: e.target.value })} /></div>
                  <div style={{ flex: "0 0 70px" }}><label style={lbl}>번호</label><input style={cell} value={q.display_number} onChange={(e) => patchQ(i, { display_number: e.target.value })} /></div>
                  <div style={{ flex: "1 1 160px", minWidth: 0 }}><label style={lbl}>요약 <Counter v={q.summary} max={RECO.summary} /></label><input style={cell} value={q.summary} onChange={(e) => patchQ(i, { summary: e.target.value })} /></div>
                  <button onClick={() => delQ(i)} style={{ ...cell, width: "auto", color: "#C53030", cursor: "pointer" }}>삭제</button>
                </div>
                <div style={{ marginTop: 8 }}>
                  <label style={lbl}>질문 문구 <Counter v={q.text} max={RECO.question_text} /></label>
                  <input style={cell} value={q.text} onChange={(e) => patchQ(i, { text: e.target.value })} />
                </div>
                <div style={{ marginTop: 8 }}>
                  <label style={lbl}>도움말(선택)</label>
                  <input style={cell} value={q.help || ""} onChange={(e) => patchQ(i, { help: e.target.value })} />
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 8, alignItems: "flex-end" }}>
                  <div style={{ flex: "1 1 160px", minWidth: 0 }}><label style={lbl}>예 →</label>
                    <select style={cell} value={q.yes} onChange={(e) => patchQ(i, { yes: e.target.value })}>
                      <option value="">(선택)</option>{targets.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                    </select></div>
                  <div style={{ flex: "1 1 160px", minWidth: 0 }}><label style={lbl}>아니오 →</label>
                    <select style={cell} value={q.no} onChange={(e) => patchQ(i, { no: e.target.value })}>
                      <option value="">(선택)</option>{targets.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                    </select></div>
                  <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 4, paddingBottom: 6 }}>
                    <input type="checkbox" checked={!!q.country_list_ref} onChange={(e) => patchQ(i, { country_list_ref: e.target.checked })} /> 국가목록
                  </label>
                </div>
              </div>
            ))}

            {/* 결과 */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10 }}>
              <div style={{ fontSize: 13, fontWeight: 700 }}>결과</div>
              <button className="btn-secondary" style={{ fontSize: 12 }} onClick={addR}>+ 결과 추가</button>
            </div>
            {cfg.results.map((r, i) => (
              <div key={i} style={{ border: "1px solid var(--hw-border)", borderRadius: 8, padding: 10, margin: "8px 0", background: "#FAFBFC" }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
                  <div style={{ flex: "0 0 100px" }}><label style={lbl}>id</label><input style={cell} value={r.id} onChange={(e) => patchR(i, { id: e.target.value })} /></div>
                  <div style={{ flex: "1 1 160px", minWidth: 0 }}><label style={lbl}>판정문 <Counter v={r.headline} max={RECO.headline} /></label><input style={cell} value={r.headline} onChange={(e) => patchR(i, { headline: e.target.value })} /></div>
                  <div style={{ flex: "0 0 110px" }}><label style={lbl}>라벨 <Counter v={r.label || ""} max={RECO.label} /></label><input style={cell} value={r.label || ""} onChange={(e) => patchR(i, { label: e.target.value })} /></div>
                  <button onClick={() => delR(i)} style={{ ...cell, width: "auto", color: "#C53030", cursor: "pointer" }}>삭제</button>
                </div>
                <div style={{ marginTop: 8 }}>
                  <label style={lbl}>결과 주의문구 <Counter v={r.notice_text || ""} max={RECO.notice} /></label>
                  <input style={cell} value={r.notice_text || ""} onChange={(e) => patchR(i, { notice_text: e.target.value })} />
                </div>
              </div>
            ))}

            {/* 항목 검증 */}
            <div style={{ marginTop: 12, fontSize: 12 }}>
              {report.errors.length > 0 && (
                <div style={{ background: "#FFF5F5", border: "1px solid #FEB2B2", color: "#C53030", borderRadius: 6, padding: 8 }}>
                  <b>오류(공개 불가):</b><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{report.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
                </div>
              )}
              {(report.warnings.length > 0 || lengthWarnings.length > 0) && (
                <div style={{ background: "#FFFAF0", border: "1px solid #FBD38D", color: "#9C4221", borderRadius: 6, padding: 8, marginTop: 6 }}>
                  <b>경고:</b><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{[...report.warnings, ...lengthWarnings].map((w, i) => <li key={i}>{w}</li>)}</ul>
                </div>
              )}
              {report.errors.length === 0 && report.warnings.length === 0 && lengthWarnings.length === 0 && (
                <div style={{ color: "#276749" }}>✓ 구조 검증 통과</div>
              )}
            </div>
          </div>
        )}

        <div style={{ display: "flex", gap: 8, marginTop: 14, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn-secondary" disabled={!item} onClick={() => setPreview(true)}>미리보기</button>
          <button className="btn-primary" disabled={saving} onClick={save}>저장(공개 상태 반영)</button>
          <span style={{ fontSize: 12, color: "var(--hw-text-sub)" }}>공개 항목 {bundle.items.filter((it) => it.is_published).length}개</span>
        </div>
      </div>

      {/* 미리보기 pane (공개 컴포넌트 재사용) */}
      {(() => {
        const vp = PREVIEW_VIEWPORTS[previewVpIdx];
        const scale = Math.min(1, 360 / vp.w);           // 좁은 관리자 화면에서 가로 스크롤 방지(외부 축소)
        const boxW = Math.round(vp.w * scale), boxH = Math.round(vp.h * scale);
        return (
          <div style={{ flex: "0 0 360px", maxWidth: "100%", position: "sticky", top: 12 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--hw-text-sub)", marginBottom: 6 }}>
              미리보기{item ? ` — ${item.title || item.config.item_name}` : ""}
            </div>
            {/* viewport 선택(내부 레이아웃 계산은 선택한 원본 크기 기준, 외부 wrapper 만 축소) */}
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
              {PREVIEW_VIEWPORTS.map((v, i) => (
                <button key={`${v.w}x${v.h}`} data-testid={`preview-vp-${v.w}`} onClick={() => setPreviewVpIdx(i)}
                  className={i === previewVpIdx ? "btn-primary" : "btn-secondary"} style={{ fontSize: 11, padding: "4px 8px" }}>
                  {v.w}×{v.h}
                </button>
              ))}
            </div>
            <div style={{ display: "flex", justifyContent: "center", maxWidth: "100%" }}>
              {item && preview ? (
                <div style={{ width: boxW, height: boxH, maxWidth: "100%", overflow: "hidden" }}>
                  <div style={{ width: vp.w, height: vp.h, transform: `scale(${scale})`, transformOrigin: "top left" }}>
                    <CommonCriteriaSelfCheck items={previewItems} open onClose={() => setPreview(false)} frame={{ width: vp.w, height: vp.h }} />
                  </div>
                </div>
              ) : (
                <div style={{ width: boxW, height: boxH, maxWidth: "100%", boxSizing: "border-box", border: "1px dashed var(--hw-border)", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", color: "#A0AEC0", fontSize: 13, textAlign: "center", padding: 8 }}>
                  {item ? "“미리보기”를 눌러 확인" : "편집할 항목을 선택하세요"}
                </div>
              )}
            </div>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--hw-text-sub)", margin: "12px 0 4px" }}>문자 본문 미리보기(전송 안 함)</div>
            <pre style={{ fontSize: 11, background: "#F7FAFC", border: "1px solid var(--hw-border)", borderRadius: 6, padding: 8, whiteSpace: "pre-wrap", maxHeight: 200, overflow: "auto" }}>{smsPreview}</pre>
          </div>
        );
      })()}
    </div>
  );
}
