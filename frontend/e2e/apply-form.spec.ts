import { test, expect, Page } from "@playwright/test";

// 신청서 단순화 — 대표자/실무자 필드, 사업자번호·전화 자동 형식화, 담당자/이용목적 제거,
// 두 이메일 동일 차단, 사업자번호 10자리 미만 차단. availability mock 으로 폼을 노출한다.
const AVAIL_URL = "**/api/public/availability*";
async function mockAvail(page: Page, enabled: boolean) {
  await page.route(AVAIL_URL, (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify({ enabled }),
  }));
}

test.describe("사무소 이용 신청서", () => {
  test.beforeEach(async ({ page }) => {
    await mockAvail(page, true);
    await page.goto("/apply");
    await expect(page.getByRole("heading", { name: "사무소 이용 신청" })).toBeVisible();
  });

  test("대표자·실무자 필드 표시, 신청 담당자/이용 목적 제거", async ({ page }) => {
    await expect(page.getByText("대표자 이메일")).toBeVisible();
    await expect(page.getByText("승인 후 사무소 관리자 계정으로 발급됩니다.")).toBeVisible();
    await expect(page.getByText("실무자용 계정 발급 정보")).toBeVisible();
    await expect(page.getByText("승인 후 직원용 서브계정으로 발급됩니다.")).toBeVisible();
    await expect(page.getByText("신청 담당자")).toHaveCount(0);
    await expect(page.getByText("이용 목적")).toHaveCount(0);
    await expect(page.getByText("계정 사용자 1")).toHaveCount(0);
  });

  test("사업자등록번호 숫자 입력 → 하이픈 자동 형식", async ({ page }) => {
    const biz = page.locator('input[inputmode="numeric"]').first();
    await biz.fill("2131237464");
    await expect(biz).toHaveValue("213-12-37464");
    // 하이픈 포함 붙여넣기도 동일 결과.
    await biz.fill("");
    await biz.fill("213-12-37464");
    await expect(biz).toHaveValue("213-12-37464");
  });

  test("전화번호 숫자 입력 → 하이픈 자동 형식", async ({ page }) => {
    const phone = page.locator('input[inputmode="tel"]').first();
    await phone.fill("01094339280");
    await expect(phone).toHaveValue("010-9433-9280");
    await phone.fill("");
    await phone.fill("021234567");
    await expect(phone).toHaveValue("02-123-4567");
  });

  // 입력칸 순서(모두 input.hw-input): 0 사무소명 · 1 대표자명 · 2 대표자이메일 ·
  // 3 사업자번호 · 4 주소 · 5 대표전화 · 6 실무자이름 · 7 실무자이메일.
  async function fillForm(page: Page, { biz, repEmail, staffEmail }: { biz: string; repEmail: string; staffEmail: string }) {
    const i = page.locator("input.hw-input");
    await i.nth(0).fill("테스트사무소");
    await i.nth(1).fill("대표자");
    await i.nth(2).fill(repEmail);
    await i.nth(3).fill(biz);
    await i.nth(6).fill("실무자");
    await i.nth(7).fill(staffEmail);
    await page.getByRole("checkbox").nth(0).check();
    await page.getByRole("checkbox").nth(1).check();
  }

  test("두 이메일 동일 시 제출 차단", async ({ page }) => {
    await fillForm(page, { biz: "2131237464", repEmail: "same@x.kr", staffEmail: "same@x.kr" });
    await page.getByRole("button", { name: "이용 신청 제출" }).click();
    await expect(page.getByText("대표자와 실무자의 이메일은 서로 달라야 합니다.")).toBeVisible();
  });

  test("사업자번호 10자리 미만 제출 차단", async ({ page }) => {
    await fillForm(page, { biz: "21312", repEmail: "rep@x.kr", staffEmail: "staff@x.kr" });
    await page.getByRole("button", { name: "이용 신청 제출" }).click();
    await expect(page.getByText("사업자등록번호 10자리를 입력해 주세요.")).toBeVisible();
  });
});
