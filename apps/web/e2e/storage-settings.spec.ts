import { expect, test } from '@playwright/test';

for (const locale of ['zh-CN', 'en-US']) {
  test(`storage usage, direct cleanup and partial failure refresh (${locale})`, async ({ page }) => {
    const en = locale === 'en-US';
    const categories = ['program', 'database', 'images', 'cache', 'logs', 'backups', 'updates', 'uploads', 'other'].map((id) => ({ id, sizeBytes: 1024, clearable: ['cache', 'logs', 'backups', 'updates', 'uploads'].includes(id) }));
    let reads = 0;
    let clears = 0;
    let partialReads = 0;
    await page.context().addCookies([{ name: 'shuku_session', value: 'storage-session', domain: '127.0.0.1', path: '/' }]);
    await page.route('**/api/**', async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/auth/me') {
        return route.fulfill({ json: { ok: true, data: { user: { id: 'storage-admin', email: 'storage@example.com', name: 'Storage admin', role: 'admin', locale }, authorization: { isAdmin: true, canManageSystem: true, authzVersion: 1 } } } });
      }
      if (url.pathname === '/api/system/storage/cache') {
        clears++;
        categories[3].sizeBytes = 0;
        return route.fulfill({ json: { ok: true, data: { root: '/app/storage', categories: [categories[3]] } } });
      }
      if (url.pathname === '/api/system/storage/logs') {
        categories[4].sizeBytes = 512;
        return route.fulfill({ status: 400, json: { ok: false, error: { message: 'failed' } } });
      }
      if (url.pathname === '/api/system/storage') {
        const category = url.searchParams.get('category');
        if (category) partialReads++; else reads++;
        return route.fulfill({ json: { ok: true, data: { root: '/app/storage', categories: category ? categories.filter((row) => row.id === category) : categories } } });
      }
      return route.fulfill({ json: { ok: true, data: { shelves: [], settings: {}, libraries: [] } } });
    });
    await page.goto('/settings/storage');
    await expect(page).toHaveURL(/\/settings\/data\?tab=storage$/);
    const content = page.getByTestId('app-shell-content');
    await expect(content.getByRole('link', { name: en ? 'Storage management' : '空间管理', exact: true })).toHaveAttribute('aria-current', 'page');
    await expect(content.locator('main li')).toHaveCount(9);
    await expect(content.getByRole('button', { name: en ? /^Clear / : /^清理 / })).toHaveCount(5);
    await page.screenshot({ path: test.info().outputPath('storage.png'), fullPage: true });
    const cache = content.locator('main li').filter({ hasText: en ? 'Cache' : '缓存' });
    await cache.getByRole('button').click();
    await expect(cache).toContainText('0 B');
    expect(clears).toBe(1);
    expect(reads).toBe(1);
    const logs = content.locator('main li').filter({ hasText: en ? 'Log' : '日志' });
    await logs.getByRole('button').click();
    await expect(content.getByRole('alert')).toHaveText(en ? 'Cleanup failed; please retry' : '清理失败，请重试');
    await expect(logs).toContainText('512 B');
    expect(partialReads).toBe(1);
    await content.getByRole('button', { name: en ? 'Refresh' : '刷新', exact: true }).click();
    await expect.poll(() => reads).toBe(2);
  });
}
