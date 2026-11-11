import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run against a live Mesa server with the real catalog:
//   python scripts/run_local.py --cloud --port 8765
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: { baseURL: process.env.MESA_URL ?? "http://127.0.0.1:8765", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 860 } } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});
