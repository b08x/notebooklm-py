import { existsSync } from "node:fs";
import { defineConfig } from "@playwright/test";

const PORT = Number(process.env.E2E_PORT ?? 8799);
export const E2E_TOKEN = "e2e-token";
export const E2E_NOTEBOOK = process.env.E2E_NOTEBOOK ?? "nb-e2e";
// Title the seed script stores for the fixture notebook (scripts/seed_corpus_fixture.py).
export const E2E_NOTEBOOK_TITLE = `Fixture notebook ${E2E_NOTEBOOK}`;

// Use a preinstalled Chromium when the matching Playwright build is not downloaded.
const chromium =
  process.env.PLAYWRIGHT_CHROMIUM_PATH ??
  (existsSync("/opt/pw-browsers/chromium")
    ? "/opt/pw-browsers/chromium"
    : [
        `${process.env.HOME}/.cache/ms-playwright/chromium-1208/chrome-linux64/chrome`,
        `${process.env.HOME}/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome`,
      ].find((p) => existsSync(p)));

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  reporter: [["list"]],
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    launchOptions: chromium ? { executablePath: chromium } : {},
    viewport: { width: 1440, height: 860 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: `uv run notebooklm-server --host 127.0.0.1 --port ${PORT}`,
    cwd: "..",
    url: `http://127.0.0.1:${PORT}/healthz`,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      NOTEBOOKLM_SERVER_TOKEN: E2E_TOKEN,
      // An empty profile dir: the explorer must work without a NotebookLM login.
      NOTEBOOKLM_HOME: `${process.env.TMPDIR ?? "/tmp"}/nblm-e2e-home`,
      OLLAMA_URL: "http://127.0.0.1:9",
    },
  },
});
