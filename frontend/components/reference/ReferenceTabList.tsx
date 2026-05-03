"use client";
// frontend/components/reference/ReferenceTabList.tsx

import { useEffect, useRef, useState } from "react";
import { ChevronRight } from "lucide-react";

interface Props {
  sheets: string[];
  selectedSheet: string | null;
  editMode: boolean;
  onSelect: (sheet: string) => void;
  onAdd: (name: string) => Promise<void>;
  onDelete: (name: string) => Promise<void>;
  onRename: (oldName: string, newName: string) => Promise<void>;
}

export default function ReferenceTabList({
  sheets, selectedSheet, editMode,
  onSelect, onAdd, onDelete, onRename,
}: Props) {
  const [openMenu, setOpenMenu]       = useState<string | null>(null);
  const [renamingTab, setRenamingTab] = useState<string | null>(null);
  const [renameVal, setRenameVal]     = useState("");
  const [addingTab, setAddingTab]     = useState(false);
  const [newTabVal, setNewTabVal]     = useState("");
  const [hoveredTab, setHoveredTab]   = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const renameRef = useRef<HTMLInputElement | null>(null);
  const addRef    = useRef<HTMLInputElement | null>(null);

  // 메뉴 바깥 클릭 닫기
  useEffect(() => {
    const h = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setOpenMenu(null);
    };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  useEffect(() => { if (renamingTab) renameRef.current?.focus(); }, [renamingTab]);
  useEffect(() => { if (addingTab)   addRef.current?.focus(); }, [addingTab]);

  async function commitRename() {
    if (!renamingTab) return;
    const val = renameVal.trim();
    if (val && val !== renamingTab) {
      await onRename(renamingTab, val);
    }
    setRenamingTab(null);
  }

  async function commitAdd() {
    const val = newTabVal.trim();
    if (val) {
      await onAdd(val);
    }
    setAddingTab(false);
    setNewTabVal("");
  }

  async function handleDelete(name: string) {
    setOpenMenu(null);
    if (!confirm(`"${name}" 시트를 삭제하시겠습니까? 복구할 수 없습니다.`)) return;
    await onDelete(name);
  }

  return (
    <div className="hw-card" style={{ width: 180, flexShrink: 0, padding: "8px 0", minHeight: 200 }}>
      <div style={{ padding: "6px 12px 8px", fontSize: 11, fontWeight: 600, color: "#A0AEC0", letterSpacing: "0.05em", textTransform: "uppercase" }}>
        시트 탭
      </div>

      {sheets.map((sheet) => {
        const isActive  = selectedSheet === sheet;
        const isRenaming = renamingTab === sheet;

        return (
          <div
            key={sheet}
            style={{ position: "relative" }}
            onMouseEnter={() => setHoveredTab(sheet)}
            onMouseLeave={() => setHoveredTab(null)}
          >
            {isRenaming ? (
              <div style={{ padding: "4px 10px" }}>
                <input
                  ref={renameRef}
                  value={renameVal}
                  maxLength={30}
                  onChange={(e) => setRenameVal(e.target.value)}
                  onKeyDown={async (e) => {
                    if (e.key === "Enter")  { e.preventDefault(); await commitRename(); }
                    if (e.key === "Escape") { setRenamingTab(null); }
                  }}
                  onBlur={commitRename}
                  style={{
                    width: "100%", padding: "3px 6px", fontSize: 12, borderRadius: 4,
                    border: "2px solid #3182ce", outline: "none",
                  }}
                />
              </div>
            ) : (
              <button
                onClick={() => onSelect(sheet)}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  width: "100%", textAlign: "left", padding: "6px 12px",
                  fontSize: 12, border: "none", cursor: "pointer",
                  color: isActive ? "var(--hw-gold-text)" : "#4A5568",
                  background: isActive ? "var(--hw-gold-light)" : "transparent",
                  fontWeight: isActive ? 600 : 400,
                }}
              >
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                  {sheet}
                </span>
                {isActive && !editMode && <ChevronRight size={12} />}
                {editMode && hoveredTab === sheet && (
                  <span
                    role="button"
                    onClick={(e) => { e.stopPropagation(); setOpenMenu(openMenu === sheet ? null : sheet); }}
                    style={{ fontSize: 14, color: "#718096", padding: "0 2px", lineHeight: 1 }}
                    title="메뉴"
                  >
                    ⋮
                  </span>
                )}
              </button>
            )}

            {/* 드롭다운 메뉴 */}
            {openMenu === sheet && editMode && (
              <div
                ref={menuRef}
                style={{
                  position: "absolute", left: "100%", top: 0, zIndex: 200,
                  background: "#fff", border: "1px solid #E2E8F0", borderRadius: 6,
                  boxShadow: "0 4px 12px rgba(0,0,0,0.12)", minWidth: 120,
                }}
              >
                <button
                  style={{ display: "block", width: "100%", padding: "7px 12px", fontSize: 12, background: "none", border: "none", textAlign: "left", cursor: "pointer", color: "#2D3748" }}
                  onClick={() => { setOpenMenu(null); setRenamingTab(sheet); setRenameVal(sheet); }}
                >
                  이름 변경
                </button>
                <button
                  style={{ display: "block", width: "100%", padding: "7px 12px", fontSize: 12, background: "none", border: "none", textAlign: "left", cursor: "pointer", color: "#E53E3E" }}
                  onClick={() => handleDelete(sheet)}
                >
                  삭제
                </button>
              </div>
            )}
          </div>
        );
      })}

      {/* 새 탭 추가 (편집 모드) */}
      {editMode && (
        <div style={{ padding: "6px 10px", borderTop: "1px solid #EDF2F7", marginTop: 4 }}>
          {addingTab ? (
            <input
              ref={addRef}
              value={newTabVal}
              maxLength={30}
              placeholder="탭 이름 입력"
              onChange={(e) => setNewTabVal(e.target.value)}
              onKeyDown={async (e) => {
                if (e.key === "Enter")  { e.preventDefault(); await commitAdd(); }
                if (e.key === "Escape") { setAddingTab(false); setNewTabVal(""); }
              }}
              onBlur={async () => { if (newTabVal.trim()) await commitAdd(); else setAddingTab(false); }}
              style={{
                width: "100%", padding: "4px 6px", fontSize: 11, borderRadius: 4,
                border: "2px solid #3182ce", outline: "none",
              }}
            />
          ) : (
            <button
              onClick={() => setAddingTab(true)}
              style={{
                width: "100%", padding: "4px 0", fontSize: 11, fontWeight: 600,
                background: "none", border: "1px dashed #CBD5E0", borderRadius: 4,
                color: "#718096", cursor: "pointer",
              }}
            >
              + 새 탭
            </button>
          )}
        </div>
      )}
    </div>
  );
}
