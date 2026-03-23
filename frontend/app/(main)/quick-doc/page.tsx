"use client";
import { useState, useRef, useEffect, useCallback } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  quickDocApi,
  type CustomerSearchResult,
  type FullDocGenRequest,
} from "@/lib/api";
import {
  FileText, Download, Loader2, Search, X,
  RotateCcw, User, Home, Shield, Users, UserCheck, Stamp,
} from "lucide-react";

// ── 색상 상수 ─────────────────────────────────────────────────────────────
const GOLD = "#F5A623";
const GOLD_LIGHT = "rgba(245,166,35,0.10)";
const BORDER = "#E2E8F0";
const GRAY_BG = "#F9FAFB";

// ─────────────────────────────────────────────────────────────────────────
// 관계인 조건 판별 — Streamlit page_document.py 기준 완전 일치
// ─────────────────────────────────────────────────────────────────────────
function needGuarantor(cat: string, min: string, kind: string, detail: string) {
  if (cat !== "체류" || kind !== "F") return false;
  if (["등록", "연장"].includes(min)) return ["1","2","3","6"].includes(detail);
  if (min === "변경") return ["1","2","3","5","6"].includes(detail);
  if (min === "부여") return ["2","3","5"].includes(detail);
  return false;
}

function needAggregator(cat: string, min: string, kind: string, detail: string) {
  return cat === "체류" && min === "변경" && kind === "F" && detail === "5";
}

function calcIsMinor(regNo: string): boolean {
  const reg = regNo.replace(/-/g, "");
  if (reg.length < 6 || !/^\d{6}/.test(reg)) return false;
  const yy = parseInt(reg.slice(0, 2), 10);
  const now = new Date();
  const currentShort = now.getFullYear() % 100;
  const century = yy <= currentShort ? 2000 : 1900;
  try {
    const birth = new Date(century + yy, parseInt(reg.slice(2,4),10) - 1, parseInt(reg.slice(4,6),10));
    const age = Math.floor((now.getTime() - birth.getTime()) / (365.25 * 24 * 3600 * 1000));
    return age < 18;
  } catch { return false; }
}

// ─────────────────────────────────────────────────────────────────────────
// 타입
// ─────────────────────────────────────────────────────────────────────────
interface RoleState {
  customer: CustomerSearchResult | null;
  directName: string;    // 직접 이름 입력
  seal: boolean;
}

function emptyRole(sealDefault = true): RoleState {
  return { customer: null, directName: "", seal: sealDefault };
}

function roleDisplayName(r: RoleState): string {
  if (r.customer) return r.customer.name;
  return r.directName.trim();
}

function roleIsSet(r: RoleState): boolean {
  return !!(r.customer || r.directName.trim());
}

// ─────────────────────────────────────────────────────────────────────────
// 인라인 고객 검색 컴포넌트
// ─────────────────────────────────────────────────────────────────────────
interface RoleSelectorProps {
  label: string;
  icon: React.ReactNode;
  required?: boolean;
  role: RoleState;
  allowDirectInput?: boolean;
  directInputPlaceholder?: string;
  onChange: (updated: RoleState) => void;
}

function RoleSelector({
  label, icon, required = false,
  role, allowDirectInput = false, directInputPlaceholder = "이름 직접 입력",
  onChange,
}: RoleSelectorProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const isSet = roleIsSet(role);

  const searchQ = useQuery({
    queryKey: ["qd-cust", query],
    queryFn: () => quickDocApi.searchCustomers(query).then((r) => r.data),
    enabled: open && query.length >= 1,
    staleTime: 30_000,
  });

  // 외부 클릭 시 드롭다운 닫기
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const selectCustomer = (c: CustomerSearchResult) => {
    onChange({ ...role, customer: c, directName: "" });
    setOpen(false);
    setQuery("");
  };

  const clearRole = () => {
    onChange({ ...role, customer: null, directName: "" });
    setQuery("");
  };

  return (
    <div style={{
      border: `1px solid ${isSet ? GOLD : BORDER}`,
      borderRadius: 10,
      padding: "10px 14px",
      background: isSet ? GOLD_LIGHT : "#FAFAFA",
      marginBottom: 8,
    }}>
      {/* 헤더 행 */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ color: GOLD }}>{icon}</span>
          <span style={{ fontSize: 13, fontWeight: 700, color: "#2D3748" }}>
            {label} {required && <span style={{ color: "#E53E3E" }}>*</span>}
          </span>
          {isSet && (
            <span style={{ fontSize: 12, color: "#276749", fontWeight: 600 }}>
              ✅ {roleDisplayName(role)}
            </span>
          )}
        </div>
        {/* 도장 토글 */}
        <label style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer", userSelect: "none" }}>
          <input
            type="checkbox"
            checked={role.seal}
            onChange={(e) => onChange({ ...role, seal: e.target.checked })}
            style={{ accentColor: GOLD, width: 14, height: 14 }}
          />
          <span style={{ fontSize: 11, color: "#718096" }}>도장</span>
        </label>
      </div>

      {/* 검색 + 직접입력 */}
      {!role.customer && (
        <div style={{ display: "flex", gap: 6 }}>
          {/* 검색 */}
          <div ref={dropdownRef} style={{ position: "relative", flex: 1 }}>
            <div style={{ position: "relative" }}>
              <Search size={12} style={{ position: "absolute", left: 8, top: "50%", transform: "translateY(-50%)", color: "#A0AEC0" }} />
              <input
                value={query}
                onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
                onFocus={() => setOpen(true)}
                placeholder="고객 DB 검색"
                style={{
                  width: "100%", paddingLeft: 26, paddingRight: 8,
                  padding: "7px 8px 7px 26px",
                  border: `1px solid ${BORDER}`, borderRadius: 7,
                  fontSize: 12, background: "#fff", boxSizing: "border-box",
                }}
              />
            </div>
            {open && query.length >= 1 && (
              <div style={{
                position: "absolute", top: "100%", left: 0, right: 0, zIndex: 50,
                background: "#fff", border: `1px solid ${BORDER}`,
                borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.10)",
                maxHeight: 180, overflowY: "auto",
              }}>
                {searchQ.isLoading && (
                  <div style={{ padding: "8px 12px", fontSize: 12, color: "#A0AEC0" }}>검색 중...</div>
                )}
                {!searchQ.isLoading && (searchQ.data ?? []).length === 0 && (
                  <div style={{ padding: "8px 12px", fontSize: 12, color: "#A0AEC0" }}>결과 없음</div>
                )}
                {(searchQ.data ?? []).map((c) => (
                  <button key={c.id} onClick={() => selectCustomer(c)}
                    style={{
                      display: "block", width: "100%", textAlign: "left",
                      padding: "8px 12px", fontSize: 12, background: "transparent",
                      border: "none", cursor: "pointer", color: "#2D3748",
                      borderBottom: `1px solid ${BORDER}`,
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = GOLD_LIGHT)}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                  >
                    {c.label}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* 직접 입력 (허용된 경우) */}
          {allowDirectInput && (
            <input
              value={role.directName}
              onChange={(e) => onChange({ ...role, directName: e.target.value })}
              placeholder={directInputPlaceholder}
              style={{
                flex: 1, padding: "7px 10px",
                border: `1px solid ${BORDER}`, borderRadius: 7,
                fontSize: 12, background: "#fff",
              }}
            />
          )}
        </div>
      )}

      {/* 선택 해제 버튼 */}
      {isSet && (
        <button onClick={clearRole}
          style={{
            fontSize: 11, color: "#A0AEC0", background: "none", border: "none",
            cursor: "pointer", padding: "2px 0", display: "flex", alignItems: "center", gap: 3,
          }}>
          <X size={10} /> 선택 해제
        </button>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
// 메인 페이지
// ─────────────────────────────────────────────────────────────────────────
export default function QuickDocPage() {
  // ── 업무 선택 ──
  const [category, setCategory] = useState("");
  const [minwon, setMinwon]     = useState("");
  const [kind, setKind]         = useState("");
  const [detail, setDetail]     = useState("");

  // ── 서류 체크 ──
  const [checkedDocs, setCheckedDocs] = useState<Set<string>>(new Set());

  // ── 관계인 ──
  const [applicant,     setApplicant]     = useState<RoleState>(emptyRole(true));
  const [accommodation, setAccommodation] = useState<RoleState>(emptyRole(true));
  const [guarantor,     setGuarantor]     = useState<RoleState>(emptyRole(true));
  const [guardian,      setGuardian]      = useState<RoleState>(emptyRole(true));
  const [aggregator,    setAggregator]    = useState<RoleState>(emptyRole(true));
  const [agentSeal,     setAgentSeal]     = useState(true);

  // ── PDF ──
  const [pdfUrl, setPdfUrl]         = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [confirmMissing, setConfirmMissing] = useState<string[] | null>(null);

  // ── 행정사 정보 ──
  const [agentInfo, setAgentInfo] = useState<{ office_name: string; contact_name: string } | null>(null);

  useEffect(() => {
    const raw = typeof window !== "undefined" ? localStorage.getItem("user_info") : null;
    if (raw) {
      try { setAgentInfo(JSON.parse(raw)); } catch { /* ignore */ }
    }
  }, []);

  // ── 선택 트리 ──
  const { data: tree } = useQuery({
    queryKey: ["qd-tree"],
    queryFn: () => quickDocApi.getTree().then((r) => r.data),
  });

  // ── 파생 값 ──
  const typeOptions    = tree?.types[`${category}|${minwon}`] ?? [];
  const subtypeOptions = tree?.subtypes[`${category}|${minwon}|${kind}`] ?? [];

  const selectionComplete =
    !!category && !!minwon &&
    (typeOptions.length === 0 || !!kind) &&
    (subtypeOptions.length === 0 || !!detail);

  const effectiveKind   = kind   || "";
  const effectiveDetail = detail || "";

  // 관계인 조건
  const showGuarantor  = selectionComplete && needGuarantor(category, minwon, effectiveKind, effectiveDetail);
  const showAggregator = selectionComplete && needAggregator(category, minwon, effectiveKind, effectiveDetail);
  const isMinor        = calcIsMinor(applicant.customer?.reg_no ?? "");
  const showGuardian   = isMinor;

  // ── 필요서류 자동 조회 ──
  const docsMut = useMutation({
    mutationFn: () =>
      quickDocApi.getRequiredDocs(
        category, minwon, effectiveKind, effectiveDetail,
        applicant.customer?.reg_no ?? "",
      ).then((r) => r.data),
    onSuccess: (data) => {
      setCheckedDocs(new Set([...data.main_docs, ...data.agent_docs]));
    },
  });

  // 선택 완료 시 자동 서류 조회
  useEffect(() => {
    if (selectionComplete) {
      docsMut.mutate();
    } else {
      setCheckedDocs(new Set());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, minwon, kind, detail, applicant.customer?.reg_no]);

  // ── 리셋 ──
  const resetAll = () => {
    setCategory(""); setMinwon(""); setKind(""); setDetail("");
    setCheckedDocs(new Set());
    setApplicant(emptyRole(true));
    setAccommodation(emptyRole(true));
    setGuarantor(emptyRole(true));
    setGuardian(emptyRole(true));
    setAggregator(emptyRole(true));
    if (pdfUrl) { URL.revokeObjectURL(pdfUrl); setPdfUrl(null); }
    setConfirmMissing(null);
  };

  // 구분 변경 → 하위 초기화
  const selectCategory = (v: string) => {
    setCategory(v); setMinwon(""); setKind(""); setDetail("");
  };
  const selectMinwon = (v: string) => {
    setMinwon(v); setKind(""); setDetail("");
  };
  const selectKind = (v: string) => {
    setKind(v); setDetail("");
  };

  // ── PDF 생성 ──
  const doGenerate = useCallback(async () => {
    if (!roleIsSet(applicant)) { toast.error("신청인을 선택하거나 이름을 입력해 주세요."); return; }
    if (checkedDocs.size === 0) { toast.error("서류를 하나 이상 선택하세요."); return; }

    setGenerating(true);
    setConfirmMissing(null);
    if (pdfUrl) { URL.revokeObjectURL(pdfUrl); setPdfUrl(null); }

    const payload: FullDocGenRequest = {
      category, minwon,
      kind:   effectiveKind,
      detail: effectiveDetail,
      applicant_id:   applicant.customer?.id,
      applicant_name: !applicant.customer ? applicant.directName.trim() || undefined : undefined,
      accommodation_id:   accommodation.customer?.id,
      accommodation_name: !accommodation.customer ? accommodation.directName.trim() || undefined : undefined,
      guarantor_id:  guarantor.customer?.id,
      guarantor_name: !guarantor.customer ? guarantor.directName.trim() || undefined : undefined,
      guardian_id:   guardian.customer?.id,
      guardian_name: !guardian.customer ? guardian.directName.trim() || undefined : undefined,
      aggregator_id: aggregator.customer?.id,
      aggregator_name: !aggregator.customer ? aggregator.directName.trim() || undefined : undefined,
      selected_docs: Array.from(checkedDocs),
      seal_applicant:     applicant.seal,
      seal_accommodation: accommodation.seal,
      seal_guarantor:     guarantor.seal,
      seal_guardian:      guardian.seal,
      seal_aggregator:    aggregator.seal,
      seal_agent:         agentSeal,
    };

    try {
      const res = await quickDocApi.generateFull(payload);
      const blob = res.data as Blob;
      if (blob.type?.includes("application/json")) {
        const text = await blob.text();
        try { toast.error("PDF 생성 실패: " + (JSON.parse(text)?.detail || text)); } catch { toast.error("PDF 생성 실패"); }
        return;
      }
      setPdfUrl(URL.createObjectURL(blob));
      toast.success("PDF 생성 완료");
    } catch (err: unknown) {
      const errData = (err as { response?: { data?: Blob | { detail?: string } } })?.response?.data;
      if (errData instanceof Blob) {
        try {
          const text = await errData.text();
          const json = JSON.parse(text);
          toast.error("PDF 생성 실패: " + String(json?.detail?.message || json?.detail || text).slice(0, 200));
        } catch { toast.error("PDF 생성 실패 (파싱 오류)"); }
      } else {
        toast.error((errData as { detail?: string })?.detail || "PDF 생성 실패");
      }
    } finally {
      setGenerating(false);
    }
  }, [applicant, accommodation, guarantor, guardian, aggregator, agentSeal, checkedDocs, category, minwon, effectiveKind, effectiveDetail, pdfUrl]);

  const handleGenerate = () => {
    const missing: string[] = [];
    if (!roleIsSet(accommodation)) missing.push("숙소제공자");
    if (showGuarantor && !roleIsSet(guarantor)) missing.push("신원보증인");
    if (showGuardian  && !roleIsSet(guardian))  missing.push("대리인");
    if (showAggregator && !roleIsSet(aggregator)) missing.push("합산자");
    if (missing.length > 0) { setConfirmMissing(missing); return; }
    doGenerate();
  };

  const docs = docsMut.data;

  // ─────────────────────────────────────────────────────────────────────
  // RENDER
  // ─────────────────────────────────────────────────────────────────────
  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>

      {/* 헤더 */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <FileText size={18} style={{ color: GOLD }} />
          <h1 style={{ fontSize: 20, fontWeight: 800, color: "#1A202C", margin: 0 }}>문서 자동작성</h1>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {agentInfo && (
            <span style={{ fontSize: 12, color: "#718096" }}>
              <b>{agentInfo.office_name}</b> / {agentInfo.contact_name}
            </span>
          )}
          {(category || roleIsSet(applicant)) && (
            <button onClick={resetAll}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                padding: "5px 10px", borderRadius: 8, border: `1px solid ${BORDER}`,
                fontSize: 12, background: "#fff", cursor: "pointer", color: "#718096",
              }}>
              <RotateCcw size={11} /> 처음부터
            </button>
          )}
        </div>
      </div>

      {/* 현재 선택 브레드크럼 */}
      {category && (
        <div style={{
          display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap",
          fontSize: 12, padding: "7px 12px", borderRadius: 8, marginBottom: 14,
          background: GOLD_LIGHT, color: "#92631A",
        }}>
          {[category, minwon, kind, detail].filter(Boolean).map((v, i) => (
            <span key={i} style={{ display: "flex", alignItems: "center", gap: 4, fontWeight: 600 }}>
              {i > 0 && <span style={{ opacity: 0.5 }}>›</span>}
              {v}
            </span>
          ))}
          {selectionComplete && (
            <span style={{ marginLeft: "auto", color: "#276749", fontWeight: 600 }}>✓ 업무 선택 완료</span>
          )}
        </div>
      )}

      {/* ── 3단 레이아웃 ── */}
      <div style={{ display: "grid", gridTemplateColumns: "200px 220px 1fr", gap: 16, alignItems: "start" }}>

        {/* ══════ 열 1: 업무 선택 ══════ */}
        <div style={{ background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 12, padding: "16px 14px", boxShadow: "0 1px 4px rgba(0,0,0,0.05)" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 12 }}>① 업무 선택</div>

          {/* 구분 */}
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 6 }}>구분</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {(tree?.categories ?? ["체류", "사증"]).map((c) => (
                <button key={c} onClick={() => selectCategory(c)}
                  style={{
                    padding: "5px 12px", borderRadius: 99, fontSize: 12, cursor: "pointer",
                    border: `1.5px solid ${category === c ? GOLD : BORDER}`,
                    background: category === c ? GOLD : "#fff",
                    color: category === c ? "#fff" : "#4A5568",
                    fontWeight: category === c ? 700 : 400,
                    transition: "all 0.1s",
                  }}>
                  {c}
                </button>
              ))}
            </div>
          </div>

          {/* 민원 */}
          {category && (tree?.minwon[category] ?? []).length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 6 }}>민원</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {(tree?.minwon[category] ?? []).map((m) => (
                  <button key={m} onClick={() => selectMinwon(m)}
                    style={{
                      padding: "5px 10px", borderRadius: 99, fontSize: 12, cursor: "pointer",
                      border: `1.5px solid ${minwon === m ? GOLD : BORDER}`,
                      background: minwon === m ? GOLD : "#fff",
                      color: minwon === m ? "#fff" : "#4A5568",
                      fontWeight: minwon === m ? 700 : 400,
                    }}>
                    {m}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* 종류 */}
          {minwon && typeOptions.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 6 }}>종류</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {typeOptions.map((k) => (
                  <button key={k} onClick={() => selectKind(k)}
                    style={{
                      padding: "5px 10px", borderRadius: 99, fontSize: 12, cursor: "pointer",
                      border: `1.5px solid ${kind === k ? GOLD : BORDER}`,
                      background: kind === k ? GOLD : "#fff",
                      color: kind === k ? "#fff" : "#4A5568",
                      fontWeight: kind === k ? 700 : 400,
                    }}>
                    {k}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* 세부 */}
          {kind && subtypeOptions.length > 0 && (
            <div style={{ marginBottom: 6 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 6 }}>세부</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {subtypeOptions.map((d) => (
                  <button key={d} onClick={() => setDetail(d)}
                    style={{
                      padding: "5px 10px", borderRadius: 99, fontSize: 12, cursor: "pointer",
                      border: `1.5px solid ${detail === d ? GOLD : BORDER}`,
                      background: detail === d ? GOLD : "#fff",
                      color: detail === d ? "#fff" : "#4A5568",
                      fontWeight: detail === d ? 700 : 400,
                    }}>
                    {kind === "F" ? `F-${d}` : d}
                  </button>
                ))}
              </div>
            </div>
          )}

          {!selectionComplete && category && (
            <div style={{ fontSize: 11, color: "#A0AEC0", marginTop: 8 }}>
              {!minwon ? "민원을 선택하세요" : !kind && typeOptions.length > 0 ? "종류를 선택하세요" : !detail && subtypeOptions.length > 0 ? "세부를 선택하세요" : ""}
            </div>
          )}
        </div>

        {/* ══════ 열 2: 필요 서류 ══════ */}
        <div style={{ background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 12, padding: "16px 14px", boxShadow: "0 1px 4px rgba(0,0,0,0.05)" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 12 }}>② 필요 서류</div>

          {!selectionComplete && (
            <div style={{ fontSize: 12, color: "#A0AEC0", padding: "12px 0" }}>
              업무를 선택하면<br />필요 서류가 자동으로 표시됩니다.
            </div>
          )}

          {selectionComplete && docsMut.isPending && (
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#A0AEC0" }}>
              <Loader2 size={13} className="animate-spin" /> 조회 중...
            </div>
          )}

          {selectionComplete && !docsMut.isPending && !docs && (
            <div style={{ fontSize: 12, color: "#A0AEC0" }}>선택한 업무에 해당하는 서류 설정이 없습니다.</div>
          )}

          {docs && (
            <>
              {/* 전체선택/해제 */}
              <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                <button
                  onClick={() => setCheckedDocs(new Set([...docs.main_docs, ...docs.agent_docs]))}
                  style={{ fontSize: 11, color: "#3182CE", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
                  전체 선택
                </button>
                <button
                  onClick={() => setCheckedDocs(new Set())}
                  style={{ fontSize: 11, color: "#718096", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
                  전체 해제
                </button>
                <span style={{ fontSize: 11, color: "#A0AEC0", marginLeft: "auto" }}>{checkedDocs.size}개 선택</span>
              </div>

              {docs.main_docs.length > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 5 }}>민원 서류</div>
                  {docs.main_docs.map((doc) => (
                    <label key={doc} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={checkedDocs.has(doc)}
                        onChange={(e) => {
                          const n = new Set(checkedDocs);
                          e.target.checked ? n.add(doc) : n.delete(doc);
                          setCheckedDocs(n);
                        }}
                        style={{ accentColor: GOLD, width: 13, height: 13 }}
                      />
                      <span style={{ fontSize: 12, color: "#2D3748" }}>{doc}</span>
                    </label>
                  ))}
                </div>
              )}

              {docs.agent_docs.length > 0 && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 600, color: "#718096", marginBottom: 5 }}>행정사 서류</div>
                  {docs.agent_docs.map((doc) => (
                    <label key={doc} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={checkedDocs.has(doc)}
                        onChange={(e) => {
                          const n = new Set(checkedDocs);
                          e.target.checked ? n.add(doc) : n.delete(doc);
                          setCheckedDocs(n);
                        }}
                        style={{ accentColor: GOLD, width: 13, height: 13 }}
                      />
                      <span style={{ fontSize: 12, color: "#2D3748" }}>{doc}</span>
                    </label>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        {/* ══════ 열 3: 관계인 배정 + 도장 + PDF ══════ */}
        <div style={{ background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 12, padding: "16px 18px", boxShadow: "0 1px 4px rgba(0,0,0,0.05)" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 12 }}>③ 관계인 배정 &amp; 도장</div>

          {/* 신청인 (항상 표시, DB 검색 + 직접 입력) */}
          <RoleSelector
            label="신청인" icon={<User size={13} />} required
            role={applicant} onChange={setApplicant}
            allowDirectInput directInputPlaceholder="DB에 없으면 이름 직접 입력"
          />

          {/* 숙소제공자 (항상 표시) */}
          <RoleSelector
            label="숙소제공자" icon={<Home size={13} />}
            role={accommodation} onChange={setAccommodation}
            allowDirectInput directInputPlaceholder="이름 직접 입력 가능"
          />

          {/* 신원보증인 (조건부) */}
          {showGuarantor && (
            <RoleSelector
              label="신원보증인" icon={<Shield size={13} />}
              role={guarantor} onChange={setGuarantor}
              allowDirectInput directInputPlaceholder="이름 직접 입력 가능"
            />
          )}

          {/* 대리인 (미성년자인 경우만) */}
          {showGuardian && (
            <RoleSelector
              label="대리인 (미성년 법정대리인)" icon={<UserCheck size={13} />}
              role={guardian} onChange={setGuardian}
              allowDirectInput directInputPlaceholder="이름 직접 입력 가능"
            />
          )}

          {/* 합산자 (F-5 변경 시만) */}
          {showAggregator && (
            <RoleSelector
              label="합산자 (소득 합산)" icon={<Users size={13} />}
              role={aggregator} onChange={setAggregator}
              allowDirectInput directInputPlaceholder="이름 직접 입력 가능"
            />
          )}

          {/* 행정사 도장 */}
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "9px 12px", border: `1px solid ${BORDER}`, borderRadius: 10,
            background: GRAY_BG, marginBottom: 8,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <Stamp size={13} style={{ color: GOLD }} />
              <span style={{ fontSize: 13, fontWeight: 700, color: "#2D3748" }}>행정사</span>
              <span style={{ fontSize: 12, color: "#718096" }}>
                {agentInfo?.contact_name || agentInfo?.office_name || "계정 정보 없음"} — 자동 채움
              </span>
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 5, cursor: "pointer", userSelect: "none" }}>
              <input type="checkbox" checked={agentSeal} onChange={(e) => setAgentSeal(e.target.checked)}
                style={{ accentColor: GOLD, width: 14, height: 14 }} />
              <span style={{ fontSize: 11, color: "#718096" }}>도장</span>
            </label>
          </div>

          {/* 관계인 조건 안내 */}
          {selectionComplete && (
            <div style={{ fontSize: 11, color: "#718096", marginBottom: 10, padding: "6px 10px", background: "#EBF8FF", borderRadius: 6, lineHeight: 1.6 }}>
              {showGuarantor ? "✓ 신원보증인 필요 (F계열)" : ""}
              {showAggregator ? " ✓ 합산자 필요 (F-5 변경)" : ""}
              {showGuardian ? " ✓ 대리인 필요 (미성년 신청인)" : ""}
              {!showGuarantor && !showAggregator && !showGuardian ? "이 업무는 신청인 + 숙소제공자만 필요합니다." : ""}
            </div>
          )}

          {/* 누락 경고 */}
          {confirmMissing && (
            <div style={{
              padding: "12px 14px", background: "#FFF5F5", border: "1px solid #FEB2B2",
              borderRadius: 8, marginBottom: 12,
            }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#C53030", marginBottom: 6 }}>누락 항목이 있습니다:</div>
              {confirmMissing.map((r) => (
                <div key={r} style={{ fontSize: 12, color: "#9B2C2C", marginBottom: 2 }}>• {r}이(가) 입력되지 않았습니다.</div>
              ))}
              <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                <button onClick={() => { setConfirmMissing(null); doGenerate(); }}
                  style={{
                    padding: "6px 14px", borderRadius: 8, fontSize: 12, cursor: "pointer",
                    background: GOLD, color: "#fff", border: "none", fontWeight: 600,
                  }}>
                  그대로 작성
                </button>
                <button onClick={() => setConfirmMissing(null)}
                  style={{
                    padding: "6px 14px", borderRadius: 8, fontSize: 12, cursor: "pointer",
                    background: "#fff", border: `1px solid ${BORDER}`, color: "#718096",
                  }}>
                  취소
                </button>
              </div>
            </div>
          )}

          {/* PDF 생성 버튼 */}
          <button
            onClick={handleGenerate}
            disabled={!selectionComplete || !roleIsSet(applicant) || checkedDocs.size === 0 || generating}
            style={{
              width: "100%", padding: "12px 0",
              background: (!selectionComplete || !roleIsSet(applicant) || checkedDocs.size === 0) ? "#E2E8F0" : GOLD,
              color: (!selectionComplete || !roleIsSet(applicant) || checkedDocs.size === 0) ? "#A0AEC0" : "#fff",
              border: "none", borderRadius: 10, fontSize: 14, fontWeight: 700, cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
              transition: "all 0.15s",
              marginBottom: 12,
            }}>
            {generating
              ? <><Loader2 size={14} className="animate-spin" /> PDF 생성 중...</>
              : <><FileText size={14} /> 🖨 PDF 생성</>}
          </button>

          {/* 비활성화 안내 */}
          {(!selectionComplete || !roleIsSet(applicant) || checkedDocs.size === 0) && !generating && (
            <div style={{ fontSize: 11, color: "#A0AEC0", textAlign: "center", marginBottom: 8 }}>
              {!selectionComplete ? "업무를 완전히 선택해 주세요" :
               !roleIsSet(applicant) ? "신청인을 입력해 주세요" :
               "서류를 하나 이상 선택해 주세요"}
            </div>
          )}

        </div>

      </div>

      {/* ── PDF 결과 — 3단 grid 아래 하단 전체폭 ── */}
      {pdfUrl && (
        <div style={{
          border: "2px solid #276749", borderRadius: 12,
          background: "#F0FFF4", padding: "16px 20px",
        }}>
          {/* 상단: 성공 메시지 + 다운로드 버튼 */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
            <div>
              <span style={{ fontSize: 15, fontWeight: 700, color: "#276749" }}>✅ PDF 생성 완료</span>
              <span style={{ fontSize: 12, color: "#38A169", marginLeft: 10 }}>
                {roleDisplayName(applicant) || "고객"}_{category}_{minwon}
              </span>
            </div>
            <button
              onClick={() => {
                const a = document.createElement("a");
                a.href = pdfUrl;
                a.download = `${roleDisplayName(applicant) || "고객"}_${category}_${minwon}.pdf`;
                a.click();
              }}
              style={{
                display: "flex", alignItems: "center", gap: 5,
                padding: "8px 18px", borderRadius: 8, fontSize: 13,
                background: GOLD, color: "#fff", border: "none", cursor: "pointer", fontWeight: 700,
              }}>
              <Download size={14} /> 다운로드
            </button>
          </div>
          {/* 전체폭 PDF 뷰어 — #pagemode=none 으로 썸네일 패널 기본 접힘 */}
          <iframe
            src={`${pdfUrl}#pagemode=none`}
            style={{
              width: "100%",
              height: "max(900px, calc(100vh - 200px))",
              borderRadius: 8,
              border: "1px solid #C6F6D5",
              display: "block",
            }}
            title="PDF 미리보기"
          />
        </div>
      )}
    </div>
  );
}
