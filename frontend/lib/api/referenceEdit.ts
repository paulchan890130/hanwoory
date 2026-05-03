// frontend/lib/api/referenceEdit.ts
// 업무참고 인라인 편집 API 클라이언트 — 변경된 단위만 호출

import { api } from "@/lib/api";

function _detail(err: unknown): string {
  const e = err as { response?: { data?: { detail?: string } } };
  return e?.response?.data?.detail ?? String(err);
}

async function call<T>(fn: () => Promise<{ data: T }>): Promise<T> {
  try {
    const res = await fn();
    return res.data;
  } catch (err) {
    throw new Error(_detail(err));
  }
}

export const referenceEditApi = {
  // ── 셀 ────────────────────────────────────────────────────────────────────
  updateCell: (sheetName: string, rowIndex: number, colKey: string, value: string) =>
    call(() => api.patch("/api/reference/cell", { sheet_name: sheetName, row_index: rowIndex, col_key: colKey, value })),

  // ── 행 ────────────────────────────────────────────────────────────────────
  insertRow: (sheetName: string, insertAfter: number | null, values: Record<string, string>) =>
    call(() => api.post("/api/reference/row", { sheet_name: sheetName, insert_after: insertAfter, values })),
  deleteRow: (sheetName: string, rowIndex: number) =>
    call(() => api.delete("/api/reference/row", { data: { sheet_name: sheetName, row_index: rowIndex } })),
  reorderRow: (sheetName: string, fromIndex: number, toIndex: number) =>
    call(() => api.patch("/api/reference/row/reorder", { sheet_name: sheetName, from_index: fromIndex, to_index: toIndex })),
  updateRowHeight: (sheetName: string, rowIndex: number, pixelHeight: number) =>
    call(() => api.patch("/api/reference/row/height", { sheet_name: sheetName, row_index: rowIndex, pixel_height: pixelHeight })),

  // ── 열 ────────────────────────────────────────────────────────────────────
  insertColumn: (sheetName: string, colName: string, insertAfter: string | null) =>
    call(() => api.post("/api/reference/column", { sheet_name: sheetName, col_name: colName, insert_after: insertAfter })),
  deleteColumn: (sheetName: string, colKey: string) =>
    call(() => api.delete("/api/reference/column", { data: { sheet_name: sheetName, col_key: colKey } })),
  renameColumn: (sheetName: string, oldName: string, newName: string) =>
    call(() => api.patch("/api/reference/column/rename", { sheet_name: sheetName, old_name: oldName, new_name: newName })),
  updateColumnWidth: (sheetName: string, colKey: string, pixelWidth: number) =>
    call(() => api.patch("/api/reference/column/width", { sheet_name: sheetName, col_key: colKey, pixel_width: pixelWidth })),

  // ── 시트 탭 ───────────────────────────────────────────────────────────────
  addSheet: (sheetName: string) =>
    call(() => api.post("/api/reference/sheet", { sheet_name: sheetName })),
  deleteSheet: (sheetName: string) =>
    call(() => api.delete("/api/reference/sheet", { data: { sheet_name: sheetName } })),
  renameSheet: (oldName: string, newName: string) =>
    call(() => api.patch("/api/reference/sheet/rename", { old_name: oldName, new_name: newName })),
};
