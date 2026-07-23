import { test, expect, Page, Route } from "@playwright/test";

// 최초 로그인 온보딩 투어 — (main) 인증 셸에 상주하는 OnboardingController.
// /api/auth/me 의 onboarding_required 로 자동 표시되며, 완료/건너뛰기 시 complete API 를 호출한다.
// SSR 백엔드 없이 route interception 으로 셸 endpoint 를 mock 한다.

const ME_ADMIN = {
  login_id: "admin@test", tenant_id: "t1", role: "admin", office_role: "office_admin",
  is_admin: true, is_master: false, office_name: "테스트사무소",
  onboarding_required: true, onboarding_version: 1,
  profile_complete: false, missing_profile_fields: ["agent_rrn"],
};

async function setupShell(page: Page, me: Record<string, unknown>, onComplete?: (body: unknown) => void, seedGuard = false) {
  const json = (body: unknown) => (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  // 넓은 catch-all(리스트 endpoint 는 빈 배열 허용) → 특정 endpoint 는 아래에서 override.
  await page.route("**/api/**", (route) => {
    const url = route.request().url();
    if (route.request().method() === "POST" && url.includes("/api/auth/me/onboarding/complete")) {
      onComplete?.(JSON.parse(route.request().postData() || "{}"));
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true }) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/auth/me", json(me));
  await page.route("**/api/manual/alerts/active", json({ alerts: [], is_admin: false }));
  await page.route("**/api/customers/expiry-alerts", json({ card_alerts: [], passport_alerts: [] }));
  await page.route("**/api/dashboard**", json({}));
  await page.goto("/");
  await page.evaluate((args) => {
    const { u, guard } = args as { u: Record<string, unknown>; guard: boolean };
    localStorage.setItem("access_token", "e2e-token");
    localStorage.setItem("user_info", JSON.stringify(u));
    if (guard) localStorage.setItem(`onboarding_done_${u.login_id}_v${u.onboarding_version || 1}`, "1");
    document.cookie = "kid_auth=1; path=/; SameSite=Lax";
  }, { u: me, guard: seedGuard });
  await page.goto("/dashboard");
}

test.describe("최초 로그인 온보딩 투어", () => {
  test("onboarding_required → 환영 모달 자동 표시 + 단계 진행", async ({ page }) => {
    await setupShell(page, ME_ADMIN);
    await expect(page.getByTestId("onboarding-overlay")).toBeVisible();
    await expect(page.getByTestId("onboarding-card")).toContainText("환영");
    await page.getByTestId("onboarding-next").click();
    await expect(page.getByTestId("onboarding-card")).toContainText("마이페이지");
    await page.getByTestId("onboarding-prev").click();
    await expect(page.getByTestId("onboarding-card")).toContainText("환영");
  });

  test("건너뛰기 → complete(skipped) 호출 + 오버레이 종료", async ({ page }) => {
    let body: unknown = null;
    await setupShell(page, ME_ADMIN, (b) => { body = b; });
    await expect(page.getByTestId("onboarding-overlay")).toBeVisible();
    await page.getByTestId("onboarding-skip").click();
    await expect(page.getByTestId("onboarding-overlay")).toHaveCount(0);
    await expect.poll(() => (body as { action?: string } | null)?.action).toBe("skipped");
  });

  test("과거 localStorage 가드가 있어도 서버 required=true 면 표시(서버 권위)", async ({ page }) => {
    // onboarding_done_<login>_v1=1 가 남아 있어도 서버가 required=true 면 팝업이 떠야 한다.
    await setupShell(page, ME_ADMIN, undefined, /* seedGuard */ true);
    await expect(page.getByTestId("onboarding-overlay")).toBeVisible();
    await expect(page.getByTestId("onboarding-card")).toContainText("환영");
  });

  test("onboarding_required=false → 자동 표시 안 함", async ({ page }) => {
    await setupShell(page, { ...ME_ADMIN, onboarding_required: false });
    await page.waitForTimeout(500);
    await expect(page.getByTestId("onboarding-overlay")).toHaveCount(0);
  });

  test("사용법 다시 보기 이벤트 → 재시작", async ({ page }) => {
    await setupShell(page, { ...ME_ADMIN, onboarding_required: false });
    await page.waitForTimeout(300);
    await expect(page.getByTestId("onboarding-overlay")).toHaveCount(0);
    await page.evaluate(() => window.dispatchEvent(new CustomEvent("restart-onboarding")));
    await expect(page.getByTestId("onboarding-overlay")).toBeVisible();
  });
});
