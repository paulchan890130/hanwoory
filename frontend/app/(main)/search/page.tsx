"use client";
import { useState, useEffect, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import {
  Search, User, ClipboardList, BookOpen, BookMarked, FileText, Loader2,
} from "lucide-react";
import { searchApi } from "@/lib/api";

interface SearchResult {
  id: string;
  type: string;
  title: string;
  summary: string;
  highlight?: string;
  url?: string;
}

// ── 검색 카테고리 탭 정의 ────────────────────────────────────────────────────────
const SEARCH_TYPES = [
  { key: "all",       label: "전체",        icon: Search      },
  { key: "customer",  label: "고객",        icon: User        },
  { key: "task",      label: "업무",        icon: ClipboardList },
  { key: "board",     label: "게시판",       icon: BookOpen    },
  { key: "reference", label: "업무참고",     icon: BookMarked  },
  { key: "memo",      label: "메모",        icon: FileText    },
] as const;

type SearchType = (typeof SEARCH_TYPES)[number]["key"];

// ── 스켈레톤 로딩 카드 ──────────────────────────────────────────────────────────
function SkeletonCard() {
  return (
    <div
      className="rounded-xl border p-4 space-y-2 animate-pulse"
      style={{ background: "#fff", borderColor: "#E2E8F0" }}
    >
      <div className="h-3 rounded" style={{ background: "#EDF2F7", width: "60%" }} />
      <div className="h-2.5 rounded" style={{ background: "#EDF2F7", width: "90%" }} />
      <div className="h-2.5 rounded" style={{ background: "#EDF2F7", width: "75%" }} />
    </div>
  );
}

// ── 검색 결과 빈 상태 ──────────────────────────────────────────────────────────
function EmptyState({ query }: { query: string }) {
  return (
    <div
      className="text-center py-16 rounded-xl border"
      style={{ background: "#fff", borderColor: "#E2E8F0" }}
    >
      <Search size={36} style={{ color: "#E2E8F0", margin: "0 auto 12px" }} />
      <div className="font-medium text-sm mb-1" style={{ color: "#4A5568" }}>
        &quot;{query}&quot; 검색 결과 없음
      </div>
      <div className="text-xs" style={{ color: "#A0AEC0" }}>
        다른 검색어를 입력하거나 카테고리를 변경해 보세요.
      </div>
    </div>
  );
}

// ── 결과 타입별 아이콘/색상 매핑 ──────────────────────────────────────────────
const TYPE_META: Record<string, { icon: React.ElementType; color: string; label: string }> = {
  customer:  { icon: User,          color: "#4299E1", label: "고객"    },
  task:      { icon: ClipboardList, color: "#48BB78", label: "업무"    },
  board:     { icon: BookOpen,      color: "#ED8936", label: "게시판"  },
  reference: { icon: BookMarked,    color: "#9F7AEA", label: "업무참고" },
  memo:      { icon: FileText,      color: "#F6AD55", label: "메모"    },
};

// ── 검색 결과 카드 ─────────────────────────────────────────────────────────────
function ResultCard({ result, router }: { result: SearchResult; router: ReturnType<typeof useRouter> }) {
  const meta = TYPE_META[result.type] || { icon: Search, color: "#A0AEC0", label: result.type };
  const Icon = meta.icon;

  return (
    <div
      className="rounded-xl border p-4 cursor-pointer transition-all"
      style={{ background: "#fff", borderColor: "#E2E8F0" }}
      onClick={() => result.url && router.push(result.url)}
      onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = "#F5A623"; (e.currentTarget as HTMLDivElement).style.boxShadow = "0 2px 8px rgba(245,166,35,0.15)"; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.borderColor = "#E2E8F0"; (e.currentTarget as HTMLDivElement).style.boxShadow = "none"; }}
    >
      <div className="flex items-start gap-3">
        <div
          className="flex items-center justify-center rounded-lg shrink-0"
          style={{ width: 32, height: 32, background: `${meta.color}18` }}
        >
          <Icon size={14} style={{ color: meta.color }} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span
              className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
              style={{ background: `${meta.color}18`, color: meta.color }}
            >
              {meta.label}
            </span>
            <span className="font-semibold text-sm truncate" style={{ color: "#1A202C" }}>
              {result.title}
            </span>
          </div>
          {result.summary && (
            <div className="text-xs leading-relaxed" style={{ color: "#718096" }}>
              {result.summary}
            </div>
          )}
          {result.highlight && (
            <div
              className="text-xs mt-1 px-2 py-1 rounded"
              style={{ background: "rgba(245,166,35,0.08)", color: "#744210" }}
              dangerouslySetInnerHTML={{ __html: result.highlight }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ── 실제 API 연동 검색 결과 컴포넌트 ──────────────────────────────────────────
function SearchResults({
  query,
  type,
}: {
  query: string;
  type: SearchType;
}) {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!query) return;
    setIsLoading(true);
    setError(null);
    searchApi
      .search(query, type)
      .then((res) => {
        const data = res.data as { results?: SearchResult[] };
        setResults(data.results || []);
      })
      .catch((err) => {
        console.error("[search] API 오류:", err);
        setError("검색 중 오류가 발생했습니다. 다시 시도해주세요.");
        setResults([]);
      })
      .finally(() => setIsLoading(false));
  }, [query, type]);

  if (!query) return null;

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => <SkeletonCard key={i} />)}
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="text-center py-12 rounded-xl border"
        style={{ background: "#fff", borderColor: "#FED7D7" }}
      >
        <div className="text-sm font-medium mb-1" style={{ color: "#C53030" }}>{error}</div>
      </div>
    );
  }

  if (results.length === 0) {
    return <EmptyState query={query} />;
  }

  return (
    <div>
      <div className="text-xs mb-3" style={{ color: "#718096" }}>
        총 <strong>{results.length}</strong>개 결과
      </div>
      <div className="space-y-3">
        {results.map((r) => (
          <ResultCard key={`${r.type}-${r.id}`} result={r} router={router} />
        ))}
      </div>
    </div>
  );
}

// ── 메인 검색 페이지 ─────────────────────────────────────────────────────────────
function SearchPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const initialQuery = searchParams.get("q") || "";
  const initialType = (searchParams.get("type") as SearchType) || "all";

  const [query, setQuery] = useState(initialQuery);
  const [inputValue, setInputValue] = useState(initialQuery);
  const [activeType, setActiveType] = useState<SearchType>(initialType);

  // URL params 변경 시 상태 동기화
  useEffect(() => {
    const q = searchParams.get("q") || "";
    const t = (searchParams.get("type") as SearchType) || "all";
    setQuery(q);
    setInputValue(q);
    setActiveType(t);
  }, [searchParams]);

  const handleSearch = (q: string, type: SearchType = activeType) => {
    const term = q.trim();
    if (!term) return;
    const params = new URLSearchParams({ q: term });
    if (type !== "all") params.set("type", type);
    router.push(`/search?${params.toString()}`);
  };

  const handleTypeChange = (type: SearchType) => {
    setActiveType(type);
    if (query) handleSearch(query, type);
  };

  return (
    <div className="space-y-5">
      {/* 페이지 헤더 */}
      <div className="flex items-center gap-3">
        <h1 className="hw-page-title">통합검색</h1>
        {query && (
          <span className="text-sm" style={{ color: "#718096" }}>
            &quot;{query}&quot; 검색 결과
          </span>
        )}
      </div>

      {/* 검색 입력 */}
      <div className="hw-card">
        <div className="flex gap-3">
          <div className="hw-search-bar flex-1">
            <Search size={14} className="search-icon" />
            <input
              type="text"
              placeholder="고객, 업무, 게시글, 메모, 업무참고 검색..."
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSearch(inputValue);
              }}
              autoFocus
            />
          </div>
          <button
            onClick={() => handleSearch(inputValue)}
            className="btn-primary flex items-center gap-1.5 text-sm px-5"
          >
            <Search size={14} /> 검색
          </button>
        </div>
      </div>

      {/* 카테고리 탭 필터 */}
      {query && (
        <div className="hw-tabs">
          {SEARCH_TYPES.map(({ key, label, icon: Icon }) => (
            <button
              key={key}
              className={`hw-tab flex items-center gap-1.5 ${activeType === key ? "active" : ""}`}
              onClick={() => handleTypeChange(key)}
            >
              <Icon size={12} />
              {label}
            </button>
          ))}
        </div>
      )}

      {/* 검색 결과 영역 */}
      {query ? (
        <SearchResults query={query} type={activeType} />
      ) : (
        /* 검색어 없을 때: 안내 */
        <div
          className="text-center py-16 rounded-xl border"
          style={{ background: "#fff", borderColor: "#E2E8F0" }}
        >
          <Search size={40} style={{ color: "#E2E8F0", margin: "0 auto 16px" }} />
          <div className="font-semibold text-sm mb-2" style={{ color: "#4A5568" }}>
            통합검색
          </div>
          <div className="text-xs leading-relaxed" style={{ color: "#A0AEC0" }}>
            고객, 진행업무, 게시판, 업무참고, 메모를 한 번에 검색합니다.
            <br />
            위 검색창에 키워드를 입력하거나, 상단바의 검색창(Ctrl+K)을 사용하세요.
          </div>
          <div className="mt-6 flex flex-wrap gap-2 justify-center">
            {["비자", "등록증", "여권", "취업"].map((hint) => (
              <button
                key={hint}
                onClick={() => {
                  setInputValue(hint);
                  handleSearch(hint);
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
    </div>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--hw-gold)" }} />
      </div>
    }>
      <SearchPageContent />
    </Suspense>
  );
}
