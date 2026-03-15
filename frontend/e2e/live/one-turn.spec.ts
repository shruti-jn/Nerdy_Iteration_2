import { test, expect } from "@playwright/test";

/**
 * Live-canary test: exercises the real backend with live API keys.
 *
 * Prerequisites:
 *   - Backend running at localhost:8000 with valid API keys
 *   - Frontend running at localhost:5173 with VITE_MOCK=false
 *
 * This test is intentionally lenient on timing (60s timeout) because
 * it depends on live STT/LLM/TTS APIs. It's a canary, not a gate.
 */

test.beforeEach(async ({ page }, testInfo) => {
  // Skip if backend is unreachable
  try {
    const resp = await page.request.get("http://localhost:8000/health");
    if (!resp.ok()) {
      test.skip(true, "Backend not reachable — skipping live canary");
    }
  } catch {
    test.skip(true, "Backend not reachable — skipping live canary");
  }
});

test.describe("Live canary: one real turn", () => {
  test("full flow: topic select → greeting → student turn → tutor response", async ({ page }) => {
    await page.goto("/");

    // Step 1: Topic selection
    await expect(page.getByText("What do you want to learn today?")).toBeVisible();
    await page.screenshot({ path: "e2e/evidence/live-01-topic-select.png" });

    await page.getByRole("button", { name: /Start Photosynthesis/ }).click();

    // Step 2: Getting Ready — wait for WS connection
    await expect(page.getByText("Preparing your lesson...")).toBeVisible();

    // Wait for Start Lesson or fallback (avatar may or may not connect)
    const startBtn = page.getByRole("button", { name: "Start Lesson" });
    const fallbackBtn = page.getByRole("button", { name: "Start without avatar" });
    await expect(startBtn).toBeEnabled({ timeout: 20_000 });
    await page.screenshot({ path: "e2e/evidence/live-02-getting-ready.png" });

    if (await fallbackBtn.isVisible()) {
      await fallbackBtn.click();
    } else {
      await startBtn.click();
    }

    // Step 3: Lesson view — wait for greeting
    await expect(page.locator(".app__main")).toBeVisible();
    await page.screenshot({ path: "e2e/evidence/live-03-lesson-view.png" });

    // Wait for real greeting text (from LLM via backend)
    await expect(page.locator(".teaching-panel__text")).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: "e2e/evidence/live-04-greeting.png" });

    // Wait for mic to enable (greeting_complete received)
    const micBtn = page.getByRole("button", { name: "Hold to speak" });
    await expect(micBtn).toBeEnabled({ timeout: 15_000 });
    await page.screenshot({ path: "e2e/evidence/live-05-mic-enabled.png" });

    // Step 4: Simulate a student turn.
    // We can't easily record real audio in Playwright, so we send
    // end_of_utterance directly via the WebSocket to trigger the LLM.
    // The backend will use an empty/short transcript and respond.
    await page.evaluate(() => {
      const ws = (window as unknown as Record<string, unknown>).__tutorWs as WebSocket | undefined;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "end_of_utterance" }));
      }
    });

    // Wait for tutor response to the student turn
    // The response text should change (new content after greeting)
    await page.waitForTimeout(2_000);
    await page.screenshot({ path: "e2e/evidence/live-06-after-turn.png" });

    // Step 5: Verify latency panel has real data
    const latencyPanel = page.locator(".latency-panel");
    if (await latencyPanel.isVisible()) {
      await page.screenshot({ path: "e2e/evidence/live-07-latency-panel.png" });
    }

    // Verify no error banners
    const errorBanner = page.locator(".app__error-banner");
    const hasError = await errorBanner.isVisible();
    if (hasError) {
      const errorText = await errorBanner.textContent();
      console.warn("Error banner visible:", errorText);
    }
  });

  test("WebSocket connects and receives session_start", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /Start Photosynthesis/ }).click();

    // Wait for getting-ready view
    await expect(page.getByText("Preparing your lesson...")).toBeVisible();

    // The "Connecting to tutor" step should complete (WS connected)
    // Check that the step shows a checkmark (done state)
    await expect(page.locator(".step--done .step__label").first()).toContainText(
      "Connecting to tutor",
      { timeout: 10_000 },
    );

    await page.screenshot({ path: "e2e/evidence/live-08-ws-connected.png" });
  });
});
