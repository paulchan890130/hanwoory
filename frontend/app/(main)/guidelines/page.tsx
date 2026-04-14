"use client";
import { useState, useCallback, useRef } from "react";
import { Search, BookOpen, ChevronDown, ChevronUp, X, Loader2, FileText, Paperclip, AlertCircle, BookMarked } from "lucide-react";
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
  { key: "REGISTRATION",             label: "등록" },
  { key: "REENTRY",                   label: "재입국" },
  { key: "GRANT",                     label: "자격부여" },
  { key: "VISA_CONFIRM",              label: "사증발급인정" },
  { key: "APPLICATION_CLAIM",         label: "직접신청" },
  { key: "DOMESTIC_RESIDENCE_REPORT", label: "거소신고" },
  { key: "ACTIVITY_EXTRA",            label: "활동범위" },
];

// ── 서류 뱃지 ─────────────────────────────────────────────────────────────────
function DocBadge({ text, color }: { text: string; color: string }) {
  return (
    <span
      className="inline-block text-[11px] px-2 py-0.5 rounded-full mr-1 mb-1"
      style={{ background: `${color}18`, color, border: `1px solid ${color}40` }}
    >
      {text}
    </span>
  );
}

// ── 업무유형 뱃지 ─────────────────────────────────────────────────────────────
function ActionBadge({ type }: { type: string }) {
  const color = ACTION_TYPE_COLORS[type] || "#A0AEC0";
  const label = ACTION_TYPE_LABELS[type] || type;
  return (
    <span
      className="inline-block text-[10px] font-semibold px-1.5 py-0.5 rounded"
      style={{ background: `${color}18`, color }}
    >
      {label}
    </span>
  );
}

// ── 상세 패널 ──────────────────────────────────────────────────────────────────
function DetailPanel({ row, onClose }: { row: GuidelineRow; onClose: () => void }) {
  const formDocs = row.form_docs ? row.form_docs.split("|").map(s => s.trim()).filter(Boolean) : [];
  const suppDocs = row.supporting_docs ? row.supporting_docs.split("|").map(s => s.trim()).filter(Boolean) : [];
  const exceptions = row.exceptions_summary
    ? row.exceptions_summary.split("|").map(s => s.trim()).filter(Boolean)
    : [];

  return (
    <div
      style={{
        position: "fixed", top: 0, right: 0, bottom: 0,
        width: 420, background: "#fff",
        boxShadow: "-4px 0 24px rgba(0,0,0,0.12)",
        zIndex: 300, overflowY: "auto",
        display: "flex", flexDirection: "column",
      }}
    >
      {/* 헤더 */}
      <div
        className="flex items-start justify-between p-5 border-b shrink-0"
        style={{ borderColor: "#E2E8F0" }}
      >
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-bold text-sm" style={{ color: "#1A202C" }}>
              {row.detailed_code}
            </span>
            <ActionBadge type={row.action_type} />
          </div>
          <div className="font-semibold text-base" style={{ color: "#2D3748" }}>
            {row.business_name}
          </div>
          {row.overview_short && (
            <div className="text-xs mt-1.5 leading-relaxed" style={{ color: "#718096" }}>
              {row.overview_short}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg transition-colors shrink-0 ml-3"
          style={{ color: "#A0AEC0" }}
          onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "#F7FAFC"; }}
          onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
        >
          <X size={16} />
        </button>
      </div>

      {/* 본문 */}
      <div className="flex-1 p-5 space-y-5">

        {/* 작성서류 (업체 준비) */}
        {formDocs.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <FileText size={13} style={{ color: "#4299E1" }} />
              <span className="text-xs font-semibold" style={{ color: "#4299E1" }}>
                작성서류 (업체 준비)
              </span>
            </div>
            <div className="space-y-1">
              {formDocs.map((doc, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-[11px] font-medium w-4 shrink-0" style={{ color: "#CBD5E0" }}>
                    {i + 1}
                  </span>
                  <span className="text-sm" style={{ color: "#2D3748" }}>{doc}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 첨부서류 (고객 준비) */}
        {suppDocs.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <Paperclip size={13} style={{ color: "#48BB78" }} />
              <span className="text-xs font-semibold" style={{ color: "#48BB78" }}>
                첨부서류 (고객 준비)
              </span>
            </div>
            <div className="space-y-1">
              {suppDocs.map((doc, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="text-[11px] font-medium w-4 shrink-0" style={{ color: "#CBD5E0" }}>
                    {i + 1}
                  </span>
                  <span className="text-sm" style={{ color: "#2D3748" }}>{doc}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 인지세 */}
        {row.fee_rule && (
          <div>
            <div className="text-xs font-semibold mb-1.5" style={{ color: "#718096" }}>인지세</div>
            <div
              className="text-sm px-3 py-2 rounded-lg"
              style={{ background: "#FFFBF0", color: "#744210", border: "1px solid #F6E05E" }}
            >
              {row.fee_rule}
            </div>
          </div>
        )}

        {/* 예외사항 */}
        {exceptions.length > 0 && (
          <div>
            <div className="flex items-center gap-1.5 mb-2">
              <AlertCircle size={13} style={{ color: "#ED8936" }} />
              <span className="text-xs font-semibold" style={{ color: "#ED8936" }}>예외사항</span>
            </div>
            <div className="space-y-1.5">
              {exceptions.map((exc, i) => (
                <div
                  key={i}
                  className="text-xs px-3 py-2 rounded-lg leading-relaxed"
                  style={{ background: "#FFFAF0", color: "#7B341E", border: "1px solid #FBD38D" }}
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
            <div className="flex items-center gap-1.5 mb-1.5">
              <BookMarked size={13} style={{ color: "#9F7AEA" }} />
              <span className="text-xs font-semibold" style={{ color: "#9F7AEA" }}>근거</span>
            </div>
            <div className="text-xs leading-relaxed" style={{ color: "#718096" }}>
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
  row,
  isSelected,
  onClick,
}: {
  row: GuidelineRow;
  isSelected: boolean;
  onClick: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const color = ACTION_TYPE_COLORS[row.action_type] || "#A0AEC0";
  const formDocs = row.form_docs ? row.form_docs.split("|").map(s => s.trim()).filter(Boolean) : [];
  const suppDocs = row.supporting_docs ? row.supporting_docs.split("|").map(s => s.trim()).filter(Boolean) : [];

  return (
    <div
      className="rounded-xl border transition-all"
      style={{
        background: "#fff",
        borderColor: isSelected ? color : "#E2E8F0",
        boxShadow: isSelected ? `0 0 0 2px ${color}40` : "none",
      }}
    >
      {/* 카드 헤더 — 클릭 시 상세 패널 */}
      <div
        className="p-4 cursor-pointer"
        onClick={onClick}
        onMouseEnter={(e) => {
          if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = "#F7FAFC";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLDivElement).style.background = "transparent";
        }}
      >
        <div className="flex items-start gap-3">
          {/* 색상 바 */}
          <div
            className="shrink-0 rounded-full"
            style={{ width: 3, height: 40, background: color, marginTop: 2 }}
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className="font-bold text-sm" style={{ color: "#1A202C" }}>
                {row.detailed_code}
              </span>
              <ActionBadge type={row.action_type} />
              <span className="text-xs" style={{ color: "#718096" }}>{row.major_action_std}</span>
            </div>
            <div className="font-medium text-sm mb-1" style={{ color: "#2D3748" }}>
              {row.business_name}
            </div>
            {row.overview_short && (
              <div className="text-xs leading-relaxed" style={{ color: "#A0AEC0" }}>
                {row.overview_short.length > 80
                  ? row.overview_short.slice(0, 80) + "…"
                  : row.overview_short}
              </div>
            )}
          </div>
          {/* 펼치기 버튼 */}
          <button
            className="shrink-0 p-1"
            style={{ color: "#CBD5E0" }}
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
          >
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>
      </div>

      {/* 펼쳐진 서류 목록 미리보기 */}
      {expanded && (
        <div
          className="px-4 pb-4 border-t"
          style={{ borderColor: "#F7FAFC" }}
        >
          <div className="pt-3 grid grid-cols-2 gap-3">
            {formDocs.length > 0 && (
              <div>
                <div className="text-[10px] font-semibold mb-1.5" style={{ color: "#4299E1" }}>
                  작성서류 ({formDocs.length})
                </div>
                <div>
                  {formDocs.map((d, i) => (
                    <DocBadge key={i} text={d} color="#4299E1" />
                  ))}
                </div>
              </div>
            )}
            {suppDocs.length > 0 && (
              <div>
                <div className="text-[10px] font-semibold mb-1.5" style={{ color: "#48BB78" }}>
                  첨부서류 ({suppDocs.length})
                </div>
                <div>
                  {suppDocs.map((d, i) => (
                    <DocBadge key={i} text={d} color="#48BB78" />
                  ))}
                </div>
              </div>
            )}
          </div>
          {row.fee_rule && (
            <div className="mt-2 text-xs" style={{ color: "#718096" }}>
              인지세: <span style={{ color: "#744210" }}>{row.fee_rule}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── 메인 페이지 ───────────────────────────────────────────────────────────────
export default function GuidelinesPage() {
  const [query, setQuery] = useState("");
  const [inputValue, setInputValue] = useState("");
  const [activeType, setActiveType] = useState("");
  const [results, setResults] = useState<GuidelineRow[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [hasSearched, setHasSearched] = useState(false);
  const [selectedRow, setSelectedRow] = useState<GuidelineRow | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const doSearch = useCallback(
    async (q: string, type: string) => {
      setIsLoading(true);
      setHasSearched(true);
      setSelectedRow(null);
      try {
        let res;
        if (q.trim()) {
          res = await guidelinesApi.search(q.trim(), type || undefined, 1, 50);
        } else {
          res = await guidelinesApi.list({ action_type: type || undefined, limit: 50 });
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
    },
    []
  );

  const handleSearch = () => {
    setQuery(inputValue);
    doSearch(inputValue, activeType);
  };

  const handleTypeChange = (type: string) => {
    setActiveType(type);
    doSearch(inputValue, type);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handleSearch();
  };

  return (
    <div className="space-y-5" style={{ paddingRight: selectedRow ? 440 : 0, transition: "padding-right 0.2s" }}>
      {/* 페이지 헤더 */}
      <div className="flex items-center gap-3">
        <BookOpen size={20} style={{ color: "var(--hw-gold)" }} />
        <h1 className="hw-page-title">실무지침</h1>
        {hasSearched && !isLoading && (
          <span className="text-sm" style={{ color: "#A0AEC0" }}>
            {total}건
          </span>
        )}
      </div>

      {/* 검색창 */}
      <div className="hw-card">
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
              placeholder="체류자격 코드, 업무명, 서류명으로 검색 (예: F-4, 시간제취업, 사업자등록증)"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              autoFocus
              style={{
                width: "100%", height: 38,
                border: "1px solid #CBD5E0", borderRadius: 20,
                padding: "0 16px 0 38px", fontSize: 13,
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
                onClick={() => { setInputValue(""); inputRef.current?.focus(); }}
                style={{
                  position: "absolute", right: 10, top: "50%",
                  transform: "translateY(-50%)",
                  color: "#CBD5E0", background: "none", border: "none", cursor: "pointer", padding: 2,
                }}
              >
                <X size={13} />
              </button>
            )}
          </div>
          <button
            onClick={handleSearch}
            className="btn-primary flex items-center gap-1.5 text-sm px-5 shrink-0"
          >
            <Search size={14} /> 검색
          </button>
        </div>
      </div>

      {/* 업무유형 탭 */}
      <div className="hw-tabs" style={{ flexWrap: "wrap", gap: 4 }}>
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

      {/* 결과 영역 */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={24} className="animate-spin" style={{ color: "var(--hw-gold)" }} />
        </div>
      ) : hasSearched ? (
        results.length === 0 ? (
          <div
            className="text-center py-16 rounded-xl border"
            style={{ background: "#fff", borderColor: "#E2E8F0" }}
          >
            <Search size={36} style={{ color: "#E2E8F0", margin: "0 auto 12px" }} />
            <div className="font-medium text-sm mb-1" style={{ color: "#4A5568" }}>
              검색 결과 없음
            </div>
            <div className="text-xs" style={{ color: "#A0AEC0" }}>
              다른 검색어나 업무유형을 선택해 보세요.
            </div>
          </div>
        ) : (
          <div className="space-y-2.5">
            {results.map((row) => (
              <GuidelineCard
                key={row.row_id}
                row={row}
                isSelected={selectedRow?.row_id === row.row_id}
                onClick={() =>
                  setSelectedRow(selectedRow?.row_id === row.row_id ? null : row)
                }
              />
            ))}
          </div>
        )
      ) : (
        /* 초기 안내 */
        <div
          className="text-center py-16 rounded-xl border"
          style={{ background: "#fff", borderColor: "#E2E8F0" }}
        >
          <BookOpen size={40} style={{ color: "#E2E8F0", margin: "0 auto 16px" }} />
          <div className="font-semibold text-sm mb-2" style={{ color: "#4A5568" }}>
            출입국 실무지침
          </div>
          <div className="text-xs leading-relaxed mb-6" style={{ color: "#A0AEC0" }}>
            체류자격 코드, 업무명, 서류명으로 검색하거나
            <br />
            업무유형 탭을 클릭해 전체 목록을 확인하세요.
          </div>
          {/* 빠른 검색 힌트 */}
          <div className="flex flex-wrap gap-2 justify-center">
            {["F-4", "E-7", "D-2", "F-6", "통합신청서", "사업자등록증"].map((hint) => (
              <button
                key={hint}
                onClick={() => {
                  setInputValue(hint);
                  setQuery(hint);
                  doSearch(hint, activeType);
                }}
                className="text-xs px-3 py-1.5 rounded-full transition-colors"
                style={{
                  background: "var(--hw-gold-light)",
                  color: "var(--hw-gold-text)",
                  border: "1px solid var(--hw-gold)",
                }}
              >
                {hint}
              </button>
            ))}
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
