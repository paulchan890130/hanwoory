import { test, expect, Page } from "@playwright/test";

// 계정 활성화 화면 레이아웃 — 입력칸이 카드 content box 안에 정확히 정렬되는지 bounding-box 로
// 검증한다(screenshot 만으로 통과시키지 않음). 활성화 token API 는 route mock 한다.
const CHECK_URL = "**/api/public/activation/*";
const COMPLETE_URL = "**/api/public/activation/complete";

const SHORT_EMAIL = "rep@hanbit.kr";
const LONG_EMAIL = "very.long.office.representative.email.address.for.layout@extremely-long-domain-name-example.co.kr";

async function mockReady(page: Page, loginId: string) {
  await page.route(CHECK_URL, (route) => {
    if (route.request().url().includes("/complete")) return route.fallback();
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ login_id: loginId }) });
  });
}
async function mockInvalid(page: Page) {
  await page.route(CHECK_URL, (route) => {
    if (route.request().url().includes("/complete")) return route.fallback();
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "invalid" }) });
  });
}
async function mockComplete(page: Page, status = 200) {
  await page.route(COMPLETE_URL, (route) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ ok: true }) }));
}

const VIEWPORTS = [
  { w: 320, h: 568 }, { w: 360, h: 740 }, { w: 375, h: 812 },
  { w: 390, h: 844 }, { w: 412, h: 915 }, { w: 768, h: 1024 }, { w: 1440, h: 900 },
];

// 카드 content box(패딩 안쪽) 대비 두 입력칸 경계/폭 + 문서 가로 오버플로우 측정.
async function measure(page: Page) {
  return page.evaluate(() => {
    const card = document.querySelector(".hw-card") as HTMLElement;
    const inputs = Array.from(card.querySelectorAll("input")) as HTMLElement[];
    const cs = getComputedStyle(card);
    const cr = card.getBoundingClientRect();
    const contentLeft = cr.left + parseFloat(cs.paddingLeft);
    const contentRight = cr.right - parseFloat(cs.paddingRight);
    const rects = inputs.map((i) => i.getBoundingClientRect());
    return {
      contentLeft, contentRight,
      cardOverflowX: cs.overflowX,
      inputs: rects.map((r) => ({ left: r.left, right: r.right, width: r.width })),
      docOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });
}

test.describe("계정 활성화 — ready 레이아웃(입력칸 정렬)", () => {
  for (const v of VIEWPORTS) {
    test(`${v.w}x${v.h} 두 입력칸이 카드 content box 안에 정렬`, async ({ page }) => {
      await page.setViewportSize({ width: v.w, height: v.h });
      await mockReady(page, SHORT_EMAIL);
      await page.goto("/activate/tok-abc");
      await expect(page.getByText("새 비밀번호", { exact: true })).toBeVisible();
      const m = await measure(page);
      expect(m.inputs.length).toBe(2);
      for (const inp of m.inputs) {
        expect(inp.left).toBeGreaterThanOrEqual(m.contentLeft - 0.5);   // 왼쪽 경계
        expect(inp.right).toBeLessThanOrEqual(m.contentRight + 1);       // 오른쪽 경계(카드 초과 없음)
      }
      // 두 입력칸 좌우 경계·폭 동일
      expect(Math.abs(m.inputs[0].left - m.inputs[1].left)).toBeLessThanOrEqual(0.5);
      expect(Math.abs(m.inputs[0].right - m.inputs[1].right)).toBeLessThanOrEqual(0.5);
      expect(Math.abs(m.inputs[0].width - m.inputs[1].width)).toBeLessThanOrEqual(0.5);
      // 문서 가로 스크롤 없음
      expect(m.docOverflow).toBeLessThanOrEqual(0);
      // focus ring clipping 방지 — 카드가 내용을 자르지 않음
      expect(m.cardOverflowX).not.toBe("hidden");
    });
  }

  test("긴 이메일도 카드 밖으로 넘지 않음(가로 스크롤 없음)", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 740 });
    await mockReady(page, LONG_EMAIL);
    await page.goto("/activate/tok-long");
    await expect(page.getByText("새 비밀번호", { exact: true })).toBeVisible();
    const m = await measure(page);
    for (const inp of m.inputs) expect(inp.right).toBeLessThanOrEqual(m.contentRight + 1);
    expect(m.docOverflow).toBeLessThanOrEqual(0);
    await page.screenshot({ path: "e2e/.artifacts/activation-long-email-360x740.png" });
  });

  test("비밀번호 불일치 검증 오류 표시 + 오버플로우 없음", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 740 });
    await mockReady(page, SHORT_EMAIL);
    await page.goto("/activate/tok-abc");
    const inputs = page.locator(".hw-card input");
    await inputs.nth(0).fill("abcdef");
    await inputs.nth(1).fill("zzzzzz");
    await page.getByRole("button", { name: /활성화/ }).click();
    await expect(page.getByText("비밀번호 확인이 일치하지 않습니다.")).toBeVisible();
    const m = await measure(page);
    expect(m.docOverflow).toBeLessThanOrEqual(0);
    for (const inp of m.inputs) expect(inp.right).toBeLessThanOrEqual(m.contentRight + 1);
  });

  test("invalid token 화면", async ({ page }) => {
    await mockInvalid(page);
    await page.goto("/activate/tok-bad");
    await expect(page.getByText(/유효하지 않거나 만료된/)).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("activation done 화면", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 740 });
    await mockReady(page, LONG_EMAIL);
    await mockComplete(page, 200);
    await page.goto("/activate/tok-abc");
    const inputs = page.locator(".hw-card input");
    await inputs.nth(0).fill("abcdef");
    await inputs.nth(1).fill("abcdef");
    await page.getByRole("button", { name: /활성화/ }).click();
    await expect(page.getByText(/계정이 활성화되었습니다/)).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
