import { defineConfig, devices } from "@playwright/test";

// 공통기준 자가점검 E2E — 개발·CI 전용. 운영 이미지에 브라우저 바이너리를 포함하지 않는다
// (Dockerfile 은 `npm install` 만 하고 `playwright install` 을 호출하지 않는다).
// 백엔드 없이 `next start` 만으로 동작(자가점검은 설정 GET 실패 시 번들 기본값으로 fallback).
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "e2e/.report" }]],
  use: {
    baseURL: "http://localhost:3111",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    permissions: ["clipboard-read", "clipboard-write"],
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npx next start -p 3111",
    url: "http://localhost:3111",
    timeout: 120_000,
    reuseExistingServer: true,
    env: { API_URL: "http://127.0.0.1:59999" }, // 도달 불가 → 설정 GET 실패 → 기본 설정 fallback
  },
});
