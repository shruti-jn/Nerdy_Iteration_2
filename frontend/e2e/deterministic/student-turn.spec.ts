import { test, expect } from "@playwright/test";

/**
 * Simulate hold-to-speak: mousedown on mic → short hold → mouseup.
 * Uses the page.mouse API to properly trigger React's onMouseDown/onMouseUp.
 */
async function holdAndReleaseMic(page: import("@playwright/test").Page, holdMs = 300) {
  const micBtn = page.getByRole("button", { name: "Hold to speak" });
  const box = await micBtn.boundingBox();
  if (!box) throw new Error("Mic button not found");
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.waitForTimeout(holdMs);
  await page.mouse.up();
}

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

    await holdAndReleaseMic(page);

    // Mock mode generates a tutor response after ~1500ms.
    // The response streams words then commits to history.
    // Wait for the tutor response to appear in conversation history.
    await expect(
      page.locator(".conv-history").locator(".conv-entry").nth(2),
    ).toBeVisible({ timeout: 8_000 });

    await page.screenshot({ path: "e2e/evidence/turn-02-tutor-responded.png" });
  });

  test("turn counter increments after a student turn", async ({ page }) => {
    await enterLessonWithGreeting(page);

    // Turn counter should start at 0
    await expect(page.locator(".topbar__turn-count")).toContainText("0");

    await holdAndReleaseMic(page);

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

    // Use mouse API for fine-grained control: press and hold
    const box = await micBtn.boundingBox();
    if (!box) throw new Error("Mic button not found");
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();

    // While recording, a "…" placeholder should appear in conversation history
    await expect(
      page.locator(".conv-history").getByText("…"),
    ).toBeVisible({ timeout: 3_000 });

    await page.screenshot({ path: "e2e/evidence/turn-04-student-placeholder.png" });

    await page.mouse.up();
  });

  test("tutor response is committed to conversation history", async ({ page }) => {
    await enterLessonWithGreeting(page);

    await holdAndReleaseMic(page);

    // Wait for tutor response to be committed to history
    // Conversation history should have at least 3 entries:
    // greeting + student utterance + tutor response
    await expect(page.locator(".conv-entry").nth(2)).toBeVisible({ timeout: 8_000 });
    const historyEntries = page.locator(".conv-entry");
    const count = await historyEntries.count();
    expect(count).toBeGreaterThanOrEqual(3);

    await page.screenshot({ path: "e2e/evidence/turn-05-history-updated.png" });
  });

  test("concept visual updates after a student turn", async ({ page }) => {
    await enterLessonWithGreeting(page);

    // Visual should already be showing the intro step from the greeting
    await expect(page.locator(".concept-canvas__diagram")).toBeVisible({ timeout: 5_000 });
    const introEmoji = await page.locator(".concept-canvas__diagram").textContent();

    await holdAndReleaseMic(page);

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
