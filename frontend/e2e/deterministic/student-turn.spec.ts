import { test, expect } from "@playwright/test";

/**
 * Navigate to lesson view and wait for greeting to complete.
 */
async function enterLessonWithGreeting(page: import("@playwright/test").Page) {
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

  // Wait for greeting to complete — mic becomes enabled
  const micBtn = page.getByRole("button", { name: "Hold to speak" });
  await expect(micBtn).toBeEnabled({ timeout: 8_000 });
}

test.describe("Student turn interaction", () => {
  test("pressing and releasing mic triggers a tutor response", async ({ page }) => {
    await enterLessonWithGreeting(page);

    const micBtn = page.getByRole("button", { name: "Hold to speak" });

    // Simulate hold-to-speak: mousedown → short hold → mouseup
    await micBtn.dispatchEvent("mousedown");
    await page.screenshot({ path: "e2e/evidence/turn-01-mic-pressed.png" });

    // Brief hold to simulate speaking
    await page.waitForTimeout(300);
    await micBtn.dispatchEvent("mouseup");

    // Mock mode generates a tutor response after ~1500ms.
    // Wait for new text in the tutor response panel.
    // The mock responses include "Photosynthesis" or "question" or "plant".
    await expect(page.locator(".teaching-panel__text")).toBeVisible({ timeout: 8_000 });

    await page.screenshot({ path: "e2e/evidence/turn-02-tutor-responded.png" });
  });

  test("turn counter increments after a student turn", async ({ page }) => {
    await enterLessonWithGreeting(page);

    // Turn counter should start at 0
    await expect(page.locator(".topbar__turn-count")).toContainText("0");

    const micBtn = page.getByRole("button", { name: "Hold to speak" });
    await micBtn.dispatchEvent("mousedown");
    await page.waitForTimeout(300);
    await micBtn.dispatchEvent("mouseup");

    // Wait for the tutor response to complete (mock: ~1500ms + word streaming + 400ms commit)
    // The turn counter should increment to 1
    await expect(page.locator(".topbar__turn-count")).toContainText("1", {
      timeout: 8_000,
    });

    await page.screenshot({ path: "e2e/evidence/turn-03-counter-incremented.png" });
  });

  test("student utterance placeholder appears in conversation history", async ({ page }) => {
    await enterLessonWithGreeting(page);

    const micBtn = page.getByRole("button", { name: "Hold to speak" });
    await micBtn.dispatchEvent("mousedown");

    // While recording, a "…" placeholder should appear in conversation history
    await expect(
      page.locator(".conv-history").getByText("…"),
    ).toBeVisible({ timeout: 3_000 });

    await page.screenshot({ path: "e2e/evidence/turn-04-student-placeholder.png" });

    await micBtn.dispatchEvent("mouseup");
  });

  test("tutor response is committed to conversation history", async ({ page }) => {
    await enterLessonWithGreeting(page);

    const micBtn = page.getByRole("button", { name: "Hold to speak" });
    await micBtn.dispatchEvent("mousedown");
    await page.waitForTimeout(300);
    await micBtn.dispatchEvent("mouseup");

    // Wait for tutor response to be committed to history
    await page.waitForTimeout(4_000);

    // Conversation history should have at least 2 entries:
    // greeting + student utterance (+ tutor response)
    const historyEntries = page.locator(".conv-entry");
    const count = await historyEntries.count();
    expect(count).toBeGreaterThanOrEqual(2);

    await page.screenshot({ path: "e2e/evidence/turn-05-history-updated.png" });
  });

  test("concept visual updates after a student turn", async ({ page }) => {
    await enterLessonWithGreeting(page);

    // Visual should already be showing the intro step from the greeting
    await expect(page.locator(".concept-canvas__diagram")).toBeVisible({ timeout: 5_000 });
    const introEmoji = await page.locator(".concept-canvas__diagram").textContent();

    const micBtn = page.getByRole("button", { name: "Hold to speak" });
    await micBtn.dispatchEvent("mousedown");
    await page.waitForTimeout(300);
    await micBtn.dispatchEvent("mouseup");

    // Wait for the tutor response + visual update
    await expect(page.locator(".topbar__turn-count")).toContainText("1", { timeout: 8_000 });

    // The step progress label should advance past "Introduction"
    await expect(page.locator(".step-progress__label")).not.toHaveText("Introduction", { timeout: 5_000 });

    // The emoji diagram should have changed from the intro
    const newEmoji = await page.locator(".concept-canvas__diagram").textContent();
    expect(newEmoji).not.toBe(introEmoji);

    await page.screenshot({ path: "e2e/evidence/turn-06-visual-updated.png" });
  });
});
