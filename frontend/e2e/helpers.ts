import { type Page, expect } from "@playwright/test";

/**
 * Navigate from topic selection through to the lesson view.
 * Takes screenshots at each transition for evidence.
 */
export async function navigateToLesson(
  page: Page,
  topic: "Photosynthesis" | "Newton's Laws" = "Photosynthesis",
): Promise<void> {
  await page.goto("/");

  await expect(page.getByText("What do you want to learn today?")).toBeVisible();
  await page.screenshot({ path: "e2e/evidence/01-topic-select.png" });

  await page.getByRole("button", { name: new RegExp(`Start ${topic}`) }).click();

  await expect(page.getByText("Preparing your lesson...")).toBeVisible();
  await page.screenshot({ path: "e2e/evidence/02-getting-ready.png" });

  // Wait for the Start Lesson button to become enabled.
  // In mock mode the avatar errors quickly, so both "Start Lesson" and
  // "Start without avatar" appear. We wait for Start Lesson to be enabled
  // (which happens when wsConnected && showFallback are both true).
  const startBtn = page.getByRole("button", { name: "Start Lesson" });
  const fallbackBtn = page.getByRole("button", { name: "Start without avatar" });

  await expect(startBtn).toBeEnabled({ timeout: 15_000 });
  await page.screenshot({ path: "e2e/evidence/03-ready-to-start.png" });

  if (await fallbackBtn.isVisible()) {
    await fallbackBtn.click();
  } else {
    await startBtn.click();
  }

  await expect(page.locator(".app__main")).toBeVisible();
  await page.screenshot({ path: "e2e/evidence/04-lesson-view.png" });
}

/**
 * Wait for the tutor greeting text to appear in the TeachingPanel.
 */
export async function waitForGreeting(page: Page): Promise<void> {
  await expect(
    page.locator(".teaching-panel__text").getByText(/Hey there/),
  ).toBeVisible({ timeout: 10_000 });
}

/**
 * Wait for the mic button to be interactive (mode = idle, not greeting/responding).
 */
export async function waitForMicEnabled(page: Page): Promise<void> {
  await expect(page.locator(".app")).not.toHaveClass(/app--tutor-greeting/, {
    timeout: 10_000,
  });
}

/**
 * Enter lesson and wait for greeting to complete (mic enabled).
 */
export async function enterLessonWithGreeting(
  page: Page,
  topic: "Photosynthesis" | "Newton's Laws" = "Photosynthesis",
): Promise<void> {
  await navigateToLesson(page, topic);
  const micBtn = page.getByRole("button", { name: "Hold to speak" });
  await expect(micBtn).toBeEnabled({ timeout: 8_000 });
}
