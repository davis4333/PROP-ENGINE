import { defineConfig, devices } from "@playwright/test";
import { existsSync } from "node:fs";

const PORT = 3100;
const baseURL = `http://127.0.0.1:${PORT}`;

// This sandboxed dev environment ships a pre-installed Chromium at a fixed
// path (PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 stops npm postinstall from
// re-fetching it). Real CI (.github/workflows/ci.yml) has no such path --
// it runs `playwright install --with-deps chromium` and Playwright finds
// its own default-installed browser. Only override executablePath when
// the sandboxed path actually exists, so CI isn't pointed at a binary
// that was never installed there.
const sandboxChromium = "/opt/pw-browsers/chromium";
const launchOptions = existsSync(sandboxChromium)
  ? { executablePath: sandboxChromium }
  : {};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env["CI"],
  retries: process.env["CI"] ? 2 : 0,
  reporter: "list",
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions,
      },
    },
  ],
  webServer: {
    command: `pnpm exec next dev --port ${PORT}`,
    url: baseURL,
    reuseExistingServer: !process.env["CI"],
    timeout: 120_000,
  },
});
