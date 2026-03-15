import { test, expect } from "@playwright/test";

test.describe("Lesson flow: topic select → getting ready → lesson", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("shows topic selection screen on load", async ({ page }) => {
    await expect(page.getByText("What do you want to learn today?")).toBeVisible();
    await expect(page.getByRole("button", { name: /Start Photosynthesis/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Start Newton's Laws/ })).toBeVisible();

    // Coming Soon topics are disabled
    await expect(page.getByRole("button", { name: /Water Cycle/ })).toBeDisabled();

    await page.screenshot({ path: "e2e/evidence/flow-01-topic-select.png" });
  });

  test("clicking a topic transitions to Getting Ready view", async ({ page }) => {
    await page.getByRole("button", { name: /Start Photosynthesis/ }).click();

    await expect(page.getByText("Photosynthesis")).toBeVisible();
    await expect(page.getByText("Preparing your lesson...")).toBeVisible();
    await expect(page.getByText("Connecting to tutor")).toBeVisible();
    await expect(page.getByText("Loading avatar")).toBeVisible();
    await expect(page.getByText("Ready!")).toBeVisible();

    await page.screenshot({ path: "e2e/evidence/flow-02-getting-ready.png" });
  });

  test("Start Lesson or fallback button enables and transitions to lesson view", async ({ page }) => {
    await page.getByRole("button", { name: /Start Photosynthesis/ }).click();
    await expect(page.getByText("Preparing your lesson...")).toBeVisible();

    // In mock mode: WS connects immediately, avatar errors, fallback appears.
    const startBtn = page.getByRole("button", { name: "Start Lesson" });
    const fallbackBtn = page.getByRole("button", { name: "Start without avatar" });

    await expect(startBtn).toBeEnabled({ timeout: 15_000 });
    await page.screenshot({ path: "e2e/evidence/flow-03-ready-to-start.png" });

    // Click whichever is available — prefer fallback since avatar isn't real
    if (await fallbackBtn.isVisible()) {
      await fallbackBtn.click();
    } else {
      await startBtn.click();
    }

    // Lesson view should now be visible
    await expect(page.locator(".app__main")).toBeVisible();
    await expect(page.locator(".topbar")).toBeVisible();
    await expect(page.locator(".bottom-bar")).toBeVisible();

    await page.screenshot({ path: "e2e/evidence/flow-04-lesson-view.png" });
  });

  test("Back button returns to topic selection", async ({ page }) => {
    await page.getByRole("button", { name: /Start Photosynthesis/ }).click();
    await expect(page.getByText("Preparing your lesson...")).toBeVisible();

    await page.getByRole("button", { name: "Back to topic selection" }).click();

    await expect(page.getByText("What do you want to learn today?")).toBeVisible();
  });

  test("lesson view shows correct topic in TopBar", async ({ page }) => {
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
    // TopBar should show the topic name
    await expect(page.locator(".topbar__topic-text")).toHaveText("Photosynthesis");
    // Turn counter starts at 0
    await expect(page.locator(".topbar__turn-count")).toContainText("0");
  });
});
