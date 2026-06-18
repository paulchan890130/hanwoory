"use client";
// frontend/components/reference/ReferenceToolbar.tsx

interface Props {
  editMode: boolean;
  onEditModeChange: (v: boolean) => void;
}

export default function ReferenceToolbar({ editMode, onEditModeChange }: Props) {
  return (
    <>
      {/* 편집 모드 배너 */}
      {editMode && (
        <div style={{
          background: "#FFF9E6", border: "1px solid #E8DFC8", borderRadius: 6,
          padding: "8px 16px", display: "flex", alignItems: "center",
          justifyContent: "space-between", fontSize: 12, color: "#6B5314",
        }}>
          <span>⚠ 편집 모드 — 변경사항이 즉시 저장됩니다</span>
          <button
            onClick={() => onEditModeChange(false)}
            style={{
              padding: "3px 10px", borderRadius: 4, fontSize: 11, fontWeight: 600,
              background: "#fff", border: "1px solid #D4A843", color: "#6B5314", cursor: "pointer",
            }}
          >
            편집 모드 끄기
          </button>
        </div>
      )}

      {/* 헤더 버튼 영역 */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <button
          onClick={() => onEditModeChange(!editMode)}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "5px 12px", borderRadius: 6, fontSize: 12, fontWeight: 600,
            cursor: "pointer",
            background: editMode ? "#FFF9E6" : "#F7FAFC",
            color: editMode ? "#6B5314" : "#4A5568",
            border: editMode ? "1px solid #D4A843" : "1px solid #CBD5E0",
          }}
        >
          ✏ 편집
        </button>
      </div>
    </>
  );
}
