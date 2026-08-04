import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// These run against `next dev` only (see playwright.config.ts) -- no
// engine API is started alongside it in this harness, so each page must
// be checked against BOTH possible real states: live data (if a backend
// happens to be reachable at API_BASE_URL) or the graceful "can't reach
// the API" fallback (see src/app/page.tsx / ledger/page.tsx). Either is a
// legitimate pass; a hard crash or blank page is not.

test.describe("Today page", () => {
  test("renders either real slate data or a graceful API-unreachable message", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Today's Slate" }),
    ).toBeVisible();
  });

  test("has no detectable accessibility violations", async ({ page }) => {
    await page.goto("/");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
});

test.describe("Ledger page", () => {
  test("renders either the ledger table or a graceful API-unreachable message", async ({
    page,
  }) => {
    await page.goto("/ledger");
    await expect(
      page.getByRole("heading", { name: "Results Ledger" }),
    ).toBeVisible();
  });

  test("has no detectable accessibility violations", async ({ page }) => {
    await page.goto("/ledger");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
});

test.describe("Admin page", () => {
  test("shows the shared-secret gate (never fetches without a secret)", async ({
    page,
  }) => {
    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: "Admin" })).toBeVisible();
    await expect(page.getByLabel("Admin secret")).toBeVisible();
  });

  test("has no detectable accessibility violations", async ({ page }) => {
    await page.goto("/admin");
    const results = await new AxeBuilder({ page }).analyze();
    expect(results.violations).toEqual([]);
  });
});

test.describe("Navigation", () => {
  test("the header links move between all three pages", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Ledger" }).click();
    await expect(page).toHaveURL(/\/ledger$/);
    await page.getByRole("link", { name: "Admin" }).click();
    await expect(page).toHaveURL(/\/admin$/);
    await page.getByRole("link", { name: "Today" }).click();
    await expect(page).toHaveURL(/\/$/);
  });
});
