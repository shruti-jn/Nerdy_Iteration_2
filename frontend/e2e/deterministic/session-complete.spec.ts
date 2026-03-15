import { test, expect } from "@playwright/test";

/**
 * Navigate to lesson, wait for greeting, and set totalTurns to a small
 * number so we can trigger session_complete quickly.
 */
async function enterLessonWithLowTurnLimit(page: import("@playwright/test").Page) {
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

  // Wait for greeting to complete
  const micBtn = page.getByRole("button", { name: "Hold to speak" });
  await expect(micBtn).toBeEnabled({ timeout: 8_000 });

  // Set totalTurns to 1 so the next turn triggers session_complete
  await page.evaluate(() => {
    const store = (window as unknown as Record<string, any>).__store;
    if (store?.setTurnInfo) {
      store.setTurnInfo(0, 1);
    }
  });
}

async function doOneTurn(page: import("@playwright/test").Page) {
  const micBtn = page.getByRole("button", { name: "Hold to speak" });
  const box = await micBtn.boundingBox();
  if (!box) throw new Error("Mic button not found");
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.waitForTimeout(300);
  await page.mouse.up();
}

test.describe("Session complete flow", () => {
  test("CelebrationOverlay appears when all turns are used", async ({ page }) => {
    await enterLessonWithLowTurnLimit(page);

    await doOneTurn(page);

    // Wait for the celebration overlay to appear (mock: ~1.5s response + 400ms commit + 200ms complete)
    await expect(page.locator(".celebration")).toBeVisible({ timeout: 10_000 });

    // Verify overlay content
    await expect(page.getByText("Amazing work!")).toBeVisible();
    await expect(page.locator(".celebration__topic")).toHaveText("Photosynthesis");
    await expect(page.getByRole("button", { name: "Try another topic" })).toBeVisible();

    await page.screenshot({ path: "e2e/evidence/complete-01-celebration.png" });
  });

  test("visual state shows recap (isRecap) on final turn", async ({ page }) => {
    await enterLessonWithLowTurnLimit(page);

    await doOneTurn(page);

    // The concept canvas should show the recap checkmark
    await expect(page.locator(".concept-canvas--recap")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator(".concept-canvas__check")).toBeVisible();

    await page.screenshot({ path: "e2e/evidence/complete-02-recap-visual.png" });
  });

  test("'Try another topic' returns to topic selection", async ({ page }) => {
    await enterLessonWithLowTurnLimit(page);

    await doOneTurn(page);

    await expect(page.locator(".celebration")).toBeVisible({ timeout: 10_000 });

    await page.getByRole("button", { name: "Try another topic" }).click();

    // Should return to topic selection
    await expect(page.getByText("What do you want to learn today?")).toBeVisible();

    await page.screenshot({ path: "e2e/evidence/complete-03-back-to-topics.png" });
  });

  test("celebration overlay has correct session stats", async ({ page }) => {
    await enterLessonWithLowTurnLimit(page);

    await doOneTurn(page);

    await expect(page.locator(".celebration")).toBeVisible({ timeout: 10_000 });

    // Stats should show the turn count and total
    const statValues = page.locator(".celebration__stat-value");
    const count = await statValues.count();
    expect(count).toBe(2);

    await page.screenshot({ path: "e2e/evidence/complete-04-stats.png" });
  });
});
