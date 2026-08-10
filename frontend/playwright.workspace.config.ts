import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "workspace-http.spec.ts",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: "http://localhost:6175",
    headless: true,
    viewport: { width: 1440, height: 900 },
  },
  webServer: [
    {
      command: "node e2e/support/start-workspace-api.mjs",
      cwd: ".",
      port: 54323,
      timeout: 30_000,
      reuseExistingServer: false,
      env: { RO_WORKBENCH_E2E_API_PORT: "54323" },
    },
    {
      command: "pnpm exec vite --host 127.0.0.1 --port 6175",
      port: 6175,
      timeout: 30_000,
      reuseExistingServer: false,
      env: { RO_WORKBENCH_API_TARGET: "http://127.0.0.1:54323" },
    },
  ],
});
