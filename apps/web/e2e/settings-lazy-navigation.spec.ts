import { expect, test, type Page } from '@playwright/test';

type RequestCounts = Record<string, number>;

const organizeJobs = {
  jobs: [],
  books: [],
  page: 1,
  pageSize: 20,
  total: 0,
  totalPages: 1,
  statusCounts: { SUCCESS: 0, FAILED: 0, RECOGNIZING: 0, WAITING: 0 },
  providerNames: {}
};

async function mockSettingsApi(page: Page, locale: 'zh-CN' | 'en-US' = 'zh-CN') {
  const counts: RequestCounts = {};
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname;
    counts[pathname] = (counts[pathname] ?? 0) + 1;
    const methodPath = `${route.request().method()} ${pathname}`;
    counts[methodPath] = (counts[methodPath] ?? 0) + 1;

    if (pathname.endsWith('/api/auth/me')) {
      await route.fulfill({
        json: {
          ok: true,
          data: {
            user: { id: 'settings-user', email: 'settings@example.com', name: 'Settings user', role: 'admin', locale },
            authorization: { isAdmin: true, canManageSystem: true, authzVersion: 1 }
          }
        }
      });
      return;
    }
    if (pathname.endsWith('/api/shelves')) {
      await route.fulfill({ json: { ok: true, data: { shelves: [] } } });
      return;
    }
    if (pathname.endsWith('/api/organize/jobs')) {
      await route.fulfill({ json: { ok: true, data: organizeJobs } });
      return;
    }
    if (pathname.endsWith('/api/metadata/providers')) {
      await route.fulfill({ json: { ok: true, data: { providers: [], pipelines: [] } } });
      return;
    }
    if (pathname.endsWith('/api/library/categories')) {
      await route.fulfill({ json: { ok: true, data: { categories: [], page: 1, pageSize: 20, total: 0, totalPages: 1 } } });
      return;
    }
    if (pathname.endsWith('/api/organize/policy')) {
      await route.fulfill({
        json: {
          ok: true,
          data: {
            policy: {
              id: 'default', enabled: false, scheduleMode: 'MANUAL', intervalMinutes: 60, autoRunOnNew: false,
              autoRunOnNewSince: null, rules: { unrecognized: true, missingMetadata: true }, writeMetadataToFiles: false,
              preferLocalMetadata: true, localMetadataPriority: ['SIDECAR_OPF', 'EMBEDDED', 'PATH'],
              lastScheduledAt: null, nextRunAt: null, updatedAt: null
            }
          }
        }
      });
      return;
    }
    if (pathname.endsWith('/api/organize/candidates')) {
      await route.fulfill({ json: { ok: true, data: { candidates: { total: 0 } } } });
      return;
    }
    if (pathname.endsWith('/api/kindle-settings')) {
      await route.fulfill({ json: { ok: true, data: { kindle: { email: '' }, smtp: { configured: false, fromEmail: '' } } } });
      return;
    }
    if (pathname.endsWith('/api/email-settings')) {
      await route.fulfill({
        json: {
          ok: true,
          data: {
            smtp: { host: '', port: 587, security: 'starttls', username: '', fromEmail: '', fromName: '', maxAttachmentMb: null, passwordConfigured: false },
            kindle: { email: '' }
          }
        }
      });
      return;
    }
    if (pathname.endsWith('/api/kindle-send-tasks')) {
      await route.fulfill({ json: { ok: true, data: { tasks: [], total: 0 } } });
      return;
    }
    if (pathname.endsWith('/api/import-tasks')) {
      await route.fulfill({ json: { ok: true, data: { tasks: [], summary: { completed: 0, failed: 0 }, page: 1, pageSize: 10, total: 0, totalPages: 1 } } });
      return;
    }
    if (pathname.endsWith('/api/libraries/tree')) {
      const requestedPath = url.searchParams.get('path');
      await route.fulfill({ json: { ok: true, data: { node: requestedPath === '/library' ? { name: 'library', path: '/library', readable: true, children: [] } : { name: '/', path: '/', readable: true, children: [{ name: 'library', path: '/library', readable: true }] } } } });
      return;
    }
    if (pathname.endsWith('/api/libraries')) {
      await route.fulfill({ json: { ok: true, data: { libraries: [] } } });
      return;
    }
    if (pathname.endsWith('/api/system-settings')) {
      await route.fulfill({ json: { ok: true, data: { settings: {} } } });
      return;
    }
    await route.fulfill({ json: { ok: true, data: {} } });
  });
  return counts;
}

function requestCount(counts: RequestCounts, pathname: string) {
  return counts[pathname] ?? 0;
}

test.beforeEach(async ({ context, page }) => {
  await context.addCookies([{ name: 'shuku_session', value: 'settings-session', domain: '127.0.0.1', path: '/' }]);
  await context.addInitScript(() => localStorage.setItem('shuku:pwa:install-dismissed:settings-user', '1'));
  await mockSettingsApi(page);
});

test('settings tab starts its selected animation before the route is confirmed', async ({ page }) => {
  await page.goto('/settings/organize?tab=queue');
  const providersTab = page.locator('a[href="/settings/organize?tab=providers"]');
  await expect(providersTab).toHaveCount(1);

  await page.route(/\/settings\/organize(?:\?.*)?$/, async (route) => {
    if (new URL(route.request().url()).searchParams.get('tab') === 'providers') {
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    await route.continue();
  });

  await providersTab.click({ noWaitAfter: true });
  await expect(providersTab).toHaveAttribute('data-pending-navigation', 'true');
  await expect(providersTab).not.toHaveAttribute('aria-current', 'page');
  await expect(page).toHaveURL(/tab=providers/);
  await expect(providersTab).toHaveAttribute('aria-current', 'page');
});

test('settings navigation keeps session and shelves stable while tabs load on demand', async ({ page }) => {
  const counts = await mockSettingsApi(page);
  await page.goto('/settings/organize?tab=queue');
  await expect.poll(() => requestCount(counts, '/api/organize/jobs')).toBeGreaterThan(0);
  await expect.poll(() => requestCount(counts, '/api/auth/me')).toBeGreaterThan(0);
  await expect.poll(() => requestCount(counts, '/api/shelves')).toBeGreaterThan(0);
  await page.waitForTimeout(750);
  const initialJobsRequests = requestCount(counts, '/api/organize/jobs');
  const initialAuthRequests = requestCount(counts, '/api/auth/me');
  const initialShelfRequests = requestCount(counts, '/api/shelves');
  expect(requestCount(counts, '/api/metadata/providers')).toBe(0);
  expect(requestCount(counts, '/api/library/categories')).toBe(0);
  expect(requestCount(counts, '/api/organize/policy')).toBe(0);
  expect(requestCount(counts, '/api/organize/candidates')).toBe(0);

  await page.locator('a[href="/settings/organize?tab=providers"]').click();
  await expect.poll(() => requestCount(counts, '/api/metadata/providers')).toBeGreaterThan(0);
  await page.locator('a[href="/settings/organize?tab=categories"]').click();
  await expect.poll(() => requestCount(counts, '/api/library/categories')).toBeGreaterThan(0);
  await page.locator('a[href="/settings/organize?tab=recognition"]').click();
  await expect.poll(() => requestCount(counts, '/api/organize/policy')).toBeGreaterThan(0);
  await expect.poll(() => requestCount(counts, '/api/organize/candidates')).toBeGreaterThan(0);
  await page.locator('a[href="/settings/organize?tab=queue"]').click();
  await expect.poll(() => requestCount(counts, '/api/organize/jobs')).toBeGreaterThan(initialJobsRequests);

  await page
    .getByRole('navigation', { name: '设置分类' })
    .getByRole('link', { name: '邮件与 Kindle' })
    .click();
  await expect.poll(() => requestCount(counts, '/api/kindle-settings')).toBeGreaterThan(0);
  expect(requestCount(counts, '/api/email-settings')).toBe(0);
  expect(requestCount(counts, '/api/kindle-send-tasks')).toBe(0);

  await page.locator('a[href="/settings/email?tab=smtp"]').click();
  await expect.poll(() => requestCount(counts, '/api/email-settings')).toBeGreaterThan(0);
  await page.locator('a[href="/settings/email?tab=queue"]').click();
  await expect.poll(() => requestCount(counts, '/api/kindle-send-tasks')).toBeGreaterThan(0);

  expect(requestCount(counts, '/api/auth/me')).toBe(initialAuthRequests);
  expect(requestCount(counts, '/api/shelves')).toBe(initialShelfRequests);

  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent('shuku:account-changed', {
      detail: { id: 'settings-user', email: 'updated@example.com', name: 'Updated settings user' }
    }));
    window.dispatchEvent(new CustomEvent('shuku:shelves-changed'));
  });
  const mobileNavigationTrigger = page.getByRole('button', { name: '打开导航菜单' });
  if (await mobileNavigationTrigger.isVisible()) {
    await mobileNavigationTrigger.click();
    await expect(
      page.getByTestId('mobile-navigation').getByText('Updated settings user', { exact: true })
    ).toBeVisible();
  } else {
    await expect(
      page.locator('aside').first().getByText('Updated settings user', { exact: true })
    ).toBeVisible();
  }
  await expect.poll(() => requestCount(counts, '/api/shelves')).toBe(initialShelfRequests + 1);
  expect(requestCount(counts, '/api/auth/me')).toBe(initialAuthRequests);
});

test('library import sections fetch only when their tab mounts and refresh after remount', async ({ page }) => {
  const counts = await mockSettingsApi(page);
  await page.goto('/settings/library');
  await expect.poll(() => requestCount(counts, '/api/import-tasks')).toBeGreaterThan(0);
  await expect(page.getByRole('button', { name: '清理导入队列' })).toHaveCount(0);
  const initialImportTaskRequests = requestCount(counts, '/api/import-tasks');
  expect(requestCount(counts, '/api/libraries/tree')).toBe(0);
  expect(requestCount(counts, '/api/libraries')).toBe(0);
  expect(requestCount(counts, '/api/system-settings')).toBe(0);

  await page.getByRole('tab', { name: '文件管理' }).click();
  await expect.poll(() => requestCount(counts, '/api/libraries/tree')).toBeGreaterThan(0);
  await page.getByRole('tab', { name: '书库' }).click();
  await expect.poll(() => requestCount(counts, '/api/libraries')).toBeGreaterThan(0);
  await page.getByRole('tab', { name: '偏好设置' }).click();
  await expect.poll(() => requestCount(counts, '/api/system-settings')).toBeGreaterThan(0);
  await page.getByRole('tab', { name: '导入记录' }).click();
  await expect.poll(() => requestCount(counts, '/api/import-tasks')).toBeGreaterThan(initialImportTaskRequests);
});

test('new library shows expanded scan rules with a 10 KB minimum by default', async ({ page }) => {
  await page.goto('/settings/library');
  await page.getByRole('tab', { name: '文件管理' }).click();
  await page.getByRole('tab', { name: '书库' }).click();
  await page.getByRole('button', { name: '新增书库' }).click();

  const folderPath = page.getByRole('combobox', { name: '书库路径' });
  await folderPath.fill('/library');
  await page.getByRole('button', { name: '展开文件夹路径树' }).click();
  const directoryTree = page.getByRole('tree');
  await expect(directoryTree.getByRole('button', { name: '/', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'library', exact: true }).click();
  await expect(folderPath).toHaveValue('/library');

  const scanRules = page.getByRole('button', { name: /扫描规则/ });
  await expect(scanRules).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('spinbutton', { name: '最小文件大小 KB' })).toHaveValue('10');
});

test('library import preferences save after editing ignore patterns', async ({ page }) => {
  const counts = await mockSettingsApi(page);
  await page.goto('/settings/library');
  await page.getByRole('tab', { name: '偏好设置' }).click();
  await expect.poll(() => requestCount(counts, '/api/system-settings')).toBeGreaterThan(0);

  const ignorePatterns = page.locator('textarea');
  await ignorePatterns.fill('*.tmp');
  await expect(page.getByRole('button', { name: '保存偏好' })).toBeEnabled();
  await page.getByRole('button', { name: '保存偏好' }).click();

  await expect.poll(() => requestCount(counts, 'PUT /api/system-settings')).toBe(1);
  await expect(page.getByRole('button', { name: '保存偏好' })).toBeDisabled();

  await ignorePatterns.fill('*.part');
  await page.getByRole('button', { name: '保存偏好' }).click();
  await expect.poll(() => requestCount(counts, 'PUT /api/system-settings')).toBe(2);
  await expect(page.getByRole('button', { name: '保存偏好' })).toBeDisabled();

  await ignorePatterns.fill('*.cache');
  await expect(page.getByRole('button', { name: '保存偏好' })).toBeEnabled();
  await page.getByRole('button', { name: '撤销更改' }).click();
  await expect(ignorePatterns).toHaveValue('*.part');
  await expect(page.getByRole('button', { name: '保存偏好' })).toBeDisabled();
});

test('English settings tabs retain route-backed accessibility state', async ({ context, page }) => {
  await context.clearCookies();
  await context.addCookies([{ name: 'shuku_session', value: 'english-settings-session', domain: '127.0.0.1', path: '/' }]);
  await mockSettingsApi(page, 'en-US');
  await page.goto('/settings/organize?tab=queue');

  const queueTab = page.locator('a[href="/settings/organize?tab=queue"]');
  const providersTab = page.locator('a[href="/settings/organize?tab=providers"]');
  await expect(queueTab).toHaveAttribute('aria-current', 'page');
  await expect(providersTab).not.toHaveAttribute('aria-current', 'page');
  await providersTab.press('Enter');
  await expect(providersTab).toHaveAttribute('aria-current', 'page');
});
