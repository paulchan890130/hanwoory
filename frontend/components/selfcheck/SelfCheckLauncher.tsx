"use client";
// 공개 진입점 — 게시된 유효한 관리 설정이 있을 때만 버튼을 렌더한다.
// 미게시/설정없음/검증실패/API오류 → 버튼을 렌더하지 않는다(공개 사용자에게 번들 기본설정을
// 대신 노출하지 않는다). 진행 중에는 설정 GET 외 네트워크 요청이 없다.
import { useEffect, useRef, useState } from "react";
import { selfCheckApi } from "@/lib/api";
import type { SelfCheckConfig } from "@/lib/selfcheck/types";
import { validateConfig } from "@/lib/selfcheck/logic";
import CommonCriteriaSelfCheck from "./CommonCriteriaSelfCheck";

interface Props {
  className?: string;
  label?: string;
  style?: React.CSSProperties;
}

export default function SelfCheckLauncher({ className, label = "공통기준 자가점검", style }: Props) {
  // null = 표시 안 함(초기/불가). 유효 게시 설정일 때만 SelfCheckConfig 로 설정.
  const [config, setConfig] = useState<SelfCheckConfig | null>(null);
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    // 게시된 유효한 설정만 표시. 그 외(미게시/손상/오류)는 숨김 — 기본설정 fallback 없음.
    selfCheckApi.getPublic()
      .then((r) => {
        if (cancelled) return;
        const data = r.data as { published?: boolean; config?: SelfCheckConfig | null };
        const cfg = data?.config;
        const ok =
          data?.published === true &&
          !!cfg &&
          validateConfig(cfg).errors.length === 0;
        setConfig(ok ? (cfg as SelfCheckConfig) : null);
      })
      .catch(() => {
        // API 404/500/503/네트워크/JSON 오류 → 숨김, 재시도·fallback·로그 없음.
        if (!cancelled) setConfig(null);
      });
    return () => { cancelled = true; };
  }, []);

  if (!config) return null;  // 게시 유효 설정이 없으면 런처 자체를 렌더하지 않음

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
