import { test, expect, Page } from "@playwright/test";

// 기본 설정(CR-1.0): q1 예 → q2 예 → q3 아니오 → 결핵 검진 대상입니다
async function openSelfCheck(page: Page) {
  await page.goto("/");
  const btn = page.getByTestId("self-check-open");
  await expect(btn).toBeVisible();
  await btn.click();
  await expect(page.getByRole("dialog")).toBeVisible();
}
async function completeToResult(page: Page) {
  await openSelfCheck(page);
  await page.getByRole("button", { name: "예", exact: true }).click();       // q1
  await page.getByRole("button", { name: "예", exact: true }).click();       // q2
  await page.getByRole("button", { name: "아니오", exact: true }).click();   // q3
  await expect(page.getByRole("heading", { name: /검진 대상입니다/ })).toBeVisible();
}

const VIEWPORTS = [
  { w: 360, h: 740 }, { w: 375, h: 812 }, { w: 390, h: 844 }, { w: 412, h: 915 },
];

test.describe("공통기준 자가점검", () => {
  test("질문 1개씩 진행 → 결과 도달", async ({ page }) => {
    await completeToResult(page);
    // 결과 화면 필수 요소
    await expect(page.getByText("내 답변")).toBeVisible();
    await expect(page.getByText("판정 경로")).toBeVisible();
    await expect(page.getByText("전체 판정 로직")).toBeVisible();
    await expect(page.getByText(/적용 로직: CR-1\.0/)).toBeVisible();
    await expect(page.getByRole("button", { name: "문자로 보내기" })).toBeVisible();
    await expect(page.getByRole("button", { name: "다시 점검" })).toBeVisible();
  });

  test("질문은 한 번에 1개만 표시", async ({ page }) => {
    await openSelfCheck(page);
    // 첫 질문만 — heading(h2) 1개
    const headings = page.getByRole("dialog").getByRole("heading");
    await expect(headings).toHaveCount(1);
  });

  for (const v of VIEWPORTS) {
    test(`결과 화면 ${v.w}×${v.h} 무스크롤 + 버튼 노출`, async ({ page }) => {
      await page.setViewportSize({ width: v.w, height: v.h });
      await completeToResult(page);
      const dialog = page.getByRole("dialog");
      // 결과 팝업 내부 세로 스크롤 없음(핵심 요건)
      const noInnerScroll = await dialog.evaluate((el) => el.scrollHeight <= el.clientHeight + 1);
      expect(noInnerScroll, `dialog inner scroll @${v.w}x${v.h}`).toBeTruthy();
      // 팝업이 뷰포트 높이를 넘지 않음
      const fitsViewport = await dialog.evaluate((el) => el.getBoundingClientRect().height <= window.innerHeight + 1);
      expect(fitsViewport, `dialog fits viewport @${v.w}x${v.h}`).toBeTruthy();
      // 모달 열린 동안 배경 스크롤 잠금
      const bgLocked = await page.evaluate(() => getComputedStyle(document.body).overflow === "hidden");
      expect(bgLocked, `background scroll locked @${v.w}x${v.h}`).toBeTruthy();
      // 하단 버튼/헤드라인 노출
      await expect(page.getByRole("heading", { name: /검진 대상입니다/ })).toBeVisible();
      await expect(page.getByRole("button", { name: "문자로 보내기" })).toBeVisible();
      await expect(page.getByRole("button", { name: "다시 점검" })).toBeVisible();
      await page.screenshot({ path: `e2e/.artifacts/result-${v.w}x${v.h}.png` });
    });
  }

  test("점검 중 사용자 답변이 네트워크로 전송되지 않음", async ({ page }) => {
    const suspicious: string[] = [];
    page.on("request", (req) => {
      const url = req.url();
      const post = (req.postData() || "");
      const hay = (url + " " + post).toLowerCase();
      // 설정 조회(GET /api/self-check/config)는 허용. 그 외 답변/결과/경로 흔적 차단.
      const isConfigGet = req.method() === "GET" && url.includes("/api/self-check/config");
      if (isConfigGet) return;
      for (const kw of ["고위험국가 국적", "90일 초과", "6개월내", "검진 대상", "판정경로", "answer", "result", "sendbeacon"]) {
        if (hay.includes(kw.toLowerCase())) suspicious.push(`${req.method()} ${url} :: ${kw}`);
      }
      // 점검 도메인으로의 POST 자체가 없어야 함
      if (req.method() !== "GET" && url.includes("self-check")) suspicious.push(`${req.method()} ${url}`);
    });
    await completeToResult(page);
    expect(suspicious, suspicious.join("\n")).toHaveLength(0);
  });

  test("답변/결과가 storage 에 저장되지 않음", async ({ page }) => {
    await completeToResult(page);
    const storage = await page.evaluate(() => ({
      local: JSON.stringify(window.localStorage),
      session: JSON.stringify(window.sessionStorage),
      cookie: document.cookie,
    }));
    const hay = (storage.local + storage.session + storage.cookie).toLowerCase();
    for (const kw of ["검진 대상", "판정", "answer", "self-check", "selfcheck", "고위험국가"]) {
      expect(hay.includes(kw.toLowerCase()), `storage contains ${kw}`).toBeFalsy();
    }
  });

  test("문자 버튼: 본문 복사(자동 전송 없음) + 수신번호 안내", async ({ page }) => {
    // 데스크톱 headless → PC 분기(문자앱 미실행, 본문 복사만). 네트워크 요청 없음.
    let anySelfCheckPost = false;
    page.on("request", (req) => {
      if (req.method() !== "GET" && req.url().includes("self-check")) anySelfCheckPost = true;
    });
    await completeToResult(page);
    await page.getByRole("button", { name: "문자로 보내기" }).click();
    // 클립보드 본문 검증(로컬 생성 — 결과·경로·버전 포함, 자동 전송 없음)
    await page.waitForTimeout(300);
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    expect(clip).toContain("[한우리 공통기준 점검]");
    expect(clip).toContain("결핵 검진 대상입니다");
    expect(clip).toContain("적용로직: CR-1.0");
    expect(clip).toContain("판정경로");
    expect(anySelfCheckPost, "자동 문자전송/서버요청 없음").toBeFalsy();
  });

  test("다시 열면 첫 질문부터 시작", async ({ page }) => {
    await completeToResult(page);
    await page.getByRole("button", { name: "닫기", exact: true }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await page.getByTestId("self-check-open").click();
    // 첫 질문 다시 표시, 결과 아님
    await expect(page.getByRole("dialog").getByText("결핵 고위험 국가 국적입니까?")).toBeVisible();
    await expect(page.getByRole("heading", { name: /검진 대상입니다/ })).toHaveCount(0);
  });
});
