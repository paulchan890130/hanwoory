import { test, expect, Page } from "@playwright/test";

import { CRIMINAL_RECORD_CONFIG, TUBERCULOSIS_CONFIG, FINGERPRINT_CONFIG } from "../lib/selfcheck/defaultConfig";
import { TUBERCULOSIS_HIGH_RISK_COUNTRIES } from "../lib/selfcheck/tuberculosis";
import type { SelfCheckConfig, SelfCheckItem } from "../lib/selfcheck/types";

// 공개 API 는 게시된 항목 번들 { schema_version, items:[...] } 를 반환한다. 런처는 items 가
// 1개 이상일 때만 표시되며, 2개 이상이면 항목 선택 화면을 먼저 보여준다. 모든 표시 테스트는
// GET /api/self-check/config 를 route interception 으로 명시 mock 한다(공개 fallback 없음).
const CONFIG_URL = "**/api/self-check/config*";

function item(id: string, config: SelfCheckConfig, over: Partial<SelfCheckItem> = {}): SelfCheckItem {
  // 기본 placement=["home"] — 홈 런처 표시 테스트가 대부분. 위치 필터 테스트는 over 로 재정의.
  return { item_id: id, title: config.item_name, sort_order: 0, is_published: true, popup_enabled: true, placement: ["home"], config, ...over };
}
function bundle(items: SelfCheckItem[]) {
  return { schema_version: 2, items };
}

// 간단 단일 항목(빠른 결과 도달) — 자가점검 기본 흐름/개인정보 테스트용.
const SIMPLE_CFG: SelfCheckConfig = {
  item_name: "테스트 점검", logic_version: "TEST-1.0", start_question_id: "q1",
  notice_text: "테스트 주의문구",
  questions: [
    { id: "q1", display_number: "①", text: "첫 번째 질문입니까?", summary: "첫질문", yes: "q2", no: "r_no", sort_order: 1 },
    { id: "q2", display_number: "②", text: "두 번째 질문입니까?", summary: "둘째질문", yes: "r_yes", no: "r_no", sort_order: 2 },
  ],
  results: [
    { id: "r_yes", headline: "제출 대상입니다", label: "대상", notice_text: "제출 안내" },
    { id: "r_no", headline: "대상 아님", label: "비대상" },
  ],
};

async function mockBundle(page: Page, body: unknown) {
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

const VIEWPORTS = [{ w: 360, h: 740 }, { w: 375, h: 812 }, { w: 390, h: 844 }, { w: 412, h: 915 }];

// 항목 config 의 최장 경로(예/아니오 시퀀스)를 클릭해 결과까지 진행.
async function clickPath(page: Page, seq: Array<"yes" | "no">) {
  for (const a of seq) {
    await page.getByRole("button", { name: a === "yes" ? "예" : "아니오", exact: true }).click();
  }
}

test.describe("공통기준 자가점검 — 단일 게시 항목", () => {
  test.beforeEach(async ({ page }) => { await mockBundle(page, bundle([item("simple", SIMPLE_CFG)])); });

  test("항목 1개 → 런처 표시 → 선택화면 없이 바로 질문", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("self-check-open")).toBeVisible();
    await page.getByTestId("self-check-open").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByText("첫 번째 질문입니까?")).toBeVisible();  // 선택화면 건너뜀
  });

  test("결과까지 진행 + 내 답변/판정경로/전체로직/버전 표시", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("self-check-open").click();
    await clickPath(page, ["yes", "yes"]);
    await expect(page.getByRole("heading", { name: /제출 대상입니다/ })).toBeVisible();
    await expect(page.getByText("내 답변")).toBeVisible();
    await expect(page.getByText("판정 경로")).toBeVisible();
    await expect(page.getByText("전체 판정 로직")).toBeVisible();
    await expect(page.getByText(/적용 로직: TEST-1\.0/)).toBeVisible();
    await expect(page.getByRole("button", { name: "문자로 보내기" })).toBeVisible();
  });

  test("점검 중 사용자 답변 네트워크 미전송", async ({ page }) => {
    const bad: string[] = [];
    page.on("request", (req) => {
      const url = req.url(); const post = req.postData() || "";
      const hay = (url + " " + post).toLowerCase();
      if (req.method() === "GET" && url.includes("/api/self-check/config")) return;
      for (const kw of ["첫질문", "둘째질문", "제출 대상", "answer", "result"]) if (hay.includes(kw.toLowerCase())) bad.push(`${req.method()} ${url}`);
      if (req.method() !== "GET" && url.includes("self-check")) bad.push(`${req.method()} ${url}`);
    });
    await page.goto("/");
    await page.getByTestId("self-check-open").click();
    await clickPath(page, ["yes", "yes"]);
    await expect(page.getByRole("heading", { name: /제출 대상입니다/ })).toBeVisible();
    expect(bad, bad.join("\n")).toHaveLength(0);
  });

  test("답변/결과 storage 미저장", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("self-check-open").click();
    await clickPath(page, ["yes", "yes"]);
    const s = await page.evaluate(() => JSON.stringify(localStorage) + JSON.stringify(sessionStorage) + document.cookie);
    for (const kw of ["제출 대상", "판정", "answer", "self-check", "첫질문"]) expect(s.toLowerCase().includes(kw.toLowerCase()), `storage has ${kw}`).toBeFalsy();
  });

  test("문자 버튼: 본문 복사, 자동 전송 없음", async ({ page }) => {
    let scPost = false;
    page.on("request", (req) => { if (req.method() !== "GET" && req.url().includes("self-check")) scPost = true; });
    await page.goto("/");
    await page.getByTestId("self-check-open").click();
    await clickPath(page, ["yes", "yes"]);
    await page.getByRole("button", { name: "문자로 보내기" }).click();
    await page.waitForTimeout(300);
    const clip = await page.evaluate(() => navigator.clipboard.readText());
    expect(clip).toContain("[한우리 공통기준 점검]");
    expect(clip).toContain("제출 대상입니다");
    expect(scPost).toBeFalsy();
  });
});

test.describe("공통기준 자가점검 — 다중 게시 항목(선택 화면)", () => {
  test.beforeEach(async ({ page }) => {
    await mockBundle(page, bundle([
      item("criminal-record", CRIMINAL_RECORD_CONFIG, { sort_order: 1 }),
      item("tuberculosis", TUBERCULOSIS_CONFIG, { sort_order: 2 }),
      item("fingerprint", FINGERPRINT_CONFIG, { sort_order: 3 }),
    ]));
  });

  test("항목 2개 이상 → 선택 화면 표시(순서대로)", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("self-check-open").click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByText("점검할 항목을 선택하세요")).toBeVisible();
    await expect(page.getByRole("button", { name: /해외범죄경력증명 필요 확인/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /결핵검진 필요 확인/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /지문등록 필요 확인/ })).toBeVisible();
  });

  test("항목 선택 → q1 진행 → 항목 변경으로 복귀", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("self-check-open").click();
    await page.getByRole("button", { name: /지문등록 필요 확인/ }).click();
    await expect(page.getByText("만 17세 이상입니까?")).toBeVisible();
    // 뒤로(항목 선택) 버튼
    await page.getByRole("button", { name: "항목 선택으로" }).click();
    await expect(page.getByText("점검할 항목을 선택하세요")).toBeVisible();
  });
});

// PDF 3개 항목 각각 최장 경로 결과 화면이 4개 모바일 viewport 에서 한 화면 완결(무클리핑).
const LONGEST: Record<string, { title: RegExp; seq: Array<"yes" | "no">; headline: RegExp }> = {
  "criminal-record": { title: /해외범죄경력증명 필요 확인/, seq: ["yes", "no", "yes", "yes"], headline: /제출 대상입니다/ },
  "tuberculosis": { title: /결핵검진 필요 확인/, seq: ["yes", "yes", "yes", "yes"], headline: /제출 대상입니다/ },
  "fingerprint": { title: /지문등록 필요 확인/, seq: ["yes", "yes"], headline: /원칙적으로 지문등록/ },
};

test.describe("결과 화면 한 화면 완결 — 4개 모바일 viewport", () => {
  test.beforeEach(async ({ page }) => {
    await mockBundle(page, bundle([
      item("criminal-record", CRIMINAL_RECORD_CONFIG, { sort_order: 1 }),
      item("tuberculosis", TUBERCULOSIS_CONFIG, { sort_order: 2 }),
      item("fingerprint", FINGERPRINT_CONFIG, { sort_order: 3 }),
    ]));
  });

  for (const [key, spec] of Object.entries(LONGEST)) {
    for (const v of VIEWPORTS) {
      test(`${key} ${v.w}x${v.h} 무스크롤 + 결과/버튼 노출`, async ({ page }) => {
        await page.setViewportSize({ width: v.w, height: v.h });
        await page.goto("/");
        await page.getByTestId("self-check-open").click();
        await page.getByRole("button", { name: spec.title }).click();
        await clickPath(page, spec.seq);
        const dialog = page.getByRole("dialog");
        await expect(page.getByRole("heading", { name: spec.headline })).toBeVisible();
        // 결과 영역 clipping 없음(내부 스크롤 없이 한 화면)
        expect(await dialog.evaluate((el) => el.scrollHeight <= el.clientHeight + 1), `inner scroll @${key} ${v.w}x${v.h}`).toBeTruthy();
        expect(await dialog.evaluate((el) => el.getBoundingClientRect().height <= window.innerHeight + 1), `fits @${key}`).toBeTruthy();

        // 직접 geometry: 결과 본문 무클리핑 + 각 섹션이 액션 버튼 위에 있음(잘림 착시 제거).
        const geo = await page.evaluate(() => {
          const q = (id: string) => document.querySelector(`[data-testid="${id}"]`) as HTMLElement | null;
          const body = q("selfcheck-result-body")!;
          const actions = q("selfcheck-actions")!;
          const at = actions.getBoundingClientRect().top;
          const bottomOf = (id: string) => { const e = q(id); return e ? e.getBoundingClientRect().bottom : -Infinity; };
          const last = q("selfcheck-full-logic-last");
          const lastRect = last?.getBoundingClientRect();
          const vis = (r?: DOMRect) => !!r && r.width > 0 && r.height > 0 && r.bottom <= window.innerHeight + 1;
          return {
            bodyClip: body.scrollHeight <= body.clientHeight + 1,
            answer: bottomOf("selfcheck-answer-list") <= at + 1,
            path: bottomOf("selfcheck-path") <= at + 1,
            logic: bottomOf("selfcheck-full-logic") <= at + 1,
            version: bottomOf("selfcheck-version") <= at + 1,
            lastLineVisible: vis(lastRect),
            versionVisible: vis(q("selfcheck-version")?.getBoundingClientRect()),
          };
        });
        expect(geo.bodyClip, `result body clipped @${key} ${v.w}x${v.h}`).toBeTruthy();
        expect(geo.answer, `answer below actions @${key}`).toBeTruthy();
        expect(geo.path, `path below actions @${key}`).toBeTruthy();
        expect(geo.logic, `logic below actions @${key}`).toBeTruthy();
        expect(geo.version, `version below actions @${key}`).toBeTruthy();
        expect(geo.lastLineVisible, `last logic line not visible @${key}`).toBeTruthy();
        expect(geo.versionVisible, `version not visible @${key}`).toBeTruthy();

        await expect(page.getByText("내 답변")).toBeVisible();
        await expect(page.getByText("판정 경로")).toBeVisible();
        await expect(page.getByText("전체 판정 로직")).toBeVisible();
        await expect(page.getByRole("button", { name: "문자로 보내기" })).toBeVisible();
        await expect(page.getByRole("button", { name: "다시 점검" })).toBeVisible();
        if (v.w === 360) await page.screenshot({ path: `e2e/.artifacts/${key}-${v.w}x${v.h}.png` });
      });
    }
  }
});

test.describe("공통기준 자가점검 — 미게시/오류 시 런처 숨김", () => {
  const CR1 = "결핵 검진 대상입니다"; // 과거 번들 기본(CR-1.0) 문구 — 공개에 절대 노출 금지

  async function assertHidden(page: Page) {
    await page.goto("/");
    await expect(page.getByTestId("self-check-open")).toHaveCount(0);
    await expect(page.getByRole("dialog")).toHaveCount(0);
    await expect(page.getByText(CR1)).toHaveCount(0);
  }

  test("빈 items → 숨김", async ({ page }) => { await mockBundle(page, bundle([])); await assertHidden(page); });
  test("게시 항목 없음(모두 draft) → 숨김", async ({ page }) => {
    await mockBundle(page, bundle([item("x", SIMPLE_CFG, { is_published: false })])); await assertHidden(page);
  });
  test("그래프 오류 항목만 → 숨김", async ({ page }) => {
    const broken = { ...SIMPLE_CFG, questions: [{ ...SIMPLE_CFG.questions[0], yes: "ghost" }] } as SelfCheckConfig;
    await mockBundle(page, bundle([item("b", broken)])); await assertHidden(page);
  });
  test("config API 404 → 숨김", async ({ page }) => { await mockStatus(page, 404); await assertHidden(page); });
  test("config API 500 → 숨김", async ({ page }) => { await mockStatus(page, 500); await assertHidden(page); });
  test("네트워크 실패 → 숨김", async ({ page }) => { await mockAbort(page); await assertHidden(page); });
});

test.describe("공통기준 자가점검 — placement 필터(런처)", () => {
  test("home 항목만 노출(other/빈 placement 제외)", async ({ page }) => {
    await mockBundle(page, bundle([
      item("home-a", CRIMINAL_RECORD_CONFIG, { placement: ["home"], sort_order: 1 }),
      item("other-b", TUBERCULOSIS_CONFIG, { placement: ["other"], sort_order: 2 }),
      item("none-c", FINGERPRINT_CONFIG, { placement: [], sort_order: 3 }),
    ]));
    await page.goto("/");
    await page.getByTestId("self-check-open").click();
    // home 항목이 1개 → 선택화면 없이 바로 진행(해외범죄 q1)
    await expect(page.getByText("만 14세 이상입니까?")).toBeVisible();
  });

  test("home 에 지정된 항목이 없으면 런처 숨김", async ({ page }) => {
    await mockBundle(page, bundle([
      item("other-b", TUBERCULOSIS_CONFIG, { placement: ["other"] }),
      item("none-c", FINGERPRINT_CONFIG, { placement: [] }),
    ]));
    await page.goto("/");
    await expect(page.getByTestId("self-check-open")).toHaveCount(0);
  });
});

test.describe("공통기준 자가점검 관리자 편집기", () => {
  const ADMIN_URL = "**/api/self-check/admin/config";
  const v2Bundle = {
    schema_version: 2,
    items: [
      { item_id: "criminal-record", title: "해외범죄경력증명 필요 확인", description: "", sort_order: 1, is_published: false, popup_enabled: true, placement: ["home"], config: CRIMINAL_RECORD_CONFIG },
      { item_id: "tuberculosis", title: "결핵검진 필요 확인", description: "", sort_order: 2, is_published: false, popup_enabled: true, placement: ["home"], config: TUBERCULOSIS_CONFIG },
    ],
  };
  const legacyContent = { ...CRIMINAL_RECORD_CONFIG, item_name: "기존 단일 설정" };

  // 공개 페이지에서 실제 origin 에 localStorage(isLoggedIn) + cookie(미들웨어)를 심은 뒤 보호 라우트로 이동.
  // adminStatus 로 관리자 GET 의 HTTP 상태를 지정(기본 200) → 503/409 fail-closed 화면 검증.
  async function authAndGoto(page: import("@playwright/test").Page, adminBody: unknown, adminStatus = 200) {
    // (main) 레이아웃이 마운트 시 호출하는 두 endpoint 를 올바른 shape 으로 mock →
    // 5xx/401 로 인한 /login 자동 리다이렉트·크래시 없이 관리 화면이 렌더된다.
    const json = (body: unknown) => (route: import("@playwright/test").Route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    // 인증 셸(레이아웃/탑바)이 마운트 시 호출하는 endpoint 를 올바른 shape 으로 mock →
    // 5xx/401 로 인한 전역 /login 리다이렉트·크래시 없이 관리 화면이 렌더된다.
    await page.route("**/api/auth/me", json({ login_id: "sys@test", is_admin: true, is_master: true }));
    await page.route("**/api/manual/alerts/active", json({ alerts: [], is_admin: true }));
    await page.route("**/api/signature/temp-slots", json([]));
    await page.route("**/api/signature/pad/events", json({ events: [] }));
    await page.route("**/api/customers/expiry-alerts", json({ card_alerts: [], passport_alerts: [] }));
    await page.route(ADMIN_URL, (route) => {
      if (route.request().method() !== "GET") return route.fallback();  // PUT(저장)은 아래 테스트별 mock 로
      return route.fulfill({ status: adminStatus, contentType: "application/json", body: JSON.stringify(adminBody) });
    });
    await page.goto("/");  // 공개 → 리다이렉트 없음, origin 확보
    await page.evaluate(() => {
      localStorage.setItem("access_token", "e2e-test-token");
      localStorage.setItem("user_info", JSON.stringify({ login_id: "sys@test", is_admin: true, is_master: true }));
      document.cookie = "kid_auth=1; path=/; SameSite=Lax";
    });
    await page.goto("/marketing/self-check");
  }

  test("4개 viewport 선택 + description·placement 편집 노출", async ({ page }) => {
    await authAndGoto(page, v2Bundle);
    // 편집기 렌더(선택 항목 편집 섹션)
    await expect(page.getByTestId("item-description")).toBeVisible();
    await expect(page.getByTestId("placement-home")).toBeVisible();
    // viewport 4종 버튼
    for (const w of [360, 375, 390, 412]) await expect(page.getByTestId(`preview-vp-${w}`)).toBeVisible();
    // description 편집 반영
    await page.getByTestId("item-description").fill("설명 편집 테스트");
    await expect(page.getByTestId("item-description")).toHaveValue("설명 편집 테스트");
    // placement 토글
    const home = page.getByTestId("placement-home");
    await home.uncheck(); await expect(home).not.toBeChecked();
    await home.check(); await expect(home).toBeChecked();
    // 412 viewport 선택 → 미리보기 열기 시 가로 스크롤 없음
    await page.getByTestId("preview-vp-412").click();
    await page.getByRole("button", { name: "미리보기", exact: true }).click();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("legacy 단일 설정 → 안내 배너 표시", async ({ page }) => {
    await authAndGoto(page, legacyContent);
    await expect(page.getByTestId("selfcheck-legacy-banner")).toBeVisible();
    // 배너 안내 + '불러오기' 버튼이 함께 존재(둘 다 같은 문구 → 버튼 role 로 특정).
    await expect(page.getByRole("button", { name: "PDF 기준 3개 기본 항목 불러오기" })).toBeVisible();
  });

  test("결핵 항목 선택 → 공식 35/35 + 출처 metadata 표시", async ({ page }) => {
    await authAndGoto(page, v2Bundle);
    await page.getByText("결핵검진 필요 확인").first().click();  // 항목 목록에서 TB 선택
    await expect(page.getByTestId("tb-status")).toBeVisible();
    await expect(page.getByTestId("tb-status-count")).toContainText("35/35");
    await expect(page.getByTestId("tb-status-match")).toContainText("예");
    await expect(page.getByTestId("tb-status-source")).toContainText("완료");
    // source metadata 편집칸 노출 + 값 존재
    await expect(page.getByTestId("tb-source-title")).toBeVisible();
    await expect(page.getByTestId("tb-source-title")).not.toHaveValue("");
  });

  test("결핵 국가 목록 부족 → 공개 체크 차단(원상복구)", async ({ page }) => {
    const shortTb: SelfCheckConfig = { ...TUBERCULOSIS_CONFIG, country_list: TUBERCULOSIS_HIGH_RISK_COUNTRIES.slice(0, 17) };
    const body = {
      schema_version: 2,
      items: [{ item_id: "tuberculosis", title: "결핵검진 필요 확인", description: "", sort_order: 1, is_published: false, popup_enabled: true, placement: ["home"], config: shortTb }],
    };
    await authAndGoto(page, body);
    const cb = page.getByTestId("publish-tuberculosis");
    await expect(cb).not.toBeChecked();
    await cb.click();  // 공개 시도 → 검증 미통과 → 안내 후 원상복구
    await expect(page.getByText("결핵 항목은 공식 35개국 목록과 출처 확인이 완료된 경우에만 공개할 수 있습니다.")).toBeVisible();
    await expect(cb).not.toBeChecked();
  });

  test("결핵 35개국 완비 → 공개 체크 허용", async ({ page }) => {
    const body = {
      schema_version: 2,
      items: [{ item_id: "tuberculosis", title: "결핵검진 필요 확인", description: "", sort_order: 1, is_published: false, popup_enabled: true, placement: ["home"], config: TUBERCULOSIS_CONFIG }],
    };
    await authAndGoto(page, body);
    const cb = page.getByTestId("publish-tuberculosis");
    await cb.click();
    await expect(cb).toBeChecked();
  });

  test("obsolete legacy → 경고 배너 + 공개 안내", async ({ page }) => {
    const body = { schema_version: 2, items: [{ item_id: "legacy", title: "기존 설정", description: null, sort_order: 0, is_published: true, popup_enabled: true, placement: ["home"], config: legacyContent }], obsolete_legacy: true };
    await authAndGoto(page, body);
    await expect(page.getByTestId("selfcheck-obsolete-banner")).toBeVisible();
    await expect(page.getByTestId("selfcheck-obsolete-banner")).toContainText("폐기 대상");
    // obsolete 일 때는 일반 legacy 배너를 대신 표시하지 않는다.
    await expect(page.getByTestId("selfcheck-legacy-banner")).toHaveCount(0);
  });

  // ── PART D/E: 관리자 조회 fail-closed + 빈 bundle 보존 + obsolete 갱신 ──────────
  test("관리자 GET 503 → unavailable(편집기·저장·기본안 없음)", async ({ page }) => {
    await authAndGoto(page, { detail: { code: "SELF_CHECK_CONFIG_UNAVAILABLE", message: "x" } }, 503);
    await expect(page.getByTestId("selfcheck-unavailable")).toBeVisible();
    await expect(page.getByTestId("selfcheck-retry")).toBeVisible();
    await expect(page.getByRole("button", { name: "저장(공개 상태 반영)" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "PDF 기준 3개 기본 항목 불러오기" })).toHaveCount(0);
    await expect(page.getByText("해외범죄경력증명 필요 확인")).toHaveCount(0);  // 기본안 자동 표시 없음
  });

  test("관리자 GET 409 corrupt → 편집 차단(저장·기본안 없음)", async ({ page }) => {
    await authAndGoto(page, { detail: { code: "SELF_CHECK_CONFIG_CORRUPT", message: "x", errors: ["JSON 파싱 실패"] } }, 409);
    await expect(page.getByTestId("selfcheck-corrupt")).toBeVisible();
    await expect(page.getByRole("button", { name: "저장(공개 상태 반영)" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "PDF 기준 3개 기본 항목 불러오기" })).toHaveCount(0);
  });

  test("관리자 GET 빈 bundle → 항목 0개(기본안 자동생성 없음, 불러오기 버튼 노출)", async ({ page }) => {
    await authAndGoto(page, { schema_version: 2, items: [], config_state: "absent", obsolete_legacy: false });
    // 편집기는 렌더되지만 항목은 0개, 기본 3항목이 자동 생성되지 않음
    await expect(page.getByRole("button", { name: "PDF 기준 3개 기본 항목 불러오기" })).toBeVisible();
    await expect(page.getByTestId("publish-criminal-record")).toHaveCount(0);
    await expect(page.getByTestId("publish-tuberculosis")).toHaveCount(0);
    await expect(page.getByText("항목이 없습니다.", { exact: false })).toBeVisible();
  });

  test("기본안 불러오기: 클릭만으로 PUT 0회 · 저장 후 PUT 1회", async ({ page }) => {
    let puts = 0;
    await authAndGoto(page, { schema_version: 2, items: [], config_state: "absent", obsolete_legacy: false });
    // 저장 PUT 카운트(GET 은 authAndGoto 로 fallback)
    await page.route(ADMIN_URL, (route) => {
      if (route.request().method() === "PUT") { puts += 1; return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, published_items: [], item_errors: {}, tb_warnings: {} }) }); }
      return route.fallback();
    });
    page.on("dialog", (d) => d.accept());  // loadDefaults 의 window.confirm 수락
    await page.getByRole("button", { name: "PDF 기준 3개 기본 항목 불러오기" }).click();
    // 3개 항목 로드 + 전부 비공개
    await expect(page.getByTestId("publish-criminal-record")).not.toBeChecked();
    await expect(page.getByTestId("publish-tuberculosis")).not.toBeChecked();
    await expect(page.getByTestId("publish-fingerprint")).not.toBeChecked();
    await page.waitForTimeout(200);
    expect(puts, "불러오기만으로 PUT 발생").toBe(0);
    // 저장 → PUT 1회
    await page.getByRole("button", { name: "저장(공개 상태 반영)" }).click();
    await expect.poll(() => puts).toBe(1);
  });

  test("obsolete legacy → 불러오기 미저장 안내 → 저장 후 경고 제거", async ({ page }) => {
    const body = { schema_version: 2, items: [{ item_id: "legacy", title: "기존 설정", description: null, sort_order: 0, is_published: true, popup_enabled: true, placement: ["home"], config: legacyContent }], obsolete_legacy: true };
    await authAndGoto(page, body);
    await page.route(ADMIN_URL, (route) => {
      if (route.request().method() === "PUT") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ok: true, published_items: [], item_errors: {}, tb_warnings: {} }) });
      return route.fallback();
    });
    page.on("dialog", (d) => d.accept());
    await expect(page.getByTestId("selfcheck-obsolete-banner")).toBeVisible();
    await page.getByRole("button", { name: "PDF 기준 3개 기본 항목 불러오기" }).click();
    await expect(page.getByTestId("selfcheck-obsolete-unsaved")).toBeVisible();  // 미저장 안내
    await page.getByRole("button", { name: "저장(공개 상태 반영)" }).click();
    await expect(page.getByTestId("selfcheck-obsolete-banner")).toHaveCount(0);  // 저장 후 경고 제거
  });

  test("정상 v2 → 기존 항목 그대로 표시(자동 대체 없음)", async ({ page }) => {
    await authAndGoto(page, { ...v2Bundle, config_state: "valid", obsolete_legacy: false });
    await expect(page.getByTestId("publish-criminal-record")).toBeVisible();
    await expect(page.getByTestId("publish-tuberculosis")).toBeVisible();
    await expect(page.getByTestId("publish-fingerprint")).toHaveCount(0);  // 원본에 없던 항목 자동추가 없음
  });
});
