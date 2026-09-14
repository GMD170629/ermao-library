import { defineConfig, devices } from '@playwright/test';

const externalBaseURL = process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: './e2e',
  testIgnore: ['**/release-live.spec.ts'],
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
    { name: 'chrome', use: { ...devices['Desktop Chrome'], channel: 'chrome' } },
    {
      name: 'http-chrome',
      testMatch: ['**/readium-reader.spec.ts', '**/local-original-formats.spec.ts'],
      grep: /cached original EPUB|failed original transfer|original locally|original fails closed|WASM digest|HTTP original/,
      use: {
        ...devices['Desktop Chrome'], channel: 'chrome',
        baseURL: 'http://reader-http.test:3100',
        launchOptions: { args: ['--host-resolver-rules=MAP reader-http.test 127.0.0.1', '--no-proxy-server'] }
      }
    },
    { name: 'mobile-chrome', use: { ...devices['Pixel 7'], channel: 'chrome' } }
  ]
});
