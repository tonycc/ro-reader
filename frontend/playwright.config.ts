import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: "http://localhost:6173",
    headless: true,
    viewport: { width: 1440, height: 900 },
  },
  webServer: [
    {
      command: "uv run uvicorn ro_workbench_api.app:app --host 127.0.0.1 --port 54321 --log-level warning",
      cwd: "..",
      port: 54321,
      timeout: 15_000,
      reuseExistingServer: true,
    },
    {
      command: "npx vite --host 127.0.0.1 --port 6173",
      port: 6173,
      timeout: 10_000,
      reuseExistingServer: true,
    },
  ],
});
