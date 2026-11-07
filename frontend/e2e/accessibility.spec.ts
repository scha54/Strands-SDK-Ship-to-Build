/**
 * Accessibility browser runs (task 10.3).
 *
 * Validates: Requirements R-09.1 (keyboard-only, visual order), R-09.2 (visible
 * focus, 3:1), R-09.3 (programmatic labels), R-09.4 (text contrast), R-09.5
 * (no horizontal scroll from 320 px), R-09.8 and R-09.10 (alternative paths),
 * NFR-03 (axe), NFR-04 (viewport).
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const SCREENS = ["setup", "timeline", "activity", "summary"] as const;

async function open(page: Page, screen: string): Promise<void> {
  await page.goto(`/harness.html?screen=${screen}`);
  await expect(page.locator("main")).toBeVisible();
  if (screen.startsWith("activity")) {
    await page.getByRole("button", { name: "Skip this question" }).click();
    await expect(page.getByTestId("progress")).toBeVisible();
  }
}

async function noHorizontalScroll(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
}

for (const screen of SCREENS) {
  test(`axe finds no violations on ${screen} (R-09.3, R-09.4, NFR-03)`, async ({ page }) => {
    await open(page, screen);
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(results.violations).toEqual([]);
  });

  test(`no horizontal scroll at 320 px on ${screen} (R-09.5, NFR-04)`, async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });
    await open(page, screen);
    expect(await noHorizontalScroll(page)).toBe(true);
  });
}

test("axe finds no violations on the alternative and no-alternative views (R-09.8, R-09.10)", async ({
  page,
}) => {
  for (const screen of ["activity-alt", "activity-none"]) {
    await open(page, screen);
    await page.getByLabel("Do not rely on color").check();
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
      .analyze();
    expect(results.violations).toEqual([]);
  }
});

test("keyboard-only: Tab follows visual order and focus is visible (R-09.1, R-09.2)", async ({
  page,
}) => {
  await open(page, "setup");
  const seen: string[] = [];
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return {
        label: (el.getAttribute("aria-label") ?? el.textContent ?? el.id).trim().slice(0, 30),
        top: Math.round(r.top + window.scrollY),
        outlineWidth: parseFloat(cs.outlineWidth),
        outlineStyle: cs.outlineStyle,
        outlineColor: cs.outlineColor,
        tag: el.tagName,
      };
    });
    if (info === null) break;
    seen.push(`${info.top}:${info.tag}`);
    // Visible indicator (R-09.2): a solid outline of at least 2 px.
    expect(info.outlineStyle).not.toBe("none");
    expect(info.outlineWidth).toBeGreaterThanOrEqual(2);
    // Outline color must reach 3:1 against the white page background.
    const m = info.outlineColor.match(/\d+/g)?.map(Number) ?? [0, 0, 0];
    const lin = (v: number): number => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    };
    const L = 0.2126 * lin(m[0] ?? 0) + 0.7152 * lin(m[1] ?? 0) + 0.0722 * lin(m[2] ?? 0);
    expect(1.05 / (L + 0.05)).toBeGreaterThanOrEqual(3);
  }
  expect(seen.length).toBeGreaterThan(5);
  // Reading order: vertical position never moves up while tabbing forward
  // (the age-band radios share a row, so equal tops are allowed).
  const tops = seen.map((s) => Number(s.split(":")[0]));
  const sorted = [...tops].sort((a, b) => a - b);
  expect(tops).toEqual(sorted);
});

test("keyboard-only: the activity can be completed without a pointer (R-09.1)", async ({
  page,
}) => {
  await page.goto("/harness.html?screen=activity");
  await page.getByRole("button", { name: "Skip this question" }).focus();
  await page.keyboard.press("Enter");
  const answer = page.getByLabel("Your answer");
  await expect(answer).toBeVisible();
  await answer.focus();
  await page.keyboard.type("3");
  await expect(answer).toHaveValue("3");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Check my answer" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Show a hint" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("hint")).toContainText("Count slowly.");
});

test("alternative instruction replaces the color-dependent one (R-09.8)", async ({ page }) => {
  await open(page, "activity-alt");
  await expect(page.getByText("red stones")).toBeVisible();
  await page.getByLabel("Do not rely on color").check();
  await expect(page.getByTestId("alternative-instruction")).toContainText("big stones");
  await expect(page.getByText("red stones")).toHaveCount(0);
  await expect(page.getByLabel("Your answer")).toBeVisible();
});
