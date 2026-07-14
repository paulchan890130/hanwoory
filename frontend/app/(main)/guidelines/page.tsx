"use client";
import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { useRouter } from "next/navigation";
import {
  Search, BookOpen, ChevronDown, ChevronUp, X, Loader2,
  FileText, Paperclip, AlertCircle, BookMarked,
  ArrowRight, GitBranch, ShieldAlert, ChevronRight,
  Info, CheckCircle2, Layers, ExternalLink as ExtLinkIcon, Maximize2,
  Pencil, Plus, Trash2, Check, Trees,
} from "lucide-react";
import { GuidelineSubType, ManualRef } from "@/lib/api";
import { guidelinesApi, guidelineCategoriesApi, GuidelineRow, GuidelineEntryPoint, api } from "@/lib/api";
import { getUser, canManageContent } from "@/lib/auth";
import {
  ACTION_TYPE_LABELS, ACTION_TYPE_COLORS, ActionBadge, DocChip, GuidelineCard, buildQuickDocUrl,
} from "@/components/guidelines/shared";
import { sanitizeFeeRuleDisplay } from "@/components/qualifications/v2docSanitize";
import { toast } from "sonner";

// ── 업무유형 한글 라벨 ────────────────────────────────────────────────────────
// (ACTION_TYPE_LABELS/COLORS · ActionBadge · DocChip · GuidelineCard · buildQuickDocUrl 은
//  @/components/guidelines/shared 로 이동 — v3 자격 중심 화면과 공용, 동작 불변)

// 운영 화면 출처 비노출 원칙: 자료 출처·페이지가 드러나는 UI(매뉴얼 페이지 버튼·뷰어, 근거 섹션)는
// 화면에서 숨긴다. manual_ref/basis_section 데이터와 API·PDF 엔드포인트는 그대로 유지(비노출만).
const SHOW_INTERNAL_SOURCE_UI = false;

// ── 새 트리: 업무유형 전체 라벨 (상세) ─────────────────────────────────────
const ACTION_LABELS: Record<string, string> = {
  EXTEND:                    "체류기간 연장허가",
  CHANGE:                    "체류자격 변경허가",
  REGISTRATION:              "외국인 등록",
  REENTRY:                   "재입국 허가",
  EXTRA_WORK:                "체류자격외 활동",
  WORKPLACE:                 "근무처 변경·추가",
  GRANT:                     "체류자격 부여",
  VISA_CONFIRM:              "사증",
  DOMESTIC_RESIDENCE_REPORT: "거소신고",
  APPLICATION_CLAIM:         "직접신청",
  ACTIVITY_EXTRA:            "활동범위 확대",
};

const FAMILY_LABELS: Record<string, string> = {
  A: "A (외교·공무)",
  B: "B (사증면제·관광통과)",
  C: "C (단기체류)",
  D: "D (유학·연수·투자)",
  E: "E (전문직업·기술)",
  F: "F (거주·영주·결혼·동포)",
  G: "G (기타)",
  H: "H (방문취업·관광취업)",
};

const MID_LABELS: Record<string, string> = {
  "A-1": "외교",
  "A-2": "공무",
  "A-3": "협정",
  "B-1": "사증면제",
  "B-2": "관광통과",
  "C-1": "일시취재",
  "C-3": "단기방문",
  "C-4": "단기취업",
  "D-1": "문화예술",
  "D-2": "유학",
  "D-3": "기술연수",
  "D-4": "일반연수",
  "D-5": "취재",
  "D-6": "종교",
  "D-7": "주재",
  "D-8": "기업투자",
  "D-9": "무역경영",
  "D-10": "구직",
  "E-1": "교수",
  "E-2": "회화지도",
  "E-3": "연구",
  "E-4": "기술지도",
  "E-5": "전문직업",
  "E-6": "예술흥행",
  "E-7": "특정활동",
  "E-8": "계절근로",
  "E-9": "비전문취업",
  "E-10": "선원취업",
  "F-1": "방문동거",
  "F-2": "거주",
  "F-3": "동반",
  "F-4": "재외동포",
  "F-5": "영주",
  "F-6": "결혼이민",
  "G-1": "기타",
  "H-1": "관광취업",
  "H-2": "방문취업",
};

const SUB_LABELS: Record<string, string> = {
  "E-7-1": "전문인력",
  "E-7-2": "준전문인력",
  "E-7-3": "일반기능인력",
  "E-7-4": "숙련기능인력",
  "E-7-S": "네거티브방식 전문인력",
  "E-7-T": "최우수인재",
  "E-7-Y": "청년특별",
  "E-7-4R": "지역특화형 숙련기능",
  "D-2-1": "전문학사",
  "D-2-2": "학사",
  "D-2-3": "석사",
  "D-2-4": "박사",
  "D-2-5": "연구생",
  "D-2-6": "교환학생",
  "D-2-7": "사이버대학",
  "D-2-8": "소재부품",
  "D-4-1": "한국어연수",
  "D-4-7": "외국어연수",
  "D-8-1": "법인투자",
  "D-8-2": "벤처투자",
  "D-8-3": "개인기업투자",
  "D-10-1": "일반구직",
  "D-10-2": "기술창업준비",
  "D-10-3": "첨단기술인턴",
  "D-10-T": "최우수인재구직",
  "F-1-5": "결혼이민자 부모 방문동거",
  "F-1-11": "방문취업자 가족",
  "F-1-15": "우수인재·투자자·유학생 부모",
  "F-1-21": "외국공관원 가사보조인",
  "F-1-22": "고액투자가 가사보조인",
  "F-1-24": "해외우수인재 가사보조인",
  "F-2-3": "영주자 배우자·미성년자녀",
  "F-2-4": "난민인정자",
  "F-2-5": "고액투자자",
  "F-2-6": "숙련생산기능",
  "F-2-7": "점수제 우수인재",
  "F-2-71": "K-STAR 거주",
  "F-2-99": "기타 장기체류자",
  "F-2-R": "지역특화형 우수인재",
  "F-2-T": "최우수인재 거주",
  "F-3-3R": "지역특화 숙련기능인력 가족",
  "F-4-R": "지역특화형 재외동포",
  "F-4-19": "지역특화형 재외동포(고시)",
  "F-5-1": "국민배우자 등 5년",
  "F-5-2": "영주자 배우자·미성년자녀",
  "F-5-6": "결혼이민 2년",
  "F-5-10": "재외동포 동포영주",
  "F-5-11": "특정분야 능력소유자",
  "F-5-14": "방문취업 제조업 4년",
  "F-5-S1": "K-STAR 영주",
  "E-10-2": "어선원",
  "H-2": "방문취업",
};

const ACTION_TYPE_ORDER = [
  "CHANGE","EXTEND","REGISTRATION","EXTRA_WORK","WORKPLACE",
  "GRANT","REENTRY","VISA_CONFIRM","APPLICATION_CLAIM",
  "DOMESTIC_RESIDENCE_REPORT","ACTIVITY_EXTRA",
];

const ACTION_TYPE_TABS = [
  { key: "",                          label: "전체" },
  { key: "CHANGE",                    label: "변경" },
  { key: "EXTEND",                    label: "연장" },
  { key: "EXTRA_WORK",                label: "자격외활동" },
  { key: "WORKPLACE",                 label: "근무처" },
  { key: "REGISTRATION",              label: "등록" },
  { key: "REENTRY",                   label: "재입국" },
  { key: "GRANT",                     label: "자격부여" },
  { key: "VISA_CONFIRM",              label: "사증발급인정" },
  { key: "APPLICATION_CLAIM",         label: "직접신청" },
  { key: "DOMESTIC_RESIDENCE_REPORT", label: "거소신고" },
  { key: "ACTIVITY_EXTRA",            label: "활동범위" },
];

// ── EXTRA_WORK: row_id → 신청자 현재 자격 키 ─────────────────────────────────
const EXTRA_WORK_APPLICANT_MAP: Record<string, string> = {
  "M1-0042": "E-1/E-3/E-4/E-5",
  "M1-0047": "F-3 (전문인력 배우자)",
  "M1-0050": "D-2",
  "M1-0052": "F-3 (전문인력 배우자)",
  "M1-0058": "A-3",
  "M1-0059": "F-3 (전문인력 배우자)",
  "M1-0060": "F-3 (전문인력 배우자)",
  "M1-0061": "F-3 (전문인력 배우자)",
  "M1-0062": "C-4-5/E-7",
  "M1-0063": "C-4-5/E-7",
  "M1-0064": "C-4-5/E-7",
  "M1-0065": "A-1/A-2",
  "M1-0066": "A-1/A-2",
  "M1-0067": "A-1/A-2",
  "M1-0068": "A-1/A-2",
  "M1-0069": "A-1/A-2",
  "M1-0070": "F-3 (전문인력 배우자)",
  "M1-0071": "F-1/F-3",
  "M1-0072": "F-1/F-3",
  "M1-0073": "F-1 (중국동포)",
  "M1-0074": "제주 특화",
  "M1-0075": "제주 특화",
  "M1-0076": "제주 특화",
  "M1-0077": "G-1",
  "M1-0078": "G-1",
  "M1-0079": "A-1/A-2",
  "M1-0080": "F-1 (중국동포)",
  "M1-0081": "E-7",
  "M1-0082": "G-1",
  "M1-0083": "F-3 (전문인력 배우자)",
};

const APPLICANT_LABELS: Record<string, string> = {
  "A-1":                   "A-1 (외교)",
  "A-2":                   "A-2 (공무)",
  "A-1/A-2":               "A-1/A-2 (외교·공무)",
  "A-3":                   "A-3 (협정)",
  "C-4-5/E-7":             "C-4-5/E-7 (단기취업·특정활동)",
  "D-1":                   "D-1 (문화예술)",
  "D-2":                   "D-2 (유학)",
  "D-2-1":                 "D-2-1 (전문학사 유학)",
  "D-2-2":                 "D-2-2 (학사 유학)",
  "D-2-3":                 "D-2-3 (석사 유학)",
  "D-2-4":                 "D-2-4 (박사 유학)",
  "D-2-5":                 "D-2-5 (연구과정 유학)",
  "D-2-6":                 "D-2-6 (교환학생)",
  "D-2-7":                 "D-2-7 (일-학습 연계)",
  "D-2-8":                 "D-2-8 (방문학생)",
  "D-4-1":                 "D-4-1 (한국어연수)",
  "D-4-2":                 "D-4-2 (일반연수)",
  "D-4-7":                 "D-4-7 (외국어연수)",
  "D-6":                   "D-6 (종교)",
  "D-7":                   "D-7 (주재)",
  "D-8-1":                 "D-8-1 (법인투자)",
  "D-8-3":                 "D-8-3 (개인기업투자)",
  "D-10-1":                "D-10-1 (일반구직)",
  "D-10-2":                "D-10-2 (기술창업준비)",
  "D-10-3":                "D-10-3 (첨단기술인턴)",
  "E-1":                   "E-1 (교수)",
  "E-1/E-3/E-4/E-5":       "E-1/E-3/E-4/E-5 (교수·연구·기술지도·전문직업)",
  "E-3":                   "E-3 (연구)",
  "E-4":                   "E-4 (기술지도)",
  "E-5":                   "E-5 (전문직업)",
  "E-7":                   "E-7 (특정활동)",
  "F-1/F-3":               "F-1/F-3 (방문동거·동반)",
  "F-1 (중국동포)":        "F-1 (방문동거 중국동포)",
  "F-3 (전문인력 배우자)": "F-3 (전문인력·고액투자자 배우자)",
  "F-3-2R":                "F-3-2R (지역동포가족)",
  "F-4":                   "F-4 (재외동포)",
  "G-1":                   "G-1 (기타)",
  "제주 특화":             "제주도 특화 대상",
};

// ── TB 적용 대상 action_type ───────────────────────────────────────────────────
const TB_APPLICABLE_TYPES = new Set(["REGISTRATION", "CHANGE", "EXTEND", "GRANT"]);
const TB_STAGE_LABEL: Record<string, string> = {
  REGISTRATION: "외국인등록 신청 시",
  CHANGE:       "체류자격 변경 허가 신청 시",
  EXTEND:       "체류기간 연장 허가 신청 시",
  GRANT:        "체류자격 부여 신청 시",
};

// ── 진입점 fallback ────────────────────────────────────────────────────────────
const ENTRY_POINTS: GuidelineEntryPoint[] = [
  { id:"F5",   label:"영주 (F-5)",        subtitle:"체류자격 변경·등록",    codes:"F-5",       color:"#48BB78", search_query:"F-5",        action_types:["CHANGE","REGISTRATION"] },
  { id:"F4",   label:"재외동포 (F-4)",    subtitle:"변경·연장·등록",        codes:"F-4",       color:"#4299E1", search_query:"F-4",        action_types:["CHANGE","EXTEND","REGISTRATION"] },
  { id:"E7",   label:"특정활동 (E-7)",    subtitle:"변경·연장·부여",        codes:"E-7",       color:"#9F7AEA", search_query:"E-7",        action_types:["CHANGE","EXTEND","GRANT"] },
  { id:"D2",   label:"유학 (D-2)",        subtitle:"등록·변경·연장·자격외활동", codes:"D-2",  color:"#667EEA", search_query:"D-2",        action_types:["CHANGE","EXTEND","REGISTRATION","EXTRA_WORK"] },
  { id:"H2",   label:"방문취업 (H-2)",    subtitle:"등록·연장·변경",        codes:"H-2",       color:"#ED8936", search_query:"H-2",        action_types:["CHANGE","EXTEND","REGISTRATION"] },
  { id:"F6",   label:"결혼이민 (F-6)",    subtitle:"변경·연장·부여",        codes:"F-6",       color:"#FC8181", search_query:"F-6",        action_types:["CHANGE","EXTEND","GRANT"] },
  { id:"F2",   label:"거주 (F-2)",        subtitle:"변경·연장·부여",        codes:"F-2",       color:"#F6AD55", search_query:"F-2",        action_types:["CHANGE","EXTEND","GRANT"] },
  { id:"REG",  label:"외국인 등록",        subtitle:"최초 등록 절차",        codes:"등록",       color:"#38B2AC", search_query:"외국인등록",  action_types:["REGISTRATION"] },
  { id:"REEN", label:"재입국 허가",        subtitle:"단수·복수 재입국",      codes:"재입국",     color:"#F6AD55", search_query:"재입국허가",  action_types:["REENTRY"] },
  { id:"EX",   label:"체류자격 외 활동",  subtitle:"시간제취업·기타",       codes:"자격외활동", color:"#ED8936", search_query:"시간제취업",  action_types:["EXTRA_WORK"] },
  { id:"WP",   label:"근무처 변경·추가",  subtitle:"취업자격 근무처",       codes:"근무처",     color:"#9F7AEA", search_query:"근무처변경",  action_types:["WORKPLACE"] },
  { id:"GR",   label:"체류자격 부여",     subtitle:"출생·귀화 후 부여",     codes:"부여",       color:"#FC8181", search_query:"체류자격부여",action_types:["GRANT"] },
  { id:"VC",   label:"사증",              subtitle:"자격별 사증 절차",         codes:"사증",       color:"#667EEA", search_query:"사증발급인정",action_types:["VISA_CONFIRM"] },
  { id:"DR",   label:"거소신고",          subtitle:"재외동포 거소",          codes:"거소",       color:"#68D391", search_query:"거소신고",    action_types:["DOMESTIC_RESIDENCE_REPORT"] },
];

// ── buildTree: 새 트리 구조 생성 ──────────────────────────────────────────────
function getMidCode(code: string): string {
  if (!code) return "_BLANK";
  const parts = code.split("-");
  if (parts.length >= 2) return parts[0] + "-" + parts[1];
  return code;
}

function getFamily(code: string): string {
  if (!code) return "_BLANK";
  return code[0].toUpperCase();
}

function hasSub(code: string): boolean {
  return code.split("-").length >= 3;
}

interface TreeNode {
  action: string;
  family: string;
  mid: string;
  sub: string | null;  // null = 소분류 없음
  rows: GuidelineRow[];
}

// ── 분류 오버레이(A+) — source_key 는 backend seed 로직과 동일 ────────────────
// major = "M|{action}" / middle = "m|{action}|{family}" / minor = "s|{action}|{family}|{mid}"
type GLCat = import("@/lib/api").GuidelineCategory;
export interface GLOverlay {
  byId: Map<number, GLCat>;
  bySourceKey: Map<string, GLCat>;
  overrides: Record<string, number>;
}
function skMajor(action: string): string { return `M|${action || "_OTHER"}`; }
function skMiddle(action: string, code: string): string { return `m|${action || "_OTHER"}|${getFamily(code)}`; }
function skMinor(action: string, code: string): string { return `s|${action || "_OTHER"}|${getFamily(code)}|${getMidCode(code)}`; }
function parseSk(sk: string): { action: string; family: string; mid: string } | null {
  const p = (sk || "").split("|");
  if (p[0] === "M" && p.length >= 2) return { action: p[1], family: "", mid: "" };
  if (p[0] === "m" && p.length >= 3) return { action: p[1], family: p[2], mid: "" };
  if (p[0] === "s" && p.length >= 4) return { action: p[1], family: p[2], mid: p[3] };
  return null;
}
// override 대상 category → 트리 좌표(action/family/mid). source_key 없으면 부모 체인으로 해석.
function resolveCatCoords(cat: GLCat | undefined, ov: GLOverlay): { action: string; family: string; mid: string } | null {
  if (!cat || cat.level !== "minor" || !cat.is_active) return null;
  const minorKey = cat.source_key ? (parseSk(cat.source_key)?.mid || `__C${cat.id}`) : `__C${cat.id}`;
  const middle = cat.parent_id != null ? ov.byId.get(cat.parent_id) : undefined;
  const famKey = middle?.source_key ? (parseSk(middle.source_key)?.family || `__C${middle.id}`) : (middle ? `__C${middle.id}` : "_BLANK");
  const major = middle?.parent_id != null ? ov.byId.get(middle.parent_id) : undefined;
  const actKey = major?.source_key ? (parseSk(major.source_key)?.action || `__C${major.id}`) : (major ? `__C${major.id}` : (cat.source_key ? (parseSk(cat.source_key)?.action || "_OTHER") : "_OTHER"));
  return { action: actKey, family: famKey, mid: minorKey };
}

function buildTree(rows: GuidelineRow[], overlay?: GLOverlay | null): Map<string, Map<string, Map<string, GuidelineRow[]>>> {
  // action → family → mid → rows
  const tree = new Map<string, Map<string, Map<string, GuidelineRow[]>>>();
  for (const row of rows) {
    const action0 = row.action_type || "_OTHER";
    const code = row.detailed_code || "";
    let action = action0, fam = getFamily(code), mid = getMidCode(code);

    // override: row_id → category. 대상이 active minor면 그 좌표로 재배치, 아니면 원래 JSON 분류로 fallback.
    if (overlay) {
      const ovId = overlay.overrides[row.row_id];
      if (ovId != null) {
        const coords = resolveCatCoords(overlay.byId.get(ovId), overlay);
        if (coords) { action = coords.action; fam = coords.family; mid = coords.mid; }
        // 대상이 없거나 비활성/비-minor면 coords=null → 아래 비활성 검사 후 자연 분류/미분류
      } else {
        // override 없는 row: JSON 파생 분류 중 하나라도 비활성이면 '미분류' 버킷으로 보존(숨김+유실방지)
        const inact = (k: string): boolean => { const c = overlay.bySourceKey.get(k); return !!c && c.is_active === false; };
        if (inact(skMajor(action0)) || inact(skMiddle(action0, code)) || inact(skMinor(action0, code))) {
          action = "__UNCLASSIFIED__"; fam = "_ALL"; mid = "_ALL";
        }
      }
    }

    if (!tree.has(action)) tree.set(action, new Map());
    const famMap = tree.get(action)!;
    if (!famMap.has(fam)) famMap.set(fam, new Map());
    const midMap = famMap.get(fam)!;
    if (!midMap.has(mid)) midMap.set(mid, []);
    midMap.get(mid)!.push(row);
  }
  return tree;
}

// 대분류(action_type) 한글 라벨 — backend ACTION_KO 와 동일. (2차 안전장치)
const MAJOR_KO: Record<string, string> = {
  CHANGE: "체류자격 변경", EXTEND: "체류기간 연장", REGISTRATION: "외국인등록",
  EXTRA_WORK: "체류자격외활동", WORKPLACE: "근무처 변경·추가", GRANT: "체류자격 부여",
  REENTRY: "재입국허가", VISA_CONFIRM: "사증", APPLICATION_CLAIM: "각종 신청·신고",
  DOMESTIC_RESIDENCE_REPORT: "국내거소신고", ACTIVITY_EXTRA: "활동범위 추가",
};
// display_name 이 비었거나 영문코드와 같을 때 쓸 한글 기본 표시명.
function glDefaultLabel(level: "major" | "middle" | "minor", action: string, family: string, fallback: string): string {
  if (level === "major") return MAJOR_KO[action] ?? ACTION_LABELS[action] ?? fallback;
  if (level === "middle") return FAMILY_LABELS[family] ?? fallback;
  return fallback; // minor: 코드 그대로(fallback=mid)
}
// 분류 표시명: overlay display_name 우선(사용자 수정값/한글). 비었거나 raw 코드와 같으면 한글 기본 라벨.
function glLabel(level: "major" | "middle" | "minor", action: string, family: string, mid: string,
                 overlay: GLOverlay | null | undefined, fallback: string): string {
  if (action === "__UNCLASSIFIED__") return level === "major" ? "미분류(비활성 분류 항목)" : "전체";
  if (family === "_ALL" || mid === "_ALL") return "전체";
  const rawCode = level === "major" ? action : level === "middle" ? family : mid;
  let dn: string | undefined;
  if (overlay) {
    if (typeof rawCode === "string" && rawCode.startsWith("__C")) {
      dn = overlay.byId.get(Number(rawCode.slice(3)))?.display_name;
    } else {
      const sk = level === "major" ? skMajor(action) : level === "middle" ? `m|${action || "_OTHER"}|${family}` : `s|${action || "_OTHER"}|${family}|${mid}`;
      dn = overlay.bySourceKey.get(sk)?.display_name;
    }
  }
  // 사용자 수정/한글 값이면 그대로. 비었거나 영문코드(rawCode)와 동일하면 한글 기본 라벨로 대체.
  if (dn && dn.trim() && dn !== rawCode) return dn;
  return glDefaultLabel(level, action, family, fallback);
}
function glSortKeys(level: "major" | "middle" | "minor", action: string, family: string, keys: string[],
                    overlay: GLOverlay | null | undefined): string[] {
  if (!overlay) return [...keys].sort();
  const orderOf = (k: string): number => {
    if (k.startsWith("__C")) return overlay.byId.get(Number(k.slice(3)))?.sort_order ?? 9999;
    const sk = level === "major" ? skMajor(k) : level === "middle" ? `m|${action || "_OTHER"}|${k}` : `s|${action || "_OTHER"}|${family}|${k}`;
    const c = overlay.bySourceKey.get(sk);
    return c ? c.sort_order : 9999;
  };
  return [...keys].sort((a, b) => (orderOf(a) - orderOf(b)) || a.localeCompare(b));
}

// ── 트리 헬퍼 ──────────────────────────────────────────────────────────────────
function isCodeEntry(entry: GuidelineEntryPoint): boolean {
  return /^[A-Z]-[0-9A-Z]/i.test(entry.search_query);
}

function getMatchingRows(rows: GuidelineRow[], entry: GuidelineEntryPoint): GuidelineRow[] {
  const q = entry.search_query.toLowerCase();
  if (isCodeEntry(entry)) {
    return rows.filter(r => (r.detailed_code || "").toLowerCase().startsWith(q));
  }
  const atFilter = new Set(entry.action_types || []);
  return rows.filter(r => atFilter.size === 0 || atFilter.has(r.action_type));
}

async function fetchRowsForEntry(entry: GuidelineEntryPoint): Promise<GuidelineRow[]> {
  if (isCodeEntry(entry)) {
    const res = await guidelinesApi.getTreeResults({ search_query: entry.search_query, limit: 100 });
    return Array.isArray(res.data.data) ? res.data.data : [];
  }
  const actionTypes = entry.action_types || [];
  if (actionTypes.length === 1) {
    const res = await guidelinesApi.getTreeResults({ action_type: actionTypes[0], limit: 100 });
    return Array.isArray(res.data.data) ? res.data.data : [];
  }
  const res = await guidelinesApi.list({ limit: 500, status: "all" });
  return getMatchingRows(Array.isArray(res.data.data) ? res.data.data : [], entry);
}

// (buildQuickDocUrl · DocChip · ActionBadge — @/components/guidelines/shared 로 이동)

// ── 서류 섹션 (DetailPanel 전용) ───────────────────────────────────────────────
function DocSection({ title, icon, color, docs }: { title: string; icon: React.ReactNode; color: string; docs: string[] }) {
  if (docs.length === 0) return null;
  return (
    <div>
      <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:8 }}>
        {icon}
        <span style={{ fontSize:12, fontWeight:700, color }}>{title}</span>
        <span style={{ fontSize:11, color:"#A0AEC0" }}>({docs.length})</span>
      </div>
      <div style={{ display:"flex", flexWrap:"wrap", gap:6 }}>
        {docs.map((doc, i) => <DocChip key={i} text={doc} color={color} />)}
      </div>
    </div>
  );
}

// ── 인라인 파이프 편집기 ──────────────────────────────────────────────────────
function PipeEditor({
  items,
  onChange,
}: {
  items: string[];
  onChange: (items: string[]) => void;
}) {
  return (
    <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
      {items.map((item, i) => (
        <div key={i} style={{ display:"flex", gap:6, alignItems:"center" }}>
          <input
            value={item}
            onChange={e => { const n = [...items]; n[i] = e.target.value; onChange(n); }}
            style={{ flex:1, fontSize:12, padding:"5px 9px", border:"1px solid #CBD5E0", borderRadius:6, outline:"none" }}
          />
          <button
            onClick={() => onChange(items.filter((_, j) => j !== i))}
            style={{ padding:"4px 7px", borderRadius:6, border:"1px solid #FEB2B2", background:"#FFF5F5", color:"#C53030", cursor:"pointer" }}
            title="삭제"
          >
            <Trash2 size={12} />
          </button>
        </div>
      ))}
      <button
        onClick={() => onChange([...items, ""])}
        style={{ display:"flex", alignItems:"center", gap:5, fontSize:11, padding:"5px 10px", borderRadius:6, border:"1px dashed #CBD5E0", background:"#F7FAFC", color:"#718096", cursor:"pointer" }}
      >
        <Plus size={11} /> 항목 추가
      </button>
    </div>
  );
}

// ── form_docs 채널 편집기 ─────────────────────────────────────────────────────
function FormDocsEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const hasChannels = value.includes("【전자민원】") || value.includes("【창구민원】");

  const [onlineItems, setOnlineItems] = useState<string[]>(() => {
    if (!hasChannels) return [];
    const m = value.match(/【전자민원】([^【]*)/);
    return m ? m[1].split("|").map(s => s.trim()).filter(Boolean) : [];
  });
  const [counterItems, setCounterItems] = useState<string[]>(() => {
    if (!hasChannels) return [];
    const m = value.match(/【창구민원】([^【]*)/);
    return m ? m[1].split("|").map(s => s.trim()).filter(Boolean) : [];
  });
  const [simpleItems, setSimpleItems] = useState<string[]>(() => {
    if (hasChannels) return [];
    return value.split("|").map(s => s.trim()).filter(Boolean);
  });

  useEffect(() => {
    if (hasChannels) {
      const assembled = `【전자민원】 ${onlineItems.join(" | ")} || 【창구민원】 ${counterItems.join(" | ")}`;
      onChange(assembled);
    } else {
      onChange(simpleItems.join(" | "));
    }
  }, [onlineItems, counterItems, simpleItems]);

  if (hasChannels) {
    return (
      <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
        <div>
          <div style={{ fontSize:11, fontWeight:700, color:"#2B6CB0", marginBottom:6 }}>【전자민원】</div>
          <PipeEditor items={onlineItems} onChange={setOnlineItems} />
        </div>
        <div>
          <div style={{ fontSize:11, fontWeight:700, color:"#276749", marginBottom:6 }}>【창구민원】</div>
          <PipeEditor items={counterItems} onChange={setCounterItems} />
        </div>
      </div>
    );
  }
  return <PipeEditor items={simpleItems} onChange={setSimpleItems} />;
}

// ── 편집 가능한 섹션 헤더 ─────────────────────────────────────────────────────
function EditableHeader({
  title,
  icon,
  color,
  isAdmin,
  isEditing,
  onToggle,
  onSave,
  onCancel,
  saving,
}: {
  title: string;
  icon: React.ReactNode;
  color: string;
  isAdmin: boolean;
  isEditing: boolean;
  onToggle: () => void;
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
}) {
  return (
    <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:8 }}>
      {icon}
      <span style={{ fontSize:12, fontWeight:700, color }}>{title}</span>
      <span style={{ flex:1 }} />
      {isAdmin && !isEditing && (
        <button onClick={onToggle}
          style={{ display:"flex", alignItems:"center", gap:3, fontSize:10, padding:"2px 7px", borderRadius:5, border:"1px solid #CBD5E0", background:"#F7FAFC", color:"#718096", cursor:"pointer" }}>
          <Pencil size={10} /> 편집
        </button>
      )}
      {isAdmin && isEditing && (
        <div style={{ display:"flex", gap:5 }}>
          <button onClick={onSave} disabled={saving}
            style={{ display:"flex", alignItems:"center", gap:3, fontSize:10, padding:"2px 8px", borderRadius:5, border:"1px solid #48BB78", background:"#F0FFF4", color:"#276749", cursor:"pointer", fontWeight:600 }}>
            {saving ? <Loader2 size={10} className="animate-spin" /> : <Check size={10} />} 저장
          </button>
          <button onClick={onCancel}
            style={{ fontSize:10, padding:"2px 7px", borderRadius:5, border:"1px solid #CBD5E0", background:"#fff", color:"#718096", cursor:"pointer" }}>
            취소
          </button>
        </div>
      )}
    </div>
  );
}

// ── 전자/창구 민원 서류 파싱 ─────────────────────────────────────────────────
function parseChannelDocs(raw: string): { online: string[]; counter: string[]; simple: string[] } {
  if (!raw) return { online: [], counter: [], simple: [] };
  if (raw.includes("【전자민원】") || raw.includes("【창구민원】")) {
    const onlineMatch  = raw.match(/【전자민원】([^【]*)/);
    const counterMatch = raw.match(/【창구민원】([^【]*)/);
    const parseItems = (s: string) => s.split("|").map(x => x.replace(/\|\|/g,"").trim()).filter(Boolean);
    return {
      online:  onlineMatch  ? parseItems(onlineMatch[1])  : [],
      counter: counterMatch ? parseItems(counterMatch[1]) : [],
      simple:  [],
    };
  }
  return { online: [], counter: [], simple: raw.split("|").map(s=>s.trim()).filter(Boolean) };
}

function ChannelDocSection({ title, icon, color, docs }: { title: string; icon: React.ReactNode; color: string; docs: string[] }) {
  if (!docs.length) return null;
  return (
    <div>
      <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:8 }}>
        {icon}
        <span style={{ fontSize:12, fontWeight:700, color }}>{title}</span>
        <span style={{ fontSize:10, color:"#A0AEC0", marginLeft:2 }}>({docs.length})</span>
      </div>
      <div style={{ display:"flex", flexWrap:"wrap", gap:5 }}>
        {docs.map((d, i) => <DocChip key={i} text={d} color={color} />)}
      </div>
    </div>
  );
}

// ── 매뉴얼 PDF 뷰어 ──────────────────────────────────────────────────────────
function ManualPdfViewer({ refs, onClose }: { refs: ManualRef[]; onClose: () => void; }) {
  const [activeIdx, setActiveIdx] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const active = refs[activeIdx];
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => { setToken(localStorage.getItem("access_token")); }, []);
  if (!active || !token) return null;

  const pdfUrl = `/api/guidelines/manual-pdf/${encodeURIComponent(active.manual)}?token=${encodeURIComponent(token)}#page=${active.page_from}&navpanes=0&pagemode=none&toolbar=1&view=Fit`;
  const containerStyle: React.CSSProperties = fullscreen
    ? { position:"fixed", inset:0, zIndex:500, background:"#fff" }
    : { position:"fixed", top:0, right:460, bottom:0, width:"min(50vw, 720px)", background:"#fff", boxShadow:"-4px 0 24px rgba(0,0,0,0.10)", zIndex:290, display:"flex", flexDirection:"column" };

  return (
    <div style={containerStyle}>
      <div style={{ display:"flex", alignItems:"center", gap:8, padding:"10px 14px", borderBottom:"1px solid #E2E8F0", background:"#F7FAFC", flexShrink:0 }}>
        <BookOpen size={14} style={{ color:"#2B6CB0" }} />
        <span style={{ fontSize:12, fontWeight:700, color:"#2D3748" }}>공식 매뉴얼</span>
        {refs.length > 1 && (
          <div style={{ display:"flex", gap:4, marginLeft:8 }}>
            {refs.map((r, i) => (
              <button key={i} onClick={() => setActiveIdx(i)}
                style={{ fontSize:11, padding:"3px 9px", borderRadius:14, border:`1px solid ${i===activeIdx?"#4299E1":"#E2E8F0"}`, background:i===activeIdx?"#EBF8FF":"#fff", color:i===activeIdx?"#2B6CB0":"#718096", fontWeight:i===activeIdx?600:400, cursor:"pointer" }}>
                {r.manual} p.{r.page_from}
              </button>
            ))}
          </div>
        )}
        <span style={{ flex:1 }} />
        {active.match_text && <span style={{ fontSize:10, color:"#A0AEC0" }}>{active.match_text}</span>}
        <a href={pdfUrl} target="_blank" rel="noopener noreferrer" style={{ padding:5, borderRadius:6, color:"#718096", display:"flex" }} title="새 창으로 열기"><ExtLinkIcon size={13} /></a>
        <button onClick={() => setFullscreen(f => !f)} style={{ padding:5, borderRadius:6, background:"none", border:"none", cursor:"pointer", color:"#718096" }} title={fullscreen?"축소":"전체화면"}><Maximize2 size={13} /></button>
        <button onClick={onClose} style={{ padding:5, borderRadius:6, background:"none", border:"none", cursor:"pointer", color:"#A0AEC0" }} title="닫기"><X size={14} /></button>
      </div>
      <div style={{ padding:"6px 14px", background:"#FFF9E6", borderBottom:"1px solid #E8DFC8", fontSize:11, color:"#6B5314", flexShrink:0 }}>
        📖 <strong>{active.manual}</strong> p.{active.page_from}
        {active.page_to && active.page_to !== active.page_from && ` ~ ${active.page_to}`}
        {active.match_type === "section_only" && <span style={{ marginLeft:8, color:"#9C4221" }}>※ 자격 섹션 전체 — 페이지 내에서 키워드 검색 필요</span>}
      </div>
      <iframe key={pdfUrl} src={pdfUrl} style={{ flex:1, width:"100%", border:"none" }} title={`${active.manual} 매뉴얼`} />
    </div>
  );
}

// ── 상세 패널 ──────────────────────────────────────────────────────────────────
// ── 관리자 전용: row 분류 이동 / override 해제 (대→주→소 선택) ─────────────────
function CategoryMoveControl({ rowId, overlay, onChanged }: {
  rowId: string; overlay: GLOverlay | null; onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [maj, setMaj] = useState<number | "">("");
  const [mid, setMid] = useState<number | "">("");
  const [minor, setMinor] = useState<number | "">("");
  const [busy, setBusy] = useState(false);
  if (!overlay) return null;

  const cats = Array.from(overlay.byId.values());
  const byOrder = (a: GLCat, b: GLCat) => (a.sort_order - b.sort_order) || a.display_name.localeCompare(b.display_name);
  const majors = cats.filter((c) => c.level === "major" && c.is_active).sort(byOrder);
  const middles = cats.filter((c) => c.level === "middle" && c.is_active && c.parent_id === maj).sort(byOrder);
  const minors = cats.filter((c) => c.level === "minor" && c.is_active && c.parent_id === mid).sort(byOrder);
  const hasOverride = !!overlay.overrides[rowId];

  const sel: React.CSSProperties = { width: "100%", padding: "5px 8px", border: "1px solid #CBD5E0", borderRadius: 6, fontSize: 12 };

  const save = async () => {
    if (typeof minor !== "number") { toast.error("이동할 소분류를 선택하세요."); return; }
    setBusy(true);
    try { await guidelineCategoriesApi.setOverride(rowId, minor); toast.success("분류 이동됨"); setOpen(false); onChanged(); }
    catch { toast.error("분류 이동 실패"); }
    finally { setBusy(false); }
  };
  const clear = async () => {
    setBusy(true);
    try { await guidelineCategoriesApi.clearOverride(rowId); toast.success("원래 분류로 복귀"); onChanged(); }
    catch { toast.error("복귀 실패"); }
    finally { setBusy(false); }
  };

  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ display: "flex", gap: 6 }}>
        <button onClick={() => setOpen((v) => !v)}
          style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", gap: 6, padding: "8px 14px", borderRadius: 8, background: "rgba(159,122,234,0.10)", border: "1px solid #9F7AEA", color: "#553C9A", fontSize: 12, fontWeight: 700, cursor: "pointer" }}>
          <GitBranch size={13} /> 분류 이동{hasOverride ? " (이동됨)" : ""}
        </button>
        {hasOverride && (
          <button onClick={clear} disabled={busy}
            style={{ padding: "8px 12px", borderRadius: 8, background: "#fff", border: "1px solid #CBD5E0", color: "#4A5568", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>
            원래 분류로
          </button>
        )}
      </div>
      {open && (
        <div style={{ marginTop: 8, padding: 10, border: "1px solid #E2E8F0", borderRadius: 8, background: "#FAFBFC", display: "flex", flexDirection: "column", gap: 6 }}>
          {majors.length === 0 && <div style={{ fontSize: 11, color: "#A0AEC0" }}>활성 분류가 없습니다. 관리자 화면에서 “기본 분류 생성”을 먼저 실행하세요.</div>}
          <select style={sel} value={maj} onChange={(e) => { setMaj(e.target.value ? Number(e.target.value) : ""); setMid(""); setMinor(""); }}>
            <option value="">대분류 선택</option>
            {majors.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}
          </select>
          <select style={sel} value={mid} disabled={!maj} onChange={(e) => { setMid(e.target.value ? Number(e.target.value) : ""); setMinor(""); }}>
            <option value="">주분류 선택</option>
            {middles.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}
          </select>
          <select style={sel} value={minor} disabled={!mid} onChange={(e) => setMinor(e.target.value ? Number(e.target.value) : "")}>
            <option value="">소분류 선택</option>
            {minors.map((c) => <option key={c.id} value={c.id}>{c.display_name}</option>)}
          </select>
          <button onClick={save} disabled={busy || typeof minor !== "number"} className="btn-primary" style={{ fontSize: 12, padding: "6px 12px" }}>
            {busy ? "저장 중..." : "이 소분류로 이동"}
          </button>
        </div>
      )}
    </div>
  );
}

function DetailPanel({
  row,
  onClose,
  onShowManual,
  manualOpen,
  isAdmin,
  onRowUpdate,
  overlay,
  onOverlayChange,
}: {
  row: GuidelineRow;
  onClose: () => void;
  onShowManual: (refs: ManualRef[]) => void;
  manualOpen: boolean;
  isAdmin: boolean;
  onRowUpdate: (rowId: string, field: string, value: string) => void;
  overlay: GLOverlay | null;
  onOverlayChange: () => void;
}) {
  const router = useRouter();
  const [relatedExceptions, setRelatedExceptions] = useState<{ exc_id: string; trigger_condition?: string; add_supporting_docs?: string; add_form_docs?: string }[]>([]);
  const [selectedSubType, setSelectedSubType] = useState<GuidelineSubType | null>(null);
  const manualRefs = (row.manual_ref ?? []).filter(r => r.page_from > 0);

  // 편집 상태
  const [editingField, setEditingField] = useState<string | null>(null);
  const [editFormDocs, setEditFormDocs] = useState(row.form_docs ?? "");
  const [editSupportingDocs, setEditSupportingDocs] = useState<string[]>([]);
  const [editFeeRule, setEditFeeRule] = useState(row.fee_rule ?? "");
  const [editPracticalNotes, setEditPracticalNotes] = useState<string[]>([]);
  const [editExceptions, setEditExceptions] = useState<string[]>([]);
  const [editBasis, setEditBasis] = useState(row.basis_section ?? "");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setRelatedExceptions([]);
    setSelectedSubType(null);
    setEditingField(null);
    setEditFormDocs(row.form_docs ?? "");
    setEditSupportingDocs((row.supporting_docs ?? "").split("|").map(s => s.trim()).filter(Boolean));
    setEditFeeRule(row.fee_rule ?? "");
    setEditPracticalNotes((row.practical_notes ?? "").split("|").map(s => s.trim()).filter(Boolean));
    setEditExceptions((row.exceptions_summary ?? "").split("|").map(s => s.trim()).filter(Boolean));
    setEditBasis(row.basis_section ?? "");
    guidelinesApi.getDetail(row.row_id)
      .then(res => {
        const data = res.data as GuidelineRow & { related_exceptions?: { exc_id: string; trigger_condition?: string; add_supporting_docs?: string; add_form_docs?: string }[] };
        if (data.related_exceptions?.length) setRelatedExceptions(data.related_exceptions);
      })
      .catch(() => {});
  }, [row.row_id]);

  const startEdit = (field: string) => {
    setEditingField(field);
    if (field === "form_docs") setEditFormDocs(row.form_docs ?? "");
    if (field === "supporting_docs") setEditSupportingDocs((row.supporting_docs ?? "").split("|").map(s => s.trim()).filter(Boolean));
    if (field === "fee_rule") setEditFeeRule(row.fee_rule ?? "");
    if (field === "practical_notes") setEditPracticalNotes((row.practical_notes ?? "").split("|").map(s => s.trim()).filter(Boolean));
    if (field === "exceptions_summary") setEditExceptions((row.exceptions_summary ?? "").split("|").map(s => s.trim()).filter(Boolean));
    if (field === "basis_section") setEditBasis(row.basis_section ?? "");
  };

  const cancelEdit = () => setEditingField(null);

  const saveField = async (field: string, value: string) => {
    setSaving(true);
    try {
      await (window as Window & { fetch: typeof fetch }).fetch(`/api/guidelines/${row.row_id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${localStorage.getItem("access_token") ?? ""}`,
        },
        body: JSON.stringify({ field, value }),
      }).then(async r => {
        if (!r.ok) {
          const err = await r.json().catch(() => ({ detail: "저장 실패" }));
          throw new Error(err.detail ?? "저장 실패");
        }
        return r.json();
      });
      onRowUpdate(row.row_id, field, value);
      setEditingField(null);
      toast.success("저장되었습니다.");
    } catch (e) {
      toast.error(`저장 실패: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  const activeDocs = selectedSubType ?? row;
  const formParsed = parseChannelDocs(activeDocs.form_docs ?? "");
  const requiredDocs = (activeDocs.supporting_docs ?? "").split("|").map(s => s.trim()).filter(Boolean);
  const exceptions = (row.exceptions_summary ?? "").split("|").map(s => s.trim()).filter(Boolean);
  const practicalNotes = ((selectedSubType?.practical_notes ?? row.practical_notes) ?? "").split("|").map(s => s.trim()).filter(Boolean);
  const stepAfterItems = (row.step_after ?? "").split("|").map(s => s.trim()).filter(Boolean);
  const deepLinkUrl = buildQuickDocUrl(row);
  const hasSubTypes = (row.sub_types?.length ?? 0) > 0;

  return (
    <div style={{ position:"fixed", top:0, right:0, bottom:0, width:460, background:"#fff", boxShadow:"-4px 0 32px rgba(0,0,0,0.13)", zIndex:300, overflowY:"auto", display:"flex", flexDirection:"column" }}>
      {/* 헤더 */}
      <div style={{ padding:"18px 20px 14px", borderBottom:"1px solid #E2E8F0", flexShrink:0, background:"#FAFBFC" }}>
        <div style={{ display:"flex", alignItems:"flex-start", gap:12 }}>
          <div style={{ flex:1, minWidth:0 }}>
            <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:4, flexWrap:"wrap" }}>
              <ActionBadge type={row.action_type} />
              <span style={{ fontSize:12, color:"#A0AEC0" }}>{row.detailed_code}</span>
              {row.apply_channel && (
                <span style={{ fontSize:10, padding:"2px 7px", borderRadius:20, background:"#EBF8FF", color:"#2B6CB0", border:"1px solid #BEE3F8" }}>{row.apply_channel}</span>
              )}
            </div>
            <div style={{ fontSize:16, fontWeight:700, color:"#1A202C", lineHeight:1.4, marginBottom:4 }}>{row.business_name}</div>
            {row.overview_short && <div style={{ fontSize:12, color:"#718096", lineHeight:1.6 }}>{row.overview_short}</div>}
            {/* 사증 업무 절차 구분 — 트리는 '사증'으로 묶고 상세에서 인정/공관/확인필요를 구분 */}
            {row.visa_procedure && (
              <div style={{
                marginTop:8, padding:"8px 10px", borderRadius:8, fontSize:11, lineHeight:1.6,
                background: row.visa_procedure==="consulate" ? "#FFFAF0" : row.visa_procedure==="recognition" ? "#EBF8FF" : "#FFF5F5",
                border: `1px solid ${row.visa_procedure==="consulate" ? "#FBD38D" : row.visa_procedure==="recognition" ? "#BEE3F8" : "#FEB2B2"}`,
                color: row.visa_procedure==="consulate" ? "#7B341E" : row.visa_procedure==="recognition" ? "#2C5282" : "#822727",
              }}>
                {row.visa_procedure === "recognition" && (<>
                  <b>사증절차:</b> 사증발급인정신청<br/>
                  <b>신청장소:</b> 국내 출입국·외국인관서 — 인정서 발급 후 재외공관에서 사증 신청
                </>)}
                {row.visa_procedure === "consulate" && (<>
                  <b>사증절차:</b> 재외공관 사증발급신청<br/>
                  <b>신청장소:</b> 재외공관
                </>)}
                {row.visa_procedure === "both" && (<>
                  <b>사증절차:</b> 사증발급인정신청 또는 재외공관 사증발급신청<br/>
                  초청자·체류목적·관할 기준에 따라 확인 필요
                </>)}
                {row.visa_procedure === "confirm_needed" && (<>
                  <b>사증절차:</b> 확인 필요<br/>
                  매뉴얼 또는 재외공관 기준 확인 후 진행
                </>)}
              </div>
            )}
          </div>
          <button onClick={onClose} style={{ padding:6, borderRadius:8, background:"none", border:"none", cursor:"pointer", color:"#A0AEC0", flexShrink:0 }}
            onMouseEnter={e=>(e.currentTarget as HTMLButtonElement).style.background="#F7FAFC"}
            onMouseLeave={e=>(e.currentTarget as HTMLButtonElement).style.background="none"}>
            <X size={16} />
          </button>
        </div>
        <div style={{ marginTop:12, display:"flex", flexDirection:"column", gap:8 }}>
          {SHOW_INTERNAL_SOURCE_UI && manualRefs.length > 0 && (
            <button onClick={() => onShowManual(manualRefs)}
              style={{ width:"100%", display:"flex", alignItems:"center", justifyContent:"center", gap:6, padding:"8px 14px", borderRadius:8, background:manualOpen?"#2B6CB0":"rgba(66,153,225,0.10)", border:"1px solid #4299E1", color:manualOpen?"#fff":"#2B6CB0", fontSize:12, fontWeight:700, cursor:"pointer", transition:"all 0.15s" }}>
              <BookOpen size={13} /> 공식 매뉴얼 보기
              <span style={{ fontSize:10, fontWeight:400, opacity:0.85 }}>({manualRefs.map(r => `${r.manual} p.${r.page_from}`).join(", ")})</span>
            </button>
          )}
          {deepLinkUrl && (
            <button onClick={() => router.push(deepLinkUrl)}
              style={{ width:"100%", display:"flex", alignItems:"center", justifyContent:"center", gap:6, padding:"8px 14px", borderRadius:8, background:"rgba(212,168,67,0.10)", border:"1px solid #D4A843", color:"#6B5314", fontSize:12, fontWeight:700, cursor:"pointer", transition:"all 0.15s" }}
              onMouseEnter={e=>(e.currentTarget as HTMLButtonElement).style.background="rgba(212,168,67,0.20)"}
              onMouseLeave={e=>(e.currentTarget as HTMLButtonElement).style.background="rgba(212,168,67,0.10)"}>
              <FileText size={13} /> 문서 자동작성으로 이동 <ArrowRight size={13} />
            </button>
          )}
          {isAdmin && (
            <CategoryMoveControl rowId={row.row_id} overlay={overlay} onChanged={onOverlayChange} />
          )}
        </div>
      </div>

      {/* L4 조건 분기 */}
      {hasSubTypes && (
        <div style={{ padding:"14px 20px", borderBottom:"1px solid #E2E8F0", background:"#F0F4FF" }}>
          <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:10 }}>
            <Layers size={13} style={{ color:"#4299E1" }} />
            <span style={{ fontSize:12, fontWeight:700, color:"#2B6CB0" }}>어떤 경우인가요?</span>
            <span style={{ fontSize:10, color:"#718096" }}> (선택하면 해당 서류만 표시)</span>
          </div>
          <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
            <button onClick={() => setSelectedSubType(null)}
              style={{ padding:"8px 12px", borderRadius:8, textAlign:"left", fontSize:12, cursor:"pointer", background:!selectedSubType?"#4299E1":"#fff", color:!selectedSubType?"#fff":"#4A5568", border:`1px solid ${!selectedSubType?"#4299E1":"#E2E8F0"}`, fontWeight:!selectedSubType?600:400 }}>
              전체 (기본 서류 표시)
            </button>
            {row.sub_types!.map((st, i) => (
              <button key={i} onClick={() => setSelectedSubType(st)}
                style={{ padding:"8px 12px", borderRadius:8, textAlign:"left", fontSize:12, cursor:"pointer", background:selectedSubType?.label===st.label?"#EBF8FF":"#fff", color:selectedSubType?.label===st.label?"#2B6CB0":"#4A5568", border:`1px solid ${selectedSubType?.label===st.label?"#4299E1":"#E2E8F0"}`, fontWeight:selectedSubType?.label===st.label?600:400, lineHeight:1.5 }}>
                <div style={{ fontWeight:600 }}>{st.label}</div>
                <div style={{ fontSize:10, color:"#718096", marginTop:2 }}>{st.condition}</div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 본문 */}
      <div style={{ flex:1, padding:"18px 20px", display:"flex", flexDirection:"column", gap:18 }}>

        {/* 사무소 준비서류 */}
        <div>
          <EditableHeader
            title="사무소 준비서류"
            icon={<FileText size={13} style={{color:"#4299E1"}}/>}
            color="#4299E1"
            isAdmin={isAdmin}
            isEditing={editingField === "form_docs"}
            onToggle={() => startEdit("form_docs")}
            onSave={() => saveField("form_docs", editFormDocs)}
            onCancel={cancelEdit}
            saving={saving}
          />
          {editingField === "form_docs" ? (
            <FormDocsEditor value={editFormDocs} onChange={setEditFormDocs} />
          ) : (
            <>
              {formParsed.simple.length > 0 && (
                <div style={{ display:"flex", flexWrap:"wrap", gap:6 }}>
                  {formParsed.simple.map((doc, i) => <DocChip key={i} text={doc} color="#4299E1" />)}
                </div>
              )}
              {(formParsed.online.length > 0 || formParsed.counter.length > 0) && (
                <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
                  <ChannelDocSection title="전자민원" icon={<span style={{fontSize:10,padding:"1px 6px",borderRadius:10,background:"#BEE3F8",color:"#2B6CB0"}}>온라인</span>} color="#2B6CB0" docs={formParsed.online} />
                  <ChannelDocSection title="창구민원" icon={<span style={{fontSize:10,padding:"1px 6px",borderRadius:10,background:"#C6F6D5",color:"#276749"}}>방문</span>} color="#276749" docs={formParsed.counter} />
                </div>
              )}
              {formParsed.simple.length === 0 && formParsed.online.length === 0 && formParsed.counter.length === 0 && (
                <div style={{ fontSize:12, color:"#CBD5E0" }}>—</div>
              )}
            </>
          )}
        </div>

        {/* 필요서류 (고객 준비) */}
        <div>
          <EditableHeader
            title="필요서류 (고객 준비)"
            icon={<Paperclip size={13} style={{color:"#48BB78"}}/>}
            color="#48BB78"
            isAdmin={isAdmin}
            isEditing={editingField === "supporting_docs"}
            onToggle={() => startEdit("supporting_docs")}
            onSave={() => saveField("supporting_docs", editSupportingDocs.join(" | "))}
            onCancel={cancelEdit}
            saving={saving}
          />
          {editingField === "supporting_docs" ? (
            <PipeEditor items={editSupportingDocs} onChange={setEditSupportingDocs} />
          ) : (
            requiredDocs.length > 0
              ? <div style={{ display:"flex", flexWrap:"wrap", gap:6 }}>{requiredDocs.map((d, i) => <DocChip key={i} text={d} color="#48BB78" />)}</div>
              : <div style={{ fontSize:12, color:"#CBD5E0" }}>—</div>
          )}
        </div>

        {/* 인지세 — 편집 제외(fee_rule은 v2 원본 수정 금지 대상, 표시도 정제값만 — 원문 노출 방지) */}
        <div>
          <EditableHeader
            title="인지세"
            icon={<span style={{fontSize:12}}>💴</span>}
            color="#718096"
            isAdmin={false}
            isEditing={editingField === "fee_rule"}
            onToggle={() => startEdit("fee_rule")}
            onSave={() => saveField("fee_rule", editFeeRule)}
            onCancel={cancelEdit}
            saving={saving}
          />
          {editingField === "fee_rule" ? (
            <input
              value={editFeeRule}
              onChange={e => setEditFeeRule(e.target.value)}
              style={{ width:"100%", fontSize:13, padding:"7px 10px", border:"1px solid #CBD5E0", borderRadius:7, outline:"none", boxSizing:"border-box" }}
            />
          ) : row.fee_rule ? (
            <div style={{ fontSize:13, padding:"10px 14px", borderRadius:8, background:"#FFF9E6", color:"#6B5314", border:"1px solid #E8DFC8", lineHeight:1.5, wordBreak:"break-word", overflowWrap:"break-word" }}>{sanitizeFeeRuleDisplay(row)}</div>
          ) : (
            <div style={{ fontSize:12, color:"#CBD5E0" }}>—</div>
          )}
        </div>

        {/* 실무 주의사항 */}
        <div>
          <EditableHeader
            title="실무 주의사항"
            icon={<Info size={13} style={{color:"#3182CE"}}/>}
            color="#3182CE"
            isAdmin={isAdmin}
            isEditing={editingField === "practical_notes"}
            onToggle={() => startEdit("practical_notes")}
            onSave={() => saveField("practical_notes", editPracticalNotes.join(" | "))}
            onCancel={cancelEdit}
            saving={saving}
          />
          {editingField === "practical_notes" ? (
            <PipeEditor items={editPracticalNotes} onChange={setEditPracticalNotes} />
          ) : practicalNotes.length > 0 ? (
            <div style={{ display:"flex", flexDirection:"column", gap:5 }}>
              {practicalNotes.map((note, i) => (
                <div key={i} style={{ display:"flex", gap:8, fontSize:12, padding:"7px 12px", borderRadius:8, background:"#EBF8FF", color:"#2C5282", border:"1px solid #BEE3F8", lineHeight:1.6 }}>
                  <span style={{ flexShrink:0, marginTop:2, color:"#3182CE" }}>•</span>
                  <span>{note}</span>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize:12, color:"#CBD5E0" }}>—</div>
          )}
        </div>

        {/* 예외사항 (관리자 편집 가능) */}
        {(isAdmin || exceptions.length > 0) && (
          <div>
            <EditableHeader
              title="예외사항"
              icon={<AlertCircle size={13} style={{color:"#ED8936"}}/>}
              color="#ED8936"
              isAdmin={isAdmin}
              isEditing={editingField === "exceptions_summary"}
              onToggle={() => startEdit("exceptions_summary")}
              onSave={() => saveField("exceptions_summary", editExceptions.map(s => s.trim()).filter(Boolean).join(" | "))}
              onCancel={cancelEdit}
              saving={saving}
            />
            {editingField === "exceptions_summary" ? (
              <PipeEditor items={editExceptions} onChange={setEditExceptions} />
            ) : exceptions.length > 0 ? (
              <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
                {exceptions.map((exc, i) => (
                  <div key={i} style={{ fontSize:12, padding:"8px 12px", borderRadius:8, background:"#FFFAF0", color:"#7B341E", border:"1px solid #FBD38D", lineHeight:1.6 }}>{exc}</div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize:12, color:"#CBD5E0" }}>—</div>
            )}
          </div>
        )}

        {/* 공통 조건부 예외 */}
        {relatedExceptions.filter(e => e.trigger_condition).length > 0 && (
          <div>
            <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:8 }}>
              <GitBranch size={13} style={{color:"#9F7AEA"}}/>
              <span style={{ fontSize:12, fontWeight:700, color:"#9F7AEA" }}>공통 조건부 예외</span>
            </div>
            <div style={{ display:"flex", flexDirection:"column", gap:5 }}>
              {relatedExceptions.filter(e=>e.trigger_condition).map(e => (
                <div key={e.exc_id} style={{ fontSize:11, padding:"7px 11px", borderRadius:7, background:"#F5F3FF", color:"#553C9A", border:"1px solid #D6BCFA", lineHeight:1.6 }}>
                  <span style={{fontWeight:700}}>조건: </span>{e.trigger_condition}
                  {e.add_supporting_docs && <span style={{display:"block",marginTop:2,color:"#44337A"}}>→ 추가 서류: <strong>{e.add_supporting_docs}</strong></span>}
                  {e.add_form_docs && <span style={{display:"block",marginTop:2,color:"#44337A"}}>→ 추가 작성: <strong>{e.add_form_docs}</strong></span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 허가 후 다음 단계 */}
        {stepAfterItems.length > 0 && (
          <div>
            <div style={{ display:"flex", alignItems:"center", gap:6, marginBottom:8 }}>
              <CheckCircle2 size={13} style={{color:"#48BB78"}}/>
              <span style={{ fontSize:12, fontWeight:700, color:"#276749" }}>허가 후 다음 단계</span>
            </div>
            <div style={{ display:"flex", flexDirection:"column", gap:5 }}>
              {stepAfterItems.map((step, i) => (
                <div key={i} style={{ display:"flex", gap:8, fontSize:12, padding:"7px 12px", borderRadius:8, background:"#F0FFF4", color:"#22543D", border:"1px solid #9AE6B4", lineHeight:1.6 }}>
                  <span style={{ flexShrink:0, fontWeight:700, color:"#48BB78" }}>{i+1}.</span>
                  <span>{step}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 근거 (관리자 편집 가능) — 출처 비노출 원칙으로 화면에서 숨김(데이터·PATCH API 유지) */}
        {SHOW_INTERNAL_SOURCE_UI && (isAdmin || row.basis_section) && (
          <div>
            <EditableHeader
              title="근거"
              icon={<BookMarked size={13} style={{color:"#9F7AEA"}}/>}
              color="#9F7AEA"
              isAdmin={isAdmin}
              isEditing={editingField === "basis_section"}
              onToggle={() => startEdit("basis_section")}
              onSave={() => saveField("basis_section", editBasis)}
              onCancel={cancelEdit}
              saving={saving}
            />
            {editingField === "basis_section" ? (
              <textarea
                value={editBasis}
                onChange={e => setEditBasis(e.target.value)}
                rows={4}
                placeholder="근거 (빈 값 저장 가능, 줄바꿈 유지)"
                style={{ width:"100%", fontSize:12, padding:"8px 10px", border:"1px solid #CBD5E0", borderRadius:8, outline:"none", lineHeight:1.6, resize:"vertical", boxSizing:"border-box" }}
              />
            ) : row.basis_section ? (
              <div style={{ fontSize:12, color:"#718096", lineHeight:1.7, whiteSpace:"pre-wrap", wordBreak:"break-word", overflowWrap:"break-word" }}>{row.basis_section}</div>
            ) : (
              <div style={{ fontSize:12, color:"#CBD5E0" }}>—</div>
            )}
          </div>
        )}

        {/* 결핵 고위험국 경고 */}
        {TB_APPLICABLE_TYPES.has(row.action_type) && (
          <div style={{ padding:"10px 14px", borderRadius:8, background:"#FFF5F5", border:"1px solid #FEB2B2", display:"flex", gap:10, alignItems:"flex-start" }}>
            <ShieldAlert size={14} style={{color:"#E53E3E",flexShrink:0,marginTop:1}}/>
            <div>
              <div style={{ fontSize:12, fontWeight:700, color:"#C53030", marginBottom:3 }}>결핵 고위험국 국적자 주의</div>
              <div style={{ fontSize:11, color:"#742A2A", lineHeight:1.6 }}>
                {TB_STAGE_LABEL[row.action_type]} 결핵 고위험국 국적자는 보건소 결핵 검사 결과서를 함께 제출해야 합니다.<br/>
                <span style={{color:"#9B2C2C",fontWeight:600}}>해당 여부: 베트남·중국·인도·필리핀·인도네시아 등 약 70개국</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── 결과 카드 ─────────────────────────────────────────────────────────────────
// (GuidelineCard — @/components/guidelines/shared 로 이동, v3 화면과 공용)

// ── 진입점 카드 ───────────────────────────────────────────────────────────────
function EntryPointCard({ entry, rowCount, onClick }: { entry: GuidelineEntryPoint; rowCount: number; onClick: () => void }) {
  const [hovered, setHovered] = useState(false);
  return (
    <button onClick={onClick} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      style={{ display:"flex", alignItems:"flex-start", gap:10, padding:"14px 16px", borderRadius:12, border:`1.5px solid ${hovered?entry.color:"#E2E8F0"}`, background:hovered?`${entry.color}0C`:"#fff", cursor:"pointer", textAlign:"left", transition:"all 0.15s", width:"100%" }}>
      <div style={{ width:36, height:36, borderRadius:10, flexShrink:0, background:`${entry.color}18`, display:"flex", alignItems:"center", justifyContent:"center", fontSize:12, fontWeight:800, color:entry.color }}>
        {entry.codes.slice(0,2)}
      </div>
      <div style={{ flex:1, minWidth:0 }}>
        <div style={{ fontSize:13, fontWeight:700, color:"#2D3748", marginBottom:2 }}>{entry.label}</div>
        <div style={{ fontSize:11, color:"#A0AEC0" }}>{entry.subtitle}</div>
        {rowCount > 0 && <div style={{ fontSize:10, color:entry.color, fontWeight:600, marginTop:3 }}>{rowCount}건</div>}
      </div>
      <ChevronRight size={14} style={{ color:hovered?entry.color:"#CBD5E0", flexShrink:0, marginTop:2, transition:"color 0.15s" }}/>
    </button>
  );
}

// ── L2 업무유형 카드 ──────────────────────────────────────────────────────────
function ActionTypeCard({ actionType, label, color, onClick }: { actionType: string; label: string; count?: number; color: string; onClick: () => void }) {
  const [hovered, setHovered] = useState(false);
  return (
    <button onClick={onClick} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
      style={{ display:"flex", alignItems:"center", justifyContent:"space-between", padding:"16px 18px", borderRadius:12, border:`1.5px solid ${hovered?color:"#E2E8F0"}`, background:hovered?`${color}0C`:"#fff", cursor:"pointer", textAlign:"left", transition:"all 0.15s", width:"100%" }}>
      <div style={{ fontSize:14, fontWeight:700, color:"#2D3748" }}>{label}</div>
      <div style={{ width:32, height:32, borderRadius:8, background:`${color}18`, display:"flex", alignItems:"center", justifyContent:"center" }}>
        <ArrowRight size={14} style={{color}}/>
      </div>
    </button>
  );
}

// ── 새 트리: 선택 버튼 공통 ───────────────────────────────────────────────────
function TreeSelectButton({ label, subtitle, color, selected, onClick }: { label: string; subtitle?: string; color: string; selected: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick}
      style={{
        padding:"10px 16px", borderRadius:10, textAlign:"left", fontSize:13, cursor:"pointer",
        background: selected ? color : "#fff",
        color: selected ? "#fff" : "#2D3748",
        border: `1.5px solid ${selected ? color : "#E2E8F0"}`,
        fontWeight: selected ? 700 : 500,
        transition:"all 0.12s",
        display:"flex", alignItems:"center", justifyContent:"space-between", gap:8,
        height:"auto",
      }}
      onMouseEnter={e => { if (!selected) { (e.currentTarget as HTMLButtonElement).style.background = `${color}10`; (e.currentTarget as HTMLButtonElement).style.borderColor = color; } }}
      onMouseLeave={e => { if (!selected) { (e.currentTarget as HTMLButtonElement).style.background = "#fff"; (e.currentTarget as HTMLButtonElement).style.borderColor = "#E2E8F0"; } }}
    >
      <span style={{ display:"flex", flexDirection:"column", gap:2, minWidth:0 }}>
        <span>{label}</span>
        {subtitle && (
          <span style={{ fontSize:11, fontWeight:400, color: selected ? "rgba(255,255,255,0.8)" : "#A0AEC0", lineHeight:1.2 }}>
            {subtitle}
          </span>
        )}
      </span>
      <ChevronRight size={14} style={{ opacity:0.5, flexShrink:0 }} />
    </button>
  );
}

// ── 메인 페이지 ───────────────────────────────────────────────────────────────
export default function GuidelinesPage() {
  const user = useMemo(() => getUser(), []);
  // 실무지침 수정은 관리자/준 관리자 허용(백엔드 require_guideline_editor 와 일치).
  const isAdmin = canManageContent(user);
  const pageRouter = useRouter();

  const [entryPoints, setEntryPoints]       = useState<GuidelineEntryPoint[]>(ENTRY_POINTS);
  const [allRows, setAllRows]               = useState<GuidelineRow[]>([]);
  const [loadingAll, setLoadingAll]         = useState(true);
  const [loadError, setLoadError]           = useState("");

  // 기존 트리 상태
  const [selectedEntry, setSelectedEntry]           = useState<GuidelineEntryPoint | null>(null);
  const [selectedActionType, setSelectedActionType] = useState<string | null>(null);
  const [selectedRow, setSelectedRow]               = useState<GuidelineRow | null>(null);
  const [manualPdfRefs, setManualPdfRefs]           = useState<ManualRef[] | null>(null);
  const [currentEntryRows, setCurrentEntryRows]     = useState<GuidelineRow[]>([]);
  const [treeLoading, setTreeLoading]               = useState(false);
  const [treeError, setTreeError]                   = useState("");

  // ── 새 트리 모드 상태 ──
  const [treeMode, setTreeMode]         = useState(true);
  const [selAction, setSelAction]       = useState<string | null>(null);
  const [selFamily, setSelFamily]       = useState<string | null>(null);
  const [selMid, setSelMid]             = useState<string | null>(null);

  // 보조 탭 딥링크(/qualifications 화면의 분류별/업무별 탭에서 진입): ?view=class|work
  // 저장된 이전 탭 상태는 없으며(모드 미영속), 쿼리 없으면 기존 기본값(업무별) 유지.
  useEffect(() => {
    const v = new URLSearchParams(window.location.search).get("view");
    if (v === "class") setTreeMode(false);
    else if (v === "work") setTreeMode(true);
  }, []);

  // 검색 상태
  const [searchQuery, setSearchQuery]         = useState("");
  const [searchActiveType, setSearchActiveType] = useState("");
  const [searchResults, setSearchResults]     = useState<GuidelineRow[]>([]);
  const [searchTotal, setSearchTotal]         = useState(0);
  const [isSearching, setIsSearching]         = useState(false);
  const [hasSearched, setHasSearched]         = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);

  // 마운트 시 전체 rows + 진입점 동시 로딩
  useEffect(() => {
    setLoadError("");
    Promise.all([
      guidelinesApi.getEntryPoints().then(res => res.data.data).catch(() => [] as GuidelineEntryPoint[]),
      guidelinesApi.list({ limit: 500, status: "all" }).then(res => res.data.data).catch(() => {
        setLoadError("실무지침 목록을 불러오지 못했습니다. 로그인 상태 또는 서버 연결을 확인해 주세요.");
        return [] as GuidelineRow[];
      }),
    ]).then(([eps, rows]) => {
      if (eps.length > 0) setEntryPoints(eps);
      setAllRows(Array.isArray(rows) ? rows : []);
    }).finally(() => setLoadingAll(false));
  }, []);

  // 새 트리 구조 (buildTree 결과)
  // 분류 오버레이(A+) — best-effort. 실패/플래그off(409)면 null → 기존 JSON 트리 그대로.
  const [overlay, setOverlay] = useState<GLOverlay | null>(null);
  const reloadOverlay = useCallback(() => {
    guidelineCategoriesApi.list(true)
      .then((r) => {
        const cats = r.data.categories || [];
        const byId = new Map<number, typeof cats[number]>(cats.map((c) => [c.id, c]));
        const bySourceKey = new Map<string, typeof cats[number]>(
          cats.filter((c) => c.source_key).map((c) => [c.source_key, c]));
        setOverlay({ byId, bySourceKey, overrides: r.data.overrides || {} });
      })
      .catch((e) => { console.warn("[guidelines] 분류 오버레이 로드 실패 — 기본 분류로 표시", e); setOverlay(null); });
  }, []);
  useEffect(() => { reloadOverlay(); }, [reloadOverlay]);

  const tree = useMemo(() => buildTree(allRows, overlay), [allRows, overlay]);

  // L1(대분류) 표시 순서: 기존 ACTION_TYPE_ORDER 유지 + overlay/custom/미분류는 뒤에 추가.
  const treeActions = useMemo(() => {
    const known = ACTION_TYPE_ORDER.filter((a) => tree.has(a));
    const extras = Array.from(tree.keys()).filter((a) => !ACTION_TYPE_ORDER.includes(a) && a !== "__UNCLASSIFIED__");
    const sortedExtras = glSortKeys("major", "", "", extras, overlay);
    const unclassified = tree.has("__UNCLASSIFIED__") ? ["__UNCLASSIFIED__"] : [];
    return [...known, ...sortedExtras, ...unclassified];
  }, [tree, overlay]);

  // 새 트리: selAction → family 목록
  const treeActionFamilies = useMemo(() => {
    if (!selAction) return [];
    const famMap = tree.get(selAction);
    if (!famMap) return [];
    return glSortKeys("middle", selAction, "", Array.from(famMap.keys()), overlay);
  }, [tree, selAction, overlay]);

  // 새 트리: selAction + selFamily → mid 목록
  const treeActionMids = useMemo(() => {
    if (!selAction || !selFamily) return [];
    const famMap = tree.get(selAction);
    if (!famMap) return [];
    const midMap = famMap.get(selFamily);
    if (!midMap) return [];
    return glSortKeys("minor", selAction, selFamily, Array.from(midMap.keys()), overlay);
  }, [tree, selAction, selFamily, overlay]);

  // 새 트리: 선택된 mid의 row들
  const treeSelectedRows = useMemo(() => {
    if (!selAction || !selFamily || !selMid) return [];
    const famMap = tree.get(selAction);
    if (!famMap) return [];
    const midMap = famMap.get(selFamily);
    if (!midMap) return [];
    return midMap.get(selMid) ?? [];
  }, [tree, selAction, selFamily, selMid]);

  // 새 트리: mid 선택 시 소분류가 있는지 (모든 row가 동일 mid로 terminal이면 바로 카드)
  // mid에 속한 row들 중 hasSub인 것이 있으면 → sub 그룹으로 더 분기
  const treeSubGroups = useMemo(() => {
    if (!treeSelectedRows.length) return null;
    const withSub = treeSelectedRows.filter(r => hasSub(r.detailed_code || ""));
    if (!withSub.length) return null;
    // sub code별로 그룹핑
    const groups = new Map<string, GuidelineRow[]>();
    for (const row of treeSelectedRows) {
      const sub = hasSub(row.detailed_code || "") ? row.detailed_code : getMidCode(row.detailed_code || "");
      if (!groups.has(sub)) groups.set(sub, []);
      groups.get(sub)!.push(row);
    }
    return groups;
  }, [treeSelectedRows]);

  // 새 트리: selMid 선택 후 표시할 rows (sub 없으면 그대로, sub 있으면 sub별 그룹)
  const [selSub, setSelSub] = useState<string | null>(null);
  const treeTerminalRows = useMemo(() => {
    if (!treeSelectedRows.length) return [];
    if (!treeSubGroups) return treeSelectedRows;  // 소분류 없음 → 바로 terminal
    if (selSub) return treeSubGroups.get(selSub) ?? [];
    return [];  // sub 있는데 아직 미선택
  }, [treeSelectedRows, treeSubGroups, selSub]);

  // EXTRA_WORK: 신청자 자격 선택 상태
  const [selApplicant, setSelApplicant] = useState<string | null>(null);

  // EXTRA_WORK: 신청자 자격별 그룹핑 (알파벳 순 정렬)
  const extraWorkApplicantGroups = useMemo<Map<string, GuidelineRow[]>>(() => {
    const groups = new Map<string, GuidelineRow[]>();
    for (const row of allRows) {
      if (row.action_type !== "EXTRA_WORK") continue;
      const applicant = EXTRA_WORK_APPLICANT_MAP[row.row_id] ?? row.detailed_code ?? "_OTHER";
      if (!groups.has(applicant)) groups.set(applicant, []);
      groups.get(applicant)!.push(row);
    }
    const sorted: Array<[string, GuidelineRow[]]> = Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0]));
    return new Map<string, GuidelineRow[]>(sorted);
  }, [allRows]);

  // EXTRA_WORK: 선택된 신청자 자격의 rows
  const extraWorkSelectedRows = useMemo<GuidelineRow[]>(() => {
    if (!selApplicant) return [];
    return extraWorkApplicantGroups.get(selApplicant) ?? [];
  }, [extraWorkApplicantGroups, selApplicant]);

  // 기존 트리 헬퍼
  const entryRowCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const ep of entryPoints) {
      counts[ep.id ?? ep.label] = allRows.length > 0
        ? getMatchingRows(allRows, ep).length
        : (ep.count ?? 0);
    }
    return counts;
  }, [entryPoints, allRows]);

  const treeL2Items = useMemo(() => {
    if (!selectedEntry) return [];
    const grouped: Record<string, number> = {};
    currentEntryRows.forEach(r => { grouped[r.action_type] = (grouped[r.action_type] || 0) + 1; });
    return Object.entries(grouped)
      .map(([at, count]) => ({ key: at, label: ACTION_TYPE_LABELS[at] || at, count, color: ACTION_TYPE_COLORS[at] || "#A0AEC0" }))
      .sort((a, b) => {
        const ai = ACTION_TYPE_ORDER.indexOf(a.key);
        const bi = ACTION_TYPE_ORDER.indexOf(b.key);
        return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
      });
  }, [currentEntryRows, selectedEntry]);

  const skipL2 = treeL2Items.length <= 1;

  const treeL3Rows = useMemo(() => {
    if (!selectedEntry) return [];
    if (skipL2) return currentEntryRows;
    if (selectedActionType) return currentEntryRows.filter(r => r.action_type === selectedActionType);
    return [];
  }, [currentEntryRows, selectedEntry, selectedActionType, skipL2]);

  const viewMode: "search" | "l1" | "l2" | "l3" =
    hasSearched ? "search"
    : !selectedEntry ? "l1"
    : (skipL2 || selectedActionType !== null) ? "l3"
    : "l2";

  const loadEntryRows = useCallback(async (entry: GuidelineEntryPoint) => {
    setTreeLoading(true);
    setTreeError("");
    setCurrentEntryRows([]);
    try {
      let matched = allRows.length > 0 ? getMatchingRows(allRows, entry) : [];
      if (matched.length === 0) matched = await fetchRowsForEntry(entry);
      setCurrentEntryRows(matched);
      if (matched.length === 0) setTreeError("이 분류에 연결된 실무지침이 없습니다.");
    } catch {
      setCurrentEntryRows([]);
      setTreeError("이 분류에 연결된 실무지침이 없습니다.");
    } finally {
      setTreeLoading(false);
    }
  }, [allRows]);

  const doSearch = useCallback(async (q: string, type: string) => {
    if (!q.trim() && !type) return;
    setIsSearching(true);
    setHasSearched(true);
    setSelectedRow(null);
    try {
      const res = q.trim()
        ? await guidelinesApi.search(q.trim(), type || undefined, 1, 80)
        : await guidelinesApi.list({ action_type: type || undefined, limit: 80 });
      setSearchResults(res.data.data);
      setSearchTotal(res.data.total);
    } catch {
      setSearchResults([]); setSearchTotal(0);
    } finally {
      setIsSearching(false);
    }
  }, []);

  const handleSearch = () => {
    if (searchQuery.trim()) {
      setSelectedEntry(null); setSelectedActionType(null);
      setTreeMode(false); resetTree();
      doSearch(searchQuery, searchActiveType);
    }
  };

  const handleClearSearch = () => {
    setSearchQuery(""); setHasSearched(false);
    setSearchResults([]); setSearchTotal(0); setSearchActiveType("");
    inputRef.current?.focus();
  };

  const handleEntryClick = (entry: GuidelineEntryPoint) => {
    setSelectedEntry(entry); setSelectedActionType(null);
    setSelectedRow(null); setHasSearched(false);
    void loadEntryRows(entry);
  };

  const handleBackToL1 = () => {
    setSelectedEntry(null); setSelectedActionType(null);
    setSelectedRow(null); setCurrentEntryRows([]);
  };

  const handleBackToL2 = () => {
    setSelectedActionType(null); setSelectedRow(null);
  };

  // 새 트리 reset
  const resetTree = useCallback(() => {
    setSelAction(null); setSelFamily(null); setSelMid(null); setSelSub(null); setSelApplicant(null);
    setSelectedRow(null);
  }, []);

  // 단일 항목 자동 열기 (일반 트리)
  useEffect(() => {
    if (selAction && selAction !== "EXTRA_WORK" && treeTerminalRows.length === 1) {
      setSelectedRow(treeTerminalRows[0]);
    }
  }, [treeTerminalRows, selAction]); // eslint-disable-line react-hooks/exhaustive-deps

  // EXTRA_WORK 단일 항목 자동 열기
  useEffect(() => {
    if (selAction === "EXTRA_WORK" && selApplicant && extraWorkSelectedRows.length === 1) {
      setSelectedRow(extraWorkSelectedRows[0]);
    }
  }, [extraWorkSelectedRows, selAction, selApplicant]); // eslint-disable-line react-hooks/exhaustive-deps

  const enterTreeMode = () => {
    setTreeMode(true);
    setHasSearched(false);
    setSelectedEntry(null);
    setSelectedActionType(null);
    resetTree();
  };

  const exitTreeMode = () => {
    setTreeMode(false);
    resetTree();
  };

  // allRows 낙관적 업데이트 (편집 저장 후)
  const handleRowUpdate = useCallback((rowId: string, field: string, value: string) => {
    setAllRows(prev => prev.map(r => r.row_id === rowId ? { ...r, [field]: value } : r));
    setCurrentEntryRows(prev => prev.map(r => r.row_id === rowId ? { ...r, [field]: value } : r));
    setSelectedRow(prev => prev?.row_id === rowId ? { ...prev, [field]: value } : prev);
  }, []);

  // 새 트리: 현재 레벨 타이틀 색상
  const actionColor = selAction ? (ACTION_TYPE_COLORS[selAction] || "#4299E1") : "#4299E1";

  return (
    <div style={{ paddingRight: selectedRow ? 460 : 0, transition: "padding-right 0.2s", overflowX:"hidden" }}>

      {/* ── 헤더 ── */}
      <div style={{ display:"flex", alignItems:"center", gap:10, marginBottom:14 }}>
        <BookOpen size={20} style={{color:"var(--hw-gold)"}}/>
        <h1 className="hw-page-title" style={{margin:0}}>실무지침</h1>
        {loadingAll && <Loader2 size={13} className="animate-spin" style={{color:"#A0AEC0"}}/>}
        {hasSearched && !isSearching && <span style={{fontSize:13,color:"#A0AEC0"}}>{searchTotal}건</span>}
        {canManageContent(user) && (
          <button onClick={() => pageRouter.push("/admin/guideline-categories")}
            title="관리자/준 관리자 — 실무지침 대/주/소분류 편집"
            style={{ fontSize:12, fontWeight:600, color:"#6B5314", background:"#FFF9E6", border:"1px solid #D4A843", borderRadius:6, padding:"4px 10px", cursor:"pointer" }}>
            🗂 분류 관리
          </button>
        )}
        {hasSearched && (
          <button onClick={handleClearSearch}
            style={{ marginLeft:"auto", display:"flex", alignItems:"center", gap:4, fontSize:12, color:"#A0AEC0", background:"none", border:"none", cursor:"pointer", padding:"4px 8px" }}>
            <X size={12}/> 검색 초기화
          </button>
        )}
      </div>

      {/* ── 검색창 ── */}
      <div className="hw-card" style={{ marginBottom:14 }}>
        <div style={{ display:"flex", gap:10, alignItems:"center" }}>
          <div style={{ flex:1, position:"relative", minWidth:0 }}>
            <Search size={14} style={{ position:"absolute", left:12, top:"50%", transform:"translateY(-50%)", color:"#A0AEC0", pointerEvents:"none" }}/>
            <input ref={inputRef} type="text"
              placeholder="직접 검색: 코드·업무명·서류명 (예: F-4, 재직증명서, 시간제취업)"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") handleSearch(); }}
              style={{ width:"100%", height:38, border:"1px solid #CBD5E0", borderRadius:20, padding:"0 36px 0 38px", fontSize:13, outline:"none", background:"#F8F9FA", boxSizing:"border-box" }}
              onFocus={e=>{ e.currentTarget.style.borderColor="var(--hw-gold)"; e.currentTarget.style.background="#fff"; }}
              onBlur={e=>{ e.currentTarget.style.borderColor="#CBD5E0"; e.currentTarget.style.background="#F8F9FA"; }}
            />
            {searchQuery && (
              <button onClick={handleClearSearch} style={{ position:"absolute", right:10, top:"50%", transform:"translateY(-50%)", color:"#CBD5E0", background:"none", border:"none", cursor:"pointer", padding:2 }}>
                <X size={13}/>
              </button>
            )}
          </div>
          <button onClick={handleSearch} className="btn-primary"
            style={{ display:"flex", alignItems:"center", gap:6, fontSize:13, padding:"0 18px", height:38, flexShrink:0, borderRadius:20 }}>
            <Search size={13}/> 검색
          </button>
        </div>
      </div>

      {loadError && (
        <div style={{ marginBottom:14, padding:"12px 14px", borderRadius:10, background:"#FFF5F5", border:"1px solid #FEB2B2", color:"#C53030", fontSize:13, fontWeight:600 }}>
          {loadError}
        </div>
      )}

      {/* ── 검색 결과 뷰 ── */}
      {viewMode === "search" && (
        <>
          <div className="hw-tabs" style={{ flexWrap:"wrap", gap:4, marginBottom:14 }}>
            {ACTION_TYPE_TABS.map(({ key, label }) => (
              <button key={key} className={`hw-tab ${searchActiveType === key ? "active" : ""}`}
                onClick={() => { setSearchActiveType(key); doSearch(searchQuery, key); }}>{label}</button>
            ))}
          </div>
          {isSearching ? (
            <div style={{ display:"flex", justifyContent:"center", padding:"60px 0" }}>
              <Loader2 size={24} className="animate-spin" style={{color:"var(--hw-gold)"}}/>
            </div>
          ) : searchResults.length === 0 ? (
            <div style={{ textAlign:"center", padding:"60px 0", borderRadius:12, background:"#fff", border:"1px solid #E2E8F0" }}>
              <Search size={36} style={{color:"#E2E8F0",margin:"0 auto 12px"}}/>
              <div style={{fontSize:14,fontWeight:600,color:"#4A5568",marginBottom:4}}>검색 결과 없음</div>
              <div style={{fontSize:12,color:"#A0AEC0"}}>다른 검색어나 업무유형 탭을 선택해 보세요.</div>
            </div>
          ) : (
            <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
              {searchResults.map(row => (
                <GuidelineCard key={row.row_id} row={row}
                  isSelected={selectedRow?.row_id === row.row_id}
                  onClick={() => setSelectedRow(selectedRow?.row_id === row.row_id ? null : row)}/>
              ))}
            </div>
          )}
        </>
      )}

      {/* ── 탐색 뷰 (비검색 상태) ── */}
      {!hasSearched && (
        <>
          {/* 모드 토글 버튼 + 매뉴얼 다운로드 링크 */}
          {!selectedEntry && (
            <div style={{ display:"flex", gap:8, marginBottom:14, flexWrap:"wrap", alignItems:"center" }}>
              {/* 분류별 찾기 */}
              <button
                onClick={exitTreeMode}
                style={{
                  display:"flex", alignItems:"center", gap:5, fontSize:12, padding:"6px 14px", borderRadius:20,
                  border:`1.5px solid ${!treeMode ? "var(--hw-gold)" : "#CBD5E0"}`,
                  background: !treeMode ? "rgba(212,168,67,0.08)" : "#fff",
                  color: !treeMode ? "var(--hw-gold-text)" : "#718096",
                  fontWeight: !treeMode ? 700 : 400, cursor:"pointer",
                }}>
                <GitBranch size={13} /> 분류별 찾기
              </button>
              {/* 업무별 찾기 */}
              <button
                onClick={enterTreeMode}
                style={{
                  display:"flex", alignItems:"center", gap:5, fontSize:12, padding:"6px 14px", borderRadius:20,
                  border:`1.5px solid ${treeMode ? "var(--hw-gold)" : "#CBD5E0"}`,
                  background: treeMode ? "rgba(212,168,67,0.08)" : "#fff",
                  color: treeMode ? "var(--hw-gold-text)" : "#718096",
                  fontWeight: treeMode ? 700 : 400, cursor:"pointer",
                }}>
                <Trees size={13} /> 업무별 찾기
              </button>
              {/* v3 자격 중심 화면(기본 화면) — 실무지침 진입 기본값은 /qualifications */}
              {isAdmin && (
                <button
                  onClick={() => pageRouter.push("/qualifications")}
                  style={{
                    display:"flex", alignItems:"center", gap:5, fontSize:12, padding:"6px 14px", borderRadius:20,
                    border:"1.5px solid #CBD5E0", background:"#fff", color:"#718096", fontWeight:400, cursor:"pointer",
                  }}>
                  <GitBranch size={13} /> 자격별 찾기
                </button>
              )}
              {/* 매뉴얼 PDF 다운로드 버튼 제거(Phase I-1J):
                  Render(Linux)에서 HWP→전체 PDF 변환 불가(win32com/OpenHwpExe 의존),
                  legacy unlocked_*.pdf 가 최신화되지 않아 "최신 전체 매뉴얼"로 오인 → 삭제. */}
            </div>
          )}

          {/* ── 새 트리 모드 ── */}
          {treeMode && !selectedEntry && (
            <div>
              {/* 브레드크럼 */}
              {(selAction) && (
                <div style={{ display:"flex", alignItems:"center", gap:4, marginBottom:14, flexWrap:"wrap" }}>
                  <button onClick={resetTree}
                    style={{ fontSize:12, color:"#718096", background:"#F7FAFC", border:"1px solid #E2E8F0", borderRadius:20, padding:"4px 12px", cursor:"pointer" }}>
                    ← 전체
                  </button>
                  <ChevronRight size={13} style={{color:"#CBD5E0"}}/>
                  <button
                    onClick={() => {
                      if (selAction === "EXTRA_WORK") { setSelApplicant(null); setSelectedRow(null); }
                      else { setSelFamily(null); setSelMid(null); setSelSub(null); setSelectedRow(null); }
                    }}
                    style={{ fontSize:12,
                      fontWeight: (selAction === "EXTRA_WORK" ? selApplicant : selFamily) ? 400 : 700,
                      padding:"4px 12px", borderRadius:20,
                      background: (selAction === "EXTRA_WORK" ? selApplicant : selFamily) ? "#F7FAFC" : `${actionColor}18`,
                      border: (selAction === "EXTRA_WORK" ? selApplicant : selFamily) ? "1px solid #E2E8F0" : `1px solid ${actionColor}40`,
                      color: (selAction === "EXTRA_WORK" ? selApplicant : selFamily) ? "#718096" : actionColor,
                      cursor:"pointer" }}>
                    {ACTION_LABELS[selAction] ?? selAction}
                  </button>
                  {/* EXTRA_WORK: 신청자 자격 */}
                  {selAction === "EXTRA_WORK" && selApplicant && (
                    <>
                      <ChevronRight size={13} style={{color:"#CBD5E0"}}/>
                      <span style={{ fontSize:12, fontWeight:700, padding:"4px 12px", borderRadius:20, background:`${actionColor}18`, border:`1px solid ${actionColor}40`, color:actionColor }}>
                        {APPLICANT_LABELS[selApplicant] ?? selApplicant}
                      </span>
                    </>
                  )}
                  {/* 일반 트리: 계열 → 중분류 → 소분류 */}
                  {selAction !== "EXTRA_WORK" && selFamily && (
                    <>
                      <ChevronRight size={13} style={{color:"#CBD5E0"}}/>
                      <button
                        onClick={() => { setSelMid(null); setSelSub(null); setSelectedRow(null); }}
                        style={{ fontSize:12, fontWeight: selMid ? 400 : 700, padding:"4px 12px", borderRadius:20,
                          background: selMid ? "#F7FAFC" : `${actionColor}18`,
                          border: selMid ? "1px solid #E2E8F0" : `1px solid ${actionColor}40`,
                          color: selMid ? "#718096" : actionColor, cursor:"pointer" }}>
                        {FAMILY_LABELS[selFamily] ?? selFamily}
                      </button>
                    </>
                  )}
                  {selAction !== "EXTRA_WORK" && selMid && (
                    <>
                      <ChevronRight size={13} style={{color:"#CBD5E0"}}/>
                      <button
                        onClick={() => { setSelSub(null); setSelectedRow(null); }}
                        style={{ fontSize:12, fontWeight: selSub ? 400 : 700, padding:"4px 12px", borderRadius:20,
                          background: selSub ? "#F7FAFC" : `${actionColor}18`,
                          border: selSub ? "1px solid #E2E8F0" : `1px solid ${actionColor}40`,
                          color: selSub ? "#718096" : actionColor, cursor:"pointer" }}>
                        {selMid}
                      </button>
                    </>
                  )}
                  {selAction !== "EXTRA_WORK" && selSub && (
                    <>
                      <ChevronRight size={13} style={{color:"#CBD5E0"}}/>
                      <span style={{ fontSize:12, fontWeight:700, padding:"4px 12px", borderRadius:20, background:`${actionColor}18`, border:`1px solid ${actionColor}40`, color:actionColor }}>
                        {selSub}
                      </span>
                    </>
                  )}
                </div>
              )}

              {/* L1: 업무유형 선택 */}
              {!selAction && (
                <div>
                  <div style={{ fontSize:12, color:"#718096", marginBottom:12 }}>업무 유형을 선택하세요</div>
                  <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(200px, 1fr))", gap:8 }}>
                    {treeActions.map(action => {
                      const famMap = tree.get(action);
                      if (!famMap || famMap.size === 0) return null;
                      const color = ACTION_TYPE_COLORS[action] || "#A0AEC0";
                      return (
                        <TreeSelectButton
                          key={action}
                          label={glLabel("major", action, "", "", overlay, ACTION_LABELS[action] ?? action)}
                          color={color}
                          selected={false}
                          onClick={() => { setSelAction(action); setSelFamily(null); setSelMid(null); setSelSub(null); setSelApplicant(null); setSelectedRow(null); }}
                        />
                      );
                    })}
                  </div>
                </div>
              )}

              {/* L2: EXTRA_WORK — 신청자 현재 자격 선택 */}
              {selAction === "EXTRA_WORK" && !selApplicant && (
                <div>
                  <div style={{ fontSize:12, color:"#718096", marginBottom:12 }}>
                    <strong style={{color:actionColor}}>{ACTION_LABELS["EXTRA_WORK"]}</strong> — 현재 가지고 계신 체류자격을 선택하세요
                  </div>
                  <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(220px, 1fr))", gap:8 }}>
                    {Array.from(extraWorkApplicantGroups.entries()).map(([applicant, rows]) => (
                      <TreeSelectButton
                        key={applicant}
                        label={APPLICANT_LABELS[applicant] ?? applicant}
                        subtitle={`${rows.length}건`}
                        color={actionColor}
                        selected={false}
                        onClick={() => setSelApplicant(applicant)}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* L2: 대분류(알파벳 계열) 선택 */}
              {selAction && selAction !== "EXTRA_WORK" && !selFamily && (
                <div>
                  <div style={{ fontSize:12, color:"#718096", marginBottom:12 }}>
                    <strong style={{color:actionColor}}>{ACTION_LABELS[selAction]}</strong> — 자격 계열을 선택하세요
                  </div>
                  <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(220px, 1fr))", gap:8 }}>
                    {treeActionFamilies.map(fam => (
                      <TreeSelectButton
                        key={fam}
                        label={glLabel("middle", selAction!, fam, "", overlay, FAMILY_LABELS[fam] ?? fam)}
                        color={actionColor}
                        selected={false}
                        onClick={() => { setSelFamily(fam); setSelMid(null); setSelSub(null); }}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* L3: 중분류 선택 */}
              {selAction && selAction !== "EXTRA_WORK" && selFamily && !selMid && (
                <div>
                  <div style={{ fontSize:12, color:"#718096", marginBottom:12 }}>
                    <strong style={{color:actionColor}}>{FAMILY_LABELS[selFamily] ?? selFamily}</strong> — 자격코드를 선택하세요
                  </div>
                  <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(160px, 1fr))", gap:8 }}>
                    {treeActionMids.map(mid => (
                      <TreeSelectButton
                        key={mid}
                        label={glLabel("minor", selAction!, selFamily!, mid, overlay, mid)}
                        subtitle={MID_LABELS[mid]}
                        color={actionColor}
                        selected={false}
                        onClick={() => { setSelMid(mid); setSelSub(null); }}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* L3: EXTRA_WORK — 신청 가능한 활동 목록 */}
              {selAction === "EXTRA_WORK" && selApplicant && (
                <div>
                  <div style={{ fontSize:12, color:"#718096", marginBottom:12 }}>
                    <strong style={{color:actionColor}}>{APPLICANT_LABELS[selApplicant] ?? selApplicant}</strong> — {extraWorkSelectedRows.length}건
                  </div>
                  <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
                    {extraWorkSelectedRows.map(row => (
                      <GuidelineCard key={row.row_id} row={row}
                        isSelected={selectedRow?.row_id === row.row_id}
                        onClick={() => setSelectedRow(selectedRow?.row_id === row.row_id ? null : row)}/>
                    ))}
                  </div>
                </div>
              )}

              {/* L4: 소분류 선택 (있는 경우) 또는 바로 카드 목록 */}
              {selAction && selAction !== "EXTRA_WORK" && selFamily && selMid && (
                <div>
                  {treeSubGroups && !selSub ? (
                    /* 소분류 있음 → 소분류 선택 */
                    <div>
                      <div style={{ fontSize:12, color:"#718096", marginBottom:12 }}>
                        <strong style={{color:actionColor}}>{selMid}</strong> — 세부 자격코드를 선택하세요
                      </div>
                      <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(160px, 1fr))", gap:8 }}>
                        {Array.from(treeSubGroups.keys()).sort().map(sub => (
                          <TreeSelectButton
                            key={sub}
                            label={sub}
                            subtitle={SUB_LABELS[sub]}
                            color={actionColor}
                            selected={false}
                            onClick={() => setSelSub(sub)}
                          />
                        ))}
                      </div>
                    </div>
                  ) : (
                    /* 소분류 없거나 선택됨 → 카드 목록 */
                    <div>
                      <div style={{ fontSize:12, color:"#718096", marginBottom:12 }}>
                        <strong style={{color:actionColor}}>{selSub ?? selMid}</strong> — {treeTerminalRows.length}건
                      </div>
                      <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
                        {treeTerminalRows.map(row => (
                          <GuidelineCard key={row.row_id} row={row}
                            isSelected={selectedRow?.row_id === row.row_id}
                            onClick={() => setSelectedRow(selectedRow?.row_id === row.row_id ? null : row)}/>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── 기존 진입점 모드 ── */}
          {!treeMode && (
            <>
              {/* L1: 진입점 그리드 */}
              {viewMode === "l1" && (
                <div>
                  <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:12 }}>
                    <GitBranch size={14} style={{color:"#A0AEC0"}}/>
                    <span style={{fontSize:12,color:"#A0AEC0"}}>업무 분류를 선택해 타고 들어가거나, 위에서 직접 검색하세요</span>
                  </div>
                  <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(210px, 1fr))", gap:10 }}>
                    {entryPoints.map(entry => (
                      <EntryPointCard
                        key={entry.id ?? entry.label}
                        entry={entry}
                        rowCount={entryRowCounts[entry.id ?? entry.label] ?? 0}
                        onClick={() => handleEntryClick(entry)}
                      />
                    ))}
                  </div>
                  <div style={{ marginTop:24, textAlign:"center" }}>
                    <div style={{fontSize:11,color:"#CBD5E0",marginBottom:10}}>자주 찾는 서류</div>
                    <div style={{display:"flex",flexWrap:"wrap",gap:6,justifyContent:"center"}}>
                      {["통합신청서","사업자등록증","재직증명서","가족관계증명서","위임장"].map(hint => (
                        <button key={hint}
                          onClick={() => { setSearchQuery(hint); doSearch(hint, ""); }}
                          style={{ fontSize:11, padding:"4px 12px", borderRadius:99, background:"rgba(212,168,67,0.08)", color:"var(--hw-gold-text)", border:"1px solid rgba(212,168,67,0.35)", cursor:"pointer" }}>
                          {hint}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* 브레드크럼 (L2·L3) */}
              {(viewMode === "l2" || viewMode === "l3") && selectedEntry && (
                <div style={{ display:"flex", alignItems:"center", gap:4, marginBottom:16, flexWrap:"wrap" }}>
                  <button onClick={handleBackToL1}
                    style={{ display:"flex", alignItems:"center", gap:3, fontSize:12, color:"#718096", background:"#F7FAFC", border:"1px solid #E2E8F0", borderRadius:20, padding:"4px 12px", cursor:"pointer", fontWeight:500 }}>
                    ← 전체 목록
                  </button>
                  <ChevronRight size={13} style={{color:"#CBD5E0"}}/>
                  {viewMode === "l3" && selectedActionType ? (
                    <>
                      <button onClick={handleBackToL2}
                        style={{ fontSize:12, color:"#718096", background:"#F7FAFC", border:"1px solid #E2E8F0", borderRadius:20, padding:"4px 12px", cursor:"pointer", fontWeight:500 }}>
                        {selectedEntry.label}
                      </button>
                      <ChevronRight size={13} style={{color:"#CBD5E0"}}/>
                      <span style={{ fontSize:12, fontWeight:700, padding:"4px 12px", background:`${ACTION_TYPE_COLORS[selectedActionType]}18`, borderRadius:20, border:`1px solid ${ACTION_TYPE_COLORS[selectedActionType]}40`, color:ACTION_TYPE_COLORS[selectedActionType] }}>
                        {ACTION_TYPE_LABELS[selectedActionType]}
                      </span>
                    </>
                  ) : (
                    <span style={{ fontSize:12, fontWeight:700, padding:"4px 12px", background:`${selectedEntry.color}18`, borderRadius:20, border:`1px solid ${selectedEntry.color}40`, color:selectedEntry.color }}>
                      {selectedEntry.label}
                    </span>
                  )}
                  <span style={{ marginLeft:"auto", fontSize:12, color:"#A0AEC0" }}>
                    {viewMode === "l3" ? `${treeL3Rows.length}건` : ""}
                  </span>
                </div>
              )}

              {/* L2: 업무유형 선택 */}
              {viewMode === "l2" && selectedEntry && (
                <div>
                  <div style={{fontSize:12,color:"#718096",marginBottom:14}}>
                    <strong style={{color:"#2D3748"}}>{selectedEntry.label}</strong> — 업무 유형을 선택하세요
                  </div>
                  <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(200px, 1fr))", gap:10 }}>
                    {treeL2Items.map(item => (
                      <ActionTypeCard
                        key={item.key}
                        actionType={item.key}
                        label={item.label}
                        count={item.count}
                        color={item.color}
                        onClick={() => { setSelectedActionType(item.key); setSelectedRow(null); }}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* L3: 항목 목록 */}
              {viewMode === "l3" && (
                treeLoading ? (
                  <div style={{ display:"flex", justifyContent:"center", padding:"60px 0" }}>
                    <Loader2 size={24} className="animate-spin" style={{color:"var(--hw-gold)"}}/>
                  </div>
                ) : treeL3Rows.length === 0 ? (
                  <div style={{textAlign:"center",padding:"40px 0",color:"#A0AEC0",fontSize:13}}>
                    {treeError || "이 분류에 연결된 실무지침이 없습니다."}
                  </div>
                ) : (
                  <div style={{display:"flex",flexDirection:"column",gap:10}}>
                    {treeL3Rows.map(row => (
                      <GuidelineCard key={row.row_id} row={row}
                        isSelected={selectedRow?.row_id === row.row_id}
                        onClick={() => setSelectedRow(selectedRow?.row_id === row.row_id ? null : row)}/>
                    ))}
                  </div>
                )
              )}
            </>
          )}
        </>
      )}

      {/* 매뉴얼 PDF 뷰어 */}
      {manualPdfRefs && (
        <ManualPdfViewer refs={manualPdfRefs} onClose={() => setManualPdfRefs(null)} />
      )}

      {/* 상세 패널 */}
      {selectedRow && (
        <DetailPanel
          row={selectedRow}
          overlay={overlay}
          onOverlayChange={reloadOverlay}
          onClose={() => { setSelectedRow(null); setManualPdfRefs(null); }}
          onShowManual={(refs) => setManualPdfRefs(prev => prev ? null : refs)}
          manualOpen={!!manualPdfRefs}
          isAdmin={isAdmin}
          onRowUpdate={handleRowUpdate}
        />
      )}
    </div>
  );
}
