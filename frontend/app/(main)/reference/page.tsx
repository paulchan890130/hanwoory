"use client";
import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { referenceApi } from "@/lib/api";
import { BookMarked, ExternalLink, RefreshCw, ChevronRight } from "lucide-react";

export default function ReferencePage() {
  const [selectedSheet, setSelectedSheet] = useState<string | null>(null);

  const { data: sheetInfo, isLoading: sheetsLoading, error: sheetsError } = useQuery({
    queryKey: ["reference", "sheets"],
    queryFn: () => referenceApi.listSheets().then((r) => r.data),
  });

  const { data: sheetData, isLoading: dataLoading, isFetching } = useQuery({
    queryKey: ["reference", "data", selectedSheet],
    queryFn: () =>
      selectedSheet
        ? referenceApi.getSheetData(selectedSheet).then((r) => r.data)
        : Promise.resolve(null),
    enabled: !!selectedSheet,
  });

  const sheets = sheetInfo?.sheets ?? [];
  useEffect(() => {
    if (sheets.length > 0 && selectedSheet === null) {
      setSelectedSheet(sheets[0]);
    }
  }, [sheets, selectedSheet]);

  const sheetEditUrl = sheetInfo?.sheet_key
    ? `https://docs.google.com/spreadsheets/d/${sheetInfo.sheet_key}/edit`
    : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* 페이지 헤더 */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <BookMarked size={18} style={{ color: "var(--hw-gold)" }} />
          <h1 className="hw-page-title">업무참고</h1>
        </div>
        {sheetEditUrl && (
          <a
            href={sheetEditUrl}
            target="_blank"
            rel="noopener noreferrer"
            style={{
              display: "flex", alignItems: "center", gap: 6,
              fontSize: 12, padding: "5px 12px", borderRadius: 6,
              color: "#3182CE", background: "#EBF8FF", border: "1px solid #BEE3F8",
              textDecoration: "none",
            }}
          >
            <ExternalLink size={12} />
            원본 시트 열기
          </a>
        )}
      </div>

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
          {/* 시트 탭 목록 (좌측) */}
          <div className="hw-card" style={{ width: 180, flexShrink: 0, padding: "8px 0", minHeight: 200 }}>
            <div style={{ padding: "6px 12px 8px", fontSize: 11, fontWeight: 600, color: "#A0AEC0", letterSpacing: "0.05em", textTransform: "uppercase" }}>
              시트 탭
            </div>
            {sheets.map((sheet) => (
              <button
                key={sheet}
                onClick={() => setSelectedSheet(sheet)}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  width: "100%", textAlign: "left", padding: "6px 12px",
                  fontSize: 12, border: "none", cursor: "pointer",
                  color: selectedSheet === sheet ? "var(--hw-gold-text)" : "#4A5568",
                  background: selectedSheet === sheet ? "var(--hw-gold-light)" : "transparent",
                  fontWeight: selectedSheet === sheet ? 600 : 400,
                }}
              >
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sheet}</span>
                {selectedSheet === sheet && <ChevronRight size={12} />}
              </button>
            ))}
          </div>

          {/* 시트 데이터 (우측) */}
          <div style={{ flex: 1, minWidth: 0 }}>
            {dataLoading || isFetching ? (
              <div className="hw-card" style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: "#A0AEC0" }}>
                <RefreshCw size={14} style={{ animation: "spin 1s linear infinite", color: "var(--hw-gold)" }} />
                데이터 불러오는 중...
              </div>
            ) : !sheetData ? (
              <div className="hw-card" style={{ fontSize: 13, textAlign: "center", padding: "40px 0", color: "#A0AEC0" }}>
                좌측에서 시트를 선택하세요.
              </div>
            ) : sheetData.rows.length === 0 ? (
              <div className="hw-card" style={{ fontSize: 13, textAlign: "center", padding: "40px 0", color: "#A0AEC0" }}>
                <div style={{ fontWeight: 500, marginBottom: 4 }}>&quot;{sheetData.sheet}&quot; 시트에 데이터가 없습니다.</div>
                <div style={{ fontSize: 12 }}>원본 시트에서 내용을 입력해주세요.</div>
              </div>
            ) : (
              <div className="hw-card" style={{ padding: 0, overflow: "hidden" }}>
                {/* 시트명 + 행수 */}
                <div style={{ padding: "10px 16px", borderBottom: "1px solid #E2E8F0", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#2D3748" }}>{sheetData.sheet}</div>
                  <div style={{ fontSize: 12, color: "#A0AEC0" }}>{sheetData.rows.length}행</div>
                </div>
                {/* 테이블 */}
                <div style={{ overflowX: "auto", overflowY: "auto", maxHeight: "calc(100vh - 260px)" }}>
                  <table className="hw-table" style={{ width: "100%", fontSize: 12 }}>
                    <thead>
                      <tr>
                        {sheetData.headers.map((h: string) => (
                          <th key={h} style={{ textAlign: "left", whiteSpace: "nowrap" }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sheetData.rows.map((row: Record<string, string>, i: number) => (
                        <tr key={i}>
                          {sheetData.headers.map((h: string) => (
                            <td
                              key={h}
                              style={{ verticalAlign: "top", whiteSpace: "pre-wrap", wordBreak: "break-word", maxWidth: 400 }}
                            >
                              {row[h] ?? ""}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ padding: "6px 16px", borderTop: "1px solid #E2E8F0", fontSize: 11, color: "#A0AEC0" }}>
                  편집은 원본 시트에서 해주세요.
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
