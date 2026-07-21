"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { selfCheckApi } from "@/lib/api";
import type { SelfCheckConfig } from "@/lib/selfcheck/types";
import { DEFAULT_SELF_CHECK_CONFIG } from "@/lib/selfcheck/defaultConfig";
import SelfCheckAdminEditor from "@/components/selfcheck/SelfCheckAdminEditor";

export default function SelfCheckAdminPage() {
  const [state, setState] = useState<"loading" | "ready">("loading");
  const [initial, setInitial] = useState<SelfCheckConfig | null>(null);
  const [published, setPublished] = useState(false);

  useEffect(() => {
    selfCheckApi.adminGet()
      .then((r) => {
        const data = r.data as { published?: boolean; config?: SelfCheckConfig | null };
        setInitial(data?.config ?? DEFAULT_SELF_CHECK_CONFIG);
        setPublished(!!data?.published);
      })
      .catch(() => setInitial(DEFAULT_SELF_CHECK_CONFIG))
      .finally(() => setState("ready"));
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1 className="hw-page-title">공통기준 자가점검 관리</h1>
        <Link href="/marketing" className="btn-secondary" style={{ textDecoration: "none", fontSize: 13 }}>← 마케팅으로</Link>
      </div>
      {state === "loading"
        ? <div className="hw-card" style={{ color: "var(--hw-text-sub)" }}>불러오는 중...</div>
        : <SelfCheckAdminEditor initial={initial} initialPublished={published} />}
    </div>
  );
}
