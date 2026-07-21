import { test, expect, Page } from "@playwright/test";

// 승인형 SaaS 가용성 게이트 — /apply · /login 가입탭 · 홈 CTA 를 API mock 으로 검증한다.
// 실제 백엔드 없이 route interception 으로 GET /api/public/availability 를 명시 mock.
const AVAIL_URL = "**/api/public/availability*";
const SELFCHECK_URL = "**/api/self-check/config*";

async function mockAvail(page: Page, enabled: boolean) {
  await page.route(AVAIL_URL, (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({ enabled }),
  }));
}
async function abortAvail(page: Page) {
  await page.route(AVAIL_URL, (route) => route.abort());
}
// 홈 로드 시 자가점검 런처가 끼어들지 않도록 비공개로 고정.
async function hideSelfCheck(page: Page) {
  await page.route(SELFCHECK_URL, (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({ published: false, config: null }),
  }));
}

// ── /apply 4-state ────────────────────────────────────────────────────────────
test.describe("/apply 가용성 4-state", () => {
  test("enabled → 신청 폼 노출", async ({ page }) => {
    await mockAvail(page, true);
    await page.goto("/apply");
    await expect(page.getByRole("heading", { name: "사무소 이용 신청" })).toBeVisible();
    await expect(page.getByRole("button", { name: "이용 신청 제출" })).toBeVisible();
  });

  test("disabled → 마감 안내, 폼 없음", async ({ page }) => {
    await mockAvail(page, false);
    await page.goto("/apply");
    await expect(page.getByRole("heading", { name: /신규 신청을 받지 않습니다/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "이용 신청 제출" })).toHaveCount(0);
  });

  test("확인 실패 → 재시도 안내, 폼 없음(fail-closed)", async ({ page }) => {
    await abortAvail(page);
    await page.goto("/apply");
    await expect(page.getByRole("heading", { name: /확인할 수 없습니다/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "다시 시도" })).toBeVisible();
    await expect(page.getByRole("button", { name: "이용 신청 제출" })).toHaveCount(0);
  });
});

// ── /login 가입탭 4-state (fail-closed) ────────────────────────────────────────
test.describe("/login 가입탭 가용성", () => {
  test("enabled → 이용신청 CTA, 레거시 가입폼 없음", async ({ page }) => {
    await mockAvail(page, true);
    await page.goto("/login");
    await page.getByRole("button", { name: "가입신청" }).click();
    await expect(page.getByRole("link", { name: "사무소 이용신청 하러 가기" })).toBeVisible();
    await expect(page.getByText("대행기관명 *")).toHaveCount(0);
  });

  test("disabled(SaaS OFF) → 레거시 가입폼 노출", async ({ page }) => {
    await mockAvail(page, false);
    await page.goto("/login");
    await page.getByRole("button", { name: "가입신청" }).click();
    await expect(page.getByText("대행기관명 *")).toBeVisible();
  });

  test("확인 실패 → 레거시 가입폼 절대 미노출(fail-closed)", async ({ page }) => {
    await abortAvail(page);
    await page.goto("/login");
    await page.getByRole("button", { name: "가입신청" }).click();
    await expect(page.getByText(/가입 가능 여부를 확인하지 못했습니다/)).toBeVisible();
    await expect(page.getByText("대행기관명 *")).toHaveCount(0);
  });
});

// ── 홈 CTA ─────────────────────────────────────────────────────────────────────
test.describe("홈 '사무소 이용신청' CTA", () => {
  test("enabled → 데스크톱 nav 에 CTA", async ({ page }) => {
    await hideSelfCheck(page);
    await mockAvail(page, true);
    await page.goto("/");
    await expect(page.getByRole("link", { name: "사무소 이용신청" }).first()).toBeVisible();
  });

  test("disabled → CTA 없음", async ({ page }) => {
    await hideSelfCheck(page);
    await mockAvail(page, false);
    await page.goto("/");
    await expect(page.getByRole("link", { name: "사무소 이용신청" })).toHaveCount(0);
  });
});
