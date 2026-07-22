"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { selfCheckApi } from "@/lib/api";
import type { SelfCheckBundle } from "@/lib/selfcheck/types";
import { normalizeBundle } from "@/lib/selfcheck/logic";
import { DEFAULT_SELF_CHECK_BUNDLE } from "@/lib/selfcheck/defaultConfig";
import SelfCheckAdminEditor from "@/components/selfcheck/SelfCheckAdminEditor";

export default function SelfCheckAdminPage() {
  const [state, setState] = useState<"loading" | "ready" | "denied">("loading");
  const [initial, setInitial] = useState<SelfCheckBundle | null>(null);

  useEffect(() => {
    // 서버가 최종 권위(require_system_admin). 403 → 접근 거부, 200 → 편집기 표시.
    // 응답은 번들(신규) 또는 레거시 단일 config 를 서버가 번들로 정규화해 반환한다.
    selfCheckApi.adminGet()
      .then((r) => {
        const bundle = normalizeBundle(r.data);
        setInitial(bundle.items.length ? bundle : DEFAULT_SELF_CHECK_BUNDLE);
        setState("ready");
      })
      .catch((e) => {
        if (e?.response?.status === 403) { setState("denied"); return; }
        // 그 외(개발/오프라인) → PDF 기준 기본 번들로 편집기 노출(저장 전까지 DB 무변경)
        setInitial(DEFAULT_SELF_CHECK_BUNDLE);
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
      {state === "ready" && <SelfCheckAdminEditor initialBundle={initial} />}
    </div>
  );
}
