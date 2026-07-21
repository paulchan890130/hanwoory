"use client";
// 관리자 편집기 — 질문 그래프/결과/국가목록/버전/공개여부 설정.
// 미리보기는 공개 컴포넌트(CommonCriteriaSelfCheck)를 그대로 재사용(별도 복제 UI 없음).
// 미리보기 답변/결과도 메모리에만 존재하며 저장/전송하지 않는다.
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { selfCheckApi } from "@/lib/api";
import type { SelfCheckConfig, SelfCheckQuestion, SelfCheckResult } from "@/lib/selfcheck/types";
import { DEFAULT_SELF_CHECK_CONFIG } from "@/lib/selfcheck/defaultConfig";
import { validateConfig, buildFullLogic } from "@/lib/selfcheck/logic";
import { buildSmsBody } from "@/lib/selfcheck/sms";
import CommonCriteriaSelfCheck from "./CommonCriteriaSelfCheck";

// 권장 글자 수(한 화면 유지용). 초과 시 경고만 표시(공개 내용 임의 생략 없음).
const RECO = { item_name: 22, headline: 18, label: 8, question_text: 44, summary: 16, notice: 70 };

const cell: React.CSSProperties = { border: "1px solid var(--hw-border)", borderRadius: 6, padding: "6px 8px", fontSize: 13, width: "100%", boxSizing: "border-box" };
const lbl: React.CSSProperties = { fontSize: 11, fontWeight: 600, color: "var(--hw-text-sub)", display: "block", marginBottom: 3 };

function Counter({ v, max }: { v: string; max: number }) {
  const over = (v || "").length > max;
  return <span style={{ fontSize: 10, color: over ? "#C53030" : "#A0AEC0" }}>{(v || "").length}/{max}{over ? " 초과" : ""}</span>;
}

export default function SelfCheckAdminEditor({ initial, initialPublished }: { initial?: SelfCheckConfig | null; initialPublished?: boolean }) {
  const [cfg, setCfg] = useState<SelfCheckConfig>(initial ?? DEFAULT_SELF_CHECK_CONFIG);
  const [published, setPublished] = useState(!!initialPublished);
  const [preview, setPreview] = useState(false);
  const [saving, setSaving] = useState(false);

  const report = useMemo(() => validateConfig(cfg), [cfg]);
  const targets = useMemo(
    () => [...cfg.questions.map((q) => ({ id: q.id, label: `질문 ${q.display_number} (${q.id})` })),
           ...cfg.results.map((r) => ({ id: r.id, label: `결과 ${r.label || r.headline} (${r.id})` }))],
    [cfg],
  );
  const lengthWarnings = useMemo(() => {
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

  const patch = (p: Partial<SelfCheckConfig>) => setCfg((c) => ({ ...c, ...p }));
  const patchQ = (i: number, p: Partial<SelfCheckQuestion>) =>
    setCfg((c) => ({ ...c, questions: c.questions.map((q, j) => (j === i ? { ...q, ...p } : q)) }));
  const patchR = (i: number, p: Partial<SelfCheckResult>) =>
    setCfg((c) => ({ ...c, results: c.results.map((r, j) => (j === i ? { ...r, ...p } : r)) }));
  const addQ = () => setCfg((c) => ({ ...c, questions: [...c.questions, { id: `q${c.questions.length + 1}`, display_number: `${c.questions.length + 1}`, text: "", summary: "", yes: "", no: "", sort_order: c.questions.length + 1 }] }));
  const addR = () => setCfg((c) => ({ ...c, results: [...c.results, { id: `r${c.results.length + 1}`, headline: "", label: "" }] }));
  const delQ = (i: number) => setCfg((c) => ({ ...c, questions: c.questions.filter((_, j) => j !== i) }));
  const delR = (i: number) => setCfg((c) => ({ ...c, results: c.results.filter((_, j) => j !== i) }));

  const save = async (pub: boolean) => {
    if (pub && report.errors.length) { toast.error("오류를 먼저 수정해야 게시할 수 있습니다."); return; }
    setSaving(true);
    try {
      await selfCheckApi.adminSave(cfg, pub);
      setPublished(pub);
      toast.success(pub ? "게시되었습니다." : "임시 저장되었습니다.");
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: { message?: string } } } })?.response?.data?.detail;
      toast.error(typeof d === "object" && d?.message ? d.message : "저장 실패");
    } finally { setSaving(false); }
  };

  const smsPreview = buildSmsBody(cfg, cfg.questions.slice(0, 1).map((q) => ({ question_id: q.id, display_number: q.display_number, summary: q.summary, answer: "예" as unknown as "yes" })), cfg.results[0]?.id ?? null);

  return (
    <div className="hw-card" style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 20, alignItems: "start" }}>
      {/* 편집 */}
      <div style={{ minWidth: 0 }}>
        <div className="hw-card-title">공통기준 자가점검 설정</div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
          <div>
            <label style={lbl}>점검 항목명 <Counter v={cfg.item_name} max={RECO.item_name} /></label>
            <input style={cell} value={cfg.item_name} onChange={(e) => patch({ item_name: e.target.value })} />
          </div>
          <div>
            <label style={lbl}>로직 버전</label>
            <input style={cell} value={cfg.logic_version} onChange={(e) => patch({ logic_version: e.target.value })} placeholder="CR-1.0" />
          </div>
          <div>
            <label style={lbl}>시작 질문</label>
            <select style={cell} value={cfg.start_question_id} onChange={(e) => patch({ start_question_id: e.target.value })}>
              {cfg.questions.map((q) => <option key={q.id} value={q.id}>{q.display_number} ({q.id})</option>)}
            </select>
          </div>
          <div>
            <label style={lbl}>공통 주의문구 <Counter v={cfg.notice_text || ""} max={RECO.notice} /></label>
            <input style={cell} value={cfg.notice_text || ""} onChange={(e) => patch({ notice_text: e.target.value })} />
          </div>
        </div>

        <div style={{ marginBottom: 12 }}>
          <label style={lbl}>고위험 국가 목록(첫 질문에서 펼침, 한 줄에 하나)</label>
          <textarea style={{ ...cell, height: 60, resize: "vertical" }}
            value={(cfg.country_list || []).join("\n")}
            onChange={(e) => patch({ country_list: e.target.value.split("\n").map((s) => s.trim()).filter(Boolean) })} />
        </div>

        {/* 질문 */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 6 }}>
          <div style={{ fontSize: 13, fontWeight: 700 }}>질문</div>
          <button className="btn-secondary" style={{ fontSize: 12 }} onClick={addQ}>+ 질문 추가</button>
        </div>
        {cfg.questions.map((q, i) => (
          <div key={i} style={{ border: "1px solid var(--hw-border)", borderRadius: 8, padding: 10, margin: "8px 0", background: "#FAFBFC" }}>
            <div style={{ display: "grid", gridTemplateColumns: "80px 90px 1fr auto", gap: 8, alignItems: "end" }}>
              <div><label style={lbl}>id</label><input style={cell} value={q.id} onChange={(e) => patchQ(i, { id: e.target.value })} /></div>
              <div><label style={lbl}>번호</label><input style={cell} value={q.display_number} onChange={(e) => patchQ(i, { display_number: e.target.value })} /></div>
              <div><label style={lbl}>요약 <Counter v={q.summary} max={RECO.summary} /></label><input style={cell} value={q.summary} onChange={(e) => patchQ(i, { summary: e.target.value })} /></div>
              <button onClick={() => delQ(i)} style={{ ...cell, width: "auto", color: "#C53030", cursor: "pointer" }}>삭제</button>
            </div>
            <div style={{ marginTop: 8 }}>
              <label style={lbl}>질문 문구 <Counter v={q.text} max={RECO.question_text} /></label>
              <input style={cell} value={q.text} onChange={(e) => patchQ(i, { text: e.target.value })} />
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 8, marginTop: 8, alignItems: "end" }}>
              <div><label style={lbl}>예 →</label>
                <select style={cell} value={q.yes} onChange={(e) => patchQ(i, { yes: e.target.value })}>
                  <option value="">(선택)</option>{targets.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                </select></div>
              <div><label style={lbl}>아니오 →</label>
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
            <div style={{ display: "grid", gridTemplateColumns: "90px 1fr 100px auto", gap: 8, alignItems: "end" }}>
              <div><label style={lbl}>id</label><input style={cell} value={r.id} onChange={(e) => patchR(i, { id: e.target.value })} /></div>
              <div><label style={lbl}>판정문 <Counter v={r.headline} max={RECO.headline} /></label><input style={cell} value={r.headline} onChange={(e) => patchR(i, { headline: e.target.value })} /></div>
              <div><label style={lbl}>라벨 <Counter v={r.label || ""} max={RECO.label} /></label><input style={cell} value={r.label || ""} onChange={(e) => patchR(i, { label: e.target.value })} /></div>
              <button onClick={() => delR(i)} style={{ ...cell, width: "auto", color: "#C53030", cursor: "pointer" }}>삭제</button>
            </div>
            <div style={{ marginTop: 8 }}>
              <label style={lbl}>결과 주의문구 <Counter v={r.notice_text || ""} max={RECO.notice} /></label>
              <input style={cell} value={r.notice_text || ""} onChange={(e) => patchR(i, { notice_text: e.target.value })} />
            </div>
          </div>
        ))}

        {/* 검증 */}
        <div style={{ marginTop: 12, fontSize: 12 }}>
          {report.errors.length > 0 && (
            <div style={{ background: "#FFF5F5", border: "1px solid #FEB2B2", color: "#C53030", borderRadius: 6, padding: 8 }}>
              <b>오류(게시 불가):</b><ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{report.errors.map((e, i) => <li key={i}>{e}</li>)}</ul>
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

        <div style={{ display: "flex", gap: 8, marginTop: 14, alignItems: "center" }}>
          <button className="btn-secondary" onClick={() => setPreview(true)}>미리보기</button>
          <button className="btn-secondary" disabled={saving} onClick={() => save(false)}>임시 저장</button>
          <button className="btn-primary" disabled={saving || report.errors.length > 0} onClick={() => save(true)}>저장 후 공개</button>
          <span style={{ fontSize: 12, color: published ? "#276749" : "#A0AEC0" }}>{published ? "● 공개 중" : "○ 비공개"}</span>
        </div>
      </div>

      {/* 360×740 미리보기(공개 컴포넌트 재사용) + 문자 본문 미리보기 */}
      <div style={{ position: "sticky", top: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--hw-text-sub)", marginBottom: 6 }}>미리보기 (360×740)</div>
        <div style={{ display: "flex", justifyContent: "center" }}>
          <CommonCriteriaSelfCheck config={cfg} open={preview} onClose={() => setPreview(false)} frame={{ width: 360, height: 740 }} />
          {!preview && (
            <div style={{ width: 360, height: 740, border: "1px dashed var(--hw-border)", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", color: "#A0AEC0", fontSize: 13 }}>
              “미리보기”를 눌러 확인
            </div>
          )}
        </div>
        <div style={{ fontSize: 12, fontWeight: 600, color: "var(--hw-text-sub)", margin: "12px 0 4px" }}>문자 본문 미리보기(전송 안 함)</div>
        <pre style={{ fontSize: 11, background: "#F7FAFC", border: "1px solid var(--hw-border)", borderRadius: 6, padding: 8, whiteSpace: "pre-wrap", maxHeight: 200, overflow: "auto" }}>{smsPreview}</pre>
      </div>
    </div>
  );
}
