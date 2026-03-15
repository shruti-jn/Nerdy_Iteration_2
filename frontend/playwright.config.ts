import { defineConfig, devices } from "@playwright/test";

const E2E_PORT = 5174;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 1,
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://localhost:${E2E_PORT}`,
    screenshot: "on",
    video: "retain-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "deterministic",
      testDir: "./e2e/deterministic",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "live-canary",
      testDir: "./e2e/live",
      timeout: 60_000,
      use: {
        ...devices["Desktop Chrome"],
        baseURL: "http://localhost:5173",
      },
    },
  ],
  webServer: {
    command: `npx vite --port ${E2E_PORT} --mode test`,
    port: E2E_PORT,
    reuseExistingServer: false,
    timeout: 15_000,
  },
});
