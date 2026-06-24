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
