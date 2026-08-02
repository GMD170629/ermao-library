import { defineConfig, devices } from '@playwright/test';

const externalBaseURL = process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: externalBaseURL ?? 'http://127.0.0.1:3100',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  webServer: externalBaseURL ? undefined : {
    command: 'node scripts/prepare-pdfjs-worker.mjs && pnpm exec next dev -p 3100',
    url: 'http://127.0.0.1:3100/login',
    reuseExistingServer: true,
    timeout: 120_000
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'iphone-webkit', use: { ...devices['iPhone 13'] } }
  ]
});
