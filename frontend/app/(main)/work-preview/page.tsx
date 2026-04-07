"use client";
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { quickDocApi, type WorkPreviewData } from "@/lib/api";
import {
  Eye, ChevronRight, FileText, Paperclip, MessageSquare,
  ClipboardList, FileEdit, Clock, AlertCircle, Copy, ArrowRight,
} from "lucide-react";

// ── 색상 상수 ─────────────────────────────────────────────────────────────────
const GOLD = "#F5A623";
const GOLD_LIGHT = "rgba(245,166,35,0.10)";
const BORDER = "#E2E8F0";

// ── 로컬 타입 ─────────────────────────────────────────────────────────────────
interface Sel {
  category: string;
  minwon: string;
  kind: string;
  detail: string;
}
const EMPTY: Sel = { category: "", minwon: "", kind: "", detail: "" };

// ─────────────────────────────────────────────────────────────────────────────
export default function WorkPreviewPage() {
  const router = useRouter();
  const [sel, setSel] = useState<Sel>(EMPTY);
  const [smsCopied, setSmsCopied] = useState(false);

  // ── 선택 트리 로드 ────────────────────────────────────────────────────────
  const { data: tree } = useQuery({
    queryKey: ["quick-doc", "tree"],
    queryFn: () => quickDocApi.getTree().then((r) => r.data),
    staleTime: 10 * 60 * 1000,
  });

  // ── 미리보기 데이터 로드 (category + minwon 확정 후) ──────────────────────
  const previewEnabled = !!(sel.category && sel.minwon);
  const { data: preview, isFetching: previewLoading } = useQuery({
    queryKey: ["work-preview", sel.category, sel.minwon, sel.kind, sel.detail],
    queryFn: () =>
      quickDocApi.getPreview(sel.category, sel.minwon, sel.kind, sel.detail).then((r) => r.data),
    enabled: previewEnabled,
    staleTime: 5 * 60 * 1000,
  });

  // ── 상위 선택 변경 시 하위 초기화 ────────────────────────────────────────
  const setCategory = (v: string) => setSel({ category: v, minwon: "", kind: "", detail: "" });
  const setMinwon = (v: string) => setSel((s) => ({ ...s, minwon: v, kind: "", detail: "" }));
  const setKind = (v: string) => setSel((s) => ({ ...s, kind: v, detail: "" }));
  const setDetail = (v: string) => setSel((s) => ({ ...s, detail: v }));

  // ── 파생 옵션 ────────────────────────────────────────────────────────────
  const minwonOptions = tree ? (tree.minwon[sel.category] ?? []) : [];
  const kindOptions = tree ? (tree.types[`${sel.category}|${sel.minwon}`] ?? []) : [];
  const detailOptions = tree
    ? (tree.subtypes[`${sel.category}|${sel.minwon}|${sel.kind}`] ?? [])
    : [];

  // kind "x" 는 "없음"을 의미
  const kindIsNone = kindOptions.length === 1 && kindOptions[0] === "x";
  useEffect(() => {
    if (kindIsNone && sel.kind !== "x") setSel((s) => ({ ...s, kind: "x", detail: "" }));
  }, [kindIsNone, sel.kind]);

  // ── SMS 복사 ─────────────────────────────────────────────────────────────
  const handleSmsCopy = () => {
    if (!preview?.sms_template) return;
    navigator.clipboard.writeText(preview.sms_template).then(() => {
      setSmsCopied(true);
      setTimeout(() => setSmsCopied(false), 2000);
      toast.success("SMS 템플릿이 복사되었습니다.");
    });
  };

  // ── 업무 등록으로 이동 ───────────────────────────────────────────────────
  const handleStartWork = () => {
    const params = new URLSearchParams();
    if (preview?.category) params.set("category", preview.category);
    if (preview?.minwon) params.set("work", `${preview.minwon} ${preview.kind}${preview.detail ? `-${preview.detail}` : ""}`);
    router.push(`/tasks?${params.toString()}`);
  };

  // ── 문서자동작성으로 이동 ────────────────────────────────────────────────
  const handleGoDocGen = () => {
    router.push("/quick-doc");
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* 페이지 헤더 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Eye size={18} style={{ color: GOLD }} />
        <h1 className="hw-page-title">업무 미리보기</h1>
      </div>

      <div style={{ display: "flex", gap: 16, alignItems: "flex-start", flexWrap: "wrap" }}>

        {/* ── 좌측: 3단계 선택 패널 ─────────────────────────────────────── */}
        <div
          className="hw-card"
          style={{ width: 210, flexShrink: 0, padding: "16px 0" }}
        >
          <div style={{ padding: "0 16px 10px", fontSize: 11, fontWeight: 700, color: "#A0AEC0", letterSpacing: "0.06em", textTransform: "uppercase" }}>
            업무 선택
          </div>

          {/* 1. 업무 분류 */}
          <SectionLabel>1. 업무 분류</SectionLabel>
          {tree?.categories.map((cat) => (
            <SelBtn
              key={cat}
              label={cat}
              active={sel.category === cat}
              onClick={() => setCategory(cat)}
            />
          ))}

          {/* 2. 업무 항목 */}
          {sel.category && (
            <>
              <div style={{ margin: "10px 12px 4px", borderTop: `1px solid ${BORDER}` }} />
              <SectionLabel>2. 업무 항목</SectionLabel>
              {minwonOptions.map((m) => (
                <SelBtn
                  key={m}
                  label={m}
                  active={sel.minwon === m}
                  onClick={() => setMinwon(m)}
                />
              ))}
            </>
          )}

          {/* 3. 세부 코드 (kind) */}
          {sel.minwon && !kindIsNone && kindOptions.length > 0 && (
            <>
              <div style={{ margin: "10px 12px 4px", borderTop: `1px solid ${BORDER}` }} />
              <SectionLabel>3. 세부 코드</SectionLabel>
              {kindOptions.map((k) => (
                <SelBtn
                  key={k}
                  label={k}
                  active={sel.kind === k}
                  onClick={() => setKind(k)}
                />
              ))}
            </>
          )}

          {/* 3b. 세부 번호 (detail) */}
          {sel.kind && sel.kind !== "x" && detailOptions.length > 0 && (
            <>
              <div style={{ margin: "10px 12px 4px", borderTop: `1px solid ${BORDER}` }} />
              <SectionLabel>세부 번호</SectionLabel>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, padding: "2px 12px 8px" }}>
                {detailOptions.map((d) => (
                  <button
                    key={d}
                    onClick={() => setDetail(d)}
                    style={{
                      padding: "3px 10px",
                      borderRadius: 6,
                      border: `1px solid ${sel.detail === d ? GOLD : BORDER}`,
                      background: sel.detail === d ? GOLD_LIGHT : "transparent",
                      color: sel.detail === d ? "#A0660A" : "#4A5568",
                      fontSize: 12,
                      fontWeight: sel.detail === d ? 700 : 400,
                      cursor: "pointer",
                    }}
                  >
                    {d}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        {/* ── 우측: 미리보기 패널 ──────────────────────────────────────────── */}
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 12 }}>

          {/* 선택 브레드크럼 / 요약 카드 */}
          <div
            className="hw-card"
            style={{
              padding: "14px 18px",
              background: previewEnabled ? GOLD_LIGHT : "var(--hw-surface)",
              border: `1px solid ${previewEnabled ? GOLD : BORDER}`,
            }}
          >
            {!previewEnabled ? (
              <div style={{ fontSize: 13, color: "#A0AEC0", textAlign: "center", padding: "6px 0" }}>
                좌측에서 업무 분류와 항목을 선택하세요.
              </div>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: GOLD }}>{sel.category}</span>
                {sel.minwon && <><ChevronRight size={12} style={{ color: "#A0AEC0" }} /><span style={{ fontSize: 12, fontWeight: 600, color: "#4A5568" }}>{sel.minwon}</span></>}
                {sel.kind && sel.kind !== "x" && <><ChevronRight size={12} style={{ color: "#A0AEC0" }} /><span style={{ fontSize: 12, fontWeight: 600, color: "#4A5568" }}>{sel.kind}{sel.detail ? `-${sel.detail}` : ""}</span></>}
                {preview?.summary && (
                  <span style={{ marginLeft: 6, fontSize: 13, fontWeight: 700, color: "#2D3748" }}>— {preview.summary}</span>
                )}
              </div>
            )}
          </div>

          {/* 미리보기 본문 */}
          {previewLoading ? (
            <div className="hw-card" style={{ fontSize: 13, color: "#A0AEC0", padding: "28px 0", textAlign: "center" }}>
              로드 중...
            </div>
          ) : preview && previewEnabled ? (
            <>
              {/* 개요 */}
              <div className="hw-card" style={{ padding: "18px 20px" }}>
                <SectionTitle icon={<Eye size={14} />} label="업무 개요" />
                <p style={{ fontSize: 13, lineHeight: 1.85, color: "#4A5568", marginTop: 8 }}>
                  {preview.description || "개요 정보가 준비 중입니다."}
                </p>

                {/* 예상 처리일 */}
                {preview.typical_days > 0 && (
                  <div style={{ display: "inline-flex", alignItems: "center", gap: 5, marginTop: 12, padding: "4px 12px", borderRadius: 20, background: "#EBF8FF", border: "1px solid #BEE3F8" }}>
                    <Clock size={12} style={{ color: "#3182CE" }} />
                    <span style={{ fontSize: 12, color: "#2C5282", fontWeight: 600 }}>
                      예상 처리 {preview.typical_days}일
                    </span>
                  </div>
                )}
              </div>

              {/* 진행 절차 */}
              {preview.process.length > 0 && (
                <div className="hw-card" style={{ padding: "18px 20px" }}>
                  <SectionTitle icon={<ClipboardList size={14} />} label="진행 절차" />
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
                    {preview.process.map((step, i) => (
                      <div key={i} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <div style={{
                          display: "flex", alignItems: "center", justifyContent: "center",
                          width: 20, height: 20, borderRadius: "50%",
                          background: GOLD, color: "#fff",
                          fontSize: 10, fontWeight: 700, flexShrink: 0,
                        }}>{i + 1}</div>
                        <span style={{ fontSize: 12, color: "#2D3748" }}>{step}</span>
                        {i < preview.process.length - 1 && (
                          <ArrowRight size={12} style={{ color: "#CBD5E0", marginLeft: 2 }} />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 유의사항 */}
              {preview.caution && (
                <div
                  className="hw-card"
                  style={{ padding: "14px 18px", background: "#FFFBEB", border: "1px solid #FBD38D" }}
                >
                  <div style={{ display: "flex", gap: 8, alignItems: "flex-start" }}>
                    <AlertCircle size={14} style={{ color: "#D69E2E", flexShrink: 0, marginTop: 2 }} />
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: "#975A16", marginBottom: 4 }}>유의사항</div>
                      <p style={{ fontSize: 12, color: "#744210", lineHeight: 1.75, margin: 0 }}>{preview.caution}</p>
                    </div>
                  </div>
                </div>
              )}

              {/* 서식·첨부 2-pane */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                {/* 서식 서류 */}
                <div className="hw-card" style={{ padding: "16px 18px" }}>
                  <SectionTitle icon={<FileText size={14} />} label="서식 서류" />
                  {preview.form_docs.length === 0 ? (
                    <p style={{ fontSize: 12, color: "#A0AEC0", marginTop: 8 }}>준비 중</p>
                  ) : (
                    <ul style={{ listStyle: "none", padding: 0, margin: "10px 0 0", display: "flex", flexDirection: "column", gap: 5 }}>
                      {preview.form_docs.map((doc) => (
                        <li key={doc} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#4A5568" }}>
                          <div style={{ width: 6, height: 6, borderRadius: "50%", background: GOLD, flexShrink: 0 }} />
                          {doc}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {/* 대행 첨부 */}
                <div className="hw-card" style={{ padding: "16px 18px" }}>
                  <SectionTitle icon={<Paperclip size={14} />} label="대행 서류" />
                  {preview.attach_docs.length === 0 ? (
                    <p style={{ fontSize: 12, color: "#A0AEC0", marginTop: 8 }}>없음</p>
                  ) : (
                    <ul style={{ listStyle: "none", padding: 0, margin: "10px 0 0", display: "flex", flexDirection: "column", gap: 5 }}>
                      {preview.attach_docs.map((doc) => (
                        <li key={doc} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#4A5568" }}>
                          <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#A0AEC0", flexShrink: 0 }} />
                          {doc}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              {/* SMS 템플릿 */}
              {preview.sms_template && (
                <div className="hw-card" style={{ padding: "16px 18px" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                    <SectionTitle icon={<MessageSquare size={14} />} label="SMS 템플릿" />
                    <button
                      onClick={handleSmsCopy}
                      style={{
                        display: "flex", alignItems: "center", gap: 5,
                        fontSize: 11, padding: "4px 10px", borderRadius: 6,
                        border: `1px solid ${BORDER}`, background: "transparent",
                        color: smsCopied ? "#276749" : "#4A5568",
                        cursor: "pointer",
                      }}
                    >
                      <Copy size={11} />
                      {smsCopied ? "복사됨" : "복사"}
                    </button>
                  </div>
                  <div
                    style={{
                      padding: "10px 14px",
                      borderRadius: 8,
                      background: "#F7FAFC",
                      border: `1px solid ${BORDER}`,
                      fontSize: 12,
                      color: "#4A5568",
                      lineHeight: 1.8,
                      fontFamily: "monospace",
                      whiteSpace: "pre-wrap",
                    }}
                  >
                    {preview.sms_template}
                  </div>
                  <p style={{ fontSize: 11, color: "#A0AEC0", marginTop: 6 }}>
                    &#123;name&#125; · &#123;days&#125; · &#123;tel&#125; 등은 발송 시 실제 값으로 교체하세요.
                  </p>
                </div>
              )}

              {/* 액션 버튼 바 */}
              <div
                className="hw-card"
                style={{ padding: "14px 18px", display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}
              >
                <button
                  onClick={handleStartWork}
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "8px 18px", borderRadius: 8, border: "none",
                    background: GOLD, color: "#fff",
                    fontSize: 13, fontWeight: 600, cursor: "pointer",
                  }}
                >
                  <ClipboardList size={14} />
                  업무 등록하기
                </button>
                <button
                  onClick={handleGoDocGen}
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "8px 18px", borderRadius: 8,
                    border: `1px solid ${BORDER}`, background: "transparent",
                    color: "#4A5568", fontSize: 13, fontWeight: 500, cursor: "pointer",
                  }}
                >
                  <FileEdit size={14} />
                  문서 자동작성
                </button>
              </div>
            </>
          ) : previewEnabled ? (
            <div className="hw-card" style={{ fontSize: 13, color: "#A0AEC0", padding: "28px 0", textAlign: "center" }}>
              선택한 업무에 대한 정보가 없습니다.
            </div>
          ) : null}

        </div>
      </div>
    </div>
  );
}

// ── 작은 헬퍼 컴포넌트 ────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ padding: "2px 16px 4px", fontSize: 10, fontWeight: 700, color: "#A0AEC0", letterSpacing: "0.05em" }}>
      {children}
    </div>
  );
}

function SelBtn({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        width: "100%", textAlign: "left",
        padding: "6px 16px", border: "none", cursor: "pointer",
        fontSize: 12,
        color: active ? "#A0660A" : "#4A5568",
        background: active ? "rgba(245,166,35,0.10)" : "transparent",
        fontWeight: active ? 700 : 400,
      }}
    >
      <span>{label}</span>
      {active && <ChevronRight size={12} style={{ color: "#F5A623" }} />}
    </button>
  );
}

function SectionTitle({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{ color: "#F5A623" }}>{icon}</span>
      <span style={{ fontSize: 12, fontWeight: 700, color: "#2D3748" }}>{label}</span>
    </div>
  );
}
