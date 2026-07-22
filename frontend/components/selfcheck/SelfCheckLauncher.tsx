"use client";
// 공개 진입점 — 게시된 유효 항목이 1개 이상일 때만 버튼을 렌더한다.
// 미게시/항목없음/검증실패/API오류 → 버튼을 렌더하지 않는다(기본설정 fallback 없음).
// 진행 중에는 설정 GET 외 네트워크 요청이 없다(답변/결과 미전송).
import { useEffect, useRef, useState } from "react";
import { selfCheckApi } from "@/lib/api";
import type { SelfCheckItem } from "@/lib/selfcheck/types";
import { normalizeBundle, publishedItems } from "@/lib/selfcheck/logic";
import CommonCriteriaSelfCheck from "./CommonCriteriaSelfCheck";

interface Props {
  className?: string;
  label?: string;
  style?: React.CSSProperties;
}

export default function SelfCheckLauncher({ className, label = "공통기준 자가점검", style }: Props) {
  const [items, setItems] = useState<SelfCheckItem[]>([]);
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    // 공개 API 는 {schema_version, items:[게시 항목]} 를 반환. 클라이언트도 재검증 후 노출.
    selfCheckApi.getPublic()
      .then((r) => {
        if (cancelled) return;
        const bundle = normalizeBundle(r.data);
        setItems(publishedItems(bundle));
      })
      .catch(() => { if (!cancelled) setItems([]); });
    return () => { cancelled = true; };
  }, []);

  if (!items.length) return null;  // 게시 유효 항목이 없으면 런처 자체를 렌더하지 않음

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        className={className}
        style={style}
        onClick={() => setOpen(true)}
        data-testid="self-check-open"
      >
        {label}
      </button>
      <CommonCriteriaSelfCheck items={items} open={open} onClose={() => setOpen(false)} />
    </>
  );
}
