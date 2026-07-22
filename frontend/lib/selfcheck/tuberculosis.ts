// 결핵검진 자가점검(TB-1.0) 전용 source of truth + 게시 검증.
// 이 파일은 "관리자 설정"만 다룬다(사용자 답변/결과 무관). 프론트 편의 검증이며 서버가 최종 권위.
//
// 공식 기준: 법무부 결핵검사 의무화 대상국가(2020.4.1. 확대, 35개국) 및 2025~2026년
// 재외공관 공식 안내와 대조. 목록은 정확히 35개이며 임의 번역·축약하지 않는다.
import type { SelfCheckConfig, SelfCheckItem } from "./types";

// 공식 결핵 고위험 국가 35개국(표시 순서 = 공식 안내 배열). 임의 변경 금지.
export const TUBERCULOSIS_HIGH_RISK_COUNTRIES: string[] = [
  "네팔", "동티모르", "러시아", "말레이시아", "몽골", "미얀마", "방글라데시",
  "베트남", "스리랑카", "우즈베키스탄", "인도", "인도네시아", "중국", "캄보디아",
  "키르기스스탄", "태국", "파키스탄", "필리핀", "라오스", "카자흐스탄", "타지키스탄",
  "우크라이나", "아제르바이잔", "벨라루스", "몰도바공화국", "나이지리아",
  "남아프리카공화국", "에티오피아", "콩고민주공화국", "케냐", "모잠비크", "짐바브웨",
  "앙골라", "페루", "파푸아뉴기니",
];

// 표기 alias(검색·비교 시 동일 국가로 취급). 화면 표기는 canonical 로 통일.
export const TB_COUNTRY_ALIASES: Record<string, string> = {
  "키르기스": "키르기스스탄",
  "키르기즈": "키르기스스탄",
  "키르기스공화국": "키르기스스탄",
  "몰도바": "몰도바공화국",
  "남아공": "남아프리카공화국",
  "콩고": "콩고민주공화국",
};

export function normalizeCountry(name: string): string {
  const s = (name || "").replace(/\s+/g, "").trim();
  return TB_COUNTRY_ALIASES[s] || s;
}

// canonical 집합(정규화된 35개국).
export const TB_CANONICAL_SET: ReadonlySet<string> = new Set(
  TUBERCULOSIS_HIGH_RISK_COUNTRIES.map(normalizeCountry),
);
export const TB_CANONICAL_COUNT = TB_CANONICAL_SET.size; // 35

// 폐기된 과거(잘못된) 문구 — 하나라도 있으면 게시 차단.
export const TB_BANNED_PHRASES: string[] = [
  "90일을 초과하는 장기체류",
  "최근 6개월 이내 결핵검진",
  "최근 6개월 이내 결핵검진 확인서 제출 이력",
  "6개월내 검진 제출이력",
];

// 국가 목록 출처 metadata 기본값(관리자 설정용 — 사용자 답변과 무관).
export const TB_SOURCE_META = {
  country_list_source_title: "법무부 결핵검사 의무화 대상국가 및 재외공관 공식 안내",
  country_list_source_date: "2020-04-01 기준 35개국",
  country_list_verified_at: "2026-07-23",
  country_list_source_note: "법무부 및 2025~2026년 재외공관 공식 안내와 대조",
} as const;

// TB 항목 판별: item_id 가 tuberculosis 이거나 config.logic_version 이 TB-1.0.
export function isTuberculosisItem(item: Pick<SelfCheckItem, "item_id" | "config">): boolean {
  return item.item_id === "tuberculosis" || (item.config?.logic_version === "TB-1.0");
}
export function isTuberculosisConfig(cfg: SelfCheckConfig | null | undefined): boolean {
  return !!cfg && cfg.logic_version === "TB-1.0";
}

function configTextBlob(cfg: SelfCheckConfig): string {
  const parts: string[] = [cfg.item_name || ""];
  for (const q of cfg.questions || []) parts.push(q.text || "", q.summary || "", q.help || "");
  for (const r of cfg.results || []) parts.push(r.headline || "", r.label || "", r.notice_text || "");
  return parts.join("\n");
}

export interface TbVerification {
  ok: boolean;
  reasons: string[];
  count: number;            // 정규화된 국가 수(빈값 제외)
  dup: number;              // 중복 개수
  matchesCanonical: boolean;
  hasSource: boolean;       // source title/date/verified_at 모두 존재
  banned: boolean;          // 폐기 문구 포함 여부
  versionOk: boolean;       // logic_version == TB-1.0
}

// TB 항목이 "게시 가능"한지 검증. 서버 로직과 동일 개념(서버가 최종 권위).
export function verifyTuberculosis(cfg: SelfCheckConfig | null | undefined): TbVerification {
  const reasons: string[] = [];
  const versionOk = !!cfg && cfg.logic_version === "TB-1.0";
  if (!versionOk) reasons.push("로직 버전이 TB-1.0 이 아닙니다.");

  const raw = (cfg?.country_list || []).map((c) => (c || "").trim()).filter(Boolean);
  const norm = raw.map(normalizeCountry);
  const count = norm.length;
  const uniq = new Set(norm);
  const dup = norm.length - uniq.size;
  const matchesCanonical = uniq.size === TB_CANONICAL_SET.size && Array.from(uniq).every((c) => TB_CANONICAL_SET.has(c));

  if (count !== TB_CANONICAL_COUNT) reasons.push(`국가 목록이 정확히 ${TB_CANONICAL_COUNT}개가 아닙니다(현재 ${count}개).`);
  if (dup > 0) reasons.push("국가 목록에 중복이 있습니다.");
  if (!matchesCanonical) reasons.push("공식 35개국 목록과 일치하지 않습니다.");

  const hasSource = !!(cfg && (cfg.country_list_source_title || "").trim()
    && (cfg.country_list_source_date || "").trim()
    && (cfg.country_list_verified_at || "").trim());
  if (!hasSource) reasons.push("출처 정보(source metadata)가 없습니다.");

  const blob = cfg ? configTextBlob(cfg) : "";
  const banned = TB_BANNED_PHRASES.some((b) => blob.includes(b));
  if (banned) reasons.push("폐기된 과거 문구가 포함되어 있습니다.");

  return { ok: reasons.length === 0, reasons, count, dup, matchesCanonical, hasSource, banned, versionOk };
}
