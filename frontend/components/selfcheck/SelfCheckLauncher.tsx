"use client";
// 공개 진입점 — 버튼을 누르면 자가점검 팝업을 연다.
// 게시된 관리 설정만 GET(1회). 진행 중에는 어떤 네트워크 요청도 없다.
import { useEffect, useRef, useState } from "react";
import { selfCheckApi } from "@/lib/api";
import type { SelfCheckConfig } from "@/lib/selfcheck/types";
import { DEFAULT_SELF_CHECK_CONFIG } from "@/lib/selfcheck/defaultConfig";
import { validateConfig } from "@/lib/selfcheck/logic";
import CommonCriteriaSelfCheck from "./CommonCriteriaSelfCheck";

interface Props {
  className?: string;
  label?: string;
  style?: React.CSSProperties;
}

export default function SelfCheckLauncher({ className, label = "공통기준 자가점검", style }: Props) {
  const [config, setConfig] = useState<SelfCheckConfig | null>(null);
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    // 게시된 설정만 조회. 미게시/오류 시 번들 기본 설정(CR-1.0)로 동작(관리자가 저장하면 대체).
    selfCheckApi.getPublic()
      .then((r) => {
        if (cancelled) return;
        const data = r.data as { published?: boolean; config?: SelfCheckConfig | null };
        const cfg = data?.published && data.config ? data.config : DEFAULT_SELF_CHECK_CONFIG;
        setConfig(validateConfig(cfg).errors.length === 0 ? cfg : DEFAULT_SELF_CHECK_CONFIG);
      })
      .catch(() => { if (!cancelled) setConfig(DEFAULT_SELF_CHECK_CONFIG); });
    return () => { cancelled = true; };
  }, []);

  if (!config) return null;

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
      <CommonCriteriaSelfCheck config={config} open={open} onClose={() => setOpen(false)} />
    </>
  );
}
