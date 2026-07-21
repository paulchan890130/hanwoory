"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { selfCheckApi } from "@/lib/api";
import type { SelfCheckConfig } from "@/lib/selfcheck/types";
import { DEFAULT_SELF_CHECK_CONFIG } from "@/lib/selfcheck/defaultConfig";
import SelfCheckAdminEditor from "@/components/selfcheck/SelfCheckAdminEditor";

export default function SelfCheckAdminPage() {
  const [state, setState] = useState<"loading" | "ready" | "denied">("loading");
  const [initial, setInitial] = useState<SelfCheckConfig | null>(null);
  const [published, setPublished] = useState(false);

  useEffect(() => {
    // 서버가 최종 권위(require_system_admin). 403 → 접근 거부(office_admin 직접 접근 차단),
    // 200 → 시스템 관리자(마스터 또는 env 허용목록) → 편집기 표시.
    selfCheckApi.adminGet()
      .then((r) => {
        const data = r.data as { published?: boolean; config?: SelfCheckConfig | null };
        setInitial(data?.config ?? DEFAULT_SELF_CHECK_CONFIG);
        setPublished(!!data?.published);
        setState("ready");
      })
      .catch((e) => {
        if (e?.response?.status === 403) { setState("denied"); return; }
        // 그 외(개발/오프라인) → 기본 설정으로 편집기 노출
        setInitial(DEFAULT_SELF_CHECK_CONFIG);
        setState("ready");
      });
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1 className="hw-page-title">공통기준 자가점검 관리</h1>
        <Link href="/marketing" className="btn-secondary" style={{ textDecoration: "none", fontSize: 13 }}>← 마케팅으로</Link>
      </div>
      {state === "loading" && <div className="hw-card" style={{ color: "var(--hw-text-sub)" }}>불러오는 중...</div>}
      {state === "denied" && (
        <div className="hw-card" style={{ color: "#C53030", lineHeight: 1.7 }}>
          시스템 관리자 전용 화면입니다. 접근 권한이 없습니다.
        </div>
      )}
      {state === "ready" && <SelfCheckAdminEditor initial={initial} initialPublished={published} />}
    </div>
  );
}
