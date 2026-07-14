"use client";
// v3 자격 중심 화면 공용 컴포넌트 (FEATURE_GUIDELINES_V3, 관리자 read-only 베타)
import { V3Program, V3Route } from "@/lib/api";

// ── 자격코드 자연 정렬 ────────────────────────────────────────────────────────
// D-2 < D-10, E-7 < E-7-4 < E-7-S1, F-1-5 < F-1-15. 단순 문자열 정렬 금지.
// backend/routers/guidelines_v3.py 의 qual_code_sort_key 와 로직 일치 유지.
type SegKey = [number, number | string, number | string];
function qualCodeSortKey(code: string): SegKey[] {
  const parts = (code || "").split("-");
  if (parts.length === 0) return [];
  const key: SegKey[] = [[1, parts[0], 0]];
  for (const seg of parts.slice(1)) {
    let m = /^(\d+)([A-Za-z]*)$/.exec(seg);
    if (m) { key.push([0, parseInt(m[1], 10), m[2]]); continue; }
    m = /^([A-Za-z]+)(\d*)$/.exec(seg);
    if (m) { key.push([1, m[1], m[2] ? parseInt(m[2], 10) : 0]); continue; }
    key.push([2, seg, 0]);
  }
  return key;
}
function cmpVal(a: number | string, b: number | string): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  const as = String(a), bs = String(b);
  return as < bs ? -1 : as > bs ? 1 : 0;
}
export function compareQualCode(a: string, b: string): number {
  const ka = qualCodeSortKey(a), kb = qualCodeSortKey(b);
  const n = Math.min(ka.length, kb.length);
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < 3; j++) {
      const c = cmpVal(ka[i][j], kb[i][j]);
      if (c !== 0) return c;
    }
  }
  return ka.length - kb.length;
}

// ── 내부 id 표시 차단 ─────────────────────────────────────────────────────────
// VR:/SB:/Q:/PG: 내부 id 는 데이터 연결용 — 사용자 문구에 남아 있으면 제거(안전망).
export function stripInternalIds(text: string | null | undefined): string {
  if (!text) return "";
  return text
    .replace(/\(\s*(?:VR|SB|Q|PG):[^)]*\)/g, "")
    .replace(/(?:VR|SB|Q|PG):[A-Za-z0-9_\-.]+/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

// ── applicability 배지 규약 (09 목업 기준) ──────────────────────────────────
export const APPLICABILITY_STYLE: Record<string, { label: string; color: string; bg: string; border: string }> = {
  applicable:     { label: "가능",     color: "#2C7A7B", bg: "#E6FFFA", border: "#81E6D9" },
  not_applicable: { label: "불가",     color: "#4A5568", bg: "#EDF2F7", border: "#CBD5E0" },
  conditional:    { label: "조건부",   color: "#975A16", bg: "#FFFFF0", border: "#F6E05E" },
  unknown:        { label: "확인필요", color: "#C53030", bg: "#FFF5F5", border: "#FEB2B2" },
};

export function ApplicabilityBadge({ value }: { value: string }) {
  const s = APPLICABILITY_STYLE[value] ?? APPLICABILITY_STYLE.unknown;
  return (
    <span style={{ display:"inline-block", fontSize:11, fontWeight:700, padding:"3px 10px",
      borderRadius:99, color:s.color, background:s.bg, border:`1px solid ${s.border}`, whiteSpace:"nowrap" }}>
      {s.label}
    </span>
  );
}

export const ROUTE_TYPE_LABEL: Record<string, string> = {
  consulate: "공관장재량 사증",
  recognition: "사증발급인정신청",
  evisa: "전자사증",
  both: "공관·인정 병행",
  not_applicable: "사증발급인정서 대상 아님",
  excluded: "사증발급인정서 제외",
  domestic_only: "국내 체류자격 부여·변경 경로",
  alternative_route: "대체 신청 경로",
  discontinued: "신규 신청 중단",
};

// 경로 배지(2026-07-14 유형 분리): 실제 신청 경로(가능)와 상태 행(대상 아님/국내 경로/신청 중단),
// 대체 경로를 시각적으로 구분한다.
export function routeTone(r: V3Route): { color: string; bg: string; border: string; badge: string } {
  if (r.status === "abolished" || r.route_type === "discontinued")
    return { color:"#822727", bg:"#FFF5F5", border:"#FEB2B2", badge:"신규 신청 불가" };
  if (r.route_type === "not_applicable" || r.route_type === "excluded")
    return { color:"#4A5568", bg:"#EDF2F7", border:"#CBD5E0", badge:"대상 아님" };
  if (r.route_type === "domestic_only")
    return { color:"#2B6CB0", bg:"#EBF8FF", border:"#90CDF4", badge:"국내 경로" };
  if (r.route_type === "alternative_route")
    return { color:"#553C9A", bg:"#FAF5FF", border:"#D6BCFA", badge:"대체 경로" };
  return { color:"#2C7A7B", bg:"#E6FFFA", border:"#81E6D9", badge:"가능" };
}

export function ConfidenceChip({ value }: { value: string }) {
  if (value === "high") return null;
  return (
    <span style={{ fontSize:10, fontWeight:700, padding:"2px 7px", borderRadius:6,
      background:"#FFF5F5", color:"#C53030", border:"1px solid #FEB2B2" }}>
      {value === "medium" ? "추가 확인 필요" : "확인 필요"}
    </span>
  );
}

export function ProgramChip({ program, small }: { program: V3Program; small?: boolean }) {
  return (
    <span style={{ display:"inline-flex", alignItems:"center", gap:4,
      fontSize: small ? 10 : 11, fontWeight:600, padding: small ? "2px 8px" : "3px 10px",
      borderRadius:99, background:"rgba(212,168,67,0.10)", color:"var(--hw-gold-text)",
      border:"1px solid rgba(212,168,67,0.35)", whiteSpace:"nowrap" }}>
      🏷 {program.program_name}
    </span>
  );
}

export function SourceNote({ manual, pages }: { manual: string; pages: number[] }) {
  if (!manual && (!pages || pages.length === 0)) return null;
  return (
    <span style={{ fontSize:11, color:"#A0AEC0" }}>
      근거: {manual}{pages && pages.length > 0 ? ` p.${pages.join(", ")}` : ""}
    </span>
  );
}
