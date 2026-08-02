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
    if (pathname.endsWith('/api/library/duplicates')) {
      await route.fulfill({ json: { ok: true, data: { groups: [] } } });
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
              autoRunOnNewSince: null, rules: { unrecognized: true, missingMetadata: true }, overwriteTitleAuthor: true,
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
    if (pathname.endsWith('/api/import-tasks/clear')) {
      await route.fulfill({
        status: 202,
        json: {
          ok: true,
          data: {
            created: true,
            operation: {
              id: 'queue-clear',
              queueName: 'import',
              action: 'clear',
              status: 'requested',
              messageCode: 'queue.clear.requested',
              requestedAt: '2026-07-29T00:00:00Z',
              startedAt: null,
              finishedAt: null,
              updatedAt: '2026-07-29T00:00:00Z'
            }
          }
        }
      });
      return;
    }
    if (pathname.endsWith('/api/system/queue-operations/queue-clear')) {
      await route.fulfill({
        json: {
          ok: true,
          data: {
            operation: {
              id: 'queue-clear',
              queueName: 'import',
              action: 'clear',
              status: 'completed',
              messageCode: 'queue.clear.completed',
              requestedAt: '2026-07-29T00:00:00Z',
              startedAt: '2026-07-29T00:00:01Z',
              finishedAt: '2026-07-29T00:00:02Z',
              updatedAt: '2026-07-29T00:00:02Z'
            }
          }
        }
      });
      return;
    }
    if (pathname.endsWith('/api/import-tasks')) {
      await route.fulfill({ json: { ok: true, data: { tasks: [], summary: { completed: 0, failed: 0 }, page: 1, pageSize: 10, total: 0, totalPages: 1 } } });
      return;
    }
    if (pathname.endsWith('/api/monitor-folders/tree')) {
      const requestedPath = url.searchParams.get('path');
      await route.fulfill({ json: { ok: true, data: { node: requestedPath === '/monitor' ? { name: 'monitor', path: '/monitor', readable: true, children: [] } : { name: '/', path: '/', readable: true, children: [{ name: 'monitor', path: '/monitor', readable: true }] }, monitorRoot: null } } });
      return;
    }
    if (pathname.endsWith('/api/monitor-folders')) {
      await route.fulfill({ json: { ok: true, data: { folders: [] } } });
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
  expect(requestCount(counts, '/api/library/duplicates')).toBe(0);
  expect(requestCount(counts, '/api/library/categories')).toBe(0);
  expect(requestCount(counts, '/api/organize/policy')).toBe(0);
  expect(requestCount(counts, '/api/organize/candidates')).toBe(0);

  await page.locator('a[href="/settings/organize?tab=providers"]').click();
  await expect.poll(() => requestCount(counts, '/api/metadata/providers')).toBeGreaterThan(0);
  await page.locator('a[href="/settings/organize?tab=duplicates"]').click();
  await expect.poll(() => requestCount(counts, '/api/library/duplicates')).toBeGreaterThan(0);
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
  const initialImportTaskRequests = requestCount(counts, '/api/import-tasks');
  expect(requestCount(counts, '/api/monitor-folders/tree')).toBe(0);
  expect(requestCount(counts, '/api/monitor-folders')).toBe(0);
  expect(requestCount(counts, '/api/system-settings')).toBe(0);

  await page.getByRole('tab', { name: '文件管理' }).click();
  await expect.poll(() => requestCount(counts, '/api/monitor-folders/tree')).toBeGreaterThan(0);
  await page.getByRole('tab', { name: '监控文件夹' }).click();
  await expect.poll(() => requestCount(counts, '/api/monitor-folders')).toBeGreaterThan(0);
  await page.getByRole('tab', { name: '偏好设置' }).click();
  await expect.poll(() => requestCount(counts, '/api/system-settings')).toBeGreaterThan(0);
  await page.getByRole('tab', { name: '导入记录' }).click();
  await expect.poll(() => requestCount(counts, '/api/import-tasks')).toBeGreaterThan(initialImportTaskRequests);
});

test('new monitor folder shows expanded scan rules with a 10 KB minimum by default', async ({ page }) => {
  await page.goto('/settings/library');
  await page.getByRole('tab', { name: '文件管理' }).click();
  await page.getByRole('tab', { name: '监控文件夹' }).click();
  await page.getByRole('button', { name: '添加文件夹' }).click();

  const folderPath = page.getByRole('combobox', { name: '监控文件夹路径' });
  await folderPath.fill('/monitor');
  await page.getByRole('button', { name: '展开文件夹路径树' }).click();
  const directoryTree = page.getByRole('tree');
  await expect(directoryTree.getByRole('button', { name: '/', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'monitor', exact: true }).click();
  await expect(folderPath).toHaveValue('/monitor');

  const scanRules = page.getByRole('button', { name: /扫描规则/ });
  await expect(scanRules).toHaveAttribute('aria-expanded', 'true');
  await expect(page.getByRole('spinbutton', { name: '最小文件大小 KB' })).toHaveValue('10');
});

test('library import queue clear confirms, polls, and refreshes only after completion', async ({ page }) => {
  const counts = await mockSettingsApi(page);
  await page.goto('/settings/library');

  const clearButton = page.getByRole('button', { name: '清理导入队列' });
  await clearButton.click();
  const dialog = page.getByRole('dialog', { name: '清理导入队列？' });
  await expect(dialog).toContainText('只删除队列记录，不会删除源文件、生成文件或已入库书籍');
  await dialog.getByRole('button', { name: '取消' }).click();
  expect(requestCount(counts, 'POST /api/import-tasks/clear')).toBe(0);

  await clearButton.click();
  await page.getByRole('dialog', { name: '清理导入队列？' }).getByRole('button', { name: '确认清理' }).click();

  await expect.poll(() => requestCount(counts, 'POST /api/import-tasks/clear')).toBe(1);
  await expect.poll(() => requestCount(counts, 'GET /api/system/queue-operations/queue-clear')).toBe(1);
  await expect(page.getByText('导入队列已清理', { exact: true }).first()).toBeVisible();
  await expect.poll(() => requestCount(counts, '/api/import-tasks')).toBeGreaterThan(1);
});

test('library import preferences save after editing the stability check time', async ({ page }) => {
  const counts = await mockSettingsApi(page);
  await page.goto('/settings/library');
  await page.getByRole('tab', { name: '偏好设置' }).click();
  await expect.poll(() => requestCount(counts, '/api/system-settings')).toBeGreaterThan(0);

  const checkTime = page.getByRole('spinbutton', { name: '检查时间' });
  const stabilitySwitch = page.getByRole('switch', { name: '导入时检查文件稳定性' });
  await expect(stabilitySwitch).not.toBeChecked();
  await stabilitySwitch.click();
  await checkTime.fill('2.0');
  await expect(page.getByRole('button', { name: '保存偏好' })).toBeEnabled();
  await page.getByRole('button', { name: '保存偏好' }).click();

  await expect.poll(() => requestCount(counts, 'PUT /api/system-settings')).toBe(1);
  await expect(page.getByRole('button', { name: '保存偏好' })).toBeDisabled();

  await checkTime.fill('3.5');
  await page.getByRole('button', { name: '保存偏好' }).click();
  await expect.poll(() => requestCount(counts, 'PUT /api/system-settings')).toBe(2);

  await stabilitySwitch.click();
  await expect(page.getByRole('button', { name: '保存偏好' })).toBeEnabled();
  await page.getByRole('button', { name: '撤销更改' }).click();
  await expect(stabilitySwitch).toBeChecked();
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
