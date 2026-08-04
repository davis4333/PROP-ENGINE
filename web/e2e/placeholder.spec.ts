import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test.describe("Placeholder home page", () => {
  test("loads and shows the Cassandra wordmark and tagline", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(
      page.getByRole("heading", { name: "CASSANDRA" }),
    ).toBeVisible();
    await expect(page.getByText("DATA. MODELS. RESULTS.")).toBeVisible();
    await expect(page.getByText(/engine is under construction/i)).toBeVisible();
  });

  test("has no detectable accessibility violations", async ({ page }) => {
    await page.goto("/");

    const results = await new AxeBuilder({ page }).analyze();

    expect(results.violations).toEqual([]);
  });
});
