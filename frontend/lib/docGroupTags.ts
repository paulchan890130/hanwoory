// 업무별 준비서류 글↔중분류 연결 유틸 (A안: marketing_posts.tags 안의 토큰 사용).
//
//   doc_group:<group_key>  — 어느 중분류에 속하는지 (group_key 는 [a-z0-9-])
//   doc_order:<n>          — 중분류 내 표시 순서(선택). 없으면 뒤로.
//
// slug/URL/제목은 절대 건드리지 않는다. tags 의 이 두 토큰만 추가/변경한다.

const GROUP_RE = /doc_group:([a-z0-9][a-z0-9-]*)/i;
const ORDER_RE = /doc_order:(\d+)/i;

export function getDocGroup(tags: string | undefined | null): string {
  const m = (tags || "").match(GROUP_RE);
  return m ? m[1].toLowerCase() : "";
}

export function getDocOrder(tags: string | undefined | null): number | null {
  const m = (tags || "").match(ORDER_RE);
  return m ? parseInt(m[1], 10) : null;
}

// tags 를 콤마 토큰으로 분해(공백 정리). doc_group/doc_order 외 사용자 태그는 보존.
function splitTags(tags: string | undefined | null): string[] {
  return (tags || "")
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
}

function joinTags(tokens: string[]): string {
  return tokens.join(", ");
}

// doc_group 토큰을 key 로 설정(기존 doc_group 토큰 제거 후 추가). 다른 태그 보존.
export function setDocGroup(tags: string | undefined | null, key: string): string {
  const kept = splitTags(tags).filter((t) => !GROUP_RE.test(t));
  if (key) kept.push(`doc_group:${key}`);
  return joinTags(kept);
}

// doc_order 토큰 설정(null 이면 제거).
export function setDocOrder(tags: string | undefined | null, order: number | null): string {
  const kept = splitTags(tags).filter((t) => !ORDER_RE.test(t));
  if (order != null) kept.push(`doc_order:${order}`);
  return joinTags(kept);
}

// ── 업무안내 게시판(/board) vs 준비서류 분류 기준 (공개·관리자 공통 단일 출처) ──
// 업무안내 게시판 = 카테고리가 board 계열이거나 빈값. doc_group 태그 유무는 보지 않는다.
export const BOARD_CATEGORIES = ["공지사항", "업무 안내", "제도 변경", "기타"];
const BOARD_SET = new Set(BOARD_CATEGORIES);
// 준비서류 계열 카테고리(업무안내 게시판에서 제외 대상).
export const PREP_CATEGORIES = ["준비서류 안내", "출입국 업무안내", "중국 공증·아포스티유", "영주권·귀화"];
const PREP_SET = new Set(PREP_CATEGORIES);

// /board(공개) 및 관리자 업무안내 관리에 노출할 글인지 — **카테고리 기준 단일 규칙**.
export function isBoardPost(p: { category?: string }): boolean {
  const c = (p.category || "").trim();
  return c === "" || BOARD_SET.has(c);
}

// 미분류 준비서류 = 준비서류 계열 카테고리 + doc_group 미지정(관리자에서만 확인).
export function isUnclassifiedPrep(p: { category?: string; tags?: string }): boolean {
  const c = (p.category || "").trim();
  return PREP_SET.has(c) && !getDocGroup(p.tags);
}
