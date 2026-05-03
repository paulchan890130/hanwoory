"use client";
// frontend/components/scan/RoiPresetBar.tsx — 심플 버전

import { useEffect, useRef, useState } from "react";
import type { RoiPreset } from "@/lib/types/roiPreset";

// ── Props ────────────────────────────────────────────────────────────────────

export interface RoiPresetBarProps {
  presets: (RoiPreset | null)[];
  activeSlot: 1 | 2 | 3;
  editMode: boolean;
  isDirty: boolean;
  onSlotChange: (slot: 1 | 2 | 3) => void;
  onEditModeChange: (v: boolean) => void;
  onSave: () => void;
  onSaveEmpty: (slot: 1 | 2 | 3) => void;
  onRename: (slot: 1 | 2 | 3, name: string) => void;
}

// ── 스타일 ───────────────────────────────────────────────────────────────────

const BASE_BTN: React.CSSProperties = {
  height: 28, padding: "0 10px", borderRadius: 5, fontSize: 12, fontWeight: 600,
  cursor: "pointer", border: "1px solid #CBD5E0", background: "#fff", color: "#4A5568",
  whiteSpace: "nowrap",
};
const ACTIVE_BTN: React.CSSProperties = {
  ...BASE_BTN, background: "#4A5568", color: "#fff", border: "1px solid #4A5568",
};
const EMPTY_BTN: React.CSSProperties = {
  ...BASE_BTN, color: "#A0AEC0", border: "1px dashed #CBD5E0", background: "#FAFAFA",
};

const SLOTS = [1, 2, 3] as const;

// ── 컴포넌트 ──────────────────────────────────────────────────────────────────

export default function RoiPresetBar({
  presets, activeSlot, editMode, isDirty,
  onSlotChange, onEditModeChange, onSave, onSaveEmpty, onRename,
}: RoiPresetBarProps) {
  // 빈 슬롯 팝오버
  const [emptyPopover, setEmptyPopover] = useState<1 | 2 | 3 | null>(null);
  // 인라인 이름 편집
  const [renamingSlot, setRenamingSlot] = useState<2 | 3 | null>(null);
  const [renameVal, setRenameVal]       = useState("");
  const renameInputRef                  = useRef<HTMLInputElement>(null);

  // 팝오버 바깥 클릭 시 닫기
  const popoverRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setEmptyPopover(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // 인라인 rename input autoFocus
  useEffect(() => {
    if (renamingSlot !== null) renameInputRef.current?.focus();
  }, [renamingSlot]);

  function startRename(slot: 2 | 3) {
    setRenameVal(presets[slot - 1]?.name ?? `슬롯 ${slot}`);
    setRenamingSlot(slot);
  }

  function commitRename() {
    if (renamingSlot === null) return;
    const name = renameVal.trim() || presets[renamingSlot - 1]?.name || `슬롯 ${renamingSlot}`;
    onRename(renamingSlot, name);
    setRenamingSlot(null);
  }

  const isSlot1Active = activeSlot === 1;
  const saveEnabled   = !isSlot1Active && editMode;

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap",
      padding: "6px 10px", background: "#F7FAFC",
      border: "1px solid #E2E8F0", borderRadius: 8,
    }}>
      {/* 레이블 */}
      <span style={{ fontSize: 11, fontWeight: 600, color: "#718096", flexShrink: 0 }}>
        프리셋:
      </span>

      {/* 슬롯 버튼들 */}
      {SLOTS.map((slot) => {
        const preset  = presets[slot - 1];
        const isActive = slot === activeSlot;
        const isEmpty  = preset === null;
        const dirtyMark = isActive && isDirty ? " *" : "";

        // ── 슬롯 1: 항상 존재, 클릭 = 선택만 ──────────────────────────────
        if (slot === 1) {
          return (
            <button
              key={1}
              style={isActive ? ACTIVE_BTN : BASE_BTN}
              onClick={() => onSlotChange(1)}
            >
              {isActive ? "●" : "○"} 1: {preset?.name ?? "기본값"}{dirtyMark}
            </button>
          );
        }

        // ── 슬롯 2/3: 빈 슬롯 ─────────────────────────────────────────────
        if (isEmpty) {
          return (
            <div key={slot} style={{ position: "relative" }} ref={emptyPopover === slot ? popoverRef : null}>
              <button
                style={EMPTY_BTN}
                onClick={() => setEmptyPopover(emptyPopover === slot ? null : slot as 2 | 3)}
              >
                + {slot}
              </button>
              {emptyPopover === slot && (
                <div style={{
                  position: "absolute", top: "calc(100% + 4px)", left: 0, zIndex: 1000,
                  background: "#fff", border: "1px solid #E2E8F0", borderRadius: 8,
                  padding: "10px 12px", boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
                  minWidth: 190, whiteSpace: "nowrap",
                }}>
                  <div style={{ fontSize: 12, color: "#4A5568", marginBottom: 8 }}>
                    현재 위치를 슬롯 {slot}에 저장?
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      style={{ ...BASE_BTN, background: "#D4A843", color: "#fff", border: "1px solid #D4A843" }}
                      onClick={() => {
                        setEmptyPopover(null);
                        onSaveEmpty(slot as 2 | 3);
                      }}
                    >
                      저장
                    </button>
                    <button style={{ ...BASE_BTN, background: "#F7FAFC" }} onClick={() => setEmptyPopover(null)}>
                      취소
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        }

        // ── 슬롯 2/3: 채워진 슬롯 ─────────────────────────────────────────
        return (
          <div key={slot} style={{ position: "relative" }}>
            {renamingSlot === slot ? (
              // 인라인 이름 편집
              <input
                ref={renameInputRef}
                value={renameVal}
                maxLength={10}
                onChange={(e) => setRenameVal(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter")  { e.preventDefault(); commitRename(); }
                  if (e.key === "Escape") { setRenamingSlot(null); }
                }}
                onBlur={commitRename}
                style={{
                  height: 28, padding: "0 8px", borderRadius: 5, fontSize: 12,
                  border: "2px solid #3182ce", outline: "none", width: 100,
                }}
              />
            ) : (
              <button
                style={isActive ? ACTIVE_BTN : BASE_BTN}
                onClick={() => onSlotChange(slot as 2 | 3)}
                onDoubleClick={() => startRename(slot as 2 | 3)}
                title="더블클릭으로 이름 변경"
              >
                {isActive ? "●" : "○"} {slot}: {preset.name}{dirtyMark}
              </button>
            )}
          </div>
        );
      })}

      {/* 우측: 편집모드 + 현재 저장 */}
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
        <label style={{
          display: "flex", alignItems: "center", gap: 5, fontSize: 12,
          color: isSlot1Active ? "#CBD5E0" : editMode ? "#D4A843" : "#718096",
          fontWeight: editMode ? 600 : 400,
          cursor: isSlot1Active ? "not-allowed" : "pointer",
        }}>
          <input
            type="checkbox"
            checked={editMode}
            disabled={isSlot1Active}
            onChange={(e) => onEditModeChange(e.target.checked)}
          />
          편집모드
        </label>

        <button
          disabled={!saveEnabled}
          onClick={saveEnabled ? onSave : undefined}
          style={{
            ...BASE_BTN,
            background: saveEnabled ? "#D4A843" : "#F7FAFC",
            color: saveEnabled ? "#fff" : "#CBD5E0",
            border: saveEnabled ? "1px solid #D4A843" : "1px solid #E2E8F0",
            cursor: saveEnabled ? "pointer" : "not-allowed",
          }}
        >
          💾 현재 저장
        </button>
      </div>
    </div>
  );
}
