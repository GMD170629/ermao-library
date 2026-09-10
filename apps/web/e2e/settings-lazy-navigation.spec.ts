import { expect, test, type Page, type Route } from '@playwright/test';

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
    if (pathname.endsWith('/api/library/facets')) {
      await route.fulfill({ json: { ok: true, data: { facets: [], page: 1, pageSize: 20, total: 0, totalPages: 1 } } });
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
    if (pathname.endsWith('/api/library-import-tasks')) {
      await route.fulfill({ json: { ok: true, data: { tasks: [], completed: 0, failed: 0, page: 1, pageSize: 10, total: 0, totalPages: 1 } } });
      return;
    }
    if (pathname.endsWith('/api/libraries/tree')) {
      const requestedPath = url.searchParams.get('path');
      await route.fulfill({ json: { ok: true, data: { node: requestedPath === '/library' ? { name: 'library', path: '/library', readable: true, children: [] } : { name: '/', path: '/', readable: true, children: [{ name: 'library', path: '/library', readable: true }] } } } });
      return;
    }
    if (pathname.endsWith('/api/libraries')) {
      await route.fulfill({ json: { ok: true, data: { libraries: [{ id: 'library-1', name: '主书库', rootPath: '/library', enabled: true }] } } });
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

test('recognition settings save only writable policy fields and retain saved values', async ({ page }) => {
  let writablePolicy = {
    enabled: false, scheduleMode: 'MANUAL', intervalMinutes: 60, autoRunOnNew: false,
    rules: { unrecognized: true, missingMetadata: true }, writeMetadataToFiles: false,
    preferLocalMetadata: true, localMetadataPriority: ['SIDECAR_OPF', 'EMBEDDED', 'PATH']
  };
  const submitted: unknown[] = [];
  await page.route('**/api/organize/policy', async (route) => {
    if (route.request().method() === 'PUT') {
      submitted.push(route.request().postDataJSON());
      writablePolicy = {
        enabled: true, scheduleMode: 'INTERVAL', intervalMinutes: 1440, autoRunOnNew: true,
        rules: { unrecognized: false, missingMetadata: true }, writeMetadataToFiles: true,
        preferLocalMetadata: false, localMetadataPriority: ['EMBEDDED', 'SIDECAR_OPF', 'PATH']
      };
    }
    await route.fulfill({ json: { ok: true, data: { policy: {
      ...writablePolicy, id: 'default', autoRunOnNewSince: '2026-09-10T00:00:00Z',
      lastScheduledAt: '2026-09-10T00:00:00Z', nextRunAt: '2026-09-11T00:00:00Z',
      updatedAt: '2026-09-10T00:00:00Z'
    } } } });
  });
  await page.goto('/settings/organize?tab=recognition');
  await page.getByRole('switch', { name: '定时执行识别', exact: true }).click();
  await page.getByRole('button', { name: '识别任务执行间隔', exact: true }).click();
  await page.getByRole('option', { name: '每天', exact: true }).click();
  await page.getByRole('switch', { name: '新增后自动执行', exact: true }).click();
  await page.getByRole('switch', { name: '元数据变化自动保存到旁车 OPF', exact: true }).click();
  await page.getByRole('switch', { name: '本地元数据优先', exact: true }).click();
  await page.getByRole('checkbox', { name: '尚未识别的读物', exact: true }).uncheck();
  await page.getByRole('button', { name: '下移OPF 文件', exact: true }).click();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect.poll(() => submitted.length).toBe(1);
  expect(submitted[0]).toEqual(writablePolicy);
  await expect(page.getByText('识别设置已保存', { exact: true })).toBeVisible();

  await page.reload();
  await expect(page.getByRole('switch', { name: '定时执行识别', exact: true })).toBeEnabled();
  await expect(page.getByRole('switch', { name: '定时执行识别', exact: true })).toBeChecked();
  await expect(page.getByRole('button', { name: '识别任务执行间隔', exact: true })).toContainText('每天');
  await expect(page.getByRole('checkbox', { name: '尚未识别的读物', exact: true })).not.toBeChecked();
  await page.getByRole('button', { name: '保存设置', exact: true }).click();
  await expect.poll(() => submitted.length).toBe(2);
  expect(submitted[1]).toEqual(writablePolicy);
});

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
  expect(requestCount(counts, '/api/library/facets')).toBe(0);
  expect(requestCount(counts, '/api/organize/policy')).toBe(0);
  expect(requestCount(counts, '/api/organize/candidates')).toBe(0);

  await page.locator('a[href="/settings/organize?tab=providers"]').click();
  await expect.poll(() => requestCount(counts, '/api/metadata/providers')).toBeGreaterThan(0);
  await page.locator('a[href="/settings/organize?tab=categories"]').click();
  await expect.poll(() => requestCount(counts, '/api/library/facets')).toBeGreaterThan(0);
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
  await expect.poll(() => requestCount(counts, '/api/library-import-tasks')).toBeGreaterThan(0);
  const initialImportTaskRequests = requestCount(counts, '/api/library-import-tasks');
  expect(requestCount(counts, '/api/libraries/tree')).toBe(0);
  expect(requestCount(counts, '/api/libraries')).toBeGreaterThan(0);
  expect(requestCount(counts, '/api/system-settings')).toBe(0);

  await page.getByRole('tab', { name: '文件管理' }).click();
  await expect.poll(() => requestCount(counts, '/api/libraries/tree')).toBeGreaterThan(0);
  await page.getByRole('tab', { name: '书库' }).click();
  await expect.poll(() => requestCount(counts, '/api/libraries')).toBeGreaterThan(0);
  await page.getByRole('tab', { name: '偏好设置' }).click();
  await expect.poll(() => requestCount(counts, '/api/system-settings')).toBeGreaterThan(0);
  await page.getByRole('tab', { name: '导入记录' }).click();
  await expect.poll(() => requestCount(counts, '/api/library-import-tasks')).toBeGreaterThan(initialImportTaskRequests);
});

test('new library shows expanded scan rules with a 10 KB minimum by default', async ({ page }) => {
  await page.goto('/settings/library');
  await page.getByRole('tab', { name: '文件管理' }).click();
  await page.getByRole('tab', { name: '书库' }).click();
  await page.getByRole('button', { name: '新增书库' }).click();

  const folderPath = page.getByRole('combobox', { name: '书库路径' });
  await folderPath.fill('/library');
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

for (const locale of ['zh-CN', 'en-US'] as const) {
  test(`import history combines library, keyword and state filters (${locale})`, async ({ page }, testInfo) => {
    await mockSettingsApi(page, locale);
    const requests: URL[] = [];
    await page.route(/\/api\/(library-import-tasks|libraries\/library-1\/import-tasks)\?/, async (route) => {
      const url = new URL(route.request().url());
      requests.push(url);
      const keyword = url.searchParams.get('keyword') ?? '';
      await route.fulfill({ json: { ok: true, data: {
        tasks: [{ id: 'task-1', kind: 'SCAN_LIBRARY', libraryId: 'library-1', libraryName: keyword || '主书库', state: 'QUEUED', createdAt: '2026-09-10T00:00:00Z' }],
        queued: 1, running: 0, completed: 0, failed: 0, page: Number(url.searchParams.get('page')), pageSize: 10, total: 21, totalPages: 3
      } } });
    });
    await page.goto('/settings/library');
    const chinese = locale === 'zh-CN';
    const allLibraries = chinese ? '全部书库' : 'All libraries';
    const refresh = page.getByRole('button', { name: chinese ? '刷新' : 'Refresh', exact: true });
    const search = page.getByRole('searchbox', { name: chinese ? '关键字筛选' : 'Filter by keyword' });
    const library = page.getByRole('button', { name: chinese ? '书库' : 'Library', exact: true });
    await expect(library).toContainText(allLibraries);
    await expect(refresh).toBeEnabled();
    expect(requests[0]?.pathname).toBe('/api/library-import-tasks');
    await expect(search.locator('..').getByRole('button', { name: chinese ? '刷新' : 'Refresh', exact: true })).toBeVisible();
    await page.getByRole('button', { name: chinese ? '下一页' : 'Next Page', exact: true }).click();
    await expect.poll(() => requests.at(-1)?.searchParams.get('page')).toBe('2');
    await search.fill('  Book%_title  ');
    await expect.poll(() => requests.at(-1)?.searchParams.get('keyword')).toBe('Book%_title');
    expect(requests.at(-1)?.searchParams.get('page')).toBe('1');
    await library.click();
    await page.getByRole('option', { name: '主书库', exact: true }).click();
    await expect.poll(() => requests.at(-1)?.pathname).toBe('/api/libraries/library-1/import-tasks');
    const state = page.getByRole('button', { name: chinese ? '按状态筛选' : 'Filter by Status', exact: true });
    await state.click();
    await page.getByRole('option', { name: chinese ? '失败' : 'Failed', exact: true }).click();
    await expect.poll(() => requests.at(-1)?.searchParams.get('state')).toBe('FAILED');
    expect(requests.at(-1)?.searchParams.get('keyword')).toBe('Book%_title');
    await expect(refresh).toBeEnabled();
    const beforeRefresh = requests.length;
    await refresh.click();
    await expect.poll(() => requests.length).toBeGreaterThan(beforeRefresh);
    expect(requests.at(-1)?.searchParams.get('keyword')).toBe('Book%_title');
    await search.fill('');
    await expect.poll(() => requests.at(-1)?.searchParams.has('keyword')).toBe(false);
    await library.click();
    await page.getByRole('option', { name: allLibraries, exact: true }).click();
    await expect.poll(() => requests.at(-1)?.pathname).toBe('/api/library-import-tasks');
    const beforePolling = requests.length;
    await expect.poll(() => requests.length).toBeGreaterThan(beforePolling);
    await search.focus();
    await expect(search).toBeFocused();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('import-filters.png'), fullPage: true });
  });
}

test('import keyword debounce rejects an older slow response and supports empty libraries', async ({ page }) => {
  await mockSettingsApi(page);
  await page.route('**/api/libraries', async (route) => {
    await route.fulfill({ json: { ok: true, data: { libraries: [] } } });
  });
  const requests: string[] = [];
  const pending: Route[] = [];
  const result = (title: string) => ({ ok: true, data: {
    tasks: title ? [{ id: title, kind: 'SCAN_LIBRARY', libraryId: 'disabled-library', libraryName: title, state: 'SUCCEEDED', createdAt: '2026-09-10T00:00:00Z' }] : [],
    queued: 0, running: 0, completed: 1, failed: 0, page: 1, pageSize: 10, total: title ? 1 : 0, totalPages: 1
  } });
  await page.route('**/api/library-import-tasks?**', async (route) => {
    const keyword = new URL(route.request().url()).searchParams.get('keyword') ?? '';
    requests.push(keyword);
    if (keyword === 'old') {
      pending.push(route);
      return;
    }
    await route.fulfill({ json: result(keyword) });
  });
  await page.goto('/settings/library');
  await expect(page.getByText('暂无导入任务。', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '书库', exact: true })).toContainText('全部书库');
  const search = page.getByRole('searchbox', { name: '关键字筛选' });
  await page.clock.install({ time: new Date('2026-09-10T00:00:00Z') });
  await page.clock.pauseAt(new Date('2026-09-10T00:00:01Z'));
  await search.fill('o');
  await page.clock.runFor(200);
  await search.fill('old');
  await page.clock.runFor(299);
  expect(requests.filter((keyword) => keyword !== '')).toEqual([]);
  await page.clock.runFor(1);
  await expect.poll(() => pending.length).toBe(1);
  await search.fill('new');
  await page.clock.runFor(300);
  await expect(page.getByText('new', { exact: true })).toBeVisible();
  for (const route of pending) await route.fulfill({ json: result('old') });
  await expect(page.getByText('old', { exact: true })).toHaveCount(0);
  await expect(page.getByText('new', { exact: true })).toBeVisible();
  await search.fill('');
  await page.clock.runFor(1);
  await expect(page.getByText('暂无导入任务。', { exact: true })).toBeVisible();
});
