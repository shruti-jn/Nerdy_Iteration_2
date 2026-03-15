import { test, expect } from "@playwright/test";

test.describe("Avatar failure fallback", () => {
  test("'Start without avatar' button appears after avatar error", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /Start Photosynthesis/ }).click();
    await expect(page.getByText("Preparing your lesson...")).toBeVisible();

    // In mock mode the avatar errors quickly, showing "Start without avatar".
    const fallbackBtn = page.getByRole("button", { name: "Start without avatar" });
    await expect(fallbackBtn).toBeVisible({ timeout: 15_000 });

    await page.screenshot({ path: "e2e/evidence/fallback-01-button-visible.png" });
  });

  test("clicking fallback starts lesson without avatar", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /Start Photosynthesis/ }).click();

    const fallbackBtn = page.getByRole("button", { name: "Start without avatar" });
    await expect(fallbackBtn).toBeVisible({ timeout: 15_000 });
    await fallbackBtn.click();

    // Lesson view should load
    await expect(page.locator(".app__main")).toBeVisible();
    await expect(page.locator(".topbar__topic-text")).toHaveText("Photosynthesis");

    await page.screenshot({ path: "e2e/evidence/fallback-02-lesson-started.png" });
  });

  test("lesson is fully functional without avatar (greeting + mic)", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /Start Photosynthesis/ }).click();

    const fallbackBtn = page.getByRole("button", { name: "Start without avatar" });
    await expect(fallbackBtn).toBeVisible({ timeout: 15_000 });
    await fallbackBtn.click();

    await expect(page.locator(".app__main")).toBeVisible();

    // Greeting should still play in mock mode
    await expect(
      page.locator(".teaching-panel__text"),
    ).toContainText("Hey there", { timeout: 5_000 });

    // Mic should enable after greeting completes
    const micBtn = page.getByRole("button", { name: "Hold to speak" });
    await expect(micBtn).toBeEnabled({ timeout: 5_000 });

    await page.screenshot({ path: "e2e/evidence/fallback-03-functional.png" });
  });

  test("avatar area shows placeholder, not live video", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /Start Photosynthesis/ }).click();

    const fallbackBtn = page.getByRole("button", { name: "Start without avatar" });
    await expect(fallbackBtn).toBeVisible({ timeout: 15_000 });
    await fallbackBtn.click();

    await expect(page.locator(".app__main")).toBeVisible();

    // The avatar feed should be visible but not playing live video.
    // The video element exists but has no srcObject in mock mode.
    const video = page.locator(".avatar-feed video");
    if (await video.isVisible()) {
      const srcObj = await video.evaluate((el: HTMLVideoElement) => el.srcObject);
      expect(srcObj).toBeNull();
    }

    await page.screenshot({ path: "e2e/evidence/fallback-04-avatar-placeholder.png" });
  });
});
