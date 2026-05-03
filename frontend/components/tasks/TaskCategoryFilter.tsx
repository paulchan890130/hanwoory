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
            style={{
              padding: "8px 14px",
              fontSize: 13,
              fontWeight: isActive ? 700 : 400,
              color: isActive ? "#1A202C" : "#718096",
              background: "none",
              border: "none",
              borderBottom: isActive ? "2px solid #1A202C" : "2px solid transparent",
              marginBottom: -2,
              cursor: "pointer",
              whiteSpace: "nowrap",
              display: "flex",
              alignItems: "center",
              gap: 5,
              transition: "color 0.1s",
            }}
            onMouseEnter={(e) => {
              if (!isActive) (e.currentTarget as HTMLButtonElement).style.color = "#2D3748";
            }}
            onMouseLeave={(e) => {
              if (!isActive) (e.currentTarget as HTMLButtonElement).style.color = "#718096";
            }}
          >
            {label}
            {count !== undefined && (
              <span style={{
                fontSize: 11,
                fontWeight: 700,
                background: isActive ? "#1A202C" : "#EDF2F7",
                color: isActive ? "#fff" : "#718096",
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
