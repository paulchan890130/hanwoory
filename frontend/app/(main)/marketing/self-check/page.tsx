"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { selfCheckApi } from "@/lib/api";
import type { SelfCheckBundle } from "@/lib/selfcheck/types";
import { normalizeBundle } from "@/lib/selfcheck/logic";
import SelfCheckAdminEditor from "@/components/selfcheck/SelfCheckAdminEditor";

// 관리자 조회는 실패/설정없음/정상/손상을 구별한다(서버가 최종 권위).
// fail-closed: 조회 실패(503)·손상(409)에서는 편집기·저장 버튼을 표시하지 않고,
// 기본(PDF) 설정을 자동으로 보여주지 않는다(기존 운영 설정 덮어쓰기 방지).
type PageState = "loading" | "ready" | "denied" | "unavailable" | "corrupt";

export default function SelfCheckAdminPage() {
  const [state, setState] = useState<PageState>("loading");
  const [initial, setInitial] = useState<SelfCheckBundle | null>(null);
  const [obsoleteLegacy, setObsoleteLegacy] = useState(false);
  const [corruptErrors, setCorruptErrors] = useState<string[]>([]);

  const load = useCallback(() => {
    setState("loading");
    // 서버가 최종 권위(require_system_admin). 200 → 편집기, 403 → 거부, 503 → 조회실패,
    // 409 → 손상. 정상 빈 bundle(absent)은 그대로 빈 bundle 로 편집기에 전달(기본안 자동대체 금지).
    selfCheckApi.adminGet()
      .then((r) => {
        const bundle = normalizeBundle(r.data);
        setObsoleteLegacy(!!(r.data as { obsolete_legacy?: boolean })?.obsolete_legacy);
        setInitial(bundle);   // 빈 bundle 이어도 기본안으로 대체하지 않음
        setState("ready");
      })
      .catch((e) => {
        const status = e?.response?.status;
        const detail = e?.response?.data?.detail;
        if (status === 403) { setState("denied"); return; }
        if (status === 409) {
          setCorruptErrors(Array.isArray(detail?.errors) ? detail.errors : []);
          setState("corrupt");
          return;
        }
        // 500·503·네트워크 실패 → unavailable (기본안 자동 표시 없음, 저장 차단)
        setState("unavailable");
      });
  }, []);

  useEffect(() => { load(); }, [load]);

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
      {state === "unavailable" && (
        <div data-testid="selfcheck-unavailable" className="hw-card" style={{ color: "#C53030", lineHeight: 1.7 }}>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>자가점검 설정을 불러오지 못했습니다.</div>
          <div style={{ color: "var(--hw-text-sub)", fontSize: 13 }}>
            기존 설정 보호를 위해 편집을 중단했습니다. 잠시 후 다시 시도하세요.
          </div>
          <button className="btn-secondary" data-testid="selfcheck-retry" style={{ marginTop: 10, fontSize: 13 }} onClick={load}>다시 시도</button>
        </div>
      )}
      {state === "corrupt" && (
        <div data-testid="selfcheck-corrupt" className="hw-card" style={{ color: "#C53030", lineHeight: 1.7 }}>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>저장된 자가점검 설정이 손상되어 안전하게 편집할 수 없습니다.</div>
          <div style={{ color: "var(--hw-text-sub)", fontSize: 13 }}>
            기존 설정을 덮어쓰지 않도록 편집이 차단되었습니다. 운영 DB 는 자동으로 변경되지 않습니다.
          </div>
          {corruptErrors.length > 0 && (
            <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 12, color: "var(--hw-text-sub)" }}>
              {corruptErrors.slice(0, 8).map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          )}
          <button className="btn-secondary" data-testid="selfcheck-retry" style={{ marginTop: 10, fontSize: 13 }} onClick={load}>다시 시도</button>
        </div>
      )}
      {state === "ready" && <SelfCheckAdminEditor initialBundle={initial} obsoleteLegacy={obsoleteLegacy} />}
    </div>
  );
}
