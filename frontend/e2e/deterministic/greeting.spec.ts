import { test, expect } from "@playwright/test";

/**
 * Navigate through topic select → getting ready → start lesson.
 * Shared setup for greeting tests.
 */
async function enterLesson(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByRole("button", { name: /Start Photosynthesis/ }).click();

  const startBtn = page.getByRole("button", { name: "Start Lesson" });
  const fallbackBtn = page.getByRole("button", { name: "Start without avatar" });
  await expect(startBtn).toBeEnabled({ timeout: 15_000 });

  if (await fallbackBtn.isVisible()) {
    await fallbackBtn.click();
  } else {
    await startBtn.click();
  }

  await expect(page.locator(".app__main")).toBeVisible();
}

test.describe("Greeting flow", () => {
  test("greeting text appears in teaching panel after starting lesson", async ({ page }) => {
    await enterLesson(page);

    // Mock greeting fires after ~800ms: "Hey there! Plants make their own food..."
    await expect(
      page.locator(".teaching-panel__text"),
    ).toContainText("Hey there", { timeout: 5_000 });

    await page.screenshot({ path: "e2e/evidence/greeting-01-text-visible.png" });
  });

  test("visual panel appears with concept diagram during greeting", async ({ page }) => {
    await enterLesson(page);

    // Mock emits a visual update alongside the greeting
    await expect(
      page.locator(".concept-canvas__diagram"),
    ).toBeVisible({ timeout: 5_000 });

    // Step progress bar should be visible
    await expect(page.locator(".step-progress")).toBeVisible();
    await expect(page.locator(".step-progress__label")).toHaveText("Introduction");

    await page.screenshot({ path: "e2e/evidence/greeting-05-visual-panel.png" });
  });

  test("mic button is disabled during greeting", async ({ page }) => {
    await enterLesson(page);

    // During greeting, the mic button should be disabled (mode = tutor-greeting)
    const micBtn = page.getByRole("button", { name: /Hold to speak|Stop recording/ });
    await expect(micBtn).toBeDisabled();

    // The hint text should indicate the tutor is speaking
    await expect(page.locator(".mic-btn__hint")).toContainText(
      /introducing the topic|Tutor speaking/,
    );

    await page.screenshot({ path: "e2e/evidence/greeting-02-mic-disabled.png" });
  });

  test("mic button enables after greeting completes", async ({ page }) => {
    await enterLesson(page);

    // Wait for greeting text to appear first
    await expect(
      page.locator(".teaching-panel__text"),
    ).toContainText("Hey there", { timeout: 5_000 });

    // After greeting completes (~1.5s total in mock), mode returns to idle.
    // The mock sets mode to idle 100ms after commitTutorResponse (400ms after words).
    // Wait for the mic button to become enabled.
    const micBtn = page.getByRole("button", { name: "Hold to speak" });
    await expect(micBtn).toBeEnabled({ timeout: 5_000 });

    // Hint should say "Hold to speak"
    await expect(page.locator(".mic-btn__hint")).toHaveText("Hold to speak");

    await page.screenshot({ path: "e2e/evidence/greeting-03-mic-enabled.png" });
  });

  test("greeting appears in conversation history", async ({ page }) => {
    await enterLesson(page);

    // Wait for greeting to complete and be committed to history
    const micBtn = page.getByRole("button", { name: "Hold to speak" });
    await expect(micBtn).toBeEnabled({ timeout: 5_000 });

    // Conversation history should contain the greeting
    await expect(
      page.locator(".conv-history").getByText(/Hey there/),
    ).toBeVisible();

    await page.screenshot({ path: "e2e/evidence/greeting-04-in-history.png" });
  });
});
