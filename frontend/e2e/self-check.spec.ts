import { test, expect, Page } from "@playwright/test";

// 공개 런처는 "게시된 유효 설정"이 있을 때만 표시된다. 공개 DEFAULT fallback 은 제거됐으므로
// 모든 표시 테스트는 GET /api/self-check/config 를 route interception 으로 명시 mock 한다.
const CONFIG_URL = "**/api/self-check/config*";

const TEST_CONFIG = {
  item_name: "테스트 점검",
  logic_version: "TEST-1.0",
  start_question_id: "q1",
  notice_text: "테스트 주의문구",
  country_list_title: "고위험 국가",
  country_list: ["가나다국", "라마바국"],
  questions: [
    { id: "q1", display_number: "①", text: "첫 번째 질문입니까?", summary: "첫질문", country_list_ref: true, yes: "q2", no: "r_no" },
    { id: "q2", display_number: "②", text: "두 번째 질문입니까?", summary: "둘째질문", yes: "r_yes", no: "r_no" },
  ],
  results: [
    { id: "r_yes", headline: "제출 대상입니다", label: "대상", notice_text: "제출 안내" },
    { id: "r_no", headline: "대상 아님", label: "비대상" },
  ],
};
const INVALID_CONFIG = { ...TEST_CONFIG, start_question_id: "nonexistent" }; // 검증 errors 발생

async function mockConfig(page: Page, body: unknown) {
  await page.route(CONFIG_URL, (route) => route.fulfill({
    status: 200, contentType: "application/json", body: JSON.stringify(body),
    headers: { "Cache-Control": "no-store" },
  }));
}
async function mockStatus(page: Page, status: number) {
  await page.route(CONFIG_URL, (route) => route.fulfill({ status, contentType: "application/json", body: "{}" }));
}
async function mockAbort(page: Page) {
  await page.route(CONFIG_URL, (route) => route.abort());
}

async function completeToResult(page: Page) {
  await page.goto("/");
  const btn = page.getByTestId("self-check-open");
  await expect(btn).toBeVisible();
  await btn.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "예", exact: true }).click();   // q1
  await page.getByRole("button", { name: "예", exact: true }).click();   // q2
  await expect(page.getByRole("heading", { name: /제출 대상입니다/ })).toBeVisible();
}

const VIEWPORTS = [{ w: 360, h: 740 }, { w: 375, h: 812 }, { w: 390, h: 844 }, { w: 412, h: 915 }];

test.describe("공통기준 자가점검 — 게시된 설정", () => {
  test.beforeEach(async ({ page }) => { await mockConfig(page, { published: true, config: TEST_CONFIG }); });

  test("게시 설정 → 런처 표시·진행·결과", async ({ page }) => {
    await completeToResult(page);
    await expect(page.getByText("내 답변")).toBeVisible();
    await expect(page.getByText("판정 경로")).toBeVisible();
    await expect(page.getByText("전체 판정 로직")).toBeVisible();
    await expect(page.getByText(/적용 로직: TEST-1\.0/)).toBeVisible();
    await expect(page.getByRole("button", { name: "문자로 보내기" })).toBeVisible();
  });

  test("질문은 한 번에 1개만", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("self-check-open").click();
    await expect(page.getByRole("dialog").getByRole("heading")).toHaveCount(1);
  });

  for (const v of VIEWPORTS) {
    test(`결과 ${v.w}×${v.h} 무스크롤 + 버튼 노출`, async ({ page }) => {
      await page.setViewportSize({ width: v.w, height: v.h });
      await completeToResult(page);
      const dialog = page.getByRole("dialog");
      expect(await dialog.evaluate((el) => el.scrollHeight <= el.clientHeight + 1), `inner scroll @${v.w}x${v.h}`).toBeTruthy();
      expect(await dialog.evaluate((el) => el.getBoundingClientRect().height <= window.innerHeight + 1), `fits @${v.w}x${v.h}`).toBeTruthy();
      expect(await page.evaluate(() => getComputedStyle(document.body).overflow === "hidden"), `bg lock @${v.w}x${v.h}`).toBeTruthy();
      await expect(page.getByRole("heading", { name: /제출 대상입니다/ })).toBeVisible();
      await expect(page.getByRole("button", { name: "문자로 보내기" })).toBeVisible();
      await expect(page.getByRole("button", { name: "다시 점검" })).toBeVisible();
      await page.screenshot({ path: `e2e/.artifacts/result-${v.w}x${v.h}.png` });
    });
  }

  test("점검 중 사용자 답변 네트워크 미전송", async ({ page }) => {
    const bad: string[] = [];
    page.on("request", (req) => {
      const url = req.url(); const post = req.postData() || "";
      const hay = (url + " " + post).toLowerCase();
      if (req.method() === "GET" && url.includes("/api/self-check/config")) return;
      for (const kw of ["첫질문", "둘째질문", "제출 대상", "판정경로", "answer", "result"]) if (hay.includes(kw.toLowerCase())) bad.push(`${req.method()} ${url} :: ${kw}`);
      if (req.method() !== "GET" && url.includes("self-check")) bad.push(`${req.method()} ${url}`);
    });
    await completeToResult(page);
    expect(bad, bad.join("\n")).toHaveLength(0);
  });

  test("답변/결과 storage 미저장", async ({ page }) => {
    await completeToResult(page);
    const s = await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage) + document.cookie);
    for (const kw of ["제출 대상", "판정", "answer", "self-check", "첫질문"]) expect(s.toLowerCase().includes(kw.toLowerCase()), `storage has ${kw}`).toBeFalsy();
  });

  test("문자 버튼: 본문 복사, 자동 전송 없음", async ({ page }) => {
    let scPost = false;
    page.on("request", (req) => { if (req.method() !== "GET" && req.url().includes("self-check")) scPost = true; });
    await completeToResult(page);
    await page.getByRole("button", { name: "문자로 보내기" }).click();
    await page.waitForTimeout(300);
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    expect(clip).toContain("[한우리 공통기준 점검]");
    expect(clip).toContain("제출 대상입니다");
    expect(clip).toContain("적용로직: TEST-1.0");
    expect(scPost).toBeFalsy();
  });

  test("다시 열면 첫 질문부터", async ({ page }) => {
    await completeToResult(page);
    await page.getByRole("button", { name: "닫기", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.getByTestId("self-check-open").click();
    await expect(page.getByRole("dialog").getByText("첫 번째 질문입니까?")).toBeVisible();
    await expect(page.getByRole("heading", { name: /제출 대상입니다/ })).toHaveCount(0);
  });
});

test.describe("공통기준 자가점검 — 비공개/오류 시 런처 숨김", () => {
  const CR1 = "결핵 검진 대상입니다"; // DEFAULT_SELF_CHECK_CONFIG(CR-1.0) 기본문구 — 공개에 절대 노출 금지

  async function assertHidden(page: Page) {
    await page.goto("/");
    await expect(page.getByTestId("self-check-open")).toHaveCount(0);   // 런처 없음
    await expect(page.getByRole("dialog")).toHaveCount(0);
    // 번들 기본(CR-1.0) 문구/버전이 DOM 에 없어야 함
    await expect(page.getByText(CR1)).toHaveCount(0);
    await expect(page.getByText(/CR-1\.0/)).toHaveCount(0);
  }

  test("published=false → 숨김, DEFAULT 미노출", async ({ page }) => {
    await mockConfig(page, { published: false, config: null });
    await assertHidden(page);
  });
  test("published=true + config=null → 숨김", async ({ page }) => {
    await mockConfig(page, { published: true, config: null });
    await assertHidden(page);
  });
  test("published=true + 잘못된 config → 숨김", async ({ page }) => {
    await mockConfig(page, { published: true, config: INVALID_CONFIG });
    await assertHidden(page);
  });
  test("config API 404 → 숨김", async ({ page }) => { await mockStatus(page, 404); await assertHidden(page); });
  test("config API 500 → 숨김", async ({ page }) => { await mockStatus(page, 500); await assertHidden(page); });
  test("네트워크 실패 → 숨김", async ({ page }) => { await mockAbort(page); await assertHidden(page); });
});
