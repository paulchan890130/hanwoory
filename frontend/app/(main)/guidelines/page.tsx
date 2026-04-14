"use client";
import { useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  Search, BookOpen, ChevronDown, ChevronUp, X, Loader2,
  FileText, Paperclip, AlertCircle, BookMarked, ExternalLink,
  ArrowRight, GitBranch,
} from "lucide-react";
import { guidelinesApi, GuidelineRow } from "@/lib/api";

// ── 업무유형 한글 라벨 ────────────────────────────────────────────────────────
const ACTION_TYPE_LABELS: Record<string, string> = {
  CHANGE:                    "체류자격 변경",
  EXTEND:                    "체류기간 연장",
  EXTRA_WORK:                "체류자격 외 활동",
  WORKPLACE:                 "근무처 변경·추가",
  REGISTRATION:              "외국인등록",
  REENTRY:                   "재입국허가",
  GRANT:                     "체류자격 부여",
  VISA_CONFIRM:              "사증발급인정서",
  APPLICATION_CLAIM:         "직접신청",
  DOMESTIC_RESIDENCE_REPORT: "국내 거소신고",
  ACTIVITY_EXTRA:            "활동범위 확대",
};

const ACTION_TYPE_COLORS: Record<string, string> = {
  CHANGE:                    "#4299E1",
  EXTEND:                    "#48BB78",
  EXTRA_WORK:                "#ED8936",
  WORKPLACE:                 "#9F7AEA",
  REGISTRATION:              "#38B2AC",
  REENTRY:                   "#F6AD55",
  GRANT:                     "#FC8181",
  VISA_CONFIRM:              "#667EEA",
  APPLICATION_CLAIM:         "#A0AEC0",
  DOMESTIC_RESIDENCE_REPORT: "#68D391",
  ACTIVITY_EXTRA:            "#F6AD55",
};

const ACTION_TYPE_TABS = [
  { key: "",                          label: "전체" },
  { key: "CHANGE",                    label: "변경" },
  { key: "EXTEND",                    label: "연장" },
  { key: "EXTRA_WORK",                label: "자격외활동" },
  { key: "WORKPLACE",                 label: "근무처" },
  { key: "REGISTRATION",              label: "등록" },
  { key: "REENTRY",                   label: "재입국" },
  { key: "GRANT",                     label: "자격부여" },
  { key: "VISA_CONFIRM",              label: "사증발급인정" },
  { key: "APPLICATION_CLAIM",         label: "직접신청" },
  { key: "DOMESTIC_RESIDENCE_REPORT", label: "거소신고" },
  { key: "ACTIVITY_EXTRA",            label: "활동범위" },
];

// ── 상담 진입점 (트리 모드) ────────────────────────────────────────────────────
interface EntryPoint {
  label: string;
  subtitle: string;
  codes: string;
  color: string;
  searchQuery: string;
  quickdoc?: { category: string; minwon: string; kind?: string; detail?: string };
}

const ENTRY_POINTS: EntryPoint[] = [
  {
    label: "재외동포 (F-4)",
    subtitle: "체류자격 변경·연장",
    codes: "F-4",
    color: "#4299E1",
    searchQuery: "F-4",
    quickdoc: { category: "체류", minwon: "변경", kind: "F", detail: "4" },
  },
  {
    label: "특정활동 (E-7)",
    subtitle: "변경·연장·부여",
    codes: "E-7",
    color: "#9F7AEA",
    searchQuery: "E-7",
    quickdoc: { category: "체류", minwon: "변경", kind: "E7" },
  },
  {
    label: "유학 (D-2)",
    subtitle: "등록·변경·연장",
    codes: "D-2",
    color: "#667EEA",
    searchQuery: "D-2",
    quickdoc: { category: "체류", minwon: "변경", kind: "D" },
  },
  {
    label: "방문취업 (H-2)",
    subtitle: "등록·연장·변경",
    codes: "H-2",
    color: "#ED8936",
    searchQuery: "H-2",
    quickdoc: { category: "체류", minwon: "변경", kind: "H2" },
  },
  {
    label: "결혼이민 (F-6)",
    subtitle: "변경·연장·부여",
    codes: "F-6",
    color: "#FC8181",
    searchQuery: "F-6",
    quickdoc: { category: "체류", minwon: "변경", kind: "F", detail: "6" },
  },
  {
    label: "외국인 등록",
    subtitle: "최초 등록 절차",
    codes: "등록",
    color: "#38B2AC",
    searchQuery: "외국인등록",
  },
  {
    label: "재입국 허가",
    subtitle: "단수·복수 재입국",
    codes: "재입국",
    color: "#F6AD55",
    searchQuery: "재입국허가",
  },
  {
    label: "체류자격 외 활동",
    subtitle: "시간제취업·기타",
    codes: "자격외활동",
    color: "#ED8936",
    searchQuery: "시간제취업",
  },
  {
    label: "근무처 변경·추가",
    subtitle: "취업자격 근무처",
    codes: "근무처",
    color: "#9F7AEA",
    searchQuery: "근무처변경",
  },
  {
    label: "체류자격 부여",
    subtitle: "출생·귀화 후 부여",
    codes: "부여",
    color: "#FC8181",
    searchQuery: "체류자격부여",
  },
  {
    label: "사증발급인정서",
    subtitle: "국내 초청 사증",
    codes: "사증",
    color: "#667EEA",
    searchQuery: "사증발급인정",
  },
  {
    label: "거소신고",
    subtitle: "재외동포 거소",
    codes: "거소",
    color: "#68D391",
    searchQuery: "거소신고",
  },
  {
    label: "직접신청",
    subtitle: "체류지·신고 등",
    codes: "신고",
    color: "#A0AEC0",
    searchQuery: "직접신청",
  },
];

// ── quickdoc 딥링크 URL 생성 ───────────────────────────────────────────────────
function buildQuickDocUrl(row: GuidelineRow): string | null {
  // row에 quickdoc 필드가 있으면 우선 사용
  if ((row as Record<string, unknown>).quickdoc_category) {
    const r = row as GuidelineRow & {
      quickdoc_category?: string;
      quickdoc_minwon?: string;
      quickdoc_kind?: string;
      quickdoc_detail?: string;
    };
    const params = new URLSearchParams();
    if (r.quickdoc_category) params.set("category", r.quickdoc_category);
    if (r.quickdoc_minwon)   params.set("minwon",   r.quickdoc_minwon);
    if (r.quickdoc_kind)     params.set("kind",     r.quickdoc_kind);
    if (r.quickdoc_detail)   params.set("detail",   r.quickdoc_detail);
    params.set("from_label", row.business_name);
    return `/quick-doc?${params.toString()}`;
  }
  // 없으면 코드 기반 추론
  const code = row.detailed_code ?? "";
  const at   = row.action_type ?? "";
  const params = new URLSearchParams();

  // 사증 계열
  if (at === "VISA_CONFIRM") {
    params.set("category", "사증");
    params.set("from_label", row.business_name);
    return `/quick-doc?${params.toString()}`;
  }

  params.set("category", "체류");
  const minwonMap: Record<string, string> = {
    CHANGE: "변경", EXTEND: "연장", REGISTRATION: "등록",
    GRANT: "부여", EXTRA_WORK: "기타", WORKPLACE: "기타",
    REENTRY: "기타", DOMESTIC_RESIDENCE_REPORT: "기타",
    ACTIVITY_EXTRA: "기타", APPLICATION_CLAIM: "기타",
  };
  const minwon = minwonMap[at];
  if (!minwon) return null;
  params.set("minwon", minwon);

  // kind 추론
  if (code.startsWith("F-4") || code.startsWith("F4")) {
    params.set("kind", "F"); params.set("detail", "4");
  } else if (code.startsWith("F-6") || code.startsWith("F6")) {
    params.set("kind", "F"); params.set("detail", "6");
  } else if (code.startsWith("F-2") || code.startsWith("F2")) {
    params.set("kind", "F"); params.set("detail", "2");
  } else if (code.startsWith("F-5") || code.startsWith("F5")) {
    params.set("kind", "F"); params.set("detail", "5");
  } else if (code.startsWith("H-2") || code.startsWith("H2")) {
    params.set("kind", "H2");
  } else if (code.startsWith("E-7") || code.startsWith("E7")) {
    params.set("kind", "E7");
  } else if (code.startsWith("D-") || code.startsWith("D")) {
    params.set("kind", "D");
  }

  params.set("from_label", row.business_name);
  return `/quick-doc?${params.toString()}`;
}

// ── 서류 칩 ──────────────────────────────────────────────────────────────────
function DocChip({ text, color }: { text: string; color: string }) {
  return (
    <span
      style={{
        display: "inline-block",
        fontSize: 11, padding: "3px 9px", borderRadius: 99,
        background: `${color}18`, color, border: `1px solid ${color}40`,
        whiteSpace: "nowrap", fontWeight: 500,
      }}
    >
      {text}
    </span>
  );
}

// ── 업무유형 뱃지 ──────────────────────────────────────────────────────────────
function ActionBadge({ type }: { type: string }) {
  const color = ACTION_TYPE_COLORS[type] || "#A0AEC0";
  const label = ACTION_TYPE_LABELS[type] || type;
  return (
    <span
      style={{
        display: "inline-block", fontSize: 10, fontWeight: 700,
        padding: "2px 7px", borderRadius: 6,
        background: `${color}18`, color,
      }}
    >
      {label}
    </span>
  );
}

// ── 서류 섹션 (DetailPanel 전용) ───────────────────────────────────────────────
function DocSection({
  title, icon, color, docs,
}: {
  title: string; icon: React.ReactNode; color: string; docs: string[];
}) {
  if (docs.length === 0) return null;
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        {icon}
        <span style={{ fontSize: 12, fontWeight: 700, color }}>{title}</span>
        <span style={{ fontSize: 11, color: "#A0AEC0" }}>({docs.length})</span>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {docs.map((doc, i) => (
          <DocChip key={i} text={doc} color={color} />
        ))}
      </div>
    </div>
  );
}

// ── 상세 패널 ──────────────────────────────────────────────────────────────────
function DetailPanel({
  row, onClose,
}: {
  row: GuidelineRow; onClose: () => void;
}) {
  const router = useRouter();
  const officeDocs = (row.form_docs ?? "").split("|").map(s => s.trim()).filter(Boolean);
  const requiredDocs = (row.supporting_docs ?? "").split("|").map(s => s.trim()).filter(Boolean);
  const exceptions = (row.exceptions_summary ?? "").split("|").map(s => s.trim()).filter(Boolean);
  const deepLinkUrl = buildQuickDocUrl(row);

  return (
    <div
      style={{
        position: "fixed", top: 0, right: 0, bottom: 0,
        width: 440, background: "#fff",
        boxShadow: "-4px 0 32px rgba(0,0,0,0.13)",
        zIndex: 300, overflowY: "auto",
        display: "flex", flexDirection: "column",
      }}
    >
      {/* 헤더 */}
      <div
        style={{
          padding: "18px 20px 14px",
          borderBottom: "1px solid #E2E8F0",
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
              <ActionBadge type={row.action_type} />
              <span style={{ fontSize: 12, color: "#A0AEC0" }}>{row.detailed_code}</span>
            </div>
            <div style={{ fontSize: 16, fontWeight: 700, color: "#1A202C", lineHeight: 1.4, marginBottom: 4 }}>
              {row.business_name}
            </div>
            {row.overview_short && (
              <div style={{ fontSize: 12, color: "#718096", lineHeight: 1.6 }}>
                {row.overview_short}
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            style={{
              padding: 6, borderRadius: 8, background: "none", border: "none",
              cursor: "pointer", color: "#A0AEC0", flexShrink: 0,
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#F7FAFC"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "none"; }}
          >
            <X size={16} />
          </button>
        </div>

        {/* 문서자동작성 딥링크 버튼 */}
        {deepLinkUrl && (
          <button
            onClick={() => router.push(deepLinkUrl)}
            style={{
              marginTop: 12, width: "100%",
              display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
              padding: "8px 14px", borderRadius: 8,
              background: "rgba(245,166,35,0.10)", border: "1px solid #F5A623",
              color: "#92631A", fontSize: 12, fontWeight: 700,
              cursor: "pointer", transition: "all 0.15s",
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "rgba(245,166,35,0.20)"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "rgba(245,166,35,0.10)"; }}
          >
            <FileText size={13} />
            문서 자동작성으로 이동
            <ArrowRight size={13} />
          </button>
        )}
      </div>

      {/* 본문 */}
      <div style={{ flex: 1, padding: "18px 20px", display: "flex", flexDirection: "column", gap: 18 }}>

        {/* 사무소 준비서류 */}
        <DocSection
          title="사무소 준비서류"
          icon={<FileText size={13} style={{ color: "#4299E1" }} />}
          color="#4299E1"
          docs={officeDocs}
        />

        {/* 필요서류 (고객 준비) */}
        <DocSection
          title="필요서류 (고객 준비)"
          icon={<Paperclip size={13} style={{ color: "#48BB78" }} />}
          color="#48BB78"
          docs={requiredDocs}
        />

        {/* 인지세 */}
        {row.fee_rule && (
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: "#718096", marginBottom: 6 }}>인지세</div>
            <div
              style={{
                fontSize: 13, padding: "10px 14px", borderRadius: 8,
                background: "#FFFBF0", color: "#744210", border: "1px solid #F6E05E",
                lineHeight: 1.5,
              }}
            >
              {row.fee_rule}
            </div>
          </div>
        )}

        {/* 예외사항 */}
        {exceptions.length > 0 && (
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
              <AlertCircle size={13} style={{ color: "#ED8936" }} />
              <span style={{ fontSize: 12, fontWeight: 700, color: "#ED8936" }}>예외사항</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {exceptions.map((exc, i) => (
                <div
                  key={i}
                  style={{
                    fontSize: 12, padding: "8px 12px", borderRadius: 8,
                    background: "#FFFAF0", color: "#7B341E",
                    border: "1px solid #FBD38D", lineHeight: 1.6,
                  }}
                >
                  {exc}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 근거 */}
        {row.basis_section && (
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
              <BookMarked size={13} style={{ color: "#9F7AEA" }} />
              <span style={{ fontSize: 12, fontWeight: 700, color: "#9F7AEA" }}>근거</span>
            </div>
            <div style={{ fontSize: 12, color: "#718096", lineHeight: 1.7 }}>
              {row.basis_section}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── 결과 카드 ─────────────────────────────────────────────────────────────────
function GuidelineCard({
  row, isSelected, onClick,
}: {
  row: GuidelineRow; isSelected: boolean; onClick: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const color = ACTION_TYPE_COLORS[row.action_type] || "#A0AEC0";
  const officeDocs = (row.form_docs ?? "").split("|").map(s => s.trim()).filter(Boolean);
  const requiredDocs = (row.supporting_docs ?? "").split("|").map(s => s.trim()).filter(Boolean);

  return (
    <div
      style={{
        background: "#fff", borderRadius: 12,
        border: `1px solid ${isSelected ? color : "#E2E8F0"}`,
        boxShadow: isSelected ? `0 0 0 2px ${color}30` : "none",
        transition: "border-color 0.15s",
      }}
    >
      {/* 카드 헤더 */}
      <div
        style={{ padding: "14px 16px", cursor: "pointer" }}
        onClick={onClick}
        onMouseEnter={(e) => {
          if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = "#F7FAFC";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLDivElement).style.background = "transparent";
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
          {/* 색상 바 */}
          <div
            style={{
              width: 3, height: 42, borderRadius: 99,
              background: color, flexShrink: 0, marginTop: 2,
            }}
          />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4, flexWrap: "wrap" }}>
              <ActionBadge type={row.action_type} />
              <span style={{ fontSize: 11, color: "#A0AEC0" }}>{row.detailed_code}</span>
              <span style={{ fontSize: 11, color: "#CBD5E0" }}>{row.major_action_std}</span>
            </div>
            <div style={{ fontSize: 14, fontWeight: 600, color: "#2D3748", marginBottom: 3 }}>
              {row.business_name}
            </div>
            {row.overview_short && (
              <div style={{ fontSize: 12, color: "#A0AEC0", lineHeight: 1.5 }}>
                {row.overview_short.length > 90
                  ? row.overview_short.slice(0, 90) + "…"
                  : row.overview_short}
              </div>
            )}
          </div>
          {/* 펼치기 */}
          <button
            style={{ padding: 4, color: "#CBD5E0", background: "none", border: "none", cursor: "pointer", flexShrink: 0 }}
            onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
          >
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>

      {/* 펼쳐진 서류 */}
      {expanded && (
        <div style={{ padding: "0 16px 14px", borderTop: "1px solid #F7FAFC" }}>
          <div style={{ paddingTop: 12, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {officeDocs.length > 0 && (
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: "#4299E1", marginBottom: 6 }}>
                  사무소 준비서류 ({officeDocs.length})
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {officeDocs.map((d, i) => (
                    <DocChip key={i} text={d} color="#4299E1" />
                  ))}
                </div>
              </div>
            )}
            {requiredDocs.length > 0 && (
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: "#48BB78", marginBottom: 6 }}>
                  필요서류 ({requiredDocs.length})
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {requiredDocs.map((d, i) => (
                    <DocChip key={i} text={d} color="#48BB78" />
                  ))}
                </div>
              </div>
            )}
          </div>
          {row.fee_rule && (
            <div style={{ marginTop: 8, fontSize: 11, color: "#718096" }}>
              인지세: <span style={{ color: "#744210", fontWeight: 600 }}>{row.fee_rule}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 진입점 카드 (트리 모드) ───────────────────────────────────────────────────
function EntryPointCard({
  entry, onClick,
}: {
  entry: EntryPoint; onClick: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", alignItems: "flex-start", gap: 10,
        padding: "12px 14px", borderRadius: 10,
        border: `1.5px solid ${hovered ? entry.color : "#E2E8F0"}`,
        background: hovered ? `${entry.color}0C` : "#fff",
        cursor: "pointer", textAlign: "left",
        transition: "all 0.15s", width: "100%",
      }}
    >
      <div
        style={{
          width: 32, height: 32, borderRadius: 8, flexShrink: 0,
          background: `${entry.color}18`,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 14, fontWeight: 800, color: entry.color,
        }}
      >
        {entry.codes.slice(0, 2)}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#2D3748", marginBottom: 2 }}>
          {entry.label}
        </div>
        <div style={{ fontSize: 11, color: "#A0AEC0" }}>{entry.subtitle}</div>
      </div>
      <ArrowRight
        size={13}
        style={{
          color: hovered ? entry.color : "#CBD5E0",
          flexShrink: 0, marginTop: 2,
          transition: "color 0.15s",
        }}
      />
    </button>
  );
}

// ── 메인 페이지 ───────────────────────────────────────────────────────────────
export default function GuidelinesPage() {
  const [inputValue, setInputValue]   = useState("");
  const [activeType, setActiveType]   = useState("");
  const [results, setResults]         = useState<GuidelineRow[]>([]);
  const [total, setTotal]             = useState(0);
  const [isLoading, setIsLoading]     = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [selectedRow, setSelectedRow] = useState<GuidelineRow | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 모드 결정: 2자 이상이면 검색 모드, 그 이하면 트리 모드
  const mode = inputValue.trim().length >= 2 ? "search" : "tree";

  const doSearch = useCallback(async (q: string, type: string) => {
    setIsLoading(true);
    setHasSearched(true);
    setSelectedRow(null);
    try {
      let res;
      if (q.trim()) {
        res = await guidelinesApi.search(q.trim(), type || undefined, 1, 60);
      } else {
        res = await guidelinesApi.list({ action_type: type || undefined, limit: 60 });
      }
      setResults(res.data.data);
      setTotal(res.data.total);
    } catch (err) {
      console.error("[guidelines] 검색 오류:", err);
      setResults([]);
      setTotal(0);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleSearch = () => {
    doSearch(inputValue, activeType);
  };

  const handleEntryPointClick = (entry: EntryPoint) => {
    setInputValue(entry.searchQuery);
    doSearch(entry.searchQuery, "");
    setActiveType("");
  };

  const handleTypeChange = (type: string) => {
    setActiveType(type);
    doSearch(inputValue, type);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handleSearch();
  };

  const handleClear = () => {
    setInputValue("");
    setHasSearched(false);
    setResults([]);
    setTotal(0);
    setSelectedRow(null);
    setActiveType("");
    inputRef.current?.focus();
  };

  return (
    <div style={{ paddingRight: selectedRow ? 460 : 0, transition: "padding-right 0.2s" }}>
      {/* 페이지 헤더 */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
        <BookOpen size={20} style={{ color: "var(--hw-gold)" }} />
        <h1 className="hw-page-title" style={{ margin: 0 }}>실무지침</h1>
        {hasSearched && !isLoading && (
          <span style={{ fontSize: 13, color: "#A0AEC0" }}>{total}건</span>
        )}
        {hasSearched && (
          <button
            onClick={handleClear}
            style={{
              marginLeft: "auto", display: "flex", alignItems: "center", gap: 4,
              fontSize: 12, color: "#A0AEC0", background: "none", border: "none",
              cursor: "pointer", padding: "4px 8px",
            }}
          >
            <X size={12} /> 초기화
          </button>
        )}
      </div>

      {/* 검색창 */}
      <div className="hw-card" style={{ marginBottom: 14 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
            <Search
              size={14}
              style={{
                position: "absolute", left: 12, top: "50%",
                transform: "translateY(-50%)",
                color: "#A0AEC0", pointerEvents: "none",
              }}
            />
            <input
              ref={inputRef}
              type="text"
              placeholder="체류자격 코드, 업무명, 서류명 검색 (예: F-4, 시간제취업, 통합신청서)"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              autoFocus
              style={{
                width: "100%", height: 38,
                border: "1px solid #CBD5E0", borderRadius: 20,
                padding: "0 36px 0 38px", fontSize: 13,
                outline: "none", background: "#F8F9FA",
                boxSizing: "border-box",
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = "var(--hw-gold)";
                e.currentTarget.style.background = "#fff";
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = "#CBD5E0";
                e.currentTarget.style.background = "#F8F9FA";
              }}
            />
            {inputValue && (
              <button
                onClick={handleClear}
                style={{
                  position: "absolute", right: 10, top: "50%",
                  transform: "translateY(-50%)",
                  color: "#CBD5E0", background: "none", border: "none",
                  cursor: "pointer", padding: 2,
                }}
              >
                <X size={13} />
              </button>
            )}
          </div>
          <button
            onClick={handleSearch}
            className="btn-primary"
            style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, padding: "0 18px", height: 38, flexShrink: 0, borderRadius: 20 }}
          >
            <Search size={13} /> 검색
          </button>
        </div>
      </div>

      {/* 업무유형 탭 (검색 결과가 있을 때만) */}
      {hasSearched && (
        <div className="hw-tabs" style={{ flexWrap: "wrap", gap: 4, marginBottom: 14 }}>
          {ACTION_TYPE_TABS.map(({ key, label }) => (
            <button
              key={key}
              className={`hw-tab ${activeType === key ? "active" : ""}`}
              onClick={() => handleTypeChange(key)}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {/* ─── 결과 영역 ─── */}
      {isLoading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: "60px 0" }}>
          <Loader2 size={24} className="animate-spin" style={{ color: "var(--hw-gold)" }} />
        </div>
      ) : hasSearched ? (
        /* 검색 모드: 결과 목록 */
        results.length === 0 ? (
          <div
            style={{
              textAlign: "center", padding: "60px 0", borderRadius: 12,
              background: "#fff", border: "1px solid #E2E8F0",
            }}
          >
            <Search size={36} style={{ color: "#E2E8F0", margin: "0 auto 12px" }} />
            <div style={{ fontSize: 14, fontWeight: 600, color: "#4A5568", marginBottom: 4 }}>
              검색 결과 없음
            </div>
            <div style={{ fontSize: 12, color: "#A0AEC0" }}>
              다른 검색어나 업무유형 탭을 선택해 보세요.
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {results.map((row) => (
              <GuidelineCard
                key={row.row_id}
                row={row}
                isSelected={selectedRow?.row_id === row.row_id}
                onClick={() => setSelectedRow(selectedRow?.row_id === row.row_id ? null : row)}
              />
            ))}
          </div>
        )
      ) : (
        /* 트리 모드: 진입점 카드 그리드 */
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <GitBranch size={14} style={{ color: "#A0AEC0" }} />
            <span style={{ fontSize: 12, color: "#A0AEC0" }}>
              업무 유형을 선택하거나 위에서 직접 검색하세요
            </span>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
              gap: 8,
            }}
          >
            {ENTRY_POINTS.map((entry) => (
              <EntryPointCard
                key={entry.label}
                entry={entry}
                onClick={() => handleEntryPointClick(entry)}
              />
            ))}
          </div>
          {/* 빠른 검색 힌트 */}
          <div style={{ marginTop: 20, textAlign: "center" }}>
            <div style={{ fontSize: 11, color: "#CBD5E0", marginBottom: 10 }}>자주 찾는 서류</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, justifyContent: "center" }}>
              {["통합신청서", "사업자등록증", "재직증명서", "가족관계증명서", "위임장"].map((hint) => (
                <button
                  key={hint}
                  onClick={() => {
                    setInputValue(hint);
                    doSearch(hint, "");
                  }}
                  style={{
                    fontSize: 11, padding: "4px 12px", borderRadius: 99,
                    background: "rgba(245,166,35,0.08)",
                    color: "var(--hw-gold-text)",
                    border: "1px solid rgba(245,166,35,0.35)",
                    cursor: "pointer",
                  }}
                >
                  {hint}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* 상세 패널 */}
      {selectedRow && (
        <DetailPanel row={selectedRow} onClose={() => setSelectedRow(null)} />
      )}
    </div>
  );
}
