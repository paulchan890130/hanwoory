"use client";
// 최초 로그인 온보딩(사용법 안내) 투어 — (main) 인증 셸에 상주.
// - 서버(onboarding_required)가 권위. 신규 초대 사용자만 자동 표시(기존 사용자 backfill 완료).
//   시스템 관리자는 강제하지 않는다(서버가 onboarding_required=false 로 내려줌).
// - 완료/건너뛰기 → authApi.completeOnboarding 기록 + localStorage 가드 → 재로그인·나브 시 자동 미표시.
// - "사용법 다시 보기"는 window 'restart-onboarding' 이벤트로 언제든 재시작(서버 상태 미변경).
// - route 가 바뀌어도 단계 유지(컨트롤러가 셸에 상주). 화면 밖 대상은 scrollIntoView 후 강조.
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getUser } from "@/lib/auth";
import { authApi } from "@/lib/api";

interface TourStep {
  key: string;
  title: string;
  body: string;
  tourId?: string;   // 강조할 data-tour-id (없으면 중앙 카드)
  route?: string;    // 이동할 경로(필요 시)
}

const ONBOARDING_VERSION = 1;

function guardKey(loginId: string) { return `onboarding_done_${loginId}_v${ONBOARDING_VERSION}`; }

function buildSteps(isAdmin: boolean): TourStep[] {
  const steps: TourStep[] = [
    { key: "welcome", title: "한우리소프트에 오신 것을 환영합니다", body: isAdmin
        ? "문서 자동작성을 위해 먼저 사무소 필수정보를 입력하는 방법을 안내해 드립니다. 잠시만 따라와 주세요."
        : "주요 메뉴 사용법을 간단히 안내해 드립니다. 잠시만 따라와 주세요." },
    { key: "my", title: "마이페이지", body: "여기에서 문서 자동작성에 필요한 사무소 정보를 관리합니다.", tourId: "sidebar-my" },
    { key: "profile", title: "문서 자동작성 필수정보", body: isAdmin
        ? "사무소명·주소·대표 전화번호·사업자등록번호·행정사 주민등록번호를 입력하세요. 이 정보가 문서에 자동으로 들어갑니다."
        : "본인 담당자명과 연락처를 확인·입력하세요. 사무소 공통정보는 대표자(사무소 관리자)가 관리합니다.",
      tourId: "profile-required-info", route: "/my" },
    { key: "save", title: "저장", body: "입력한 필수정보를 저장하면 문서 자동작성에 반영됩니다.", tourId: "profile-save", route: "/my" },
    { key: "customers", title: "고객관리", body: "고객 정보를 등록·조회합니다.", tourId: "sidebar-customers" },
    { key: "work", title: "업무관리", body: "진행 중인 업무를 관리합니다.", tourId: "sidebar-work" },
    { key: "quick-doc", title: "문서 자동작성", body: "고객·사무소 정보를 바탕으로 신청서류를 자동으로 작성합니다.", tourId: "sidebar-quick-doc" },
  ];
  if (isAdmin) {
    steps.push({ key: "account", title: "계정·사무소 관리", body: "실무자 계정과 사무소 설정을 관리합니다.", tourId: "sidebar-account" });
  }
  steps.push({ key: "done", title: "준비 완료", body: isAdmin
    ? "이제 필수정보를 입력하고 서비스를 사용해 보세요. 상단 ‘사용법 다시 보기’로 언제든 다시 볼 수 있습니다."
    : "이제 서비스를 사용해 보세요. 상단 ‘사용법 다시 보기’로 언제든 다시 볼 수 있습니다." });
  return steps;
}

export default function OnboardingController() {
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [steps, setSteps] = useState<TourStep[]>([]);
  const [idx, setIdx] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const versionRef = useRef(ONBOARDING_VERSION);
  const loginRef = useRef("");

  const start = useCallback((isAdmin: boolean) => {
    setSteps(buildSteps(isAdmin));
    setIdx(0);
    setOpen(true);
  }, []);

  // 자동 표시(서버 권위) — 최초 마운트 1회.
  useEffect(() => {
    const u = getUser();
    loginRef.current = u?.login_id ?? "";
    let cancelled = false;
    authApi.me()
      .then((r) => {
        if (cancelled) return;
        const d = r.data as {
          onboarding_required?: boolean; onboarding_version?: number;
          role?: string; is_admin?: boolean; is_master?: boolean;
        };
        versionRef.current = d.onboarding_version ?? ONBOARDING_VERSION;
        const gk = `onboarding_done_${loginRef.current}_v${versionRef.current}`;
        if (localStorage.getItem(gk) === "1") return;         // 이미 완료/건너뜀(로컬 가드)
        if (!d.onboarding_required) return;                   // 서버가 불필요 판단(기존·시스템관리자)
        const isAdmin = d.role === "office_admin" || !!d.is_admin || !!d.is_master;
        start(isAdmin);
      })
      .catch(() => {/* 실패 시 강제 표시하지 않음 */});
    return () => { cancelled = true; };
  }, [start]);

  // "사용법 다시 보기" — 언제든 재시작(서버 상태 미변경).
  useEffect(() => {
    const onRestart = () => {
      const u = getUser();
      const isAdmin = u?.role === "office_admin" || !!u?.is_admin || !!u?.is_master;
      start(isAdmin);
    };
    window.addEventListener("restart-onboarding", onRestart as EventListener);
    return () => window.removeEventListener("restart-onboarding", onRestart as EventListener);
  }, [start]);

  const step = open ? steps[idx] : undefined;

  // 단계 이동 시 필요한 경로로 이동(투어는 셸 상주라 라우트 변경에도 유지).
  useEffect(() => {
    if (!step) return;
    if (step.route && pathname !== step.route) router.push(step.route);
    // 모바일: 사이드바 대상이면 드로어 열기 요청.
    if (step.tourId?.startsWith("sidebar-") && window.innerWidth < 768) {
      window.dispatchEvent(new CustomEvent("onboarding-open-sidebar"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, open]);

  // 대상 요소 위치 측정(강조 링). 없으면 중앙 카드.
  useLayoutEffect(() => {
    if (!step) { setRect(null); return; }
    if (!step.tourId) { setRect(null); return; }
    let tries = 0;
    let raf = 0;
    const measure = () => {
      const el = document.querySelector(`[data-tour-id="${step.tourId}"]`) as HTMLElement | null;
      if (el) {
        try { el.scrollIntoView({ block: "center", inline: "nearest" }); } catch { /* noop */ }
        setRect(el.getBoundingClientRect());
        return;
      }
      if (tries++ < 20) { raf = window.setTimeout(measure, 100) as unknown as number; }
      else setRect(null); // 못 찾으면 중앙 카드로 대체
    };
    measure();
    const onMove = () => {
      const el = document.querySelector(`[data-tour-id="${step.tourId}"]`) as HTMLElement | null;
      if (el) setRect(el.getBoundingClientRect());
    };
    window.addEventListener("resize", onMove);
    window.addEventListener("scroll", onMove, true);
    return () => {
      window.clearTimeout(raf);
      window.removeEventListener("resize", onMove);
      window.removeEventListener("scroll", onMove, true);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, open, pathname]);

  const finish = useCallback((action: "completed" | "skipped") => {
    setOpen(false);
    setRect(null);
    try { localStorage.setItem(guardKey(loginRef.current), "1"); } catch { /* noop */ }
    authApi.completeOnboarding(versionRef.current, action).catch(() => {/* 기록 실패 무시 */});
  }, []);

  if (!open || !step) return null;

  const isLast = idx === steps.length - 1;
  const pad = 6;
  const ring = rect
    ? { top: Math.max(0, rect.top - pad), left: Math.max(0, rect.left - pad), width: rect.width + pad * 2, height: rect.height + pad * 2 }
    : null;

  // 툴팁 위치: 링이 있으면 그 아래(공간 없으면 위), 없으면 화면 중앙.
  const vh = typeof window !== "undefined" ? window.innerHeight : 800;
  const belowSpace = ring ? vh - (ring.top + ring.height) : 0;
  const cardTop = ring ? (belowSpace > 200 ? ring.top + ring.height + 10 : Math.max(10, ring.top - 190)) : undefined;

  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 4000 }} data-testid="onboarding-overlay" aria-modal="true" role="dialog">
      {/* 딤 배경 (스포트라이트: 링 영역은 밝게 강조) */}
      <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.45)" }} onClick={() => { /* 배경 클릭은 닫지 않음 */ }} />
      {ring && (
        <div style={{
          position: "absolute", top: ring.top, left: ring.left, width: ring.width, height: ring.height,
          border: "3px solid var(--hw-gold-400, #E3C77A)", borderRadius: 10,
          boxShadow: "0 0 0 9999px rgba(0,0,0,0.45)", pointerEvents: "none", transition: "all 0.15s ease",
        }} data-testid="onboarding-spotlight" />
      )}
      {/* 안내 카드 */}
      <div
        data-testid="onboarding-card"
        style={{
          position: "absolute",
          top: cardTop, left: ring ? Math.min(Math.max(10, ring.left), (typeof window !== "undefined" ? window.innerWidth : 400) - 330) : "50%",
          transform: ring ? undefined : "translate(-50%, -50%)",
          ...(ring ? {} : { top: "50%" }),
          width: "min(320px, 92vw)", background: "#fff", borderRadius: 12, padding: "16px 18px",
          boxShadow: "0 12px 40px rgba(0,0,0,0.28)",
        }}
      >
        <div style={{ fontSize: 12, color: "#A0AEC0", marginBottom: 4 }}>{idx + 1} / {steps.length}</div>
        <div style={{ fontSize: 16, fontWeight: 800, color: "#1A202C", marginBottom: 6 }}>{step.title}</div>
        <div style={{ fontSize: 13.5, color: "#4A5568", lineHeight: 1.7, marginBottom: 14 }}>{step.body}</div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
          <button type="button" onClick={() => finish("skipped")} data-testid="onboarding-skip"
            style={{ background: "none", border: "none", color: "#A0AEC0", fontSize: 12, cursor: "pointer" }}>건너뛰기</button>
          <div style={{ display: "flex", gap: 8 }}>
            {idx > 0 && (
              <button type="button" onClick={() => setIdx((i) => Math.max(0, i - 1))} data-testid="onboarding-prev"
                className="btn-secondary" style={{ fontSize: 13, padding: "6px 12px" }}>이전</button>
            )}
            {!isLast ? (
              <button type="button" onClick={() => setIdx((i) => Math.min(steps.length - 1, i + 1))} data-testid="onboarding-next"
                className="btn-primary" style={{ fontSize: 13, padding: "6px 14px" }}>다음</button>
            ) : (
              <button type="button" onClick={() => finish("completed")} data-testid="onboarding-done"
                className="btn-primary" style={{ fontSize: 13, padding: "6px 14px" }}>완료</button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
