"use client";

interface Props {
  categories: string[];
  activeCategory: string | "all";
  onChange: (category: string | "all") => void;
  counts?: Record<string, number>;
  totalCount?: number;
}

export default function TaskCategoryFilter({ categories, activeCategory, onChange, counts, totalCount }: Props) {
  const all = ["all", ...categories];

  return (
    <div style={{
      display: "flex",
      gap: 0,
      borderBottom: "2px solid #E2E8F0",
      marginBottom: 0,
      overflowX: "auto",
    }}>
      {all.map((cat) => {
        const isActive = activeCategory === cat;
        const label = cat === "all" ? "전체" : cat;
        const count = cat === "all" ? totalCount : counts?.[cat];

        return (
          <button
            key={cat}
            onClick={() => onChange(cat as string | "all")}
            aria-pressed={isActive}
            style={{
              padding: "8px 14px",
              fontSize: 13,
              fontWeight: isActive ? 700 : 500,
              color: isActive ? "var(--hw-gold-700)" : "#4A5568",
              background: isActive ? "var(--hw-gold-50)" : "none",
              border: "none",
              borderBottom: isActive ? "2px solid var(--hw-gold-500)" : "2px solid transparent",
              borderRadius: "6px 6px 0 0",
              marginBottom: -2,
              cursor: "pointer",
              whiteSpace: "nowrap",
              display: "flex",
              alignItems: "center",
              gap: 5,
              transition: "color 0.12s, background 0.12s",
            }}
            onMouseEnter={(e) => {
              if (!isActive) { const t = e.currentTarget as HTMLButtonElement; t.style.color = "#1A202C"; t.style.background = "var(--hw-gold-50)"; }
            }}
            onMouseLeave={(e) => {
              if (!isActive) { const t = e.currentTarget as HTMLButtonElement; t.style.color = "#4A5568"; t.style.background = "none"; }
            }}
          >
            {label}
            {count !== undefined && (
              <span style={{
                fontSize: 11,
                fontWeight: 700,
                background: isActive ? "var(--hw-gold-200)" : "#EDF2F7",
                color: isActive ? "#111827" : "#718096",
                padding: "1px 6px",
                borderRadius: 10,
                minWidth: 18,
                textAlign: "center",
              }}>
                {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
