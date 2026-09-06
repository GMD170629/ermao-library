import { defineConfig, devices } from '@playwright/test';

if (process.env.RELEASE_LIVE_E2E !== '1') {
  throw new Error('The release live suite is opt-in; set RELEASE_LIVE_E2E=1');
}

const baseURL = process.env.PLAYWRIGHT_BASE_URL;
if (!baseURL) {
  throw new Error('The release live suite requires PLAYWRIGHT_BASE_URL');
}

export default defineConfig({
  testDir: './e2e',
  testMatch: /release-live\.spec\.ts$/,
  fullyParallel: false,
  timeout: 300_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL,
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  webServer: undefined,
  projects: [
    { name: 'chrome', use: { ...devices['Desktop Chrome'], channel: 'chrome' } },
    { name: 'mobile-chrome', use: { ...devices['Pixel 7'], channel: 'chrome' } }
  ]
});
