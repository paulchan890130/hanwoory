"use client";
// 문서 자동작성 필수정보 미완료 배너 — 대시보드/상단 상주.
// profile_complete=false 일 때만 노출(서버가 역할별로 계산 → office_staff 는 수정 불가한 tenant
// 공통정보 때문에 영구 경고가 뜨지 않는다). /my 페이지에서는 중복이므로 숨긴다.
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { authApi } from "@/lib/api";

export default function ProfileIncompleteBanner() {
  const pathname = usePathname();
  const [incomplete, setIncomplete] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () => authApi.me()
      .then((r) => { if (!cancelled) setIncomplete((r.data as { profile_complete?: boolean }).profile_complete === false); })
      .catch(() => {/* 무시 */});
    load();
    const onFocus = () => load();
    window.addEventListener("focus", onFocus);
    return () => { cancelled = true; window.removeEventListener("focus", onFocus); };
  }, [pathname]);

  if (!incomplete || pathname === "/my") return null;

  return (
    <div data-testid="profile-incomplete-banner" style={{
      display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap",
      background: "#FFFAF0", border: "1px solid #FBD38D", color: "#9C4221",
      borderRadius: 8, padding: "10px 14px", marginBottom: 16, fontSize: 13, lineHeight: 1.6,
    }}>
      <span>문서 자동작성 필수정보가 완료되지 않았습니다.</span>
      <a href="/my" className="btn-secondary" style={{ textDecoration: "none", fontSize: 12, whiteSpace: "nowrap" }}>
        마이페이지에서 입력하기
      </a>
    </div>
  );
}
