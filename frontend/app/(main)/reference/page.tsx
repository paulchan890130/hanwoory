"use client";
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BookMarked, RefreshCw } from "lucide-react";
import { referenceApi } from "@/lib/api";
import { referenceEditApi } from "@/lib/api/referenceEdit";
import type { SheetData } from "@/lib/types/reference";
import ReferenceToolbar  from "@/components/reference/ReferenceToolbar";
import ReferenceTabList  from "@/components/reference/ReferenceTabList";
import ReferenceTable    from "@/components/reference/ReferenceTable";

export default function ReferencePage() {
  const qc = useQueryClient();
  const [selectedSheet, setSelectedSheet] = useState<string | null>(null);
  const [editMode, setEditMode]           = useState(false);
  // 낙관적 업데이트용 로컬 사본 (구조변경 후 re-fetch로 동기화)
  const [localData, setLocalData]         = useState<SheetData | null>(null);

  // ── 시트 목록 ─────────────────────────────────────────────────────────────
  const { data: sheetInfo, isLoading: sheetsLoading, error: sheetsError } = useQuery({
    queryKey: ["reference", "sheets"],
    queryFn: () => referenceApi.listSheets().then((r) => r.data),
  });

  // ── 시트 데이터 ───────────────────────────────────────────────────────────
  const { data: sheetData, isLoading: dataLoading, isFetching } = useQuery({
    queryKey: ["reference", "data", selectedSheet],
    queryFn: () =>
      selectedSheet
        ? referenceApi.getSheetData(selectedSheet).then((r) => r.data)
        : Promise.resolve(null),
    enabled: !!selectedSheet,
  });

  const sheets     = sheetInfo?.sheets ?? [];
  const sheetEditUrl = sheetInfo?.sheet_key
    ? `https://docs.google.com/spreadsheets/d/${sheetInfo.sheet_key}/edit`
    : null;

  // 첫 시트 자동 선택
  useEffect(() => {
    if (sheets.length > 0 && selectedSheet === null) setSelectedSheet(sheets[0]);
  }, [sheets, selectedSheet]);

  // sheetData가 바뀌면 localData 동기화
  useEffect(() => {
    if (sheetData) setLocalData({ sheet: sheetData.sheet, headers: sheetData.headers, rows: sheetData.rows });
  }, [sheetData]);

  // 데이터 re-fetch (구조적 변경 후)
  function refetchData() {
    qc.invalidateQueries({ queryKey: ["reference", "data", selectedSheet] });
  }
  function refetchSheets() {
    qc.invalidateQueries({ queryKey: ["reference", "sheets"] });
  }

  // ── 탭 조작 핸들러 ────────────────────────────────────────────────────────
  async function handleAddSheet(name: string) {
    try {
      await referenceEditApi.addSheet(name);
      await refetchSheets();
      // 목록 갱신 후 새 탭 선택
      setSelectedSheet(name);
    } catch (err) { toast.error(`탭 추가 실패: ${err}`); }
  }

  async function handleDeleteSheet(name: string) {
    try {
      await referenceEditApi.deleteSheet(name);
      const result = await referenceApi.listSheets().then((r) => r.data);
      qc.setQueryData(["reference", "sheets"], result);
      if (selectedSheet === name) setSelectedSheet(result.sheets[0] ?? null);
    } catch (err) { toast.error(`탭 삭제 실패: ${err}`); }
  }

  async function handleRenameSheet(oldName: string, newName: string) {
    try {
      await referenceEditApi.renameSheet(oldName, newName);
      const result = await referenceApi.listSheets().then((r) => r.data);
      qc.setQueryData(["reference", "sheets"], result);
      if (selectedSheet === oldName) setSelectedSheet(newName);
    } catch (err) { toast.error(`탭 이름 변경 실패: ${err}`); }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* ── 페이지 헤더 ── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <BookMarked size={18} style={{ color: "var(--hw-gold)" }} />
          <h1 className="hw-page-title">업무참고</h1>
        </div>
        <ReferenceToolbar
          editMode={editMode}
          onEditModeChange={setEditMode}
          sheetEditUrl={sheetEditUrl}
        />
      </div>

      {/* 편집 모드 배너 */}
      {editMode && (
        <div style={{
          background: "#FFF9E6", border: "1px solid #E8DFC8", borderRadius: 6,
          padding: "8px 16px", display: "flex", alignItems: "center",
          justifyContent: "space-between", fontSize: 12, color: "#6B5314",
        }}>
          <span>⚠ 편집 모드 — 변경사항이 즉시 구글시트에 반영됩니다</span>
          <button
            onClick={() => setEditMode(false)}
            style={{ padding: "3px 10px", borderRadius: 4, fontSize: 11, fontWeight: 600, background: "#fff", border: "1px solid #D4A843", color: "#6B5314", cursor: "pointer" }}
          >
            편집 모드 끄기
          </button>
        </div>
      )}

      {/* ── 메인 컨텐츠 ── */}
      {sheetsLoading ? (
        <div className="hw-card" style={{ fontSize: 13, color: "#A0AEC0" }}>시트 목록 불러오는 중...</div>
      ) : sheetsError ? (
        <div className="hw-card" style={{ fontSize: 13, color: "#E53E3E" }}>
          시트 목록을 불러오지 못했습니다. 업무정리 스프레드시트가 연결되어 있는지 확인하세요.
        </div>
      ) : sheets.length === 0 ? (
        <div className="hw-card" style={{ fontSize: 13, textAlign: "center", padding: "40px 0", color: "#A0AEC0" }}>
          연결된 업무정리 시트가 없습니다.
        </div>
      ) : (
        <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
          {/* 좌측: 탭 목록 */}
          <ReferenceTabList
            sheets={sheets}
            selectedSheet={selectedSheet}
            editMode={editMode}
            onSelect={setSelectedSheet}
            onAdd={handleAddSheet}
            onDelete={handleDeleteSheet}
            onRename={handleRenameSheet}
          />

          {/* 우측: 테이블 */}
          <div style={{ flex: 1, minWidth: 0 }}>
            {dataLoading || isFetching ? (
              <div className="hw-card" style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#A0AEC0" }}>
                <RefreshCw size={14} style={{ animation: "spin 1s linear infinite", color: "var(--hw-gold)" }} />
                데이터 불러오는 중...
              </div>
            ) : !localData ? (
              <div className="hw-card" style={{ fontSize: 13, textAlign: "center", padding: "40px 0", color: "#A0AEC0" }}>
                좌측에서 시트를 선택하세요.
              </div>
            ) : localData.rows.length === 0 && !editMode ? (
              <div className="hw-card" style={{ fontSize: 13, textAlign: "center", padding: "40px 0", color: "#A0AEC0" }}>
                <div style={{ fontWeight: 500, marginBottom: 4 }}>&quot;{localData.sheet}&quot; 시트에 데이터가 없습니다.</div>
                <div style={{ fontSize: 12 }}>{editMode ? "아래 [+ 행 추가] 버튼을 눌러 시작하세요." : "원본 시트에서 내용을 입력해주세요."}</div>
              </div>
            ) : (
              <ReferenceTable
                sheetData={localData}
                editMode={editMode}
                onDataChange={setLocalData}
                onRefetch={refetchData}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
