// frontend/lib/types/reference.ts

export interface SheetData {
  sheet: string;
  headers: string[];
  rows: Record<string, string>[];
}

export interface ColWidths {
  [colKey: string]: number; // px, default 120
}

export interface RowHeights {
  [rowIndex: number]: number; // px
}
