"use client";
// 마케팅 게시글 본문 shortcode `[[self-check:ID]]` → 해당 자가점검 도구 버튼.
// placement=post 로 공개 설정을 조회하고, 게시 + 팝업 + 그래프 유효 + 위치(post) 통과 항목만 노출.
// 알 수 없는 item_id / 미게시 / popup_enabled=false / placement 불일치 → 아무것도 렌더하지 않음
// (공개 화면에 오류 문구를 노출하지 않는다). 답변/결과/경로는 서버·스토리지에 저장·전송하지 않는다.
import { useEffect, useState } from "react";
import { selfCheckApi } from "@/lib/api";
import type { SelfCheckItem } from "@/lib/selfcheck/types";
import { normalizeBundle, publishedItems } from "@/lib/selfcheck/logic";
import CommonCriteriaSelfCheck from "./CommonCriteriaSelfCheck";

// 한 게시글에 shortcode 가 여러 개 있어도 self-check config 요청은 1회만 — placement 별 promise 캐시.
const _postItemsCache = new Map<string, Promise<SelfCheckItem[]>>();
function loadPostItems(): Promise<SelfCheckItem[]> {
  const key = "post";
  if (!_postItemsCache.has(key)) {
    _postItemsCache.set(
      key,
      selfCheckApi
        .getPublic("post")
        .then((r) => publishedItems(normalizeBundle(r.data), "post"))
        .catch(() => [] as SelfCheckItem[]),
    );
  }
  return _postItemsCache.get(key)!;
}

export default function SelfCheckPostBlock({ itemId }: { itemId: string }) {
  const [items, setItems] = useState<SelfCheckItem[] | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadPostItems().then((all) => { if (!cancelled) setItems(all); });
    return () => { cancelled = true; };
  }, []);

  if (items === null) return null; // 로딩 중 → 아무것도 그리지 않음(깜빡임/오류문구 방지)

  const wantAll = itemId === "all";
  const shown = wantAll ? items : items.filter((it) => it.item_id === itemId);
  if (!shown.length) return null; // 미게시/알수없음/위치불일치 → 렌더 안 함

  const label = wantAll
    ? "공통기준 자가점검"
    : (shown[0].title || shown[0].config.item_name || "자가점검");

  return (
    <div style={{ margin: "22px 0" }} data-testid={`selfcheck-post-${itemId}`}>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid={`selfcheck-post-open-${itemId}`}
        style={{
          display: "inline-flex", alignItems: "center", gap: 8, cursor: "pointer",
          background: "var(--hw-gold-50, #FBF6EC)", border: "1px solid var(--hw-gold-300, #E3C77A)",
          color: "var(--hw-gold-800, #5A4B1E)", borderRadius: 10, padding: "12px 18px",
          fontSize: 15, fontWeight: 700,
        }}
      >
        <span aria-hidden>🩺</span> {label} 시작하기
      </button>
      <CommonCriteriaSelfCheck items={shown} open={open} onClose={() => setOpen(false)} />
    </div>
  );
}
