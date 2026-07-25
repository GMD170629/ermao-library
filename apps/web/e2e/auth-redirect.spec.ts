import { expect, test, type Page } from '@playwright/test';

async function mockExpiredSession(page: Page) {
  await page.route('**/api/v2/account', async (route) => {
    await route.fulfill({
      status: 401,
      json: { ok: false, error: { message: 'UNAUTHORIZED' } }
    });
  });
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/v2/auth/setup/status', async (route) => {
    await route.fulfill({ json: { ok: true, data: { initialized: true } } });
  });
});

test('a missing session is redirected by the server before protected content renders', async ({ page }) => {
  await page.goto('/library?status=READING');

  await expect(page).toHaveURL(/\/login\?next=%2Flibrary%3Fstatus%3DREADING$/);
  await expect(page.getByRole('button', { name: '登录' })).toBeVisible();
});

test('an expired session cookie is verified and redirected without showing API errors', async ({ context, page }) => {
  await context.addCookies([{ name: 'shuku_session', value: 'expired-session', domain: '127.0.0.1', path: '/' }]);
  await mockExpiredSession(page);

  await page.goto('/library?status=READING');

  await expect(page).toHaveURL(/\/login\?next=%2Flibrary%3Fstatus%3DREADING$/);
  await expect(page.getByRole('button', { name: '登录' })).toBeVisible();
  await expect(page.getByText('UNAUTHORIZED')).toHaveCount(0);
});

test('the retired mobile URL enters the responsive web shell and keeps session validation', async ({ context, page }) => {
  await context.addCookies([{ name: 'shuku_session', value: 'expired-session', domain: '127.0.0.1', path: '/' }]);
  await mockExpiredSession(page);

  await page.goto('/mobile');

  await expect(page).toHaveURL(/\/login\?next=%2Fmobile$/);
  await expect(page.getByRole('button', { name: '登录' })).toBeVisible();
});
